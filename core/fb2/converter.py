import html
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

from core.fb2.common import (
    ConversionCancelledError,
    EPUB_BASED_FORMATS,
    _DEST_MOVE_LOCK,
    _WHITESPACE_RE,
    get_facade_attr,
    logger,
)
from core.fb2.organizer import _sanitize_fs_component
from core.fb2.xml_io import _read_zip_entry_limited, get_book_xml
from core.fb2.metadata import update_fb2_xml


def patch_html_title_elements(html_text, author_css, title_css, meta=None):
    pattern = re.compile(
        r'(<(?P<tag>p|h[1-6])\b[^>]*class=["\'][^"\']*body-title-header[^"\']*["\'][^>]*>)(?P<inner>[\s\S]*?)(</(?P=tag)>)',
        re.IGNORECASE
    )
    matches = list(pattern.finditer(html_text))
    valid = [m for m in matches if re.sub(r'<[^>]+>', '', m.group('inner')).strip()]

    if len(valid) >= 2:
        title_m = valid[-1]
        author_ms = valid[:-1]
        t_tag = title_m.group('tag')
        t_repl = f'<{t_tag} class="body-title-header book-title" style="{title_css}">{title_m.group("inner")}</{t_tag}>'
        html_text = html_text[:title_m.start()] + t_repl + html_text[title_m.end():]
        for a_m in reversed(author_ms):
            a_tag = a_m.group('tag')
            a_repl = f'<{a_tag} class="body-title-header book-author" style="{author_css}">{a_m.group("inner")}</{a_tag}>'
            html_text = html_text[:a_m.start()] + a_repl + html_text[a_m.end():]
        return html_text

    elif len(valid) == 1:
        m = valid[0]
        tag, inner = m.group('tag'), m.group('inner')
        lines_raw = re.sub(r'<(?:br|/p|/div|/span|p|div|span)\b[^>]*>', '\n', inner, flags=re.IGNORECASE)
        lines = [re.sub(r'<[^>]+>', '', line).strip() for line in lines_raw.split('\n') if re.sub(r'<[^>]+>', '', line).strip()]

        if len(lines) >= 2:
            spans = [f'<span class="book-author" style="display: block; {author_css}">{a_line}</span>' for a_line in lines[:-1]]
            spans.append(f'<span class="book-title" style="display: block; {title_css}">{lines[-1]}</span>')
            repl = (
                f'<{tag} class="body-title-header" '
                f'style="font-size: 100% !important; font-weight: normal !important; font-style: normal !important; text-indent: 0; margin: 0; padding: 0;">'
                f'{"".join(spans)}</{tag}>'
            )
            return html_text[:m.start()] + repl + html_text[m.end():]

    return html_text


_SAFE_INLINE_CSS_TOKEN_RE = re.compile(r"^[#a-zA-Z0-9.%_-]+$")


def _sanitize_inline_css_param(style_params, key, fallback):
    from core.css_preview import _sanitize_css_value

    raw = style_params.get(key, fallback) if isinstance(style_params, dict) else fallback
    clean = _sanitize_css_value(raw, "")
    if not clean or not _SAFE_INLINE_CSS_TOKEN_RE.fullmatch(clean):
        clean = fallback
    return html.escape(clean, quote=True)


def patch_epub_title_classes(epub_path, style_params, meta=None):
    if not os.path.exists(epub_path):
        return False

    h1_sz = _sanitize_inline_css_param(style_params, "h1_sz", "150%")
    h1_cl = _sanitize_inline_css_param(style_params, "h1_cl", "black")
    h1_al = _sanitize_inline_css_param(style_params, "h1_al", "center")
    auth_sz = _sanitize_inline_css_param(style_params, "auth_sz", "110%")
    auth_cl = _sanitize_inline_css_param(style_params, "auth_cl", "dimgray")
    auth_al = _sanitize_inline_css_param(style_params, "auth_al", "center")
    auth_style = _sanitize_inline_css_param(style_params, "auth_style", "italic")

    author_css = (
        f"font-family: 'author-font', 'paragraph', serif !important; font-size: {auth_sz} !important; "
        f"color: {auth_cl} !important; font-style: {auth_style} !important; font-weight: bold !important; "
        f"text-align: {auth_al} !important; margin-top: 0.4em !important; margin-bottom: 0.4em !important;"
    )
    title_css = (
        f"font-family: 'title-font', 'paragraph', serif !important; font-size: {h1_sz} !important; "
        f"color: {h1_cl} !important; font-style: normal !important; font-weight: bold !important; "
        f"text-align: {h1_al} !important; margin-top: 0.8em !important; margin-bottom: 0.5em !important;"
    )

    epub_dir = os.path.dirname(os.path.abspath(epub_path)) or "."
    fd_tmp, temp_epub = tempfile.mkstemp(prefix=".fbc_epub_", suffix=".tmp", dir=epub_dir)
    os.close(fd_tmp)
    try:
        with zipfile.ZipFile(epub_path, 'r') as zin, zipfile.ZipFile(temp_epub, 'w') as zout:
            if "mimetype" in zin.namelist():
                zout.writestr("mimetype", _read_zip_entry_limited(zin, "mimetype", max_bytes=4096), compress_type=zipfile.ZIP_STORED)
            for item in zin.infolist():
                if item.filename == "mimetype":
                    continue
                content = _read_zip_entry_limited(zin, item.filename)
                if item.filename.lower().endswith(('.xhtml', '.html', '.htm')):
                    try:
                        text = content.decode('utf-8')
                        if 'body-title-header' in text or 'body-title' in text:
                            patched = patch_html_title_elements(text, author_css, title_css, meta)
                            if patched != text:
                                content = patched.encode('utf-8')
                    except Exception as e:
                        logger.debug("Пропущен патч HTML-заголовков для %s: %s", item.filename, e)
                zout.writestr(item, content, compress_type=zipfile.ZIP_DEFLATED)
        os.replace(temp_epub, epub_path)
        return True
    except Exception:
        if os.path.exists(temp_epub):
            try:
                os.remove(temp_epub)
            except OSError:
                pass
        return False


def _run_cancellable_process(cmd, cwd, cancel_event=None, on_output_line=None):
    """Запускает внешний процесс через Popen и немедленно завершает его при срабатывании cancel_event."""
    import threading

    if cancel_event is not None and cancel_event.is_set():
        raise ConversionCancelledError("Conversion cancelled")

    popen_kwargs = {
        "cwd": cwd,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.Popen(cmd, **popen_kwargs)
    if on_output_line is not None:
        out_lines = []
        err_lines = []

        def _drain(stream, bucket):
            try:
                for line in iter(stream.readline, ""):
                    bucket.append(line)
                    try:
                        on_output_line(line.rstrip("\r\n"))
                    except Exception:
                        pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        t_out = threading.Thread(target=_drain, args=(proc.stdout, out_lines), daemon=True)
        t_err = threading.Thread(target=_drain, args=(proc.stderr, err_lines), daemon=True)
        t_out.start()
        t_err.start()
        try:
            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=1.5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    raise ConversionCancelledError("Conversion cancelled")
                try:
                    proc.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    continue
        except ConversionCancelledError:
            raise
        except Exception:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            raise
        finally:
            t_out.join(timeout=1.0)
            t_err.join(timeout=1.0)
        stdout = "".join(out_lines)
        stderr = "".join(err_lines)
    else:
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.communicate(timeout=1.5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.communicate()
                    raise ConversionCancelledError("Conversion cancelled")
                try:
                    stdout, stderr = proc.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except ConversionCancelledError:
            raise
        except Exception:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
            raise

    if cancel_event is not None and cancel_event.is_set():
        raise ConversionCancelledError("Conversion cancelled")

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout, stderr=stderr)
    return stdout, stderr


def _save_debug_report_if_present(tmp_work_dir, dest_dir, data):
    """Сохраняет сформированный fbc-report.zip рядом с итоговым файлом при запуске с --debug."""
    report_src = os.path.join(tmp_work_dir, "fbc-report.zip")
    if not os.path.isfile(report_src):
        return None
    base_label = data.get("display_name") or os.path.basename(data.get("path") or "book")
    raw_stem = os.path.splitext(base_label.replace("/", "_").replace("\\", "_"))[0].strip() or "book"
    stem = _sanitize_fs_component(raw_stem, fallback="book", max_len=80)
    report_dst = os.path.join(dest_dir, f"{stem}_fbc-report.zip")
    try:
        with _DEST_MOVE_LOCK:
            os.makedirs(dest_dir, exist_ok=True)
            if os.path.exists(report_dst):
                os.remove(report_dst)
            shutil.move(report_src, report_dst)
        logger.info("Сохранён отладочный отчёт fbc: %s", report_dst)
        return report_dst
    except Exception as e:
        logger.warning("Не удалось сохранить fbc-report.zip: %s", e)
        return None


def _attach_fonts_dir(base_dir, fbc_config, tmp_work_dir):
    """Делает каталог fonts доступным из рабочей папки fbc (для url("fonts/...") в CSS)."""
    candidates = []
    if base_dir:
        candidates.append(os.path.join(base_dir, "fonts"))
    if fbc_config:
        cfg_fonts = os.path.join(os.path.dirname(os.path.abspath(fbc_config)), "fonts")
        if cfg_fonts not in candidates:
            candidates.append(cfg_fonts)

    src_fonts = next((p for p in candidates if os.path.isdir(p)), None)
    if not src_fonts:
        return None

    dst_fonts = os.path.join(tmp_work_dir, "fonts")
    if os.name == "nt":
        shutil.copytree(src_fonts, dst_fonts)
        return dst_fonts
    try:
        os.symlink(src_fonts, dst_fonts, target_is_directory=True)
    except (OSError, NotImplementedError):
        shutil.copytree(src_fonts, dst_fonts)
    return dst_fonts


def _attach_stylesheet_file(base_dir, fbc_config, tmp_work_dir):
    """Делает ebook_styles.css доступным из рабочей папки fbc при относительном stylesheet_path."""
    candidates = []
    if fbc_config:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(fbc_config)), "ebook_styles.css"))
    if base_dir:
        base_css = os.path.join(base_dir, "ebook_styles.css")
        if base_css not in candidates:
            candidates.append(base_css)

    src_css = next((p for p in candidates if os.path.isfile(p)), None)
    if not src_css:
        return None

    dst_css = os.path.join(tmp_work_dir, "ebook_styles.css")
    try:
        from core.css_preview import ensure_kfx_dropcap_css

        with open(src_css, "r", encoding="utf-8") as fh:
            raw_css = fh.read()
        patched_css = ensure_kfx_dropcap_css(raw_css)
        with open(dst_css, "w", encoding="utf-8") as fh:
            fh.write(patched_css)
    except Exception:
        shutil.copy2(src_css, dst_css)
    return dst_css


def _split_output_name(filename):
    low = filename.lower()
    if low.endswith(".kepub.epub"):
        return filename[:-len(".kepub.epub")], filename[-len(".kepub.epub"):]
    return os.path.splitext(filename)


def convert_book_file(
    fbc_cmd,
    fbc_config,
    base_dir,
    data,
    dest_dir,
    selected_format,
    title_style_params,
    compression=None,
    cancel_event=None,
    debug=False,
    no_cover=False,
    claimed_outputs=None,
    image_color_profile="none",
    jpeg_quality=95,
    image_color_profile_custom=None,
):
    """Конвертирует одну книгу через fbc в изолированной временной папке и при необходимости патчит заголовки EPUB."""
    if cancel_event is not None and cancel_event.is_set():
        raise ConversionCancelledError("Conversion cancelled")

    is_epub_format = selected_format in EPUB_BASED_FORMATS
    has_img_opt = bool((image_color_profile and image_color_profile != "none") or image_color_profile_custom)
    src_path = data.get("path") or ""
    orig_meta = data.get("orig_meta")
    can_use_source_directly = (
        not has_img_opt
        and data.get("archive_entry") is None
        and not data.get("xml")
        and not data.get("cover_modified", False)
        and isinstance(orig_meta, dict)
        and data.get("meta") == orig_meta
        and bool(src_path)
        and src_path.lower().endswith(".fb2")
        and os.path.isfile(src_path)
    )

    created_tmp_fb2 = False
    if can_use_source_directly:
        tmp_path = src_path
    else:
        xml_bytes = get_book_xml(data)
        if not xml_bytes:
            src_label = data.get("display_name") or src_path or "unknown"
            raise RuntimeError(f"Не удалось прочитать исходный файл FB2: {src_label}")

        new_xml_bytes = update_fb2_xml(
            xml_bytes, data['meta'],
            cover_bytes=data.get('cover_bytes'),
            cover_mime=data.get('cover_mime', 'image/jpeg'),
            cover_modified=data.get('cover_modified', False),
            orig_meta=orig_meta,
        )
        if has_img_opt:
            from core.image_optimizer import optimize_fb2_binaries_for_profile

            new_xml_bytes = optimize_fb2_binaries_for_profile(
                new_xml_bytes,
                profile_id=image_color_profile,
                jpeg_quality=jpeg_quality,
                custom_profile=image_color_profile_custom,
            )
        with tempfile.NamedTemporaryFile(delete=False, suffix=".fb2") as tmp:
            tmp.write(new_xml_bytes)
            tmp_path = tmp.name
        created_tmp_fb2 = True

    try:
        with tempfile.TemporaryDirectory() as tmp_root:
            tmp_root_real = os.path.realpath(tmp_root)
            tmp_work_dir = os.path.join(tmp_root_real, "work")
            tmp_out_dir = os.path.join(tmp_root_real, "out")
            os.makedirs(tmp_work_dir, exist_ok=True)
            os.makedirs(tmp_out_dir, exist_ok=True)
            linked_fonts = _attach_fonts_dir(base_dir, fbc_config, tmp_work_dir)
            linked_css = _attach_stylesheet_file(base_dir, fbc_config, tmp_work_dir)

            try:
                cmd = [fbc_cmd]
                if debug:
                    cmd.append("--debug")
                cmd.extend(["convert", "--overwrite", "--to", selected_format])
                if compression and selected_format in ("azw3", "kfx", "azw8"):
                    cmd.extend(["--compression", compression])
                if no_cover and selected_format in ("epub2", "epub3", "kepub", "kepub3", "pdf"):
                    cmd.append("--no-cover")
                cmd.extend(["--config", fbc_config, tmp_path, tmp_out_dir])

                try:
                    run_proc = get_facade_attr("_run_cancellable_process", _run_cancellable_process)
                    run_proc(cmd, cwd=tmp_work_dir, cancel_event=cancel_event)
                except subprocess.CalledProcessError as e:
                    if debug:
                        _save_debug_report_if_present(tmp_work_dir, dest_dir, data)
                    err_out = (e.stderr or e.stdout or "").strip()
                    if not err_out:
                        fbc_log_path = os.path.join(tmp_work_dir, "fbc.log")
                        if os.path.isfile(fbc_log_path):
                            try:
                                with open(fbc_log_path, "r", encoding="utf-8", errors="replace") as lf:
                                    err_out = lf.read().strip()
                            except Exception as log_err:
                                logger.debug("Не удалось прочитать лог fbc %s: %s", fbc_log_path, log_err)
                    if err_out:
                        err_tail = "\n".join(err_out.splitlines()[-8:])
                        logger.error("Ошибка fbc (код %s) для %s:\n%s", e.returncode, data.get("display_name") or data.get("path"), err_tail)
                        raise RuntimeError(f"fbc exit code {e.returncode}:\n{err_tail}") from e
                    logger.error("Ошибка fbc (код %s) для %s", e.returncode, data.get("display_name") or data.get("path"))
                    raise RuntimeError(f"fbc exit code {e.returncode}") from e

                if debug:
                    _save_debug_report_if_present(tmp_work_dir, dest_dir, data)

                if cancel_event is not None and cancel_event.is_set():
                    raise ConversionCancelledError("Conversion cancelled")

                produced_tmp = []
                for root_dir, _, files in os.walk(tmp_out_dir):
                    for fname in sorted(files):
                        produced_tmp.append(os.path.join(root_dir, fname))

                if is_epub_format:
                    for ep in produced_tmp:
                        if ep.lower().endswith(('.epub', '.kepub.epub')):
                            patch_epub_title_classes(ep, title_style_params, data['meta'])

                if cancel_event is not None and cancel_event.is_set():
                    raise ConversionCancelledError("Conversion cancelled")

                created_final = []
                with _DEST_MOVE_LOCK:
                    os.makedirs(dest_dir, exist_ok=True)
                    for src_fp in produced_tmp:
                        base_out = os.path.basename(src_fp)
                        dst_fp = os.path.join(dest_dir, base_out)
                        if claimed_outputs is not None:
                            stem, ext = _split_output_name(base_out)
                            norm_dst = os.path.normcase(os.path.abspath(dst_fp))
                            suffix_n = 2
                            while norm_dst in claimed_outputs:
                                dst_fp = os.path.join(dest_dir, f"{stem} ({suffix_n}){ext}")
                                norm_dst = os.path.normcase(os.path.abspath(dst_fp))
                                suffix_n += 1
                            claimed_outputs.add(norm_dst)
                        fd_tmp, tmp_dst = tempfile.mkstemp(prefix=".fbc_out_", suffix=".tmp", dir=dest_dir)
                        os.close(fd_tmp)
                        try:
                            shutil.copy2(src_fp, tmp_dst)
                            os.replace(tmp_dst, dst_fp)
                        except Exception:
                            if os.path.exists(tmp_dst):
                                try:
                                    os.remove(tmp_dst)
                                except OSError:
                                    pass
                            raise
                        try:
                            os.remove(src_fp)
                        except OSError:
                            pass
                        created_final.append(dst_fp)

                return created_final
            finally:
                for linked_path in (linked_fonts, linked_css):
                    if linked_path and os.path.islink(linked_path):
                        try:
                            os.unlink(linked_path)
                        except OSError:
                            pass
    finally:
        if created_tmp_fb2 and os.path.exists(tmp_path):
            os.remove(tmp_path)


def compute_book_dedup_key(meta):
    """Формирует нормализованный логический ключ книги для выявления дубликатов в очереди."""
    if not isinstance(meta, dict):
        return ""
    title = _WHITESPACE_RE.sub(" ", (meta.get("title") or "").strip().lower())
    if not title:
        return ""
    last = _WHITESPACE_RE.sub(" ", (meta.get("last") or "").strip().lower())
    series = _WHITESPACE_RE.sub(" ", (meta.get("series") or "").strip().lower())
    num_raw = (meta.get("num") or "").strip()
    num = str(int(num_raw)) if num_raw.isdigit() else num_raw.lower()
    return f"{last}|{series}|{num}|{title}"


def find_duplicate_item_ids(files_data):
    """Возвращает множество item_id дубликатов (оставляя первое вхождение каждой книги)."""
    seen_keys = set()
    dup_ids = set()
    for item_id, data in (files_data or {}).items():
        if not isinstance(data, dict):
            continue
        key = compute_book_dedup_key(data.get("meta"))
        if not key:
            continue
        if key in seen_keys:
            dup_ids.add(item_id)
        else:
            seen_keys.add(key)
    return dup_ids


def should_skip_existing_conversion(data, dest_dir, target_filename):
    """Определяет, можно ли пропустить конвертацию: выходной файл существует, не старше исходника и книга не правилась."""
    if not isinstance(data, dict) or not dest_dir or not target_filename:
        return False
    if data.get("cover_modified"):
        return False
    orig_meta = data.get("orig_meta")
    if isinstance(orig_meta, dict) and data.get("meta") != orig_meta:
        return False
    src_path = data.get("path")
    if not src_path or not os.path.isfile(src_path):
        return False
    target_path = os.path.join(dest_dir, target_filename)
    if not os.path.isfile(target_path):
        return False
    try:
        return os.path.getmtime(target_path) >= os.path.getmtime(src_path)
    except OSError:
        return False


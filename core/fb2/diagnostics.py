import base64
import html
import io
import os
import stat
import tempfile
import zipfile
import xml.etree.ElementTree as ET

from core.fb2.common import (
    HAS_PIL,
    Image,
    get_facade_attr,
    logger,
)
from core.fb2.xml_io import (
    _XML_ENCODING_RE,
    _find_title_info,
    _get_root_ns_uri,
    _local_tag,
    _parse_fb2_root,
    _qtag,
    extract_cover_from_fb2,
    get_book_xml,
)
from core.fb2.metadata import _empty_meta, parse_metadata

OVERSIZED_IMAGE_BYTES = 2 * 1024 * 1024
_NOTES_BODY_NAMES = frozenset({"notes", "comments", "примечания", "комментарии"})
_UNSET = object()


def _detect_declared_encoding(xml_bytes):
    if not xml_bytes:
        return "utf-8"
    raw = xml_bytes.lstrip(b'\xef\xbb\xbf\r\n\t ')[:256]
    m_enc = _XML_ENCODING_RE.search(raw)
    if m_enc:
        try:
            enc = m_enc.group(1).decode('ascii', errors='ignore').strip().lower()
            if enc:
                return enc
        except Exception as e:
            logger.debug("Не удалось определить объявленную кодировку FB2: %s", e)
    return "utf-8"


def _is_strict_xml_valid(xml_bytes):
    if not xml_bytes:
        return False
    try:
        ET.fromstring(xml_bytes)
        return True
    except Exception:
        return False


def quick_check_fb2(xml_bytes, meta=None, cover_bytes=None):
    """Быстрая предпроверка FB2 при импорте: возвращает список кодов предупреждений без тяжёлого разбора тела."""
    warnings = []
    if xml_bytes is not None and not _is_strict_xml_valid(xml_bytes):
        warnings.append("broken_xml")
    m = meta if isinstance(meta, dict) else (parse_metadata(xml_bytes) if xml_bytes else {})
    if not (m.get("title") or "").strip():
        warnings.append("missing_title")
    if not (m.get("last") or "").strip() and not (m.get("first") or "").strip():
        warnings.append("missing_author")
    if not cover_bytes:
        warnings.append("missing_cover")
    return warnings


def refresh_book_warnings(data, xml_bytes=None):
    """Обновляет динамические предупреждения книги после редактирования метаданных/обложки или save-back."""
    if not isinstance(data, dict):
        return []
    existing = list(data.get("warnings") or [])
    if xml_bytes is not None:
        has_broken_xml = not _is_strict_xml_valid(xml_bytes)
    else:
        has_broken_xml = "broken_xml" in existing
    warnings = []
    if has_broken_xml:
        warnings.append("broken_xml")
    meta = data.get("meta") or {}
    if not (meta.get("title") or "").strip():
        warnings.append("missing_title")
    if not (meta.get("last") or "").strip() and not (meta.get("first") or "").strip():
        warnings.append("missing_author")
    if not data.get("cover_bytes"):
        warnings.append("missing_cover")
    data["warnings"] = warnings
    return warnings


def _extract_section_toc(section_el, max_nodes=400, counter=None):
    if counter is None:
        counter = [0]
    if counter[0] >= max_nodes:
        return None
    title_text = ""
    children_toc = []
    for ch in section_el:
        cname = _local_tag(ch)
        if cname == "title" and not title_text:
            parts = ["".join(p.itertext()).strip() for p in ch if _local_tag(p) == "p"]
            title_text = " — ".join(p for p in parts if p)
        elif cname == "section":
            sub = _extract_section_toc(ch, max_nodes=max_nodes, counter=counter)
            if sub is not None:
                children_toc.append(sub)
    if not title_text and not children_toc:
        return None
    counter[0] += 1
    return {"title": title_text, "children": children_toc}


def inspect_fb2(xml_bytes, meta=None, cover_bytes=_UNSET):
    """Выполняет детальный аудит структуры FB2 по запросу: XML, оглавление (TOC), сноски и встроенные изображения."""
    encoding = _detect_declared_encoding(xml_bytes)
    file_size = len(xml_bytes) if xml_bytes else 0
    xml_valid_strict = _is_strict_xml_valid(xml_bytes)
    root = _parse_fb2_root(xml_bytes) if xml_bytes else None
    xml_recovered = (not xml_valid_strict) and (root is not None)

    parsed_meta = meta if isinstance(meta, dict) else (parse_metadata(xml_bytes) if xml_bytes else _empty_meta())
    if cover_bytes is _UNSET:
        eff_cover, _ = extract_cover_from_fb2(xml_bytes) if xml_bytes else (None, None)
    else:
        eff_cover = cover_bytes

    warnings = []
    if not xml_valid_strict:
        warnings.append({
            "code": "broken_xml",
            "severity": "warning" if xml_recovered else "error",
            "count": 1,
        })
    if not (parsed_meta.get("title") or "").strip():
        warnings.append({"code": "missing_title", "severity": "warning", "count": 1})
    if not (parsed_meta.get("last") or "").strip() and not (parsed_meta.get("first") or "").strip():
        warnings.append({"code": "missing_author", "severity": "warning", "count": 1})
    if not eff_cover:
        warnings.append({"code": "missing_cover", "severity": "warning", "count": 1})

    toc = []
    chapter_count = 0
    paragraph_count = 0
    footnotes_count = 0
    images = []
    total_images_bytes = 0
    invalid_binaries = 0
    oversized_images = 0

    if root is not None:
        ti, ns_uri = _find_title_info(root)
        cover_id = None
        if ti is not None:
            cp = ti.find(_qtag(ns_uri, 'coverpage'))
            cover_img = cp.find(_qtag(ns_uri, 'image')) if cp is not None else None
            if cover_img is not None:
                for k, v in cover_img.attrib.items():
                    if k.endswith('href') and v.startswith('#'):
                        cover_id = v[1:]
                        break

        root_ns = _get_root_ns_uri(root)
        bodies = root.findall(_qtag(root_ns, 'body'))
        if not bodies:
            bodies = [el for el in root if _local_tag(el) == 'body']

        main_body = None
        notes_bodies = []
        for b in bodies:
            bname = (b.attrib.get('name') or '').strip().lower()
            if bname in _NOTES_BODY_NAMES:
                notes_bodies.append(b)
            elif main_body is None:
                main_body = b
        if main_body is None and bodies:
            main_body = bodies[0]

        if main_body is not None:
            counter = [0]
            for ch in main_body:
                if _local_tag(ch) == 'section':
                    node = _extract_section_toc(ch, max_nodes=400, counter=counter)
                    if node is not None:
                        toc.append(node)
            chapter_count = counter[0]
            paragraph_count = sum(1 for el in main_body.iter() if _local_tag(el) == 'p')

        if main_body is None or paragraph_count == 0:
            warnings.append({"code": "empty_body", "severity": "error", "count": 1})

        for nb in notes_bodies:
            footnotes_count += sum(1 for ch in nb if _local_tag(ch) == 'section')

        binaries = root.findall(_qtag(root_ns, 'binary'))
        if not binaries:
            binaries = [el for el in root.iter() if _local_tag(el) == 'binary']
        for bin_el in binaries:
            bid = (bin_el.attrib.get('id') or '').strip()
            ctype = (bin_el.attrib.get('content-type') or 'application/octet-stream').strip()
            raw_b64 = "".join((bin_el.text or "").split())
            valid = False
            size_bytes = 0
            width = None
            height = None
            if raw_b64:
                try:
                    raw = base64.b64decode(raw_b64, validate=False)
                    size_bytes = len(raw)
                    if size_bytes > 0:
                        valid = True
                        if get_facade_attr("HAS_PIL", HAS_PIL) and Image is not None and ctype.lower().startswith("image/"):
                            try:
                                with Image.open(io.BytesIO(raw)) as im:
                                    width, height = im.size
                            except Exception:
                                valid = False
                except Exception:
                    valid = False
            oversized = valid and size_bytes > OVERSIZED_IMAGE_BYTES
            if not valid:
                invalid_binaries += 1
            if oversized:
                oversized_images += 1
            total_images_bytes += size_bytes
            images.append({
                "id": bid or "—",
                "content_type": ctype,
                "size_bytes": size_bytes,
                "width": width,
                "height": height,
                "valid": valid,
                "oversized": oversized,
                "is_cover": bool(cover_id and bid == cover_id),
            })

    if invalid_binaries > 0:
        warnings.append({"code": "invalid_binary", "severity": "warning", "count": invalid_binaries})
    if oversized_images > 0:
        warnings.append({"code": "oversized_image", "severity": "warning", "count": oversized_images})

    return {
        "encoding": encoding,
        "file_size_bytes": file_size,
        "xml_valid_strict": xml_valid_strict,
        "xml_recovered": xml_recovered,
        "warnings": warnings,
        "toc": toc,
        "chapter_count": chapter_count,
        "paragraph_count": paragraph_count,
        "footnotes_count": footnotes_count,
        "images": images,
        "total_images_bytes": total_images_bytes,
    }


def _fb2_inline_to_html(el):
    """Преобразует содержимое FB2-элемента (<p>, <v>) в безопасный HTML с поддержкой emphasis/strong/sup/sub."""
    parts = []
    if el.text:
        parts.append(html.escape(el.text))
    for child in el:
        cname = _local_tag(child)
        inner = _fb2_inline_to_html(child)
        if cname == "emphasis":
            parts.append(f"<i>{inner}</i>")
        elif cname == "strong":
            parts.append(f"<b>{inner}</b>")
        elif cname == "sup":
            parts.append(f"<sup>{inner}</sup>")
        elif cname == "sub":
            parts.append(f"<sub>{inner}</sub>")
        elif cname == "strikethrough":
            parts.append(f"<s>{inner}</s>")
        elif cname == "a":
            parts.append(f'<sup style="color: #2563eb; font-weight: bold; font-size: 75%;">{inner}</sup>')
        else:
            parts.append(inner)
        if child.tail:
            parts.append(html.escape(child.tail))
    return "".join(parts)


def extract_book_preview_data(xml_bytes, meta=None, cover_bytes=None, cover_mime=None, max_paragraphs=24):
    """Извлекает реальные фрагменты книги FB2 (обложка, аннотация, эпиграф, первая глава, сноска) для превью."""
    if not xml_bytes:
        return None
    root = _parse_fb2_root(xml_bytes)
    parsed_meta = parse_metadata(xml_bytes) if meta is None else dict(meta)

    author_parts = [p for p in (parsed_meta.get("first"), parsed_meta.get("mid"), parsed_meta.get("last")) if (p or "").strip()]
    author = " ".join(p.strip() for p in author_parts)
    title = (parsed_meta.get("title") or "").strip()
    series = (parsed_meta.get("series") or "").strip()
    num = (parsed_meta.get("num") or "").strip()
    series_line = f"{series} #{num}" if (series and num) else series

    cover_data_uri = ""
    if cover_bytes:
        raw_mime = (cover_mime or "image/jpeg").strip().lower()
        if raw_mime == "image/jpg":
            raw_mime = "image/jpeg"
        mime = raw_mime if raw_mime in ("image/jpeg", "image/png", "image/webp", "image/gif") else "image/jpeg"
        b64 = base64.b64encode(cover_bytes).decode("ascii")
        cover_data_uri = f"data:{mime};base64,{b64}"

    annotation_paras = []
    epigraph_lines = []
    epigraph_author = ""
    chapter_title = ""
    blocks = []
    footnote_title = ""
    footnote_paras = []

    if root is not None:
        ti, ns_uri = _find_title_info(root)
        if ti is not None:
            anno_el = ti.find(_qtag(ns_uri, "annotation"))
            if anno_el is not None:
                for ch in anno_el:
                    if _local_tag(ch) == "p":
                        txt = _fb2_inline_to_html(ch).strip()
                        if txt:
                            annotation_paras.append(txt)

        root_ns = _get_root_ns_uri(root)
        bodies = root.findall(_qtag(root_ns, "body"))
        if not bodies:
            bodies = [el for el in root if _local_tag(el) == "body"]

        main_body = None
        notes_body = None
        for b in bodies:
            bname = (b.attrib.get("name") or "").strip().lower()
            if not bname and main_body is None:
                main_body = b
            elif bname in ("notes", "comments", "примечания", "комментарии") and notes_body is None:
                notes_body = b
        if main_body is None and bodies:
            main_body = bodies[0]

        def _extract_epigraph(parent_el):
            nonlocal epigraph_lines, epigraph_author
            if epigraph_lines:
                return
            for ch in parent_el:
                if _local_tag(ch) == "epigraph":
                    for ec in ch:
                        ec_name = _local_tag(ec)
                        if ec_name == "p":
                            t = _fb2_inline_to_html(ec).strip()
                            if t:
                                epigraph_lines.append(t)
                        elif ec_name == "text-author":
                            t = _fb2_inline_to_html(ec).strip()
                            if t:
                                epigraph_author = t
                    if epigraph_lines:
                        return

        if main_body is not None:
            _extract_epigraph(main_body)
            # Ищем первую содержательную секцию
            def _find_first_content_section(el):
                secs = [c for c in el if _local_tag(c) == "section"]
                for sec in secs:
                    has_direct_p = any(_local_tag(c) in ("p", "poem", "cite") for c in sec)
                    if has_direct_p:
                        return sec
                    sub = _find_first_content_section(sec)
                    if sub is not None:
                        return sub
                return secs[0] if secs else None

            first_sec = _find_first_content_section(main_body)
            if first_sec is not None:
                _extract_epigraph(first_sec)
                for ch in first_sec:
                    cname = _local_tag(ch)
                    if cname == "title" and not chapter_title:
                        t_parts = [_fb2_inline_to_html(p).strip() for p in ch if _local_tag(p) == "p"]
                        chapter_title = " — ".join(p for p in t_parts if p)
                    elif cname == "p":
                        txt = _fb2_inline_to_html(ch).strip()
                        if txt:
                            blocks.append(("p", txt))
                    elif cname == "subtitle":
                        txt = _fb2_inline_to_html(ch).strip()
                        if txt:
                            blocks.append(("subtitle", txt))
                    elif cname == "empty-line":
                        blocks.append(("empty", ""))
                    elif cname == "poem":
                        verses = []
                        for st_el in ch:
                            if _local_tag(st_el) == "stanza":
                                for v_el in st_el:
                                    if _local_tag(v_el) == "v":
                                        vt = _fb2_inline_to_html(v_el).strip()
                                        if vt:
                                            verses.append(vt)
                        if verses:
                            blocks.append(("poem", "<br>".join(verses[:8])))
                    elif cname == "cite":
                        c_ps = [_fb2_inline_to_html(p).strip() for p in ch if _local_tag(p) == "p"]
                        if c_ps:
                            blocks.append(("cite", "<br>".join(p for p in c_ps[:3] if p)))
                    if len(blocks) >= max_paragraphs:
                        break

        if notes_body is not None:
            note_secs = [c for c in notes_body if _local_tag(c) == "section"]
            if note_secs:
                ns0 = note_secs[0]
                for ch in ns0:
                    cname = _local_tag(ch)
                    if cname == "title" and not footnote_title:
                        footnote_title = " ".join(_fb2_inline_to_html(p).strip() for p in ch if _local_tag(p) == "p").strip()
                    elif cname == "p":
                        pt = _fb2_inline_to_html(ch).strip()
                        if pt:
                            footnote_paras.append(pt)
                            if len(footnote_paras) >= 2:
                                break

    return {
        "author": author,
        "title": title,
        "series": series_line,
        "cover_data_uri": cover_data_uri,
        "annotation": annotation_paras[:3],
        "epigraph_lines": epigraph_lines[:3],
        "epigraph_author": epigraph_author,
        "chapter_title": chapter_title,
        "blocks": blocks,
        "footnote_title": footnote_title,
        "footnote_paras": footnote_paras,
    }


def repair_and_optimize_fb2(xml_bytes, max_image_bytes=OVERSIZED_IMAGE_BYTES, max_dim=1600, jpeg_quality=85):
    """Санитизирует битый XML -> UTF-8, удаляет пустые/битые <binary> и сжимает тяжёлые иллюстрации (> max_image_bytes)."""
    if not xml_bytes:
        raise ValueError("Пустой FB2")
    old_size = len(xml_bytes)
    was_strict_valid = _is_strict_xml_valid(xml_bytes)
    root = _parse_fb2_root(xml_bytes)
    if root is None:
        raise RuntimeError("Не удалось восстановить структуру XML FB2")

    root_ns = _get_root_ns_uri(root)
    removed_binaries = 0
    optimized_images = 0

    for bin_el in list(root.findall(_qtag(root_ns, "binary"))):
        raw_b64 = "".join((bin_el.text or "").split())
        if not raw_b64:
            root.remove(bin_el)
            removed_binaries += 1
            continue
        try:
            raw = base64.b64decode(raw_b64, validate=False)
        except Exception:
            root.remove(bin_el)
            removed_binaries += 1
            continue
        if not raw:
            root.remove(bin_el)
            removed_binaries += 1
            continue

        ctype = (bin_el.attrib.get("content-type") or "").strip().lower()
        if get_facade_attr("HAS_PIL", HAS_PIL) and Image is not None and ctype.startswith("image/"):
            try:
                with Image.open(io.BytesIO(raw)) as im:
                    im.load()
                    if len(raw) > max_image_bytes:
                        w, h = im.size
                        work = im.convert("RGB")
                        if max(w, h) > max_dim:
                            work.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                        out_buf = io.BytesIO()
                        work.save(out_buf, format="JPEG", quality=jpeg_quality, optimize=True)
                        new_raw = out_buf.getvalue()
                        if len(new_raw) < len(raw):
                            bin_el.set("content-type", "image/jpeg")
                            bin_el.text = base64.encodebytes(new_raw).decode("ascii")
                            optimized_images += 1
            except Exception:
                root.remove(bin_el)
                removed_binaries += 1

    repaired_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    stats = {
        "xml_fixed": not was_strict_valid,
        "removed_binaries": removed_binaries,
        "optimized_images": optimized_images,
        "old_size": old_size,
        "new_size": len(repaired_bytes),
    }
    return repaired_bytes, stats


def repair_book_in_source(data, max_image_bytes=OVERSIZED_IMAGE_BYTES):
    """Исправляет и оптимизирует FB2 и атомарно записывает обратно в исходный .fb2 или .zip."""
    src_path = data.get("path")
    if not src_path or not os.path.isfile(src_path):
        raise FileNotFoundError(f"Исходный файл не найден: {src_path}")
    xml_bytes = get_book_xml(data)
    if not xml_bytes:
        raise RuntimeError(f"Не удалось прочитать исходный FB2: {src_path}")

    repaired_bytes, stats = repair_and_optimize_fb2(xml_bytes, max_image_bytes=max_image_bytes)

    orig_mode = None
    if os.name != "nt":
        try:
            orig_mode = stat.S_IMODE(os.stat(src_path).st_mode)
        except OSError:
            orig_mode = 0o644

    parent_dir = os.path.dirname(os.path.abspath(src_path)) or "."
    if src_path.lower().endswith(".zip"):
        target_entry = data.get("archive_entry")
        fd, tmp_zip = tempfile.mkstemp(prefix=".fbc_repair_", suffix=".zip", dir=parent_dir)
        os.close(fd)
        try:
            with zipfile.ZipFile(src_path, "r") as zin:
                names = zin.namelist()
                if not target_entry:
                    target_entry = next((n for n in names if n.lower().endswith(".fb2")), None)
                if not target_entry or target_entry not in names:
                    raise RuntimeError(f"В архиве {os.path.basename(src_path)} не найден исходный FB2")
                with zipfile.ZipFile(tmp_zip, "w") as zout:
                    for info in zin.infolist():
                        if info.filename == target_entry:
                            zout.writestr(info, repaired_bytes, compress_type=zipfile.ZIP_DEFLATED)
                        else:
                            zout.writestr(info, zin.read(info.filename))
            with zipfile.ZipFile(tmp_zip, "r") as zchk:
                bad_member = zchk.testzip()
                if bad_member is not None:
                    raise RuntimeError(f"Ошибка проверки целостности ZIP ({bad_member})")
            if orig_mode is not None:
                try:
                    os.chmod(tmp_zip, orig_mode)
                except OSError:
                    pass
            os.replace(tmp_zip, src_path)
        except Exception:
            if os.path.exists(tmp_zip):
                os.remove(tmp_zip)
            raise
    else:
        fd, tmp_fb2 = tempfile.mkstemp(prefix=".fbc_repair_", suffix=".fb2", dir=parent_dir)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(repaired_bytes)
                fh.flush()
                os.fsync(fh.fileno())
            if orig_mode is not None:
                try:
                    os.chmod(tmp_fb2, orig_mode)
                except OSError:
                    pass
            os.replace(tmp_fb2, src_path)
        except Exception:
            if os.path.exists(tmp_fb2):
                os.remove(tmp_fb2)
            raise

    if "xml" in data:
        data["xml"] = repaired_bytes
    refresh_book_warnings(data, xml_bytes=repaired_bytes)
    logger.info("Исправлен FB2 %s: %s", data.get("display_name") or src_path, stats)
    return stats


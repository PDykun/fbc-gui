import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.request
import zipfile

from core.fbc_manager import (
    FBC_RELEASES_API,
    _copy_stream_limited,
    compute_file_hashes,
    parse_checksums_text,
)
from core.logger import get_logger
from core.updater import _build_ssl_context, is_safe_http_url, safe_urlopen

logger = get_logger("s2k_manager")

S2K_GITHUB_API_LATEST = f"{FBC_RELEASES_API.replace('/fb2cng/', '/sync2kindle/')}/latest"
S2K_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
S2K_TIMEOUT_SEC = 20
S2K_VERSION_RE = re.compile(r"\b(\d+\.\d+(?:\.\d+)?)\b")
_S2K_COPY_FILE_RE = re.compile(r'"action"\s*:\s*"Copy"[^}]*"file"\s*:\s*"([^"]+)"')

EBOOK_SYNC_EXTENSIONS = (".epub", ".azw3", ".kfx", ".azw8", ".pdf", ".mobi")
S2K_BOOK_EXTENSIONS = (".kfx", ".azw3", ".mobi", ".pdf")
S2K_SIDECAR_EXTENSIONS = (".apnx",)
S2K_KINDLE_FORMATS = ("kfx", "azw3", "pdf")
FOLDER_READER_FORMATS = ("epub2", "epub3", "kepub", "kepub3", "azw3", "kfx", "azw8", "pdf")

# Общий мьютекс для исключения конфликтов при одновременной доставке на ридер через s2k (MTP/USB)
DEVICE_SYNC_EXEC_LOCK = threading.Lock()


def _s2k_exe_name():
    return "s2k.exe" if os.name == "nt" else "s2k"


def find_local_s2k_candidates(user_data_dir=None):
    """Ищет локальный бинарник s2k (sync2kindle) в user_data_dir, PATH и стандартных каталогах."""
    exe = _s2k_exe_name()
    candidates = []
    seen = set()

    def _add(p):
        if not p:
            return
        ap = os.path.abspath(p)
        key = os.path.normcase(ap)
        if key not in seen and os.path.isfile(ap):
            seen.add(key)
            candidates.append(ap)

    if user_data_dir:
        _add(os.path.join(user_data_dir, exe))
    which_path = shutil.which(exe) or shutil.which("s2k")
    if which_path:
        _add(which_path)

    if sys.platform == "darwin":
        for d in ("/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin")):
            _add(os.path.join(d, exe))
    elif os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            _add(os.path.join(local_app, "FBC_GUI", exe))
    else:
        for d in ("/usr/local/bin", "/usr/bin", os.path.expanduser("~/.local/bin")):
            _add(os.path.join(d, exe))
    return candidates


class S2kMissingLibraryError(RuntimeError):
    """Ошибка запуска s2k на macOS из-за отсутствующей системной библиотеки (например, libmtp)."""


class S2kPermissionError(PermissionError):
    """Ошибка доступа macOS TCC при чтении папки с книгами для sync2kindle."""


def is_missing_libmtp_stderr(stderr_text):
    """Возвращает True, если stderr указывает на отсутствие libmtp на macOS."""
    low = str(stderr_text or "").lower()
    return "libmtp" in low and ("library not loaded" in low or "image not found" in low or "no such file" in low)


def probe_s2k_binary(bin_path, timeout=5, raise_on_missing_lib=False):
    """Запускает s2k --version и возвращает словарь {'path', 'version'} или None."""
    if not bin_path or not os.path.isfile(bin_path):
        return None
    kwargs = {
        "cwd": os.path.dirname(os.path.abspath(bin_path)),
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        res = subprocess.run([bin_path, "--version"], **kwargs)
        out = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
        if res.returncode != 0 and is_missing_libmtp_stderr(out):
            if raise_on_missing_lib:
                raise S2kMissingLibraryError(out)
            return None
        if res.returncode != 0 and not out:
            return None
        m = S2K_VERSION_RE.search(out)
        ver = m.group(1) if m else "unknown"
        return {"path": os.path.abspath(bin_path), "version": ver}
    except S2kMissingLibraryError:
        raise
    except Exception:
        return None


def resolve_local_s2k(user_data_dir=None, raise_on_missing_lib=False):
    """Возвращает информацию о первом рабочем локальном бинарнике s2k или None."""
    missing_lib_err = None
    for cand in find_local_s2k_candidates(user_data_dir=user_data_dir):
        try:
            info = probe_s2k_binary(cand, raise_on_missing_lib=raise_on_missing_lib)
        except S2kMissingLibraryError as e:
            missing_lib_err = e
            continue
        if info:
            return info
    if missing_lib_err is not None and raise_on_missing_lib:
        raise missing_lib_err
    return None


def select_s2k_release_asset(assets, platform_name=None, machine=None):
    """Подбирает архив s2k (полная сборка USB/MTP) из списка активов релиза GitHub."""
    plat = (platform_name or sys.platform).lower()
    mach = (machine or platform.machine()).lower()
    if plat == "darwin":
        os_tokens = ("darwin", "macos")
    elif plat.startswith("win"):
        os_tokens = ("windows", "win")
    else:
        os_tokens = ("linux",)

    if any(k in mach for k in ("arm64", "aarch64")):
        arch_tokens = ("arm64", "aarch64")
    else:
        arch_tokens = ("amd64", "x86_64", "x64")

    best_full = None
    best_min = None
    for asset in (assets or []):
        name = str(asset.get("name") or "")
        low = name.lower()
        if not low.endswith((".zip", ".tar.gz", ".tgz")):
            continue
        if not any(t in low for t in os_tokens):
            continue
        if not any(t in low for t in arch_tokens):
            continue
        if low.startswith("s2k-"):
            best_full = asset
            break
        if low.startswith("s2km-") and best_min is None:
            best_min = asset
    return best_full or best_min


def _fetch_json(url, timeout=S2K_TIMEOUT_SEC):
    if not is_safe_http_url(url, allow_relative=False, require_https=True):
        raise ValueError(f"Небезопасный URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "FBC-GUI"})
    with safe_urlopen(req, timeout=timeout, context=_build_ssl_context(), require_https=True) as resp:
        raw = resp.read(2 * 1024 * 1024)
    return json.loads(raw.decode("utf-8", errors="replace"))


def download_and_install_s2k(user_data_dir, cancel_event=None, progress_callback=None, status_callback=None):
    """Загружает последний релиз sync2kindle (s2k) с GitHub, проверяет хеш и распаковывает в user_data_dir."""
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Cancelled")
    os.makedirs(user_data_dir, exist_ok=True)
    rel = _fetch_json(S2K_GITHUB_API_LATEST)
    assets = rel.get("assets") or []
    asset = select_s2k_release_asset(assets)
    if not asset:
        raise RuntimeError("Не найден подходящий дистрибутив sync2kindle (s2k) для вашей ОС и архитектуры.")

    dl_url = str(asset.get("browser_download_url") or "")
    asset_name = os.path.basename(str(asset.get("name") or "s2k.zip"))
    if not is_safe_http_url(dl_url, allow_relative=False, require_https=True):
        raise ValueError(f"Небезопасный URL загрузки: {dl_url}")

    checksums = {}
    for a in assets:
        an = str(a.get("name") or "").lower()
        raw_digest = str(a.get("digest") or "").strip()
        if ":" in raw_digest:
            algo, hex_val = raw_digest.split(":", 1)
            algo = algo.strip().lower()
            hex_val = hex_val.strip().lower()
            if algo in ("md5", "sha256") and re.fullmatch(r"[0-9a-f]{32}|[0-9a-f]{64}", hex_val):
                checksums.setdefault(an, {})[algo] = hex_val
        if "checksum" in an or "sha256" in an:
            c_url = str(a.get("browser_download_url") or "")
            if is_safe_http_url(c_url, allow_relative=False, require_https=True):
                try:
                    req = urllib.request.Request(c_url, headers={"User-Agent": "FBC-GUI"})
                    with safe_urlopen(req, timeout=S2K_TIMEOUT_SEC, context=_build_ssl_context(), require_https=True) as r:
                        for fn, algos in parse_checksums_text(r.read(512 * 1024).decode("utf-8", errors="replace")).items():
                            checksums.setdefault(fn, {}).update(algos)
                except Exception as e:
                    logger.debug("Не удалось загрузить checksums sync2kindle: %s", e)

    exe_name = _s2k_exe_name()
    dst_bin = os.path.join(user_data_dir, exe_name)

    with tempfile.TemporaryDirectory(prefix="s2k_dl_") as td:
        archive_path = os.path.join(td, asset_name)
        req = urllib.request.Request(dl_url, headers={"User-Agent": "FBC-GUI"})
        with safe_urlopen(req, timeout=S2K_TIMEOUT_SEC, context=_build_ssl_context(), require_https=True) as resp:
            raw_len = resp.headers.get("Content-Length") if hasattr(resp, "headers") and resp.headers else None
            try:
                total_bytes = int(raw_len) if raw_len else int(asset.get("size") or 0)
            except (TypeError, ValueError):
                total_bytes = 0
            if total_bytes > S2K_MAX_ARCHIVE_BYTES:
                raise ValueError(f"Размер архива превышает допустимый лимит ({S2K_MAX_ARCHIVE_BYTES} байт)")
            downloaded = 0
            if progress_callback is not None:
                progress_callback(0, total_bytes, asset_name)
            with open(archive_path, "wb") as out_f:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError("Cancelled")
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > S2K_MAX_ARCHIVE_BYTES:
                        raise ValueError(f"Размер архива превышает допустимый лимит ({S2K_MAX_ARCHIVE_BYTES} байт)")
                    out_f.write(chunk)
                    if progress_callback is not None:
                        progress_callback(downloaded, total_bytes, asset_name)
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Cancelled")

        if status_callback is not None:
            status_callback("verifying")

        expected = checksums.get(asset_name.lower())
        hash_verified = False
        if isinstance(expected, dict) and expected:
            actual_hashes = compute_file_hashes(archive_path)
            for algo, exp_hex in expected.items():
                actual_hex = actual_hashes.get(algo, "")
                if actual_hex and actual_hex.lower() != str(exp_hex).lower():
                    raise RuntimeError(f"Ошибка проверки контрольной суммы {asset_name} ({algo})")
            hash_verified = True
        else:
            logger.warning(
                "Релиз sync2kindle не содержит контрольной суммы для %s; целостность архива не подтверждена",
                asset_name,
            )

        fd_tmp, extracted_tmp = tempfile.mkstemp(prefix=f".{exe_name}.", suffix=".tmp", dir=user_data_dir)
        os.close(fd_tmp)
        found_bin = False
        try:
            if asset_name.lower().endswith(".zip"):
                with zipfile.ZipFile(archive_path, "r") as z:
                    for member in z.namelist():
                        if os.path.basename(member).lower() in (exe_name.lower(), "s2km", "s2km.exe"):
                            with z.open(member, "r") as src_m, open(extracted_tmp, "wb") as dst_m:
                                _copy_stream_limited(src_m, dst_m, max_bytes=S2K_MAX_ARCHIVE_BYTES)
                            found_bin = True
                            break
            else:
                with tarfile.open(archive_path, "r:*") as tf:
                    for member in tf.getmembers():
                        if member.isfile() and os.path.basename(member.name).lower() in (exe_name.lower(), "s2km", "s2km.exe"):
                            src_m = tf.extractfile(member)
                            if src_m is not None:
                                with src_m, open(extracted_tmp, "wb") as dst_m:
                                    _copy_stream_limited(src_m, dst_m, max_bytes=S2K_MAX_ARCHIVE_BYTES)
                                found_bin = True
                            break

            if not found_bin:
                raise RuntimeError(f"В архиве {asset_name} не найден исполняемый файл {exe_name}")

            if os.name != "nt":
                os.chmod(extracted_tmp, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
            os.replace(extracted_tmp, dst_bin)
        except Exception:
            if os.path.exists(extracted_tmp):
                try:
                    os.remove(extracted_tmp)
                except OSError:
                    pass
            raise

    info = probe_s2k_binary(dst_bin)
    result = dict(info) if info else {
        "path": dst_bin,
        "version": str(rel.get("tag_name") or "").lstrip("vV") or "unknown",
    }
    result["verified"] = hash_verified
    logger.info("sync2kindle установлен: %s (ver=%s, verified=%s)", dst_bin, result["version"], hash_verified)
    return result


def check_directory_access(dir_path):
    """Универсально проверяет, существует ли папка и доступна ли она на чтение (macOS TCC / ACL / права ОС)."""
    if not dir_path:
        return {"exists": False, "readable": False, "protected": False, "error": "empty_path"}
    ap = os.path.abspath(str(dir_path))
    if not os.path.isdir(ap):
        return {"exists": False, "readable": False, "protected": False, "error": "not_found"}
    try:
        with os.scandir(ap) as it:
            next(it, None)
        return {"exists": True, "readable": True, "protected": False, "error": ""}
    except PermissionError as e:
        return {"exists": True, "readable": False, "protected": True, "error": str(e)}
    except OSError as e:
        return {"exists": True, "readable": False, "protected": False, "error": str(e)}


def check_sync_format_compatibility(mode, output_format, device_profile="custom"):
    """Проверяет совместимость выбранного формата конвертации с режимом доставки на ридер."""
    norm_mode = str(mode or "mtp").strip().lower()
    if norm_mode not in ("mtp", "usb", "folder"):
        norm_mode = "mtp"
    norm_fmt = str(output_format or "").strip().lower()
    norm_prof = str(device_profile or "custom").strip().lower()

    if norm_mode in ("mtp", "usb"):
        supported = S2K_KINDLE_FORMATS
        recommended = "kfx" if norm_mode == "mtp" else "azw3"
    else:
        supported = FOLDER_READER_FORMATS
        if norm_prof == "kobo":
            recommended = "kepub"
        elif norm_prof == "remarkable":
            recommended = "pdf"
        else:
            recommended = "epub3"

    return {
        "compatible": norm_fmt in supported,
        "recommended": recommended,
        "supported": supported,
        "mode": norm_mode,
        "format": norm_fmt,
    }


def stage_books_for_s2k(source_dir, staging_dir, explicit_files=None):
    """Копирует готовые книги для Kindle (.kfx/.azw3/.mobi/.pdf + .apnx) во временную папку без macOS TCC."""
    os.makedirs(staging_dir, exist_ok=True)
    staged_books = []
    staged_names = set()
    perm_error = None

    def _stage_one_file(src_fp, rel_fp=None):
        nonlocal perm_error
        if not src_fp or not os.path.isfile(src_fp):
            return False
        fname = os.path.basename(src_fp)
        if fname.startswith("."):
            return False
        low = fname.lower()
        is_book = low.endswith(S2K_BOOK_EXTENSIONS)
        is_sidecar = low.endswith(S2K_SIDECAR_EXTENSIONS)
        if not (is_book or is_sidecar):
            return False
        target_rel = rel_fp or fname
        norm_key = os.path.normcase(target_rel)
        if norm_key in staged_names:
            return is_book
        dst_fp = os.path.join(staging_dir, target_rel)
        os.makedirs(os.path.dirname(dst_fp), exist_ok=True)
        try:
            shutil.copy2(src_fp, dst_fp)
        except PermissionError as e:
            perm_error = e
            return False
        staged_names.add(norm_key)
        if is_book:
            staged_books.append(target_rel)
            stem, _ = os.path.splitext(src_fp)
            apnx_src = stem + ".apnx"
            if os.path.isfile(apnx_src):
                apnx_rel = os.path.splitext(target_rel)[0] + ".apnx"
                _stage_one_file(apnx_src, rel_fp=apnx_rel)
        return is_book

    # 1. Сначала копируем явно известные сконвертированные файлы (не требует os.listdir на TCC-папках macOS)
    for fp in (explicit_files or []):
        _stage_one_file(fp)
    if staged_books:
        return staged_books

    # 2. Иначе проверяем доступ к source_dir и сканируем папку, перехватывая PermissionError от macOS TCC
    if source_dir and os.path.isdir(source_dir):
        src_root = os.path.abspath(source_dir)
        access = check_directory_access(src_root)
        if access["protected"]:
            raise S2kPermissionError(access["error"] or src_root)

        def _on_walk_err(err):
            nonlocal perm_error
            if isinstance(err, PermissionError):
                perm_error = err

        for root, dirs, files in os.walk(src_root, onerror=_on_walk_err):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            rel_dir = os.path.relpath(root, src_root)
            for fname in sorted(files):
                src_fp = os.path.join(root, fname)
                rel_fp = fname if rel_dir == "." else os.path.join(rel_dir, fname)
                _stage_one_file(src_fp, rel_fp=rel_fp)

    if not staged_books and perm_error is not None:
        raise S2kPermissionError(str(perm_error)) from perm_error
    return staged_books


def parse_s2k_copy_action(line):
    """Извлекает имя книги из строки лога sync2kindle о копировании файла на устройство."""
    text = str(line or "")
    if "Executing" not in text or "Copy" not in text:
        return None
    m = _S2K_COPY_FILE_RE.search(text)
    if not m:
        return None
    rel_path = m.group(1).replace("\\", "/")
    return os.path.basename(rel_path)


def summarize_s2k_output(output_text):
    """Извлекает список скопированных книг из вывода sync2kindle."""
    copied = []
    for line in str(output_text or "").splitlines():
        fname = parse_s2k_copy_action(line)
        if fname:
            copied.append(fname)
    return {"copied": copied, "count": len(copied)}


def is_no_books_in_source_stderr(stderr_text):
    """Возвращает True, если s2k сообщил об отсутствии подходящих файлов книг в source_dir."""
    low = str(stderr_text or "").lower()
    return "no books in the source path" in low


def write_s2k_sync_config(config_path, source_dir, target_dir="documents/books"):
    """Записывает минимальный YAML-конфиг для sync2kindle (s2k -c <file> mtp|usb)."""
    src = os.path.abspath(str(source_dir or "."))
    tgt = str(target_dir or "").strip() or "documents/books"
    lines = [
        f"source: {json.dumps(src, ensure_ascii=False)}",
        f"target: {json.dumps(tgt, ensure_ascii=False)}",
        "",
    ]
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return config_path


def build_s2k_sync_command(
    s2k_bin,
    mode,
    source_dir="",
    target_dir="",
    dry_run=False,
    ignore_device_removals=True,
    config_path=None,
):
    """Формирует команду запуска sync2kindle: s2k [-c config.yaml] mtp|usb [options]."""
    norm_mode = "usb" if str(mode).strip().lower() == "usb" else "mtp"
    cmd = [s2k_bin]
    if config_path:
        cmd.extend(["-c", os.path.abspath(config_path)])
    cmd.append(norm_mode)
    if ignore_device_removals:
        cmd.append("--ignore-device-removals")
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def sync_folder_to_mounted_device(source_dir, target_dir, dry_run=False, explicit_files=None, progress_callback=None):
    """Копирует сконвертированные книги из source_dir в смонтированную папку ридера (Kobo/PocketBook/USB)."""
    if not target_dir or not os.path.isdir(target_dir):
        raise FileNotFoundError(f"Папка ридера не найдена: {target_dir}")
    tgt_access = check_directory_access(target_dir)
    if tgt_access["protected"]:
        raise S2kPermissionError(os.path.abspath(target_dir))

    candidate_files = []
    seen = set()
    for fp in (explicit_files or []):
        if fp and os.path.isfile(fp) and os.path.basename(fp).lower().endswith(EBOOK_SYNC_EXTENSIONS):
            norm = os.path.normcase(os.path.abspath(fp))
            if norm not in seen:
                seen.add(norm)
                candidate_files.append(os.path.abspath(fp))

    if not candidate_files:
        if not source_dir or not os.path.isdir(source_dir):
            raise FileNotFoundError(f"Папка с книгами не найдена: {source_dir}")
        src_access = check_directory_access(source_dir)
        if src_access["protected"]:
            raise S2kPermissionError(os.path.abspath(source_dir))
        try:
            entries = sorted(os.listdir(source_dir))
        except PermissionError as e:
            raise S2kPermissionError(os.path.abspath(source_dir)) from e
        for fname in entries:
            src_fp = os.path.join(source_dir, fname)
            if os.path.isfile(src_fp) and fname.lower().endswith(EBOOK_SYNC_EXTENSIONS):
                candidate_files.append(src_fp)

    copied = []
    skipped = []
    total = len(candidate_files)
    for idx, src_fp in enumerate(candidate_files, start=1):
        fname = os.path.basename(src_fp)
        dst_fp = os.path.join(target_dir, fname)
        if os.path.isfile(dst_fp):
            try:
                if os.path.getsize(dst_fp) == os.path.getsize(src_fp) and os.path.getmtime(dst_fp) >= os.path.getmtime(src_fp):
                    skipped.append(fname)
                    if progress_callback is not None:
                        progress_callback(idx, total, fname)
                    continue
            except OSError:
                pass
        if not dry_run:
            try:
                shutil.copy2(src_fp, dst_fp)
            except PermissionError as e:
                raise S2kPermissionError(os.path.abspath(src_fp)) from e
        copied.append(fname)
        if progress_callback is not None:
            progress_callback(idx, total, fname)
    return {"copied": copied, "skipped": skipped, "dry_run": bool(dry_run)}


def _classify_mounted_volume(vol_path, vol_name):
    """Определяет тип смонтированного USB-ридера по имени тома и служебным папкам."""
    low = str(vol_name or "").lower()
    if os.path.isdir(os.path.join(vol_path, ".kobo")) or "kobo" in low:
        books_dir = os.path.join(vol_path, "Books")
        return {
            "name": f"Kobo ({vol_name})",
            "kind": "kobo",
            "path": books_dir if os.path.isdir(books_dir) else vol_path,
            "recommended_format": "kepub3",
        }
    if "kindle" in low or (
        os.path.isdir(os.path.join(vol_path, "documents"))
        and os.path.isdir(os.path.join(vol_path, "system"))
    ):
        docs_dir = os.path.join(vol_path, "documents")
        return {
            "name": f"Kindle ({vol_name})",
            "kind": "kindle",
            "path": docs_dir if os.path.isdir(docs_dir) else vol_path,
            "recommended_format": "azw3",
        }
    if "pocketbook" in low or (
        os.path.isdir(os.path.join(vol_path, "system", "config"))
        and os.path.isdir(os.path.join(vol_path, "books"))
    ):
        pb_books = os.path.join(vol_path, "books")
        return {
            "name": f"PocketBook ({vol_name})",
            "kind": "pocketbook",
            "path": pb_books if os.path.isdir(pb_books) else vol_path,
            "recommended_format": "epub3",
        }
    if "boox" in low or "onyx" in low:
        boox_books = os.path.join(vol_path, "Books")
        return {
            "name": f"ONYX BOOX ({vol_name})",
            "kind": "onyx_boox",
            "path": boox_books if os.path.isdir(boox_books) else vol_path,
            "recommended_format": "epub3",
        }
    return None


def detect_mounted_readers(platform_name=None, volumes_roots=None, home_dir=None):
    """Ищет подключённые по USB ридеры (Kobo, Kindle, PocketBook, BOOX) и облачные папки Kobo (Dropbox/Google Drive)."""
    plat = (platform_name or sys.platform).lower()
    home = os.path.abspath(home_dir or os.path.expanduser("~"))
    found = []
    seen_paths = set()

    def _add(entry):
        if not entry:
            return
        norm = os.path.normcase(os.path.abspath(entry["path"]))
        if norm not in seen_paths:
            seen_paths.add(norm)
            found.append(entry)

    if volumes_roots is not None:
        roots = list(volumes_roots)
    elif plat == "darwin":
        roots = ["/Volumes"]
    elif plat.startswith("win"):
        roots = [f"{chr(c)}:\\" for c in range(ord("D"), ord("Z") + 1) if os.path.isdir(f"{chr(c)}:\\")]
    else:
        user = os.path.basename(home)
        roots = [p for p in (f"/media/{user}", f"/run/media/{user}", "/media", "/mnt") if os.path.isdir(p)]

    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        if plat.startswith("win") and len(root) <= 3 and root.endswith("\\"):
            _add(_classify_mounted_volume(root, root.rstrip("\\")))
            continue
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            continue
        for name in entries:
            if name.startswith(".") or name in ("Macintosh HD", "Recovery", "Preboot", "VM"):
                continue
            vol_path = os.path.join(root, name)
            if not os.path.isdir(vol_path):
                continue
            _add(_classify_mounted_volume(vol_path, name))

    cloud_candidates = [
        ("Kobo Cloud (Dropbox)", os.path.join(home, "Dropbox", "Apps", "Rakuten Kobo")),
        ("Kobo Cloud (Dropbox)", os.path.join(home, "Library", "CloudStorage", "Dropbox", "Apps", "Rakuten Kobo")),
        ("Kobo Cloud (Google Drive)", os.path.join(home, "Google Drive", "Rakuten Kobo")),
        ("Kobo Cloud (Google Drive)", os.path.join(home, "Google Drive", "My Drive", "Rakuten Kobo")),
    ]
    cloud_storage_dir = os.path.join(home, "Library", "CloudStorage")
    if os.path.isdir(cloud_storage_dir):
        try:
            for item in sorted(os.listdir(cloud_storage_dir)):
                if item.startswith("GoogleDrive-"):
                    cloud_candidates.append(
                        ("Kobo Cloud (Google Drive)", os.path.join(cloud_storage_dir, item, "My Drive", "Rakuten Kobo"))
                    )
        except OSError:
            pass

    for label, cpath in cloud_candidates:
        if os.path.isdir(cpath):
            _add({
                "name": label,
                "kind": "kobo_cloud",
                "path": cpath,
                "recommended_format": "kepub3",
            })

    return found

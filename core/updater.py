import hashlib
import json
import os
import platform as py_platform
import plistlib
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

from packaging.version import InvalidVersion, Version

try:
    from PyQt6.QtCore import QThread, pyqtSignal
    HAS_PYQT = True
except ImportError:
    QThread = object
    pyqtSignal = None
    HAS_PYQT = False

from core.logger import get_logger

logger = get_logger("updater")

UPDATE_CHECK_INTERVAL_SEC = 86400
MAX_MANIFEST_BYTES = 256 * 1024
MAX_UPDATE_FILE_BYTES = 512 * 1024 * 1024

DEFAULT_GITHUB_REPO = "PDykun/fbc-gui"
DEFAULT_MANIFEST_URL = f"https://github.com/{DEFAULT_GITHUB_REPO}/releases/latest/download/version.json"
DEFAULT_RELEASES_URL = f"https://github.com/{DEFAULT_GITHUB_REPO}/releases/latest"
DEFAULT_ALLOWED_UPDATE_HOSTS = (
    "github.com",
    "api.github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
)

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_UNSAFE_WIN_BAT_CHARS = frozenset('"\r\n\x00')


class UpdateCancelledError(Exception):
    """Исключение при отмене загрузки обновления пользователем."""


class UpdateHashMismatchError(RuntimeError):
    """Исключение при несовпадении контрольной суммы SHA-256 скачанного обновления."""


def is_safe_http_url(url, allow_relative=False, require_https=False):
    """Проверяет, что URL использует безопасную схему https (или http при require_https=False)."""
    raw = str(url or "").strip()
    if not raw or any(ch in raw for ch in ("\r", "\n", "\x00")):
        return False
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme:
        allowed = ("https",) if require_https else ("http", "https")
        return parsed.scheme.lower() in allowed and bool(parsed.netloc)
    return bool(allow_relative and not raw.startswith("//"))


def is_allowed_update_host(url, allowed_hosts=DEFAULT_ALLOWED_UPDATE_HOSTS):
    """Проверяет, что хост URL обновления принадлежит доверенному списку доменов."""
    if not allowed_hosts:
        return True
    parsed = urllib.parse.urlparse(str(url or "").strip())
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    return any(host == h.lower() or host.endswith("." + h.lower()) for h in allowed_hosts)


def normalize_update_platform_arch(sys_platform=None, machine=None):
    """Возвращает нормализованную пару (os_name, arch), например ('macos', 'arm64') или ('windows', 'x64')."""
    plat = (sys_platform or sys.platform).lower()
    if plat.startswith("darwin") or plat.startswith("mac"):
        os_name = "macos"
    elif plat.startswith("win") or plat in ("nt", "cygwin", "msys"):
        os_name = "windows"
    else:
        os_name = "linux"

    raw_arch = (machine or py_platform.machine() or "").lower().strip()
    if raw_arch in ("arm64", "aarch64"):
        arch = "arm64"
    elif raw_arch in ("x86_64", "amd64", "x64"):
        arch = "x64"
    elif raw_arch in ("i386", "i686", "x86", "386"):
        arch = "x86"
    else:
        arch = raw_arch or "x64"
    return os_name, arch


def get_current_platform_id(sys_platform=None, machine=None):
    """Возвращает идентификатор текущей платформы и архитектуры, например 'macos-arm64' или 'windows-x64'."""
    os_name, arch = normalize_update_platform_arch(sys_platform=sys_platform, machine=machine)
    return f"{os_name}-{arch}"


def parse_version_tuple(ver_str):
    """Преобразует строку версии ('1.0.2') в кортеж целых чисел (1, 0, 2)."""
    parts = []
    for chunk in str(ver_str or "0").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def _parse_semver(ver_str):
    cleaned = str(ver_str or "").strip().lstrip("vV")
    if not cleaned:
        return None
    try:
        return Version(cleaned)
    except InvalidVersion:
        return None


def parse_build_number(build_val):
    """Извлекает целочисленный номер билда из int или строки ('115', '2.11.115', 'build 115')."""
    if isinstance(build_val, bool) or build_val is None:
        return 0
    if isinstance(build_val, int):
        return max(0, build_val)
    raw = str(build_val).strip()
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        nums = re.findall(r"\d+", raw)
        return int(nums[-1]) if nums else 0


def is_newer_version(remote_ver, remote_build, local_ver, local_build):
    """Возвращает True, если удалённая версия или номер билда новее локальных (через packaging.version)."""
    r_sem = _parse_semver(remote_ver)
    l_sem = _parse_semver(local_ver)

    if r_sem is not None and l_sem is not None:
        if r_sem != l_sem:
            return r_sem > l_sem
    else:
        r_ver = parse_version_tuple(remote_ver)
        l_ver = parse_version_tuple(local_ver)
        max_len = max(len(r_ver), len(l_ver))
        r_ver_padded = r_ver + (0,) * (max_len - len(r_ver))
        l_ver_padded = l_ver + (0,) * (max_len - len(l_ver))
        if r_ver_padded != l_ver_padded:
            return r_ver_padded > l_ver_padded

    return parse_build_number(remote_build) > parse_build_number(local_build)


def compute_file_sha256(filepath):
    """Вычисляет SHA-256 хеш файла в нижнем регистре."""
    digest = hashlib.sha256()
    with open(filepath, "rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def verify_file_sha256(filepath, expected_sha256):
    """Проверяет, что SHA-256 файла совпадает с ожидаемым 64-символьным hex-хешем."""
    expected = str(expected_sha256 or "").strip().lower()
    if not _SHA256_RE.fullmatch(expected):
        return False
    actual = compute_file_sha256(filepath)
    return actual == expected


def _infer_asset_kind(filename, explicit_kind=""):
    kind = str(explicit_kind or "").strip().lower()
    if kind in ("installer", "portable", "dmg", "archive"):
        return kind
    low = str(filename or "").strip().lower()
    if low.endswith(".dmg"):
        return "dmg"
    if low.endswith(".exe"):
        if "setup" in low or "installer" in low:
            return "installer"
        return "portable"
    return "archive"


def _candidate_asset_keys(sys_platform=None, machine=None):
    os_name, arch = normalize_update_platform_arch(sys_platform=sys_platform, machine=machine)
    if os_name == "macos":
        keys = [f"macos-{arch}", f"darwin-{arch}"]
        if arch == "arm64":
            keys.extend(["macos-universal", "darwin-universal", "macos-x64", "darwin-x64"])
        elif arch == "x64":
            keys.extend(["macos-universal", "darwin-universal"])
        keys.extend(["darwin", "macos", "mac"])
        return keys
    if os_name == "windows":
        keys = [f"windows-{arch}", f"win-{arch}"]
        if arch == "arm64":
            keys.extend(["windows-x64", "win-x64"])
        keys.extend(["win32", "windows", "win"])
        return keys
    return [f"linux-{arch}", "linux", str(sys_platform or sys.platform).lower()]


def _extract_filename_from_url(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    return os.path.basename(urllib.parse.unquote(parsed.path))


def select_update_asset(manifest, sys_platform=None, machine=None, fallback_url=""):
    """Выбирает подходящий актив обновления (URL, имя файла, SHA-256, тип) под текущую ОС и архитектуру."""
    if not isinstance(manifest, dict):
        return {
            "url": fallback_url,
            "filename": _extract_filename_from_url(fallback_url),
            "sha256": "",
            "kind": "",
            "platform_key": "",
        }

    keys = _candidate_asset_keys(sys_platform=sys_platform, machine=machine)
    release_base = str(manifest.get("release_base_url") or "").strip().rstrip("/")

    for container_key in ("assets", "downloads"):
        container = manifest.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in keys:
            entry = container.get(key)
            if isinstance(entry, dict):
                raw_url = str(entry.get("url") or "").strip()
                filename = str(entry.get("filename") or entry.get("name") or "").strip()
                if not raw_url and filename and release_base:
                    raw_url = f"{release_base}/{filename}"
                if raw_url and is_safe_http_url(raw_url, allow_relative=True, require_https=True):
                    if not filename:
                        filename = _extract_filename_from_url(raw_url)
                    sha256 = str(entry.get("sha256") or "").strip().lower()
                    return {
                        "url": raw_url,
                        "filename": filename,
                        "sha256": sha256 if _SHA256_RE.fullmatch(sha256) else "",
                        "kind": _infer_asset_kind(filename, entry.get("kind", "")),
                        "platform_key": key,
                    }
            elif isinstance(entry, str) and is_safe_http_url(entry, allow_relative=True, require_https=True):
                raw_url = entry.strip()
                filename = _extract_filename_from_url(raw_url)
                return {
                    "url": raw_url,
                    "filename": filename,
                    "sha256": "",
                    "kind": _infer_asset_kind(filename),
                    "platform_key": key,
                }

    top_url = manifest.get("download_url")
    if isinstance(top_url, str) and is_safe_http_url(top_url, allow_relative=True, require_https=True):
        raw_url = top_url.strip()
        filename = _extract_filename_from_url(raw_url)
        return {
            "url": raw_url,
            "filename": filename,
            "sha256": "",
            "kind": _infer_asset_kind(filename),
            "platform_key": "default",
        }

    return {
        "url": fallback_url,
        "filename": _extract_filename_from_url(fallback_url),
        "sha256": "",
        "kind": "",
        "platform_key": "",
    }


def select_download_url(manifest, platform=None, fallback_url="", machine=None):
    """Выбирает безопасный URL скачивания для текущей ОС из манифеста version.json."""
    asset = select_update_asset(
        manifest,
        sys_platform=platform,
        machine=machine,
        fallback_url=fallback_url,
    )
    return asset.get("url") or fallback_url


MAX_HTTP_REDIRECTS = 5
_SENSITIVE_REDIRECT_HEADERS = frozenset({"authorization", "x-goog-api-key"})
_ORIG_URLOPEN = urllib.request.urlopen


def _build_ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Контролирует HTTP-редиректы: проверяет схему URL, доверенные хосты, лимит переходов и снимает секретные заголовки на чужой origin."""

    def __init__(self, require_https=True, max_redirects=MAX_HTTP_REDIRECTS, allowed_hosts=None):
        super().__init__()
        self._require_https = bool(require_https)
        self._max_redirects = max(0, int(max_redirects))
        self._allowed_hosts = tuple(allowed_hosts) if allowed_hosts is not None else None

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        count = int(getattr(req, "_fbc_redirect_count", 0))
        if count >= self._max_redirects:
            raise urllib.error.HTTPError(
                newurl, code, f"Too many redirects (>{self._max_redirects})", headers, fp
            )
        resolved = urllib.parse.urljoin(req.full_url, str(newurl or "").strip())
        if not is_safe_http_url(resolved, allow_relative=False, require_https=self._require_https):
            raise ValueError(f"Blocked unsafe redirect URL: {resolved}")
        if self._allowed_hosts is not None and not is_allowed_update_host(resolved, self._allowed_hosts):
            raise ValueError(f"Blocked redirect to untrusted host: {resolved}")
        new_req = super().redirect_request(req, fp, code, msg, headers, resolved)
        if new_req is None:
            return None
        new_req._fbc_redirect_count = count + 1
        old_p = urllib.parse.urlsplit(req.full_url)
        new_p = urllib.parse.urlsplit(resolved)
        if (old_p.scheme.lower(), old_p.netloc.lower()) != (new_p.scheme.lower(), new_p.netloc.lower()):
            for hdr_dict in (new_req.headers, new_req.unredirected_hdrs):
                for k in list(hdr_dict.keys()):
                    if k.lower() in _SENSITIVE_REDIRECT_HEADERS:
                        del hdr_dict[k]
        return new_req


def safe_urlopen(
    req,
    timeout=15,
    context=None,
    require_https=True,
    max_redirects=MAX_HTTP_REDIRECTS,
    allowed_hosts=None,
):
    """Безопасная обёртка над urllib.request с проверкой URL, редиректов, доверенных хостов и TLS-контекста."""
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    if not is_safe_http_url(url, allow_relative=False, require_https=require_https):
        raise ValueError(f"Unsupported URL scheme: {url}")
    if allowed_hosts is not None and not is_allowed_update_host(url, allowed_hosts):
        raise ValueError(f"Untrusted URL host: {url}")
    if urllib.request.urlopen is not _ORIG_URLOPEN:
        return urllib.request.urlopen(req, timeout=timeout, context=context)
    handlers = [
        _SafeRedirectHandler(
            require_https=require_https,
            max_redirects=max_redirects,
            allowed_hosts=allowed_hosts,
        )
    ]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(req, timeout=timeout)


def fetch_update_info(
    local_ver,
    local_build,
    manifest_url=DEFAULT_MANIFEST_URL,
    timeout=8,
    lang="ru",
    fallback_url=DEFAULT_RELEASES_URL,
    sys_platform=None,
    machine=None,
    allowed_hosts=None,
):
    """Загружает version.json (через GitHub Releases latest/download) и проверяет наличие новой версии."""
    local_build_num = parse_build_number(local_build)
    result = {
        "has_update": False,
        "version": str(local_ver),
        "build": local_build_num,
        "download_url": fallback_url,
        "filename": "",
        "sha256": "",
        "kind": "",
        "platform_key": "",
        "changelog": "",
        "error": None,
    }
    try:
        if not is_safe_http_url(manifest_url, allow_relative=False, require_https=True):
            raise ValueError(f"Unsupported manifest URL scheme: {manifest_url}")
        eff_hosts = allowed_hosts
        if eff_hosts is None and is_allowed_update_host(manifest_url, DEFAULT_ALLOWED_UPDATE_HOSTS):
            eff_hosts = DEFAULT_ALLOWED_UPDATE_HOSTS
        req = urllib.request.Request(
            manifest_url,
            headers={
                "User-Agent": f"FBC-GUI/{local_ver}",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
        )
        ctx = _build_ssl_context()
        with safe_urlopen(
            req,
            timeout=timeout,
            context=ctx,
            require_https=True,
            allowed_hosts=eff_hosts,
        ) as resp:
            raw_bytes = resp.read(MAX_MANIFEST_BYTES + 1)
        if len(raw_bytes) > MAX_MANIFEST_BYTES:
            raise ValueError("Update manifest exceeds size limit")
        manifest = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("Invalid manifest format")

        remote_ver = str(manifest.get("version", local_ver)).strip()
        remote_build = parse_build_number(manifest.get("build", 0))
        changelog_raw = manifest.get("changelog", "")
        if isinstance(changelog_raw, dict):
            changelog = str(
                changelog_raw.get(lang)
                or changelog_raw.get("en")
                or changelog_raw.get("ru")
                or ""
            ).strip()
        else:
            changelog = str(changelog_raw or "").strip()

        result["version"] = remote_ver
        result["build"] = remote_build

        asset = select_update_asset(
            manifest,
            sys_platform=sys_platform,
            machine=machine,
            fallback_url=fallback_url,
        )
        selected_url = asset.get("url") or fallback_url
        if selected_url and not is_safe_http_url(selected_url, allow_relative=False, require_https=True):
            if fallback_url and is_safe_http_url(fallback_url, allow_relative=False, require_https=True):
                selected_url = urllib.parse.urljoin(fallback_url.rstrip("/") + "/", selected_url)
            else:
                selected_url = fallback_url

        result["download_url"] = selected_url
        result["filename"] = asset.get("filename") or _extract_filename_from_url(selected_url)
        result["sha256"] = asset.get("sha256") or ""
        result["kind"] = asset.get("kind") or ""
        result["platform_key"] = asset.get("platform_key") or ""
        result["changelog"] = changelog
        result["has_update"] = is_newer_version(remote_ver, remote_build, local_ver, local_build)
    except Exception as e:
        result["error"] = str(e)
    return result


def download_and_verify_update(
    download_url,
    expected_sha256,
    filename="",
    dest_dir=None,
    progress_callback=None,
    status_callback=None,
    cancel_event=None,
    timeout=30,
    user_agent="FBC-GUI",
    allowed_hosts=None,
):
    """Скачивает файл обновления во временную папку и проверяет его SHA-256 перед установкой."""
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateCancelledError("Update download cancelled")

    if not is_safe_http_url(download_url, allow_relative=False, require_https=True):
        raise ValueError(f"Unsupported download URL scheme: {download_url}")
    eff_hosts = allowed_hosts
    if eff_hosts is None and is_allowed_update_host(download_url, DEFAULT_ALLOWED_UPDATE_HOSTS):
        eff_hosts = DEFAULT_ALLOWED_UPDATE_HOSTS
    if eff_hosts is not None and not is_allowed_update_host(download_url, eff_hosts):
        raise ValueError(f"Untrusted update download host: {download_url}")

    expected_clean = str(expected_sha256 or "").strip().lower()
    if not _SHA256_RE.fullmatch(expected_clean):
        raise ValueError("Missing or invalid SHA-256 checksum in update manifest")

    safe_name = os.path.basename(str(filename or _extract_filename_from_url(download_url) or "update.bin"))
    if not safe_name or safe_name in (".", ".."):
        safe_name = "update.bin"

    created_temp_dir = dest_dir is None
    target_dir = dest_dir or tempfile.mkdtemp(prefix="fbc_gui_update_")
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, safe_name)

    if status_callback:
        status_callback("downloading")

    req = urllib.request.Request(download_url, headers={"User-Agent": user_agent})
    ctx = _build_ssl_context()
    downloaded = 0

    try:
        with safe_urlopen(req, timeout=timeout, context=ctx, require_https=True, allowed_hosts=eff_hosts) as resp, open(target_path, "wb") as out_fh:
            try:
                total = max(0, int(resp.headers.get("Content-Length") or 0))
            except (TypeError, ValueError):
                total = 0
            if total > MAX_UPDATE_FILE_BYTES:
                raise ValueError(f"Update file exceeds size limit ({MAX_UPDATE_FILE_BYTES} bytes)")
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise UpdateCancelledError("Update download cancelled")
                chunk = resp.read(65536)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MAX_UPDATE_FILE_BYTES:
                    raise ValueError(f"Update file exceeds size limit ({MAX_UPDATE_FILE_BYTES} bytes)")
                out_fh.write(chunk)
                if progress_callback:
                    progress_callback(downloaded, total, safe_name)

        if status_callback:
            status_callback("verifying")

        actual_sha256 = compute_file_sha256(target_path)
        if actual_sha256 != expected_clean:
            raise UpdateHashMismatchError(
                f"SHA-256 mismatch for {safe_name}: expected {expected_clean}, got {actual_sha256}"
            )
    except Exception:
        try:
            if os.path.exists(target_path):
                os.remove(target_path)
            if created_temp_dir and os.path.isdir(target_dir):
                shutil.rmtree(target_dir, ignore_errors=True)
        except OSError:
            pass
        raise

    logger.info("Обновление загружено и проверено (SHA-256 OK): %s", target_path)
    return target_path


def create_windows_portable_update_script(current_exe, new_exe, pid, script_dir=None):
    """Создаёт временный .bat-скрипт для безопасной подмены портативного .exe после закрытия приложения."""
    cur_raw = os.path.abspath(current_exe)
    new_raw = os.path.abspath(new_exe)
    for label, pval in (("current_exe", cur_raw), ("new_exe", new_raw)):
        if any(ch in pval for ch in _UNSAFE_WIN_BAT_CHARS):
            raise ValueError(f"Unsafe character in {label} path for Windows batch updater")

    safe_pid = int(pid)
    if safe_pid <= 0:
        raise ValueError(f"Invalid process ID: {pid}")

    out_dir = script_dir or os.path.dirname(new_raw)
    os.makedirs(out_dir, exist_ok=True)
    fd, bat_path = tempfile.mkstemp(prefix="fbc_gui_portable_update_", suffix=".bat", dir=out_dir)

    cur_abs = cur_raw.replace("%", "%%")
    new_abs = new_raw.replace("%", "%%")

    script = (
        "@echo off\r\n"
        "setlocal DisableDelayedExpansion\r\n"
        "chcp 65001 >NUL\r\n"
        f"set \"TARGET_PID={safe_pid}\"\r\n"
        f"set \"CURRENT_EXE={cur_abs}\"\r\n"
        f"set \"NEW_EXE={new_abs}\"\r\n"
        "set /a WAIT_TRIES=0\r\n"
        ":wait_loop\r\n"
        "tasklist /FI \"PID eq %TARGET_PID%\" /FO CSV /NH 2>NUL | findstr /C:\",\\\"%TARGET_PID%\\\",\" >NUL\r\n"
        "if not errorlevel 1 (\r\n"
        "    set /a WAIT_TRIES+=1\r\n"
        "    if %WAIT_TRIES% GEQ 60 goto do_replace\r\n"
        "    timeout /t 1 /nobreak >NUL\r\n"
        "    goto wait_loop\r\n"
        ")\r\n"
        ":do_replace\r\n"
        "move /Y \"%NEW_EXE%\" \"%CURRENT_EXE%\" >NUL\r\n"
        "if errorlevel 1 (\r\n"
        "    timeout /t 1 /nobreak >NUL\r\n"
        "    move /Y \"%NEW_EXE%\" \"%CURRENT_EXE%\" >NUL\r\n"
        ")\r\n"
        "start \"\" \"%CURRENT_EXE%\"\r\n"
        "del \"%~f0\"\r\n"
    )
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(script)
    return bat_path


def _mount_and_open_macos_dmg(dmg_path):
    """Монтирует .dmg через hdiutil и открывает смонтированный том в Finder (fallback: open <dmg>)."""
    mount_point = ""
    try:
        proc = subprocess.run(
            ["hdiutil", "attach", "-plist", dmg_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        if proc.returncode == 0 and proc.stdout:
            plist_data = plistlib.loads(proc.stdout)
            for ent in plist_data.get("system-entities", []):
                mp = ent.get("mount-point")
                if mp and os.path.isdir(mp):
                    mount_point = mp
                    break
    except Exception as e:
        logger.warning("Не удалось смонтировать DMG через hdiutil -plist: %s", e)

    popen_kw = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "start_new_session": True,
    }
    if mount_point:
        subprocess.Popen(["open", mount_point], **popen_kw)
        return mount_point

    subprocess.Popen(["open", dmg_path], **popen_kw)
    return ""


def apply_downloaded_update(
    file_path,
    kind="auto",
    sys_platform=None,
    current_exe=None,
    current_pid=None,
    silent_flag="/SILENT",
):
    """Применяет проверенный файл обновления с учётом ОС (Windows installer/portable, macOS DMG)."""
    plat = (sys_platform or sys.platform).lower()
    resolved_kind = _infer_asset_kind(file_path, "" if kind == "auto" else kind)

    if plat.startswith("win"):
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        if resolved_kind == "portable":
            target_exe = current_exe or sys.executable
            pid = current_pid if current_pid is not None else os.getpid()
            bat_path = create_windows_portable_update_script(target_exe, file_path, pid)
            no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                ["cmd.exe", "/c", bat_path],
                creationflags=creationflags | no_win,
                close_fds=True,
            )
            logger.info("Запущен скрипт обновления портативной версии: %s", bat_path)
            return {"action": "portable_script_launched", "should_quit": True, "path": bat_path}

        cmd = [file_path, silent_flag, "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"]
        subprocess.Popen(cmd, creationflags=creationflags, close_fds=True)
        logger.info("Запущен тихий установщик обновления Windows: %s", cmd)
        return {"action": "installer_launched", "should_quit": True, "path": file_path}

    if plat.startswith("darwin"):
        mount_point = _mount_and_open_macos_dmg(file_path)
        logger.info("Открыт образ обновления macOS DMG: %s (mount=%s)", file_path, mount_point or "open")
        return {
            "action": "dmg_mounted",
            "should_quit": False,
            "path": file_path,
            "mount_point": mount_point,
        }

    subprocess.Popen(
        ["xdg-open", os.path.dirname(os.path.abspath(file_path))],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"action": "folder_opened", "should_quit": False, "path": file_path}


if HAS_PYQT:
    class UpdateCheckWorker(QThread):
        """Фоновый поток для проверки обновлений без блокировки GUI."""
        checked = pyqtSignal(dict, bool)

        def __init__(
            self,
            local_ver,
            local_build,
            manifest_url=DEFAULT_MANIFEST_URL,
            manual=False,
            lang="ru",
            fallback_url=DEFAULT_RELEASES_URL,
            parent=None,
        ):
            super().__init__(parent)
            self.local_ver = local_ver
            self.local_build = local_build
            self.manifest_url = manifest_url
            self.manual = manual
            self.lang = lang
            self.fallback_url = fallback_url

        def run(self):
            if self.isInterruptionRequested():
                return
            info = fetch_update_info(
                self.local_ver,
                self.local_build,
                self.manifest_url,
                lang=self.lang,
                fallback_url=self.fallback_url,
            )
            if not self.isInterruptionRequested():
                self.checked.emit(info, self.manual)


    class UpdateDownloadWorker(QThread):
        """Фоновый поток скачивания, SHA-256 верификации и запуска обновления."""
        status_changed = pyqtSignal(str)
        progress_changed = pyqtSignal(int, int, str)
        finished_download = pyqtSignal(dict)

        def __init__(
            self,
            download_url,
            expected_sha256,
            filename="",
            kind="auto",
            app_version="",
            parent=None,
        ):
            super().__init__(parent)
            self.download_url = download_url
            self.expected_sha256 = expected_sha256
            self.filename = filename
            self.kind = kind
            self.app_version = app_version
            self._cancel_event = threading.Event()

        def cancel(self):
            self._cancel_event.set()
            self.requestInterruption()

        def run(self):
            try:
                path = download_and_verify_update(
                    download_url=self.download_url,
                    expected_sha256=self.expected_sha256,
                    filename=self.filename,
                    progress_callback=lambda dl, tot, name: self.progress_changed.emit(int(dl), int(tot), str(name)),
                    status_callback=lambda st: self.status_changed.emit(str(st)),
                    cancel_event=self._cancel_event,
                    user_agent=f"FBC-GUI/{self.app_version or 'update'}",
                    allowed_hosts=DEFAULT_ALLOWED_UPDATE_HOSTS,
                )
                self.status_changed.emit("installing")
                apply_res = apply_downloaded_update(path, kind=self.kind)
                self.finished_download.emit({
                    "ok": True,
                    "cancelled": False,
                    "error": "",
                    **apply_res,
                })
            except UpdateCancelledError:
                self.finished_download.emit({
                    "ok": False,
                    "cancelled": True,
                    "error": "cancelled",
                })
            except UpdateHashMismatchError as e:
                logger.error("Ошибка проверки SHA-256 обновления: %s", e)
                self.finished_download.emit({
                    "ok": False,
                    "cancelled": False,
                    "hash_mismatch": True,
                    "error": str(e),
                })
            except Exception as e:
                logger.error("Ошибка загрузки/установки обновления: %s", e)
                self.finished_download.emit({
                    "ok": False,
                    "cancelled": False,
                    "error": str(e),
                })

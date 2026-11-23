import json
import ssl
import sys
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal

UPDATE_CHECK_INTERVAL_SEC = 86400


def parse_version_tuple(ver_str):
    """Преобразует строку версии ('1.0.2') в кортеж целых чисел (1, 0, 2)."""
    parts = []
    for chunk in str(ver_str or "0").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def is_newer_version(remote_ver, remote_build, local_ver, local_build):
    """Возвращает True, если удалённая версия/сборка новее локальной."""
    r_ver = parse_version_tuple(remote_ver)
    l_ver = parse_version_tuple(local_ver)
    max_len = max(len(r_ver), len(l_ver))
    r_ver_padded = r_ver + (0,) * (max_len - len(r_ver))
    l_ver_padded = l_ver + (0,) * (max_len - len(l_ver))

    if r_ver_padded != l_ver_padded:
        return r_ver_padded > l_ver_padded

    try:
        r_b = int(remote_build or 0)
    except (TypeError, ValueError):
        r_b = 0
    try:
        l_b = int(local_build or 0)
    except (TypeError, ValueError):
        l_b = 0
    return r_b > l_b


def select_download_url(manifest, platform=None, fallback_url=""):
    """Выбирает URL скачивания для текущей ОС из манифеста version.json."""
    plat = platform or sys.platform
    downloads = manifest.get("downloads")
    if isinstance(downloads, dict):
        if plat == "darwin":
            keys = ("darwin", "macos", "mac")
        elif plat == "win32":
            keys = ("win32", "windows", "win")
        else:
            keys = (plat, "linux")
        for k in keys:
            url = downloads.get(k)
            if isinstance(url, str) and url.strip():
                return url.strip()

    top_url = manifest.get("download_url")
    if isinstance(top_url, str) and top_url.strip():
        return top_url.strip()
    return fallback_url


def _build_ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fetch_update_info(
    local_ver,
    local_build,
    manifest_url,
    timeout=5,
    lang="ru",
    fallback_url=""
):
    """Загружает version.json и проверяет наличие новой версии."""
    result = {
        "has_update": False,
        "version": str(local_ver),
        "build": int(local_build or 0),
        "download_url": fallback_url,
        "changelog": "",
        "error": None,
    }
    try:
        req = urllib.request.Request(
            manifest_url,
            headers={"User-Agent": f"FBC-GUI/{local_ver}"},
        )
        ctx = _build_ssl_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
        manifest = json.loads(raw)
        if not isinstance(manifest, dict):
            raise ValueError("Invalid manifest format")

        remote_ver = str(manifest.get("version", local_ver)).strip()
        remote_build = manifest.get("build", 0)
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
        try:
            result["build"] = int(remote_build or 0)
        except (TypeError, ValueError):
            result["build"] = 0
        result["download_url"] = select_download_url(manifest, fallback_url=fallback_url)
        result["changelog"] = changelog
        result["has_update"] = is_newer_version(remote_ver, remote_build, local_ver, local_build)
    except Exception as e:
        result["error"] = str(e)
    return result


class UpdateCheckWorker(QThread):
    """Фоновый поток для проверки обновлений без блокировки GUI."""
    checked = pyqtSignal(dict, bool)

    def __init__(self, local_ver, local_build, manifest_url, manual=False, lang="ru", fallback_url="", parent=None):
        super().__init__(parent)
        self.local_ver = local_ver
        self.local_build = local_build
        self.manifest_url = manifest_url
        self.manual = manual
        self.lang = lang
        self.fallback_url = fallback_url

    def run(self):
        info = fetch_update_info(
            self.local_ver,
            self.local_build,
            self.manifest_url,
            lang=self.lang,
            fallback_url=self.fallback_url,
        )
        self.checked.emit(info, self.manual)

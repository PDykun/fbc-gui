import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from core.config import atomic_write_text
from core.logger import get_logger
from core.updater import is_safe_http_url, parse_version_tuple

MAX_HTTP_META_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BIN_BYTES = 256 * 1024 * 1024
FBC_HTTP_USER_AGENT = "FBC-GUI/2.9"

try:
    from PyQt6.QtCore import QThread, pyqtSignal
    HAS_PYQT = True
except ImportError:
    QThread = object
    pyqtSignal = None
    HAS_PYQT = False

logger = get_logger("fbc_manager")

FBC_GITHUB_REPO = "rupor-github/fb2cng"
FBC_RELEASES_API = f"https://api.github.com/repos/{FBC_GITHUB_REPO}/releases"
FBC_MIN_VERSION = "2.1.1"
FBC_MAX_MAJOR = 2
FBC_TARGET_VERSION = "2.1.1"
FBC_VERIFIED_CACHE_FILE = "fbc_verified.json"

# Эталонные контрольные суммы официальных бинарников fb2cng (для мгновенной оффлайн-проверки)
KNOWN_FBC_HASHES = {
    ("2.1.1", "darwin-arm64"): {
        "md5": "7b59c71d33402c3103bf8166c72a7f4a",
        "sha256": "500c73124cc63a827bf0fb908a9a53d3f2bbf72f3000c1ca87c656705eb9187e",
    },
    ("2.1.1", "windows-amd64"): {
        "md5": "af2efed9af0ac5b121613e5b4c03a2ac",
        "sha256": "c3b55c4a477c47208330913d6f0a9ec80ebc9d43563b5de3c134f2059cb4bef8",
    },
}

_FBC_VERSION_RE = re.compile(
    r"fbc\s+version\s+v?(\d+(?:\.\d+)+)\s*\((go[^)]*)\)(?:\s*:\s*([0-9a-fA-F]{7,40}))?",
    re.IGNORECASE,
)


class FbcDownloadCancelledError(Exception):
    """Исключение, выбрасываемое при отмене загрузки fb2cng пользователем."""


def get_fbc_binary_name(os_name=None):
    target_os = (os_name or ("windows" if os.name == "nt" else sys.platform)).lower()
    return "fbc.exe" if target_os.startswith("win") else "fbc"


def normalize_platform_arch(sys_platform=None, machine=None):
    """Возвращает нормализованную пару (os_name, arch), например ('darwin', 'arm64') или ('windows', 'amd64')."""
    plat = (sys_platform or sys.platform).lower()
    if plat.startswith("darwin") or plat.startswith("mac"):
        os_name = "darwin"
    elif plat.startswith("win") or plat in ("nt", "cygwin", "msys"):
        os_name = "windows"
    else:
        os_name = "linux"

    raw_arch = (machine or platform.machine() or "").lower().strip()
    if raw_arch in ("arm64", "aarch64"):
        arch = "arm64"
    elif raw_arch in ("x86_64", "amd64", "x64"):
        arch = "amd64"
    elif raw_arch in ("i386", "i686", "x86", "386"):
        arch = "386"
    else:
        arch = raw_arch or "amd64"
    return os_name, arch


def compute_file_hashes(filepath):
    """Вычисляет MD5 и SHA256 файла."""
    h_md5 = hashlib.md5()
    h_sha256 = hashlib.sha256()
    with open(filepath, "rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h_md5.update(chunk)
            h_sha256.update(chunk)
    return {
        "md5": h_md5.hexdigest().lower(),
        "sha256": h_sha256.hexdigest().lower(),
    }


def parse_fbc_version_output(output_text):
    """Разбирает вывод `fbc --version` и проверяет, что это именно fb2cng."""
    if not output_text:
        return None
    m = _FBC_VERSION_RE.search(output_text)
    if not m:
        return None
    return {
        "version": m.group(1).strip(),
        "go_version": m.group(2).strip(),
        "commit": (m.group(3) or "").strip(),
        "raw": output_text.strip(),
    }


def is_compatible_fbc_version(ver_str, min_version=FBC_MIN_VERSION, max_major=FBC_MAX_MAJOR):
    """Проверяет, что версия fb2cng не ниже минимальной и принадлежит совместимой мажорной ветке."""
    if not ver_str:
        return False
    cur = parse_version_tuple(ver_str)
    req = parse_version_tuple(min_version)
    max_len = max(len(cur), len(req))
    cur_pad = cur + (0,) * (max_len - len(cur))
    req_pad = req + (0,) * (max_len - len(req))
    if cur_pad < req_pad:
        return False
    if max_major is not None and cur_pad[0] > int(max_major):
        return False
    return True


def find_local_fbc_candidates(user_data_dir=None, extra_dirs=None, include_system_path=True):
    """Ищет исполняемый файл fbc/fbc.exe по путям ОС (PATH, стандартные каталоги) и в папке данных приложения."""
    bin_name = get_fbc_binary_name()
    raw_candidates = []

    if include_system_path:
        which_hit = shutil.which(bin_name)
        if which_hit:
            raw_candidates.append(which_hit)

        env_path = os.environ.get("PATH", "")
        for p_dir in env_path.split(os.pathsep):
            p_dir = p_dir.strip().strip('"')
            if p_dir:
                raw_candidates.append(os.path.join(p_dir, bin_name))

        # Стандартные пути ОС (на macOS GUI-приложения из Finder часто не получают /opt/homebrew/bin в PATH)
        if sys.platform == "darwin":
            std_dirs = [
                "/opt/homebrew/bin",
                "/usr/local/bin",
                os.path.expanduser("~/.local/bin"),
                os.path.expanduser("~/bin"),
            ]
        elif os.name == "nt":
            std_dirs = [
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "fb2cng"),
                os.path.join(os.environ.get("ProgramFiles", ""), "fb2cng"),
                os.path.join(os.environ.get("ProgramFiles(x86)", ""), "fb2cng"),
            ]
        else:
            std_dirs = [
                "/usr/local/bin",
                "/usr/bin",
                os.path.expanduser("~/.local/bin"),
                os.path.expanduser("~/bin"),
            ]
        for s_dir in std_dirs:
            if s_dir:
                raw_candidates.append(os.path.join(s_dir, bin_name))

    if user_data_dir:
        raw_candidates.append(os.path.join(user_data_dir, bin_name))

    for e_dir in (extra_dirs or ()):
        if e_dir:
            raw_candidates.append(os.path.join(e_dir, bin_name))

    found = []
    seen = set()
    for cand in raw_candidates:
        if not cand or not os.path.isfile(cand):
            continue
        try:
            real = os.path.realpath(cand)
        except OSError:
            real = os.path.abspath(cand)
        if real in seen:
            continue
        seen.add(real)
        found.append(cand)
    return found


def inspect_fbc_binary(filepath, timeout=5):
    """Идентифицирует локальный файл fbc: проверяет `--version`, совместимость версии и вычисляет MD5/SHA256."""
    result = {
        "path": filepath,
        "exists": False,
        "is_fb2cng": False,
        "version": "",
        "go_version": "",
        "commit": "",
        "compatible": False,
        "md5": "",
        "sha256": "",
        "error": "",
    }
    if not filepath or not os.path.isfile(filepath):
        result["error"] = "file_not_found"
        return result

    result["exists"] = True
    try:
        hashes = compute_file_hashes(filepath)
        result["md5"] = hashes["md5"]
        result["sha256"] = hashes["sha256"]
    except Exception as e:
        result["error"] = f"hash_error: {e}"
        return result

    if os.name != "nt" and not os.access(filepath, os.X_OK):
        try:
            os.chmod(filepath, 0o755)
        except OSError:
            pass

    run_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.DEVNULL,
        "text": True,
        "timeout": timeout,
    }
    if os.name == "nt":
        run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = subprocess.run([filepath, "--version"], **run_kwargs)
        combined = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
        parsed = parse_fbc_version_output(combined)
        if not parsed:
            result["error"] = "not_fb2cng"
            return result
        result["is_fb2cng"] = True
        result["version"] = parsed["version"]
        result["go_version"] = parsed["go_version"]
        result["commit"] = parsed["commit"]
        result["compatible"] = is_compatible_fbc_version(parsed["version"])
        if not result["compatible"]:
            result["error"] = "incompatible_version"
        return result
    except subprocess.TimeoutExpired:
        result["error"] = "version_timeout"
        return result
    except Exception as e:
        result["error"] = f"exec_error: {e}"
        return result


def _build_ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _http_get_bytes(url, timeout=10, headers=None, max_bytes=MAX_HTTP_META_BYTES):
    if not is_safe_http_url(url, allow_relative=False, require_https=True):
        raise ValueError(f"Unsupported URL scheme: {url}")
    req_headers = {
        "User-Agent": FBC_HTTP_USER_AGENT,
        "Accept": "application/vnd.github+json",
    }
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    ctx = _build_ssl_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"Response from {url} exceeds size limit ({max_bytes} bytes)")
    return data


def parse_checksums_text(text):
    """Разбирает текстовые файлы контрольных сумм (checksums.txt, *.md5, *.sha256, BSD MD5)."""
    parsed = {}
    if not text:
        return parsed
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Формат BSD: MD5 (filename) = <hex> или SHA256 (filename) = <hex>
        m_bsd = re.match(r"^(MD5|SHA256)\s*\(([^)]+)\)\s*=\s*([0-9a-fA-F]{32}|[0-9a-fA-F]{64})$", line, re.IGNORECASE)
        if m_bsd:
            algo = m_bsd.group(1).lower()
            fname = os.path.basename(m_bsd.group(2).strip()).lower()
            digest = m_bsd.group(3).lower()
            parsed.setdefault(fname, {})[algo] = digest
            continue
        # Формат GNU: <hex>  [*]<filename>
        m_gnu = re.match(r"^([0-9a-fA-F]{32}|[0-9a-fA-F]{64})\s+\*?(.+)$", line)
        if m_gnu:
            digest = m_gnu.group(1).lower()
            fname = os.path.basename(m_gnu.group(2).strip()).lower()
            algo = "md5" if len(digest) == 32 else "sha256"
            parsed.setdefault(fname, {})[algo] = digest
    return parsed


def fetch_github_release(version=FBC_TARGET_VERSION, timeout=10):
    """Загружает метаданные релиза fb2cng из GitHub Releases API."""
    if not version or str(version).lower() == "latest":
        url = f"{FBC_RELEASES_API}/latest"
    else:
        tag = str(version).strip()
        if not tag.startswith("v"):
            tag = f"v{tag}"
        url = f"{FBC_RELEASES_API}/tags/{tag}"
    raw = _http_get_bytes(url, timeout=timeout)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid GitHub release payload")
    return data


def fetch_release_checksums(release_data, timeout=10):
    """Собирает контрольные суммы из поля digest GitHub API и файлов checksums/*.md5/*.sha256 в релизе."""
    checksums = {}
    assets = release_data.get("assets") or []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip()
        low_name = name.lower()
        # Нативный digest из GitHub Releases API (например "sha256:...")
        raw_digest = str(asset.get("digest") or "").strip()
        if ":" in raw_digest:
            algo, hex_val = raw_digest.split(":", 1)
            algo = algo.strip().lower()
            hex_val = hex_val.strip().lower()
            if algo in ("md5", "sha256") and re.fullmatch(r"[0-9a-f]{32}|[0-9a-f]{64}", hex_val):
                checksums.setdefault(low_name, {})[algo] = hex_val

        # Отдельные текстовые файлы контрольных сумм
        if any(tok in low_name for tok in ("checksum", "md5", "sha256", "sha256sums", "md5sums")):
            dl_url = asset.get("browser_download_url")
            if dl_url and int(asset.get("size") or 0) <= 512 * 1024:
                try:
                    txt = _http_get_bytes(dl_url, timeout=timeout).decode("utf-8", errors="replace")
                    for fn, algos in parse_checksums_text(txt).items():
                        checksums.setdefault(fn, {}).update(algos)
                except Exception as e:
                    logger.warning("Не удалось загрузить файл контрольных сумм %s: %s", name, e)
    return checksums


def select_release_asset(release_data, os_name=None, arch=None):
    """Подбирает подходящий архив fb2cng из списка активов GitHub-релиза под текущую ОС и архитектуру."""
    if os_name is None or arch is None:
        det_os, det_arch = normalize_platform_arch()
        os_name = os_name or det_os
        arch = arch or det_arch

    assets = [a for a in (release_data.get("assets") or []) if isinstance(a, dict)]
    archive_assets = [
        a for a in assets
        if str(a.get("name") or "").lower().endswith((".zip", ".tar.gz", ".tgz"))
    ]
    if not archive_assets:
        return None

    os_aliases = {
        "darwin": ("darwin", "macos", "osx"),
        "windows": ("windows", "win"),
        "linux": ("linux",),
    }.get(os_name, (os_name,))

    arch_priority = [arch]
    if os_name == "windows" and arch == "arm64":
        arch_priority.append("amd64")
    elif os_name == "darwin" and arch == "arm64":
        arch_priority.extend(["universal", "amd64"])

    arch_aliases = {
        "arm64": ("arm64", "aarch64"),
        "amd64": ("amd64", "x86_64", "x64"),
        "386": ("386", "x86", "i386"),
        "universal": ("universal", "all"),
    }

    os_token_set = set(os_aliases)
    for pref_arch in arch_priority:
        a_tokens = set(arch_aliases.get(pref_arch, (pref_arch,)))
        for asset in archive_assets:
            low = str(asset.get("name") or "").lower()
            if not low.startswith("fbc"):
                continue
            parts = set(re.split(r"[-_.]+", low))
            if (parts & os_token_set) and (parts & a_tokens):
                return asset

    return None


def _load_verified_cache(user_data_dir):
    if not user_data_dir:
        return {}
    cache_path = os.path.join(user_data_dir, FBC_VERIFIED_CACHE_FILE)
    if not os.path.isfile(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_verified_cache(user_data_dir, entry):
    if not user_data_dir:
        return
    cache_path = os.path.join(user_data_dir, FBC_VERIFIED_CACHE_FILE)
    try:
        os.makedirs(user_data_dir, exist_ok=True)
        cache = _load_verified_cache(user_data_dir)
        entries = cache.get("verified")
        if not isinstance(entries, list):
            entries = []
        # Обновляем или добавляем запись по MD5
        entries = [e for e in entries if isinstance(e, dict) and e.get("md5") != entry.get("md5")]
        entries.insert(0, entry)
        cache["verified"] = entries[:16]
        atomic_write_text(cache_path, json.dumps(cache, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning("Не удалось сохранить кэш проверки fbc: %s", e)


def _matches_verified_cache(user_data_dir, version, md5_hex, sha256_hex):
    cache = _load_verified_cache(user_data_dir)
    for item in cache.get("verified") or []:
        if not isinstance(item, dict):
            continue
        if (
            item.get("version") == version
            and item.get("md5") == md5_hex
            and (not sha256_hex or item.get("sha256") == sha256_hex)
        ):
            return True
    return False


def verify_binary_against_github(info, user_data_dir=None, check_github=True, timeout=8):
    """Проверяет подлинность найденного fbc по эталонным MD5/SHA256, локальному кэшу и GitHub-релизу."""
    if not info.get("is_fb2cng"):
        return {"verified": False, "source": "", "reason": info.get("error") or "not_fb2cng"}
    if not info.get("compatible"):
        return {"verified": False, "source": "", "reason": "incompatible_version"}

    version = info.get("version", "")
    md5_hex = info.get("md5", "").lower()
    sha256_hex = info.get("sha256", "").lower()
    os_name, arch = normalize_platform_arch()
    plat_key = f"{os_name}-{arch}"

    # 1. Проверка по встроенным эталонным MD5/SHA256
    known = KNOWN_FBC_HASHES.get((version, plat_key))
    if known:
        if known.get("md5") == md5_hex and (not known.get("sha256") or known.get("sha256") == sha256_hex):
            return {"verified": True, "source": "known_md5", "reason": ""}
        return {"verified": False, "source": "known_md5", "reason": "hash_mismatch"}

    # 2. Проверка по локальному кэшу ранее проверенных загрузок с GitHub
    if _matches_verified_cache(user_data_dir, version, md5_hex, sha256_hex):
        return {"verified": True, "source": "verified_cache", "reason": ""}

    # 3. Онлайн-проверка против релиза rupor-github/fb2cng на GitHub
    if not check_github:
        return {"verified": True, "source": "local_version_only", "reason": ""}

    try:
        release = fetch_github_release(version=version, timeout=timeout)
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            e.close()
        except Exception:
            pass
        if code == 404:
            return {"verified": False, "source": "github", "reason": "unknown_release"}
        logger.warning("GitHub API недоступен при проверке fbc v%s (HTTP %s)", version, code)
        return {"verified": True, "source": "offline_version_only", "reason": ""}
    except Exception as e:
        logger.warning("Не удалось связаться с GitHub для проверки fbc v%s: %s", version, e)
        return {"verified": True, "source": "offline_version_only", "reason": ""}

    checksums = fetch_release_checksums(release, timeout=timeout)
    bin_name = get_fbc_binary_name(os_name).lower()
    expected_bin = checksums.get(bin_name)
    if expected_bin:
        if expected_bin.get("md5") and expected_bin["md5"] != md5_hex:
            return {"verified": False, "source": "github_md5", "reason": "hash_mismatch"}
        if expected_bin.get("sha256") and expected_bin["sha256"] != sha256_hex:
            return {"verified": False, "source": "github_sha256", "reason": "hash_mismatch"}
        _save_verified_cache(
            user_data_dir,
            {"version": version, "md5": md5_hex, "sha256": sha256_hex, "tag": release.get("tag_name", "")},
        )
        return {"verified": True, "source": "github_checksum", "reason": ""}

    # Релиз v{version} существует на GitHub, но публикует только архивы без отдельного хэша бинарника:
    # допускаем запуск, но НЕ кэшируем хэш как криптографически подтверждённый.
    if select_release_asset(release, os_name=os_name, arch=arch) is not None:
        return {"verified": True, "source": "github_release_unhashed", "reason": ""}

    return {"verified": False, "source": "github", "reason": "no_matching_asset"}


def _copy_stream_limited(src, dst, max_bytes=MAX_ARCHIVE_BIN_BYTES):
    total = 0
    while True:
        chunk = src.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise RuntimeError(f"Extracted binary exceeds size limit ({max_bytes} bytes)")
        dst.write(chunk)


def _extract_fbc_from_archive(archive_path, dest_bin_path, bin_name):
    """Безопасно извлекает исполняемый файл fbc/fbc.exe из .zip или .tar.gz архива с лимитом размера."""
    low = archive_path.lower()
    target_lower = bin_name.lower()

    if low.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            match = None
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                if os.path.basename(name.replace("\\", "/")).lower() == target_lower:
                    match = name
                    break
            if not match:
                raise RuntimeError(f"Binary {bin_name} not found inside archive")
            with zf.open(match, "r") as src, open(dest_bin_path, "wb") as dst:
                _copy_stream_limited(src, dst)
        return dest_bin_path

    if low.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive_path, "r:gz") as tf:
            match = None
            for member in tf.getmembers():
                if member.isfile() and os.path.basename(member.name.replace("\\", "/")).lower() == target_lower:
                    match = member
                    break
            if not match:
                raise RuntimeError(f"Binary {bin_name} not found inside archive")
            src = tf.extractfile(match)
            if src is None:
                raise RuntimeError(f"Failed to extract {bin_name} from archive")
            with src, open(dest_bin_path, "wb") as dst:
                _copy_stream_limited(src, dst)
        return dest_bin_path

    raise RuntimeError(f"Unsupported archive format: {os.path.basename(archive_path)}")


def download_and_install_fbc(
    user_data_dir,
    target_version=FBC_TARGET_VERSION,
    progress_callback=None,
    cancel_event=None,
    timeout=30,
):
    """Скачивает нужную версию fb2cng с GitHub, проверяет хэши и устанавливает в user_data_dir."""
    if cancel_event is not None and cancel_event.is_set():
        raise FbcDownloadCancelledError("Download cancelled")

    os_name, arch = normalize_platform_arch()
    bin_name = get_fbc_binary_name(os_name)

    if progress_callback:
        progress_callback(0, 0, f"Fetching GitHub release v{target_version}...")

    try:
        release = fetch_github_release(version=target_version, timeout=15)
    except urllib.error.HTTPError as e:
        code = e.code
        if code == 404 and target_version != "latest":
            try:
                e.close()
            except Exception:
                pass
            release = fetch_github_release(version="latest", timeout=15)
        else:
            raise

    if cancel_event is not None and cancel_event.is_set():
        raise FbcDownloadCancelledError("Download cancelled")

    asset = select_release_asset(release, os_name=os_name, arch=arch)
    if not asset or not asset.get("browser_download_url"):
        raise RuntimeError(f"No compatible fb2cng asset found for {os_name}-{arch} in {release.get('tag_name')}")

    asset_name = os.path.basename(str(asset["name"]).replace("\\", "/")).strip()
    if not asset_name or asset_name in (".", ".."):
        raise RuntimeError(f"Invalid release asset name: {asset.get('name')}")
    dl_url = str(asset["browser_download_url"])
    if not is_safe_http_url(dl_url, allow_relative=False, require_https=True):
        raise RuntimeError(f"Unsupported download URL scheme: {dl_url}")
    expected_size = int(asset.get("size") or 0)
    checksums = fetch_release_checksums(release, timeout=10)

    os.makedirs(user_data_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fbc_dl_") as tmp_dir:
        archive_path = os.path.join(tmp_dir, asset_name)
        req = urllib.request.Request(dl_url, headers={"User-Agent": FBC_HTTP_USER_AGENT})
        ctx = _build_ssl_context()

        downloaded = 0
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp, open(archive_path, "wb") as out_fh:
            try:
                total = max(0, int(resp.headers.get("Content-Length") or expected_size or 0))
            except (TypeError, ValueError):
                total = max(0, expected_size)
            if total > MAX_ARCHIVE_BIN_BYTES:
                raise RuntimeError(f"Download exceeds size limit ({MAX_ARCHIVE_BIN_BYTES} bytes)")
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise FbcDownloadCancelledError("Download cancelled")
                chunk = resp.read(65536)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MAX_ARCHIVE_BIN_BYTES:
                    raise RuntimeError(f"Download exceeds size limit ({MAX_ARCHIVE_BIN_BYTES} bytes)")
                out_fh.write(chunk)
                if progress_callback:
                    progress_callback(downloaded, total, asset_name)

        # Проверка контрольной суммы скачанного архива (GitHub API digest / checksums)
        archive_hashes = compute_file_hashes(archive_path)
        expected_archive = checksums.get(asset_name.lower()) or {}
        if expected_archive.get("sha256") and expected_archive["sha256"] != archive_hashes["sha256"]:
            raise RuntimeError(
                f"SHA256 mismatch for {asset_name}: expected {expected_archive['sha256']}, got {archive_hashes['sha256']}"
            )
        if expected_archive.get("md5") and expected_archive["md5"] != archive_hashes["md5"]:
            raise RuntimeError(
                f"MD5 mismatch for {asset_name}: expected {expected_archive['md5']}, got {archive_hashes['md5']}"
            )

        fd_tmp, extracted_tmp = tempfile.mkstemp(prefix=f".{bin_name}.", suffix=".tmp", dir=user_data_dir)
        os.close(fd_tmp)
        try:
            _extract_fbc_from_archive(archive_path, extracted_tmp, bin_name)
            if os.name != "nt":
                os.chmod(extracted_tmp, 0o755)

            info = inspect_fbc_binary(extracted_tmp)
            if not info.get("is_fb2cng") or not info.get("compatible"):
                raise RuntimeError(
                    f"Downloaded binary failed verification: {info.get('error') or info.get('version')}"
                )

            # Проверка бинарника против эталонных MD5/SHA256 (если заданы для этой версии и платформы)
            known = KNOWN_FBC_HASHES.get((info["version"], f"{os_name}-{arch}"))
            if known:
                if known.get("md5") and known["md5"] != info["md5"]:
                    raise RuntimeError("Downloaded fbc binary MD5 mismatch")
                if known.get("sha256") and known["sha256"] != info["sha256"]:
                    raise RuntimeError("Downloaded fbc binary SHA256 mismatch")

            final_path = os.path.join(user_data_dir, bin_name)
            os.replace(extracted_tmp, final_path)
            if os.name != "nt":
                os.chmod(final_path, 0o755)
        except Exception:
            if os.path.exists(extracted_tmp):
                try:
                    os.remove(extracted_tmp)
                except OSError:
                    pass
            raise

    _save_verified_cache(
        user_data_dir,
        {
            "version": info["version"],
            "md5": info["md5"],
            "sha256": info["sha256"],
            "tag": release.get("tag_name", f"v{info['version']}"),
            "asset": asset_name,
        },
    )
    logger.info(
        "Установлен fb2cng v%s (%s, md5=%s) из GitHub (%s)",
        info["version"], final_path, info["md5"], asset_name,
    )
    return {
        "ok": True,
        "path": final_path,
        "version": info["version"],
        "md5": info["md5"],
        "sha256": info["sha256"],
        "source": "github_download",
        "downloaded": True,
        "reason": "",
        "error": "",
    }


def resolve_local_fbc(user_data_dir=None, extra_dirs=None, include_system_path=True):
    """Быстрый оффлайн-поиск совместимого локального fbc для первичной инициализации."""
    for cand in find_local_fbc_candidates(
        user_data_dir=user_data_dir,
        extra_dirs=extra_dirs,
        include_system_path=include_system_path,
    ):
        info = inspect_fbc_binary(cand)
        if info.get("is_fb2cng") and info.get("compatible"):
            ver_res = verify_binary_against_github(info, user_data_dir=user_data_dir, check_github=False)
            if ver_res.get("verified"):
                return {
                    "path": cand,
                    "version": info["version"],
                    "md5": info["md5"],
                    "sha256": info["sha256"],
                    "source": ver_res.get("source", ""),
                }
    return None


def ensure_fbc_available(
    user_data_dir,
    target_version=FBC_TARGET_VERSION,
    allow_download=True,
    check_github=True,
    include_system_path=True,
    extra_dirs=None,
    progress_callback=None,
    status_callback=None,
    cancel_event=None,
):
    """Ищет fbc в системе, проверяет версию и MD5/SHA256 с GitHub, а при отсутствии или несоответствии — скачивает."""
    if status_callback:
        status_callback("searching")

    candidates = find_local_fbc_candidates(
        user_data_dir=user_data_dir,
        extra_dirs=extra_dirs,
        include_system_path=include_system_path,
    )
    last_reason = "not_found"
    rejected_details = []

    for cand in candidates:
        if cancel_event is not None and cancel_event.is_set():
            raise FbcDownloadCancelledError("Cancelled")
        info = inspect_fbc_binary(cand)
        if not info.get("is_fb2cng"):
            last_reason = info.get("error") or "not_fb2cng"
            rejected_details.append((cand, last_reason))
            logger.info("Пропущен кандидат %s: %s", cand, last_reason)
            continue
        if not info.get("compatible"):
            last_reason = "incompatible_version"
            rejected_details.append((cand, f"version={info.get('version')}"))
            logger.info("Несовместимая версия fbc в %s: v%s (нужна >= %s)", cand, info.get("version"), FBC_MIN_VERSION)
            continue

        if status_callback:
            status_callback("verifying")

        ver_res = verify_binary_against_github(info, user_data_dir=user_data_dir, check_github=check_github)
        if ver_res.get("verified"):
            logger.info(
                "Обнаружен и проверен fb2cng v%s: %s (md5=%s, source=%s)",
                info["version"], cand, info["md5"], ver_res.get("source"),
            )
            return {
                "ok": True,
                "path": cand,
                "version": info["version"],
                "md5": info["md5"],
                "sha256": info["sha256"],
                "source": ver_res.get("source", ""),
                "downloaded": False,
                "reason": "",
                "error": "",
            }

        last_reason = ver_res.get("reason") or "verification_failed"
        rejected_details.append((cand, last_reason))
        logger.warning("Кандидат %s не прошёл проверку (%s)", cand, last_reason)

    if not allow_download:
        return {
            "ok": False,
            "path": "",
            "version": "",
            "md5": "",
            "sha256": "",
            "source": "",
            "downloaded": False,
            "reason": last_reason,
            "error": last_reason,
            "rejected": rejected_details,
        }

    if status_callback:
        status_callback(f"downloading:{last_reason}")

    try:
        res = download_and_install_fbc(
            user_data_dir=user_data_dir,
            target_version=target_version,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )
        res["reason"] = last_reason
        return res
    except FbcDownloadCancelledError:
        return {
            "ok": False,
            "path": "",
            "version": "",
            "md5": "",
            "sha256": "",
            "source": "",
            "downloaded": False,
            "cancelled": True,
            "reason": last_reason,
            "error": "cancelled",
        }
    except Exception as e:
        logger.error("Не удалось скачать fb2cng с GitHub: %s", e)
        return {
            "ok": False,
            "path": "",
            "version": "",
            "md5": "",
            "sha256": "",
            "source": "",
            "downloaded": False,
            "reason": last_reason,
            "error": str(e),
        }


if HAS_PYQT:
    class FbcEnsureWorker(QThread):
        """Фоновый поток проверки и (при необходимости) загрузки fb2cng с GitHub."""

        status_changed = pyqtSignal(str)
        progress_changed = pyqtSignal(int, int, str)
        finished_check = pyqtSignal(dict)

        def __init__(self, user_data_dir, target_version=FBC_TARGET_VERSION, allow_download=True, parent=None):
            super().__init__(parent)
            self.user_data_dir = user_data_dir
            self.target_version = target_version
            self.allow_download = allow_download
            self._cancel_event = threading.Event()

        def cancel(self):
            self._cancel_event.set()
            self.requestInterruption()

        def run(self):
            res = ensure_fbc_available(
                user_data_dir=self.user_data_dir,
                target_version=self.target_version,
                allow_download=self.allow_download,
                check_github=True,
                progress_callback=lambda dl, tot, name: self.progress_changed.emit(int(dl), int(tot), str(name)),
                status_callback=lambda st: self.status_changed.emit(str(st)),
                cancel_event=self._cancel_event,
            )
            self.finished_check.emit(res)

import io
import os
import re
import stat
import sys
import json
import shutil
import tempfile
import textwrap
import subprocess

try:
    from ruamel.yaml import YAML
except ModuleNotFoundError:
    _venv_lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".venv", "lib")
    if os.path.isdir(_venv_lib):
        for _py_dir in sorted(os.listdir(_venv_lib)):
            _sp = os.path.join(_venv_lib, _py_dir, "site-packages")
            if os.path.isdir(_sp) and _sp not in sys.path:
                sys.path.append(_sp)
    from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import LiteralScalarString, DoubleQuotedScalarString

try:
    import keyring
    HAS_KEYRING = True
except ImportError:
    keyring = None
    HAS_KEYRING = False

KEYRING_SERVICE = "FBC_GUI"
KEYRING_SMTP_ACCOUNT = "smtp_password"
KEYRING_GOOGLE_BOOKS_ACCOUNT = "google_books_api_key"
KEYRING_OPDS_ACCOUNT = "opds_password"
_KEYCHAIN_ACCOUNT_RE = re.compile(r"^[a-z0-9_]+$")

from core.i18n import LOCALE, get_theme_choices
from core.fb2_processor import (
    DEFAULT_FILENAME_TOKENS, DEFAULT_TITLE_TOKENS, LEGACY_DEFAULT_FILENAME_TOKENS,
    build_fbc_output_name_template
)
from core.logger import get_logger
from core.metadata_lookup import DEFAULT_ENABLED_PROVIDERS

logger = get_logger("config")

DEFAULT_OUTPUT_FORMAT = "epub3"

DEFAULT_OUTPUT_NAME_TEMPLATE = build_fbc_output_name_template(DEFAULT_FILENAME_TOKENS)

DEFAULT_TITLE_META_TEMPLATE = build_fbc_output_name_template(
    DEFAULT_FILENAME_TOKENS,
    for_metadata_title=True,
)

LEGACY_THEME_MAP = {
    "Tuck Midnight": "Golden",
    "Midnight": "Golden",
    "Light": "Golden",
    "macOS Light": "Golden",
    "macOS Dark": "Golden",
    "Nordic Slate": "Modern",
    "Авто": "Auto"
}


DEVICE_PROFILES = {
    "kindle": {
        "output_format": "kfx",
        "screen_width": "1264",
        "screen_height": "1680",
        "screen_dpi": "300",
        "footnotes_mode": "float",
        "remove_transparency": "false",
        "rasterize_svg": "false",
        "kfx_compression": "none",
        "grayscale": "none",
        "image_color_profile": "eink_bw",
    },
    "kindle_scribe_2024": {
        "output_format": "kfx",
        "screen_width": "1860",
        "screen_height": "2480",
        "screen_dpi": "300",
        "footnotes_mode": "float",
        "remove_transparency": "false",
        "rasterize_svg": "false",
        "kfx_compression": "none",
        "grayscale": "none",
        "image_color_profile": "eink_bw",
        "fit_to_screen": "true",
        "cover_resize": "keepAR",
        "optimize_images": "true",
        "jpeg_quality_level": "95",
    },
    "kindle_scribe_2025": {
        "output_format": "kfx",
        "screen_width": "1980",
        "screen_height": "2640",
        "screen_dpi": "300",
        "footnotes_mode": "float",
        "remove_transparency": "false",
        "rasterize_svg": "false",
        "kfx_compression": "none",
        "grayscale": "none",
        "image_color_profile": "eink_bw",
        "fit_to_screen": "true",
        "cover_resize": "keepAR",
        "optimize_images": "true",
        "jpeg_quality_level": "95",
    },
    "kindle_scribe_colorsoft": {
        "output_format": "kfx",
        "screen_width": "1980",
        "screen_height": "2640",
        "screen_dpi": "300",
        "footnotes_mode": "float",
        "remove_transparency": "false",
        "rasterize_svg": "false",
        "kfx_compression": "none",
        "grayscale": "none",
        "image_color_profile": "eink_kaleido3",
        "fit_to_screen": "true",
        "cover_resize": "keepAR",
        "optimize_images": "true",
        "jpeg_quality_level": "95",
    },
    "kobo": {
        "output_format": "kepub3",
        "screen_width": "1264",
        "screen_height": "1680",
        "screen_dpi": "300",
        "footnotes_mode": "float",
        "grayscale": "none",
        "image_color_profile": "eink_kaleido3",
        "fit_to_screen": "true",
        "cover_resize": "keepAR",
        "optimize_images": "true",
        "jpeg_quality_level": "95",
    },
    "pocketbook": {
        "output_format": "epub3",
        "screen_width": "1404",
        "screen_height": "1872",
        "screen_dpi": "300",
        "footnotes_mode": "float",
        "grayscale": "none",
        "image_color_profile": "eink_bw",
        "fit_to_screen": "true",
        "cover_resize": "keepAR",
        "optimize_images": "true",
        "jpeg_quality_level": "95",
    },
    "onyx_boox": {
        "output_format": "epub3",
        "screen_width": "1860",
        "screen_height": "2480",
        "screen_dpi": "300",
        "footnotes_mode": "float",
        "grayscale": "none",
        "image_color_profile": "eink_bw",
        "fit_to_screen": "true",
        "cover_resize": "keepAR",
        "optimize_images": "true",
        "jpeg_quality_level": "95",
    },
    "remarkable": {
        "output_format": "pdf",
        "screen_width": "1620",
        "screen_height": "2160",
        "screen_dpi": "229",
        "footnotes_mode": "floatRenumbered",
        "grayscale": "none",
        "image_color_profile": "eink_gallery3",
        "rasterize_svg": "false",
        "fit_to_screen": "true",
        "cover_resize": "keepAR",
        "optimize_images": "true",
        "jpeg_quality_level": "95",
    },
    "pdf": {
        "output_format": "pdf",
        "screen_width": "1748",
        "screen_height": "2480",
        "screen_dpi": "300",
        "footnotes_mode": "floatRenumbered",
        "image_color_profile": "none",
    },
}


def get_default_app_settings():
    return {
        "theme": "Modern",
        "theme_family": "Modern",
        "theme_mode": "auto",
        "language": "",
        "active_user_preset": "",
        "device_profile": "custom",
        "output_format": DEFAULT_OUTPUT_FORMAT,
        "screen_width": "1264",
        "screen_height": "1680",
        "screen_dpi": "300",
        "footnotes_mode": "float",
        "insert_soft_hyphen": "false",
        "file_name_transliterate": "false",
        "meta_transliterate": "false",
        "dropcaps_enable": "true",
        "text_transform_speech": "false",
        "text_transform_dashes": "false",
        "text_transform_dialogue": "false",
        "annotation_enable": "true",
        "annotation_in_toc": "false",
        "toc_type": "normal",
        "toc_page_placement": "after",
        "toc_include_untitled": "false",
        "page_map_enable": "true",
        "page_map_size": "2300",
        "page_map_adobe_de": "false",
        "fix_zip": "false",
        "open_from_cover": "true",
        "cover_generate": "false",
        "no_cover": "false",
        "skip_existing": "false",
        "filename_mode": "default",
        "filename_tokens": [dict(t) for t in DEFAULT_FILENAME_TOKENS],
        "title_template_mode": "filename",
        "title_template_tokens": [dict(t) for t in DEFAULT_TITLE_TOKENS],
        "azw3_compression": "standard",
        "kfx_compression": "none",
        "azw3_apnx": "none",
        "markdown_images": "placeholder",
        "convert_workers": "auto",
        "save_mode": "source",
        "custom_output_dir": os.path.expanduser("~"),
        "raster_format": "auto",
        "rasterize_svg": "false",
        "remove_transparency": "false",
        "image_scale_factor": "1.0",
        "optimize_images": "true",
        "jpeg_quality_level": "95",
        "baseline_jpeg": "false",
        "fit_to_screen": "false",
        "grayscale": "none",
        "image_color_profile": "none",
        "preview_simulate_eink": "true",
        "cover_resize": "keepAR",
        "email_auto_send": "false",
        "smtp_host": "",
        "smtp_port": "465",
        "smtp_security": "ssl",
        "smtp_user": "",
        "smtp_password": "",
        "email_from": "",
        "email_to": "",
        "device_sync_mode": "mtp",
        "device_sync_target": "documents/books",
        "device_sync_ignore_removals": "true",
        "metadata_providers": list(DEFAULT_ENABLED_PROVIDERS),
        "google_books_api_key": "",
        "opds_url": "",
        "opds_username": "",
        "opds_password": "",
        "tray_enabled": "false",
        "tray_minimize_on_close": "false",
        "tray_hide_dock_macos": "false",
        "autostart_enabled": "false",
        "watch_notifications_enabled": "true",
        "watch_folders": [],
        "library_enabled": "false",
        "library_inpx_path": "",
        "last_update_check": 0
    }


def _create_yaml():
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    return yaml


def _insert_key_after(mapping, key, val, after_key=None, only_if_missing=False):
    """Устанавливает или вставляет ключ в CommentedMap после after_key, сохраняя порядок и комментарии."""
    if key in mapping:
        if not only_if_missing:
            mapping[key] = val
        return
    if after_key and after_key in mapping:
        idx = list(mapping.keys()).index(after_key) + 1
        mapping.insert(idx, key, val)
    else:
        mapping[key] = val


def _ensure_subblock(parent_map, block_name, entries, before_keys=("footnotes",)):
    """Гарантирует наличие подсекции block_name внутри parent_map (CommentedMap)."""
    existing = parent_map.get(block_name)
    if isinstance(existing, CommentedMap):
        for k, v in entries:
            if k not in existing:
                existing[k] = v
        return existing

    sub = CommentedMap()
    for k, v in entries:
        sub[k] = v

    insert_idx = None
    keys_list = list(parent_map.keys())
    for bk in before_keys:
        if bk in keys_list:
            insert_idx = keys_list.index(bk)
            break
    if insert_idx is not None:
        parent_map.insert(insert_idx, block_name, sub)
    else:
        parent_map[block_name] = sub
    return sub


def _yaml_val_to_str(val):
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)


def _to_bool(val, default=False):
    if isinstance(val, bool):
        return val
    if val is None:
        return default
    return str(val).strip().lower() in ("true", "1", "yes")


def _to_int(val, default=95):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def atomic_write_text(filepath, text, encoding="utf-8"):
    """Атомарно записывает текст в файл через временный файл в той же директории и os.replace()."""
    abs_path = os.path.abspath(filepath)
    parent_dir = os.path.dirname(abs_path) or "."
    os.makedirs(parent_dir, exist_ok=True)
    target_mode = None
    if os.name != "nt":
        if os.path.basename(abs_path) == "settings.json":
            target_mode = 0o600
        else:
            try:
                target_mode = stat.S_IMODE(os.stat(abs_path).st_mode)
            except OSError:
                target_mode = 0o644
    fd, tmp_path = tempfile.mkstemp(prefix=".fbc_tmp_", suffix=".tmp", dir=parent_dir)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        if target_mode is not None:
            try:
                os.chmod(tmp_path, target_mode)
            except OSError:
                pass
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def _normalize_stylesheet_path(cfg_path, css_path):
    """Возвращает относительное имя CSS, если он лежит рядом с config.yaml, для переносимости конфига."""
    if not css_path:
        return "ebook_styles.css"
    try:
        if cfg_path and os.path.dirname(os.path.abspath(cfg_path)) == os.path.dirname(os.path.abspath(css_path)):
            return os.path.basename(css_path)
    except OSError:
        pass
    return str(css_path).replace("\\", "/")


def migrate_fbc_config_211(cfg_path, css_path):
    """Обновляет существующий config.yaml для совместимости с fb2cng 2.1.1."""
    if not os.path.exists(cfg_path):
        return
    try:
        yaml = _create_yaml()
        with open(cfg_path, "r", encoding="utf-8") as f:
            orig_text = f.read()
        data = yaml.load(io.StringIO(orig_text))
        if not isinstance(data, CommentedMap):
            return

        doc = data.get("document")
        if not isinstance(doc, CommentedMap):
            doc = CommentedMap()
            data["document"] = doc

        md_val = "placeholder"
        images = doc.get("images")
        if isinstance(images, CommentedMap):
            # 1. Миграция 1.9.2 полей (если старый конфиг)
            _insert_key_after(images, "rasterize_svg", False, "remove_transparency", only_if_missing=True)
            _insert_key_after(images, "raster_format", "auto", "rasterize_svg", only_if_missing=True)

            # 2. Перенос document.images.markdown -> document.markdown.images (breaking change в 2.1.1)
            if "markdown" in images:
                raw_md = images.pop("markdown")
                if raw_md is not None:
                    md_val = str(raw_md)
                images.ca.items.pop("markdown", None)

            # 3. Новые опции обработки изображений 2.1.1
            _insert_key_after(images, "fit_to_screen", False, "scale_factor", only_if_missing=True)
            _insert_key_after(images, "baseline_jpeg", False, "fit_to_screen", only_if_missing=True)
            _insert_key_after(images, "grayscale", "none", "baseline_jpeg", only_if_missing=True)

        # 4. Секции форматов markdown, kfx и azw3
        _ensure_subblock(doc, "markdown", [("images", md_val)], before_keys=("kfx", "azw3", "footnotes"))
        _ensure_subblock(doc, "kfx", [("compression", "none")], before_keys=("azw3", "footnotes"))
        _ensure_subblock(doc, "azw3", [("compression", "standard"), ("apnx", "none")], before_keys=("footnotes",))

        # 5. Исправление некорректного экранирования обратного слеша в output_name_template
        if "output_name_template" in doc and isinstance(doc["output_name_template"], str):
            raw_tpl = doc["output_name_template"]
            fixed_tpl = raw_tpl.replace('replace "\\" ', 'replace "\\\\" ')
            if fixed_tpl != raw_tpl:
                doc["output_name_template"] = LiteralScalarString(fixed_tpl)

        css_norm = _normalize_stylesheet_path(cfg_path, css_path)
        if "stylesheet_path" in doc and str(doc["stylesheet_path"]) != css_norm:
            doc["stylesheet_path"] = DoubleQuotedScalarString(css_norm)

        buf = io.StringIO()
        yaml.dump(data, buf)
        new_text = buf.getvalue()
        if new_text != orig_text:
            atomic_write_text(cfg_path, new_text)
    except Exception as e:
        logger.exception("Ошибка миграции config.yaml: %s", e)


migrate_fbc_config_192 = migrate_fbc_config_211


def _save_secret_secure(account, secret):
    """Сохраняет секрет в keyring или системной связке ключей macOS (без передачи значения в argv)."""
    if not isinstance(account, str) or not _KEYCHAIN_ACCOUNT_RE.fullmatch(account):
        logger.warning("Отклонён некорректный идентификатор аккаунта секрета: %r", account)
        return False
    if HAS_KEYRING:
        try:
            if secret:
                keyring.set_password(KEYRING_SERVICE, account, secret)
            else:
                try:
                    keyring.delete_password(KEYRING_SERVICE, account)
                except Exception as e:
                    logger.debug("Не удалось удалить пароль из keyring для %s: %s", account, e)
            return True
        except Exception as e:
            logger.warning("Ошибка сохранения секрета (%s) в keyring: %s", account, e)
            return False
    if sys.platform == "darwin":
        try:
            if secret:
                sec_hex = str(secret).encode("utf-8").hex()
                cmd_line = (
                    f'add-generic-password -U -a "{account}" '
                    f'-s "{KEYRING_SERVICE}" -X {sec_hex}\n'
                )
                res = subprocess.run(
                    ["security", "-i"],
                    input=cmd_line,
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                stderr_txt = (res.stderr or "").strip()
                if stderr_txt and "error" in stderr_txt.lower():
                    logger.warning("security -i вернул ошибку при сохранении секрета (%s): %s", account, stderr_txt)
                    return False
            else:
                subprocess.run(
                    ["security", "delete-generic-password", "-a", account, "-s", KEYRING_SERVICE],
                    capture_output=True,
                    timeout=5,
                )
            return True
        except subprocess.TimeoutExpired:
            logger.warning("Таймаут сохранения секрета (%s) в Keychain macOS", account)
            return False
        except Exception as e:
            logger.warning("Ошибка сохранения секрета (%s) в Keychain macOS: %s", account, e)
            return False
    return False


def _load_secret_secure(account):
    """Загружает секрет из keyring или системной связке ключей macOS."""
    if not isinstance(account, str) or not _KEYCHAIN_ACCOUNT_RE.fullmatch(account):
        return None
    if HAS_KEYRING:
        try:
            return keyring.get_password(KEYRING_SERVICE, account) or ""
        except Exception:
            return None
    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["security", "find-generic-password", "-a", account, "-s", KEYRING_SERVICE, "-w"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                return res.stdout.rstrip("\r\n")
        except subprocess.TimeoutExpired:
            logger.warning("Таймаут чтения секрета (%s) из Keychain macOS", account)
        except Exception as e:
            logger.debug("Ошибка чтения секрета из macOS Keychain для %s: %s", account, e)
    return None


def _save_smtp_password_secure(password):
    """Сохраняет SMTP-пароль в keyring или системной связке ключей macOS (без передачи пароля в argv)."""
    return _save_secret_secure(KEYRING_SMTP_ACCOUNT, password)


def _load_smtp_password_secure():
    """Загружает SMTP-пароль из keyring или системной связке ключей macOS."""
    return _load_secret_secure(KEYRING_SMTP_ACCOUNT)


def _save_google_books_key_secure(api_key):
    """Сохраняет API-ключ Google Books в keyring или системной связке ключей macOS."""
    return _save_secret_secure(KEYRING_GOOGLE_BOOKS_ACCOUNT, api_key)


def _load_google_books_key_secure():
    """Загружает API-ключ Google Books из keyring или системной связке ключей macOS."""
    return _load_secret_secure(KEYRING_GOOGLE_BOOKS_ACCOUNT)


def _save_opds_password_secure(password):
    """Сохраняет пароль OPDS в keyring или системной связке ключей macOS."""
    return _save_secret_secure(KEYRING_OPDS_ACCOUNT, password)


def _load_opds_password_secure():
    """Загружает пароль OPDS из keyring или системной связке ключей macOS."""
    return _load_secret_secure(KEYRING_OPDS_ACCOUNT)


def is_secure_password_storage_available():
    """Проверяет, доступно ли системное защищённое хранилище для секретов (keyring или Keychain macOS)."""
    if HAS_KEYRING and keyring is not None:
        try:
            kr = keyring.get_keyring()
            kr_name = type(kr).__name__.lower()
            if "fail" not in kr_name and "null" not in kr_name:
                return True
        except Exception as e:
            logger.debug("Проверка доступности keyring завершилась ошибкой: %s", e)
    if sys.platform == "darwin":
        return True
    return False


_LAST_PLAINTEXT_SECRET_FIELDS = ()


def get_last_plaintext_secret_fields():
    """Возвращает кортеж имён секретных полей, которые не удалось сохранить в защищённое хранилище (оставлены только в памяти сессии)."""
    return _LAST_PLAINTEXT_SECRET_FIELDS


def save_app_settings(settings_path, app_settings):
    global _LAST_PLAINTEXT_SECRET_FIELDS
    data_to_save = dict(app_settings)
    unsaved_fields = []
    for field_name, saver_fn, label in (
        ("smtp_password", _save_smtp_password_secure, "SMTP-пароль"),
        ("google_books_api_key", _save_google_books_key_secure, "API-ключ Google Books"),
        ("opds_password", _save_opds_password_secure, "пароль OPDS"),
    ):
        secret_val = data_to_save.get(field_name, "")
        saved_secure = saver_fn(secret_val)
        # Никогда не записываем секреты в открытом виде в settings.json
        data_to_save[field_name] = ""
        if not saved_secure and secret_val:
            unsaved_fields.append(field_name)
            logger.warning(
                "Защищённое хранилище секретов (keyring) недоступно; %s оставлен только в памяти сессии и не записан в settings.json",
                label,
            )
    _LAST_PLAINTEXT_SECRET_FIELDS = tuple(unsaved_fields)
    try:
        payload = json.dumps(data_to_save, ensure_ascii=False, indent=2)
        atomic_write_text(settings_path, payload)
    except Exception as e:
        logger.exception("Ошибка сохранения settings.json (%s): %s", settings_path, e)


def load_app_settings(settings_path, app_settings):
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                app_settings.update(data)
            else:
                raise ValueError("settings.json root is not a JSON object")
        except Exception as e:
            logger.warning("Повреждённый settings.json (%s): %s; создаётся резервная копия", settings_path, e)
            backup_path = f"{settings_path}.bak"
            try:
                shutil.copy2(settings_path, backup_path)
            except Exception as bak_err:
                logger.warning("Не удалось создать резервную копию %s: %s", backup_path, bak_err)
        changed = False
        legacy_pwd = app_settings.get("smtp_password", "")
        if legacy_pwd:
            if _save_smtp_password_secure(legacy_pwd):
                changed = True
        else:
            sec_pwd = _load_smtp_password_secure()
            if sec_pwd:
                app_settings["smtp_password"] = sec_pwd
        legacy_gb = app_settings.get("google_books_api_key", "")
        if legacy_gb:
            if _save_google_books_key_secure(legacy_gb):
                changed = True
        else:
            sec_gb = _load_google_books_key_secure()
            if sec_gb:
                app_settings["google_books_api_key"] = sec_gb
        legacy_opds = app_settings.get("opds_password", "")
        if legacy_opds:
            if _save_opds_password_secure(legacy_opds):
                changed = True
        else:
            sec_opds = _load_opds_password_secure()
            if sec_opds:
                app_settings["opds_password"] = sec_opds
        raw_provs = app_settings.get("metadata_providers")
        if not isinstance(raw_provs, list):
            app_settings["metadata_providers"] = list(DEFAULT_ENABLED_PROVIDERS)
            changed = True
        raw_watch = app_settings.get("watch_folders")
        if not isinstance(raw_watch, list):
            app_settings["watch_folders"] = []
            changed = True
        if (
            app_settings.get("filename_mode", "default") == "default"
            and app_settings.get("filename_tokens") == LEGACY_DEFAULT_FILENAME_TOKENS
        ):
            app_settings["filename_tokens"] = [dict(t) for t in DEFAULT_FILENAME_TOKENS]
            changed = True
        if app_settings.get("title_template_mode") not in ("filename", "custom"):
            app_settings["title_template_mode"] = "filename"
            changed = True
        valid_keys = {val for _, val in get_theme_choices()}
        raw_theme = app_settings.get("theme", "Modern")
        if raw_theme in ("Auto", "Авто"):
            if app_settings.get("theme_mode") not in ("auto", "light", "dark"):
                app_settings["theme_mode"] = "auto"
            fam = app_settings.get("theme_family", "Modern")
            app_settings["theme"] = fam if fam in valid_keys else "Modern"
            changed = True
        elif raw_theme in ("Midnight", "macOS Dark", "Tuck Midnight") and "theme_mode" not in app_settings:
            app_settings["theme_mode"] = "dark"
            app_settings["theme_family"] = "Golden"
            changed = True
        elif raw_theme in ("Light", "macOS Light") and "theme_mode" not in app_settings:
            app_settings["theme_mode"] = "light"
            app_settings["theme_family"] = "Golden"
            changed = True
        elif raw_theme == "Nordic Slate":
            app_settings["theme_family"] = "Modern"
            changed = True

        mapped_theme = LEGACY_THEME_MAP.get(app_settings.get("theme", "Modern"), app_settings.get("theme", "Modern"))
        if mapped_theme not in valid_keys:
            mapped_theme = app_settings.get("theme_family") if app_settings.get("theme_family") in valid_keys else "Modern"
        if mapped_theme != app_settings.get("theme"):
            app_settings["theme"] = mapped_theme
            changed = True

        if app_settings.get("theme_family") not in valid_keys:
            app_settings["theme_family"] = mapped_theme if mapped_theme in valid_keys else "Modern"
            changed = True
        if app_settings.get("theme_mode") not in ("auto", "light", "dark"):
            app_settings["theme_mode"] = "auto"
            changed = True

        available_langs = {code for _, code in LOCALE.discover_locales()}
        lang = app_settings.get("language", "")
        if not lang or lang not in available_langs:
            app_settings["language"] = LOCALE.detect_system_language()
            changed = True

        if changed:
            save_app_settings(settings_path, app_settings)
    else:
        app_settings["language"] = LOCALE.detect_system_language()
        save_app_settings(settings_path, app_settings)


def sync_settings_from_fbc_config(fbc_config_path, app_settings):
    """Считывает актуальные параметры из config.yaml (fb2cng 2.1.1)."""
    if not os.path.exists(fbc_config_path):
        return
    try:
        yaml = _create_yaml()
        with open(fbc_config_path, "r", encoding="utf-8") as f:
            data = yaml.load(f)
        if not isinstance(data, dict):
            return

        doc = data.get("document") or {}
        if not isinstance(doc, dict):
            return
        images = doc.get("images") or {}
        if not isinstance(images, dict):
            images = {}

        simple_map = [
            ("raster_format", "raster_format"),
            ("rasterize_svg", "rasterize_svg"),
            ("remove_transparency", "remove_transparency"),
            ("scale_factor", "image_scale_factor"),
            ("optimize", "optimize_images"),
            ("jpeg_quality_level", "jpeg_quality_level"),
            ("fit_to_screen", "fit_to_screen"),
            ("baseline_jpeg", "baseline_jpeg"),
            ("grayscale", "grayscale"),
        ]
        for yaml_key, app_key in simple_map:
            if yaml_key in images and images[yaml_key] is not None:
                app_settings[app_key] = _yaml_val_to_str(images[yaml_key])

        cover = images.get("cover")
        if isinstance(cover, dict):
            if cover.get("resize") is not None:
                app_settings["cover_resize"] = _yaml_val_to_str(cover["resize"])
            if cover.get("generate") is not None:
                app_settings["cover_generate"] = _yaml_val_to_str(cover["generate"])

        screen = images.get("screen")
        if isinstance(screen, dict):
            for sk, ak in (("width", "screen_width"), ("height", "screen_height"), ("dpi", "screen_dpi")):
                if screen.get(sk) is not None:
                    app_settings[ak] = _yaml_val_to_str(screen[sk])

        for doc_key, app_key in (
            ("insert_soft_hyphen", "insert_soft_hyphen"),
            ("file_name_transliterate", "file_name_transliterate"),
            ("open_from_cover", "open_from_cover"),
            ("fix_zip", "fix_zip"),
            ("toc_type", "toc_type"),
        ):
            if doc_key in doc and doc[doc_key] is not None:
                app_settings[app_key] = _yaml_val_to_str(doc[doc_key])

        for block_name, key, app_key in [
            ("azw3", "compression", "azw3_compression"),
            ("azw3", "apnx", "azw3_apnx"),
            ("kfx", "compression", "kfx_compression"),
            ("markdown", "images", "markdown_images"),
            ("footnotes", "mode", "footnotes_mode"),
            ("dropcaps", "enable", "dropcaps_enable"),
            ("metainformation", "transliterate", "meta_transliterate"),
            ("annotation", "enable", "annotation_enable"),
            ("annotation", "in_toc", "annotation_in_toc"),
            ("toc_page", "placement", "toc_page_placement"),
            ("toc_page", "include_chapters_without_title", "toc_include_untitled"),
            ("page_map", "enable", "page_map_enable"),
            ("page_map", "size", "page_map_size"),
            ("page_map", "adobe_de", "page_map_adobe_de"),
        ]:
            blk = doc.get(block_name)
            if isinstance(blk, dict) and blk.get(key) is not None:
                app_settings[app_key] = _yaml_val_to_str(blk[key])

        tt = doc.get("text_transformations")
        if isinstance(tt, dict):
            for sub_key, app_key in (
                ("speech", "text_transform_speech"),
                ("dashes", "text_transform_dashes"),
                ("dialogue", "text_transform_dialogue"),
            ):
                sub_blk = tt.get(sub_key)
                if isinstance(sub_blk, dict) and sub_blk.get("enable") is not None:
                    app_settings[app_key] = _yaml_val_to_str(sub_blk["enable"])
    except Exception as e:
        logger.exception("Ошибка чтения FBC_CONFIG: %s", e)


def update_fbc_config_file(fbc_config_path, css_path, app_settings):
    """Записывает настройки секций images, azw3, kfx, markdown, footnotes, dropcaps и текста в config.yaml."""
    if not os.path.exists(fbc_config_path):
        return
    try:
        yaml = _create_yaml()
        with open(fbc_config_path, "r", encoding="utf-8") as f:
            data = yaml.load(f)
        if not isinstance(data, CommentedMap):
            return

        doc = data.get("document")
        if not isinstance(doc, CommentedMap):
            doc = CommentedMap()
            data["document"] = doc

        images = _ensure_subblock(doc, "images", [], before_keys=("markdown", "kfx", "azw3", "footnotes"))
        _insert_key_after(images, "remove_transparency", _to_bool(app_settings.get("remove_transparency", "false")), "use_broken")
        _insert_key_after(images, "rasterize_svg", _to_bool(app_settings.get("rasterize_svg", "false")), "remove_transparency")
        _insert_key_after(images, "raster_format", str(app_settings.get("raster_format", "auto")), "rasterize_svg")
        try:
            sf_val = max(0.25, min(4.0, float(app_settings.get("image_scale_factor", "1.0"))))
        except (TypeError, ValueError):
            sf_val = 1.0
        _insert_key_after(images, "scale_factor", sf_val, "raster_format")
        _insert_key_after(images, "fit_to_screen", _to_bool(app_settings.get("fit_to_screen", "false")), "scale_factor")
        _insert_key_after(images, "baseline_jpeg", _to_bool(app_settings.get("baseline_jpeg", "false")), "fit_to_screen")
        _insert_key_after(images, "grayscale", str(app_settings.get("grayscale", "none")), "baseline_jpeg")
        _insert_key_after(images, "optimize", _to_bool(app_settings.get("optimize_images", "true"), True), "grayscale")
        _insert_key_after(images, "jpeg_quality_level", _to_int(app_settings.get("jpeg_quality_level", "95"), 95), "optimize")

        screen = _ensure_subblock(images, "screen", [("width", 1264), ("height", 1680), ("dpi", 300)], before_keys=("cover",))
        screen["width"] = max(200, _to_int(app_settings.get("screen_width", "1264"), 1264))
        screen["height"] = max(200, _to_int(app_settings.get("screen_height", "1680"), 1680))
        screen["dpi"] = max(72, _to_int(app_settings.get("screen_dpi", "300"), 300))

        cover = _ensure_subblock(images, "cover", [("generate", False)], before_keys=())
        cover["generate"] = _to_bool(app_settings.get("cover_generate", "false"), False)
        _insert_key_after(cover, "resize", str(app_settings.get("cover_resize", "keepAR")), "generate")

        kfx = _ensure_subblock(doc, "kfx", [("compression", "none")], before_keys=("azw3", "footnotes"))
        kfx["compression"] = str(app_settings.get("kfx_compression", "none"))

        azw3 = _ensure_subblock(doc, "azw3", [("compression", "standard"), ("apnx", "none")], before_keys=("footnotes",))
        azw3["compression"] = str(app_settings.get("azw3_compression", "standard"))
        _insert_key_after(azw3, "apnx", str(app_settings.get("azw3_apnx", "none")), "compression")

        markdown = _ensure_subblock(doc, "markdown", [("images", "placeholder")], before_keys=("kfx", "azw3", "footnotes"))
        markdown["images"] = str(app_settings.get("markdown_images", "placeholder"))

        footnotes = _ensure_subblock(doc, "footnotes", [("mode", "float")], before_keys=("annotation", "toc_page", "dropcaps"))
        fn_mode = str(app_settings.get("footnotes_mode", "float"))
        if fn_mode in ("default", "float", "floatRenumbered"):
            footnotes["mode"] = fn_mode

        annotation = _ensure_subblock(doc, "annotation", [("enable", True)], before_keys=("toc_page", "dropcaps"))
        annotation["enable"] = _to_bool(app_settings.get("annotation_enable", "true"), True)
        annotation["in_toc"] = _to_bool(app_settings.get("annotation_in_toc", "false"), False)

        toc_page = _ensure_subblock(doc, "toc_page", [("placement", "after")], before_keys=("dropcaps",))
        toc_place = str(app_settings.get("toc_page_placement", "after"))
        if toc_place in ("none", "before", "after"):
            toc_page["placement"] = toc_place
        toc_page["include_chapters_without_title"] = _to_bool(app_settings.get("toc_include_untitled", "false"), False)

        page_map = _ensure_subblock(doc, "page_map", [("enable", True), ("size", 2300), ("adobe_de", False)], before_keys=("images",))
        page_map["enable"] = _to_bool(app_settings.get("page_map_enable", "true"), True)
        page_map["size"] = max(500, min(20000, _to_int(app_settings.get("page_map_size", "2300"), 2300)))
        page_map["adobe_de"] = _to_bool(app_settings.get("page_map_adobe_de", "false"), False)

        dropcaps = _ensure_subblock(doc, "dropcaps", [("enable", True)], before_keys=("text_transformations",))
        dropcaps["enable"] = _to_bool(app_settings.get("dropcaps_enable", "true"), True)

        tt = _ensure_subblock(doc, "text_transformations", [], before_keys=())
        for sub_key, app_key in (
            ("speech", "text_transform_speech"),
            ("dashes", "text_transform_dashes"),
            ("dialogue", "text_transform_dialogue"),
        ):
            sub_blk = _ensure_subblock(tt, sub_key, [("enable", False)], before_keys=())
            sub_blk["enable"] = _to_bool(app_settings.get(app_key, "false"), False)

        metainfo = _ensure_subblock(doc, "metainformation", [("transliterate", False)], before_keys=("page_map", "images"))
        if app_settings.get("title_template_mode") == "custom" and app_settings.get("title_template_tokens"):
            title_tpl_body = build_fbc_output_name_template(
                app_settings.get("title_template_tokens"),
                for_metadata_title=True,
            )
        elif app_settings.get("filename_mode") == "custom" and app_settings.get("filename_tokens"):
            title_tpl_body = build_fbc_output_name_template(
                app_settings.get("filename_tokens"),
                for_metadata_title=True,
            )
        else:
            title_tpl_body = textwrap.dedent(DEFAULT_TITLE_META_TEMPLATE)
        metainfo["title_template"] = LiteralScalarString(title_tpl_body.rstrip("\n") + "\n")
        metainfo["transliterate"] = _to_bool(app_settings.get("meta_transliterate", "false"), False)

        doc["fix_zip"] = _to_bool(app_settings.get("fix_zip", "false"), False)
        _insert_key_after(doc, "open_from_cover", _to_bool(app_settings.get("open_from_cover", "true"), True), "fix_zip")
        toc_t = str(app_settings.get("toc_type", "normal"))
        if toc_t in ("normal", "old_kindle", "flat"):
            _insert_key_after(doc, "toc_type", toc_t, "open_from_cover")
        _insert_key_after(doc, "file_name_transliterate", _to_bool(app_settings.get("file_name_transliterate", "false"), False), "output_name_template")
        _insert_key_after(doc, "insert_soft_hyphen", _to_bool(app_settings.get("insert_soft_hyphen", "false"), False), "file_name_transliterate")

        if app_settings.get("filename_mode") == "custom" and app_settings.get("filename_tokens"):
            tpl_body = build_fbc_output_name_template(app_settings.get("filename_tokens"))
        else:
            tpl_body = textwrap.dedent(DEFAULT_OUTPUT_NAME_TEMPLATE)
        tpl_str = LiteralScalarString(tpl_body.rstrip("\n") + "\n")
        _insert_key_after(doc, "output_name_template", tpl_str, "stylesheet_path")

        css_norm = _normalize_stylesheet_path(fbc_config_path, css_path)
        _insert_key_after(doc, "stylesheet_path", DoubleQuotedScalarString(css_norm), "toc_type")

        buf = io.StringIO()
        yaml.dump(data, buf)
        atomic_write_text(fbc_config_path, buf.getvalue())
    except Exception as e:
        logger.exception("Ошибка сохранения FBC_CONFIG: %s", e)


def cleanup_stale_temp_dirs(
    prefixes=("fbc_preview_", "fbc_gui_update_"),
    max_age_sec=86400,
    temp_root=None,
):
    """Удаляет устаревшие временные каталоги превью и обновлений старше max_age_sec в TEMP."""
    import time

    root_dir = temp_root or tempfile.gettempdir()
    if not root_dir or not os.path.isdir(root_dir):
        return 0
    cutoff = time.time() - max(0, float(max_age_sec))
    removed = 0
    try:
        entries = list(os.scandir(root_dir))
    except OSError as e:
        logger.debug("Не удалось просканировать временный каталог %s: %s", root_dir, e)
        return 0
    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
            if not any(entry.name.startswith(pref) for pref in prefixes):
                continue
            st = entry.stat(follow_symlinks=False)
            if st.st_mtime <= cutoff:
                shutil.rmtree(entry.path, ignore_errors=True)
                if not os.path.exists(entry.path):
                    removed += 1
        except OSError as e:
            logger.debug("Не удалось очистить временный каталог %s: %s", entry.path, e)
    return removed

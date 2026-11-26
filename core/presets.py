import copy
import json
import os
import re

from core.config import atomic_write_text

PRESET_SCHEMA_VERSION = 1
PRESET_FILE_EXT = ".fbcpreset.json"
MAX_PRESET_FILE_BYTES = 2 * 1024 * 1024  # 2 MB

_DANGEROUS_CSS_IMPORT_RE = re.compile(r"@import\b[^;{}]*(?:;|$)", re.IGNORECASE)
_DANGEROUS_CSS_EXPR_RE = re.compile(r"expression\s*\([^)]*\)", re.IGNORECASE)
_DANGEROUS_CSS_BEHAVIOR_RE = re.compile(r"(?:behavior|-moz-binding)\s*:[^;{}]*(?:;|$)", re.IGNORECASE)
_DANGEROUS_CSS_REMOTE_URL_RE = re.compile(
    r"url\(\s*['\"]?\s*(?:https?:|javascript:|vbscript:)[^)]*\)",
    re.IGNORECASE,
)


def sanitize_preset_css(css_text):
    """Удаляет потенциально опасные директивы (@import, expression, remote/script url) из CSS пресета."""
    raw = str(css_text or "")
    if not raw:
        return ""
    cleaned = _DANGEROUS_CSS_IMPORT_RE.sub("", raw)
    cleaned = _DANGEROUS_CSS_EXPR_RE.sub("", cleaned)
    cleaned = _DANGEROUS_CSS_BEHAVIOR_RE.sub("", cleaned)
    cleaned = _DANGEROUS_CSS_REMOTE_URL_RE.sub("none", cleaned)
    return cleaned


# Только переносимые настройки конвертации и стилей (без SMTP, паролей, путей и UI-предпочтений)
PRESET_SETTING_KEYS = (
    "device_profile",
    "output_format",
    "screen_width",
    "screen_height",
    "screen_dpi",
    "footnotes_mode",
    "insert_soft_hyphen",
    "file_name_transliterate",
    "meta_transliterate",
    "dropcaps_enable",
    "text_transform_speech",
    "text_transform_dashes",
    "text_transform_dialogue",
    "annotation_enable",
    "annotation_in_toc",
    "toc_type",
    "toc_page_placement",
    "toc_include_untitled",
    "page_map_enable",
    "page_map_size",
    "page_map_adobe_de",
    "fix_zip",
    "open_from_cover",
    "cover_generate",
    "no_cover",
    "filename_mode",
    "filename_tokens",
    "title_template_mode",
    "title_template_tokens",
    "azw3_compression",
    "kfx_compression",
    "azw3_apnx",
    "markdown_images",
    "raster_format",
    "rasterize_svg",
    "remove_transparency",
    "image_scale_factor",
    "optimize_images",
    "jpeg_quality_level",
    "baseline_jpeg",
    "fit_to_screen",
    "grayscale",
    "image_color_profile",
    "image_color_profile_custom",
    "cover_resize",
    "css_ui_state",
)


def slugify_preset_name(name):
    """Преобразует название пресета в безопасное имя файла для Windows и macOS."""
    raw = str(name or "").strip()
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", raw)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    return cleaned[:80] or "preset"


def extract_preset_settings(app_settings):
    """Извлекает из app_settings только переносимые ключи пресета (без SMTP, путей и темы)."""
    result = {}
    if not isinstance(app_settings, dict):
        return result
    fn_mode = app_settings.get("filename_mode")
    title_mode = app_settings.get("title_template_mode")
    for key in PRESET_SETTING_KEYS:
        if key not in app_settings:
            continue
        if key == "filename_tokens" and fn_mode != "custom":
            continue
        if key == "title_template_tokens" and title_mode != "custom":
            continue
        val = app_settings[key]
        if key == "css_ui_state" and not isinstance(val, dict):
            continue
        if key == "image_color_profile_custom":
            if not isinstance(val, dict) or not val:
                continue
        if key in ("filename_tokens", "title_template_tokens") and not isinstance(val, list):
            continue
        result[key] = copy.deepcopy(val)
    return result


def build_preset_payload(name, app_settings, css_content=""):
    clean_name = str(name or "").strip() or "Preset"
    return {
        "schema_version": PRESET_SCHEMA_VERSION,
        "name": clean_name,
        "settings": extract_preset_settings(app_settings),
        "css_content": sanitize_preset_css(css_content),
    }


def load_preset_file(filepath):
    """Загружает и валидирует файл пресета .fbcpreset.json."""
    if os.path.getsize(filepath) > MAX_PRESET_FILE_BYTES:
        raise ValueError(f"Preset file exceeds maximum allowed size ({MAX_PRESET_FILE_BYTES} bytes)")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Preset file must contain a JSON object")
    settings = data.get("settings")
    if settings is not None and not isinstance(settings, dict):
        raise ValueError("Preset 'settings' field must be an object")
    if not settings and not data.get("css_content"):
        raise ValueError("Preset file contains neither settings nor CSS content")

    fallback_name = os.path.basename(filepath)
    if fallback_name.lower().endswith(PRESET_FILE_EXT):
        fallback_name = fallback_name[:-len(PRESET_FILE_EXT)]
    elif fallback_name.lower().endswith(".json"):
        fallback_name = fallback_name[:-5]

    return {
        "schema_version": int(data.get("schema_version") or PRESET_SCHEMA_VERSION),
        "name": str(data.get("name") or fallback_name).strip() or "Preset",
        "settings": extract_preset_settings(settings or {}),
        "css_content": sanitize_preset_css(data.get("css_content") or ""),
    }


def list_presets(presets_dir):
    """Возвращает отсортированный список доступных пользовательских пресетов."""
    if not presets_dir or not os.path.isdir(presets_dir):
        return []
    items = []
    for fname in sorted(os.listdir(presets_dir)):
        if not fname.lower().endswith(PRESET_FILE_EXT):
            continue
        fp = os.path.join(presets_dir, fname)
        if not os.path.isfile(fp):
            continue
        try:
            payload = load_preset_file(fp)
            items.append({
                "name": payload["name"],
                "path": fp,
                "filename": fname,
            })
        except Exception:
            continue
    items.sort(key=lambda x: x["name"].lower())
    return items


def save_preset(presets_dir, name, app_settings, css_content=""):
    """Атомарно сохраняет пресет в папку presets_dir и возвращает путь к файлу."""
    os.makedirs(presets_dir, exist_ok=True)
    payload = build_preset_payload(name, app_settings, css_content)
    filename = slugify_preset_name(payload["name"]) + PRESET_FILE_EXT
    target_path = os.path.join(presets_dir, filename)
    atomic_write_text(target_path, json.dumps(payload, ensure_ascii=False, indent=2))
    return target_path


def delete_preset(filepath):
    if filepath and os.path.isfile(filepath):
        os.remove(filepath)
        return True
    return False


def export_preset_to_file(filepath, name, app_settings, css_content=""):
    """Атомарно экспортирует пресет в произвольный файл .fbcpreset.json."""
    target = str(filepath)
    if not target.lower().endswith(".json"):
        target += PRESET_FILE_EXT
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = build_preset_payload(name, app_settings, css_content)
    atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2))
    return target


def import_preset_from_file(src_path, presets_dir):
    """Валидирует внешний файл пресета и сохраняет его копию в presets_dir."""
    payload = load_preset_file(src_path)
    saved_path = save_preset(
        presets_dir,
        payload["name"],
        payload["settings"],
        payload["css_content"],
    )
    return payload["name"], saved_path, payload


def apply_preset_to_settings(app_settings, payload, *, reset_default_tokens=False):
    """Применяет переносимые настройки пресета к app_settings, не затрагивая приватные поля."""
    if not isinstance(app_settings, dict) or not isinstance(payload, dict):
        return
    raw_settings = payload.get("settings") or {}
    clean = extract_preset_settings(raw_settings)
    for key, val in clean.items():
        if key == "title_template_mode" and val not in ("filename", "custom"):
            val = "filename"
        app_settings[key] = copy.deepcopy(val)
    if reset_default_tokens and isinstance(raw_settings, dict):
        for tok_key in ("filename_tokens", "title_template_tokens"):
            if isinstance(raw_settings.get(tok_key), list):
                app_settings[tok_key] = copy.deepcopy(raw_settings[tok_key])


def sync_bundled_presets(bundled_dir, presets_dir):
    """Копирует отсутствующие встроенные пресеты в пользовательскую папку без перезаписи изменённых."""
    if not bundled_dir or not presets_dir or not os.path.isdir(bundled_dir):
        return []
    os.makedirs(presets_dir, exist_ok=True)
    copied = []
    for fname in sorted(os.listdir(bundled_dir)):
        if not fname.lower().endswith(PRESET_FILE_EXT):
            continue
        src_fp = os.path.join(bundled_dir, fname)
        dst_fp = os.path.join(presets_dir, fname)
        if os.path.isfile(src_fp) and not os.path.exists(dst_fp):
            with open(src_fp, "r", encoding="utf-8") as sf:
                atomic_write_text(dst_fp, sf.read())
            copied.append(dst_fp)
    return copied


def find_builtin_preset_path(bundled_dir, name=None, filename=None):
    """Ищет эталонный встроенный пресет по имени файла или названию пресета."""
    if not bundled_dir or not os.path.isdir(bundled_dir):
        return None
    if filename:
        candidate = os.path.join(bundled_dir, os.path.basename(filename))
        if os.path.isfile(candidate):
            return candidate
    if name:
        slug_candidate = os.path.join(bundled_dir, slugify_preset_name(name) + PRESET_FILE_EXT)
        if os.path.isfile(slug_candidate):
            return slug_candidate
        target = str(name).strip().lower()
        for fname in sorted(os.listdir(bundled_dir)):
            if not fname.lower().endswith(PRESET_FILE_EXT):
                continue
            fp = os.path.join(bundled_dir, fname)
            try:
                payload = load_preset_file(fp)
                if payload["name"].strip().lower() == target:
                    return fp
            except Exception:
                continue
    return None


def is_builtin_preset_modified(user_filepath, bundled_dir):
    """Возвращает True, если пользовательский пресет отличается от встроенного эталона."""
    if not user_filepath or not os.path.isfile(user_filepath):
        return False
    try:
        user_payload = load_preset_file(user_filepath)
    except Exception:
        return False
    builtin_fp = find_builtin_preset_path(
        bundled_dir,
        name=user_payload.get("name"),
        filename=os.path.basename(user_filepath),
    )
    if not builtin_fp:
        return False
    try:
        builtin_payload = load_preset_file(builtin_fp)
    except Exception:
        return False
    return (
        user_payload.get("settings") != builtin_payload.get("settings")
        or user_payload.get("css_content") != builtin_payload.get("css_content")
    )


def restore_builtin_preset(presets_dir, bundled_dir, name=None, filename=None):
    """Восстанавливает встроенный пресет по умолчанию в presets_dir и возвращает (name, saved_path, payload)."""
    builtin_fp = find_builtin_preset_path(bundled_dir, name=name, filename=filename)
    if not builtin_fp:
        raise FileNotFoundError(f"Built-in preset not found: {name or filename}")
    payload = load_preset_file(builtin_fp)
    os.makedirs(presets_dir, exist_ok=True)
    target_name = os.path.basename(filename) if filename else os.path.basename(builtin_fp)
    target_path = os.path.join(presets_dir, target_name)
    with open(builtin_fp, "r", encoding="utf-8") as sf:
        atomic_write_text(target_path, sf.read())
    return payload["name"], target_path, payload

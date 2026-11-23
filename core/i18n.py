import os
import json
from PyQt6.QtCore import QLocale
from core.logger import get_logger


def _deep_merge_dicts(base, override):
    res = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(res.get(k), dict):
            res[k] = _deep_merge_dicts(res[k], v)
        else:
            res[k] = v
    return res


class LocaleManager:
    """Загружает внешние текстовые языковые пакеты из папки locales/*.json."""
    def __init__(self, locales_dir="", bundled_dir=""):
        self.locales_dir = locales_dir
        self.bundled_dir = bundled_dir
        self.lang_code = "ru"
        self.strings = {}
        self.fallback = {}

    def _read_json(self, path):
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
            except Exception as e:
                get_logger("i18n").warning("Ошибка чтения языкового файла %s: %s", path, e)
        return {}

    def _load_lang_dict(self, code):
        data = {}
        if self.bundled_dir and self.bundled_dir != self.locales_dir:
            data = self._read_json(os.path.join(self.bundled_dir, f"{code}.json"))
        user_data = self._read_json(os.path.join(self.locales_dir, f"{code}.json"))
        return _deep_merge_dicts(data, user_data) if data else user_data

    def discover_locales(self):
        found = {}
        for d in (self.bundled_dir, self.locales_dir):
            if d and os.path.isdir(d):
                for fname in sorted(os.listdir(d)):
                    if fname.lower().endswith(".json"):
                        stem = os.path.splitext(fname)[0]
                        data = self._read_json(os.path.join(d, fname))
                        code = str(data.get("_lang_code") or stem).strip()
                        name = str(data.get("_lang_name") or code.upper()).strip()
                        found[code] = name
        if not found:
            found = {"ru": "Русский", "en": "English"}
        ordered = []
        for preferred in ("ru", "en"):
            if preferred in found:
                ordered.append((found.pop(preferred), preferred))
        for code in sorted(found.keys()):
            ordered.append((found[code], code))
        return ordered

    def detect_system_language(self):
        available = {code for _, code in self.discover_locales()}
        sys_name = (QLocale.system().name() or "").lower()
        if sys_name.startswith("ru") and "ru" in available:
            return "ru"
        if "en" in available:
            return "en"
        return next(iter(available), "ru")

    def set_language(self, lang_code):
        available = {code for _, code in self.discover_locales()}
        if lang_code not in available:
            lang_code = self.detect_system_language()
        self.lang_code = lang_code
        self.strings = self._load_lang_dict(lang_code)
        fb_code = "ru" if "ru" in available and lang_code != "ru" else ("en" if "en" in available else lang_code)
        self.fallback = self._load_lang_dict(fb_code) if fb_code != lang_code else {}

    def get(self, key_path, default=None, **kwargs):
        val = self.strings
        for part in key_path.split("."):
            val = val.get(part) if isinstance(val, dict) else None
        if val is None and self.fallback:
            val = self.fallback
            for part in key_path.split("."):
                val = val.get(part) if isinstance(val, dict) else None
        if val is None:
            val = default if default is not None else key_path
        if isinstance(val, str) and kwargs:
            try:
                return val.format(**kwargs)
            except Exception:
                return val
        return val


LOCALE = LocaleManager()


def init_locale(locales_dir, bundled_dir):
    LOCALE.locales_dir = locales_dir
    LOCALE.bundled_dir = bundled_dir


def tr(key_path, **kwargs):
    return LOCALE.get(key_path, **kwargs)


LEGACY_ALIGN_MAP = {
    "По ширине": "justify", "По центру": "center", "По левому краю": "left", "По правому краю": "right",
    "Justify": "justify", "Center": "center", "Left": "left", "Right": "right"
}
LEGACY_STYLE_MAP = {
    "Курсив": "italic", "Обычный": "normal", "Italic": "italic", "Normal": "normal"
}
LEGACY_NOTE_BG_MAP = {
    "#e6e6fa (Лавандовый)": "#e6e6fa", "#f4f4f4 (Серый)": "#f4f4f4",
    "#fff9c4 (Песочный)": "#fff9c4", "#e8f5e9 (Мятный)": "#e8f5e9",
    "#e1f5fe (Голубой)": "#e1f5fe", "#ffffff (Белый)": "#ffffff",
    "transparent (Без фона)": "transparent"
}
LEGACY_NOTE_BORDER_MAP = {
    "1px #505050 solid (Серая)": "1px #505050 solid",
    "1px purple solid (Пурпурная)": "1px purple solid",
    "1px #2196F3 solid (Синяя)": "1px #2196F3 solid",
    "none (Без рамки)": "none"
}


def get_align_options(keys=("justify", "center", "left", "right")):
    return [(tr(f"styles.align.{k}"), k) for k in keys]


def get_style_options():
    return [(tr(f"styles.font_style.{k}"), k) for k in ("italic", "normal")]


def get_note_bg_options():
    keys = ["#e6e6fa", "#f4f4f4", "#fff9c4", "#e8f5e9", "#e1f5fe", "#ffffff", "transparent"]
    return [(tr(f"styles.note_bg.{k}"), k) for k in keys]


def get_note_border_options():
    keys = ["1px #505050 solid", "1px purple solid", "1px #2196F3 solid", "none"]
    return [(tr(f"styles.note_border.{k}"), k) for k in keys]


def get_theme_choices():
    return [
        ("Golden", "Golden"),
        ("Modern", "Modern")
    ]


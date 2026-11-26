"""Реестр тем оформления, парсинг QSS-токенов/палитр и эффекты подсветки главного окна."""

import os
import re
import subprocess
import sys

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QLabel,
    QPushButton,
)

from core.logger import get_logger


COLOR_HEX_MAP = {
    "red": "#ff3b30", "blue": "#007aff", "purple": "#af52de", "green": "#28cd41",
    "magenta": "#ff2d55", "fuchsia": "#ff2d55", "black": "#000000", "navy": "#000080",
    "darkred": "#8b0000", "dimgray": "#696969"
}

LEGACY_THEME_MAP = {
    "Tuck Midnight": "Golden",
    "Midnight": "Golden",
    "Light": "Golden",
    "macOS Light": "Golden",
    "macOS Dark": "Golden",
    "Nordic Slate": "Modern",
    "Авто": "Auto"
}

DEFAULT_PALETTES = {
    "dark": {
        "window": "#131822",
        "text": "#F1F5F9",
        "base": "#1B2230",
        "alt_base": "#1E2636",
        "button": "#252F42",
        "highlight": "#38BDF8",
        "highlight_text": "#0F172A",
    },
    "light": {
        "window": "#F2F4F7",
        "text": "#1E293B",
        "base": "#FFFFFF",
        "alt_base": "#F8FAFC",
        "button": "#F1F5F9",
        "highlight": "#BAE6FD",
        "highlight_text": "#0F172A",
    },
}

DEFAULT_THEME_TOKENS = {
    "dark": {
        "halo_primary": "rgba(142, 175, 130, 125)",
        "halo_secondary": "rgba(56, 189, 248, 135)",
        "halo_nav": "rgba(56, 189, 248, 130)",
        "halo_pill": "rgba(56, 189, 248, 110)",
        "row_sel_start": "#474133",
        "row_sel_mid": "#4D4334",
        "row_sel_end": "#453C33",
        "row_sel_border": "#9E8456",
        "row_sel_halo": "rgba(217, 165, 95, 70)",
        "row_sel_text": "#F8FAFC",
        "row_bg_start": "#1E2636",
        "row_bg_end": "#222B3C",
        "row_border": "#2E3A4F",
        "row_text": "#E2E8F0",
        "row_sep": "rgba(255, 255, 255, 38)",
    },
    "light": {
        "halo_primary": "rgba(88, 150, 128, 120)",
        "halo_secondary": "rgba(56, 189, 248, 115)",
        "halo_nav": "rgba(56, 189, 248, 110)",
        "halo_pill": "rgba(56, 189, 248, 95)",
        "row_sel_start": "#FEECBC",
        "row_sel_mid": "#FEF1CC",
        "row_sel_end": "#FEEAB7",
        "row_sel_border": "#DFC078",
        "row_sel_halo": "rgba(217, 175, 95, 65)",
        "row_sel_text": "#1E293B",
        "row_bg_start": "#F8FAFC",
        "row_bg_end": "#F1F5F9",
        "row_border": "#CBD5E1",
        "row_text": "#1E293B",
        "row_sep": "rgba(148, 163, 184, 75)",
    },
}


def parse_qcolor(val_str, fallback="#38BDF8"):
    if not val_str:
        return QColor(fallback)
    s = val_str.strip()
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([0-9.]+))?\s*\)", s, re.I)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a_raw = m.group(4)
        if a_raw is None:
            a = 255
        else:
            af = float(a_raw)
            a = int(af * 255) if af <= 1.0 else int(af)
        return QColor(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)), max(0, min(255, a)))
    col = QColor(s)
    return col if col.isValid() else QColor(fallback)


class ExternalThemeRegistry:
    """Управляет загрузкой внешних QSS-файлов тем оформления из папки themes/."""

    def __init__(self, themes_dir="", bundled_dir=""):
        self.themes_dir = themes_dir
        self.bundled_dir = bundled_dir

    def _search_dirs(self):
        dirs = []
        for d in (self.themes_dir, self.bundled_dir):
            if d and os.path.isdir(d) and d not in dirs:
                dirs.append(d)
        fallback_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "themes")
        if os.path.isdir(fallback_dir) and fallback_dir not in dirs:
            dirs.append(fallback_dir)
        return dirs

    def discover_families(self):
        """Находит доступные семейства тем по файлам <family>_light.qss / <family>_dark.qss."""
        found = {}
        for d in self._search_dirs():
            try:
                for fname in sorted(os.listdir(d)):
                    if not fname.lower().endswith(".qss"):
                        continue
                    stem = os.path.splitext(fname)[0].lower()
                    if stem.endswith("_light"):
                        fam_key = stem[:-6]
                    elif stem.endswith("_dark"):
                        fam_key = stem[:-5]
                    elif stem in ("light", "dark"):
                        fam_key = "modern"
                    else:
                        fam_key = stem
                    if fam_key:
                        found[fam_key] = fam_key.capitalize()
            except Exception as e:
                get_logger("theme").debug("Ошибка сканирования каталога тем %s: %s", d, e)
        ordered = []
        for std in ("golden", "modern"):
            if std in found:
                ordered.append(found.pop(std))
            else:
                ordered.append(std.capitalize())
        for k in sorted(found.keys()):
            ordered.append(found[k])
        return ordered

    def resolve_qss_path(self, family, mode):
        """Возвращает путь к внешнему .qss файлу для заданного семейства и режима ('light'/'dark')."""
        fam_slug = (family or "Modern").strip().lower()
        mode_slug = "light" if (mode or "").strip().lower() == "light" else "dark"

        candidates = [
            f"{fam_slug}_{mode_slug}.qss",
            f"{fam_slug}.qss",
        ]
        if fam_slug == "modern":
            candidates.append(f"{mode_slug}.qss")

        for d in self._search_dirs():
            for cand in candidates:
                p = os.path.join(d, cand)
                if os.path.isfile(p):
                    return p
        return ""

    def load_qss(self, family, mode):
        path = self.resolve_qss_path(family, mode)
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                get_logger("theme").warning("Ошибка чтения файла темы %s: %s", path, e)
        return ""


THEME_REGISTRY = ExternalThemeRegistry()


def init_themes(themes_dir, bundled_dir=""):
    THEME_REGISTRY.themes_dir = themes_dir
    THEME_REGISTRY.bundled_dir = bundled_dir


def detect_system_dark_mode():
    """Определяет, включена ли в ОС темная тема оформления."""
    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=1
            )
            return res.returncode == 0 and "dark" in res.stdout.strip().lower()
        except Exception as e:
            get_logger("theme").debug("Не удалось определить AppleInterfaceStyle: %s", e)
    try:
        hints = QGuiApplication.styleHints()
        if hints and hasattr(hints, "colorScheme"):
            scheme = hints.colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return True
            if scheme == Qt.ColorScheme.Light:
                return False
    except Exception as e:
        get_logger("theme").debug("Не удалось определить системную схему Qt: %s", e)
    return True


def resolve_theme_family_and_mode(theme_setting, theme_family="Modern", theme_mode="auto"):
    """
    Возвращает кортеж (family, effective_mode):
    - family: 'Modern' или 'Golden' (либо пользовательская тема из папки themes)
    - effective_mode: 'dark' или 'light'
    """
    mapped = LEGACY_THEME_MAP.get(theme_setting, theme_setting)
    families = THEME_REGISTRY.discover_families()
    fam_lookup = {f.lower(): f for f in families}

    if mapped and mapped.lower() in fam_lookup:
        family = fam_lookup[mapped.lower()]
    elif theme_family and theme_family.lower() in fam_lookup:
        family = fam_lookup[theme_family.lower()]
    else:
        family = "Modern"

    if mapped == "Auto" or (theme_mode or "auto").lower() == "auto":
        eff_mode = "dark" if detect_system_dark_mode() else "light"
    else:
        eff_mode = "light" if str(theme_mode).lower() == "light" else "dark"

    return family, eff_mode


def parse_palette_from_qss(qss_text, mode="dark"):
    """Извлекает базовые цвета палитры Qt из метаданных внешнего QSS-файла."""
    colors = dict(DEFAULT_PALETTES.get(mode, DEFAULT_PALETTES["dark"]))
    if not qss_text:
        return colors

    meta_map = {
        "palette-window": "window",
        "palette-text": "text",
        "palette-base": "base",
        "palette-alt-base": "alt_base",
        "palette-button": "button",
        "palette-highlight": "highlight",
        "palette-highlight-text": "highlight_text",
    }
    for tag, key in meta_map.items():
        m = re.search(rf"@{re.escape(tag)}\s*:\s*(#[0-9a-fA-F]{{3,8}})", qss_text)
        if m:
            colors[key] = m.group(1)

    return colors


def parse_theme_tokens_from_qss(qss_text, mode="dark"):
    """Извлекает токены гало-подсветки и скруглённых строк таблицы из метаданных QSS."""
    tokens = dict(DEFAULT_THEME_TOKENS.get(mode, DEFAULT_THEME_TOKENS["dark"]))
    if not qss_text:
        return tokens

    tag_map = {
        "halo-primary": "halo_primary",
        "halo-secondary": "halo_secondary",
        "halo-nav": "halo_nav",
        "halo-pill": "halo_pill",
        "row-sel-start": "row_sel_start",
        "row-sel-mid": "row_sel_mid",
        "row-sel-end": "row_sel_end",
        "row-sel-border": "row_sel_border",
        "row-sel-halo": "row_sel_halo",
        "row-sel-text": "row_sel_text",
        "row-bg-start": "row_bg_start",
        "row-bg-end": "row_bg_end",
        "row-border": "row_border",
        "row-text": "row_text",
        "row-sep": "row_sep",
    }
    for tag, key in tag_map.items():
        m = re.search(rf"@{re.escape(tag)}\s*:\s*([^\n\*]+)", qss_text)
        if m:
            tokens[key] = m.group(1).strip()
    return tokens


def build_qpalette_from_qss(qss_text, mode="dark"):
    c = parse_palette_from_qss(qss_text, mode)
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(c["window"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(c["base"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(c["alt_base"]))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["alt_base"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(c["button"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(c["highlight"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(c["highlight_text"]))
    return pal


def build_theme_qss(theme_setting, theme_family="Modern", theme_mode="auto"):
    """Загружает QSS-стили из внешнего файла темы в папке themes/."""
    family, eff_mode = resolve_theme_family_and_mode(theme_setting, theme_family, theme_mode)
    return THEME_REGISTRY.load_qss(family, eff_mode)


def _apply_halo_effect(widget, qcolor, blur_radius=20):
    if widget is None:
        return
    eff = QGraphicsDropShadowEffect(widget)
    eff.setOffset(0, 0)
    eff.setBlurRadius(blur_radius)
    eff.setColor(qcolor)
    widget.setGraphicsEffect(eff)


def refresh_widget_halos(window, qss_text="", mode="dark"):
    """Обновляет гало-подсветку (свечение) вокруг кнопок и переключателей главного окна."""
    if window is None:
        return
    tokens = parse_theme_tokens_from_qss(qss_text, mode)
    c_primary = parse_qcolor(tokens["halo_primary"])
    c_secondary = parse_qcolor(tokens["halo_secondary"])
    c_nav = parse_qcolor(tokens["halo_nav"])
    c_pill = parse_qcolor(tokens["halo_pill"])

    for btn in window.findChildren(QPushButton):
        obj_name = btn.objectName()
        variant = btn.property("variant")
        is_nav = bool(btn.property("nav"))
        is_pill = bool(btn.property("pill"))

        if obj_name == "NavPillActive" or (is_nav and bool(btn.property("active"))):
            _apply_halo_effect(btn, c_nav, blur_radius=20)
        elif obj_name == "NavPill" or is_nav:
            btn.setGraphicsEffect(None)
        elif obj_name == "AccentButton" or variant == "primary":
            _apply_halo_effect(btn, c_primary, blur_radius=24)
        elif obj_name == "SecondaryButton" or variant == "secondary":
            _apply_halo_effect(btn, c_secondary, blur_radius=22)
        elif obj_name == "OptionPillActive" or (is_pill and btn.isChecked()):
            _apply_halo_effect(btn, c_pill, blur_radius=16)
        elif obj_name == "OptionPill" or is_pill:
            btn.setGraphicsEffect(None)
        elif obj_name in ("ThemeAutoBtn", "ThemeLightBtn", "ThemeDarkBtn"):
            if bool(btn.property("active")):
                _apply_halo_effect(btn, c_pill, blur_radius=14)
            else:
                btn.setGraphicsEffect(None)

    for frame in window.findChildren(QFrame):
        fname = frame.objectName()
        if fname == "TokenPreviewCard":
            _apply_halo_effect(frame, c_pill, blur_radius=18)
        elif fname == "TokenTagChip":
            _apply_halo_effect(frame, c_pill, blur_radius=10)

    for delegate_attr, table_attr in (
        ("table_row_delegate", "table"),
        ("watch_table_row_delegate", "watch_table"),
    ):
        delegate = getattr(window, delegate_attr, None)
        if delegate is not None:
            delegate.set_tokens(tokens)
            tbl = getattr(window, table_attr, None)
            if tbl is not None:
                tbl.viewport().update()


def start_window_crossfade(window):
    """Плавно растворяет снимок предыдущей темы поверх нового оформления."""
    if window is None or not window.isVisible():
        return
    try:
        pixmap: QPixmap = window.grab()
        overlay = QLabel(window)
        overlay.setPixmap(pixmap)
        overlay.setGeometry(0, 0, window.width(), window.height())
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        effect = QGraphicsOpacityEffect(overlay)
        effect.setOpacity(1.0)
        overlay.setGraphicsEffect(effect)
        overlay.show()
        overlay.raise_()

        anim = QPropertyAnimation(effect, b"opacity", overlay)
        anim.setDuration(200)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(overlay.deleteLater)
        anim.start()

        window._fade_overlay = overlay
        window._fade_anim = anim
    except Exception as e:
        get_logger("theme").debug("Анимация смены темы пропущена: %s", e)


# Реэкспорт переиспользуемых виджетов для обратной совместимости импортов из ui.theme
from ui.widgets import (  # noqa: E402, F401
    ColorPickerWidget,
    FilenameTemplateBuilder,
    FlowLayout,
    FormatComboBox,
    PillSelector,
    RoundedRowDelegate,
    ThemeModeButton,
    ThemeToggleWidget,
    _ActiveTagChip,
    _DragGripDots,
    _PaletteTagButton,
    _PreviewBookFileIcon,
    _ResetIconButton,
    _SeparatorChip,
    _TokenDropArea,
    _make_closed_hand_cursor_pixmap,
    _make_rounded_drag_pixmap,
    _start_chip_drag,
    add_setting_row,
    create_section_card,
)

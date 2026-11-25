import os
import re
import sys
import subprocess

from PyQt6.QtCore import Qt, QEasingCurve, QPropertyAnimation, QRectF, QPointF, QRect, QPoint, QSize, QMimeData, pyqtSignal
from PyQt6.QtGui import (
    QColor, QGuiApplication, QPalette, QPixmap, QDrag,
    QPainter, QPainterPath, QLinearGradient, QPen, QFontMetrics
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLayout,
    QPushButton, QLabel, QComboBox, QFrame,
    QColorDialog, QDialog, QLineEdit,
    QGraphicsOpacityEffect, QGraphicsDropShadowEffect,
    QStyledItemDelegate, QStyle
)

from core.i18n import tr
from core.logger import get_logger
from core.fb2_processor import (
    DEFAULT_FILENAME_TOKENS, DEFAULT_TITLE_TOKENS,
    FILENAME_TAG_IDS, TITLE_TAG_IDS,
    render_title_metadata_preview, simulate_fbc_target
)


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

    if hasattr(window, "table_row_delegate") and window.table_row_delegate is not None:
        window.table_row_delegate.set_tokens(tokens)
        if hasattr(window, "table"):
            window.table.viewport().update()


class RoundedRowDelegate(QStyledItemDelegate):
    """Отрисовывает строки таблицы книг в виде единой скруглённой капсулы с градиентом и мягким гало."""

    def __init__(self, table, parent=None):
        super().__init__(parent or table)
        self.table = table
        self.tokens = dict(DEFAULT_THEME_TOKENS["dark"])

    def set_tokens(self, tokens):
        if isinstance(tokens, dict):
            self.tokens.update(tokens)

    def createEditor(self, parent, option, index):
        if not index.isValid() or index.column() in (0, 7, 8):
            return None
        editor = QLineEdit(parent)
        bg = self.tokens.get("row_sel_mid", "#4D4334")
        fg = self.tokens.get("row_sel_text", "#F8FAFC")
        brd = self.tokens.get("row_sel_border", "#9E8456")
        editor.setStyleSheet(
            f"QLineEdit {{ background-color: {bg}; color: {fg}; "
            f"border: 1px solid {brd}; border-radius: 6px; padding: 0px 8px; margin: 0px; }}"
        )
        return editor

    def updateEditorGeometry(self, editor, option, index):
        if editor is not None:
            editor.setGeometry(option.rect.adjusted(3, 5, -3, -5))

    def paint(self, painter: QPainter, option, index):
        if not index.isValid() or self.table is None:
            super().paint(painter, option, index)
            return

        row = index.row()
        col = index.column()
        col_count = self.table.columnCount()
        model = self.table.model()

        first_rect = self.table.visualRect(model.index(row, 0))
        last_rect = self.table.visualRect(model.index(row, col_count - 1))
        cell_rect = option.rect

        row_left = first_rect.left() + 5
        row_right = last_rect.right() - 5
        row_top = cell_rect.top() + 3
        row_bottom = cell_rect.bottom() - 3
        row_rect = QRectF(row_left, row_top, max(10, row_right - row_left), max(10, row_bottom - row_top))

        is_selected = bool(option.state & QStyle.StateFlag.State_Selected) or (
            self.table.selectionModel() and self.table.selectionModel().isRowSelected(row, index.parent())
        )

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setClipRect(cell_rect)

        radius = 8.0

        if is_selected:
            # Мягкое внешнее гало вокруг выделенной скруглённой строки
            halo_col = parse_qcolor(self.tokens.get("row_sel_halo", "rgba(217, 165, 95, 70)"))
            for expand, alpha_mul in ((3.0, 0.22), (2.0, 0.38), (1.0, 0.55)):
                hc = QColor(halo_col)
                hc.setAlpha(int(halo_col.alpha() * alpha_mul))
                halo_path = QPainterPath()
                halo_path.addRoundedRect(row_rect.adjusted(-expand, -expand, expand, expand), radius + expand, radius + expand)
                painter.setPen(QPen(hc, 1.2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(halo_path)

            grad = QLinearGradient(row_rect.topLeft(), row_rect.topRight())
            grad.setColorAt(0.0, parse_qcolor(self.tokens.get("row_sel_start", "#474133")))
            grad.setColorAt(0.5, parse_qcolor(self.tokens.get("row_sel_mid", "#4D4334")))
            grad.setColorAt(1.0, parse_qcolor(self.tokens.get("row_sel_end", "#453C33")))
            border_col = parse_qcolor(self.tokens.get("row_sel_border", "#9E8456"))
            text_col = parse_qcolor(self.tokens.get("row_sel_text", "#F8FAFC"))
        else:
            grad = QLinearGradient(row_rect.topLeft(), row_rect.topRight())
            grad.setColorAt(0.0, parse_qcolor(self.tokens.get("row_bg_start", "#1E2636")))
            grad.setColorAt(1.0, parse_qcolor(self.tokens.get("row_bg_end", "#222B3C")))
            border_col = parse_qcolor(self.tokens.get("row_border", "#2E3A4F"))
            text_col = parse_qcolor(self.tokens.get("row_text", "#E2E8F0"))

        capsule_path = QPainterPath()
        capsule_path.addRoundedRect(row_rect, radius, radius)
        painter.fillPath(capsule_path, grad)

        pen = QPen(border_col, 1.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(capsule_path)

        # Вертикальный разделитель ячеек внутри скруглённой строки
        if col < col_count - 1:
            sep_col = parse_qcolor(self.tokens.get("row_sep", "rgba(255, 255, 255, 38)"))
            painter.setPen(QPen(sep_col, 1.0))
            x_sep = cell_rect.right()
            painter.drawLine(int(x_sep), int(row_top + 2), int(x_sep), int(row_bottom - 2))

        # Отрисовка текста ячейки
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        if text:
            painter.setPen(text_col)
            font = option.font
            painter.setFont(font)
            left_pad = 14 if col == 0 else 10
            right_pad = 14 if col == col_count - 1 else 10
            text_rect = cell_rect.adjusted(left_pad, 0, -right_pad, 0)
            fm = QFontMetrics(font)
            elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, max(10, text_rect.width()))
            painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), elided)

        painter.restore()


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


class ThemeModeButton(QPushButton):
    """Кнопка сегмента переключателя режима темы с векторной отрисовкой иконок (Авто / Светлая / Тёмная)."""

    def __init__(self, kind: str, parent=None):
        super().__init__("", parent)
        self.kind = kind
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        super().paintEvent(event)
        import math
        from PyQt6.QtWidgets import QStyleOptionButton

        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        col = opt.palette.color(QPalette.ColorRole.ButtonText)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cx = self.width() / 2.0
        cy = self.height() / 2.0

        if self.kind == "auto":
            # Комбинированная иконка «Авто»: круг день/ночь (левая половина заполнена, справа лучи солнца)
            scx = cx - 0.8
            r = 5.0
            rect = QRectF(scx - r, cy - r, r * 2.0, r * 2.0)

            pen = QPen(col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(rect)

            half_path = QPainterPath()
            half_path.moveTo(scx, cy - r)
            half_path.arcTo(rect, 90.0, 180.0)
            half_path.closeSubpath()
            painter.fillPath(half_path, col)

            r_in = r + 1.8
            r_out = r + 3.4
            for deg in (-48, 0, 48):
                rad = math.radians(deg)
                p1 = QPointF(scx + r_in * math.cos(rad), cy + r_in * math.sin(rad))
                p2 = QPointF(scx + r_out * math.cos(rad), cy + r_out * math.sin(rad))
                painter.drawLine(p1, p2)

        elif self.kind == "light":
            # Векторная иконка Солнца (центральный диск и 8 лучей)
            r_core = 3.2
            pen = QPen(col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(col)
            painter.drawEllipse(QPointF(cx, cy), r_core, r_core)

            r_in = 5.3
            r_out = 7.3
            for deg in range(0, 360, 45):
                rad = math.radians(deg)
                p1 = QPointF(cx + r_in * math.cos(rad), cy + r_in * math.sin(rad))
                p2 = QPointF(cx + r_out * math.cos(rad), cy + r_out * math.sin(rad))
                painter.drawLine(p1, p2)

        elif self.kind == "dark":
            # Векторная иконка Полумесяца
            r_outer = 5.8
            r_cut = 4.7
            outer_path = QPainterPath()
            outer_path.addEllipse(QPointF(cx + 0.5, cy), r_outer, r_outer)
            cut_path = QPainterPath()
            cut_path.addEllipse(QPointF(cx + 3.1, cy - 2.0), r_cut, r_cut)
            crescent = outer_path.subtracted(cut_path)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(col)
            painter.drawPath(crescent)

        painter.end()


class ThemeToggleWidget(QFrame):
    """Трёхпозиционный переключатель режима темы (Авто / Светлая / Тёмная) в верхней части главного окна."""

    def __init__(self, callback=None, parent=None):
        super().__init__(parent)
        self.setObjectName("ThemeTogglePill")
        self._callback = callback
        self._mode = "auto"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(3)

        self.btn_auto = ThemeModeButton("auto", self)
        self.btn_auto.setObjectName("ThemeAutoBtn")

        self.btn_light = ThemeModeButton("light", self)
        self.btn_light.setObjectName("ThemeLightBtn")

        self.btn_dark = ThemeModeButton("dark", self)
        self.btn_dark.setObjectName("ThemeDarkBtn")

        self._buttons = {
            "auto": self.btn_auto,
            "light": self.btn_light,
            "dark": self.btn_dark,
        }

        layout.addWidget(self.btn_auto)
        layout.addWidget(self.btn_light)
        layout.addWidget(self.btn_dark)

        self.btn_auto.clicked.connect(lambda: self._on_clicked("auto"))
        self.btn_light.clicked.connect(lambda: self._on_clicked("light"))
        self.btn_dark.clicked.connect(lambda: self._on_clicked("dark"))
        self.update_tooltips()
        self.set_mode("auto")

    def update_tooltips(self):
        self.btn_auto.setToolTip(tr("settings.theme_auto_tooltip"))
        self.btn_light.setToolTip(tr("settings.theme_day_tooltip"))
        self.btn_dark.setToolTip(tr("settings.theme_night_tooltip"))

    def set_mode(self, mode):
        m = str(mode).lower()
        self._mode = m if m in ("auto", "light", "dark") else "auto"
        for key, btn in self._buttons.items():
            is_act = (key == self._mode)
            btn.setProperty("active", is_act)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def _on_clicked(self, mode):
        if mode != self._mode:
            self.set_mode(mode)
            if self._callback:
                self._callback(mode)
        else:
            self.set_mode(mode)



class PillSelector(QWidget):
    """Горизонтальный переключатель-пилюля."""
    def __init__(self, options, default=None, callback=None, parent=None, segmented=False):
        super().__init__(parent)
        self._callbacks = [callback] if callback else []
        self._buttons = {}
        self._current_val = None

        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        if segmented:
            container = QFrame(self)
            container.setObjectName("SegmentedSwitch")
            layout = QHBoxLayout(container)
            layout.setContentsMargins(3, 3, 3, 3)
            layout.setSpacing(2)
            outer_layout.addWidget(container)
        else:
            layout = outer_layout
            layout.setSpacing(6)

        for opt in options:
            label, val = opt if isinstance(opt, tuple) else (str(opt), str(opt))
            btn = QPushButton(label)
            btn.setProperty("pill", True)
            if segmented:
                btn.setProperty("segmented", True)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._buttons[val] = btn
            layout.addWidget(btn)
            btn.clicked.connect(lambda checked=False, v=val: self._on_clicked(v))

        initial = default if default in self._buttons else (next(iter(self._buttons)) if self._buttons else None)
        if initial is not None:
            self.set(initial)

    def _apply_button_styles(self):
        for val, btn in self._buttons.items():
            is_sel = (val == self._current_val)
            btn.blockSignals(True)
            btn.setChecked(is_sel)
            btn.blockSignals(False)
            btn.setObjectName("OptionPillActive" if is_sel else "OptionPill")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()
        win = self.window()
        if win and hasattr(win, "_refresh_halos"):
            win._refresh_halos()

    def _on_clicked(self, val):
        if val != self._current_val:
            self.set(val)
            for cb in self._callbacks:
                cb(val)
        else:
            self._apply_button_styles()

    def get(self):
        return self._current_val or ""

    def set(self, val):
        if val in self._buttons:
            self._current_val = val
            self._apply_button_styles()


class ColorPickerWidget(QWidget):
    def __init__(self, parent=None, values=None, default_color="black", width=105):
        super().__init__(parent)
        self._values = list(values or [])
        self._current_color = default_color
        self._callbacks = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.swatch = QLabel()
        self.swatch.setFixedSize(22, 20)
        self.swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_swatch(default_color)
        layout.addWidget(self.swatch)

        self.combo = QComboBox()
        self.combo.addItems(self._values)
        self.combo.setEditable(True)
        self.combo.setCurrentText(default_color)
        self.combo.setFixedWidth(width)
        self.combo.currentTextChanged.connect(self._on_combo_changed)
        layout.addWidget(self.combo)

        self.btn_palette = QPushButton("🎨")
        self.btn_palette.setFixedWidth(34)
        self.btn_palette.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_palette.clicked.connect(self._choose_custom_color)
        layout.addWidget(self.btn_palette)

    def _resolve_hex(self, color_name):
        c = (color_name or "").strip().lower()
        if c in COLOR_HEX_MAP:
            return COLOR_HEX_MAP[c]
        if c.startswith("#") and len(c) in (4, 7):
            return c
        col = QColor(c)
        return col.name() if col.isValid() else "#000000"

    def _update_swatch(self, color_name):
        hex_c = self._resolve_hex(color_name)
        self.swatch.setStyleSheet(
            f"background-color: {hex_c}; border: 1px solid #888888; border-radius: 5px;"
        )

    def _on_combo_changed(self, text):
        self._current_color = text
        self._update_swatch(text)
        for cb in self._callbacks:
            cb()

    def _choose_custom_color(self):
        dlg = QColorDialog(QColor(self._resolve_hex(self._current_color)), self.window())
        dlg.setWindowTitle(tr("common.choose_color"))
        dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        dlg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if self.window() and self.window().styleSheet():
            dlg.setStyleSheet(self.window().styleSheet())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            col = dlg.currentColor()
            if col.isValid():
                hex_c = col.name()
                if hex_c not in self._values:
                    self._values.append(hex_c)
                    self.combo.addItem(hex_c)
                self.combo.setCurrentText(hex_c)

    def get(self):
        return self.combo.currentText().strip()

    def set(self, val):
        val = (val or "").strip()
        if val and val not in self._values:
            self._values.append(val)
            self.combo.addItem(val)
        self.combo.setCurrentText(val)

    def bind(self, event_type, callback):
        if event_type == "<<ComboboxSelected>>":
            self._callbacks.append(callback)


def create_section_card(title_text):
    card = QFrame()
    card.setObjectName("SectionCard")
    vbox = QVBoxLayout(card)
    vbox.setContentsMargins(20, 16, 20, 16)
    vbox.setSpacing(12)

    lbl = QLabel(title_text.upper())
    lbl.setObjectName("SectionHeader")
    vbox.addWidget(lbl)
    return card, vbox


def add_setting_row(parent_layout, title, subtitle, right_widget):
    row = QHBoxLayout()
    row.setContentsMargins(0, 2, 0, 2)

    left = QVBoxLayout()
    left.setSpacing(2)
    t_lbl = QLabel(title)
    t_lbl.setObjectName("RowTitle")
    left.addWidget(t_lbl)
    if subtitle:
        s_lbl = QLabel(subtitle)
        s_lbl.setObjectName("RowDesc")
        s_lbl.setWordWrap(True)
        left.addWidget(s_lbl)

    row.addLayout(left, 1)
    row.addWidget(right_widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    parent_layout.addLayout(row)


class FormatComboBox(QComboBox):
    """Стилизованный выпадающий список форматов с векторной стрелкой."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FormatCombo")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(118)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        col = self.palette().color(QPalette.ColorRole.Text)
        pen = QPen(col, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx = self.width() - 15.0
        cy = self.height() / 2.0
        path = QPainterPath()
        path.moveTo(cx - 4.0, cy - 1.8)
        path.lineTo(cx, cy + 2.2)
        path.lineTo(cx + 4.0, cy - 1.8)
        painter.drawPath(path)
        painter.end()


class FlowLayout(QLayout):
    """Переносящаяся по строкам компоновка для тегов-пилюль и разделителей."""

    def __init__(self, parent=None, margin=0, h_spacing=6, v_spacing=6):
        super().__init__(parent)
        self._items = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        pw = self.parentWidget()
        w = pw.width() if (pw is not None and pw.width() > 100) else 720
        h = self.heightForWidth(w)
        return QSize(w, max(h, self.minimumSize().height()))

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        pw = self.parentWidget()
        if pw is not None and pw.width() > 100:
            size.setHeight(max(size.height(), self.heightForWidth(pw.width())))
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        lines = []
        current_line = []

        for item in self._items:
            sz = item.sizeHint()
            next_x = x + sz.width() + self._h_spacing
            if next_x - self._h_spacing > effective.right() and line_height > 0:
                lines.append((y, line_height, current_line))
                x = effective.x()
                y = y + line_height + self._v_spacing
                next_x = x + sz.width() + self._h_spacing
                line_height = 0
                current_line = []
            current_line.append((item, x, sz))
            x = next_x
            line_height = max(line_height, sz.height())

        if current_line:
            lines.append((y, line_height, current_line))

        if not test_only:
            for line_y, lh, row_items in lines:
                for item, ix, sz in row_items:
                    iy = line_y + max(0, (lh - sz.height()) // 2)
                    item.setGeometry(QRect(QPoint(ix, iy), sz))

        return y + line_height - rect.y() + m.bottom()


class _PreviewBookFileIcon(QWidget):
    """Векторная иконка файла электронной книги (документ с загнутым уголком и раскрытой книгой)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 44)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        app_pal = QGuiApplication.palette()
        fg = app_pal.color(QPalette.ColorRole.WindowText)
        bg = app_pal.color(QPalette.ColorRole.Window)
        if bg.alpha() == 0:
            bg = QColor("#152238")
        fg_main = QColor(fg)
        fg_main.setAlpha(235)

        # Контур документа со скошенным правым верхним углом
        w, h = 30.0, 38.0
        x0, y0 = 3.0, 3.0
        fold = 9.0
        r = 3.5
        doc_path = QPainterPath()
        doc_path.moveTo(x0 + r, y0)
        doc_path.lineTo(x0 + w - fold, y0)
        doc_path.lineTo(x0 + w, y0 + fold)
        doc_path.lineTo(x0 + w, y0 + h - r)
        doc_path.quadTo(x0 + w, y0 + h, x0 + w - r, y0 + h)
        doc_path.lineTo(x0 + r, y0 + h)
        doc_path.quadTo(x0, y0 + h, x0, y0 + h - r)
        doc_path.lineTo(x0, y0 + r)
        doc_path.quadTo(x0, y0, x0 + r, y0)
        doc_path.closeSubpath()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fg_main)
        painter.drawPath(doc_path)

        # Загнутый уголок (полупрозрачный вырез)
        fold_path = QPainterPath()
        fold_path.moveTo(x0 + w - fold, y0)
        fold_path.lineTo(x0 + w - fold, y0 + fold)
        fold_path.lineTo(x0 + w, y0 + fold)
        fold_path.closeSubpath()
        fold_col = QColor(bg)
        fold_col.setAlpha(155)
        painter.fillPath(fold_path, fold_col)

        # Раскрытая книга внутри документа
        cx = x0 + w / 2.0
        by_top = y0 + 17.5
        by_bot = y0 + 30.5
        bw = 9.0

        book_l = QPainterPath()
        book_l.moveTo(cx - 0.8, by_top + 1.5)
        book_l.quadTo(cx - bw * 0.5, by_top - 0.6, cx - bw, by_top + 1.2)
        book_l.lineTo(cx - bw, by_bot)
        book_l.quadTo(cx - bw * 0.5, by_bot - 1.5, cx - 0.8, by_bot + 0.8)
        book_l.closeSubpath()

        book_r = QPainterPath()
        book_r.moveTo(cx + 0.8, by_top + 1.5)
        book_r.quadTo(cx + bw * 0.5, by_top - 0.6, cx + bw, by_top + 1.2)
        book_r.lineTo(cx + bw, by_bot)
        book_r.quadTo(cx + bw * 0.5, by_bot - 1.5, cx + 0.8, by_bot + 0.8)
        book_r.closeSubpath()

        painter.fillPath(book_l, bg)
        painter.fillPath(book_r, bg)
        painter.end()


class _DragGripDots(QWidget):
    """Шеститочечный индикатор перетаскивания (⋮⋮) слева от тега."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 14)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        col = QColor(self.palette().color(QPalette.ColorRole.WindowText))
        col.setAlpha(135)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(col)
        for row in range(3):
            for col_i in range(2):
                cx = 2.5 + col_i * 4.5
                cy = 2.5 + row * 4.2
                painter.drawEllipse(QPointF(cx, cy), 1.15, 1.15)
        painter.end()


class _ResetIconButton(QPushButton):
    """Кнопка сброса с векторной круговой стрелкой слева от текста."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("TokenResetBtn")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        fm = QFontMetrics(self.font())
        self.setMinimumWidth(fm.horizontalAdvance(text) + 38)

    def paintEvent(self, event):
        super().paintEvent(event)
        from PyQt6.QtWidgets import QStyleOptionButton
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        col = opt.palette.color(QPalette.ColorRole.ButtonText)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(col, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        cx = 16.0
        cy = self.height() / 2.0
        r = 5.0
        rect = QRectF(cx - r, cy - r, r * 2.0, r * 2.0)
        painter.drawArc(rect, 130 * 16, -290 * 16)
        # Стрелка на левом верхнем конце дуги
        ax, ay = cx - 3.6, cy - 3.5
        arrow = QPainterPath()
        arrow.moveTo(ax - 2.6, ay + 0.6)
        arrow.lineTo(ax, ay)
        arrow.lineTo(ax + 0.8, ay - 2.6)
        painter.drawPath(arrow)
        painter.end()


class _PaletteTagButton(QPushButton):
    """Кнопка тега в палитре: клик добавляет тег в конец, перетаскивание вставляет в нужную позицию."""

    def __init__(self, tag_id, label, parent=None):
        super().__init__(f"+ {label}", parent)
        self.tag_id = tag_id
        self._drag_start = None
        self.setObjectName("TokenPaletteChip")
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.MouseButton.LeftButton) and self._drag_start is not None:
            if (event.position().toPoint() - self._drag_start).manhattanLength() >= QApplication.startDragDistance():
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData("application/x-fbc-new-tag", self.tag_id.encode("utf-8"))
                drag.setMimeData(mime)
                drag.setPixmap(self.grab())
                drag.exec(Qt.DropAction.CopyAction)
                self._drag_start = None
                return
        super().mouseMoveEvent(event)


class _ActiveTagChip(QFrame):
    """Перетаскиваемая пилюля тега в области конструктора с захватом и кнопкой удаления."""

    remove_requested = pyqtSignal(int)

    def __init__(self, index, tag_id, label, parent=None):
        super().__init__(parent)
        self.index = index
        self.tag_id = tag_id
        self._drag_start = None
        self.setObjectName("TokenTagChip")
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 8, 0)
        lay.setSpacing(6)

        lay.addWidget(_DragGripDots(self))

        lbl = QLabel(label)
        lbl.setObjectName("TokenTagLabel")
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(lbl)

        btn_rm = QPushButton("✕")
        btn_rm.setObjectName("TokenRemoveBtn")
        btn_rm.setFixedSize(18, 18)
        btn_rm.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_rm.clicked.connect(lambda: self.remove_requested.emit(self.index))
        lay.addWidget(btn_rm)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.MouseButton.LeftButton) and self._drag_start is not None:
            if (event.position().toPoint() - self._drag_start).manhattanLength() >= QApplication.startDragDistance():
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData("application/x-fbc-move-token", str(self.index).encode("utf-8"))
                drag.setMimeData(mime)
                drag.setPixmap(self.grab())
                drag.exec(Qt.DropAction.MoveAction)
                self._drag_start = None
                return
        super().mouseMoveEvent(event)


class _SeparatorChip(QFrame):
    """Редактируемый чип-разделитель в области конструктора с увеличенными отступами и удалением."""

    text_changed = pyqtSignal(int, str)
    remove_requested = pyqtSignal(int)

    def __init__(self, index, value, parent=None):
        super().__init__(parent)
        self.index = index
        self._drag_start = None
        self.setObjectName("TokenSepChip")
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(6)

        self.edit = QLineEdit(value)
        self.edit.setObjectName("TokenSepEdit")
        self.edit.setFrame(False)
        self.edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fit_width(value)
        self.edit.textChanged.connect(self._on_text_changed)
        lay.addWidget(self.edit)

        btn_rm = QPushButton("✕")
        btn_rm.setObjectName("TokenRemoveBtn")
        btn_rm.setFixedSize(18, 18)
        btn_rm.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_rm.clicked.connect(lambda: self.remove_requested.emit(self.index))
        lay.addWidget(btn_rm)

    def _fit_width(self, text):
        fm = QFontMetrics(self.edit.font())
        w = max(24, fm.horizontalAdvance(text or " ") + 12)
        self.edit.setFixedWidth(min(140, w))

    def _on_text_changed(self, text):
        self._fit_width(text)
        self.text_changed.emit(self.index, text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.MouseButton.LeftButton) and self._drag_start is not None:
            if (event.position().toPoint() - self._drag_start).manhattanLength() >= QApplication.startDragDistance():
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData("application/x-fbc-move-token", str(self.index).encode("utf-8"))
                drag.setMimeData(mime)
                drag.setPixmap(self.grab())
                drag.exec(Qt.DropAction.MoveAction)
                self._drag_start = None
                return
        super().mouseMoveEvent(event)


class _TokenDropArea(QFrame):
    """Область конструктора шаблона, принимающая перетаскивание тегов и изменение порядка."""

    token_dropped_new = pyqtSignal(str, int)
    token_moved = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TokenDropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(56)
        self.flow = FlowLayout(self, margin=12, h_spacing=6, v_spacing=8)

    def _drop_index_for_pos(self, pos):
        token_widgets = []
        for i in range(self.flow.count()):
            w = self.flow.itemAt(i).widget()
            if w is not None and not w.property("is_arrow"):
                token_widgets.append(w)
        if not token_widgets:
            return 0
        for idx, w in enumerate(token_widgets):
            g = w.geometry()
            if pos.y() < g.top():
                return idx
            if g.top() <= pos.y() <= g.bottom() and pos.x() < g.center().x():
                return idx
        return len(token_widgets)

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasFormat("application/x-fbc-new-tag") or md.hasFormat("application/x-fbc-move-token"):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        md = event.mimeData()
        if md.hasFormat("application/x-fbc-new-tag") or md.hasFormat("application/x-fbc-move-token"):
            event.acceptProposedAction()

    def dropEvent(self, event):
        md = event.mimeData()
        target_idx = self._drop_index_for_pos(event.position().toPoint())
        if md.hasFormat("application/x-fbc-new-tag"):
            tag_id = bytes(md.data("application/x-fbc-new-tag")).decode("utf-8")
            self.token_dropped_new.emit(tag_id, target_idx)
            event.acceptProposedAction()
        elif md.hasFormat("application/x-fbc-move-token"):
            src_idx = int(bytes(md.data("application/x-fbc-move-token")).decode("utf-8"))
            self.token_moved.emit(src_idx, target_idx)
            event.acceptProposedAction()


class FilenameTemplateBuilder(QWidget):
    """Визуальный линейный таймлайн-конструктор шаблона имени выходного файла или заголовка метаданных."""

    tokens_changed = pyqtSignal(list)

    def __init__(self, initial_tokens=None, output_format="epub3", sample_meta=None, parent=None, mode="filename"):
        super().__init__(parent)
        self._mode = "title" if mode == "title" else "filename"
        self._default_tokens = DEFAULT_TITLE_TOKENS if self._mode == "title" else DEFAULT_FILENAME_TOKENS
        self._tag_ids = TITLE_TAG_IDS if self._mode == "title" else FILENAME_TAG_IDS
        self._tokens = [dict(t) for t in (initial_tokens or self._default_tokens)]
        self._output_format = output_format
        self._sample_meta = sample_meta or {
            "last": "Толстой",
            "first": "Лев",
            "mid": "Николаевич",
            "series": "Война и мир",
            "num": "1",
            "title": "Том первый",
        }

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 2)
        root.setSpacing(14)

        # 1. Главный блок: приподнятая карточка превью
        preview_card = QFrame()
        preview_card.setObjectName("TokenPreviewCard")
        preview_card.setMinimumHeight(82)
        p_lay = QHBoxLayout(preview_card)
        p_lay.setContentsMargins(18, 14, 18, 14)
        p_lay.setSpacing(16)

        file_icon = _PreviewBookFileIcon(preview_card)
        p_lay.addWidget(file_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        p_text_box = QVBoxLayout()
        p_text_box.setContentsMargins(0, 0, 0, 0)
        p_text_box.setSpacing(3)

        hdr_key = "settings.title_preview_hdr" if self._mode == "title" else "settings.fn_preview_hdr"
        p_hdr = QLabel(tr(hdr_key))
        p_hdr.setObjectName("TokenPreviewHdr")
        p_text_box.addWidget(p_hdr)

        self.lbl_preview_main = QLabel()
        self.lbl_preview_main.setObjectName("TokenPreviewTitle")
        self.lbl_preview_main.setWordWrap(True)
        self.lbl_preview_main.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        p_text_box.addWidget(self.lbl_preview_main)

        self.lbl_preview_sub = QLabel()
        self.lbl_preview_sub.setObjectName("TokenPreviewSub")
        self.lbl_preview_sub.setWordWrap(True)
        p_text_box.addWidget(self.lbl_preview_sub)

        p_lay.addLayout(p_text_box, 1)
        root.addWidget(preview_card)

        # 2. Средний блок: линейный таймлайн-конструктор со стрелками ->
        tl_key = "settings.title_timeline_lbl" if self._mode == "title" else "settings.fn_timeline_lbl"
        timeline_hdr = QLabel(tr(tl_key))
        timeline_hdr.setObjectName("TokenSectionLabel")
        root.addWidget(timeline_hdr)

        self.drop_area = _TokenDropArea()
        self.drop_area.token_dropped_new.connect(self._insert_tag_at)
        self.drop_area.token_moved.connect(self._move_token)
        root.addWidget(self.drop_area)

        # 3. Нижний блок: Доступные элементы (две организованные строки)
        palette_lbl = QLabel(tr("settings.fn_palette_lbl"))
        palette_lbl.setObjectName("TokenSectionLabel")
        root.addWidget(palette_lbl)

        tags_row = QHBoxLayout()
        tags_row.setContentsMargins(0, 0, 0, 0)
        tags_row.setSpacing(10)

        tags_lbl = QLabel(tr("settings.fn_tags_lbl"))
        tags_lbl.setObjectName("TokenSubLabel")
        tags_lbl.setContentsMargins(0, 5, 0, 0)
        tags_row.addWidget(tags_lbl, 0, Qt.AlignmentFlag.AlignTop)

        palette_wrap = QWidget()
        palette_flow = FlowLayout(palette_wrap, margin=0, h_spacing=6, v_spacing=6)
        for tag_id in self._tag_ids:
            btn = _PaletteTagButton(tag_id, tr(f"settings.fn_tag_{tag_id}"))
            btn.clicked.connect(lambda checked=False, tid=tag_id: self._append_tag(tid))
            palette_flow.addWidget(btn)
        tags_row.addWidget(palette_wrap, 1)
        root.addLayout(tags_row)

        tools_row = QHBoxLayout()
        tools_row.setContentsMargins(0, 0, 0, 0)
        tools_row.setSpacing(6)

        sep_lbl = QLabel(tr("settings.fn_sep_lbl"))
        sep_lbl.setObjectName("TokenSubLabel")
        tools_row.addWidget(sep_lbl)

        for label, val in [("-", " - "), ("—", " — "), ("_", "_"), (".", "."), ("(", "("), (")", ") ")]:
            b = QPushButton(label)
            b.setObjectName("TokenSepPillBtn")
            b.setFixedSize(28, 28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda checked=False, v=val: self._append_text(v))
            tools_row.addWidget(b)

        b_space = QPushButton(tr("settings.fn_space"))
        b_space.setObjectName("TokenSepSpaceBtn")
        b_space.setCursor(Qt.CursorShape.PointingHandCursor)
        b_space.clicked.connect(lambda checked=False: self._append_text(" "))
        tools_row.addWidget(b_space)

        tools_row.addStretch()

        btn_reset = _ResetIconButton(tr("settings.fn_preset_reset"))
        btn_reset.clicked.connect(lambda: self._apply_preset(self._default_tokens))
        tools_row.addWidget(btn_reset)

        root.addLayout(tools_row)

        self._rebuild_chips()

    def set_context(self, output_format=None, sample_meta=None):
        if output_format:
            self._output_format = output_format
        if sample_meta:
            self._sample_meta = sample_meta
        self._update_preview()

    def _update_preview(self):
        no_series_meta = dict(self._sample_meta, series="", num="")
        if self._mode == "title":
            sample_full = render_title_metadata_preview(self._tokens, self._sample_meta)
            sample_no_ser = render_title_metadata_preview(self._tokens, no_series_meta)
        else:
            sample_full = simulate_fbc_target(self._sample_meta, self._output_format, "custom", self._tokens)
            sample_no_ser = simulate_fbc_target(no_series_meta, self._output_format, "custom", self._tokens)
        self.lbl_preview_main.setText(sample_full)
        self.lbl_preview_sub.setText(tr("settings.fn_preview_no_series", no_series=sample_no_ser))

    def _emit_changed(self):
        self._update_preview()
        self.tokens_changed.emit([dict(t) for t in self._tokens])

    def _rebuild_chips(self):
        while self.drop_area.flow.count():
            item = self.drop_area.flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        for idx, tok in enumerate(self._tokens):
            if idx > 0:
                arrow = QLabel("→")
                arrow.setObjectName("TokenArrowLabel")
                arrow.setProperty("is_arrow", True)
                arrow.setFixedHeight(30)
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                self.drop_area.flow.addWidget(arrow)

            if tok.get("type") == "tag":
                tid = tok.get("id", "title")
                chip = _ActiveTagChip(idx, tid, tr(f"settings.fn_tag_{tid}"))
                chip.remove_requested.connect(self._remove_token)
                self.drop_area.flow.addWidget(chip)
            else:
                sep = _SeparatorChip(idx, tok.get("value", ""))
                sep.text_changed.connect(self._update_text_token)
                sep.remove_requested.connect(self._remove_token)
                self.drop_area.flow.addWidget(sep)
        self._update_preview()

    def _append_tag(self, tag_id):
        if self._tokens and self._tokens[-1].get("type") == "tag":
            self._tokens.append({"type": "text", "value": " "})
        self._tokens.append({"type": "tag", "id": tag_id})
        self._rebuild_chips()
        self._emit_changed()

    def _append_text(self, text):
        if self._tokens and self._tokens[-1].get("type") == "text":
            self._tokens[-1]["value"] = self._tokens[-1].get("value", "") + text
        else:
            self._tokens.append({"type": "text", "value": text})
        self._rebuild_chips()
        self._emit_changed()

    def _insert_tag_at(self, tag_id, target_idx):
        target_idx = max(0, min(len(self._tokens), target_idx))
        self._tokens.insert(target_idx, {"type": "tag", "id": tag_id})
        self._rebuild_chips()
        self._emit_changed()

    def _move_token(self, src_idx, target_idx):
        if not (0 <= src_idx < len(self._tokens)):
            return
        tok = self._tokens.pop(src_idx)
        if target_idx > src_idx:
            target_idx -= 1
        target_idx = max(0, min(len(self._tokens), target_idx))
        self._tokens.insert(target_idx, tok)
        self._rebuild_chips()
        self._emit_changed()

    def _update_text_token(self, idx, new_val):
        if 0 <= idx < len(self._tokens) and self._tokens[idx].get("type") == "text":
            self._tokens[idx]["value"] = new_val
            self._emit_changed()

    def _remove_token(self, idx):
        if 0 <= idx < len(self._tokens):
            self._tokens.pop(idx)
            self._rebuild_chips()
            self._emit_changed()

    def _apply_preset(self, preset_tokens):
        self._tokens = [dict(t) for t in preset_tokens]
        self._rebuild_chips()
        self._emit_changed()

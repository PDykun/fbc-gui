import os

from PyQt6.QtCore import Qt, QUrl, QRectF, pyqtProperty
from PyQt6.QtGui import QGuiApplication, QDesktopServices, QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame,
    QInputDialog, QDialog, QPlainTextEdit, QTabWidget, QTabBar,
)

from core.i18n import tr


def show_themed_message(parent, title, text, icon_type="info"):
    """Отображает кастомное диалоговое окно в стиле текущей темы."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    dlg.setModal(True)
    dlg.setMinimumWidth(420)

    if parent and parent.styleSheet():
        dlg.setStyleSheet(parent.styleSheet())

    root = QVBoxLayout(dlg)
    root.setContentsMargins(20, 20, 20, 18)
    root.setSpacing(16)

    card = QFrame()
    card.setObjectName("SectionCard")
    c_layout = QHBoxLayout(card)
    c_layout.setContentsMargins(18, 16, 18, 16)
    c_layout.setSpacing(14)

    icons = {"info": "✦", "warning": "⚠", "error": "✕"}
    icon_lbl = QLabel(icons.get(icon_type, "✦"))
    icon_lbl.setStyleSheet("font-size: 24px; font-weight: bold;")
    c_layout.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)

    msg_box = QVBoxLayout()
    msg_box.setSpacing(6)
    t_lbl = QLabel(title)
    t_lbl.setObjectName("RowTitle")
    msg_box.addWidget(t_lbl)

    m_lbl = QLabel(text)
    m_lbl.setObjectName("RowDesc")
    m_lbl.setWordWrap(True)
    m_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    msg_box.addWidget(m_lbl)

    c_layout.addLayout(msg_box, 1)
    root.addWidget(card)

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    btn_ok = QPushButton(tr("common.ok"))
    btn_ok.setObjectName("AccentButton")
    btn_ok.setProperty("variant", "primary")
    btn_ok.setFixedWidth(96)
    btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_ok.clicked.connect(dlg.accept)
    btn_row.addWidget(btn_ok)
    root.addLayout(btn_row)

    dlg.exec()


def show_conversion_summary_dialog(parent, title, summary_text, icon_type="info", errors=None, output_dir=None, allow_retry=False):
    """Показывает единый сводный диалог итогов конвертации со списком ошибок, повтором и открытием папки."""
    errors = list(errors or [])
    retry_requested = {"value": False}
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    dlg.setModal(True)
    dlg.setMinimumWidth(560 if errors else 440)

    if parent and parent.styleSheet():
        dlg.setStyleSheet(parent.styleSheet())

    root = QVBoxLayout(dlg)
    root.setContentsMargins(20, 20, 20, 18)
    root.setSpacing(14)

    card = QFrame()
    card.setObjectName("SectionCard")
    card_v = QVBoxLayout(card)
    card_v.setContentsMargins(18, 16, 18, 16)
    card_v.setSpacing(12)

    top_row = QHBoxLayout()
    top_row.setSpacing(14)

    icons = {"info": "✦", "warning": "⚠", "error": "✕"}
    icon_lbl = QLabel(icons.get(icon_type, "✦"))
    icon_lbl.setStyleSheet("font-size: 24px; font-weight: bold;")
    top_row.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)

    msg_box = QVBoxLayout()
    msg_box.setSpacing(6)
    t_lbl = QLabel(title)
    t_lbl.setObjectName("RowTitle")
    msg_box.addWidget(t_lbl)

    m_lbl = QLabel(summary_text)
    m_lbl.setObjectName("RowDesc")
    m_lbl.setWordWrap(True)
    m_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    msg_box.addWidget(m_lbl)

    top_row.addLayout(msg_box, 1)
    card_v.addLayout(top_row)

    error_report_text = ""
    if errors:
        err_hdr = QLabel(tr("converter.err_summary_header", count=len(errors)))
        err_hdr.setObjectName("SectionHeader")
        card_v.addWidget(err_hdr)

        lines = []
        for idx, item in enumerate(errors, start=1):
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                fname, msg = str(item[0]), str(item[1]).strip()
                indented = "\n   ".join(msg.splitlines()) if msg else ""
                lines.append(f"{idx}. {fname}\n   {indented}")
            else:
                lines.append(f"{idx}. {str(item).strip()}")
        error_report_text = "\n\n".join(lines)

        err_view = QPlainTextEdit()
        err_view.setReadOnly(True)
        err_view.setPlainText(error_report_text)
        err_view.setMinimumHeight(140)
        err_view.setMaximumHeight(280)
        card_v.addWidget(err_view)

    root.addWidget(card)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)

    if errors:
        btn_copy = QPushButton(tr("converter.btn_copy_errors"))
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)

        def _copy_errors():
            cb = QGuiApplication.clipboard()
            if cb:
                cb.setText(error_report_text)
            btn_copy.setText(tr("converter.btn_copied"))

        btn_copy.clicked.connect(_copy_errors)
        btn_row.addWidget(btn_copy)

        if allow_retry:
            btn_retry = QPushButton(tr("converter.btn_retry_failed"))
            btn_retry.setObjectName("SecondaryButton")
            btn_retry.setProperty("variant", "secondary")
            btn_retry.setCursor(Qt.CursorShape.PointingHandCursor)

            def _on_retry():
                retry_requested["value"] = True
                dlg.accept()

            btn_retry.clicked.connect(_on_retry)
            btn_row.addWidget(btn_retry)

    btn_row.addStretch()

    if output_dir and os.path.isdir(output_dir):
        btn_open = QPushButton(tr("converter.btn_open_folder"))
        btn_open.setObjectName("SecondaryButton")
        btn_open.setProperty("variant", "secondary")
        btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(output_dir))))
        btn_row.addWidget(btn_open)

    btn_ok = QPushButton(tr("common.ok"))
    btn_ok.setObjectName("AccentButton")
    btn_ok.setProperty("variant", "primary")
    btn_ok.setFixedWidth(96)
    btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_ok.setDefault(True)
    btn_ok.clicked.connect(dlg.accept)
    btn_row.addWidget(btn_ok)
    root.addLayout(btn_row)

    dlg.exec()
    return retry_requested["value"]


def show_themed_confirm(parent, title, text, confirm_label=None, cancel_label=None, icon_type="warning"):
    """Отображает тематическое окно подтверждения с двумя кнопками и возвращает True при подтверждении."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    dlg.setModal(True)
    dlg.setMinimumWidth(440)

    if parent and parent.styleSheet():
        dlg.setStyleSheet(parent.styleSheet())

    root = QVBoxLayout(dlg)
    root.setContentsMargins(20, 20, 20, 18)
    root.setSpacing(16)

    card = QFrame()
    card.setObjectName("SectionCard")
    c_layout = QHBoxLayout(card)
    c_layout.setContentsMargins(18, 16, 18, 16)
    c_layout.setSpacing(14)

    icons = {"info": "✦", "warning": "⚠", "error": "✕"}
    icon_lbl = QLabel(icons.get(icon_type, "⚠"))
    icon_lbl.setStyleSheet("font-size: 24px; font-weight: bold;")
    c_layout.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)

    msg_box = QVBoxLayout()
    msg_box.setSpacing(6)
    t_lbl = QLabel(title)
    t_lbl.setObjectName("RowTitle")
    msg_box.addWidget(t_lbl)

    m_lbl = QLabel(text)
    m_lbl.setObjectName("RowDesc")
    m_lbl.setWordWrap(True)
    m_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    msg_box.addWidget(m_lbl)

    c_layout.addLayout(msg_box, 1)
    root.addWidget(card)

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    btn_cancel = QPushButton(cancel_label or tr("common.cancel"))
    btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_cancel.clicked.connect(dlg.reject)
    btn_row.addWidget(btn_cancel)

    btn_confirm = QPushButton(confirm_label or tr("common.ok"))
    btn_confirm.setObjectName("AccentButton")
    btn_confirm.setProperty("variant", "primary")
    btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_confirm.setDefault(True)
    btn_confirm.clicked.connect(dlg.accept)
    btn_row.addWidget(btn_confirm)
    root.addLayout(btn_row)

    return dlg.exec() == QDialog.DialogCode.Accepted


def show_update_dialog(parent, title, text, download_label, later_label):
    """Отображает тематическое окно уведомления об обновлении с кнопкой скачивания."""
    return show_themed_confirm(parent, title, text, download_label, later_label, icon_type="info")


def ask_themed_text(parent, title, label_text, initial_text=""):
    """Отображает тематическое окно ввода текста в соответствии с выбранной темой."""
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label_text)
    dlg.setTextValue(initial_text)
    dlg.setOkButtonText(tr("common.save"))
    dlg.setCancelButtonText(tr("common.cancel"))
    dlg.setOption(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput, False)
    dlg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    dlg.setMinimumWidth(380)
    if parent and parent.styleSheet():
        dlg.setStyleSheet(parent.styleSheet())
    ok = dlg.exec() == QDialog.DialogCode.Accepted
    return dlg.textValue(), ok


def _format_bytes_human(num_bytes):
    n = max(0, int(num_bytes or 0))
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


class SegmentedTabBar(QTabBar):
    """QTabBar с векторной скруглённой капсулой-треком (цвета задаются через QSS)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._track_color = QColor("#E6EBF2")
        self._track_border_color = QColor("#CBD5E1")
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setUsesScrollButtons(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @pyqtProperty(QColor)
    def trackColor(self):
        return self._track_color

    @trackColor.setter
    def trackColor(self, col):
        self._track_color = QColor(col)
        self.update()

    @pyqtProperty(QColor)
    def trackBorderColor(self):
        return self._track_border_color

    @trackBorderColor.setter
    def trackBorderColor(self, col):
        self._track_border_color = QColor(col)
        self.update()

    def paintEvent(self, event):
        if self.count() > 0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            radius = rect.height() / 2.0
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)
            painter.fillPath(path, self._track_color)
            painter.setPen(QPen(self._track_border_color, 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.end()
        super().paintEvent(event)


def create_segmented_tabs(parent=None):
    """Создаёт QTabWidget с сегментированной капсулой вкладок."""
    tabs = QTabWidget(parent)
    tabs.setDocumentMode(False)
    tabs.setTabBar(SegmentedTabBar(tabs))
    return tabs


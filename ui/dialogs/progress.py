from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame, QProgressBar, QDialog,
)

from core.i18n import tr


class ConversionProgressDialog(QDialog):
    """Тематическое окно прогресса конвертации книг и отправки (по эл. почте или на ридер)."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent, total_files, show_email=False, secondary_mode=None, show_convert=True, custom_title=None):
        super().__init__(parent)
        sec_mode = secondary_mode or ("email" if show_email else None)
        self._secondary_mode = sec_mode
        if custom_title:
            title = custom_title
        elif sec_mode == "sync":
            title = tr("converter.progress_title_sync") if show_convert else tr("settings.sync_title")
        elif sec_mode == "email":
            title = tr("converter.progress_title_send")
        else:
            title = tr("converter.progress_title")
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setModal(True)
        self.setMinimumWidth(460)
        self._allow_close = False
        self._cancelling = False

        if parent and parent.styleSheet():
            self.setStyleSheet(parent.styleSheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        card = QFrame()
        card.setObjectName("SectionCard")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(18, 16, 18, 18)
        c_layout.setSpacing(12)

        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(10)
        icon_lbl = QLabel("⚡")
        icon_lbl.setStyleSheet("font-size: 20px;")
        hdr_row.addWidget(icon_lbl)

        t_lbl = QLabel(title)
        t_lbl.setObjectName("RowTitle")
        hdr_row.addWidget(t_lbl, 1)
        c_layout.addLayout(hdr_row)

        self.lbl_convert = None
        self.pb_convert = None
        if show_convert:
            self.lbl_convert = QLabel(tr("converter.progress_convert_prep"))
            self.lbl_convert.setObjectName("RowDesc")
            self.lbl_convert.setWordWrap(True)
            c_layout.addWidget(self.lbl_convert)

            self.pb_convert = QProgressBar()
            self.pb_convert.setObjectName("ConversionProgressBar")
            self.pb_convert.setRange(0, max(1, total_files))
            self.pb_convert.setValue(0)
            self.pb_convert.setFormat("%p%")
            c_layout.addWidget(self.pb_convert)

        self.lbl_email = None
        self.pb_email = None
        if sec_mode:
            wait_text = (
                tr("converter.progress_sync_wait")
                if sec_mode == "sync" and show_convert
                else (tr("settings.sync_status_running") if sec_mode == "sync" else tr("converter.progress_email_wait"))
            )
            self.lbl_email = QLabel(wait_text)
            self.lbl_email.setObjectName("RowDesc")
            self.lbl_email.setWordWrap(True)
            c_layout.addWidget(self.lbl_email)

            self.pb_email = QProgressBar()
            self.pb_email.setObjectName("EmailProgressBar")
            self.pb_email.setRange(0, 100)
            self.pb_email.setValue(0)
            self.pb_email.setFormat("%p%")
            c_layout.addWidget(self.pb_email)

        root.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QPushButton(tr("common.cancel"))
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self.btn_cancel)
        root.addLayout(btn_row)

    def _on_cancel_clicked(self):
        if self._cancelling or self._allow_close:
            return
        self._cancelling = True
        self.btn_cancel.setEnabled(False)
        if self.lbl_convert is not None:
            self.lbl_convert.setText(tr("converter.progress_cancelling"))
        elif self.lbl_email is not None:
            self.lbl_email.setText(tr("converter.progress_cancelling"))
        self.cancel_requested.emit()

    def update_conversion(self, value, status_text):
        if self.pb_convert is not None:
            self.pb_convert.setValue(value)
        if self.lbl_convert is not None and not self._cancelling:
            self.lbl_convert.setText(status_text)

    def update_email(self, value, status_text):
        if self.pb_email is not None and self.lbl_email is not None:
            if value < 0:
                self.pb_email.setRange(0, 0)
            else:
                if self.pb_email.maximum() == 0:
                    self.pb_email.setRange(0, 100)
                self.pb_email.setValue(max(0, min(100, int(value))))
            if not self._cancelling:
                self.lbl_email.setText(status_text)

    def update_secondary(self, value, status_text):
        self.update_email(value, status_text)

    def finish_and_close(self):
        self._allow_close = True
        self.accept()

    def reject(self):
        if self._allow_close:
            super().reject()
        else:
            self._on_cancel_clicked()

    def closeEvent(self, event):
        if self._allow_close:
            super().closeEvent(event)
        else:
            self._on_cancel_clicked()
            event.ignore()


class ImportProgressDialog(QDialog):
    """Тематическое окно прогресса фонового импорта книг и архивов."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        title = tr("converter.import_title")
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setModal(True)
        self.setMinimumWidth(460)
        self._allow_close = False
        self._cancelling = False

        if parent and parent.styleSheet():
            self.setStyleSheet(parent.styleSheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        card = QFrame()
        card.setObjectName("SectionCard")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(18, 16, 18, 18)
        c_layout.setSpacing(12)

        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(10)
        icon_lbl = QLabel("📚")
        icon_lbl.setStyleSheet("font-size: 20px;")
        hdr_row.addWidget(icon_lbl)

        t_lbl = QLabel(title)
        t_lbl.setObjectName("RowTitle")
        hdr_row.addWidget(t_lbl, 1)
        c_layout.addLayout(hdr_row)

        self.lbl_status = QLabel(tr("converter.import_scanning"))
        self.lbl_status.setObjectName("RowDesc")
        self.lbl_status.setWordWrap(True)
        c_layout.addWidget(self.lbl_status)

        self.pb_import = QProgressBar()
        self.pb_import.setObjectName("ConversionProgressBar")
        self.pb_import.setRange(0, 0)
        self.pb_import.setFormat("%p%")
        c_layout.addWidget(self.pb_import)

        root.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QPushButton(tr("common.cancel"))
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self.btn_cancel)
        root.addLayout(btn_row)

    def _on_cancel_clicked(self):
        if self._cancelling or self._allow_close:
            return
        self._cancelling = True
        self.btn_cancel.setEnabled(False)
        self.lbl_status.setText(tr("converter.import_cancelling"))
        self.cancel_requested.emit()

    def update_progress(self, current, total, filename):
        if total > 0:
            if self.pb_import.maximum() != total:
                self.pb_import.setRange(0, total)
            self.pb_import.setValue(min(current, total))
        if not self._cancelling:
            self.lbl_status.setText(
                tr("converter.import_progress", cur=min(current, max(1, total)), total=max(1, total), name=filename)
            )

    def finish_and_close(self):
        self._allow_close = True
        self.accept()

    def reject(self):
        if self._allow_close:
            super().reject()
        else:
            self._on_cancel_clicked()

    def closeEvent(self, event):
        if self._allow_close:
            super().closeEvent(event)
        else:
            self._on_cancel_clicked()
            event.ignore()


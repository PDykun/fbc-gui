from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame, QProgressBar, QDialog,
)

from core.i18n import tr


class FbcSetupDialog(QDialog):
    """Тематическое окно проверки и загрузки движка fb2cng (fbc) с GitHub."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent, initial_status="", title=None):
        super().__init__(parent)
        title = title or tr("fbc_setup.title")
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setModal(True)
        self.setMinimumWidth(480)
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
        icon_lbl = QLabel("⬇")
        icon_lbl.setStyleSheet("font-size: 20px; font-weight: bold;")
        hdr_row.addWidget(icon_lbl)

        t_lbl = QLabel(title)
        t_lbl.setObjectName("RowTitle")
        hdr_row.addWidget(t_lbl, 1)
        c_layout.addLayout(hdr_row)

        self.lbl_status = QLabel(initial_status or tr("fbc_setup.searching"))
        self.lbl_status.setObjectName("RowDesc")
        self.lbl_status.setWordWrap(True)
        c_layout.addWidget(self.lbl_status)

        self.pb_download = QProgressBar()
        self.pb_download.setObjectName("ConversionProgressBar")
        self.pb_download.setRange(0, 0)
        self.pb_download.setFormat("%p%")
        c_layout.addWidget(self.pb_download)

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
        self.lbl_status.setText(tr("fbc_setup.cancelling"))
        self.cancel_requested.emit()

    def set_status_text(self, text, indeterminate=False):
        if not self._cancelling and text:
            self.lbl_status.setText(text)
        if indeterminate and self.pb_download.maximum() != 0:
            self.pb_download.setRange(0, 0)

    def update_download_progress(self, downloaded, total, asset_name):
        if self._cancelling:
            return
        if total and total > 0:
            pct = int(min(100, max(0, (downloaded * 100) // total)))
            if self.pb_download.maximum() != 100:
                self.pb_download.setRange(0, 100)
            self.pb_download.setValue(pct)
            dl_mb = downloaded / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            self.lbl_status.setText(
                tr("fbc_setup.progress", name=asset_name, dl=f"{dl_mb:.1f}", total=f"{tot_mb:.1f}")
            )
        else:
            if self.pb_download.maximum() != 0:
                self.pb_download.setRange(0, 0)
            if asset_name:
                self.lbl_status.setText(tr("fbc_setup.downloading_generic", name=asset_name))

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


class UpdateDownloadDialog(QDialog):
    """Тематическое окно загрузки, SHA-256 проверки и запуска обновления программы."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent, version_str="", initial_status=""):
        super().__init__(parent)
        title = tr("about.update_dl_title")
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setModal(True)
        self.setMinimumWidth(480)
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
        icon_lbl = QLabel("⬇")
        icon_lbl.setStyleSheet("font-size: 20px; font-weight: bold;")
        hdr_row.addWidget(icon_lbl)

        t_lbl = QLabel(title)
        t_lbl.setObjectName("RowTitle")
        hdr_row.addWidget(t_lbl, 1)
        c_layout.addLayout(hdr_row)

        self.lbl_status = QLabel(
            initial_status or tr("about.update_dl_preparing", ver=version_str)
        )
        self.lbl_status.setObjectName("RowDesc")
        self.lbl_status.setWordWrap(True)
        c_layout.addWidget(self.lbl_status)

        self.pb_download = QProgressBar()
        self.pb_download.setObjectName("ConversionProgressBar")
        self.pb_download.setRange(0, 0)
        self.pb_download.setFormat("%p%")
        c_layout.addWidget(self.pb_download)

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
        self.lbl_status.setText(tr("about.update_dl_cancelling"))
        self.cancel_requested.emit()

    def set_status_text(self, text, indeterminate=False):
        if not self._cancelling and text:
            self.lbl_status.setText(text)
        if indeterminate:
            self.pb_download.setRange(0, 0)

    def update_download_progress(self, downloaded, total, asset_name):
        if self._cancelling:
            return
        if total and total > 0:
            pct = int(min(100, max(0, (downloaded * 100) // total)))
            if self.pb_download.maximum() != 100:
                self.pb_download.setRange(0, 100)
            self.pb_download.setValue(pct)
            dl_mb = downloaded / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            self.lbl_status.setText(
                tr("about.update_dl_progress", name=asset_name, dl=f"{dl_mb:.1f}", total=f"{tot_mb:.1f}")
            )
        else:
            if self.pb_download.maximum() != 0:
                self.pb_download.setRange(0, 0)
            if asset_name:
                self.lbl_status.setText(tr("about.update_dl_downloading", name=asset_name))

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


import os

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QPixmap, QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QFrame, QProgressBar, QCheckBox,
    QInputDialog, QDialog, QLineEdit, QFileDialog, QPlainTextEdit
)

from core.i18n import tr
from core.fb2_processor import (
    COVER_PREVIEW_SIZE, fit_image_to_cover_size, simulate_fbc_target
)


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


def show_update_dialog(parent, title, text, download_label, later_label):
    """Отображает тематическое окно уведомления об обновлении с кнопкой скачивания."""
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

    icon_lbl = QLabel("✦")
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
    btn_later = QPushButton(later_label)
    btn_later.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_later.clicked.connect(dlg.reject)
    btn_row.addWidget(btn_later)

    btn_download = QPushButton(download_label)
    btn_download.setObjectName("AccentButton")
    btn_download.setProperty("variant", "primary")
    btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_download.clicked.connect(dlg.accept)
    btn_row.addWidget(btn_download)
    root.addLayout(btn_row)

    return dlg.exec() == QDialog.DialogCode.Accepted


class ConversionProgressDialog(QDialog):
    """Тематическое окно прогресса конвертации книг и отправки по эл. почте."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent, total_files, show_email=False):
        super().__init__(parent)
        title = tr("converter.progress_title_send") if show_email else tr("converter.progress_title")
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
        if show_email:
            self.lbl_email = QLabel(tr("converter.progress_email_wait"))
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
        self.lbl_convert.setText(tr("converter.progress_cancelling"))
        self.cancel_requested.emit()

    def update_conversion(self, value, status_text):
        self.pb_convert.setValue(value)
        if not self._cancelling:
            self.lbl_convert.setText(status_text)

    def update_email(self, value, status_text):
        if self.pb_email is not None and self.lbl_email is not None:
            self.pb_email.setValue(value)
            self.lbl_email.setText(status_text)

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


class BookEditDialog(QDialog):
    """Тематическое окно редактирования всех метаданных и обложки выбранной книги."""

    def __init__(self, parent, data, output_format, filename_mode="default", filename_tokens=None):
        super().__init__(parent)
        self.setWindowTitle(tr("converter.edit_dlg_title"))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setModal(True)
        self.setMinimumWidth(740)
        if parent and parent.styleSheet():
            self.setStyleSheet(parent.styleSheet())

        self._output_format = output_format
        self._filename_mode = filename_mode
        self._filename_tokens = filename_tokens
        self._orig_cover_bytes = data.get("orig_cover_bytes")
        self._orig_cover_mime = data.get("orig_cover_mime")
        self._cover_bytes = data.get("cover_bytes")
        self._cover_mime = data.get("cover_mime")
        self._cover_modified = bool(data.get("cover_modified", False))
        meta = data.get("meta", {})

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 18)
        root.setSpacing(16)

        card = QFrame()
        card.setObjectName("SectionCard")
        c_layout = QHBoxLayout(card)
        c_layout.setContentsMargins(20, 18, 20, 18)
        c_layout.setSpacing(24)

        left_box = QVBoxLayout()
        left_box.setSpacing(12)

        hdr_lbl = QLabel(tr("converter.edit_dlg_title").upper())
        hdr_lbl.setObjectName("SectionHeader")
        left_box.addWidget(hdr_lbl)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        lbl_src_val = QLabel(data.get("display_name") or os.path.basename(data.get("path", "")))
        lbl_src_val.setObjectName("RowDesc")
        lbl_src_val.setWordWrap(True)
        form.addRow(QLabel(tr("converter.edit_dlg_file")), lbl_src_val)

        self.ed_last = QLineEdit(meta.get("last", ""))
        self.ed_first = QLineEdit(meta.get("first", ""))
        self.ed_mid = QLineEdit(meta.get("mid", ""))
        self.ed_series = QLineEdit(meta.get("series", ""))
        self.ed_num = QLineEdit(meta.get("num", ""))
        self.ed_title = QLineEdit(meta.get("title", ""))

        for ed in (self.ed_last, self.ed_first, self.ed_mid, self.ed_series, self.ed_num, self.ed_title):
            ed.setMinimumWidth(250)

        form.addRow(QLabel(tr("converter.edit_dlg_last")), self.ed_last)
        form.addRow(QLabel(tr("converter.edit_dlg_first")), self.ed_first)
        form.addRow(QLabel(tr("converter.edit_dlg_mid")), self.ed_mid)
        form.addRow(QLabel(tr("converter.edit_dlg_series")), self.ed_series)
        form.addRow(QLabel(tr("converter.edit_dlg_num")), self.ed_num)
        form.addRow(QLabel(tr("converter.edit_dlg_title_field")), self.ed_title)

        self.lbl_target_val = QLabel()
        self.lbl_target_val.setObjectName("RowDesc")
        self.lbl_target_val.setWordWrap(True)
        self.lbl_target_val.setMinimumHeight(34)
        self.lbl_target_val.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.addRow(QLabel(tr("converter.edit_dlg_target")), self.lbl_target_val)

        for ed in (self.ed_series, self.ed_num, self.ed_title):
            ed.textChanged.connect(self._update_target_preview)
        self._update_target_preview()

        left_box.addLayout(form)
        left_box.addStretch()
        c_layout.addLayout(left_box, 1)

        cover_box = QVBoxLayout()
        cover_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        cover_box.setSpacing(8)

        cov_hdr = QLabel(tr("converter.cover_header"))
        cov_hdr.setObjectName("SectionHeader")
        cov_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_box.addWidget(cov_hdr)

        self.cover_preview_lbl = QLabel()
        self.cover_preview_lbl.setObjectName("CoverPanel")
        self.cover_preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_preview_lbl.setFixedSize(COVER_PREVIEW_SIZE[0], COVER_PREVIEW_SIZE[1])
        cover_box.addWidget(self.cover_preview_lbl)

        self.cover_info_label = QLabel()
        self.cover_info_label.setObjectName("RowDesc")
        self.cover_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_box.addWidget(self.cover_info_label)

        self.btn_replace_cover = QPushButton(tr("converter.btn_replace_cover"))
        self.btn_replace_cover.setObjectName("SecondaryButton")
        self.btn_replace_cover.setProperty("variant", "secondary")
        self.btn_replace_cover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_replace_cover.clicked.connect(self._replace_cover)
        cover_box.addWidget(self.btn_replace_cover)

        self.btn_reset_cover = QPushButton(tr("converter.btn_reset_cover"))
        self.btn_reset_cover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_cover.setEnabled(self._cover_modified)
        self.btn_reset_cover.clicked.connect(self._reset_cover)
        cover_box.addWidget(self.btn_reset_cover)

        cover_box.addStretch()
        c_layout.addLayout(cover_box)
        root.addWidget(card)

        self._render_cover()

        btn_row = QHBoxLayout()
        self.chk_save_source = QCheckBox(tr("converter.edit_dlg_save_source"))
        self.chk_save_source.setChecked(False)
        self.chk_save_source.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(self.chk_save_source)
        btn_row.addStretch()
        btn_cancel = QPushButton(tr("converter.btn_cancel"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_apply = QPushButton(tr("converter.btn_apply"))
        btn_apply.setObjectName("AccentButton")
        btn_apply.setProperty("variant", "primary")
        btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_apply.setDefault(True)
        btn_apply.clicked.connect(self.accept)
        btn_row.addWidget(btn_apply)
        root.addLayout(btn_row)

    def _update_target_preview(self):
        self.lbl_target_val.setText(
            simulate_fbc_target(self.get_meta(), self._output_format, self._filename_mode, self._filename_tokens)
        )

    def _render_cover(self):
        if not self._cover_bytes:
            self.cover_preview_lbl.setText(tr("converter.cover_missing"))
            self.cover_preview_lbl.setPixmap(QPixmap())
            self.cover_info_label.setText(tr("converter.cover_size_empty"))
            return
        pixmap = QPixmap()
        pixmap.loadFromData(self._cover_bytes)
        scaled = pixmap.scaled(
            COVER_PREVIEW_SIZE[0], COVER_PREVIEW_SIZE[1],
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.cover_preview_lbl.setPixmap(scaled)
        status = tr("converter.cover_modified") if self._cover_modified else ""
        self.cover_info_label.setText(tr("converter.cover_size", w=pixmap.width(), h=pixmap.height(), status=status))

    def _replace_cover(self):
        img_path, _ = QFileDialog.getOpenFileName(
            self, tr("converter.dlg_select_cover"), "", tr("converter.filter_images")
        )
        if img_path:
            try:
                fitted_bytes, mime_type = fit_image_to_cover_size(img_path)
                self._cover_bytes = fitted_bytes
                self._cover_mime = mime_type
                self._cover_modified = True
                self.btn_reset_cover.setEnabled(True)
                self._render_cover()
            except Exception as e:
                show_themed_message(self, tr("common.error"), tr("converter.err_update_cover", e=e), "error")

    def _reset_cover(self):
        self._cover_bytes = self._orig_cover_bytes
        self._cover_mime = self._orig_cover_mime
        self._cover_modified = False
        self.btn_reset_cover.setEnabled(False)
        self._render_cover()

    def get_meta(self):
        return {
            "last": self.ed_last.text().strip(),
            "first": self.ed_first.text().strip(),
            "mid": self.ed_mid.text().strip(),
            "series": self.ed_series.text().strip(),
            "num": self.ed_num.text().strip(),
            "title": self.ed_title.text().strip(),
        }

    def get_cover_state(self):
        return self._cover_bytes, self._cover_mime, self._cover_modified

    def should_save_to_source(self):
        return bool(self.chk_save_source.isChecked())


class BatchEditDialog(QDialog):
    """Тематическое окно пакетного редактирования метаданных для нескольких книг."""

    def __init__(self, parent, count, common_meta=None):
        super().__init__(parent)
        self.setWindowTitle(tr("converter.batch_dlg_title"))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setModal(True)
        self.setMinimumWidth(500)
        if parent and parent.styleSheet():
            self.setStyleSheet(parent.styleSheet())

        common_meta = common_meta or {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 18)
        root.setSpacing(16)

        card = QFrame()
        card.setObjectName("SectionCard")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(20, 18, 20, 18)
        c_layout.setSpacing(14)

        hdr_lbl = QLabel(tr("converter.batch_dlg_title").upper())
        hdr_lbl.setObjectName("SectionHeader")
        c_layout.addWidget(hdr_lbl)

        desc_lbl = QLabel(tr("converter.batch_dlg_count", count=count))
        desc_lbl.setObjectName("RowDesc")
        desc_lbl.setWordWrap(True)
        c_layout.addWidget(desc_lbl)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self._fields = {}
        specs = [
            ("last", tr("converter.edit_dlg_last")),
            ("first", tr("converter.edit_dlg_first")),
            ("mid", tr("converter.edit_dlg_mid")),
            ("series", tr("converter.edit_dlg_series")),
        ]
        for key, label_txt in specs:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(10)

            chk = QCheckBox()
            chk.setChecked(False)
            ed = QLineEdit(common_meta.get(key, ""))
            ed.setMinimumWidth(260)
            ed.textEdited.connect(lambda _txt, c=chk: c.setChecked(True))

            row_l.addWidget(chk)
            row_l.addWidget(ed, 1)
            form.addRow(QLabel(label_txt), row_w)
            self._fields[key] = (chk, ed)

        c_layout.addLayout(form)
        root.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton(tr("converter.btn_cancel"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_apply = QPushButton(tr("converter.btn_apply"))
        btn_apply.setObjectName("AccentButton")
        btn_apply.setProperty("variant", "primary")
        btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_apply.setDefault(True)
        btn_apply.clicked.connect(self.accept)
        btn_row.addWidget(btn_apply)
        root.addLayout(btn_row)

    def get_updates(self):
        updates = {}
        for key, (chk, ed) in self._fields.items():
            if chk.isChecked():
                updates[key] = ed.text().strip()
        return updates

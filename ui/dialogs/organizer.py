import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QFrame, QDialog, QLineEdit, QFileDialog,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from core.i18n import tr
from core.fb2_processor import plan_organize_fb2_files


class OrganizeBooksDialog(QDialog):
    """Диалог переименования и раскладки исходных FB2/ZIP по папкам с предпросмотром Было -> Стало."""

    def __init__(self, parent, items, default_dest_dir="", filename_mode="default", filename_tokens=None):
        super().__init__(parent)
        self.setWindowTitle(tr("converter.organize_title"))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setModal(True)
        self.setMinimumSize(720, 480)
        if parent and parent.styleSheet():
            self.setStyleSheet(parent.styleSheet())

        self._items = list(items or [])
        self._filename_mode = filename_mode
        self._filename_tokens = filename_tokens
        self._current_plan = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 18)
        root.setSpacing(14)

        card = QFrame()
        card.setObjectName("SectionCard")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(18, 16, 18, 16)
        c_layout.setSpacing(12)

        hdr = QLabel(tr("converter.organize_title").upper())
        hdr.setObjectName("SectionHeader")
        c_layout.addWidget(hdr)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        dest_w = QWidget()
        dest_l = QHBoxLayout(dest_w)
        dest_l.setContentsMargins(0, 0, 0, 0)
        dest_l.setSpacing(8)
        self.ed_dest = QLineEdit(default_dest_dir or os.path.expanduser("~"))
        self.ed_dest.textChanged.connect(self._refresh_preview)
        btn_browse = QPushButton(tr("settings.btn_choose_dir"))
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.clicked.connect(self._choose_dest)
        dest_l.addWidget(self.ed_dest, 1)
        dest_l.addWidget(btn_browse)
        form.addRow(QLabel(tr("converter.organize_dest")), dest_w)

        self.cb_structure = QComboBox()
        self.cb_structure.addItem(tr("converter.organize_struct_author_series"), "author_series")
        self.cb_structure.addItem(tr("converter.organize_struct_author"), "author")
        self.cb_structure.addItem(tr("converter.organize_struct_flat"), "flat")
        self.cb_structure.currentIndexChanged.connect(self._refresh_preview)
        form.addRow(QLabel(tr("converter.organize_structure")), self.cb_structure)

        self.cb_mode = QComboBox()
        self.cb_mode.addItem(tr("converter.organize_mode_copy"), "copy")
        self.cb_mode.addItem(tr("converter.organize_mode_move"), "move")
        form.addRow(QLabel(tr("converter.organize_mode")), self.cb_mode)
        c_layout.addLayout(form)

        self.preview_table = QTableWidget(0, 2)
        self.preview_table.setHorizontalHeaderLabels([
            tr("converter.organize_col_before"),
            tr("converter.organize_col_after"),
        ])
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        c_layout.addWidget(self.preview_table, 1)

        root.addWidget(card, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton(tr("converter.btn_cancel"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        self.btn_run = QPushButton(tr("converter.organize_btn_run"))
        self.btn_run.setObjectName("AccentButton")
        self.btn_run.setProperty("variant", "primary")
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run.setDefault(True)
        self.btn_run.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_run)
        root.addLayout(btn_row)

        self._refresh_preview()

    def _choose_dest(self):
        folder = QFileDialog.getExistingDirectory(self, tr("converter.organize_title"), self.ed_dest.text().strip() or os.path.expanduser("~"))
        if folder:
            self.ed_dest.setText(folder)

    def _refresh_preview(self):
        dest_root = self.ed_dest.text().strip() or os.path.expanduser("~")
        pattern = self.cb_structure.currentData() or "author_series"
        self._current_plan = plan_organize_fb2_files(
            self._items,
            dest_root,
            pattern_mode=pattern,
            filename_mode=self._filename_mode,
            filename_tokens=self._filename_tokens,
        )
        self.preview_table.setRowCount(len(self._current_plan))
        for r, entry in enumerate(self._current_plan):
            rel_dst = os.path.relpath(entry["dst_path"], dest_root) if (os.path.isdir(dest_root) or dest_root) else entry["dst_path"]
            self.preview_table.setItem(r, 0, QTableWidgetItem(entry["display_name"]))
            self.preview_table.setItem(r, 1, QTableWidgetItem(rel_dst))
        self.btn_run.setEnabled(bool(self._current_plan))

    def get_plan(self):
        return list(self._current_plan)

    def is_copy_mode(self):
        return (self.cb_mode.currentData() or "copy") == "copy"


"""Диалог добавления и редактирования правила папки автоконвертации (Watch Folder)."""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from core.presets import list_presets
from core.watch_folder import PRESET_CURRENT_TOKEN, normalize_watch_rule
from ui.dialogs.common import show_themed_message


class WatchFolderRuleDialog(QDialog):
    """Диалог настройки одного правила Watch Folder (папка, пресет, доставка, действие с исходником)."""

    def __init__(self, parent=None, *, rule=None, presets_dir="", app_settings=None):
        super().__init__(parent)
        self.presets_dir = presets_dir
        self.app_settings = app_settings or {}
        self._initial = normalize_watch_rule(rule) if rule else normalize_watch_rule({"enabled": True})
        self._is_edit = bool(rule)

        self.setWindowTitle(
            tr("watch.dlg_edit_title") if self._is_edit else tr("watch.dlg_add_title")
        )
        self.setObjectName("MainContainer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setModal(True)
        if parent and parent.styleSheet():
            self.setStyleSheet(parent.styleSheet())
        self.setMinimumWidth(580)
        self._build_ui()
        self._populate()
        self._update_delivery_fields()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        card = QFrame()
        card.setObjectName("SectionCard")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(18, 16, 18, 16)
        card_lay.setSpacing(12)

        hdr = QLabel(self.windowTitle().upper())
        hdr.setObjectName("SectionHeader")
        card_lay.addWidget(hdr)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(tr("watch.ph_rule_name"))
        form.addRow(tr("watch.lbl_rule_name"), self.name_edit)

        folder_row = QWidget()
        folder_lay = QHBoxLayout(folder_row)
        folder_lay.setContentsMargins(0, 0, 0, 0)
        folder_lay.setSpacing(8)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(tr("watch.ph_folder"))
        folder_lay.addWidget(self.folder_edit, 1)
        btn_browse_folder = QPushButton(tr("settings.btn_choose_dir"))
        btn_browse_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse_folder.clicked.connect(self._browse_watch_folder)
        folder_lay.addWidget(btn_browse_folder)
        form.addRow(tr("watch.lbl_folder"), folder_row)

        self.recursive_chk = QCheckBox(tr("watch.chk_recursive"))
        self.recursive_chk.setCursor(Qt.CursorShape.PointingHandCursor)
        form.addRow("", self.recursive_chk)

        self.preset_combo = QComboBox()
        self.preset_combo.addItem(tr("watch.preset_current"), PRESET_CURRENT_TOKEN)
        for item in list_presets(self.presets_dir):
            self.preset_combo.addItem(item["name"], item["name"])
        form.addRow(tr("watch.lbl_preset"), self.preset_combo)

        self.delivery_combo = QComboBox()
        self.delivery_combo.addItem(tr("watch.delivery_folder"), "folder")
        self.delivery_combo.addItem(tr("watch.delivery_email"), "email")
        self.delivery_combo.addItem(tr("watch.delivery_device_sync"), "device_sync")
        self.delivery_combo.currentIndexChanged.connect(self._update_delivery_fields)
        form.addRow(tr("watch.lbl_delivery"), self.delivery_combo)

        # Поле для доставки в папку
        self.output_dir_row = QWidget()
        out_lay = QHBoxLayout(self.output_dir_row)
        out_lay.setContentsMargins(0, 0, 0, 0)
        out_lay.setSpacing(8)
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText(tr("watch.ph_output_dir"))
        out_lay.addWidget(self.output_dir_edit, 1)
        btn_browse_out = QPushButton(tr("settings.btn_choose_dir"))
        btn_browse_out.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse_out.clicked.connect(self._browse_output_dir)
        out_lay.addWidget(btn_browse_out)
        self.lbl_output_dir = QLabel(tr("watch.lbl_output_dir"))
        form.addRow(self.lbl_output_dir, self.output_dir_row)

        # Поле для доставки по Email
        self.email_to_edit = QLineEdit()
        self.email_to_edit.setPlaceholderText(
            self.app_settings.get("email_to", "") or "reader@kindle.com"
        )
        self.lbl_email_to = QLabel(tr("watch.lbl_email_to"))
        form.addRow(self.lbl_email_to, self.email_to_edit)

        # Поля для доставки на ридер
        self.sync_row = QWidget()
        sync_lay = QHBoxLayout(self.sync_row)
        sync_lay.setContentsMargins(0, 0, 0, 0)
        sync_lay.setSpacing(8)
        self.sync_mode_combo = QComboBox()
        self.sync_mode_combo.addItem(tr("watch.sync_mode_global"), "")
        self.sync_mode_combo.addItem(tr("settings.opt_sync_mtp"), "mtp")
        self.sync_mode_combo.addItem(tr("settings.opt_sync_usb"), "usb")
        self.sync_mode_combo.addItem(tr("settings.opt_sync_folder"), "folder")
        sync_lay.addWidget(self.sync_mode_combo)
        self.sync_target_edit = QLineEdit()
        self.sync_target_edit.setPlaceholderText(
            self.app_settings.get("device_sync_target", "documents/books")
        )
        sync_lay.addWidget(self.sync_target_edit, 1)
        self.lbl_sync = QLabel(tr("watch.lbl_sync_target"))
        form.addRow(self.lbl_sync, self.sync_row)

        # Действие с исходником
        self.post_action_combo = QComboBox()
        self.post_action_combo.addItem(tr("watch.post_move_processed"), "move_processed")
        self.post_action_combo.addItem(tr("watch.post_keep"), "keep")
        self.post_action_combo.addItem(tr("watch.post_trash"), "trash")
        form.addRow(tr("watch.lbl_post_action"), self.post_action_combo)

        self.enabled_chk = QCheckBox(tr("watch.chk_enabled"))
        self.enabled_chk.setCursor(Qt.CursorShape.PointingHandCursor)
        form.addRow("", self.enabled_chk)

        card_lay.addLayout(form)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setObjectName("RowDesc")
        self.lbl_hint.setWordWrap(True)
        card_lay.addWidget(self.lbl_hint)

        root.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton(tr("common.cancel"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton(tr("common.save"))
        btn_save.setObjectName("AccentButton")
        btn_save.setProperty("variant", "primary")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

    def _populate(self):
        r = self._initial
        self.name_edit.setText(r.get("name", ""))
        self.folder_edit.setText(r.get("folder", ""))
        self.recursive_chk.setChecked(bool(r.get("recursive", False)))
        self.enabled_chk.setChecked(bool(r.get("enabled", True)))

        p_idx = self.preset_combo.findData(r.get("preset_name", PRESET_CURRENT_TOKEN))
        if p_idx >= 0:
            self.preset_combo.setCurrentIndex(p_idx)

        d_idx = self.delivery_combo.findData(r.get("delivery_mode", "folder"))
        if d_idx >= 0:
            self.delivery_combo.setCurrentIndex(d_idx)

        self.output_dir_edit.setText(r.get("output_dir", ""))
        self.email_to_edit.setText(r.get("email_to", ""))

        sm_idx = self.sync_mode_combo.findData(r.get("device_sync_mode", ""))
        if sm_idx >= 0:
            self.sync_mode_combo.setCurrentIndex(sm_idx)
        self.sync_target_edit.setText(r.get("device_sync_target", ""))

        pa_idx = self.post_action_combo.findData(r.get("post_action", "move_processed"))
        if pa_idx >= 0:
            self.post_action_combo.setCurrentIndex(pa_idx)

    def _update_delivery_fields(self):
        mode = self.delivery_combo.currentData() or "folder"
        is_folder = mode == "folder"
        is_email = mode == "email"
        is_sync = mode == "device_sync"

        self.lbl_output_dir.setVisible(is_folder)
        self.output_dir_row.setVisible(is_folder)
        self.lbl_email_to.setVisible(is_email)
        self.email_to_edit.setVisible(is_email)
        self.lbl_sync.setVisible(is_sync)
        self.sync_row.setVisible(is_sync)

        if is_email and not (self.app_settings.get("smtp_host") or "").strip():
            self.lbl_hint.setText(tr("watch.hint_smtp_missing"))
        elif is_sync:
            self.lbl_hint.setText(tr("watch.hint_device_sync"))
        else:
            self.lbl_hint.setText(tr("watch.hint_folder"))

    def _browse_watch_folder(self):
        start = self.folder_edit.text().strip() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, tr("watch.dlg_choose_folder"), start)
        if chosen:
            self.folder_edit.setText(chosen)
            if not self.name_edit.text().strip():
                self.name_edit.setText(os.path.basename(os.path.normpath(chosen)) or chosen)

    def _browse_output_dir(self):
        start = self.output_dir_edit.text().strip() or self.folder_edit.text().strip() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, tr("settings.dlg_choose_dir"), start)
        if chosen:
            self.output_dir_edit.setText(chosen)

    def _on_save(self):
        folder = self.folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            show_themed_message(self, tr("common.warning"), tr("watch.err_invalid_folder"), "warning")
            return
        self.accept()

    def get_rule(self):
        return normalize_watch_rule({
            "id": self._initial["id"],
            "enabled": self.enabled_chk.isChecked(),
            "name": self.name_edit.text().strip(),
            "folder": self.folder_edit.text().strip(),
            "recursive": self.recursive_chk.isChecked(),
            "preset_name": self.preset_combo.currentData() or PRESET_CURRENT_TOKEN,
            "delivery_mode": self.delivery_combo.currentData() or "folder",
            "output_dir": self.output_dir_edit.text().strip(),
            "email_to": self.email_to_edit.text().strip(),
            "device_sync_mode": self.sync_mode_combo.currentData() or "",
            "device_sync_target": self.sync_target_edit.text().strip(),
            "post_action": self.post_action_combo.currentData() or "move_processed",
        })

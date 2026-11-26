"""Диалог добавления и редактирования правила папки автоконвертации (Watch Folder)."""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
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

from core.cover_studio import TEMPLATES as COVER_TEMPLATES
from core.i18n import LOCALE, tr
from core.metadata_lookup import DEFAULT_PROVIDER_ORDER, PROVIDER_LABELS
from core.presets import list_presets
from core.watch_folder import (
    PRESET_CURRENT_TOKEN,
    WATCH_ENRICH_CONFIDENCE_PRESETS,
    normalize_watch_rule,
)
from ui.dialogs.common import create_segmented_tabs, show_themed_message
from ui.theme import FormatComboBox, PillSelector


def _tr_fb(key, ru_default, en_default):
    default = ru_default if LOCALE.lang_code == "ru" else en_default
    return str(LOCALE.get(key, default=default))


class WatchFolderRuleDialog(QDialog):
    """Диалог настройки одного правила Watch Folder (основные параметры и подготовка книг)."""

    def __init__(self, parent=None, *, rule=None, presets_dir="", app_settings=None):
        super().__init__(parent)
        self.presets_dir = presets_dir
        self.app_settings = app_settings or {}
        self._initial = normalize_watch_rule(rule) if rule else normalize_watch_rule({"enabled": True})
        self._is_edit = bool(rule)
        self._provider_checks = {}

        self.setWindowTitle(
            tr("watch.dlg_edit_title") if self._is_edit else tr("watch.dlg_add_title")
        )
        self.setObjectName("MainContainer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setModal(True)
        if parent is not None:
            self.setPalette(parent.palette())
            if parent.styleSheet():
                self.setStyleSheet(parent.styleSheet())
        self.setMinimumWidth(620)
        self._build_ui()
        self._populate()
        self._update_delivery_fields()
        self._update_prep_fields()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        self.tabs = create_segmented_tabs(self)
        self.tabs.addTab(self._build_general_tab(), _tr_fb("watch.tab_general", "Основные", "General"))
        self.tabs.addTab(self._build_prep_tab(), _tr_fb("watch.tab_preparation", "Подготовка книг", "Book Preparation"))

        root.addWidget(self.tabs, 1)
        root.addLayout(self._build_footer_row())

    def _build_general_tab(self):
        tab_general = QWidget()
        gen_lay = QVBoxLayout(tab_general)
        gen_lay.setContentsMargins(0, 4, 0, 0)
        gen_lay.setSpacing(12)

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

        self.preset_combo = FormatComboBox()
        self.preset_combo.addItem(tr("watch.preset_current"), PRESET_CURRENT_TOKEN)
        for item in list_presets(self.presets_dir):
            self.preset_combo.addItem(item["name"], item["name"])
        form.addRow(tr("watch.lbl_preset"), self.preset_combo)

        self.delivery_combo = FormatComboBox()
        self.delivery_combo.addItem(tr("watch.delivery_folder"), "folder")
        self.delivery_combo.addItem(tr("watch.delivery_email"), "email")
        self.delivery_combo.addItem(tr("watch.delivery_device_sync"), "device_sync")
        self.delivery_combo.currentIndexChanged.connect(self._update_delivery_fields)
        form.addRow(tr("watch.lbl_delivery"), self.delivery_combo)

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

        self.email_to_edit = QLineEdit()
        self.email_to_edit.setPlaceholderText(
            self.app_settings.get("email_to", "") or "reader@kindle.com"
        )
        self.lbl_email_to = QLabel(tr("watch.lbl_email_to"))
        form.addRow(self.lbl_email_to, self.email_to_edit)

        self.sync_row = QWidget()
        sync_lay = QHBoxLayout(self.sync_row)
        sync_lay.setContentsMargins(0, 0, 0, 0)
        sync_lay.setSpacing(8)
        self.sync_mode_combo = FormatComboBox()
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

        self.post_action_combo = FormatComboBox()
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

        gen_lay.addWidget(card)
        return tab_general

    def _build_prep_tab(self):
        tab_prep = QWidget()
        prep_lay = QVBoxLayout(tab_prep)
        prep_lay.setContentsMargins(0, 4, 0, 0)
        prep_lay.setSpacing(12)

        prep_card = QFrame()
        prep_card.setObjectName("SectionCard")
        pc_lay = QVBoxLayout(prep_card)
        pc_lay.setContentsMargins(18, 16, 18, 16)
        pc_lay.setSpacing(12)

        prep_hdr = QLabel(
            _tr_fb("watch.sec_book_prep", "ПОДГОТОВКА КНИГ ПЕРЕД КОНВЕРТАЦИЕЙ", "BOOK PREPARATION BEFORE CONVERSION")
        )
        prep_hdr.setObjectName("SectionHeader")
        pc_lay.addWidget(prep_hdr)

        prep_form = QFormLayout()
        prep_form.setSpacing(10)
        prep_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.auto_repair_chk = QCheckBox(
            _tr_fb(
                "watch.chk_auto_repair",
                "Исправлять повреждённые FB2 и битые иллюстрации перед конвертацией",
                "Repair malformed FB2 XML and broken images before conversion",
            )
        )
        self.auto_repair_chk.setCursor(Qt.CursorShape.PointingHandCursor)
        prep_form.addRow("", self.auto_repair_chk)

        self.enrich_mode_combo = FormatComboBox()
        self.enrich_mode_combo.addItem(_tr_fb("watch.enrich_off", "Выключено", "Off"), "off")
        self.enrich_mode_combo.addItem(_tr_fb("watch.enrich_cover_only", "Только недостающая обложка", "Missing cover only"), "cover_only")
        self.enrich_mode_combo.addItem(_tr_fb("watch.enrich_empty_only", "Пустые поля и обложка", "Empty fields & cover"), "empty_only")
        self.enrich_mode_combo.currentIndexChanged.connect(self._update_prep_fields)
        prep_form.addRow(
            _tr_fb("watch.lbl_auto_enrich", "Автопоиск в сети:", "Online auto-lookup:"),
            self.enrich_mode_combo,
        )

        self.conf_selector = PillSelector(
            [
                (_tr_fb("watch.conf_strict", "Строгая", "Strict"), "strict"),
                (_tr_fb("watch.conf_balanced", "Сбалансированная", "Balanced"), "balanced"),
                (_tr_fb("watch.conf_relaxed", "Мягкая", "Relaxed"), "relaxed"),
            ],
            default="balanced",
            segmented=True,
        )
        self.lbl_conf = QLabel(_tr_fb("watch.lbl_confidence", "Точность совпадения:", "Match accuracy:"))
        prep_form.addRow(self.lbl_conf, self.conf_selector)

        prov_row = QWidget()
        prov_lay = QHBoxLayout(prov_row)
        prov_lay.setContentsMargins(0, 0, 0, 0)
        prov_lay.setSpacing(10)
        for pid in DEFAULT_PROVIDER_ORDER:
            chk = QCheckBox(PROVIDER_LABELS.get(pid, pid))
            chk.setCursor(Qt.CursorShape.PointingHandCursor)
            self._provider_checks[pid] = chk
            prov_lay.addWidget(chk)
        prov_lay.addStretch(1)
        self.lbl_providers = QLabel(_tr_fb("watch.lbl_providers", "Источники:", "Sources:"))
        self.prov_row = prov_row
        prep_form.addRow(self.lbl_providers, prov_row)

        self.fallback_cover_chk = QCheckBox(
            _tr_fb(
                "watch.chk_fallback_cover",
                "Создавать обложку в Cover Studio, если она не найдена",
                "Generate a cover in Cover Studio if still missing",
            )
        )
        self.fallback_cover_chk.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fallback_cover_chk.toggled.connect(self._update_prep_fields)
        prep_form.addRow("", self.fallback_cover_chk)

        self.fallback_tpl_combo = FormatComboBox()
        is_ru = (LOCALE.lang_code or "ru") == "ru"
        for tid, info in COVER_TEMPLATES.items():
            self.fallback_tpl_combo.addItem(info["name_ru"] if is_ru else info["name_en"], tid)
        self.fallback_tpl_combo.activated.connect(self._on_fallback_template_activated)
        self.lbl_fallback_tpl = QLabel(_tr_fb("watch.lbl_fallback_template", "Стиль обложки:", "Cover style:"))
        prep_form.addRow(self.lbl_fallback_tpl, self.fallback_tpl_combo)

        self.fallback_series_color_chk = QCheckBox(
            _tr_fb(
                "watch.chk_fallback_series_color",
                "Единый цвет обложки для всех книг одной серии",
                "Consistent cover color for all books in the same series",
            )
        )
        self.fallback_series_color_chk.setCursor(Qt.CursorShape.PointingHandCursor)
        prep_form.addRow("", self.fallback_series_color_chk)

        self.write_back_chk = QCheckBox(
            _tr_fb(
                "watch.chk_write_back",
                "Сохранять исправления и обложку обратно в исходный файл",
                "Write repairs and cover back to the source file",
            )
        )
        self.write_back_chk.setCursor(Qt.CursorShape.PointingHandCursor)
        prep_form.addRow("", self.write_back_chk)

        pc_lay.addLayout(prep_form)

        prep_hint = QLabel(
            _tr_fb(
                "watch.hint_prep",
                "По умолчанию исходный файл не изменяется — исправления, найденные метаданные и обложка применяются только к временной копии перед конвертацией.",
                "By default, source files are never modified — repairs, fetched metadata, and generated covers are applied only to a temporary copy before conversion.",
            )
        )
        prep_hint.setObjectName("RowDesc")
        prep_hint.setWordWrap(True)
        pc_lay.addWidget(prep_hint)

        prep_lay.addWidget(prep_card)
        prep_lay.addStretch(1)
        return tab_prep

    def _build_footer_row(self):
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
        return btn_row

    @staticmethod
    def _confidence_to_preset(value):
        val = float(value or 0.88)
        if val >= 0.90:
            return "strict"
        if val <= 0.83:
            return "relaxed"
        return "balanced"

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

        # Подготовка книг
        self.auto_repair_chk.setChecked(bool(r.get("auto_repair", False)))
        em_idx = self.enrich_mode_combo.findData(r.get("auto_enrich_mode", "off"))
        if em_idx >= 0:
            self.enrich_mode_combo.setCurrentIndex(em_idx)
        self.conf_selector.set(self._confidence_to_preset(r.get("enrich_min_confidence", 0.88)))
        active_provs = set(r.get("enrich_providers") or ())
        for pid, chk in self._provider_checks.items():
            chk.setChecked(pid in active_provs)

        self.fallback_cover_chk.setChecked(bool(r.get("fallback_cover_enabled", False)))
        tpl_idx = self.fallback_tpl_combo.findData(r.get("fallback_cover_template", "eink_minimal"))
        if tpl_idx >= 0:
            self.fallback_tpl_combo.setCurrentIndex(tpl_idx)
        self.fallback_series_color_chk.setChecked(bool(r.get("fallback_cover_series_color", True)))
        self.write_back_chk.setChecked(bool(r.get("write_back_source", False)))

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

    def _on_fallback_template_activated(self, _index):
        if not self.fallback_cover_chk.isChecked():
            self.fallback_cover_chk.setChecked(True)

    def _update_prep_fields(self):
        enrich_on = (self.enrich_mode_combo.currentData() or "off") != "off"
        self.lbl_conf.setEnabled(enrich_on)
        self.conf_selector.setEnabled(enrich_on)
        self.lbl_providers.setEnabled(enrich_on)
        self.prov_row.setEnabled(enrich_on)

        fb_on = self.fallback_cover_chk.isChecked()
        self.fallback_series_color_chk.setEnabled(fb_on)

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
            self.tabs.setCurrentIndex(0)
            show_themed_message(self, tr("common.warning"), tr("watch.err_invalid_folder"), "warning")
            return
        self.accept()

    def get_rule(self):
        selected_provs = [pid for pid, chk in self._provider_checks.items() if chk.isChecked()]
        conf_key = self.conf_selector.get() or "balanced"
        min_conf = WATCH_ENRICH_CONFIDENCE_PRESETS.get(conf_key, 0.88)
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
            "auto_repair": self.auto_repair_chk.isChecked(),
            "auto_enrich_mode": self.enrich_mode_combo.currentData() or "off",
            "enrich_min_confidence": min_conf,
            "enrich_providers": selected_provs,
            "fallback_cover_enabled": self.fallback_cover_chk.isChecked(),
            "fallback_cover_template": self.fallback_tpl_combo.currentData() or "eink_minimal",
            "fallback_cover_series_color": self.fallback_series_color_chk.isChecked(),
            "write_back_source": self.write_back_chk.isChecked(),
        })

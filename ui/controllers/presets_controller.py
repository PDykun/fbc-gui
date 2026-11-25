import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QInputDialog

from core.config import DEFAULT_OUTPUT_FORMAT, atomic_write_text
from core.css_preview import generate_css_content as build_css_content, get_default_css_ui_state
from core.i18n import tr
from core.logger import get_logger
from core.presets import (
    PRESET_FILE_EXT,
    apply_preset_to_settings,
    delete_preset as delete_user_preset_file,
    export_preset_to_file,
    find_builtin_preset_path,
    import_preset_from_file,
    list_presets as list_user_presets,
    load_preset_file,
    restore_builtin_preset,
    save_preset as save_user_preset_file,
    slugify_preset_name,
)
from ui.dialogs import show_themed_message

logger = get_logger("app")


class PresetsController:
    """Контроллер управления пользовательскими и встроенными пресетами настроек и CSS."""

    def _update_preset_buttons_state(self):
        if not hasattr(self, "user_preset_combo"):
            return
        item = self.user_preset_combo.currentData()
        has_item = isinstance(item, dict) and bool(item.get("path"))
        has_builtin = False
        if has_item:
            has_builtin = bool(
                find_builtin_preset_path(
                    self.bundled_presets_dir,
                    name=item.get("name"),
                    filename=item.get("filename"),
                )
            )
        if hasattr(self, "btn_preset_apply"):
            self.btn_preset_apply.setEnabled(has_item)
        if hasattr(self, "btn_preset_delete"):
            self.btn_preset_delete.setEnabled(has_item)
        if hasattr(self, "btn_preset_restore"):
            self.btn_preset_restore.setEnabled(has_builtin)

    def refresh_user_presets_combo(self, selected_name=None):
        if not hasattr(self, "user_preset_combo"):
            return
        cb = self.user_preset_combo
        prev_name = selected_name
        if prev_name is None:
            prev_name = self.app_settings.get("active_user_preset", "") or None
        if prev_name is None and cb.currentIndex() >= 0:
            cur_data = cb.currentData()
            if isinstance(cur_data, dict):
                prev_name = cur_data.get("name")

        cb.blockSignals(True)
        cb.clear()
        presets = list_user_presets(self.presets_dir)
        if not presets:
            cb.addItem(tr("settings.preset_none"), None)
        else:
            target_idx = 0
            for idx, item in enumerate(presets):
                cb.addItem(item["name"], item)
                if prev_name and item["name"] == prev_name:
                    target_idx = idx
            cb.setCurrentIndex(target_idx)
        cb.blockSignals(False)
        self._update_preset_buttons_state()

    def _current_preset_css_and_settings(self):
        if hasattr(self, "_get_css_ui_state"):
            self.app_settings["css_ui_state"] = self._get_css_ui_state()
        css_content = ""
        if hasattr(self, "generate_css_content"):
            css_content = self.generate_css_content()
        elif os.path.isfile(self.css_path):
            with open(self.css_path, "r", encoding="utf-8") as f:
                css_content = f.read()
        return self.app_settings, css_content

    def _apply_preset_payload(self, payload, selected_name=None):
        if self._has_blocking_workers():
            logger.warning("Применение пресета отклонено: активны фоновые задачи")
            show_themed_message(self, tr("common.warning"), tr("common.busy_workers_warning"), "warning")
            return False
        preset_settings = payload.get("settings") or {}
        has_css_ui_state = isinstance(preset_settings.get("css_ui_state"), dict) and bool(preset_settings.get("css_ui_state"))
        apply_preset_to_settings(self.app_settings, payload)
        active_name = selected_name or payload.get("name") or ""
        self.app_settings["active_user_preset"] = active_name

        css_content = payload.get("css_content") or ""
        if css_content:
            atomic_write_text(self.css_path, css_content)
            if not has_css_ui_state:
                self.app_settings.pop("css_ui_state", None)
        elif has_css_ui_state:
            merged_css_state = {**get_default_css_ui_state(), **preset_settings["css_ui_state"]}
            atomic_write_text(self.css_path, build_css_content(merged_css_state, self.fonts_dir))

        self.save_app_settings()
        self.update_fbc_config_file()

        cur_page = self.pages.currentIndex() if hasattr(self, "pages") else 3
        search_query = self.search_edit.text() if hasattr(self, "search_edit") else ""
        selected_id = None
        if hasattr(self, "table"):
            sel_rows = self.table.selectionModel().selectedRows()
            if sel_rows:
                it = self.table.item(sel_rows[0].row(), 0)
                if it:
                    selected_id = it.data(Qt.ItemDataRole.UserRole)

        self.create_widgets()
        self._update_undo_redo_ui()
        if search_query and hasattr(self, "search_edit"):
            self.search_edit.blockSignals(True)
            self.search_edit.setText(search_query)
            self.search_edit.blockSignals(False)
        self._repopulate_table_from_files_data(selected_id)
        self.load_and_parse_css_to_gui()
        self.save_visual_css(show_alert=False)
        self.apply_theme(self.app_settings.get("theme", "Modern"), save=False)
        self.refresh_user_presets_combo(selected_name=active_name)
        self.switch_page(cur_page)
        self.refresh_preview()
        return True

    def save_user_preset_clicked(self):
        default_name = ""
        if hasattr(self, "user_preset_combo") and isinstance(self.user_preset_combo.currentData(), dict):
            default_name = self.user_preset_combo.currentData().get("name", "")
        if not default_name:
            fmt = self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT).upper()
            prof = self.app_settings.get("device_profile", "custom")
            default_name = f"{prof.capitalize()} {fmt}" if prof != "custom" else f"My {fmt} Preset"

        name, ok = QInputDialog.getText(
            self,
            tr("settings.dlg_preset_save_title"),
            tr("settings.dlg_preset_save_prompt"),
            text=default_name,
        )
        name = (name or "").strip()
        if not ok or not name:
            return
        try:
            settings, css_content = self._current_preset_css_and_settings()
            save_user_preset_file(self.presets_dir, name, settings, css_content)
            self.app_settings["active_user_preset"] = name
            self.save_app_settings()
            self.refresh_user_presets_combo(selected_name=name)
            logger.info("Сохранён пользовательский пресет: %s", name)
            show_themed_message(self, tr("common.success"), tr("settings.msg_preset_saved", name=name), "info")
        except Exception as e:
            logger.error("Ошибка сохранения пресета %s: %s", name, e)
            show_themed_message(self, tr("common.error"), tr("settings.err_preset_io", e=e), "error")

    def apply_user_preset_clicked(self):
        if not hasattr(self, "user_preset_combo"):
            return
        item = self.user_preset_combo.currentData()
        if not isinstance(item, dict) or not item.get("path"):
            return
        try:
            payload = load_preset_file(item["path"])
            if self._apply_preset_payload(payload, selected_name=payload["name"]):
                logger.info("Применён пользовательский пресет: %s", payload["name"])
                show_themed_message(self, tr("common.success"), tr("settings.msg_preset_applied", name=payload["name"]), "info")
        except Exception as e:
            logger.error("Ошибка применения пресета %s: %s", item.get("path"), e)
            show_themed_message(self, tr("common.error"), tr("settings.err_preset_io", e=e), "error")

    def delete_user_preset_clicked(self):
        if not hasattr(self, "user_preset_combo"):
            return
        item = self.user_preset_combo.currentData()
        if not isinstance(item, dict) or not item.get("path"):
            return
        try:
            delete_user_preset_file(item["path"])
            name = item.get("name", "")
            if self.app_settings.get("active_user_preset") == name:
                self.app_settings["active_user_preset"] = ""
                self.save_app_settings()
            self.refresh_user_presets_combo()
            logger.info("Удалён пользовательский пресет: %s", name)
            show_themed_message(self, tr("common.info"), tr("settings.msg_preset_deleted", name=name), "info")
        except Exception as e:
            logger.error("Ошибка удаления пресета: %s", e)
            show_themed_message(self, tr("common.error"), tr("settings.err_preset_io", e=e), "error")

    def restore_user_preset_clicked(self):
        if not hasattr(self, "user_preset_combo"):
            return
        item = self.user_preset_combo.currentData()
        if not isinstance(item, dict):
            return
        try:
            name, _, payload = restore_builtin_preset(
                self.presets_dir,
                self.bundled_presets_dir,
                name=item.get("name"),
                filename=item.get("filename"),
            )
            if self._apply_preset_payload(payload, selected_name=name):
                logger.info("Восстановлен встроенный пресет по умолчанию: %s", name)
                show_themed_message(self, tr("common.success"), tr("settings.msg_preset_restored", name=name), "info")
        except Exception as e:
            logger.error("Ошибка восстановления пресета: %s", e)
            show_themed_message(self, tr("common.error"), tr("settings.err_preset_io", e=e), "error")

    def export_user_preset_clicked(self):
        preset_name = ""
        if hasattr(self, "user_preset_combo") and isinstance(self.user_preset_combo.currentData(), dict):
            preset_name = self.user_preset_combo.currentData().get("name", "")
        if not preset_name:
            preset_name = f"fbc_{self.app_settings.get('output_format', DEFAULT_OUTPUT_FORMAT)}"

        suggested = os.path.join(
            os.path.expanduser("~"),
            slugify_preset_name(preset_name) + PRESET_FILE_EXT,
        )
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("settings.dlg_preset_export_title"),
            suggested,
            tr("settings.filter_preset_files"),
        )
        if not out_path:
            return
        try:
            settings, css_content = self._current_preset_css_and_settings()
            final_path = export_preset_to_file(out_path, preset_name, settings, css_content)
            logger.info("Экспортирован пресет в %s", final_path)
            show_themed_message(self, tr("common.success"), tr("settings.msg_preset_exported", path=final_path), "info")
        except Exception as e:
            logger.error("Ошибка экспорта пресета: %s", e)
            show_themed_message(self, tr("common.error"), tr("settings.err_preset_io", e=e), "error")

    def import_user_preset_clicked(self):
        in_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("settings.dlg_preset_import_title"),
            os.path.expanduser("~"),
            tr("settings.filter_preset_files"),
        )
        if not in_path:
            return
        try:
            name, _, payload = import_preset_from_file(in_path, self.presets_dir)
            if self._apply_preset_payload(payload, selected_name=name):
                logger.info("Импортирован и применён пресет: %s", name)
                show_themed_message(self, tr("common.success"), tr("settings.msg_preset_imported", name=name), "info")
        except Exception as e:
            logger.error("Ошибка импорта пресета %s: %s", in_path, e)
            show_themed_message(self, tr("common.error"), tr("settings.err_preset_io", e=e), "error")

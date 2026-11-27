import os

from PyQt6.QtWidgets import QFileDialog, QInputDialog, QWidget

from core.config import DEFAULT_OUTPUT_FORMAT, atomic_write_text, get_default_app_settings
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

    _PRESET_NONE_DATA = "__none__"

    def _update_preset_buttons_state(self):
        if not hasattr(self, "user_preset_combo"):
            return
        item = self.user_preset_combo.currentData()
        is_none = item == self._PRESET_NONE_DATA
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
            self.btn_preset_apply.setEnabled(has_item or is_none)
        if hasattr(self, "btn_preset_delete"):
            self.btn_preset_delete.setEnabled(has_item)
        if hasattr(self, "btn_preset_restore"):
            self.btn_preset_restore.setEnabled(has_builtin)

    def refresh_user_presets_combo(self, selected_name=None):
        if not hasattr(self, "user_preset_combo"):
            return
        cb = self.user_preset_combo
        if selected_name is not None:
            prev_name = selected_name
        else:
            prev_name = self.app_settings.get("active_user_preset", "")
            if not prev_name and cb.currentIndex() >= 0:
                cur_data = cb.currentData()
                if isinstance(cur_data, dict):
                    prev_name = cur_data.get("name", "")

        cb.blockSignals(True)
        cb.clear()
        cb.addItem(tr("settings.preset_option_none"), self._PRESET_NONE_DATA)
        presets = list_user_presets(self.presets_dir)
        target_idx = 0
        for idx, item in enumerate(presets, start=1):
            cb.addItem(item["name"], item)
            if prev_name and item["name"] == prev_name:
                target_idx = idx
        cb.setCurrentIndex(target_idx)
        cb.blockSignals(False)
        self._update_preset_buttons_state()

    def _build_default_reset_payload(self):
        default_settings = get_default_app_settings()
        default_css_state = get_default_css_ui_state()
        default_settings["css_ui_state"] = default_css_state
        fonts_dir = getattr(self, "fonts_dir", "")
        default_css = build_css_content(default_css_state, fonts_dir)
        return {
            "name": "",
            "settings": default_settings,
            "css_content": default_css,
        }

    def reset_to_default_preset(self, show_alert=True):
        payload = self._build_default_reset_payload()
        if self._apply_preset_payload(payload, selected_name="", reset_default_tokens=True):
            logger.info("Настройки и стили сброшены к значениям по умолчанию (пресет «Нет»)")
            if show_alert:
                show_themed_message(self, tr("common.success"), tr("settings.msg_preset_reset_default"), "info")
            return True
        self.refresh_user_presets_combo(selected_name=self.app_settings.get("active_user_preset", ""))
        return False

    def on_user_preset_activated(self, _idx):
        if not hasattr(self, "user_preset_combo"):
            return
        if self.user_preset_combo.currentData() == self._PRESET_NONE_DATA:
            self.reset_to_default_preset()

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

    def _sync_ui_after_preset_apply(self, active_name):
        # 1. Пересобираем только страницу настроек на месте (очередь, поиск и WebView превью не пересоздаются)
        if hasattr(self, "pages") and hasattr(self, "create_settings_page"):
            cur_page = self.pages.currentIndex()
            old_settings_page = getattr(self, "page_settings", None)
            settings_idx = self.pages.indexOf(old_settings_page) if old_settings_page is not None else -1
            if settings_idx >= 0:
                new_settings_page = QWidget()
                self.create_settings_page(new_settings_page)
                self.pages.removeWidget(old_settings_page)
                old_settings_page.deleteLater()
                self.pages.insertWidget(settings_idx, new_settings_page)
                self.page_settings = new_settings_page
                if hasattr(self, "switch_page"):
                    self.switch_page(cur_page)

        # 2. Обновляем страницу конвертера на месте (без сброса таблицы, поиска, фильтров и выделения)
        fmt_val = self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT)
        if hasattr(self, "format_combo"):
            idx = self.format_combo.findData(fmt_val)
            if idx >= 0 and self.format_combo.currentIndex() != idx:
                self.format_combo.blockSignals(True)
                self.format_combo.setCurrentIndex(idx)
                self.format_combo.blockSignals(False)
        if hasattr(self, "_refresh_all_target_filenames"):
            self._refresh_all_target_filenames()
        if hasattr(self, "update_header_status"):
            self.update_header_status()
        if hasattr(self, "update_convert_button_text"):
            self.update_convert_button_text()

        # 3. Обновляем страницу стилей на месте
        for attr, skey, default_val in (
            ("grayscale_cb", "grayscale", "none"),
            ("image_color_profile_cb", "image_color_profile", "none"),
            ("fit_to_screen_cb", "fit_to_screen", "false"),
            ("cover_resize_cb", "cover_resize", "keepAR"),
        ):
            cb = getattr(self, attr, None)
            if cb is not None and hasattr(self, "_set_combo_by_data"):
                cb.blockSignals(True)
                self._set_combo_by_data(cb, str(self.app_settings.get(skey, default_val)))
                cb.blockSignals(False)

        self.load_and_parse_css_to_gui()
        if hasattr(self, "sync_style_color_palettes"):
            self.sync_style_color_palettes()
        self.save_visual_css(show_alert=False)
        if hasattr(self, "_refresh_halos"):
            self._refresh_halos()
        self.refresh_user_presets_combo(selected_name=active_name)
        self.refresh_preview()

    def _apply_preset_payload(self, payload, selected_name=None, *, reset_default_tokens=False):
        if self._has_blocking_workers():
            logger.warning("Применение пресета отклонено: активны фоновые задачи")
            show_themed_message(self, tr("common.warning"), tr("common.busy_workers_warning"), "warning")
            return False
        preset_settings = payload.get("settings") or {}
        has_css_ui_state = isinstance(preset_settings.get("css_ui_state"), dict) and bool(preset_settings.get("css_ui_state"))
        apply_preset_to_settings(self.app_settings, payload, reset_default_tokens=reset_default_tokens)
        active_name = (payload.get("name") or "") if selected_name is None else selected_name
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
        self._sync_ui_after_preset_apply(active_name)
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
        if item == self._PRESET_NONE_DATA:
            self.reset_to_default_preset()
            return
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
            self.refresh_user_presets_combo(selected_name=self.app_settings.get("active_user_preset", ""))
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

import os
import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFileDialog, QInputDialog

from core.config import (
    DEFAULT_OUTPUT_FORMAT,
    DEVICE_PROFILES,
    load_app_settings as load_settings_file,
    save_app_settings as save_settings_file,
    sync_settings_from_fbc_config as sync_fbc_config,
    update_fbc_config_file as write_fbc_config,
)
from core.email_sender import (
    is_email_auto_send_ready as check_email_auto_ready,
    is_smtp_configured,
)
from core.fb2_processor import should_skip_existing_conversion, simulate_fbc_target
from core.i18n import tr
from core.logger import get_log_file_path, get_logger
from core.metadata_lookup import DEFAULT_ENABLED_PROVIDERS, DEFAULT_PROVIDER_ORDER
from core.s2k_manager import check_directory_access, check_sync_format_compatibility, detect_mounted_readers
from core.workers import DeviceSyncWorker, TestEmailWorker
from ui.dialogs import ConversionProgressDialog, show_themed_confirm, show_themed_message

logger = get_logger("app")


class SettingsController:
    """Контроллер настроек приложения, профилей устройств, SMTP и синхронизации ридера."""

    def _set_setting(self, key, value, *, update_fbc=True, refresh_preview=False, debounce=False):
        """Унифицированное обновление параметра настроек с сохранением и синхронизацией config.yaml."""
        self.app_settings[key] = value
        if debounce:
            self._schedule_settings_save(update_fbc_config=update_fbc)
        else:
            self.save_app_settings()
            if update_fbc:
                self.update_fbc_config_file()
        if refresh_preview:
            self.refresh_preview()

    def on_footnotes_mode_changed(self, val):
        self._set_setting("footnotes_mode", str(val or "float"))

    def on_soft_hyphen_changed(self, val):
        self._set_setting("insert_soft_hyphen", str(val or "false"))

    def on_dropcaps_enable_changed(self, val):
        self._set_setting("dropcaps_enable", str(val or "true"))

    def on_fn_translit_changed(self, val):
        self._set_setting("file_name_transliterate", str(val or "false"))

    def on_meta_translit_changed(self, val):
        self._set_setting("meta_transliterate", str(val or "false"))

    def on_fbc_bool_setting_changed(self, key, val):
        self._set_setting(key, str(val or "false"))

    def on_toc_placement_changed(self, val):
        v = str(val or "after")
        self._set_setting("toc_page_placement", v if v in ("none", "before", "after") else "after")

    def on_toc_type_changed(self, val):
        v = str(val or "normal")
        self._set_setting("toc_type", v if v in ("normal", "old_kindle", "flat") else "normal")

    def on_page_map_size_changed(self, val):
        digits = str(val or "").strip()
        if digits.isdigit():
            self._set_setting("page_map_size", digits, debounce=True)

    def on_image_scale_changed(self, val):
        if val:
            self._set_setting("image_scale_factor", str(val).strip())

    def on_skip_existing_toggled(self, checked):
        self._set_setting("skip_existing", "true" if checked else "false", update_fbc=False)

    def on_raster_format_changed(self, val):
        self._set_setting("raster_format", val, refresh_preview=True)

    def on_rasterize_svg_changed(self, val):
        self._set_setting("rasterize_svg", val, refresh_preview=True)

    def on_remove_transparency_changed(self, val):
        self._set_setting("remove_transparency", val)

    def on_optimize_images_changed(self, val):
        self._set_setting("optimize_images", val)

    def on_jpeg_quality_changed(self, val):
        if val:
            self._set_setting("jpeg_quality_level", val)

    def on_azw3_compression_changed(self, val):
        self._set_setting("azw3_compression", val)

    def on_kfx_compression_changed(self, val):
        self._set_setting("kfx_compression", val)

    def on_azw3_apnx_changed(self, val):
        self._set_setting("azw3_apnx", val)

    def on_markdown_images_changed(self, val):
        self._set_setting("markdown_images", val)

    def on_convert_workers_changed(self, val):
        self._set_setting("convert_workers", str(val or "auto"), update_fbc=False)

    def on_baseline_jpeg_changed(self, val):
        self._set_setting("baseline_jpeg", val)

    def on_grayscale_changed(self, idx=None):
        self._set_setting("grayscale", self._get_combo_data(self.grayscale_cb, "none"), refresh_preview=True)

    def on_image_color_profile_changed(self, idx=None):
        self.app_settings.pop("image_color_profile_custom", None)
        self._set_setting(
            "image_color_profile",
            self._get_combo_data(self.image_color_profile_cb, "none"),
            update_fbc=False,
            refresh_preview=True,
        )

    def on_fit_to_screen_changed(self, idx=None):
        self._set_setting("fit_to_screen", self._get_combo_data(self.fit_to_screen_cb, "false"))

    def on_cover_resize_changed(self, idx=None):
        self._set_setting("cover_resize", self._get_combo_data(self.cover_resize_cb, "keepAR"))

    def _schedule_settings_save(self, update_fbc_config=False):
        self._pending_settings_save = True
        if update_fbc_config:
            self._pending_fbc_config_save = True
        self._settings_save_timer.start()

    def _flush_pending_settings(self):
        if self._settings_save_timer.isActive():
            self._settings_save_timer.stop()
        need_settings = self._pending_settings_save
        need_fbc = self._pending_fbc_config_save
        self._pending_settings_save = False
        self._pending_fbc_config_save = False
        if need_settings:
            self.save_app_settings()
        if need_fbc:
            self.update_fbc_config_file()

    def load_app_settings(self):
        load_settings_file(self.settings_path, self.app_settings)

    def save_app_settings(self):
        save_settings_file(self.settings_path, self.app_settings)

    def sync_settings_from_fbc_config(self):
        sync_fbc_config(self.fbc_config_path, self.app_settings)

    def update_fbc_config_file(self):
        write_fbc_config(self.fbc_config_path, self.css_path, self.app_settings)

    def _set_device_profile_combo(self, profile_key):
        if hasattr(self, "device_profile_combo"):
            idx = self.device_profile_combo.findData(profile_key)
            if idx >= 0 and self.device_profile_combo.currentIndex() != idx:
                self.device_profile_combo.blockSignals(True)
                self.device_profile_combo.setCurrentIndex(idx)
                self.device_profile_combo.blockSignals(False)

    def on_format_changed(self, fmt_val):
        if not fmt_val:
            return
        self.app_settings["output_format"] = fmt_val
        if not getattr(self, "_applying_device_profile", False):
            cur_prof = self.app_settings.get("device_profile", "custom")
            preset = DEVICE_PROFILES.get(cur_prof)
            if preset and preset.get("output_format") != fmt_val:
                self.app_settings["device_profile"] = "custom"
                self._set_device_profile_combo("custom")
        self.save_app_settings()
        self.update_header_status()
        if hasattr(self, "format_selector") and self.format_selector.get() != fmt_val:
            self.format_selector.set(fmt_val)
        if hasattr(self, "format_combo"):
            idx = self.format_combo.findData(fmt_val)
            if idx >= 0 and self.format_combo.currentIndex() != idx:
                self.format_combo.blockSignals(True)
                self.format_combo.setCurrentIndex(idx)
                self.format_combo.blockSignals(False)
        self._refresh_all_target_filenames()
        self._refresh_filename_builder_preview()

    def on_device_profile_changed(self, profile_key):
        key = str(profile_key or "custom").strip().lower()
        self.app_settings["device_profile"] = key
        self._set_device_profile_combo(key)
        preset = DEVICE_PROFILES.get(key)
        if not preset:
            self.save_app_settings()
            return

        self._applying_device_profile = True
        try:
            for k, v in preset.items():
                self.app_settings[k] = str(v)

            fmt_val = preset.get("output_format")
            if fmt_val:
                if hasattr(self, "format_selector"):
                    self.format_selector.set(fmt_val)
                if hasattr(self, "format_combo"):
                    idx = self.format_combo.findData(fmt_val)
                    if idx >= 0:
                        self.format_combo.blockSignals(True)
                        self.format_combo.setCurrentIndex(idx)
                        self.format_combo.blockSignals(False)

            for attr, skey in (
                ("screen_w_edit", "screen_width"),
                ("screen_h_edit", "screen_height"),
                ("screen_dpi_edit", "screen_dpi"),
            ):
                if skey in preset and hasattr(self, attr):
                    ed = getattr(self, attr)
                    ed.blockSignals(True)
                    ed.setText(str(preset[skey]))
                    ed.blockSignals(False)

            selector_sync = [
                ("footnotes_mode_selector", "footnotes_mode"),
                ("rem_trans_selector", "remove_transparency"),
                ("rasterize_svg_selector", "rasterize_svg"),
                ("kfx_comp_selector", "kfx_compression"),
                ("optimize_img_selector", "optimize_images"),
            ]
            for attr, skey in selector_sync:
                if skey in preset and hasattr(self, attr):
                    getattr(self, attr).set(str(preset[skey]))

            for attr, skey in (
                ("grayscale_cb", "grayscale"),
                ("image_color_profile_cb", "image_color_profile"),
                ("fit_to_screen_cb", "fit_to_screen"),
                ("cover_resize_cb", "cover_resize"),
            ):
                if skey in preset and hasattr(self, attr):
                    cb = getattr(self, attr)
                    cb.blockSignals(True)
                    self._set_combo_by_data(cb, str(preset[skey]))
                    cb.blockSignals(False)

            if "jpeg_quality_level" in preset and hasattr(self, "jpeg_qual_cb"):
                self.jpeg_qual_cb.blockSignals(True)
                self.jpeg_qual_cb.setCurrentText(str(preset["jpeg_quality_level"]))
                self.jpeg_qual_cb.blockSignals(False)

            self.save_app_settings()
            self.update_fbc_config_file()
            self.update_header_status()
            self._refresh_all_target_filenames()
            self._refresh_filename_builder_preview()
            self.refresh_preview()
            logger.info("Применён профиль устройства: %s", key)
        finally:
            self._applying_device_profile = False

    def on_screen_param_changed(self, key, val):
        digits = val.strip()
        if not digits.isdigit():
            return
        self.app_settings[key] = digits
        if not getattr(self, "_applying_device_profile", False):
            self.app_settings["device_profile"] = "custom"
            self._set_device_profile_combo("custom")
        self._schedule_settings_save(update_fbc_config=True)

    def on_filename_mode_changed(self, mode_val):
        mode = "custom" if mode_val == "custom" else "default"
        self.app_settings["filename_mode"] = mode
        self.save_app_settings()
        self.update_fbc_config_file()
        if hasattr(self, "filename_builder"):
            self.filename_builder.setVisible(mode == "custom")
        self._refresh_all_target_filenames()

    def on_filename_tokens_changed(self, tokens):
        self.app_settings["filename_tokens"] = tokens
        self.save_app_settings()
        self.update_fbc_config_file()
        self._refresh_all_target_filenames()

    def on_title_template_mode_changed(self, mode_val):
        mode = "custom" if mode_val == "custom" else "filename"
        self.app_settings["title_template_mode"] = mode
        self.save_app_settings()
        self.update_fbc_config_file()
        if hasattr(self, "title_template_builder"):
            self.title_template_builder.setVisible(mode == "custom")

    def on_title_template_tokens_changed(self, tokens):
        self.app_settings["title_template_tokens"] = tokens
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_save_mode_changed(self, mode_val):
        self.app_settings["save_mode"] = mode_val
        self.save_app_settings()
        self.btn_choose_dir.setEnabled(mode_val == "custom")
        self.update_header_status()

    def choose_custom_output_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            tr("settings.dlg_choose_dir"),
            self.app_settings.get("custom_output_dir", os.path.expanduser("~"))
        )
        if folder:
            self.app_settings["custom_output_dir"] = folder
            self.lbl_custom_dir.setText(folder)
            self.save_app_settings()

    def is_email_auto_send_ready(self):
        return check_email_auto_ready(self.app_settings)

    def update_convert_button_text(self):
        if not hasattr(self, "btn_convert"):
            return
        if self.is_email_auto_send_ready():
            self.btn_convert.setText(tr("converter.btn_convert_send"))
        else:
            self.btn_convert.setText(tr("converter.btn_convert"))

    def on_email_auto_changed(self, val):
        self.app_settings["email_auto_send"] = val
        self.save_app_settings()
        self.update_convert_button_text()

    def on_email_field_changed(self, key, val):
        self.app_settings[key] = val.strip() if key != "smtp_password" else val
        self.update_convert_button_text()
        self._schedule_settings_save(update_fbc_config=False)

    def send_test_email_clicked(self):
        if getattr(self, "_test_email_worker", None) is not None and self._test_email_worker.isRunning():
            return
        if not is_smtp_configured(self.app_settings):
            show_themed_message(self, tr("common.warning"), tr("settings.email_test_incomplete"), "warning")
            return
        if hasattr(self, "btn_test_email"):
            self.btn_test_email.setEnabled(False)
            self.btn_test_email.setText(tr("settings.btn_test_email_sending"))
        worker = TestEmailWorker(
            dict(self.app_settings),
            app_name=self.app_name,
            app_version=self.app_version,
            parent=self,
        )
        self._test_email_worker = worker
        worker.finished_test.connect(self._on_test_email_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_test_email_finished(self, ok, err_msg):
        self._test_email_worker = None
        if getattr(self, "_closing", False):
            return
        if hasattr(self, "btn_test_email"):
            try:
                self.btn_test_email.setEnabled(True)
                self.btn_test_email.setText(tr("settings.btn_test_email"))
            except RuntimeError:
                pass
        if ok:
            recipient = self.app_settings.get("email_to", "").strip()
            logger.info("Тестовое письмо SMTP успешно отправлено на %s", recipient)
            show_themed_message(self, tr("common.success"), tr("settings.email_test_ok", email=recipient), "info")
        else:
            logger.error("Ошибка отправки тестового письма SMTP: %s", err_msg)
            show_themed_message(self, tr("converter.err_email_title"), tr("settings.email_test_err", e=err_msg), "error")

    def on_device_sync_mode_changed(self, val):
        mode = str(val or "mtp").strip().lower()
        if mode not in ("mtp", "usb", "folder"):
            mode = "mtp"
        self.app_settings["device_sync_mode"] = mode
        self.save_app_settings()
        if hasattr(self, "btn_choose_sync_target"):
            self.btn_choose_sync_target.setEnabled(mode == "folder")
            self.btn_choose_sync_target.setToolTip(
                tr("settings.dlg_choose_sync_dir") if mode == "folder" else tr("settings.tip_choose_sync_dir_mtp")
            )

    def on_device_sync_target_changed(self, val):
        self.app_settings["device_sync_target"] = str(val or "").strip()
        self._schedule_settings_save(update_fbc_config=False)

    def on_device_sync_ignore_removals_changed(self, val):
        self.app_settings["device_sync_ignore_removals"] = "true" if str(val).lower() == "true" else "false"
        self.save_app_settings()

    def on_metadata_provider_toggled(self, provider_id, checked):
        cur = set(self.app_settings.get("metadata_providers") or DEFAULT_ENABLED_PROVIDERS)
        if checked:
            cur.add(provider_id)
        else:
            cur.discard(provider_id)
        self.app_settings["metadata_providers"] = [p for p in DEFAULT_PROVIDER_ORDER if p in cur]
        self.save_app_settings()

    def on_google_books_key_changed(self, val):
        self.app_settings["google_books_api_key"] = str(val or "").strip()
        self._schedule_settings_save(update_fbc_config=False)

    def on_opds_field_changed(self, key, val):
        if key not in ("opds_url", "opds_username", "opds_password"):
            return
        self.app_settings[key] = str(val or "").strip() if key != "opds_password" else str(val or "")
        self._schedule_settings_save(update_fbc_config=False)

    def choose_device_sync_target_dir(self):
        cur = self.app_settings.get("device_sync_target", "")
        start_dir = cur if (cur and os.path.isdir(cur)) else os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, tr("settings.dlg_choose_sync_dir"), start_dir)
        if folder:
            self.app_settings["device_sync_target"] = folder
            if hasattr(self, "device_sync_target_edit"):
                self.device_sync_target_edit.setText(folder)
            self.save_app_settings()

    def detect_device_sync_target_clicked(self):
        """Автоматически находит подключённые USB-ридеры (Kobo, Kindle, PocketBook, BOOX) и облачные папки Kobo."""
        found = detect_mounted_readers()
        if not found:
            show_themed_message(self, tr("settings.sync_title"), tr("settings.msg_detect_reader_none"), "info")
            return
        if len(found) == 1:
            chosen = found[0]
        else:
            labels = [f"{d['name']} — {d['path']}" for d in found]
            label, ok = QInputDialog.getItem(
                self,
                tr("settings.dlg_detect_reader_title"),
                tr("settings.dlg_detect_reader_prompt"),
                labels,
                0,
                False,
            )
            if not ok or label not in labels:
                return
            chosen = found[labels.index(label)]

        self.on_device_sync_mode_changed("folder")
        if hasattr(self, "device_sync_mode_selector"):
            self.device_sync_mode_selector.set("folder")
        self.app_settings["device_sync_target"] = chosen["path"]
        if hasattr(self, "device_sync_target_edit"):
            self.device_sync_target_edit.setText(chosen["path"])
        self.save_app_settings()
        show_themed_message(
            self,
            tr("settings.sync_title"),
            tr("settings.msg_detect_reader_ok", name=chosen["name"], path=chosen["path"]),
            "info",
        )

    def _resolve_device_sync_source_dir(self):
        if self.app_settings.get("save_mode") == "custom":
            cdir = (self.app_settings.get("custom_output_dir") or "").strip()
            if cdir and os.path.isdir(cdir):
                return cdir
        for data in self.files_data.values():
            p = data.get("path")
            if p:
                d = os.path.dirname(os.path.abspath(p))
                if os.path.isdir(d):
                    return d
        cdir = (self.app_settings.get("custom_output_dir") or "").strip()
        home_dir = os.path.abspath(os.path.expanduser("~"))
        if cdir and os.path.isdir(cdir) and os.path.abspath(cdir) != home_dir:
            return cdir
        return ""

    def _set_sync_buttons_enabled(self, enabled):
        for attr in ("btn_sync_now", "btn_sync_dry_run", "btn_sync_device"):
            btn = getattr(self, attr, None)
            if btn is not None:
                try:
                    btn.setEnabled(enabled)
                except RuntimeError:
                    pass

    def _on_device_sync_cancel_requested(self):
        self._device_sync_cancelled = True
        worker = getattr(self, "_device_sync_worker", None)
        if worker is not None:
            worker.cancel()

    def _sync_mode_display_name(self, mode):
        m = str(mode or "mtp").strip().lower()
        if m == "usb":
            return tr("settings.opt_sync_usb")
        if m == "folder":
            return tr("settings.opt_sync_folder")
        return tr("settings.opt_sync_mtp")

    def _collect_unconverted_queue_items(self, target_format):
        """Возвращает книги из очереди, для которых ещё нет актуального сконвертированного файла."""
        pending = []
        save_mode = self.app_settings.get("save_mode", "source")
        custom_dir = (self.app_settings.get("custom_output_dir") or "").strip()
        fn_mode = self.app_settings.get("filename_mode", "default")
        fn_tokens = self.app_settings.get("filename_tokens")
        for item_id, data in self.files_data.items():
            if not isinstance(data, dict) or not data.get("path"):
                continue
            target_name = simulate_fbc_target(data.get("meta") or {}, target_format, fn_mode, fn_tokens)
            if save_mode == "custom" and custom_dir and os.path.isdir(custom_dir):
                dest_dir = custom_dir
            else:
                dest_dir = os.path.dirname(os.path.abspath(data["path"]))
            if not should_skip_existing_conversion(data, dest_dir, target_name):
                data["item_id"] = item_id
                pending.append(data)
        return pending

    def _collect_existing_queue_output_files(self, target_format):
        """Возвращает пути уже существующих сконвертированных файлов для книг из очереди."""
        found = []
        seen = set()
        save_mode = self.app_settings.get("save_mode", "source")
        custom_dir = (self.app_settings.get("custom_output_dir") or "").strip()
        fn_mode = self.app_settings.get("filename_mode", "default")
        fn_tokens = self.app_settings.get("filename_tokens")
        for data in self.files_data.values():
            if not isinstance(data, dict) or not data.get("path"):
                continue
            target_name = simulate_fbc_target(data.get("meta") or {}, target_format, fn_mode, fn_tokens)
            if save_mode == "custom" and custom_dir and os.path.isdir(custom_dir):
                dest_dir = custom_dir
            else:
                dest_dir = os.path.dirname(os.path.abspath(data["path"]))
            cand = os.path.join(dest_dir, target_name)
            norm = os.path.normcase(os.path.abspath(cand))
            if norm not in seen and os.path.isfile(cand):
                seen.add(norm)
                found.append(cand)
        return found

    def send_to_reader_clicked(self):
        """Умная отправка на ридер: проверка формата под устройство → конвертация при необходимости → отправка."""
        if getattr(self, "_device_sync_worker", None) is not None and self._device_sync_worker.isRunning():
            return
        if getattr(self, "_convert_worker", None) is not None and self._convert_worker.isRunning():
            return

        mode = str(self.app_settings.get("device_sync_mode", "mtp")).strip().lower()
        cur_fmt = str(self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT)).strip().lower()
        profile = str(self.app_settings.get("device_profile", "custom")).strip().lower()

        compat = check_sync_format_compatibility(mode, cur_fmt, device_profile=profile)
        if not compat["compatible"]:
            recommended = compat["recommended"]
            supported_str = ", ".join(f.upper() for f in compat["supported"])
            confirmed = show_themed_confirm(
                self,
                tr("settings.sync_fmt_mismatch_title"),
                tr(
                    "settings.sync_fmt_mismatch_msg",
                    fmt=cur_fmt.upper(),
                    mode=self._sync_mode_display_name(mode),
                    supported=supported_str,
                    recommended=recommended.upper(),
                ),
                tr("settings.sync_fmt_switch_btn", recommended=recommended.upper()),
                icon_type="warning",
            )
            if not confirmed:
                return
            self.on_format_changed(recommended)
            cur_fmt = recommended

        target_dir = str(self.app_settings.get("device_sync_target", "documents/books")).strip()
        if mode == "folder":
            if not target_dir or not os.path.isdir(target_dir):
                self.choose_device_sync_target_dir()
                target_dir = str(self.app_settings.get("device_sync_target", "")).strip()
                if not target_dir or not os.path.isdir(target_dir):
                    return
            tgt_access = check_directory_access(target_dir)
            if tgt_access["protected"]:
                logger.error("Ранняя проверка доступа: папка ридера защищена ОС (%s)", target_dir)
                self._show_sync_permission_dialog(target_dir, dry_run=False)
                return

        ignore_del = str(self.app_settings.get("device_sync_ignore_removals", "true")).lower() == "true"
        existing_files = self._collect_existing_queue_output_files(cur_fmt) if self.files_data else []
        if self.files_data:
            pending_items = self._collect_unconverted_queue_items(cur_fmt)
            if pending_items:
                self._run_conversion(
                    pending_items,
                    debug=False,
                    device_sync_params={
                        "mode": mode,
                        "target_dir": target_dir,
                        "ignore_device_removals": ignore_del,
                        "dry_run": False,
                        "existing_files": existing_files,
                        "source_dir": self._resolve_device_sync_source_dir(),
                    },
                )
                return

        self.run_device_sync(
            dry_run=False,
            explicit_files=existing_files,
        )

    def _show_sync_permission_dialog(self, folder_path, dry_run=False):
        title = tr("settings.sync_title_dry") if dry_run else tr("settings.sync_title")
        msg = tr("settings.sync_err_permission", source=os.path.abspath(folder_path))
        if sys.platform == "darwin":
            if show_themed_confirm(
                self,
                title,
                msg,
                tr("settings.btn_open_macos_privacy"),
                cancel_label=tr("common.ok"),
                icon_type="error",
            ):
                QDesktopServices.openUrl(
                    QUrl("x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders")
                )
        else:
            show_themed_message(self, title, msg, "error")

    def run_device_sync(self, dry_run=False, source_dir_override="", explicit_files=None):
        if getattr(self, "_device_sync_worker", None) is not None and self._device_sync_worker.isRunning():
            return
        source_dir = (
            source_dir_override
            if (source_dir_override and os.path.isdir(source_dir_override))
            else self._resolve_device_sync_source_dir()
        )
        if not source_dir:
            show_themed_message(self, tr("common.warning"), tr("settings.sync_err_no_source"), "warning")
            return
        if explicit_files is None and self.files_data:
            cur_fmt = str(self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT)).strip().lower()
            explicit_files = self._collect_existing_queue_output_files(cur_fmt)
        if not explicit_files:
            src_access = check_directory_access(source_dir)
            if src_access["protected"]:
                logger.error("Ранняя проверка доступа: папка защищена ОС (%s)", source_dir)
                self._show_sync_permission_dialog(source_dir, dry_run=dry_run)
                return
        mode = str(self.app_settings.get("device_sync_mode", "mtp")).strip().lower()
        target_dir = str(self.app_settings.get("device_sync_target", "documents/books")).strip()
        if mode == "folder":
            if not target_dir or not os.path.isdir(target_dir):
                self.choose_device_sync_target_dir()
                target_dir = str(self.app_settings.get("device_sync_target", "")).strip()
                if not target_dir or not os.path.isdir(target_dir):
                    return
            tgt_access = check_directory_access(target_dir)
            if tgt_access["protected"]:
                logger.error("Ранняя проверка доступа: папка ридера защищена ОС (%s)", target_dir)
                self._show_sync_permission_dialog(target_dir, dry_run=dry_run)
                return
        ignore_del = str(self.app_settings.get("device_sync_ignore_removals", "true")).lower() == "true"
        self._set_sync_buttons_enabled(False)
        self._s2k_setup_dlg = None
        self._device_sync_cancelled = False
        dlg_title = tr("settings.sync_title_dry") if dry_run else tr("settings.sync_title")
        sync_dlg = ConversionProgressDialog(
            self,
            0,
            secondary_mode="sync",
            show_convert=False,
            custom_title=dlg_title,
        )
        self._s2k_setup_dlg = sync_dlg
        worker = DeviceSyncWorker(
            mode=mode,
            source_dir=source_dir,
            target_dir=target_dir,
            user_data_dir=self.base_dir,
            dry_run=dry_run,
            ignore_device_removals=ignore_del,
            explicit_files=explicit_files,
            parent=self,
        )
        self._device_sync_worker = worker
        sync_dlg.cancel_requested.connect(self._on_device_sync_cancel_requested)
        worker.sync_progress.connect(sync_dlg.update_secondary)
        worker.finished_sync.connect(self._on_device_sync_finished)
        worker.finished.connect(worker.deleteLater)
        sync_dlg.open()
        worker.start()

    def _on_device_sync_finished(self, ok, output, dry_run):
        worker = getattr(self, "_device_sync_worker", None)
        self._device_sync_worker = None
        if getattr(self, "_closing", False):
            return
        dlg = getattr(self, "_s2k_setup_dlg", None)
        self._s2k_setup_dlg = None
        if dlg is not None:
            try:
                dlg.finish_and_close()
            except RuntimeError:
                pass
        self._set_sync_buttons_enabled(True)
        if getattr(self, "_device_sync_cancelled", False):
            self._device_sync_cancelled = False
            return
        title = tr("settings.sync_title_dry") if dry_run else tr("settings.sync_title")
        if ok:
            logger.info("Синхронизация с ридером завершена (dry_run=%s)", dry_run)
            show_themed_message(self, title, output, "info")
        else:
            logger.error("Ошибка синхронизации с ридером: %s", output)
            if worker is not None and getattr(worker, "last_error_code", "") == "permission":
                self._show_sync_permission_dialog(
                    getattr(worker, "last_error_path", "") or self._resolve_device_sync_source_dir(),
                    dry_run=dry_run,
                )
            else:
                show_themed_message(self, title, output, "error")

    def open_log_file(self):
        log_path = get_log_file_path() or self.log_path
        if log_path and os.path.isfile(log_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(log_path)))
        else:
            show_themed_message(self, tr("common.info"), tr("about.err_no_log", path=log_path), "info")

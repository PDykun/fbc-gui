import os

from PyQt6.QtCore import Qt, QTimer

from core.config import DEFAULT_OUTPUT_FORMAT
from core.fb2_processor import copy_meta_dict
from core.i18n import tr
from core.logger import get_logger
from core.workers import ConversionWorker, DeviceSyncWorker
from ui.dialogs import (
    ConversionProgressDialog,
    show_conversion_summary_dialog,
    show_themed_message,
)

logger = get_logger("app")


class ConversionController:
    """Контроллер запуска и отслеживания пакетной конвертации книг."""

    def convert_all(self, debug=False):
        items = []
        for item_id, data in self.files_data.items():
            data["item_id"] = item_id
            items.append(data)
        self._run_conversion(items, debug=debug)

    def convert_selected(self, debug=False):
        selected_rows = sorted({
            idx.row() for idx in self.table.selectionModel().selectedRows()
            if not self.table.isRowHidden(idx.row())
        })
        items = []
        for r in selected_rows:
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if data:
                data["item_id"] = item_id
                items.append(data)
        self._run_conversion(items, debug=debug)

    def _prepare_conversion_params(self, debug, device_sync_params):
        selected_format = self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT)
        compression = None
        if selected_format == "azw3":
            compression = self.app_settings.get("azw3_compression", "standard")
        elif selected_format in ("kfx", "azw8"):
            compression = self.app_settings.get("kfx_compression", "none")

        sync_enabled = bool(device_sync_params) and not debug
        email_enabled = self.is_email_auto_send_ready() and not debug and not sync_enabled
        return {
            "selected_format": selected_format,
            "save_mode": self.app_settings.get("save_mode", "source"),
            "custom_dir": self.app_settings.get("custom_output_dir", ""),
            "title_style_params": self._get_title_style_params(),
            "compression": compression,
            "no_cover": str(self.app_settings.get("no_cover", "false")).lower() == "true",
            "skip_existing": str(self.app_settings.get("skip_existing", "false")).lower() == "true",
            "sync_enabled": sync_enabled,
            "email_enabled": email_enabled,
            "secondary_mode": "sync" if sync_enabled else ("email" if email_enabled else None),
        }

    def _start_device_sync_after_conversion(
        self, device_sync_params, save_mode, custom_dir, converted_files, progress_dlg, on_sync_finished
    ):
        sync_files = list(converted_files or [])
        for fp in (device_sync_params.get("existing_files") or []):
            if fp not in sync_files:
                sync_files.append(fp)
        if converted_files:
            if save_mode == "custom" and custom_dir and os.path.isdir(custom_dir):
                sync_src = custom_dir
            else:
                sync_src = os.path.dirname(converted_files[0])
        else:
            sync_src = device_sync_params.get("source_dir") or self._resolve_device_sync_source_dir()

        sync_worker = DeviceSyncWorker(
            mode=device_sync_params.get("mode", "mtp"),
            source_dir=sync_src,
            target_dir=device_sync_params.get("target_dir", "documents/books"),
            user_data_dir=self.base_dir,
            dry_run=bool(device_sync_params.get("dry_run", False)),
            ignore_device_removals=bool(device_sync_params.get("ignore_device_removals", True)),
            explicit_files=sync_files,
            parent=self,
        )
        self._device_sync_worker = sync_worker
        sync_worker.sync_progress.connect(progress_dlg.update_secondary)
        sync_worker.finished_sync.connect(on_sync_finished)
        progress_dlg.cancel_requested.connect(sync_worker.cancel)
        sync_worker.start()
        return sync_worker

    def _resolve_conversion_output_dir(self, save_mode, custom_dir, converted_files, items, debug):
        if converted_files:
            if save_mode == "custom" and custom_dir and os.path.isdir(custom_dir):
                return custom_dir
            return os.path.dirname(converted_files[0])
        if debug and items:
            if save_mode == "custom" and custom_dir and os.path.isdir(custom_dir):
                return custom_dir
            return os.path.dirname(items[0]["path"])
        return None

    def _show_conversion_outcome(
        self, params, items, debug, show_summary_on_success, result_box, sync_box, skipped_count
    ):
        success_count = result_box.get("success_count", 0)
        converted_files = result_box.get("converted_files", [])
        convert_errors = result_box.get("convert_errors", [])
        email_error = result_box.get("email_error", "")
        cancelled = result_box.get("cancelled", False)
        failed_items = result_box.get("failed_items", [])
        output_dir = self._resolve_conversion_output_dir(
            params["save_mode"], params["custom_dir"], converted_files, items, debug
        )
        err_count = len(convert_errors)
        fmt_upper = params["selected_format"].upper()
        want_retry = False

        if cancelled:
            want_retry = show_conversion_summary_dialog(
                self,
                tr("common.info"),
                tr("converter.msg_cancelled", count=success_count),
                icon_type="warning" if err_count else "info",
                errors=convert_errors,
                output_dir=output_dir,
                allow_retry=bool(failed_items),
            )
        elif params["sync_enabled"] and sync_box:
            sync_ok = bool(sync_box.get("ok"))
            sync_sent = int(sync_box.get("sent_count", 0) or 0)
            if not sync_ok:
                if sync_box.get("error_code") == "permission" and hasattr(self, "_show_sync_permission_dialog"):
                    self._show_sync_permission_dialog(sync_box.get("error_path") or output_dir or "", dry_run=False)
                else:
                    want_retry = show_conversion_summary_dialog(
                        self,
                        tr("settings.sync_title"),
                        tr("converter.msg_done_sync_err", count=success_count, e=sync_box.get("output", "")),
                        icon_type="error",
                        errors=convert_errors,
                        output_dir=output_dir,
                        allow_retry=bool(failed_items),
                    )
            else:
                title = tr("converter.err_convert_title") if err_count else tr("common.done")
                summary = (
                    tr("converter.msg_done_sync_with_errors", fmt=fmt_upper, count=success_count, err_count=err_count, sent=sync_sent)
                    if err_count
                    else tr("converter.msg_done_sync", fmt=fmt_upper, count=success_count, sent=sync_sent)
                )
                want_retry = show_conversion_summary_dialog(
                    self, title, summary, icon_type="warning" if err_count else "info",
                    errors=convert_errors, output_dir=output_dir, allow_retry=bool(failed_items),
                )
        elif params["email_enabled"] and converted_files:
            if email_error:
                want_retry = show_conversion_summary_dialog(
                    self, tr("converter.err_email_title"), tr("converter.err_email", count=success_count, e=email_error),
                    icon_type="error", errors=convert_errors, output_dir=output_dir, allow_retry=bool(failed_items),
                )
            else:
                recipient = self.app_settings.get("email_to", "").strip()
                title = tr("converter.err_convert_title") if err_count else tr("common.done")
                summary = (
                    tr("converter.msg_done_email_with_errors", fmt=fmt_upper, count=success_count, err_count=err_count, email=recipient)
                    if err_count
                    else tr("converter.msg_done_email", fmt=fmt_upper, count=success_count, email=recipient)
                )
                want_retry = show_conversion_summary_dialog(
                    self, title, summary, icon_type="warning" if err_count else "info",
                    errors=convert_errors, output_dir=output_dir, allow_retry=bool(failed_items),
                )
        elif err_count or show_summary_on_success:
            skipped_suffix = tr("converter.msg_skipped_suffix", skipped=skipped_count) if skipped_count > 0 else ""
            if err_count:
                title = tr("converter.err_convert_title")
                summary = tr("converter.msg_done_with_errors", fmt=fmt_upper, count=success_count, err_count=err_count) + skipped_suffix
                icon_type = "error" if success_count == 0 else "warning"
            else:
                title = tr("common.done")
                summary = tr("converter.msg_done", fmt=fmt_upper, count=success_count) + skipped_suffix
                icon_type = "info"
            want_retry = show_conversion_summary_dialog(
                self, title, summary, icon_type=icon_type,
                errors=convert_errors, output_dir=output_dir, allow_retry=bool(failed_items),
            )

        return want_retry, output_dir

    def _run_conversion(self, items, debug=False, show_summary_on_success=True, device_sync_params=None):
        if getattr(self, "_convert_worker", None) is not None and self._convert_worker.isRunning():
            logger.warning("Повторный запуск конвертации отклонён: конвертация уже выполняется")
            return None
        if not items:
            show_themed_message(self, tr("common.warning"), tr("converter.warn_empty_list"), "warning")
            return None
        fbc_bin = self.fbc_cmd
        if not fbc_bin or not os.path.isfile(fbc_bin):
            self._ensure_fbc_on_startup(
                interactive=True,
                on_ready=lambda it=items, d=debug, sp=device_sync_params: self._run_conversion(
                    it, debug=d, show_summary_on_success=show_summary_on_success, device_sync_params=sp
                ),
            )
            return None

        self.save_visual_css(show_alert=False)
        self.update_fbc_config_file()
        params = self._prepare_conversion_params(debug, device_sync_params)
        progress_dlg = ConversionProgressDialog(
            self, len(items), show_email=params["email_enabled"], secondary_mode=params["secondary_mode"],
        )
        self._convert_progress_dlg = progress_dlg

        for it in items:
            if it.get("item_id"):
                self._set_item_status(it["item_id"], "", "")

        worker_items = [{**it, "meta": copy_meta_dict(it.get("meta") or {})} for it in items]
        convert_worker = ConversionWorker(
            items=worker_items,
            selected_format=params["selected_format"],
            save_mode=params["save_mode"],
            custom_dir=params["custom_dir"],
            title_style_params=params["title_style_params"],
            compression=params["compression"],
            email_enabled=params["email_enabled"],
            app_settings=dict(self.app_settings),
            debug=debug,
            no_cover=params["no_cover"],
            skip_existing=params["skip_existing"],
            fbc_cmd=fbc_bin,
            fbc_config=self.fbc_config_path,
            base_dir=self.base_dir,
            app_name=self.app_name,
            app_version=self.app_version,
            parent=self,
        )
        self._convert_worker = convert_worker
        convert_worker.convert_progress.connect(progress_dlg.update_conversion)
        convert_worker.email_progress.connect(progress_dlg.update_email)
        convert_worker.item_status.connect(self._set_item_status)
        progress_dlg.cancel_requested.connect(convert_worker.cancel)

        result_box = {}
        sync_box = {}
        current_sync_worker = [None]

        def _on_sync_finished(ok, output, dry_run):
            sync_box["ok"] = ok
            sync_box["output"] = output
            sync_box["dry_run"] = dry_run
            worker = current_sync_worker[0] or getattr(self, "_device_sync_worker", None)
            sync_box["sent_count"] = int(getattr(worker, "sent_count", 0) or 0) if worker else 0
            sync_box["error_code"] = getattr(worker, "last_error_code", "") if worker else ""
            sync_box["error_path"] = getattr(worker, "last_error_path", "") if worker else ""
            progress_dlg.finish_and_close()

        def _on_finished(success_count, converted_files, convert_errors, email_error, cancelled, failed_items):
            effective_cancelled = bool(cancelled or progress_dlg._cancelling)
            result_box.update({
                "success_count": success_count,
                "converted_files": converted_files,
                "convert_errors": convert_errors,
                "email_error": email_error,
                "cancelled": effective_cancelled,
                "failed_items": failed_items,
            })
            if getattr(self, "_closing", False):
                progress_dlg.finish_and_close()
                return
            skipped_cnt = int(getattr(convert_worker, "skipped_count", 0) or 0)
            if params["sync_enabled"] and not effective_cancelled and (
                converted_files or skipped_cnt > 0 or device_sync_params.get("existing_files")
            ):
                current_sync_worker[0] = self._start_device_sync_after_conversion(
                    device_sync_params, params["save_mode"], params["custom_dir"],
                    converted_files, progress_dlg, _on_sync_finished,
                )
            else:
                progress_dlg.finish_and_close()

        from core.workers import stop_qthread_safely

        convert_worker.finished_all.connect(_on_finished)
        convert_worker.start()
        skipped_count = 0
        try:
            progress_dlg.exec()
            stop_qthread_safely(convert_worker, timeout_ms=3000, label="_convert_worker")
            skipped_count = int(getattr(convert_worker, "skipped_count", 0) or 0)
            if current_sync_worker[0] is not None:
                stop_qthread_safely(current_sync_worker[0], timeout_ms=3000, label="_device_sync_worker")
        finally:
            self._convert_progress_dlg = None
            if getattr(self, "_convert_worker", None) is convert_worker:
                self._convert_worker = None
            for sig in (convert_worker.convert_progress, convert_worker.email_progress, convert_worker.finished_all):
                try:
                    sig.disconnect()
                except (TypeError, RuntimeError):
                    pass
            try:
                if not convert_worker.isRunning():
                    convert_worker.deleteLater()
            except RuntimeError:
                pass
            if current_sync_worker[0] is not None:
                sw = current_sync_worker[0]
                if getattr(self, "_device_sync_worker", None) is sw:
                    self._device_sync_worker = None
                for sig in (sw.sync_progress, sw.finished_sync):
                    try:
                        sig.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                try:
                    if not sw.isRunning():
                        sw.deleteLater()
                except RuntimeError:
                    pass
            try:
                progress_dlg.deleteLater()
            except RuntimeError:
                pass

        if getattr(self, "_closing", False):
            return None

        want_retry, output_dir = self._show_conversion_outcome(
            params, items, debug, show_summary_on_success, result_box, sync_box, skipped_count
        )
        failed_items = result_box.get("failed_items", [])
        if want_retry and failed_items:
            QTimer.singleShot(0, lambda fi=failed_items, d=debug: self._run_conversion(fi, debug=d))
        success_count = result_box.get("success_count", 0)
        cancelled = result_box.get("cancelled", False)
        return {
            "ok": (not cancelled) and (success_count > 0 or skipped_count > 0),
            "cancelled": cancelled,
            "success_count": success_count,
            "err_count": len(result_box.get("convert_errors", [])),
            "output_dir": output_dir,
            "converted_files": result_box.get("converted_files", []),
        }

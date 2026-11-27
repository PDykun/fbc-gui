import os
import sys
import time
import webbrowser

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from core.fbc_manager import FBC_TARGET_VERSION, FbcEnsureWorker
from core.i18n import LOCALE, tr
from core.logger import get_logger
from core.updater import (
    DEFAULT_MANIFEST_URL,
    DEFAULT_RELEASES_URL,
    UPDATE_CHECK_INTERVAL_SEC,
    UpdateCheckWorker,
    UpdateDownloadWorker,
    is_safe_http_url,
)
from ui.dialogs import (
    FbcSetupDialog,
    UpdateDownloadDialog,
    show_themed_message,
    show_update_dialog,
)

logger = get_logger("app")


class UpdatesController:
    """Контроллер проверки/установки fb2cng и автообновлений FBC GUI."""

    def _ensure_fbc_on_startup(self, interactive=False, on_ready=None):
        if self._fbc_worker is not None and self._fbc_worker.isRunning():
            if on_ready is not None:
                self._fbc_ready_callback = on_ready
            return

        self._fbc_ready_callback = on_ready
        self._fbc_setup_dlg = None

        if interactive:
            self._open_fbc_setup_dialog(tr("fbc_setup.searching"))

        worker = FbcEnsureWorker(
            user_data_dir=self.base_dir,
            target_version=FBC_TARGET_VERSION,
            allow_download=True,
            parent=self,
        )
        self._fbc_worker = worker
        worker.status_changed.connect(self._on_fbc_status_changed)
        worker.progress_changed.connect(self._on_fbc_progress_changed)
        worker.finished_check.connect(self._on_fbc_check_finished)
        worker.finished.connect(worker.deleteLater)
        if self._fbc_setup_dlg is not None:
            self._fbc_setup_dlg.cancel_requested.connect(worker.cancel)
        worker.start()

    def _open_fbc_setup_dialog(self, status_text):
        if self._fbc_setup_dlg is None:
            self._fbc_setup_dlg = FbcSetupDialog(self, initial_status=status_text)
            if self._fbc_worker is not None:
                self._fbc_setup_dlg.cancel_requested.connect(self._fbc_worker.cancel)
            self._fbc_setup_dlg.open()
        else:
            self._fbc_setup_dlg.set_status_text(status_text)

    def _on_fbc_status_changed(self, status_code):
        if status_code == "searching":
            if self._fbc_setup_dlg is not None:
                self._fbc_setup_dlg.set_status_text(tr("fbc_setup.searching"))
        elif status_code == "verifying":
            if self._fbc_setup_dlg is not None:
                self._fbc_setup_dlg.set_status_text(tr("fbc_setup.verifying"))
        elif status_code.startswith("downloading:"):
            reason = status_code.split(":", 1)[1]
            reason_key = {
                "not_found": "fbc_setup.reason_not_found",
                "incompatible_version": "fbc_setup.reason_incompatible_version",
                "hash_mismatch": "fbc_setup.reason_hash_mismatch",
            }.get(reason, "fbc_setup.reason_default")
            self._open_fbc_setup_dialog(tr(reason_key, ver=FBC_TARGET_VERSION))

    def _on_fbc_progress_changed(self, downloaded, total, asset_name):
        if self._fbc_setup_dlg is None:
            self._open_fbc_setup_dialog(tr("fbc_setup.downloading_generic", name=asset_name))
        self._fbc_setup_dlg.update_download_progress(downloaded, total, asset_name)

    def _on_fbc_check_finished(self, result):
        self._fbc_worker = None
        if getattr(self, "_closing", False):
            return
        dlg = self._fbc_setup_dlg
        self._fbc_setup_dlg = None
        if dlg is not None:
            try:
                dlg.finish_and_close()
            except RuntimeError:
                pass

        cb = self._fbc_ready_callback
        self._fbc_ready_callback = None

        if result.get("ok") and result.get("path"):
            self.fbc_cmd = result["path"]
            if result.get("version"):
                self.fbc_version = result["version"]
                if hasattr(self, "lbl_third_party_ver"):
                    try:
                        self.lbl_third_party_ver.setText(f"<b>{tr('about.third_party_ver', ver=self.fbc_version)}</b>")
                    except RuntimeError:
                        pass
            try:
                self.update_header_status()
            except RuntimeError:
                pass
            if result.get("downloaded") and not cb:
                logger.info("fb2cng v%s успешно установлен в %s", self.fbc_version, self.fbc_cmd)
            if cb is not None:
                QTimer.singleShot(0, cb)
            return

        if result.get("cancelled"):
            return

        err_text = result.get("error") or result.get("reason") or "unknown error"
        retry = show_update_dialog(
            self,
            tr("fbc_setup.err_title"),
            tr("fbc_setup.err_msg", e=err_text),
            tr("fbc_setup.btn_retry"),
            tr("fbc_setup.btn_skip"),
        )
        if retry:
            QTimer.singleShot(0, lambda c=cb: self._ensure_fbc_on_startup(interactive=True, on_ready=c))

    def _schedule_startup_update_check(self):
        last_check = float(self.app_settings.get("last_update_check", 0) or 0)
        if time.time() - last_check >= UPDATE_CHECK_INTERVAL_SEC:
            self.check_for_updates(manual=False)

    def check_for_updates(self, manual=False):
        if self._update_worker is not None and self._update_worker.isRunning():
            return
        if self._update_dl_worker is not None and self._update_dl_worker.isRunning():
            return
        if manual and hasattr(self, "btn_check_updates"):
            self.btn_check_updates.setEnabled(False)
            self.btn_check_updates.setText(tr("about.updates_checking"))

        worker = UpdateCheckWorker(
            self.app_version,
            self.build_number,
            manifest_url=DEFAULT_MANIFEST_URL,
            manual=manual,
            lang=LOCALE.lang_code,
            fallback_url=DEFAULT_RELEASES_URL,
            parent=self,
        )
        self._update_worker = worker
        worker.checked.connect(self._on_update_check_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_update_check_finished(self, result, manual):
        self._update_worker = None
        if getattr(self, "_closing", False):
            return
        if hasattr(self, "btn_check_updates"):
            try:
                self.btn_check_updates.setEnabled(True)
                self.btn_check_updates.setText(tr("about.btn_check_updates"))
            except RuntimeError:
                pass

        if not result.get("error"):
            self.app_settings["last_update_check"] = int(time.time())
            self.save_app_settings()

        if result.get("error"):
            if manual:
                show_themed_message(self, tr("common.error"), tr("about.updates_err", e=result["error"]), "error")
            return

        if result.get("has_update"):
            changelog = result.get("changelog") or ""
            notes = f"\n\n{changelog}" if changelog else ""
            msg = tr(
                "about.update_avail_msg",
                app=self.app_name,
                ver=result.get("version"),
                build=result.get("build"),
                cur_ver=self.app_version,
                cur_build=self.build_number,
                notes=notes,
            )
            can_in_app = bool(result.get("sha256") and is_safe_http_url(result.get("download_url"), allow_relative=False, require_https=True))
            if can_in_app:
                action_label = tr("about.btn_open_dmg_update") if sys.platform == "darwin" else tr("about.btn_install_update")
            else:
                action_label = tr("about.btn_download_update")

            if show_update_dialog(
                self,
                tr("about.update_avail_title"),
                msg,
                action_label,
                tr("about.btn_later"),
            ):
                if can_in_app:
                    self._start_update_download(result)
                else:
                    dl_url = result.get("download_url") or DEFAULT_RELEASES_URL
                    if not is_safe_http_url(dl_url, allow_relative=False, require_https=True):
                        logger.warning("Отклонён небезопасный URL обновления: %s", dl_url)
                        dl_url = DEFAULT_RELEASES_URL
                    webbrowser.open(dl_url)
        elif manual:
            show_themed_message(
                self,
                tr("common.info"),
                tr("about.updates_none", ver=self.app_version, build=self.build_number),
                "info",
            )

    def _start_update_download(self, update_info):
        if self._update_dl_worker is not None and self._update_dl_worker.isRunning():
            return
        ver = update_info.get("version") or ""
        build = int(update_info.get("build") or 0)
        ver_display = f"{ver}.{build}" if (ver == self.app_version and build > 0) else ver
        self._update_dl_dlg = UpdateDownloadDialog(
            self,
            version_str=ver_display,
            initial_status=tr("about.update_dl_preparing", ver=ver_display),
        )
        worker = UpdateDownloadWorker(
            download_url=update_info["download_url"],
            expected_sha256=update_info["sha256"],
            filename=update_info.get("filename", ""),
            kind=update_info.get("kind", "auto"),
            app_version=self.app_version,
            parent=self,
        )
        self._update_dl_worker = worker
        self._update_dl_dlg.cancel_requested.connect(worker.cancel)
        worker.status_changed.connect(self._on_update_dl_status)
        worker.progress_changed.connect(self._on_update_dl_progress)
        worker.finished_download.connect(self._on_update_dl_finished)
        worker.finished.connect(worker.deleteLater)
        self._update_dl_dlg.open()
        worker.start()

    def _on_update_dl_status(self, status_code):
        dlg = getattr(self, "_update_dl_dlg", None)
        if dlg is None:
            return
        if status_code == "verifying":
            dlg.set_status_text(tr("about.update_dl_verifying"), indeterminate=True)
        elif status_code == "installing":
            dlg.set_status_text(tr("about.update_dl_installing"), indeterminate=True)

    def _on_update_dl_progress(self, downloaded, total, asset_name):
        dlg = getattr(self, "_update_dl_dlg", None)
        if dlg is not None:
            dlg.update_download_progress(downloaded, total, asset_name)

    def _on_update_dl_finished(self, result):
        self._update_dl_worker = None
        if getattr(self, "_closing", False):
            return
        dlg = self._update_dl_dlg
        self._update_dl_dlg = None
        if dlg is not None:
            try:
                dlg.finish_and_close()
            except RuntimeError:
                pass

        if result.get("cancelled"):
            return

        if not result.get("ok"):
            err_key = "about.update_sha256_err" if result.get("hash_mismatch") else "about.update_dl_err"
            show_themed_message(self, tr("common.error"), tr(err_key, e=result.get("error", "")), "error")
            return

        if result.get("should_quit"):
            if hasattr(self, "quit_application"):
                QTimer.singleShot(150, self.quit_application)
            else:
                app_inst = QApplication.instance()
                if app_inst is not None:
                    QTimer.singleShot(150, app_inst.quit)
        elif result.get("action") == "dmg_mounted":
            name = os.path.basename(result.get("path", "")) or "FBC GUI.dmg"
            show_themed_message(
                self,
                tr("common.done"),
                tr("about.update_dmg_opened", name=name, app=self.app_name),
                "info",
            )

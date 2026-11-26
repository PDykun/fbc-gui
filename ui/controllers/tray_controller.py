"""Контроллер системного трея / macOS Menu Bar и фоновых папок автоконвертации (Watch Folder)."""

import os
import sys

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QAction, QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QSystemTrayIcon,
    QTableWidgetItem,
    QWidget,
)

from core.autostart import is_autostart_enabled, is_autostart_supported, set_autostart_enabled
from core.i18n import tr
from core.logger import get_logger
from core.notifier import send_system_notification, set_macos_dock_visible
from core.watch_folder import PRESET_CURRENT_TOKEN, WatchFolderManager, normalize_watch_rules
from ui.dialogs import WatchFolderRuleDialog, show_themed_confirm, show_themed_message

logger = get_logger("tray")


class TrayWatchController:
    """Миксин-контроллер MainWindow для системного трея, macOS Menu Bar и Watch Folder."""

    def init_tray_and_watch(self):
        """Инициализирует WatchFolderManager и QSystemTrayIcon после создания UI."""
        self._force_quit = False
        self._tray_icon = None
        self._tray_menu = None
        self._watch_busy = False
        self._watch_busy_label = ""

        # Синхронизируем настройку автозапуска с фактическим состоянием ОС (по умолчанию выкл)
        if is_autostart_supported():
            actual_auto = is_autostart_enabled()
            self.app_settings["autostart_enabled"] = "true" if actual_auto else "false"
            if hasattr(self, "autostart_selector"):
                self.autostart_selector.set(self.app_settings["autostart_enabled"])

        self.watch_manager = WatchFolderManager(
            base_dir=self.base_dir,
            get_fbc_cmd=lambda: self.fbc_cmd,
            get_app_settings=lambda: dict(self.app_settings),
            fbc_config_path=self.fbc_config_path,
            css_path=self.css_path,
            fonts_dir=self.fonts_dir,
            presets_dir=self.presets_dir,
            app_name=self.app_name,
            app_version=self.app_version,
            parent=self,
        )
        self.watch_manager.status_changed.connect(self._on_watch_status_changed)
        self.watch_manager.activity_changed.connect(self._on_watch_activity_changed)
        self.watch_manager.batch_completed.connect(self._on_watch_batch_completed)
        self.watch_manager.folder_error.connect(self._on_watch_folder_error)

        rules = normalize_watch_rules(self.app_settings.get("watch_folders"))
        self.app_settings["watch_folders"] = rules
        self.watch_manager.set_rules(rules)
        if any(r.get("enabled") for r in rules):
            self.watch_manager.start()

        self._sync_tray_icon_state()
        self.refresh_watch_folders_table()

    def _is_bool_setting(self, key, default=False):
        raw = self.app_settings.get(key, "true" if default else "false")
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("true", "1", "yes")

    def is_tray_active(self):
        """Возвращает True, если иконка трея включена и поддерживается системой."""
        return (
            self._is_bool_setting("tray_enabled", False)
            and QSystemTrayIcon.isSystemTrayAvailable()
        )

    def should_minimize_to_tray_on_close(self):
        return self.is_tray_active() and self._is_bool_setting("tray_minimize_on_close", False)

    def _load_tray_qicon(self, active=False):
        icons_dir = getattr(self, "icons_dir", "")
        if sys.platform == "darwin":
            fname = "tray_macos_active_template.png" if active else "tray_macos_template.png"
            fpath = os.path.join(icons_dir, fname) if icons_dir else ""
            if fpath and os.path.isfile(fpath):
                icon = QIcon(fpath)
                icon.setIsMask(True)
                return icon
        else:
            fpath = os.path.join(icons_dir, "tray_win.ico") if icons_dir else ""
            if fpath and os.path.isfile(fpath):
                return QIcon(fpath)
        fallback = self.windowIcon()
        if not fallback.isNull():
            return fallback
        return QApplication.windowIcon()

    def _sync_tray_icon_state(self):
        want_tray = self.is_tray_active()
        app_inst = QApplication.instance()
        if app_inst is not None:
            app_inst.setQuitOnLastWindowClosed(not self.should_minimize_to_tray_on_close())

        if not want_tray:
            if self._tray_icon is not None:
                self._tray_icon.hide()
                self._tray_icon.deleteLater()
                self._tray_icon = None
                self._tray_menu = None
            if sys.platform == "darwin":
                set_macos_dock_visible(True)
            return

        if self._tray_icon is None:
            self._tray_icon = QSystemTrayIcon(self._load_tray_qicon(self._watch_busy), self)
            self._tray_menu = QMenu(self)
            self._tray_icon.setContextMenu(self._tray_menu)
            self._tray_icon.activated.connect(self._on_tray_activated)
            self._tray_icon.show()
        else:
            self._tray_icon.setIcon(self._load_tray_qicon(self._watch_busy))
            if not self._tray_icon.isVisible():
                self._tray_icon.show()

        self.refresh_tray_menu()

    def refresh_tray_menu(self):
        """Пересобирает контекстное меню трея / macOS Menu Bar с актуальным статусом и языком."""
        if self._tray_icon is None or self._tray_menu is None:
            return
        menu = self._tray_menu
        menu.clear()

        mgr = getattr(self, "watch_manager", None)
        active_cnt = mgr.active_rules_count() if mgr else 0
        if self._watch_busy and self._watch_busy_label:
            status_txt = tr("watch.tray_status_busy", name=self._watch_busy_label)
        elif mgr and mgr.paused:
            status_txt = tr("watch.tray_status_paused")
        elif active_cnt > 0:
            status_txt = tr("watch.tray_status_active", count=active_cnt)
        else:
            status_txt = tr("watch.tray_status_idle")

        act_status = QAction(status_txt, menu)
        act_status.setEnabled(False)
        menu.addAction(act_status)
        menu.addSeparator()

        act_show = menu.addAction(tr("watch.tray_open_window"))
        act_show.triggered.connect(self.restore_from_tray)

        if mgr is not None and active_cnt > 0:
            pause_txt = tr("watch.tray_resume") if mgr.paused else tr("watch.tray_pause")
            act_pause = menu.addAction(pause_txt)
            act_pause.triggered.connect(self.toggle_watch_pause)

            folders_menu = menu.addMenu(tr("watch.tray_folders_menu"))
            for rule in mgr.rules:
                if not rule.get("enabled"):
                    continue
                label = rule.get("name") or os.path.basename(rule["folder"])
                act_f = folders_menu.addAction(label)
                folder_path = rule["folder"]
                act_f.triggered.connect(lambda checked=False, p=folder_path: self._open_local_folder(p))

        if mgr is not None and mgr.recent_history:
            recent_menu = menu.addMenu(tr("watch.tray_recent_menu"))
            for rec in list(mgr.recent_history)[:5]:
                mark = "✓" if rec.get("ok") else "✕"
                act_r = recent_menu.addAction(f"{mark} {rec.get('filename', '')} ({rec.get('rule_name', '')})")
                act_r.setEnabled(False)

        act_settings = menu.addAction(tr("watch.tray_settings"))
        act_settings.triggered.connect(self._open_watch_settings)
        menu.addSeparator()

        act_quit = menu.addAction(tr("watch.tray_quit"))
        act_quit.triggered.connect(self.quit_application)

        self._tray_icon.setToolTip(f"{self.app_name} — {status_txt}")

    def _on_tray_activated(self, reason):
        if sys.platform != "darwin" and reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.restore_from_tray()

    def hide_to_tray(self):
        """Скрывает главное окно в трей / Menu Bar (и при опции скрывает иконку из Dock на macOS)."""
        self.hide()
        if sys.platform == "darwin" and self._is_bool_setting("tray_hide_dock_macos", False):
            set_macos_dock_visible(False)

    def restore_from_tray(self):
        """Восстанавливает главное окно из трея / Menu Bar."""
        if sys.platform == "darwin":
            set_macos_dock_visible(True)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _open_watch_settings(self):
        self.restore_from_tray()
        if hasattr(self, "switch_page"):
            self.switch_page(3)

    def _open_local_folder(self, folder_path):
        if folder_path and os.path.isdir(folder_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))

    def toggle_watch_pause(self):
        mgr = getattr(self, "watch_manager", None)
        if mgr is None:
            return
        mgr.set_paused(not mgr.paused)
        self.refresh_watch_folders_table()
        self.refresh_tray_menu()

    def quit_application(self):
        """Полный выход из приложения (минуя сворачивание в трей)."""
        self._force_quit = True
        self.close()
        app_inst = QApplication.instance()
        if app_inst is not None:
            app_inst.quit()

    def _on_watch_status_changed(self):
        self.refresh_tray_menu()
        self.refresh_watch_folders_table()

    def _on_watch_activity_changed(self, busy, label):
        self._watch_busy = bool(busy)
        self._watch_busy_label = str(label or "")
        if self._tray_icon is not None:
            self._tray_icon.setIcon(self._load_tray_qicon(self._watch_busy))
        self.refresh_tray_menu()

    def _on_watch_batch_completed(self, summary):
        self.refresh_tray_menu()
        if not self._is_bool_setting("watch_notifications_enabled", True):
            return
        ok_cnt = int(summary.get("success_count", 0) or 0)
        err_cnt = int(summary.get("error_count", 0) or 0)
        if ok_cnt == 0 and err_cnt == 0:
            return
        rule_name = summary.get("rule_name", "")
        delivery_key = f"watch.delivery_{summary.get('delivery_mode', 'folder')}"
        delivery_lbl = tr(delivery_key)
        if err_cnt and ok_cnt:
            msg = tr("watch.notify_partial", rule=rule_name, ok=ok_cnt, err=err_cnt, delivery=delivery_lbl)
            level = "warning"
        elif err_cnt:
            first_err = (summary.get("errors") or [("", "")])[0][1]
            msg = tr("watch.notify_error", rule=rule_name, err=err_cnt, details=str(first_err)[:120])
            level = "error"
        else:
            msg = tr("watch.notify_ok", rule=rule_name, count=ok_cnt, delivery=delivery_lbl)
            level = "info"

        send_system_notification(
            self.app_name,
            msg,
            tray_icon=self._tray_icon,
            level=level,
        )

    def _on_watch_folder_error(self, _rule_id, folder):
        self.refresh_watch_folders_table()
        if self._is_bool_setting("watch_notifications_enabled", True):
            send_system_notification(
                self.app_name,
                tr("watch.notify_permission_error", folder=folder),
                tray_icon=self._tray_icon,
                level="warning",
            )

    # --- Обработчики настроек трея / автозапуска / Watch Folders ---

    def on_tray_enabled_changed(self, val):
        self.app_settings["tray_enabled"] = str(val)
        self.save_app_settings()
        self._sync_tray_icon_state()

    def on_tray_minimize_on_close_changed(self, val):
        self.app_settings["tray_minimize_on_close"] = str(val)
        self.save_app_settings()
        self._sync_tray_icon_state()

    def on_tray_hide_dock_changed(self, val):
        self.app_settings["tray_hide_dock_macos"] = str(val)
        self.save_app_settings()
        if sys.platform == "darwin" and not self._is_bool_setting("tray_hide_dock_macos", False):
            set_macos_dock_visible(True)

    def on_watch_notifications_changed(self, val):
        self.app_settings["watch_notifications_enabled"] = str(val)
        self.save_app_settings()

    def on_autostart_changed(self, val):
        want = str(val).lower() == "true"
        ok, err = set_autostart_enabled(want)
        if not ok:
            prev = "true" if is_autostart_enabled() else "false"
            self.app_settings["autostart_enabled"] = prev
            if hasattr(self, "autostart_selector"):
                self.autostart_selector.set(prev)
            show_themed_message(self, tr("common.error"), tr("watch.err_autostart", e=err), "error")
            return
        self.app_settings["autostart_enabled"] = "true" if want else "false"
        self.save_app_settings()

    # --- CRUD правил Watch Folder в Настройках ---

    def _apply_updated_watch_rules(self, rules):
        clean = normalize_watch_rules(rules)
        self.app_settings["watch_folders"] = clean
        self.save_app_settings()
        mgr = getattr(self, "watch_manager", None)
        if mgr is not None:
            mgr.set_rules(clean)
            if any(r.get("enabled") for r in clean):
                mgr.start()
            else:
                mgr.stop()
        self.refresh_watch_folders_table()
        self.refresh_tray_menu()

    def add_watch_folder_clicked(self):
        dlg = WatchFolderRuleDialog(
            self,
            presets_dir=self.presets_dir,
            app_settings=self.app_settings,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            rules = list(self.app_settings.get("watch_folders") or [])
            rules.append(dlg.get_rule())
            self._apply_updated_watch_rules(rules)

    def _selected_watch_row(self):
        table = getattr(self, "watch_table", None)
        if table is None:
            return -1
        row = table.currentRow()
        if row >= 0:
            return row
        sel_model = table.selectionModel()
        if sel_model is not None:
            rows = sel_model.selectedRows()
            if rows:
                return rows[0].row()
        return -1

    def on_watch_table_context_menu(self, pos):
        table = getattr(self, "watch_table", None)
        if table is None:
            return
        index = table.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        rules = list(self.app_settings.get("watch_folders") or [])
        if row < 0 or row >= len(rules):
            return
        table.selectRow(row)
        table.setCurrentCell(row, index.column())

        menu = QMenu(self)
        act_edit = menu.addAction(tr("watch.btn_edit"))
        menu.addSeparator()
        act_delete = menu.addAction(tr("watch.btn_delete"))
        chosen = menu.exec(table.viewport().mapToGlobal(pos))
        if chosen == act_edit:
            self.edit_watch_folder_clicked()
        elif chosen == act_delete:
            self.delete_watch_folder_clicked()

    def edit_watch_folder_clicked(self):
        row = self._selected_watch_row()
        rules = list(self.app_settings.get("watch_folders") or [])
        if row < 0 or row >= len(rules):
            return
        dlg = WatchFolderRuleDialog(
            self,
            rule=rules[row],
            presets_dir=self.presets_dir,
            app_settings=self.app_settings,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            rules[row] = dlg.get_rule()
            self._apply_updated_watch_rules(rules)

    def delete_watch_folder_clicked(self):
        row = self._selected_watch_row()
        rules = list(self.app_settings.get("watch_folders") or [])
        if row < 0 or row >= len(rules):
            return
        name = rules[row].get("name") or rules[row].get("folder")
        if not show_themed_confirm(
            self,
            tr("common.warning"),
            tr("watch.confirm_delete", name=name),
            tr("watch.btn_delete"),
        ):
            return
        rules.pop(row)
        self._apply_updated_watch_rules(rules)

    def _on_watch_rule_toggled(self, rule_id, enabled):
        rules = list(self.app_settings.get("watch_folders") or [])
        changed = False
        for r in rules:
            if r.get("id") == rule_id:
                r["enabled"] = bool(enabled)
                changed = True
                break
        if changed:
            self._apply_updated_watch_rules(rules)

    def refresh_watch_folders_table(self):
        table = getattr(self, "watch_table", None)
        if table is None:
            return
        prev_selected_id = None
        prev_row = self._selected_watch_row()
        if 0 <= prev_row < table.rowCount():
            it0 = table.item(prev_row, 0)
            if it0 is not None:
                prev_selected_id = it0.data(Qt.ItemDataRole.UserRole)

        rules = normalize_watch_rules(self.app_settings.get("watch_folders"))
        mgr = getattr(self, "watch_manager", None)
        table.setRowCount(len(rules))

        status_labels = {
            "active": tr("watch.status_active"),
            "paused": tr("watch.status_paused"),
            "disabled": tr("watch.status_disabled"),
            "missing": tr("watch.status_missing"),
            "permission_error": tr("watch.status_permission_error"),
        }

        restore_row = -1
        for row, rule in enumerate(rules):
            rid = rule["id"]
            if prev_selected_id and rid == prev_selected_id:
                restore_row = row

            it_chk = QTableWidgetItem("")
            it_chk.setData(Qt.ItemDataRole.UserRole, rid)
            it_chk.setFlags(it_chk.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, it_chk)

            chk_wrap = QWidget()
            chk_wrap.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            chk_lay = QHBoxLayout(chk_wrap)
            chk_lay.setContentsMargins(0, 0, 0, 0)
            chk_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk = QCheckBox()
            chk.setChecked(bool(rule.get("enabled", True)))
            chk.setCursor(Qt.CursorShape.PointingHandCursor)
            chk.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            chk.toggled.connect(lambda checked, r_id=rid: self._on_watch_rule_toggled(r_id, checked))
            chk_lay.addWidget(chk)
            table.setCellWidget(row, 0, chk_wrap)

            it_name = QTableWidgetItem(rule.get("name") or os.path.basename(rule["folder"]))
            it_folder = QTableWidgetItem(rule.get("folder", ""))
            it_folder.setToolTip(rule.get("folder", ""))

            p_name = rule.get("preset_name", PRESET_CURRENT_TOKEN)
            preset_lbl = tr("watch.preset_current") if p_name == PRESET_CURRENT_TOKEN else p_name
            it_preset = QTableWidgetItem(preset_lbl)

            d_mode = rule.get("delivery_mode", "folder")
            it_delivery = QTableWidgetItem(tr(f"watch.delivery_{d_mode}"))

            st_code = mgr.get_rule_status(rid) if mgr else ("active" if rule.get("enabled") else "disabled")
            it_status = QTableWidgetItem(status_labels.get(st_code, st_code))

            for col, item in enumerate((it_name, it_folder, it_preset, it_delivery, it_status), start=1):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, col, item)

        if restore_row >= 0:
            table.selectRow(restore_row)
            table.setCurrentCell(restore_row, 1)

        hdr = table.horizontalHeader()
        if hdr is not None:
            hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

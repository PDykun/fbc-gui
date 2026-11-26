"""Системные уведомления и платформенные интеграции (macOS Menu Bar / Dock, Windows AppUserModelID)."""

import ctypes
import os
import subprocess
import sys
import threading

from PyQt6.QtWidgets import QSystemTrayIcon

from core.logger import get_logger

logger = get_logger("notifier")

WINDOWS_APP_USER_MODEL_ID = "eu.pashka.fbc-gui"


def set_windows_app_user_model_id(app_id=WINDOWS_APP_USER_MODEL_ID):
    """Задаёт AppUserModelID на Windows, чтобы Toast-уведомления подписывались как FBC GUI."""
    if os.name != "nt":
        return False
    try:
        shell32 = getattr(ctypes, "windll", None)
        if shell32 is None:
            return False
        res = shell32.shell32.SetCurrentProcessExplicitAppUserModelID(str(app_id))
        return res == 0
    except Exception as e:
        logger.debug("Не удалось установить AppUserModelID: %s", e)
        return False


def _escape_applescript_string(text):
    """Безопасно экранирует строку для передачи в AppleScript literal."""
    cleaned = str(text or "").replace("\r", " ").replace("\n", " ").strip()
    return cleaned.replace("\\", "\\\\").replace('"', '\\"')


def _reap_process_async(proc, timeout=5.0):
    """Завершает и собирает дочерний процесс в фоновом daemon-потоке, предотвращая зомби-процессы."""
    def _wait():
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass
        except Exception:
            pass

    threading.Thread(target=_wait, name="osascript-reaper", daemon=True).start()


def _send_macos_osascript_notification(title, message):
    """Отправляет нативное уведомление macOS через osascript (без shell-интерполяции и зомби-процессов)."""
    safe_title = _escape_applescript_string(title)
    safe_msg = _escape_applescript_string(message)
    script = f'display notification "{safe_msg}" with title "{safe_title}"'
    try:
        proc = subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        _reap_process_async(proc)
        return True
    except Exception as e:
        logger.debug("Не удалось отправить уведомление через osascript: %s", e)
        return False


def send_system_notification(title, message, *, tray_icon=None, level="info", timeout_ms=5000):
    """Отправляет системное уведомление на macOS или Windows."""
    title_txt = str(title or "FBC GUI").strip()
    msg_txt = str(message or "").strip()
    if not msg_txt:
        return False

    if sys.platform == "darwin":
        if _send_macos_osascript_notification(title_txt, msg_txt):
            return True

    if tray_icon is not None:
        try:
            if tray_icon.isVisible() and tray_icon.supportsMessages():
                icon_map = {
                    "info": QSystemTrayIcon.MessageIcon.Information,
                    "warning": QSystemTrayIcon.MessageIcon.Warning,
                    "error": QSystemTrayIcon.MessageIcon.Critical,
                }
                qicon = icon_map.get(str(level).lower(), QSystemTrayIcon.MessageIcon.Information)
                tray_icon.showMessage(title_txt, msg_txt, qicon, int(timeout_ms))
                return True
        except Exception as e:
            logger.debug("Ошибка показа уведомления через QSystemTrayIcon: %s", e)

    return False


def set_macos_dock_visible(visible):
    """Переключает видимость иконки приложения в Dock на macOS (Regular / Accessory)."""
    if sys.platform != "darwin":
        return False
    try:
        from AppKit import (
            NSApp,
            NSApplicationActivationPolicyAccessory,
            NSApplicationActivationPolicyRegular,
        )
        app = NSApp()
        if app is None:
            return False
        policy = (
            NSApplicationActivationPolicyRegular
            if visible
            else NSApplicationActivationPolicyAccessory
        )
        app.setActivationPolicy_(policy)
        if visible:
            app.activateIgnoringOtherApps_(True)
        return True
    except Exception as e:
        logger.debug("Не удалось изменить политику Dock на macOS: %s", e)
        return False

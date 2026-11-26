"""Кроссплатформенное управление автозапуском FBC GUI при входе в систему (macOS LaunchAgents / Windows Run)."""

import os
import plistlib
import sys
import tempfile

from core.logger import get_logger

logger = get_logger("autostart")

MACOS_AGENT_LABEL = "eu.pashka.fbc-gui"
WINDOWS_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINDOWS_RUN_VALUE_NAME = "FBC_GUI"


def is_autostart_supported(platform=None):
    """Возвращает True, если на текущей ОС поддерживается автозапуск при входе."""
    plat = platform or sys.platform
    return plat == "darwin" or plat.startswith("win")


def get_macos_launch_agent_path(home_dir=None):
    """Возвращает путь к файлу ~/Library/LaunchAgents/eu.pashka.fbc-gui.plist."""
    base = home_dir or os.path.expanduser("~")
    return os.path.join(base, "Library", "LaunchAgents", f"{MACOS_AGENT_LABEL}.plist")


def get_autostart_program_arguments(
    *,
    platform=None,
    frozen=None,
    executable=None,
    script_path=None,
    minimized=True,
):
    """Формирует список аргументов запуска приложения для автозапуска."""
    plat = platform or sys.platform
    is_frozen = getattr(sys, "frozen", False) if frozen is None else bool(frozen)
    exe = executable or sys.executable
    extra = ["--minimized"] if minimized else []

    if is_frozen:
        return [os.path.abspath(exe), *extra]

    entry = script_path or os.path.abspath(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fbc_gui.py")
    )
    if plat.startswith("win") and exe.lower().endswith("python.exe"):
        pythonw = exe[:-10] + "pythonw.exe"
        if os.path.isfile(pythonw):
            exe = pythonw
    return [os.path.abspath(exe), os.path.abspath(entry), *extra]


def format_windows_run_command(args):
    """Собирает корректно экранированную командную строку для реестра Windows Run."""
    quoted = []
    for a in args:
        s = str(a)
        if " " in s or "\t" in s or '"' in s or not s:
            s = '"' + s.replace('"', '\\"') + '"'
        quoted.append(s)
    return " ".join(quoted)


def _atomic_write_bytes(filepath, data):
    abs_path = os.path.abspath(filepath)
    parent = os.path.dirname(abs_path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".fbc_plist_", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def is_autostart_enabled(*, platform=None, macos_plist_path=None, winreg_module=None, verify_executable=None):
    """Проверяет, включён ли автозапуск приложения в системе (с валидацией содержимого plist на macOS)."""
    plat = platform or sys.platform
    if plat == "darwin":
        plist_path = macos_plist_path or get_macos_launch_agent_path()
        if not os.path.isfile(plist_path):
            return False
        try:
            with open(plist_path, "rb") as fh:
                payload = plistlib.load(fh)
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        prog_args = payload.get("ProgramArguments")
        if not isinstance(prog_args, list) or not prog_args or not str(prog_args[0] or "").strip():
            return False
        check_exe = (macos_plist_path is None) if verify_executable is None else bool(verify_executable)
        if check_exe and not os.path.exists(str(prog_args[0])):
            return False
        return True

    if plat.startswith("win"):
        try:
            wr = winreg_module
            if wr is None:
                import winreg as wr
            with wr.OpenKey(wr.HKEY_CURRENT_USER, WINDOWS_RUN_KEY_PATH, 0, wr.KEY_READ) as key:
                val, _ = wr.QueryValueEx(key, WINDOWS_RUN_VALUE_NAME)
                return bool(str(val or "").strip())
        except FileNotFoundError:
            return False
        except OSError:
            return False
    return False


def set_autostart_enabled(
    enabled,
    *,
    platform=None,
    macos_plist_path=None,
    winreg_module=None,
    program_args=None,
):
    """Включает или выключает автозапуск при входе в систему. Возвращает (ok, error_message)."""
    plat = platform or sys.platform
    want = bool(enabled)

    if plat == "darwin":
        plist_path = macos_plist_path or get_macos_launch_agent_path()
        try:
            if want:
                args = list(program_args) if program_args else get_autostart_program_arguments(platform=plat)
                payload = {
                    "Label": MACOS_AGENT_LABEL,
                    "ProgramArguments": args,
                    "RunAtLoad": True,
                    "KeepAlive": False,
                    "ProcessType": "Interactive",
                }
                _atomic_write_bytes(plist_path, plistlib.dumps(payload, fmt=plistlib.FMT_XML))
                logger.info("Автозапуск macOS включён: %s", plist_path)
            else:
                if os.path.exists(plist_path):
                    os.remove(plist_path)
                    logger.info("Автозапуск macOS выключен: удалён %s", plist_path)
            return True, ""
        except Exception as e:
            logger.error("Ошибка настройки автозапуска macOS: %s", e)
            return False, str(e)

    if plat.startswith("win"):
        try:
            wr = winreg_module
            if wr is None:
                import winreg as wr
            with wr.OpenKey(wr.HKEY_CURRENT_USER, WINDOWS_RUN_KEY_PATH, 0, wr.KEY_SET_VALUE) as key:
                if want:
                    args = list(program_args) if program_args else get_autostart_program_arguments(platform=plat)
                    cmd = format_windows_run_command(args)
                    wr.SetValueEx(key, WINDOWS_RUN_VALUE_NAME, 0, wr.REG_SZ, cmd)
                    logger.info("Автозапуск Windows включён: %s", cmd)
                else:
                    try:
                        wr.DeleteValue(key, WINDOWS_RUN_VALUE_NAME)
                        logger.info("Автозапуск Windows выключен")
                    except FileNotFoundError:
                        pass
            return True, ""
        except Exception as e:
            logger.error("Ошибка настройки автозапуска Windows: %s", e)
            return False, str(e)

    return False, f"Autostart is not supported on platform: {plat}"

import atexit
import faulthandler
import logging
import os
import platform
import sqlite3
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler

_LOG_FILE_PATH = ""
_LOGGING_INITIALIZED = False
_DEBUG_LOGGING_ENABLED = False
_FILE_HANDLER = None
_FAULTHANDLER_FILE = None
_HOOKS_INSTALLED = False
_ORIG_SYS_EXCEPTHOOK = None
_ORIG_THREADING_EXCEPTHOOK = None
_ORIG_UNRAISABLEHOOK = None
_QT_HANDLER_INSTALLED = False
_PREV_QT_MSG_HANDLER = None

_STD_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_STD_DATEFMT = "%Y-%m-%d %H:%M:%S"
_DEBUG_FORMAT = (
    "%(asctime)s.%(msecs)03d [%(levelname)s] "
    "[pid=%(process)d tid=%(thread)d %(threadName)s] "
    "%(name)s (%(filename)s:%(lineno)d in %(funcName)s): %(message)s"
)
_STD_MAX_BYTES = 2 * 1024 * 1024
_STD_BACKUP_COUNT = 3
_DEBUG_MAX_BYTES = 10 * 1024 * 1024
_DEBUG_BACKUP_COUNT = 5


class _HomePathMaskFilter(logging.Filter):
    """Маскирует домашний каталог пользователя в сообщениях журнала для защиты приватности."""

    def __init__(self):
        super().__init__()
        home = os.path.expanduser("~")
        self._home_variants = tuple(
            v for v in dict.fromkeys((home, home.replace("\\", "/"), home.replace("/", "\\")))
            if v and len(v) > 3
        )

    def filter(self, record):
        if not self._home_variants:
            return True
        try:
            msg = record.getMessage()
            masked = msg
            for hv in self._home_variants:
                if hv in masked:
                    masked = masked.replace(hv, "~")
            if masked != msg:
                record.msg = masked
                record.args = None
        except Exception:
            pass
        return True


def _is_file_log_disabled():
    return os.environ.get("FBC_GUI_DISABLE_FILE_LOG", "").strip().lower() in ("1", "true", "yes")


def _flush_all_handlers():
    root_logger = logging.getLogger("fbc_gui")
    for h in list(root_logger.handlers):
        try:
            h.flush()
        except Exception:
            pass


def format_all_threads_dump():
    """Возвращает снимок стеков вызовов всех активных Python-потоков (аналог Thread Stacks в отчёте ОС)."""
    frames = sys._current_frames()
    threads_by_id = {t.ident: t for t in threading.enumerate()}
    lines = ["=== Active Python Threads Stack Dump ==="]
    for tid, frame in frames.items():
        t = threads_by_id.get(tid)
        t_name = t.name if t is not None else "Unknown"
        is_daemon = getattr(t, "daemon", False) if t is not None else False
        lines.append(f"--- Thread {tid} ({t_name}, daemon={is_daemon}) ---")
        lines.append("".join(traceback.format_stack(frame)).rstrip())
    return "\n".join(lines)


def collect_system_diagnostics(app_info=None):
    """Собирает системную сводку среды выполнения для диагностического заголовка в логе."""
    qt_ver = "N/A"
    pyqt_ver = "N/A"
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

        qt_ver = QT_VERSION_STR
        pyqt_ver = PYQT_VERSION_STR
    except Exception:
        pass

    lines = [
        "=== FBC GUI Debug Diagnostics ===",
        f"OS / Platform: {platform.platform()} ({sys.platform}, arch={platform.machine()})",
        f"Python: {sys.version.splitlines()[0]} (frozen={getattr(sys, 'frozen', False)})",
        f"PyQt6 / Qt: PyQt6={pyqt_ver}, Qt={qt_ver}",
        f"SQLite: {sqlite3.sqlite_version}",
        f"Process: pid={os.getpid()}, cpu_count={os.cpu_count()}",
    ]
    if isinstance(app_info, dict):
        for key, val in app_info.items():
            if val is not None and str(val).strip() != "":
                lines.append(f"{key}: {val}")
    return "\n".join(lines)


def _debug_sys_excepthook(exc_type, exc_value, exc_tb):
    try:
        log = get_logger("crash")
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).rstrip()
        log.critical("UNHANDLED EXCEPTION in main thread:\n%s\n\n%s", tb_str, format_all_threads_dump())
        _flush_all_handlers()
    except Exception:
        pass
    if _ORIG_SYS_EXCEPTHOOK is not None:
        _ORIG_SYS_EXCEPTHOOK(exc_type, exc_value, exc_tb)


def _debug_threading_excepthook(args):
    try:
        log = get_logger("crash")
        t_name = getattr(args.thread, "name", "Unknown") if args.thread else "Unknown"
        t_ident = getattr(args.thread, "ident", None) if args.thread else None
        tb_str = "".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        ).rstrip()
        log.critical(
            "UNHANDLED EXCEPTION in thread %s (tid=%s):\n%s\n\n%s",
            t_name,
            t_ident,
            tb_str,
            format_all_threads_dump(),
        )
        _flush_all_handlers()
    except Exception:
        pass
    if _ORIG_THREADING_EXCEPTHOOK is not None:
        _ORIG_THREADING_EXCEPTHOOK(args)


def _debug_unraisablehook(unraisable):
    try:
        log = get_logger("crash")
        tb_str = "".join(
            traceback.format_exception(
                unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback
            )
        ).rstrip()
        log.error(
            "UNRAISABLE EXCEPTION (%s; obj=%r):\n%s",
            unraisable.err_msg or "unraisable",
            unraisable.object,
            tb_str,
        )
        _flush_all_handlers()
    except Exception:
        pass
    if _ORIG_UNRAISABLEHOOK is not None:
        _ORIG_UNRAISABLEHOOK(unraisable)


def _qt_message_handler(msg_type, context, message):
    try:
        from PyQt6.QtCore import QtMsgType

        log = get_logger("qt")
        loc = ""
        if context is not None and (context.file or context.function):
            loc = f" [{context.file or '?'}:{context.line} {context.function or ''}]"
        if msg_type == QtMsgType.QtFatalMsg:
            log.critical("QtFatal%s: %s\n%s", loc, message, format_all_threads_dump())
            _flush_all_handlers()
        elif msg_type == QtMsgType.QtCriticalMsg:
            log.error("QtCritical%s: %s", loc, message)
        elif msg_type == QtMsgType.QtWarningMsg:
            log.warning("QtWarning%s: %s", loc, message)
        elif msg_type == QtMsgType.QtInfoMsg:
            log.info("QtInfo%s: %s", loc, message)
        else:
            log.debug("QtDebug%s: %s", loc, message)
    except Exception:
        pass


def _install_debug_hooks():
    global _HOOKS_INSTALLED, _ORIG_SYS_EXCEPTHOOK, _ORIG_THREADING_EXCEPTHOOK, _ORIG_UNRAISABLEHOOK
    global _QT_HANDLER_INSTALLED, _PREV_QT_MSG_HANDLER

    if not _HOOKS_INSTALLED:
        _ORIG_SYS_EXCEPTHOOK = sys.excepthook
        sys.excepthook = _debug_sys_excepthook
        if hasattr(threading, "excepthook"):
            _ORIG_THREADING_EXCEPTHOOK = threading.excepthook
            threading.excepthook = _debug_threading_excepthook
        if hasattr(sys, "unraisablehook"):
            _ORIG_UNRAISABLEHOOK = sys.unraisablehook
            sys.unraisablehook = _debug_unraisablehook
        _HOOKS_INSTALLED = True

    if not _QT_HANDLER_INSTALLED:
        try:
            from PyQt6.QtCore import qInstallMessageHandler

            _PREV_QT_MSG_HANDLER = qInstallMessageHandler(_qt_message_handler)
            _QT_HANDLER_INSTALLED = True
        except Exception:
            pass


def _uninstall_debug_hooks():
    global _HOOKS_INSTALLED, _ORIG_SYS_EXCEPTHOOK, _ORIG_THREADING_EXCEPTHOOK, _ORIG_UNRAISABLEHOOK
    global _QT_HANDLER_INSTALLED, _PREV_QT_MSG_HANDLER

    if _HOOKS_INSTALLED:
        if _ORIG_SYS_EXCEPTHOOK is not None:
            sys.excepthook = _ORIG_SYS_EXCEPTHOOK
        if hasattr(threading, "excepthook") and _ORIG_THREADING_EXCEPTHOOK is not None:
            threading.excepthook = _ORIG_THREADING_EXCEPTHOOK
        if hasattr(sys, "unraisablehook") and _ORIG_UNRAISABLEHOOK is not None:
            sys.unraisablehook = _ORIG_UNRAISABLEHOOK
        _ORIG_SYS_EXCEPTHOOK = None
        _ORIG_THREADING_EXCEPTHOOK = None
        _ORIG_UNRAISABLEHOOK = None
        _HOOKS_INSTALLED = False

    if _QT_HANDLER_INSTALLED:
        try:
            from PyQt6.QtCore import qInstallMessageHandler

            qInstallMessageHandler(_PREV_QT_MSG_HANDLER)
        except Exception:
            pass
        _PREV_QT_MSG_HANDLER = None
        _QT_HANDLER_INSTALLED = False


def _enable_faulthandler():
    global _FAULTHANDLER_FILE
    if _is_file_log_disabled() or not _LOG_FILE_PATH:
        return
    if _FAULTHANDLER_FILE is not None:
        return
    try:
        fh = open(_LOG_FILE_PATH, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=fh, all_threads=True)
        _FAULTHANDLER_FILE = fh
    except Exception as e:
        get_logger("app").debug("Не удалось включить faulthandler: %s", e)


def _disable_faulthandler():
    global _FAULTHANDLER_FILE
    try:
        if faulthandler.is_enabled():
            faulthandler.disable()
    except Exception:
        pass
    fh = _FAULTHANDLER_FILE
    _FAULTHANDLER_FILE = None
    if fh is not None:
        try:
            fh.flush()
            fh.close()
        except Exception:
            pass


def shutdown_debug_logging():
    """Корректно отключает faulthandler и закрывает его файловый дескриптор при выходе."""
    _disable_faulthandler()
    _flush_all_handlers()


atexit.register(shutdown_debug_logging)


def is_debug_logging_enabled():
    """Возвращает True, если активен подробный диагностический режим Debug."""
    return _DEBUG_LOGGING_ENABLED


def set_debug_logging(enabled, *, app_info=None):
    """Переключает режим расширенного диагностического логирования (DEBUG, стек потоков, Qt и faulthandler)."""
    global _DEBUG_LOGGING_ENABLED
    flag = bool(enabled)
    was_enabled = _DEBUG_LOGGING_ENABLED
    _DEBUG_LOGGING_ENABLED = flag

    root_logger = logging.getLogger("fbc_gui")
    target_level = logging.DEBUG if flag else logging.INFO
    root_logger.setLevel(target_level)

    fmt = logging.Formatter(_DEBUG_FORMAT if flag else _STD_FORMAT, datefmt=_STD_DATEFMT)
    if _FILE_HANDLER is not None:
        _FILE_HANDLER.setLevel(target_level)
        _FILE_HANDLER.setFormatter(fmt)
        _FILE_HANDLER.maxBytes = _DEBUG_MAX_BYTES if flag else _STD_MAX_BYTES
        _FILE_HANDLER.backupCount = _DEBUG_BACKUP_COUNT if flag else _STD_BACKUP_COUNT

    if flag:
        _install_debug_hooks()
        _enable_faulthandler()
        if not was_enabled or app_info:
            get_logger("app").info("Режим Debug-логирования включён\n%s", collect_system_diagnostics(app_info))
            _flush_all_handlers()
    else:
        if was_enabled:
            get_logger("app").info("Режим Debug-логирования выключен")
            _flush_all_handlers()
        _disable_faulthandler()
        _uninstall_debug_hooks()

    return _DEBUG_LOGGING_ENABLED


def init_logging(base_dir, log_filename="fbc_gui.log", max_bytes=_STD_MAX_BYTES, backup_count=_STD_BACKUP_COUNT, debug=False):
    """Настраивает централизованное логирование с ротацией файла."""
    global _LOG_FILE_PATH, _LOGGING_INITIALIZED, _FILE_HANDLER
    os.makedirs(base_dir, exist_ok=True)
    log_path = os.path.join(base_dir, log_filename)
    _LOG_FILE_PATH = log_path

    root_logger = logging.getLogger("fbc_gui")
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)
    root_logger.propagate = False

    if _LOGGING_INITIALIZED:
        if debug != _DEBUG_LOGGING_ENABLED:
            set_debug_logging(debug)
        return log_path

    formatter = logging.Formatter(_DEBUG_FORMAT if debug else _STD_FORMAT, datefmt=_STD_DATEFMT)
    home_filter = _HomePathMaskFilter()
    root_logger.addFilter(home_filter)

    if not _is_file_log_disabled():
        try:
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=_DEBUG_MAX_BYTES if debug else max_bytes,
                backupCount=_DEBUG_BACKUP_COUNT if debug else backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
            _FILE_HANDLER = file_handler
        except Exception as e:
            try:
                sys.stderr.write(f"fbc_gui: failed to initialize file logger at {log_path}: {e}\n")
            except Exception:
                # stderr недоступен при отказе инициализации самого логгера
                pass

    if not getattr(sys, "frozen", False):
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    _LOGGING_INITIALIZED = True
    if debug:
        set_debug_logging(True)
    return log_path


def get_logger(name="app"):
    """Возвращает именованный логгер в пространстве имён fbc_gui."""
    if not name or name == "fbc_gui":
        return logging.getLogger("fbc_gui")
    if name.startswith("fbc_gui."):
        return logging.getLogger(name)
    return logging.getLogger(f"fbc_gui.{name}")


def get_log_file_path():
    """Возвращает путь к текущему файлу журнала."""
    return _LOG_FILE_PATH

import os
import sys
import logging
from logging.handlers import RotatingFileHandler

_LOG_FILE_PATH = ""
_LOGGING_INITIALIZED = False


def init_logging(base_dir, log_filename="fbc_gui.log", max_bytes=2 * 1024 * 1024, backup_count=3):
    """Настраивает централизованное логирование с ротацией файла."""
    global _LOG_FILE_PATH, _LOGGING_INITIALIZED
    os.makedirs(base_dir, exist_ok=True)
    log_path = os.path.join(base_dir, log_filename)
    _LOG_FILE_PATH = log_path

    root_logger = logging.getLogger("fbc_gui")
    root_logger.setLevel(logging.INFO)
    root_logger.propagate = False

    if _LOGGING_INITIALIZED:
        return log_path

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    disable_file_log = os.environ.get("FBC_GUI_DISABLE_FILE_LOG", "").strip().lower() in ("1", "true", "yes")
    if not disable_file_log:
        try:
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
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

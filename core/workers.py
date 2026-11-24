import getpass
import json
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from PyQt6.QtCore import QObject, QThread, pyqtSignal

try:
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    HAS_QT_NETWORK = True
except ImportError:
    QLocalServer = None
    QLocalSocket = None
    HAS_QT_NETWORK = False

from core.email_sender import (
    EmailCancelledError,
    send_converted_files_via_email as send_email_attachments,
    send_test_email as dispatch_test_email,
)
from core.fb2_processor import (
    ConversionCancelledError,
    collect_book_paths,
    convert_book_file,
    extract_cover_from_fb2,
    iter_fb2_from_file,
    parse_metadata,
    simulate_fbc_target,
)
from core.i18n import tr
from core.logger import get_logger

logger = get_logger("workers")


class FileImportWorker(QThread):
    """Фоновый поток сканирования папок/архивов и разбора метаданных FB2 без хранения сырого XML в памяти."""

    progress = pyqtSignal(int, int, str)
    finished_import = pyqtSignal(list, bool)

    def __init__(self, filepaths, existing_keys=None, parent=None):
        super().__init__(parent)
        self.filepaths = list(filepaths or [])
        self.existing_keys = set(existing_keys or ())

    def run(self):
        resolved_paths = collect_book_paths(self.filepaths)
        total = len(resolved_paths)
        imported = []
        cancelled = False
        seen_keys = set(self.existing_keys)

        for idx, path in enumerate(resolved_paths, start=1):
            if self.isInterruptionRequested():
                cancelled = True
                break
            self.progress.emit(idx, total, os.path.basename(path))
            for source_key, archive_entry, display_name, xml_bytes in iter_fb2_from_file(path):
                if self.isInterruptionRequested():
                    cancelled = True
                    break
                if source_key in seen_keys or not xml_bytes:
                    continue
                seen_keys.add(source_key)

                meta = parse_metadata(xml_bytes)
                cover_bytes, cover_mime = extract_cover_from_fb2(xml_bytes)
                imported.append({
                    'path': path,
                    'archive_entry': archive_entry,
                    'source_key': source_key,
                    'display_name': display_name,
                    'meta': meta,
                    'orig_cover_bytes': cover_bytes,
                    'orig_cover_mime': cover_mime,
                    'cover_bytes': cover_bytes,
                    'cover_mime': cover_mime,
                    'cover_modified': False,
                })
            if cancelled:
                break

        self.finished_import.emit(imported, cancelled)


class ConversionWorker(QThread):
    """Фоновый поток пакетной конвертации книг через fb2cng и опциональной отправки по SMTP."""

    convert_progress = pyqtSignal(int, str)
    email_progress = pyqtSignal(int, str)
    item_status = pyqtSignal(str, str, str)
    finished_all = pyqtSignal(int, list, list, str, bool, list)

    def __init__(
        self,
        items,
        selected_format,
        save_mode,
        custom_dir,
        title_style_params,
        compression,
        email_enabled,
        app_settings,
        debug=False,
        no_cover=False,
        fbc_cmd="",
        fbc_config="",
        base_dir="",
        app_name="FBC GUI",
        app_version="",
        parent=None,
    ):
        super().__init__(parent)
        self.items = items
        self.selected_format = selected_format
        self.save_mode = save_mode
        self.custom_dir = custom_dir
        self.title_style_params = title_style_params
        self.compression = compression
        self.email_enabled = email_enabled
        self.app_settings = app_settings
        self.debug = bool(debug)
        self.no_cover = bool(no_cover)
        self.fbc_cmd = fbc_cmd
        self.fbc_config = fbc_config
        self.base_dir = base_dir
        self.app_name = app_name
        self.app_version = app_version
        self._cancel_event = threading.Event()

    def cancel(self):
        """Немедленно сигнализирует отмену всем активным процессам fbc и очереди задач."""
        self._cancel_event.set()
        self.requestInterruption()

    def _resolve_worker_count(self, total):
        raw = str(self.app_settings.get("convert_workers", "auto")).strip().lower()
        if raw.isdigit():
            workers = max(1, min(8, int(raw)))
        else:
            workers = min(4, max(1, os.cpu_count() or 2))
        return max(1, min(workers, total))

    def _convert_single_item(self, idx, data):
        item_id = data.get("item_id", "")
        original_path = data["path"]
        source_label = data.get("display_name") or os.path.basename(original_path)
        display_name = simulate_fbc_target(
            data["meta"],
            self.selected_format,
            self.app_settings.get("filename_mode", "default"),
            self.app_settings.get("filename_tokens"),
        )
        if self.save_mode == "custom" and self.custom_dir and os.path.isdir(self.custom_dir):
            dest_dir = self.custom_dir
        else:
            dest_dir = os.path.dirname(original_path)

        if item_id:
            self.item_status.emit(item_id, "running", "")

        t0 = time.monotonic()
        try:
            created = convert_book_file(
                self.fbc_cmd,
                self.fbc_config,
                self.base_dir,
                data,
                dest_dir,
                self.selected_format,
                self.title_style_params,
                compression=self.compression,
                cancel_event=self._cancel_event,
                debug=self.debug,
                no_cover=self.no_cover,
                claimed_outputs=self._claimed_outputs,
            )
            elapsed = time.monotonic() - t0
            logger.info(
                "Конвертация ОК [%.2fs]: %s -> %s",
                elapsed,
                source_label,
                ", ".join(os.path.basename(p) for p in created),
            )
            if item_id:
                self.item_status.emit(item_id, "ok", "")
            return idx, display_name, source_label, created, None, False
        except ConversionCancelledError:
            elapsed = time.monotonic() - t0
            logger.info("Конвертация ОТМЕНЕНА [%.2fs]: %s", elapsed, source_label)
            if item_id:
                self.item_status.emit(item_id, "cancelled", "")
            return idx, display_name, source_label, [], None, True
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.error("Конвертация ОШИБКА [%.2fs]: %s: %s", elapsed, source_label, e)
            if item_id:
                self.item_status.emit(item_id, "error", str(e))
            return idx, display_name, source_label, [], str(e), False

    def run(self):
        total = len(self.items)
        if total == 0:
            self.finished_all.emit(0, [], [], "", False, [])
            return

        workers = self._resolve_worker_count(total)
        batch_t0 = time.monotonic()
        logger.info(
            "Старт пакетной конвертации: книг=%d, формат=%s, потоков=%d, email=%s, debug=%s",
            total,
            self.selected_format,
            workers,
            self.email_enabled,
            self.debug,
        )

        self._claimed_outputs = set()
        results_by_idx = {}
        errors_by_idx = {}
        completed = 0
        cancelled = False
        email_error = ""

        first_display = simulate_fbc_target(
            self.items[0]["meta"],
            self.selected_format,
            self.app_settings.get("filename_mode", "default"),
            self.app_settings.get("filename_tokens"),
        )
        self.convert_progress.emit(
            0,
            tr("converter.progress_convert_file", cur=1, total=total, name=first_display),
        )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            pending = set()
            next_idx = 0

            while next_idx < total and len(pending) < workers:
                if self.isInterruptionRequested() or self._cancel_event.is_set():
                    cancelled = True
                    break
                pending.add(executor.submit(self._convert_single_item, next_idx, self.items[next_idx]))
                next_idx += 1

            while pending:
                done, pending = wait(pending, timeout=0.15, return_when=FIRST_COMPLETED)
                for fut in done:
                    idx, display_name, source_label, created, err_msg, was_cancelled = fut.result()
                    if was_cancelled:
                        cancelled = True
                        continue
                    completed += 1
                    if err_msg:
                        errors_by_idx[idx] = (source_label, err_msg)
                    else:
                        results_by_idx[idx] = created
                    self.convert_progress.emit(
                        completed,
                        tr("converter.progress_convert_file", cur=completed, total=total, name=display_name),
                    )

                if self.isInterruptionRequested() or self._cancel_event.is_set():
                    cancelled = True
                    for fut in list(pending):
                        fut.cancel()
                    continue

                while next_idx < total and len(pending) < workers:
                    if self.isInterruptionRequested() or self._cancel_event.is_set():
                        cancelled = True
                        break
                    pending.add(executor.submit(self._convert_single_item, next_idx, self.items[next_idx]))
                    next_idx += 1

        converted_files = []
        for idx in sorted(results_by_idx.keys()):
            converted_files.extend(results_by_idx[idx])
        success_count = len(results_by_idx)
        convert_errors = [errors_by_idx[idx] for idx in sorted(errors_by_idx.keys())]
        failed_items = [self.items[idx] for idx in sorted(errors_by_idx.keys())]

        logger.info(
            "Завершение конвертации за %.2fs: успешно=%d, ошибок=%d, отменено=%s",
            time.monotonic() - batch_t0,
            success_count,
            len(convert_errors),
            cancelled,
        )

        if not cancelled:
            self.convert_progress.emit(
                total,
                tr("converter.progress_convert_done", total=total),
            )

        if not cancelled and self.email_enabled and converted_files:
            try:
                logger.info(
                    "Отправка %d файлов на %s",
                    len(converted_files),
                    self.app_settings.get("email_to", ""),
                )
                send_email_attachments(
                    self.app_settings,
                    converted_files,
                    self.app_name,
                    self.app_version,
                    progress_callback=lambda pct, txt: self.email_progress.emit(pct, txt),
                    cancel_event=self._cancel_event,
                )
                logger.info("Отправка по SMTP завершена успешно")
            except EmailCancelledError:
                logger.info("Отправка по SMTP отменена пользователем")
                cancelled = True
            except Exception as e:
                logger.exception("Ошибка отправки по SMTP: %s", e)
                email_error = str(e)

        self.finished_all.emit(
            success_count,
            converted_files,
            convert_errors,
            email_error,
            cancelled,
            failed_items,
        )


class TestEmailWorker(QThread):
    """Фоновый поток для отправки тестового письма SMTP без блокировки интерфейса."""

    finished_test = pyqtSignal(bool, str)

    def __init__(self, app_settings, app_name="FBC GUI", app_version="", parent=None):
        super().__init__(parent)
        self.app_settings = app_settings
        self.app_name = app_name
        self.app_version = app_version

    def run(self):
        try:
            dispatch_test_email(self.app_settings, self.app_name, self.app_version)
            self.finished_test.emit(True, "")
        except Exception as e:
            self.finished_test.emit(False, str(e))


class SingleInstanceManager(QObject):
    """Обеспечивает единый экземпляр приложения на Windows/macOS через QLocalServer/QLocalSocket."""

    MAX_IPC_PAYLOAD_BYTES = 1024 * 1024
    activation_requested = pyqtSignal(list)

    def __init__(self, server_name=None, parent=None):
        super().__init__(parent)
        if not server_name:
            try:
                user_slug = "".join(ch for ch in getpass.getuser() if ch.isalnum() or ch in ("_", "-")) or "user"
            except Exception:
                user_slug = "user"
            server_name = f"fbc_gui_single_instance_{user_slug}"
        self.server_name = server_name
        self._server = None

    def try_send_to_running(self, paths=None):
        """Пытается передать пути уже запущенному экземпляру; возвращает True, если он ответил."""
        if not HAS_QT_NETWORK or QLocalSocket is None:
            return False
        sock = QLocalSocket()
        sock.connectToServer(self.server_name)
        if not sock.waitForConnected(250):
            return False
        payload = json.dumps({"paths": list(paths or [])}, ensure_ascii=False).encode("utf-8")
        sock.write(payload)
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return True

    def start_server(self):
        """Запускает локальный сервер для приёма файлов от повторных запусков."""
        if not HAS_QT_NETWORK or QLocalServer is None:
            return False
        QLocalServer.removeServer(self.server_name)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        if not self._server.listen(self.server_name):
            logger.warning(
                "Не удалось запустить QLocalServer (%s): %s",
                self.server_name,
                self._server.errorString(),
            )
            self._server = None
            return False
        return True

    def _on_new_connection(self):
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            if conn is None:
                continue
            chunks = []
            total_len = 0
            limit = self.MAX_IPC_PAYLOAD_BYTES + 1
            if conn.bytesAvailable() > 0 or conn.waitForReadyRead(300):
                while total_len < limit:
                    part = bytes(conn.read(limit - total_len))
                    if part:
                        chunks.append(part)
                        total_len += len(part)
                    if total_len >= limit:
                        break
                    if conn.bytesAvailable() > 0:
                        continue
                    if not conn.waitForReadyRead(50):
                        break
            raw = b"".join(chunks)
            conn.disconnectFromServer()
            conn.deleteLater()
            paths = []
            if len(raw) > self.MAX_IPC_PAYLOAD_BYTES:
                logger.warning(
                    "IPC-сообщение отклонено: превышен лимит размера (%d байт)",
                    self.MAX_IPC_PAYLOAD_BYTES,
                )
            elif raw:
                try:
                    data = json.loads(raw.decode("utf-8", errors="replace"))
                    if isinstance(data, dict) and isinstance(data.get("paths"), list):
                        paths = [p for p in data["paths"] if isinstance(p, str) and os.path.exists(p)]
                except Exception as e:
                    logger.warning("Некорректный JSON в IPC-сообщении: %s", e)
            self.activation_requested.emit(paths)

    def close(self):
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(self.server_name)
            self._server = None

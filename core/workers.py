import copy
import getpass
import json
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

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
    copy_meta_dict,
    extract_cover_from_fb2,
    iter_fb2_from_file,
    parse_metadata,
    quick_check_fb2,
    should_skip_existing_conversion,
    simulate_fbc_target,
)
from core.i18n import tr
from core.logger import get_logger

logger = get_logger("workers")
_ORPHANED_THREADS = set()


def stop_qthread_safely(worker, timeout_ms=2500, label=""):
    """Корректно останавливает QThread и безопасно отсоединяет его при таймауте, предотвращая SIGABRT."""
    if worker is None:
        return True
    try:
        if hasattr(worker, "cancel"):
            worker.cancel()
        if hasattr(worker, "requestInterruption"):
            worker.requestInterruption()
        if not worker.isRunning():
            return True
        if worker.wait(int(timeout_ms)):
            return True
    except RuntimeError:
        return True

    logger.warning(
        "Фоновый поток %s не завершился за %d мс; отсоединяем до естественного завершения",
        label or type(worker).__name__,
        int(timeout_ms),
    )
    try:
        worker.disconnect()
    except (TypeError, RuntimeError):
        pass
    try:
        worker.setParent(None)
    except RuntimeError:
        return False

    _ORPHANED_THREADS.add(worker)

    def _cleanup_orphan(w=worker):
        _ORPHANED_THREADS.discard(w)
        try:
            w.deleteLater()
        except RuntimeError:
            pass

    try:
        worker.finished.connect(_cleanup_orphan)
        if not worker.isRunning():
            _cleanup_orphan()
    except RuntimeError:
        _ORPHANED_THREADS.discard(worker)
    return False


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
                warnings = quick_check_fb2(xml_bytes, meta=meta, cover_bytes=cover_bytes)
                imported.append({
                    'path': path,
                    'archive_entry': archive_entry,
                    'source_key': source_key,
                    'display_name': display_name,
                    'meta': meta,
                    'orig_meta': copy_meta_dict(meta),
                    'orig_cover_bytes': cover_bytes,
                    'orig_cover_mime': cover_mime,
                    'cover_bytes': cover_bytes,
                    'cover_mime': cover_mime,
                    'cover_modified': False,
                    'warnings': warnings,
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
        skip_existing=False,
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
        self.title_style_params = copy.deepcopy(title_style_params)
        self.compression = compression
        self.email_enabled = email_enabled
        self.app_settings = copy.deepcopy(app_settings or {})
        self.debug = bool(debug)
        self.no_cover = bool(no_cover)
        self.skip_existing = bool(skip_existing)
        self.skipped_count = 0
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

        if self.skip_existing and not self.debug and should_skip_existing_conversion(data, dest_dir, display_name):
            logger.info("Конвертация ПРОПУЩЕНА (актуальный файл уже существует): %s", source_label)
            if item_id:
                self.item_status.emit(item_id, "skipped", "")
            return idx, display_name, source_label, [], None, False, True

        if item_id:
            self.item_status.emit(item_id, "running", "")

        t0 = time.monotonic()
        try:
            try:
                jpeg_q = int(self.app_settings.get("jpeg_quality_level", "95"))
            except (TypeError, ValueError):
                jpeg_q = 95
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
                image_color_profile=self.app_settings.get("image_color_profile", "none"),
                jpeg_quality=jpeg_q,
                image_color_profile_custom=self.app_settings.get("image_color_profile_custom"),
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
            return idx, display_name, source_label, created, None, False, False
        except ConversionCancelledError:
            elapsed = time.monotonic() - t0
            logger.info("Конвертация ОТМЕНЕНА [%.2fs]: %s", elapsed, source_label)
            if item_id:
                self.item_status.emit(item_id, "cancelled", "")
            return idx, display_name, source_label, [], None, True, False
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.error("Конвертация ОШИБКА [%.2fs]: %s: %s", elapsed, source_label, e)
            if item_id:
                self.item_status.emit(item_id, "error", str(e))
            return idx, display_name, source_label, [], str(e), False, False

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
                    idx, display_name, source_label, created, err_msg, was_cancelled, was_skipped = fut.result()
                    if was_cancelled:
                        cancelled = True
                        continue
                    completed += 1
                    if was_skipped:
                        self.skipped_count += 1
                    elif err_msg:
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
        self.app_settings = copy.deepcopy(app_settings or {})
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
    _ALLOWED_IPC_EXTENSIONS = (".fb2", ".zip", ".ttf", ".otf", ".woff", ".woff2")
    activation_requested = pyqtSignal(list)

    @classmethod
    def _is_allowed_ipc_path(cls, path):
        if not isinstance(path, str) or not path or "\x00" in path:
            return False
        if os.path.isdir(path):
            return True
        return os.path.isfile(path) and path.lower().endswith(cls._ALLOWED_IPC_EXTENSIONS)

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
        if hasattr(self._server, "setSocketOptions") and hasattr(QLocalServer, "SocketOption"):
            self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
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

    def _finalize_ipc_payload(self, conn, raw):
        try:
            conn.disconnectFromServer()
        except Exception:
            pass
        try:
            conn.deleteLater()
        except Exception:
            pass
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
                    paths = [p for p in data["paths"] if self._is_allowed_ipc_path(p)]
            except Exception as e:
                logger.warning("Некорректный JSON в IPC-сообщении: %s", e)
        self.activation_requested.emit(paths)

    def _on_new_connection(self):
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            if conn is None:
                continue
            limit = self.MAX_IPC_PAYLOAD_BYTES + 1
            if hasattr(conn, "readyRead") and hasattr(conn, "disconnected"):
                state = {"chunks": [], "total": 0, "done": False}
                deadline_timer = QTimer(self)
                deadline_timer.setSingleShot(True)

                def _finish(c=conn, st=state, tm=deadline_timer):
                    if st["done"]:
                        return
                    st["done"] = True
                    tm.stop()
                    tm.deleteLater()
                    self._finalize_ipc_payload(c, b"".join(st["chunks"]))

                def _drain(c=conn, st=state, lim=limit, fin=_finish):
                    if st["done"]:
                        return
                    while st["total"] < lim and c.bytesAvailable() > 0:
                        part = bytes(c.read(lim - st["total"]))
                        if not part:
                            break
                        st["chunks"].append(part)
                        st["total"] += len(part)
                    if st["total"] >= lim:
                        fin()

                conn.readyRead.connect(_drain)
                conn.disconnected.connect(_finish)
                deadline_timer.timeout.connect(_finish)
                deadline_timer.start(500)
                if conn.bytesAvailable() > 0:
                    _drain()
                continue

            # Резервный путь для синхронных mock-соединений без Qt-сигналов (ограничен общим дедлайном 0.5 с)
            chunks = []
            total_len = 0
            deadline = time.monotonic() + 0.5
            if conn.bytesAvailable() > 0 or conn.waitForReadyRead(300):
                while total_len < limit and time.monotonic() < deadline:
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
            self._finalize_ipc_payload(conn, b"".join(chunks))

    def close(self):
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(self.server_name)
            self._server = None


class DeviceSyncWorker(QThread):
    """Фоновый поток доставки книг на ридер через sync2kindle (MTP/USBMS) или смонтированную папку."""

    status_changed = pyqtSignal(str)
    download_progress = pyqtSignal(object, object, str)
    sync_progress = pyqtSignal(int, str)
    finished_sync = pyqtSignal(bool, str, bool)

    def __init__(
        self,
        mode,
        source_dir,
        target_dir,
        user_data_dir,
        dry_run=False,
        ignore_device_removals=True,
        explicit_files=None,
        parent=None,
    ):
        super().__init__(parent)
        self.mode = str(mode or "mtp").strip().lower()
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.user_data_dir = user_data_dir
        self.dry_run = bool(dry_run)
        self.ignore_device_removals = bool(ignore_device_removals)
        self.explicit_files = list(explicit_files or [])
        self.sent_count = 0
        self.skipped_count = 0
        self.last_error_code = ""
        self.last_error_path = ""
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()
        self.requestInterruption()

    def run(self):
        import inspect
        import shutil
        import subprocess
        import tempfile
        from core.fb2_processor import _run_cancellable_process
        from core.s2k_manager import (
            DEVICE_SYNC_EXEC_LOCK,
            S2kMissingLibraryError,
            S2kPermissionError,
            build_s2k_sync_command,
            download_and_install_s2k,
            is_missing_libmtp_stderr,
            is_no_books_in_source_stderr,
            parse_s2k_copy_action,
            resolve_local_s2k,
            stage_books_for_s2k,
            summarize_s2k_output,
            sync_folder_to_mounted_device,
            write_s2k_sync_config,
        )

        with DEVICE_SYNC_EXEC_LOCK:
            self._run_device_sync_locked(
                _run_cancellable_process,
                S2kMissingLibraryError,
                S2kPermissionError,
                build_s2k_sync_command,
                download_and_install_s2k,
                is_missing_libmtp_stderr,
                is_no_books_in_source_stderr,
                parse_s2k_copy_action,
                resolve_local_s2k,
                stage_books_for_s2k,
                summarize_s2k_output,
                sync_folder_to_mounted_device,
                write_s2k_sync_config,
                inspect,
                shutil,
                subprocess,
                tempfile,
            )

    def _run_folder_sync(self, sync_folder_to_mounted_device):
        self.status_changed.emit(tr("settings.sync_status_copying"))
        self.sync_progress.emit(5, tr("settings.sync_status_copying"))

        def _on_folder_prog(cur, total, fname):
            pct = 5 + int(90 * cur / max(1, total))
            self.sync_progress.emit(
                pct,
                tr("converter.progress_sync_file", cur=cur, total=total, name=fname),
            )

        res = sync_folder_to_mounted_device(
            self.source_dir,
            self.target_dir,
            dry_run=self.dry_run,
            explicit_files=self.explicit_files,
            progress_callback=_on_folder_prog,
        )
        self.sent_count = len(res["copied"])
        self.skipped_count = len(res["skipped"])
        self.sync_progress.emit(100, tr("converter.progress_sync_done", count=self.sent_count))
        lines = []
        if res["copied"]:
            prefix = tr("settings.sync_dry_would_copy") if self.dry_run else tr("settings.sync_copied")
            lines.append(f"{prefix} ({len(res['copied'])}):")
            lines.extend(f"  • {name}" for name in res["copied"])
        if res["skipped"]:
            lines.append(f"{tr('settings.sync_skipped')} ({len(res['skipped'])})")
        if not lines:
            lines.append(tr("settings.sync_nothing"))
        self.finished_sync.emit(True, "\n".join(lines), self.dry_run)

    def _ensure_s2k_binary(self, resolve_local_s2k, download_and_install_s2k):
        self.status_changed.emit(tr("settings.sync_status_checking_s2k"))
        self.sync_progress.emit(5, tr("settings.sync_status_checking_s2k"))
        info = resolve_local_s2k(self.user_data_dir, raise_on_missing_lib=True)
        if info:
            return info
        self.status_changed.emit("downloading")
        self.sync_progress.emit(-1, tr("settings.sync_status_downloading_s2k"))

        def _on_dl_prog(dl, tot, name):
            self.download_progress.emit(dl, tot, name)
            if tot and tot > 0:
                pct = max(0, min(100, int(dl * 100 / tot)))
                self.sync_progress.emit(pct, tr("settings.sync_status_downloading_s2k"))

        def _on_dl_status(st):
            self.status_changed.emit(st)
            if st == "verifying":
                self.sync_progress.emit(-1, tr("settings.sync_status_verifying_s2k"))

        return download_and_install_s2k(
            self.user_data_dir,
            cancel_event=self._cancel_event,
            progress_callback=_on_dl_prog,
            status_callback=_on_dl_status,
        )

    def _run_device_sync_locked(
        self,
        _run_cancellable_process,
        S2kMissingLibraryError,
        S2kPermissionError,
        build_s2k_sync_command,
        download_and_install_s2k,
        is_missing_libmtp_stderr,
        is_no_books_in_source_stderr,
        parse_s2k_copy_action,
        resolve_local_s2k,
        stage_books_for_s2k,
        summarize_s2k_output,
        sync_folder_to_mounted_device,
        write_s2k_sync_config,
        inspect,
        shutil,
        subprocess,
        tempfile,
    ):
        tmp_cfg_path = None
        staging_dir = None
        try:
            if self.mode == "folder":
                self._run_folder_sync(sync_folder_to_mounted_device)
                return

            info = self._ensure_s2k_binary(resolve_local_s2k, download_and_install_s2k)
            work_dir = self.user_data_dir
            if not work_dir or not os.path.isdir(work_dir):
                work_dir = os.path.dirname(os.path.abspath(info["path"]))

            staging_dir = tempfile.mkdtemp(prefix="s2k_stage_", dir=work_dir)
            staged_books = stage_books_for_s2k(
                self.source_dir,
                staging_dir,
                explicit_files=self.explicit_files,
            )
            if not staged_books:
                logger.warning("В папке-источнике не найдено готовых книг для Kindle: %s", self.source_dir)
                self.finished_sync.emit(
                    False,
                    tr("settings.sync_err_no_books_in_source", source=os.path.abspath(self.source_dir)),
                    self.dry_run,
                )
                return
            total_staged = len(staged_books)
            logger.info("Подготовлено книг для sync2kindle: %d (из %s)", total_staged, self.source_dir)
            self.sync_progress.emit(10, tr("converter.progress_sync_prep", total=total_staged))

            fd, tmp_cfg_path = tempfile.mkstemp(prefix="s2k_sync_", suffix=".yaml", dir=work_dir)
            os.close(fd)
            write_s2k_sync_config(tmp_cfg_path, staging_dir, self.target_dir)

            cmd = build_s2k_sync_command(
                info["path"],
                self.mode,
                staging_dir,
                self.target_dir,
                dry_run=self.dry_run,
                ignore_device_removals=self.ignore_device_removals,
                config_path=tmp_cfg_path,
            )
            self.status_changed.emit("syncing")
            self.sync_progress.emit(15, tr("converter.progress_sync_connect"))

            live_copied = [0]

            def _on_s2k_line(line):
                fname = parse_s2k_copy_action(line)
                if fname:
                    live_copied[0] += 1
                    cur = min(live_copied[0], total_staged)
                    pct = 15 + int(80 * cur / max(1, total_staged))
                    self.sync_progress.emit(
                        pct,
                        tr("converter.progress_sync_file", cur=cur, total=total_staged, name=fname),
                    )

            try:
                supports_streaming = "on_output_line" in inspect.signature(_run_cancellable_process).parameters
            except (TypeError, ValueError):
                supports_streaming = False

            if supports_streaming:
                stdout, stderr = _run_cancellable_process(
                    cmd,
                    cwd=work_dir,
                    cancel_event=self._cancel_event,
                    on_output_line=_on_s2k_line,
                )
            else:
                stdout, stderr = _run_cancellable_process(
                    cmd,
                    cwd=work_dir,
                    cancel_event=self._cancel_event,
                )

            raw_output = "\n".join(p for p in ((stdout or "").strip(), (stderr or "").strip()) if p)
            if raw_output:
                logger.info("Вывод sync2kindle (dry_run=%s):\n%s", self.dry_run, raw_output)
            summary = summarize_s2k_output(raw_output)
            self.sent_count = summary["count"]
            self.sync_progress.emit(100, tr("converter.progress_sync_done", count=self.sent_count))

            if self.sent_count > 0:
                summary_msg = (
                    tr("converter.msg_sync_dry_count", count=self.sent_count)
                    if self.dry_run
                    else tr("converter.msg_sync_done_count", count=self.sent_count)
                )
            else:
                summary_msg = tr("converter.msg_sync_done_none")
            self.finished_sync.emit(True, summary_msg, self.dry_run)
        except ConversionCancelledError:
            self.finished_sync.emit(False, tr("settings.sync_cancelled"), self.dry_run)
        except S2kMissingLibraryError as e:
            logger.error("sync2kindle не может запуститься: отсутствует libmtp (%s)", e)
            self.finished_sync.emit(False, tr("settings.sync_err_macos_libmtp"), self.dry_run)
        except S2kPermissionError as e:
            err_path = str(e).strip() if os.path.isabs(str(e).strip()) else os.path.abspath(self.source_dir)
            self.last_error_code = "permission"
            self.last_error_path = err_path
            logger.error("Нет прав доступа macOS к папке %s: %s", err_path, e)
            self.finished_sync.emit(
                False,
                tr("settings.sync_err_permission", source=err_path),
                self.dry_run,
            )
        except subprocess.CalledProcessError as e:
            if self._cancel_event.is_set():
                self.finished_sync.emit(False, tr("settings.sync_cancelled"), self.dry_run)
                return
            details = "\n".join(
                p for p in ((getattr(e, "stderr", "") or "").strip(), (getattr(e, "output", "") or "").strip()) if p
            )
            if is_missing_libmtp_stderr(details):
                logger.error("sync2kindle завершился с ошибкой отсутствия libmtp: %s", details)
                self.finished_sync.emit(False, tr("settings.sync_err_macos_libmtp"), self.dry_run)
                return
            if is_no_books_in_source_stderr(details):
                logger.warning("sync2kindle не нашёл готовых книг в %s: %s", self.source_dir, details)
                self.finished_sync.emit(
                    False,
                    tr("settings.sync_err_no_books_in_source", source=os.path.abspath(self.source_dir)),
                    self.dry_run,
                )
                return
            err_msg = details or str(e)
            logger.error("Ошибка синхронизации с ридером: %s", err_msg)
            self.finished_sync.emit(False, err_msg, self.dry_run)
        except Exception as e:
            if self._cancel_event.is_set():
                self.finished_sync.emit(False, tr("settings.sync_cancelled"), self.dry_run)
                return
            logger.error("Ошибка синхронизации с ридером: %s", e)
            self.finished_sync.emit(False, str(e), self.dry_run)
        finally:
            if tmp_cfg_path and os.path.exists(tmp_cfg_path):
                try:
                    os.remove(tmp_cfg_path)
                except OSError:
                    pass
            if staging_dir and os.path.isdir(staging_dir):
                shutil.rmtree(staging_dir, ignore_errors=True)


class MetadataLookupWorker(QThread):
    """Фоновый поток Фазы 1: онлайн-поиск кандидатов метаданных по провайдерам."""

    finished_lookup = pyqtSignal(object)

    def __init__(
        self,
        title="",
        author="",
        isbn="",
        enabled_providers=None,
        google_books_api_key="",
        opds_url="",
        opds_username="",
        opds_password="",
        limit_per_provider=4,
        parent=None,
    ):
        super().__init__(parent)
        self.title = str(title or "")
        self.author = str(author or "")
        self.isbn = str(isbn or "")
        self.enabled_providers = list(enabled_providers) if enabled_providers is not None else None
        self.google_books_api_key = str(google_books_api_key or "")
        self.opds_url = str(opds_url or "")
        self.opds_username = str(opds_username or "")
        self.opds_password = str(opds_password or "")
        self.limit_per_provider = int(limit_per_provider or 4)
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()
        self.requestInterruption()

    def run(self):
        from core.metadata_lookup import LookupResult, search_book_metadata

        try:
            res = search_book_metadata(
                title=self.title,
                author=self.author,
                isbn=self.isbn,
                enabled_providers=self.enabled_providers,
                google_books_api_key=self.google_books_api_key,
                opds_url=self.opds_url,
                opds_username=self.opds_username,
                opds_password=self.opds_password,
                limit_per_provider=self.limit_per_provider,
                cancel_event=self._cancel_event,
            )
            self.finished_lookup.emit(res)
        except Exception as e:
            logger.error("Ошибка фонового поиска метаданных: %s", e)
            self.finished_lookup.emit(LookupResult(candidates=[], errors={"lookup": str(e)}))


class CoverFetchWorker(QThread):
    """Фоновый поток Фазы 2: скачивание и дедупликация обложек найденных кандидатов."""

    finished_covers = pyqtSignal(list)

    def __init__(
        self,
        candidates,
        max_covers=8,
        opds_url="",
        opds_username="",
        opds_password="",
        parent=None,
    ):
        super().__init__(parent)
        self.candidates = list(candidates or [])
        self.max_covers = int(max_covers or 8)
        self.opds_url = str(opds_url or "")
        self.opds_username = str(opds_username or "")
        self.opds_password = str(opds_password or "")
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()
        self.requestInterruption()

    def run(self):
        from core.metadata_lookup import fetch_candidate_covers

        try:
            covers = fetch_candidate_covers(
                self.candidates,
                max_covers=self.max_covers,
                opds_url=self.opds_url,
                opds_username=self.opds_username,
                opds_password=self.opds_password,
                cancel_event=self._cancel_event,
            )
            self.finished_covers.emit(covers)
        except Exception as e:
            logger.error("Ошибка фоновой загрузки обложек: %s", e)
            self.finished_covers.emit([])


class BackgroundTaskWorker(QThread):
    """Универсальный фоновый поток для файловых операций очереди без блокировки GUI."""

    finished_task = pyqtSignal(object, object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
            self.finished_task.emit(result, None)
        except Exception as e:
            self.finished_task.emit(None, e)

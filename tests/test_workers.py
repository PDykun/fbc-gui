import json
import os
import tempfile
import unittest
from unittest import mock

from core import workers


class _FakeConn:
    def __init__(self, payload: bytes, chunk_size: int | None = None):
        if chunk_size and payload:
            self._chunks = [payload[i:i + chunk_size] for i in range(0, len(payload), chunk_size)]
        elif payload:
            self._chunks = [payload]
        else:
            self._chunks = []
        self._buf = b""
        self.disconnected = False
        self.deleted = False

    def bytesAvailable(self):
        return len(self._buf)

    def waitForReadyRead(self, _timeout):
        if self._buf:
            return True
        if self._chunks:
            self._buf += self._chunks.pop(0)
            return True
        return False

    def read(self, max_bytes):
        if not self._buf and self._chunks:
            self._buf += self._chunks.pop(0)
        out = self._buf[:max_bytes]
        self._buf = self._buf[max_bytes:]
        return out

    def disconnectFromServer(self):
        self.disconnected = True

    def deleteLater(self):
        self.deleted = True


class _FakeServer:
    def __init__(self, conns):
        self._conns = list(conns)

    def hasPendingConnections(self):
        return bool(self._conns)

    def nextPendingConnection(self):
        return self._conns.pop(0) if self._conns else None


class TestWorkers(unittest.TestCase):
    def test_single_instance_accepts_valid_paths_and_filters_missing(self):
        with tempfile.TemporaryDirectory() as td:
            real_file = os.path.join(td, "book.fb2")
            with open(real_file, "w", encoding="utf-8") as f:
                f.write("<FictionBook/>")
            missing_file = os.path.join(td, "missing.fb2")

            mgr = workers.SingleInstanceManager(server_name="test_ipc_valid")
            received = []
            mgr.activation_requested.connect(received.append)

            payload = json.dumps({"paths": [real_file, missing_file, 123]}).encode("utf-8")
            conn = _FakeConn(payload, chunk_size=16)
            mgr._server = _FakeServer([conn])
            mgr._on_new_connection()

            self.assertEqual(received, [[real_file]])
            self.assertTrue(conn.disconnected)
            self.assertTrue(conn.deleted)

    def test_single_instance_rejects_oversized_and_malformed_payloads(self):
        mgr = workers.SingleInstanceManager(server_name="test_ipc_bad")
        received = []
        mgr.activation_requested.connect(received.append)

        oversized = b"x" * (workers.SingleInstanceManager.MAX_IPC_PAYLOAD_BYTES + 10)
        mgr._server = _FakeServer([_FakeConn(oversized)])
        with self.assertLogs("fbc_gui.workers", level="WARNING") as cm_big:
            mgr._on_new_connection()
        self.assertEqual(received[-1], [])
        self.assertTrue(any("лимит" in line for line in cm_big.output))

        mgr._server = _FakeServer([_FakeConn(b"{bad json")])
        with self.assertLogs("fbc_gui.workers", level="WARNING") as cm_bad:
            mgr._on_new_connection()
        self.assertEqual(received[-1], [])
        self.assertTrue(any("JSON" in line for line in cm_bad.output))

    def test_file_import_worker_imports_fb2_and_deduplicates(self):
        fb2_xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            '<description><title-info>'
            '<author><first-name>Лев</first-name><last-name>Толстой</last-name></author>'
            '<book-title>Война и мир</book-title>'
            '</title-info></description><body><section><p>Текст</p></section></body>'
            '</FictionBook>'
        )
        with tempfile.TemporaryDirectory() as td:
            fp = os.path.join(td, "sample.fb2")
            with open(fp, "w", encoding="utf-8") as f:
                f.write(fb2_xml)

            worker = workers.FileImportWorker([fp], existing_keys=set())
            results = []
            worker.finished_import.connect(lambda items, cancelled: results.append((items, cancelled)))
            worker.run()

            self.assertEqual(len(results), 1)
            items, cancelled = results[0]
            self.assertFalse(cancelled)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["meta"]["title"], "Война и мир")

            # Повторный импорт с тем же source_key пропускает дубликат
            worker2 = workers.FileImportWorker([fp], existing_keys={items[0]["source_key"]})
            results2 = []
            worker2.finished_import.connect(lambda itms, canc: results2.append((itms, canc)))
            worker2.run()
            self.assertEqual(results2[0][0], [])

    def test_conversion_worker_resolve_count_and_empty_items(self):
        w_auto = workers.ConversionWorker(
            items=[],
            selected_format="epub3",
            save_mode="source",
            custom_dir="",
            title_style_params={},
            compression=None,
            email_enabled=False,
            app_settings={"convert_workers": "auto"},
        )
        self.assertGreaterEqual(w_auto._resolve_worker_count(10), 1)
        self.assertLessEqual(w_auto._resolve_worker_count(10), 4)

        w_fixed = workers.ConversionWorker(
            items=[],
            selected_format="epub3",
            save_mode="source",
            custom_dir="",
            title_style_params={},
            compression=None,
            email_enabled=False,
            app_settings={"convert_workers": "99"},
        )
        self.assertEqual(w_fixed._resolve_worker_count(10), 8)
        self.assertEqual(w_fixed._resolve_worker_count(2), 2)

        emitted = []
        w_auto.finished_all.connect(lambda *args: emitted.append(args))
        w_auto.run()
        self.assertEqual(emitted, [(0, [], [], "", False, [])])

    def test_email_worker_emits_success_and_error(self):
        w_ok = workers.TestEmailWorker({"smtp_host": "localhost"}, app_name="FBC GUI", app_version="2.8.3")
        out_ok = []
        w_ok.finished_test.connect(lambda ok, err: out_ok.append((ok, err)))
        with mock.patch.object(workers, "dispatch_test_email") as mock_send:
            w_ok.run()
        mock_send.assert_called_once_with({"smtp_host": "localhost"}, "FBC GUI", "2.8.3")
        self.assertEqual(out_ok, [(True, "")])

        w_err = workers.TestEmailWorker({"smtp_host": "localhost"}, app_name="FBC GUI", app_version="2.8.3")
        out_err = []
        w_err.finished_test.connect(lambda ok, err: out_err.append((ok, err)))
        with mock.patch.object(workers, "dispatch_test_email", side_effect=RuntimeError("smtp down")):
            w_err.run()
        self.assertEqual(out_err, [(False, "smtp down")])

    def test_single_instance_graceful_without_qt_network(self):
        mgr = workers.SingleInstanceManager(server_name="test_no_net")
        with mock.patch.object(workers, "HAS_QT_NETWORK", False):
            self.assertFalse(mgr.try_send_to_running(["/tmp/a.fb2"]))
            self.assertFalse(mgr.start_server())

    def test_conversion_worker_skips_existing_up_to_date_books(self):
        import time

        with tempfile.TemporaryDirectory() as td:
            src_fb2 = os.path.join(td, "book.fb2")
            out_dir = os.path.join(td, "out")
            os.makedirs(out_dir, exist_ok=True)
            with open(src_fb2, "wb") as fh:
                fh.write(b"<FictionBook/>")

            meta = {"last": "Толстой", "first": "Лев", "mid": "", "series": "", "num": "", "title": "Война и мир"}
            target_file = os.path.join(out_dir, "Толстой - Война и мир.epub")
            with open(target_file, "wb") as fh:
                fh.write(b"EPUB")
            now = time.time()
            os.utime(src_fb2, (now - 30, now - 30))
            os.utime(target_file, (now, now))

            item = {
                "item_id": "row_1",
                "path": src_fb2,
                "display_name": "book.fb2",
                "meta": dict(meta),
                "orig_meta": dict(meta),
                "cover_modified": False,
            }
            w = workers.ConversionWorker(
                items=[item],
                selected_format="epub3",
                save_mode="custom",
                custom_dir=out_dir,
                title_style_params={},
                compression=None,
                email_enabled=False,
                app_settings={"convert_workers": "1", "filename_mode": "default"},
                skip_existing=True,
            )
            from PyQt6.QtCore import Qt
            statuses = []
            finished = []
            w.item_status.connect(lambda iid, st, err: statuses.append((iid, st, err)), Qt.ConnectionType.DirectConnection)
            w.finished_all.connect(lambda *args: finished.append(args), Qt.ConnectionType.DirectConnection)

            with mock.patch.object(workers, "convert_book_file") as mock_conv:
                w.run()

            mock_conv.assert_not_called()
            self.assertEqual(statuses, [("row_1", "skipped", "")])
            self.assertEqual(w.skipped_count, 1)
            self.assertEqual(finished, [(0, [], [], "", False, [])])


    def test_single_instance_ipc_path_filtering(self):
        from core.workers import SingleInstanceManager

        with tempfile.TemporaryDirectory() as td:
            fb2_p = os.path.join(td, "book.fb2")
            zip_p = os.path.join(td, "book.zip")
            ttf_p = os.path.join(td, "font.ttf")
            txt_p = os.path.join(td, "note.txt")
            for p in (fb2_p, zip_p, ttf_p, txt_p):
                with open(p, "wb") as fh:
                    fh.write(b"x")

            self.assertTrue(SingleInstanceManager._is_allowed_ipc_path(td))
            self.assertTrue(SingleInstanceManager._is_allowed_ipc_path(fb2_p))
            self.assertTrue(SingleInstanceManager._is_allowed_ipc_path(zip_p))
            self.assertTrue(SingleInstanceManager._is_allowed_ipc_path(ttf_p))
            self.assertFalse(SingleInstanceManager._is_allowed_ipc_path(txt_p))
            self.assertFalse(SingleInstanceManager._is_allowed_ipc_path(fb2_p + "\x00.txt"))

    def test_conversion_worker_deepcopies_nested_app_settings(self):
        src_settings = {
            "convert_workers": "2",
            "filename_tokens": [{"type": "author"}],
        }
        w = workers.ConversionWorker(
            items=[],
            selected_format="epub3",
            save_mode="source",
            custom_dir="",
            title_style_params={"h1_cl": "red"},
            compression=None,
            email_enabled=False,
            app_settings=src_settings,
        )
        src_settings["filename_tokens"].append({"type": "title"})
        self.assertEqual(len(w.app_settings["filename_tokens"]), 1)

    def test_stop_qthread_safely_detaches_stuck_thread_and_cleans_orphan(self):
        import threading
        from PyQt6.QtCore import QThread
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        release_ev = threading.Event()
        cancelled = []

        class _StuckWorker(QThread):
            def cancel(self):
                cancelled.append(True)

            def run(self):
                release_ev.wait(timeout=3.0)

        w = _StuckWorker()
        w.start()
        try:
            stopped = workers.stop_qthread_safely(w, timeout_ms=40, label="test_stuck")
            self.assertFalse(stopped)
            self.assertEqual(cancelled, [True])
            self.assertIn(w, workers._ORPHANED_THREADS)
            self.assertIsNone(w.parent())
        finally:
            release_ev.set()
            w.wait(2000)
            app.processEvents()

        self.assertNotIn(w, workers._ORPHANED_THREADS)


if __name__ == "__main__":
    unittest.main()

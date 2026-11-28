import json
import logging
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from core import logger as log_mod


class TestDebugLogging(unittest.TestCase):
    def tearDown(self):
        log_mod.set_debug_logging(False)

    def test_collect_system_diagnostics_contains_env_and_app_info(self):
        text = log_mod.collect_system_diagnostics({"App": "FBC GUI v2.13", "Format": "epub3"})
        self.assertIn("FBC GUI Debug Diagnostics", text)
        self.assertIn("OS / Platform:", text)
        self.assertIn("Python:", text)
        self.assertIn("SQLite:", text)
        self.assertIn("App: FBC GUI v2.13", text)
        self.assertIn("Format: epub3", text)

    def test_format_all_threads_dump_includes_current_thread(self):
        dump = log_mod.format_all_threads_dump()
        self.assertIn("Active Python Threads Stack Dump", dump)
        self.assertIn(threading.current_thread().name, dump)
        self.assertIn("test_format_all_threads_dump_includes_current_thread", dump)

    def test_set_debug_logging_toggles_level_and_hooks(self):
        orig_sys_hook = sys.excepthook
        orig_thread_hook = getattr(threading, "excepthook", None)
        root = logging.getLogger("fbc_gui")

        with patch.dict(os.environ, {"FBC_GUI_DISABLE_FILE_LOG": "1"}):
            log_mod.set_debug_logging(True, app_info={"App": "TestApp"})
            self.assertTrue(log_mod.is_debug_logging_enabled())
            self.assertEqual(root.level, logging.DEBUG)
            self.assertIs(sys.excepthook, log_mod._debug_sys_excepthook)
            if orig_thread_hook is not None:
                self.assertIs(threading.excepthook, log_mod._debug_threading_excepthook)

            log_mod.set_debug_logging(False)
            self.assertFalse(log_mod.is_debug_logging_enabled())
            self.assertEqual(root.level, logging.INFO)
            self.assertIs(sys.excepthook, orig_sys_hook)
            if orig_thread_hook is not None:
                self.assertIs(threading.excepthook, orig_thread_hook)

    def test_debug_excepthook_logs_traceback_and_thread_dump(self):
        captured = []

        class _ListHandler(logging.Handler):
            def emit(self, record):
                captured.append(self.format(record))

        handler = _ListHandler()
        root = logging.getLogger("fbc_gui")
        root.addHandler(handler)
        try:
            with patch.dict(os.environ, {"FBC_GUI_DISABLE_FILE_LOG": "1"}):
                log_mod.set_debug_logging(True)
                with patch.object(log_mod, "_ORIG_SYS_EXCEPTHOOK", None):
                    try:
                        raise RuntimeError("boom-debug-test")
                    except RuntimeError as exc:
                        log_mod._debug_sys_excepthook(type(exc), exc, exc.__traceback__)
        finally:
            root.removeHandler(handler)

        joined = "\n".join(captured)
        self.assertIn("UNHANDLED EXCEPTION in main thread", joined)
        self.assertIn("RuntimeError: boom-debug-test", joined)
        self.assertIn("Active Python Threads Stack Dump", joined)

    def test_read_startup_debug_flag(self):
        import fbc_gui

        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "settings.json")
            self.assertFalse(fbc_gui._read_startup_debug_flag(sp))
            with open(sp, "w", encoding="utf-8") as f:
                json.dump({"debug_logging": "true"}, f)
            self.assertTrue(fbc_gui._read_startup_debug_flag(sp))
            with open(sp, "w", encoding="utf-8") as f:
                json.dump({"debug_logging": "false"}, f)
            self.assertFalse(fbc_gui._read_startup_debug_flag(sp))


if __name__ == "__main__":
    unittest.main()

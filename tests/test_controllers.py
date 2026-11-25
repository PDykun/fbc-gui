import unittest

from ui.controllers import (
    ConversionController,
    PresetsController,
    PreviewController,
    QueueController,
    SettingsController,
    UpdatesController,
)


class _DummyCombo:
    def __init__(self, data):
        self._data = data

    def currentData(self):
        return self._data

    def currentText(self):
        return str(self._data or "")


class _FakeSettingsHost(SettingsController):
    def __init__(self):
        self.app_settings = {}
        self.saved = 0
        self.fbc_updated = 0
        self.preview_refreshed = 0
        self.scheduled = []
        self.grayscale_cb = _DummyCombo("luma")
        self.fit_to_screen_cb = _DummyCombo("true")
        self.cover_resize_cb = _DummyCombo("stretch")

    def save_app_settings(self):
        self.saved += 1

    def update_fbc_config_file(self):
        self.fbc_updated += 1

    def refresh_preview(self):
        self.preview_refreshed += 1

    def _schedule_settings_save(self, update_fbc_config=False):
        self.scheduled.append(update_fbc_config)

    def _get_combo_data(self, cb, default=""):
        data = cb.currentData()
        return data if data is not None else default


class TestControllers(unittest.TestCase):
    def test_settings_controller_consolidated_handlers(self):
        host = _FakeSettingsHost()

        host.on_footnotes_mode_changed("inline")
        self.assertEqual(host.app_settings["footnotes_mode"], "inline")
        self.assertEqual(host.saved, 1)
        self.assertEqual(host.fbc_updated, 1)

        host.on_toc_placement_changed("invalid_value")
        self.assertEqual(host.app_settings["toc_page_placement"], "after")

        host.on_toc_type_changed("flat")
        self.assertEqual(host.app_settings["toc_type"], "flat")

        host.on_skip_existing_toggled(True)
        self.assertEqual(host.app_settings["skip_existing"], "true")
        self.assertEqual(host.fbc_updated, 3)  # skip_existing не переписывает config.yaml

        host.on_raster_format_changed("png")
        self.assertEqual(host.app_settings["raster_format"], "png")
        self.assertEqual(host.preview_refreshed, 1)

        host.on_grayscale_changed()
        self.assertEqual(host.app_settings["grayscale"], "luma")
        self.assertEqual(host.preview_refreshed, 2)

        host.on_page_map_size_changed("abc")
        self.assertNotIn("page_map_size", host.app_settings)
        self.assertEqual(host.scheduled, [])

        host.on_page_map_size_changed("2500")
        self.assertEqual(host.app_settings["page_map_size"], "2500")
        self.assertEqual(host.scheduled, [True])

    def test_main_window_inherits_all_controllers_and_facades(self):
        import fbc_gui
        from core import fb2_processor
        import ui.dialogs as dialogs

        for ctrl in (
            SettingsController,
            PresetsController,
            PreviewController,
            QueueController,
            ConversionController,
            UpdatesController,
        ):
            self.assertTrue(issubclass(fbc_gui.MainWindow, ctrl))

        # Проверка ключевых реэкспортов фасадов после декомпозиции
        for sym in (
            "parse_metadata",
            "update_fb2_xml",
            "inspect_fb2",
            "repair_and_optimize_fb2",
            "convert_book_file",
            "plan_organize_fb2_files",
            "DEFAULT_FILENAME_TOKENS",
        ):
            self.assertTrue(hasattr(fb2_processor, sym), f"Missing fb2_processor.{sym}")

        for dlg_sym in (
            "show_themed_message",
            "ConversionProgressDialog",
            "BookEditDialog",
            "BatchEditDialog",
            "BookInspectorDialog",
            "OrganizeBooksDialog",
            "MetadataLookupDialog",
        ):
            self.assertTrue(hasattr(dialogs, dlg_sym), f"Missing ui.dialogs.{dlg_sym}")

    def test_main_window_instantiates_and_builds_all_pages(self):
        import os
        from unittest.mock import patch

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        import fbc_gui

        app = QApplication.instance() or QApplication([])
        with (
            patch.object(fbc_gui.MainWindow, "_ensure_fbc_on_startup", lambda self, *a, **kw: None),
            patch.object(fbc_gui.MainWindow, "_schedule_startup_update_check", lambda self, *a, **kw: None),
        ):
            win = fbc_gui.MainWindow()
            try:
                self.assertEqual(win.pages.count(), 5)
                for idx in range(5):
                    win.switch_page(idx)
                    self.assertEqual(win.pages.currentIndex(), idx)
            finally:
                win.close()
                app.processEvents()

    def test_xml_io_rejects_doctype_and_oversized_plain_fb2(self):
        import os
        import tempfile
        from core.fb2.xml_io import _parse_fb2_root, _read_plain_file_limited

        xxe = b'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe "boom">]><FictionBook/>'
        self.assertIsNone(_parse_fb2_root(xxe))

        with tempfile.TemporaryDirectory() as td:
            fp = os.path.join(td, "big.fb2")
            with open(fp, "wb") as fh:
                fh.write(b"x" * 2048)
            with self.assertRaises(ValueError):
                _read_plain_file_limited(fp, max_bytes=1024)

    def test_converter_error_handler_preserves_called_process_error_when_log_unreadable(self):
        import os
        import subprocess
        import tempfile
        from unittest.mock import patch
        from core.fb2.converter import convert_book_file

        sample_fb2 = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            b'<description><title-info><book-title>T</book-title></title-info></description>'
            b'<body><section><p>Hi</p></section></body></FictionBook>'
        )
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "b.fb2")
            with open(src, "wb") as fh:
                fh.write(sample_fb2)
            data = {"path": src, "display_name": "b.fb2", "meta": {"title": "T"}, "xml": sample_fb2}
            real_open = open

            def _fail_proc(cmd, cwd, cancel_event=None):
                with real_open(os.path.join(cwd, "fbc.log"), "w", encoding="utf-8") as lf:
                    lf.write("error details")
                raise subprocess.CalledProcessError(2, cmd, output="", stderr="")

            def _guarded_open(path, *args, **kwargs):
                if str(path).endswith("fbc.log"):
                    raise OSError("locked")
                return real_open(path, *args, **kwargs)

            with patch("core.fb2_processor._run_cancellable_process", side_effect=_fail_proc), \
                 patch("builtins.open", side_effect=_guarded_open):
                with self.assertRaises(RuntimeError) as ctx:
                    convert_book_file("fbc", "config.yaml", td, data, td, "epub3", {})
                self.assertIn("fbc exit code 2", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

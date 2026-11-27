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
            patch.object(fbc_gui.MainWindow, "load_app_settings", lambda self: None),
            patch.object(fbc_gui.MainWindow, "_ensure_fbc_on_startup", lambda self, *a, **kw: None),
            patch.object(fbc_gui.MainWindow, "_schedule_startup_update_check", lambda self, *a, **kw: None),
        ):
            win = fbc_gui.MainWindow()
            try:
                from ui.controllers.library_controller import PAGE_LIBRARY_INDEX
                self.assertEqual(win.pages.count(), 6)
                self.assertTrue(win.nav_buttons[PAGE_LIBRARY_INDEX].isHidden())
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


    def test_preset_none_option_default_and_resets_settings_and_css(self):
        import os
        import tempfile
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton
        from core.config import get_default_app_settings
        from core.css_preview import get_default_css_ui_state
        from core.presets import save_preset

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)

        with tempfile.TemporaryDirectory() as td:
            presets_dir = os.path.join(td, "presets")
            css_path = os.path.join(td, "ebook_styles.css")
            save_preset(presets_dir, "My Kindle", {"output_format": "kfx", "device_profile": "kindle"}, "body {}")

            class _FakePresetHost(PresetsController):
                def __init__(self):
                    self.presets_dir = presets_dir
                    self.bundled_presets_dir = os.path.join(td, "bundled")
                    self.fonts_dir = ""
                    self.css_path = css_path
                    self.app_settings = get_default_app_settings()
                    self.app_settings["active_user_preset"] = ""
                    self.user_preset_combo = QComboBox()
                    self.btn_preset_apply = QPushButton()
                    self.btn_preset_delete = QPushButton()
                    self.btn_preset_restore = QPushButton()
                    self.saved = 0
                    self.fbc_updated = 0

                def _has_blocking_workers(self):
                    return False

                def save_app_settings(self):
                    self.saved += 1

                def update_fbc_config_file(self):
                    self.fbc_updated += 1

                def create_widgets(self):
                    pass

                def _update_undo_redo_ui(self):
                    pass

                def _repopulate_table_from_files_data(self, _sel):
                    pass

                def load_and_parse_css_to_gui(self):
                    pass

                def save_visual_css(self, show_alert=False):
                    pass

                def apply_theme(self, _theme, save=False):
                    pass

                def switch_page(self, _idx):
                    pass

                def refresh_preview(self):
                    pass

            host = _FakePresetHost()
            host.refresh_user_presets_combo()

            # 1. Пункт «Нет» первый и выбран по умолчанию; кнопки «Удалить» и «Сбросить» неактивны
            self.assertEqual(host.user_preset_combo.currentIndex(), 0)
            self.assertEqual(host.user_preset_combo.itemData(0), PresetsController._PRESET_NONE_DATA)
            self.assertEqual(host.user_preset_combo.count(), 2)
            self.assertTrue(host.btn_preset_apply.isEnabled())
            self.assertFalse(host.btn_preset_delete.isEnabled())
            self.assertFalse(host.btn_preset_restore.isEnabled())

            # 2. Имитируем применённый пресет и пользовательские правки, затем выбираем «Нет»
            host.app_settings["active_user_preset"] = "My Kindle"
            host.app_settings["output_format"] = "kfx"
            host.app_settings["device_profile"] = "kindle"
            host.app_settings["filename_mode"] = "custom"
            host.app_settings["css_ui_state"] = {"h1_cl": "black", "drop_color": "black"}
            host.app_settings["smtp_host"] = "smtp.keep.me"
            host.app_settings["custom_output_dir"] = "/keep/my/dir"
            host.user_preset_combo.setCurrentIndex(0)

            with patch("ui.controllers.presets_controller.show_themed_message") as mock_msg:
                host.on_user_preset_activated(0)
                mock_msg.assert_called_once()

            defaults = get_default_app_settings()
            self.assertEqual(host.app_settings["active_user_preset"], "")
            self.assertEqual(host.app_settings["output_format"], defaults["output_format"])
            self.assertEqual(host.app_settings["device_profile"], defaults["device_profile"])
            self.assertEqual(host.app_settings["filename_mode"], defaults["filename_mode"])
            self.assertEqual(host.app_settings["css_ui_state"], get_default_css_ui_state())
            self.assertEqual(host.app_settings["smtp_host"], "smtp.keep.me")
            self.assertEqual(host.app_settings["custom_output_dir"], "/keep/my/dir")
            self.assertTrue(os.path.isfile(css_path))
            self.assertEqual(host.user_preset_combo.currentIndex(), 0)


    def test_single_source_version_and_targeted_preset_ui_refresh(self):
        import os
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication
        import core.fbc_manager as fbc_manager
        import core.metadata_lookup as metadata_lookup
        import core.version as version_mod
        import fbc_gui

        # 1. Единый источник версии core/version.py
        self.assertEqual(fbc_gui.__version__, version_mod.__version__)
        self.assertEqual(fbc_gui.__build__, version_mod.__build__)
        self.assertIn(version_mod.__version__, fbc_manager.FBC_HTTP_USER_AGENT)
        self.assertIn(version_mod.__version__, metadata_lookup.LOOKUP_USER_AGENT)
        try:
            import update_version_json
        except ModuleNotFoundError:
            update_version_json = None
        if update_version_json is not None:
            ver, bld = update_version_json.extract_app_meta(fbc_gui.__file__)
            self.assertEqual((ver, bld), (version_mod.__version__, version_mod.__build__))

        # 2. При применении пресета не пересоздаются page_converter, table, search_edit и page_preview
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        with (
            patch.object(fbc_gui.MainWindow, "_ensure_fbc_on_startup", lambda self, *a, **kw: None),
            patch.object(fbc_gui.MainWindow, "_schedule_startup_update_check", lambda self, *a, **kw: None),
        ):
            win = fbc_gui.MainWindow()
            try:
                orig_converter_page = win.page_converter
                orig_table = win.table
                orig_search = win.search_edit
                orig_preview_page = win.page_preview
                orig_settings_page = win.page_settings
                win.search_edit.setText("Толстой")
                win.switch_page(3)

                with (
                    patch.object(win, "save_app_settings", lambda: None),
                    patch.object(win, "update_fbc_config_file", lambda: None),
                    patch.object(win, "save_visual_css", lambda show_alert=False: True),
                ):
                    ok = win._apply_preset_payload(
                        {"name": "TestPreset", "settings": {"output_format": "kfx", "grayscale": "luma"}},
                        selected_name="TestPreset",
                    )

                self.assertTrue(ok)
                self.assertIs(win.page_converter, orig_converter_page)
                self.assertIs(win.table, orig_table)
                self.assertIs(win.search_edit, orig_search)
                self.assertIs(win.page_preview, orig_preview_page)
                self.assertIsNot(win.page_settings, orig_settings_page)
                self.assertEqual(win.search_edit.text(), "Толстой")
                self.assertEqual(win.format_combo.currentData(), "kfx")
                self.assertEqual(win.pages.currentIndex(), 3)
            finally:
                win.close()
                app.processEvents()

    def test_updates_controller_schedules_quit_application_on_should_quit(self):
        from unittest.mock import patch

        class _FakeUpdateHost(UpdatesController):
            def __init__(self):
                self._update_dl_dlg = None
                self._update_dl_worker = None
                self.quit_called = 0

            def quit_application(self):
                self.quit_called += 1

        host = _FakeUpdateHost()
        with patch("ui.controllers.updates_controller.show_themed_message"), \
             patch("ui.controllers.updates_controller.QTimer.singleShot") as mock_single:
            host._on_update_dl_finished({"ok": True, "should_quit": True, "cancelled": False})

        mock_single.assert_called_once_with(150, host.quit_application)

    def test_segmented_tab_bar_qss_scoping_avoids_bare_qtabbar_properties(self):
        import os
        import re
        from PyQt6.QtWidgets import QApplication
        from ui.dialogs.common import SegmentedTabBar

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QApplication.instance() or QApplication([])
        bar = SegmentedTabBar()
        self.assertEqual(bar.objectName(), "SegmentedTabBar")

        themes_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "themes")
        for fname in sorted(os.listdir(themes_dir)):
            if not fname.endswith(".qss"):
                continue
            with open(os.path.join(themes_dir, fname), encoding="utf-8") as fh:
                qss = fh.read()
            bare_blocks = re.findall(r"(?m)^QTabBar\s*\{([^}]*)\}", qss)
            for blk in bare_blocks:
                self.assertNotIn("qproperty-trackColor", blk, f"{fname} leaks trackColor onto bare QTabBar")
                self.assertNotIn("qproperty-trackBorderColor", blk, f"{fname} leaks trackBorderColor onto bare QTabBar")
            self.assertIn("QTabBar#SegmentedTabBar", qss, f"{fname} missing QTabBar#SegmentedTabBar block")

    def test_book_edit_dialog_source_and_target_labels_expand_without_clipping(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from ui.dialogs.book_edit import BookEditDialog

        app = QApplication.instance() or QApplication([])
        data = {
            "display_name": "Kornev_Chertopoloh-Kornev-_1_Aspekt-belee-smerti.TbEqvA.805803.fb2.zip",
            "meta": {
                "last": "Корнев",
                "first": "Павел",
                "mid": "Николаевич",
                "series": "Чертополох [Корнев]",
                "num": "1",
                "title": "Аспект белее смерти",
            },
        }
        dlg = BookEditDialog(None, data, "kfx")
        try:
            dlg.show()
            app.processEvents()
            field_w = dlg.ed_last.width()
            self.assertGreaterEqual(dlg.lbl_src_val.width(), field_w)
            self.assertGreaterEqual(dlg.lbl_src_val.height(), dlg.lbl_src_val.heightForWidth(dlg.lbl_src_val.width()))
            self.assertEqual(dlg.lbl_src_val.toolTip(), data["display_name"])

            dlg.ed_title.setText("Очень длинное название книги для проверки автоматического переноса строк без обрезания")
            app.processEvents()
            self.assertGreaterEqual(dlg.lbl_target_val.width(), field_w)
            self.assertGreaterEqual(
                dlg.lbl_target_val.height(),
                dlg.lbl_target_val.heightForWidth(dlg.lbl_target_val.width()),
            )
            self.assertEqual(dlg.lbl_target_val.toolTip(), dlg.lbl_target_val.text())
        finally:
            dlg.close()
            app.processEvents()

    def test_preview_controller_caches_book_preview_and_debounces_style_change(self):
        import os
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QApplication.instance() or QApplication([])

        class _FakePreviewHost(PreviewController):
            def __init__(self):
                self._loading_css = False
                self.saved = 0
                self.refreshed = 0

            def save_visual_css(self, show_alert=False):
                self.saved += 1

            def refresh_preview(self):
                self.refreshed += 1

        host = _FakePreviewHost()
        book = {
            "source_key": "book_1",
            "path": "/nonexistent/book_1.fb2",
            "meta": {"title": "First", "last": "Author"},
            "cover_bytes": b"IMG1",
            "cover_mime": "image/jpeg",
        }
        with patch("ui.controllers.preview_controller.get_book_xml", return_value=b"<FictionBook/>") as mock_xml, \
             patch("ui.controllers.preview_controller.extract_book_preview_data", return_value={"title": "First"}) as mock_ext:
            p1 = host._get_cached_book_preview(book)
            p2 = host._get_cached_book_preview(book)
            self.assertEqual(p1, {"title": "First"})
            self.assertIs(p1, p2)
            self.assertEqual(mock_xml.call_count, 1)
            self.assertEqual(mock_ext.call_count, 1)

            book["meta"] = {"title": "Changed", "last": "Author"}
            host._get_cached_book_preview(book)
            self.assertEqual(mock_ext.call_count, 2)

        host.on_style_param_changed()
        self.assertEqual(host.saved, 1)
        self.assertEqual(host.refreshed, 0)
        self.assertTrue(host._preview_refresh_timer.isActive())
        host._preview_refresh_timer.stop()

    def test_updates_controller_warns_once_on_unverified_fbc(self):
        from unittest.mock import patch

        class _FakeFbcHost(UpdatesController):
            def __init__(self):
                self._fbc_worker = None
                self._fbc_setup_dlg = None
                self._fbc_ready_callback = None
                self.fbc_cmd = ""
                self.fbc_version = ""

            def update_header_status(self):
                pass

        host = _FakeFbcHost()
        res = {"ok": True, "path": "/usr/local/bin/fbc", "version": "2.1.1", "unverified": True, "reason": "offline"}
        with patch("ui.controllers.updates_controller.show_themed_message") as mock_msg:
            host._on_fbc_check_finished(res)
            host._on_fbc_check_finished(res)

        mock_msg.assert_called_once()
        self.assertEqual(mock_msg.call_args[0][3], "warning")

    def test_tray_controller_quit_application_closes_modals_and_schedules_quit(self):
        import os
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication, QDialog
        from ui.controllers import TrayWatchController

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])

        class _FakeTrayHost(TrayWatchController):
            def __init__(self):
                self._force_quit = False
                self.closed = False

            def close(self):
                self.closed = True

        host = _FakeTrayHost()
        modal = QDialog()
        modal.show()
        app.processEvents()
        try:
            with patch("ui.controllers.tray_controller.QTimer.singleShot") as mock_single:
                host.quit_application()
            self.assertTrue(host._force_quit)
            self.assertTrue(host.closed)
            self.assertFalse(modal.isVisible())
            mock_single.assert_called_once_with(0, app.quit)
        finally:
            modal.close()
            app.processEvents()

    def test_segmented_tabs_retain_python_bar_and_s2k_user_agent_and_keyring_copy(self):
        import os
        from PyQt6.QtWidgets import QApplication
        import core.s2k_manager as s2k_manager
        import core.version as version_mod
        from core.i18n import tr
        from ui.dialogs.common import SegmentedTabBar, create_segmented_tabs

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QApplication.instance() or QApplication([])
        tabs = create_segmented_tabs()
        self.assertIsInstance(tabs.tabBar(), SegmentedTabBar)
        self.assertIs(tabs._segmented_tab_bar, tabs.tabBar())
        self.assertGreaterEqual(tabs.tabBar().metaObject().indexOfProperty("trackColor"), 0)

        self.assertIn(version_mod.__version__, s2k_manager.S2K_HTTP_USER_AGENT)
        self.assertNotIn("settings.json", tr("settings.lookup_keyring_warning").lower())

    def test_send_test_email_rejects_crlf_in_app_name_subject(self):
        from core.email_sender import send_test_email

        cfg = {
            "smtp_host": "smtp.example.com",
            "smtp_port": "465",
            "smtp_security": "ssl",
            "smtp_user": "user@example.com",
            "smtp_password": "secret",
            "email_from": "user@example.com",
            "email_to": "reader@example.com",
        }
        with self.assertRaises(ValueError):
            send_test_email(cfg, "FBC\r\nBcc: evil@example.com", "2.12")

    def test_dark_theme_modal_dialogs_render_opaque_dark_background(self):
        import os
        from PyQt6.QtWidgets import QApplication
        from ui.theme import init_themes, build_theme_qss, build_qpalette_from_qss
        from ui.dialogs.inspector import BookInspectorDialog
        from ui.dialogs.book_edit import BookEditDialog, BatchEditDialog
        from ui.dialogs.watch_folder import WatchFolderRuleDialog

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        themes_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "themes")
        init_themes(themes_dir, themes_dir)

        for fname in sorted(os.listdir(themes_dir)):
            if not fname.endswith(".qss"):
                continue
            with open(os.path.join(themes_dir, fname), encoding="utf-8") as fh:
                qss_src = fh.read()
            self.assertLess(
                qss_src.index("QWidget {"),
                qss_src.index("QMainWindow, QDialog"),
                f"{fname}: QWidget rule must precede QDialog rule",
            )

        sample_book = {
            "path": "/tmp/a.fb2",
            "display_name": "a.fb2",
            "meta": {"title": "T", "last": "A", "first": "B", "mid": "", "series": "", "num": ""},
        }
        sample_report = {
            "xml_valid_strict": True,
            "xml_recovered": False,
            "encoding": "utf-8",
            "size_bytes": 100,
            "chapter_count": 0,
            "paragraph_count": 1,
            "footnotes_count": 0,
            "images": [],
            "toc": [],
            "warnings": [],
        }

        for family in ("Modern", "Golden"):
            qss = build_theme_qss(family, family, "dark")
            pal = build_qpalette_from_qss(qss, "dark")
            app.setPalette(pal)
            app.setStyleSheet(qss)
            for dlg in (
                BookInspectorDialog(None, "a.fb2", sample_report),
                BookEditDialog(None, sample_book, "kfx"),
                BatchEditDialog(None, 2, {}),
                WatchFolderRuleDialog(None),
            ):
                try:
                    dlg.show()
                    app.processEvents()
                    px = dlg.grab().toImage().pixelColor(4, 4)
                    self.assertEqual(px.alpha(), 255, f"{family} {type(dlg).__name__} background must be opaque")
                    self.assertLess(px.lightness(), 60, f"{family} {type(dlg).__name__} background must be dark, got {px.name()}")
                finally:
                    dlg.close()
                    app.processEvents()

    def test_modal_dialogs_cancel_and_late_signals_are_crash_safe(self):
        import os
        from PyQt6.QtWidgets import QApplication
        from ui.dialogs import (
            ConversionProgressDialog,
            CoverStudioDialog,
            FbcSetupDialog,
            ImportProgressDialog,
            UpdateDownloadDialog,
        )

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])

        # 1. CoverStudioDialog: отмена останавливает отложенный таймер перерисовки
        cs_dlg = CoverStudioDialog(None, book_data={"meta": {"title": "Дюна", "last": "Герберт"}})
        cs_dlg._schedule_preview()
        self.assertTrue(cs_dlg._debounce_timer.isActive())
        cs_dlg.reject()
        self.assertTrue(cs_dlg._closing)
        self.assertFalse(cs_dlg._debounce_timer.isActive())
        cs_dlg.deleteLater()
        app.processEvents()

        # 2. Progress/Setup/Update диалоги: повторная отмена и запоздалые update_* после finish_and_close безопасны
        for dlg in (
            ConversionProgressDialog(None, 3, show_email=True),
            ImportProgressDialog(None),
            FbcSetupDialog(None),
            UpdateDownloadDialog(None, version_str="2.12"),
        ):
            hits = []
            dlg.cancel_requested.connect(lambda h=hits: h.append(1))
            dlg.reject()
            dlg.reject()  # повторный клик/Esc не должен дублировать сигнал
            self.assertEqual(len(hits), 1)
            self.assertFalse(dlg.btn_cancel.isEnabled())
            dlg.finish_and_close()
            dlg.finish_and_close()  # идемпотентность
            if hasattr(dlg, "update_conversion"):
                dlg.update_conversion(1, "late")
                dlg.update_email(50, "late")
            if hasattr(dlg, "update_progress"):
                dlg.update_progress(1, 2, "late.fb2")
            if hasattr(dlg, "update_download_progress"):
                dlg.update_download_progress(10, 100, "asset")
                dlg.set_status_text("late")
            dlg.deleteLater()
            app.processEvents()

        # 3. UpdatesController: запоздалые сигналы FbcEnsureWorker после завершения не переоткрывают зомби-диалог
        class _FakeUpdateHost(UpdatesController):
            def __init__(self):
                self._closing = False
                self._fbc_worker = None
                self._fbc_setup_dlg = None
                self._update_dl_worker = None
                self._update_dl_dlg = None

        u_host = _FakeUpdateHost()
        u_host._on_fbc_status_changed("downloading:not_found")
        u_host._on_fbc_progress_changed(10, 100, "fbc.zip")
        self.assertIsNone(u_host._fbc_setup_dlg)
        u_host._cancel_fbc_worker()
        u_host._cancel_update_dl_worker()

        # 4. QueueController / SettingsController: безопасная отмена при удалённом C++ воркере
        class _DeletedWorker:
            def requestInterruption(self):
                raise RuntimeError("wrapped C/C++ object deleted")

            def cancel(self):
                raise RuntimeError("wrapped C/C++ object deleted")

        class _FakeQueueHost(QueueController):
            def __init__(self):
                self._import_worker = _DeletedWorker()

        class _FakeSyncHost(SettingsController):
            def __init__(self):
                self._device_sync_worker = _DeletedWorker()
                self._device_sync_cancelled = False

        _FakeQueueHost()._cancel_import_worker()
        sync_host = _FakeSyncHost()
        sync_host._on_device_sync_cancel_requested()
        self.assertTrue(sync_host._device_sync_cancelled)


if __name__ == "__main__":
    unittest.main()

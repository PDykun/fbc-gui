"""Offscreen smoke-тесты диалогов и helper-компонентов UI."""

import os
import tempfile
import unittest

from PyQt6.QtWidgets import QApplication

from ui.dialogs import (
    BatchEditDialog,
    BookInspectorDialog,
    OrganizeBooksDialog,
    WatchFolderRuleDialog,
)


class TestUiDialogsSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_batch_edit_dialog_collects_updates(self):
        dlg = BatchEditDialog(None, 3, {"last": "Толстой", "first": "Лев", "mid": "", "series": "Классика", "lang": "ru"})
        try:
            self.assertEqual(dlg.get_updates(), {})
            self.assertIsNone(dlg.get_genre_operation())
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_book_inspector_dialog_instantiates_with_report(self):
        report = {
            "xml_valid_strict": True,
            "xml_recovered": False,
            "encoding": "utf-8",
            "warnings": [],
            "chapter_count": 2,
            "paragraph_count": 10,
            "footnotes_count": 1,
            "toc": [{"title": "Глава 1", "children": []}],
            "images": [],
        }
        dlg = BookInspectorDialog(None, "sample.fb2", report)
        try:
            self.assertFalse(dlg.debug_requested)
            self.assertFalse(dlg.repair_requested)
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_organize_books_dialog_builds_plan(self):
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "raw.fb2")
            with open(src, "wb") as fh:
                fh.write(b"<FictionBook/>")
            items = [{
                "item_id": "1",
                "path": src,
                "display_name": "raw.fb2",
                "meta": {"last": "Толстой", "first": "Лев", "series": "Классика", "num": "1", "title": "Война"},
            }]
            dlg = OrganizeBooksDialog(None, items, default_dest_dir=td)
            try:
                plan = dlg.get_plan()
                self.assertEqual(len(plan), 1)
                self.assertTrue(dlg.is_copy_mode())
            finally:
                dlg.close()
                dlg.deleteLater()

    def test_watch_folder_rule_dialog_roundtrip(self):
        dlg = WatchFolderRuleDialog(None)
        try:
            rule = dlg.get_rule()
            self.assertIsInstance(rule, dict)
            self.assertIn("delivery_mode", rule)
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_opds_http_warning_and_plaintext_secret_tracking(self):
        from unittest.mock import patch
        from core.config import get_default_app_settings, get_last_plaintext_secret_fields, save_app_settings
        from core.metadata_lookup import OpdsProvider

        prov = OpdsProvider(opds_url="http://opds.local:8080/opds", username="u", password="p")
        with patch("core.metadata_lookup.logger.warning") as warn_mock:
            hdrs = prov._headers_for("http://opds.local:8080/opds/search")
        self.assertIn("Authorization", hdrs)
        warn_mock.assert_called_once()

        with tempfile.TemporaryDirectory() as td:
            sp = os.path.join(td, "settings.json")
            st = get_default_app_settings()
            st["smtp_password"] = "plain_fallback_test"
            with patch("core.config._save_secret_secure", return_value=False):
                save_app_settings(sp, st)
            self.assertIn("smtp_password", get_last_plaintext_secret_fields())
            with open(sp, "r", encoding="utf-8") as fh:
                self.assertNotIn("plain_fallback_test", fh.read())
            if os.name != "nt":
                self.assertEqual(os.stat(sp).st_mode & 0o777, 0o600)

    def test_progress_dialogs_fit_multiline_filenames(self):
        from ui.dialogs import ConversionProgressDialog, ImportProgressDialog

        long_name = "Converting (1 of 1): Демина - (ХДК) - Хельмова дюжина красавиц (Omnibus) — очень длинное название тома.epub"
        dlg = ConversionProgressDialog(None, total_files=1)
        try:
            dlg.show()
            dlg.update_conversion(0, long_name)
            self.assertGreaterEqual(dlg.lbl_convert.minimumHeight(), 36)
            self.assertGreaterEqual(dlg.height(), dlg.sizeHint().height())
        finally:
            dlg.finish_and_close()
            dlg.deleteLater()

        imp = ImportProgressDialog(None)
        try:
            imp.show()
            imp.update_progress(1, 5, long_name)
            self.assertGreaterEqual(imp.lbl_status.minimumHeight(), 36)
            self.assertGreaterEqual(imp.height(), imp.sizeHint().height())
        finally:
            imp.finish_and_close()
            imp.deleteLater()


if __name__ == "__main__":
    unittest.main()

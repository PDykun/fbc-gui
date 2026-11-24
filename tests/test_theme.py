import os
import tempfile
import unittest
from unittest import mock

from ui.theme import (
    ExternalThemeRegistry,
    parse_palette_from_qss,
    parse_theme_tokens_from_qss,
)


class TestThemeRegistry(unittest.TestCase):
    def test_load_qss_logs_warning_on_read_error(self):
        with tempfile.TemporaryDirectory() as td:
            qss_path = os.path.join(td, "modern_dark.qss")
            with open(qss_path, "w", encoding="utf-8") as f:
                f.write("/* test */")

            reg = ExternalThemeRegistry(themes_dir=td, bundled_dir=td)
            with mock.patch("builtins.open", side_effect=OSError("permission denied")):
                with self.assertLogs("fbc_gui.theme", level="WARNING") as cm:
                    out = reg.load_qss("Modern", "dark")

            self.assertEqual(out, "")
            self.assertTrue(any("modern_dark.qss" in line for line in cm.output))

    def test_parse_palette_and_tokens_from_qss(self):
        qss = """
        /*
         * @palette-window: #112233
         * @palette-highlight: #445566
         * @halo-primary: rgba(10, 20, 30, 128)
         * @row-sel-border: #AABBCC
         */
        QWidget { color: white; }
        """
        pal = parse_palette_from_qss(qss, mode="dark")
        self.assertEqual(pal["window"], "#112233")
        self.assertEqual(pal["highlight"], "#445566")

        tokens = parse_theme_tokens_from_qss(qss, mode="dark")
        self.assertEqual(tokens["halo_primary"], "rgba(10, 20, 30, 128)")
        self.assertEqual(tokens["row_sel_border"], "#AABBCC")

    def test_book_edit_dialog_updates_target_preview_on_metadata_changes(self):
        from PyQt6.QtWidgets import QApplication
        from core.fb2_processor import DEFAULT_FILENAME_TOKENS
        from ui.dialogs import BookEditDialog

        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        data = {
            "path": "/tmp/sample.fb2",
            "display_name": "sample.fb2",
            "meta": {
                "last": "Толстой",
                "first": "Лев",
                "mid": "Николаевич",
                "series": "Классика",
                "num": "1",
                "title": "Война и мир",
            },
        }
        dlg = BookEditDialog(
            None,
            data,
            output_format="epub3",
            filename_mode="custom",
            filename_tokens=DEFAULT_FILENAME_TOKENS,
        )
        try:
            self.assertIn("Толстой", dlg.lbl_target_val.text())
            dlg.ed_last.setText("Чехов")
            self.assertIn("Чехов", dlg.lbl_target_val.text())
            dlg.ed_series.setText("Собрание Сочинений")
            dlg.ed_num.setText("3")
            dlg.ed_title.setText("Чайка")
            self.assertEqual(dlg.lbl_target_val.text(), "Чехов - (СС - 03) Чайка.epub")
        finally:
            dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()

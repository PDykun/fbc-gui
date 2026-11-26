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
            self.assertEqual(dlg.lbl_target_val.text(), "Чехов - (СС-03) - Чайка.epub")
        finally:
            dlg.deleteLater()

    def test_book_inspector_dialog_renders_tabs_and_debug_action(self):
        from PyQt6.QtWidgets import QApplication
        from ui.dialogs import BookInspectorDialog

        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        report = {
            "encoding": "utf-8",
            "file_size_bytes": 4096,
            "xml_valid_strict": False,
            "xml_recovered": True,
            "warnings": [{"code": "broken_xml", "severity": "warning", "count": 1}],
            "toc": [{"title": "Глава 1", "children": [{"title": "Сцена 1.1", "children": []}]}],
            "chapter_count": 2,
            "paragraph_count": 12,
            "footnotes_count": 3,
            "images": [
                {"id": "cover.jpg", "content_type": "image/jpeg", "size_bytes": 2048, "width": 600, "height": 900, "valid": True, "oversized": False, "is_cover": True},
            ],
            "total_images_bytes": 2048,
        }
        dlg = BookInspectorDialog(None, "sample.fb2", report)
        try:
            self.assertEqual(dlg.tabs.count(), 3)
            self.assertEqual(dlg.toc_tree.topLevelItemCount(), 1)
            self.assertEqual(dlg.media_table.rowCount(), 1)
            self.assertFalse(dlg.debug_requested)
            dlg._on_debug_clicked()
            self.assertTrue(dlg.debug_requested)
        finally:
            dlg.deleteLater()

    def test_template_builder_separator_chips_are_non_selectable_draggable_labels(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit
        from ui.theme import FilenameTemplateBuilder, _SeparatorChip

        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        for mode in ("filename", "title"):
            builder = FilenameTemplateBuilder(mode=mode)
            try:
                builder._append_text("(")
                builder._append_text(")")
                sep_chips = builder.drop_area.findChildren(_SeparatorChip)
                self.assertGreaterEqual(len(sep_chips), 2)
                for chip in sep_chips:
                    self.assertEqual(chip.findChildren(QLineEdit), [])
                    labels = chip.findChildren(QLabel)
                    self.assertEqual(len(labels), 1)
                    self.assertEqual(labels[0].textInteractionFlags(), Qt.TextInteractionFlag.NoTextInteraction)
                    self.assertTrue(labels[0].testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
                builder.drop_area._set_drop_indicator(1)
                self.assertIsNotNone(builder.drop_area._drop_indicator_rect())
                builder.drop_area._set_drop_indicator(None)
                self.assertIsNone(builder.drop_area._drop_indicator_rect())
            finally:
                builder.deleteLater()

        from ui.theme import _make_closed_hand_cursor_pixmap
        hand_pix = _make_closed_hand_cursor_pixmap()
        self.assertFalse(hand_pix.isNull())


if __name__ == "__main__":
    unittest.main()

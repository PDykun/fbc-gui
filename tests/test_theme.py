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


if __name__ == "__main__":
    unittest.main()

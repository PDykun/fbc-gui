import json
import os
import tempfile
import unittest

from core.i18n import LocaleManager


class TestLocaleManager(unittest.TestCase):
    def test_read_json_logs_warning_on_malformed_json(self):
        with tempfile.TemporaryDirectory() as td:
            bad_path = os.path.join(td, "broken.json")
            with open(bad_path, "w", encoding="utf-8") as f:
                f.write("{invalid json")

            mgr = LocaleManager(locales_dir=td, bundled_dir=td)
            with self.assertLogs("fbc_gui.i18n", level="WARNING") as cm:
                data = mgr._read_json(bad_path)

            self.assertEqual(data, {})
            self.assertTrue(any("broken.json" in line for line in cm.output))

    def test_fallback_and_format_error_safety(self):
        with tempfile.TemporaryDirectory() as td:
            ru_data = {
                "_lang_code": "ru",
                "_lang_name": "Русский",
                "common": {"hello": "Привет, {name}", "only_ru": "Только RU"},
            }
            en_data = {
                "_lang_code": "en",
                "_lang_name": "English",
                "common": {"hello": "Hello, {name}"},
            }
            with open(os.path.join(td, "ru.json"), "w", encoding="utf-8") as f:
                json.dump(ru_data, f, ensure_ascii=False)
            with open(os.path.join(td, "en.json"), "w", encoding="utf-8") as f:
                json.dump(en_data, f, ensure_ascii=False)

            mgr = LocaleManager(locales_dir=td, bundled_dir=td)
            mgr.set_language("en")
            self.assertEqual(mgr.get("common.hello", name="World"), "Hello, World")
            self.assertEqual(mgr.get("common.only_ru"), "Только RU")
            self.assertEqual(mgr.get("common.missing_key"), "common.missing_key")
            # При несоответствии параметров форматирования не должно быть исключения
            self.assertEqual(mgr.get("common.hello", wrong_arg="X"), "Hello, {name}")


if __name__ == "__main__":
    unittest.main()

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

    def test_bundled_locales_ru_en_parity_and_placeholders(self):
        import re

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ru_path = os.path.join(project_root, "locales", "ru.json")
        en_path = os.path.join(project_root, "locales", "en.json")

        def _flatten(node, prefix=""):
            out = {}
            for k, v in node.items():
                key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    out.update(_flatten(v, key))
                else:
                    out[key] = v
            return out

        with open(ru_path, encoding="utf-8") as fh:
            ru_flat = _flatten(json.load(fh))
        with open(en_path, encoding="utf-8") as fh:
            en_flat = _flatten(json.load(fh))

        self.assertEqual(set(ru_flat.keys()), set(en_flat.keys()))
        ph_re = re.compile(r"\{([a-zA-Z0-9_]+)(?:![rsa])?(?::[^}]+)?\}")
        for key in sorted(ru_flat.keys()):
            ru_val, en_val = ru_flat[key], en_flat[key]
            self.assertEqual(type(ru_val), type(en_val), f"Type mismatch for {key}")
            if isinstance(ru_val, str):
                self.assertTrue(ru_val.strip(), f"Empty RU string for {key}")
                self.assertTrue(en_val.strip(), f"Empty EN string for {key}")
                self.assertEqual(
                    set(ph_re.findall(ru_val)),
                    set(ph_re.findall(en_val)),
                    f"Placeholder mismatch for {key}",
                )
            elif isinstance(ru_val, list):
                self.assertEqual(len(ru_val), len(en_val), f"List length mismatch for {key}")


if __name__ == "__main__":
    unittest.main()

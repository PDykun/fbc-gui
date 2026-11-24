import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from core.config import (
    DEFAULT_OUTPUT_NAME_TEMPLATE,
    DEVICE_PROFILES,
    _save_smtp_password_secure,
    atomic_write_text,
    get_default_app_settings,
    is_secure_password_storage_available,
    load_app_settings,
    migrate_fbc_config_211,
    save_app_settings,
    sync_settings_from_fbc_config,
    update_fbc_config_file,
)
from core.fb2_processor import DEFAULT_FILENAME_TOKENS


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_CONFIG_YAML = os.path.join(PROJECT_ROOT, "config.yaml")
BASE_CSS_PATH = os.path.join(PROJECT_ROOT, "ebook_styles.css")
FBC_BIN = os.path.join(PROJECT_ROOT, "fbc.exe" if os.name == "nt" else "fbc")


class TestConfig(unittest.TestCase):
    def test_default_output_name_template_backslash_escaping(self):
        self.assertIn('replace "\\\\" "\u2215" $title', DEFAULT_OUTPUT_NAME_TEMPLATE)
        self.assertNotIn('replace "\\" ', DEFAULT_OUTPUT_NAME_TEMPLATE)

    def test_device_profiles_complete(self):
        for key in (
            "kindle",
            "kindle_scribe_2024",
            "kindle_scribe_2025",
            "kindle_scribe_colorsoft",
            "kobo",
            "pocketbook",
            "onyx_boox",
            "remarkable",
            "pdf",
        ):
            self.assertIn(key, DEVICE_PROFILES)
            prof = DEVICE_PROFILES[key]
            for field in ("output_format", "screen_width", "screen_height", "screen_dpi", "footnotes_mode"):
                self.assertIn(field, prof, f"{key} missing {field}")
        rm = DEVICE_PROFILES["remarkable"]
        self.assertEqual(rm["output_format"], "pdf")
        self.assertEqual((rm["screen_width"], rm["screen_height"], rm["screen_dpi"]), ("1620", "2160", "229"))

    def test_migrate_fbc_config_211_and_autoheal(self):
        legacy_yaml = (
            "version: 1\n"
            "document:\n"
            '  stylesheet_path: "/old/path.css"\n'
            "  output_name_template: |\n"
            '    {{- $title = replace "\\" "∕" $title -}}\n'
            "  images:\n"
            "    use_broken: false\n"
            "    remove_transparency: false\n"
            "    scale_factor: 1.0\n"
            "    markdown: external\n"
        )
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "config.yaml")
            with open(cfg, "w", encoding="utf-8") as f:
                f.write(legacy_yaml)

            migrate_fbc_config_211(cfg, BASE_CSS_PATH)

            with open(cfg, encoding="utf-8") as f:
                text = f.read()
            self.assertIn('replace "\\\\" "∕"', text)
            self.assertIn("markdown:", text)
            self.assertIn("images: external", text)
            self.assertIn("kfx:", text)
            self.assertIn("azw3:", text)
            self.assertIn("fit_to_screen: false", text)
            self.assertIn("baseline_jpeg: false", text)
            self.assertIn("grayscale: none", text)

    def test_update_and_sync_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "config.yaml")
            shutil.copy2(BASE_CONFIG_YAML, cfg)

            st = get_default_app_settings()
            st.update(
                {
                    "screen_width": "1404",
                    "screen_height": "1872",
                    "screen_dpi": "227",
                    "footnotes_mode": "floatRenumbered",
                    "insert_soft_hyphen": "true",
                    "dropcaps_enable": "false",
                    "file_name_transliterate": "true",
                    "meta_transliterate": "true",
                    "text_transform_speech": "true",
                    "text_transform_dashes": "true",
                    "text_transform_dialogue": "true",
                    "annotation_enable": "false",
                    "toc_page_placement": "before",
                    "open_from_cover": "false",
                    "cover_generate": "true",
                    "azw3_compression": "huffdic",
                    "azw3_apnx": "eink",
                    "kfx_compression": "lzma",
                    "markdown_images": "embedded",
                    "grayscale": "luma",
                    "fit_to_screen": "true",
                    "baseline_jpeg": "true",
                    "filename_mode": "custom",
                    "filename_tokens": DEFAULT_FILENAME_TOKENS,
                    "title_template_mode": "custom",
                    "title_template_tokens": [
                        {"type": "text", "value": "["},
                        {"type": "tag", "id": "series"},
                        {"type": "text", "value": " #"},
                        {"type": "tag", "id": "num"},
                        {"type": "text", "value": "] "},
                        {"type": "tag", "id": "title"},
                    ],
                }
            )

            update_fbc_config_file(cfg, BASE_CSS_PATH, st)

            loaded = get_default_app_settings()
            sync_settings_from_fbc_config(cfg, loaded)

            for key in (
                "screen_width",
                "screen_height",
                "screen_dpi",
                "footnotes_mode",
                "insert_soft_hyphen",
                "dropcaps_enable",
                "file_name_transliterate",
                "meta_transliterate",
                "text_transform_speech",
                "text_transform_dashes",
                "text_transform_dialogue",
                "annotation_enable",
                "toc_page_placement",
                "open_from_cover",
                "cover_generate",
                "azw3_compression",
                "azw3_apnx",
                "kfx_compression",
                "markdown_images",
                "grayscale",
                "fit_to_screen",
                "baseline_jpeg",
            ):
                self.assertEqual(loaded[key], st[key], f"Mismatch for {key}")

            if os.path.isfile(FBC_BIN):
                out_cfg = os.path.join(td, "active.yaml")
                res = subprocess.run(
                    [FBC_BIN, "-c", cfg, "dumpconfig", out_cfg],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(res.returncode, 0, res.stderr or res.stdout)

    def test_load_app_settings_migrates_legacy_themes(self):
        with tempfile.TemporaryDirectory() as td:
            sp = os.path.join(td, "settings.json")
            with open(sp, "w", encoding="utf-8") as f:
                json.dump({"theme": "Nordic Slate", "language": "ru"}, f)

            st = get_default_app_settings()
            with patch("core.config._load_smtp_password_secure", return_value=""), patch(
                "core.config._save_smtp_password_secure", return_value=True
            ):
                load_app_settings(sp, st)

            self.assertEqual(st["theme"], "Modern")
            self.assertEqual(st["theme_family"], "Modern")
            self.assertIn(st["theme_mode"], ("auto", "light", "dark"))

    def test_secure_password_storage_check_and_save_behavior(self):
        with tempfile.TemporaryDirectory() as td:
            sp = os.path.join(td, "settings.json")
            st = get_default_app_settings()
            st["smtp_password"] = "secret123"

            with patch("core.config._save_smtp_password_secure", return_value=True):
                save_app_settings(sp, st)
            with open(sp, encoding="utf-8") as f:
                saved_secure = json.load(f)
            self.assertEqual(saved_secure["smtp_password"], "")

            with patch("core.config._save_smtp_password_secure", return_value=False), patch(
                "core.config.logger.warning"
            ) as mock_warn:
                save_app_settings(sp, st)
                self.assertTrue(mock_warn.called)

        with patch("core.config.HAS_KEYRING", False), patch("core.config.sys.platform", "win32"):
            self.assertFalse(is_secure_password_storage_available())
        with patch("core.config.HAS_KEYRING", False), patch("core.config.sys.platform", "darwin"):
            self.assertTrue(is_secure_password_storage_available())

    def test_atomic_write_text_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "sample.json")
            atomic_write_text(target, '{"ok": true}')
            with open(target, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"ok": True})
            self.assertEqual(os.listdir(td), ["sample.json"])

    def test_load_app_settings_backs_up_corrupted_json(self):
        with tempfile.TemporaryDirectory() as td:
            sp = os.path.join(td, "settings.json")
            raw_broken = "{not valid json"
            with open(sp, "w", encoding="utf-8") as f:
                f.write(raw_broken)

            st = get_default_app_settings()
            with patch("core.config._load_smtp_password_secure", return_value=""), patch(
                "core.config._save_smtp_password_secure", return_value=True
            ), self.assertLogs("fbc_gui.config", level="WARNING") as cm:
                load_app_settings(sp, st)
            self.assertTrue(any("Повреждённый settings.json" in line for line in cm.output))

            bak_path = f"{sp}.bak"
            self.assertTrue(os.path.isfile(bak_path))
            with open(bak_path, encoding="utf-8") as f:
                self.assertEqual(f.read(), raw_broken)

    def test_save_smtp_password_macos_uses_stdin_not_argv(self):
        secret = 'p@ss "word" \\ тест'
        fake_res = subprocess.CompletedProcess(["security", "-i"], 0, stdout="", stderr="")
        with patch("core.config.HAS_KEYRING", False), patch(
            "core.config.sys.platform", "darwin"
        ), patch("core.config.subprocess.run", return_value=fake_res) as mock_run:
            ok = _save_smtp_password_secure(secret)
            self.assertTrue(ok)
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            cmd = args[0]
            self.assertEqual(cmd, ["security", "-i"])
            self.assertNotIn(secret, cmd)
            self.assertIn(secret.encode("utf-8").hex(), kwargs.get("input", ""))
            self.assertIn("-X ", kwargs.get("input", ""))

    def test_atomic_write_text_preserves_permissions(self):
        if os.name == "nt":
            self.skipTest("POSIX file permissions are not applicable on Windows")
        import stat

        with tempfile.TemporaryDirectory() as td:
            regular = os.path.join(td, "config.yaml")
            with open(regular, "w", encoding="utf-8") as fh:
                fh.write("v: 1\n")
            os.chmod(regular, 0o644)
            atomic_write_text(regular, "v: 2\n")
            self.assertEqual(stat.S_IMODE(os.stat(regular).st_mode), 0o644)

            settings_path = os.path.join(td, "settings.json")
            atomic_write_text(settings_path, '{"ok": true}')
            self.assertEqual(stat.S_IMODE(os.stat(settings_path).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()

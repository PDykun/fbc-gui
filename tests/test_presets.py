import json
import os
import tempfile
import unittest

from core.config import DEVICE_PROFILES, get_default_app_settings
from core.presets import (
    PRESET_FILE_EXT,
    apply_preset_to_settings,
    delete_preset,
    export_preset_to_file,
    extract_preset_settings,
    import_preset_from_file,
    is_builtin_preset_modified,
    list_presets,
    load_preset_file,
    restore_builtin_preset,
    save_preset,
    slugify_preset_name,
    sync_bundled_presets,
)


class TestPresets(unittest.TestCase):
    def test_extract_preset_settings_strips_private_and_local_fields(self):
        settings = get_default_app_settings()
        settings["smtp_host"] = "smtp.secret.local"
        settings["smtp_password"] = "top-secret-password"
        settings["email_to"] = "me@kindle.com"
        settings["custom_output_dir"] = "/Users/private/Books"
        settings["theme"] = "Golden"
        settings["output_format"] = "kfx"
        settings["css_ui_state"] = {"h1_cl": "#112233"}

        extracted = extract_preset_settings(settings)
        self.assertEqual(extracted["output_format"], "kfx")
        self.assertEqual(extracted["css_ui_state"], {"h1_cl": "#112233"})
        for forbidden in ("smtp_host", "smtp_password", "email_to", "custom_output_dir", "theme", "language"):
            self.assertNotIn(forbidden, extracted)

    def test_save_list_load_apply_delete_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            settings = get_default_app_settings()
            settings["output_format"] = "kepub3"
            settings["footnotes_mode"] = "floatRenumbered"
            settings["text_transform_speech"] = "true"
            settings["css_ui_state"] = {"p_align": "left", "drop_color": "#005500"}

            saved = save_preset(td, "Мой Kobo: классика", settings, "p { text-align: left; }")
            self.assertTrue(saved.endswith(PRESET_FILE_EXT))
            self.assertTrue(os.path.isfile(saved))

            items = list_presets(td)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["name"], "Мой Kobo: классика")

            loaded = load_preset_file(items[0]["path"])
            self.assertEqual(loaded["settings"]["output_format"], "kepub3")
            self.assertEqual(loaded["css_content"], "p { text-align: left; }")

            target = get_default_app_settings()
            target["smtp_password"] = "keep-me"
            target["custom_output_dir"] = "/keep/dir"
            apply_preset_to_settings(target, loaded)
            self.assertEqual(target["output_format"], "kepub3")
            self.assertEqual(target["footnotes_mode"], "floatRenumbered")
            self.assertEqual(target["text_transform_speech"], "true")
            self.assertEqual(target["css_ui_state"]["drop_color"], "#005500")
            self.assertEqual(target["smtp_password"], "keep-me")
            self.assertEqual(target["custom_output_dir"], "/keep/dir")

            self.assertTrue(delete_preset(saved))
            self.assertEqual(list_presets(td), [])

    def test_export_import_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as td:
            presets_dir = os.path.join(td, "presets")
            export_path = os.path.join(td, "shared_profile")

            settings = get_default_app_settings()
            settings["output_format"] = "pdf"
            settings["screen_dpi"] = "229"
            out_file = export_preset_to_file(export_path, "PDF A5 Reader", settings, "body { margin: 0; }")
            self.assertTrue(out_file.endswith(PRESET_FILE_EXT))

            name, saved_path, payload = import_preset_from_file(out_file, presets_dir)
            self.assertEqual(name, "PDF A5 Reader")
            self.assertTrue(os.path.isfile(saved_path))
            self.assertEqual(payload["settings"]["screen_dpi"], "229")

            bad_file = os.path.join(td, "bad.fbcpreset.json")
            with open(bad_file, "w", encoding="utf-8") as fh:
                json.dump({"name": "Empty"}, fh)
            with self.assertRaises(ValueError):
                load_preset_file(bad_file)

    def test_slugify_preset_name(self):
        self.assertEqual(slugify_preset_name("Kindle / Paperwhite: 2026"), "Kindle___Paperwhite__2026")
        self.assertEqual(slugify_preset_name("   "), "preset")

    def test_bundled_defaults_fonts_and_restore(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bundled_dir = os.path.join(project_root, "presets_defaults")
        distributed_fonts = {
            "PT-Astra-Serif_Regular.ttf",
            "PT-Astra-Serif_Italic.ttf",
            "PT-Astra-Serif_Bold.ttf",
            "PT-Astra-Serif_Bold-Italic.ttf",
            "PomorskyUnicode.otf",
            "__none__",
        }

        items = list_presets(bundled_dir)
        names = {it["name"] for it in items}
        for required in (
            "Kindle Paperwhite (2024)",
            "Kindle Scribe (2022/2024)",
            "Kindle Scribe (2025)",
            "Kindle Scribe Colorsoft (2025)",
            "reMarkable Paper Pro (2024)",
        ):
            self.assertIn(required, names)

        for it in items:
            payload = load_preset_file(it["path"])
            st = payload["settings"]
            prof_key = st.get("device_profile")
            self.assertIn(prof_key, DEVICE_PROFILES)
            self.assertEqual(st.get("output_format"), DEVICE_PROFILES[prof_key]["output_format"])
            css_ui = st.get("css_ui_state", {})
            for fk in ("font_para", "font_drop", "font_title", "font_author"):
                self.assertIn(
                    css_ui.get(fk),
                    distributed_fonts,
                    f"{it['name']} uses non-distributed font {css_ui.get(fk)}",
                )

        with tempfile.TemporaryDirectory() as td:
            copied = sync_bundled_presets(bundled_dir, td)
            self.assertEqual(len(copied), len(items))
            target_item = list_presets(td)[0]
            self.assertFalse(is_builtin_preset_modified(target_item["path"], bundled_dir))

            payload = load_preset_file(target_item["path"])
            payload["settings"]["jpeg_quality_level"] = "75"
            save_preset(td, payload["name"], payload["settings"], payload["css_content"])
            self.assertTrue(is_builtin_preset_modified(target_item["path"], bundled_dir))

            sync_bundled_presets(bundled_dir, td)
            self.assertEqual(load_preset_file(target_item["path"])["settings"]["jpeg_quality_level"], "75")

            restored_name, restored_path, restored_payload = restore_builtin_preset(
                td, bundled_dir, name=payload["name"], filename=target_item["filename"]
            )
            self.assertEqual(restored_name, payload["name"])
            self.assertEqual(restored_payload["settings"]["jpeg_quality_level"], "95")
            self.assertFalse(is_builtin_preset_modified(restored_path, bundled_dir))

    def test_builtin_color_and_monochrome_presets_styles(self):
        from core.css_preview import (
            get_default_css_ui_state,
            get_monochrome_css_ui_state,
            parse_css_file_to_state,
        )

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bundled_dir = os.path.join(project_root, "presets_defaults")
        default_state = get_default_css_ui_state()
        mono_state = get_monochrome_css_ui_state()
        color_profiles = {"kindle_scribe_colorsoft", "kobo", "remarkable"}

        for it in list_presets(bundled_dir):
            payload = load_preset_file(it["path"])
            st = payload["settings"]
            prof = st.get("device_profile")
            css_ui = st.get("css_ui_state", {})
            css_content = payload.get("css_content", "")

            with tempfile.TemporaryDirectory() as td:
                css_fp = os.path.join(td, "ebook_styles.css")
                with open(css_fp, "w", encoding="utf-8") as fh:
                    fh.write(css_content)
                parsed = parse_css_file_to_state(css_fp)

            if prof in color_profiles:
                self.assertEqual(css_ui, default_state, f"Color preset {it['name']} css_ui_state mismatch")
                self.assertEqual(parsed.get("h1_cl"), "red", f"Color preset {it['name']} h1_cl")
                self.assertEqual(parsed.get("drop_color"), "red", f"Color preset {it['name']} drop_color")
                self.assertEqual(parsed.get("auth_cl"), "green", f"Color preset {it['name']} auth_cl")
            else:
                self.assertEqual(css_ui, mono_state, f"B&W preset {it['name']} css_ui_state mismatch")
                self.assertEqual(parsed.get("h1_cl"), "black", f"B&W preset {it['name']} h1_cl")
                self.assertEqual(parsed.get("drop_color"), "black", f"B&W preset {it['name']} drop_color")
                self.assertEqual(parsed.get("auth_cl"), "dimgray", f"B&W preset {it['name']} auth_cl")
                self.assertNotIn("red", css_content.lower())
                self.assertNotIn("#8b0000", css_content.lower())

    def test_preset_edge_cases_and_corrupt_files(self):
        with tempfile.TemporaryDirectory() as td:
            # 1. Невалидный JSON, не-словарь и некорректное поле settings
            for fname, raw in (
                ("broken.fbcpreset.json", "{not valid json"),
                ("array.fbcpreset.json", "[1, 2, 3]"),
                ("bad_settings.fbcpreset.json", json.dumps({"name": "Bad", "settings": "nope"})),
            ):
                p = os.path.join(td, fname)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(raw)
                with self.assertRaises(ValueError):
                    load_preset_file(p)

            # 2. list_presets пропускает повреждённые файлы и возвращает валидные
            st = get_default_app_settings()
            save_preset(td, "Valid Preset", st, "body {}")
            listed = list_presets(td)
            self.assertEqual([it["name"] for it in listed], ["Valid Preset"])

            # 3. apply_preset_to_settings игнорирует приватные/неизвестные ключи и битый css_ui_state
            target = get_default_app_settings()
            target["smtp_password"] = "secret"
            target["custom_output_dir"] = "/safe/dir"
            target["css_ui_state"] = {"h1_cl": "red"}
            apply_preset_to_settings(
                target,
                {
                    "settings": {
                        "output_format": "azw3",
                        "smtp_password": "hacked",
                        "custom_output_dir": "/evil",
                        "unknown_future_key": "ignored",
                        "css_ui_state": "not-a-dict",
                    }
                },
            )
            self.assertEqual(target["output_format"], "azw3")
            self.assertEqual(target["smtp_password"], "secret")
            self.assertEqual(target["custom_output_dir"], "/safe/dir")
            self.assertNotIn("unknown_future_key", target)
            self.assertEqual(target.get("css_ui_state"), {"h1_cl": "red"})


    def test_preset_setting_keys_include_v210_settings(self):
        src = {
            "annotation_in_toc": "true",
            "toc_type": "flat",
            "toc_include_untitled": "true",
            "page_map_enable": "false",
            "page_map_size": "3000",
            "page_map_adobe_de": "true",
            "fix_zip": "true",
            "image_scale_factor": "1.5",
            "smtp_password": "PRIVATE_VALUE",
            "opds_password": "PRIVATE_VALUE",
        }
        extracted = extract_preset_settings(src)
        for key in (
            "annotation_in_toc",
            "toc_type",
            "toc_include_untitled",
            "page_map_enable",
            "page_map_size",
            "page_map_adobe_de",
            "fix_zip",
            "image_scale_factor",
        ):
            self.assertEqual(extracted.get(key), src[key])
        self.assertNotIn("smtp_password", extracted)
        self.assertNotIn("opds_password", extracted)

        target = {}
        apply_preset_to_settings(target, {"settings": extracted})
        self.assertEqual(target["toc_type"], "flat")
        self.assertEqual(target["image_scale_factor"], "1.5")


    def test_default_mode_presets_omit_redundant_template_tokens_and_preserve_user_tokens(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bundled_dir = os.path.join(project_root, "presets_defaults")

        # 1. Встроенные пресеты с режимом по умолчанию не дублируют filename_tokens / title_template_tokens
        for it in list_presets(bundled_dir):
            with open(it["path"], "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            st = raw.get("settings") or {}
            self.assertEqual(st.get("filename_mode"), "default")
            self.assertNotIn("filename_tokens", st, f"{it['name']} should not duplicate filename_tokens")
            self.assertEqual(st.get("title_template_mode"), "filename")
            self.assertNotIn("title_template_tokens", st, f"{it['name']} should not duplicate title_template_tokens")

        # 2. extract_preset_settings опускает токены для non-custom и сохраняет для custom
        base = get_default_app_settings()
        extracted_def = extract_preset_settings(base)
        self.assertNotIn("filename_tokens", extracted_def)
        self.assertNotIn("title_template_tokens", extracted_def)

        custom_fn = [{"type": "tag", "id": "title"}]
        custom_tt = [{"type": "tag", "id": "last"}]
        base["filename_mode"] = "custom"
        base["filename_tokens"] = custom_fn
        base["title_template_mode"] = "custom"
        base["title_template_tokens"] = custom_tt
        extracted_custom = extract_preset_settings(base)
        self.assertEqual(extracted_custom["filename_tokens"], custom_fn)
        self.assertEqual(extracted_custom["title_template_tokens"], custom_tt)

        # 3. Применение пресета с filename_mode='default' не затирает пользовательские filename_tokens,
        #    а reset_default_tokens=True (пункт «Нет») сбрасывает их
        target = get_default_app_settings()
        target["filename_tokens"] = custom_fn
        apply_preset_to_settings(
            target,
            {"settings": {"filename_mode": "default", "filename_tokens": [{"type": "tag", "id": "last"}]}},
        )
        self.assertEqual(target["filename_tokens"], custom_fn)

        defaults = get_default_app_settings()
        apply_preset_to_settings(target, {"settings": defaults}, reset_default_tokens=True)
        self.assertEqual(target["filename_tokens"], defaults["filename_tokens"])

    def test_load_preset_enforces_size_limit_and_sanitizes_css(self):
        from core.presets import MAX_PRESET_FILE_BYTES, sanitize_preset_css

        dirty_css = (
            '@import url("https://evil.invalid/a.css");\n'
            'body { width: expression(alert(1)); background: url("https://evil.invalid/bg.png"); }\n'
            '@font-face { src: url("fonts/PT-Astra-Serif_Regular.ttf"); }\n'
        )
        cleaned = sanitize_preset_css(dirty_css)
        self.assertNotIn("@import", cleaned.lower())
        self.assertNotIn("expression(", cleaned.lower())
        self.assertNotIn("evil.invalid", cleaned.lower())
        self.assertIn("PT-Astra-Serif_Regular.ttf", cleaned)

        with tempfile.TemporaryDirectory() as td:
            p_dirty = os.path.join(td, "dirty.fbcpreset.json")
            with open(p_dirty, "w", encoding="utf-8") as fh:
                json.dump({"name": "Dirty", "settings": {"output_format": "epub3"}, "css_content": dirty_css}, fh)
            loaded = load_preset_file(p_dirty)
            self.assertNotIn("evil.invalid", loaded["css_content"])

            p_huge = os.path.join(td, "huge.fbcpreset.json")
            with open(p_huge, "wb") as fh:
                fh.write(b"{" + b" " * (MAX_PRESET_FILE_BYTES + 16) + b"}")
            with self.assertRaises(ValueError):
                load_preset_file(p_huge)


if __name__ == "__main__":
    unittest.main()

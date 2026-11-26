import json
import os
import plistlib
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication

from core.autostart import (
    WINDOWS_RUN_VALUE_NAME,
    format_windows_run_command,
    get_autostart_program_arguments,
    is_autostart_enabled,
    set_autostart_enabled,
)
from core.config import get_default_app_settings
from core.notifier import _escape_applescript_string, send_system_notification
from core.presets import save_preset
from core.watch_folder import (
    PRESET_CURRENT_TOKEN,
    WatchFolderManager,
    WatchStateStore,
    apply_post_action,
    build_isolated_conversion_env,
    is_file_readable_and_ready,
    is_ignored_watch_path,
    normalize_watch_rules,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _FakeWinreg:
    HKEY_CURRENT_USER = object()
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {}

    class _KeyCtx:
        def __init__(self, store):
            self.store = store

        def __enter__(self):
            return self.store

        def __exit__(self, *args):
            return False

    def OpenKey(self, root, path, reserved, access):
        return self._KeyCtx(self.values)

    def QueryValueEx(self, key, name):
        if name not in key:
            raise FileNotFoundError(name)
        return key[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, reg_type, value):
        key[name] = value

    def DeleteValue(self, key, name):
        if name not in key:
            raise FileNotFoundError(name)
        del key[name]


class TestWatchFolderAndTray(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_default_settings_have_autostart_disabled_and_watch_keys(self):
        defaults = get_default_app_settings()
        self.assertEqual(defaults["autostart_enabled"], "false")
        self.assertEqual(defaults["tray_enabled"], "false")
        self.assertEqual(defaults["tray_minimize_on_close"], "false")
        self.assertEqual(defaults["tray_hide_dock_macos"], "false")
        self.assertEqual(defaults["watch_notifications_enabled"], "true")
        self.assertEqual(defaults["watch_folders"], [])

    def test_normalize_watch_rules_supports_multiple_folders_and_dedups_ids(self):
        rules = normalize_watch_rules([
            {"id": "dup", "folder": "/tmp/ToKindle", "delivery_mode": "email", "post_action": "trash"},
            {"id": "dup", "folder": "/tmp/ToKobo", "delivery_mode": "invalid", "post_action": "weird"},
            {"folder": ""},  # должен быть отфильтрован
        ])
        self.assertEqual(len(rules), 2)
        self.assertNotEqual(rules[0]["id"], rules[1]["id"])
        self.assertEqual(rules[0]["name"], "ToKindle")
        self.assertEqual(rules[0]["delivery_mode"], "email")
        self.assertEqual(rules[0]["post_action"], "trash")
        self.assertEqual(rules[1]["delivery_mode"], "folder")
        self.assertEqual(rules[1]["post_action"], "move_processed")

    def test_ignore_temp_hidden_and_internal_subdirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(is_ignored_watch_path(os.path.join(tmp, ".DS_Store"), tmp))
            self.assertTrue(is_ignored_watch_path(os.path.join(tmp, "._book.fb2"), tmp))
            self.assertTrue(is_ignored_watch_path(os.path.join(tmp, "book.fb2.crdownload"), tmp))
            self.assertTrue(is_ignored_watch_path(os.path.join(tmp, "book.zip.part"), tmp))
            self.assertTrue(is_ignored_watch_path(os.path.join(tmp, "Processed", "book.fb2"), tmp))
            self.assertTrue(is_ignored_watch_path(os.path.join(tmp, "Failed", "book.fb2"), tmp))
            self.assertTrue(is_ignored_watch_path(os.path.join(tmp, "Converted", "book.epub"), tmp))
            self.assertFalse(is_ignored_watch_path(os.path.join(tmp, "book.fb2"), tmp))
            self.assertFalse(is_ignored_watch_path(os.path.join(tmp, "sub", "book.zip"), tmp))

    def test_file_readability_and_zip_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty_fb2 = os.path.join(tmp, "empty.fb2")
            open(empty_fb2, "wb").close()
            self.assertFalse(is_file_readable_and_ready(empty_fb2))

            good_fb2 = os.path.join(tmp, "good.fb2")
            with open(good_fb2, "wb") as fh:
                fh.write(b"<FictionBook></FictionBook>")
            self.assertTrue(is_file_readable_and_ready(good_fb2))

            broken_zip = os.path.join(tmp, "broken.zip")
            with open(broken_zip, "wb") as fh:
                fh.write(b"not a zip at all")
            self.assertFalse(is_file_readable_and_ready(broken_zip))

            good_zip = os.path.join(tmp, "good.zip")
            with zipfile.ZipFile(good_zip, "w") as zf:
                zf.writestr("book.fb2", "<FictionBook/>")
            self.assertTrue(is_file_readable_and_ready(good_zip))

    def test_watch_state_store_persistence_and_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "watch_state.json")
            fp = os.path.join(tmp, "novel.fb2")
            store = WatchStateStore(state_path)
            self.assertFalse(store.is_processed("r1", fp, 100, 1234.5))
            store.mark_processed("r1", fp, 100, 1234.5, status="ok")
            store.mark_processed("r_old", fp, 100, 1234.5, status="ok")

            reloaded = WatchStateStore(state_path)
            self.assertTrue(reloaded.is_processed("r1", fp, 100, 1234.5))
            self.assertFalse(reloaded.is_processed("r1", fp, 200, 1234.5))
            reloaded.prune_unknown_rules(["r1"])
            self.assertFalse(reloaded.is_processed("r_old", fp, 100, 1234.5))

    def test_apply_post_action_collision_and_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            b1 = os.path.join(tmp, "book.fb2")
            with open(b1, "w", encoding="utf-8") as fh:
                fh.write("v1")
            dst1 = apply_post_action(b1, tmp, "move_processed", success=True)
            self.assertTrue(os.path.isfile(dst1))
            self.assertEqual(os.path.basename(os.path.dirname(dst1)), "Processed")

            # Коллизия имён в Processed/
            b2 = os.path.join(tmp, "book.fb2")
            with open(b2, "w", encoding="utf-8") as fh:
                fh.write("v2")
            dst2 = apply_post_action(b2, tmp, "move_processed", success=True)
            self.assertNotEqual(dst1, dst2)
            self.assertIn("(2)", os.path.basename(dst2))

            # Ошибка -> Failed/
            b3 = os.path.join(tmp, "bad.fb2")
            with open(b3, "w", encoding="utf-8") as fh:
                fh.write("bad")
            dst3 = apply_post_action(b3, tmp, "move_processed", success=False)
            self.assertEqual(os.path.basename(os.path.dirname(dst3)), "Failed")

            # keep -> файл остаётся на месте
            b4 = os.path.join(tmp, "stay.fb2")
            with open(b4, "w", encoding="utf-8") as fh:
                fh.write("stay")
            dst4 = apply_post_action(b4, tmp, "keep", success=True)
            self.assertEqual(dst4, b4)
            self.assertTrue(os.path.isfile(b4))

    def test_isolated_preset_env_does_not_mutate_main_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            presets_dir = os.path.join(tmp, "presets")
            env_dir = os.path.join(tmp, "env")
            base_cfg = os.path.join(REPO_ROOT, "config.yaml")
            base_css = os.path.join(REPO_ROOT, "ebook_styles.css")
            base_settings = get_default_app_settings()
            base_settings["output_format"] = "epub3"

            preset_settings = dict(base_settings)
            preset_settings["output_format"] = "kfx"
            save_preset(presets_dir, "Kindle Fast", preset_settings, "body { color: black; }")

            merged, tmp_cfg, tmp_css, style_params = build_isolated_conversion_env(
                env_dir,
                base_cfg,
                base_css,
                os.path.join(REPO_ROOT, "fonts"),
                base_settings,
                presets_dir,
                "Kindle Fast",
            )
            self.assertEqual(base_settings["output_format"], "epub3")
            self.assertEqual(merged["output_format"], "kfx")
            self.assertTrue(os.path.isfile(tmp_cfg))
            self.assertTrue(os.path.isfile(tmp_css))
            with open(tmp_css, "r", encoding="utf-8") as fh:
                self.assertIn("body { color: black; }", fh.read())
            self.assertIn("h1_sz", style_params)

    def test_autostart_macos_and_windows_backends(self):
        with tempfile.TemporaryDirectory() as tmp:
            plist_path = os.path.join(tmp, "eu.pashka.fbc-gui.plist")
            self.assertFalse(is_autostart_enabled(platform="darwin", macos_plist_path=plist_path))
            ok, err = set_autostart_enabled(
                True,
                platform="darwin",
                macos_plist_path=plist_path,
                program_args=["/Applications/FBC GUI.app/Contents/MacOS/FBC GUI", "--minimized"],
            )
            self.assertTrue(ok, err)
            self.assertTrue(is_autostart_enabled(platform="darwin", macos_plist_path=plist_path))
            with open(plist_path, "rb") as fh:
                data = plistlib.load(fh)
            self.assertEqual(data["ProgramArguments"][-1], "--minimized")
            self.assertTrue(data["RunAtLoad"])

            ok, err = set_autostart_enabled(False, platform="darwin", macos_plist_path=plist_path)
            self.assertTrue(ok, err)
            self.assertFalse(os.path.exists(plist_path))

        fake_wr = _FakeWinreg()
        self.assertFalse(is_autostart_enabled(platform="win32", winreg_module=fake_wr))
        ok, err = set_autostart_enabled(
            True,
            platform="win32",
            winreg_module=fake_wr,
            program_args=[r"C:\Program Files\FBC GUI\FBC_GUI.exe", "--minimized"],
        )
        self.assertTrue(ok, err)
        self.assertTrue(is_autostart_enabled(platform="win32", winreg_module=fake_wr))
        self.assertIn("--minimized", fake_wr.values[WINDOWS_RUN_VALUE_NAME])
        self.assertIn('"C:\\Program Files\\FBC GUI\\FBC_GUI.exe"', fake_wr.values[WINDOWS_RUN_VALUE_NAME])
        ok, err = set_autostart_enabled(False, platform="win32", winreg_module=fake_wr)
        self.assertTrue(ok, err)
        self.assertFalse(is_autostart_enabled(platform="win32", winreg_module=fake_wr))

        cmd_str = format_windows_run_command(get_autostart_program_arguments(platform="win32", frozen=True, executable=r"C:\App Dir\FBC_GUI.exe"))
        self.assertIn("--minimized", cmd_str)

    def test_notifier_sanitization_and_tray_fallback(self):
        escaped = _escape_applescript_string('Line 1\n"Quote" \\ Path')
        self.assertNotIn("\n", escaped)
        self.assertIn('\\"Quote\\"', escaped)
        self.assertIn("\\\\", escaped)

        mock_tray = MagicMock()
        mock_tray.isVisible.return_value = True
        mock_tray.supportsMessages.return_value = True
        with patch("core.notifier.sys.platform", "win32"):
            sent = send_system_notification("FBC GUI", "Done: 2 books", tray_icon=mock_tray)
        self.assertTrue(sent)
        mock_tray.showMessage.assert_called_once()

    def test_watch_manager_tracks_multiple_rules_and_missing_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            dir_a = os.path.join(tmp, "ToKindle")
            dir_b = os.path.join(tmp, "ToKobo")
            os.makedirs(dir_a)
            os.makedirs(dir_b)
            missing_dir = os.path.join(tmp, "DoesNotExist")

            mgr = WatchFolderManager(
                base_dir=tmp,
                get_fbc_cmd=lambda: "",
                get_app_settings=get_default_app_settings,
                fbc_config_path=os.path.join(REPO_ROOT, "config.yaml"),
                css_path=os.path.join(REPO_ROOT, "ebook_styles.css"),
                fonts_dir=os.path.join(REPO_ROOT, "fonts"),
                presets_dir=os.path.join(tmp, "presets"),
            )
            mgr.set_rules([
                {"id": "r1", "enabled": True, "folder": dir_a, "preset_name": PRESET_CURRENT_TOKEN},
                {"id": "r2", "enabled": True, "folder": dir_b, "preset_name": PRESET_CURRENT_TOKEN},
                {"id": "r3", "enabled": True, "folder": missing_dir, "preset_name": PRESET_CURRENT_TOKEN},
            ])
            self.assertEqual(mgr.active_rules_count(), 3)
            self.assertEqual(mgr.get_rule_status("r1"), "active")
            self.assertEqual(mgr.get_rule_status("r2"), "active")
            self.assertEqual(mgr.get_rule_status("r3"), "missing")

            mgr.set_paused(True)
            self.assertTrue(mgr.paused)
            mgr.stop()

    def test_watch_locale_keys_parity_and_no_cli_flags(self):
        with open(os.path.join(REPO_ROOT, "locales", "ru.json"), "r", encoding="utf-8") as fh:
            ru = json.load(fh)["watch"]
        with open(os.path.join(REPO_ROOT, "locales", "en.json"), "r", encoding="utf-8") as fh:
            en = json.load(fh)["watch"]
        self.assertEqual(set(ru.keys()), set(en.keys()))
        for lang_map in (ru, en):
            for k, val in lang_map.items():
                self.assertNotIn("--minimized", val, f"CLI flag leaked into {k}")
                self.assertNotIn("--debug", val, f"CLI flag leaked into {k}")

    def test_watch_state_store_batch_saves_once_and_backoff_skips_rescan(self):
        from core.s2k_manager import DEVICE_SYNC_EXEC_LOCK as S2K_LOCK
        from core.watch_folder import DEVICE_SYNC_EXEC_LOCK as WF_LOCK

        self.assertIs(S2K_LOCK, WF_LOCK)

        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "watch_state.json")
            store = WatchStateStore(state_path)
            with patch.object(store, "save", wraps=store.save) as spy_save:
                store.mark_processed_batch(
                    "r1",
                    [
                        {"path": os.path.join(tmp, "a.fb2"), "size": 10, "mtime": 1.0, "status": "ok"},
                        {"path": os.path.join(tmp, "b.fb2"), "size": 20, "mtime": 2.0, "status": "ok"},
                        {"path": os.path.join(tmp, "c.fb2"), "size": 30, "mtime": 3.0, "status": "error", "error": "fail"},
                    ],
                )
            spy_save.assert_called_once()
            self.assertTrue(store.is_processed("r1", os.path.join(tmp, "b.fb2"), 20, 2.0))

            watch_dir = os.path.join(tmp, "inbox")
            os.makedirs(watch_dir)
            book_fp = os.path.join(watch_dir, "retry.fb2")
            with open(book_fp, "wb") as fh:
                fh.write(b"<FictionBook/>")
            st = os.stat(book_fp)

            mgr = WatchFolderManager(
                base_dir=tmp,
                get_fbc_cmd=lambda: "",
                get_app_settings=get_default_app_settings,
                fbc_config_path=os.path.join(REPO_ROOT, "config.yaml"),
                css_path=os.path.join(REPO_ROOT, "ebook_styles.css"),
                fonts_dir=os.path.join(REPO_ROOT, "fonts"),
                presets_dir=os.path.join(tmp, "presets"),
            )
            rule = {"id": "r_sync", "enabled": True, "folder": watch_dir, "delivery_mode": "device_sync"}
            mgr.set_rules([rule])
            mgr._on_job_finished({
                "rule_id": "r_sync",
                "rule_name": "inbox",
                "delivery_mode": "device_sync",
                "cancelled": False,
                "processed_sources": [
                    {"path": book_fp, "size": st.st_size, "mtime": st.st_mtime, "ok": False, "error": "no device"}
                ],
            })
            mgr._pending_files.clear()
            mgr._scan_rule(mgr.rules[0])
            self.assertEqual(mgr._pending_files, {})
            mgr.stop()

    def test_macos_osascript_notifier_reaps_subprocess(self):
        from core.notifier import _send_macos_osascript_notification

        fake_proc = MagicMock()
        with patch("core.notifier.subprocess.Popen", return_value=fake_proc) as popen_mock, \
             patch("core.notifier._reap_process_async") as reap_mock:
            ok = _send_macos_osascript_notification("FBC GUI", "Done")
        self.assertTrue(ok)
        popen_mock.assert_called_once()
        reap_mock.assert_called_once_with(fake_proc)

    def test_autostart_macos_rejects_corrupted_or_stale_plist(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_plist = os.path.join(tmp, "corrupt.plist")
            with open(bad_plist, "wb") as fh:
                fh.write(b"not-a-plist")
            self.assertFalse(is_autostart_enabled(platform="darwin", macos_plist_path=bad_plist))

            stale_plist = os.path.join(tmp, "stale.plist")
            ok, _ = set_autostart_enabled(
                True,
                platform="darwin",
                macos_plist_path=stale_plist,
                program_args=[os.path.join(tmp, "missing_app_bin"), "--minimized"],
            )
            self.assertTrue(ok)
            self.assertFalse(
                is_autostart_enabled(platform="darwin", macos_plist_path=stale_plist, verify_executable=True)
            )

    def test_watch_scan_worker_scans_recursive_dir_off_main_thread(self):
        from core.watch_folder import WatchScanWorker

        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, "nested")
            os.makedirs(sub)
            book = os.path.join(sub, "deep.fb2")
            with open(book, "wb") as fh:
                fh.write(b"<FictionBook/>")
            ignored_dir = os.path.join(tmp, "Processed")
            os.makedirs(ignored_dir)
            with open(os.path.join(ignored_dir, "done.fb2"), "wb") as fh:
                fh.write(b"<FictionBook/>")

            captured = []
            worker = WatchScanWorker([{"id": "r_rec", "folder": tmp, "recursive": True}])
            worker.scan_finished.connect(captured.append)
            worker.run()
            self.assertEqual(len(captured), 1)
            res = captured[0][0]
            self.assertEqual(res["status"], "ok")
            self.assertIn(book, res["files"])
            self.assertFalse(any("Processed" in p for p in res["files"]))


if __name__ == "__main__":
    unittest.main()

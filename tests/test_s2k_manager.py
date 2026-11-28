import os
import tempfile
import time
import unittest

from PyQt6.QtWidgets import QApplication

from core.s2k_manager import (
    build_s2k_sync_command,
    select_s2k_release_asset,
    sync_folder_to_mounted_device,
)
from core.workers import DeviceSyncWorker


_APP = QApplication.instance() or QApplication([])


class TestS2kManager(unittest.TestCase):
    def test_select_s2k_release_asset_prefers_full_s2k_for_platform_and_arch(self):
        assets = [
            {"name": "s2km-darwin-arm64.tar.gz", "browser_download_url": "s2km-mac"},
            {"name": "s2k-darwin-arm64.tar.gz", "browser_download_url": "s2k-mac-arm"},
            {"name": "s2k-windows-amd64.zip", "browser_download_url": "s2k-win"},
            {"name": "checksums.txt", "browser_download_url": "sums"},
        ]
        mac_asset = select_s2k_release_asset(assets, platform_name="darwin", machine="arm64")
        self.assertIsNotNone(mac_asset)
        self.assertEqual(mac_asset["name"], "s2k-darwin-arm64.tar.gz")

        win_asset = select_s2k_release_asset(assets, platform_name="win32", machine="AMD64")
        self.assertIsNotNone(win_asset)
        self.assertEqual(win_asset["name"], "s2k-windows-amd64.zip")

        self.assertIsNone(select_s2k_release_asset(assets, platform_name="linux", machine="x86_64"))

    def test_build_s2k_sync_command_modes_and_flags(self):
        cmd_mtp = build_s2k_sync_command(
            "/usr/local/bin/s2k",
            "mtp",
            "/tmp/books",
            "documents/books",
            dry_run=True,
            ignore_device_removals=True,
            config_path="/tmp/s2k.yaml",
        )
        self.assertEqual(
            cmd_mtp,
            [
                "/usr/local/bin/s2k",
                "-c",
                os.path.abspath("/tmp/s2k.yaml"),
                "mtp",
                "--ignore-device-removals",
                "--dry-run",
            ],
        )

        cmd_usb = build_s2k_sync_command(
            "/usr/local/bin/s2k",
            "usb",
            "/tmp/books",
            "",
            dry_run=False,
            ignore_device_removals=False,
        )
        self.assertEqual(cmd_usb, ["/usr/local/bin/s2k", "usb"])

    def test_sync_folder_to_mounted_device_dry_run_copy_and_skip(self):
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "out")
            dst = os.path.join(td, "kindle_mount")
            os.makedirs(src)
            os.makedirs(dst)
            ep = os.path.join(src, "book1.epub")
            kfx = os.path.join(src, "book2.kfx")
            txt = os.path.join(src, "notes.txt")
            for p, content in ((ep, b"EPUBDATA"), (kfx, b"KFXDATA"), (txt, b"IGNORED")):
                with open(p, "wb") as fh:
                    fh.write(content)

            dry = sync_folder_to_mounted_device(src, dst, dry_run=True)
            self.assertEqual(dry["copied"], ["book1.epub", "book2.kfx"])
            self.assertEqual(dry["skipped"], [])
            self.assertFalse(os.path.exists(os.path.join(dst, "book1.epub")))

            real = sync_folder_to_mounted_device(src, dst, dry_run=False)
            self.assertEqual(real["copied"], ["book1.epub", "book2.kfx"])
            self.assertTrue(os.path.isfile(os.path.join(dst, "book1.epub")))
            self.assertFalse(os.path.exists(os.path.join(dst, "notes.txt")))

            again = sync_folder_to_mounted_device(src, dst, dry_run=False)
            self.assertEqual(again["copied"], [])
            self.assertEqual(again["skipped"], ["book1.epub", "book2.kfx"])

            now = time.time() + 10
            with open(ep, "wb") as fh:
                fh.write(b"UPDATED_EPUB")
            os.utime(ep, (now, now))
            updated = sync_folder_to_mounted_device(src, dst, dry_run=False)
            self.assertEqual(updated["copied"], ["book1.epub"])
            self.assertEqual(updated["skipped"], ["book2.kfx"])

    def test_device_sync_worker_folder_mode(self):
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "src")
            dst = os.path.join(td, "dst")
            os.makedirs(src)
            os.makedirs(dst)
            with open(os.path.join(src, "novel.kepub.epub"), "wb") as fh:
                fh.write(b"KEPUB")

            worker = DeviceSyncWorker(
                mode="folder",
                source_dir=src,
                target_dir=dst,
                user_data_dir=td,
                dry_run=False,
            )
            results = []
            worker.finished_sync.connect(lambda ok, out, dry: results.append((ok, out, dry)))
            worker.run()
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0][0])
            self.assertIn("novel.kepub.epub", results[0][1])
            self.assertFalse(results[0][2])
            self.assertTrue(os.path.isfile(os.path.join(dst, "novel.kepub.epub")))


    def test_case_insensitive_checksum_mismatch_rejected(self):
        import io
        import json
        import tempfile
        import urllib.parse
        import zipfile
        from unittest.mock import patch
        from core.s2k_manager import download_and_install_s2k

        class _DummyResp:
            def __init__(self, payload):
                self._buf = io.BytesIO(payload)
                self.headers = {}

            def read(self, n=-1):
                return self._buf.read(n)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        asset_url = urllib.parse.urlunsplit(("https", "downloads.example.org", "/S2K-Darwin-Arm64.zip", "", ""))
        cs_url = urllib.parse.urlunsplit(("https", "downloads.example.org", "/checksums.txt", "", ""))

        with tempfile.TemporaryDirectory() as td:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                zf.writestr("s2k", b"dummy")
            zip_bytes = zip_buf.getvalue()

            rel_json = json.dumps({
                "tag_name": "v1.0.0",
                "assets": [
                    {"name": "S2K-Darwin-Arm64.zip", "browser_download_url": asset_url},
                    {"name": "checksums.txt", "browser_download_url": cs_url},
                ],
            }).encode("utf-8")
            bad_checksums = ("0" * 64 + "  S2K-Darwin-Arm64.zip\n").encode("utf-8")

            def _fake_urlopen(req, timeout=20, context=None, require_https=True, allowed_hosts=None):
                u = req.full_url if hasattr(req, "full_url") else str(req)
                if "checksums.txt" in u:
                    return _DummyResp(bad_checksums)
                if "S2K-Darwin-Arm64.zip" in u:
                    return _DummyResp(zip_bytes)
                return _DummyResp(rel_json)

            with patch("core.s2k_manager.select_s2k_release_asset", return_value={
                "name": "S2K-Darwin-Arm64.zip",
                "browser_download_url": asset_url,
            }), patch("core.s2k_manager.safe_urlopen", side_effect=_fake_urlopen):
                with self.assertRaises(RuntimeError) as ctx:
                    download_and_install_s2k(td)
                self.assertIn("контрольной суммы", str(ctx.exception))

    def test_download_and_install_s2k_reports_progress_and_verifying_status(self):
        import hashlib
        import io
        import json
        import urllib.parse
        import zipfile
        from unittest.mock import patch
        from core.s2k_manager import _s2k_exe_name, download_and_install_s2k

        class _DummyResp:
            def __init__(self, payload, headers=None):
                self._buf = io.BytesIO(payload)
                self.headers = headers or {}

            def read(self, n=-1):
                return self._buf.read(n)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        asset_url = urllib.parse.urlunsplit(("https", "downloads.example.org", "/s2k-darwin-arm64.zip", "", ""))
        cs_url = urllib.parse.urlunsplit(("https", "downloads.example.org", "/checksums.txt", "", ""))
        exe_name = _s2k_exe_name()

        with tempfile.TemporaryDirectory() as td:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                zf.writestr(exe_name, b"#!/bin/sh\necho 1.2.3\n")
            zip_bytes = zip_buf.getvalue()
            sha = hashlib.sha256(zip_bytes).hexdigest()

            rel_json = json.dumps({
                "tag_name": "v1.2.3",
                "assets": [
                    {"name": "s2k-darwin-arm64.zip", "size": len(zip_bytes), "browser_download_url": asset_url},
                    {"name": "checksums.txt", "browser_download_url": cs_url},
                ],
            }).encode("utf-8")
            checksums_raw = f"{sha}  s2k-darwin-arm64.zip\n".encode("utf-8")

            def _fake_urlopen(req, timeout=20, context=None, require_https=True, allowed_hosts=None):
                u = req.full_url if hasattr(req, "full_url") else str(req)
                if "checksums.txt" in u:
                    return _DummyResp(checksums_raw)
                if "s2k-darwin-arm64.zip" in u:
                    return _DummyResp(zip_bytes, headers={"Content-Length": str(len(zip_bytes))})
                return _DummyResp(rel_json)

            progress_events = []
            status_events = []
            with (
                patch("core.s2k_manager.select_s2k_release_asset", return_value={
                    "name": "s2k-darwin-arm64.zip",
                    "size": len(zip_bytes),
                    "browser_download_url": asset_url,
                }),
                patch("core.s2k_manager.safe_urlopen", side_effect=_fake_urlopen),
                patch("core.s2k_manager.probe_s2k_binary", return_value={"path": os.path.join(td, exe_name), "version": "1.2.3"}),
            ):
                info = download_and_install_s2k(
                    td,
                    progress_callback=lambda dl, tot, name: progress_events.append((dl, tot, name)),
                    status_callback=lambda st: status_events.append(st),
                )
            self.assertEqual(info["version"], "1.2.3")
            self.assertGreaterEqual(len(progress_events), 2)
            self.assertEqual(progress_events[0], (0, len(zip_bytes), "s2k-darwin-arm64.zip"))
            self.assertEqual(progress_events[-1], (len(zip_bytes), len(zip_bytes), "s2k-darwin-arm64.zip"))
            self.assertEqual(status_events, ["verifying"])

    def test_missing_libmtp_detection_and_friendly_error(self):
        from unittest.mock import patch
        from core.s2k_manager import S2kMissingLibraryError, is_missing_libmtp_stderr

        dyld_err = "dyld[14019]: Library not loaded: /opt/homebrew/opt/libmtp/lib/libmtp.9.dylib"
        self.assertTrue(is_missing_libmtp_stderr(dyld_err))
        self.assertFalse(is_missing_libmtp_stderr("no device found"))

        with tempfile.TemporaryDirectory() as td:
            worker = DeviceSyncWorker(
                mode="mtp",
                source_dir=td,
                target_dir="documents/books",
                user_data_dir=td,
                dry_run=True,
            )
            results = []
            worker.finished_sync.connect(lambda ok, out, dry: results.append((ok, out, dry)))
            with patch("core.s2k_manager.resolve_local_s2k", side_effect=S2kMissingLibraryError(dyld_err)):
                worker.run()
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0][0])
            self.assertIn("brew install libmtp", results[0][1])

    def test_device_sync_worker_mtp_stages_books_and_passes_yaml_config(self):
        from unittest.mock import patch
        from ruamel.yaml import YAML

        with tempfile.TemporaryDirectory() as td:
            src_dir = os.path.join(td, "books_src")
            data_dir = os.path.join(td, "app_data")
            os.makedirs(src_dir)
            os.makedirs(data_dir)
            with open(os.path.join(src_dir, "book1.kfx"), "wb") as fh:
                fh.write(b"KFXDATA")
            with open(os.path.join(src_dir, "raw.fb2"), "wb") as fh:
                fh.write(b"<FictionBook/>")
            captured = {}

            def _fake_run(cmd, cwd, cancel_event=None):
                captured["cmd"] = list(cmd)
                captured["cwd"] = cwd
                cfg_idx = cmd.index("-c")
                cfg_file = cmd[cfg_idx + 1]
                captured["cfg_path"] = cfg_file
                with open(cfg_file, "r", encoding="utf-8") as fh:
                    captured["cfg_data"] = YAML().load(fh)
                staged_dir = captured["cfg_data"]["source"]
                captured["staged_dir"] = staged_dir
                captured["staged_files"] = sorted(os.listdir(staged_dir))
                return ("dry-run ok", "")

            worker = DeviceSyncWorker(
                mode="mtp",
                source_dir=src_dir,
                target_dir="documents/books",
                user_data_dir=data_dir,
                dry_run=True,
            )
            results = []
            worker.finished_sync.connect(lambda ok, out, dry: results.append((ok, out, dry)))
            with (
                patch("core.s2k_manager.resolve_local_s2k", return_value={"path": os.path.join(data_dir, "s2k"), "version": "1.0"}),
                patch("core.fb2_processor._run_cancellable_process", side_effect=_fake_run),
            ):
                worker.run()
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0][0])
            self.assertEqual(captured["cwd"], data_dir)
            self.assertEqual(captured["cmd"][1], "-c")
            self.assertEqual(captured["cmd"][3], "mtp")
            self.assertNotEqual(captured["staged_dir"], os.path.abspath(src_dir))
            self.assertEqual(os.path.dirname(captured["staged_dir"]), data_dir)
            self.assertEqual(captured["staged_files"], ["book1.kfx"])
            self.assertEqual(captured["cfg_data"]["target"], "documents/books")
            self.assertFalse(os.path.exists(captured["cfg_path"]))
            self.assertFalse(os.path.exists(captured["staged_dir"]))

            # Папка только с .fb2 без сконвертированных файлов для Kindle даёт понятное сообщение
            empty_src = os.path.join(td, "only_fb2")
            os.makedirs(empty_src)
            with open(os.path.join(empty_src, "only.fb2"), "wb") as fh:
                fh.write(b"<FictionBook/>")
            err_results = []
            worker2 = DeviceSyncWorker(
                mode="mtp",
                source_dir=empty_src,
                target_dir="documents/books",
                user_data_dir=data_dir,
                dry_run=True,
            )
            worker2.finished_sync.connect(lambda ok, out, dry: err_results.append((ok, out, dry)))
            with patch("core.s2k_manager.resolve_local_s2k", return_value={"path": os.path.join(data_dir, "s2k"), "version": "1.0"}):
                worker2.run()
            self.assertEqual(len(err_results), 1)
            self.assertFalse(err_results[0][0])
            self.assertIn(os.path.abspath(empty_src), err_results[0][1])

    def test_check_sync_format_compatibility(self):
        from core.s2k_manager import check_sync_format_compatibility

        c_mtp_epub = check_sync_format_compatibility("mtp", "epub3", "kindle_scribe_2024")
        self.assertFalse(c_mtp_epub["compatible"])
        self.assertEqual(c_mtp_epub["recommended"], "kfx")

        c_mtp_kfx = check_sync_format_compatibility("mtp", "kfx", "kindle_scribe_2024")
        self.assertTrue(c_mtp_kfx["compatible"])

        c_usb_epub = check_sync_format_compatibility("usb", "epub3", "kindle")
        self.assertFalse(c_usb_epub["compatible"])
        self.assertEqual(c_usb_epub["recommended"], "azw3")

        c_folder_epub = check_sync_format_compatibility("folder", "epub3", "pocketbook")
        self.assertTrue(c_folder_epub["compatible"])

        c_folder_md = check_sync_format_compatibility("folder", "md", "kobo")
        self.assertFalse(c_folder_md["compatible"])
        self.assertEqual(c_folder_md["recommended"], "kepub")

    def test_stage_books_explicit_files_bypasses_os_walk_and_reports_tcc_error(self):
        from unittest.mock import patch
        from core.s2k_manager import S2kPermissionError, stage_books_for_s2k

        with tempfile.TemporaryDirectory() as td:
            src_dir = os.path.join(td, "protected_downloads")
            stage_dir = os.path.join(td, "stage")
            os.makedirs(src_dir)
            kfx_path = os.path.join(src_dir, "book.kfx")
            with open(kfx_path, "wb") as fh:
                fh.write(b"KFX")

            # С explicit_files os.walk не вызывается вообще
            with patch("core.s2k_manager.os.walk", side_effect=AssertionError("os.walk should not be called")):
                staged = stage_books_for_s2k(src_dir, stage_dir, explicit_files=[kfx_path])
            self.assertEqual(staged, ["book.kfx"])
            self.assertTrue(os.path.isfile(os.path.join(stage_dir, "book.kfx")))

            # Без explicit_files PermissionError при обходе папки превращается в S2kPermissionError
            stage_dir2 = os.path.join(td, "stage2")

            def _fake_walk(root, onerror=None):
                if onerror:
                    onerror(PermissionError(1, "Operation not permitted", root))
                return iter([])

            with patch("core.s2k_manager.os.walk", side_effect=_fake_walk):
                with self.assertRaises(S2kPermissionError):
                    stage_books_for_s2k(src_dir, stage_dir2)

    def test_check_directory_access_and_folder_sync_protection(self):
        from unittest.mock import patch
        from core.s2k_manager import S2kPermissionError, check_directory_access

        with tempfile.TemporaryDirectory() as td:
            ok_access = check_directory_access(td)
            self.assertTrue(ok_access["exists"])
            self.assertTrue(ok_access["readable"])
            self.assertFalse(ok_access["protected"])

            missing = check_directory_access(os.path.join(td, "no_such_dir"))
            self.assertFalse(missing["exists"])
            self.assertFalse(missing["protected"])

            with patch("core.s2k_manager.os.scandir", side_effect=PermissionError(1, "Operation not permitted", td)):
                prot = check_directory_access(td)
            self.assertTrue(prot["exists"])
            self.assertFalse(prot["readable"])
            self.assertTrue(prot["protected"])

            # sync_folder_to_mounted_device с explicit_files работает даже если source_dir защищён
            src = os.path.join(td, "src")
            dst = os.path.join(td, "dst")
            os.makedirs(src)
            os.makedirs(dst)
            ep = os.path.join(src, "test.epub")
            with open(ep, "wb") as fh:
                fh.write(b"EPUB")

            res = sync_folder_to_mounted_device(src, dst, dry_run=False, explicit_files=[ep])
            self.assertEqual(res["copied"], ["test.epub"])
            self.assertTrue(os.path.isfile(os.path.join(dst, "test.epub")))

            # Без explicit_files защищённый source_dir даёт S2kPermissionError
            orig_scandir = os.scandir

            def _block_src(path):
                if os.path.abspath(path) == os.path.abspath(src):
                    raise PermissionError(1, "Operation not permitted", path)
                return orig_scandir(path)

            with patch("core.s2k_manager.os.scandir", side_effect=_block_src):
                with self.assertRaises(S2kPermissionError):
                    sync_folder_to_mounted_device(src, dst, dry_run=True)

    def test_parse_s2k_copy_action_and_summary(self):
        from core.s2k_manager import parse_s2k_copy_action, summarize_s2k_output

        sample = (
            '2026-11-25T15:20:42.459+0300\tINFO\ts2k.sync\tSync starting {"protocol": "MTP"}\n'
            '2026-11-25T15:20:43.919+0300\tINFO\ts2k.sync.mtp-device\tExecuting\t{"action": "Copy", "file": "documents/books/(ХДК - 01) Книга 1.kfx"}\n'
            '2026-11-25T15:20:44.060+0300\tINFO\ts2k.sync.mtp-device\tExecuting\t{"action": "Copy", "file": "documents/books/(ХДК - 02) Книга 2.kfx"}\n'
            '2026-11-25T15:20:44.986+0300\tINFO\ts2k.sync\tSync finished {"protocol": "MTP"}\n'
        )
        self.assertIsNone(parse_s2k_copy_action("Sync starting"))
        self.assertEqual(
            parse_s2k_copy_action('INFO Executing {"action": "Copy", "file": "documents/books/book.kfx"}'),
            "book.kfx",
        )
        summary = summarize_s2k_output(sample)
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["copied"], ["(ХДК - 01) Книга 1.kfx", "(ХДК - 02) Книга 2.kfx"])

    def test_github_asset_digest_mismatch_rejected_without_checksums_file(self):
        import io
        import json
        import urllib.parse
        import zipfile
        from unittest.mock import patch
        from core.s2k_manager import download_and_install_s2k

        class _DummyResp:
            def __init__(self, payload):
                self._buf = io.BytesIO(payload)
                self.headers = {}

            def read(self, n=-1):
                return self._buf.read(n)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        asset_url = urllib.parse.urlunsplit(("https", "downloads.example.org", "/s2k-darwin-arm64.zip", "", ""))
        with tempfile.TemporaryDirectory() as td:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                zf.writestr("s2k", b"dummy")
            zip_bytes = zip_buf.getvalue()

            rel_json = json.dumps({
                "tag_name": "v1.2.3",
                "assets": [
                    {
                        "name": "s2k-darwin-arm64.zip",
                        "browser_download_url": asset_url,
                        "digest": "sha256:" + ("f" * 64),
                    },
                ],
            }).encode("utf-8")

            def _fake_urlopen(req, timeout=20, context=None, require_https=True, allowed_hosts=None):
                u = req.full_url if hasattr(req, "full_url") else str(req)
                if "s2k-darwin-arm64.zip" in u:
                    return _DummyResp(zip_bytes)
                return _DummyResp(rel_json)

            with patch("core.s2k_manager.select_s2k_release_asset", return_value={
                "name": "s2k-darwin-arm64.zip",
                "browser_download_url": asset_url,
                "digest": "sha256:" + ("f" * 64),
            }), patch("core.s2k_manager.safe_urlopen", side_effect=_fake_urlopen):
                with self.assertRaises(RuntimeError) as ctx:
                    download_and_install_s2k(td)
                self.assertIn("контрольной суммы", str(ctx.exception))

    def test_detect_mounted_readers_usb_and_kobo_cloud(self):
        from core.s2k_manager import detect_mounted_readers

        with tempfile.TemporaryDirectory() as td:
            vols = os.path.join(td, "Volumes")
            home = os.path.join(td, "Home")
            os.makedirs(os.path.join(vols, "KOBOeReader", ".kobo"))
            os.makedirs(os.path.join(vols, "Kindle", "documents"))
            os.makedirs(os.path.join(vols, "Kindle", "system"))
            os.makedirs(os.path.join(vols, "PB740", "system", "config"))
            os.makedirs(os.path.join(vols, "PB740", "books"))
            os.makedirs(os.path.join(home, "Dropbox", "Apps", "Rakuten Kobo"))

            detected = detect_mounted_readers(
                platform_name="darwin",
                volumes_roots=[vols],
                home_dir=home,
            )
            by_kind = {d["kind"]: d for d in detected}
            self.assertIn("kobo", by_kind)
            self.assertEqual(by_kind["kobo"]["recommended_format"], "kepub3")
            self.assertIn("kindle", by_kind)
            self.assertTrue(by_kind["kindle"]["path"].endswith("documents"))
            self.assertIn("pocketbook", by_kind)
            self.assertTrue(by_kind["pocketbook"]["path"].endswith("books"))
            self.assertIn("kobo_cloud", by_kind)
            self.assertTrue(by_kind["kobo_cloud"]["path"].endswith("Rakuten Kobo"))

    def test_download_and_install_s2k_fails_closed_without_checksum_before_exec(self):
        import io
        import json
        import urllib.parse
        import zipfile
        from unittest.mock import patch
        from core.s2k_manager import _s2k_exe_name, download_and_install_s2k

        class _DummyResp:
            def __init__(self, payload):
                self._buf = io.BytesIO(payload)
                self.headers = {}

            def read(self, n=-1):
                return self._buf.read(n)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        asset_url = urllib.parse.urlunsplit(("https", "downloads.example.org", "/s2k-darwin-arm64.zip", "", ""))
        exe_name = _s2k_exe_name()
        with tempfile.TemporaryDirectory() as td:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                zf.writestr(exe_name, b"dummy")
            zip_bytes = zip_buf.getvalue()
            rel_json = json.dumps({
                "tag_name": "v1.2.3",
                "assets": [{"name": "s2k-darwin-arm64.zip", "browser_download_url": asset_url}],
            }).encode("utf-8")

            def _fake_urlopen(req, timeout=20, context=None, require_https=True, allowed_hosts=None):
                u = req.full_url if hasattr(req, "full_url") else str(req)
                return _DummyResp(zip_bytes if "s2k-darwin-arm64.zip" in u else rel_json)

            with patch("core.s2k_manager.select_s2k_release_asset", return_value={
                "name": "s2k-darwin-arm64.zip",
                "browser_download_url": asset_url,
            }), patch("core.s2k_manager.safe_urlopen", side_effect=_fake_urlopen), \
                 patch("core.s2k_manager.probe_s2k_binary") as mock_probe:
                with self.assertRaises(RuntimeError) as ctx:
                    download_and_install_s2k(td)
                self.assertIn("контрольной суммы", str(ctx.exception).lower())
                mock_probe.assert_not_called()

    def test_download_and_install_s2k_handles_windows_backslash_zip_entry(self):
        import hashlib
        import io
        import json
        import urllib.parse
        import zipfile
        from unittest.mock import patch
        from core.s2k_manager import _s2k_exe_name, download_and_install_s2k

        class _DummyResp:
            def __init__(self, payload):
                self._buf = io.BytesIO(payload)
                self.headers = {}

            def read(self, n=-1):
                return self._buf.read(n)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        asset_url = urllib.parse.urlunsplit(("https", "downloads.example.org", "/s2k-win.zip", "", ""))
        exe_name = _s2k_exe_name()
        with tempfile.TemporaryDirectory() as td:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                zf.writestr(f"nested\\dir\\{exe_name}", b"binary-content")
            zip_bytes = zip_buf.getvalue()
            sha = hashlib.sha256(zip_bytes).hexdigest()
            rel_json = json.dumps({
                "tag_name": "v1.2.3",
                "assets": [{
                    "name": "s2k-win.zip",
                    "browser_download_url": asset_url,
                    "digest": f"sha256:{sha}",
                }],
            }).encode("utf-8")

            def _fake_urlopen(req, timeout=20, context=None, require_https=True, allowed_hosts=None):
                u = req.full_url if hasattr(req, "full_url") else str(req)
                return _DummyResp(zip_bytes if "s2k-win.zip" in u else rel_json)

            with patch("core.s2k_manager.select_s2k_release_asset", return_value={
                "name": "s2k-win.zip",
                "browser_download_url": asset_url,
                "digest": f"sha256:{sha}",
            }), patch("core.s2k_manager.safe_urlopen", side_effect=_fake_urlopen), \
                 patch("core.s2k_manager.probe_s2k_binary", return_value={"path": os.path.join(td, exe_name), "version": "1.2.3"}):
                info = download_and_install_s2k(td)
            self.assertEqual(info["version"], "1.2.3")
            self.assertTrue(os.path.isfile(os.path.join(td, exe_name)))


    def test_write_s2k_sync_config_writes_isolated_history_dir(self):
        import tempfile
        from core.s2k_manager import write_s2k_sync_config

        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "sync.yaml")
            src = os.path.join(td, "stage")
            hist = os.path.join(td, "hist")
            write_s2k_sync_config(cfg, src, "documents/books", history_dir=hist)
            with open(cfg, "r", encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("source:", content)
            self.assertIn("target:", content)
            self.assertIn("history:", content)
            self.assertIn(os.path.basename(hist), content)


if __name__ == "__main__":
    unittest.main()

import hashlib
import io
import json
import os
import plistlib
import tempfile
import threading
import unittest
from unittest import mock

from core.updater import (
    DEFAULT_GITHUB_REPO,
    DEFAULT_MANIFEST_URL,
    UpdateCancelledError,
    UpdateHashMismatchError,
    apply_downloaded_update,
    compute_file_sha256,
    create_windows_portable_update_script,
    download_and_verify_update,
    fetch_update_info,
    is_newer_version,
    is_safe_http_url,
    normalize_update_platform_arch,
    parse_version_tuple,
    select_download_url,
    select_update_asset,
    verify_file_sha256,
)


class _MockResponse:
    def __init__(self, data, headers=None):
        self._buf = io.BytesIO(data)
        self.headers = headers or {"Content-Length": str(len(data))}

    def read(self, size=-1):
        return self._buf.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestUpdater(unittest.TestCase):
    def test_default_manifest_url_uses_github_releases_latest_download(self):
        self.assertEqual(
            DEFAULT_MANIFEST_URL,
            f"https://github.com/{DEFAULT_GITHUB_REPO}/releases/latest/download/version.json",
        )

    def test_parse_version_tuple(self):
        self.assertEqual(parse_version_tuple("2.5"), (2, 5))
        self.assertEqual(parse_version_tuple("v2.5.1"), (2, 5, 1))
        self.assertEqual(parse_version_tuple("2.5b3"), (2, 53))
        self.assertEqual(parse_version_tuple(""), (0,))

    def test_is_newer_version_semver_packaging(self):
        self.assertTrue(is_newer_version("0.10", 1, "0.9", 1))
        self.assertTrue(is_newer_version("2.10", 68, "2.9", 68))
        self.assertTrue(is_newer_version("v2.9", 68, "2.8.3", 67))
        self.assertTrue(is_newer_version("2.5.1", 49, "2.5", 49))
        self.assertTrue(is_newer_version("2.5", 50, "2.5", 49))
        self.assertTrue(is_newer_version("2.9", 68, "2.9b1", 68))
        self.assertFalse(is_newer_version("2.9b1", 99, "2.9", 68))
        self.assertFalse(is_newer_version("2.5", 49, "2.5", 49))
        self.assertFalse(is_newer_version("2.4", 99, "2.5", 49))

    def test_normalize_update_platform_arch(self):
        self.assertEqual(normalize_update_platform_arch("darwin", "arm64"), ("macos", "arm64"))
        self.assertEqual(normalize_update_platform_arch("darwin", "x86_64"), ("macos", "x64"))
        self.assertEqual(normalize_update_platform_arch("win32", "AMD64"), ("windows", "x64"))
        self.assertEqual(normalize_update_platform_arch("win32", "ARM64"), ("windows", "arm64"))

    def test_select_update_asset_by_os_and_arch(self):
        sha_mac_arm = "a" * 64
        sha_mac_x64 = "b" * 64
        sha_win_x64 = "c" * 64
        sha_win_arm = "d" * 64
        manifest = {
            "version": "2.9",
            "build": 69,
            "release_base_url": "https://example.invalid/releases/download/v2.9",
            "assets": {
                "macos-arm64": {
                    "filename": "FBC_GUI_v2.9_macos_arm64.dmg",
                    "sha256": sha_mac_arm,
                    "kind": "dmg",
                },
                "macos-x64": {
                    "filename": "FBC_GUI_v2.9_macos_x64.dmg",
                    "sha256": sha_mac_x64,
                    "kind": "dmg",
                },
                "windows-x64": {
                    "filename": "FBC_GUI_Setup_v2.9_win_x64.exe",
                    "sha256": sha_win_x64,
                    "kind": "installer",
                },
                "windows-arm64": {
                    "filename": "FBC_GUI_Setup_v2.9_win_arm64.exe",
                    "sha256": sha_win_arm,
                    "kind": "installer",
                },
            },
        }
        arm_asset = select_update_asset(manifest, sys_platform="darwin", machine="arm64")
        self.assertEqual(arm_asset["filename"], "FBC_GUI_v2.9_macos_arm64.dmg")
        self.assertEqual(arm_asset["sha256"], sha_mac_arm)
        self.assertEqual(arm_asset["kind"], "dmg")
        self.assertTrue(arm_asset["url"].endswith("/FBC_GUI_v2.9_macos_arm64.dmg"))

        x64_asset = select_update_asset(manifest, sys_platform="darwin", machine="x86_64")
        self.assertEqual(x64_asset["filename"], "FBC_GUI_v2.9_macos_x64.dmg")
        self.assertEqual(x64_asset["sha256"], sha_mac_x64)

        win_x64 = select_update_asset(manifest, sys_platform="win32", machine="AMD64")
        self.assertEqual(win_x64["filename"], "FBC_GUI_Setup_v2.9_win_x64.exe")
        self.assertEqual(win_x64["sha256"], sha_win_x64)
        self.assertEqual(win_x64["kind"], "installer")

        win_arm = select_update_asset(manifest, sys_platform="win32", machine="ARM64")
        self.assertEqual(win_arm["filename"], "FBC_GUI_Setup_v2.9_win_arm64.exe")
        self.assertEqual(win_arm["sha256"], sha_win_arm)
        self.assertEqual(win_arm["kind"], "installer")

        arm_only = {"assets": {"macos-arm64": manifest["assets"]["macos-arm64"]}}
        self.assertEqual(
            select_update_asset(arm_only, sys_platform="darwin", machine="x86_64", fallback_url="fb")["url"],
            "fb",
        )

    def test_select_download_url(self):
        manifest = {
            "downloads": {
                "darwin": "pkg/mac",
                "win32": "pkg/win",
            },
            "download_url": "pkg/all",
        }
        self.assertEqual(select_download_url(manifest, platform="darwin"), "pkg/mac")
        self.assertEqual(select_download_url(manifest, platform="win32"), "pkg/win")
        self.assertEqual(select_download_url(manifest, platform="linux"), "pkg/all")
        self.assertEqual(select_download_url({}, platform="linux", fallback_url="pkg/fb"), "pkg/fb")

    def test_select_download_url_rejects_unsafe_schemes(self):
        self.assertTrue(is_safe_http_url("https://localhost/app"))
        self.assertTrue(is_safe_http_url("https://localhost/app", require_https=True))
        self.assertFalse(is_safe_http_url("http://localhost/app", require_https=True))
        self.assertFalse(is_safe_http_url("ftp://localhost/app", allow_relative=True))
        self.assertFalse(is_safe_http_url("mailto:user@localhost", allow_relative=True))
        self.assertFalse(is_safe_http_url("//localhost/app", allow_relative=True))

        unsafe_manifest = {
            "downloads": {"darwin": "http://localhost/mac"},
            "download_url": "mailto:user@localhost",
        }
        self.assertEqual(
            select_download_url(unsafe_manifest, platform="darwin", fallback_url="pkg/fb"),
            "pkg/fb",
        )
        info_http = fetch_update_info("2.8", 60, manifest_url="http://example.invalid/version.json")
        self.assertIsNotNone(info_http["error"])
        with self.assertRaises(ValueError):
            download_and_verify_update("http://example.invalid/app.exe", "a" * 64)

    def test_sha256_verification_and_download_flow(self):
        payload = b"FBC GUI installer test payload 2.9"
        good_sha = hashlib.sha256(payload).hexdigest()
        bad_sha = "0" * 64
        dl_url = "https://example.invalid/releases/download/v2.9/FBC_GUI_v2.9_mac.dmg"
        manifest = {
            "version": "2.9",
            "build": 68,
            "assets": {
                "macos-arm64": {
                    "filename": "FBC_GUI_v2.9_mac.dmg",
                    "url": dl_url,
                    "sha256": good_sha,
                    "kind": "dmg",
                }
            },
            "changelog": {"ru": "Новый автоапдейтер", "en": "New auto-updater"},
        }
        manifest_bytes = json.dumps(manifest).encode("utf-8")

        def _fake_urlopen(req, timeout=8, context=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if url.endswith("version.json"):
                return _MockResponse(manifest_bytes)
            return _MockResponse(payload)

        with mock.patch("core.updater.urllib.request.urlopen", side_effect=_fake_urlopen):
            info = fetch_update_info(
                "2.8.3",
                67,
                manifest_url="https://example.invalid/releases/latest/download/version.json",
                lang="ru",
                sys_platform="darwin",
                machine="arm64",
            )
            self.assertIsNone(info["error"])
            self.assertTrue(info["has_update"])
            self.assertEqual(info["version"], "2.9")
            self.assertEqual(info["sha256"], good_sha)
            self.assertEqual(info["changelog"], "Новый автоапдейтер")

            with tempfile.TemporaryDirectory() as tmpdir:
                statuses = []
                downloaded_path = download_and_verify_update(
                    download_url=info["download_url"],
                    expected_sha256=info["sha256"],
                    filename=info["filename"],
                    dest_dir=tmpdir,
                    status_callback=statuses.append,
                )
                self.assertTrue(os.path.isfile(downloaded_path))
                self.assertEqual(compute_file_sha256(downloaded_path), good_sha)
                self.assertTrue(verify_file_sha256(downloaded_path, good_sha))
                self.assertFalse(verify_file_sha256(downloaded_path, bad_sha))
                self.assertEqual(statuses, ["downloading", "verifying"])

                bad_dir = os.path.join(tmpdir, "bad")
                with self.assertRaises(UpdateHashMismatchError):
                    download_and_verify_update(
                        download_url=info["download_url"],
                        expected_sha256=bad_sha,
                        filename="bad.dmg",
                        dest_dir=bad_dir,
                    )
                self.assertFalse(os.path.exists(os.path.join(bad_dir, "bad.dmg")))

                cancel_ev = threading.Event()
                cancel_ev.set()
                with self.assertRaises(UpdateCancelledError):
                    download_and_verify_update(
                        download_url=info["download_url"],
                        expected_sha256=good_sha,
                        filename="cancelled.dmg",
                        dest_dir=tmpdir,
                        cancel_event=cancel_ev,
                    )

    def test_apply_downloaded_update_windows_installer_and_portable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_exe = os.path.join(tmpdir, "FBC_GUI_Setup_v2.9.exe")
            portable_exe = os.path.join(tmpdir, "FBC_GUI.exe")
            open(setup_exe, "wb").close()
            open(portable_exe, "wb").close()

            with mock.patch("core.updater.subprocess.Popen") as popen_mock:
                res_inst = apply_downloaded_update(setup_exe, kind="installer", sys_platform="win32")
                self.assertEqual(res_inst["action"], "installer_launched")
                self.assertTrue(res_inst["should_quit"])
                args = popen_mock.call_args[0][0]
                self.assertEqual(args[0], setup_exe)
                self.assertIn("/SILENT", args)

            with mock.patch("core.updater.subprocess.Popen") as popen_mock:
                res_port = apply_downloaded_update(
                    portable_exe,
                    kind="portable",
                    sys_platform="win32",
                    current_exe=os.path.join(tmpdir, "Current_FBC_GUI.exe"),
                    current_pid=4321,
                )
                self.assertEqual(res_port["action"], "portable_script_launched")
                self.assertTrue(res_port["should_quit"])
                bat_path = res_port["path"]
                self.assertTrue(os.path.isfile(bat_path))
                with open(bat_path, "r", encoding="utf-8") as fh:
                    content = fh.read()
                self.assertIn("TARGET_PID=4321", content)
                self.assertIn("move /Y", content)
                popen_mock.assert_called_once()

    def test_apply_downloaded_update_macos_dmg_mounts_and_opens(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dmg_path = os.path.join(tmpdir, "FBC_GUI_v2.9_mac.dmg")
            open(dmg_path, "wb").close()
            fake_mount = os.path.join(tmpdir, "VolMount")
            os.makedirs(fake_mount, exist_ok=True)

            fake_plist = plistlib.dumps({"system-entities": [{"mount-point": fake_mount}]})
            fake_proc = mock.Mock(returncode=0, stdout=fake_plist, stderr=b"")

            with mock.patch("core.updater.subprocess.run", return_value=fake_proc) as run_mock, \
                 mock.patch("core.updater.subprocess.Popen") as popen_mock:
                res = apply_downloaded_update(dmg_path, kind="dmg", sys_platform="darwin")
                self.assertEqual(res["action"], "dmg_mounted")
                self.assertFalse(res["should_quit"])
                self.assertEqual(res["mount_point"], fake_mount)
                run_mock.assert_called_once()
                popen_mock.assert_called_once_with(["open", fake_mount])

    def test_create_windows_portable_update_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bat = create_windows_portable_update_script(
                current_exe=os.path.join(tmpdir, "100%_Папка", "old.exe"),
                new_exe=os.path.join(tmpdir, "new.exe"),
                pid=9999,
                script_dir=tmpdir,
            )
            self.assertTrue(os.path.isfile(bat))
            with open(bat, "r", encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("chcp 65001 >NUL", text)
            self.assertIn("WAIT_TRIES", text)
            self.assertIn('findstr /C:",\\"%TARGET_PID%\\","', text)
            self.assertIn("100%%_Папка", text)
            self.assertIn("9999", text)
            self.assertIn("old.exe", text)
            self.assertIn("new.exe", text)

    def test_download_and_verify_update_cleans_created_temp_dir_on_error(self):
        created_dirs = []
        real_mkdtemp = tempfile.mkdtemp

        def _tracking_mkdtemp(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            created_dirs.append(path)
            return path

        with mock.patch("core.updater.tempfile.mkdtemp", side_effect=_tracking_mkdtemp), \
             mock.patch("core.updater.urllib.request.urlopen", return_value=_MockResponse(b"corrupted")):
            with self.assertRaises(UpdateHashMismatchError):
                download_and_verify_update(
                    download_url="https://example.invalid/releases/download/v2.9.1/app.dmg",
                    expected_sha256="0" * 64,
                    filename="app.dmg",
                    dest_dir=None,
                )

        self.assertEqual(len(created_dirs), 1)
        self.assertFalse(os.path.exists(created_dirs[0]))

    def test_download_and_verify_update_handles_malformed_content_length(self):
        payload = b"valid update bytes"
        good_sha = hashlib.sha256(payload).hexdigest()
        resp = _MockResponse(payload, headers={"Content-Length": "not-a-number"})
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("core.updater.urllib.request.urlopen", return_value=resp):
                path = download_and_verify_update(
                    download_url="https://example.invalid/releases/download/v2.9.1/app.dmg",
                    expected_sha256=good_sha,
                    filename="app.dmg",
                    dest_dir=td,
                )
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(compute_file_sha256(path), good_sha)

    def test_update_manifest_resets_stale_assets_on_version_change(self):
        try:
            from update_version_json import update_manifest
        except ImportError:
            self.skipTest("update_version_json.py is not present in this checkout")

        with tempfile.TemporaryDirectory() as td:
            manifest_path = os.path.join(td, "version.json")
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "version": "2.9",
                        "build": 69,
                        "assets": {"macos-arm64": {"filename": "old.dmg", "sha256": "a" * 64}},
                        "downloads": {"macos-arm64": "https://example.invalid/old.dmg", "darwin": "https://example.invalid/old.dmg"},
                    },
                    fh,
                )

            import contextlib

            with contextlib.redirect_stdout(io.StringIO()):
                update_manifest(manifest_path, td, "2.9.1", 75)
            with open(manifest_path, encoding="utf-8") as fh:
                updated = json.load(fh)

            self.assertEqual(updated["version"], "2.9.1")
            self.assertEqual(updated["build"], 75)
            self.assertEqual(updated["assets"], {})
            self.assertEqual(updated["downloads"], {})


    def test_safe_redirect_handler_blocks_downgrade_and_strips_headers_cross_origin(self):
        import urllib.error
        import urllib.parse
        import urllib.request
        from core.updater import _SafeRedirectHandler

        def _u(scheme, host, path):
            return urllib.parse.urlunsplit((scheme, host, path, "", ""))

        handler = _SafeRedirectHandler(require_https=True, max_redirects=2)
        req = urllib.request.Request(
            _u("https", "api.example.org", "/v1/books"),
            headers={
                "Authorization": "Bearer placeholder",
                "X-Goog-Api-Key": "DEMO_KEY",
                "Accept": "application/json",
            },
        )
        with self.assertRaises(ValueError):
            handler.redirect_request(req, None, 302, "Found", {}, _u("http", "api.example.org", "/v1/books"))
        with self.assertRaises(ValueError):
            handler.redirect_request(req, None, 302, "Found", {}, _u("ftp", "files.example.org", "/book.zip"))

        new_req = handler.redirect_request(req, None, 302, "Found", {}, _u("https", "cdn.other.org", "/item"))
        self.assertIsNotNone(new_req)
        hdrs_low = {k.lower(): v for k, v in new_req.header_items()}
        self.assertNotIn("authorization", hdrs_low)
        self.assertNotIn("x-goog-api-key", hdrs_low)
        self.assertEqual(hdrs_low.get("accept"), "application/json")

        same_req = handler.redirect_request(req, None, 302, "Found", {}, _u("https", "api.example.org", "/v2/books"))
        same_hdrs_low = {k.lower(): v for k, v in same_req.header_items()}
        self.assertIn("authorization", same_hdrs_low)
        self.assertIn("x-goog-api-key", same_hdrs_low)

        req2 = handler.redirect_request(same_req, None, 302, "Found", {}, _u("https", "api.example.org", "/v3/books"))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            handler.redirect_request(req2, None, 302, "Found", {}, _u("https", "api.example.org", "/v4/books"))
        cm.exception.close()

    def test_build_only_update_detection_and_manifest_reset(self):
        import contextlib
        from core.updater import parse_build_number
        from update_version_json import update_manifest

        self.assertEqual(parse_build_number(115), 115)
        self.assertEqual(parse_build_number("115"), 115)
        self.assertEqual(parse_build_number("2.11.115"), 115)
        self.assertEqual(parse_build_number("build 115"), 115)
        self.assertEqual(parse_build_number(None), 0)
        self.assertEqual(parse_build_number(""), 0)

        self.assertTrue(is_newer_version("2.11", 115, "2.11", 114))
        self.assertTrue(is_newer_version("2.11", "2.11.115", "2.11", 114))
        self.assertFalse(is_newer_version("2.11", 115, "2.11", 115))
        self.assertFalse(is_newer_version("2.11", 114, "2.11", 115))

        seen_headers = {}
        manifest = {
            "version": "2.11",
            "build": 115,
            "assets": {
                "macos-arm64": {
                    "filename": "FBC_GUI_v2.11_macos_arm64.dmg",
                    "url": "https://example.invalid/releases/download/v2.11/FBC_GUI_v2.11_macos_arm64.dmg",
                    "sha256": "b" * 64,
                    "kind": "dmg",
                }
            },
        }
        manifest_bytes = json.dumps(manifest).encode("utf-8")

        def _fake_urlopen(req, timeout=8, context=None):
            seen_headers.update({k.lower(): v for k, v in req.header_items()})
            return _MockResponse(manifest_bytes)

        with mock.patch("core.updater.urllib.request.urlopen", side_effect=_fake_urlopen):
            info = fetch_update_info(
                "2.11",
                114,
                manifest_url="https://example.invalid/releases/latest/download/version.json",
                sys_platform="darwin",
                machine="arm64",
            )
        self.assertIsNone(info["error"])
        self.assertTrue(info["has_update"])
        self.assertEqual(info["version"], "2.11")
        self.assertEqual(info["build"], 115)
        self.assertEqual(seen_headers.get("cache-control"), "no-cache")

        with tempfile.TemporaryDirectory() as td:
            manifest_path = os.path.join(td, "version.json")
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "version": "2.11",
                        "build": 114,
                        "assets": {"macos-arm64": {"filename": "old.dmg", "sha256": "a" * 64}},
                        "downloads": {"macos-arm64": "https://example.invalid/old.dmg"},
                    },
                    fh,
                )
            with contextlib.redirect_stdout(io.StringIO()):
                update_manifest(manifest_path, td, "2.11", 115)
            with open(manifest_path, encoding="utf-8") as fh:
                updated = json.load(fh)
            self.assertEqual(updated["version"], "2.11")
            self.assertEqual(updated["build"], 115)
            self.assertEqual(updated["assets"], {})
            self.assertEqual(updated["downloads"], {})


if __name__ == "__main__":
    unittest.main()

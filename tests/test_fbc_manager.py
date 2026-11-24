import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from unittest import mock

from core import fbc_manager


def _make_fake_fbc_script(path, output_line, exit_code=0):
    """Создаёт кроссплатформенный тестовый исполняемый скрипт (Unix shell или .bat)."""
    if os.name == "nt":
        content = f"@echo off\r\necho {output_line}\r\nexit /b {exit_code}\r\n"
    else:
        content = f"#!/bin/sh\necho '{output_line}'\nexit {exit_code}\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    if os.name != "nt":
        os.chmod(path, 0o755)
    return path


class _FakeHttpResponse:
    def __init__(self, data, headers=None):
        self._buf = io.BytesIO(data)
        self.headers = headers or {"Content-Length": str(len(data))}

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestFbcManager(unittest.TestCase):
    def test_parse_fbc_version_output(self):
        parsed = fbc_manager.parse_fbc_version_output(
            "fbc version 2.1.1 (go1.27.4) : d218bd92c7a0c0562e97d967c0dbcd39020a6584"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["version"], "2.1.1")
        self.assertEqual(parsed["go_version"], "go1.27.4")
        self.assertEqual(parsed["commit"], "d218bd92c7a0c0562e97d967c0dbcd39020a6584")

        # Посторонняя утилита с тем же именем (например FreeBASIC compiler)
        self.assertIsNone(
            fbc_manager.parse_fbc_version_output("FreeBASIC Compiler - Version 1.10.1 (2023-12-25)")
        )
        self.assertIsNone(fbc_manager.parse_fbc_version_output(""))

    def test_is_compatible_fbc_version(self):
        self.assertFalse(fbc_manager.is_compatible_fbc_version("1.74.0"))
        self.assertFalse(fbc_manager.is_compatible_fbc_version("2.0.9"))
        self.assertFalse(fbc_manager.is_compatible_fbc_version("2.1.0"))
        self.assertTrue(fbc_manager.is_compatible_fbc_version("2.1.1"))
        self.assertTrue(fbc_manager.is_compatible_fbc_version("2.2.0"))
        self.assertFalse(fbc_manager.is_compatible_fbc_version("3.0.0"))

    def test_parse_checksums_text(self):
        md5_a = "a" * 32
        sha_b = "b" * 64
        md5_c = "c" * 32
        txt = (
            f"# comment\n"
            f"{md5_a}  fbc-darwin-arm64.zip\n"
            f"{sha_b} *fbc-windows-amd64.zip\n"
            f"MD5 (fbc) = {md5_c}\n"
        )
        parsed = fbc_manager.parse_checksums_text(txt)
        self.assertEqual(parsed["fbc-darwin-arm64.zip"]["md5"], md5_a)
        self.assertEqual(parsed["fbc-windows-amd64.zip"]["sha256"], sha_b)
        self.assertEqual(parsed["fbc"]["md5"], md5_c)

    def test_select_release_asset(self):
        release = {
            "tag_name": "v2.1.1",
            "assets": [
                {"name": "checksums.txt", "browser_download_url": "https://example/checksums.txt"},
                {"name": "fbc-darwin-amd64.zip", "browser_download_url": "https://example/mac-x64.zip"},
                {"name": "fbc-darwin-arm64.zip", "browser_download_url": "https://example/mac-arm64.zip"},
                {"name": "fbc-windows-amd64.zip", "browser_download_url": "https://example/win-x64.zip"},
                {"name": "fbc-linux-amd64.tar.gz", "browser_download_url": "https://example/lin-x64.tar.gz"},
            ],
        }
        self.assertEqual(
            fbc_manager.select_release_asset(release, "darwin", "arm64")["name"],
            "fbc-darwin-arm64.zip",
        )
        self.assertEqual(
            fbc_manager.select_release_asset(release, "darwin", "amd64")["name"],
            "fbc-darwin-amd64.zip",
        )
        self.assertEqual(
            fbc_manager.select_release_asset(release, "windows", "amd64")["name"],
            "fbc-windows-amd64.zip",
        )
        # Windows ARM64 откатывается на amd64, если отдельного arm64 архива нет
        self.assertEqual(
            fbc_manager.select_release_asset(release, "windows", "arm64")["name"],
            "fbc-windows-amd64.zip",
        )
        self.assertEqual(
            fbc_manager.select_release_asset(release, "linux", "amd64")["name"],
            "fbc-linux-amd64.tar.gz",
        )

    def test_find_local_fbc_candidates_respects_path_and_deduplicates(self):
        bin_name = fbc_manager.get_fbc_binary_name()
        with tempfile.TemporaryDirectory() as td:
            dir_path = os.path.join(td, "sysbin")
            dir_user = os.path.join(td, "userdata")
            os.makedirs(dir_path)
            os.makedirs(dir_user)
            p_sys = os.path.join(dir_path, bin_name)
            p_usr = os.path.join(dir_user, bin_name)
            with open(p_sys, "wb") as f:
                f.write(b"sys")
            with open(p_usr, "wb") as f:
                f.write(b"usr")

            with mock.patch.dict(os.environ, {"PATH": dir_path}), \
                 mock.patch.object(fbc_manager.shutil, "which", return_value=p_sys):
                cands = fbc_manager.find_local_fbc_candidates(user_data_dir=dir_user, include_system_path=True)

            real_cands = [os.path.realpath(c) for c in cands]
            self.assertIn(os.path.realpath(p_sys), real_cands)
            self.assertIn(os.path.realpath(p_usr), real_cands)
            self.assertEqual(real_cands.index(os.path.realpath(p_sys)), 0)
            self.assertEqual(len(real_cands), len(set(real_cands)))

    def test_verify_binary_known_hash_match_and_mismatch(self):
        info_base = {
            "is_fb2cng": True,
            "compatible": True,
            "version": "2.1.1",
            "md5": "7b59c71d33402c3103bf8166c72a7f4a",
            "sha256": "500c73124cc63a827bf0fb908a9a53d3f2bbf72f3000c1ca87c656705eb9187e",
        }
        with mock.patch.object(fbc_manager, "normalize_platform_arch", return_value=("darwin", "arm64")):
            ok_res = fbc_manager.verify_binary_against_github(info_base, check_github=False)
            self.assertTrue(ok_res["verified"])
            self.assertEqual(ok_res["source"], "known_md5")

            tampered = dict(info_base, md5="0" * 32)
            bad_res = fbc_manager.verify_binary_against_github(tampered, check_github=False)
            self.assertFalse(bad_res["verified"])
            self.assertEqual(bad_res["reason"], "hash_mismatch")

    def test_verify_binary_rejects_unknown_release_404(self):
        info = {
            "is_fb2cng": True,
            "compatible": True,
            "version": "2.99.99",
            "md5": "1" * 32,
            "sha256": "2" * 64,
        }
        err_404 = urllib.error.HTTPError("https://api.github.com/test", 404, "Not Found", {}, None)
        with mock.patch.object(fbc_manager, "fetch_github_release", side_effect=err_404):
            res = fbc_manager.verify_binary_against_github(info, check_github=True)
        self.assertFalse(res["verified"])
        self.assertEqual(res["reason"], "unknown_release")

    def test_download_and_install_fbc_verifies_digest_and_extracts(self):
        if os.name == "nt":
            self.skipTest("Unix shell mock binary test")

        with tempfile.TemporaryDirectory() as td:
            bin_name = "fbc"
            fake_bin_content = (
                "#!/bin/sh\n"
                "echo 'fbc version 2.2.0 (go1.27.4) : deadbeef1234567890'\n"
            ).encode("utf-8")

            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                zf.writestr(bin_name, fake_bin_content)
            zip_bytes = zip_buf.getvalue()
            zip_sha256 = hashlib.sha256(zip_bytes).hexdigest()

            release_payload = {
                "tag_name": "v2.2.0",
                "assets": [
                    {
                        "name": "fbc-darwin-arm64.zip",
                        "size": len(zip_bytes),
                        "digest": f"sha256:{zip_sha256}",
                        "browser_download_url": "https://example.invalid/fbc-darwin-arm64.zip",
                    }
                ],
            }

            progress_calls = []

            with mock.patch.object(fbc_manager, "normalize_platform_arch", return_value=("darwin", "arm64")), \
                 mock.patch.object(fbc_manager, "fetch_github_release", return_value=release_payload), \
                 mock.patch.object(fbc_manager.urllib.request, "urlopen", return_value=_FakeHttpResponse(zip_bytes)):
                res = fbc_manager.download_and_install_fbc(
                    td,
                    target_version="2.2.0",
                    progress_callback=lambda dl, tot, name: progress_calls.append((dl, tot, name)),
                )

            self.assertTrue(res["ok"])
            self.assertTrue(res["downloaded"])
            self.assertEqual(res["version"], "2.2.0")
            self.assertTrue(os.path.isfile(res["path"]))
            self.assertTrue(os.access(res["path"], os.X_OK))
            self.assertGreater(len(progress_calls), 0)

            # Кэш проверки записан и повторный ensure_fbc_available не перекачивает бинарник
            cache_path = os.path.join(td, fbc_manager.FBC_VERIFIED_CACHE_FILE)
            self.assertTrue(os.path.isfile(cache_path))

            with mock.patch.object(fbc_manager, "normalize_platform_arch", return_value=("darwin", "arm64")), \
                 mock.patch.object(fbc_manager, "download_and_install_fbc") as mock_dl:
                res2 = fbc_manager.ensure_fbc_available(
                    td,
                    allow_download=True,
                    check_github=True,
                    include_system_path=False,
                )
            self.assertTrue(res2["ok"])
            self.assertFalse(res2["downloaded"])
            self.assertEqual(res2["source"], "verified_cache")
            mock_dl.assert_not_called()

    def test_download_rejects_corrupted_archive_digest(self):
        with tempfile.TemporaryDirectory() as td:
            release_payload = {
                "tag_name": "v2.2.0",
                "assets": [
                    {
                        "name": "fbc-darwin-arm64.zip",
                        "size": 10,
                        "digest": "sha256:" + ("0" * 64),
                        "browser_download_url": "https://example.invalid/fbc-darwin-arm64.zip",
                    }
                ],
            }
            with mock.patch.object(fbc_manager, "normalize_platform_arch", return_value=("darwin", "arm64")), \
                 mock.patch.object(fbc_manager, "fetch_github_release", return_value=release_payload), \
                 mock.patch.object(fbc_manager.urllib.request, "urlopen", return_value=_FakeHttpResponse(b"corrupted")):
                with self.assertRaises(RuntimeError) as ctx:
                    fbc_manager.download_and_install_fbc(td, target_version="2.2.0")
            self.assertIn("SHA256 mismatch", str(ctx.exception))

    def test_ensure_fbc_available_rejects_outdated_and_triggers_download(self):
        if os.name == "nt":
            self.skipTest("Unix shell mock binary test")

        with tempfile.TemporaryDirectory() as td:
            old_fbc = os.path.join(td, "fbc")
            _make_fake_fbc_script(old_fbc, "fbc version 1.74.0 (go1.22.0) : 1111111")

            fake_dl_result = {
                "ok": True,
                "path": old_fbc,
                "version": "2.1.1",
                "md5": "7b59c71d33402c3103bf8166c72a7f4a",
                "sha256": "500c73124cc63a827bf0fb908a9a53d3f2bbf72f3000c1ca87c656705eb9187e",
                "source": "github_download",
                "downloaded": True,
                "reason": "",
                "error": "",
            }
            with mock.patch.object(fbc_manager, "download_and_install_fbc", return_value=fake_dl_result) as mock_dl:
                res = fbc_manager.ensure_fbc_available(
                    td,
                    allow_download=True,
                    check_github=False,
                    include_system_path=False,
                )
            self.assertTrue(res["ok"])
            self.assertTrue(res["downloaded"])
            self.assertEqual(res["reason"], "incompatible_version")
            mock_dl.assert_called_once()

    def test_copy_stream_limited_enforces_limit(self):
        src = io.BytesIO(b"abcdefghij")
        dst = io.BytesIO()
        fbc_manager._copy_stream_limited(src, dst, max_bytes=10)
        self.assertEqual(dst.getvalue(), b"abcdefghij")

        src_big = io.BytesIO(b"0123456789X")
        dst_big = io.BytesIO()
        with self.assertRaises(RuntimeError):
            fbc_manager._copy_stream_limited(src_big, dst_big, max_bytes=10)

    def test_download_and_install_fbc_pre_cancelled(self):
        import threading

        ev = threading.Event()
        ev.set()
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(fbc_manager, "fetch_github_release") as mock_fetch:
                with self.assertRaises(fbc_manager.FbcDownloadCancelledError):
                    fbc_manager.download_and_install_fbc(td, cancel_event=ev)
            mock_fetch.assert_not_called()

    def test_verify_binary_does_not_cache_unhashed_github_release(self):
        with tempfile.TemporaryDirectory() as td:
            info = {
                "is_fb2cng": True,
                "compatible": True,
                "version": "2.99.1",
                "md5": "a" * 32,
                "sha256": "b" * 64,
            }
            release_payload = {
                "tag_name": "v2.99.1",
                "assets": [
                    {
                        "name": "fbc-darwin-arm64.zip",
                        "browser_download_url": "https://example.invalid/fbc-darwin-arm64.zip",
                    }
                ],
            }
            with mock.patch.object(fbc_manager, "normalize_platform_arch", return_value=("darwin", "arm64")), \
                 mock.patch.object(fbc_manager, "fetch_github_release", return_value=release_payload), \
                 mock.patch.object(fbc_manager, "fetch_release_checksums", return_value={}):
                res = fbc_manager.verify_binary_against_github(info, user_data_dir=td, check_github=True)
            self.assertTrue(res["verified"])
            self.assertEqual(res["source"], "github_release_unhashed")
            self.assertFalse(os.path.exists(os.path.join(td, fbc_manager.FBC_VERIFIED_CACHE_FILE)))

    def test_download_rejects_plain_http_url(self):
        with tempfile.TemporaryDirectory() as td:
            release_payload = {
                "tag_name": "v2.2.0",
                "assets": [
                    {
                        "name": "fbc-darwin-arm64.zip",
                        "size": 10,
                        "browser_download_url": "http://example.invalid/fbc-darwin-arm64.zip",
                    }
                ],
            }
            with mock.patch.object(fbc_manager, "normalize_platform_arch", return_value=("darwin", "arm64")), \
                 mock.patch.object(fbc_manager, "fetch_github_release", return_value=release_payload):
                with self.assertRaises(RuntimeError) as ctx:
                    fbc_manager.download_and_install_fbc(td, target_version="2.2.0")
            self.assertIn("Unsupported download URL scheme", str(ctx.exception))

    def test_download_fbc_enforces_size_limit_and_handles_bad_content_length(self):
        with tempfile.TemporaryDirectory() as td:
            release_payload = {
                "tag_name": "v2.2.0",
                "assets": [
                    {
                        "name": "fbc-darwin-arm64.zip",
                        "size": 10,
                        "browser_download_url": "https://example.invalid/fbc-darwin-arm64.zip",
                    }
                ],
            }
            bad_cl_big = _FakeHttpResponse(b"0123456789X", headers={"Content-Length": "invalid"})
            with mock.patch.object(fbc_manager, "MAX_ARCHIVE_BIN_BYTES", 10), \
                 mock.patch.object(fbc_manager, "normalize_platform_arch", return_value=("darwin", "arm64")), \
                 mock.patch.object(fbc_manager, "fetch_github_release", return_value=release_payload), \
                 mock.patch.object(fbc_manager.urllib.request, "urlopen", return_value=bad_cl_big):
                with self.assertRaises(RuntimeError) as ctx:
                    fbc_manager.download_and_install_fbc(td, target_version="2.2.0")
            self.assertIn("size limit", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

import unittest

from core.updater import (
    is_newer_version,
    parse_version_tuple,
    select_download_url,
)


class TestUpdater(unittest.TestCase):
    def test_parse_version_tuple(self):
        self.assertEqual(parse_version_tuple("2.5"), (2, 5))
        self.assertEqual(parse_version_tuple("v2.5.1"), (2, 5, 1))
        self.assertEqual(parse_version_tuple("2.5b3"), (2, 53))
        self.assertEqual(parse_version_tuple(""), (0,))

    def test_is_newer_version(self):
        self.assertTrue(is_newer_version("2.6", 50, "2.5", 49))
        self.assertTrue(is_newer_version("2.5.1", 49, "2.5", 49))
        self.assertTrue(is_newer_version("2.5", 50, "2.5", 49))
        self.assertFalse(is_newer_version("2.5", 49, "2.5", 49))
        self.assertFalse(is_newer_version("2.4", 99, "2.5", 49))

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
        from core.updater import is_safe_http_url

        self.assertTrue(is_safe_http_url("https://localhost/app"))
        self.assertFalse(is_safe_http_url("ftp://localhost/app", allow_relative=True))
        self.assertFalse(is_safe_http_url("mailto:user@localhost", allow_relative=True))
        self.assertFalse(is_safe_http_url("//localhost/app", allow_relative=True))

        unsafe_manifest = {
            "downloads": {"darwin": "ftp://localhost/mac"},
            "download_url": "mailto:user@localhost",
        }
        self.assertEqual(
            select_download_url(unsafe_manifest, platform="darwin", fallback_url="pkg/fb"),
            "pkg/fb",
        )


if __name__ == "__main__":
    unittest.main()

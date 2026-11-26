"""Unit tests for Watch Folder Auto-Repair, Auto-Enrich confidence matching, and Cover Studio fallback."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from core.metadata_lookup import BookMetadataCandidate, LookupResult
from core.watch_folder import (
    match_best_enrich_candidate,
    normalize_watch_rule,
    prepare_watch_book_item,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    from ui.dialogs.watch_folder import WatchFolderRuleDialog

    HAS_QT = True
except Exception:
    HAS_QT = False


def _sample_jpeg_bytes() -> bytes:
    img = Image.new("RGB", (200, 300), "#12352C")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestWatchRuleNormalization(unittest.TestCase):
    def test_defaults_keep_preprocessing_disabled_for_legacy_rules(self) -> None:
        rule = normalize_watch_rule({"folder": "/tmp/books"})
        self.assertFalse(rule["auto_repair"])
        self.assertEqual(rule["auto_enrich_mode"], "off")
        self.assertEqual(rule["enrich_min_confidence"], 0.88)
        self.assertFalse(rule["fallback_cover_enabled"])
        self.assertEqual(rule["fallback_cover_template"], "eink_minimal")
        self.assertTrue(rule["fallback_cover_series_color"])
        self.assertFalse(rule["write_back_source"])

    def test_invalid_values_are_sanitized(self) -> None:
        rule = normalize_watch_rule({
            "folder": "/tmp/books",
            "auto_enrich_mode": "invalid_mode",
            "enrich_min_confidence": 5.0,
            "enrich_timeout_sec": 1,
            "fallback_cover_template": "nonexistent",
        })
        self.assertEqual(rule["auto_enrich_mode"], "off")
        self.assertEqual(rule["enrich_min_confidence"], 0.99)
        self.assertEqual(rule["enrich_timeout_sec"], 3.0)
        self.assertEqual(rule["fallback_cover_template"], "eink_minimal")


class TestWatchEnrichMatching(unittest.TestCase):
    def test_exact_isbn_match_returns_full_confidence(self) -> None:
        cand = BookMetadataCandidate(
            provider="fantlab",
            title="Другое издание",
            last="Стругацкий",
            isbn="978-0-306-40615-7",
        )
        matched, score = match_best_enrich_candidate(
            [cand],
            {"title": "Пикник", "last": "Стругацкий", "isbn": "9780306406157"},
            min_confidence=0.92,
        )
        self.assertIs(matched, cand)
        self.assertEqual(score, 1.0)

    def test_wrong_author_is_rejected_even_when_title_matches(self) -> None:
        wrong_author = BookMetadataCandidate(
            provider="litres",
            title="Ловец бабочек",
            last="Иванов",
        )
        matched, _score = match_best_enrich_candidate(
            [wrong_author],
            {"title": "Ловец бабочек [СИ]", "last": "Дёмина"},
            min_confidence=0.80,
        )
        self.assertIsNone(matched)

    def test_yo_and_samizdat_noise_match_cleanly(self) -> None:
        good = BookMetadataCandidate(
            provider="fantlab",
            title="Ловец бабочек",
            last="Демина",
            series="Хельмова дюжина",
        )
        matched, score = match_best_enrich_candidate(
            [good],
            {"title": "Ловец бабочек [СИ]", "last": "Дёмина", "series": "Хельмова дюжина"},
            min_confidence=0.92,
        )
        self.assertIs(matched, good)
        self.assertGreaterEqual(score, 0.92)


class TestPrepareWatchBookItem(unittest.TestCase):
    def test_auto_repair_fixes_broken_xml_without_modifying_source(self) -> None:
        broken_xml = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            b'<description><title-info>'
            b'<author><first-name>Ivan</first-name><last-name>Petrov</last-name></author>'
            b'<book-title>Rock & Roll</book-title>'
            b'</title-info></description>'
            b'<body><section><p>Hello & world</p></section></body>'
            b'</FictionBook>'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            src_path = os.path.join(tmpdir, "broken.fb2")
            with open(src_path, "wb") as fh:
                fh.write(broken_xml)

            item_data = {
                "path": src_path,
                "display_name": "broken.fb2",
                "meta": {"title": "Rock & Roll", "last": "Petrov", "first": "Ivan", "mid": "", "series": "", "num": ""},
                "cover_bytes": None,
                "cover_mime": None,
                "cover_modified": False,
            }
            stats = prepare_watch_book_item(
                item_data,
                broken_xml,
                {"folder": tmpdir, "auto_repair": True, "write_back_source": False},
            )
            self.assertTrue(stats["repaired"])
            self.assertIn("xml", item_data)
            self.assertFalse(stats["written_back"])
            # Source file must stay untouched when write_back_source=False
            with open(src_path, "rb") as fh:
                self.assertEqual(fh.read(), broken_xml)

    def test_auto_enrich_fills_empty_fields_preserves_existing_and_caches(self) -> None:
        cand = BookMetadataCandidate(
            provider="fantlab",
            title="Пикник на обочине",
            first="Аркадий",
            last="Стругацкий",
            series="Мир Полудня",
            num="1",
            genres=["sf"],
            annotation="Классический роман.",
            publisher="АСТ",
            cover_urls=["https://example.com/cover.jpg"],
        )
        jpeg = _sample_jpeg_bytes()
        item1 = {
            "display_name": "picnic.fb2",
            "meta": {
                "title": "Пикник на обочине",
                "first": "Аркадий",
                "last": "Стругацкий",
                "mid": "",
                "series": "Моя серия",  # Existing value must NOT be overwritten
                "num": "",
                "genres": [],
                "annotation": "",
                "publisher": "",
                "isbn": "",
            },
            "cover_bytes": None,
            "cover_mime": None,
            "cover_modified": False,
        }
        rule = {
            "folder": "/tmp/books",
            "auto_enrich_mode": "empty_only",
            "enrich_min_confidence": 0.88,
            "enrich_providers": ["fantlab"],
        }
        cache = {}

        with patch("core.watch_folder.search_book_metadata", return_value=LookupResult(candidates=[cand])) as m_search, \
             patch("core.watch_folder.fetch_candidate_covers", return_value=[{"bytes": jpeg, "mime": "image/jpeg"}]):
            stats1 = prepare_watch_book_item(item1, b"", rule, enrich_cache=cache)
            self.assertTrue(stats1["enriched"])
            self.assertEqual(item1["meta"]["series"], "Моя серия")
            self.assertEqual(item1["meta"]["annotation"], "Классический роман.")
            self.assertEqual(item1["meta"]["genres"], ["sf"])
            self.assertIsNotNone(item1["cover_bytes"])
            self.assertEqual(m_search.call_count, 1)

            # Second identical book hits session cache without another network call
            item2 = {
                "display_name": "picnic2.fb2",
                "meta": {"title": "Пикник на обочине", "first": "Аркадий", "last": "Стругацкий", "series": "", "genres": []},
                "cover_bytes": None,
                "cover_mime": None,
                "cover_modified": False,
            }
            stats2 = prepare_watch_book_item(item2, b"", rule, enrich_cache=cache)
            self.assertTrue(stats2["enriched"])
            self.assertEqual(m_search.call_count, 1)

    def test_fallback_cover_studio_generates_only_when_missing(self) -> None:
        item_missing = {
            "display_name": "no_cover.fb2",
            "meta": {"title": "Книга без обложки", "last": "Автор", "series": "Цикл", "num": "2"},
            "cover_bytes": None,
            "cover_mime": None,
            "cover_modified": False,
        }
        rule = {
            "folder": "/tmp/books",
            "fallback_cover_enabled": True,
            "fallback_cover_template": "series_edition",
            "fallback_cover_series_color": True,
        }
        stats = prepare_watch_book_item(item_missing, b"", rule)
        self.assertTrue(stats["cover_generated"])
        self.assertTrue(item_missing["cover_bytes"].startswith(b"\xff\xd8\xff"))

        # Existing cover must NOT be replaced by fallback
        item_has_cover = {
            "display_name": "has_cover.fb2",
            "meta": {"title": "Книга с обложкой"},
            "cover_bytes": b"EXISTING",
            "cover_mime": "image/jpeg",
            "cover_modified": False,
        }
        stats2 = prepare_watch_book_item(item_has_cover, b"", rule)
        self.assertFalse(stats2["cover_generated"])
        self.assertEqual(item_has_cover["cover_bytes"], b"EXISTING")


@unittest.skipUnless(HAS_QT, "PyQt6 not available")
class TestWatchFolderRuleDialogPrepTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_dialog_round_trips_preprocessing_settings(self) -> None:
        initial = {
            "folder": "/tmp",
            "name": "Kindle Drop",
            "auto_repair": True,
            "auto_enrich_mode": "empty_only",
            "enrich_min_confidence": 0.92,
            "enrich_providers": ["fantlab", "openlibrary"],
            "fallback_cover_enabled": True,
            "fallback_cover_template": "classic_serif",
            "fallback_cover_series_color": False,
            "write_back_source": True,
        }
        dlg = WatchFolderRuleDialog(None, rule=initial)
        try:
            out = dlg.get_rule()
            self.assertTrue(out["auto_repair"])
            self.assertEqual(out["auto_enrich_mode"], "empty_only")
            self.assertEqual(out["enrich_min_confidence"], 0.92)
            self.assertEqual(out["enrich_providers"], ["fantlab", "openlibrary"])
            self.assertTrue(out["fallback_cover_enabled"])
            self.assertEqual(out["fallback_cover_template"], "classic_serif")
            self.assertFalse(out["fallback_cover_series_color"])
            self.assertTrue(out["write_back_source"])
        finally:
            dlg.close()

    def test_fallback_template_combo_exposes_all_styles_and_enables_on_pick(self) -> None:
        from core.cover_studio import TEMPLATES as COVER_TEMPLATES

        dlg = WatchFolderRuleDialog(None, rule={"folder": "/tmp", "fallback_cover_enabled": False})
        try:
            self.assertTrue(dlg.fallback_tpl_combo.isEnabled())
            self.assertEqual(dlg.fallback_tpl_combo.count(), len(COVER_TEMPLATES))
            available = {
                dlg.fallback_tpl_combo.itemData(i)
                for i in range(dlg.fallback_tpl_combo.count())
            }
            self.assertEqual(available, set(COVER_TEMPLATES.keys()))

            idx = dlg.fallback_tpl_combo.findData("modern_band")
            self.assertGreaterEqual(idx, 0)
            dlg.fallback_tpl_combo.setCurrentIndex(idx)
            dlg._on_fallback_template_activated(idx)
            out = dlg.get_rule()
            self.assertTrue(out["fallback_cover_enabled"])
            self.assertEqual(out["fallback_cover_template"], "modern_band")
        finally:
            dlg.close()

    def test_tray_notification_includes_prep_counters_when_nonzero(self) -> None:
        from ui.controllers.tray_controller import TrayWatchController

        class _DummyHost(TrayWatchController):
            def __init__(self):
                self.app_name = "FBC GUI"
                self.app_settings = {"watch_notifications_enabled": True}
                self._tray_icon = None

            def refresh_tray_menu(self):
                pass

        host = _DummyHost()
        sent = []
        with patch("ui.controllers.tray_controller.send_system_notification", side_effect=lambda title, msg, **kw: sent.append(msg)):
            host._on_watch_batch_completed({
                "rule_name": "Kindle",
                "delivery_mode": "folder",
                "success_count": 3,
                "error_count": 0,
                "repaired_count": 1,
                "enriched_count": 2,
                "covers_generated_count": 1,
            })
            host._on_watch_batch_completed({
                "rule_name": "Kindle",
                "delivery_mode": "folder",
                "success_count": 1,
                "error_count": 0,
                "repaired_count": 0,
                "enriched_count": 0,
                "covers_generated_count": 0,
            })

        self.assertEqual(len(sent), 2)
        self.assertIn("•", sent[0])
        self.assertIn("1", sent[0])
        self.assertIn("2", sent[0])
        self.assertNotIn("•", sent[1])


if __name__ == "__main__":
    unittest.main()

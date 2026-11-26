"""Unit tests for core/cover_studio.py and ui/dialogs/cover_studio.py."""

from __future__ import annotations

import io
import os
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from core import cover_studio as cs

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtGui import QUndoStack
    from PyQt6.QtWidgets import QApplication
    from ui.dialogs.cover_studio import CoverStudioDialog, apply_cover_studio_to_books

    HAS_QT = True
except Exception:
    HAS_QT = False


class _FakeQueueTarget:
    """Минимальный таргет для проверки интеграции UpdateBooksCommand + QUndoStack."""

    def __init__(self, files_data: dict):
        self.files_data = files_data
        self.undo_stack = QUndoStack()

    def _apply_book_snapshots(self, pairs):
        for item_id, snap in pairs:
            data = self.files_data.get(item_id)
            if data is None:
                continue
            data["meta"] = dict(snap["meta"])
            data["cover_bytes"] = snap.get("cover_bytes")
            data["cover_mime"] = snap.get("cover_mime")
            data["cover_modified"] = bool(snap.get("cover_modified", False))


class TestCoverPalettes(unittest.TestCase):
    def test_auto_series_is_deterministic(self) -> None:
        spec = cs.CoverSpec(palette_id="auto_series")
        p1 = cs.resolve_palette(spec, series="Мир Полудня")
        p2 = cs.resolve_palette(spec, series="  мир   полудня ")
        self.assertEqual(p1.id, p2.id)
        self.assertIn(p1.id, cs.SERIES_COLOR_POOL)

    def test_auto_series_empty_falls_back_to_eink_paper(self) -> None:
        spec = cs.CoverSpec(palette_id="auto_series")
        p = cs.resolve_palette(spec, series="")
        self.assertEqual(p.id, "eink_paper")

    def test_custom_hex_overrides_and_auto_contrast(self) -> None:
        spec = cs.CoverSpec(palette_id="eink_paper", custom_bg="#101820", custom_accent="E0A458")
        p = cs.resolve_palette(spec, series="")
        self.assertEqual(p.bg, "#101820")
        self.assertEqual(p.accent, "#E0A458")
        self.assertEqual(p.fg, "#F5F5F5")

    def test_invalid_custom_hex_is_ignored(self) -> None:
        spec = cs.CoverSpec(palette_id="emerald", custom_bg="not-a-color")
        p = cs.resolve_palette(spec)
        self.assertEqual(p.bg, cs.PALETTES["emerald"].bg)


class TestCoverSpecAndMetadata(unittest.TestCase):
    def test_round_trip_dict(self) -> None:
        original = cs.CoverSpec(
            template_id="series_edition",
            palette_id="burgundy",
            show_genre_badge=True,
            eink_profile="eink_bw",
            output_size=(400, 600),
            output_format="PNG",
            jpeg_quality=85,
        )
        restored = cs.CoverSpec.from_dict(original.to_dict())
        self.assertEqual(original, restored)

    def test_from_book_data_queue_entry(self) -> None:
        entry = {
            "meta": {
                "last": "Герберт",
                "first": "Фрэнк",
                "mid": "",
                "series": "Хроники Дюны",
                "num": "1",
                "title": "Дюна",
                "genres": ["sf_space"],
            },
            "cover_bytes": None,
        }
        meta = cs.CoverMetadata.from_book_data(entry, lang="ru")
        self.assertEqual(meta.title, "Дюна")
        self.assertEqual(meta.author, "Фрэнк Герберт")
        self.assertEqual(meta.series, "Хроники Дюны")
        self.assertEqual(meta.series_number, "1")
        self.assertTrue(bool(meta.genre))


class TestTextWrappingAndRendering(unittest.TestCase):
    def setUp(self) -> None:
        self.img = Image.new("RGB", (600, 900), "#FFFFFF")
        self.draw = ImageDraw.Draw(self.img)
        self.font_path = cs.resolve_font_path("PT Astra Serif", bold=True)

    def test_cyrillic_fit_within_bounds(self) -> None:
        long_title = (
            "Очень длинное название фантастического романа о путешествии "
            "через межзвёздные пространства и загадочные миры далёкого будущего"
        )
        font, lines, step = cs.fit_text_block(
            self.draw,
            long_title,
            self.font_path,
            max_width=480,
            max_height=360,
            max_size=72,
            min_size=24,
            max_lines=6,
        )
        self.assertGreaterEqual(len(lines), 1)
        self.assertLessEqual(len(lines), 6)
        self.assertGreater(step, 0)
        for line in lines:
            bbox = self.draw.textbbox((0, 0), line, font=font)
            self.assertLessEqual(bbox[2] - bbox[0], 485)

    def test_all_five_templates_render_valid_jpeg(self) -> None:
        meta = cs.CoverMetadata(
            title="Пикник на обочине",
            author="Аркадий и Борис Стругацкие",
            series="Мир Полудня",
            series_number="1",
            genre="Научная фантастика",
        )
        for tpl_id in cs.TEMPLATES:
            with self.subTest(template=tpl_id):
                raw = cs.render_cover_bytes(
                    meta,
                    cs.CoverSpec(template_id=tpl_id, palette_id="auto_series", show_genre_badge=True),
                )
                self.assertTrue(raw.startswith(b"\xff\xd8\xff"))
                img = Image.open(io.BytesIO(raw))
                self.assertEqual(img.size, (600, 900))
                self.assertEqual(img.format, "JPEG")

    def test_eink_profiles_via_image_optimizer(self) -> None:
        meta = cs.CoverMetadata(title="Тест E Ink", author="Автор")
        for profile in ("eink_bw", "eink_bw_16_dither", "eink_kaleido3", "eink_gallery3"):
            with self.subTest(profile=profile):
                out = cs.render_cover_image(
                    meta,
                    cs.CoverSpec(palette_id="emerald", eink_profile=profile),
                    simulate_eink_preview=True,
                )
                self.assertEqual(out.size, (600, 900))
                if profile in ("eink_bw", "eink_bw_16_dither"):
                    px = out.getpixel((300, 450))
                    self.assertEqual(px[0], px[1])
                    self.assertEqual(px[1], px[2])

    def test_discover_bundled_fonts(self) -> None:
        fonts_dir = Path(__file__).resolve().parent.parent / "fonts"
        names = cs.discover_available_fonts(fonts_dir)
        self.assertTrue(any("Astra" in n for n in names))


@unittest.skipUnless(HAS_QT, "PyQt6 not available")
class TestCoverStudioDialogAndUndo(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_dialog_renders_and_updates_spec(self) -> None:
        book_data = {
            "meta": {
                "last": "Толстой",
                "first": "Лев",
                "mid": "",
                "series": "Классика",
                "num": "1",
                "title": "Война и мир",
                "genres": [],
            },
            "cover_bytes": None,
        }
        dlg = CoverStudioDialog(None, book_data=book_data, books_count=1)
        try:
            dlg._select_template("classic_serif")
            dlg._select_palette("burgundy")
            dlg._update_preview_now()
            spec = dlg.get_spec()
            self.assertEqual(spec.template_id, "classic_serif")
            self.assertEqual(spec.palette_id, "burgundy")
            raw, mime = dlg.get_rendered_cover()
            self.assertEqual(mime, "image/jpeg")
            self.assertTrue(raw.startswith(b"\xff\xd8\xff"))
        finally:
            dlg.close()

    def test_apply_cover_studio_with_undo_and_only_missing(self) -> None:
        files_data = {
            "1": {
                "meta": {"last": "Лем", "first": "Станислав", "mid": "", "series": "", "num": "", "title": "Солярис"},
                "cover_bytes": None,
                "cover_mime": None,
                "cover_modified": False,
            },
            "2": {
                "meta": {"last": "Лем", "first": "Станислав", "mid": "", "series": "", "num": "", "title": "Эдем"},
                "cover_bytes": b"EXISTING_COVER",
                "cover_mime": "image/jpeg",
                "cover_modified": False,
            },
        }
        target = _FakeQueueTarget(files_data)
        spec = cs.CoverSpec(template_id="eink_minimal", palette_id="graphite", output_size=(300, 450))

        updated = apply_cover_studio_to_books(target, ["1", "2"], spec, only_missing=True)
        self.assertEqual(updated, 1)
        self.assertIsNotNone(files_data["1"]["cover_bytes"])
        self.assertTrue(files_data["1"]["cover_modified"])
        self.assertEqual(files_data["2"]["cover_bytes"], b"EXISTING_COVER")

        # Undo restores original state cleanly
        self.assertTrue(target.undo_stack.canUndo())
        target.undo_stack.undo()
        self.assertIsNone(files_data["1"]["cover_bytes"])
        self.assertFalse(files_data["1"]["cover_modified"])

        # Redo reapplies generated cover
        target.undo_stack.redo()
        self.assertIsNotNone(files_data["1"]["cover_bytes"])
        self.assertTrue(files_data["1"]["cover_modified"])

    def test_book_edit_dialog_has_cover_studio_button_and_qss_object_names(self) -> None:
        from ui.dialogs.book_edit import BookEditDialog
        from ui.theme import FormatComboBox

        data = {
            "path": "/tmp/book.fb2",
            "display_name": "book.fb2",
            "meta": {"last": "Иванов", "first": "Иван", "mid": "", "series": "Цикл", "num": "1", "title": "Книга"},
            "cover_bytes": None,
            "cover_mime": None,
            "orig_cover_bytes": None,
            "orig_cover_mime": None,
            "cover_modified": False,
        }
        edit_dlg = BookEditDialog(None, data, "epub3")
        try:
            self.assertEqual(edit_dlg.objectName(), "MainContainer")
            self.assertTrue(hasattr(edit_dlg, "btn_cover_studio"))
            self.assertTrue(edit_dlg.btn_cover_studio.isEnabled())
        finally:
            edit_dlg.close()

        cs_dlg = CoverStudioDialog(None, book_data=data, books_count=1)
        try:
            self.assertIsInstance(cs_dlg.combo_font, FormatComboBox)
            self.assertEqual(cs_dlg.preview_label.objectName(), "CoverPanel")
            for btn in cs_dlg._template_buttons.values():
                self.assertEqual(btn.objectName(), "TemplateCardBtn")
        finally:
            cs_dlg.close()


if __name__ == "__main__":
    unittest.main()

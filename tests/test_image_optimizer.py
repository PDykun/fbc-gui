"""Тесты оптимизации изображений под экраны ридеров, расширяемого реестра профилей и имитации E Ink в превью."""

import base64
import io
import os
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from core.css_preview import build_full_preview_html, get_default_css_ui_state
from core.fb2_processor import convert_book_file, extract_cover_from_fb2, parse_metadata
from core.image_optimizer import (
    HAS_PIL,
    IMAGE_DISPLAY_PROFILES,
    clear_preview_image_cache,
    get_eink_paper_preview_style,
    get_image_display_profile_choices,
    optimize_and_preview_image_bytes,
    optimize_fb2_binaries_for_profile,
    optimize_image_bytes,
    register_image_display_profile,
    resolve_image_display_profile,
    simulate_eink_preview_bytes,
)

if HAS_PIL:
    from PIL import Image


def _make_color_gradient_png(width=64, height=64):
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            px[x, y] = (int(x * 255 / max(1, width - 1)), int(y * 180 / max(1, height - 1)), 90)
    img.save(buf, format="PNG")
    return buf.getvalue()


@unittest.skipUnless(HAS_PIL, "Pillow is required for image optimizer tests")
class TestImageOptimizer(unittest.TestCase):
    def setUp(self):
        clear_preview_image_cache()

    def test_bw_and_16_dither_profiles_produce_grayscale_and_bounded_levels(self):
        src_png = _make_color_gradient_png()
        same_bytes, same_mime = optimize_image_bytes(src_png, "image/png", "none")
        self.assertEqual(same_bytes, src_png)
        self.assertEqual(same_mime, "image/png")

        bw_bytes, bw_mime = optimize_image_bytes(src_png, "image/png", "eink_bw")
        self.assertEqual(bw_mime, "image/png")
        with Image.open(io.BytesIO(bw_bytes)) as im:
            self.assertEqual(im.mode, "L")

        dith_bytes, _ = optimize_image_bytes(src_png, "image/png", "eink_bw_16_dither")
        with Image.open(io.BytesIO(dith_bytes)) as im:
            self.assertEqual(im.mode, "L")
            unique_vals = set(im.getdata())
            self.assertLessEqual(len(unique_vals), 16)

    def test_color_profiles_enhance_saturation_and_simulate_eink_reduces_range(self):
        src_png = _make_color_gradient_png()
        kal_bytes, _ = optimize_image_bytes(src_png, "image/png", "eink_kaleido3")
        gal_bytes, _ = optimize_image_bytes(src_png, "image/png", "eink_gallery3")
        self.assertNotEqual(kal_bytes, src_png)
        self.assertNotEqual(gal_bytes, src_png)

        sim_kal, _ = simulate_eink_preview_bytes(kal_bytes, "image/png", "eink_kaleido3")
        with Image.open(io.BytesIO(sim_kal)) as im:
            self.assertEqual(im.mode, "RGB")
            extrema = im.getextrema()
            # Чёрная и белая границы сжаты в физический диапазон Kaleido 3
            for lo, hi in extrema:
                self.assertGreaterEqual(lo, 25)
                self.assertLessEqual(hi, 225)

    def test_extensible_profile_registration_and_inline_custom_profile(self):
        custom_id = "eink_kaleido4_test"
        try:
            register_image_display_profile(
                custom_id,
                {
                    "fallback_label": "Color E Ink (Kaleido 4)",
                    "mode": "color",
                    "optimize": {"gamma": 1.10, "saturation": 1.20, "contrast": 1.05},
                    "simulate": {
                        "color_bits_per_channel": 5,
                        "saturation_scale": 0.72,
                        "black_floor": 30,
                        "white_ceiling": 225,
                        "paper_bg": "#E4E2DC",
                        "paper_text": "#222220",
                    },
                },
            )
            choices = dict((pid, lbl) for lbl, pid in get_image_display_profile_choices())
            self.assertIn(custom_id, choices)

            src_png = _make_color_gradient_png(32, 32)
            out_b, _ = optimize_and_preview_image_bytes(src_png, "image/png", custom_id, simulate_eink=True)
            self.assertTrue(len(out_b) > 0)
            style = get_eink_paper_preview_style(custom_id, simulate_eink=True)
            self.assertEqual(style["paper_bg"], "#E4E2DC")
        finally:
            IMAGE_DISPLAY_PROFILES.pop(custom_id, None)
            clear_preview_image_cache()

        # Inline custom_profile из пресета без регистрации в глобальном реестре
        inline = resolve_image_display_profile(
            "none",
            custom_profile={"mode": "grayscale", "optimize": {"gamma": 1.25}},
        )
        self.assertEqual(inline["mode"], "grayscale")
        self.assertEqual(inline["optimize"]["gamma"], 1.25)

    def test_optimize_fb2_binaries_and_converter_disables_fast_path(self):
        src_png = _make_color_gradient_png(32, 32)
        b64 = base64.b64encode(src_png).decode("ascii")
        fb2_xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">'
            '<description><title-info>'
            '<author><first-name>Иван</first-name><last-name>Тестов</last-name></author>'
            '<book-title>Книга</book-title>'
            '<coverpage><image l:href="#cover.png"/></coverpage>'
            '</title-info></description>'
            '<body><section><p>Текст</p></section></body>'
            f'<binary id="cover.png" content-type="image/png">{b64}</binary>'
            '</FictionBook>'
        ).encode("utf-8")

        opt_xml = optimize_fb2_binaries_for_profile(fb2_xml, "eink_bw")
        cov_bytes, cov_mime = extract_cover_from_fb2(opt_xml)
        self.assertEqual(cov_mime, "image/png")
        with Image.open(io.BytesIO(cov_bytes)) as im:
            self.assertEqual(im.mode, "L")

        # В convert_book_file при активном профиле исходник на диске не меняется, а fbc получает временный оптимизированный FB2
        with tempfile.TemporaryDirectory() as td:
            src_fb2 = os.path.join(td, "orig.fb2")
            out_dir = os.path.join(td, "out")
            os.makedirs(out_dir)
            with open(src_fb2, "wb") as fh:
                fh.write(fb2_xml)
            meta = parse_metadata(fb2_xml)
            data = {
                "path": src_fb2,
                "archive_entry": None,
                "display_name": "orig.fb2",
                "meta": dict(meta),
                "orig_meta": dict(meta),
                "cover_modified": False,
            }
            captured_input = []

            def _fake_fbc(cmd, cwd, cancel_event=None):
                captured_input.append(cmd[-2])
                ep = os.path.join(cmd[-1], "Out.epub")
                with zipfile.ZipFile(ep, "w") as zf:
                    zf.writestr("mimetype", "application/epub+zip")
                return "", ""

            with patch("core.fb2_processor._run_cancellable_process", side_effect=_fake_fbc):
                convert_book_file(
                    "fbc",
                    "config.yaml",
                    td,
                    data,
                    out_dir,
                    "epub3",
                    {},
                    image_color_profile="eink_bw",
                )
            self.assertNotEqual(captured_input[0], src_fb2)
            with open(src_fb2, "rb") as fh:
                self.assertEqual(fh.read(), fb2_xml)

    def test_preview_html_applies_profile_and_eink_simulation(self):
        src_png = _make_color_gradient_png(32, 32)
        b64 = base64.b64encode(src_png).decode("ascii")
        orig_uri = f"data:image/png;base64,{b64}"
        book_preview = {
            "title": "Тест",
            "author": "Автор",
            "series": "",
            "cover_data_uri": orig_uri,
            "blocks": [("p", "Первый абзац текста.")],
        }
        html_out = build_full_preview_html(
            get_default_css_ui_state(),
            {"para": "Georgia", "title": "Georgia", "author": "Georgia", "drop": "Georgia"},
            "vector",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts"),
            "FBC GUI",
            "2.11",
            "justify",
            "center",
            for_browser=True,
            book_preview=book_preview,
            image_color_profile="eink_kaleido3",
            simulate_eink=True,
        )
        # Обложка перекодирована через Pillow и добавлены E Ink стили подложки Kaleido 3
        self.assertNotIn(orig_uri, html_out)
        self.assertIn("#D8D7D2", html_out)

    def test_preview_simulate_eink_default_true_and_persists_user_disable(self):
        from core.config import get_default_app_settings, load_app_settings, save_app_settings

        defaults = get_default_app_settings()
        self.assertEqual(defaults["preview_simulate_eink"], "true")

        with tempfile.TemporaryDirectory() as td:
            sp = os.path.join(td, "settings.json")
            st = get_default_app_settings()
            st["preview_simulate_eink"] = "false"
            save_app_settings(sp, st)

            reloaded = get_default_app_settings()
            load_app_settings(sp, reloaded)
            self.assertEqual(reloaded["preview_simulate_eink"], "false")

    def test_display_color_palette_and_quantization_across_profiles(self):
        from core.image_optimizer import (
            EINK_BW_16_LEVELS,
            get_display_color_palette,
            quantize_hex_for_display_profile,
            simulate_hex_for_display_profile,
        )

        # 1. Ч/Б E Ink (eink_bw, eink_bw_16_dither, grayscale=True) -> ровно 16 градаций серого, без RGB-диалога
        for prof_id, gray in (("eink_bw", False), ("eink_bw_16_dither", False), ("none", True)):
            pal = get_display_color_palette(prof_id, grayscale=gray)
            self.assertEqual(pal["mode"], "grayscale")
            self.assertEqual(len(pal["swatches"]), 16)
            self.assertEqual(tuple(pal["swatches"]), EINK_BW_16_LEVELS)
            self.assertFalse(pal["allow_custom_dialog"])
            self.assertTrue(pal["monochrome_note_bg"])
            q = quantize_hex_for_display_profile("#ff0000", prof_id, grayscale=gray)
            self.assertIn(q, EINK_BW_16_LEVELS)
            sim = simulate_hex_for_display_profile("#000000", prof_id, grayscale=gray)
            self.assertNotEqual(sim, "#000000")  # black_floor > 0

        # 2. Kaleido 3 (4 бита на канал = 4096 цветов)
        pal_k3 = get_display_color_palette("eink_kaleido3")
        self.assertEqual(pal_k3["mode"], "color_eink")
        self.assertTrue(pal_k3["allow_custom_dialog"])
        self.assertFalse(pal_k3["monochrome_note_bg"])
        self.assertEqual(pal_k3["color_bits"], 4)
        for sw in pal_k3["swatches"]:
            self.assertEqual(sw, quantize_hex_for_display_profile(sw, "eink_kaleido3"))
        self.assertEqual(quantize_hex_for_display_profile("#12abef", "eink_kaleido3"), "#11aaee")

        # 3. Gallery 3 (5 бит на канал) и Full (none)
        pal_g3 = get_display_color_palette("eink_gallery3")
        self.assertEqual(pal_g3["mode"], "color_eink")
        self.assertEqual(pal_g3["color_bits"], 5)
        self.assertGreater(len(pal_g3["swatches"]), len(pal_k3["swatches"]))

        pal_full = get_display_color_palette("none", grayscale=False)
        self.assertEqual(pal_full["mode"], "full")
        self.assertEqual(pal_full["swatches"], [])
        self.assertFalse(pal_full["monochrome_note_bg"])

    def test_reader_palette_dialog_and_color_picker_sync_with_note_bg(self):
        from PyQt6.QtWidgets import QApplication
        from core.i18n import get_note_bg_options
        from core.image_optimizer import EINK_BW_16_LEVELS, get_display_color_palette
        from ui.widgets import ColorPickerWidget, ReaderPaletteDialog

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])

        # 1. Диалог Ч/Б E Ink: 16 плиток, слайдер активен, произвольный цвет квантуется в серый
        bw_pal = get_display_color_palette("eink_bw")
        dlg_bw = ReaderPaletteDialog("#ff0000", bw_pal)
        try:
            self.assertEqual(len(dlg_bw._swatch_buttons), 16)
            self.assertIsNotNone(dlg_bw._slider)
            self.assertIn(dlg_bw.selected_hex(), EINK_BW_16_LEVELS)
            dlg_bw._slider.setValue(0)
            self.assertEqual(dlg_bw.selected_hex(), "#000000")
        finally:
            dlg_bw.close()

        # 2. Диалог Kaleido 3: без слайдера серого, квантует в 4-битную сетку
        k3_pal = get_display_color_palette("eink_kaleido3")
        dlg_k3 = ReaderPaletteDialog("#12abef", k3_pal)
        try:
            self.assertIsNone(dlg_k3._slider)
            self.assertEqual(dlg_k3.selected_hex(), "#11aaee")
        finally:
            dlg_k3.close()

        # 3. ColorPickerWidget переключает список на Ч/Б, не затирая текущее значение
        picker = ColorPickerWidget(values=["red", "blue", "black"], default_color="red")
        picker.set_display_profile("eink_bw", grayscale=False)
        self.assertEqual(picker.get(), "red")
        items = [picker.combo.itemText(i) for i in range(picker.combo.count())]
        self.assertIn("black", items)
        self.assertIn("dimgray", items)
        self.assertNotIn("blue", items)

        # 4. get_note_bg_options(monochrome=True) возвращает только монохромные фоны сносок
        mono_bg_vals = [v for _, v in get_note_bg_options(monochrome=True)]
        self.assertEqual(mono_bg_vals, ["#f4f4f4", "#ffffff", "transparent"])
        app.processEvents()


if __name__ == "__main__":
    unittest.main()

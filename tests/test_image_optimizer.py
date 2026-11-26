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


if __name__ == "__main__":
    unittest.main()

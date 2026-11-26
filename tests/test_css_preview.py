import os
import tempfile
import unittest

from core.css_preview import (
    build_full_preview_html,
    generate_css_content,
    parse_css_file_to_state,
)


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR = os.path.join(PROJECT_ROOT, "fonts")


def _sample_state(**overrides):
    base = {
        "font_para": "PT-Astra-Serif_Regular.ttf",
        "font_drop": "PomorskyUnicode.otf",
        "font_title": "PT-Astra-Serif_Regular.ttf",
        "font_author": "PT-Astra-Serif_Regular.ttf",
        "pdf_frame": "0",
        "h1_sz": "160%",
        "h1_cl": "#8b0000",
        "h1_al": "center",
        "auth_sz": "130%",
        "auth_cl": "#222222",
        "auth_al": "center",
        "auth_style": "italic",
        "h2_sz": "135%",
        "h2_cl": "#111111",
        "h2_al": "center",
        "h3_sz": "120%",
        "h3_cl": "#222222",
        "h3_al": "center",
        "h4_sz": "110%",
        "h4_cl": "#333333",
        "h4_al": "left",
        "h5_sz": "105%",
        "h5_cl": "#444444",
        "h5_al": "left",
        "p_align": "justify",
        "text_indent": "1.5em",
        "sub_align": "center",
        "drop_color": "#8b0000",
        "drop_size": "320%",
        "anno_size": "90%",
        "anno_color": "#444444",
        "anno_align": "justify",
        "anno_style": "italic",
        "epi_size": "90%",
        "epi_color": "#555555",
        "epi_align": "right",
        "epi_style": "italic",
        "poem_size": "95%",
        "poem_color": "#333333",
        "poem_align": "left",
        "poem_style": "italic",
        "note_size": "85%",
        "note_color": "#222222",
        "note_bg": "#e6e6fa",
        "note_border": "1px #505050 solid",
        "note_style": "italic",
        "img_align": "center",
        "img_width": "90%",
        "img_cap_sz": "85%",
        "img_cap_cl": "#666666",
        "img_cap_st": "italic",
    }
    base.update(overrides)
    return base


class TestCssPreview(unittest.TestCase):
    def test_generate_and_parse_css_roundtrip(self):
        st = _sample_state(pdf_frame="2px", h1_sz="180%", text_indent="2em")
        css_text = generate_css_content(st, FONTS_DIR)
        self.assertIn('@font-face { font-family: "paragraph";', css_text)
        self.assertIn('-fbc-page-frame: 2px;', css_text)

        with tempfile.TemporaryDirectory() as td:
            css_path = os.path.join(td, "test.css")
            with open(css_path, "w", encoding="utf-8") as f:
                f.write(css_text)
            parsed = parse_css_file_to_state(css_path)

        self.assertEqual(parsed.get("pdf_frame"), "2px")
        self.assertEqual(parsed.get("h1_sz"), "180%")
        self.assertEqual(parsed.get("text_indent"), "2em")
        self.assertEqual(parsed.get("p_align"), "justify")
        self.assertEqual(parsed.get("font_drop"), "PomorskyUnicode.otf")

    def test_none_fonts_omit_font_face_rules(self):
        st = _sample_state(
            font_para="__none__",
            font_drop="__none__",
            font_title="__none__",
            font_author="__none__",
        )
        css_text = generate_css_content(st, FONTS_DIR)
        self.assertNotIn("@font-face", css_text)
        self.assertNotIn('font-family: "paragraph"', css_text)

    def test_build_full_preview_html_sample_and_book_modes(self):
        st = _sample_state()
        fams = {"para": "PT Astra Serif", "title": "PT Astra Serif", "author": "PT Astra Serif", "drop": "Pomorsky Unicode"}

        sample_html = build_full_preview_html(
            st, fams, "SVG", FONTS_DIR, "FBC GUI", "2.6", "По ширине", "По центру",
            for_browser=True, grayscale=True
        )
        self.assertIn("<!DOCTYPE html>", sample_html)
        self.assertIn("grayscale(100%)", sample_html)
        self.assertIn("@font-face", sample_html)

        book_data = {
            "author": "Лев Толстой",
            "title": "Война и мир",
            "series": "Классика #1",
            "cover_data_uri": "data:image/jpeg;base64,AAA",
            "annotation": ["Краткое описание."],
            "epigraph_lines": ["Эпиграф."],
            "epigraph_author": "Автор",
            "chapter_title": "Глава 1",
            "blocks": [("p", "Первый абзац текста."), ("p", "Второй абзац.")],
            "footnote_title": "1",
            "footnote_paras": ["Текст сноски."],
        }
        book_html = build_full_preview_html(
            st, fams, "SVG", FONTS_DIR, "FBC GUI", "2.8.3", "По ширине", "По центру",
            for_browser=False, grayscale=True, book_preview=book_data, dropcaps_enable=True,
            use_web_engine=True,
        )
        self.assertIn("Война и мир", book_html)
        self.assertIn("Глава 1", book_html)
        self.assertIn("Текст сноски.", book_html)
        self.assertIn("book-spread", book_html)
        self.assertIn("cover-page", book_html)
        self.assertIn("title-page", book_html)
        self.assertIn("column-count: 2", book_html)
        self.assertIn("object-fit: cover;", book_html)
        self.assertIn("padding: 0;", book_html)

    def test_preview_isolates_same_family_font_variants(self):
        """Разные файлы одного семейства (Newton15/Bo/It) не должны перезаписывать друг друга в превью."""
        st = _sample_state(
            font_para="Newton15.ttf",
            font_title="Newton15Bo.ttf",
            font_author="Newton15It.ttf",
            font_drop="Lombardina-Initial-One.ttf",
            auth_style="italic",
            anno_style="normal",
        )
        # Qt возвращает одинаковое имя семейства для всех трёх начертаний Newton15
        fams = {
            "para": "Newton15",
            "title": "Newton15",
            "author": "Newton15",
            "drop": "Lombardina Initial One",
        }
        html_out = build_full_preview_html(
            st, fams, "SVG", FONTS_DIR, "FBC GUI", "2.8.3", "По ширине", "По центру",
            for_browser=False, use_web_engine=True,
        )
        self.assertIn('@font-face { font-family: "fbc-para"; src: url("file://', html_out)
        self.assertIn('Newton15.ttf"); font-weight: normal; font-style: normal; }', html_out)
        self.assertIn('@font-face { font-family: "fbc-title"; src: url("file://', html_out)
        self.assertIn('Newton15Bo.ttf"); font-weight: bold; font-style: normal; }', html_out)
        self.assertIn('@font-face { font-family: "fbc-author"; src: url("file://', html_out)
        self.assertIn('Newton15It.ttf"); font-weight: normal; font-style: italic; }', html_out)
        # Курсивный файл автора не должен быть назначен как normal/normal для fbc-para
        self.assertNotIn('font-family: "fbc-para"; src: url("file://' + FONTS_DIR.replace("\\", "/") + '/Newton15It.ttf"); font-weight: normal; font-style: normal;', html_out)

    def test_preview_sanitizes_malicious_cover_mime_and_uri(self):
        from core.fb2_processor import extract_book_preview_data

        fb2_xml = b'<?xml version="1.0" encoding="utf-8"?><FictionBook><description><title-info><book-title>Test</book-title></title-info></description><body><section><p>Hello</p></section></body></FictionBook>'
        preview_data = extract_book_preview_data(
            fb2_xml,
            cover_bytes=b"\xff\xd8\xff",
            cover_mime='image/jpeg" onload="alert(1)',
        )
        self.assertTrue(preview_data["cover_data_uri"].startswith("data:image/jpeg;base64,"))
        self.assertNotIn("onload", preview_data["cover_data_uri"])

        st = _sample_state()
        fams = {"para": "PT Astra Serif", "title": "PT Astra Serif", "author": "PT Astra Serif", "drop": "Pomorsky Unicode"}
        injected_data = dict(preview_data, cover_data_uri='data:image/jpeg;base64,AAA" onerror="alert(1)')
        html_out = build_full_preview_html(
            st, fams, "SVG", FONTS_DIR, "FBC GUI", "2.9", "По ширине", "По центру",
            for_browser=True, book_preview=injected_data,
        )
        self.assertNotIn('" onerror="alert(1)', html_out)
        self.assertIn("&quot; onerror=&quot;alert(1)", html_out)

    def test_preview_font_uri_encodes_spaces_and_page_number_is_2(self):
        with tempfile.TemporaryDirectory() as td:
            spaced_dir = os.path.join(td, "My Fonts #1")
            os.makedirs(spaced_dir, exist_ok=True)
            font_path = os.path.join(spaced_dir, "My Font.ttf")
            with open(font_path, "wb") as fh:
                fh.write(b"TTF")

            st = _sample_state(
                font_para="My Font.ttf",
                font_title="My Font.ttf",
                font_author="My Font.ttf",
                font_drop="__none__",
            )
            fams = {"para": "My Font", "title": "My Font", "author": "My Font", "drop": ""}
            book_data = {
                "author": "Автор",
                "title": "Книга",
                "series": "",
                "cover_data_uri": "data:image/jpeg;base64,AAA",
                "annotation": [],
                "epigraph_lines": [],
                "epigraph_author": "",
                "chapter_title": "Глава 1",
                "blocks": [("p", "Текст.")],
                "footnote_title": "",
                "footnote_paras": [],
            }
            html_out = build_full_preview_html(
                st, fams, "SVG", spaced_dir, "FBC GUI", "2.9.1", "По ширине", "По центру",
                for_browser=False, book_preview=book_data, use_web_engine=True,
            )
            self.assertIn("My%20Fonts%20%231/My%20Font.ttf", html_out)
            self.assertIn('<div class="page-num">2</div>', html_out)
            self.assertNotIn('<div class="page-num">1</div>', html_out)

    def test_install_user_fonts_validates_and_copies(self):
        from core.css_preview import install_user_fonts, is_valid_font_file

        with tempfile.TemporaryDirectory() as td:
            src_dir = os.path.join(td, "src")
            dst_dir = os.path.join(td, "fonts")
            os.makedirs(src_dir, exist_ok=True)

            good_ttf = os.path.join(src_dir, "Good.ttf")
            good_otf = os.path.join(src_dir, "Good.otf")
            bad_magic = os.path.join(src_dir, "Corrupt.ttf")
            bad_ext = os.path.join(src_dir, "Notes.txt")

            with open(good_ttf, "wb") as fh:
                fh.write(b"\x00\x01\x00\x00" + b"\x00" * 16)
            with open(good_otf, "wb") as fh:
                fh.write(b"OTTO" + b"\x00" * 16)
            with open(bad_magic, "wb") as fh:
                fh.write(b"NOTAFONT1234")
            with open(bad_ext, "wb") as fh:
                fh.write(b"\x00\x01\x00\x00" + b"\x00" * 16)

            self.assertTrue(is_valid_font_file(good_ttf))
            self.assertTrue(is_valid_font_file(good_otf))
            self.assertFalse(is_valid_font_file(bad_magic))
            self.assertFalse(is_valid_font_file(bad_ext))

            installed, errors = install_user_fonts([good_ttf, good_otf, bad_magic, bad_ext], dst_dir)
            self.assertEqual(installed, ["Good.ttf", "Good.otf"])
            self.assertEqual([name for name, _ in errors], ["Corrupt.ttf", "Notes.txt"])
            self.assertTrue(os.path.isfile(os.path.join(dst_dir, "Good.ttf")))
            self.assertTrue(os.path.isfile(os.path.join(dst_dir, "Good.otf")))
            self.assertFalse(os.path.exists(os.path.join(dst_dir, "Corrupt.ttf")))


    def test_css_and_preview_sanitization_strips_unsafe_tokens(self):
        from core.css_preview import DEFAULT_CSS_UI_STATE, build_full_preview_html, generate_css_content

        unsafe_state = dict(DEFAULT_CSS_UI_STATE)
        unsafe_state["h1_cl"] = "red; } <bad>"
        unsafe_state["note_bg"] = "url(https://untrusted.example/bg.png)"
        unsafe_state["font_para"] = "../parent/custom.ttf\"; }"

        with tempfile.TemporaryDirectory() as td:
            css = generate_css_content(unsafe_state, td)
            self.assertNotIn("<bad>", css)
            self.assertNotIn("untrusted.example", css)
            self.assertNotIn("../", css)

            html_doc = build_full_preview_html(
                unsafe_state,
                {"para": "Georgia", "title": "Georgia", "author": "Georgia", "drop": "Georgia"},
                "SVG",
                td,
                "FBC GUI",
                "2.10",
                "justify",
                "center",
                for_browser=True,
            )
            self.assertNotIn("<bad>", html_doc)
            self.assertNotIn("untrusted.example", html_doc)
            self.assertIn("Content-Security-Policy", html_doc)
            self.assertIn("default-src 'none'", html_doc)

    def test_native_webview_isolated_preview_staging_excludes_non_fonts(self):
        from pathlib import Path
        from ui.native_webview import _stage_isolated_preview

        with tempfile.TemporaryDirectory() as base_dir, tempfile.TemporaryDirectory() as temp_dir:
            fonts_dir = os.path.join(base_dir, "fonts")
            os.makedirs(fonts_dir, exist_ok=True)
            with open(os.path.join(base_dir, "settings.json"), "w", encoding="utf-8") as fh:
                fh.write('{"secret": "do_not_expose"}')
            with open(os.path.join(fonts_dir, "TestFont.ttf"), "wb") as fh:
                fh.write(b"\x00\x01\x00\x00FONT")
            with open(os.path.join(fonts_dir, "readme.txt"), "w", encoding="utf-8") as fh:
                fh.write("ignore")

            src_uri = Path(fonts_dir).resolve().as_uri().rstrip("/")
            html_in = f'<style>@font-face {{ src: url("{src_uri}/TestFont.ttf"); }}</style>'
            render_path, read_root = _stage_isolated_preview(temp_dir, html_in, base_dir)

            self.assertEqual(read_root, temp_dir)
            self.assertTrue(os.path.isfile(render_path))
            self.assertFalse(os.path.exists(os.path.join(base_dir, ".preview_render.html")))
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "settings.json")))
            self.assertTrue(os.path.isfile(os.path.join(temp_dir, "fonts", "TestFont.ttf")))
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "fonts", "readme.txt")))
            with open(render_path, "r", encoding="utf-8") as fh:
                staged = fh.read()
            self.assertNotIn(src_uri, staged)
            self.assertIn(Path(os.path.join(temp_dir, "fonts")).resolve().as_uri().rstrip("/"), staged)


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

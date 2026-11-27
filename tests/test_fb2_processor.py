import base64
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from core.fb2_processor import (
    ConversionCancelledError,
    _parse_fb2_root,
    DEFAULT_FILENAME_TOKENS,
    DEFAULT_TITLE_TOKENS,
    _run_cancellable_process,
    book_matches_filter,
    build_fbc_output_name_template,
    collect_book_paths,
    collect_startup_paths,
    convert_book_file,
    extract_all_fb2_from_file,
    extract_cover_from_fb2,
    get_book_xml,
    iter_fb2_from_file,
    load_book_xml,
    parse_metadata,
    patch_html_title_elements,
    render_filename_from_tokens,
    render_title_metadata_preview,
    save_book_changes_to_source,
    simulate_fbc_target,
    update_fb2_xml,
)


FAKE_JPG = b"\xff\xd8\xff\xe0FAKEJPEGDATA"
FAKE_JPG_B64 = base64.b64encode(FAKE_JPG).decode("ascii")

VALID_FB2 = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
    'xmlns:l="http://www.w3.org/1999/xlink">'
    "<description><title-info>"
    "<author><first-name>Лев</first-name><middle-name>Николаевич</middle-name><last-name>Толстой</last-name></author>"
    "<book-title>Война и мир</book-title>"
    '<sequence name="Русская классика" number="2"/>'
    '<coverpage><image l:href="#cover.jpg"/></coverpage>'
    "</title-info></description>"
    "<body><title><p>Лев Толстой</p><p>Война и мир</p></title><section><p>Текст.</p></section></body>"
    f'<binary id="cover.jpg" content-type="image/jpeg">{FAKE_JPG_B64}</binary>'
    "</FictionBook>"
).encode("utf-8")


class TestFb2Processor(unittest.TestCase):
    def test_collect_book_paths_filters_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "sub"))
            os.makedirs(os.path.join(td, "__MACOSX"))
            os.makedirs(os.path.join(td, ".hidden"))
            p1 = os.path.join(td, "a.fb2")
            p2 = os.path.join(td, "sub", "b.zip")
            for p in (
                p1,
                p2,
                os.path.join(td, "._a.fb2"),
                os.path.join(td, "__MACOSX", "x.fb2"),
                os.path.join(td, ".hidden", "h.fb2"),
                os.path.join(td, "readme.txt"),
            ):
                with open(p, "wb") as fh:
                    fh.write(b"x")

            found = collect_book_paths([td, p1])
            self.assertEqual([os.path.abspath(p) for p in found], [os.path.abspath(p1), os.path.abspath(p2)])

    def test_extract_all_fb2_from_multibook_zip(self):
        with tempfile.TemporaryDirectory() as td:
            zp = os.path.join(td, "pack.zip")
            with zipfile.ZipFile(zp, "w") as z:
                z.writestr("book1.fb2", VALID_FB2)
                z.writestr("nested/book2.fb2", VALID_FB2)
                z.writestr("__MACOSX/._book1.fb2", b"junk")
                z.writestr("notes.txt", b"text")

            entries = extract_all_fb2_from_file(zp)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0][1], "pack.zip / book1.fb2")
            self.assertEqual(entries[1][1], "pack.zip / book2.fb2")

    def test_parse_metadata_and_cover_valid(self):
        meta = parse_metadata(VALID_FB2)
        self.assertEqual(meta["last"], "Толстой")
        self.assertEqual(meta["first"], "Лев")
        self.assertEqual(meta["mid"], "Николаевич")
        self.assertEqual(meta["series"], "Русская классика")
        self.assertEqual(meta["num"], "2")
        self.assertEqual(meta["title"], "Война и мир")

        cov, mime = extract_cover_from_fb2(VALID_FB2)
        self.assertEqual(cov, FAKE_JPG)
        self.assertEqual(mime, "image/jpeg")

    def test_broken_fb2_bare_amp_bom_control_char_missing_xmlns_l(self):
        broken = (
            b'\xef\xbb\xbf<?xml version="1.0" encoding="utf-8"?>'
            b'<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            b"<description><title-info>"
            b"<author><first-name>A</first-name><last-name>B & C</last-name></author>"
            b"<book-title>Rock & Roll\x07</book-title>"
            b'<sequence name="Hits & Classics" number="3"/>'
            b'<coverpage><image l:href="#c1.jpg"/></coverpage>'
            b"</title-info></description><body><p>Body & text</p></body>"
            b'<binary id="c1.jpg" content-type="image/jpeg">' + FAKE_JPG_B64.encode() + b"</binary>"
            b"</FictionBook>"
        )
        meta = parse_metadata(broken)
        self.assertEqual(meta["title"], "Rock & Roll")
        self.assertEqual(meta["last"], "B & C")
        self.assertEqual(meta["series"], "Hits & Classics")
        self.assertEqual(meta["num"], "3")

        cov, mime = extract_cover_from_fb2(broken)
        self.assertEqual(cov, FAKE_JPG)
        self.assertEqual(mime, "image/jpeg")

    def test_broken_fb2_windows_1251_without_namespace(self):
        cp1251 = (
            '<?xml version="1.0" encoding="windows-1251"?>'
            "<FictionBook><description><title-info>"
            "<author><first-name>Иван</first-name><last-name>Иванов</last-name></author>"
            "<book-title>Сказки & Были</book-title>"
            "</title-info></description><body><p>Текст</p></body></FictionBook>"
        ).encode("windows-1251")

        meta = parse_metadata(cp1251)
        self.assertEqual(meta["title"], "Сказки & Были")
        self.assertEqual(meta["last"], "Иванов")

        updated = update_fb2_xml(cp1251, {**meta, "title": "Новое название"})
        self.assertIn("Новое название".encode("utf-8"), updated)

    def test_broken_fb2_unclosed_body_fallback_does_not_crash(self):
        broken_body = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">'
            b"<description><title-info>"
            b"<author><first-name>Ivan</first-name><last-name>Petrov</last-name></author>"
            b"<book-title>Broken & Book</book-title>"
            b'<sequence name="Test Series" number="5"/>'
            b'<coverpage><image l:href="#cover.jpg"/></coverpage>'
            b"</title-info></description>"
            b"<body><section><p>Unclosed<section></body>"
            b'<binary id="cover.jpg" content-type="image/jpeg">' + FAKE_JPG_B64.encode() + b"</binary>"
            b"</FictionBook>"
        )
        meta = parse_metadata(broken_body)
        self.assertEqual(meta["title"], "Broken & Book")
        self.assertEqual(meta["series"], "Test Series")
        self.assertEqual(meta["num"], "5")

        cov, _ = extract_cover_from_fb2(broken_body)
        self.assertEqual(cov, FAKE_JPG)

        out = update_fb2_xml(broken_body, meta)
        self.assertIsInstance(out, bytes)
        self.assertGreater(len(out), 0)

    def test_update_fb2_xml_updates_meta_and_cover(self):
        new_meta = {
            "first": "Фёдор",
            "last": "Достоевский",
            "mid": "",
            "series": "",
            "num": "",
            "title": "Идиот",
        }
        new_cov = b"\xff\xd8\xff\xe0NEWCOVER"
        updated = update_fb2_xml(VALID_FB2, new_meta, cover_bytes=new_cov, cover_mime="image/jpeg", cover_modified=True)
        parsed = parse_metadata(updated)
        self.assertEqual(parsed["last"], "Достоевский")
        self.assertEqual(parsed["title"], "Идиот")
        self.assertEqual(parsed["series"], "")
        cov, _ = extract_cover_from_fb2(updated)
        self.assertEqual(cov, new_cov)

    def test_filename_rendering_and_go_template(self):
        meta_full = {"last": "Толстой", "first": "Лев", "mid": "", "series": "Война и мир", "num": "1", "title": "Том 1/2"}
        self.assertEqual(
            render_filename_from_tokens(DEFAULT_FILENAME_TOKENS, meta_full, "epub3"),
            "Толстой - (ВИМ-01) - Том 1\u22152",
        )
        meta_no_series = {**meta_full, "series": "", "num": ""}
        self.assertEqual(
            render_filename_from_tokens(DEFAULT_FILENAME_TOKENS, meta_no_series, "epub3"),
            "Толстой - Том 1\u22152",
        )
        self.assertEqual(
            simulate_fbc_target(meta_full, "kepub3", "default"),
            "Толстой - (ВИМ-01) - Том 1\u22152.kepub.epub",
        )

        tpl = build_fbc_output_name_template(DEFAULT_FILENAME_TOKENS)
        self.assertEqual(tpl.count('replace "\\\\" "\u2215"'), 2)

        title_preview = render_title_metadata_preview(DEFAULT_TITLE_TOKENS, meta_full)
        self.assertEqual(title_preview, "(ВИМ - 01) Том 1/2")
        title_tpl = build_fbc_output_name_template(DEFAULT_TITLE_TOKENS, for_metadata_title=True)
        self.assertIn("{{- $title := .Title -}}", title_tpl)
        self.assertNotIn("\u2215", title_tpl)

    def test_patch_html_title_elements(self):
        html_two = '<p class="body-title-header">Author</p><h1 class="body-title-header">Book</h1>'
        patched = patch_html_title_elements(html_two, "color: green;", "color: red;")
        self.assertIn("book-author", patched)
        self.assertIn("book-title", patched)

        html_one = '<div class="wrap"><p class="body-title-header">Author<br/>Book</p></div>'
        patched_one = patch_html_title_elements(html_one, "color: green;", "color: red;")
        self.assertIn("book-author", patched_one)
        self.assertIn("book-title", patched_one)

    def test_lazy_xml_loading_plain_and_multibook_zip(self):
        with tempfile.TemporaryDirectory() as td:
            fb2_path = os.path.join(td, "single.fb2")
            with open(fb2_path, "wb") as fh:
                fh.write(VALID_FB2)

            plain_entries = list(iter_fb2_from_file(fb2_path))
            self.assertEqual(len(plain_entries), 1)
            self.assertIsNone(plain_entries[0][1])
            self.assertEqual(load_book_xml(fb2_path, None), VALID_FB2)
            self.assertEqual(get_book_xml({"path": fb2_path, "archive_entry": None}), VALID_FB2)

            zp = os.path.join(td, "multi.zip")
            alt_fb2 = VALID_FB2.replace("Война и мир".encode("utf-8"), "Анна Каренина".encode("utf-8"))
            with zipfile.ZipFile(zp, "w") as z:
                z.writestr("first.fb2", VALID_FB2)
                z.writestr("sub/second.fb2", alt_fb2)

            zip_entries = list(iter_fb2_from_file(zp))
            self.assertEqual(len(zip_entries), 2)
            self.assertEqual(zip_entries[0][1], "first.fb2")
            self.assertEqual(zip_entries[1][1], "sub/second.fb2")
            self.assertEqual(get_book_xml({"path": zp, "archive_entry": "sub/second.fb2"}), alt_fb2)
            self.assertEqual(get_book_xml({"path": "/nonexistent", "xml": b"cached"}), b"cached")

    def test_cancellable_process_terminates_immediately(self):
        cancel_ev = threading.Event()
        timer = threading.Timer(0.2, cancel_ev.set)
        timer.start()
        t0 = time.monotonic()
        try:
            with self.assertRaises(ConversionCancelledError):
                _run_cancellable_process(
                    [sys.executable, "-c", "import time; time.sleep(10)"],
                    cwd=tempfile.gettempdir(),
                    cancel_event=cancel_ev,
                )
        finally:
            timer.cancel()
        self.assertLess(time.monotonic() - t0, 3.0)

    def test_convert_book_file_respects_preset_cancel_event(self):
        cancel_ev = threading.Event()
        cancel_ev.set()
        with self.assertRaises(ConversionCancelledError):
            convert_book_file(
                "/nonexistent/fbc",
                "/nonexistent/config.yaml",
                tempfile.gettempdir(),
                {"path": "/nonexistent/book.fb2", "meta": {"title": "Test"}},
                tempfile.gettempdir(),
                "epub3",
                {},
                cancel_event=cancel_ev,
            )

    def test_collect_startup_paths_filters_flags_and_handles_file_urls(self):
        with tempfile.TemporaryDirectory() as td:
            fb2 = os.path.join(td, "book.fb2")
            txt = os.path.join(td, "notes.txt")
            with open(fb2, "wb") as fh:
                fh.write(VALID_FB2)
            with open(txt, "wb") as fh:
                fh.write(b"hi")

            argv = [
                "fbc_gui.py",
                "-psn_0_12345",
                "--debug",
                fb2,
                f"file://{fb2}",
                txt,
                os.path.join(td, "missing.fb2"),
                td,
            ]
            found = collect_startup_paths(argv)
            self.assertEqual([os.path.abspath(p) for p in found], [os.path.abspath(fb2), os.path.abspath(td)])

    def test_save_book_changes_to_source_fb2_and_multibook_zip(self):
        with tempfile.TemporaryDirectory() as td:
            # 1. Plain .fb2
            fb2_path = os.path.join(td, "orig.fb2")
            with open(fb2_path, "wb") as fh:
                fh.write(VALID_FB2)
            new_cov = b"\xff\xd8\xff\xe0SAVEDCOVER"
            data_fb2 = {
                "path": fb2_path,
                "archive_entry": None,
                "meta": {
                    "first": "Антон",
                    "last": "Чехов",
                    "mid": "Павлович",
                    "series": "Избранное",
                    "num": "7",
                    "title": "Вишнёвый сад",
                },
                "cover_bytes": new_cov,
                "cover_mime": "image/jpeg",
                "cover_modified": True,
            }
            save_book_changes_to_source(data_fb2)
            self.assertFalse(data_fb2["cover_modified"])
            reloaded = load_book_xml(fb2_path)
            self.assertEqual(parse_metadata(reloaded)["title"], "Вишнёвый сад")
            self.assertEqual(parse_metadata(reloaded)["last"], "Чехов")
            self.assertEqual(extract_cover_from_fb2(reloaded)[0], new_cov)

            # 2. Multi-book .zip (only targeted entry updated, sibling preserved)
            zp = os.path.join(td, "bundle.zip")
            sibling_fb2 = VALID_FB2.replace("Война и мир".encode("utf-8"), "Соседняя книга".encode("utf-8"))
            with zipfile.ZipFile(zp, "w") as z:
                z.writestr("book_a.fb2", VALID_FB2)
                z.writestr("book_b.fb2", sibling_fb2)

            data_zip = {
                "path": zp,
                "archive_entry": "book_a.fb2",
                "meta": {
                    "first": "Лев",
                    "last": "Толстой",
                    "mid": "Николаевич",
                    "series": "Классика",
                    "num": "9",
                    "title": "Обновлённая книга",
                },
                "cover_bytes": FAKE_JPG,
                "cover_mime": "image/jpeg",
                "cover_modified": False,
            }
            save_book_changes_to_source(data_zip)
            self.assertEqual(parse_metadata(load_book_xml(zp, "book_a.fb2"))["title"], "Обновлённая книга")
            self.assertEqual(parse_metadata(load_book_xml(zp, "book_b.fb2"))["title"], "Соседняя книга")

    def test_book_matches_filter(self):
        book_pending = {
            "path": "/tmp/tolstoy_war.fb2",
            "display_name": "tolstoy_war.fb2",
            "meta": {
                "last": "Толстой",
                "first": "Лев",
                "mid": "Николаевич",
                "series": "Русская классика",
                "num": "2",
                "title": "Война и мир",
            },
            "status": "",
        }
        book_ok = {
            "path": "/tmp/pack.zip",
            "display_name": "pack.zip / idiot.fb2",
            "meta": {
                "last": "Достоевский",
                "first": "Фёдор",
                "mid": "",
                "series": "",
                "num": "",
                "title": "Идиот",
            },
            "status": "ok",
        }
        book_err = {
            "path": "/tmp/broken.fb2",
            "display_name": "broken.fb2",
            "meta": {
                "last": "Чехов",
                "first": "Антон",
                "mid": "",
                "series": "Рассказы",
                "num": "1",
                "title": "Каштанка",
            },
            "status": "error",
        }

        self.assertTrue(book_matches_filter(book_pending, "", "all"))
        self.assertTrue(book_matches_filter(book_pending, "", "pending"))
        self.assertFalse(book_matches_filter(book_pending, "", "ok"))
        self.assertFalse(book_matches_filter(book_pending, "", "error"))

        self.assertTrue(book_matches_filter(book_ok, "", "ok"))
        self.assertFalse(book_matches_filter(book_ok, "", "pending"))
        self.assertTrue(book_matches_filter(book_err, "", "error"))
        self.assertFalse(book_matches_filter(book_err, "", "pending"))
        self.assertTrue(book_matches_filter({**book_pending, "status": "cancelled"}, "", "pending"))

        self.assertTrue(book_matches_filter(book_pending, "толстой мир", "all"))
        self.assertTrue(book_matches_filter(book_pending, "КЛАССИКА 2", "pending"))
        self.assertTrue(book_matches_filter(book_ok, "pack.zip идиот", "ok"))
        self.assertTrue(book_matches_filter(book_err, "kashtanka.kepub", "error", target_name="Kashtanka.kepub.epub"))
        self.assertFalse(book_matches_filter(book_pending, "толстой чехов", "all"))
        self.assertFalse(book_matches_filter(book_ok, "толстой", "ok"))

    def test_convert_book_file_embeds_fonts_from_base_dir(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fbc_bin = os.path.join(project_root, "fbc.exe" if os.name == "nt" else "fbc")
        fbc_cfg = os.path.join(project_root, "config.yaml")
        fonts_dir = os.path.join(project_root, "fonts")
        if not (os.path.isfile(fbc_bin) and os.path.isfile(fbc_cfg) and os.path.isdir(fonts_dir)):
            self.skipTest("fbc binary, config.yaml, or fonts directory not available")

        with tempfile.TemporaryDirectory() as td:
            fb2_path = os.path.join(td, "font_check.fb2")
            out_dir = os.path.join(td, "out")
            with open(fb2_path, "wb") as fh:
                fh.write(VALID_FB2)

            data = {
                "path": fb2_path,
                "display_name": "font_check.fb2",
                "meta": parse_metadata(VALID_FB2),
            }
            title_style_params = {
                "h1_sz": "150%", "h1_cl": "red", "h1_al": "center",
                "auth_sz": "110%", "auth_cl": "green", "auth_al": "center", "auth_style": "italic",
            }
            created = convert_book_file(
                fbc_bin, fbc_cfg, project_root, data, out_dir, "epub3", title_style_params
            )
            self.assertEqual(len(created), 1)
            with zipfile.ZipFile(created[0], "r") as z:
                names = z.namelist()
                embedded_fonts = [n for n in names if n.lower().endswith((".ttf", ".otf", ".woff", ".woff2"))]
                self.assertGreater(len(embedded_fonts), 0, f"No fonts embedded in EPUB: {names}")
                self.assertTrue(any("PomorskyUnicode.otf" in n for n in embedded_fonts))
                self.assertTrue(any("PT-Astra-Serif_Regular.ttf" in n for n in embedded_fonts))
                opf = z.read("OEBPS/content.opf").decode("utf-8")
                for fp in embedded_fonts:
                    self.assertIn(os.path.basename(fp), opf)

    def test_custom_filename_and_title_templates_parse_and_render_in_fbc(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fbc_bin = os.path.join(project_root, "fbc.exe" if os.name == "nt" else "fbc")
        if not os.path.isfile(fbc_bin):
            self.skipTest("fbc binary not available")

        out_tpl = build_fbc_output_name_template(DEFAULT_FILENAME_TOKENS)
        title_tpl = build_fbc_output_name_template(DEFAULT_TITLE_TOKENS, for_metadata_title=True)
        for tpl in (out_tpl, title_tpl):
            self.assertNotIn("-}{", tpl)
            self.assertEqual(tpl.count("{{"), tpl.count("}}"))

        with tempfile.TemporaryDirectory() as td:
            cfg_path = os.path.join(td, "config.yaml")
            fb2_path = os.path.join(td, "random_input_123.fb2")
            out_dir = os.path.join(td, "out")
            indented_out = "\n".join("    " + line for line in out_tpl.splitlines())
            indented_title = "\n".join("      " + line for line in title_tpl.splitlines())
            with open(cfg_path, "w", encoding="utf-8") as cf:
                cf.write(
                    "version: 1\n"
                    "document:\n"
                    "  output_name_template: |\n"
                    f"{indented_out}\n"
                    "  metainformation:\n"
                    "    title_template: |\n"
                    f"{indented_title}\n"
                )
            with open(fb2_path, "wb") as fh:
                fh.write(VALID_FB2)

            data = {
                "path": fb2_path,
                "display_name": "random_input_123.fb2",
                "meta": parse_metadata(VALID_FB2),
            }
            title_style_params = {
                "h1_sz": "150%", "h1_cl": "red", "h1_al": "center",
                "auth_sz": "110%", "auth_cl": "green", "auth_al": "center", "auth_style": "italic",
            }
            created = convert_book_file(
                fbc_bin, cfg_path, project_root, data, out_dir, "epub3", title_style_params
            )
            self.assertEqual(len(created), 1)
            self.assertEqual(os.path.basename(created[0]), "Толстой - (РК-02) - Война и мир.epub")
            with zipfile.ZipFile(created[0], "r") as z:
                opf = z.read("OEBPS/content.opf").decode("utf-8")
                self.assertIn("(РК - 02) Война и мир", opf)

            # Проверка книги без серии: двойной разделитель «-» не должен дублироваться
            fb2_no_ser = os.path.join(td, "no_series.fb2")
            xml_no_ser = VALID_FB2.replace('<sequence name="Русская классика" number="2"/>'.encode("utf-8"), b"")
            with open(fb2_no_ser, "wb") as fh:
                fh.write(xml_no_ser)
            out_dir_ns = os.path.join(td, "out_ns")
            created_ns = convert_book_file(
                fbc_bin,
                cfg_path,
                project_root,
                {"path": fb2_no_ser, "display_name": "no_series.fb2", "meta": parse_metadata(xml_no_ser)},
                out_dir_ns,
                "epub3",
                title_style_params,
            )
            self.assertEqual(len(created_ns), 1)
            self.assertEqual(os.path.basename(created_ns[0]), "Толстой - Война и мир.epub")

    def test_parse_fb2_root_hardens_lxml_parser_flags(self):
        broken_xml = b"<FictionBook><body><p>unclosed"
        fake_lxml = MagicMock()
        fake_lxml.fromstring.return_value = MagicMock()
        fake_lxml.tostring.return_value = b"<FictionBook/>"

        with patch("core.fb2_processor.HAS_LXML", True), patch("core.fb2_processor.LXML_ET", fake_lxml):
            root = _parse_fb2_root(broken_xml)

        self.assertIsNotNone(root)
        fake_lxml.XMLParser.assert_called_once_with(
            recover=True,
            resolve_entities=False,
            no_network=True,
            huge_tree=False,
        )

    def test_update_fb2_xml_creates_missing_title_clears_body_children_and_cleans_old_cover(self):
        src_fb2 = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
            'xmlns:l="http://www.w3.org/1999/xlink">'
            "<description><title-info>"
            "<author><first-name>Иван</first-name><last-name>Петров</last-name></author>"
            '<coverpage><image l:href="#cover.jpg"/></coverpage>'
            "</title-info></description>"
            "<body><title><p>Иван Петров</p><p>Старое <strong>название</strong></p></title>"
            "<section><p>Текст.</p></section></body>"
            f'<binary id="cover.jpg" content-type="image/jpeg">{FAKE_JPG_B64}</binary>'
            "</FictionBook>"
        ).encode("utf-8")
        fake_png = b"\x89PNG\r\n\x1a\nFAKEPNG"
        updated = update_fb2_xml(
            src_fb2,
            {"first": "Иван", "last": "Петров", "mid": "", "series": "", "num": "", "title": "Новое название"},
            cover_bytes=fake_png,
            cover_mime="image/png",
            cover_modified=True,
        )
        self.assertEqual(parse_metadata(updated)["title"], "Новое название")
        cov_bytes, cov_mime = extract_cover_from_fb2(updated)
        self.assertEqual(cov_bytes, fake_png)
        self.assertEqual(cov_mime, "image/png")
        text = updated.decode("utf-8")
        self.assertIn('id="cover.png"', text)
        self.assertNotIn('id="cover.jpg"', text)
        self.assertNotIn("<strong>", text)

    def test_convert_book_file_disambiguates_same_batch_collisions(self):
        with tempfile.TemporaryDirectory() as td:
            fb2_path = os.path.join(td, "book.fb2")
            out_dir = os.path.join(td, "out")
            with open(fb2_path, "wb") as fh:
                fh.write(VALID_FB2)

            def _fake_fbc(cmd, cwd, cancel_event=None):
                tmp_out_dir = cmd[-1]
                ep = os.path.join(tmp_out_dir, "Duplicate.kepub.epub")
                with zipfile.ZipFile(ep, "w") as z:
                    z.writestr("mimetype", "application/epub+zip")
                return "", ""

            data = {"path": fb2_path, "display_name": "book.fb2", "meta": parse_metadata(VALID_FB2)}
            style_params = {
                "h1_sz": "150%", "h1_cl": "red", "h1_al": "center",
                "auth_sz": "110%", "auth_cl": "green", "auth_al": "center", "auth_style": "italic",
            }
            claimed = set()
            with patch("core.fb2_processor._run_cancellable_process", side_effect=_fake_fbc):
                first = convert_book_file(
                    "fbc", "config.yaml", td, data, out_dir, "kepub3", style_params, claimed_outputs=claimed
                )
                second = convert_book_file(
                    "fbc", "config.yaml", td, data, out_dir, "kepub3", style_params, claimed_outputs=claimed
                )

            self.assertEqual(os.path.basename(first[0]), "Duplicate.kepub.epub")
            self.assertEqual(os.path.basename(second[0]), "Duplicate (2).kepub.epub")
            self.assertTrue(os.path.isfile(first[0]))
            self.assertTrue(os.path.isfile(second[0]))

    def test_graceful_degradation_without_pil_and_lxml(self):
        from core.fb2_processor import fit_image_to_cover_size

        with tempfile.TemporaryDirectory() as td:
            for fname, expected_mime in (
                ("raw.jpg", "image/jpeg"),
                ("raw.png", "image/png"),
                ("raw.webp", "image/webp"),
                ("raw.gif", "image/gif"),
            ):
                img_path = os.path.join(td, fname)
                with open(img_path, "wb") as fh:
                    fh.write(FAKE_JPG)
                with patch("core.fb2_processor.HAS_PIL", False):
                    raw_bytes, mime = fit_image_to_cover_size(img_path)
                self.assertEqual(raw_bytes, FAKE_JPG)
                self.assertEqual(mime, expected_mime)

        bare_amp = VALID_FB2.replace("Война и мир".encode("utf-8"), "Война & мир".encode("utf-8"))
        with patch("core.fb2_processor.HAS_LXML", False):
            root = _parse_fb2_root(bare_amp)
        self.assertIsNotNone(root)

    def test_parse_and_update_extended_metadata_xsd_order_and_extra_translators(self):
        rich_fb2 = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
            'xmlns:l="http://www.w3.org/1999/xlink">'
            "<description><title-info>"
            '<genre match="70">sf_fantasy</genre>'
            "<genre>litrpg</genre>"
            "<author><first-name>Иван</first-name><last-name>Петров</last-name></author>"
            "<book-title>Тестовая книга</book-title>"
            "<annotation><p>Первый <strong>абзац</strong></p><poem><stanza><v>Стих</v></stanza></poem></annotation>"
            '<coverpage><image l:href="#cover.jpg"/></coverpage>'
            "<lang>ru</lang>"
            "<src-lang>en</src-lang>"
            "<translator><first-name>Анна</first-name><last-name>Смирнова</last-name></translator>"
            "<translator><first-name>Борис</first-name><last-name>Кузнецов</last-name></translator>"
            '<sequence name="Цикл" number="1"/>'
            "</title-info>"
            "<publish-info><publisher>АСТ</publisher></publish-info>"
            "</description>"
            "<body><section><p>Текст.</p></section></body>"
            f'<binary id="cover.jpg" content-type="image/jpeg">{FAKE_JPG_B64}</binary>'
            "</FictionBook>"
        ).encode("utf-8")

        meta = parse_metadata(rich_fb2)
        self.assertEqual(meta["genres"], ["sf_fantasy", "litrpg"])
        self.assertEqual(meta["lang"], "ru")
        self.assertTrue(meta["annotation_has_rich_xml"])
        self.assertIn("Первый абзац", meta["annotation"])
        self.assertEqual(meta["translator_last"], "Смирнова")
        self.assertEqual(meta["translator_first"], "Анна")
        self.assertEqual(meta["extra_translators_count"], 1)
        self.assertEqual(meta["publisher"], "АСТ")

        # 1. При изменении только названия богатая аннотация и match="70" на genre не затираются
        untouched = update_fb2_xml(rich_fb2, {**meta, "title": "Обновлённое название"}, orig_meta=meta)
        untouched_str = untouched.decode("utf-8")
        self.assertIn('match="70"', untouched_str)
        self.assertIn("<strong>абзац</strong>", untouched_str)
        self.assertIn("<poem>", untouched_str)
        self.assertIn("<src-lang>en</src-lang>", untouched_str)

        # 2. Обновляем жанры, язык, аннотацию, переводчика и издателя — проверяем XSD-порядок и 2-го переводчика
        edited_meta = {
            **meta,
            "genres": ["sf_space", "custom_tag"],
            "lang": "en",
            "annotation": "Новый абзац один.\n\nНовый абзац два.",
            "translator_last": "Новиков",
            "translator_first": "Пётр",
            "translator_middle": "Игоревич",
            "publisher": "Эксмо",
        }
        updated = update_fb2_xml(rich_fb2, edited_meta, orig_meta=meta)
        parsed = parse_metadata(updated)
        self.assertEqual(parsed["genres"], ["sf_space", "custom_tag"])
        self.assertEqual(parsed["lang"], "en")
        self.assertEqual(parsed["annotation"], "Новый абзац один.\n\nНовый абзац два.")
        self.assertFalse(parsed["annotation_has_rich_xml"])
        self.assertEqual(parsed["translator_last"], "Новиков")
        self.assertEqual(parsed["translator_first"], "Пётр")
        self.assertEqual(parsed["translator_middle"], "Игоревич")
        self.assertEqual(parsed["extra_translators_count"], 1)
        self.assertEqual(parsed["publisher"], "Эксмо")
        updated_str = updated.decode("utf-8")
        self.assertIn("Кузнецов", updated_str)
        self.assertIn("<src-lang>en</src-lang>", updated_str)

        # Проверяем строгий XSD-порядок тегов внутри <title-info>
        root = _parse_fb2_root(updated)
        ti = root.find(".//{http://www.gribuser.ru/xml/fictionbook/2.0}title-info")
        tags = [el.tag.rsplit("}", 1)[-1] for el in ti]
        expected_order = ["genre", "author", "book-title", "annotation", "coverpage", "lang", "src-lang", "translator", "sequence"]
        positions = [tags.index(t) for t in expected_order]
        self.assertEqual(positions, sorted(positions), f"XSD order violated: {tags}")

    def test_save_book_changes_to_source_extended_meta_fb2_and_zip(self):
        with tempfile.TemporaryDirectory() as td:
            fb2_path = os.path.join(td, "ext.fb2")
            with open(fb2_path, "wb") as fh:
                fh.write(VALID_FB2)

            orig = parse_metadata(VALID_FB2)
            new_meta = {
                **orig,
                "genres": ["prose_rus_classic", "my_custom"],
                "lang": "ru",
                "annotation": "Классический роман-эпопея.",
                "translator_last": "Иванова",
                "translator_first": "Мария",
                "translator_middle": "",
                "publisher": "Наука",
            }
            data = {
                "path": fb2_path,
                "archive_entry": None,
                "meta": new_meta,
                "orig_meta": orig,
                "cover_bytes": FAKE_JPG,
                "cover_mime": "image/jpeg",
                "cover_modified": False,
            }
            save_book_changes_to_source(data)
            reloaded = parse_metadata(load_book_xml(fb2_path))
            self.assertEqual(reloaded["genres"], ["prose_rus_classic", "my_custom"])
            self.assertEqual(reloaded["lang"], "ru")
            self.assertEqual(reloaded["annotation"], "Классический роман-эпопея.")
            self.assertEqual(reloaded["translator_last"], "Иванова")
            self.assertEqual(reloaded["publisher"], "Наука")
            self.assertEqual(data["orig_meta"]["publisher"], "Наука")

            # Поиск в очереди по жанру и издателю
            self.assertTrue(book_matches_filter({"path": fb2_path, "meta": reloaded}, "my_custom", "all"))
            self.assertTrue(book_matches_filter({"path": fb2_path, "meta": reloaded}, "наука", "all"))

    def test_quick_check_and_inspect_fb2_structure_warnings_toc_and_media(self):
        from core.fb2_processor import (
            OVERSIZED_IMAGE_BYTES,
            inspect_fb2,
            quick_check_fb2,
            refresh_book_warnings,
        )

        structured_fb2 = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
            'xmlns:l="http://www.w3.org/1999/xlink">'
            "<description><title-info>"
            "<author><first-name>Лев</first-name><last-name>Толстой</last-name></author>"
            "<book-title>Война и мир</book-title>"
            '<coverpage><image l:href="#cover.jpg"/></coverpage>'
            "</title-info></description>"
            "<body>"
            "<section><title><p>Том 1</p></title>"
            "<section><title><p>Глава 1</p></title><p>Абзац 1.</p><p>Абзац 2.</p></section>"
            "</section>"
            "</body>"
            '<body name="notes">'
            '<section id="n1"><title><p>1</p></title><p>Примечание 1.</p></section>'
            '<section id="n2"><title><p>2</p></title><p>Примечание 2.</p></section>'
            "</body>"
            f'<binary id="cover.jpg" content-type="image/jpeg">{FAKE_JPG_B64}</binary>'
            "</FictionBook>"
        ).encode("utf-8")

        meta_ok = parse_metadata(structured_fb2)
        self.assertEqual(quick_check_fb2(structured_fb2, meta=meta_ok, cover_bytes=FAKE_JPG), [])

        with patch("core.fb2_processor.HAS_PIL", False):
            rep = inspect_fb2(structured_fb2, meta=meta_ok, cover_bytes=FAKE_JPG)
        self.assertTrue(rep["xml_valid_strict"])
        self.assertFalse(rep["xml_recovered"])
        self.assertEqual(rep["encoding"], "utf-8")
        self.assertEqual(rep["warnings"], [])
        self.assertEqual(rep["chapter_count"], 2)
        self.assertEqual(rep["toc"][0]["title"], "Том 1")
        self.assertEqual(rep["toc"][0]["children"][0]["title"], "Глава 1")
        self.assertEqual(rep["paragraph_count"], 4)
        self.assertEqual(rep["footnotes_count"], 2)
        self.assertEqual(len(rep["images"]), 1)
        self.assertTrue(rep["images"][0]["is_cover"])
        self.assertTrue(rep["images"][0]["valid"])

        # Проблемная книга: битый XML (&), пустой title/author, нет обложки, пустой binary и > 2 МБ binary
        huge_b64 = base64.b64encode(b"A" * (OVERSIZED_IMAGE_BYTES + 16)).decode("ascii")
        problem_fb2 = (
            '<?xml version="1.0" encoding="windows-1251"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            "<description><title-info><book-title></book-title></title-info></description>"
            "<body><section><p>Rock & Roll</p></section></body>"
            '<binary id="empty.png" content-type="image/png"></binary>'
            f'<binary id="huge.jpg" content-type="image/jpeg">{huge_b64}</binary>'
            "</FictionBook>"
        ).encode("windows-1251")

        quick_w = quick_check_fb2(problem_fb2, meta=parse_metadata(problem_fb2), cover_bytes=None)
        self.assertIn("broken_xml", quick_w)
        self.assertIn("missing_title", quick_w)
        self.assertIn("missing_author", quick_w)
        self.assertIn("missing_cover", quick_w)

        with patch("core.fb2_processor.HAS_PIL", False):
            rep_bad = inspect_fb2(problem_fb2, cover_bytes=None)
        codes = {w["code"] for w in rep_bad["warnings"]}
        self.assertEqual(rep_bad["encoding"], "windows-1251")
        self.assertFalse(rep_bad["xml_valid_strict"])
        self.assertTrue(rep_bad["xml_recovered"])
        self.assertTrue({"broken_xml", "missing_title", "missing_author", "missing_cover", "invalid_binary", "oversized_image"} <= codes)

        # Фильтр "warnings" и обновление предупреждений после правки
        book_entry = {"path": "/tmp/p.fb2", "meta": {"title": "", "last": "", "first": ""}, "warnings": list(quick_w), "cover_bytes": None}
        self.assertTrue(book_matches_filter(book_entry, "", "warnings"))
        book_entry["meta"] = {"title": "Fixed", "last": "Author", "first": ""}
        book_entry["cover_bytes"] = FAKE_JPG
        refresh_book_warnings(book_entry, xml_bytes=structured_fb2)
        self.assertEqual(book_entry["warnings"], [])
        self.assertFalse(book_matches_filter(book_entry, "", "warnings"))

    def test_deduplication_and_skip_existing_conversion(self):
        from core.fb2_processor import (
            compute_book_dedup_key,
            find_duplicate_item_ids,
            should_skip_existing_conversion,
        )

        m1 = {"last": "Толстой", "series": "Русская   классика", "num": "02", "title": "Война и мир"}
        m2 = {"last": "толстой", "series": "русская классика", "num": "2", "title": "  Война  и мир "}
        m3 = {"last": "Достоевский", "series": "", "num": "", "title": "Идиот"}
        self.assertEqual(compute_book_dedup_key(m1), compute_book_dedup_key(m2))
        self.assertEqual(compute_book_dedup_key({"title": ""}), "")

        files_data = {
            "id1": {"meta": m1},
            "id2": {"meta": m3},
            "id3": {"meta": m2},
        }
        self.assertEqual(find_duplicate_item_ids(files_data), {"id3"})

        with tempfile.TemporaryDirectory() as td:
            src_fb2 = os.path.join(td, "war.fb2")
            with open(src_fb2, "wb") as fh:
                fh.write(VALID_FB2)
            out_dir = os.path.join(td, "out")
            os.makedirs(out_dir, exist_ok=True)
            target_name = "war.epub"
            target_path = os.path.join(out_dir, target_name)

            data = {
                "path": src_fb2,
                "meta": dict(m1),
                "orig_meta": dict(m1),
                "cover_modified": False,
            }
            self.assertFalse(should_skip_existing_conversion(data, out_dir, target_name))

            with open(target_path, "wb") as fh:
                fh.write(b"EPUB")
            now = time.time()
            os.utime(src_fb2, (now - 60, now - 60))
            os.utime(target_path, (now, now))
            self.assertTrue(should_skip_existing_conversion(data, out_dir, target_name))

            os.utime(src_fb2, (now + 60, now + 60))
            self.assertFalse(should_skip_existing_conversion(data, out_dir, target_name))

            os.utime(src_fb2, (now - 60, now - 60))
            data_edited = {**data, "meta": {**m1, "title": "Новое название"}}
            self.assertFalse(should_skip_existing_conversion(data_edited, out_dir, target_name))
            data_cov = {**data, "cover_modified": True}
            self.assertFalse(should_skip_existing_conversion(data_cov, out_dir, target_name))

    def test_repair_and_optimize_fb2_and_save_to_source(self):
        from core.fb2_processor import (
            HAS_PIL,
            inspect_fb2,
            repair_and_optimize_fb2,
            repair_book_in_source,
        )

        if HAS_PIL:
            import io as _io
            from PIL import Image as _Image
            buf = _io.BytesIO()
            _Image.new("RGB", (2000, 1400), color=(40, 120, 200)).save(buf, format="PNG")
            big_img_bytes = buf.getvalue()
            big_b64 = base64.b64encode(big_img_bytes).decode("ascii")
            big_mime = "image/png"
            threshold = max(100, len(big_img_bytes) - 10)
        else:
            big_img_bytes = FAKE_JPG
            big_b64 = FAKE_JPG_B64
            big_mime = "image/jpeg"
            threshold = 1024 * 1024

        broken_fb2 = (
            '<?xml version="1.0" encoding="windows-1251"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
            'xmlns:l="http://www.w3.org/1999/xlink">'
            "<description><title-info>"
            "<author><first-name>Лев</first-name><last-name>Толстой</last-name></author>"
            "<book-title>Война & мир</book-title>"
            '<coverpage><image l:href="#cover.jpg"/></coverpage>'
            "</title-info></description>"
            "<body><section><p>Текст & пример.</p></section></body>"
            '<binary id="empty.png" content-type="image/png"></binary>'
            f'<binary id="cover.jpg" content-type="{big_mime}">{big_b64}</binary>'
            "</FictionBook>"
        ).encode("windows-1251")

        repaired, stats = repair_and_optimize_fb2(broken_fb2, max_image_bytes=threshold)
        self.assertTrue(stats["xml_fixed"])
        self.assertEqual(stats["removed_binaries"], 1)
        if HAS_PIL:
            self.assertEqual(stats["optimized_images"], 1)
        rep = inspect_fb2(repaired, cover_bytes=big_img_bytes)
        self.assertTrue(rep["xml_valid_strict"])
        self.assertNotIn("broken_xml", {w["code"] for w in rep["warnings"]})
        self.assertNotIn("invalid_binary", {w["code"] for w in rep["warnings"]})

        with tempfile.TemporaryDirectory() as td:
            fb2_path = os.path.join(td, "broken.fb2")
            with open(fb2_path, "wb") as fh:
                fh.write(broken_fb2)
            data = {
                "path": fb2_path,
                "archive_entry": None,
                "meta": parse_metadata(broken_fb2),
                "cover_bytes": big_img_bytes,
                "warnings": ["broken_xml"],
            }
            src_stats = repair_book_in_source(data, max_image_bytes=threshold)
            self.assertTrue(src_stats["xml_fixed"])
            self.assertNotIn("broken_xml", data["warnings"])
            self.assertEqual(parse_metadata(load_book_xml(fb2_path))["title"], "Война & мир")

    def test_plan_and_execute_organize_fb2_copy_and_move(self):
        from core.fb2_processor import (
            execute_organize_fb2_plan,
            plan_organize_fb2_files,
        )

        with tempfile.TemporaryDirectory() as td:
            src_dir = os.path.join(td, "inbox")
            dst_copy = os.path.join(td, "library_copy")
            dst_move = os.path.join(td, "library_move")
            os.makedirs(src_dir)
            f1 = os.path.join(src_dir, "raw1.fb2")
            f2 = os.path.join(src_dir, "raw2.fb2.zip")
            for p in (f1, f2):
                with open(p, "wb") as fh:
                    fh.write(VALID_FB2)

            items = [
                {
                    "item_id": "1",
                    "path": f1,
                    "display_name": "raw1.fb2",
                    "meta": {"last": "Толстой", "first": "Лев", "series": "Классика", "num": "2", "title": "Война и мир"},
                },
                {
                    "item_id": "2",
                    "path": f2,
                    "display_name": "raw2.fb2.zip",
                    "meta": {"last": "Толстой", "first": "Лев", "series": "Классика", "num": "2", "title": "Война и мир"},
                },
            ]
            plan = plan_organize_fb2_files(items, dst_copy, pattern_mode="author_series")
            self.assertEqual(len(plan), 2)
            self.assertTrue(plan[0]["dst_path"].endswith(os.path.join("Толстой Лев", "Классика", "02 - Война и мир.fb2")))
            self.assertTrue(plan[1]["dst_path"].endswith(os.path.join("Толстой Лев", "Классика", "02 - Война и мир.fb2.zip")))

            cnt, errs, pmap = execute_organize_fb2_plan(plan, copy_mode=True)
            self.assertEqual(cnt, 2)
            self.assertEqual(errs, [])
            self.assertTrue(os.path.isfile(f1))
            self.assertTrue(os.path.isfile(pmap[os.path.abspath(f1)]))
            self.assertTrue(os.path.isfile(pmap[os.path.abspath(f2)]))

            plan_mv = plan_organize_fb2_files(items[:1], dst_move, pattern_mode="author")
            cnt_mv, errs_mv, pmap_mv = execute_organize_fb2_plan(plan_mv, copy_mode=False)
            self.assertEqual(cnt_mv, 1)
            self.assertEqual(errs_mv, [])
            self.assertFalse(os.path.exists(f1))
            self.assertTrue(os.path.isfile(pmap_mv[os.path.abspath(f1)]))

    def test_isbn_normalization_parsing_and_xsd_save_back(self):
        from core.fb2_processor import is_valid_isbn, normalize_isbn

        # Валидация и нормализация ISBN-10 / ISBN-13
        self.assertEqual(normalize_isbn("ISBN 978-5-17-123456-7"), "")
        self.assertEqual(normalize_isbn("ISBN 978-5-17-090641-3"), "9785170906413")
        self.assertTrue(is_valid_isbn("978-0-306-40615-7"))
        self.assertEqual(normalize_isbn("ISBN-10: 0-8044-2957-x"), "080442957X")
        self.assertTrue(is_valid_isbn("0-8044-2957-X"))
        self.assertFalse(is_valid_isbn("0-8044-2957-9"))
        self.assertFalse(is_valid_isbn(""))

        # Парсинг <publish-info><isbn> и поиск в таблице
        fb2_with_isbn = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            "<description><title-info>"
            "<author><first-name>Иван</first-name><last-name>Петров</last-name></author>"
            "<book-title>Книга</book-title>"
            "</title-info>"
            "<publish-info>"
            "<publisher>АСТ</publisher>"
            "<year>2024</year>"
            "<isbn>978-5-17-090641-3</isbn>"
            '<sequence name="Серия издательства"/>'
            "</publish-info></description>"
            "<body><section><p>Текст.</p></section></body>"
            "</FictionBook>"
        ).encode("utf-8")
        meta = parse_metadata(fb2_with_isbn)
        self.assertEqual(meta["isbn"], "978-5-17-090641-3")
        self.assertTrue(book_matches_filter({"path": "/tmp/a.fb2", "meta": meta}, "9785170906413", "all"))
        self.assertTrue(book_matches_filter({"path": "/tmp/a.fb2", "meta": meta}, "978-5-17", "all"))

        # Minimal-diff XSD save-back: вставка <isbn> перед <sequence> в <publish-info>
        no_isbn_fb2 = fb2_with_isbn.replace(b"<isbn>978-5-17-090641-3</isbn>", b"")
        orig_no_isbn = parse_metadata(no_isbn_fb2)
        self.assertEqual(orig_no_isbn["isbn"], "")
        with_isbn = update_fb2_xml(no_isbn_fb2, {**orig_no_isbn, "isbn": "978-5-17-090641-3"}, orig_meta=orig_no_isbn)
        self.assertEqual(parse_metadata(with_isbn)["isbn"], "978-5-17-090641-3")

        root = _parse_fb2_root(with_isbn)
        pub = root.find(".//{http://www.gribuser.ru/xml/fictionbook/2.0}publish-info")
        pub_tags = [el.tag.rsplit("}", 1)[-1] for el in pub]
        self.assertEqual(pub_tags, ["publisher", "year", "isbn", "sequence"])

        # Очистка <isbn> в книге, где был только <isbn> в <publish-info>, удаляет пустой <publish-info>
        added_pub = update_fb2_xml(VALID_FB2, {**parse_metadata(VALID_FB2), "isbn": "978-0-306-40615-7"})
        self.assertEqual(parse_metadata(added_pub)["isbn"], "978-0-306-40615-7")
        cleared_pub = update_fb2_xml(added_pub, {**parse_metadata(added_pub), "isbn": ""})
        self.assertEqual(parse_metadata(cleared_pub)["isbn"], "")
        self.assertNotIn(b"<publish-info", cleared_pub)


    def test_read_zip_entry_limited_enforces_size_cap(self):
        from core.fb2_processor import _read_zip_entry_limited

        with tempfile.TemporaryDirectory() as td:
            zp = os.path.join(td, "big.zip")
            with zipfile.ZipFile(zp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("book.fb2", b"A" * 2048)
            with zipfile.ZipFile(zp, "r") as zf:
                self.assertEqual(len(_read_zip_entry_limited(zf, "book.fb2", max_bytes=4096)), 2048)
                with self.assertRaises(ValueError):
                    _read_zip_entry_limited(zf, "book.fb2", max_bytes=512)

    def test_xml_io_rejects_utf16_and_offset_doctype_xxe(self):
        utf16_xxe = (
            '<?xml version="1.0" encoding="utf-16"?>'
            '<!DOCTYPE foo [<!ENTITY xxe "secret">]>'
            '<FictionBook><description><title-info><book-title>&xxe;</book-title></title-info></description></FictionBook>'
        ).encode("utf-16")
        self.assertIsNone(_parse_fb2_root(utf16_xxe))

        padded_xxe = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            + b"<!-- " + b"A" * 70000 + b" -->"
            + b'<!DOCTYPE foo [<!ENTITY xxe "secret">]>'
            + b"<FictionBook/>"
        )
        self.assertIsNone(_parse_fb2_root(padded_xxe))

    def test_patch_epub_title_classes_sanitizes_css_injection(self):
        from core.fb2.converter import patch_epub_title_classes

        with tempfile.TemporaryDirectory() as td:
            epub_path = os.path.join(td, "test.epub")
            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr("mimetype", "application/epub+zip")
                zf.writestr(
                    "OEBPS/title.xhtml",
                    '<html><body><p class="body-title-header">Author</p><h1 class="body-title-header">Title</h1></body></html>',
                )

            malicious_style = {
                "h1_sz": '150%" onclick="alert(1)',
                "h1_cl": "red; background: url(https://evil.invalid/x)",
                "h1_al": "center",
                "auth_sz": "110%",
                "auth_cl": 'green" onmouseover="x()',
                "auth_al": "center",
                "auth_style": "italic",
            }
            self.assertTrue(patch_epub_title_classes(epub_path, malicious_style))
            with zipfile.ZipFile(epub_path, "r") as zf:
                patched_html = zf.read("OEBPS/title.xhtml").decode("utf-8")
            self.assertNotIn("onclick", patched_html)
            self.assertNotIn("onmouseover", patched_html)
            self.assertNotIn("evil.invalid", patched_html)
            self.assertIn("color: black !important;", patched_html)

    def test_convert_book_file_preserves_existing_output_on_atomic_copy_error(self):
        with tempfile.TemporaryDirectory() as td:
            fb2_path = os.path.join(td, "book.fb2")
            out_dir = os.path.join(td, "out")
            os.makedirs(out_dir, exist_ok=True)
            with open(fb2_path, "wb") as fh:
                fh.write(VALID_FB2)

            existing_out = os.path.join(out_dir, "Existing.epub")
            with open(existing_out, "wb") as fh:
                fh.write(b"ORIGINAL_GOOD_EPUB")

            def _fake_fbc(cmd, cwd, cancel_event=None):
                tmp_out_dir = cmd[-1]
                ep = os.path.join(tmp_out_dir, "Existing.epub")
                with zipfile.ZipFile(ep, "w") as z:
                    z.writestr("mimetype", "application/epub+zip")
                return "", ""

            data = {"path": fb2_path, "display_name": "book.fb2", "meta": parse_metadata(VALID_FB2)}
            style_params = {
                "h1_sz": "150%", "h1_cl": "red", "h1_al": "center",
                "auth_sz": "110%", "auth_cl": "green", "auth_al": "center", "auth_style": "italic",
            }
            with patch("core.fb2_processor._run_cancellable_process", side_effect=_fake_fbc), \
                 patch("core.fb2.converter.shutil.copy2", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    convert_book_file("fbc", "config.yaml", td, data, out_dir, "epub3", style_params)

            with open(existing_out, "rb") as fh:
                self.assertEqual(fh.read(), b"ORIGINAL_GOOD_EPUB")

    def test_convert_book_file_skips_update_xml_for_unmodified_plain_fb2(self):
        with tempfile.TemporaryDirectory() as td:
            fb2_path = os.path.join(td, "unmodified.fb2")
            out_dir = os.path.join(td, "out")
            os.makedirs(out_dir, exist_ok=True)
            with open(fb2_path, "wb") as fh:
                fh.write(VALID_FB2)

            meta = parse_metadata(VALID_FB2)
            captured_cmds = []

            def _fake_fbc(cmd, cwd, cancel_event=None):
                captured_cmds.append(list(cmd))
                tmp_out_dir = cmd[-1]
                ep = os.path.join(tmp_out_dir, "Book.epub")
                with zipfile.ZipFile(ep, "w") as z:
                    z.writestr("mimetype", "application/epub+zip")
                return "", ""

            data = {
                "path": fb2_path,
                "archive_entry": None,
                "display_name": "unmodified.fb2",
                "meta": dict(meta),
                "orig_meta": dict(meta),
                "cover_modified": False,
            }
            style_params = {
                "h1_sz": "150%", "h1_cl": "red", "h1_al": "center",
                "auth_sz": "110%", "auth_cl": "green", "auth_al": "center", "auth_style": "italic",
            }
            with patch("core.fb2_processor._run_cancellable_process", side_effect=_fake_fbc), \
                 patch("core.fb2.converter.update_fb2_xml", side_effect=AssertionError("should not rewrite unmodified FB2")):
                created = convert_book_file("fbc", "config.yaml", td, data, out_dir, "epub3", style_params)

            self.assertEqual(len(created), 1)
            self.assertEqual(captured_cmds[0][-2], fb2_path)
            self.assertTrue(os.path.isfile(fb2_path))

    def test_format_ext_map_includes_pdf_and_txt_and_omnibus_merges_with_isolated_ids(self):
        from core.fb2_processor import FORMAT_EXT_MAP, merge_fb2_books_to_omnibus

        self.assertEqual(FORMAT_EXT_MAP.get("pdf"), ".pdf")
        self.assertEqual(FORMAT_EXT_MAP.get("txt"), ".txt")

        book1_xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">'
            '<description><title-info>'
            '<genre>sf_fantasy</genre>'
            '<author><first-name>Анджей</first-name><last-name>Сапковский</last-name></author>'
            '<book-title>Последнее желание</book-title>'
            '<coverpage><image l:href="#cover.jpg"/></coverpage>'
            '<lang>ru</lang>'
            '<sequence name="Ведьмак" number="1"/>'
            '</title-info></description>'
            '<body><section id="ch1"><p>Текст первой книги <a l:href="#n1" type="note">[1]</a></p></section></body>'
            '<body name="notes"><section id="n1"><p>Сноска книги 1</p></section></body>'
            f'<binary id="cover.jpg" content-type="image/jpeg">{FAKE_JPG_B64}</binary>'
            '</FictionBook>'
        ).encode("utf-8")
        book2_xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">'
            '<description><title-info>'
            '<genre>sf_epic</genre>'
            '<author><first-name>Анджей</first-name><last-name>Сапковский</last-name></author>'
            '<book-title>Меч предназначения</book-title>'
            '<lang>ru</lang>'
            '<sequence name="Ведьмак" number="2"/>'
            '</title-info></description>'
            '<body><section id="ch1"><p>Текст второй книги <a l:href="#n1" type="note">[1]</a></p></section></body>'
            '<body name="notes"><section id="n1"><p>Сноска книги 2</p></section></body>'
            f'<binary id="cover.jpg" content-type="image/jpeg">{FAKE_JPG_B64}</binary>'
            '</FictionBook>'
        ).encode("utf-8")

        with tempfile.TemporaryDirectory() as td:
            p1 = os.path.join(td, "b1.fb2")
            p2 = os.path.join(td, "b2.fb2")
            out_fb2 = os.path.join(td, "witcher_omnibus.fb2")
            with open(p1, "wb") as fh:
                fh.write(book1_xml)
            with open(p2, "wb") as fh:
                fh.write(book2_xml)

            items = [
                {"path": p1, "archive_entry": None, "display_name": "b1.fb2", "meta": parse_metadata(book1_xml)},
                {"path": p2, "archive_entry": None, "display_name": "b2.fb2", "meta": parse_metadata(book2_xml)},
            ]
            res = merge_fb2_books_to_omnibus(items, out_fb2)
            self.assertEqual(res["books_count"], 2)
            self.assertEqual(res["series"], "Ведьмак")
            self.assertTrue(os.path.isfile(out_fb2))

            merged_bytes = load_book_xml(out_fb2)
            merged_meta = parse_metadata(merged_bytes)
            self.assertEqual(merged_meta["last"], "Сапковский")
            self.assertEqual(merged_meta["series"], "Ведьмак")
            self.assertIn("sf_fantasy", merged_meta["genres"])
            self.assertIn("sf_epic", merged_meta["genres"])

            merged_str = merged_bytes.decode("utf-8")
            self.assertIn('id="b1_n1"', merged_str)
            self.assertIn('id="b2_n1"', merged_str)
            self.assertIn('href="#b1_n1"', merged_str)
            self.assertIn('href="#b2_n1"', merged_str)
            self.assertIn('id="b1_cover.jpg"', merged_str)
            self.assertIn('id="b2_cover.jpg"', merged_str)
            cov, _ = extract_cover_from_fb2(merged_bytes)
            self.assertEqual(cov, FAKE_JPG)

            # Обложка берётся из 2-й книги, если у 1-й нет обложки, + проверка max_xml_bytes и локализованных дефолтов
            no_cov_book1 = book1_xml.replace(b'<coverpage><image l:href="#cover.jpg"/></coverpage>', b"")
            with_cov_book2 = book2_xml.replace(
                b"<lang>ru</lang>",
                b'<coverpage><image l:href="#cover.jpg"/></coverpage><lang>ru</lang>',
            )
            p1_nc = os.path.join(td, "b1_nc.fb2")
            p2_wc = os.path.join(td, "b2_wc.fb2")
            out_fb2_en = os.path.join(td, "en_omnibus.fb2")
            with open(p1_nc, "wb") as fh:
                fh.write(no_cov_book1)
            with open(p2_wc, "wb") as fh:
                fh.write(with_cov_book2)
            items_nc = [
                {"path": p1_nc, "archive_entry": None, "display_name": "b1_nc.fb2", "meta": parse_metadata(no_cov_book1)},
                {"path": p2_wc, "archive_entry": None, "display_name": "b2_wc.fb2", "meta": parse_metadata(with_cov_book2)},
            ]
            res_en = merge_fb2_books_to_omnibus(items_nc, out_fb2_en, default_omnibus_suffix="Omnibus")
            self.assertEqual(res_en["title"], "Ведьмак (Omnibus)")
            cov_fallback, _ = extract_cover_from_fb2(load_book_xml(out_fb2_en))
            self.assertEqual(cov_fallback, FAKE_JPG)

            with self.assertRaises(ValueError):
                merge_fb2_books_to_omnibus(items_nc, os.path.join(td, "too_big.fb2"), max_xml_bytes=128)

    def test_execute_organize_fb2_plan_blocks_dest_root_escape(self):
        from core.fb2_processor import execute_organize_fb2_plan

        with tempfile.TemporaryDirectory() as td:
            root_dir = os.path.join(td, "library")
            outside_dir = os.path.join(td, "outside")
            os.makedirs(root_dir)
            os.makedirs(outside_dir)
            src = os.path.join(td, "book.fb2")
            with open(src, "wb") as fh:
                fh.write(VALID_FB2)

            bad_plan = [{
                "item_id": "1",
                "src_path": src,
                "dst_path": os.path.join(outside_dir, "escaped.fb2"),
                "dest_root": root_dir,
                "display_name": "book.fb2",
            }]
            cnt, errs, _ = execute_organize_fb2_plan(bad_plan, copy_mode=True)
            self.assertEqual(cnt, 0)
            self.assertEqual(len(errs), 1)
            self.assertFalse(os.path.exists(os.path.join(outside_dir, "escaped.fb2")))

    def test_attach_stylesheet_and_windows_fonts_avoid_symlinks(self):
        from core.fb2.converter import _attach_fonts_dir, _attach_stylesheet_file

        with tempfile.TemporaryDirectory() as td:
            src_dir = os.path.join(td, "src")
            fonts_dir = os.path.join(src_dir, "fonts")
            work_dir = os.path.join(td, "work")
            os.makedirs(fonts_dir)
            os.makedirs(work_dir)
            css_path = os.path.join(src_dir, "ebook_styles.css")
            with open(css_path, "w", encoding="utf-8") as fh:
                fh.write("body { margin: 0; }\n")
            with open(os.path.join(fonts_dir, "sample.ttf"), "wb") as fh:
                fh.write(b"FONT")

            with patch("core.fb2.converter.os.symlink", side_effect=AssertionError("symlink must not be called")):
                dst_css = _attach_stylesheet_file(src_dir, None, work_dir)
                with patch("core.fb2.converter.os.name", "nt"):
                    dst_fonts = _attach_fonts_dir(src_dir, None, work_dir)

            self.assertEqual(dst_css, os.path.join(work_dir, "ebook_styles.css"))
            self.assertTrue(os.path.isfile(dst_css))
            self.assertFalse(os.path.islink(dst_css))
            self.assertEqual(dst_fonts, os.path.join(work_dir, "fonts"))
            self.assertTrue(os.path.isdir(dst_fonts))
            self.assertFalse(os.path.islink(dst_fonts))
            self.assertTrue(os.path.isfile(os.path.join(dst_fonts, "sample.ttf")))

    def test_quick_check_rejects_doctype_without_expanding_entities(self):
        from core.fb2.diagnostics import _is_strict_xml_valid, quick_check_fb2

        xxe_fb2 = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<!DOCTYPE foo [<!ENTITY a "1234567890"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
            b'<FictionBook><description><title-info><book-title>&b;</book-title></title-info></description>'
            b'<body><section><p>Text</p></section></body></FictionBook>'
        )
        self.assertFalse(_is_strict_xml_valid(xxe_fb2))
        warns = quick_check_fb2(xxe_fb2, meta={"title": "T", "last": "A"}, cover_bytes=b"img")
        self.assertIn("broken_xml", warns)

    def test_organizer_sanitizes_windows_reserved_names_and_caps_length(self):
        from core.fb2.organizer import _sanitize_fs_component

        for reserved in ("CON", "prn", "Aux", "NUL", "COM1", "lpt9"):
            sanitized = _sanitize_fs_component(reserved)
            self.assertNotEqual(sanitized.upper(), reserved.upper())
            self.assertTrue(sanitized.endswith("_"))

        long_name = "А" * 200
        self.assertLessEqual(len(_sanitize_fs_component(long_name)), 100)

    def test_omnibus_applies_unsaved_cover_and_meta_edits(self):
        from core.fb2_processor import merge_fb2_books_to_omnibus

        new_cov = b"\xff\xd8\xff\xe0UNSAVEDCOVER"
        with tempfile.TemporaryDirectory() as td:
            p1 = os.path.join(td, "b1.fb2")
            p2 = os.path.join(td, "b2.fb2")
            out_fb2 = os.path.join(td, "omnibus_unsaved.fb2")
            with open(p1, "wb") as fh:
                fh.write(VALID_FB2)
            with open(p2, "wb") as fh:
                fh.write(VALID_FB2)

            orig1 = parse_metadata(VALID_FB2)
            edited1 = {**orig1, "title": "Отредактированная книга 1"}
            items = [
                {
                    "path": p1,
                    "archive_entry": None,
                    "display_name": "b1.fb2",
                    "meta": edited1,
                    "orig_meta": orig1,
                    "cover_bytes": new_cov,
                    "cover_mime": "image/jpeg",
                    "cover_modified": True,
                },
                {
                    "path": p2,
                    "archive_entry": None,
                    "display_name": "b2.fb2",
                    "meta": dict(orig1),
                    "orig_meta": dict(orig1),
                    "cover_modified": False,
                },
            ]
            merge_fb2_books_to_omnibus(items, out_fb2)
            merged_bytes = load_book_xml(out_fb2)
            cov, _ = extract_cover_from_fb2(merged_bytes)
            self.assertEqual(cov, new_cov)
            self.assertIn("Отредактированная книга 1".encode("utf-8"), merged_bytes)

    def test_update_fb2_xml_preserves_body_title_markup_when_title_unchanged(self):
        rich_title_fb2 = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            "<description><title-info>"
            "<author><first-name>Лев</first-name><last-name>Толстой</last-name></author>"
            "<book-title>Война и мир</book-title>"
            "</title-info></description>"
            "<body><title><p>Лев Толстой</p><p>Война и <emphasis>мир</emphasis></p></title>"
            "<section><p>Текст.</p></section></body>"
            "</FictionBook>"
        ).encode("utf-8")
        orig = parse_metadata(rich_title_fb2)
        updated = update_fb2_xml(rich_title_fb2, {**orig, "series": "Новая серия"}, orig_meta=orig)
        self.assertIn(b"<emphasis>", updated)

    def test_logger_masks_home_directory_path(self):
        import logging
        from core.logger import _HomePathMaskFilter

        home = os.path.expanduser("~")
        if not home or home == "~":
            self.skipTest("Home directory cannot be expanded")
        flt = _HomePathMaskFilter()
        rec = logging.LogRecord("test", logging.INFO, __file__, 1, "Opened %s", (os.path.join(home, "secret.fb2"),), None)
        self.assertTrue(flt.filter(rec))
        self.assertNotIn(home, rec.getMessage())
        self.assertIn("~", rec.getMessage())


if __name__ == "__main__":
    unittest.main()

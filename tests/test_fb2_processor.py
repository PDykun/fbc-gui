import base64
import os
import sys
import tempfile
import threading
import time
import unittest
import zipfile

from core.fb2_processor import (
    ConversionCancelledError,
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
            "Толстой - (ВИМ - 01) Том 1\u22152",
        )
        meta_no_series = {**meta_full, "series": "", "num": ""}
        self.assertEqual(
            render_filename_from_tokens(DEFAULT_FILENAME_TOKENS, meta_no_series, "epub3"),
            "Толстой - Том 1\u22152",
        )
        self.assertEqual(
            simulate_fbc_target(meta_full, "kepub3", "default"),
            "(ВИМ - 01) Том 1\u22152.kepub.epub",
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
            self.assertEqual(os.path.basename(created[0]), "Толстой - (РК - 02) Война и мир.epub")
            with zipfile.ZipFile(created[0], "r") as z:
                opf = z.read("OEBPS/content.opf").decode("utf-8")
                self.assertIn("(РК - 02) Война и мир", opf)


if __name__ == "__main__":
    unittest.main()

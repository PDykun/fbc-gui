import io
import unittest
from unittest.mock import patch
import urllib.parse

from core.fb2_processor import HAS_PIL
from core.metadata_lookup import (
    BookMetadataCandidate,
    FantLabProvider,
    GoogleBooksProvider,
    LitResProvider,
    OpdsProvider,
    OpenLibraryProvider,
    _https_url,
    _safe_parse_xml,
    build_providers,
    clean_annotation_text,
    download_cover_image,
    fetch_candidate_covers,
    map_external_genres_to_fb2,
    normalize_lang_code,
    score_candidate,
    search_book_metadata,
    split_author_name,
)


def _make_png_bytes(width=120, height=180, color=(30, 80, 140)):
    if HAS_PIL:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (width, height), color=color).save(buf, format="PNG")
        return buf.getvalue()
    return b"\x89PNG\r\n\x1a\n" + (b"\x00" * 200)


class TestMetadataLookup(unittest.TestCase):
    def test_text_author_lang_and_genre_helpers(self):
        cleaned = clean_annotation_text("<p>Первый [b]абзац[/b] &amp; тест.</p><p>Второй<br/>ряд [url=x]ссылка[/url].</p>")
        self.assertEqual(cleaned, "Первый абзац & тест.\n\nВторой\nряд ссылка.")

        self.assertEqual(split_author_name("Толстой, Лев Николаевич"), ("Лев", "Николаевич", "Толстой"))
        self.assertEqual(split_author_name("Толстой Лев Николаевич"), ("Лев", "Николаевич", "Толстой"))
        self.assertEqual(split_author_name("Лев Николаевич Толстой"), ("Лев", "Николаевич", "Толстой"))
        self.assertEqual(split_author_name("Frank Herbert"), ("Frank", "", "Herbert"))

        self.assertEqual(normalize_lang_code("rus"), "ru")
        self.assertEqual(normalize_lang_code("ru-RU"), "ru")
        self.assertEqual(normalize_lang_code("eng"), "en")
        self.assertEqual(normalize_lang_code("deu"), "de")

        genres = map_external_genres_to_fb2(["Космическая фантастика", "Киберпанк", "sf_fantasy", "Space Opera"])
        self.assertEqual(genres, ["sf_space", "sf_cyberpunk", "sf_fantasy"])

    def test_fantlab_provider_parses_search_and_extended_details(self):
        search_payload = {
            "matches": [
                {"work_id": 42, "rusname": "Пикник на обочине", "autor_rusname": "Аркадий Стругацкий, Борис Стругацкий", "year": 1972}
            ]
        }
        details_payload = {
            "work_name": "Пикник на обочине",
            "authors": [{"name": "Аркадий Стругацкий"}],
            "work_description": "[b]Знаменитая[/b] повесть о Зоне.",
            "work_year": 1972,
            "parents": {"cycles": [[{"work_name": "Мир Полудня"}]]},
            "classificatory": {"genre_group": [{"genre": [{"label": "Научная фантастика"}]}]},
            "image": "/images/editions/orig/1001",
            "editions_blocks": {
                "paper": {"list": [{"edition_id": 777, "isbn": "978-5-17-090641-3", "creators": "АСТ", "lang_code": "rus"}]}
            },
            "translations": [{"translators": [{"name": "Анна Смирнова"}]}],
        }

        def _fake_json(url, timeout=8.0, headers=None, max_bytes=0):
            if "search-works" in url:
                return search_payload
            return details_payload

        with patch("core.metadata_lookup._http_get_json", side_effect=_fake_json):
            res = FantLabProvider().search(title="Пикник на обочине", author="Стругацкий")

        self.assertEqual(len(res), 1)
        c = res[0]
        self.assertEqual(c.provider, "fantlab")
        self.assertEqual(c.title, "Пикник на обочине")
        self.assertEqual(c.last, "Стругацкий")
        self.assertEqual(c.series, "Мир Полудня")
        self.assertEqual(c.isbn, "978-5-17-090641-3")
        self.assertEqual(c.publisher, "АСТ")
        self.assertEqual(c.genres, ["sf"])
        self.assertEqual(c.annotation, "Знаменитая повесть о Зоне.")
        self.assertEqual(c.translator_last, "Смирнова")
        self.assertEqual(len(c.cover_urls), 2)

    def test_litres_provider_parses_storefront_payload(self):
        payload = {
            "payload": {
                "data": [
                    {
                        "instance": {
                            "id": 9001,
                            "title": "Дюна",
                            "url": "/book/frenk-gerbert/dyuna/",
                            "persons": [
                                {"role": "author", "full_name": "Фрэнк Герберт"},
                                {"role": "translator", "full_name": "Павел Вязников"},
                            ],
                            "series": [{"name": "Хроники Дюны", "art_order": 1}],
                            "genres": [{"name": "Космическая фантастика"}],
                            "cover_url": "/pub/c/cover/9001.jpg",
                            "publisher": {"name": "АСТ"},
                            "isbn": "978-5-17-090641-3",
                            "annotation": "<p>Песчаная планета Арракис.</p>",
                            "language_code": "ru",
                            "year": 2020,
                        }
                    }
                ]
            }
        }
        with patch("core.metadata_lookup._http_get_json", return_value=payload):
            res = LitResProvider().search(title="Дюна", author="Герберт")

        self.assertEqual(len(res), 1)
        c = res[0]
        self.assertEqual(c.provider, "litres")
        self.assertEqual(c.title, "Дюна")
        self.assertEqual(c.last, "Герберт")
        self.assertEqual(c.series, "Хроники Дюны")
        self.assertEqual(c.num, "1")
        self.assertEqual(c.translator_last, "Вязников")
        self.assertEqual(c.genres, ["sf_space"])
        self.assertEqual(c.annotation, "Песчаная планета Арракис.")
        self.assertTrue(c.cover_urls[0].startswith("https://"))

    def test_openlibrary_and_googlebooks_providers(self):
        ol_payload = {
            "docs": [
                {
                    "key": "/works/OL1W",
                    "title": "Dune",
                    "author_name": ["Frank Herbert"],
                    "isbn": ["9780441172719"],
                    "publisher": ["Ace Books"],
                    "first_publish_year": 1965,
                    "language": ["eng"],
                    "cover_i": 12345,
                    "subject": ["Science fiction", "Space opera"],
                }
            ]
        }
        with patch("core.metadata_lookup._http_get_json", return_value=ol_payload):
            ol_res = OpenLibraryProvider().search(isbn="978-0-441-17271-9")

        self.assertEqual(len(ol_res), 1)
        self.assertEqual(ol_res[0].lang, "en")
        self.assertEqual(ol_res[0].publisher, "Ace Books")
        self.assertIn("default=false", ol_res[0].cover_urls[0])

        # Google Books без ключа не выполняет сетевых запросов
        with patch("core.metadata_lookup._http_get_json") as mock_get:
            self.assertEqual(GoogleBooksProvider(api_key="").search(title="Dune"), [])
            mock_get.assert_not_called()

        # Google Books с ключом использует plain q= и переводит imageLinks на https
        http_thumb = urllib.parse.urlunsplit(("http", "books.google.com", "/books/content", "id=gb1", ""))
        gb_payload = {
            "items": [
                {
                    "id": "gb1",
                    "volumeInfo": {
                        "title": "Dune",
                        "authors": ["Frank Herbert"],
                        "publisher": "Ace",
                        "publishedDate": "1990-09-01",
                        "description": "Desert planet epic.",
                        "language": "en",
                        "categories": ["Science Fiction"],
                        "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780441172719"}],
                        "imageLinks": {"thumbnail": http_thumb},
                    },
                }
            ]
        }
        with patch("core.metadata_lookup._http_get_json", return_value=gb_payload) as mock_gb:
            gb_res = GoogleBooksProvider(api_key="TEST_KEY").search(title="Dune", author="Herbert")
            called_url = mock_gb.call_args[0][0]
            called_headers = mock_gb.call_args[1].get("headers") or {}
            self.assertNotIn("key=", called_url)
            self.assertEqual(called_headers.get("X-Goog-Api-Key"), "TEST_KEY")
            self.assertNotIn("intitle", called_url)
            self.assertNotIn("inauthor", called_url)

        self.assertEqual(len(gb_res), 1)
        self.assertTrue(gb_res[0].cover_urls[0].startswith("https://"))

    def test_search_book_metadata_isolates_errors_and_ranks_by_isbn_and_similarity(self):
        good_cand = BookMetadataCandidate(
            provider="fantlab",
            title="Война и мир",
            first="Лев",
            last="Толстой",
            isbn="978-5-17-090641-3",
            cover_urls=[_https_url("fantlab.ru", "/images/editions/big/1")],
        )
        weak_cand = BookMetadataCandidate(
            provider="openlibrary",
            title="Completely Unrelated Title",
            last="Other",
            isbn="",
        )

        with patch.object(FantLabProvider, "search", return_value=[good_cand]), \
             patch.object(LitResProvider, "search", side_effect=RuntimeError("HTTP 503")), \
             patch.object(OpenLibraryProvider, "search", return_value=[weak_cand]):
            res = search_book_metadata(
                title="Война и мир",
                author="Толстой",
                isbn="978-5-17-090641-3",
                enabled_providers=("fantlab", "litres", "openlibrary"),
            )

        self.assertIn("litres", res.errors)
        self.assertEqual(len(res.candidates), 1)
        self.assertEqual(res.candidates[0].provider, "fantlab")
        self.assertGreater(res.candidates[0].score, 0.85)
        self.assertLess(score_candidate(weak_cand, query_title="Война и мир", query_author="Толстой"), 0.25)
        self.assertEqual([p.provider_id for p in build_providers(google_books_api_key="")], ["fantlab", "litres", "openlibrary"])

    def test_download_and_deduplicate_covers(self):
        png_a = _make_png_bytes(120, 180, color=(20, 40, 80))
        png_b = _make_png_bytes(140, 210, color=(90, 20, 40))

        u1 = _https_url("fantlab.ru", "/images/editions/big/10")
        u2 = _https_url("www.litres.ru", "/pub/c/cover/10.jpg")
        u3 = _https_url("covers.openlibrary.org", "/b/id/99-L.jpg")

        cands = [
            BookMetadataCandidate(provider="fantlab", cover_urls=[u1]),
            BookMetadataCandidate(provider="litres", cover_urls=[u2]),
            BookMetadataCandidate(provider="openlibrary", cover_urls=[u3]),
        ]

        mapping = {u1: png_a, u2: png_a, u3: png_b}

        def _fake_bytes(url, timeout=10.0, headers=None, max_bytes=0, require_https=True):
            return mapping[url]

        with patch("core.metadata_lookup._http_get_bytes", side_effect=_fake_bytes):
            covers = fetch_candidate_covers(cands, max_covers=5)

        self.assertEqual(len(covers), 2)
        self.assertEqual(covers[0]["provider"], "fantlab")
        self.assertEqual(covers[1]["provider"], "openlibrary")

        tiny = _make_png_bytes(1, 1)
        with patch("core.metadata_lookup._http_get_bytes", return_value=tiny):
            with self.assertRaises(ValueError):
                download_cover_image(u1)

    def test_lookup_and_cover_workers_run_and_cancel(self):
        from core.metadata_lookup import LookupResult
        from core.workers import CoverFetchWorker, MetadataLookupWorker

        fake_cand = BookMetadataCandidate(provider="fantlab", title="Дюна", last="Герберт")
        fake_res = LookupResult(candidates=[fake_cand], errors={})
        captured_lookup = []

        w_lookup = MetadataLookupWorker(
            title="Дюна",
            author="Герберт",
            enabled_providers=["fantlab"],
        )
        w_lookup.finished_lookup.connect(captured_lookup.append)
        with patch("core.metadata_lookup.search_book_metadata", return_value=fake_res) as mock_search:
            w_lookup.run()
            self.assertTrue(mock_search.called)
        self.assertEqual(len(captured_lookup), 1)
        self.assertEqual(captured_lookup[0].candidates[0].title, "Дюна")

        captured_covers = []
        w_cov = CoverFetchWorker([fake_cand], max_covers=4)
        w_cov.cancel()
        self.assertTrue(w_cov._cancel_event.is_set())
        w_cov.finished_covers.connect(captured_covers.append)
        with patch("core.metadata_lookup.fetch_candidate_covers", return_value=[]) as mock_cov:
            w_cov.run()
            self.assertTrue(mock_cov.called)
        self.assertEqual(captured_covers, [[]])

    def test_metadata_lookup_dialog_selection_presets_and_updates(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from core.metadata_lookup import LookupResult
        from ui.dialogs import MetadataLookupDialog

        _app = QApplication.instance() or QApplication([])
        cur_meta = {
            "title": "Дюна",
            "last": "Герберт",
            "first": "",
            "mid": "",
            "series": "",
            "num": "",
            "genres": [],
            "lang": "",
            "annotation": "",
            "translator_first": "",
            "translator_last": "",
            "translator_middle": "",
            "publisher": "",
            "isbn": "",
        }
        cand = BookMetadataCandidate(
            provider="fantlab",
            title="Дюна (новое издание)",
            first="Фрэнк",
            last="Герберт",
            series="Хроники Дюны",
            num="1",
            genres=["sf_space"],
            lang="ru",
            annotation="Эпический роман о планете Арракис.",
            translator_first="Павел",
            translator_last="Вязников",
            publisher="АСТ",
            isbn="978-5-17-090641-3",
            year="2020",
            score=0.95,
        )

        with patch.object(MetadataLookupDialog, "_start_search", lambda self: None):
            dlg = MetadataLookupDialog(
                None,
                cur_meta,
                app_settings={"metadata_providers": ["fantlab"], "google_books_api_key": "", "opds_url": ""},
            )
            self.assertFalse(dlg._prov_checks["googlebooks"].isEnabled())
            self.assertFalse(dlg._prov_checks["opds"].isEnabled())

            with patch("core.workers.CoverFetchWorker.start", lambda self: None):
                dlg._on_lookup_finished(LookupResult(candidates=[cand], errors={}))

            # По умолчанию отмечены только пустые поля (title и last уже заполнены)
            updates_empty = dlg.get_selected_meta_updates()
            self.assertNotIn("title", updates_empty)
            self.assertNotIn("last", updates_empty)
            self.assertEqual(updates_empty["first"], "Фрэнк")
            self.assertEqual(updates_empty["series"], "Хроники Дюны")
            self.assertEqual(updates_empty["isbn"], "978-5-17-090641-3")
            self.assertEqual(updates_empty["translator_last"], "Вязников")

            # Пресет «Все найденные» отмечает и уже заполненные поля
            dlg._apply_selection_preset("all")
            updates_all = dlg.get_selected_meta_updates()
            self.assertEqual(updates_all["title"], "Дюна (новое издание)")
            self.assertEqual(updates_all["last"], "Герберт")

            # Пресет «Только обложка» снимает все текстовые поля
            dlg._apply_selection_preset("none")
            self.assertEqual(dlg.get_selected_meta_updates(), {})

            # Выбор обложки из галереи
            png_bytes = _make_png_bytes(120, 180)
            dlg._on_covers_loaded([{"provider": "fantlab", "bytes": png_bytes, "mime": "image/png", "width": 120, "height": 180}])
            self.assertIsNone(dlg.get_selected_cover())
            dlg._select_cover(0)
            cov = dlg.get_selected_cover()
            self.assertIsNotNone(cov)
            self.assertGreater(len(cov[0]), 0)
            dlg.close()

    def test_opds_provider_opensearch_parsing_auth_and_xxe(self):
        root_url = urllib.parse.urlunsplit(("http", "nas.local:8083", "/opds", "", ""))
        os_url = urllib.parse.urlunsplit(("http", "nas.local:8083", "/opds-opensearch.xml", "", ""))
        search_tpl = urllib.parse.urlunsplit(
            ("http", "nas.local:8083", "/opds/search", "searchTerm={searchTerms}&searchType=books", "")
        )
        cover_rel = "/covers/42.png"
        cover_abs = urllib.parse.urlunsplit(("http", "nas.local:8083", cover_rel, "", ""))
        rel_img = urllib.parse.urlunsplit(("http", "opds-spec.org", "/image", "", ""))
        rel_acq = urllib.parse.urlunsplit(("http", "opds-spec.org", "/acquisition", "", ""))

        root_feed = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<feed>'
            f'<link rel="search" type="application/opensearchdescription+xml" href="{os_url}"/>'
            '</feed>'
        ).encode("utf-8")
        opensearch_xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<OpenSearchDescription>'
            f'<Url type="application/atom+xml" template="{search_tpl.replace("&", "&amp;")}"/>'
            '</OpenSearchDescription>'
        ).encode("utf-8")
        search_feed = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<feed>'
            '<entry><title>Навигация</title><id>nav:1</id></entry>'
            '<entry>'
            '<id>tag:book:42</id>'
            '<title>Пикник на обочине</title>'
            '<author><name>Аркадий Стругацкий</name></author>'
            '<category term="sf" label="Научная фантастика"/>'
            '<language>ru</language>'
            '<publisher>АСТ</publisher>'
            '<issued>1972</issued>'
            '<identifier>urn:isbn:978-5-17-090641-3</identifier>'
            '<content type="html">&lt;p&gt;Повесть о Зоне.&lt;/p&gt;</content>'
            f'<link rel="{rel_img}" type="image/png" href="{cover_rel}"/>'
            f'<link rel="{rel_acq}" type="application/fb2+zip" href="/b/42/fb2"/>'
            '</entry>'
            '</feed>'
        ).encode("utf-8")

        seen_headers = {}

        def _fake_bytes(url, timeout=8.0, headers=None, max_bytes=0, require_https=True):
            seen_headers[url] = dict(headers or {})
            if url == root_url:
                return root_feed
            if url == os_url:
                return opensearch_xml
            if "/opds/search" in url:
                return search_feed
            if url == cover_abs:
                return _make_png_bytes(120, 180)
            raise AssertionError(f"Unexpected URL: {url}")

        with patch("core.metadata_lookup._http_get_bytes", side_effect=_fake_bytes):
            prov = OpdsProvider(opds_url=root_url, username="alice", password="secret")
            items = prov.search(title="Пикник", author="Стругацкий")
            self.assertEqual(len(items), 1)
            c = items[0]
            self.assertEqual(c.provider, "opds")
            self.assertEqual(c.title, "Пикник на обочине")
            self.assertEqual(c.last, "Стругацкий")
            self.assertEqual(c.genres, ["sf"])
            self.assertEqual(c.lang, "ru")
            self.assertEqual(c.publisher, "АСТ")
            self.assertEqual(c.year, "1972")
            self.assertEqual(c.isbn, "978-5-17-090641-3")
            self.assertEqual(c.annotation, "Повесть о Зоне.")
            self.assertEqual(c.cover_urls, [cover_abs])
            self.assertIn("Authorization", seen_headers[root_url])

            covers = fetch_candidate_covers(
                items,
                max_covers=4,
                opds_url=root_url,
                opds_username="alice",
                opds_password="secret",
            )
            self.assertEqual(len(covers), 1)
            self.assertEqual(covers[0]["provider"], "opds")
            self.assertIn("Authorization", seen_headers[cover_abs])

        # Защита от XXE / DOCTYPE
        with self.assertRaises(ValueError):
            _safe_parse_xml(b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><feed/>')

        # build_providers включает opds только при валидном HTTP/HTTPS URL
        self.assertEqual(
            [p.provider_id for p in build_providers(enabled_providers=("opds",), opds_url="file:///etc/passwd")],
            [],
        )
        self.assertEqual(
            [p.provider_id for p in build_providers(enabled_providers=("opds",), opds_url=root_url)],
            ["opds"],
        )

    def test_converter_cover_panel_has_lookup_online_button(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication, QWidget
        from core.config import get_default_app_settings
        from core.i18n import LOCALE, init_locale
        from ui.pages.converter_page import build_converter_page

        locales_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales")
        init_locale(locales_dir, locales_dir)
        LOCALE.set_language("ru")
        _app = QApplication.instance() or QApplication([])

        class _StubWin:
            def __init__(self):
                self.app_settings = get_default_app_settings()
                self._table_status_filter = "all"
            def __getattr__(self, _name):
                return lambda *a, **kw: None
            def installEventFilter(self, _obj):
                pass

        win = _StubWin()
        parent = QWidget()
        with patch("PyQt6.QtCore.QObject.installEventFilter", lambda self, obj: None):
            build_converter_page(win, parent)
        self.assertTrue(hasattr(win, "btn_lookup_online"))
        self.assertFalse(win.btn_lookup_online.isEnabled())
        self.assertGreater(len(win.btn_lookup_online.text().strip()), 0)
        parent.close()


    def test_utf16_doctype_rejected_and_secret_masking(self):
        from core.metadata_lookup import _mask_secrets_in_text

        utf16_xml = '<?xml version="1.0" encoding="utf-16"?><!DOCTYPE foo [<!ENTITY x "y">]><feed/>'.encode("utf-16")
        with self.assertRaises(ValueError):
            _safe_parse_xml(utf16_xml)

        sample_url = _https_url("api.example.org", "/v1", {"q": "x", "key": "DemoKey123"})
        masked = _mask_secrets_in_text(f"HTTP Error 403 for {sample_url} Basic sampletoken")
        self.assertNotIn("DemoKey123", masked)
        self.assertNotIn("sampletoken", masked)
        self.assertIn("key=***", masked)
        self.assertIn("Basic ***", masked)


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from core.inpx_library import (
    InpxLibraryIndex,
    _format_inpx_authors,
    resolve_book_source,
)

INP_SEP = "\x04"


def _make_sample_fb2(title="Тестовая книга", author_last="Иванов", author_first="Иван"):
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
        "<description><title-info>"
        f"<author><first-name>{author_first}</first-name><last-name>{author_last}</last-name></author>"
        f"<book-title>{title}</book-title>"
        "<lang>ru</lang>"
        "</title-info></description>"
        "<body><section><p>Текст книги.</p></section></body>"
        "</FictionBook>"
    ).encode("utf-8")


def _make_default_inp_row(
    author,
    genre,
    title,
    series,
    serno,
    file_stem,
    size="300000",
    libid="1",
    deleted="0",
    ext="fb2",
    date="2020-01-01",
    insno="",
    folder="",
    lang="ru",
    librate="",
    keywords="",
):
    return INP_SEP.join([
        author, genre, title, series, serno, file_stem, size, libid,
        deleted, ext, date, insno, folder, lang, librate, keywords,
    ])


def _build_inpx(
    inpx_path,
    inp_files,
    *,
    collection_info="Flibusta Test\r\nflibusta\r\n0\r\nTest\r\n",
    version_info="20261127\r\n",
    structure_info=None,
):
    with zipfile.ZipFile(inpx_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if collection_info is not None:
            zf.writestr("collection.info", collection_info.encode("utf-8"))
        if version_info is not None:
            zf.writestr("version.info", version_info.encode("utf-8"))
        if structure_info is not None:
            zf.writestr("structure.info", structure_info.encode("utf-8"))
        for name, lines in inp_files.items():
            zf.writestr(name, ("\r\n".join(lines) + "\r\n").encode("utf-8"))


class TestInpxLibrary(unittest.TestCase):
    def test_format_inpx_authors(self):
        self.assertEqual(
            _format_inpx_authors("Стругацкий,Аркадий,Натанович:Стругацкий,Борис,Натанович:"),
            "Стругацкий Аркадий Натанович, Стругацкий Борис Натанович",
        )
        self.assertEqual(_format_inpx_authors("Толстой,Лев,:"), "Толстой Лев")
        self.assertEqual(_format_inpx_authors(""), "")

    def test_index_default_and_custom_structure(self):
        with tempfile.TemporaryDirectory() as td:
            inpx_path = os.path.join(td, "lib.inpx")
            db_path = os.path.join(td, "cache.sqlite")
            row_ok = _make_default_inp_row(
                "Лукьяненко,Сергей,Васильевич:", "sf_fantasy:", "Ночной дозор",
                "Дозоры", "1", "1001", size="512000", deleted="0", ext="fb2", lang="ru",
            )
            row_non_fb2 = _make_default_inp_row(
                "Автор,Тест,:", "sf:", "Книга в EPUB",
                "", "", "1002", size="12345", deleted="0", ext="epub", lang="ru",
            )
            row_del = _make_default_inp_row(
                "Лукьяненко,Сергей,:", "sf_fantasy:", "Удалённая книга",
                "Дозоры", "2", "1003", size="400000", deleted="1", ext="fb2", lang="ru",
            )
            _build_inpx(inpx_path, {"fb2-001.inp": [row_ok, row_non_fb2, row_del]})

            idx = InpxLibraryIndex(db_path)
            info = idx.build_index(inpx_path)
            self.assertEqual(info["collection_name"], "Flibusta Test")
            self.assertEqual(info["version"], "20261127")
            self.assertEqual(info["total_books"], 2)

            res = idx.search(query="", hide_deleted=False)
            self.assertEqual(res["total"], 2)
            titles = {b["title"]: b for b in res["items"]}
            self.assertEqual(titles["Ночной дозор"]["author"], "Лукьяненко Сергей Васильевич")
            self.assertEqual(titles["Ночной дозор"]["inp_name"], "fb2-001")
            self.assertEqual(titles["Удалённая книга"]["deleted"], 1)

            # Custom structure.info with FOLDER field
            inpx_custom = os.path.join(td, "custom.inpx")
            db_custom = os.path.join(td, "custom.sqlite")
            custom_row = INP_SEP.join([
                "Herbert,Frank:", "Dune", "Dune Chronicles", "1",
                "dune_1", "fb2", "sub/dune.zip", "en", "0",
            ])
            _build_inpx(
                inpx_custom,
                {"pack.inp": [custom_row]},
                structure_info="AUTHOR;TITLE;SERIES;SERNO;FILE;EXT;FOLDER;LANG;DEL\r\n",
            )
            cidx = InpxLibraryIndex(db_custom)
            cinfo = cidx.build_index(inpx_custom)
            self.assertEqual(cinfo["total_books"], 1)
            cres = cidx.search(query="Dune", hide_deleted=True)
            self.assertEqual(cres["items"][0]["folder"], "sub/dune.zip")
            self.assertEqual(cres["items"][0]["lang"], "en")

    def test_sqlite_index_search_filters_and_series_books(self):
        with tempfile.TemporaryDirectory() as td:
            inpx_path = os.path.join(td, "lib.inpx")
            db_path = os.path.join(td, "cache.sqlite")
            rows = [
                _make_default_inp_row(
                    "Стругацкий,Аркадий,:Стругацкий,Борис,:", "sf:", "Пикник на обочине",
                    "Мир Полудня", "1", "10", size="300000", deleted="0", lang="ru",
                ),
                _make_default_inp_row(
                    "Стругацкий,Аркадий,:Стругацкий,Борис,:", "sf:", "Трудно быть богом",
                    "Мир Полудня", "2", "11", size="350000", deleted="0", lang="ru",
                ),
                _make_default_inp_row(
                    "Стругацкий,Аркадий,:", "sf:", "Старая версия",
                    "Мир Полудня", "3", "12", size="100000", deleted="1", lang="ru",
                ),
                _make_default_inp_row(
                    "Herbert,Frank,:", "sf:", "Dune",
                    "Dune", "1", "20", size="700000", deleted="0", lang="en",
                ),
            ]
            _build_inpx(inpx_path, {"fb2-01.inp": rows})

            idx = InpxLibraryIndex(db_path)
            self.assertTrue(idx.needs_reindex(inpx_path))
            res_build = idx.build_index(inpx_path)
            self.assertEqual(res_build["total_books"], 4)
            self.assertFalse(idx.needs_reindex(inpx_path))

            # Hide deleted by default
            res_all = idx.search(query="", hide_deleted=True)
            self.assertEqual(res_all["total"], 3)

            res_with_del = idx.search(query="", hide_deleted=False)
            self.assertEqual(res_with_del["total"], 4)

            # Field-specific search
            res_author = idx.search(query="Стругацкий", field="author", hide_deleted=True)
            self.assertEqual(res_author["total"], 2)

            res_title = idx.search(query="Пикник", field="title", hide_deleted=True)
            self.assertEqual(res_title["total"], 1)
            self.assertEqual(res_title["items"][0]["file"], "10")

            # Language filter
            res_en = idx.search(query="", lang="en", hide_deleted=True)
            self.assertEqual(res_en["total"], 1)
            self.assertEqual(res_en["items"][0]["title"], "Dune")

            # Series lookup ordered by serno
            series_books = idx.get_series_books("Мир Полудня", author_hint="Стругацкий Аркадий", hide_deleted=True)
            self.assertEqual([b["serno"] for b in series_books], ["1", "2"])

    def test_resolve_book_source_zip_folder_unpacked_and_traversal_guard(self):
        with tempfile.TemporaryDirectory() as td:
            inpx_path = os.path.join(td, "lib.inpx")
            open(inpx_path, "wb").close()

            # 1. ZIP named after inp_name
            zip_by_inp = os.path.join(td, "fb2-001.zip")
            with zipfile.ZipFile(zip_by_inp, "w") as zf:
                zf.writestr("1001.fb2", _make_sample_fb2("Из архива по inp"))
            src1 = resolve_book_source(inpx_path, {"inp_name": "fb2-001", "file": "1001", "ext": "fb2", "folder": ""})
            self.assertIsNotNone(src1)
            self.assertEqual(os.path.realpath(src1["path"]), os.path.realpath(zip_by_inp))
            self.assertEqual(src1["archive_entry"], "1001.fb2")

            # 2. ZIP in FOLDER column
            sub_dir = os.path.join(td, "pack")
            os.makedirs(sub_dir, exist_ok=True)
            zip_by_folder = os.path.join(sub_dir, "books.zip")
            with zipfile.ZipFile(zip_by_folder, "w") as zf:
                zf.writestr("nested/2002.fb2", _make_sample_fb2("Из FOLDER"))
            src2 = resolve_book_source(
                inpx_path,
                {"inp_name": "other", "file": "2002", "ext": "fb2", "folder": "pack/books.zip"},
            )
            self.assertIsNotNone(src2)
            self.assertEqual(os.path.realpath(src2["path"]), os.path.realpath(zip_by_folder))
            self.assertEqual(src2["archive_entry"], "nested/2002.fb2")

            # 3. Unpacked fb2 file
            unpacked = os.path.join(td, "3003.fb2")
            with open(unpacked, "wb") as fh:
                fh.write(_make_sample_fb2("Распакованная"))
            src3 = resolve_book_source(inpx_path, {"inp_name": "missing_zip", "file": "3003", "ext": "fb2", "folder": ""})
            self.assertIsNotNone(src3)
            self.assertEqual(os.path.realpath(src3["path"]), os.path.realpath(unpacked))
            self.assertIsNone(src3["archive_entry"])

            # 4. Path traversal outside INPX directory must be rejected
            src_bad = resolve_book_source(
                inpx_path,
                {"inp_name": "../escape", "file": "escape", "ext": "fb2", "folder": "../escape.zip"},
            )
            self.assertIsNone(src_bad)

    def test_file_import_worker_explicit_entries_and_main_window_toggle(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from core.workers import FileImportWorker
        import fbc_gui
        from ui.controllers.library_controller import PAGE_LIBRARY_INDEX

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as td:
            zpath = os.path.join(td, "fb2-01.zip")
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("555.fb2", _make_sample_fb2("Книга из библиотеки", "Петров", "Пётр"))

            results = []
            worker = FileImportWorker(
                filepaths=[],
                existing_keys=set(),
                explicit_entries=[{"path": zpath, "archive_entry": "555.fb2", "display_name": "fb2-01.zip / 555.fb2"}],
            )
            worker.finished_import.connect(lambda items, cancelled: results.append((items, cancelled)))
            worker.run()
            self.assertEqual(len(results), 1)
            items, cancelled = results[0]
            self.assertFalse(cancelled)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["archive_entry"], "555.fb2")
            self.assertEqual(items[0]["meta"]["title"], "Книга из библиотеки")
            self.assertEqual(items[0]["meta"]["last"], "Петров")

        with (
            patch.object(fbc_gui.MainWindow, "_ensure_fbc_on_startup", lambda self, *a, **kw: None),
            patch.object(fbc_gui.MainWindow, "_schedule_startup_update_check", lambda self, *a, **kw: None),
        ):
            win = fbc_gui.MainWindow()
            try:
                with patch.object(win, "save_app_settings", lambda: None):
                    # По умолчанию вкладка скрыта
                    self.assertFalse(win.is_library_enabled())
                    self.assertTrue(win.nav_buttons[PAGE_LIBRARY_INDEX].isHidden())

                    # Включаем — вкладка появляется
                    win.on_library_enabled_changed("true")
                    self.assertTrue(win.is_library_enabled())
                    self.assertFalse(win.nav_buttons[PAGE_LIBRARY_INDEX].isHidden())

                    # Переключаемся на библиотеку и выключаем — возвращается на Конвертер
                    win.switch_page(PAGE_LIBRARY_INDEX)
                    self.assertEqual(win.pages.currentIndex(), PAGE_LIBRARY_INDEX)
                    win.on_library_enabled_changed("false")
                    self.assertTrue(win.nav_buttons[PAGE_LIBRARY_INDEX].isHidden())
                    self.assertEqual(win.pages.currentIndex(), 0)
            finally:
                win.close()
                app.processEvents()


if __name__ == "__main__":
    unittest.main()

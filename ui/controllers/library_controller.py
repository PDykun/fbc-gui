"""Контроллер вкладки локальной библиотеки INPX в стиле freeLib."""

from collections import OrderedDict
import html
import os
from urllib.parse import unquote

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import QFileDialog, QListWidgetItem, QMenu, QTreeWidgetItem

from core.fb2_genres import get_genre_label
from core.i18n import tr
from core.inpx_library import InpxLibraryIndex, load_book_preview_details, resolve_book_source
from core.logger import get_logger
from core.workers import BackgroundTaskWorker, InpxIndexWorker
from ui.dialogs import ImportProgressDialog, show_themed_message

logger = get_logger("app")

PAGE_LIBRARY_INDEX = 5

_ROLE_KIND = Qt.ItemDataRole.UserRole + 1
_ROLE_BOOK = Qt.ItemDataRole.UserRole + 2
_ROLE_ENTITY = Qt.ItemDataRole.UserRole + 3


def _format_book_size(size_bytes):
    try:
        b = int(size_bytes or 0)
    except (TypeError, ValueError):
        b = 0
    if b <= 0:
        return "—"
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.0f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    return f"{b / (1024 * 1024 * 1024):.2f} GB"


def _format_rating_stars(rate):
    try:
        r = max(0, min(5, int(rate or 0)))
    except (TypeError, ValueError):
        r = 0
    if r <= 0:
        return "☆☆☆☆☆"
    return "★" * r + "☆" * (5 - r)


def _format_genres_display(raw_genres):
    if not raw_genres:
        return ""
    parts = [p.strip() for p in str(raw_genres).split(",") if p.strip()]
    return ", ".join(get_genre_label(c, tr) for c in parts)


class LibraryController:
    """Контроллер экрана «Библиотека»: INPX-индекс, навигация freeLib, дерево книг и передача в конвертер."""

    def is_library_enabled(self):
        return str(self.app_settings.get("library_enabled", "false")).lower() == "true"

    def _get_library_db_path(self):
        return os.path.join(self.base_dir, "library_cache.sqlite")

    def _get_library_index(self):
        db_path = os.path.abspath(self._get_library_db_path())
        idx = getattr(self, "_lib_index", None)
        if idx is None or idx.db_path != db_path:
            if idx is not None:
                idx.close()
            idx = InpxLibraryIndex(db_path)
            self._lib_index = idx
        return idx

    def _close_library_index(self):
        idx = getattr(self, "_lib_index", None)
        if idx is not None:
            idx.close()
            self._lib_index = None

    def _update_library_nav_visibility(self):
        enabled = self.is_library_enabled()
        btn = getattr(self, "nav_buttons", {}).get(PAGE_LIBRARY_INDEX)
        if btn is not None:
            btn.setVisible(enabled)
        if not enabled and hasattr(self, "pages") and self.pages.currentIndex() == PAGE_LIBRARY_INDEX:
            self.switch_page(0)

    def on_library_enabled_changed(self, val):
        enabled = str(val or "false").lower() == "true"
        self.app_settings["library_enabled"] = "true" if enabled else "false"
        self.save_app_settings()
        self._update_library_nav_visibility()

    def on_library_page_opened(self):
        inpx_path = str(self.app_settings.get("library_inpx_path", "")).strip()
        if hasattr(self, "lib_inpx_path_edit"):
            self.lib_inpx_path_edit.setText(inpx_path)
        if not inpx_path:
            self._set_library_status(tr("library.status_not_configured"))
            self._clear_library_views()
            return
        if not os.path.isfile(inpx_path):
            self._set_library_status(tr("library.status_file_missing", path=inpx_path))
            self._clear_library_views()
            return

        index = self._get_library_index()
        if index.needs_reindex(inpx_path):
            self._start_library_indexing(inpx_path)
        else:
            self._refresh_library_status_from_meta(index.get_meta())
            self._refresh_library_languages()
            self._reload_library_left_list()

    def _set_library_status(self, text):
        if hasattr(self, "lbl_lib_status"):
            self.lbl_lib_status.setText(text)

    def _refresh_library_status_from_meta(self, meta):
        if not meta:
            self._set_library_status(tr("library.status_not_configured"))
            return
        col_name = meta.get("collection_name") or os.path.basename(meta.get("inpx_path", ""))
        total = int(meta.get("total_books") or 0)
        ver = meta.get("version") or ""
        if ver:
            self._set_library_status(tr("library.status_ready_ver", name=col_name, count=total, ver=ver))
        else:
            self._set_library_status(tr("library.status_ready", name=col_name, count=total))

    def _refresh_library_languages(self):
        if not hasattr(self, "lib_lang_combo"):
            return
        cur_data = self.lib_lang_combo.currentData() or "all"
        hide_del = self.chk_lib_hide_deleted.isChecked() if hasattr(self, "chk_lib_hide_deleted") else True
        langs = self._get_library_index().list_languages(hide_deleted=hide_del)
        self.lib_lang_combo.blockSignals(True)
        try:
            self.lib_lang_combo.clear()
            self.lib_lang_combo.addItem(tr("library.lang_all"), "all")
            for code in langs:
                self.lib_lang_combo.addItem(code.upper(), code)
            idx = self.lib_lang_combo.findData(cur_data)
            self.lib_lang_combo.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            self.lib_lang_combo.blockSignals(False)

    def choose_library_inpx_clicked(self):
        cur_path = str(self.app_settings.get("library_inpx_path", "")).strip()
        start_dir = os.path.dirname(cur_path) if (cur_path and os.path.isdir(os.path.dirname(cur_path))) else os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("library.dlg_select_inpx"),
            start_dir,
            tr("library.filter_inpx"),
        )
        if not path:
            return
        self.app_settings["library_inpx_path"] = path
        self.save_app_settings()
        if hasattr(self, "lib_inpx_path_edit"):
            self.lib_inpx_path_edit.setText(path)
        self._start_library_indexing(path)

    def reindex_library_clicked(self):
        inpx_path = str(self.app_settings.get("library_inpx_path", "")).strip()
        if not inpx_path or not os.path.isfile(inpx_path):
            show_themed_message(self, tr("common.warning"), tr("library.warn_no_inpx"), "warning")
            return
        self._start_library_indexing(inpx_path)

    def _start_library_indexing(self, inpx_path):
        existing = getattr(self, "_inpx_index_worker", None)
        if existing is not None:
            try:
                if existing.isRunning():
                    return
            except RuntimeError:
                pass

        # Освобождаем кэшированное read-only соединение перед пересборкой и os.replace (важно для Windows)
        self._close_library_index()
        self._set_library_status(tr("library.status_indexing", name=os.path.basename(inpx_path)))
        dlg = ImportProgressDialog(self)
        dlg.setWindowTitle(tr("library.index_progress_title"))
        dlg.lbl_status.setText(tr("library.status_indexing", name=os.path.basename(inpx_path)))
        self._inpx_progress_dlg = dlg

        worker = InpxIndexWorker(self._get_library_db_path(), inpx_path, parent=self)
        self._inpx_index_worker = worker
        worker.progress.connect(dlg.update_progress)
        dlg.cancel_requested.connect(self._cancel_inpx_index_worker)
        worker.finished_index.connect(self._on_inpx_index_finished)
        worker.finished.connect(worker.deleteLater)

        self._inpx_dlg_timer = QTimer(self)
        self._inpx_dlg_timer.setSingleShot(True)
        self._inpx_dlg_timer.timeout.connect(self._show_inpx_progress_dialog)
        self._inpx_dlg_timer.start(220)
        worker.start()

    def _cancel_inpx_index_worker(self):
        worker = getattr(self, "_inpx_index_worker", None)
        if worker is not None:
            try:
                worker.cancel()
            except RuntimeError:
                pass

    def _show_inpx_progress_dialog(self):
        worker = getattr(self, "_inpx_index_worker", None)
        dlg = getattr(self, "_inpx_progress_dlg", None)
        if worker is not None and worker.isRunning() and dlg is not None and not dlg.isVisible():
            dlg.open()

    def _on_inpx_index_finished(self, ok, payload, cancelled):
        self._inpx_index_worker = None
        if getattr(self, "_closing", False):
            return
        timer = getattr(self, "_inpx_dlg_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        dlg = getattr(self, "_inpx_progress_dlg", None)
        if dlg is not None:
            self._inpx_progress_dlg = None
            try:
                dlg.finish_and_close()
                dlg.deleteLater()
            except RuntimeError:
                pass

        if cancelled:
            self._set_library_status(tr("library.status_cancelled"))
            return
        if not ok:
            self._set_library_status(tr("library.status_error", e=payload))
            show_themed_message(self, tr("common.error"), tr("library.err_index", e=payload), "error")
            return

        self._refresh_library_status_from_meta(self._get_library_index().get_meta())
        self._refresh_library_languages()
        self._reload_library_left_list()

    # --- Режимы навигации (Авторы / Серии / Жанры / Поиск) и алфавит ---

    def _get_library_mode(self):
        if hasattr(self, "lib_mode_selector"):
            return self.lib_mode_selector.get() or "authors"
        return "authors"

    def _get_library_lang_and_del(self):
        lang = self.lib_lang_combo.currentData() if hasattr(self, "lib_lang_combo") else "all"
        hide_del = self.chk_lib_hide_deleted.isChecked() if hasattr(self, "chk_lib_hide_deleted") else True
        return (lang or "all"), hide_del

    def on_library_mode_changed(self, mode):
        if hasattr(self, "lib_left_stack"):
            self.lib_left_stack.setCurrentIndex(1 if mode == "search" else 0)
        if hasattr(self, "lib_alpha_container"):
            self.lib_alpha_container.setVisible(mode in ("authors", "series"))

        if mode == "search":
            # В режиме «Поиск» правое дерево пустое, пока пользователь не выполнит поиск
            self._clear_library_book_tree()
            self._clear_library_details()
            if hasattr(self, "lbl_lib_results_info"):
                self.lbl_lib_results_info.setText("")
        else:
            self._reload_library_left_list()

    def on_library_alpha_clicked(self, letter):
        self._lib_alpha_prefix = letter
        for ch, btn in getattr(self, "lib_alpha_buttons", {}).items():
            btn.blockSignals(True)
            btn.setChecked(ch == letter)
            btn.blockSignals(False)
        if self._get_library_mode() not in ("authors", "series") and hasattr(self, "lib_mode_selector"):
            self.lib_mode_selector.set("authors")
            self.on_library_mode_changed("authors")
            return
        self._reload_library_left_list()

    def on_library_left_filter_changed(self, _text=None):
        timer = getattr(self, "_lib_search_timer", None)
        if timer is None:
            parent = self if isinstance(self, QObject) else None
            timer = QTimer(parent)
            timer.setSingleShot(True)
            timer.timeout.connect(self._reload_library_left_list)
            self._lib_search_timer = timer
        timer.start(200)

    def on_library_lang_or_del_changed(self):
        if self._get_library_mode() == "search":
            self.run_library_advanced_search()
        else:
            self._reload_library_left_list()

    def _clear_library_views(self):
        if hasattr(self, "lib_entity_list"):
            self.lib_entity_list.clear()
        self._clear_library_book_tree()
        self._clear_library_details()
        if hasattr(self, "lbl_lib_results_info"):
            self.lbl_lib_results_info.setText("")

    def _clear_library_book_tree(self):
        self._lib_updating_tree = True
        try:
            if hasattr(self, "lib_book_tree"):
                self.lib_book_tree.clear()
        finally:
            self._lib_updating_tree = False
        self.on_library_selection_changed()

    def _clear_library_details(self):
        self._lib_preview_req_id = getattr(self, "_lib_preview_req_id", 0) + 1
        if hasattr(self, "lib_book_details"):
            self.lib_book_details.clear()
        if hasattr(self, "lib_book_cover"):
            self.lib_book_cover.setPixmap(QPixmap())
            self.lib_book_cover.setText(tr("library.cover_placeholder"))

    def _reload_library_left_list(self):
        if not hasattr(self, "lib_entity_list"):
            return
        inpx_path = str(self.app_settings.get("library_inpx_path", "")).strip()
        if not inpx_path or not os.path.isfile(self._get_library_db_path()):
            self._clear_library_views()
            return

        mode = self._get_library_mode()
        if mode == "search":
            return

        lang, hide_del = self._get_library_lang_and_del()
        filter_txt = self.lib_left_filter_edit.text().strip() if hasattr(self, "lib_left_filter_edit") else ""
        prefix = getattr(self, "_lib_alpha_prefix", "*")
        if filter_txt:
            # Когда пользователь явно ввёл текст в «Фильтр», ищем по всей базе независимо от выбранной буквы
            prefix_eff = "*"
        else:
            prefix_eff = prefix

        index = self._get_library_index()
        self.lib_entity_list.blockSignals(True)
        try:
            self.lib_entity_list.clear()
            if mode == "authors":
                rows = index.list_authors(prefix=prefix_eff, filter_text=filter_txt, lang=lang, hide_deleted=hide_del)
                for row in rows:
                    it = QListWidgetItem(f"{row['name']} ({row['count']})")
                    it.setData(_ROLE_ENTITY, ("author", row["id"], row["name"]))
                    self.lib_entity_list.addItem(it)
            elif mode == "series":
                rows = index.list_series(prefix=prefix_eff, filter_text=filter_txt, lang=lang, hide_deleted=hide_del)
                for row in rows:
                    it = QListWidgetItem(f"{row['name']} ({row['count']})")
                    it.setData(_ROLE_ENTITY, ("series", row["name"], row["name"]))
                    self.lib_entity_list.addItem(it)
            elif mode == "genres":
                rows = index.list_genres(lang=lang, hide_deleted=hide_del)
                flt_low = filter_txt.lower()
                items_named = []
                for row in rows:
                    label = get_genre_label(row["code"], tr)
                    if flt_low and flt_low not in label.lower() and flt_low not in row["code"].lower():
                        continue
                    items_named.append((label, row["code"], row["count"]))
                items_named.sort(key=lambda x: x[0].lower())
                for label, code, cnt in items_named:
                    it = QListWidgetItem(f"{label} ({cnt})")
                    it.setData(_ROLE_ENTITY, ("genre", code, label))
                    self.lib_entity_list.addItem(it)
        finally:
            self.lib_entity_list.blockSignals(False)

        if self.lib_entity_list.count() > 0:
            self.lib_entity_list.setCurrentRow(0)
        else:
            self._clear_library_book_tree()
            self._clear_library_details()
            if hasattr(self, "lbl_lib_results_info"):
                self.lbl_lib_results_info.setText(tr("library.results_count", total=0))

    def on_library_entity_selected(self, current, _previous=None):
        if current is None:
            self._clear_library_book_tree()
            self._clear_library_details()
            return
        payload = current.data(_ROLE_ENTITY)
        if not payload:
            return
        kind, key, _label = payload
        lang, hide_del = self._get_library_lang_and_del()
        index = self._get_library_index()

        if kind == "author":
            books = index.get_books_by_author(key, lang=lang, hide_deleted=hide_del)
            self._populate_library_book_tree(books, total=len(books), truncated=False)
        elif kind == "series":
            books = index.get_books_by_series(key, lang=lang, hide_deleted=hide_del)
            self._populate_library_book_tree(books, total=len(books), truncated=False)
        elif kind == "genre":
            res = index.get_books_by_genre(key, lang=lang, hide_deleted=hide_del)
            self._populate_library_book_tree(res["items"], total=res["total"], truncated=res["truncated"])

    def run_library_advanced_search(self):
        if not os.path.isfile(self._get_library_db_path()):
            self._clear_library_book_tree()
            return
        title = self.lib_adv_title_edit.text().strip() if hasattr(self, "lib_adv_title_edit") else ""
        author = self.lib_adv_author_edit.text().strip() if hasattr(self, "lib_adv_author_edit") else ""
        series = self.lib_adv_series_edit.text().strip() if hasattr(self, "lib_adv_series_edit") else ""
        genre = self.lib_adv_genre_edit.text().strip() if hasattr(self, "lib_adv_genre_edit") else ""
        if not (title or author or series or genre):
            self._clear_library_book_tree()
            self._clear_library_details()
            if hasattr(self, "lbl_lib_results_info"):
                self.lbl_lib_results_info.setText("")
            return

        lang, hide_del = self._get_library_lang_and_del()
        res = self._get_library_index().search_advanced(
            title=title,
            author=author,
            series=series,
            genre=genre,
            lang=lang,
            hide_deleted=hide_del,
        )
        self._populate_library_book_tree(res["items"], total=res["total"], truncated=res["truncated"])

    def clear_library_advanced_search(self):
        for attr in ("lib_adv_title_edit", "lib_adv_author_edit", "lib_adv_series_edit", "lib_adv_genre_edit"):
            ed = getattr(self, attr, None)
            if ed is not None:
                ed.clear()
        self._clear_library_book_tree()
        self._clear_library_details()
        if hasattr(self, "lbl_lib_results_info"):
            self.lbl_lib_results_info.setText("")

    # --- Дерево книг (Автор -> Серия -> Книги) ---

    def _populate_library_book_tree(self, books, *, total=None, truncated=False):
        if not hasattr(self, "lib_book_tree"):
            return
        self._lib_updating_tree = True
        first_book_item = None
        try:
            self.lib_book_tree.clear()
            bold_font = QFont()
            bold_font.setBold(True)

            # Группировка: Автор -> Серия (или None) -> список книг
            by_author = OrderedDict()
            for book in books:
                a_name = (book.get("author") or "").strip() or tr("converter.omnibus_unknown_author")
                s_name = (book.get("series") or "").strip()
                by_author.setdefault(a_name, OrderedDict()).setdefault(s_name, []).append(book)

            for a_name, series_map in by_author.items():
                a_item = QTreeWidgetItem(self.lib_book_tree)
                a_item.setText(0, a_name)
                a_item.setFont(0, bold_font)
                a_item.setFlags(a_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                a_item.setCheckState(0, Qt.CheckState.Unchecked)
                a_item.setData(0, _ROLE_KIND, "author")

                for s_name, s_books in series_map.items():
                    parent_node = a_item
                    if s_name:
                        s_item = QTreeWidgetItem(a_item)
                        s_item.setText(0, s_name)
                        s_item.setFont(0, bold_font)
                        s_item.setFlags(s_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        s_item.setCheckState(0, Qt.CheckState.Unchecked)
                        s_item.setData(0, _ROLE_KIND, "series")
                        s_item.setData(0, _ROLE_BOOK, s_books[0])
                        parent_node = s_item

                    for book in s_books:
                        b_item = QTreeWidgetItem(parent_node)
                        b_item.setText(0, book.get("title") or book.get("file") or "")
                        b_item.setText(1, book.get("serno") or "")
                        b_item.setText(2, _format_book_size(book.get("size")))
                        b_item.setText(3, _format_rating_stars(book.get("librate")))
                        b_item.setText(4, book.get("date") or "")
                        b_item.setText(5, _format_genres_display(book.get("genres")))
                        b_item.setFlags(b_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        b_item.setCheckState(0, Qt.CheckState.Unchecked)
                        b_item.setData(0, _ROLE_KIND, "book")
                        b_item.setData(0, _ROLE_BOOK, book)
                        if first_book_item is None:
                            first_book_item = b_item

            self.lib_book_tree.expandAll()
        finally:
            self._lib_updating_tree = False

        if hasattr(self, "lbl_lib_results_info"):
            tot_val = len(books) if total is None else int(total)
            if truncated:
                self.lbl_lib_results_info.setText(
                    tr("library.results_truncated", shown=len(books), total=tot_val)
                )
            else:
                self.lbl_lib_results_info.setText(tr("library.results_count", total=tot_val))

        if first_book_item is not None:
            self.lib_book_tree.setCurrentItem(first_book_item)
        else:
            self._clear_library_details()
        self.on_library_selection_changed()

    def _set_subtree_check_state(self, item, state):
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            self._set_subtree_check_state(child, state)

    def _update_parent_check_state(self, item):
        parent = item.parent()
        if parent is None:
            return
        checked = 0
        unchecked = 0
        for i in range(parent.childCount()):
            st = parent.child(i).checkState(0)
            if st == Qt.CheckState.Checked:
                checked += 1
            elif st == Qt.CheckState.Unchecked:
                unchecked += 1
        if checked == parent.childCount():
            parent.setCheckState(0, Qt.CheckState.Checked)
        elif unchecked == parent.childCount():
            parent.setCheckState(0, Qt.CheckState.Unchecked)
        else:
            parent.setCheckState(0, Qt.CheckState.PartiallyChecked)
        self._update_parent_check_state(parent)

    def on_library_tree_item_changed(self, item, column):
        if getattr(self, "_lib_updating_tree", False) or column != 0 or item is None:
            return
        self._lib_updating_tree = True
        try:
            state = item.checkState(0)
            if state != Qt.CheckState.PartiallyChecked and item.childCount() > 0:
                self._set_subtree_check_state(item, state)
            self._update_parent_check_state(item)
        finally:
            self._lib_updating_tree = False
        self.on_library_selection_changed()

    def _collect_checked_books(self):
        if not hasattr(self, "lib_book_tree"):
            return []
        books = []
        seen_ids = set()

        def _walk(node):
            if node.data(0, _ROLE_KIND) == "book" and node.checkState(0) == Qt.CheckState.Checked:
                bk = node.data(0, _ROLE_BOOK)
                if bk and bk.get("id") not in seen_ids:
                    seen_ids.add(bk.get("id"))
                    books.append(bk)
            for i in range(node.childCount()):
                _walk(node.child(i))

        root = self.lib_book_tree.invisibleRootItem()
        for i in range(root.childCount()):
            _walk(root.child(i))
        return books

    def _collect_books_from_item(self, item):
        books = []
        seen_ids = set()

        def _walk(node):
            if node.data(0, _ROLE_KIND) == "book":
                bk = node.data(0, _ROLE_BOOK)
                if bk and bk.get("id") not in seen_ids:
                    seen_ids.add(bk.get("id"))
                    books.append(bk)
            for i in range(node.childCount()):
                _walk(node.child(i))

        if item is not None:
            _walk(item)
        return books

    def _get_target_library_books(self):
        """Возвращает отмеченные чекбоксами книги; если ничего не отмечено — выделенные строки дерева."""
        checked = self._collect_checked_books()
        if checked:
            return checked
        if not hasattr(self, "lib_book_tree"):
            return []
        books = []
        seen_ids = set()
        for item in self.lib_book_tree.selectedItems():
            for bk in self._collect_books_from_item(item):
                if bk.get("id") not in seen_ids:
                    seen_ids.add(bk.get("id"))
                    books.append(bk)
        return books

    def on_library_selection_changed(self):
        if not hasattr(self, "btn_lib_add_to_converter"):
            return
        cnt = len(self._get_target_library_books())
        self.btn_lib_add_to_converter.setEnabled(cnt > 0)
        if cnt > 0:
            self.btn_lib_add_to_converter.setText(tr("library.btn_add_to_converter", count=cnt))
        else:
            self.btn_lib_add_to_converter.setText(tr("library.btn_add_to_converter_empty"))

    # --- Нижняя карточка описания книги и обложки ---

    def on_library_tree_current_changed(self, current, _previous=None):
        if current is None or current.data(0, _ROLE_KIND) != "book":
            return
        book = current.data(0, _ROLE_BOOK)
        if not book:
            return
        try:
            self._render_book_details_html(book, details=None)
            self._schedule_book_details_load(book)
        except Exception as e:
            logger.error("Ошибка отображения карточки книги: %s", e)

    def _render_book_details_html(self, book, details=None):
        if not hasattr(self, "lib_book_details"):
            return
        title = html.escape(book.get("title") or book.get("file") or "")
        authors_raw = [a.strip() for a in str(book.get("author") or "").split(",") if a.strip()]
        authors_html = "; ".join(
            f'<a href="author:{html.escape(a, quote=True)}" style="color:#4da3ff;text-decoration:none;">{html.escape(a)}</a>'
            for a in authors_raw
        ) or "—"

        genres_raw = [g.strip() for g in str(book.get("genres") or "").split(",") if g.strip()]
        genres_html = "; ".join(
            f'<a href="genre:{html.escape(g, quote=True)}" style="color:#4da3ff;text-decoration:none;">{html.escape(get_genre_label(g, tr))}</a>'
            for g in genres_raw
        ) or "—"

        ser = (book.get("series") or "").strip()
        serno = (book.get("serno") or "").strip()
        if ser:
            ser_label = f"{ser} #{serno}" if serno else ser
            series_html = f'<a href="series:{html.escape(ser, quote=True)}" style="color:#4da3ff;text-decoration:none;">{html.escape(ser_label)}</a>'
        else:
            series_html = "—"

        if details is None:
            anno_html = f'<p style="opacity:0.65;">{html.escape(tr("library.details_loading"))}</p>'
        elif details.get("annotation"):
            paras = [html.escape(p.strip()) for p in details["annotation"].splitlines() if p.strip()]
            anno_html = "".join(f"<p style='margin:6px 0;line-height:1.45;'>{p}</p>" for p in paras)
        else:
            anno_html = f'<p style="opacity:0.6;">{html.escape(tr("library.details_no_annotation"))}</p>'

        file_path_str = ""
        archive_size_str = ""
        if details and details.get("found"):
            file_path_str = details.get("path") or ""
            if details.get("archive_size"):
                archive_size_str = _format_book_size(details["archive_size"])
        else:
            file_path_str = book.get("folder") or (f"{book.get('inp_name')}.zip" if book.get("inp_name") else "")

        fname = f"{book.get('file') or ''}.{book.get('ext') or 'fb2'}"
        date_str = book.get("date") or "—"
        size_str = _format_book_size(book.get("size"))

        footer_lines = [
            f"<b>{html.escape(tr('library.detail_path'))}</b> {html.escape(file_path_str or '—')}",
            f"<b>{html.escape(tr('library.detail_filename'))}</b> {html.escape(fname)} ({html.escape(size_str)})",
        ]
        if archive_size_str:
            footer_lines.append(f"<b>{html.escape(tr('library.detail_archive_size'))}</b> {html.escape(archive_size_str)}")
        footer_lines.append(f"<b>{html.escape(tr('library.detail_date'))}</b> {html.escape(date_str)}")

        doc_html = (
            f"<h2 style='margin:0 0 8px 0;font-size:18px;'>{title}</h2>"
            f"<div style='margin-bottom:8px;line-height:1.45;'>"
            f"<b>{html.escape(tr('library.detail_author'))}</b> {authors_html}<br>"
            f"<b>{html.escape(tr('library.detail_genre'))}</b> {genres_html}<br>"
            f"<b>{html.escape(tr('library.detail_series'))}</b> {series_html}"
            f"</div>"
            f"{anno_html}"
            f"<div style='margin-top:10px;padding:8px 10px;border-radius:6px;"
            f"background:rgba(127,127,127,0.14);font-size:12px;line-height:1.45;'>"
            f"{'<br>'.join(footer_lines)}"
            f"</div>"
        )
        self.lib_book_details.setHtml(doc_html)

    def _schedule_book_details_load(self, book):
        self._lib_pending_preview_book = dict(book)
        if hasattr(self, "lib_book_cover"):
            self.lib_book_cover.setPixmap(QPixmap())
            self.lib_book_cover.setText(tr("library.cover_loading"))
        timer = getattr(self, "_lib_preview_timer", None)
        if timer is None:
            parent = self if isinstance(self, QObject) else None
            timer = QTimer(parent)
            timer.setSingleShot(True)
            timer.timeout.connect(self._flush_book_details_load)
            self._lib_preview_timer = timer
        timer.start(120)

    def _flush_book_details_load(self):
        book = getattr(self, "_lib_pending_preview_book", None)
        if book and not getattr(self, "_closing", False):
            self._load_book_details_async(book)

    def _load_book_details_async(self, book):
        inpx_path = str(self.app_settings.get("library_inpx_path", "")).strip()
        req_id = getattr(self, "_lib_preview_req_id", 0) + 1
        self._lib_preview_req_id = req_id

        if not inpx_path or not os.path.isfile(inpx_path):
            self._apply_book_preview_result(req_id, book, {"found": False})
            return

        workers = getattr(self, "_lib_preview_workers", None)
        if workers is None:
            workers = set()
            self._lib_preview_workers = workers

        worker = BackgroundTaskWorker(lambda p=inpx_path, b=dict(book): load_book_preview_details(p, b), parent=self)
        workers.add(worker)
        self._lib_preview_worker = worker
        worker.finished_task.connect(
            lambda res, err, rid=req_id, bk=book: self._apply_book_preview_result(rid, bk, res if err is None else {"found": False})
        )
        def _cleanup_worker(w=worker):
            try:
                self._lib_preview_workers.discard(w)
            except Exception:
                pass
            if getattr(self, "_lib_preview_worker", None) is w:
                self._lib_preview_worker = None
            try:
                w.deleteLater()
            except RuntimeError:
                pass
        worker.finished.connect(_cleanup_worker)
        worker.start()

    def _apply_book_preview_result(self, req_id, book, details):
        if getattr(self, "_closing", False) or req_id != getattr(self, "_lib_preview_req_id", 0):
            return
        try:
            self._render_book_details_html(book, details=details or {"found": False})
            if not hasattr(self, "lib_book_cover"):
                return
            cover_bytes = (details or {}).get("cover_bytes")
            if cover_bytes:
                pm = QPixmap()
                if pm.loadFromData(cover_bytes):
                    target_w = max(140, self.lib_book_cover.width() - 8)
                    target_h = max(180, self.lib_book_cover.height() - 8)
                    self.lib_book_cover.setPixmap(
                        pm.scaled(target_w, target_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    )
                    self.lib_book_cover.setText("")
                    return
            self.lib_book_cover.setPixmap(QPixmap())
            self.lib_book_cover.setText(tr("library.cover_missing"))
        except Exception as e:
            logger.error("Ошибка обновления карточки предпросмотра книги: %s", e)

    def on_library_detail_link_clicked(self, url):
        scheme = url.scheme()
        val = unquote(url.path() or "")
        if not val:
            return
        if scheme == "author":
            self._jump_to_library_entity("authors", val)
        elif scheme == "series":
            self._jump_to_library_entity("series", val)
        elif scheme == "genre":
            self._jump_to_library_entity("genres", get_genre_label(val, tr))

    def _jump_to_library_entity(self, mode, filter_value):
        if hasattr(self, "lib_mode_selector"):
            self.lib_mode_selector.set(mode)
        if hasattr(self, "lib_left_stack"):
            self.lib_left_stack.setCurrentIndex(0)
        if hasattr(self, "lib_alpha_container"):
            self.lib_alpha_container.setVisible(mode in ("authors", "series"))
        if hasattr(self, "lib_left_filter_edit"):
            self.lib_left_filter_edit.blockSignals(True)
            self.lib_left_filter_edit.setText(filter_value)
            self.lib_left_filter_edit.blockSignals(False)
        self._reload_library_left_list()

    # --- Контекстное меню и передача книг в конвертер ---

    def on_library_tree_double_clicked(self, item, _column):
        if item is not None and item.data(0, _ROLE_KIND) == "book":
            book = item.data(0, _ROLE_BOOK)
            if book:
                self._send_library_books_to_converter([book])

    def on_library_tree_context_menu(self, pos):
        item = self.lib_book_tree.itemAt(pos)
        if item is None:
            return
        clicked_books = self._collect_books_from_item(item)
        target_books = self._get_target_library_books()
        books_to_add = target_books if len(target_books) > len(clicked_books) else clicked_books
        if not books_to_add:
            return

        ref_book = item.data(0, _ROLE_BOOK) if item.data(0, _ROLE_KIND) in ("book", "series") else books_to_add[0]
        series_name = ((ref_book or {}).get("series") or "").strip()

        menu = QMenu(self)
        if len(books_to_add) == 1:
            act_add = menu.addAction(tr("library.ctx_add_one"))
        else:
            act_add = menu.addAction(tr("library.ctx_add_multi", count=len(books_to_add)))

        act_series = None
        if series_name:
            act_series = menu.addAction(tr("library.ctx_add_series", series=series_name))

        chosen = menu.exec(self.lib_book_tree.viewport().mapToGlobal(pos))
        if chosen == act_add:
            self._send_library_books_to_converter(books_to_add)
        elif act_series is not None and chosen == act_series:
            self.add_library_series_to_converter(ref_book)

    def add_selected_library_books_to_converter(self):
        books = self._get_target_library_books()
        if books:
            self._send_library_books_to_converter(books)

    def add_library_series_to_converter(self, book_row):
        series_name = str((book_row or {}).get("series") or "").strip()
        if not series_name:
            return
        hide_del = self.chk_lib_hide_deleted.isChecked() if hasattr(self, "chk_lib_hide_deleted") else True
        series_books = self._get_library_index().get_series_books(
            series_name,
            author_hint=book_row.get("author") or "",
            hide_deleted=hide_del,
        )
        if series_books:
            self._send_library_books_to_converter(series_books)

    def _send_library_books_to_converter(self, book_rows):
        inpx_path = str(self.app_settings.get("library_inpx_path", "")).strip()
        if not inpx_path or not os.path.isfile(inpx_path):
            show_themed_message(self, tr("common.warning"), tr("library.warn_no_inpx"), "warning")
            return

        resolved = []
        missing = []
        for book in book_rows:
            src = resolve_book_source(inpx_path, book)
            if src is not None:
                resolved.append(src)
            else:
                missing.append(book.get("title") or book.get("file") or "?")

        if not resolved:
            show_themed_message(
                self,
                tr("common.warning"),
                tr("library.err_files_not_found", count=len(missing)),
                "warning",
            )
            return

        # Передаём выбранные книги в очередь конвертера и остаёмся на вкладке «Библиотека»
        self.enqueue_library_entries(resolved)
        if hasattr(self, "lbl_lib_results_info"):
            msg = tr("library.msg_added_to_converter", count=len(resolved))
            if missing:
                msg += "  •  " + tr("library.msg_missing_suffix", missing=len(missing))
            self.lbl_lib_results_info.setText(msg)
        if missing:
            show_themed_message(
                self,
                tr("common.warning"),
                tr("library.warn_partial_missing", added=len(resolved), missing=len(missing)),
                "warning",
            )

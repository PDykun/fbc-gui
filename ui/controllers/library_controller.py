"""Контроллер вкладки локальной библиотеки INPX (индексация, поиск и передача в конвертер)."""

import os

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtWidgets import QFileDialog, QMenu, QTableWidgetItem

from core.i18n import tr
from core.inpx_library import InpxLibraryIndex, resolve_book_source
from core.logger import get_logger
from core.workers import InpxIndexWorker
from ui.dialogs import ImportProgressDialog, show_themed_message

logger = get_logger("app")

PAGE_LIBRARY_INDEX = 5


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
    return f"{b / (1024 * 1024):.1f} MB"


class LibraryController:
    """Контроллер экрана «Библиотека»: подключение INPX, кэш-индексация, поиск и отправка в конвертер."""

    def is_library_enabled(self):
        return str(self.app_settings.get("library_enabled", "false")).lower() == "true"

    def _get_library_db_path(self):
        return os.path.join(self.base_dir, "library_cache.sqlite")

    def _get_library_index(self):
        return InpxLibraryIndex(self._get_library_db_path())

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
            self._clear_library_results()
            return
        if not os.path.isfile(inpx_path):
            self._set_library_status(tr("library.status_file_missing", path=inpx_path))
            self._clear_library_results()
            return

        index = self._get_library_index()
        if index.needs_reindex(inpx_path):
            self._start_library_indexing(inpx_path)
        else:
            self._refresh_library_status_from_meta(index.get_meta())
            self.run_library_search()

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
        self.run_library_search()

    def on_library_search_changed(self, _text=None):
        timer = getattr(self, "_lib_search_timer", None)
        if timer is None:
            parent = self if isinstance(self, QObject) else None
            timer = QTimer(parent)
            timer.setSingleShot(True)
            timer.timeout.connect(self.run_library_search)
            self._lib_search_timer = timer
        timer.start(220)

    def on_library_filter_changed(self, *_args):
        self.run_library_search()

    def _clear_library_results(self):
        self._lib_current_rows = []
        if hasattr(self, "lib_table"):
            self.lib_table.setRowCount(0)
        if hasattr(self, "lbl_lib_results_info"):
            self.lbl_lib_results_info.setText("")
        self.on_library_selection_changed()

    def run_library_search(self):
        if not hasattr(self, "lib_table"):
            return
        inpx_path = str(self.app_settings.get("library_inpx_path", "")).strip()
        if not inpx_path or not os.path.isfile(self._get_library_db_path()):
            self._clear_library_results()
            return

        query = self.lib_search_edit.text().strip() if hasattr(self, "lib_search_edit") else ""
        field = self.lib_field_selector.get() if hasattr(self, "lib_field_selector") else "all"
        lang = self.lib_lang_combo.currentData() if hasattr(self, "lib_lang_combo") else "all"
        hide_del = self.chk_lib_hide_deleted.isChecked() if hasattr(self, "chk_lib_hide_deleted") else True

        index = self._get_library_index()
        res = index.search(query=query, field=field, lang=lang or "all", hide_deleted=hide_del, limit=300)
        items = res["items"]
        self._lib_current_rows = items

        self.lib_table.setUpdatesEnabled(False)
        try:
            self.lib_table.setRowCount(len(items))
            for r, book in enumerate(items):
                it_auth = QTableWidgetItem(book.get("author") or "")
                it_auth.setData(Qt.ItemDataRole.UserRole, r)
                self.lib_table.setItem(r, 0, it_auth)
                self.lib_table.setItem(r, 1, QTableWidgetItem(book.get("series") or ""))
                self.lib_table.setItem(r, 2, QTableWidgetItem(book.get("serno") or ""))
                self.lib_table.setItem(r, 3, QTableWidgetItem(book.get("title") or ""))
                self.lib_table.setItem(r, 4, QTableWidgetItem((book.get("lang") or "").upper()))
                self.lib_table.setItem(r, 5, QTableWidgetItem(_format_book_size(book.get("size"))))
                arch = book.get("folder") or (f"{book.get('inp_name')}.zip" if book.get("inp_name") else "")
                self.lib_table.setItem(r, 6, QTableWidgetItem(arch))
        finally:
            self.lib_table.setUpdatesEnabled(True)

        if hasattr(self, "lbl_lib_results_info"):
            if res["truncated"]:
                self.lbl_lib_results_info.setText(
                    tr("library.results_truncated", shown=len(items), total=res["total"])
                )
            else:
                self.lbl_lib_results_info.setText(tr("library.results_count", total=res["total"]))
        self.on_library_selection_changed()

    def _get_selected_library_books(self):
        if not hasattr(self, "lib_table"):
            return []
        rows = sorted({idx.row() for idx in self.lib_table.selectionModel().selectedRows()})
        cur_rows = getattr(self, "_lib_current_rows", [])
        return [cur_rows[r] for r in rows if 0 <= r < len(cur_rows)]

    def on_library_selection_changed(self):
        if not hasattr(self, "btn_lib_add_to_converter"):
            return
        cnt = len(self._get_selected_library_books())
        self.btn_lib_add_to_converter.setEnabled(cnt > 0)
        if cnt > 0:
            self.btn_lib_add_to_converter.setText(tr("library.btn_add_to_converter", count=cnt))
        else:
            self.btn_lib_add_to_converter.setText(tr("library.btn_add_to_converter_empty"))

    def on_library_row_double_clicked(self, index):
        if not index or not index.isValid():
            return
        cur_rows = getattr(self, "_lib_current_rows", [])
        row = index.row()
        if 0 <= row < len(cur_rows):
            self._send_library_books_to_converter([cur_rows[row]])

    def on_library_table_context_menu(self, pos):
        index = self.lib_table.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        selected_rows = sorted({idx.row() for idx in self.lib_table.selectionModel().selectedRows()})
        if row not in selected_rows:
            self.lib_table.selectRow(row)
            selected_rows = [row]

        cur_rows = getattr(self, "_lib_current_rows", [])
        books = [cur_rows[r] for r in selected_rows if 0 <= r < len(cur_rows)]
        if not books:
            return

        clicked_book = cur_rows[row] if 0 <= row < len(cur_rows) else books[0]
        series_name = (clicked_book.get("series") or "").strip()

        menu = QMenu(self)
        if len(books) == 1:
            act_add = menu.addAction(tr("library.ctx_add_one"))
        else:
            act_add = menu.addAction(tr("library.ctx_add_multi", count=len(books)))

        act_series = None
        if series_name:
            act_series = menu.addAction(tr("library.ctx_add_series", series=series_name))

        chosen = menu.exec(self.lib_table.viewport().mapToGlobal(pos))
        if chosen == act_add:
            self._send_library_books_to_converter(books)
        elif act_series is not None and chosen == act_series:
            self.add_library_series_to_converter(clicked_book)

    def add_selected_library_books_to_converter(self):
        books = self._get_selected_library_books()
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

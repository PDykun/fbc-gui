import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QFileDialog, QMenu, QTableWidgetItem

from core.config import DEFAULT_OUTPUT_FORMAT
from core.cover_studio import CoverSpec
from core.fb2_genres import normalize_genre_list
from core.fb2_processor import (
    COVER_PREVIEW_SIZE,
    book_matches_filter,
    copy_meta_dict,
    execute_organize_fb2_plan,
    merge_fb2_books_to_omnibus,
    find_duplicate_item_ids,
    fit_image_to_cover_size,
    get_book_xml,
    inspect_fb2,
    refresh_book_warnings,
    repair_book_in_source,
    save_book_changes_to_source,
    simulate_fbc_target,
)
from core.i18n import tr
from core.logger import get_logger
from core.undo_commands import (
    RemoveBooksCommand,
    ReorderBooksCommand,
    UpdateBooksCommand,
    snapshot_book_state,
)
from core.workers import BackgroundTaskWorker, FileImportWorker
from ui.dialogs import (
    BatchEditDialog,
    BookEditDialog,
    BookInspectorDialog,
    CoverStudioDialog,
    ImportProgressDialog,
    MetadataLookupDialog,
    OrganizeBooksDialog,
    apply_cover_studio_to_books,
    show_themed_message,
)

logger = get_logger("app")


class QueueController:
    """Контроллер таблицы книг, импорта, фильтрации, Undo/Redo, обложек и метаданных."""

    def _repopulate_table_from_files_data(self, selected_id=None):
        if not hasattr(self, "table"):
            return
        self._updating_table_items = True
        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        try:
            self.table.setRowCount(0)
            sel_row = -1
            for item_id, data in self.files_data.items():
                data["item_id"] = item_id
                row = self.table.rowCount()
                self.table.insertRow(row)
                meta = data["meta"]
                it_file = QTableWidgetItem(data.get("display_name") or os.path.basename(data["path"]))
                it_file.setData(Qt.ItemDataRole.UserRole, item_id)
                it_file.setFlags(it_file.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 0, it_file)
                self.table.setItem(row, 1, QTableWidgetItem(meta["last"]))
                self.table.setItem(row, 2, QTableWidgetItem(meta["first"]))
                self.table.setItem(row, 3, QTableWidgetItem(meta["mid"]))
                self.table.setItem(row, 4, QTableWidgetItem(meta["series"]))
                self.table.setItem(row, 5, QTableWidgetItem(meta["num"]))
                self.table.setItem(row, 6, QTableWidgetItem(meta["title"]))
                it_target = QTableWidgetItem(self.simulate_fbc_target(meta))
                it_target.setFlags(it_target.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 7, it_target)
                self.table.setItem(row, 8, self._make_status_item(data.get("status", ""), data.get("status_error", ""), data.get("warnings")))
                if item_id == selected_id:
                    sel_row = row
            if sel_row >= 0:
                self.table.selectRow(sel_row)
            elif self.table.rowCount() > 0:
                self.table.selectRow(0)
        finally:
            self.table.setSortingEnabled(was_sorting)
            self._updating_table_items = False
        self._refresh_duplicates_state()
        self.apply_table_filter()
        self.update_header_status()

    def _rebuild_row_index(self):
        index = {}
        if hasattr(self, "table"):
            for r in range(self.table.rowCount()):
                it0 = self.table.item(r, 0)
                if it0 is not None:
                    index[it0.data(Qt.ItemDataRole.UserRole)] = r
        self._row_by_item_id = index
        return index

    def _find_table_row_by_item_id(self, item_id):
        if not hasattr(self, "table"):
            return None
        cache = getattr(self, "_row_by_item_id", None)
        if isinstance(cache, dict):
            r = cache.get(item_id)
            if r is not None and 0 <= r < self.table.rowCount():
                it0 = self.table.item(r, 0)
                if it0 is not None and it0.data(Qt.ItemDataRole.UserRole) == item_id:
                    return r
        return self._rebuild_row_index().get(item_id)

    def _refresh_all_target_filenames(self):
        if not hasattr(self, "table"):
            return
        self._updating_table_items = True
        row_index = {}
        try:
            for r in range(self.table.rowCount()):
                it = self.table.item(r, 0)
                if not it:
                    continue
                item_id = it.data(Qt.ItemDataRole.UserRole)
                row_index[item_id] = r
                data = self.files_data.get(item_id)
                if data:
                    it_target = QTableWidgetItem(self.simulate_fbc_target(data['meta']))
                    it_target.setFlags(it_target.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(r, 7, it_target)
            self._row_by_item_id = row_index
        finally:
            self._updating_table_items = False

    def _refresh_filename_builder_preview(self):
        sample_meta = next(iter(self.files_data.values()))["meta"] if self.files_data else None
        out_fmt = self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT)
        if hasattr(self, "filename_builder"):
            self.filename_builder.set_context(output_format=out_fmt, sample_meta=sample_meta)
        if hasattr(self, "title_template_builder"):
            self.title_template_builder.set_context(output_format=out_fmt, sample_meta=sample_meta)

    def render_cover_preview(self, img_bytes, is_modified=False):
        if not img_bytes:
            self.cover_preview_lbl.setText(tr("converter.cover_missing"))
            self.cover_preview_lbl.setPixmap(QPixmap())
            self.cover_info_label.setText(tr("converter.cover_size_empty"))
            return

        pixmap = QPixmap()
        pixmap.loadFromData(img_bytes)
        scaled = pixmap.scaled(
            COVER_PREVIEW_SIZE[0], COVER_PREVIEW_SIZE[1],
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.cover_preview_lbl.setPixmap(scaled)
        status = tr("converter.cover_modified") if is_modified else ""
        self.cover_info_label.setText(tr("converter.cover_size", w=pixmap.width(), h=pixmap.height(), status=status))

    def _format_status_text(self, status_code):
        mapping = {
            "running": tr("converter.status_running"),
            "ok": tr("converter.status_ok"),
            "error": tr("converter.status_error"),
            "cancelled": tr("converter.status_cancelled"),
            "skipped": tr("converter.status_skipped"),
        }
        return mapping.get(status_code or "", "")

    def _make_status_item(self, status_code="", error_msg="", warnings=None, is_duplicate=False):
        txt = self._format_status_text(status_code)
        tooltip_parts = [str(error_msg)] if error_msg else []
        if not status_code:
            if warnings:
                txt = tr("converter.status_warnings", count=len(warnings))
                tooltip_parts.extend(f"⚠ {tr(f'inspector.warn_{code}', count=1)}" for code in warnings)
            elif is_duplicate:
                txt = tr("converter.status_duplicate")
            if is_duplicate:
                tooltip_parts.append(f"≈ {tr('converter.tooltip_duplicate')}")
        it = QTableWidgetItem(txt)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if tooltip_parts:
            it.setToolTip("\n".join(tooltip_parts))
        return it

    def _refresh_duplicates_state(self):
        dup_ids = find_duplicate_item_ids(self.files_data)
        for iid, data in self.files_data.items():
            data["is_duplicate"] = iid in dup_ids
        if hasattr(self, "btn_remove_duplicates"):
            cnt = len(dup_ids)
            self.btn_remove_duplicates.setText(tr("converter.btn_remove_duplicates", count=cnt))
            self.btn_remove_duplicates.setVisible(cnt > 0)
        if hasattr(self, "table"):
            self._updating_table_items = True
            try:
                for r in range(self.table.rowCount()):
                    it0 = self.table.item(r, 0)
                    if not it0:
                        continue
                    iid = it0.data(Qt.ItemDataRole.UserRole)
                    data = self.files_data.get(iid)
                    if data and not data.get("status"):
                        self.table.setItem(r, 8, self._make_status_item("", "", data.get("warnings"), data.get("is_duplicate", False)))
            finally:
                self._updating_table_items = False
        return dup_ids

    def remove_duplicate_books(self):
        if not hasattr(self, "table"):
            return
        dup_ids = find_duplicate_item_ids(self.files_data)
        if not dup_ids:
            return
        removed_entries = []
        for r in range(self.table.rowCount()):
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            iid = it0.data(Qt.ItemDataRole.UserRole)
            if iid in dup_ids and iid in self.files_data:
                removed_entries.append((r, iid, self.files_data[iid]))
        if removed_entries:
            self.undo_stack.push(
                RemoveBooksCommand(
                    self,
                    removed_entries,
                    tr("converter.undo_remove_duplicates", count=len(removed_entries)),
                )
            )

    def _set_item_status(self, item_id, status_code, error_msg=""):
        data = self.files_data.get(item_id)
        warnings = None
        if data is not None:
            data["status"] = status_code
            data["status_error"] = error_msg
            warnings = data.get("warnings")
        if not hasattr(self, "table"):
            return
        r = self._find_table_row_by_item_id(item_id)
        if r is not None:
            self._updating_table_items = True
            try:
                self.table.setItem(r, 8, self._make_status_item(status_code, error_msg, warnings))
            finally:
                self._updating_table_items = False
        self.apply_table_filter()

    def focus_table_search(self):
        if hasattr(self, "pages") and self.pages.currentIndex() != 0:
            self.switch_page(0)
        if hasattr(self, "search_edit"):
            self.search_edit.setFocus()
            self.search_edit.selectAll()

    def on_table_filter_changed(self, _text=None):
        self.apply_table_filter()

    def on_status_filter_changed(self, val):
        self._table_status_filter = val if val in ("all", "pending", "ok", "error", "warnings") else "all"
        self.apply_table_filter()

    def apply_table_filter(self):
        if not hasattr(self, "table"):
            return
        query = self.search_edit.text() if hasattr(self, "search_edit") else ""
        status_filter = getattr(self, "_table_status_filter", "all")
        total = self.table.rowCount()
        shown = 0
        for r in range(total):
            it0 = self.table.item(r, 0)
            if not it0:
                self.table.setRowHidden(r, False)
                shown += 1
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if data is None:
                self.table.setRowHidden(r, False)
                shown += 1
                continue
            it_target = self.table.item(r, 7)
            target_name = it_target.text() if it_target else ""
            visible = book_matches_filter(data, query=query, status_filter=status_filter, target_name=target_name)
            self.table.setRowHidden(r, not visible)
            if visible:
                shown += 1
        if hasattr(self, "lbl_filter_count"):
            self.lbl_filter_count.setText(tr("converter.filter_count", shown=shown, total=total))
        self._update_convert_selected_button()

    def _update_undo_redo_ui(self, *_args):
        stack = getattr(self, "undo_stack", None)
        if stack is None:
            return
        if hasattr(self, "btn_undo"):
            self.btn_undo.setEnabled(stack.canUndo())
            utxt = stack.undoText()
            self.btn_undo.setToolTip(
                f"{tr('converter.btn_undo')}: {utxt}" if utxt else tr("converter.btn_undo")
            )
        if hasattr(self, "btn_redo"):
            self.btn_redo.setEnabled(stack.canRedo())
            rtxt = stack.redoText()
            self.btn_redo.setToolTip(
                f"{tr('converter.btn_redo')}: {rtxt}" if rtxt else tr("converter.btn_redo")
            )

    def undo_last_action(self):
        if hasattr(self, "undo_stack") and self.undo_stack.canUndo():
            self.undo_stack.undo()

    def redo_last_action(self):
        if hasattr(self, "undo_stack") and self.undo_stack.canRedo():
            self.undo_stack.redo()

    def _populate_table_row(self, row, item_id, data):
        meta = data["meta"]
        it_file = QTableWidgetItem(data.get("display_name") or os.path.basename(data["path"]))
        it_file.setData(Qt.ItemDataRole.UserRole, item_id)
        it_file.setFlags(it_file.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, it_file)
        self.table.setItem(row, 1, QTableWidgetItem(meta.get("last", "")))
        self.table.setItem(row, 2, QTableWidgetItem(meta.get("first", "")))
        self.table.setItem(row, 3, QTableWidgetItem(meta.get("mid", "")))
        self.table.setItem(row, 4, QTableWidgetItem(meta.get("series", "")))
        self.table.setItem(row, 5, QTableWidgetItem(meta.get("num", "")))
        self.table.setItem(row, 6, QTableWidgetItem(meta.get("title", "")))
        it_target = QTableWidgetItem(self.simulate_fbc_target(meta))
        it_target.setFlags(it_target.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 7, it_target)
        self.table.setItem(row, 8, self._make_status_item(data.get("status", ""), data.get("status_error", ""), data.get("warnings")))

    def _apply_book_snapshots(self, pairs):
        if not hasattr(self, "table"):
            return
        row_by_id = {}
        for r in range(self.table.rowCount()):
            it0 = self.table.item(r, 0)
            if it0:
                row_by_id[it0.data(Qt.ItemDataRole.UserRole)] = r

        col_keys = ["last", "first", "mid", "series", "num", "title"]
        self._updating_table_items = True
        try:
            for item_id, snap in pairs:
                data = self.files_data.get(item_id)
                if data is None:
                    continue
                new_meta = copy_meta_dict(snap["meta"])
                data["meta"] = new_meta
                data["cover_bytes"] = snap.get("cover_bytes")
                data["cover_mime"] = snap.get("cover_mime")
                data["cover_modified"] = bool(snap.get("cover_modified", False))
                refresh_book_warnings(data)
                r = row_by_id.get(item_id)
                if r is not None:
                    for idx_c, key in enumerate(col_keys, start=1):
                        cell = self.table.item(r, idx_c)
                        if cell is not None:
                            cell.setText(new_meta.get(key, ""))
                        else:
                            self.table.setItem(r, idx_c, QTableWidgetItem(new_meta.get(key, "")))
                    it_target = QTableWidgetItem(self.simulate_fbc_target(new_meta))
                    it_target.setFlags(it_target.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(r, 7, it_target)
                    if not data.get("status"):
                        self.table.setItem(r, 8, self._make_status_item("", "", data.get("warnings")))
        finally:
            self._updating_table_items = False
        self._refresh_duplicates_state()
        self.apply_table_filter()
        self.on_table_selection_changed()
        self._refresh_filename_builder_preview()

    def _remove_items_by_ids(self, item_ids):
        if not hasattr(self, "table"):
            return
        drop = set(item_ids)
        first_removed_row = None
        self._updating_table_items = True
        try:
            for r in range(self.table.rowCount() - 1, -1, -1):
                it0 = self.table.item(r, 0)
                if it0 and it0.data(Qt.ItemDataRole.UserRole) in drop:
                    first_removed_row = r
                    self.table.removeRow(r)
            for iid in drop:
                self.files_data.pop(iid, None)
            if self.table.rowCount() > 0 and first_removed_row is not None:
                self.table.selectRow(min(first_removed_row, self.table.rowCount() - 1))
        finally:
            self._updating_table_items = False
        self._refresh_duplicates_state()
        self.apply_table_filter()
        self.on_table_selection_changed()
        self.update_header_status()
        self._refresh_filename_builder_preview()

    def _restore_removed_items(self, removed_entries):
        if not hasattr(self, "table"):
            return
        self._updating_table_items = True
        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        try:
            restored_rows = []
            for row_idx, item_id, data in sorted(removed_entries, key=lambda x: x[0]):
                data["item_id"] = item_id
                self.files_data[item_id] = data
                pos = max(0, min(row_idx, self.table.rowCount()))
                self.table.insertRow(pos)
                self._populate_table_row(pos, item_id, data)
                restored_rows.append(pos)
            self.table.clearSelection()
            for r in restored_rows:
                self.table.selectRow(r)
        finally:
            self.table.setSortingEnabled(was_sorting)
            self._updating_table_items = False
        self._refresh_duplicates_state()
        self.apply_table_filter()
        self.on_table_selection_changed()
        self.update_header_status()
        self._refresh_filename_builder_preview()

    def _apply_table_order(self, ordered_ids, selected_ids=None):
        if not hasattr(self, "table"):
            return
        selected_set = set(selected_ids or [])
        existing_order = [iid for iid in ordered_ids if iid in self.files_data]
        remaining = [iid for iid in self.files_data.keys() if iid not in existing_order]
        final_order = existing_order + remaining

        new_files_data = {iid: self.files_data[iid] for iid in final_order}
        self.files_data = new_files_data

        self._updating_table_items = True
        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        try:
            self.table.setRowCount(0)
            selected_rows = []
            for iid in final_order:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self._populate_table_row(row, iid, self.files_data[iid])
                if iid in selected_set:
                    selected_rows.append(row)
            self.table.clearSelection()
            for r in selected_rows:
                self.table.selectRow(r)
        finally:
            if was_sorting:
                self.table.setSortingEnabled(True)
            self._updating_table_items = False
        self.apply_table_filter()
        self.on_table_selection_changed()

    def move_selected_rows(self, delta):
        """Перемещает выбранные видимые строки таблицы вверх (delta=-1) или вниз (delta=+1)."""
        if not hasattr(self, "table") or delta == 0:
            return
        row_count = self.table.rowCount()
        visible_rows = [r for r in range(row_count) if not self.table.isRowHidden(r)]
        selected_rows = sorted({
            idx.row() for idx in self.table.selectionModel().selectedRows()
            if not self.table.isRowHidden(idx.row())
        })
        if not selected_rows or len(visible_rows) < 2:
            return
        vis_pos = {r: i for i, r in enumerate(visible_rows)}
        sel_vis_indices = [vis_pos[r] for r in selected_rows if r in vis_pos]
        if not sel_vis_indices:
            return
        if delta < 0 and sel_vis_indices[0] <= 0:
            return
        if delta > 0 and sel_vis_indices[-1] >= len(visible_rows) - 1:
            return

        before_order = []
        for r in range(row_count):
            it0 = self.table.item(r, 0)
            if it0:
                before_order.append(it0.data(Qt.ItemDataRole.UserRole))
        if len(before_order) != row_count:
            return

        after_order = list(before_order)
        step = -1 if delta < 0 else 1
        ordered_vis = sel_vis_indices if step < 0 else list(reversed(sel_vis_indices))
        selected_ids = [before_order[r] for r in selected_rows]
        for vi in ordered_vis:
            src_row = visible_rows[vi]
            dst_row = visible_rows[vi + step]
            after_order[src_row], after_order[dst_row] = after_order[dst_row], after_order[src_row]

        if before_order != after_order:
            self.undo_stack.push(
                ReorderBooksCommand(
                    self,
                    before_order,
                    after_order,
                    selected_ids=selected_ids,
                    text=tr("converter.undo_move", count=len(selected_ids)),
                )
            )

    def _update_convert_selected_button(self, selected_count=None):
        if not hasattr(self, "btn_convert_selected"):
            return
        if selected_count is None:
            if hasattr(self, "table"):
                selected_count = sum(
                    1 for idx in self.table.selectionModel().selectedRows()
                    if not self.table.isRowHidden(idx.row())
                )
            else:
                selected_count = 0
        self.btn_convert_selected.setEnabled(selected_count > 0)
        if selected_count > 0:
            self.btn_convert_selected.setText(tr("converter.btn_convert_selected", count=selected_count))
        else:
            self.btn_convert_selected.setText(tr("converter.btn_convert_selected_empty"))

    def on_table_selection_changed(self):
        rows = [idx for idx in self.table.selectionModel().selectedRows() if not self.table.isRowHidden(idx.row())]
        self._update_convert_selected_button(len(rows))
        if not rows:
            self.btn_replace_cover.setEnabled(False)
            self.btn_reset_cover.setEnabled(False)
            if hasattr(self, "btn_lookup_online"):
                self.btn_lookup_online.setEnabled(False)
            if hasattr(self, "btn_cover_studio"):
                self.btn_cover_studio.setEnabled(False)
            self.render_cover_preview(None)
            return
        item_id = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        data = self.files_data.get(item_id)
        if data:
            self.btn_replace_cover.setEnabled(True)
            self.btn_reset_cover.setEnabled(data.get('cover_modified', False))
            if hasattr(self, "btn_lookup_online"):
                self.btn_lookup_online.setEnabled(True)
            if hasattr(self, "btn_cover_studio"):
                self.btn_cover_studio.setEnabled(True)
            self.render_cover_preview(data.get('cover_bytes'), data.get('cover_modified', False))

    def replace_selected_cover(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        item_id = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        data = self.files_data.get(item_id)
        if not data:
            return

        img_path, _ = QFileDialog.getOpenFileName(
            self, tr("converter.dlg_select_cover"), "", tr("converter.filter_images")
        )
        if img_path:
            try:
                fitted_bytes, mime_type = fit_image_to_cover_size(img_path)
                before = snapshot_book_state(data)
                after = {
                    **before,
                    "cover_bytes": fitted_bytes,
                    "cover_mime": mime_type,
                    "cover_modified": True,
                }
                self.undo_stack.push(
                    UpdateBooksCommand(
                        self,
                        [{"item_id": item_id, "before": before, "after": after}],
                        tr("converter.undo_cover"),
                    )
                )
            except Exception as e:
                show_themed_message(self, tr("common.error"), tr("converter.err_update_cover", e=e), "error")

    def reset_selected_cover(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        item_id = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        data = self.files_data.get(item_id)
        if not data:
            return
        before = snapshot_book_state(data)
        after = {
            **before,
            "cover_bytes": data.get("orig_cover_bytes"),
            "cover_mime": data.get("orig_cover_mime"),
            "cover_modified": False,
        }
        if before != after:
            self.undo_stack.push(
                UpdateBooksCommand(
                    self,
                    [{"item_id": item_id, "before": before, "after": after}],
                    tr("converter.undo_cover"),
                )
            )

    def on_table_double_click(self, item):
        if item is None or item.column() in (0, 7, 8):
            return
        self.table.editItem(item)

    def on_table_item_changed(self, item):
        if getattr(self, "_updating_table_items", False) or item is None:
            return
        row, col = item.row(), item.column()
        if col in (0, 7, 8):
            return
        it0 = self.table.item(row, 0)
        if not it0:
            return
        item_id = it0.data(Qt.ItemDataRole.UserRole)
        data = self.files_data.get(item_id)
        if not data:
            return

        col_names = ["file", "last", "first", "mid", "series", "num", "title", "target", "status"]
        col_key = col_names[col]
        new_val = item.text().strip()
        old_val = data["meta"].get(col_key, "")

        if old_val == new_val:
            if item.text() != new_val:
                self._updating_table_items = True
                try:
                    item.setText(new_val)
                finally:
                    self._updating_table_items = False
            return

        before = snapshot_book_state(data)
        after_meta = dict(before["meta"])
        after_meta[col_key] = new_val
        after = {**before, "meta": after_meta}
        cols_labels = tr("converter.columns")
        col_label = cols_labels[col] if isinstance(cols_labels, list) and col < len(cols_labels) else col_key
        self.undo_stack.push(
            UpdateBooksCommand(
                self,
                [{"item_id": item_id, "before": before, "after": after}],
                tr("converter.undo_edit_cell", col=col_label),
            )
        )

    def on_table_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        selected_rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if row not in selected_rows:
            self.table.selectRow(row)
            selected_rows = [row]

        menu = QMenu(self)
        if len(selected_rows) == 1:
            it0 = self.table.item(row, 0)
            if not it0:
                return
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            act_convert_sel = menu.addAction(tr("converter.ctx_convert_selected"))
            act_debug = menu.addAction(tr("converter.ctx_debug_convert"))
            act_inspect = menu.addAction(tr("converter.ctx_inspect"))
            menu.addSeparator()
            act_edit = menu.addAction(tr("converter.ctx_edit"))
            act_lookup = menu.addAction(tr("converter.ctx_lookup_metadata"))
            act_cover_studio = menu.addAction(tr("converter.ctx_cover_studio"))
            act_save_src = menu.addAction(tr("converter.ctx_save_source"))
            act_organize = menu.addAction(tr("converter.ctx_organize_fb2"))
            act_autonum = menu.addAction(tr("converter.ctx_autonumber_series", count=1))
            act_up = menu.addAction(tr("converter.ctx_move_up"))
            act_down = menu.addAction(tr("converter.ctx_move_down"))
            menu.addSeparator()
            act_delete = menu.addAction(tr("converter.ctx_delete"))
            chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
            if chosen == act_convert_sel:
                self.convert_selected()
            elif chosen == act_debug:
                self.convert_selected(debug=True)
            elif chosen == act_inspect:
                self.inspect_book_row(row, item_id)
            elif chosen == act_edit:
                self.edit_book_row(row, item_id)
            elif chosen == act_lookup:
                self.lookup_book_metadata_row(row, item_id)
            elif chosen == act_cover_studio:
                self.open_cover_studio_rows([row])
            elif chosen == act_save_src:
                self.save_rows_to_source([row])
            elif chosen == act_organize:
                self.organize_fb2_rows([row])
            elif chosen == act_autonum:
                self.autonumber_series_rows([row])
            elif chosen == act_up:
                self.move_selected_rows(-1)
            elif chosen == act_down:
                self.move_selected_rows(1)
            elif chosen == act_delete:
                self.remove_book_rows([row])
        else:
            cnt = len(selected_rows)
            act_convert_sel = menu.addAction(tr("converter.ctx_convert_selected_multi", count=cnt))
            act_debug = menu.addAction(tr("converter.ctx_debug_convert"))
            menu.addSeparator()
            act_batch = menu.addAction(tr("converter.ctx_batch_edit", count=cnt))
            act_cover_studio = menu.addAction(tr("converter.ctx_cover_studio_multi", count=cnt))
            act_save_src = menu.addAction(tr("converter.ctx_save_source_multi", count=cnt))
            act_organize = menu.addAction(tr("converter.ctx_organize_fb2"))
            act_omnibus = menu.addAction(tr("converter.ctx_merge_omnibus", count=cnt))
            act_autonum = menu.addAction(tr("converter.ctx_autonumber_series", count=cnt))
            act_up = menu.addAction(tr("converter.ctx_move_up"))
            act_down = menu.addAction(tr("converter.ctx_move_down"))
            menu.addSeparator()
            act_delete = menu.addAction(tr("converter.ctx_delete_selected", count=cnt))
            chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
            if chosen == act_convert_sel:
                self.convert_selected()
            elif chosen == act_debug:
                self.convert_selected(debug=True)
            elif chosen == act_batch:
                self.batch_edit_rows(selected_rows)
            elif chosen == act_cover_studio:
                self.open_cover_studio_rows(selected_rows)
            elif chosen == act_save_src:
                self.save_rows_to_source(selected_rows)
            elif chosen == act_organize:
                self.organize_fb2_rows(selected_rows)
            elif chosen == act_omnibus:
                self.merge_omnibus_rows(selected_rows)
            elif chosen == act_autonum:
                self.autonumber_series_rows(selected_rows)
            elif chosen == act_up:
                self.move_selected_rows(-1)
            elif chosen == act_down:
                self.move_selected_rows(1)
            elif chosen == act_delete:
                self.remove_book_rows(selected_rows)

    def _run_queue_bg_task(self, fn, on_done):
        existing = getattr(self, "_bg_task_worker", None)
        if existing is not None:
            try:
                if existing.isRunning():
                    show_themed_message(self, tr("common.warning"), tr("common.busy_workers_warning"), "warning")
                    return False
            except RuntimeError:
                pass
        worker = BackgroundTaskWorker(fn, parent=self)
        self._bg_task_worker = worker

        def _handle_done(result, error, w=worker):
            if getattr(self, "_bg_task_worker", None) is w:
                self._bg_task_worker = None
            if getattr(self, "_closing", False):
                return
            on_done(result, error)

        worker.finished_task.connect(_handle_done)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        return True

    def merge_omnibus_rows(self, rows):
        """Объединяет выбранные книги (в порядке таблицы) в один том FB2 (Омнибус) и добавляет его в очередь."""
        if not rows or len(rows) < 2:
            return
        items = []
        for r in sorted(rows):
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if data:
                items.append(data)
        if len(items) < 2:
            return
        first_meta = items[0].get("meta") or {}
        base_dir = os.path.dirname(os.path.abspath(items[0]["path"]))
        default_stem = (first_meta.get("series") or first_meta.get("title") or "omnibus").strip()
        safe_stem = "".join(ch for ch in default_stem if ch not in '<>:"/\\|?*').strip() or "omnibus"
        omnibus_suffix = tr("converter.omnibus_suffix")
        default_path = os.path.join(base_dir, f"{safe_stem} ({omnibus_suffix}).fb2")
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("converter.dlg_merge_omnibus"),
            default_path,
            "FictionBook 2 (*.fb2)",
        )
        if not out_path:
            return
        if not out_path.lower().endswith(".fb2"):
            out_path += ".fb2"

        default_collection_title = tr("converter.omnibus_default_title")
        default_unknown_author = tr("converter.omnibus_unknown_author")
        default_book_prefix = tr("converter.omnibus_book_prefix")

        def _work():
            return merge_fb2_books_to_omnibus(
                items,
                out_path,
                default_omnibus_suffix=omnibus_suffix,
                default_collection_title=default_collection_title,
                default_unknown_author=default_unknown_author,
                default_book_prefix=default_book_prefix,
            )

        def _done(res, err):
            if err is not None:
                logger.error("Ошибка объединения книг в омнибус: %s", err)
                show_themed_message(self, tr("common.error"), tr("converter.err_merge_omnibus", e=err), "error")
                return
            self.process_files([res["path"]])
            show_themed_message(
                self,
                tr("common.success"),
                tr("converter.msg_merge_omnibus_ok", count=res["books_count"], path=os.path.basename(res["path"])),
                "info",
            )

        self._run_queue_bg_task(_work, _done)

    def organize_fb2_rows(self, rows):
        """Копирует или перемещает исходные .fb2/.zip выбранных строк по папкам Автор/Серия без конвертации."""
        if not rows:
            return
        items = []
        for r in sorted(rows):
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if data:
                data["item_id"] = item_id
                items.append(data)
        if not items:
            return
        default_dest = self.app_settings.get("custom_output_dir") or os.path.dirname(os.path.abspath(items[0]["path"]))
        dlg = OrganizeBooksDialog(
            self,
            items,
            default_dest_dir=default_dest,
            filename_mode=self.app_settings.get("filename_mode", "default"),
            filename_tokens=self.app_settings.get("filename_tokens"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        plan = dlg.get_plan()
        copy_mode = dlg.is_copy_mode()
        count, errors, path_map = execute_organize_fb2_plan(plan, copy_mode=copy_mode)
        if not copy_mode and path_map:
            self._updating_table_items = True
            try:
                for item_id, data in self.files_data.items():
                    old_abs = os.path.abspath(data.get("path", ""))
                    if old_abs in path_map:
                        new_path = path_map[old_abs]
                        data["path"] = new_path
                        entry = data.get("archive_entry")
                        base = os.path.basename(new_path)
                        if entry:
                            data["source_key"] = f"{new_path}::{entry}"
                            if " / " in (data.get("display_name") or ""):
                                data["display_name"] = f"{base} / {os.path.basename(entry.replace('\\', '/'))}"
                            else:
                                data["display_name"] = base
                        else:
                            data["source_key"] = new_path
                            data["display_name"] = base
                for r in range(self.table.rowCount()):
                    it0 = self.table.item(r, 0)
                    if it0:
                        d = self.files_data.get(it0.data(Qt.ItemDataRole.UserRole))
                        if d:
                            it0.setText(d.get("display_name") or os.path.basename(d["path"]))
            finally:
                self._updating_table_items = False
        if errors:
            err_txt = "\n".join(f"{name}: {msg}" for name, msg in errors)
            show_themed_message(self, tr("common.error"), tr("converter.organize_err", e=err_txt), "error")
        elif count > 0:
            show_themed_message(self, tr("common.success"), tr("converter.organize_msg_ok", count=count), "info")

    def save_rows_to_source(self, rows):
        """Сохраняет текущие метаданные и обложки выбранных строк обратно в исходные .fb2/.zip файлы."""
        if not rows:
            return
        targets = []
        for r in sorted(rows):
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if data:
                targets.append((item_id, data))
        if not targets:
            return

        def _work():
            saved_ids = []
            errors = []
            for item_id, data in targets:
                try:
                    save_book_changes_to_source(data)
                    saved_ids.append(item_id)
                except Exception as e:
                    logger.error("Ошибка сохранения в исходный FB2 (%s): %s", data.get("display_name") or data.get("path"), e)
                    errors.append(f"{data.get('display_name') or os.path.basename(data['path'])}: {e}")
            return saved_ids, errors

        def _done(res, err):
            if err is not None:
                show_themed_message(self, tr("common.error"), tr("converter.err_save_source", e=err), "error")
                return
            saved_ids, errors = res
            if saved_ids and hasattr(self, "table"):
                self._updating_table_items = True
                try:
                    for iid in saved_ids:
                        data = self.files_data.get(iid)
                        cur_row = self._find_table_row_by_item_id(iid)
                        if data is not None and cur_row is not None and not data.get("status"):
                            self.table.setItem(cur_row, 8, self._make_status_item("", "", data.get("warnings"), data.get("is_duplicate", False)))
                finally:
                    self._updating_table_items = False
            self.apply_table_filter()
            self.on_table_selection_changed()
            if errors:
                show_themed_message(self, tr("common.error"), tr("converter.err_save_source", e="\n".join(errors)), "error")
            elif saved_ids:
                show_themed_message(self, tr("common.success"), tr("converter.msg_save_source_ok", count=len(saved_ids)), "info")

        self._run_queue_bg_task(_work, _done)

    def inspect_book_row(self, row, item_id):
        data = self.files_data.get(item_id)
        if not data:
            return
        xml_bytes = get_book_xml(data)
        report = inspect_fb2(xml_bytes, meta=data.get("meta"), cover_bytes=data.get("cover_bytes"))
        dlg = BookInspectorDialog(self, data.get("display_name") or os.path.basename(data.get("path", "")), report)
        dlg.exec()
        if dlg.debug_requested:
            self.convert_selected(debug=True)
        elif dlg.repair_requested:
            def _work():
                return repair_book_in_source(data)

            def _done(stats, err):
                if err is not None:
                    logger.error("Ошибка исправления FB2 (%s): %s", data.get("display_name") or data.get("path"), err)
                    show_themed_message(self, tr("common.error"), tr("inspector.err_repair", e=err), "error")
                    return
                cur_row = self._find_table_row_by_item_id(item_id)
                if cur_row is not None and not data.get("status"):
                    self._updating_table_items = True
                    try:
                        self.table.setItem(cur_row, 8, self._make_status_item("", "", data.get("warnings"), data.get("is_duplicate", False)))
                    finally:
                        self._updating_table_items = False
                self.apply_table_filter()
                self.on_table_selection_changed()
                old_kb = f"{stats['old_size'] / 1024:.1f} KB"
                new_kb = f"{stats['new_size'] / 1024:.1f} KB"
                xml_flag = tr("settings.opt_on") if stats["xml_fixed"] else tr("settings.opt_off")
                show_themed_message(
                    self,
                    tr("common.success"),
                    tr(
                        "inspector.msg_repair_ok",
                        xml_fixed=xml_flag,
                        removed=stats["removed_binaries"],
                        optimized=stats["optimized_images"],
                        old_size=old_kb,
                        new_size=new_kb,
                    ),
                    "info",
                )

            self._run_queue_bg_task(_work, _done)

    def lookup_selected_book_metadata(self):
        if not hasattr(self, "table"):
            return
        rows = [idx for idx in self.table.selectionModel().selectedRows() if not self.table.isRowHidden(idx.row())]
        if not rows:
            return
        row = rows[0].row()
        it0 = self.table.item(row, 0)
        if not it0:
            return
        item_id = it0.data(Qt.ItemDataRole.UserRole)
        self.lookup_book_metadata_row(row, item_id)

    def open_cover_studio_for_selected(self):
        if not hasattr(self, "table"):
            return
        rows = sorted({
            idx.row()
            for idx in self.table.selectionModel().selectedRows()
            if not self.table.isRowHidden(idx.row())
        })
        if rows:
            self.open_cover_studio_rows(rows)

    def open_cover_studio_rows(self, rows):
        if not rows or not hasattr(self, "table"):
            return
        item_ids = []
        for r in sorted(rows):
            it0 = self.table.item(r, 0)
            if it0:
                iid = it0.data(Qt.ItemDataRole.UserRole)
                if iid in self.files_data:
                    item_ids.append(iid)
        if not item_ids:
            return

        first_data = self.files_data[item_ids[0]]
        initial_spec = CoverSpec.from_dict(self.app_settings.get("cover_studio_spec"))
        dlg = CoverStudioDialog(
            self,
            book_data=first_data,
            books_count=len(item_ids),
            initial_spec=initial_spec,
            fonts_dir=self.fonts_dir,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        spec = dlg.get_spec()
        self.app_settings["cover_studio_spec"] = spec.to_dict()
        if hasattr(self, "save_app_settings"):
            self.save_app_settings()

        only_missing = dlg.get_apply_mode() == "missing_only"
        apply_cover_studio_to_books(
            self,
            item_ids,
            spec,
            only_missing=only_missing,
            fonts_dir=self.fonts_dir,
        )
        self.on_table_selection_changed()

    def lookup_book_metadata_row(self, row, item_id):
        data = self.files_data.get(item_id)
        if not data:
            return
        dlg = MetadataLookupDialog(self, data.get("meta", {}), app_settings=self.app_settings)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updates = dlg.get_selected_meta_updates()
        cov = dlg.get_selected_cover()
        if not updates and cov is None:
            return
        before = snapshot_book_state(data)
        after_meta = copy_meta_dict(before["meta"])
        after_meta.update(updates)
        if "annotation" in updates:
            after_meta["annotation_has_rich_xml"] = False
        after = {
            "meta": after_meta,
            "cover_bytes": cov[0] if cov is not None else before.get("cover_bytes"),
            "cover_mime": cov[1] if cov is not None else before.get("cover_mime"),
            "cover_modified": True if cov is not None else bool(before.get("cover_modified", False)),
        }
        if before != after:
            self.undo_stack.push(
                UpdateBooksCommand(
                    self,
                    [{"item_id": item_id, "before": before, "after": after}],
                    tr("converter.undo_lookup_metadata"),
                )
            )
        self.on_table_selection_changed()

    def edit_book_row(self, row, item_id):
        data = self.files_data.get(item_id)
        if not data:
            return
        output_format = self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT)
        dlg = BookEditDialog(
            self,
            data,
            output_format,
            filename_mode=self.app_settings.get("filename_mode", "default"),
            filename_tokens=self.app_settings.get("filename_tokens"),
            app_settings=self.app_settings,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            before = snapshot_book_state(data)
            new_meta = dlg.get_meta()
            cover_bytes, cover_mime, cover_modified = dlg.get_cover_state()
            after = {
                "meta": copy_meta_dict(new_meta),
                "cover_bytes": cover_bytes,
                "cover_mime": cover_mime,
                "cover_modified": bool(cover_modified),
            }
            if before != after:
                self.undo_stack.push(
                    UpdateBooksCommand(
                        self,
                        [{"item_id": item_id, "before": before, "after": after}],
                        tr("converter.undo_edit_book"),
                    )
                )

            updated_cs_spec = dlg.get_cover_studio_spec()
            if isinstance(updated_cs_spec, dict) and updated_cs_spec != self.app_settings.get("cover_studio_spec"):
                self.app_settings["cover_studio_spec"] = updated_cs_spec
                if hasattr(self, "save_app_settings"):
                    self.save_app_settings()

            if dlg.should_save_to_source():
                def _save_work():
                    save_book_changes_to_source(data)
                    return True

                def _save_done(_res, err):
                    if err is not None:
                        show_themed_message(self, tr("common.error"), tr("converter.err_save_source", e=err), "error")
                    self.on_table_selection_changed()

                self._run_queue_bg_task(_save_work, _save_done)
            self.on_table_selection_changed()

    def batch_edit_rows(self, rows):
        if not rows:
            return
        common_meta = {}
        for key in ("last", "first", "mid", "series", "lang"):
            vals = set()
            for r in rows:
                it0 = self.table.item(r, 0)
                data = self.files_data.get(it0.data(Qt.ItemDataRole.UserRole)) if it0 else None
                if data:
                    vals.add(data["meta"].get(key, ""))
            common_meta[key] = next(iter(vals)) if len(vals) == 1 else ""

        dlg = BatchEditDialog(self, len(rows), common_meta)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updates = dlg.get_updates()
        genre_op = dlg.get_genre_operation()
        if not updates and not genre_op:
            return

        changes = []
        for r in rows:
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if not data:
                continue
            before = snapshot_book_state(data)
            after_meta = copy_meta_dict(before["meta"])
            after_meta.update(updates)
            if genre_op is not None:
                g_mode, g_codes = genre_op
                cur_genres = normalize_genre_list(after_meta.get("genres"))
                if g_mode == "replace":
                    after_meta["genres"] = list(g_codes)
                elif g_mode == "add":
                    after_meta["genres"] = normalize_genre_list(cur_genres + list(g_codes))
                elif g_mode == "remove":
                    drop = set(g_codes)
                    after_meta["genres"] = [g for g in cur_genres if g not in drop]
            after = {**before, "meta": after_meta}
            if before != after:
                changes.append({"item_id": item_id, "before": before, "after": after})

        if changes:
            self.undo_stack.push(
                UpdateBooksCommand(
                    self,
                    changes,
                    tr("converter.undo_batch_edit", count=len(changes)),
                )
            )

    def autonumber_series_rows(self, rows):
        if not rows:
            return
        changes = []
        for seq_num, r in enumerate(sorted(rows), start=1):
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if not data:
                continue
            before = snapshot_book_state(data)
            after_meta = dict(before["meta"])
            after_meta["num"] = str(seq_num)
            after = {**before, "meta": after_meta}
            if before != after:
                changes.append({"item_id": item_id, "before": before, "after": after})

        if changes:
            self.undo_stack.push(
                UpdateBooksCommand(
                    self,
                    changes,
                    tr("converter.undo_autonumber", count=len(changes)),
                )
            )

    def remove_book_rows(self, rows):
        if not rows:
            return
        removed_entries = []
        for r in sorted(set(rows)):
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if data is not None:
                removed_entries.append((r, item_id, data))
        if removed_entries:
            self.undo_stack.push(
                RemoveBooksCommand(
                    self,
                    removed_entries,
                    tr("converter.undo_remove", count=len(removed_entries)),
                )
            )

    def simulate_fbc_target(self, meta):
        return simulate_fbc_target(
            meta,
            self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT),
            self.app_settings.get("filename_mode", "default"),
            self.app_settings.get("filename_tokens"),
        )

    def activate_and_import(self, filepaths):
        """Поднимает окно на передний план (в т.ч. из трея / Dock) и загружает переданные файлы."""
        if hasattr(self, "restore_from_tray"):
            self.restore_from_tray()
        else:
            if self.isMinimized():
                self.showNormal()
            self.raise_()
            self.activateWindow()
        if filepaths:
            self.enqueue_import_paths(filepaths)

    def enqueue_import_paths(self, filepaths):
        """Принимает файлы из ОС (QFileOpenEvent / sys.argv) и ставит их в очередь, если импорт уже идёт."""
        paths = [p for p in (filepaths or []) if p]
        if not paths:
            return
        if getattr(self, "_import_worker", None) is not None and self._import_worker.isRunning():
            queue = getattr(self, "_queued_import_paths", None)
            if queue is None:
                queue = []
                self._queued_import_paths = queue
            queue.extend(paths)
            return
        self.process_files(paths)

    def process_files(self, filepaths):
        if not filepaths:
            return
        if getattr(self, "_import_worker", None) is not None and self._import_worker.isRunning():
            self.enqueue_import_paths(filepaths)
            return

        existing_keys = {
            d.get('source_key') or os.path.abspath(d['path'])
            for d in self.files_data.values()
        }
        self._import_had_rows = (self.table.rowCount() > 0)
        self._import_progress_dlg = ImportProgressDialog(self)
        worker = FileImportWorker(list(filepaths), existing_keys, parent=self)
        self._import_worker = worker
        worker.progress.connect(self._import_progress_dlg.update_progress)
        self._import_progress_dlg.cancel_requested.connect(self._cancel_import_worker)
        worker.finished_import.connect(self._on_import_finished)
        worker.finished.connect(worker.deleteLater)

        self._import_dlg_timer = QTimer(self)
        self._import_dlg_timer.setSingleShot(True)
        self._import_dlg_timer.timeout.connect(self._show_import_progress_dialog)
        self._import_dlg_timer.start(180)

        worker.start()

    def _cancel_import_worker(self):
        worker = getattr(self, "_import_worker", None)
        if worker is not None:
            try:
                worker.requestInterruption()
            except RuntimeError:
                pass

    def _show_import_progress_dialog(self):
        worker = getattr(self, "_import_worker", None)
        dlg = getattr(self, "_import_progress_dlg", None)
        if worker is not None and worker.isRunning() and dlg is not None and not dlg.isVisible():
            dlg.open()

    def _on_import_finished(self, imported_items, cancelled):
        self._import_worker = None
        if getattr(self, "_closing", False):
            return
        timer = getattr(self, "_import_dlg_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

        dlg = getattr(self, "_import_progress_dlg", None)
        if dlg is not None:
            self._import_progress_dlg = None
            try:
                dlg.finish_and_close()
                dlg.deleteLater()
            except RuntimeError:
                pass

        first_new_row = None
        if imported_items:
            existing_keys = {
                d.get('source_key') or os.path.abspath(d['path'])
                for d in self.files_data.values()
            }
            self._updating_table_items = True
            was_sorting = self.table.isSortingEnabled()
            self.table.setSortingEnabled(False)
            self.table.setUpdatesEnabled(False)
            try:
                for entry in imported_items:
                    source_key = entry['source_key']
                    if source_key in existing_keys:
                        continue
                    existing_keys.add(source_key)

                    meta = entry['meta']
                    self._next_item_id += 1
                    item_id = str(self._next_item_id)
                    entry['item_id'] = item_id
                    row = self.table.rowCount()
                    self.table.insertRow(row)

                    it_file = QTableWidgetItem(entry['display_name'])
                    it_file.setData(Qt.ItemDataRole.UserRole, item_id)
                    it_file.setFlags(it_file.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, 0, it_file)
                    self.table.setItem(row, 1, QTableWidgetItem(meta['last']))
                    self.table.setItem(row, 2, QTableWidgetItem(meta['first']))
                    self.table.setItem(row, 3, QTableWidgetItem(meta['mid']))
                    self.table.setItem(row, 4, QTableWidgetItem(meta['series']))
                    self.table.setItem(row, 5, QTableWidgetItem(meta['num']))
                    self.table.setItem(row, 6, QTableWidgetItem(meta['title']))
                    it_target = QTableWidgetItem(self.simulate_fbc_target(meta))
                    it_target.setFlags(it_target.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, 7, it_target)
                    self.table.setItem(row, 8, self._make_status_item("", "", entry.get("warnings")))

                    self.files_data[item_id] = entry
                    if first_new_row is None:
                        first_new_row = row
            finally:
                self.table.setUpdatesEnabled(True)
                self.table.setSortingEnabled(was_sorting)
                self._updating_table_items = False

        if first_new_row is not None and not getattr(self, "_import_had_rows", False) and self.table.rowCount() > 0:
            self.table.selectRow(0)
        self._refresh_duplicates_state()
        self.apply_table_filter()
        self.update_header_status()
        self._refresh_filename_builder_preview()
        logger.info("Импорт книг завершён: добавлено=%d, отменено=%s", len(imported_items), cancelled)

        queued = getattr(self, "_queued_import_paths", None)
        if queued:
            next_batch = list(queued)
            queued.clear()
            QTimer.singleShot(0, lambda b=next_batch: self.process_files(b))

    def load_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("converter.dlg_select_books"), "", tr("converter.filter_books"))
        if files:
            self.process_files(files)

    def clear_list(self):
        if not self.files_data and self.table.rowCount() == 0:
            return
        removed_entries = []
        for r in range(self.table.rowCount()):
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if data is not None:
                removed_entries.append((r, item_id, data))
        if removed_entries:
            self.undo_stack.push(
                RemoveBooksCommand(self, removed_entries, tr("converter.undo_clear", count=len(removed_entries)))
            )
            return
        self.table.setRowCount(0)
        self.files_data.clear()
        self.btn_replace_cover.setEnabled(False)
        self.btn_reset_cover.setEnabled(False)
        if hasattr(self, "btn_lookup_online"):
            self.btn_lookup_online.setEnabled(False)
        if hasattr(self, "btn_cover_studio"):
            self.btn_cover_studio.setEnabled(False)
        self._update_convert_selected_button(0)
        self.render_cover_preview(None)
        self.apply_table_filter()
        self.update_header_status()

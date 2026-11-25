from PyQt6.QtGui import QUndoCommand

from core.fb2_processor import copy_meta_dict


def snapshot_book_state(data):
    """Создаёт снимок редактируемого состояния книги (метаданные + обложка)."""
    return {
        "meta": copy_meta_dict(data.get("meta") or {}),
        "cover_bytes": data.get("cover_bytes"),
        "cover_mime": data.get("cover_mime"),
        "cover_modified": bool(data.get("cover_modified", False)),
    }


class UpdateBooksCommand(QUndoCommand):
    """Отменяет и повторяет изменение метаданных и/или обложки у одной или нескольких книг."""

    def __init__(self, target, changes, text=""):
        super().__init__(text)
        self._target = target
        self._changes = [
            {
                "item_id": ch["item_id"],
                "before": {
                    "meta": copy_meta_dict(ch["before"]["meta"]),
                    "cover_bytes": ch["before"].get("cover_bytes"),
                    "cover_mime": ch["before"].get("cover_mime"),
                    "cover_modified": bool(ch["before"].get("cover_modified", False)),
                },
                "after": {
                    "meta": copy_meta_dict(ch["after"]["meta"]),
                    "cover_bytes": ch["after"].get("cover_bytes"),
                    "cover_mime": ch["after"].get("cover_mime"),
                    "cover_modified": bool(ch["after"].get("cover_modified", False)),
                },
            }
            for ch in changes
        ]

    @staticmethod
    def _clone_snap(snap):
        return {
            "meta": copy_meta_dict(snap["meta"]),
            "cover_bytes": snap.get("cover_bytes"),
            "cover_mime": snap.get("cover_mime"),
            "cover_modified": bool(snap.get("cover_modified", False)),
        }

    def redo(self):
        self._target._apply_book_snapshots([(ch["item_id"], self._clone_snap(ch["after"])) for ch in self._changes])

    def undo(self):
        self._target._apply_book_snapshots([(ch["item_id"], self._clone_snap(ch["before"])) for ch in self._changes])


class RemoveBooksCommand(QUndoCommand):
    """Отменяет и повторяет удаление одной или нескольких книг (включая очистку списка)."""

    def __init__(self, target, removed_entries, text=""):
        super().__init__(text)
        self._target = target
        # removed_entries: list[(row_index, item_id, data_dict)]
        self._removed_entries = sorted(
            [(int(r), item_id, data) for r, item_id, data in removed_entries],
            key=lambda x: x[0],
        )

    def redo(self):
        self._target._remove_items_by_ids([item_id for _, item_id, _ in self._removed_entries])

    def undo(self):
        self._target._restore_removed_items(self._removed_entries)


class ReorderBooksCommand(QUndoCommand):
    """Отменяет и повторяет изменение порядка строк таблицы."""

    def __init__(self, target, before_order, after_order, selected_ids=None, text=""):
        super().__init__(text)
        self._target = target
        self._before_order = list(before_order)
        self._after_order = list(after_order)
        self._selected_ids = list(selected_ids or [])

    def redo(self):
        self._target._apply_table_order(self._after_order, self._selected_ids)

    def undo(self):
        self._target._apply_table_order(self._before_order, self._selected_ids)

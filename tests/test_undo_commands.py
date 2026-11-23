import unittest

from PyQt6.QtGui import QUndoStack

from core.undo_commands import (
    RemoveBooksCommand,
    ReorderBooksCommand,
    UpdateBooksCommand,
    snapshot_book_state,
)


class _DummyQueueTarget:
    """Минимальная модель очереди книг для тестирования QUndoStack без QMainWindow."""

    def __init__(self, entries):
        # entries: list[(item_id, data_dict)]
        self.order = [item_id for item_id, _ in entries]
        self.files_data = {item_id: data for item_id, data in entries}
        self.selected_ids = []

    def _apply_book_snapshots(self, pairs):
        for item_id, snap in pairs:
            data = self.files_data.get(item_id)
            if data is None:
                continue
            data["meta"] = dict(snap["meta"])
            data["cover_bytes"] = snap.get("cover_bytes")
            data["cover_mime"] = snap.get("cover_mime")
            data["cover_modified"] = bool(snap.get("cover_modified", False))

    def _remove_items_by_ids(self, item_ids):
        drop = set(item_ids)
        self.order = [iid for iid in self.order if iid not in drop]
        for iid in drop:
            self.files_data.pop(iid, None)

    def _restore_removed_items(self, removed_entries):
        for row_idx, item_id, data in sorted(removed_entries, key=lambda x: x[0]):
            self.files_data[item_id] = data
            pos = max(0, min(row_idx, len(self.order)))
            self.order.insert(pos, item_id)

    def _apply_table_order(self, ordered_ids, selected_ids=None):
        existing = [iid for iid in ordered_ids if iid in self.files_data]
        missing = [iid for iid in self.order if iid not in existing]
        self.order = existing + missing
        self.selected_ids = list(selected_ids or [])


def _make_book(title, last="Автор", num="", cover=b"orig"):
    return {
        "path": f"/tmp/{title}.fb2",
        "display_name": f"{title}.fb2",
        "meta": {"last": last, "first": "", "mid": "", "series": "Цикл", "num": num, "title": title},
        "orig_cover_bytes": cover,
        "orig_cover_mime": "image/jpeg",
        "cover_bytes": cover,
        "cover_mime": "image/jpeg",
        "cover_modified": False,
    }


class TestUndoCommands(unittest.TestCase):
    def test_update_books_command_undo_redo_meta_and_cover(self):
        target = _DummyQueueTarget([
            ("1", _make_book("Книга 1", num="")),
            ("2", _make_book("Книга 2", num="")),
        ])
        stack = QUndoStack()

        b1 = snapshot_book_state(target.files_data["1"])
        a1 = {**b1, "meta": {**b1["meta"], "title": "Новое название", "num": "1"}, "cover_bytes": b"new", "cover_modified": True}
        b2 = snapshot_book_state(target.files_data["2"])
        a2 = {**b2, "meta": {**b2["meta"], "num": "2"}}

        stack.push(UpdateBooksCommand(target, [
            {"item_id": "1", "before": b1, "after": a1},
            {"item_id": "2", "before": b2, "after": a2},
        ], "Batch update"))

        self.assertEqual(target.files_data["1"]["meta"]["title"], "Новое название")
        self.assertEqual(target.files_data["1"]["cover_bytes"], b"new")
        self.assertTrue(target.files_data["1"]["cover_modified"])
        self.assertEqual(target.files_data["2"]["meta"]["num"], "2")

        stack.undo()
        self.assertEqual(target.files_data["1"]["meta"]["title"], "Книга 1")
        self.assertEqual(target.files_data["1"]["cover_bytes"], b"orig")
        self.assertFalse(target.files_data["1"]["cover_modified"])
        self.assertEqual(target.files_data["2"]["meta"]["num"], "")

        stack.redo()
        self.assertEqual(target.files_data["1"]["meta"]["title"], "Новое название")
        self.assertEqual(target.files_data["2"]["meta"]["num"], "2")

    def test_remove_and_clear_books_command_preserves_positions(self):
        d1 = _make_book("A")
        d2 = _make_book("B")
        d3 = _make_book("C")
        target = _DummyQueueTarget([("1", d1), ("2", d2), ("3", d3)])
        stack = QUndoStack()

        stack.push(RemoveBooksCommand(target, [(1, "2", d2)], "Remove B"))
        self.assertEqual(target.order, ["1", "3"])
        self.assertNotIn("2", target.files_data)

        stack.undo()
        self.assertEqual(target.order, ["1", "2", "3"])
        self.assertIn("2", target.files_data)

        stack.redo()
        self.assertEqual(target.order, ["1", "3"])

        # Clear remaining
        stack.push(RemoveBooksCommand(target, [(0, "1", d1), (1, "3", d3)], "Clear"))
        self.assertEqual(target.order, [])
        self.assertEqual(len(target.files_data), 0)

        stack.undo()
        self.assertEqual(target.order, ["1", "3"])

    def test_reorder_books_command_undo_redo(self):
        target = _DummyQueueTarget([
            ("1", _make_book("A")),
            ("2", _make_book("B")),
            ("3", _make_book("C")),
        ])
        stack = QUndoStack()

        stack.push(ReorderBooksCommand(target, ["1", "2", "3"], ["2", "1", "3"], ["2"], "Move up"))
        self.assertEqual(target.order, ["2", "1", "3"])
        self.assertEqual(target.selected_ids, ["2"])

        stack.undo()
        self.assertEqual(target.order, ["1", "2", "3"])
        self.assertEqual(target.selected_ids, ["2"])

        stack.redo()
        self.assertEqual(target.order, ["2", "1", "3"])


if __name__ == "__main__":
    unittest.main()

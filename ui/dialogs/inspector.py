from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QFrame, QDialog, QPlainTextEdit,
    QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from core.i18n import tr


from ui.dialogs.common import _format_bytes_human, create_segmented_tabs


class BookInspectorDialog(QDialog):
    """Тематический диалог диагностики структуры FB2 (сводка, оглавление, иллюстрации и сноски)."""

    def __init__(self, parent, display_name, report):
        super().__init__(parent)
        self.setWindowTitle(tr("inspector.title"))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setModal(True)
        self.setMinimumSize(680, 520)
        self.debug_requested = False
        self.repair_requested = False
        if parent and parent.styleSheet():
            self.setStyleSheet(parent.styleSheet())

        report = report or {}
        warnings = list(report.get("warnings") or [])
        toc = list(report.get("toc") or [])
        images = list(report.get("images") or [])

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 18)
        root.setSpacing(14)

        card = QFrame()
        card.setObjectName("SectionCard")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(18, 16, 18, 16)
        c_layout.setSpacing(12)

        hdr = QLabel(tr("inspector.title").upper())
        hdr.setObjectName("SectionHeader")
        c_layout.addWidget(hdr)

        self.tabs = create_segmented_tabs(self)

        # --- Вкладка 1: Сводка и предупреждения ---
        tab_summary = QWidget()
        sum_l = QVBoxLayout(tab_summary)
        sum_l.setContentsMargins(4, 10, 4, 4)
        sum_l.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(6)

        if report.get("xml_valid_strict"):
            xml_status_txt = tr("inspector.xml_ok")
        elif report.get("xml_recovered"):
            xml_status_txt = tr("inspector.xml_recovered")
        else:
            xml_status_txt = tr("inspector.xml_error")

        def _val_lbl(txt):
            lbl = QLabel(str(txt))
            lbl.setObjectName("RowDesc")
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            return lbl

        form.addRow(QLabel(tr("inspector.lbl_file")), _val_lbl(display_name or "—"))
        form.addRow(QLabel(tr("inspector.lbl_size")), _val_lbl(_format_bytes_human(report.get("file_size_bytes", 0))))
        form.addRow(QLabel(tr("inspector.lbl_encoding")), _val_lbl((report.get("encoding") or "utf-8").upper()))
        form.addRow(QLabel(tr("inspector.lbl_xml_status")), _val_lbl(xml_status_txt))
        form.addRow(QLabel(tr("inspector.lbl_chapters")), _val_lbl(report.get("chapter_count", 0)))
        form.addRow(QLabel(tr("inspector.lbl_paragraphs")), _val_lbl(report.get("paragraph_count", 0)))
        form.addRow(QLabel(tr("inspector.lbl_footnotes")), _val_lbl(report.get("footnotes_count", 0)))
        img_summary = f"{len(images)} ({_format_bytes_human(report.get('total_images_bytes', 0))})"
        form.addRow(QLabel(tr("inspector.lbl_images")), _val_lbl(img_summary))
        sum_l.addLayout(form)

        w_hdr = QLabel(tr("inspector.sec_warnings"))
        w_hdr.setObjectName("SectionHeader")
        sum_l.addWidget(w_hdr)

        self.warnings_box = QPlainTextEdit()
        self.warnings_box.setReadOnly(True)
        self.warnings_box.setMinimumHeight(110)
        if not warnings:
            self.warnings_box.setPlainText(tr("inspector.no_warnings"))
        else:
            lines = []
            for w in warnings:
                code = w.get("code", "")
                sev = "✕" if w.get("severity") == "error" else "⚠"
                cnt = w.get("count", 1)
                lines.append(f"{sev} {tr(f'inspector.warn_{code}', count=cnt)}")
            self.warnings_box.setPlainText("\n".join(lines))
        sum_l.addWidget(self.warnings_box, 1)
        self.tabs.addTab(tab_summary, tr("inspector.tab_summary"))

        # --- Вкладка 2: Оглавление (TOC) ---
        tab_toc = QWidget()
        toc_l = QVBoxLayout(tab_toc)
        toc_l.setContentsMargins(4, 10, 4, 4)
        toc_l.setSpacing(8)

        self.toc_tree = QTreeWidget()
        self.toc_tree.setHeaderHidden(True)
        if toc:
            def _add_toc_nodes(parent_item, nodes):
                for nd in nodes:
                    title = nd.get("title") or tr("inspector.untitled_section")
                    item = QTreeWidgetItem([title])
                    if parent_item is None:
                        self.toc_tree.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    _add_toc_nodes(item, nd.get("children") or [])
            _add_toc_nodes(None, toc)
            self.toc_tree.expandAll()
            toc_l.addWidget(self.toc_tree, 1)
        else:
            lbl_empty = QLabel(tr("inspector.toc_empty"))
            lbl_empty.setObjectName("RowDesc")
            lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            toc_l.addWidget(lbl_empty, 1)
        self.tabs.addTab(tab_toc, tr("inspector.tab_toc", count=report.get("chapter_count", 0)))

        # --- Вкладка 3: Иллюстрации и сноски ---
        tab_media = QWidget()
        media_l = QVBoxLayout(tab_media)
        media_l.setContentsMargins(4, 10, 4, 4)
        media_l.setSpacing(8)

        self.media_table = QTableWidget(len(images), 5)
        media_cols = tr("inspector.media_cols")
        if not isinstance(media_cols, list) or len(media_cols) != 5:
            media_cols = ["ID", "Type", "Dimensions", "Size", "Status"]
        self.media_table.setHorizontalHeaderLabels(media_cols)
        self.media_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.media_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.media_table.verticalHeader().setVisible(False)
        self.media_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3, 4):
            self.media_table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

        for r, img in enumerate(images):
            id_txt = tr("inspector.media_cover_badge", id=img["id"]) if img.get("is_cover") else img["id"]
            dims_txt = f"{img['width']}×{img['height']}" if (img.get("width") and img.get("height")) else "—"
            size_txt = _format_bytes_human(img.get("size_bytes", 0))
            if not img.get("valid"):
                st_txt = tr("inspector.media_broken")
            elif img.get("oversized"):
                st_txt = tr("inspector.media_oversized")
            else:
                st_txt = tr("inspector.media_ok")
            for col, val in enumerate((id_txt, img.get("content_type", ""), dims_txt, size_txt, st_txt)):
                self.media_table.setItem(r, col, QTableWidgetItem(str(val)))
        media_l.addWidget(self.media_table, 1)

        lbl_media_sum = QLabel(tr(
            "inspector.media_summary",
            img_count=len(images),
            total_size=_format_bytes_human(report.get("total_images_bytes", 0)),
            fn_count=report.get("footnotes_count", 0),
        ))
        lbl_media_sum.setObjectName("RowDesc")
        media_l.addWidget(lbl_media_sum)
        self.tabs.addTab(tab_media, tr("inspector.tab_media", count=len(images)))

        c_layout.addWidget(self.tabs, 1)
        root.addWidget(card, 1)

        repairable_codes = {"broken_xml", "invalid_binary", "oversized_image"}
        can_repair = any(w.get("code") in repairable_codes for w in warnings)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_repair = QPushButton(tr("inspector.btn_repair_fb2"))
        self.btn_repair.setObjectName("SecondaryButton")
        self.btn_repair.setProperty("variant", "secondary")
        self.btn_repair.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_repair.setEnabled(can_repair)
        self.btn_repair.clicked.connect(self._on_repair_clicked)
        btn_row.addWidget(self.btn_repair)

        self.btn_debug = QPushButton(tr("inspector.btn_debug_convert"))
        self.btn_debug.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_debug.clicked.connect(self._on_debug_clicked)
        btn_row.addWidget(self.btn_debug)
        btn_row.addStretch()
        btn_close = QPushButton(tr("inspector.btn_close"))
        btn_close.setObjectName("AccentButton")
        btn_close.setProperty("variant", "primary")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setDefault(True)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    def _on_repair_clicked(self):
        self.repair_requested = True
        self.accept()

    def _on_debug_clicked(self):
        self.debug_requested = True
        self.accept()


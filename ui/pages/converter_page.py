from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QHeaderView, QFrame, QLineEdit, QCheckBox
)

from core.i18n import tr
from core.config import DEFAULT_OUTPUT_FORMAT
from core.fb2_processor import COVER_PREVIEW_SIZE, FORMAT_EXT_MAP
from ui.theme import RoundedRowDelegate, FormatComboBox, PillSelector


def _build_converter_banner(win):
    banner = QFrame()
    banner.setObjectName("BannerCard")
    b_layout = QHBoxLayout(banner)
    b_layout.setContentsMargins(18, 14, 18, 14)
    b_layout.setSpacing(14)

    icon_lbl = QLabel("⚡")
    icon_lbl.setStyleSheet("font-size: 22px;")
    b_layout.addWidget(icon_lbl)

    txt_box = QVBoxLayout()
    txt_box.setSpacing(2)
    b_title = QLabel(tr("converter.banner_title"))
    b_title.setObjectName("RowTitle")
    b_desc = QLabel(tr("converter.banner_desc"))
    b_desc.setObjectName("RowDesc")
    txt_box.addWidget(b_title)
    txt_box.addWidget(b_desc)
    b_layout.addLayout(txt_box, 1)

    btn_add = QPushButton(tr("converter.btn_add"))
    btn_add.setObjectName("SecondaryButton")
    btn_add.setProperty("variant", "secondary")
    btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_add.clicked.connect(win.load_files)
    b_layout.addWidget(btn_add)

    btn_clear = QPushButton(tr("converter.btn_clear"))
    btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_clear.clicked.connect(win.clear_list)
    b_layout.addWidget(btn_clear)

    fmt_box = QHBoxLayout()
    fmt_box.setContentsMargins(6, 0, 2, 0)
    fmt_box.setSpacing(8)
    lbl_fmt = QLabel(tr("converter.lbl_format"))
    lbl_fmt.setObjectName("RowDesc")
    fmt_box.addWidget(lbl_fmt)

    win.format_combo = FormatComboBox()
    win.format_combo.setToolTip(tr("converter.format_tooltip"))
    for k in FORMAT_EXT_MAP.keys():
        win.format_combo.addItem(k.upper(), k)
    cur_fmt = win.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT)
    fmt_idx = win.format_combo.findData(cur_fmt)
    if fmt_idx >= 0:
        win.format_combo.setCurrentIndex(fmt_idx)
    win.format_combo.currentIndexChanged.connect(
        lambda idx: win.on_format_changed(win.format_combo.itemData(idx))
        if idx >= 0 and win.format_combo.itemData(idx) else None
    )
    fmt_box.addWidget(win.format_combo)
    b_layout.addLayout(fmt_box)

    win.btn_convert_selected = QPushButton(tr("converter.btn_convert_selected_empty"))
    win.btn_convert_selected.setObjectName("SecondaryButton")
    win.btn_convert_selected.setProperty("variant", "secondary")
    win.btn_convert_selected.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_convert_selected.setEnabled(False)
    win.btn_convert_selected.clicked.connect(win.convert_selected)
    b_layout.addWidget(win.btn_convert_selected)

    win.btn_convert = QPushButton(tr("converter.btn_convert"))
    win.btn_convert.setObjectName("AccentButton")
    win.btn_convert.setProperty("variant", "primary")
    win.btn_convert.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_convert.clicked.connect(win.convert_all)
    b_layout.addWidget(win.btn_convert)

    win.btn_sync_device = QPushButton(tr("converter.btn_sync_device"))
    win.btn_sync_device.setToolTip(tr("converter.btn_sync_device_tip"))
    win.btn_sync_device.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_sync_device.clicked.connect(win.send_to_reader_clicked)
    b_layout.addWidget(win.btn_sync_device)
    return banner


def _build_queue_filter_bar(win):
    filter_bar = QHBoxLayout()
    filter_bar.setContentsMargins(0, 0, 0, 0)
    filter_bar.setSpacing(10)

    win.search_edit = QLineEdit()
    win.search_edit.setPlaceholderText(tr("converter.search_placeholder"))
    win.search_edit.setClearButtonEnabled(True)
    win.search_edit.setMinimumWidth(220)
    win.search_edit.textChanged.connect(win.on_table_filter_changed)
    win.search_edit.installEventFilter(win)
    filter_bar.addWidget(win.search_edit, 1)

    win.status_filter_selector = PillSelector(
        [
            (tr("converter.filter_all"), "all"),
            (tr("converter.filter_pending"), "pending"),
            (tr("converter.filter_ok"), "ok"),
            (tr("converter.filter_error"), "error"),
            (tr("converter.filter_warnings"), "warnings"),
        ],
        default=getattr(win, "_table_status_filter", "all"),
        callback=win.on_status_filter_changed,
    )
    filter_bar.addWidget(win.status_filter_selector)

    win.lbl_filter_count = QLabel(tr("converter.filter_count", shown=0, total=0))
    win.lbl_filter_count.setObjectName("RowDesc")
    filter_bar.addWidget(win.lbl_filter_count)

    win.chk_skip_existing = QCheckBox(tr("converter.chk_skip_existing"))
    win.chk_skip_existing.setToolTip(tr("converter.chk_skip_existing_tip"))
    win.chk_skip_existing.setChecked(str(win.app_settings.get("skip_existing", "false")).lower() == "true")
    win.chk_skip_existing.setCursor(Qt.CursorShape.PointingHandCursor)
    win.chk_skip_existing.toggled.connect(win.on_skip_existing_toggled)
    filter_bar.addWidget(win.chk_skip_existing)

    win.btn_remove_duplicates = QPushButton(tr("converter.btn_remove_duplicates", count=0))
    win.btn_remove_duplicates.setObjectName("SecondaryButton")
    win.btn_remove_duplicates.setProperty("variant", "secondary")
    win.btn_remove_duplicates.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_remove_duplicates.setVisible(False)
    win.btn_remove_duplicates.clicked.connect(win.remove_duplicate_books)
    filter_bar.addWidget(win.btn_remove_duplicates)

    win.btn_undo = QPushButton("↩")
    win.btn_undo.setObjectName("SecondaryButton")
    win.btn_undo.setProperty("variant", "secondary")
    win.btn_undo.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_undo.setFixedSize(34, 30)
    win.btn_undo.setStyleSheet("padding: 0px; font-size: 15px;")
    win.btn_undo.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
    win.btn_undo.setToolTip(tr("converter.btn_undo"))
    win.btn_undo.setEnabled(False)
    win.btn_undo.clicked.connect(win.undo_last_action)
    filter_bar.addWidget(win.btn_undo)

    win.btn_redo = QPushButton("↪")
    win.btn_redo.setObjectName("SecondaryButton")
    win.btn_redo.setProperty("variant", "secondary")
    win.btn_redo.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_redo.setFixedSize(34, 30)
    win.btn_redo.setStyleSheet("padding: 0px; font-size: 15px;")
    win.btn_redo.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
    win.btn_redo.setToolTip(tr("converter.btn_redo"))
    win.btn_redo.setEnabled(False)
    win.btn_redo.clicked.connect(win.redo_last_action)
    filter_bar.addWidget(win.btn_redo)
    return filter_bar


def _build_queue_table(win):
    win.table = QTableWidget()
    win.table.setColumnCount(9)
    win.table.setAlternatingRowColors(False)
    win.table.setShowGrid(False)
    win.table.verticalHeader().setVisible(False)
    win.table.verticalHeader().setDefaultSectionSize(38)
    win.table.setHorizontalHeaderLabels(tr("converter.columns"))

    win.table_row_delegate = RoundedRowDelegate(win.table)
    win.table.setItemDelegate(win.table_row_delegate)

    header = win.table.horizontalHeader()
    header.setMinimumSectionSize(55)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)
    for col, width in [(1, 115), (2, 105), (3, 115), (4, 130)]:
        win.table.setColumnWidth(col, width)

    win.table.setSortingEnabled(True)
    win.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    win.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
    win.table.setEditTriggers(
        QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed
    )
    win.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    win.table.customContextMenuRequested.connect(win.on_table_context_menu)
    win.table.itemDoubleClicked.connect(win.on_table_double_click)
    win.table.itemChanged.connect(win.on_table_item_changed)
    win.table.itemSelectionChanged.connect(win.on_table_selection_changed)
    win.table.installEventFilter(win)
    return win.table


def _build_cover_sidebar(win):
    cover_box = QVBoxLayout()
    cover_box.setAlignment(Qt.AlignmentFlag.AlignTop)
    cover_box.setSpacing(8)

    cov_hdr = QLabel(tr("converter.cover_header"))
    cov_hdr.setObjectName("SectionHeader")
    cov_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cover_box.addWidget(cov_hdr)

    win.cover_preview_lbl = QLabel(tr("converter.cover_select_prompt"))
    win.cover_preview_lbl.setObjectName("CoverPanel")
    win.cover_preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    win.cover_preview_lbl.setFixedSize(COVER_PREVIEW_SIZE[0], COVER_PREVIEW_SIZE[1])
    cover_box.addWidget(win.cover_preview_lbl)

    win.cover_info_label = QLabel(tr("converter.cover_size_empty"))
    win.cover_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    win.cover_info_label.setObjectName("RowDesc")
    cover_box.addWidget(win.cover_info_label)

    win.btn_replace_cover = QPushButton(tr("converter.btn_replace_cover"))
    win.btn_replace_cover.setObjectName("SecondaryButton")
    win.btn_replace_cover.setProperty("variant", "secondary")
    win.btn_replace_cover.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_replace_cover.setEnabled(False)
    win.btn_replace_cover.clicked.connect(win.replace_selected_cover)
    cover_box.addWidget(win.btn_replace_cover)

    win.btn_reset_cover = QPushButton(tr("converter.btn_reset_cover"))
    win.btn_reset_cover.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_reset_cover.setEnabled(False)
    win.btn_reset_cover.clicked.connect(win.reset_selected_cover)
    cover_box.addWidget(win.btn_reset_cover)

    win.btn_lookup_online = QPushButton(tr("converter.btn_lookup_online"))
    win.btn_lookup_online.setObjectName("SecondaryButton")
    win.btn_lookup_online.setProperty("variant", "secondary")
    win.btn_lookup_online.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_lookup_online.setEnabled(False)
    win.btn_lookup_online.clicked.connect(win.lookup_selected_book_metadata)
    cover_box.addWidget(win.btn_lookup_online)

    win.btn_cover_studio = QPushButton(tr("converter.btn_cover_studio"))
    win.btn_cover_studio.setObjectName("SecondaryButton")
    win.btn_cover_studio.setProperty("variant", "secondary")
    win.btn_cover_studio.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_cover_studio.setEnabled(False)
    win.btn_cover_studio.clicked.connect(win.open_cover_studio_for_selected)
    cover_box.addWidget(win.btn_cover_studio)

    cover_box.addStretch()
    return cover_box


def build_converter_page(win, parent):
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)

    layout.addWidget(_build_converter_banner(win))

    content_card = QFrame()
    content_card.setObjectName("SectionCard")
    c_layout = QHBoxLayout(content_card)
    c_layout.setContentsMargins(16, 16, 16, 16)
    c_layout.setSpacing(16)

    table_col = QVBoxLayout()
    table_col.setContentsMargins(0, 0, 0, 0)
    table_col.setSpacing(10)
    table_col.addLayout(_build_queue_filter_bar(win))
    table_col.addWidget(_build_queue_table(win), 1)
    c_layout.addLayout(table_col, 1)

    c_layout.addLayout(_build_cover_sidebar(win))
    layout.addWidget(content_card, 1)

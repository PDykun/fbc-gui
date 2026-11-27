"""Страница локальной библиотеки INPX (поиск и передача книг в конвертер)."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from ui.theme import FormatComboBox, PillSelector, RoundedRowDelegate, create_section_card


def build_library_page(win, parent):
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    # 1. Верхняя панель подключения INPX (интегрирована в окно Библиотеки)
    conn_card, conn_lay = create_section_card(tr("library.sec_connection"))
    conn_row = QHBoxLayout()
    conn_row.setContentsMargins(0, 0, 0, 0)
    conn_row.setSpacing(8)

    win.lib_inpx_path_edit = QLineEdit(str(win.app_settings.get("library_inpx_path", "")))
    win.lib_inpx_path_edit.setReadOnly(True)
    win.lib_inpx_path_edit.setPlaceholderText(tr("library.ph_inpx_path"))
    conn_row.addWidget(win.lib_inpx_path_edit, 1)

    win.btn_lib_choose_inpx = QPushButton(tr("library.btn_choose_inpx"))
    win.btn_lib_choose_inpx.setObjectName("AccentButton")
    win.btn_lib_choose_inpx.setProperty("variant", "primary")
    win.btn_lib_choose_inpx.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_lib_choose_inpx.clicked.connect(win.choose_library_inpx_clicked)
    conn_row.addWidget(win.btn_lib_choose_inpx)

    win.btn_lib_reindex = QPushButton(tr("library.btn_reindex"))
    win.btn_lib_reindex.setObjectName("SecondaryButton")
    win.btn_lib_reindex.setProperty("variant", "secondary")
    win.btn_lib_reindex.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_lib_reindex.clicked.connect(win.reindex_library_clicked)
    conn_row.addWidget(win.btn_lib_reindex)

    conn_lay.addLayout(conn_row)

    win.lbl_lib_status = QLabel(tr("library.status_not_configured"))
    win.lbl_lib_status.setObjectName("RowDesc")
    win.lbl_lib_status.setWordWrap(True)
    conn_lay.addWidget(win.lbl_lib_status)
    layout.addWidget(conn_card)

    # 2. Панель поиска и фильтров
    search_row = QHBoxLayout()
    search_row.setContentsMargins(0, 0, 0, 0)
    search_row.setSpacing(10)

    win.lib_search_edit = QLineEdit()
    win.lib_search_edit.setPlaceholderText(tr("library.search_placeholder"))
    win.lib_search_edit.setClearButtonEnabled(True)
    win.lib_search_edit.textChanged.connect(win.on_library_search_changed)
    search_row.addWidget(win.lib_search_edit, 1)

    win.lib_field_selector = PillSelector(
        [
            (tr("library.field_all"), "all"),
            (tr("library.field_author"), "author"),
            (tr("library.field_title"), "title"),
            (tr("library.field_series"), "series"),
        ],
        default="all",
        callback=win.on_library_filter_changed,
        segmented=True,
    )
    search_row.addWidget(win.lib_field_selector)

    win.lib_lang_combo = FormatComboBox()
    win.lib_lang_combo.setMinimumWidth(110)
    for label, code in (
        (tr("library.lang_all"), "all"),
        ("RU", "ru"),
        ("EN", "en"),
        ("UK", "uk"),
        ("DE", "de"),
        ("FR", "fr"),
    ):
        win.lib_lang_combo.addItem(label, code)
    win.lib_lang_combo.currentIndexChanged.connect(lambda _idx: win.on_library_filter_changed())
    search_row.addWidget(win.lib_lang_combo)

    win.chk_lib_hide_deleted = QCheckBox(tr("library.chk_hide_deleted"))
    win.chk_lib_hide_deleted.setChecked(True)
    win.chk_lib_hide_deleted.setCursor(Qt.CursorShape.PointingHandCursor)
    win.chk_lib_hide_deleted.toggled.connect(lambda _chk: win.on_library_filter_changed())
    search_row.addWidget(win.chk_lib_hide_deleted)

    layout.addLayout(search_row)

    # 3. Таблица результатов поиска
    win.lib_table = QTableWidget(0, 7)
    win.lib_table.setAlternatingRowColors(False)
    win.lib_table.setShowGrid(False)
    win.lib_table.setHorizontalHeaderLabels(tr("library.columns"))
    win.lib_table.verticalHeader().setVisible(False)
    win.lib_table.verticalHeader().setDefaultSectionSize(42)
    win.lib_table_row_delegate = RoundedRowDelegate(win.lib_table)
    win.lib_table.setItemDelegate(win.lib_table_row_delegate)
    win.lib_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    win.lib_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    win.lib_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    win.lib_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    win.lib_table.customContextMenuRequested.connect(win.on_library_table_context_menu)
    win.lib_table.itemSelectionChanged.connect(win.on_library_selection_changed)
    win.lib_table.doubleClicked.connect(win.on_library_row_double_clicked)

    hdr = win.lib_table.horizontalHeader()
    hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
    hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
    hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
    hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
    hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
    hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
    win.lib_table.setColumnWidth(0, 210)
    win.lib_table.setColumnWidth(1, 180)
    win.lib_table.setColumnWidth(6, 170)

    layout.addWidget(win.lib_table, 1)

    # 4. Нижняя панель действий
    bottom_row = QHBoxLayout()
    bottom_row.setContentsMargins(0, 0, 0, 0)
    bottom_row.setSpacing(10)

    win.lbl_lib_results_info = QLabel("")
    win.lbl_lib_results_info.setObjectName("RowDesc")
    bottom_row.addWidget(win.lbl_lib_results_info, 1)

    win.btn_lib_add_to_converter = QPushButton(tr("library.btn_add_to_converter_empty"))
    win.btn_lib_add_to_converter.setObjectName("AccentButton")
    win.btn_lib_add_to_converter.setProperty("variant", "primary")
    win.btn_lib_add_to_converter.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_lib_add_to_converter.setEnabled(False)
    win.btn_lib_add_to_converter.clicked.connect(win.add_selected_library_books_to_converter)
    bottom_row.addWidget(win.btn_lib_add_to_converter)

    layout.addLayout(bottom_row)

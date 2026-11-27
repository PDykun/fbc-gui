"""Страница локальной библиотеки INPX в стиле freeLib (навигация, алфавит, дерево книг, описание и обложка)."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from ui.theme import FormatComboBox, PillSelector

_ALPHA_ROW_RU = list("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
_ALPHA_ROW_EN = ["*", "#"] + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def build_library_page(win, parent):
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    # 1. Компактная верхняя панель подключения INPX (интегрирована в окно Библиотеки)
    conn_frame = QFrame()
    conn_frame.setObjectName("SectionCard")
    conn_lay = QVBoxLayout(conn_frame)
    conn_lay.setContentsMargins(12, 8, 12, 8)
    conn_lay.setSpacing(4)

    conn_row = QHBoxLayout()
    conn_row.setContentsMargins(0, 0, 0, 0)
    conn_row.setSpacing(8)

    lbl_inpx = QLabel("INPX:")
    lbl_inpx.setObjectName("RowTitle")
    conn_row.addWidget(lbl_inpx)

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
    layout.addWidget(conn_frame)

    # 2. Основной горизонтальный сплиттер в стиле freeLib (Левая навигация | Правое дерево + карточка книги)
    win.lib_main_splitter = QSplitter(Qt.Orientation.Horizontal)
    win.lib_main_splitter.setChildrenCollapsible(False)
    win.lib_main_splitter.setHandleWidth(6)

    # --- ЛЕВАЯ ПАНЕЛЬ: Авторы / Серии / Жанры / Поиск ---
    left_panel = QWidget()
    left_lay = QVBoxLayout(left_panel)
    left_lay.setContentsMargins(0, 0, 4, 0)
    left_lay.setSpacing(8)

    win.lib_mode_selector = PillSelector(
        [
            (tr("library.tab_authors"), "authors"),
            (tr("library.tab_series"), "series"),
            (tr("library.tab_genres"), "genres"),
            (tr("library.tab_search"), "search"),
        ],
        default="authors",
        callback=win.on_library_mode_changed,
        segmented=True,
    )
    left_lay.addWidget(win.lib_mode_selector)

    win.lib_left_stack = QStackedWidget()

    # Страница 0: Фильтр + список сущностей (Авторы / Серии / Жанры)
    browse_page = QWidget()
    browse_lay = QVBoxLayout(browse_page)
    browse_lay.setContentsMargins(0, 0, 0, 0)
    browse_lay.setSpacing(6)

    flt_row = QHBoxLayout()
    flt_row.setContentsMargins(0, 0, 0, 0)
    flt_row.setSpacing(6)
    lbl_flt = QLabel(tr("library.lbl_filter"))
    lbl_flt.setObjectName("RowDesc")
    flt_row.addWidget(lbl_flt)

    win.lib_left_filter_edit = QLineEdit()
    win.lib_left_filter_edit.setPlaceholderText(tr("library.ph_filter"))
    win.lib_left_filter_edit.setClearButtonEnabled(True)
    win.lib_left_filter_edit.textChanged.connect(win.on_library_left_filter_changed)
    flt_row.addWidget(win.lib_left_filter_edit, 1)
    browse_lay.addLayout(flt_row)

    win.lib_entity_list = QListWidget()
    win.lib_entity_list.setUniformItemSizes(True)
    win.lib_entity_list.setAlternatingRowColors(False)
    win.lib_entity_list.currentItemChanged.connect(win.on_library_entity_selected)
    browse_lay.addWidget(win.lib_entity_list, 1)

    win.lib_left_stack.addWidget(browse_page)

    # Страница 1: Многополевой поиск (вкладка «Поиск»)
    search_page = QWidget()
    search_lay = QVBoxLayout(search_page)
    search_lay.setContentsMargins(2, 4, 2, 0)
    search_lay.setSpacing(8)

    def _add_search_field(label_key, placeholder_key):
        lbl = QLabel(tr(label_key))
        lbl.setObjectName("RowDesc")
        search_lay.addWidget(lbl)
        ed = QLineEdit()
        ed.setPlaceholderText(tr(placeholder_key))
        ed.setClearButtonEnabled(True)
        ed.returnPressed.connect(win.run_library_advanced_search)
        search_lay.addWidget(ed)
        return ed

    win.lib_adv_title_edit = _add_search_field("library.lbl_search_title", "library.ph_search_title")
    win.lib_adv_author_edit = _add_search_field("library.lbl_search_author", "library.ph_search_author")
    win.lib_adv_series_edit = _add_search_field("library.lbl_search_series", "library.ph_search_series")
    win.lib_adv_genre_edit = _add_search_field("library.lbl_search_genre", "library.ph_search_genre")

    btn_search_row = QHBoxLayout()
    btn_search_row.setContentsMargins(0, 4, 0, 0)
    btn_search_row.setSpacing(8)

    win.btn_lib_adv_search = QPushButton(tr("library.btn_find"))
    win.btn_lib_adv_search.setObjectName("AccentButton")
    win.btn_lib_adv_search.setProperty("variant", "primary")
    win.btn_lib_adv_search.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_lib_adv_search.clicked.connect(win.run_library_advanced_search)
    btn_search_row.addWidget(win.btn_lib_adv_search, 1)

    win.btn_lib_adv_clear = QPushButton(tr("library.btn_clear"))
    win.btn_lib_adv_clear.setObjectName("SecondaryButton")
    win.btn_lib_adv_clear.setProperty("variant", "secondary")
    win.btn_lib_adv_clear.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_lib_adv_clear.clicked.connect(win.clear_library_advanced_search)
    btn_search_row.addWidget(win.btn_lib_adv_clear)
    search_lay.addLayout(btn_search_row)

    win.lbl_lib_search_hint = QLabel(tr("library.search_hint"))
    win.lbl_lib_search_hint.setObjectName("RowDesc")
    win.lbl_lib_search_hint.setWordWrap(True)
    search_lay.addWidget(win.lbl_lib_search_hint)
    search_lay.addStretch()

    win.lib_left_stack.addWidget(search_page)
    left_lay.addWidget(win.lib_left_stack, 1)

    win.lib_main_splitter.addWidget(left_panel)

    # --- ПРАВАЯ ПАНЕЛЬ: Панель управления + Алфавит + Дерево книг + Карточка/Обложка ---
    right_panel = QWidget()
    right_lay = QVBoxLayout(right_panel)
    right_lay.setContentsMargins(4, 0, 0, 0)
    right_lay.setSpacing(6)

    # Верхняя панель фильтров и отправки в конвертер
    top_ctrl = QHBoxLayout()
    top_ctrl.setContentsMargins(0, 0, 0, 0)
    top_ctrl.setSpacing(8)

    lbl_lang = QLabel(tr("library.lbl_lang"))
    lbl_lang.setObjectName("RowDesc")
    top_ctrl.addWidget(lbl_lang)

    win.lib_lang_combo = FormatComboBox()
    win.lib_lang_combo.setMinimumWidth(115)
    win.lib_lang_combo.addItem(tr("library.lang_all"), "all")
    win.lib_lang_combo.currentIndexChanged.connect(lambda _idx: win.on_library_lang_or_del_changed())
    top_ctrl.addWidget(win.lib_lang_combo)

    win.chk_lib_hide_deleted = QCheckBox(tr("library.chk_hide_deleted"))
    win.chk_lib_hide_deleted.setChecked(True)
    win.chk_lib_hide_deleted.setCursor(Qt.CursorShape.PointingHandCursor)
    win.chk_lib_hide_deleted.toggled.connect(lambda _chk: win.on_library_lang_or_del_changed())
    top_ctrl.addWidget(win.chk_lib_hide_deleted)

    top_ctrl.addStretch()

    win.lbl_lib_results_info = QLabel("")
    win.lbl_lib_results_info.setObjectName("RowDesc")
    top_ctrl.addWidget(win.lbl_lib_results_info)

    win.btn_lib_add_to_converter = QPushButton(tr("library.btn_add_to_converter_empty"))
    win.btn_lib_add_to_converter.setObjectName("AccentButton")
    win.btn_lib_add_to_converter.setProperty("variant", "primary")
    win.btn_lib_add_to_converter.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_lib_add_to_converter.setEnabled(False)
    win.btn_lib_add_to_converter.clicked.connect(win.add_selected_library_books_to_converter)
    top_ctrl.addWidget(win.btn_lib_add_to_converter)

    right_lay.addLayout(top_ctrl)

    # Алфавитная линейка в 2 ряда (RU + * # EN), как в freeLib
    win.lib_alpha_container = QWidget()
    alpha_v = QVBoxLayout(win.lib_alpha_container)
    alpha_v.setContentsMargins(0, 0, 0, 0)
    alpha_v.setSpacing(3)

    win.lib_alpha_buttons = {}
    for row_letters in (_ALPHA_ROW_RU, _ALPHA_ROW_EN):
        row_lay = QHBoxLayout()
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(2)
        for ch in row_letters:
            btn = QPushButton(ch)
            btn.setCheckable(True)
            btn.setChecked(ch == "*")
            btn.setFixedHeight(24)
            btn.setMinimumWidth(22)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("QPushButton { padding: 1px 2px; font-size: 11px; border-radius: 4px; }")
            btn.clicked.connect(lambda _chk=False, letter=ch: win.on_library_alpha_clicked(letter))
            row_lay.addWidget(btn)
            win.lib_alpha_buttons[ch] = btn
        if row_letters is _ALPHA_ROW_EN:
            row_lay.addStretch(5)
        alpha_v.addLayout(row_lay)

    right_lay.addWidget(win.lib_alpha_container)

    # Вертикальный сплиттер: сверху дерево книг, снизу карточка описания + обложка
    win.lib_right_splitter = QSplitter(Qt.Orientation.Vertical)
    win.lib_right_splitter.setChildrenCollapsible(False)
    win.lib_right_splitter.setHandleWidth(6)

    # Дерево книг (Автор -> Серия -> Книги)
    win.lib_book_tree = QTreeWidget()
    win.lib_book_tree.setColumnCount(6)
    win.lib_book_tree.setHeaderLabels(tr("library.tree_columns"))
    win.lib_book_tree.setAlternatingRowColors(True)
    win.lib_book_tree.setUniformRowHeights(True)
    win.lib_book_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    win.lib_book_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    win.lib_book_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    win.lib_book_tree.customContextMenuRequested.connect(win.on_library_tree_context_menu)
    win.lib_book_tree.itemChanged.connect(win.on_library_tree_item_changed)
    win.lib_book_tree.currentItemChanged.connect(win.on_library_tree_current_changed)
    win.lib_book_tree.itemSelectionChanged.connect(win.on_library_selection_changed)
    win.lib_book_tree.itemDoubleClicked.connect(win.on_library_tree_double_clicked)

    thdr = win.lib_book_tree.header()
    thdr.setStretchLastSection(False)
    thdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    thdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    thdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    thdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    thdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
    thdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
    win.lib_book_tree.setColumnWidth(5, 160)

    win.lib_right_splitter.addWidget(win.lib_book_tree)

    # Нижняя панель: описание книги (слева) + обложка (справа)
    details_frame = QFrame()
    details_frame.setObjectName("SectionCard")
    details_lay = QHBoxLayout(details_frame)
    details_lay.setContentsMargins(12, 10, 12, 10)
    details_lay.setSpacing(12)

    win.lib_book_details = QTextBrowser()
    win.lib_book_details.setOpenLinks(False)
    win.lib_book_details.setReadOnly(True)
    win.lib_book_details.setFrameShape(QFrame.Shape.NoFrame)
    win.lib_book_details.anchorClicked.connect(win.on_library_detail_link_clicked)
    details_lay.addWidget(win.lib_book_details, 1)

    win.lib_book_cover = QLabel(tr("library.cover_placeholder"))
    win.lib_book_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
    win.lib_book_cover.setMinimumWidth(160)
    win.lib_book_cover.setMaximumWidth(230)
    win.lib_book_cover.setWordWrap(True)
    win.lib_book_cover.setObjectName("RowDesc")
    details_lay.addWidget(win.lib_book_cover)

    win.lib_right_splitter.addWidget(details_frame)
    win.lib_right_splitter.setSizes([380, 250])

    right_lay.addWidget(win.lib_right_splitter, 1)

    win.lib_main_splitter.addWidget(right_panel)
    win.lib_main_splitter.setSizes([310, 820])

    layout.addWidget(win.lib_main_splitter, 1)

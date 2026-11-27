import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QScrollArea, QGridLayout, QTextEdit, QFrame
)

from core.css_preview import BASE_FONT_SIZE_OPTIONS, VALID_FONT_EXTENSIONS
from core.i18n import (
    tr, get_align_options, get_style_options,
    get_note_bg_options, get_note_border_options
)
from ui.theme import ColorPickerWidget, create_section_card


class FontDropZone(QFrame):
    """Карточка drag-and-drop для установки пользовательских шрифтов с подсветкой при наведении."""

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self._win = win
        self.setObjectName("FontDropZone")
        self.setProperty("dragActive", False)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _set_drag_active(self, active):
        if bool(self.property("dragActive")) != bool(active):
            self.setProperty("dragActive", bool(active))
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def _extract_font_paths(self, mime_data):
        if not mime_data or not mime_data.hasUrls():
            return []
        out = []
        for url in mime_data.urls():
            p = url.toLocalFile()
            if p and os.path.isfile(p) and p.lower().endswith(VALID_FONT_EXTENSIONS):
                out.append(p)
        return out

    def dragEnterEvent(self, event):
        if self._extract_font_paths(event.mimeData()):
            self._set_drag_active(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drag_active(False)
        paths = self._extract_font_paths(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self._win._install_font_files(paths)
        else:
            event.ignore()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._win.add_user_fonts_clicked()
            event.accept()
            return
        super().mousePressEvent(event)


def _build_css_top_bar(win):
    top_bar = QHBoxLayout()
    lbl_info = QLabel(tr("styles.info_bar"))
    lbl_info.setObjectName("RowDesc")
    top_bar.addWidget(lbl_info)
    top_bar.addStretch()

    win.btn_reset_css = QPushButton(tr("styles.btn_reset"))
    win.btn_reset_css.setObjectName("SecondaryButton")
    win.btn_reset_css.setProperty("variant", "secondary")
    win.btn_reset_css.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_reset_css.clicked.connect(lambda: win.reset_visual_css(show_alert=True))
    top_bar.addWidget(win.btn_reset_css)

    btn_save_css = QPushButton(tr("styles.btn_save"))
    btn_save_css.setObjectName("AccentButton")
    btn_save_css.setProperty("variant", "primary")
    btn_save_css.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_save_css.clicked.connect(lambda: win.save_visual_css(show_alert=True))
    top_bar.addWidget(btn_save_css)
    return top_bar


def _build_fonts_section(win, available_fonts):
    c_fonts, l_fonts = create_section_card(tr("styles.sec_fonts"))
    fonts_row = QHBoxLayout()
    fonts_row.setContentsMargins(0, 0, 0, 0)
    fonts_row.setSpacing(16)

    g_fonts = QGridLayout()
    g_fonts.setContentsMargins(0, 0, 0, 0)
    g_fonts.setHorizontalSpacing(10)
    g_fonts.setVerticalSpacing(10)
    g_fonts.setColumnStretch(0, 0)
    g_fonts.setColumnStretch(1, 1)
    g_fonts.setColumnStretch(2, 0)
    g_fonts.setColumnMinimumWidth(2, 12)
    g_fonts.setColumnStretch(3, 0)
    g_fonts.setColumnStretch(4, 1)

    font_options = [(tr("styles.font_none"), "__none__")] + [(f, f) for f in available_fonts]
    default_para = "PT-Astra-Serif_Regular.ttf" if "PT-Astra-Serif_Regular.ttf" in available_fonts else "__none__"
    default_drop = "PomorskyUnicode.otf" if "PomorskyUnicode.otf" in available_fonts else "__none__"

    for attr, def_val in (
        ("font_para_cb", default_para),
        ("font_drop_cb", default_drop),
        ("font_title_cb", default_para),
        ("font_author_cb", default_para),
    ):
        cb = QComboBox()
        win._populate_data_combo(cb, font_options, def_val)
        cb.currentIndexChanged.connect(win.on_style_param_changed)
        setattr(win, attr, cb)

    g_fonts.addWidget(QLabel(tr("styles.lbl_font_para")), 0, 0)
    g_fonts.addWidget(win.font_para_cb, 0, 1)
    g_fonts.addWidget(QLabel(tr("styles.lbl_font_drop")), 0, 3)
    g_fonts.addWidget(win.font_drop_cb, 0, 4)
    g_fonts.addWidget(QLabel(tr("styles.lbl_font_title")), 1, 0)
    g_fonts.addWidget(win.font_title_cb, 1, 1)
    g_fonts.addWidget(QLabel(tr("styles.lbl_font_author")), 1, 3)
    g_fonts.addWidget(win.font_author_cb, 1, 4)

    win.pdf_frame_cb = QComboBox()
    win._populate_data_combo(
        win.pdf_frame_cb,
        [(tr("styles.pdf_frame_off"), "0"), ("0.5pt", "0.5pt"), ("1pt", "1pt"), ("1px", "1px"), ("2px", "2px")],
        "0"
    )
    pdf_frame_tip = tr("styles.tooltip_pdf_frame")
    win.pdf_frame_cb.setToolTip(pdf_frame_tip)
    win.pdf_frame_cb.currentIndexChanged.connect(win.on_style_param_changed)
    lbl_pdf_frame = QLabel(tr("styles.lbl_pdf_frame"))
    lbl_pdf_frame.setToolTip(pdf_frame_tip)
    g_fonts.addWidget(lbl_pdf_frame, 2, 0)
    g_fonts.addWidget(win.pdf_frame_cb, 2, 1)

    base_fs_options = [
        (tr("styles.base_font_default"), "default")
    ] + [(sz, sz) for sz in BASE_FONT_SIZE_OPTIONS if sz != "default"]
    win.base_font_size_cb = QComboBox()
    win._populate_data_combo(win.base_font_size_cb, base_fs_options, "default")
    base_fs_tip = tr("styles.tooltip_base_font_size")
    win.base_font_size_cb.setToolTip(base_fs_tip)
    win.base_font_size_cb.currentIndexChanged.connect(win.on_style_param_changed)
    lbl_base_fs = QLabel(tr("styles.lbl_base_font_size"))
    lbl_base_fs.setToolTip(base_fs_tip)
    g_fonts.addWidget(lbl_base_fs, 2, 3)
    g_fonts.addWidget(win.base_font_size_cb, 2, 4)

    fonts_row.addLayout(g_fonts, 1)

    win.font_drop_zone = FontDropZone(win)
    win.font_drop_zone.setMinimumWidth(260)
    win.font_drop_zone.setMaximumWidth(340)
    dz_layout = QVBoxLayout(win.font_drop_zone)
    dz_layout.setContentsMargins(14, 10, 14, 10)
    dz_layout.setSpacing(6)
    dz_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

    lbl_dz_title = QLabel(tr("styles.drop_fonts_title"))
    lbl_dz_title.setObjectName("FontDropTitle")
    lbl_dz_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    dz_layout.addWidget(lbl_dz_title)

    win.lbl_fonts_drop_hint = QLabel(tr("styles.drop_fonts_hint", count=len(available_fonts)))
    win.lbl_fonts_drop_hint.setObjectName("FontDropHint")
    win.lbl_fonts_drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    dz_layout.addWidget(win.lbl_fonts_drop_hint)

    font_mgr_row = QHBoxLayout()
    font_mgr_row.setContentsMargins(0, 4, 0, 0)
    font_mgr_row.setSpacing(8)
    font_mgr_row.addStretch()

    win.btn_add_fonts = QPushButton(tr("styles.btn_add_fonts"))
    win.btn_add_fonts.setObjectName("SecondaryButton")
    win.btn_add_fonts.setProperty("variant", "secondary")
    win.btn_add_fonts.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_add_fonts.clicked.connect(win.add_user_fonts_clicked)
    font_mgr_row.addWidget(win.btn_add_fonts)

    win.btn_open_fonts_dir = QPushButton(tr("styles.btn_open_fonts_dir"))
    win.btn_open_fonts_dir.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_open_fonts_dir.clicked.connect(win.open_fonts_folder_clicked)
    font_mgr_row.addWidget(win.btn_open_fonts_dir)
    font_mgr_row.addStretch()

    dz_layout.addLayout(font_mgr_row)
    fonts_row.addWidget(win.font_drop_zone, 0)
    l_fonts.addLayout(fonts_row)
    return c_fonts


def _build_headings_section(win, colors_list, sizes_list, align_options, style_options):
    c_hdr, l_hdr = create_section_card(tr("styles.sec_headings"))
    g_hdr = QGridLayout()
    g_hdr.setSpacing(10)

    win.h1_sz_cb = QComboBox()
    win.h1_sz_cb.addItems(sizes_list)
    win.h1_sz_cb.setCurrentText("150%")
    win.h1_sz_cb.currentTextChanged.connect(win.on_style_param_changed)
    win.h1_cl_cb = ColorPickerWidget(values=colors_list, default_color="red")
    win.h1_cl_cb.bind("<<ComboboxSelected>>", win.on_style_param_changed)
    win.h1_al_cb = QComboBox()
    win._populate_data_combo(win.h1_al_cb, align_options, "center")
    win.h1_al_cb.currentIndexChanged.connect(win.on_style_param_changed)

    g_hdr.addWidget(QLabel(tr("styles.lbl_book_title")), 0, 0)
    g_hdr.addWidget(QLabel(tr("styles.lbl_size")), 0, 1)
    g_hdr.addWidget(win.h1_sz_cb, 0, 2)
    g_hdr.addWidget(QLabel(tr("styles.lbl_color")), 0, 3)
    g_hdr.addWidget(win.h1_cl_cb, 0, 4)
    g_hdr.addWidget(QLabel(tr("styles.lbl_align")), 0, 5)
    g_hdr.addWidget(win.h1_al_cb, 0, 6)

    win.auth_sz_cb = QComboBox()
    win.auth_sz_cb.addItems(sizes_list)
    win.auth_sz_cb.setCurrentText("110%")
    win.auth_sz_cb.currentTextChanged.connect(win.on_style_param_changed)
    win.auth_cl_cb = ColorPickerWidget(values=colors_list, default_color="green")
    win.auth_cl_cb.bind("<<ComboboxSelected>>", win.on_style_param_changed)
    win.auth_al_cb = QComboBox()
    win._populate_data_combo(win.auth_al_cb, align_options, "center")
    win.auth_al_cb.currentIndexChanged.connect(win.on_style_param_changed)
    win.auth_style_cb = QComboBox()
    win._populate_data_combo(win.auth_style_cb, style_options, "italic")
    win.auth_style_cb.currentIndexChanged.connect(win.on_style_param_changed)

    g_hdr.addWidget(QLabel(tr("styles.lbl_book_author")), 1, 0)
    g_hdr.addWidget(QLabel(tr("styles.lbl_size")), 1, 1)
    g_hdr.addWidget(win.auth_sz_cb, 1, 2)
    g_hdr.addWidget(QLabel(tr("styles.lbl_color")), 1, 3)
    g_hdr.addWidget(win.auth_cl_cb, 1, 4)
    g_hdr.addWidget(QLabel(tr("styles.lbl_align")), 1, 5)
    g_hdr.addWidget(win.auth_al_cb, 1, 6)
    g_hdr.addWidget(QLabel(tr("styles.lbl_style")), 1, 7)
    g_hdr.addWidget(win.auth_style_cb, 1, 8)

    win.header_vars = {"h1": {"size": win.h1_sz_cb, "color": win.h1_cl_cb, "align": win.h1_al_cb}}
    h_configs = [
        (tr("styles.lbl_h2"), "h2", "130%", "blue", "center"),
        (tr("styles.lbl_h3"), "h3", "120%", "purple", "center"),
        (tr("styles.lbl_h4"), "h4", "120%", "green", "center"),
        (tr("styles.lbl_h5"), "h5", "120%", "magenta", "center"),
    ]
    for idx, (lbl_text, key, def_sz, def_cl, def_al) in enumerate(h_configs, start=2):
        sz_cb = QComboBox()
        sz_cb.addItems(sizes_list)
        sz_cb.setCurrentText(def_sz)
        sz_cb.currentTextChanged.connect(win.on_style_param_changed)
        cl_cb = ColorPickerWidget(values=colors_list, default_color=def_cl)
        cl_cb.bind("<<ComboboxSelected>>", win.on_style_param_changed)
        al_cb = QComboBox()
        win._populate_data_combo(al_cb, align_options, def_al)
        al_cb.currentIndexChanged.connect(win.on_style_param_changed)

        g_hdr.addWidget(QLabel(lbl_text), idx, 0)
        g_hdr.addWidget(QLabel(tr("styles.lbl_size")), idx, 1)
        g_hdr.addWidget(sz_cb, idx, 2)
        g_hdr.addWidget(QLabel(tr("styles.lbl_color")), idx, 3)
        g_hdr.addWidget(cl_cb, idx, 4)
        g_hdr.addWidget(QLabel(tr("styles.lbl_align")), idx, 5)
        g_hdr.addWidget(al_cb, idx, 6)
        win.header_vars[key] = {"size": sz_cb, "color": cl_cb, "align": al_cb}

    l_hdr.addLayout(g_hdr)
    return c_hdr


def _build_body_section(win, colors_list, align_options):
    c_body, l_body = create_section_card(tr("styles.sec_body"))
    g_body = QGridLayout()
    g_body.setSpacing(10)

    win.p_align_cb = QComboBox()
    win._populate_data_combo(win.p_align_cb, align_options, "justify")
    win.p_align_cb.currentIndexChanged.connect(win.on_style_param_changed)

    win.text_indent_cb = QComboBox()
    win.text_indent_cb.addItems(["0", "0.5em", "1em", "1.5em", "2em"])
    win.text_indent_cb.setCurrentText("1em")
    win.text_indent_cb.currentTextChanged.connect(win.on_style_param_changed)

    win.sub_align_cb = QComboBox()
    win._populate_data_combo(win.sub_align_cb, align_options, "center")
    win.sub_align_cb.currentIndexChanged.connect(win.on_style_param_changed)

    win.drop_color_cb = ColorPickerWidget(values=colors_list, default_color="red")
    win.drop_color_cb.bind("<<ComboboxSelected>>", win.on_style_param_changed)

    win.drop_size_cb = QComboBox()
    win.drop_size_cb.addItems(["2em", "2.5em", "3em", "3.5em", "4em"])
    win.drop_size_cb.setCurrentText("3em")
    win.drop_size_cb.currentTextChanged.connect(win.on_style_param_changed)

    g_body.addWidget(QLabel(tr("styles.lbl_p_align")), 0, 0)
    g_body.addWidget(win.p_align_cb, 0, 1)
    g_body.addWidget(QLabel(tr("styles.lbl_indent")), 0, 2)
    g_body.addWidget(win.text_indent_cb, 0, 3)
    g_body.addWidget(QLabel(tr("styles.lbl_sub_align")), 0, 4)
    g_body.addWidget(win.sub_align_cb, 0, 5)
    g_body.addWidget(QLabel(tr("styles.lbl_drop_color")), 1, 0)
    g_body.addWidget(win.drop_color_cb, 1, 1)
    g_body.addWidget(QLabel(tr("styles.lbl_drop_size")), 1, 2)
    g_body.addWidget(win.drop_size_cb, 1, 3)
    l_body.addLayout(g_body)
    return c_body


def _build_extra_elements_section(win, colors_list, sizes_list, align_options, style_options):
    c_extra, l_extra = create_section_card(tr("styles.sec_extra"))
    g_extra = QGridLayout()
    g_extra.setSpacing(10)

    block_rows = (
        ("anno", "styles.lbl_anno", "80%", "blue", align_options, "center", "normal"),
        ("epi", "styles.lbl_epi", "100%", "dimgray", get_align_options(("right", "center", "left")), "right", "italic"),
        ("poem", "styles.lbl_poem", "100%", "purple", get_align_options(("left", "center", "justify")), "left", "italic"),
    )
    for row_idx, (prefix, lbl_key, def_sz, def_cl, al_opts, def_al, def_st) in enumerate(block_rows):
        sz_cb = QComboBox()
        sz_cb.addItems(sizes_list)
        sz_cb.setCurrentText(def_sz)
        sz_cb.currentTextChanged.connect(win.on_style_param_changed)
        cl_cb = ColorPickerWidget(values=colors_list, default_color=def_cl)
        cl_cb.bind("<<ComboboxSelected>>", win.on_style_param_changed)
        al_cb = QComboBox()
        win._populate_data_combo(al_cb, al_opts, def_al)
        al_cb.currentIndexChanged.connect(win.on_style_param_changed)
        st_cb = QComboBox()
        win._populate_data_combo(st_cb, style_options, def_st)
        st_cb.currentIndexChanged.connect(win.on_style_param_changed)

        setattr(win, f"{prefix}_size_cb", sz_cb)
        setattr(win, f"{prefix}_color_cb", cl_cb)
        setattr(win, f"{prefix}_align_cb", al_cb)
        setattr(win, f"{prefix}_style_cb", st_cb)

        g_extra.addWidget(QLabel(tr(lbl_key)), row_idx, 0)
        g_extra.addWidget(sz_cb, row_idx, 1)
        g_extra.addWidget(cl_cb, row_idx, 2)
        g_extra.addWidget(al_cb, row_idx, 3)
        g_extra.addWidget(st_cb, row_idx, 4)

    win.note_size_cb = QComboBox()
    win.note_size_cb.addItems(sizes_list)
    win.note_size_cb.setCurrentText("80%")
    win.note_size_cb.currentTextChanged.connect(win.on_style_param_changed)
    win.note_color_cb = ColorPickerWidget(values=colors_list, default_color="black")
    win.note_color_cb.bind("<<ComboboxSelected>>", win.on_style_param_changed)
    win.note_bg_cb = QComboBox()
    win._populate_data_combo(win.note_bg_cb, get_note_bg_options(), "#e6e6fa")
    win.note_bg_cb.currentIndexChanged.connect(win.on_style_param_changed)
    win.note_border_cb = QComboBox()
    win._populate_data_combo(win.note_border_cb, get_note_border_options(), "1px #505050 solid")
    win.note_border_cb.currentIndexChanged.connect(win.on_style_param_changed)
    win.note_style_cb = QComboBox()
    win._populate_data_combo(win.note_style_cb, style_options, "italic")
    win.note_style_cb.currentIndexChanged.connect(win.on_style_param_changed)

    g_extra.addWidget(QLabel(tr("styles.lbl_note")), 3, 0)
    g_extra.addWidget(win.note_size_cb, 3, 1)
    g_extra.addWidget(win.note_color_cb, 3, 2)
    g_extra.addWidget(win.note_bg_cb, 3, 3)
    g_extra.addWidget(win.note_border_cb, 3, 4)
    g_extra.addWidget(win.note_style_cb, 3, 5)
    l_extra.addLayout(g_extra)
    return c_extra


def _build_images_section(win, colors_list, sizes_list, style_options):
    c_img, l_img = create_section_card(tr("styles.sec_images"))
    g_img = QGridLayout()
    g_img.setSpacing(10)

    win.img_align_cb = QComboBox()
    win._populate_data_combo(win.img_align_cb, get_align_options(("center", "left", "right")), "center")
    win.img_align_cb.currentIndexChanged.connect(win.on_style_param_changed)

    win.img_width_cb = QComboBox()
    win.img_width_cb.addItems(["100%", "95%", "90%", "85%", "80%", "75%", "70%", "60%", "50%"])
    win.img_width_cb.setCurrentText("100%")
    win.img_width_cb.currentTextChanged.connect(win.on_style_param_changed)

    win.img_cap_sz_cb = QComboBox()
    win.img_cap_sz_cb.addItems(sizes_list)
    win.img_cap_sz_cb.setCurrentText("85%")
    win.img_cap_sz_cb.currentTextChanged.connect(win.on_style_param_changed)

    win.img_cap_cl_cb = ColorPickerWidget(values=colors_list, default_color="dimgray")
    win.img_cap_cl_cb.bind("<<ComboboxSelected>>", win.on_style_param_changed)

    win.img_cap_st_cb = QComboBox()
    win._populate_data_combo(win.img_cap_st_cb, style_options, "italic")
    win.img_cap_st_cb.currentIndexChanged.connect(win.on_style_param_changed)

    g_img.addWidget(QLabel(tr("styles.lbl_img_block")), 0, 0)
    g_img.addWidget(QLabel(tr("styles.lbl_align")), 0, 1)
    g_img.addWidget(win.img_align_cb, 0, 2)
    g_img.addWidget(QLabel(tr("styles.lbl_max_width")), 0, 3)
    g_img.addWidget(win.img_width_cb, 0, 4)

    g_img.addWidget(QLabel(tr("styles.lbl_img_cap")), 1, 0)
    g_img.addWidget(QLabel(tr("styles.lbl_size")), 1, 1)
    g_img.addWidget(win.img_cap_sz_cb, 1, 2)
    g_img.addWidget(QLabel(tr("styles.lbl_color")), 1, 3)
    g_img.addWidget(win.img_cap_cl_cb, 1, 4)
    g_img.addWidget(QLabel(tr("styles.lbl_style")), 1, 5)
    g_img.addWidget(win.img_cap_st_cb, 1, 6)

    win.grayscale_cb = QComboBox()
    win._populate_data_combo(
        win.grayscale_cb,
        [(tr("styles.grayscale.none"), "none"), (tr("styles.grayscale.luma"), "luma")],
        win.app_settings.get("grayscale", "none")
    )
    win.grayscale_cb.currentIndexChanged.connect(win.on_grayscale_changed)

    win.fit_to_screen_cb = QComboBox()
    win._populate_data_combo(
        win.fit_to_screen_cb,
        [(tr("styles.fit_to_screen.false"), "false"), (tr("styles.fit_to_screen.true"), "true")],
        win.app_settings.get("fit_to_screen", "false")
    )
    win.fit_to_screen_cb.currentIndexChanged.connect(win.on_fit_to_screen_changed)

    win.cover_resize_cb = QComboBox()
    win._populate_data_combo(
        win.cover_resize_cb,
        [
            (tr("styles.cover_resize.keepAR"), "keepAR"),
            (tr("styles.cover_resize.fill"), "fill"),
            (tr("styles.cover_resize.fit"), "fit"),
            (tr("styles.cover_resize.stretch"), "stretch"),
            (tr("styles.cover_resize.none"), "none")
        ],
        win.app_settings.get("cover_resize", "keepAR")
    )
    win.cover_resize_cb.currentIndexChanged.connect(win.on_cover_resize_changed)

    from core.image_optimizer import get_image_display_profile_choices

    win.image_color_profile_cb = QComboBox()
    win._populate_data_combo(
        win.image_color_profile_cb,
        get_image_display_profile_choices(translator=tr),
        win.app_settings.get("image_color_profile", "none"),
    )
    img_prof_tip = tr("styles.tooltip_img_profile")
    win.image_color_profile_cb.setToolTip(img_prof_tip)
    win.image_color_profile_cb.currentIndexChanged.connect(win.on_image_color_profile_changed)

    g_img.addWidget(QLabel(tr("styles.lbl_grayscale")), 2, 0)
    g_img.addWidget(win.grayscale_cb, 2, 1, 1, 2)
    g_img.addWidget(QLabel(tr("styles.lbl_fit_to_screen")), 2, 3)
    g_img.addWidget(win.fit_to_screen_cb, 2, 4)
    g_img.addWidget(QLabel(tr("styles.lbl_cover_resize")), 2, 5)
    g_img.addWidget(win.cover_resize_cb, 2, 6)

    lbl_img_prof = QLabel(tr("styles.lbl_img_profile"))
    lbl_img_prof.setToolTip(img_prof_tip)
    g_img.addWidget(lbl_img_prof, 3, 0)
    g_img.addWidget(win.image_color_profile_cb, 3, 1, 1, 4)

    l_img.addLayout(g_img)
    return c_img


def _build_css_code_section(win):
    c_code, l_code = create_section_card(tr("styles.sec_css_code"))
    win.css_preview_text = QTextEdit()
    win.css_preview_text.setFixedHeight(110)
    win.css_preview_text.setReadOnly(True)
    l_code.addWidget(win.css_preview_text)
    return c_code


def build_visual_css_page(win, parent):
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    layout.addLayout(_build_css_top_bar(win))

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll_content = QWidget()
    scroll_content.setObjectName("ScrollContent")
    scroll_content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    scroll_layout = QVBoxLayout(scroll_content)
    scroll_layout.setContentsMargins(0, 0, 8, 0)
    scroll_layout.setSpacing(14)

    colors_list = ["red", "blue", "purple", "green", "magenta", "fuchsia", "black", "navy", "darkred", "dimgray"]
    sizes_list = ["70%", "80%", "85%", "90%", "100%", "110%", "120%", "130%", "140%", "150%", "160%", "180%", "200%"]
    align_options = get_align_options()
    style_options = get_style_options()
    available_fonts = win.get_available_fonts()

    scroll_layout.addWidget(_build_fonts_section(win, available_fonts))
    scroll_layout.addWidget(_build_headings_section(win, colors_list, sizes_list, align_options, style_options))
    scroll_layout.addWidget(_build_body_section(win, colors_list, align_options))
    scroll_layout.addWidget(_build_extra_elements_section(win, colors_list, sizes_list, align_options, style_options))
    scroll_layout.addWidget(_build_images_section(win, colors_list, sizes_list, style_options))
    scroll_layout.addWidget(_build_css_code_section(win))

    scroll.setWidget(scroll_content)
    layout.addWidget(scroll, 1)
    if hasattr(win, "sync_style_color_palettes"):
        win.sync_style_color_palettes()

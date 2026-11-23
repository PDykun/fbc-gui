from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QScrollArea, QGridLayout, QTextEdit
)

from core.i18n import (
    tr, get_align_options, get_style_options,
    get_note_bg_options, get_note_border_options
)
from ui.theme import ColorPickerWidget, create_section_card


def build_visual_css_page(win, parent):
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

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
    layout.addLayout(top_bar)

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

    c_fonts, l_fonts = create_section_card(tr("styles.sec_fonts"))
    g_fonts = QGridLayout()
    g_fonts.setSpacing(10)

    font_options = [(tr("styles.font_none"), "__none__")] + [(f, f) for f in available_fonts]
    default_para = "PT-Astra-Serif_Regular.ttf" if "PT-Astra-Serif_Regular.ttf" in available_fonts else "__none__"
    default_drop = "PomorskyUnicode.otf" if "PomorskyUnicode.otf" in available_fonts else "__none__"

    win.font_para_cb = QComboBox()
    win._populate_data_combo(win.font_para_cb, font_options, default_para)
    win.font_para_cb.currentIndexChanged.connect(win.on_style_param_changed)

    win.font_drop_cb = QComboBox()
    win._populate_data_combo(win.font_drop_cb, font_options, default_drop)
    win.font_drop_cb.currentIndexChanged.connect(win.on_style_param_changed)

    win.font_title_cb = QComboBox()
    win._populate_data_combo(win.font_title_cb, font_options, default_para)
    win.font_title_cb.currentIndexChanged.connect(win.on_style_param_changed)

    win.font_author_cb = QComboBox()
    win._populate_data_combo(win.font_author_cb, font_options, default_para)
    win.font_author_cb.currentIndexChanged.connect(win.on_style_param_changed)

    g_fonts.addWidget(QLabel(tr("styles.lbl_font_para")), 0, 0)
    g_fonts.addWidget(win.font_para_cb, 0, 1)
    g_fonts.addWidget(QLabel(tr("styles.lbl_font_drop")), 0, 2)
    g_fonts.addWidget(win.font_drop_cb, 0, 3)
    g_fonts.addWidget(QLabel(tr("styles.lbl_font_title")), 1, 0)
    g_fonts.addWidget(win.font_title_cb, 1, 1)
    g_fonts.addWidget(QLabel(tr("styles.lbl_font_author")), 1, 2)
    g_fonts.addWidget(win.font_author_cb, 1, 3)

    win.pdf_frame_cb = QComboBox()
    win._populate_data_combo(
        win.pdf_frame_cb,
        [(tr("styles.pdf_frame_off"), "0"), ("0.5pt", "0.5pt"), ("1pt", "1pt"), ("1px", "1px"), ("2px", "2px")],
        "0"
    )
    win.pdf_frame_cb.currentIndexChanged.connect(win.on_style_param_changed)
    g_fonts.addWidget(QLabel(tr("styles.lbl_pdf_frame")), 2, 0)
    g_fonts.addWidget(win.pdf_frame_cb, 2, 1)
    l_fonts.addLayout(g_fonts)
    scroll_layout.addWidget(c_fonts)

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
    scroll_layout.addWidget(c_hdr)

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
    scroll_layout.addWidget(c_body)

    c_extra, l_extra = create_section_card(tr("styles.sec_extra"))
    g_extra = QGridLayout()
    g_extra.setSpacing(10)

    win.anno_size_cb = QComboBox()
    win.anno_size_cb.addItems(sizes_list)
    win.anno_size_cb.setCurrentText("80%")
    win.anno_size_cb.currentTextChanged.connect(win.on_style_param_changed)
    win.anno_color_cb = ColorPickerWidget(values=colors_list, default_color="blue")
    win.anno_color_cb.bind("<<ComboboxSelected>>", win.on_style_param_changed)
    win.anno_align_cb = QComboBox()
    win._populate_data_combo(win.anno_align_cb, align_options, "center")
    win.anno_align_cb.currentIndexChanged.connect(win.on_style_param_changed)
    win.anno_style_cb = QComboBox()
    win._populate_data_combo(win.anno_style_cb, style_options, "normal")
    win.anno_style_cb.currentIndexChanged.connect(win.on_style_param_changed)

    g_extra.addWidget(QLabel(tr("styles.lbl_anno")), 0, 0)
    g_extra.addWidget(win.anno_size_cb, 0, 1)
    g_extra.addWidget(win.anno_color_cb, 0, 2)
    g_extra.addWidget(win.anno_align_cb, 0, 3)
    g_extra.addWidget(win.anno_style_cb, 0, 4)

    win.epi_size_cb = QComboBox()
    win.epi_size_cb.addItems(sizes_list)
    win.epi_size_cb.setCurrentText("100%")
    win.epi_size_cb.currentTextChanged.connect(win.on_style_param_changed)
    win.epi_color_cb = ColorPickerWidget(values=colors_list, default_color="dimgray")
    win.epi_color_cb.bind("<<ComboboxSelected>>", win.on_style_param_changed)
    win.epi_align_cb = QComboBox()
    win._populate_data_combo(win.epi_align_cb, get_align_options(("right", "center", "left")), "right")
    win.epi_align_cb.currentIndexChanged.connect(win.on_style_param_changed)
    win.epi_style_cb = QComboBox()
    win._populate_data_combo(win.epi_style_cb, style_options, "italic")
    win.epi_style_cb.currentIndexChanged.connect(win.on_style_param_changed)

    g_extra.addWidget(QLabel(tr("styles.lbl_epi")), 1, 0)
    g_extra.addWidget(win.epi_size_cb, 1, 1)
    g_extra.addWidget(win.epi_color_cb, 1, 2)
    g_extra.addWidget(win.epi_align_cb, 1, 3)
    g_extra.addWidget(win.epi_style_cb, 1, 4)

    win.poem_size_cb = QComboBox()
    win.poem_size_cb.addItems(sizes_list)
    win.poem_size_cb.setCurrentText("100%")
    win.poem_size_cb.currentTextChanged.connect(win.on_style_param_changed)
    win.poem_color_cb = ColorPickerWidget(values=colors_list, default_color="purple")
    win.poem_color_cb.bind("<<ComboboxSelected>>", win.on_style_param_changed)
    win.poem_align_cb = QComboBox()
    win._populate_data_combo(win.poem_align_cb, get_align_options(("left", "center", "justify")), "left")
    win.poem_align_cb.currentIndexChanged.connect(win.on_style_param_changed)
    win.poem_style_cb = QComboBox()
    win._populate_data_combo(win.poem_style_cb, style_options, "italic")
    win.poem_style_cb.currentIndexChanged.connect(win.on_style_param_changed)

    g_extra.addWidget(QLabel(tr("styles.lbl_poem")), 2, 0)
    g_extra.addWidget(win.poem_size_cb, 2, 1)
    g_extra.addWidget(win.poem_color_cb, 2, 2)
    g_extra.addWidget(win.poem_align_cb, 2, 3)
    g_extra.addWidget(win.poem_style_cb, 2, 4)

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
    scroll_layout.addWidget(c_extra)

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

    g_img.addWidget(QLabel(tr("styles.lbl_grayscale")), 2, 0)
    g_img.addWidget(win.grayscale_cb, 2, 1, 1, 2)
    g_img.addWidget(QLabel(tr("styles.lbl_fit_to_screen")), 2, 3)
    g_img.addWidget(win.fit_to_screen_cb, 2, 4)
    g_img.addWidget(QLabel(tr("styles.lbl_cover_resize")), 2, 5)
    g_img.addWidget(win.cover_resize_cb, 2, 6)

    l_img.addLayout(g_img)
    scroll_layout.addWidget(c_img)

    c_code, l_code = create_section_card(tr("styles.sec_css_code"))
    win.css_preview_text = QTextEdit()
    win.css_preview_text.setFixedHeight(110)
    win.css_preview_text.setReadOnly(True)
    l_code.addWidget(win.css_preview_text)
    scroll_layout.addWidget(c_code)

    scroll.setWidget(scroll_content)
    layout.addWidget(scroll, 1)

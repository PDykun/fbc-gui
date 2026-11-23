import os
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QScrollArea, QLineEdit
)

from core.i18n import LOCALE, tr, get_theme_choices
from core.config import DEFAULT_OUTPUT_FORMAT, is_secure_password_storage_available
from core.fb2_processor import FORMAT_EXT_MAP
from ui.theme import PillSelector, FormatComboBox, FilenameTemplateBuilder, create_section_card, add_setting_row


def build_settings_page(win, parent):
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll_content = QWidget()
    scroll_content.setObjectName("ScrollContent")
    scroll_content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    s_layout = QVBoxLayout(scroll_content)
    s_layout.setContentsMargins(0, 0, 8, 0)
    s_layout.setSpacing(16)

    card_presets, l_presets = create_section_card(tr("settings.sec_presets"))
    preset_ctrl = QWidget()
    preset_ctrl_layout = QHBoxLayout(preset_ctrl)
    preset_ctrl_layout.setContentsMargins(0, 0, 0, 0)
    preset_ctrl_layout.setSpacing(8)

    win.user_preset_combo = FormatComboBox()
    win.user_preset_combo.setMinimumWidth(200)
    preset_ctrl_layout.addWidget(win.user_preset_combo)

    win.btn_preset_apply = QPushButton(tr("settings.btn_preset_apply"))
    win.btn_preset_apply.setObjectName("AccentButton")
    win.btn_preset_apply.setProperty("variant", "primary")
    win.btn_preset_apply.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_preset_apply.clicked.connect(win.apply_user_preset_clicked)
    preset_ctrl_layout.addWidget(win.btn_preset_apply)

    win.btn_preset_save = QPushButton(tr("settings.btn_preset_save"))
    win.btn_preset_save.setObjectName("SecondaryButton")
    win.btn_preset_save.setProperty("variant", "secondary")
    win.btn_preset_save.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_preset_save.clicked.connect(win.save_user_preset_clicked)
    preset_ctrl_layout.addWidget(win.btn_preset_save)

    win.btn_preset_delete = QPushButton(tr("settings.btn_preset_delete"))
    win.btn_preset_delete.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_preset_delete.clicked.connect(win.delete_user_preset_clicked)
    preset_ctrl_layout.addWidget(win.btn_preset_delete)

    win.btn_preset_restore = QPushButton(tr("settings.btn_preset_restore"))
    win.btn_preset_restore.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_preset_restore.clicked.connect(win.restore_user_preset_clicked)
    preset_ctrl_layout.addWidget(win.btn_preset_restore)

    win.btn_preset_export = QPushButton(tr("settings.btn_preset_export"))
    win.btn_preset_export.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_preset_export.clicked.connect(win.export_user_preset_clicked)
    preset_ctrl_layout.addWidget(win.btn_preset_export)

    win.btn_preset_import = QPushButton(tr("settings.btn_preset_import"))
    win.btn_preset_import.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_preset_import.clicked.connect(win.import_user_preset_clicked)
    preset_ctrl_layout.addWidget(win.btn_preset_import)

    add_setting_row(
        l_presets,
        tr("settings.lbl_user_preset"),
        tr("settings.desc_user_preset"),
        preset_ctrl
    )
    s_layout.addWidget(card_presets)
    if hasattr(win, "_update_preset_buttons_state"):
        win.user_preset_combo.currentIndexChanged.connect(lambda _idx: win._update_preset_buttons_state())
    if hasattr(win, "refresh_user_presets_combo"):
        win.refresh_user_presets_combo()

    card_fmt, l_fmt = create_section_card(tr("settings.sec_format"))

    win.device_profile_combo = FormatComboBox()
    win.device_profile_combo.setMinimumWidth(220)
    profile_options = [
        (tr("settings.opt_profile_custom"), "custom"),
        (tr("settings.opt_profile_kindle"), "kindle"),
        (tr("settings.opt_profile_kindle_scribe_2024"), "kindle_scribe_2024"),
        (tr("settings.opt_profile_kindle_scribe_2025"), "kindle_scribe_2025"),
        (tr("settings.opt_profile_kindle_scribe_colorsoft"), "kindle_scribe_colorsoft"),
        (tr("settings.opt_profile_kobo"), "kobo"),
        (tr("settings.opt_profile_pocketbook"), "pocketbook"),
        (tr("settings.opt_profile_onyx_boox"), "onyx_boox"),
        (tr("settings.opt_profile_remarkable"), "remarkable"),
        (tr("settings.opt_profile_pdf"), "pdf"),
    ]
    for label, val in profile_options:
        win.device_profile_combo.addItem(label, val)
    cur_profile = win.app_settings.get("device_profile", "custom")
    prof_idx = win.device_profile_combo.findData(cur_profile)
    win.device_profile_combo.setCurrentIndex(prof_idx if prof_idx >= 0 else 0)
    win.device_profile_combo.currentIndexChanged.connect(
        lambda idx: win.on_device_profile_changed(win.device_profile_combo.itemData(idx))
        if idx >= 0 and win.device_profile_combo.itemData(idx) else None
    )
    add_setting_row(
        l_fmt,
        tr("settings.lbl_device_profile"),
        tr("settings.desc_device_profile"),
        win.device_profile_combo
    )

    fmt_options = [(k.upper(), k) for k in FORMAT_EXT_MAP.keys()]
    win.format_selector = PillSelector(
        fmt_options,
        default=win.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT),
        callback=win.on_format_changed
    )
    add_setting_row(
        l_fmt,
        tr("settings.lbl_format"),
        tr("settings.desc_format"),
        win.format_selector
    )

    scr_widget = QWidget()
    scr_layout = QHBoxLayout(scr_widget)
    scr_layout.setContentsMargins(0, 0, 0, 0)
    scr_layout.setSpacing(6)

    win.screen_w_edit = QLineEdit(str(win.app_settings.get("screen_width", "1264")))
    win.screen_w_edit.setFixedWidth(68)
    win.screen_w_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    win.screen_w_edit.textEdited.connect(lambda v: win.on_screen_param_changed("screen_width", v))
    scr_layout.addWidget(win.screen_w_edit)

    scr_layout.addWidget(QLabel("×"))

    win.screen_h_edit = QLineEdit(str(win.app_settings.get("screen_height", "1680")))
    win.screen_h_edit.setFixedWidth(68)
    win.screen_h_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    win.screen_h_edit.textEdited.connect(lambda v: win.on_screen_param_changed("screen_height", v))
    scr_layout.addWidget(win.screen_h_edit)

    scr_layout.addWidget(QLabel("px   DPI:"))

    win.screen_dpi_edit = QLineEdit(str(win.app_settings.get("screen_dpi", "300")))
    win.screen_dpi_edit.setFixedWidth(56)
    win.screen_dpi_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    win.screen_dpi_edit.textEdited.connect(lambda v: win.on_screen_param_changed("screen_dpi", v))
    scr_layout.addWidget(win.screen_dpi_edit)

    add_setting_row(
        l_fmt,
        tr("settings.lbl_screen_size"),
        tr("settings.desc_screen_size"),
        scr_widget
    )

    fn_mode = win.app_settings.get("filename_mode", "default")
    win.filename_mode_selector = PillSelector(
        [
            (tr("settings.opt_fn_default"), "default"),
            (tr("settings.opt_fn_custom"), "custom"),
        ],
        default=fn_mode,
        callback=win.on_filename_mode_changed
    )
    add_setting_row(
        l_fmt,
        tr("settings.lbl_filename_mode"),
        tr("settings.desc_filename_mode"),
        win.filename_mode_selector
    )

    sample_meta = next(iter(win.files_data.values()))["meta"] if getattr(win, "files_data", None) else None
    win.filename_builder = FilenameTemplateBuilder(
        initial_tokens=win.app_settings.get("filename_tokens"),
        output_format=win.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT),
        sample_meta=sample_meta,
    )
    win.filename_builder.tokens_changed.connect(win.on_filename_tokens_changed)
    win.filename_builder.setVisible(fn_mode == "custom")
    l_fmt.addWidget(win.filename_builder)
    s_layout.addWidget(card_fmt)

    card_text, l_text = create_section_card(tr("settings.sec_text_layout"))

    win.footnotes_mode_selector = PillSelector(
        [
            (tr("settings.opt_fn_mode_default"), "default"),
            (tr("settings.opt_fn_mode_float"), "float"),
            (tr("settings.opt_fn_mode_renum"), "floatRenumbered"),
        ],
        default=str(win.app_settings.get("footnotes_mode", "float")),
        callback=win.on_footnotes_mode_changed
    )
    add_setting_row(
        l_text,
        tr("settings.lbl_footnotes_mode"),
        tr("settings.desc_footnotes_mode"),
        win.footnotes_mode_selector
    )

    win.soft_hyphen_selector = PillSelector(
        [(tr("settings.opt_off"), "false"), (tr("settings.opt_on"), "true")],
        default=str(win.app_settings.get("insert_soft_hyphen", "false")),
        callback=win.on_soft_hyphen_changed
    )
    add_setting_row(
        l_text,
        tr("settings.lbl_soft_hyphen"),
        tr("settings.desc_soft_hyphen"),
        win.soft_hyphen_selector
    )

    win.dropcaps_enable_selector = PillSelector(
        [(tr("settings.opt_on"), "true"), (tr("settings.opt_off"), "false")],
        default=str(win.app_settings.get("dropcaps_enable", "true")),
        callback=win.on_dropcaps_enable_changed
    )
    add_setting_row(
        l_text,
        tr("settings.lbl_dropcaps"),
        tr("settings.desc_dropcaps"),
        win.dropcaps_enable_selector
    )

    win.fn_translit_selector = PillSelector(
        [(tr("settings.opt_off"), "false"), (tr("settings.opt_on"), "true")],
        default=str(win.app_settings.get("file_name_transliterate", "false")),
        callback=win.on_fn_translit_changed
    )
    add_setting_row(
        l_text,
        tr("settings.lbl_fn_translit"),
        tr("settings.desc_fn_translit"),
        win.fn_translit_selector
    )

    win.meta_translit_selector = PillSelector(
        [(tr("settings.opt_off"), "false"), (tr("settings.opt_on"), "true")],
        default=str(win.app_settings.get("meta_transliterate", "false")),
        callback=win.on_meta_translit_changed
    )
    add_setting_row(
        l_text,
        tr("settings.lbl_meta_translit"),
        tr("settings.desc_meta_translit"),
        win.meta_translit_selector
    )

    title_mode = win.app_settings.get("title_template_mode", "default")
    win.title_mode_selector = PillSelector(
        [
            (tr("settings.opt_fn_default"), "default"),
            (tr("settings.opt_fn_custom"), "custom"),
        ],
        default=title_mode,
        callback=win.on_title_template_mode_changed
    )
    add_setting_row(
        l_text,
        tr("settings.lbl_title_mode"),
        tr("settings.desc_title_mode"),
        win.title_mode_selector
    )

    win.title_template_builder = FilenameTemplateBuilder(
        initial_tokens=win.app_settings.get("title_template_tokens"),
        output_format=win.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT),
        sample_meta=sample_meta,
        mode="title",
    )
    win.title_template_builder.tokens_changed.connect(win.on_title_template_tokens_changed)
    win.title_template_builder.setVisible(title_mode == "custom")
    l_text.addWidget(win.title_template_builder)

    win.tt_speech_selector = PillSelector(
        [(tr("settings.opt_off"), "false"), (tr("settings.opt_on"), "true")],
        default=str(win.app_settings.get("text_transform_speech", "false")),
        callback=lambda v: win.on_fbc_bool_setting_changed("text_transform_speech", v)
    )
    add_setting_row(
        l_text,
        tr("settings.lbl_tt_speech"),
        tr("settings.desc_tt_speech"),
        win.tt_speech_selector
    )

    win.tt_dashes_selector = PillSelector(
        [(tr("settings.opt_off"), "false"), (tr("settings.opt_on"), "true")],
        default=str(win.app_settings.get("text_transform_dashes", "false")),
        callback=lambda v: win.on_fbc_bool_setting_changed("text_transform_dashes", v)
    )
    add_setting_row(
        l_text,
        tr("settings.lbl_tt_dashes"),
        tr("settings.desc_tt_dashes"),
        win.tt_dashes_selector
    )

    win.tt_dialogue_selector = PillSelector(
        [(tr("settings.opt_off"), "false"), (tr("settings.opt_on"), "true")],
        default=str(win.app_settings.get("text_transform_dialogue", "false")),
        callback=lambda v: win.on_fbc_bool_setting_changed("text_transform_dialogue", v)
    )
    add_setting_row(
        l_text,
        tr("settings.lbl_tt_dialogue"),
        tr("settings.desc_tt_dialogue"),
        win.tt_dialogue_selector
    )

    win.annotation_enable_selector = PillSelector(
        [(tr("settings.opt_on"), "true"), (tr("settings.opt_off"), "false")],
        default=str(win.app_settings.get("annotation_enable", "true")),
        callback=lambda v: win.on_fbc_bool_setting_changed("annotation_enable", v)
    )
    add_setting_row(
        l_text,
        tr("settings.lbl_annotation_enable"),
        tr("settings.desc_annotation_enable"),
        win.annotation_enable_selector
    )

    win.toc_placement_selector = PillSelector(
        [
            (tr("settings.opt_toc_none"), "none"),
            (tr("settings.opt_toc_before"), "before"),
            (tr("settings.opt_toc_after"), "after"),
        ],
        default=str(win.app_settings.get("toc_page_placement", "after")),
        callback=win.on_toc_placement_changed
    )
    add_setting_row(
        l_text,
        tr("settings.lbl_toc_placement"),
        tr("settings.desc_toc_placement"),
        win.toc_placement_selector
    )

    win.open_from_cover_selector = PillSelector(
        [(tr("settings.opt_on"), "true"), (tr("settings.opt_off"), "false")],
        default=str(win.app_settings.get("open_from_cover", "true")),
        callback=lambda v: win.on_fbc_bool_setting_changed("open_from_cover", v)
    )
    add_setting_row(
        l_text,
        tr("settings.lbl_open_from_cover"),
        tr("settings.desc_open_from_cover"),
        win.open_from_cover_selector
    )
    s_layout.addWidget(card_text)

    card_adv, l_adv = create_section_card(tr("settings.sec_adv_convert"))
    win.azw3_comp_selector = PillSelector(
        [
            (tr("settings.opt_comp_none"), "none"),
            (tr("settings.opt_comp_standard"), "standard"),
            (tr("settings.opt_comp_huffdic"), "huffdic")
        ],
        default=win.app_settings.get("azw3_compression", "standard"),
        callback=win.on_azw3_compression_changed
    )
    add_setting_row(
        l_adv,
        tr("settings.lbl_azw3_comp"),
        tr("settings.desc_azw3_comp"),
        win.azw3_comp_selector
    )

    win.azw3_apnx_selector = PillSelector(
        [
            (tr("settings.opt_off"), "none"),
            (tr("settings.opt_apnx_eink"), "eink"),
            (tr("settings.opt_apnx_app"), "app")
        ],
        default=win.app_settings.get("azw3_apnx", "none"),
        callback=win.on_azw3_apnx_changed
    )
    add_setting_row(
        l_adv,
        tr("settings.lbl_azw3_apnx"),
        tr("settings.desc_azw3_apnx"),
        win.azw3_apnx_selector
    )

    win.kfx_comp_selector = PillSelector(
        [
            (tr("settings.opt_comp_none"), "none"),
            (tr("settings.opt_comp_lzma"), "lzma")
        ],
        default=win.app_settings.get("kfx_compression", "none"),
        callback=win.on_kfx_compression_changed
    )
    add_setting_row(
        l_adv,
        tr("settings.lbl_kfx_comp"),
        tr("settings.desc_kfx_comp"),
        win.kfx_comp_selector
    )

    win.md_images_selector = PillSelector(
        [
            (tr("settings.opt_md_placeholder"), "placeholder"),
            (tr("settings.opt_md_external"), "external"),
            (tr("settings.opt_md_embedded"), "embedded")
        ],
        default=win.app_settings.get("markdown_images", "placeholder"),
        callback=win.on_markdown_images_changed
    )
    add_setting_row(
        l_adv,
        tr("settings.lbl_md_images"),
        tr("settings.desc_md_images"),
        win.md_images_selector
    )

    win.workers_selector = PillSelector(
        [
            (tr("settings.opt_workers_auto"), "auto"),
            ("1", "1"),
            ("2", "2"),
            ("4", "4"),
        ],
        default=str(win.app_settings.get("convert_workers", "auto")),
        callback=win.on_convert_workers_changed
    )
    add_setting_row(
        l_adv,
        tr("settings.lbl_workers"),
        tr("settings.desc_workers"),
        win.workers_selector
    )
    s_layout.addWidget(card_adv)

    card_img, l_img = create_section_card(tr("settings.sec_images"))
    win.raster_fmt_selector = PillSelector(
        [(tr("settings.opt_auto"), "auto"), ("JPEG", "jpeg"), ("PNG", "png")],
        default=win.app_settings.get("raster_format", "auto"),
        callback=win.on_raster_format_changed
    )
    add_setting_row(
        l_img,
        tr("settings.lbl_raster"),
        tr("settings.desc_raster"),
        win.raster_fmt_selector
    )

    win.rasterize_svg_selector = PillSelector(
        [(tr("settings.opt_svg_off"), "false"), (tr("settings.opt_svg_on"), "true")],
        default=win.app_settings.get("rasterize_svg", "false"),
        callback=win.on_rasterize_svg_changed
    )
    add_setting_row(
        l_img,
        tr("settings.lbl_svg"),
        tr("settings.desc_svg"),
        win.rasterize_svg_selector
    )

    win.rem_trans_selector = PillSelector(
        [(tr("settings.opt_off"), "false"), (tr("settings.opt_on"), "true")],
        default=win.app_settings.get("remove_transparency", "false"),
        callback=win.on_remove_transparency_changed
    )
    add_setting_row(
        l_img,
        tr("settings.lbl_trans"),
        tr("settings.desc_trans"),
        win.rem_trans_selector
    )

    opt_widget = QWidget()
    opt_layout = QHBoxLayout(opt_widget)
    opt_layout.setContentsMargins(0, 0, 0, 0)
    opt_layout.setSpacing(10)

    win.optimize_img_selector = PillSelector(
        [(tr("settings.opt_on"), "true"), (tr("settings.opt_off"), "false")],
        default=win.app_settings.get("optimize_images", "true"),
        callback=win.on_optimize_images_changed
    )
    opt_layout.addWidget(win.optimize_img_selector)

    opt_layout.addWidget(QLabel(tr("settings.lbl_jpeg_qual")))
    win.jpeg_qual_cb = QComboBox()
    win.jpeg_qual_cb.addItems(["75", "80", "85", "90", "92", "95", "100"])
    win.jpeg_qual_cb.setCurrentText(str(win.app_settings.get("jpeg_quality_level", "95")))
    win.jpeg_qual_cb.currentTextChanged.connect(win.on_jpeg_quality_changed)
    opt_layout.addWidget(win.jpeg_qual_cb)

    add_setting_row(
        l_img,
        tr("settings.lbl_opt_img"),
        tr("settings.desc_opt_img"),
        opt_widget
    )

    win.baseline_jpeg_selector = PillSelector(
        [(tr("settings.opt_off"), "false"), (tr("settings.opt_on"), "true")],
        default=win.app_settings.get("baseline_jpeg", "false"),
        callback=win.on_baseline_jpeg_changed
    )
    add_setting_row(
        l_img,
        tr("settings.lbl_baseline_jpeg"),
        tr("settings.desc_baseline_jpeg"),
        win.baseline_jpeg_selector
    )
    win.cover_generate_selector = PillSelector(
        [(tr("settings.opt_off"), "false"), (tr("settings.opt_on"), "true")],
        default=str(win.app_settings.get("cover_generate", "false")),
        callback=lambda v: win.on_fbc_bool_setting_changed("cover_generate", v)
    )
    add_setting_row(
        l_img,
        tr("settings.lbl_cover_generate"),
        tr("settings.desc_cover_generate"),
        win.cover_generate_selector
    )

    win.no_cover_selector = PillSelector(
        [(tr("settings.opt_off"), "false"), (tr("settings.opt_on"), "true")],
        default=str(win.app_settings.get("no_cover", "false")),
        callback=lambda v: win.on_fbc_bool_setting_changed("no_cover", v)
    )
    add_setting_row(
        l_img,
        tr("settings.lbl_no_cover"),
        tr("settings.desc_no_cover"),
        win.no_cover_selector
    )
    s_layout.addWidget(card_img)

    card_save, l_save = create_section_card(tr("settings.sec_save"))
    save_options = [
        (tr("settings.opt_save_source"), "source"),
        (tr("settings.opt_save_custom"), "custom")
    ]
    win.save_mode_selector = PillSelector(
        save_options,
        default=win.app_settings.get("save_mode", "source"),
        callback=win.on_save_mode_changed
    )
    add_setting_row(
        l_save,
        tr("settings.lbl_save_mode"),
        tr("settings.desc_save_mode"),
        win.save_mode_selector
    )

    dir_widget = QWidget()
    dir_layout = QHBoxLayout(dir_widget)
    dir_layout.setContentsMargins(0, 0, 0, 0)
    dir_layout.setSpacing(8)

    win.lbl_custom_dir = QLabel(win.app_settings.get("custom_output_dir", os.path.expanduser("~")))
    win.lbl_custom_dir.setObjectName("RowDesc")
    dir_layout.addWidget(win.lbl_custom_dir)

    win.btn_choose_dir = QPushButton(tr("settings.btn_choose_dir"))
    win.btn_choose_dir.clicked.connect(win.choose_custom_output_dir)
    win.btn_choose_dir.setEnabled(win.app_settings.get("save_mode") == "custom")
    dir_layout.addWidget(win.btn_choose_dir)

    add_setting_row(
        l_save,
        tr("settings.lbl_custom_dir"),
        tr("settings.desc_custom_dir"),
        dir_widget
    )
    s_layout.addWidget(card_save)

    card_theme, l_theme = create_section_card(tr("settings.sec_appearance"))
    win.theme_selector = PillSelector(
        get_theme_choices(),
        default=win.app_settings.get("theme", "Modern"),
        callback=win.apply_theme
    )
    add_setting_row(
        l_theme,
        tr("settings.lbl_theme"),
        tr("settings.desc_theme"),
        win.theme_selector
    )

    win.lang_selector = PillSelector(
        LOCALE.discover_locales(),
        default=win.app_settings.get("language", LOCALE.lang_code),
        callback=win.apply_language
    )
    add_setting_row(
        l_theme,
        tr("settings.lbl_language"),
        tr("settings.desc_language"),
        win.lang_selector
    )
    s_layout.addWidget(card_theme)

    card_email, l_email = create_section_card(tr("settings.sec_email"))

    win.email_auto_selector = PillSelector(
        [(tr("settings.opt_off"), "false"), (tr("settings.opt_on"), "true")],
        default=str(win.app_settings.get("email_auto_send", "false")),
        callback=win.on_email_auto_changed
    )
    add_setting_row(
        l_email,
        tr("settings.lbl_email_auto"),
        tr("settings.desc_email_auto"),
        win.email_auto_selector
    )

    smtp_srv_widget = QWidget()
    smtp_srv_layout = QHBoxLayout(smtp_srv_widget)
    smtp_srv_layout.setContentsMargins(0, 0, 0, 0)
    smtp_srv_layout.setSpacing(8)

    win.smtp_host_edit = QLineEdit(win.app_settings.get("smtp_host", ""))
    win.smtp_host_edit.setPlaceholderText("smtp.example.com")
    win.smtp_host_edit.setFixedWidth(200)
    win.smtp_host_edit.textChanged.connect(lambda v: win.on_email_field_changed("smtp_host", v))
    smtp_srv_layout.addWidget(win.smtp_host_edit)

    smtp_srv_layout.addWidget(QLabel(tr("settings.lbl_port")))
    win.smtp_port_edit = QLineEdit(str(win.app_settings.get("smtp_port", "465")))
    win.smtp_port_edit.setPlaceholderText("465")
    win.smtp_port_edit.setFixedWidth(68)
    win.smtp_port_edit.textChanged.connect(lambda v: win.on_email_field_changed("smtp_port", v))
    smtp_srv_layout.addWidget(win.smtp_port_edit)

    win.smtp_sec_selector = PillSelector(
        [("SSL", "ssl"), ("STARTTLS", "starttls"), (tr("settings.opt_none"), "none")],
        default=win.app_settings.get("smtp_security", "ssl"),
        callback=lambda v: win.on_email_field_changed("smtp_security", v)
    )
    smtp_srv_layout.addWidget(win.smtp_sec_selector)

    add_setting_row(
        l_email,
        tr("settings.lbl_smtp"),
        tr("settings.desc_smtp"),
        smtp_srv_widget
    )

    smtp_auth_widget = QWidget()
    smtp_auth_layout = QHBoxLayout(smtp_auth_widget)
    smtp_auth_layout.setContentsMargins(0, 0, 0, 0)
    smtp_auth_layout.setSpacing(8)

    win.smtp_user_edit = QLineEdit(win.app_settings.get("smtp_user", ""))
    win.smtp_user_edit.setPlaceholderText("user@example.com")
    win.smtp_user_edit.setFixedWidth(185)
    win.smtp_user_edit.textChanged.connect(lambda v: win.on_email_field_changed("smtp_user", v))
    smtp_auth_layout.addWidget(win.smtp_user_edit)

    win.smtp_pass_edit = QLineEdit(win.app_settings.get("smtp_password", ""))
    win.smtp_pass_edit.setPlaceholderText(tr("settings.ph_password"))
    win.smtp_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
    win.smtp_pass_edit.setFixedWidth(185)
    win.smtp_pass_edit.textChanged.connect(lambda v: win.on_email_field_changed("smtp_password", v))
    smtp_auth_layout.addWidget(win.smtp_pass_edit)

    add_setting_row(
        l_email,
        tr("settings.lbl_creds"),
        tr("settings.desc_creds"),
        smtp_auth_widget
    )

    if not is_secure_password_storage_available():
        lbl_kr_warn = QLabel(tr("settings.email_keyring_warning"))
        lbl_kr_warn.setObjectName("RowDesc")
        lbl_kr_warn.setWordWrap(True)
        lbl_kr_warn.setStyleSheet("color: #f59e0b;")
        l_email.addWidget(lbl_kr_warn)

    email_addr_widget = QWidget()
    email_addr_layout = QHBoxLayout(email_addr_widget)
    email_addr_layout.setContentsMargins(0, 0, 0, 0)
    email_addr_layout.setSpacing(8)

    win.email_from_edit = QLineEdit(win.app_settings.get("email_from", ""))
    win.email_from_edit.setPlaceholderText(tr("settings.ph_sender"))
    win.email_from_edit.setFixedWidth(185)
    win.email_from_edit.textChanged.connect(lambda v: win.on_email_field_changed("email_from", v))
    email_addr_layout.addWidget(win.email_from_edit)

    email_addr_layout.addWidget(QLabel(tr("settings.lbl_to")))
    win.email_to_edit = QLineEdit(win.app_settings.get("email_to", ""))
    win.email_to_edit.setPlaceholderText("reader@kindle.com")
    win.email_to_edit.setFixedWidth(185)
    win.email_to_edit.textChanged.connect(lambda v: win.on_email_field_changed("email_to", v))
    email_addr_layout.addWidget(win.email_to_edit)

    add_setting_row(
        l_email,
        tr("settings.lbl_addrs"),
        tr("settings.desc_addrs"),
        email_addr_widget
    )

    win.btn_test_email = QPushButton(tr("settings.btn_test_email"))
    win.btn_test_email.setObjectName("SecondaryButton")
    win.btn_test_email.setProperty("variant", "secondary")
    win.btn_test_email.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_test_email.clicked.connect(win.send_test_email_clicked)
    add_setting_row(
        l_email,
        tr("settings.lbl_email_test"),
        tr("settings.desc_email_test"),
        win.btn_test_email
    )

    s_layout.addWidget(card_email)
    s_layout.addStretch()
    scroll.setWidget(scroll_content)
    layout.addWidget(scroll, 1)

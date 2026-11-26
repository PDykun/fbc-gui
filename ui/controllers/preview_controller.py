import os

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFontDatabase
from PyQt6.QtWidgets import QFileDialog

from core.config import atomic_write_text
from core.css_preview import (
    VALID_FONT_EXTENSIONS,
    build_full_preview_html as render_preview_html,
    generate_css_content as build_css_content,
    get_default_css_ui_state,
    install_user_fonts,
    parse_css_file_to_state,
    parse_ttf_names,
)
from core.fb2_processor import extract_book_preview_data, get_book_xml
from core.i18n import (
    LEGACY_ALIGN_MAP,
    LEGACY_NOTE_BG_MAP,
    LEGACY_NOTE_BORDER_MAP,
    LEGACY_STYLE_MAP,
    tr,
)
from core.logger import get_logger
from ui.dialogs import show_themed_message

logger = get_logger("app")


class PreviewController:
    """Контроллер шрифтов, визуального редактора CSS и предпросмотра книги."""

    def register_all_fonts(self):
        if not os.path.exists(self.fonts_dir):
            return
        for f in os.listdir(self.fonts_dir):
            if f.lower().endswith(('.ttf', '.otf', '.woff', '.woff2')):
                full_path = os.path.join(self.fonts_dir, f)
                font_id = QFontDatabase.addApplicationFont(full_path)
                qt_families = QFontDatabase.applicationFontFamilies(font_id) if font_id != -1 else []
                names = parse_ttf_names(full_path)
                best = (qt_families[0] if qt_families else None) or names.get(1) or names.get(4) or names.get(6) or os.path.splitext(f)[0]
                self.font_map[f] = {
                    'family': qt_families[0] if qt_families else names.get(1),
                    'full': names.get(4),
                    'ps': names.get(6),
                    'best_name': best
                }

    def resolve_font_family(self, font_filename):
        if not font_filename or font_filename in ("__none__", "Нет", "None"):
            return "Georgia"
        info = self.font_map.get(font_filename)
        return (info.get('family') or info.get('best_name') or "Georgia") if info else "Georgia"

    def get_available_fonts(self):
        fonts = []
        if os.path.exists(self.fonts_dir):
            for f in sorted(os.listdir(self.fonts_dir)):
                if f.lower().endswith(VALID_FONT_EXTENSIONS):
                    fonts.append(f)
        return fonts or ["PT-Astra-Serif_Regular.ttf", "PomorskyUnicode.otf"]

    def _refresh_font_combos(self):
        available = self.get_available_fonts()
        font_options = [(tr("styles.font_none"), "__none__")] + [(f, f) for f in available]
        self._loading_css = True
        try:
            for cb_name in ("font_para_cb", "font_drop_cb", "font_title_cb", "font_author_cb"):
                cb = getattr(self, cb_name, None)
                if cb is None:
                    continue
                cur_val = self._get_combo_data(cb, "__none__")
                self._populate_data_combo(cb, font_options, cur_val)
        finally:
            self._loading_css = False
        if hasattr(self, "lbl_fonts_drop_hint"):
            self.lbl_fonts_drop_hint.setText(tr("styles.drop_fonts_hint", count=len(available)))

    def _install_font_files(self, filepaths):
        installed, errors = install_user_fonts(filepaths, self.fonts_dir)
        if installed:
            self.register_all_fonts()
            self._refresh_font_combos()
            self.refresh_preview()
            logger.info("Установлены пользовательские шрифты: %s", ", ".join(installed))
        if errors:
            err_txt = "\n".join(f"{name}: {msg}" for name, msg in errors)
            show_themed_message(self, tr("common.warning"), tr("styles.err_fonts_install", e=err_txt), "warning")
        elif installed:
            show_themed_message(
                self,
                tr("common.success"),
                tr("styles.msg_fonts_installed", count=len(installed), names=", ".join(installed)),
                "info",
            )

    def add_user_fonts_clicked(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("styles.dlg_select_fonts"), "", tr("styles.filter_fonts")
        )
        if files:
            self._install_font_files(files)

    def open_fonts_folder_clicked(self):
        os.makedirs(self.fonts_dir, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(self.fonts_dir)))

    def on_style_param_changed(self, *args):
        if getattr(self, '_loading_css', False):
            return
        self.save_visual_css(show_alert=False)
        self.refresh_preview()

    def on_preview_mode_changed(self, mode):
        self.preview_source_mode = "sample" if mode == "sample" else "book"
        self.refresh_preview()

    def on_preview_simulate_eink_toggled(self, checked):
        self.app_settings["preview_simulate_eink"] = "true" if checked else "false"
        self.save_app_settings()
        self.refresh_preview()

    def _get_selected_book_data(self):
        if not hasattr(self, "table") or not self.files_data:
            return None
        rows = self.table.selectionModel().selectedRows()
        if rows:
            it0 = self.table.item(rows[0].row(), 0)
            if it0:
                data = self.files_data.get(it0.data(Qt.ItemDataRole.UserRole))
                if data:
                    return data
        return next(iter(self.files_data.values()), None)

    def _build_full_preview_html(self, for_browser=False):
        st = self._get_css_ui_state()
        font_families = {
            "para": self.resolve_font_family(st["font_para"]),
            "title": self.resolve_font_family(st["font_title"]),
            "author": self.resolve_font_family(st["font_author"]),
            "drop": self.resolve_font_family(st["font_drop"]),
        }
        svg_mode = tr("preview.svg_raster") if self.app_settings.get("rasterize_svg") == "true" else tr("preview.svg_vector")
        mode = getattr(self, "preview_source_mode", "book")
        book_preview = None
        selected_data = self._get_selected_book_data() if mode == "book" else None
        if selected_data:
            book_preview = extract_book_preview_data(
                get_book_xml(selected_data),
                meta=selected_data.get("meta"),
                cover_bytes=selected_data.get("cover_bytes"),
                cover_mime=selected_data.get("cover_mime"),
            )

        if hasattr(self, "lbl_preview_source"):
            if mode == "book" and book_preview:
                disp_title = book_preview.get("title") or selected_data.get("display_name") or ""
                self.lbl_preview_source.setText(tr("preview.showing_book", title=disp_title))
            elif mode == "book":
                self.lbl_preview_source.setText(tr("preview.no_book_selected"))
            else:
                self.lbl_preview_source.setText(tr("preview.info_bar"))

        return render_preview_html(
            st, font_families, svg_mode, self.fonts_dir,
            self.app_name, self.app_version,
            self.p_align_cb.currentText(), self.img_align_cb.currentText(),
            for_browser=for_browser,
            grayscale=(self.app_settings.get("grayscale", "none") == "luma"),
            book_preview=book_preview,
            dropcaps_enable=(str(self.app_settings.get("dropcaps_enable", "true")).lower() == "true"),
            use_web_engine=bool(getattr(self, "preview_is_webengine", False)),
            image_color_profile=self.app_settings.get("image_color_profile", "none"),
            simulate_eink=(str(self.app_settings.get("preview_simulate_eink", "true")).lower() == "true"),
            image_color_profile_custom=self.app_settings.get("image_color_profile_custom"),
        )

    def refresh_preview(self):
        if not hasattr(self, 'preview_browser'):
            return
        try:
            html = self._build_full_preview_html(for_browser=False)
            if hasattr(self.preview_browser, "set_preview_html"):
                self.preview_browser.set_preview_html(html, self.base_dir)
            else:
                self.preview_browser.setHtml(html)
        except Exception as e:
            logger.warning("Ошибка превью: %s", e)

    def open_in_browser(self):
        self.save_visual_css(show_alert=False)
        preview_html_path = os.path.join(os.path.dirname(self.css_path), "preview.html")
        try:
            html = self._build_full_preview_html(for_browser=True)
            atomic_write_text(preview_html_path, html)
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(preview_html_path)))
        except Exception as e:
            show_themed_message(self, tr("common.error"), tr("preview.err_browser", e=e), "error")

    def _get_css_ui_state(self):
        return {
            "font_para": self._get_combo_data(self.font_para_cb, "__none__"),
            "font_drop": self._get_combo_data(self.font_drop_cb, "__none__"),
            "font_title": self._get_combo_data(self.font_title_cb, "__none__"),
            "font_author": self._get_combo_data(self.font_author_cb, "__none__"),
            "pdf_frame": self._get_combo_data(self.pdf_frame_cb, "0"),
            "h1_sz": self.h1_sz_cb.currentText(),
            "h1_cl": self.h1_cl_cb.get(),
            "h1_al": self._get_combo_data(self.h1_al_cb, "center"),
            "auth_sz": self.auth_sz_cb.currentText(),
            "auth_cl": self.auth_cl_cb.get(),
            "auth_al": self._get_combo_data(self.auth_al_cb, "center"),
            "auth_style": self._get_combo_data(self.auth_style_cb, "italic"),
            "h2_sz": self.header_vars["h2"]["size"].currentText(),
            "h2_cl": self.header_vars["h2"]["color"].get(),
            "h2_al": self._get_combo_data(self.header_vars["h2"]["align"], "center"),
            "h3_sz": self.header_vars["h3"]["size"].currentText(),
            "h3_cl": self.header_vars["h3"]["color"].get(),
            "h3_al": self._get_combo_data(self.header_vars["h3"]["align"], "center"),
            "h4_sz": self.header_vars["h4"]["size"].currentText(),
            "h4_cl": self.header_vars["h4"]["color"].get(),
            "h4_al": self._get_combo_data(self.header_vars["h4"]["align"], "center"),
            "h5_sz": self.header_vars["h5"]["size"].currentText(),
            "h5_cl": self.header_vars["h5"]["color"].get(),
            "h5_al": self._get_combo_data(self.header_vars["h5"]["align"], "center"),
            "p_align": self._get_combo_data(self.p_align_cb, "justify"),
            "text_indent": self.text_indent_cb.currentText(),
            "sub_align": self._get_combo_data(self.sub_align_cb, "center"),
            "drop_color": self.drop_color_cb.get(),
            "drop_size": self.drop_size_cb.currentText(),
            "anno_size": self.anno_size_cb.currentText(),
            "anno_color": self.anno_color_cb.get(),
            "anno_align": self._get_combo_data(self.anno_align_cb, "center"),
            "anno_style": self._get_combo_data(self.anno_style_cb, "normal"),
            "epi_size": self.epi_size_cb.currentText(),
            "epi_color": self.epi_color_cb.get(),
            "epi_align": self._get_combo_data(self.epi_align_cb, "right"),
            "epi_style": self._get_combo_data(self.epi_style_cb, "italic"),
            "poem_size": self.poem_size_cb.currentText(),
            "poem_color": self.poem_color_cb.get(),
            "poem_align": self._get_combo_data(self.poem_align_cb, "left"),
            "poem_style": self._get_combo_data(self.poem_style_cb, "italic"),
            "note_size": self.note_size_cb.currentText(),
            "note_color": self.note_color_cb.get(),
            "note_bg": self._get_combo_data(self.note_bg_cb, "#e6e6fa"),
            "note_border": self._get_combo_data(self.note_border_cb, "1px #505050 solid"),
            "note_style": self._get_combo_data(self.note_style_cb, "italic"),
            "img_align": self._get_combo_data(self.img_align_cb, "center"),
            "img_width": self.img_width_cb.currentText(),
            "img_cap_sz": self.img_cap_sz_cb.currentText(),
            "img_cap_cl": self.img_cap_cl_cb.get(),
            "img_cap_st": self._get_combo_data(self.img_cap_st_cb, "italic"),
        }

    def _apply_css_ui_state(self, st):
        if not isinstance(st, dict):
            return
        none_font_map = {"Нет": "__none__", "None": "__none__"}
        cb_map = [
            ("font_para", self.font_para_cb, none_font_map), ("font_drop", self.font_drop_cb, none_font_map),
            ("font_title", self.font_title_cb, none_font_map), ("font_author", self.font_author_cb, none_font_map),
            ("pdf_frame", self.pdf_frame_cb, {"0 (Выкл)": "0", "0 (Off)": "0"}),
            ("h1_sz", self.h1_sz_cb, None), ("h1_al", self.h1_al_cb, LEGACY_ALIGN_MAP),
            ("auth_sz", self.auth_sz_cb, None), ("auth_al", self.auth_al_cb, LEGACY_ALIGN_MAP), ("auth_style", self.auth_style_cb, LEGACY_STYLE_MAP),
            ("h2_sz", self.header_vars["h2"]["size"], None), ("h2_al", self.header_vars["h2"]["align"], LEGACY_ALIGN_MAP),
            ("h3_sz", self.header_vars["h3"]["size"], None), ("h3_al", self.header_vars["h3"]["align"], LEGACY_ALIGN_MAP),
            ("h4_sz", self.header_vars["h4"]["size"], None), ("h4_al", self.header_vars["h4"]["align"], LEGACY_ALIGN_MAP),
            ("h5_sz", self.header_vars["h5"]["size"], None), ("h5_al", self.header_vars["h5"]["align"], LEGACY_ALIGN_MAP),
            ("p_align", self.p_align_cb, LEGACY_ALIGN_MAP), ("text_indent", self.text_indent_cb, None), ("sub_align", self.sub_align_cb, LEGACY_ALIGN_MAP),
            ("drop_size", self.drop_size_cb, None),
            ("anno_size", self.anno_size_cb, None), ("anno_align", self.anno_align_cb, LEGACY_ALIGN_MAP), ("anno_style", self.anno_style_cb, LEGACY_STYLE_MAP),
            ("epi_size", self.epi_size_cb, None), ("epi_align", self.epi_align_cb, LEGACY_ALIGN_MAP), ("epi_style", self.epi_style_cb, LEGACY_STYLE_MAP),
            ("poem_size", self.poem_size_cb, None), ("poem_align", self.poem_align_cb, LEGACY_ALIGN_MAP), ("poem_style", self.poem_style_cb, LEGACY_STYLE_MAP),
            ("note_size", self.note_size_cb, None), ("note_bg", self.note_bg_cb, LEGACY_NOTE_BG_MAP),
            ("note_border", self.note_border_cb, LEGACY_NOTE_BORDER_MAP), ("note_style", self.note_style_cb, LEGACY_STYLE_MAP),
            ("img_align", self.img_align_cb, LEGACY_ALIGN_MAP), ("img_width", self.img_width_cb, None),
            ("img_cap_sz", self.img_cap_sz_cb, None), ("img_cap_st", self.img_cap_st_cb, LEGACY_STYLE_MAP),
        ]
        for key, cb, lmap in cb_map:
            if key in st and st[key]:
                self._set_combo_by_data(cb, st[key], lmap)

        cl_map = [
            ("h1_cl", self.h1_cl_cb), ("auth_cl", self.auth_cl_cb),
            ("h2_cl", self.header_vars["h2"]["color"]), ("h3_cl", self.header_vars["h3"]["color"]),
            ("h4_cl", self.header_vars["h4"]["color"]), ("h5_cl", self.header_vars["h5"]["color"]),
            ("drop_color", self.drop_color_cb), ("anno_color", self.anno_color_cb),
            ("epi_color", self.epi_color_cb), ("poem_color", self.poem_color_cb), ("note_color", self.note_color_cb),
            ("img_cap_cl", self.img_cap_cl_cb),
        ]
        for key, picker in cl_map:
            if key in st and st[key]:
                picker.set(str(st[key]))

    def load_and_parse_css_to_gui(self):
        self._loading_css = True
        try:
            if isinstance(self.app_settings.get("css_ui_state"), dict):
                self._apply_css_ui_state(self.app_settings["css_ui_state"])
            parsed = parse_css_file_to_state(self.css_path)
            if parsed:
                self._apply_css_ui_state(parsed)
                if hasattr(self, '_get_css_ui_state'):
                    self.app_settings["css_ui_state"] = self._get_css_ui_state()
            if hasattr(self, 'css_preview_text'):
                self.css_preview_text.setPlainText(self.generate_css_content())
        except Exception as e:
            logger.warning("Ошибка при разборе CSS: %s", e)
        finally:
            self._loading_css = False

    def generate_css_content(self):
        return build_css_content(self._get_css_ui_state(), self.fonts_dir)

    def reset_visual_css(self, show_alert=False):
        """Сбрасывает ebook_styles.css к первоначальному виду, перезаписывает на диске и подгружает в интерфейс."""
        try:
            if (
                self.bundled_css_path
                and os.path.abspath(self.bundled_css_path) != os.path.abspath(self.css_path)
                and os.path.isfile(self.bundled_css_path)
            ):
                with open(self.bundled_css_path, 'r', encoding='utf-8') as src:
                    default_css = src.read()
            else:
                default_css = build_css_content(get_default_css_ui_state(), self.fonts_dir)

            atomic_write_text(self.css_path, default_css)

            self.app_settings["css_ui_state"] = get_default_css_ui_state()
            self.load_and_parse_css_to_gui()
            self.save_app_settings()
            self.update_fbc_config_file()
            self.refresh_preview()
            logger.info("Стили CSS сброшены к первоначальному виду: %s", self.css_path)
            if show_alert:
                show_themed_message(self, tr("common.success"), tr("styles.msg_reset", path=self.css_path), "info")
            return True
        except Exception as e:
            logger.error("Ошибка сброса CSS: %s", e)
            show_themed_message(self, tr("common.error"), tr("styles.err_reset", e=e), "error")
            return False

    def save_visual_css(self, show_alert=False):
        try:
            css_content = self.generate_css_content()
            atomic_write_text(self.css_path, css_content)
            if hasattr(self, '_get_css_ui_state'):
                self.app_settings["css_ui_state"] = self._get_css_ui_state()
                self.save_app_settings()
            if hasattr(self, 'css_preview_text'):
                self.css_preview_text.setPlainText(css_content)
            if show_alert:
                show_themed_message(self, tr("common.success"), tr("styles.msg_saved", path=self.css_path), "info")
            return True
        except Exception as e:
            show_themed_message(self, tr("common.error"), tr("styles.err_save", e=e), "error")
            return False

    def _get_title_style_params(self):
        return {
            "h1_sz": self.h1_sz_cb.currentText(),
            "h1_cl": self.h1_cl_cb.get(),
            "h1_al": self._get_combo_data(self.h1_al_cb, "center"),
            "auth_sz": self.auth_sz_cb.currentText(),
            "auth_cl": self.auth_cl_cb.get(),
            "auth_al": self._get_combo_data(self.auth_al_cb, "center"),
            "auth_style": self._get_combo_data(self.auth_style_cb, "italic"),
        }

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QFrame, QCheckBox, QSizePolicy,
    QDialog, QLineEdit, QFileDialog, QPlainTextEdit,
    QComboBox, QTreeWidget, QTreeWidgetItem, QScrollArea,
)

from core.cover_studio import CoverSpec
from core.i18n import tr
from core.fb2_genres import (
    FB2_GENRE_GROUPS, KNOWN_GENRE_CODES, COMMON_LANG_CODES,
    normalize_genre_code, normalize_genre_list,
    get_genre_label, get_genre_group_label,
)
from core.fb2_processor import (
    COVER_PREVIEW_SIZE, fit_image_to_cover_size, simulate_fbc_target
)


from ui.dialogs.common import show_themed_message, create_segmented_tabs
from ui.dialogs.cover_studio import CoverStudioDialog
from ui.dialogs.metadata_lookup import MetadataLookupDialog


class BookEditDialog(QDialog):
    """Тематическое окно редактирования всех метаданных и обложки выбранной книги."""

    def __init__(self, parent, data, output_format, filename_mode="default", filename_tokens=None, app_settings=None):
        super().__init__(parent)
        self.setWindowTitle(tr("converter.edit_dlg_title"))
        self.setObjectName("MainContainer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setModal(True)
        self.setMinimumWidth(780)
        if parent is not None:
            self.setPalette(parent.palette())
            if parent.styleSheet():
                self.setStyleSheet(parent.styleSheet())

        self._output_format = output_format
        self._filename_mode = filename_mode
        self._filename_tokens = filename_tokens
        self._app_settings = dict(app_settings or {})
        self._orig_cover_bytes = data.get("orig_cover_bytes")
        self._orig_cover_mime = data.get("orig_cover_mime")
        self._cover_bytes = data.get("cover_bytes")
        self._cover_mime = data.get("cover_mime")
        self._cover_modified = bool(data.get("cover_modified", False))
        meta = data.get("meta", {})
        self._orig_annotation = (meta.get("annotation") or "").strip()
        self._orig_annotation_rich = bool(meta.get("annotation_has_rich_xml", False))
        self._extra_translators_count = int(meta.get("extra_translators_count", 0) or 0)
        self._selected_genres = normalize_genre_list(meta.get("genres"))
        self._syncing_genre_tree = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 18)
        root.setSpacing(16)

        card = QFrame()
        card.setObjectName("SectionCard")
        c_layout = QHBoxLayout(card)
        c_layout.setContentsMargins(20, 18, 20, 18)
        c_layout.setSpacing(24)

        left_box = QVBoxLayout()
        left_box.setSpacing(10)

        hdr_lbl = QLabel(tr("converter.edit_dlg_title").upper())
        hdr_lbl.setObjectName("SectionHeader")
        left_box.addWidget(hdr_lbl)

        self.tabs = create_segmented_tabs(self)
        self.tabs.addTab(self._build_basic_tab(data, meta), tr("converter.edit_tab_basic"))
        self.tabs.addTab(self._build_extra_tab(meta), tr("converter.edit_tab_extra"))

        self._rebuild_genre_chips()
        left_box.addWidget(self.tabs, 1)
        c_layout.addLayout(left_box, 1)
        c_layout.addLayout(self._build_cover_panel())
        root.addWidget(card)

        self._render_cover()

        btn_row = QHBoxLayout()
        self.chk_save_source = QCheckBox(tr("converter.edit_dlg_save_source"))
        self.chk_save_source.setChecked(False)
        self.chk_save_source.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(self.chk_save_source)
        btn_row.addStretch()
        btn_cancel = QPushButton(tr("converter.btn_cancel"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_apply = QPushButton(tr("converter.btn_apply"))
        btn_apply.setObjectName("AccentButton")
        btn_apply.setProperty("variant", "primary")
        btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_apply.setDefault(True)
        btn_apply.clicked.connect(self.accept)
        btn_row.addWidget(btn_apply)
        root.addLayout(btn_row)

    def _build_basic_tab(self, data, meta):
        tab_basic = QWidget()
        basic_layout = QVBoxLayout(tab_basic)
        basic_layout.setContentsMargins(4, 10, 4, 4)
        basic_layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        src_text = data.get("display_name") or os.path.basename(data.get("path", ""))
        self.lbl_src_val = QLabel(src_text)
        self.lbl_src_val.setObjectName("RowDesc")
        self.lbl_src_val.setWordWrap(True)
        self.lbl_src_val.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lbl_src_val.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.lbl_src_val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_src_val.setToolTip(src_text)
        form.addRow(QLabel(tr("converter.edit_dlg_file")), self.lbl_src_val)

        self.ed_last = QLineEdit(meta.get("last", ""))
        self.ed_first = QLineEdit(meta.get("first", ""))
        self.ed_mid = QLineEdit(meta.get("mid", ""))
        self.ed_series = QLineEdit(meta.get("series", ""))
        self.ed_num = QLineEdit(meta.get("num", ""))
        self.ed_title = QLineEdit(meta.get("title", ""))

        for ed in (self.ed_last, self.ed_first, self.ed_mid, self.ed_series, self.ed_num, self.ed_title):
            ed.setMinimumWidth(250)

        form.addRow(QLabel(tr("converter.edit_dlg_last")), self.ed_last)
        form.addRow(QLabel(tr("converter.edit_dlg_first")), self.ed_first)
        form.addRow(QLabel(tr("converter.edit_dlg_mid")), self.ed_mid)
        form.addRow(QLabel(tr("converter.edit_dlg_series")), self.ed_series)
        form.addRow(QLabel(tr("converter.edit_dlg_num")), self.ed_num)
        form.addRow(QLabel(tr("converter.edit_dlg_title_field")), self.ed_title)

        self.lbl_target_val = QLabel()
        self.lbl_target_val.setObjectName("RowDesc")
        self.lbl_target_val.setWordWrap(True)
        self.lbl_target_val.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lbl_target_val.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.lbl_target_val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(QLabel(tr("converter.edit_dlg_target")), self.lbl_target_val)

        for ed in (self.ed_last, self.ed_first, self.ed_mid, self.ed_series, self.ed_num, self.ed_title):
            ed.textChanged.connect(self._update_target_preview)
        self._update_target_preview()

        basic_layout.addLayout(form)
        basic_layout.addStretch()
        return tab_basic

    def _build_extra_tab(self, meta):
        tab_extra = QWidget()
        extra_layout = QVBoxLayout(tab_extra)
        extra_layout.setContentsMargins(4, 10, 4, 4)
        extra_layout.setSpacing(10)

        extra_form = QFormLayout()
        extra_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        extra_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        extra_form.setHorizontalSpacing(14)
        extra_form.setVerticalSpacing(8)

        # Жанры
        genre_box = QVBoxLayout()
        genre_box.setContentsMargins(0, 0, 0, 0)
        genre_box.setSpacing(6)

        self._chips_scroll = QScrollArea()
        self._chips_scroll.setWidgetResizable(True)
        self._chips_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chips_scroll.setFixedHeight(36)
        self._chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._chips_container = QWidget()
        self._chips_layout = QHBoxLayout(self._chips_container)
        self._chips_layout.setContentsMargins(0, 2, 0, 2)
        self._chips_layout.setSpacing(6)
        self._chips_scroll.setWidget(self._chips_container)
        genre_box.addWidget(self._chips_scroll)

        genre_search_row = QHBoxLayout()
        genre_search_row.setSpacing(6)
        self.ed_genre_search = QLineEdit()
        self.ed_genre_search.setPlaceholderText(tr("converter.edit_dlg_genres_search"))
        self.ed_genre_search.textChanged.connect(self._filter_genre_tree)
        self.ed_genre_search.returnPressed.connect(self._add_custom_genre_from_search)
        btn_add_genre = QPushButton(tr("converter.edit_dlg_genre_add"))
        btn_add_genre.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_genre.clicked.connect(self._add_custom_genre_from_search)
        genre_search_row.addWidget(self.ed_genre_search, 1)
        genre_search_row.addWidget(btn_add_genre)
        genre_box.addLayout(genre_search_row)

        self.genre_tree = QTreeWidget()
        self.genre_tree.setHeaderHidden(True)
        self.genre_tree.setFixedHeight(130)
        self.genre_tree.setRootIsDecorated(True)
        self._genre_tree_items = {}
        self._populate_genre_tree()
        self.genre_tree.itemChanged.connect(self._on_genre_tree_item_changed)
        genre_box.addWidget(self.genre_tree)
        extra_form.addRow(QLabel(tr("converter.edit_dlg_genres")), genre_box)

        # Язык
        self.cb_lang = QComboBox()
        self.cb_lang.setEditable(True)
        self.cb_lang.addItem("")
        for lc in COMMON_LANG_CODES:
            self.cb_lang.addItem(lc)
        self.cb_lang.setCurrentText((meta.get("lang") or "").strip().lower())
        self.cb_lang.setMaximumWidth(140)
        extra_form.addRow(QLabel(tr("converter.edit_dlg_lang")), self.cb_lang)

        # Переводчик
        tr_box = QVBoxLayout()
        tr_box.setContentsMargins(0, 0, 0, 0)
        tr_box.setSpacing(4)
        tr_row = QHBoxLayout()
        tr_row.setSpacing(6)
        self.ed_tr_last = QLineEdit(meta.get("translator_last", ""))
        self.ed_tr_last.setPlaceholderText(tr("converter.edit_dlg_translator_last"))
        self.ed_tr_first = QLineEdit(meta.get("translator_first", ""))
        self.ed_tr_first.setPlaceholderText(tr("converter.edit_dlg_translator_first"))
        self.ed_tr_mid = QLineEdit(meta.get("translator_middle", ""))
        self.ed_tr_mid.setPlaceholderText(tr("converter.edit_dlg_translator_mid"))
        tr_row.addWidget(self.ed_tr_last, 1)
        tr_row.addWidget(self.ed_tr_first, 1)
        tr_row.addWidget(self.ed_tr_mid, 1)
        tr_box.addLayout(tr_row)
        if self._extra_translators_count > 0:
            lbl_extra_tr = QLabel(tr("converter.edit_dlg_extra_translators", count=self._extra_translators_count))
            lbl_extra_tr.setObjectName("RowDesc")
            tr_box.addWidget(lbl_extra_tr)
        extra_form.addRow(QLabel(tr("converter.edit_dlg_translator")), tr_box)

        # Издатель и ISBN
        self.ed_publisher = QLineEdit(meta.get("publisher", ""))
        extra_form.addRow(QLabel(tr("converter.edit_dlg_publisher")), self.ed_publisher)
        self.ed_isbn = QLineEdit(meta.get("isbn", ""))
        self.ed_isbn.setPlaceholderText(tr("converter.edit_dlg_isbn_placeholder"))
        extra_form.addRow(QLabel(tr("converter.edit_dlg_isbn")), self.ed_isbn)

        # Аннотация
        anno_box = QVBoxLayout()
        anno_box.setContentsMargins(0, 0, 0, 0)
        anno_box.setSpacing(4)
        self.ed_annotation = QPlainTextEdit(meta.get("annotation", ""))
        self.ed_annotation.setMinimumHeight(80)
        self.ed_annotation.setMaximumHeight(130)
        anno_box.addWidget(self.ed_annotation)

        anno_footer = QHBoxLayout()
        anno_footer.setContentsMargins(0, 0, 0, 0)
        self.lbl_anno_chars = QLabel()
        self.lbl_anno_chars.setObjectName("RowDesc")
        anno_footer.addWidget(self.lbl_anno_chars)
        anno_footer.addStretch()
        anno_box.addLayout(anno_footer)

        if self._orig_annotation_rich:
            lbl_rich = QLabel(tr("converter.edit_dlg_annotation_rich_warn"))
            lbl_rich.setObjectName("RowDesc")
            lbl_rich.setWordWrap(True)
            anno_box.addWidget(lbl_rich)

        self.ed_annotation.textChanged.connect(self._update_annotation_counter)
        self._update_annotation_counter()
        extra_form.addRow(QLabel(tr("converter.edit_dlg_annotation")), anno_box)

        extra_layout.addLayout(extra_form)
        return tab_extra

    def _build_cover_panel(self):
        cover_box = QVBoxLayout()
        cover_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        cover_box.setSpacing(8)

        cov_hdr = QLabel(tr("converter.cover_header"))
        cov_hdr.setObjectName("SectionHeader")
        cov_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_box.addWidget(cov_hdr)

        self.cover_preview_lbl = QLabel()
        self.cover_preview_lbl.setObjectName("CoverPanel")
        self.cover_preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_preview_lbl.setFixedSize(COVER_PREVIEW_SIZE[0], COVER_PREVIEW_SIZE[1])
        cover_box.addWidget(self.cover_preview_lbl)

        self.cover_info_label = QLabel()
        self.cover_info_label.setObjectName("RowDesc")
        self.cover_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_box.addWidget(self.cover_info_label)

        self.btn_replace_cover = QPushButton(tr("converter.btn_replace_cover"))
        self.btn_replace_cover.setObjectName("SecondaryButton")
        self.btn_replace_cover.setProperty("variant", "secondary")
        self.btn_replace_cover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_replace_cover.clicked.connect(self._replace_cover)
        cover_box.addWidget(self.btn_replace_cover)

        self.btn_reset_cover = QPushButton(tr("converter.btn_reset_cover"))
        self.btn_reset_cover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_cover.setEnabled(self._cover_modified)
        self.btn_reset_cover.clicked.connect(self._reset_cover)
        cover_box.addWidget(self.btn_reset_cover)

        self.btn_lookup_online = QPushButton(tr("converter.btn_lookup_online"))
        self.btn_lookup_online.setObjectName("SecondaryButton")
        self.btn_lookup_online.setProperty("variant", "secondary")
        self.btn_lookup_online.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lookup_online.clicked.connect(self._open_online_lookup)
        cover_box.addWidget(self.btn_lookup_online)

        self.btn_cover_studio = QPushButton(tr("converter.btn_cover_studio"))
        self.btn_cover_studio.setObjectName("SecondaryButton")
        self.btn_cover_studio.setProperty("variant", "secondary")
        self.btn_cover_studio.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cover_studio.clicked.connect(self._open_cover_studio)
        cover_box.addWidget(self.btn_cover_studio)

        cover_box.addStretch()
        return cover_box

    def _populate_genre_tree(self):
        self._syncing_genre_tree = True
        try:
            self.genre_tree.clear()
            self._genre_tree_items.clear()
            selected_set = set(self._selected_genres)
            for group_id, codes in FB2_GENRE_GROUPS:
                grp_item = QTreeWidgetItem([get_genre_group_label(group_id, tr)])
                grp_item.setFlags(grp_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                has_selected = False
                for code in codes:
                    label = get_genre_label(code, tr)
                    child = QTreeWidgetItem([f"{label} ({code})"])
                    child.setData(0, Qt.ItemDataRole.UserRole, code)
                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    is_checked = code in selected_set
                    child.setCheckState(0, Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked)
                    if is_checked:
                        has_selected = True
                    grp_item.addChild(child)
                    self._genre_tree_items[code] = child
                self.genre_tree.addTopLevelItem(grp_item)
                if has_selected:
                    grp_item.setExpanded(True)
        finally:
            self._syncing_genre_tree = False

    def _filter_genre_tree(self, query):
        q = (query or "").strip().lower()
        for i in range(self.genre_tree.topLevelItemCount()):
            grp = self.genre_tree.topLevelItem(i)
            grp_match = bool(q and q in grp.text(0).lower())
            any_child_visible = False
            for j in range(grp.childCount()):
                ch = grp.child(j)
                code = str(ch.data(0, Qt.ItemDataRole.UserRole) or "")
                vis = (not q) or grp_match or (q in ch.text(0).lower()) or (q in code)
                ch.setHidden(not vis)
                if vis:
                    any_child_visible = True
            grp.setHidden(not any_child_visible)
            if q and any_child_visible:
                grp.setExpanded(True)

    def _on_genre_tree_item_changed(self, item, column):
        if self._syncing_genre_tree or column != 0:
            return
        code = item.data(0, Qt.ItemDataRole.UserRole)
        if not code:
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            if code not in self._selected_genres:
                self._selected_genres.append(code)
        else:
            self._selected_genres = [g for g in self._selected_genres if g != code]
        self._rebuild_genre_chips()

    def _add_custom_genre_from_search(self):
        raw = normalize_genre_code(self.ed_genre_search.text())
        if not raw:
            return
        if raw not in self._selected_genres:
            self._selected_genres.append(raw)
        if raw in self._genre_tree_items:
            self._syncing_genre_tree = True
            try:
                self._genre_tree_items[raw].setCheckState(0, Qt.CheckState.Checked)
            finally:
                self._syncing_genre_tree = False
        self.ed_genre_search.clear()
        self._rebuild_genre_chips()

    def _remove_genre(self, code):
        self._selected_genres = [g for g in self._selected_genres if g != code]
        if code in self._genre_tree_items:
            self._syncing_genre_tree = True
            try:
                self._genre_tree_items[code].setCheckState(0, Qt.CheckState.Unchecked)
            finally:
                self._syncing_genre_tree = False
        self._rebuild_genre_chips()

    def _rebuild_genre_chips(self):
        while self._chips_layout.count():
            it = self._chips_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        if not self._selected_genres:
            lbl = QLabel(tr("converter.edit_dlg_genres_empty"))
            lbl.setObjectName("RowDesc")
            self._chips_layout.addWidget(lbl)
        else:
            for code in self._selected_genres:
                label = get_genre_label(code, tr)
                if code not in KNOWN_GENRE_CODES:
                    chip_txt = f"{code} ({tr('converter.edit_dlg_genre_custom_tag')}) ×"
                else:
                    chip_txt = f"{label} ×"
                btn = QPushButton(chip_txt)
                btn.setToolTip(code)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
                btn.clicked.connect(lambda _chk=False, c=code: self._remove_genre(c))
                self._chips_layout.addWidget(btn)
        self._chips_layout.addStretch()

    def _update_annotation_counter(self):
        cnt = len(self.ed_annotation.toPlainText().strip())
        self.lbl_anno_chars.setText(tr("converter.edit_dlg_annotation_chars", count=cnt))

    def _update_target_preview(self):
        target_text = simulate_fbc_target(
            self.get_meta(), self._output_format, self._filename_mode, self._filename_tokens
        )
        self.lbl_target_val.setText(target_text)
        self.lbl_target_val.setToolTip(target_text)

    def _render_cover(self):
        if not self._cover_bytes:
            self.cover_preview_lbl.setText(tr("converter.cover_missing"))
            self.cover_preview_lbl.setPixmap(QPixmap())
            self.cover_info_label.setText(tr("converter.cover_size_empty"))
            return
        pixmap = QPixmap()
        pixmap.loadFromData(self._cover_bytes)
        scaled = pixmap.scaled(
            COVER_PREVIEW_SIZE[0], COVER_PREVIEW_SIZE[1],
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.cover_preview_lbl.setPixmap(scaled)
        status = tr("converter.cover_modified") if self._cover_modified else ""
        self.cover_info_label.setText(tr("converter.cover_size", w=pixmap.width(), h=pixmap.height(), status=status))

    def _replace_cover(self):
        img_path, _ = QFileDialog.getOpenFileName(
            self, tr("converter.dlg_select_cover"), "", tr("converter.filter_images")
        )
        if img_path:
            try:
                fitted_bytes, mime_type = fit_image_to_cover_size(img_path)
                self._cover_bytes = fitted_bytes
                self._cover_mime = mime_type
                self._cover_modified = True
                self.btn_reset_cover.setEnabled(True)
                self._render_cover()
            except Exception as e:
                show_themed_message(self, tr("common.error"), tr("converter.err_update_cover", e=e), "error")

    def _reset_cover(self):
        self._cover_bytes = self._orig_cover_bytes
        self._cover_mime = self._orig_cover_mime
        self._cover_modified = False
        self.btn_reset_cover.setEnabled(False)
        self._render_cover()

    def _open_online_lookup(self):
        dlg = MetadataLookupDialog(self, self.get_meta(), app_settings=self._app_settings)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updates = dlg.get_selected_meta_updates()
        if "title" in updates:
            self.ed_title.setText(updates["title"])
        if "last" in updates:
            self.ed_last.setText(updates["last"])
        if "first" in updates:
            self.ed_first.setText(updates["first"])
        if "mid" in updates:
            self.ed_mid.setText(updates["mid"])
        if "series" in updates:
            self.ed_series.setText(updates["series"])
        if "num" in updates:
            self.ed_num.setText(updates["num"])
        if "lang" in updates and hasattr(self, "cb_lang"):
            self.cb_lang.setCurrentText(updates["lang"])
        if "translator_last" in updates and hasattr(self, "ed_tr_last"):
            self.ed_tr_last.setText(updates["translator_last"])
        if "translator_first" in updates and hasattr(self, "ed_tr_first"):
            self.ed_tr_first.setText(updates["translator_first"])
        if "translator_middle" in updates and hasattr(self, "ed_tr_mid"):
            self.ed_tr_mid.setText(updates["translator_middle"])
        if "publisher" in updates and hasattr(self, "ed_publisher"):
            self.ed_publisher.setText(updates["publisher"])
        if "isbn" in updates and hasattr(self, "ed_isbn"):
            self.ed_isbn.setText(updates["isbn"])
        if "annotation" in updates and hasattr(self, "ed_annotation"):
            self.ed_annotation.setPlainText(updates["annotation"])
        if "genres" in updates:
            self._selected_genres = normalize_genre_list(updates["genres"])
            self._populate_genre_tree()
            self._rebuild_genre_chips()
        cov = dlg.get_selected_cover()
        if cov is not None:
            self._cover_bytes, self._cover_mime = cov
            self._cover_modified = True
            self.btn_reset_cover.setEnabled(True)
            self._render_cover()
        self._update_target_preview()

    def _open_cover_studio(self):
        initial_spec = CoverSpec.from_dict(self._app_settings.get("cover_studio_spec"))
        fonts_dir = getattr(self.parent(), "fonts_dir", None)
        dlg = CoverStudioDialog(
            self,
            book_data={"meta": self.get_meta()},
            books_count=1,
            initial_spec=initial_spec,
            fonts_dir=fonts_dir,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._app_settings["cover_studio_spec"] = dlg.get_spec().to_dict()
        cover_bytes, cover_mime = dlg.get_rendered_cover()
        if cover_bytes:
            self._cover_bytes = cover_bytes
            self._cover_mime = cover_mime
            self._cover_modified = True
            self.btn_reset_cover.setEnabled(True)
            self._render_cover()

    def get_cover_studio_spec(self):
        return self._app_settings.get("cover_studio_spec")

    def get_meta(self):
        new_anno = self.ed_annotation.toPlainText().strip() if hasattr(self, "ed_annotation") else self._orig_annotation
        anno_rich = self._orig_annotation_rich and (new_anno == self._orig_annotation)
        return {
            "last": self.ed_last.text().strip(),
            "first": self.ed_first.text().strip(),
            "mid": self.ed_mid.text().strip(),
            "series": self.ed_series.text().strip(),
            "num": self.ed_num.text().strip(),
            "title": self.ed_title.text().strip(),
            "genres": list(self._selected_genres),
            "lang": self.cb_lang.currentText().strip().lower() if hasattr(self, "cb_lang") else "",
            "annotation": new_anno,
            "annotation_has_rich_xml": anno_rich,
            "translator_last": self.ed_tr_last.text().strip() if hasattr(self, "ed_tr_last") else "",
            "translator_first": self.ed_tr_first.text().strip() if hasattr(self, "ed_tr_first") else "",
            "translator_middle": self.ed_tr_mid.text().strip() if hasattr(self, "ed_tr_mid") else "",
            "extra_translators_count": self._extra_translators_count,
            "publisher": self.ed_publisher.text().strip() if hasattr(self, "ed_publisher") else "",
            "isbn": self.ed_isbn.text().strip() if hasattr(self, "ed_isbn") else "",
        }

    def get_cover_state(self):
        return self._cover_bytes, self._cover_mime, self._cover_modified

    def should_save_to_source(self):
        return bool(self.chk_save_source.isChecked())


class BatchEditDialog(QDialog):
    """Тематическое окно пакетного редактирования метаданных для нескольких книг."""

    def __init__(self, parent, count, common_meta=None):
        super().__init__(parent)
        self.setWindowTitle(tr("converter.batch_dlg_title"))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setModal(True)
        self.setMinimumWidth(560)
        if parent and parent.styleSheet():
            self.setStyleSheet(parent.styleSheet())

        common_meta = common_meta or {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 18)
        root.setSpacing(16)

        card = QFrame()
        card.setObjectName("SectionCard")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(20, 18, 20, 18)
        c_layout.setSpacing(14)

        hdr_lbl = QLabel(tr("converter.batch_dlg_title").upper())
        hdr_lbl.setObjectName("SectionHeader")
        c_layout.addWidget(hdr_lbl)

        desc_lbl = QLabel(tr("converter.batch_dlg_count", count=count))
        desc_lbl.setObjectName("RowDesc")
        desc_lbl.setWordWrap(True)
        c_layout.addWidget(desc_lbl)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self._fields = {}
        specs = [
            ("last", tr("converter.edit_dlg_last")),
            ("first", tr("converter.edit_dlg_first")),
            ("mid", tr("converter.edit_dlg_mid")),
            ("series", tr("converter.edit_dlg_series")),
        ]
        for key, label_txt in specs:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(10)

            chk = QCheckBox()
            chk.setChecked(False)
            ed = QLineEdit(common_meta.get(key, ""))
            ed.setMinimumWidth(260)
            ed.textEdited.connect(lambda _txt, c=chk: c.setChecked(True))

            row_l.addWidget(chk)
            row_l.addWidget(ed, 1)
            form.addRow(QLabel(label_txt), row_w)
            self._fields[key] = (chk, ed)

        # Пакетное редактирование жанров
        genre_w = QWidget()
        genre_v = QVBoxLayout(genre_w)
        genre_v.setContentsMargins(0, 0, 0, 0)
        genre_v.setSpacing(6)
        genre_top = QHBoxLayout()
        genre_top.setSpacing(8)
        self.chk_genres = QCheckBox()
        self.chk_genres.setChecked(False)
        self.cb_genre_mode = QComboBox()
        self.cb_genre_mode.addItem(tr("converter.batch_dlg_genre_mode_add"), "add")
        self.cb_genre_mode.addItem(tr("converter.batch_dlg_genre_mode_replace"), "replace")
        self.cb_genre_mode.addItem(tr("converter.batch_dlg_genre_mode_remove"), "remove")
        self.ed_batch_genres = QLineEdit()
        self.ed_batch_genres.setPlaceholderText(tr("converter.batch_dlg_genres_hint"))
        self.ed_batch_genres.textEdited.connect(lambda _t: self.chk_genres.setChecked(True))
        genre_top.addWidget(self.chk_genres)
        genre_top.addWidget(self.cb_genre_mode)
        genre_top.addWidget(self.ed_batch_genres, 1)
        genre_v.addLayout(genre_top)

        self.cb_genre_pick = QComboBox()
        self.cb_genre_pick.addItem(tr("converter.batch_dlg_genres_pick"), "")
        for _grp_id, codes in FB2_GENRE_GROUPS:
            for code in codes:
                self.cb_genre_pick.addItem(f"{get_genre_label(code, tr)} ({code})", code)
        self.cb_genre_pick.currentIndexChanged.connect(self._on_batch_genre_picked)
        genre_v.addWidget(self.cb_genre_pick)
        form.addRow(QLabel(tr("converter.batch_dlg_genres")), genre_w)

        # Пакетное редактирование языка
        lang_w = QWidget()
        lang_l = QHBoxLayout(lang_w)
        lang_l.setContentsMargins(0, 0, 0, 0)
        lang_l.setSpacing(10)
        self.chk_lang = QCheckBox()
        self.chk_lang.setChecked(False)
        self.cb_batch_lang = QComboBox()
        self.cb_batch_lang.setEditable(True)
        self.cb_batch_lang.addItem("")
        for lc in COMMON_LANG_CODES:
            self.cb_batch_lang.addItem(lc)
        self.cb_batch_lang.setCurrentText((common_meta.get("lang") or "").strip().lower())
        self.cb_batch_lang.editTextChanged.connect(lambda _t: self.chk_lang.setChecked(True))
        self.cb_batch_lang.setMaximumWidth(140)
        lang_l.addWidget(self.chk_lang)
        lang_l.addWidget(self.cb_batch_lang)
        lang_l.addStretch()
        form.addRow(QLabel(tr("converter.batch_dlg_lang")), lang_w)

        c_layout.addLayout(form)
        root.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton(tr("converter.btn_cancel"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_apply = QPushButton(tr("converter.btn_apply"))
        btn_apply.setObjectName("AccentButton")
        btn_apply.setProperty("variant", "primary")
        btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_apply.setDefault(True)
        btn_apply.clicked.connect(self.accept)
        btn_row.addWidget(btn_apply)
        root.addLayout(btn_row)

    def _on_batch_genre_picked(self, idx):
        code = self.cb_genre_pick.itemData(idx)
        if not code:
            return
        cur = normalize_genre_list(self.ed_batch_genres.text())
        if code not in cur:
            cur.append(code)
            self.ed_batch_genres.setText(", ".join(cur))
        self.chk_genres.setChecked(True)
        self.cb_genre_pick.blockSignals(True)
        self.cb_genre_pick.setCurrentIndex(0)
        self.cb_genre_pick.blockSignals(False)

    def get_updates(self):
        updates = {}
        for key, (chk, ed) in self._fields.items():
            if chk.isChecked():
                updates[key] = ed.text().strip()
        if self.chk_lang.isChecked():
            updates["lang"] = self.cb_batch_lang.currentText().strip().lower()
        return updates

    def get_genre_operation(self):
        """Возвращает (mode, codes) для пакетного изменения жанров или None."""
        if not self.chk_genres.isChecked():
            return None
        mode = self.cb_genre_mode.currentData() or "add"
        codes = normalize_genre_list(self.ed_batch_genres.text())
        if mode != "replace" and not codes:
            return None
        return mode, codes


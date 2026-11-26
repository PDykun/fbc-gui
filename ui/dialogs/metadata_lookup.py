from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QCheckBox,
    QDialog, QLineEdit, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from core.i18n import tr
from core.metadata_lookup import DEFAULT_ENABLED_PROVIDERS, DEFAULT_PROVIDER_ORDER, PROVIDER_LABELS


class MetadataLookupDialog(QDialog):
    """Диалог онлайн-подбора обложки и метаданных (FantLab, LitRes, Open Library, Google Books)."""

    _PROVIDER_LABELS = PROVIDER_LABELS

    _FIELD_SPECS = (
        ("title", "lookup.field_title"),
        ("last", "lookup.field_last"),
        ("first", "lookup.field_first"),
        ("mid", "lookup.field_mid"),
        ("series", "lookup.field_series"),
        ("num", "lookup.field_num"),
        ("genres", "lookup.field_genres"),
        ("lang", "lookup.field_lang"),
        ("translator", "lookup.field_translator"),
        ("publisher", "lookup.field_publisher"),
        ("isbn", "lookup.field_isbn"),
        ("annotation", "lookup.field_annotation"),
    )

    def __init__(self, parent, current_meta, app_settings=None):
        super().__init__(parent)
        self.setWindowTitle(tr("lookup.title"))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setModal(True)
        self.setMinimumSize(860, 640)
        if parent and parent.styleSheet():
            self.setStyleSheet(parent.styleSheet())

        self._current_meta = dict(current_meta or {})
        self._app_settings = dict(app_settings or {})
        self._candidates = []
        self._selected_candidate = None
        self._field_checks = {}
        self._loaded_covers = []
        self._selected_cover_idx = -1
        self._cover_cards = []
        self._lookup_worker = None
        self._cover_worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 18)
        root.setSpacing(12)

        root.addWidget(self._build_search_card())
        root.addWidget(self._build_results_card(), 1)
        root.addLayout(self._build_footer_row())

        if self.ed_title.text().strip() or self.ed_isbn.text().strip():
            QTimer.singleShot(60, self._start_search)

    def _build_search_card(self):
        search_card = QFrame()
        search_card.setObjectName("SectionCard")
        s_layout = QVBoxLayout(search_card)
        s_layout.setContentsMargins(16, 14, 16, 14)
        s_layout.setSpacing(10)

        q_row = QHBoxLayout()
        q_row.setSpacing(8)
        self.ed_title = QLineEdit(self._current_meta.get("title", ""))
        author_init = " ".join(
            p for p in (self._current_meta.get("first", ""), self._current_meta.get("last", "")) if p
        ).strip()
        self.ed_author = QLineEdit(author_init)
        self.ed_isbn = QLineEdit(self._current_meta.get("isbn", ""))
        self.ed_isbn.setFixedWidth(155)

        q_row.addWidget(QLabel(tr("lookup.lbl_title")))
        q_row.addWidget(self.ed_title, 2)
        q_row.addWidget(QLabel(tr("lookup.lbl_author")))
        q_row.addWidget(self.ed_author, 2)
        q_row.addWidget(QLabel(tr("lookup.lbl_isbn")))
        q_row.addWidget(self.ed_isbn, 0)

        self.btn_search = QPushButton(tr("lookup.btn_search"))
        self.btn_search.setObjectName("AccentButton")
        self.btn_search.setProperty("variant", "primary")
        self.btn_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search.clicked.connect(self._start_search)
        q_row.addWidget(self.btn_search)
        s_layout.addLayout(q_row)

        for ed in (self.ed_title, self.ed_author, self.ed_isbn):
            ed.returnPressed.connect(self._start_search)

        prov_row = QHBoxLayout()
        prov_row.setSpacing(12)
        prov_row.addWidget(QLabel(tr("lookup.lbl_providers")))
        saved_provs = set(self._app_settings.get("metadata_providers") or DEFAULT_ENABLED_PROVIDERS)
        has_gb_key = bool(str(self._app_settings.get("google_books_api_key") or "").strip())
        has_opds_url = bool(str(self._app_settings.get("opds_url") or "").strip())
        self._prov_checks = {}
        for pid in DEFAULT_PROVIDER_ORDER:
            chk = QCheckBox(self._PROVIDER_LABELS[pid])
            chk.setCursor(Qt.CursorShape.PointingHandCursor)
            if pid == "googlebooks" and not has_gb_key:
                chk.setChecked(False)
                chk.setEnabled(False)
                chk.setToolTip(tr("lookup.provider_google_no_key"))
            elif pid == "opds" and not has_opds_url:
                chk.setChecked(False)
                chk.setEnabled(False)
                chk.setToolTip(tr("lookup.provider_opds_no_url"))
            else:
                chk.setChecked(pid in saved_provs)
            prov_row.addWidget(chk)
            self._prov_checks[pid] = chk
        prov_row.addStretch()
        s_layout.addLayout(prov_row)

        self.lbl_status = QLabel(tr("lookup.status_idle"))
        self.lbl_status.setObjectName("RowDesc")
        self.lbl_status.setWordWrap(True)
        s_layout.addWidget(self.lbl_status)
        return search_card

    def _build_results_card(self):
        body_card = QFrame()
        body_card.setObjectName("SectionCard")
        b_layout = QVBoxLayout(body_card)
        b_layout.setContentsMargins(16, 14, 16, 14)
        b_layout.setSpacing(10)

        cand_hdr = QLabel(tr("lookup.sec_candidates"))
        cand_hdr.setObjectName("SectionHeader")
        b_layout.addWidget(cand_hdr)

        self.candidates_table = QTableWidget(0, 5)
        self.candidates_table.setHorizontalHeaderLabels([
            tr("lookup.col_source"),
            tr("lookup.col_title"),
            tr("lookup.col_author"),
            tr("lookup.col_year"),
            tr("lookup.col_score"),
        ])
        self.candidates_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.candidates_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.candidates_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.candidates_table.verticalHeader().setVisible(False)
        self.candidates_table.setMaximumHeight(135)
        self.candidates_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.candidates_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.candidates_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.candidates_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.candidates_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.candidates_table.itemSelectionChanged.connect(self._on_candidate_selected)
        b_layout.addWidget(self.candidates_table)

        cmp_hdr_row = QHBoxLayout()
        cmp_hdr = QLabel(tr("lookup.sec_compare"))
        cmp_hdr.setObjectName("SectionHeader")
        cmp_hdr_row.addWidget(cmp_hdr)
        cmp_hdr_row.addStretch()

        for label_key, mode in (
            ("lookup.btn_only_empty", "empty"),
            ("lookup.btn_select_all", "all"),
            ("lookup.btn_only_cover", "none"),
        ):
            btn = QPushButton(tr(label_key))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("padding: 3px 10px; font-size: 11px;")
            btn.clicked.connect(lambda _chk=False, m=mode: self._apply_selection_preset(m))
            cmp_hdr_row.addWidget(btn)
        b_layout.addLayout(cmp_hdr_row)

        self.compare_table = QTableWidget(0, 4)
        self.compare_table.setHorizontalHeaderLabels([
            tr("lookup.col_apply"),
            tr("lookup.col_field"),
            tr("lookup.col_current"),
            tr("lookup.col_found"),
        ])
        self.compare_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.compare_table.verticalHeader().setVisible(False)
        self.compare_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.compare_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.compare_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.compare_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        b_layout.addWidget(self.compare_table, 1)

        cov_hdr_row = QHBoxLayout()
        cov_hdr = QLabel(tr("lookup.sec_covers"))
        cov_hdr.setObjectName("SectionHeader")
        cov_hdr_row.addWidget(cov_hdr)
        self.lbl_cover_sel = QLabel(tr("lookup.cover_keep_current"))
        self.lbl_cover_sel.setObjectName("RowDesc")
        cov_hdr_row.addWidget(self.lbl_cover_sel)
        cov_hdr_row.addStretch()
        btn_keep_cov = QPushButton(tr("lookup.cover_keep_current"))
        btn_keep_cov.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_keep_cov.setStyleSheet("padding: 3px 10px; font-size: 11px;")
        btn_keep_cov.clicked.connect(lambda: self._select_cover(-1))
        cov_hdr_row.addWidget(btn_keep_cov)
        b_layout.addLayout(cov_hdr_row)

        self.covers_scroll = QScrollArea()
        self.covers_scroll.setWidgetResizable(True)
        self.covers_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.covers_scroll.setFixedHeight(148)
        self.covers_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._covers_container = QWidget()
        self._covers_layout = QHBoxLayout(self._covers_container)
        self._covers_layout.setContentsMargins(0, 2, 0, 2)
        self._covers_layout.setSpacing(10)
        self.covers_scroll.setWidget(self._covers_container)
        b_layout.addWidget(self.covers_scroll)
        return body_card

    def _build_footer_row(self):
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton(tr("converter.btn_cancel"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        self.btn_apply = QPushButton(tr("lookup.btn_apply"))
        self.btn_apply.setObjectName("AccentButton")
        self.btn_apply.setProperty("variant", "primary")
        self.btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_apply)
        return btn_row

    def _stop_workers(self):
        for attr in ("_lookup_worker", "_cover_worker"):
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    if w.isRunning():
                        w.cancel()
                        w.wait(2500)
                except RuntimeError:
                    pass
                setattr(self, attr, None)

    def done(self, result):
        self._stop_workers()
        super().done(result)

    def _start_search(self):
        from core.workers import MetadataLookupWorker

        self._stop_workers()
        enabled = [pid for pid, chk in self._prov_checks.items() if chk.isChecked() and chk.isEnabled()]
        if not enabled:
            return
        self.btn_search.setEnabled(False)
        self.btn_search.setText(tr("lookup.btn_searching"))
        self.lbl_status.setText(tr("lookup.status_searching"))
        self.candidates_table.setRowCount(0)
        self.compare_table.setRowCount(0)
        self._clear_covers_ui(tr("lookup.covers_loading"))
        self._candidates = []
        self._selected_candidate = None
        self.btn_apply.setEnabled(False)

        self._lookup_worker = MetadataLookupWorker(
            title=self.ed_title.text().strip(),
            author=self.ed_author.text().strip(),
            isbn=self.ed_isbn.text().strip(),
            enabled_providers=enabled,
            google_books_api_key=str(self._app_settings.get("google_books_api_key") or ""),
            opds_url=str(self._app_settings.get("opds_url") or ""),
            opds_username=str(self._app_settings.get("opds_username") or ""),
            opds_password=str(self._app_settings.get("opds_password") or ""),
            parent=self,
        )
        self._lookup_worker.finished_lookup.connect(self._on_lookup_finished)
        self._lookup_worker.start()

    def _on_lookup_finished(self, result):
        from core.workers import CoverFetchWorker

        self.btn_search.setEnabled(True)
        self.btn_search.setText(tr("lookup.btn_search"))
        self._candidates = list(getattr(result, "candidates", None) or [])
        errors = dict(getattr(result, "errors", None) or {})

        if not self._candidates:
            if errors:
                err_str = ", ".join(f"{self._PROVIDER_LABELS.get(k, k)}" for k in errors)
                self.lbl_status.setText(tr("lookup.status_empty_err", errs=err_str))
            else:
                self.lbl_status.setText(tr("lookup.status_empty"))
            self._clear_covers_ui(tr("lookup.covers_empty"))
            return

        if errors:
            err_str = ", ".join(f"{self._PROVIDER_LABELS.get(k, k)}" for k in errors)
            self.lbl_status.setText(tr("lookup.status_found_partial", count=len(self._candidates), errs=err_str))
        else:
            self.lbl_status.setText(tr("lookup.status_found", count=len(self._candidates)))

        self.candidates_table.setRowCount(len(self._candidates))
        for r, cand in enumerate(self._candidates):
            author_str = " ".join(p for p in (cand.first, cand.last) if p).strip()
            vals = (
                self._PROVIDER_LABELS.get(cand.provider, cand.provider),
                cand.title,
                author_str,
                cand.year or "—",
                f"{int(round(cand.score * 100))}%",
            )
            for c_idx, val in enumerate(vals):
                self.candidates_table.setItem(r, c_idx, QTableWidgetItem(str(val)))

        self.candidates_table.selectRow(0)
        self.btn_apply.setEnabled(True)

        self._cover_worker = CoverFetchWorker(
            self._candidates,
            max_covers=8,
            opds_url=str(self._app_settings.get("opds_url") or ""),
            opds_username=str(self._app_settings.get("opds_username") or ""),
            opds_password=str(self._app_settings.get("opds_password") or ""),
            parent=self,
        )
        self._cover_worker.finished_covers.connect(self._on_covers_loaded)
        self._cover_worker.start()

    def _format_field_value(self, meta, key):
        if key == "genres":
            return ", ".join(meta.get("genres") or [])
        if key == "translator":
            return " ".join(
                p for p in (
                    meta.get("translator_first", ""),
                    meta.get("translator_middle", ""),
                    meta.get("translator_last", ""),
                ) if (p or "").strip()
            ).strip()
        val = str(meta.get(key) or "").strip()
        if key == "annotation" and len(val) > 120:
            return val[:120] + "…"
        return val

    def _on_candidate_selected(self):
        rows = self.candidates_table.selectionModel().selectedRows()
        if not rows:
            return
        idx = rows[0].row()
        if idx < 0 or idx >= len(self._candidates):
            return
        cand = self._candidates[idx]
        self._selected_candidate = cand
        found_meta = cand.to_meta_patch()

        self._field_checks.clear()
        self.compare_table.setRowCount(len(self._FIELD_SPECS))
        for r, (key, label_key) in enumerate(self._FIELD_SPECS):
            cur_val = self._format_field_value(self._current_meta, key)
            new_val = self._format_field_value(found_meta, key)

            chk = QCheckBox()
            chk.setCursor(Qt.CursorShape.PointingHandCursor)
            has_new = bool(new_val)
            chk.setEnabled(has_new)
            chk.setChecked(has_new and (not cur_val))
            chk_wrap = QWidget()
            chk_l = QHBoxLayout(chk_wrap)
            chk_l.setContentsMargins(6, 0, 6, 0)
            chk_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_l.addWidget(chk)
            self.compare_table.setCellWidget(r, 0, chk_wrap)
            self.compare_table.setItem(r, 1, QTableWidgetItem(tr(label_key)))
            self.compare_table.setItem(r, 2, QTableWidgetItem(cur_val or "—"))
            self.compare_table.setItem(r, 3, QTableWidgetItem(new_val or "—"))
            self._field_checks[key] = (chk, bool(cur_val), has_new)

    def _apply_selection_preset(self, mode):
        for _key, (chk, has_cur, has_new) in self._field_checks.items():
            if not has_new:
                chk.setChecked(False)
            elif mode == "all":
                chk.setChecked(True)
            elif mode == "empty":
                chk.setChecked(not has_cur)
            else:
                chk.setChecked(False)

    def _clear_covers_ui(self, message=""):
        self._loaded_covers = []
        self._cover_cards = []
        self._selected_cover_idx = -1
        self.lbl_cover_sel.setText(tr("lookup.cover_keep_current"))
        while self._covers_layout.count():
            it = self._covers_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        if message:
            lbl = QLabel(message)
            lbl.setObjectName("RowDesc")
            self._covers_layout.addWidget(lbl)
            self._covers_layout.addStretch()

    def _on_covers_loaded(self, covers):
        self._clear_covers_ui()
        self._loaded_covers = list(covers or [])
        if not self._loaded_covers:
            self._clear_covers_ui(tr("lookup.covers_empty"))
            return

        for idx, cov in enumerate(self._loaded_covers):
            card = QFrame()
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setFixedSize(98, 136)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(4, 4, 4, 4)
            cl.setSpacing(2)

            img_lbl = QLabel()
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pm = QPixmap()
            pm.loadFromData(cov["bytes"])
            img_lbl.setPixmap(pm.scaled(78, 102, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            cl.addWidget(img_lbl, 1)

            prov_name = self._PROVIDER_LABELS.get(cov["provider"], cov["provider"])
            dims = f"{cov['width']}×{cov['height']}" if (cov.get("width") and cov.get("height")) else ""
            cap = QLabel(f"{prov_name}\n{dims}".strip())
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cap.setStyleSheet("font-size: 10px;")
            cl.addWidget(cap)

            card.mousePressEvent = lambda _ev, i=idx: self._select_cover(i)
            self._covers_layout.addWidget(card)
            self._cover_cards.append(card)

        self._covers_layout.addStretch()
        self._select_cover(-1)

    def _select_cover(self, idx):
        self._selected_cover_idx = idx if (0 <= idx < len(self._loaded_covers)) else -1
        for i, card in enumerate(self._cover_cards):
            if i == self._selected_cover_idx:
                card.setStyleSheet("border: 2px solid #38bdf8; border-radius: 6px;")
            else:
                card.setStyleSheet("border: 1px solid rgba(148, 163, 184, 0.3); border-radius: 6px;")
        if self._selected_cover_idx >= 0:
            cov = self._loaded_covers[self._selected_cover_idx]
            prov = self._PROVIDER_LABELS.get(cov["provider"], cov["provider"])
            self.lbl_cover_sel.setText(
                tr("lookup.cover_selected_badge", provider=prov, w=cov.get("width", 0), h=cov.get("height", 0))
            )
        else:
            self.lbl_cover_sel.setText(tr("lookup.cover_keep_current"))

    def get_selected_meta_updates(self):
        """Возвращает словарь только отмеченных пользователем метаданных для применения."""
        if self._selected_candidate is None:
            return {}
        patch_meta = self._selected_candidate.to_meta_patch()
        updates = {}
        for key, (chk, _has_cur, has_new) in self._field_checks.items():
            if not (has_new and chk.isChecked()):
                continue
            if key == "translator":
                updates["translator_first"] = patch_meta.get("translator_first", "")
                updates["translator_middle"] = patch_meta.get("translator_middle", "")
                updates["translator_last"] = patch_meta.get("translator_last", "")
            else:
                updates[key] = patch_meta.get(key)
        return updates

    def get_selected_cover(self):
        """Возвращает (cover_bytes, cover_mime) выбранной обложки (подогнанной под FB2) или None."""
        if not (0 <= self._selected_cover_idx < len(self._loaded_covers)):
            return None
        from core.metadata_lookup import fit_cover_bytes_to_target
        cov = self._loaded_covers[self._selected_cover_idx]
        return fit_cover_bytes_to_target(cov["bytes"], cov.get("mime", "image/jpeg"))


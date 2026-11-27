"""Модальный диалог Cover Studio — встроенный генератор типографских обложек для FBC GUI."""

from __future__ import annotations

import io
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.cover_studio import (
    PALETTES,
    TEMPLATES,
    CoverMetadata,
    CoverSpec,
    discover_available_fonts,
    render_cover_bytes,
    render_template_thumbnail,
    resolve_palette,
)
from core.i18n import LOCALE, tr
from core.undo_commands import UpdateBooksCommand, snapshot_book_state
from ui.dialogs.common import _format_bytes_human
from ui.theme import ColorPickerWidget, FlowLayout, FormatComboBox, PillSelector, create_section_card

_PRIMARY_PALETTE_IDS = (
    "eink_paper",
    "graphite",
    "emerald",
    "burgundy",
    "indigo",
    "parchment",
)


def _tr_fallback(key: str, ru_default: str, en_default: str, **kwargs) -> str:
    """Возвращает перевод из locales/*.json или человекочитаемый фолбэк по текущему языку."""
    default = ru_default if LOCALE.lang_code == "ru" else en_default
    val = LOCALE.get(key, default=default, **kwargs)
    return str(val)


def _pil_to_qpixmap(img) -> QPixmap:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    pix = QPixmap()
    pix.loadFromData(buf.getvalue(), "PNG")
    return pix


def _make_swatch_icon(bg_hex: str, accent_hex: str, size: int = 14) -> QIcon:
    """Рисует аккуратную круглую иконку палитры (фон + точка акцента) в HiDPI."""
    dpr = 2
    px = size * dpr
    pix = QPixmap(px, px)
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor(128, 128, 128, 140), 1.0))
    painter.setBrush(QColor(bg_hex))
    painter.drawEllipse(1, 1, size - 2, size - 2)

    dot = max(4, size // 3)
    off = (size - dot) // 2
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(accent_hex))
    painter.drawEllipse(off, off, dot, dot)
    painter.end()
    return QIcon(pix)


class CoverStudioDialog(QDialog):
    """Двухколоночный диалог генерации типографских обложек с живым превью и симуляцией E Ink."""

    def __init__(
        self,
        parent=None,
        book_data=None,
        *,
        books_count: int = 1,
        initial_spec: CoverSpec | None = None,
        fonts_dir: Path | str | None = None,
    ):
        super().__init__(parent)
        self._lang = LOCALE.lang_code or "ru"
        self._books_count = max(1, int(books_count or 1))
        self._is_batch = self._books_count > 1
        self._fonts_dir = fonts_dir
        self._meta = CoverMetadata.from_book_data(book_data or {}, lang=self._lang)
        self._spec = initial_spec or CoverSpec()
        self._apply_mode = "all"  # "all" | "missing_only"
        self._preview_eink_mode = "none"
        self._rendered_bytes: bytes = b""
        self._template_buttons: dict[str, QToolButton] = {}
        self._palette_buttons: dict[str, QPushButton] = {}
        self._selected_palette_id = (
            "emerald" if self._spec.palette_id == "auto_series" else self._spec.palette_id
        )
        if self._selected_palette_id not in _PRIMARY_PALETTE_IDS:
            self._selected_palette_id = "eink_paper"

        self.setWindowTitle(
            _tr_fallback("cover_studio.title", "Cover Studio — Создание обложки", "Cover Studio — Create Cover")
        )
        self.setObjectName("MainContainer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setModal(True)
        self.resize(1040, 710)
        self.setMinimumSize(940, 640)

        if parent is not None:
            self.setPalette(parent.palette())
            if parent.styleSheet():
                self.setStyleSheet(parent.styleSheet())

        self._closing = False
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(120)
        self._debounce_timer.timeout.connect(self._update_preview_now)

        self._build_ui()
        self._sync_custom_color_pickers()
        self._update_preview_now()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._build_preview_column(), 0)
        body.addWidget(self._build_controls_scroll(), 1)
        root.addLayout(body, 1)

        root.addLayout(self._build_footer_row())
        self._update_palette_buttons_state()

    def _build_preview_column(self) -> QFrame:
        preview_card = QFrame()
        preview_card.setObjectName("SectionCard")
        preview_card.setFixedWidth(346)
        p_lay = QVBoxLayout(preview_card)
        p_lay.setContentsMargins(18, 16, 18, 16)
        p_lay.setSpacing(12)
        p_lay.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        p_hdr = QLabel(
            _tr_fallback("cover_studio.preview_header", "ПРЕВЬЮ ОБЛОЖКИ", "COVER PREVIEW")
        )
        p_hdr.setObjectName("SectionHeader")
        p_lay.addWidget(p_hdr, 0, Qt.AlignmentFlag.AlignLeft)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("CoverPanel")
        self.preview_label.setFixedSize(260, 390)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p_lay.addWidget(self.preview_label, 0, Qt.AlignmentFlag.AlignHCenter)

        eink_lbl = QLabel(
            _tr_fallback("cover_studio.eink_sim_label", "Симуляция экрана E Ink", "E Ink Display Simulation")
        )
        eink_lbl.setObjectName("RowDesc")
        p_lay.addWidget(eink_lbl, 0, Qt.AlignmentFlag.AlignHCenter)

        self.eink_sim_selector = PillSelector(
            [
                (_tr_fallback("cover_studio.eink_color", "Цвет", "Color"), "none"),
                ("Carta", "eink_bw"),
                ("Kaleido 3", "eink_kaleido3"),
                ("Gallery 3", "eink_gallery3"),
            ],
            default="none",
            callback=self._on_eink_sim_changed,
            segmented=True,
        )
        # Компактные горизонтальные отступы у сегментов без нарушения высоты из QSS
        for seg_btn in self.eink_sim_selector._buttons.values():
            seg_btn.setStyleSheet("padding: 0px 10px; min-width: 0px;")
        p_lay.addWidget(self.eink_sim_selector, 0, Qt.AlignmentFlag.AlignHCenter)

        self.lbl_preview_info = QLabel("")
        self.lbl_preview_info.setObjectName("RowDesc")
        self.lbl_preview_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p_lay.addWidget(self.lbl_preview_info)
        p_lay.addStretch(1)
        return preview_card

    def _build_controls_scroll(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_content = QWidget()
        scroll_content.setObjectName("ScrollContent")
        c_lay = QVBoxLayout(scroll_content)
        c_lay.setContentsMargins(0, 0, 6, 0)
        c_lay.setSpacing(12)

        c_lay.addWidget(self._build_templates_card())
        c_lay.addWidget(self._build_palette_card())
        c_lay.addWidget(self._build_typography_card())
        c_lay.addStretch(1)

        scroll.setWidget(scroll_content)
        return scroll

    def _build_templates_card(self) -> QFrame:
        tpl_card, tpl_box = create_section_card(
            _tr_fallback("cover_studio.section_templates", "Шаблон обложки", "Cover Template")
        )
        tpl_wrap = QWidget()
        tpl_flow = FlowLayout(tpl_wrap, margin=0, h_spacing=8, v_spacing=8)
        for tpl_id, tpl_info in TEMPLATES.items():
            btn = QToolButton()
            btn.setObjectName("TemplateCardBtn")
            btn.setCheckable(True)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            btn.setIconSize(QSize(62, 93))
            btn.setFixedSize(98, 128)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            title_lbl = tpl_info["name_ru"] if self._lang == "ru" else tpl_info["name_en"]
            short_lbl = title_lbl.split()[0] if len(title_lbl) > 13 else title_lbl
            btn.setText(short_lbl)
            btn.setToolTip(title_lbl)
            thumb = render_template_thumbnail(
                tpl_id,
                palette_id=self._selected_palette_id,
                size=(128, 192),
                fonts_dir=self._fonts_dir,
            )
            btn.setIcon(QIcon(_pil_to_qpixmap(thumb)))
            btn.setChecked(tpl_id == self._spec.template_id)
            btn.clicked.connect(lambda checked=False, tid=tpl_id: self._select_template(tid))
            self._template_buttons[tpl_id] = btn
            tpl_flow.addWidget(btn)
        tpl_box.addWidget(tpl_wrap)
        return tpl_card

    def _build_palette_card(self) -> QFrame:
        pal_card, pal_box = create_section_card(
            _tr_fallback("cover_studio.section_palette", "Цветовая палитра", "Color Palette")
        )
        self.chk_auto_series = QCheckBox(
            _tr_fallback(
                "cover_studio.auto_series_color",
                "Единый цвет для всех книг одной серии",
                "Consistent color for all books in the same series",
            )
        )
        self.chk_auto_series.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_auto_series.setChecked(self._spec.palette_id == "auto_series")
        self.chk_auto_series.toggled.connect(self._on_auto_series_toggled)
        pal_box.addWidget(self.chk_auto_series)

        pal_wrap = QWidget()
        pal_flow = FlowLayout(pal_wrap, margin=0, h_spacing=8, v_spacing=8)
        for pid in _PRIMARY_PALETTE_IDS:
            p = PALETTES[pid]
            label = p.name_ru if self._lang == "ru" else p.name_en
            btn = QPushButton(label)
            btn.setIcon(_make_swatch_icon(p.bg, p.accent, size=14))
            btn.setIconSize(QSize(14, 14))
            btn.setCheckable(True)
            btn.setProperty("pill", True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, pal_id=pid: self._select_palette(pal_id))
            self._palette_buttons[pid] = btn
            pal_flow.addWidget(btn)
        pal_box.addWidget(pal_wrap)

        custom_row = QHBoxLayout()
        custom_row.setSpacing(8)
        lbl_bg = QLabel(_tr_fallback("cover_studio.custom_bg", "Фон:", "Background:"))
        lbl_bg.setObjectName("RowDesc")
        self.picker_bg = ColorPickerWidget(
            self,
            values=[PALETTES[k].bg for k in _PRIMARY_PALETTE_IDS],
            default_color=self._spec.custom_bg or PALETTES[self._selected_palette_id].bg,
            width=94,
        )
        self.picker_bg.bind("<<ComboboxSelected>>", self._on_custom_color_changed)

        lbl_acc = QLabel(_tr_fallback("cover_studio.custom_accent", "Акцент:", "Accent:"))
        lbl_acc.setObjectName("RowDesc")
        self.picker_accent = ColorPickerWidget(
            self,
            values=[PALETTES[k].accent for k in _PRIMARY_PALETTE_IDS],
            default_color=self._spec.custom_accent or PALETTES[self._selected_palette_id].accent,
            width=94,
        )
        self.picker_accent.bind("<<ComboboxSelected>>", self._on_custom_color_changed)

        self.btn_reset_colors = QPushButton(
            _tr_fallback("cover_studio.btn_reset_colors", "Сброс", "Reset")
        )
        self.btn_reset_colors.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_colors.clicked.connect(self._reset_custom_colors)

        custom_row.addWidget(lbl_bg)
        custom_row.addWidget(self.picker_bg)
        custom_row.addSpacing(4)
        custom_row.addWidget(lbl_acc)
        custom_row.addWidget(self.picker_accent)
        custom_row.addSpacing(4)
        custom_row.addWidget(self.btn_reset_colors)
        custom_row.addStretch(1)
        pal_box.addLayout(custom_row)
        return pal_card

    def _build_typography_card(self) -> QFrame:
        typo_card, typo_box = create_section_card(
            _tr_fallback("cover_studio.section_typography", "Типографика и поля", "Typography & Fields")
        )
        font_row = QHBoxLayout()
        font_row.setSpacing(10)
        lbl_font = QLabel(_tr_fallback("cover_studio.font_label", "Шрифт:", "Font:"))
        lbl_font.setObjectName("RowTitle")
        self.combo_font = FormatComboBox()
        self.combo_font.setMinimumWidth(240)
        fonts = discover_available_fonts(self._fonts_dir)
        self.combo_font.addItems(fonts)
        if self._spec.title_font in fonts:
            self.combo_font.setCurrentText(self._spec.title_font)
        self.combo_font.currentTextChanged.connect(self._schedule_preview)
        font_row.addWidget(lbl_font)
        font_row.addWidget(self.combo_font, 1)
        typo_box.addLayout(font_row)

        fields_row = QHBoxLayout()
        fields_row.setSpacing(16)
        self.chk_author = QCheckBox(_tr_fallback("cover_studio.field_author", "Автор", "Author"))
        self.chk_author.setChecked(self._spec.show_author)
        self.chk_author.toggled.connect(self._schedule_preview)

        self.chk_series = QCheckBox(_tr_fallback("cover_studio.field_series", "Серия", "Series"))
        self.chk_series.setChecked(self._spec.show_series)
        self.chk_series.toggled.connect(self._schedule_preview)

        self.chk_num = QCheckBox(_tr_fallback("cover_studio.field_number", "Номер тома", "Volume #"))
        self.chk_num.setChecked(self._spec.show_series_number)
        self.chk_num.toggled.connect(self._schedule_preview)

        self.chk_genre = QCheckBox(_tr_fallback("cover_studio.field_genre", "Жанр", "Genre"))
        self.chk_genre.setChecked(self._spec.show_genre_badge)
        self.chk_genre.toggled.connect(self._schedule_preview)

        for chk in (self.chk_author, self.chk_series, self.chk_num, self.chk_genre):
            chk.setCursor(Qt.CursorShape.PointingHandCursor)
            fields_row.addWidget(chk)
        fields_row.addStretch(1)
        typo_box.addLayout(fields_row)

        if self._is_batch:
            batch_hint = QLabel(
                _tr_fallback(
                    "cover_studio.batch_hint",
                    "Пакетный режим ({count} кн.): автор, название, серия и жанр берутся из метаданных каждой книги.",
                    "Batch mode ({count} books): author, title, series, and genre are taken from each book's metadata.",
                    count=self._books_count,
                )
            )
            batch_hint.setObjectName("RowDesc")
            batch_hint.setWordWrap(True)
            typo_box.addWidget(batch_hint)
            self.edit_subtitle = None
        else:
            sub_row = QHBoxLayout()
            sub_row.setSpacing(10)
            lbl_sub = QLabel(_tr_fallback("cover_studio.subtitle_label", "Подзаголовок:", "Subtitle:"))
            lbl_sub.setObjectName("RowDesc")
            self.edit_subtitle = QLineEdit(self._spec.custom_subtitle or self._meta.subtitle)
            self.edit_subtitle.setPlaceholderText(
                _tr_fallback("cover_studio.subtitle_placeholder", "Необязательно (например, год издания)", "Optional (e.g., edition year)")
            )
            self.edit_subtitle.textChanged.connect(self._schedule_preview)
            sub_row.addWidget(lbl_sub)
            sub_row.addWidget(self.edit_subtitle, 1)
            typo_box.addLayout(sub_row)
        return typo_card

    def _build_footer_row(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addStretch(1)

        btn_cancel = QPushButton(tr("common.cancel"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)

        if self._is_batch:
            self.btn_apply_missing = QPushButton(
                _tr_fallback(
                    "cover_studio.btn_apply_missing",
                    "Только для книг без обложки",
                    "Missing Covers Only",
                )
            )
            self.btn_apply_missing.setObjectName("SecondaryButton")
            self.btn_apply_missing.setProperty("variant", "secondary")
            self.btn_apply_missing.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_apply_missing.clicked.connect(lambda: self._accept_with_mode("missing_only"))
            footer.addWidget(self.btn_apply_missing)

        self.btn_apply = QPushButton(
            _tr_fallback(
                "cover_studio.btn_apply_batch",
                "Применить ко всем ({count})",
                "Apply to All ({count})",
                count=self._books_count,
            )
            if self._is_batch
            else _tr_fallback("cover_studio.btn_apply", "Применить обложку", "Apply Cover")
        )
        self.btn_apply.setObjectName("AccentButton")
        self.btn_apply.setProperty("variant", "primary")
        self.btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply.setDefault(True)
        self.btn_apply.clicked.connect(lambda: self._accept_with_mode("all"))
        footer.addWidget(self.btn_apply)
        return footer

    def _select_template(self, template_id: str) -> None:
        for tid, btn in self._template_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(tid == template_id)
            btn.blockSignals(False)
        self._spec = CoverSpec(**{**self._spec.__dict__, "template_id": template_id})
        self._schedule_preview()

    def _select_palette(self, palette_id: str) -> None:
        self._selected_palette_id = palette_id
        self.chk_auto_series.blockSignals(True)
        self.chk_auto_series.setChecked(False)
        self.chk_auto_series.blockSignals(False)
        self._spec = CoverSpec(
            **{
                **self._spec.__dict__,
                "palette_id": palette_id,
                "custom_bg": "",
                "custom_fg": "",
                "custom_accent": "",
            }
        )
        self._update_palette_buttons_state()
        self._sync_custom_color_pickers()
        self._schedule_preview()

    def _on_auto_series_toggled(self, checked: bool) -> None:
        pid = "auto_series" if checked else self._selected_palette_id
        self._spec = CoverSpec(
            **{
                **self._spec.__dict__,
                "palette_id": pid,
                "custom_bg": "",
                "custom_fg": "",
                "custom_accent": "",
            }
        )
        self._update_palette_buttons_state()
        self._sync_custom_color_pickers()
        self._schedule_preview()

    def _on_custom_color_changed(self) -> None:
        self._spec = CoverSpec(
            **{
                **self._spec.__dict__,
                "custom_bg": self.picker_bg.get(),
                "custom_accent": self.picker_accent.get(),
                "custom_fg": "",
            }
        )
        self._schedule_preview()

    def _reset_custom_colors(self) -> None:
        self._spec = CoverSpec(
            **{**self._spec.__dict__, "custom_bg": "", "custom_fg": "", "custom_accent": ""}
        )
        self._sync_custom_color_pickers()
        self._schedule_preview()

    def _sync_custom_color_pickers(self) -> None:
        pal = resolve_palette(self._spec, self._meta.series)
        self.picker_bg.combo.blockSignals(True)
        self.picker_accent.combo.blockSignals(True)
        try:
            self.picker_bg.set(pal.bg)
            self.picker_bg._update_swatch(pal.bg)
            self.picker_accent.set(pal.accent)
            self.picker_accent._update_swatch(pal.accent)
        finally:
            self.picker_bg.combo.blockSignals(False)
            self.picker_accent.combo.blockSignals(False)

    def _update_palette_buttons_state(self) -> None:
        is_auto = self.chk_auto_series.isChecked()
        for pid, btn in self._palette_buttons.items():
            active = (not is_auto) and (pid == self._selected_palette_id)
            btn.blockSignals(True)
            btn.setChecked(active)
            btn.blockSignals(False)
            btn.setObjectName("OptionPillActive" if active else "OptionPill")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def _on_eink_sim_changed(self, mode: str) -> None:
        self._preview_eink_mode = mode
        self._schedule_preview()

    def _schedule_preview(self, *_args) -> None:
        if self._closing:
            return
        self._debounce_timer.start()

    def _stop_preview_timer(self) -> None:
        self._closing = True
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()

    def done(self, result: int) -> None:
        self._stop_preview_timer()
        super().done(result)

    def closeEvent(self, event) -> None:
        self._stop_preview_timer()
        super().closeEvent(event)

    def get_spec(self) -> CoverSpec:
        """Возвращает текущую конфигурацию CoverSpec из виджетов диалога."""
        selected_font = self.combo_font.currentText().strip() or "PT Astra Serif"
        subtitle = self.edit_subtitle.text().strip() if self.edit_subtitle is not None else ""
        return CoverSpec(
            template_id=self._spec.template_id,
            palette_id="auto_series" if self.chk_auto_series.isChecked() else self._selected_palette_id,
            custom_bg=self._spec.custom_bg,
            custom_fg=self._spec.custom_fg,
            custom_accent=self._spec.custom_accent,
            title_font=selected_font,
            meta_font=selected_font,
            show_author=self.chk_author.isChecked(),
            show_series=self.chk_series.isChecked(),
            show_series_number=self.chk_num.isChecked(),
            show_genre_badge=self.chk_genre.isChecked(),
            custom_subtitle=subtitle,
            eink_profile=self._spec.eink_profile,
            output_size=self._spec.output_size,
            output_format=self._spec.output_format,
            jpeg_quality=self._spec.jpeg_quality,
        )

    def get_apply_mode(self) -> str:
        """Возвращает 'all' или 'missing_only'."""
        return self._apply_mode

    def get_rendered_cover(self) -> tuple[bytes, str]:
        """Возвращает последнюю сгенерированную обложку ``(bytes, mime_type)``."""
        spec = self.get_spec()
        if not self._rendered_bytes:
            self._rendered_bytes = render_cover_bytes(
                self._meta, spec, fonts_dir=self._fonts_dir
            )
        mime = "image/png" if spec.output_format.upper() == "PNG" else "image/jpeg"
        return self._rendered_bytes, mime

    def _update_preview_now(self) -> None:
        if self._closing:
            return
        spec = self.get_spec()
        self._rendered_bytes = render_cover_bytes(
            self._meta, spec, fonts_dir=self._fonts_dir, simulate_eink_preview=False
        )
        if self._preview_eink_mode != "none":
            sim_spec = CoverSpec(**{**spec.__dict__, "eink_profile": self._preview_eink_mode})
            preview_bytes = render_cover_bytes(
                self._meta, sim_spec, fonts_dir=self._fonts_dir, simulate_eink_preview=True
            )
        else:
            preview_bytes = self._rendered_bytes

        pix = QPixmap()
        pix.loadFromData(preview_bytes)
        if not pix.isNull():
            scaled = pix.scaled(
                self.preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_label.setPixmap(scaled)

        w, h = spec.output_size
        size_txt = _format_bytes_human(len(self._rendered_bytes))
        self.lbl_preview_info.setText(f"{w} × {h} px · {spec.output_format} · {size_txt}")

    def _accept_with_mode(self, mode: str) -> None:
        self._apply_mode = mode
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()
            self._update_preview_now()
        self.accept()


def apply_cover_studio_to_books(
    target,
    item_ids,
    spec: CoverSpec,
    *,
    only_missing: bool = False,
    fonts_dir: Path | str | None = None,
    undo_text: str | None = None,
) -> int:
    """Генерирует обложки для списка ``item_ids`` и применяет их одной командой ``UpdateBooksCommand``.

    Возвращает количество обновлённых книг. Полностью совместимо с ``QUndoStack`` в ``MainWindow``.
    """
    lang = LOCALE.lang_code or "ru"
    mime = "image/png" if spec.output_format.upper() == "PNG" else "image/jpeg"
    changes = []

    for item_id in item_ids:
        data = target.files_data.get(item_id)
        if not data:
            continue
        if only_missing and data.get("cover_bytes"):
            continue
        meta = CoverMetadata.from_book_data(data, lang=lang)
        eff_spec = spec if len(item_ids) == 1 else CoverSpec(**{**spec.__dict__, "custom_subtitle": ""})
        cover_bytes = render_cover_bytes(meta, eff_spec, fonts_dir=fonts_dir)

        before = snapshot_book_state(data)
        after = {
            **before,
            "cover_bytes": cover_bytes,
            "cover_mime": mime,
            "cover_modified": True,
        }
        if before != after:
            changes.append({"item_id": item_id, "before": before, "after": after})

    if not changes:
        return 0

    label = undo_text or _tr_fallback(
        "converter.undo_cover_studio",
        "Создать обложки ({count})",
        "Generate covers ({count})",
        count=len(changes),
    )
    target.undo_stack.push(UpdateBooksCommand(target, changes, label))
    return len(changes)

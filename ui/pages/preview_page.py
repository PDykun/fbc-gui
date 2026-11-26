from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QPushButton, QLabel

from core.i18n import tr
from ui.theme import PillSelector, create_section_card
from ui.native_webview import create_preview_widget


def build_preview_page(win, parent):
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    top_bar = QHBoxLayout()
    top_bar.setSpacing(10)

    win.preview_mode_selector = PillSelector(
        [
            (tr("preview.mode_book"), "book"),
            (tr("preview.mode_sample"), "sample"),
        ],
        default=getattr(win, "preview_source_mode", "book"),
        callback=win.on_preview_mode_changed,
        segmented=True,
    )
    top_bar.addWidget(win.preview_mode_selector)

    win.btn_preview_simulate_eink = QPushButton(tr("preview.btn_simulate_eink"))
    win.btn_preview_simulate_eink.setCheckable(True)
    win.btn_preview_simulate_eink.setProperty("pill", True)
    win.btn_preview_simulate_eink.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_preview_simulate_eink.setToolTip(tr("preview.tooltip_simulate_eink"))
    win.btn_preview_simulate_eink.setChecked(
        str(win.app_settings.get("preview_simulate_eink", "true")).lower() == "true"
    )
    win.btn_preview_simulate_eink.toggled.connect(win.on_preview_simulate_eink_toggled)
    top_bar.addWidget(win.btn_preview_simulate_eink)

    win.lbl_preview_source = QLabel(tr("preview.info_bar"))
    win.lbl_preview_source.setObjectName("RowDesc")
    top_bar.addWidget(win.lbl_preview_source, 1)

    btn_browser = QPushButton(tr("preview.btn_browser"))
    btn_browser.clicked.connect(win.open_in_browser)
    top_bar.addWidget(btn_browser)

    btn_refresh = QPushButton(tr("preview.btn_refresh"))
    btn_refresh.setObjectName("AccentButton")
    btn_refresh.setProperty("variant", "primary")
    btn_refresh.clicked.connect(win.refresh_preview)
    top_bar.addWidget(btn_refresh)
    layout.addLayout(top_bar)

    preview_widget, engine_kind = create_preview_widget(parent)
    win.preview_browser = preview_widget
    win.preview_engine_kind = engine_kind
    win.preview_is_webengine = (engine_kind != "fallback")

    engine_labels = {
        "wkwebview": tr("preview.engine_wkwebview"),
        "webview2": tr("preview.engine_webview2"),
        "webengine": tr("preview.engine_web"),
        "fallback": tr("preview.engine_fallback"),
    }
    engine_tag = engine_labels.get(engine_kind, tr("preview.engine_fallback"))
    card, c_layout = create_section_card(f'{tr("preview.sec_preview")}  •  {engine_tag}')

    c_layout.addWidget(win.preview_browser, 1)
    layout.addWidget(card, 1)

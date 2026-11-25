import webbrowser
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel

from core.i18n import tr
from ui.theme import create_section_card, add_setting_row


def build_about_page(
    win,
    parent,
    app_name,
    app_version,
    app_author,
    app_email,
    app_url,
    third_party_name,
    third_party_version,
    third_party_url
):
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(16)

    card, c_layout = create_section_card(tr("about.sec_about"))

    add_setting_row(c_layout, tr("about.lbl_name"), tr("about.desc_name"), QLabel(f"<b>{app_name}</b>"))
    add_setting_row(c_layout, tr("about.lbl_version"), tr("about.desc_version"), QLabel(f"<b>{app_version}</b>"))

    win.btn_open_docs = QPushButton(tr("about.btn_open_docs"))
    win.btn_open_docs.setObjectName("SecondaryButton")
    win.btn_open_docs.setProperty("variant", "secondary")
    win.btn_open_docs.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_open_docs.clicked.connect(win.open_user_guide)
    add_setting_row(c_layout, tr("about.lbl_docs"), tr("about.desc_docs"), win.btn_open_docs)

    win.btn_check_updates = QPushButton(tr("about.btn_check_updates"))
    win.btn_check_updates.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_check_updates.clicked.connect(lambda: win.check_for_updates(manual=True))
    add_setting_row(c_layout, tr("about.lbl_updates"), tr("about.desc_updates"), win.btn_check_updates)

    win.btn_open_log = QPushButton(tr("about.btn_open_log"))
    win.btn_open_log.setCursor(Qt.CursorShape.PointingHandCursor)
    win.btn_open_log.clicked.connect(win.open_log_file)
    add_setting_row(c_layout, tr("about.lbl_log"), tr("about.desc_log"), win.btn_open_log)

    add_setting_row(c_layout, tr("about.lbl_author"), tr("about.desc_author"), QLabel(f"<b>{app_author}</b>"))

    btn_mail = QPushButton(app_email)
    btn_mail.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_mail.clicked.connect(lambda: webbrowser.open(f"mailto:{app_email}"))
    add_setting_row(c_layout, tr("about.lbl_email"), tr("about.desc_email"), btn_mail)

    btn_web = QPushButton(app_url)
    btn_web.setObjectName("AccentButton")
    btn_web.setProperty("variant", "primary")
    btn_web.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_web.clicked.connect(lambda: webbrowser.open(f"https://{app_url}"))
    add_setting_row(c_layout, tr("about.lbl_url"), tr("about.desc_url"), btn_web)

    tp_widget = QWidget()
    tp_layout = QHBoxLayout(tp_widget)
    tp_layout.setContentsMargins(0, 0, 0, 0)
    tp_layout.setSpacing(10)

    win.lbl_third_party_ver = QLabel(f"<b>{tr('about.third_party_ver', ver=third_party_version)}</b>")
    tp_layout.addWidget(win.lbl_third_party_ver)

    tp_label = third_party_url.replace("https://", "").replace("http://", "")
    btn_tp_url = QPushButton(tp_label)
    btn_tp_url.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_tp_url.clicked.connect(lambda: webbrowser.open(third_party_url))
    tp_layout.addWidget(btn_tp_url)

    add_setting_row(c_layout, tr("about.lbl_third_party"), third_party_name, tp_widget)

    layout.addWidget(card)
    layout.addStretch()

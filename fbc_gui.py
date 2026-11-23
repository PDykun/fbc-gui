import os
import sys
import json
import time
import struct
import getpass
import threading
import subprocess
import webbrowser
import shutil
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

from PyQt6.QtCore import Qt, QUrl, QEvent, QObject, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import (
    QPixmap, QDesktopServices, QDragEnterEvent, QDropEvent,
    QFontDatabase, QKeySequence, QShortcut, QUndoStack
)
try:
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    HAS_QT_NETWORK = True
except ImportError:
    QLocalServer = None
    QLocalSocket = None
    HAS_QT_NETWORK = False
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTableWidgetItem, QFrame,
    QGridLayout, QStackedWidget, QDialog, QMenu, QAbstractItemView,
    QInputDialog
)

# --- Метаинформация и версия программы ---
__app_name__ = "FBC GUI"
__version__ = "2.8.1"
__build__ = 54
__author__ = "Paul Dykoun"
__email__ = "me@pashka.eu"
__url__ = "www.pashka.eu/fbc_gui"

APP_NAME = __app_name__
BUILD_NUMBER = __build__
APP_VERSION = __version__
APP_AUTHOR = __author__
APP_EMAIL = __email__
APP_URL = __url__
THIRD_PARTY_NAME = "fbc2ng"
THIRD_PARTY_VERSION = "2.1.1"
THIRD_PARTY_URL = "https://github.com/rupor-github/fb2cng"


from core.config import (
    DEFAULT_OUTPUT_FORMAT, DEVICE_PROFILES, get_default_app_settings,
    migrate_fbc_config_211, load_app_settings as load_settings_file,
    save_app_settings as save_settings_file,
    sync_settings_from_fbc_config as sync_fbc_config,
    update_fbc_config_file as write_fbc_config
)
from core.fb2_processor import (
    COVER_PREVIEW_SIZE, ConversionCancelledError,
    book_matches_filter,
    collect_book_paths, collect_startup_paths, iter_fb2_from_file, get_book_xml,
    extract_cover_from_fb2, extract_book_preview_data, save_book_changes_to_source,
    fit_image_to_cover_size, simulate_fbc_target, parse_metadata, convert_book_file
)
from core.undo_commands import (
    snapshot_book_state,
    UpdateBooksCommand,
    RemoveBooksCommand,
    ReorderBooksCommand,
)
from core.presets import (
    PRESET_FILE_EXT,
    list_presets as list_user_presets,
    save_preset as save_user_preset_file,
    load_preset_file,
    delete_preset as delete_user_preset_file,
    export_preset_to_file,
    import_preset_from_file,
    apply_preset_to_settings,
    slugify_preset_name,
    sync_bundled_presets,
    find_builtin_preset_path,
    restore_builtin_preset,
)
from core.email_sender import (
    is_smtp_configured,
    is_email_auto_send_ready as check_email_auto_ready,
    send_converted_files_via_email as send_email_attachments,
    send_test_email as dispatch_test_email
)
from core.css_preview import (
    get_default_css_ui_state,
    parse_css_file_to_state,
    generate_css_content as build_css_content,
    build_full_preview_html as render_preview_html
)
from core.fbc_manager import (
    FBC_TARGET_VERSION,
    FbcEnsureWorker,
    resolve_local_fbc,
)


def setup_app_environment():
    """Настраивает пути к ресурсам, рабочей папке пользователя и ищет локальный fb2cng."""
    if getattr(sys, 'frozen', False):
        bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        if sys.platform == "darwin":
            user_data_dir = os.path.expanduser("~/Library/Application Support/FBC_GUI")
        elif os.name == "nt":
            user_data_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "FBC_GUI")
        else:
            user_data_dir = os.path.expanduser("~/.config/FBC_GUI")
    else:
        bundle_dir = os.path.dirname(os.path.abspath(__file__))
        user_data_dir = bundle_dir

    os.makedirs(user_data_dir, exist_ok=True)
    presets_dir = os.path.join(user_data_dir, "presets")
    bundled_presets_dir = os.path.join(bundle_dir, "presets_defaults")
    os.makedirs(presets_dir, exist_ok=True)
    sync_bundled_presets(bundled_presets_dir, presets_dir)

    if bundle_dir != user_data_dir:
        for fname in ("config.yaml", "ebook_styles.css"):
            src_f = os.path.join(bundle_dir, fname)
            dst_f = os.path.join(user_data_dir, fname)
            if os.path.exists(src_f) and not os.path.exists(dst_f):
                shutil.copy2(src_f, dst_f)

        for sub_dir in ("fonts", "locales", "themes"):
            src_sub = os.path.join(bundle_dir, sub_dir)
            dst_sub = os.path.join(user_data_dir, sub_dir)
            if os.path.exists(src_sub):
                os.makedirs(dst_sub, exist_ok=True)
                for f in os.listdir(src_sub):
                    s_fp = os.path.join(src_sub, f)
                    d_fp = os.path.join(dst_sub, f)
                    if os.path.isfile(s_fp) and (not os.path.exists(d_fp) or sub_dir == "themes"):
                        shutil.copy2(s_fp, d_fp)

    # Дистрибутив не включает сторонний бинарник fbc: ищем локально в PATH ОС и user_data_dir
    local_fbc = resolve_local_fbc(user_data_dir=user_data_dir)
    fbc_cmd = local_fbc["path"] if local_fbc else ""
    fbc_ver = local_fbc["version"] if local_fbc else ""

    cfg_path = os.path.join(user_data_dir, "config.yaml")
    css_path = os.path.join(user_data_dir, "ebook_styles.css")
    bundled_css_path = os.path.join(bundle_dir, "ebook_styles.css")
    migrate_fbc_config_211(cfg_path, css_path)

    return (
        user_data_dir,
        fbc_cmd,
        fbc_ver,
        cfg_path,
        css_path,
        bundled_css_path,
        os.path.join(user_data_dir, "fonts"),
        os.path.join(user_data_dir, "settings.json"),
        os.path.join(user_data_dir, "locales"),
        os.path.join(bundle_dir, "locales"),
        os.path.join(user_data_dir, "themes"),
        os.path.join(bundle_dir, "themes"),
        presets_dir,
        bundled_presets_dir,
    )


(
    BASE_DIR, FBC_CMD, FBC_DETECTED_VERSION, FBC_CONFIG, CSS_PATH, BUNDLED_CSS_PATH, FONTS_DIR,
    SETTINGS_PATH, LOCALES_DIR, BUNDLED_LOCALES_DIR,
    THEMES_DIR, BUNDLED_THEMES_DIR, PRESETS_DIR, BUNDLED_PRESETS_DIR
) = setup_app_environment()

from core.logger import init_logging, get_logger, get_log_file_path
LOG_PATH = init_logging(BASE_DIR)
logger = get_logger("app")
logger.info("%s v%s (build %s) started; base_dir=%s", APP_NAME, APP_VERSION, BUILD_NUMBER, BASE_DIR)

from core.i18n import (
    LOCALE, init_locale, tr,
    LEGACY_ALIGN_MAP, LEGACY_STYLE_MAP, LEGACY_NOTE_BG_MAP, LEGACY_NOTE_BORDER_MAP,
    get_theme_choices
)
from core.updater import UpdateCheckWorker, UPDATE_CHECK_INTERVAL_SEC
from ui.theme import (
    LEGACY_THEME_MAP, init_themes,
    resolve_theme_family_and_mode,
    build_theme_qss, build_qpalette_from_qss, start_window_crossfade,
    refresh_widget_halos,
    ThemeToggleWidget, show_themed_message, show_conversion_summary_dialog, show_update_dialog,
    ConversionProgressDialog, ImportProgressDialog, FbcSetupDialog, BookEditDialog, BatchEditDialog
)
from ui.pages.converter_page import build_converter_page
from ui.pages.css_page import build_visual_css_page
from ui.pages.preview_page import build_preview_page
from ui.pages.settings_page import build_settings_page
from ui.pages.about_page import build_about_page

init_locale(LOCALES_DIR, BUNDLED_LOCALES_DIR)
init_themes(THEMES_DIR, BUNDLED_THEMES_DIR)


def parse_ttf_names(font_path):
    names = {}
    try:
        with open(font_path, 'rb') as f:
            data = f.read()
        if len(data) < 12:
            return names
        num_tables = struct.unpack('>H', data[4:6])[0]
        name_table_offset = None
        for i in range(num_tables):
            entry = data[12 + i * 16 : 12 + (i + 1) * 16]
            if entry[0:4] == b'name':
                name_table_offset = struct.unpack('>I', entry[8:12])[0]
                break
        if name_table_offset is None or name_table_offset + 6 > len(data):
            return names
        _, count, string_offset = struct.unpack('>HHH', data[name_table_offset : name_table_offset + 6])
        record_offset = name_table_offset + 6
        storage_offset = name_table_offset + string_offset
        for i in range(count):
            rec = data[record_offset + i * 12 : record_offset + (i + 1) * 12]
            plat_id, _, _, name_id, length, str_off = struct.unpack('>HHHHHH', rec)
            if name_id in (1, 4, 6):
                str_bytes = data[storage_offset + str_off : storage_offset + str_off + length]
                try:
                    if plat_id in (0, 3):
                        decoded = str_bytes.decode('utf-16-be')
                    elif plat_id == 1:
                        decoded = str_bytes.decode('mac_roman', errors='ignore')
                    else:
                        decoded = str_bytes.decode('latin1', errors='ignore')
                    decoded = decoded.strip('\x00').strip()
                    if decoded and (name_id not in names or plat_id == 3):
                        names[name_id] = decoded
                except Exception:
                    pass
    except Exception as e:
        logger.warning("Ошибка парсинга TTF %s: %s", font_path, e)
    return names


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1380, 880)

        self.files_data = {}
        self._next_item_id = 0
        self.font_map = {}
        self._loading_css = False
        self._applying_theme = False
        self._update_worker = None
        self._fbc_worker = None
        self._fbc_setup_dlg = None
        self._fbc_ready_callback = None
        self._fbc_setup_interactive = False
        self.fbc_cmd = FBC_CMD
        self.fbc_version = FBC_DETECTED_VERSION or THIRD_PARTY_VERSION
        self._table_status_filter = "all"
        self.undo_stack = QUndoStack(self)
        self.undo_stack.canUndoChanged.connect(self._update_undo_redo_ui)
        self.undo_stack.canRedoChanged.connect(self._update_undo_redo_ui)
        self.undo_stack.undoTextChanged.connect(self._update_undo_redo_ui)
        self.undo_stack.redoTextChanged.connect(self._update_undo_redo_ui)

        self.app_settings = get_default_app_settings()
        self.load_app_settings()
        LOCALE.set_language(self.app_settings.get("language", ""))
        self.sync_settings_from_fbc_config()

        self.setup_menubar()
        self.register_all_fonts()
        self.create_widgets()
        self._update_undo_redo_ui()

        if os.path.exists(CSS_PATH):
            self.load_and_parse_css_to_gui()
        else:
            self.save_visual_css(show_alert=False)

        self.apply_theme(self.app_settings["theme"])

        # Подписка на смену системной темы ОС (для режима "Авто")
        app_inst = QApplication.instance()
        if app_inst and hasattr(app_inst.styleHints(), "colorSchemeChanged"):
            try:
                app_inst.styleHints().colorSchemeChanged.connect(self._on_system_appearance_changed)
            except Exception:
                pass

        self.setAcceptDrops(True)
        self._setup_shortcuts()
        self.refresh_preview()
        QTimer.singleShot(150, self._ensure_fbc_on_startup)
        QTimer.singleShot(1500, self._schedule_startup_update_check)

    def _setup_shortcuts(self):
        self._sc_open = QShortcut(QKeySequence.StandardKey.Open, self)
        self._sc_open.activated.connect(self.load_files)
        self._sc_find = QShortcut(QKeySequence.StandardKey.Find, self)
        self._sc_find.activated.connect(self.focus_table_search)
        self._sc_convert_all = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._sc_convert_all.activated.connect(self.convert_all)
        self._sc_convert_sel = QShortcut(QKeySequence("Ctrl+Shift+Return"), self)
        self._sc_convert_sel.activated.connect(self.convert_selected)

    def closeEvent(self, event):
        self.save_app_settings()
        super().closeEvent(event)

    def _on_system_appearance_changed(self, *args):
        if getattr(self, "_applying_theme", False):
            return
        self.apply_theme(self.app_settings.get("theme", "Modern"), save=False)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            if not getattr(self, "_applying_theme", False):
                self.apply_theme(self.app_settings.get("theme", "Modern"), save=False)

    def load_app_settings(self):
        load_settings_file(SETTINGS_PATH, self.app_settings)

    def save_app_settings(self):
        save_settings_file(SETTINGS_PATH, self.app_settings)

    def sync_settings_from_fbc_config(self):
        sync_fbc_config(FBC_CONFIG, self.app_settings)

    def update_fbc_config_file(self):
        write_fbc_config(FBC_CONFIG, CSS_PATH, self.app_settings)

    def on_header_day_night_toggled(self, mode):
        """Переключение режима оформления (auto / light / dark) из верхнего переключателя."""
        m = str(mode).lower()
        self.app_settings["theme_mode"] = m if m in ("auto", "light", "dark") else "auto"
        family = self.app_settings.get("theme_family", "Modern")
        if family not in ("Golden", "Modern"):
            family = "Modern"
        self.app_settings["theme_family"] = family
        self.app_settings["theme"] = family
        self.apply_theme(family, save=True, animate=True)

    def apply_theme(self, theme_choice, save=True, animate=False):
        if getattr(self, "_applying_theme", False):
            return
        self._applying_theme = True
        try:
            mapped_choice = LEGACY_THEME_MAP.get(theme_choice, theme_choice)
            if mapped_choice in ("Auto", "Авто"):
                self.app_settings["theme_mode"] = "auto"
                mapped_choice = self.app_settings.get("theme_family", "Modern")

            valid_keys = {val for _, val in get_theme_choices()}
            if mapped_choice not in valid_keys:
                mapped_choice = "Modern"

            self.app_settings["theme"] = mapped_choice
            self.app_settings["theme_family"] = mapped_choice
            family = mapped_choice

            mode_setting = str(self.app_settings.get("theme_mode", "auto")).lower()
            if mode_setting not in ("auto", "light", "dark"):
                mode_setting = "auto"
                self.app_settings["theme_mode"] = "auto"

            if save:
                self.save_app_settings()

            if hasattr(self, "theme_selector") and self.theme_selector.get() != mapped_choice:
                self.theme_selector.set(mapped_choice)

            eff_family, eff_mode = resolve_theme_family_and_mode(
                mapped_choice,
                family,
                mode_setting
            )

            if hasattr(self, "theme_toggle"):
                self.theme_toggle.set_mode(mode_setting)

            qss = build_theme_qss(
                mapped_choice,
                eff_family,
                mode_setting
            )
            pal = build_qpalette_from_qss(qss, eff_mode)

            if animate and self.isVisible():
                start_window_crossfade(self)

            app_inst = QApplication.instance()
            if app_inst:
                app_inst.setPalette(pal)
                app_inst.setStyleSheet(qss)
            self.setPalette(pal)
            self.setStyleSheet(qss)
            self._current_qss = qss
            self._current_eff_mode = eff_mode
            refresh_widget_halos(self, qss, eff_mode)
        finally:
            self._applying_theme = False

    def _refresh_halos(self):
        refresh_widget_halos(
            self,
            getattr(self, "_current_qss", ""),
            getattr(self, "_current_eff_mode", "dark")
        )

    def setup_menubar(self):
        menubar = self.menuBar()
        menubar.clear()
        edit_menu = menubar.addMenu(tr("menu.edit"))
        if hasattr(self, "undo_stack"):
            act_undo = self.undo_stack.createUndoAction(self, tr("menu.undo"))
            act_undo.setShortcuts(QKeySequence.StandardKey.Undo)
            edit_menu.addAction(act_undo)
            act_redo = self.undo_stack.createRedoAction(self, tr("menu.redo"))
            act_redo.setShortcuts(QKeySequence.StandardKey.Redo)
            edit_menu.addAction(act_redo)
        help_menu = menubar.addMenu(tr("menu.help"))
        act_about = help_menu.addAction(tr("menu.about", app=APP_NAME))
        act_about.triggered.connect(lambda: self.switch_page(4))

    def apply_language(self, lang_code, save=True):
        if getattr(self, "_applying_language", False):
            return
        self._applying_language = True
        try:
            LOCALE.set_language(lang_code)
            self.app_settings["language"] = LOCALE.lang_code
            if save:
                self.save_app_settings()

            cur_page = self.pages.currentIndex() if hasattr(self, "pages") else 0
            search_query = self.search_edit.text() if hasattr(self, "search_edit") else ""
            selected_id = None
            if hasattr(self, "table"):
                sel_rows = self.table.selectionModel().selectedRows()
                if sel_rows:
                    it = self.table.item(sel_rows[0].row(), 0)
                    if it:
                        selected_id = it.data(Qt.ItemDataRole.UserRole)

            self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
            self.setup_menubar()
            self.create_widgets()
            self._update_undo_redo_ui()
            if search_query and hasattr(self, "search_edit"):
                self.search_edit.blockSignals(True)
                self.search_edit.setText(search_query)
                self.search_edit.blockSignals(False)
            self._repopulate_table_from_files_data(selected_id)
            self.load_and_parse_css_to_gui()
            self.apply_theme(self.app_settings.get("theme", "Modern"), save=False)
            self.switch_page(cur_page)
            self.refresh_preview()
        finally:
            self._applying_language = False

    def _repopulate_table_from_files_data(self, selected_id=None):
        if not hasattr(self, "table"):
            return
        self._updating_table_items = True
        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        try:
            self.table.setRowCount(0)
            sel_row = -1
            for item_id, data in self.files_data.items():
                data["item_id"] = item_id
                row = self.table.rowCount()
                self.table.insertRow(row)
                meta = data["meta"]
                it_file = QTableWidgetItem(data.get("display_name") or os.path.basename(data["path"]))
                it_file.setData(Qt.ItemDataRole.UserRole, item_id)
                it_file.setFlags(it_file.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 0, it_file)
                self.table.setItem(row, 1, QTableWidgetItem(meta["last"]))
                self.table.setItem(row, 2, QTableWidgetItem(meta["first"]))
                self.table.setItem(row, 3, QTableWidgetItem(meta["mid"]))
                self.table.setItem(row, 4, QTableWidgetItem(meta["series"]))
                self.table.setItem(row, 5, QTableWidgetItem(meta["num"]))
                self.table.setItem(row, 6, QTableWidgetItem(meta["title"]))
                it_target = QTableWidgetItem(self.simulate_fbc_target(meta))
                it_target.setFlags(it_target.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 7, it_target)
                self.table.setItem(row, 8, self._make_status_item(data.get("status", ""), data.get("status_error", "")))
                if item_id == selected_id:
                    sel_row = row
            if sel_row >= 0:
                self.table.selectRow(sel_row)
            elif self.table.rowCount() > 0:
                self.table.selectRow(0)
        finally:
            self.table.setSortingEnabled(was_sorting)
            self._updating_table_items = False
        self.apply_table_filter()
        self.update_header_status()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p = url.toLocalFile()
                if p and (os.path.isdir(p) or p.lower().endswith(('.fb2', '.zip'))):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event: QDropEvent):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        self.process_files(paths)

    def register_all_fonts(self):
        if not os.path.exists(FONTS_DIR):
            return
        for f in os.listdir(FONTS_DIR):
            if f.lower().endswith(('.ttf', '.otf', '.woff', '.woff2')):
                full_path = os.path.join(FONTS_DIR, f)
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
        if os.path.exists(FONTS_DIR):
            for f in sorted(os.listdir(FONTS_DIR)):
                if f.lower().endswith(('.ttf', '.otf', '.woff', '.woff2')):
                    fonts.append(f)
        return fonts or ["PT-Astra-Serif_Regular.ttf", "PomorskyUnicode.otf"]

    def create_widgets(self):
        central = QWidget()
        central.setObjectName("MainContainer")
        central.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(28, 22, 28, 22)
        root_layout.setSpacing(18)

        header_layout = QGridLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setColumnStretch(0, 1)
        header_layout.setColumnStretch(1, 0)
        header_layout.setColumnStretch(2, 1)
        header_layout.setColumnMinimumWidth(0, 440)
        header_layout.setColumnMinimumWidth(2, 440)

        title_widget = QWidget()
        title_box = QVBoxLayout(title_widget)
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)

        self.lbl_app_title = QLabel(APP_NAME)
        self.lbl_app_title.setObjectName("AppTitle")
        title_box.addWidget(self.lbl_app_title)

        self.lbl_status_sub = QLabel(self._get_status_text())
        self.lbl_status_sub.setObjectName("AppSubtitle")
        title_box.addWidget(self.lbl_status_sub)

        header_layout.addWidget(title_widget, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.theme_toggle = ThemeToggleWidget(callback=self.on_header_day_night_toggled)
        header_layout.addWidget(self.theme_toggle, 0, 1, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)

        nav_frame = QFrame()
        nav_frame.setObjectName("NavContainer")
        nav_layout = QHBoxLayout(nav_frame)
        nav_layout.setContentsMargins(4, 3, 4, 3)
        nav_layout.setSpacing(2)

        nav_items = [
            (tr("nav.converter"), 0),
            (tr("nav.styles"), 1),
            (tr("nav.preview"), 2),
            (tr("nav.settings"), 3),
            (tr("nav.about"), 4)
        ]
        self.nav_buttons = {}
        for text, idx in nav_items:
            btn = QPushButton(text)
            btn.setProperty("nav", True)
            btn.setProperty("active", idx == 0)
            btn.setObjectName("NavPillActive" if idx == 0 else "NavPill")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            nav_layout.addWidget(btn)
            self.nav_buttons[idx] = btn
            btn.clicked.connect(lambda checked=False, i=idx: self.switch_page(i))

        header_layout.addWidget(nav_frame, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        root_layout.addLayout(header_layout)

        self.pages = QStackedWidget()
        root_layout.addWidget(self.pages, 1)

        self.page_converter = QWidget()
        self.create_converter_page(self.page_converter)
        self.pages.addWidget(self.page_converter)

        self.page_css = QWidget()
        self.create_visual_css_page(self.page_css)
        self.pages.addWidget(self.page_css)

        self.page_preview = QWidget()
        self.create_preview_page(self.page_preview)
        self.pages.addWidget(self.page_preview)

        self.page_settings = QWidget()
        self.create_settings_page(self.page_settings)
        self.pages.addWidget(self.page_settings)

        self.page_about = QWidget()
        self.create_about_page(self.page_about)
        self.pages.addWidget(self.page_about)
        self.update_convert_button_text()

    def _get_status_text(self):
        cnt = len(self.files_data)
        fmt = self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT).upper()
        save_txt = tr("status.source_folder") if self.app_settings.get("save_mode") == "source" else tr("status.custom_folder")
        ver_txt = getattr(self, "fbc_version", THIRD_PARTY_VERSION) or THIRD_PARTY_VERSION
        return tr("status.summary", cnt=cnt, fmt=fmt, save=save_txt, ver=ver_txt)

    def update_header_status(self):
        if hasattr(self, 'lbl_status_sub'):
            self.lbl_status_sub.setText(self._get_status_text())

    def switch_page(self, idx):
        for i, btn in self.nav_buttons.items():
            is_active = (i == idx)
            btn.setProperty("active", is_active)
            btn.setObjectName("NavPillActive" if is_active else "NavPill")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()
        self.pages.setCurrentIndex(idx)
        if idx == 2:
            self.refresh_preview()

    def create_converter_page(self, parent):
        build_converter_page(self, parent)

    def _populate_data_combo(self, cb, options, default_val=None):
        cb.clear()
        for label, val in options:
            cb.addItem(label, val)
        if default_val is not None:
            idx = cb.findData(default_val)
            if idx >= 0:
                cb.setCurrentIndex(idx)

    def _set_combo_by_data(self, cb, val, legacy_map=None):
        if not val:
            return
        s_val = str(val).strip()
        if legacy_map and s_val in legacy_map:
            s_val = legacy_map[s_val]
        idx = cb.findData(s_val)
        if idx >= 0:
            cb.setCurrentIndex(idx)
        else:
            cb.setCurrentText(s_val)

    def _get_combo_data(self, cb, default=""):
        data = cb.currentData()
        return data if data is not None else (cb.currentText() or default)

    def create_visual_css_page(self, parent):
        build_visual_css_page(self, parent)

    def create_preview_page(self, parent):
        build_preview_page(self, parent)

    def create_settings_page(self, parent):
        build_settings_page(self, parent)

    def _update_preset_buttons_state(self):
        if not hasattr(self, "user_preset_combo"):
            return
        item = self.user_preset_combo.currentData()
        has_item = isinstance(item, dict) and bool(item.get("path"))
        has_builtin = False
        if has_item:
            has_builtin = bool(
                find_builtin_preset_path(
                    BUNDLED_PRESETS_DIR,
                    name=item.get("name"),
                    filename=item.get("filename"),
                )
            )
        if hasattr(self, "btn_preset_apply"):
            self.btn_preset_apply.setEnabled(has_item)
        if hasattr(self, "btn_preset_delete"):
            self.btn_preset_delete.setEnabled(has_item)
        if hasattr(self, "btn_preset_restore"):
            self.btn_preset_restore.setEnabled(has_builtin)

    def refresh_user_presets_combo(self, selected_name=None):
        if not hasattr(self, "user_preset_combo"):
            return
        cb = self.user_preset_combo
        prev_name = selected_name
        if prev_name is None:
            prev_name = self.app_settings.get("active_user_preset", "") or None
        if prev_name is None and cb.currentIndex() >= 0:
            cur_data = cb.currentData()
            if isinstance(cur_data, dict):
                prev_name = cur_data.get("name")

        cb.blockSignals(True)
        cb.clear()
        presets = list_user_presets(PRESETS_DIR)
        if not presets:
            cb.addItem(tr("settings.preset_none"), None)
        else:
            target_idx = 0
            for idx, item in enumerate(presets):
                cb.addItem(item["name"], item)
                if prev_name and item["name"] == prev_name:
                    target_idx = idx
            cb.setCurrentIndex(target_idx)
        cb.blockSignals(False)
        self._update_preset_buttons_state()

    def _current_preset_css_and_settings(self):
        if hasattr(self, "_get_css_ui_state"):
            self.app_settings["css_ui_state"] = self._get_css_ui_state()
        css_content = ""
        if hasattr(self, "generate_css_content"):
            css_content = self.generate_css_content()
        elif os.path.isfile(CSS_PATH):
            with open(CSS_PATH, "r", encoding="utf-8") as f:
                css_content = f.read()
        return self.app_settings, css_content

    def _apply_preset_payload(self, payload, selected_name=None):
        preset_settings = payload.get("settings") or {}
        has_css_ui_state = isinstance(preset_settings.get("css_ui_state"), dict) and bool(preset_settings.get("css_ui_state"))
        apply_preset_to_settings(self.app_settings, payload)
        active_name = selected_name or payload.get("name") or ""
        self.app_settings["active_user_preset"] = active_name

        css_content = payload.get("css_content") or ""
        if css_content:
            with open(CSS_PATH, "w", encoding="utf-8") as f:
                f.write(css_content)
            if not has_css_ui_state:
                self.app_settings.pop("css_ui_state", None)
        elif has_css_ui_state:
            merged_css_state = {**get_default_css_ui_state(), **preset_settings["css_ui_state"]}
            with open(CSS_PATH, "w", encoding="utf-8") as f:
                f.write(build_css_content(merged_css_state, FONTS_DIR))

        self.save_app_settings()
        self.update_fbc_config_file()

        cur_page = self.pages.currentIndex() if hasattr(self, "pages") else 3
        search_query = self.search_edit.text() if hasattr(self, "search_edit") else ""
        selected_id = None
        if hasattr(self, "table"):
            sel_rows = self.table.selectionModel().selectedRows()
            if sel_rows:
                it = self.table.item(sel_rows[0].row(), 0)
                if it:
                    selected_id = it.data(Qt.ItemDataRole.UserRole)

        self.create_widgets()
        self._update_undo_redo_ui()
        if search_query and hasattr(self, "search_edit"):
            self.search_edit.blockSignals(True)
            self.search_edit.setText(search_query)
            self.search_edit.blockSignals(False)
        self._repopulate_table_from_files_data(selected_id)
        self.load_and_parse_css_to_gui()
        self.save_visual_css(show_alert=False)
        self.apply_theme(self.app_settings.get("theme", "Modern"), save=False)
        self.refresh_user_presets_combo(selected_name=active_name)
        self.switch_page(cur_page)
        self.refresh_preview()

    def save_user_preset_clicked(self):
        default_name = ""
        if hasattr(self, "user_preset_combo") and isinstance(self.user_preset_combo.currentData(), dict):
            default_name = self.user_preset_combo.currentData().get("name", "")
        if not default_name:
            fmt = self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT).upper()
            prof = self.app_settings.get("device_profile", "custom")
            default_name = f"{prof.capitalize()} {fmt}" if prof != "custom" else f"My {fmt} Preset"

        name, ok = QInputDialog.getText(
            self,
            tr("settings.dlg_preset_save_title"),
            tr("settings.dlg_preset_save_prompt"),
            text=default_name,
        )
        name = (name or "").strip()
        if not ok or not name:
            return
        try:
            settings, css_content = self._current_preset_css_and_settings()
            save_user_preset_file(PRESETS_DIR, name, settings, css_content)
            self.app_settings["active_user_preset"] = name
            self.save_app_settings()
            self.refresh_user_presets_combo(selected_name=name)
            logger.info("Сохранён пользовательский пресет: %s", name)
            show_themed_message(self, tr("common.success"), tr("settings.msg_preset_saved", name=name), "info")
        except Exception as e:
            logger.error("Ошибка сохранения пресета %s: %s", name, e)
            show_themed_message(self, tr("common.error"), tr("settings.err_preset_io", e=e), "error")

    def apply_user_preset_clicked(self):
        if not hasattr(self, "user_preset_combo"):
            return
        item = self.user_preset_combo.currentData()
        if not isinstance(item, dict) or not item.get("path"):
            return
        try:
            payload = load_preset_file(item["path"])
            self._apply_preset_payload(payload, selected_name=payload["name"])
            logger.info("Применён пользовательский пресет: %s", payload["name"])
            show_themed_message(self, tr("common.success"), tr("settings.msg_preset_applied", name=payload["name"]), "info")
        except Exception as e:
            logger.error("Ошибка применения пресета %s: %s", item.get("path"), e)
            show_themed_message(self, tr("common.error"), tr("settings.err_preset_io", e=e), "error")

    def delete_user_preset_clicked(self):
        if not hasattr(self, "user_preset_combo"):
            return
        item = self.user_preset_combo.currentData()
        if not isinstance(item, dict) or not item.get("path"):
            return
        try:
            delete_user_preset_file(item["path"])
            name = item.get("name", "")
            if self.app_settings.get("active_user_preset") == name:
                self.app_settings["active_user_preset"] = ""
                self.save_app_settings()
            self.refresh_user_presets_combo()
            logger.info("Удалён пользовательский пресет: %s", name)
            show_themed_message(self, tr("common.info"), tr("settings.msg_preset_deleted", name=name), "info")
        except Exception as e:
            logger.error("Ошибка удаления пресета: %s", e)
            show_themed_message(self, tr("common.error"), tr("settings.err_preset_io", e=e), "error")

    def restore_user_preset_clicked(self):
        if not hasattr(self, "user_preset_combo"):
            return
        item = self.user_preset_combo.currentData()
        if not isinstance(item, dict):
            return
        try:
            name, _, payload = restore_builtin_preset(
                PRESETS_DIR,
                BUNDLED_PRESETS_DIR,
                name=item.get("name"),
                filename=item.get("filename"),
            )
            self._apply_preset_payload(payload, selected_name=name)
            logger.info("Восстановлен встроенный пресет по умолчанию: %s", name)
            show_themed_message(self, tr("common.success"), tr("settings.msg_preset_restored", name=name), "info")
        except Exception as e:
            logger.error("Ошибка восстановления пресета: %s", e)
            show_themed_message(self, tr("common.error"), tr("settings.err_preset_io", e=e), "error")

    def export_user_preset_clicked(self):
        preset_name = ""
        if hasattr(self, "user_preset_combo") and isinstance(self.user_preset_combo.currentData(), dict):
            preset_name = self.user_preset_combo.currentData().get("name", "")
        if not preset_name:
            preset_name = f"fbc_{self.app_settings.get('output_format', DEFAULT_OUTPUT_FORMAT)}"

        suggested = os.path.join(
            os.path.expanduser("~"),
            slugify_preset_name(preset_name) + PRESET_FILE_EXT,
        )
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("settings.dlg_preset_export_title"),
            suggested,
            tr("settings.filter_preset_files"),
        )
        if not out_path:
            return
        try:
            settings, css_content = self._current_preset_css_and_settings()
            final_path = export_preset_to_file(out_path, preset_name, settings, css_content)
            logger.info("Экспортирован пресет в %s", final_path)
            show_themed_message(self, tr("common.success"), tr("settings.msg_preset_exported", path=final_path), "info")
        except Exception as e:
            logger.error("Ошибка экспорта пресета: %s", e)
            show_themed_message(self, tr("common.error"), tr("settings.err_preset_io", e=e), "error")

    def import_user_preset_clicked(self):
        in_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("settings.dlg_preset_import_title"),
            os.path.expanduser("~"),
            tr("settings.filter_preset_files"),
        )
        if not in_path:
            return
        try:
            name, _, payload = import_preset_from_file(in_path, PRESETS_DIR)
            self._apply_preset_payload(payload, selected_name=name)
            logger.info("Импортирован и применён пресет: %s", name)
            show_themed_message(self, tr("common.success"), tr("settings.msg_preset_imported", name=name), "info")
        except Exception as e:
            logger.error("Ошибка импорта пресета %s: %s", in_path, e)
            show_themed_message(self, tr("common.error"), tr("settings.err_preset_io", e=e), "error")

    def _refresh_all_target_filenames(self):
        if not hasattr(self, "table"):
            return
        self._updating_table_items = True
        try:
            for item_id, data in self.files_data.items():
                for r in range(self.table.rowCount()):
                    it = self.table.item(r, 0)
                    if it and it.data(Qt.ItemDataRole.UserRole) == item_id:
                        it_target = QTableWidgetItem(self.simulate_fbc_target(data['meta']))
                        it_target.setFlags(it_target.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.table.setItem(r, 7, it_target)
                        break
        finally:
            self._updating_table_items = False

    def _refresh_filename_builder_preview(self):
        sample_meta = next(iter(self.files_data.values()))["meta"] if self.files_data else None
        out_fmt = self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT)
        if hasattr(self, "filename_builder"):
            self.filename_builder.set_context(output_format=out_fmt, sample_meta=sample_meta)
        if hasattr(self, "title_template_builder"):
            self.title_template_builder.set_context(output_format=out_fmt, sample_meta=sample_meta)

    def _set_device_profile_combo(self, profile_key):
        if hasattr(self, "device_profile_combo"):
            idx = self.device_profile_combo.findData(profile_key)
            if idx >= 0 and self.device_profile_combo.currentIndex() != idx:
                self.device_profile_combo.blockSignals(True)
                self.device_profile_combo.setCurrentIndex(idx)
                self.device_profile_combo.blockSignals(False)

    def on_format_changed(self, fmt_val):
        if not fmt_val:
            return
        self.app_settings["output_format"] = fmt_val
        if not getattr(self, "_applying_device_profile", False):
            cur_prof = self.app_settings.get("device_profile", "custom")
            preset = DEVICE_PROFILES.get(cur_prof)
            if preset and preset.get("output_format") != fmt_val:
                self.app_settings["device_profile"] = "custom"
                self._set_device_profile_combo("custom")
        self.save_app_settings()
        self.update_header_status()
        if hasattr(self, "format_selector") and self.format_selector.get() != fmt_val:
            self.format_selector.set(fmt_val)
        if hasattr(self, "format_combo"):
            idx = self.format_combo.findData(fmt_val)
            if idx >= 0 and self.format_combo.currentIndex() != idx:
                self.format_combo.blockSignals(True)
                self.format_combo.setCurrentIndex(idx)
                self.format_combo.blockSignals(False)
        self._refresh_all_target_filenames()
        self._refresh_filename_builder_preview()

    def on_device_profile_changed(self, profile_key):
        key = str(profile_key or "custom").strip().lower()
        self.app_settings["device_profile"] = key
        self._set_device_profile_combo(key)
        preset = DEVICE_PROFILES.get(key)
        if not preset:
            self.save_app_settings()
            return

        self._applying_device_profile = True
        try:
            for k, v in preset.items():
                self.app_settings[k] = str(v)

            fmt_val = preset.get("output_format")
            if fmt_val:
                if hasattr(self, "format_selector"):
                    self.format_selector.set(fmt_val)
                if hasattr(self, "format_combo"):
                    idx = self.format_combo.findData(fmt_val)
                    if idx >= 0:
                        self.format_combo.blockSignals(True)
                        self.format_combo.setCurrentIndex(idx)
                        self.format_combo.blockSignals(False)

            for attr, skey in (
                ("screen_w_edit", "screen_width"),
                ("screen_h_edit", "screen_height"),
                ("screen_dpi_edit", "screen_dpi"),
            ):
                if skey in preset and hasattr(self, attr):
                    ed = getattr(self, attr)
                    ed.blockSignals(True)
                    ed.setText(str(preset[skey]))
                    ed.blockSignals(False)

            selector_sync = [
                ("footnotes_mode_selector", "footnotes_mode"),
                ("rem_trans_selector", "remove_transparency"),
                ("rasterize_svg_selector", "rasterize_svg"),
                ("kfx_comp_selector", "kfx_compression"),
                ("optimize_img_selector", "optimize_images"),
            ]
            for attr, skey in selector_sync:
                if skey in preset and hasattr(self, attr):
                    getattr(self, attr).set(str(preset[skey]))

            for attr, skey in (
                ("grayscale_cb", "grayscale"),
                ("fit_to_screen_cb", "fit_to_screen"),
                ("cover_resize_cb", "cover_resize"),
            ):
                if skey in preset and hasattr(self, attr):
                    cb = getattr(self, attr)
                    cb.blockSignals(True)
                    self._set_combo_by_data(cb, str(preset[skey]))
                    cb.blockSignals(False)

            if "jpeg_quality_level" in preset and hasattr(self, "jpeg_qual_cb"):
                self.jpeg_qual_cb.blockSignals(True)
                self.jpeg_qual_cb.setCurrentText(str(preset["jpeg_quality_level"]))
                self.jpeg_qual_cb.blockSignals(False)

            self.save_app_settings()
            self.update_fbc_config_file()
            self.update_header_status()
            self._refresh_all_target_filenames()
            self._refresh_filename_builder_preview()
            self.refresh_preview()
            logger.info("Применён профиль устройства: %s", key)
        finally:
            self._applying_device_profile = False

    def on_screen_param_changed(self, key, val):
        digits = val.strip()
        if not digits.isdigit():
            return
        self.app_settings[key] = digits
        if not getattr(self, "_applying_device_profile", False):
            self.app_settings["device_profile"] = "custom"
            self._set_device_profile_combo("custom")
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_footnotes_mode_changed(self, val):
        self.app_settings["footnotes_mode"] = str(val or "float")
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_soft_hyphen_changed(self, val):
        self.app_settings["insert_soft_hyphen"] = str(val or "false")
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_dropcaps_enable_changed(self, val):
        self.app_settings["dropcaps_enable"] = str(val or "true")
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_fn_translit_changed(self, val):
        self.app_settings["file_name_transliterate"] = str(val or "false")
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_meta_translit_changed(self, val):
        self.app_settings["meta_transliterate"] = str(val or "false")
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_fbc_bool_setting_changed(self, key, val):
        self.app_settings[key] = str(val or "false")
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_toc_placement_changed(self, val):
        v = str(val or "after")
        self.app_settings["toc_page_placement"] = v if v in ("none", "before", "after") else "after"
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_filename_mode_changed(self, mode_val):
        mode = "custom" if mode_val == "custom" else "default"
        self.app_settings["filename_mode"] = mode
        self.save_app_settings()
        self.update_fbc_config_file()
        if hasattr(self, "filename_builder"):
            self.filename_builder.setVisible(mode == "custom")
        self._refresh_all_target_filenames()

    def on_filename_tokens_changed(self, tokens):
        self.app_settings["filename_tokens"] = tokens
        self.save_app_settings()
        self.update_fbc_config_file()
        self._refresh_all_target_filenames()

    def on_title_template_mode_changed(self, mode_val):
        mode = "custom" if mode_val == "custom" else "default"
        self.app_settings["title_template_mode"] = mode
        self.save_app_settings()
        self.update_fbc_config_file()
        if hasattr(self, "title_template_builder"):
            self.title_template_builder.setVisible(mode == "custom")

    def on_title_template_tokens_changed(self, tokens):
        self.app_settings["title_template_tokens"] = tokens
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_raster_format_changed(self, val):
        self.app_settings["raster_format"] = val
        self.save_app_settings()
        self.update_fbc_config_file()
        self.refresh_preview()

    def on_rasterize_svg_changed(self, val):
        self.app_settings["rasterize_svg"] = val
        self.save_app_settings()
        self.update_fbc_config_file()
        self.refresh_preview()

    def on_remove_transparency_changed(self, val):
        self.app_settings["remove_transparency"] = val
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_optimize_images_changed(self, val):
        self.app_settings["optimize_images"] = val
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_jpeg_quality_changed(self, val):
        if val:
            self.app_settings["jpeg_quality_level"] = val
            self.save_app_settings()
            self.update_fbc_config_file()

    def on_azw3_compression_changed(self, val):
        self.app_settings["azw3_compression"] = val
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_kfx_compression_changed(self, val):
        self.app_settings["kfx_compression"] = val
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_azw3_apnx_changed(self, val):
        self.app_settings["azw3_apnx"] = val
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_markdown_images_changed(self, val):
        self.app_settings["markdown_images"] = val
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_convert_workers_changed(self, val):
        self.app_settings["convert_workers"] = str(val or "auto")
        self.save_app_settings()

    def open_log_file(self):
        log_path = get_log_file_path() or LOG_PATH
        if log_path and os.path.isfile(log_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(log_path)))
        else:
            show_themed_message(self, tr("common.info"), tr("about.err_no_log", path=log_path), "info")

    def on_baseline_jpeg_changed(self, val):
        self.app_settings["baseline_jpeg"] = val
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_grayscale_changed(self, idx=None):
        val = self._get_combo_data(self.grayscale_cb, "none")
        self.app_settings["grayscale"] = val
        self.save_app_settings()
        self.update_fbc_config_file()
        self.refresh_preview()

    def on_fit_to_screen_changed(self, idx=None):
        val = self._get_combo_data(self.fit_to_screen_cb, "false")
        self.app_settings["fit_to_screen"] = val
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_cover_resize_changed(self, idx=None):
        val = self._get_combo_data(self.cover_resize_cb, "keepAR")
        self.app_settings["cover_resize"] = val
        self.save_app_settings()
        self.update_fbc_config_file()

    def on_save_mode_changed(self, mode_val):
        self.app_settings["save_mode"] = mode_val
        self.save_app_settings()
        self.btn_choose_dir.setEnabled(mode_val == "custom")
        self.update_header_status()

    def choose_custom_output_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            tr("settings.dlg_choose_dir"),
            self.app_settings.get("custom_output_dir", os.path.expanduser("~"))
        )
        if folder:
            self.app_settings["custom_output_dir"] = folder
            self.lbl_custom_dir.setText(folder)
            self.save_app_settings()

    def is_email_auto_send_ready(self):
        return check_email_auto_ready(self.app_settings)

    def update_convert_button_text(self):
        if not hasattr(self, "btn_convert"):
            return
        if self.is_email_auto_send_ready():
            self.btn_convert.setText(tr("converter.btn_convert_send"))
        else:
            self.btn_convert.setText(tr("converter.btn_convert"))

    def on_email_auto_changed(self, val):
        self.app_settings["email_auto_send"] = val
        self.save_app_settings()
        self.update_convert_button_text()

    def on_email_field_changed(self, key, val):
        self.app_settings[key] = val.strip() if key != "smtp_password" else val
        self.save_app_settings()
        self.update_convert_button_text()

    def send_converted_files_via_email(self, file_paths):
        send_email_attachments(self.app_settings, file_paths, APP_NAME, APP_VERSION)

    def send_test_email_clicked(self):
        if getattr(self, "_test_email_worker", None) is not None and self._test_email_worker.isRunning():
            return
        if not is_smtp_configured(self.app_settings):
            show_themed_message(self, tr("common.warning"), tr("settings.email_test_incomplete"), "warning")
            return
        if hasattr(self, "btn_test_email"):
            self.btn_test_email.setEnabled(False)
            self.btn_test_email.setText(tr("settings.btn_test_email_sending"))
        self._test_email_worker = TestEmailWorker(dict(self.app_settings), parent=self)
        self._test_email_worker.finished_test.connect(self._on_test_email_finished)
        self._test_email_worker.start()

    def _on_test_email_finished(self, ok, err_msg):
        if hasattr(self, "btn_test_email"):
            self.btn_test_email.setEnabled(True)
            self.btn_test_email.setText(tr("settings.btn_test_email"))
        if ok:
            recipient = self.app_settings.get("email_to", "").strip()
            logger.info("Тестовое письмо SMTP успешно отправлено на %s", recipient)
            show_themed_message(self, tr("common.success"), tr("settings.email_test_ok", email=recipient), "info")
        else:
            logger.error("Ошибка отправки тестового письма SMTP: %s", err_msg)
            show_themed_message(self, tr("converter.err_email_title"), tr("settings.email_test_err", e=err_msg), "error")

    def create_about_page(self, parent):
        build_about_page(
            self,
            parent,
            APP_NAME, APP_VERSION, APP_AUTHOR, APP_EMAIL, APP_URL,
            THIRD_PARTY_NAME, getattr(self, "fbc_version", THIRD_PARTY_VERSION) or THIRD_PARTY_VERSION, THIRD_PARTY_URL
        )

    def _ensure_fbc_on_startup(self, interactive=False, on_ready=None):
        if self._fbc_worker is not None and self._fbc_worker.isRunning():
            if on_ready is not None:
                self._fbc_ready_callback = on_ready
            return

        self._fbc_setup_interactive = bool(interactive)
        self._fbc_ready_callback = on_ready
        self._fbc_setup_dlg = None

        if interactive:
            self._open_fbc_setup_dialog(tr("fbc_setup.searching"))

        self._fbc_worker = FbcEnsureWorker(
            user_data_dir=BASE_DIR,
            target_version=FBC_TARGET_VERSION,
            allow_download=True,
            parent=self,
        )
        self._fbc_worker.status_changed.connect(self._on_fbc_status_changed)
        self._fbc_worker.progress_changed.connect(self._on_fbc_progress_changed)
        self._fbc_worker.finished_check.connect(self._on_fbc_check_finished)
        if self._fbc_setup_dlg is not None:
            self._fbc_setup_dlg.cancel_requested.connect(self._fbc_worker.cancel)
        self._fbc_worker.start()

    def _open_fbc_setup_dialog(self, status_text):
        if self._fbc_setup_dlg is None:
            self._fbc_setup_dlg = FbcSetupDialog(self, initial_status=status_text)
            if self._fbc_worker is not None:
                self._fbc_setup_dlg.cancel_requested.connect(self._fbc_worker.cancel)
            self._fbc_setup_dlg.open()
        else:
            self._fbc_setup_dlg.set_status_text(status_text)

    def _on_fbc_status_changed(self, status_code):
        if status_code == "searching":
            if self._fbc_setup_dlg is not None:
                self._fbc_setup_dlg.set_status_text(tr("fbc_setup.searching"))
        elif status_code == "verifying":
            if self._fbc_setup_dlg is not None:
                self._fbc_setup_dlg.set_status_text(tr("fbc_setup.verifying"))
        elif status_code.startswith("downloading:"):
            reason = status_code.split(":", 1)[1]
            reason_key = {
                "not_found": "fbc_setup.reason_not_found",
                "incompatible_version": "fbc_setup.reason_incompatible_version",
                "hash_mismatch": "fbc_setup.reason_hash_mismatch",
            }.get(reason, "fbc_setup.reason_default")
            self._open_fbc_setup_dialog(tr(reason_key, ver=FBC_TARGET_VERSION))

    def _on_fbc_progress_changed(self, downloaded, total, asset_name):
        if self._fbc_setup_dlg is None:
            self._open_fbc_setup_dialog(tr("fbc_setup.downloading_generic", name=asset_name))
        self._fbc_setup_dlg.update_download_progress(downloaded, total, asset_name)

    def _on_fbc_check_finished(self, result):
        global FBC_CMD
        dlg = self._fbc_setup_dlg
        self._fbc_setup_dlg = None
        if dlg is not None:
            dlg.finish_and_close()

        cb = self._fbc_ready_callback
        self._fbc_ready_callback = None

        if result.get("ok") and result.get("path"):
            FBC_CMD = result["path"]
            self.fbc_cmd = result["path"]
            if result.get("version"):
                self.fbc_version = result["version"]
                if hasattr(self, "lbl_third_party_ver"):
                    self.lbl_third_party_ver.setText(f"<b>{tr('about.third_party_ver', ver=self.fbc_version)}</b>")
            self.update_header_status()
            if result.get("downloaded") and not cb:
                logger.info("fb2cng v%s успешно установлен в %s", self.fbc_version, self.fbc_cmd)
            if cb is not None:
                QTimer.singleShot(0, cb)
            return

        if result.get("cancelled"):
            return

        err_text = result.get("error") or result.get("reason") or "unknown error"
        retry = show_update_dialog(
            self,
            tr("fbc_setup.err_title"),
            tr("fbc_setup.err_msg", e=err_text),
            tr("fbc_setup.btn_retry"),
            tr("fbc_setup.btn_skip"),
        )
        if retry:
            QTimer.singleShot(0, lambda c=cb: self._ensure_fbc_on_startup(interactive=True, on_ready=c))

    def _schedule_startup_update_check(self):
        last_check = float(self.app_settings.get("last_update_check", 0) or 0)
        if time.time() - last_check >= UPDATE_CHECK_INTERVAL_SEC:
            self.check_for_updates(manual=False)

    def check_for_updates(self, manual=False):
        if self._update_worker is not None and self._update_worker.isRunning():
            return
        if manual and hasattr(self, "btn_check_updates"):
            self.btn_check_updates.setEnabled(False)
            self.btn_check_updates.setText(tr("about.updates_checking"))

        clean_url = APP_URL.replace("https://", "").replace("http://", "").rstrip("/")
        base_url = f"https://{clean_url}"
        manifest_url = f"{base_url}/version.json"

        self._update_worker = UpdateCheckWorker(
            APP_VERSION,
            BUILD_NUMBER,
            manifest_url=manifest_url,
            manual=manual,
            lang=LOCALE.lang_code,
            fallback_url=base_url,
            parent=self,
        )
        self._update_worker.checked.connect(self._on_update_check_finished)
        self._update_worker.start()

    def _on_update_check_finished(self, result, manual):
        if hasattr(self, "btn_check_updates"):
            self.btn_check_updates.setEnabled(True)
            self.btn_check_updates.setText(tr("about.btn_check_updates"))

        if not result.get("error"):
            self.app_settings["last_update_check"] = int(time.time())
            self.save_app_settings()

        if result.get("error"):
            if manual:
                show_themed_message(self, tr("common.error"), tr("about.updates_err", e=result["error"]), "error")
            return

        if result.get("has_update"):
            changelog = result.get("changelog") or ""
            notes = f"\n\n{changelog}" if changelog else ""
            msg = tr(
                "about.update_avail_msg",
                app=APP_NAME,
                ver=result.get("version"),
                build=result.get("build"),
                cur_ver=APP_VERSION,
                cur_build=BUILD_NUMBER,
                notes=notes,
            )
            if show_update_dialog(
                self,
                tr("about.update_avail_title"),
                msg,
                tr("about.btn_download_update"),
                tr("about.btn_later"),
            ):
                dl_url = result.get("download_url") or f"https://{APP_URL}"
                webbrowser.open(dl_url)
        elif manual:
            show_themed_message(
                self,
                tr("common.info"),
                tr("about.updates_none", ver=APP_VERSION, build=BUILD_NUMBER),
                "info",
            )

    def on_style_param_changed(self, *args):
        if getattr(self, '_loading_css', False):
            return
        self.save_visual_css(show_alert=False)
        self.refresh_preview()

    def on_preview_mode_changed(self, mode):
        self.preview_source_mode = "sample" if mode == "sample" else "book"
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
            st, font_families, svg_mode, FONTS_DIR,
            APP_NAME, APP_VERSION,
            self.p_align_cb.currentText(), self.img_align_cb.currentText(),
            for_browser=for_browser,
            grayscale=(self.app_settings.get("grayscale", "none") == "luma"),
            book_preview=book_preview,
            dropcaps_enable=(str(self.app_settings.get("dropcaps_enable", "true")).lower() == "true"),
            use_web_engine=bool(getattr(self, "preview_is_webengine", False)),
        )

    def refresh_preview(self):
        if not hasattr(self, 'preview_browser'):
            return
        try:
            html = self._build_full_preview_html(for_browser=False)
            if hasattr(self.preview_browser, "set_preview_html"):
                self.preview_browser.set_preview_html(html, BASE_DIR)
            else:
                self.preview_browser.setHtml(html)
        except Exception as e:
            logger.warning("Ошибка превью: %s", e)

    def open_in_browser(self):
        self.save_visual_css(show_alert=False)
        preview_html_path = os.path.join(os.path.dirname(CSS_PATH), "preview.html")
        try:
            html = self._build_full_preview_html(for_browser=True)
            with open(preview_html_path, 'w', encoding='utf-8') as f:
                f.write(html)
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
            parsed = parse_css_file_to_state(CSS_PATH)
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
        return build_css_content(self._get_css_ui_state(), FONTS_DIR)

    def reset_visual_css(self, show_alert=False):
        """Сбрасывает ebook_styles.css к первоначальному виду, перезаписывает на диске и подгружает в интерфейс."""
        try:
            if (
                BUNDLED_CSS_PATH
                and os.path.abspath(BUNDLED_CSS_PATH) != os.path.abspath(CSS_PATH)
                and os.path.isfile(BUNDLED_CSS_PATH)
            ):
                with open(BUNDLED_CSS_PATH, 'r', encoding='utf-8') as src:
                    default_css = src.read()
            else:
                default_css = build_css_content(get_default_css_ui_state(), FONTS_DIR)

            with open(CSS_PATH, 'w', encoding='utf-8') as f:
                f.write(default_css)

            self.app_settings["css_ui_state"] = get_default_css_ui_state()
            self.load_and_parse_css_to_gui()
            self.save_app_settings()
            self.update_fbc_config_file()
            self.refresh_preview()
            logger.info("Стили CSS сброшены к первоначальному виду: %s", CSS_PATH)
            if show_alert:
                show_themed_message(self, tr("common.success"), tr("styles.msg_reset", path=CSS_PATH), "info")
            return True
        except Exception as e:
            logger.error("Ошибка сброса CSS: %s", e)
            show_themed_message(self, tr("common.error"), tr("styles.err_reset", e=e), "error")
            return False

    def save_visual_css(self, show_alert=False):
        try:
            css_content = self.generate_css_content()
            with open(CSS_PATH, 'w', encoding='utf-8') as f:
                f.write(css_content)
            if hasattr(self, '_get_css_ui_state'):
                self.app_settings["css_ui_state"] = self._get_css_ui_state()
                self.save_app_settings()
            if hasattr(self, 'css_preview_text'):
                self.css_preview_text.setPlainText(css_content)
            if show_alert:
                show_themed_message(self, tr("common.success"), tr("styles.msg_saved", path=CSS_PATH), "info")
            return True
        except Exception as e:
            show_themed_message(self, tr("common.error"), tr("styles.err_save", e=e), "error")
            return False


    def render_cover_preview(self, img_bytes, is_modified=False):
        if not img_bytes:
            self.cover_preview_lbl.setText(tr("converter.cover_missing"))
            self.cover_preview_lbl.setPixmap(QPixmap())
            self.cover_info_label.setText(tr("converter.cover_size_empty"))
            return

        pixmap = QPixmap()
        pixmap.loadFromData(img_bytes)
        scaled = pixmap.scaled(
            COVER_PREVIEW_SIZE[0], COVER_PREVIEW_SIZE[1],
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.cover_preview_lbl.setPixmap(scaled)
        status = tr("converter.cover_modified") if is_modified else ""
        self.cover_info_label.setText(tr("converter.cover_size", w=pixmap.width(), h=pixmap.height(), status=status))

    def _format_status_text(self, status_code):
        mapping = {
            "running": tr("converter.status_running"),
            "ok": tr("converter.status_ok"),
            "error": tr("converter.status_error"),
            "cancelled": tr("converter.status_cancelled"),
        }
        return mapping.get(status_code or "", "")

    def _make_status_item(self, status_code="", error_msg=""):
        it = QTableWidgetItem(self._format_status_text(status_code))
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if error_msg:
            it.setToolTip(str(error_msg))
        return it

    def _set_item_status(self, item_id, status_code, error_msg=""):
        data = self.files_data.get(item_id)
        if data is not None:
            data["status"] = status_code
            data["status_error"] = error_msg
        if not hasattr(self, "table"):
            return
        self._updating_table_items = True
        try:
            for r in range(self.table.rowCount()):
                it0 = self.table.item(r, 0)
                if it0 and it0.data(Qt.ItemDataRole.UserRole) == item_id:
                    self.table.setItem(r, 8, self._make_status_item(status_code, error_msg))
                    break
        finally:
            self._updating_table_items = False
        self.apply_table_filter()

    def focus_table_search(self):
        if hasattr(self, "pages") and self.pages.currentIndex() != 0:
            self.switch_page(0)
        if hasattr(self, "search_edit"):
            self.search_edit.setFocus()
            self.search_edit.selectAll()

    def on_table_filter_changed(self, _text=None):
        self.apply_table_filter()

    def on_status_filter_changed(self, val):
        self._table_status_filter = val if val in ("all", "pending", "ok", "error") else "all"
        self.apply_table_filter()

    def apply_table_filter(self):
        if not hasattr(self, "table"):
            return
        query = self.search_edit.text() if hasattr(self, "search_edit") else ""
        status_filter = getattr(self, "_table_status_filter", "all")
        total = self.table.rowCount()
        shown = 0
        for r in range(total):
            it0 = self.table.item(r, 0)
            if not it0:
                self.table.setRowHidden(r, False)
                shown += 1
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if data is None:
                self.table.setRowHidden(r, False)
                shown += 1
                continue
            it_target = self.table.item(r, 7)
            target_name = it_target.text() if it_target else ""
            visible = book_matches_filter(data, query=query, status_filter=status_filter, target_name=target_name)
            self.table.setRowHidden(r, not visible)
            if visible:
                shown += 1
        if hasattr(self, "lbl_filter_count"):
            self.lbl_filter_count.setText(tr("converter.filter_count", shown=shown, total=total))
        self._update_convert_selected_button()

    def _update_undo_redo_ui(self, *_args):
        stack = getattr(self, "undo_stack", None)
        if stack is None:
            return
        if hasattr(self, "btn_undo"):
            self.btn_undo.setEnabled(stack.canUndo())
            utxt = stack.undoText()
            self.btn_undo.setToolTip(
                f"{tr('converter.btn_undo')}: {utxt}" if utxt else tr("converter.btn_undo")
            )
        if hasattr(self, "btn_redo"):
            self.btn_redo.setEnabled(stack.canRedo())
            rtxt = stack.redoText()
            self.btn_redo.setToolTip(
                f"{tr('converter.btn_redo')}: {rtxt}" if rtxt else tr("converter.btn_redo")
            )

    def undo_last_action(self):
        if hasattr(self, "undo_stack") and self.undo_stack.canUndo():
            self.undo_stack.undo()

    def redo_last_action(self):
        if hasattr(self, "undo_stack") and self.undo_stack.canRedo():
            self.undo_stack.redo()

    def _populate_table_row(self, row, item_id, data):
        meta = data["meta"]
        it_file = QTableWidgetItem(data.get("display_name") or os.path.basename(data["path"]))
        it_file.setData(Qt.ItemDataRole.UserRole, item_id)
        it_file.setFlags(it_file.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, it_file)
        self.table.setItem(row, 1, QTableWidgetItem(meta.get("last", "")))
        self.table.setItem(row, 2, QTableWidgetItem(meta.get("first", "")))
        self.table.setItem(row, 3, QTableWidgetItem(meta.get("mid", "")))
        self.table.setItem(row, 4, QTableWidgetItem(meta.get("series", "")))
        self.table.setItem(row, 5, QTableWidgetItem(meta.get("num", "")))
        self.table.setItem(row, 6, QTableWidgetItem(meta.get("title", "")))
        it_target = QTableWidgetItem(self.simulate_fbc_target(meta))
        it_target.setFlags(it_target.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 7, it_target)
        self.table.setItem(row, 8, self._make_status_item(data.get("status", ""), data.get("status_error", "")))

    def _apply_book_snapshots(self, pairs):
        if not hasattr(self, "table"):
            return
        row_by_id = {}
        for r in range(self.table.rowCount()):
            it0 = self.table.item(r, 0)
            if it0:
                row_by_id[it0.data(Qt.ItemDataRole.UserRole)] = r

        col_keys = ["last", "first", "mid", "series", "num", "title"]
        self._updating_table_items = True
        try:
            for item_id, snap in pairs:
                data = self.files_data.get(item_id)
                if data is None:
                    continue
                new_meta = dict(snap["meta"])
                data["meta"] = new_meta
                data["cover_bytes"] = snap.get("cover_bytes")
                data["cover_mime"] = snap.get("cover_mime")
                data["cover_modified"] = bool(snap.get("cover_modified", False))
                r = row_by_id.get(item_id)
                if r is not None:
                    for idx_c, key in enumerate(col_keys, start=1):
                        cell = self.table.item(r, idx_c)
                        if cell is not None:
                            cell.setText(new_meta.get(key, ""))
                        else:
                            self.table.setItem(r, idx_c, QTableWidgetItem(new_meta.get(key, "")))
                    it_target = QTableWidgetItem(self.simulate_fbc_target(new_meta))
                    it_target.setFlags(it_target.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(r, 7, it_target)
        finally:
            self._updating_table_items = False
        self.apply_table_filter()
        self.on_table_selection_changed()
        self._refresh_filename_builder_preview()

    def _remove_items_by_ids(self, item_ids):
        if not hasattr(self, "table"):
            return
        drop = set(item_ids)
        first_removed_row = None
        self._updating_table_items = True
        try:
            for r in range(self.table.rowCount() - 1, -1, -1):
                it0 = self.table.item(r, 0)
                if it0 and it0.data(Qt.ItemDataRole.UserRole) in drop:
                    first_removed_row = r
                    self.table.removeRow(r)
            for iid in drop:
                self.files_data.pop(iid, None)
            if self.table.rowCount() > 0 and first_removed_row is not None:
                self.table.selectRow(min(first_removed_row, self.table.rowCount() - 1))
        finally:
            self._updating_table_items = False
        self.apply_table_filter()
        self.on_table_selection_changed()
        self.update_header_status()
        self._refresh_filename_builder_preview()

    def _restore_removed_items(self, removed_entries):
        if not hasattr(self, "table"):
            return
        self._updating_table_items = True
        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        try:
            restored_rows = []
            for row_idx, item_id, data in sorted(removed_entries, key=lambda x: x[0]):
                data["item_id"] = item_id
                self.files_data[item_id] = data
                pos = max(0, min(row_idx, self.table.rowCount()))
                self.table.insertRow(pos)
                self._populate_table_row(pos, item_id, data)
                restored_rows.append(pos)
            self.table.clearSelection()
            for r in restored_rows:
                self.table.selectRow(r)
        finally:
            self.table.setSortingEnabled(was_sorting)
            self._updating_table_items = False
        self.apply_table_filter()
        self.on_table_selection_changed()
        self.update_header_status()
        self._refresh_filename_builder_preview()

    def _apply_table_order(self, ordered_ids, selected_ids=None):
        if not hasattr(self, "table"):
            return
        selected_set = set(selected_ids or [])
        existing_order = [iid for iid in ordered_ids if iid in self.files_data]
        remaining = [iid for iid in self.files_data.keys() if iid not in existing_order]
        final_order = existing_order + remaining

        new_files_data = {iid: self.files_data[iid] for iid in final_order}
        self.files_data = new_files_data

        self._updating_table_items = True
        self.table.setSortingEnabled(False)
        try:
            self.table.setRowCount(0)
            selected_rows = []
            for iid in final_order:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self._populate_table_row(row, iid, self.files_data[iid])
                if iid in selected_set:
                    selected_rows.append(row)
            self.table.clearSelection()
            for r in selected_rows:
                self.table.selectRow(r)
        finally:
            self._updating_table_items = False
        self.apply_table_filter()
        self.on_table_selection_changed()

    def move_selected_rows(self, delta):
        """Перемещает выбранные строки таблицы вверх (delta=-1) или вниз (delta=+1)."""
        if not hasattr(self, "table") or delta == 0:
            return
        selected_rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if not selected_rows:
            return
        row_count = self.table.rowCount()
        if delta < 0 and selected_rows[0] <= 0:
            return
        if delta > 0 and selected_rows[-1] >= row_count - 1:
            return

        before_order = []
        for r in range(row_count):
            it0 = self.table.item(r, 0)
            if it0:
                before_order.append(it0.data(Qt.ItemDataRole.UserRole))
        if len(before_order) != row_count:
            return

        after_order = list(before_order)
        ordered = selected_rows if delta < 0 else list(reversed(selected_rows))
        selected_ids = [before_order[r] for r in selected_rows]
        for r in ordered:
            target = r + delta
            after_order[r], after_order[target] = after_order[target], after_order[r]

        if before_order != after_order:
            self.undo_stack.push(
                ReorderBooksCommand(
                    self,
                    before_order,
                    after_order,
                    selected_ids=selected_ids,
                    text=tr("converter.undo_move", count=len(selected_ids)),
                )
            )

    def eventFilter(self, obj, event):
        if obj is getattr(self, "search_edit", None) and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.search_edit.clear()
                if hasattr(self, "status_filter_selector"):
                    self.status_filter_selector.set("all")
                self.on_status_filter_changed("all")
                return True
        if obj is getattr(self, "table", None) and event.type() == QEvent.Type.KeyPress:
            if self.table.state() != QAbstractItemView.State.EditingState:
                if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    selected_rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
                    if selected_rows:
                        self.remove_book_rows(selected_rows)
                        return True
                if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                    if event.key() == Qt.Key.Key_Up:
                        self.move_selected_rows(-1)
                        return True
                    if event.key() == Qt.Key.Key_Down:
                        self.move_selected_rows(1)
                        return True
        return super().eventFilter(obj, event)

    def _update_convert_selected_button(self, selected_count=None):
        if not hasattr(self, "btn_convert_selected"):
            return
        if selected_count is None:
            if hasattr(self, "table"):
                selected_count = sum(
                    1 for idx in self.table.selectionModel().selectedRows()
                    if not self.table.isRowHidden(idx.row())
                )
            else:
                selected_count = 0
        self.btn_convert_selected.setEnabled(selected_count > 0)
        if selected_count > 0:
            self.btn_convert_selected.setText(tr("converter.btn_convert_selected", count=selected_count))
        else:
            self.btn_convert_selected.setText(tr("converter.btn_convert_selected_empty"))

    def on_table_selection_changed(self):
        rows = [idx for idx in self.table.selectionModel().selectedRows() if not self.table.isRowHidden(idx.row())]
        self._update_convert_selected_button(len(rows))
        if not rows:
            self.btn_replace_cover.setEnabled(False)
            self.btn_reset_cover.setEnabled(False)
            self.render_cover_preview(None)
            return
        item_id = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        data = self.files_data.get(item_id)
        if data:
            self.btn_replace_cover.setEnabled(True)
            self.btn_reset_cover.setEnabled(data.get('cover_modified', False))
            self.render_cover_preview(data.get('cover_bytes'), data.get('cover_modified', False))

    def replace_selected_cover(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        item_id = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        data = self.files_data.get(item_id)
        if not data:
            return

        img_path, _ = QFileDialog.getOpenFileName(
            self, tr("converter.dlg_select_cover"), "", tr("converter.filter_images")
        )
        if img_path:
            try:
                fitted_bytes, mime_type = fit_image_to_cover_size(img_path)
                before = snapshot_book_state(data)
                after = {
                    **before,
                    "cover_bytes": fitted_bytes,
                    "cover_mime": mime_type,
                    "cover_modified": True,
                }
                self.undo_stack.push(
                    UpdateBooksCommand(
                        self,
                        [{"item_id": item_id, "before": before, "after": after}],
                        tr("converter.undo_cover"),
                    )
                )
            except Exception as e:
                show_themed_message(self, tr("common.error"), tr("converter.err_update_cover", e=e), "error")

    def reset_selected_cover(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        item_id = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        data = self.files_data.get(item_id)
        if not data:
            return
        before = snapshot_book_state(data)
        after = {
            **before,
            "cover_bytes": data.get("orig_cover_bytes"),
            "cover_mime": data.get("orig_cover_mime"),
            "cover_modified": False,
        }
        if before != after:
            self.undo_stack.push(
                UpdateBooksCommand(
                    self,
                    [{"item_id": item_id, "before": before, "after": after}],
                    tr("converter.undo_cover"),
                )
            )

    def on_table_double_click(self, item):
        if item is None or item.column() in (0, 7, 8):
            return
        self.table.editItem(item)

    def on_table_item_changed(self, item):
        if getattr(self, "_updating_table_items", False) or item is None:
            return
        row, col = item.row(), item.column()
        if col in (0, 7, 8):
            return
        it0 = self.table.item(row, 0)
        if not it0:
            return
        item_id = it0.data(Qt.ItemDataRole.UserRole)
        data = self.files_data.get(item_id)
        if not data:
            return

        col_names = ["file", "last", "first", "mid", "series", "num", "title", "target", "status"]
        col_key = col_names[col]
        new_val = item.text().strip()
        old_val = data["meta"].get(col_key, "")

        if old_val == new_val:
            if item.text() != new_val:
                self._updating_table_items = True
                try:
                    item.setText(new_val)
                finally:
                    self._updating_table_items = False
            return

        before = snapshot_book_state(data)
        after_meta = dict(before["meta"])
        after_meta[col_key] = new_val
        after = {**before, "meta": after_meta}
        cols_labels = tr("converter.columns")
        col_label = cols_labels[col] if isinstance(cols_labels, list) and col < len(cols_labels) else col_key
        self.undo_stack.push(
            UpdateBooksCommand(
                self,
                [{"item_id": item_id, "before": before, "after": after}],
                tr("converter.undo_edit_cell", col=col_label),
            )
        )

    def on_table_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        selected_rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if row not in selected_rows:
            self.table.selectRow(row)
            selected_rows = [row]

        menu = QMenu(self)
        if len(selected_rows) == 1:
            it0 = self.table.item(row, 0)
            if not it0:
                return
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            act_convert_sel = menu.addAction(tr("converter.ctx_convert_selected"))
            act_debug = menu.addAction(tr("converter.ctx_debug_convert"))
            menu.addSeparator()
            act_edit = menu.addAction(tr("converter.ctx_edit"))
            act_save_src = menu.addAction(tr("converter.ctx_save_source"))
            act_autonum = menu.addAction(tr("converter.ctx_autonumber_series", count=1))
            act_up = menu.addAction(tr("converter.ctx_move_up"))
            act_down = menu.addAction(tr("converter.ctx_move_down"))
            menu.addSeparator()
            act_delete = menu.addAction(tr("converter.ctx_delete"))
            chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
            if chosen == act_convert_sel:
                self.convert_selected()
            elif chosen == act_debug:
                self.convert_selected(debug=True)
            elif chosen == act_edit:
                self.edit_book_row(row, item_id)
            elif chosen == act_save_src:
                self.save_rows_to_source([row])
            elif chosen == act_autonum:
                self.autonumber_series_rows([row])
            elif chosen == act_up:
                self.move_selected_rows(-1)
            elif chosen == act_down:
                self.move_selected_rows(1)
            elif chosen == act_delete:
                self.remove_book_rows([row])
        else:
            cnt = len(selected_rows)
            act_convert_sel = menu.addAction(tr("converter.ctx_convert_selected_multi", count=cnt))
            act_debug = menu.addAction(tr("converter.ctx_debug_convert"))
            menu.addSeparator()
            act_batch = menu.addAction(tr("converter.ctx_batch_edit", count=cnt))
            act_save_src = menu.addAction(tr("converter.ctx_save_source_multi", count=cnt))
            act_autonum = menu.addAction(tr("converter.ctx_autonumber_series", count=cnt))
            act_up = menu.addAction(tr("converter.ctx_move_up"))
            act_down = menu.addAction(tr("converter.ctx_move_down"))
            menu.addSeparator()
            act_delete = menu.addAction(tr("converter.ctx_delete_selected", count=cnt))
            chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
            if chosen == act_convert_sel:
                self.convert_selected()
            elif chosen == act_debug:
                self.convert_selected(debug=True)
            elif chosen == act_batch:
                self.batch_edit_rows(selected_rows)
            elif chosen == act_save_src:
                self.save_rows_to_source(selected_rows)
            elif chosen == act_autonum:
                self.autonumber_series_rows(selected_rows)
            elif chosen == act_up:
                self.move_selected_rows(-1)
            elif chosen == act_down:
                self.move_selected_rows(1)
            elif chosen == act_delete:
                self.remove_book_rows(selected_rows)

    def save_rows_to_source(self, rows):
        """Сохраняет текущие метаданные и обложки выбранных строк обратно в исходные .fb2/.zip файлы."""
        if not rows:
            return
        saved_count = 0
        errors = []
        for r in sorted(rows):
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            data = self.files_data.get(it0.data(Qt.ItemDataRole.UserRole))
            if not data:
                continue
            try:
                save_book_changes_to_source(data)
                saved_count += 1
            except Exception as e:
                logger.error("Ошибка сохранения в исходный FB2 (%s): %s", data.get("display_name") or data.get("path"), e)
                errors.append(f"{data.get('display_name') or os.path.basename(data['path'])}: {e}")
        self.on_table_selection_changed()
        if errors:
            show_themed_message(self, tr("common.error"), tr("converter.err_save_source", e="\n".join(errors)), "error")
        elif saved_count > 0:
            show_themed_message(self, tr("common.success"), tr("converter.msg_save_source_ok", count=saved_count), "info")

    def edit_book_row(self, row, item_id):
        data = self.files_data.get(item_id)
        if not data:
            return
        output_format = self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT)
        dlg = BookEditDialog(
            self,
            data,
            output_format,
            filename_mode=self.app_settings.get("filename_mode", "default"),
            filename_tokens=self.app_settings.get("filename_tokens"),
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            before = snapshot_book_state(data)
            new_meta = dlg.get_meta()
            cover_bytes, cover_mime, cover_modified = dlg.get_cover_state()
            after = {
                "meta": dict(new_meta),
                "cover_bytes": cover_bytes,
                "cover_mime": cover_mime,
                "cover_modified": bool(cover_modified),
            }
            if before != after:
                self.undo_stack.push(
                    UpdateBooksCommand(
                        self,
                        [{"item_id": item_id, "before": before, "after": after}],
                        tr("converter.undo_edit_book"),
                    )
                )

            if dlg.should_save_to_source():
                try:
                    save_book_changes_to_source(data)
                except Exception as e:
                    show_themed_message(self, tr("common.error"), tr("converter.err_save_source", e=e), "error")
            self.on_table_selection_changed()

    def batch_edit_rows(self, rows):
        if not rows:
            return
        common_meta = {}
        for key in ("last", "first", "mid", "series"):
            vals = set()
            for r in rows:
                it0 = self.table.item(r, 0)
                data = self.files_data.get(it0.data(Qt.ItemDataRole.UserRole)) if it0 else None
                if data:
                    vals.add(data["meta"].get(key, ""))
            common_meta[key] = next(iter(vals)) if len(vals) == 1 else ""

        dlg = BatchEditDialog(self, len(rows), common_meta)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updates = dlg.get_updates()
        if not updates:
            return

        changes = []
        for r in rows:
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if not data:
                continue
            before = snapshot_book_state(data)
            after_meta = dict(before["meta"])
            after_meta.update(updates)
            after = {**before, "meta": after_meta}
            if before != after:
                changes.append({"item_id": item_id, "before": before, "after": after})

        if changes:
            self.undo_stack.push(
                UpdateBooksCommand(
                    self,
                    changes,
                    tr("converter.undo_batch_edit", count=len(changes)),
                )
            )

    def autonumber_series_rows(self, rows):
        if not rows:
            return
        changes = []
        for seq_num, r in enumerate(sorted(rows), start=1):
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if not data:
                continue
            before = snapshot_book_state(data)
            after_meta = dict(before["meta"])
            after_meta["num"] = str(seq_num)
            after = {**before, "meta": after_meta}
            if before != after:
                changes.append({"item_id": item_id, "before": before, "after": after})

        if changes:
            self.undo_stack.push(
                UpdateBooksCommand(
                    self,
                    changes,
                    tr("converter.undo_autonumber", count=len(changes)),
                )
            )

    def remove_book_rows(self, rows):
        if not rows:
            return
        removed_entries = []
        for r in sorted(set(rows)):
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if data is not None:
                removed_entries.append((r, item_id, data))
        if removed_entries:
            self.undo_stack.push(
                RemoveBooksCommand(
                    self,
                    removed_entries,
                    tr("converter.undo_remove", count=len(removed_entries)),
                )
            )

    def simulate_fbc_target(self, meta):
        return simulate_fbc_target(
            meta,
            self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT),
            self.app_settings.get("filename_mode", "default"),
            self.app_settings.get("filename_tokens"),
        )


    def activate_and_import(self, filepaths):
        """Поднимает окно на передний план (при вызове из второго экземпляра) и загружает переданные файлы."""
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        if filepaths:
            self.enqueue_import_paths(filepaths)

    def enqueue_import_paths(self, filepaths):
        """Принимает файлы из ОС (QFileOpenEvent / sys.argv) и ставит их в очередь, если импорт уже идёт."""
        paths = [p for p in (filepaths or []) if p]
        if not paths:
            return
        if getattr(self, "_import_worker", None) is not None and self._import_worker.isRunning():
            queue = getattr(self, "_queued_import_paths", None)
            if queue is None:
                queue = []
                self._queued_import_paths = queue
            queue.extend(paths)
            return
        self.process_files(paths)

    def process_files(self, filepaths):
        if not filepaths:
            return
        if getattr(self, "_import_worker", None) is not None and self._import_worker.isRunning():
            self.enqueue_import_paths(filepaths)
            return

        existing_keys = {
            d.get('source_key') or os.path.abspath(d['path'])
            for d in self.files_data.values()
        }
        self._import_had_rows = (self.table.rowCount() > 0)
        self._import_progress_dlg = ImportProgressDialog(self)
        self._import_worker = FileImportWorker(list(filepaths), existing_keys, parent=self)
        self._import_worker.progress.connect(self._import_progress_dlg.update_progress)
        self._import_progress_dlg.cancel_requested.connect(self._import_worker.requestInterruption)
        self._import_worker.finished_import.connect(self._on_import_finished)

        self._import_dlg_timer = QTimer(self)
        self._import_dlg_timer.setSingleShot(True)
        self._import_dlg_timer.timeout.connect(self._show_import_progress_dialog)
        self._import_dlg_timer.start(180)

        self._import_worker.start()

    def _show_import_progress_dialog(self):
        worker = getattr(self, "_import_worker", None)
        dlg = getattr(self, "_import_progress_dlg", None)
        if worker is not None and worker.isRunning() and dlg is not None and not dlg.isVisible():
            dlg.open()

    def _on_import_finished(self, imported_items, cancelled):
        timer = getattr(self, "_import_dlg_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

        dlg = getattr(self, "_import_progress_dlg", None)
        if dlg is not None:
            dlg.finish_and_close()
            self._import_progress_dlg = None

        first_new_row = None
        if imported_items:
            existing_keys = {
                d.get('source_key') or os.path.abspath(d['path'])
                for d in self.files_data.values()
            }
            self._updating_table_items = True
            was_sorting = self.table.isSortingEnabled()
            self.table.setSortingEnabled(False)
            self.table.setUpdatesEnabled(False)
            try:
                for entry in imported_items:
                    source_key = entry['source_key']
                    if source_key in existing_keys:
                        continue
                    existing_keys.add(source_key)

                    meta = entry['meta']
                    self._next_item_id += 1
                    item_id = str(self._next_item_id)
                    entry['item_id'] = item_id
                    row = self.table.rowCount()
                    self.table.insertRow(row)

                    it_file = QTableWidgetItem(entry['display_name'])
                    it_file.setData(Qt.ItemDataRole.UserRole, item_id)
                    it_file.setFlags(it_file.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, 0, it_file)
                    self.table.setItem(row, 1, QTableWidgetItem(meta['last']))
                    self.table.setItem(row, 2, QTableWidgetItem(meta['first']))
                    self.table.setItem(row, 3, QTableWidgetItem(meta['mid']))
                    self.table.setItem(row, 4, QTableWidgetItem(meta['series']))
                    self.table.setItem(row, 5, QTableWidgetItem(meta['num']))
                    self.table.setItem(row, 6, QTableWidgetItem(meta['title']))
                    it_target = QTableWidgetItem(self.simulate_fbc_target(meta))
                    it_target.setFlags(it_target.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, 7, it_target)
                    self.table.setItem(row, 8, self._make_status_item())

                    self.files_data[item_id] = entry
                    if first_new_row is None:
                        first_new_row = row
            finally:
                self.table.setUpdatesEnabled(True)
                self.table.setSortingEnabled(was_sorting)
                self._updating_table_items = False

        if first_new_row is not None and not getattr(self, "_import_had_rows", False) and self.table.rowCount() > 0:
            self.table.selectRow(0)
        self.apply_table_filter()
        self.update_header_status()
        self._refresh_filename_builder_preview()
        logger.info("Импорт книг завершён: добавлено=%d, отменено=%s", len(imported_items), cancelled)

        queued = getattr(self, "_queued_import_paths", None)
        if queued:
            next_batch = list(queued)
            queued.clear()
            QTimer.singleShot(0, lambda b=next_batch: self.process_files(b))

    def load_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("converter.dlg_select_books"), "", tr("converter.filter_books"))
        if files:
            self.process_files(files)

    def clear_list(self):
        if not self.files_data and self.table.rowCount() == 0:
            return
        removed_entries = []
        for r in range(self.table.rowCount()):
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if data is not None:
                removed_entries.append((r, item_id, data))
        if removed_entries:
            self.undo_stack.push(
                RemoveBooksCommand(self, removed_entries, tr("converter.undo_clear", count=len(removed_entries)))
            )
            return
        self.table.setRowCount(0)
        self.files_data.clear()
        self.btn_replace_cover.setEnabled(False)
        self.btn_reset_cover.setEnabled(False)
        self._update_convert_selected_button(0)
        self.render_cover_preview(None)
        self.apply_table_filter()
        self.update_header_status()

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

    def convert_all(self, debug=False):
        items = []
        for item_id, data in self.files_data.items():
            data["item_id"] = item_id
            items.append(data)
        self._run_conversion(items, debug=debug)

    def convert_selected(self, debug=False):
        selected_rows = sorted({
            idx.row() for idx in self.table.selectionModel().selectedRows()
            if not self.table.isRowHidden(idx.row())
        })
        items = []
        for r in selected_rows:
            it0 = self.table.item(r, 0)
            if not it0:
                continue
            item_id = it0.data(Qt.ItemDataRole.UserRole)
            data = self.files_data.get(item_id)
            if data:
                data["item_id"] = item_id
                items.append(data)
        self._run_conversion(items, debug=debug)

    def _run_conversion(self, items, debug=False):
        if not items:
            show_themed_message(self, tr("common.warning"), tr("converter.warn_empty_list"), "warning")
            return
        fbc_bin = self.fbc_cmd or FBC_CMD
        if not fbc_bin or not os.path.isfile(fbc_bin):
            self._ensure_fbc_on_startup(
                interactive=True,
                on_ready=lambda it=items, d=debug: self._run_conversion(it, debug=d),
            )
            return

        self.save_visual_css(show_alert=False)
        self.update_fbc_config_file()
        selected_format = self.app_settings.get("output_format", DEFAULT_OUTPUT_FORMAT)
        save_mode = self.app_settings.get("save_mode", "source")
        custom_dir = self.app_settings.get("custom_output_dir", "")
        title_style_params = self._get_title_style_params()

        compression = None
        if selected_format == "azw3":
            compression = self.app_settings.get("azw3_compression", "standard")
        elif selected_format in ("kfx", "azw8"):
            compression = self.app_settings.get("kfx_compression", "none")

        no_cover = str(self.app_settings.get("no_cover", "false")).lower() == "true"
        email_enabled = self.is_email_auto_send_ready() and not debug
        progress_dlg = ConversionProgressDialog(self, len(items), show_email=email_enabled)

        for it in items:
            if it.get("item_id"):
                self._set_item_status(it["item_id"], "", "")

        self._convert_worker = ConversionWorker(
            items=items,
            selected_format=selected_format,
            save_mode=save_mode,
            custom_dir=custom_dir,
            title_style_params=title_style_params,
            compression=compression,
            email_enabled=email_enabled,
            app_settings=dict(self.app_settings),
            debug=debug,
            no_cover=no_cover,
            fbc_cmd=fbc_bin,
            parent=self,
        )
        self._convert_worker.convert_progress.connect(progress_dlg.update_conversion)
        self._convert_worker.email_progress.connect(progress_dlg.update_email)
        self._convert_worker.item_status.connect(self._set_item_status)
        progress_dlg.cancel_requested.connect(self._convert_worker.cancel)

        result_box = {}

        def _on_finished(success_count, converted_files, convert_errors, email_error, cancelled, failed_items):
            result_box["success_count"] = success_count
            result_box["converted_files"] = converted_files
            result_box["convert_errors"] = convert_errors
            result_box["email_error"] = email_error
            result_box["cancelled"] = cancelled
            result_box["failed_items"] = failed_items
            progress_dlg.finish_and_close()

        self._convert_worker.finished_all.connect(_on_finished)
        self._convert_worker.start()
        progress_dlg.exec()
        self._convert_worker.wait()

        success_count = result_box.get("success_count", 0)
        converted_files = result_box.get("converted_files", [])
        convert_errors = result_box.get("convert_errors", [])
        email_error = result_box.get("email_error", "")
        cancelled = result_box.get("cancelled", False)
        failed_items = result_box.get("failed_items", [])

        output_dir = None
        if converted_files:
            if save_mode == "custom" and custom_dir and os.path.isdir(custom_dir):
                output_dir = custom_dir
            else:
                output_dir = os.path.dirname(converted_files[0])
        elif debug and items:
            if save_mode == "custom" and custom_dir and os.path.isdir(custom_dir):
                output_dir = custom_dir
            else:
                output_dir = os.path.dirname(items[0]["path"])

        err_count = len(convert_errors)
        fmt_upper = selected_format.upper()
        want_retry = False

        if cancelled:
            want_retry = show_conversion_summary_dialog(
                self,
                tr("common.info"),
                tr("converter.msg_cancelled", count=success_count),
                icon_type="warning" if err_count else "info",
                errors=convert_errors,
                output_dir=output_dir,
                allow_retry=bool(failed_items),
            )
        elif email_enabled and converted_files:
            if email_error:
                want_retry = show_conversion_summary_dialog(
                    self,
                    tr("converter.err_email_title"),
                    tr("converter.err_email", count=success_count, e=email_error),
                    icon_type="error",
                    errors=convert_errors,
                    output_dir=output_dir,
                    allow_retry=bool(failed_items),
                )
            else:
                recipient = self.app_settings.get("email_to", "").strip()
                if err_count:
                    title = tr("converter.err_convert_title")
                    summary = tr(
                        "converter.msg_done_email_with_errors",
                        fmt=fmt_upper, count=success_count, err_count=err_count, email=recipient
                    )
                    icon_type = "warning"
                else:
                    title = tr("common.done")
                    summary = tr(
                        "converter.msg_done_email",
                        fmt=fmt_upper, count=success_count, email=recipient
                    )
                    icon_type = "info"
                want_retry = show_conversion_summary_dialog(
                    self,
                    title,
                    summary,
                    icon_type=icon_type,
                    errors=convert_errors,
                    output_dir=output_dir,
                    allow_retry=bool(failed_items),
                )
        else:
            if err_count:
                title = tr("converter.err_convert_title")
                summary = tr(
                    "converter.msg_done_with_errors",
                    fmt=fmt_upper, count=success_count, err_count=err_count
                )
                icon_type = "error" if success_count == 0 else "warning"
            else:
                title = tr("common.done")
                summary = tr("converter.msg_done", fmt=fmt_upper, count=success_count)
                icon_type = "info"
            want_retry = show_conversion_summary_dialog(
                self,
                title,
                summary,
                icon_type=icon_type,
                errors=convert_errors,
                output_dir=output_dir,
                allow_retry=bool(failed_items),
            )

        if want_retry and failed_items:
            QTimer.singleShot(0, lambda fi=failed_items, d=debug: self._run_conversion(fi, debug=d))


class FileImportWorker(QThread):
    """Фоновый поток сканирования папок/архивов и разбора метаданных FB2 без хранения сырого XML в памяти."""

    progress = pyqtSignal(int, int, str)
    finished_import = pyqtSignal(list, bool)

    def __init__(self, filepaths, existing_keys=None, parent=None):
        super().__init__(parent)
        self.filepaths = list(filepaths or [])
        self.existing_keys = set(existing_keys or ())

    def run(self):
        resolved_paths = collect_book_paths(self.filepaths)
        total = len(resolved_paths)
        imported = []
        cancelled = False
        seen_keys = set(self.existing_keys)

        for idx, path in enumerate(resolved_paths, start=1):
            if self.isInterruptionRequested():
                cancelled = True
                break
            self.progress.emit(idx, total, os.path.basename(path))
            for source_key, archive_entry, display_name, xml_bytes in iter_fb2_from_file(path):
                if self.isInterruptionRequested():
                    cancelled = True
                    break
                if source_key in seen_keys or not xml_bytes:
                    continue
                seen_keys.add(source_key)

                meta = parse_metadata(xml_bytes)
                cover_bytes, cover_mime = extract_cover_from_fb2(xml_bytes)
                imported.append({
                    'path': path,
                    'archive_entry': archive_entry,
                    'source_key': source_key,
                    'display_name': display_name,
                    'meta': meta,
                    'orig_cover_bytes': cover_bytes,
                    'orig_cover_mime': cover_mime,
                    'cover_bytes': cover_bytes,
                    'cover_mime': cover_mime,
                    'cover_modified': False,
                })
            if cancelled:
                break

        self.finished_import.emit(imported, cancelled)


class ConversionWorker(QThread):
    convert_progress = pyqtSignal(int, str)
    email_progress = pyqtSignal(int, str)
    item_status = pyqtSignal(str, str, str)
    finished_all = pyqtSignal(int, list, list, str, bool, list)

    def __init__(
        self, items, selected_format, save_mode, custom_dir,
        title_style_params, compression, email_enabled, app_settings,
        debug=False, no_cover=False, fbc_cmd=None, parent=None
    ):
        super().__init__(parent)
        self.items = items
        self.selected_format = selected_format
        self.save_mode = save_mode
        self.custom_dir = custom_dir
        self.title_style_params = title_style_params
        self.compression = compression
        self.email_enabled = email_enabled
        self.app_settings = app_settings
        self.debug = bool(debug)
        self.no_cover = bool(no_cover)
        self.fbc_cmd = fbc_cmd or FBC_CMD
        self._cancel_event = threading.Event()

    def cancel(self):
        """Немедленно сигнализирует отмену всем активным процессам fbc и очереди задач."""
        self._cancel_event.set()
        self.requestInterruption()

    def _resolve_worker_count(self, total):
        raw = str(self.app_settings.get("convert_workers", "auto")).strip().lower()
        if raw.isdigit():
            workers = max(1, min(8, int(raw)))
        else:
            workers = min(4, max(1, os.cpu_count() or 2))
        return max(1, min(workers, total))

    def _convert_single_item(self, idx, data):
        item_id = data.get("item_id", "")
        original_path = data["path"]
        source_label = data.get("display_name") or os.path.basename(original_path)
        display_name = simulate_fbc_target(
            data["meta"],
            self.selected_format,
            self.app_settings.get("filename_mode", "default"),
            self.app_settings.get("filename_tokens"),
        )
        if self.save_mode == "custom" and self.custom_dir and os.path.isdir(self.custom_dir):
            dest_dir = self.custom_dir
        else:
            dest_dir = os.path.dirname(original_path)

        if item_id:
            self.item_status.emit(item_id, "running", "")

        t0 = time.monotonic()
        try:
            created = convert_book_file(
                self.fbc_cmd, FBC_CONFIG, BASE_DIR,
                data, dest_dir, self.selected_format, self.title_style_params,
                compression=self.compression,
                cancel_event=self._cancel_event,
                debug=self.debug,
                no_cover=self.no_cover,
            )
            elapsed = time.monotonic() - t0
            logger.info("Конвертация ОК [%.2fs]: %s -> %s", elapsed, source_label, ", ".join(os.path.basename(p) for p in created))
            if item_id:
                self.item_status.emit(item_id, "ok", "")
            return idx, display_name, source_label, created, None, False
        except ConversionCancelledError:
            elapsed = time.monotonic() - t0
            logger.info("Конвертация ОТМЕНЕНА [%.2fs]: %s", elapsed, source_label)
            if item_id:
                self.item_status.emit(item_id, "cancelled", "")
            return idx, display_name, source_label, [], None, True
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.error("Конвертация ОШИБКА [%.2fs]: %s: %s", elapsed, source_label, e)
            if item_id:
                self.item_status.emit(item_id, "error", str(e))
            return idx, display_name, source_label, [], str(e), False

    def run(self):
        total = len(self.items)
        if total == 0:
            self.finished_all.emit(0, [], [], "", False, [])
            return

        workers = self._resolve_worker_count(total)
        batch_t0 = time.monotonic()
        logger.info(
            "Старт пакетной конвертации: книг=%d, формат=%s, потоков=%d, email=%s, debug=%s",
            total, self.selected_format, workers, self.email_enabled, self.debug
        )

        results_by_idx = {}
        errors_by_idx = {}
        completed = 0
        cancelled = False
        email_error = ""

        first_display = simulate_fbc_target(
            self.items[0]["meta"],
            self.selected_format,
            self.app_settings.get("filename_mode", "default"),
            self.app_settings.get("filename_tokens"),
        )
        self.convert_progress.emit(
            0,
            tr("converter.progress_convert_file", cur=1, total=total, name=first_display)
        )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            pending = set()
            next_idx = 0

            while next_idx < total and len(pending) < workers:
                if self.isInterruptionRequested() or self._cancel_event.is_set():
                    cancelled = True
                    break
                pending.add(executor.submit(self._convert_single_item, next_idx, self.items[next_idx]))
                next_idx += 1

            while pending:
                done, pending = wait(pending, timeout=0.15, return_when=FIRST_COMPLETED)
                for fut in done:
                    idx, display_name, source_label, created, err_msg, was_cancelled = fut.result()
                    if was_cancelled:
                        cancelled = True
                        continue
                    completed += 1
                    if err_msg:
                        errors_by_idx[idx] = (source_label, err_msg)
                    else:
                        results_by_idx[idx] = created
                    self.convert_progress.emit(
                        completed,
                        tr("converter.progress_convert_file", cur=completed, total=total, name=display_name)
                    )

                if self.isInterruptionRequested() or self._cancel_event.is_set():
                    cancelled = True
                    for fut in list(pending):
                        fut.cancel()
                    continue

                while next_idx < total and len(pending) < workers:
                    if self.isInterruptionRequested() or self._cancel_event.is_set():
                        cancelled = True
                        break
                    pending.add(executor.submit(self._convert_single_item, next_idx, self.items[next_idx]))
                    next_idx += 1

        converted_files = []
        for idx in sorted(results_by_idx.keys()):
            converted_files.extend(results_by_idx[idx])
        success_count = len(results_by_idx)
        convert_errors = [errors_by_idx[idx] for idx in sorted(errors_by_idx.keys())]
        failed_items = [self.items[idx] for idx in sorted(errors_by_idx.keys())]

        logger.info(
            "Завершение конвертации за %.2fs: успешно=%d, ошибок=%d, отменено=%s",
            time.monotonic() - batch_t0, success_count, len(convert_errors), cancelled
        )

        if not cancelled:
            self.convert_progress.emit(
                total,
                tr("converter.progress_convert_done", total=total)
            )

        if not cancelled and self.email_enabled and converted_files:
            try:
                logger.info("Отправка %d файлов на %s", len(converted_files), self.app_settings.get("email_to", ""))
                send_email_attachments(
                    self.app_settings,
                    converted_files,
                    APP_NAME,
                    APP_VERSION,
                    progress_callback=lambda pct, txt: self.email_progress.emit(pct, txt)
                )
                logger.info("Отправка по SMTP завершена успешно")
            except Exception as e:
                logger.exception("Ошибка отправки по SMTP: %s", e)
                email_error = str(e)

        self.finished_all.emit(success_count, converted_files, convert_errors, email_error, cancelled, failed_items)


class TestEmailWorker(QThread):
    """Фоновый поток для отправки тестового письма SMTP без блокировки интерфейса."""
    finished_test = pyqtSignal(bool, str)

    def __init__(self, app_settings, parent=None):
        super().__init__(parent)
        self.app_settings = app_settings

    def run(self):
        try:
            dispatch_test_email(self.app_settings, APP_NAME, APP_VERSION)
            self.finished_test.emit(True, "")
        except Exception as e:
            self.finished_test.emit(False, str(e))


class SingleInstanceManager(QObject):
    """Обеспечивает единый экземпляр приложения на Windows/macOS через QLocalServer/QLocalSocket."""

    activation_requested = pyqtSignal(list)

    def __init__(self, server_name=None, parent=None):
        super().__init__(parent)
        if not server_name:
            try:
                user_slug = "".join(ch for ch in getpass.getuser() if ch.isalnum() or ch in ("_", "-")) or "user"
            except Exception:
                user_slug = "user"
            server_name = f"fbc_gui_single_instance_{user_slug}"
        self.server_name = server_name
        self._server = None

    def try_send_to_running(self, paths=None):
        """Пытается передать пути уже запущенному экземпляру; возвращает True, если он ответил."""
        if not HAS_QT_NETWORK or QLocalSocket is None:
            return False
        sock = QLocalSocket()
        sock.connectToServer(self.server_name)
        if not sock.waitForConnected(250):
            return False
        payload = json.dumps({"paths": list(paths or [])}, ensure_ascii=False).encode("utf-8")
        sock.write(payload)
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return True

    def start_server(self):
        """Запускает локальный сервер для приёма файлов от повторных запусков."""
        if not HAS_QT_NETWORK or QLocalServer is None:
            return False
        QLocalServer.removeServer(self.server_name)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        if not self._server.listen(self.server_name):
            logger.warning("Не удалось запустить QLocalServer (%s): %s", self.server_name, self._server.errorString())
            self._server = None
            return False
        return True

    def _on_new_connection(self):
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            if conn is None:
                continue
            conn.waitForReadyRead(300)
            raw = bytes(conn.readAll())
            conn.disconnectFromServer()
            conn.deleteLater()
            paths = []
            if raw:
                try:
                    data = json.loads(raw.decode("utf-8", errors="replace"))
                    if isinstance(data, dict) and isinstance(data.get("paths"), list):
                        paths = [p for p in data["paths"] if isinstance(p, str) and os.path.exists(p)]
                except Exception:
                    pass
            self.activation_requested.emit(paths)

    def close(self):
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(self.server_name)
            self._server = None


class FbcApplication(QApplication):
    """Подкласс QApplication с перехватом QFileOpenEvent (macOS «Открыть с помощью» / перетаскивание на иконку)."""

    files_opened = pyqtSignal(list)

    def __init__(self, argv):
        super().__init__(argv)
        self._pending_open_files = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_pending_files)

    def event(self, ev):
        if ev.type() == QEvent.Type.FileOpen:
            fp = ""
            if hasattr(ev, "file"):
                fp = ev.file() or ""
            if not fp and hasattr(ev, "url"):
                fp = ev.url().toLocalFile() or ""
            if fp and os.path.exists(fp):
                self._pending_open_files.append(fp)
                self._flush_timer.start(120)
                ev.accept()
                return True
        return super().event(ev)

    def _flush_pending_files(self):
        if not self._pending_open_files:
            return
        batch = list(self._pending_open_files)
        self._pending_open_files.clear()
        self.files_opened.emit(batch)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-V"):
        print(APP_VERSION)
        sys.exit(0)
    app = FbcApplication(sys.argv)
    startup_paths = collect_startup_paths(sys.argv)

    single_instance = SingleInstanceManager(parent=app)
    if single_instance.try_send_to_running(startup_paths):
        logger.info("Передано файлов в активный экземпляр FBC GUI: %d", len(startup_paths))
        sys.exit(0)
    single_instance.start_server()
    app.aboutToQuit.connect(single_instance.close)

    app.setStyle("Fusion")
    window = MainWindow()
    app.files_opened.connect(window.activate_and_import)
    single_instance.activation_requested.connect(window.activate_and_import)
    window.show()
    if startup_paths:
        QTimer.singleShot(0, lambda p=startup_paths: window.enqueue_import_paths(p))
    if app._pending_open_files:
        QTimer.singleShot(150, app._flush_pending_files)
    sys.exit(app.exec())

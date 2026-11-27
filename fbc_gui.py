import os
import sys
import shutil
import webbrowser

from PyQt6.QtCore import Qt, QEvent, QTimer, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence, QShortcut, QUndoStack
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QGridLayout, QStackedWidget,
    QAbstractItemView,
)

# --- Метаинформация и версия программы ---
from core.version import (
    __app_name__,
    __author__,
    __build__,
    __email__,
    __url__,
    __version__,
)

APP_NAME = __app_name__
BUILD_NUMBER = __build__
APP_VERSION = __version__
APP_AUTHOR = __author__
APP_EMAIL = __email__
APP_URL = __url__
THIRD_PARTY_NAME = "fbc2ng"
THIRD_PARTY_VERSION = "2.1.1"
THIRD_PARTY_URL = "https://github.com/rupor-github/fb2cng"
S2K_THIRD_PARTY_NAME = "sync2kindle (s2k)"
S2K_THIRD_PARTY_URL = "https://github.com/rupor-github/sync2kindle"

from core.config import (
    DEFAULT_OUTPUT_FORMAT,
    cleanup_stale_temp_dirs,
    get_default_app_settings,
    migrate_fbc_config_211,
)
from core.css_preview import VALID_FONT_EXTENSIONS
from core.fb2_processor import collect_startup_paths
from core.fbc_manager import resolve_local_fbc
from core.i18n import LOCALE, get_theme_choices, init_locale, tr
from core.logger import get_logger, init_logging
from core.notifier import set_windows_app_user_model_id
from core.presets import sync_bundled_presets
from core.updater import DEFAULT_RELEASES_URL, is_safe_http_url
from core.workers import SingleInstanceManager
from ui.controllers import (
    ConversionController,
    LibraryController,
    PresetsController,
    PreviewController,
    QueueController,
    SettingsController,
    TrayWatchController,
    UpdatesController,
)
from ui.controllers.library_controller import PAGE_LIBRARY_INDEX
from ui.dialogs import show_themed_message
from ui.pages.about_page import build_about_page
from ui.pages.converter_page import build_converter_page
from ui.pages.css_page import build_visual_css_page
from ui.pages.library_page import build_library_page
from ui.pages.preview_page import build_preview_page
from ui.pages.settings_page import build_settings_page
from ui.theme import (
    LEGACY_THEME_MAP,
    ThemeToggleWidget,
    build_qpalette_from_qss,
    build_theme_qss,
    init_themes,
    refresh_widget_halos,
    resolve_theme_family_and_mode,
    start_window_crossfade,
)

logger = get_logger("app")
_RUNTIME_INITIALIZED = False
BASE_DIR = FBC_CMD = FBC_DETECTED_VERSION = FBC_CONFIG = CSS_PATH = BUNDLED_CSS_PATH = ""
FONTS_DIR = ICONS_DIR = SETTINGS_PATH = LOCALES_DIR = BUNDLED_LOCALES_DIR = ""
THEMES_DIR = BUNDLED_THEMES_DIR = PRESETS_DIR = BUNDLED_PRESETS_DIR = LOG_PATH = ""


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

        for sub_dir in ("fonts", "locales", "themes", "icons"):
            src_sub = os.path.join(bundle_dir, sub_dir)
            dst_sub = os.path.join(user_data_dir, sub_dir)
            if os.path.exists(src_sub):
                os.makedirs(dst_sub, exist_ok=True)
                for f in os.listdir(src_sub):
                    s_fp = os.path.join(src_sub, f)
                    d_fp = os.path.join(dst_sub, f)
                    if os.path.isfile(s_fp) and (not os.path.exists(d_fp) or sub_dir in ("themes", "locales", "icons")):
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
        os.path.join(user_data_dir, "icons"),
        os.path.join(user_data_dir, "settings.json"),
        os.path.join(user_data_dir, "locales"),
        os.path.join(bundle_dir, "locales"),
        os.path.join(user_data_dir, "themes"),
        os.path.join(bundle_dir, "themes"),
        presets_dir,
        bundled_presets_dir,
    )


def init_app_runtime():
    """Инициализирует рабочую среду, логирование, локали и темы один раз при запуске приложения."""
    global _RUNTIME_INITIALIZED, BASE_DIR, FBC_CMD, FBC_DETECTED_VERSION, FBC_CONFIG
    global CSS_PATH, BUNDLED_CSS_PATH, FONTS_DIR, ICONS_DIR, SETTINGS_PATH, LOCALES_DIR, BUNDLED_LOCALES_DIR
    global THEMES_DIR, BUNDLED_THEMES_DIR, PRESETS_DIR, BUNDLED_PRESETS_DIR, LOG_PATH
    if _RUNTIME_INITIALIZED:
        return
    (
        BASE_DIR, FBC_CMD, FBC_DETECTED_VERSION, FBC_CONFIG, CSS_PATH, BUNDLED_CSS_PATH, FONTS_DIR, ICONS_DIR,
        SETTINGS_PATH, LOCALES_DIR, BUNDLED_LOCALES_DIR,
        THEMES_DIR, BUNDLED_THEMES_DIR, PRESETS_DIR, BUNDLED_PRESETS_DIR,
    ) = setup_app_environment()
    LOG_PATH = init_logging(BASE_DIR)
    logger.info("%s v%s (build %s) started; base_dir=%s", APP_NAME, APP_VERSION, BUILD_NUMBER, BASE_DIR)
    cleaned_tmp = cleanup_stale_temp_dirs()
    if cleaned_tmp:
        logger.debug("Очищено устаревших временных каталогов: %d", cleaned_tmp)
    init_locale(LOCALES_DIR, BUNDLED_LOCALES_DIR)
    init_themes(THEMES_DIR, BUNDLED_THEMES_DIR)
    _RUNTIME_INITIALIZED = True


def get_user_guide_url(lang_code=None):
    """Возвращает HTTPS-ссылку на пользовательскую документацию на GitHub под текущий язык интерфейса."""
    repo_base = DEFAULT_RELEASES_URL.rsplit("/releases", 1)[0]
    code = str(lang_code or "").strip().lower()
    fname = "USER_GUIDE_RU.md" if code.startswith("ru") else "USER_GUIDE_EN.md"
    return f"{repo_base}/blob/main/docs/{fname}"


class MainWindow(
    SettingsController,
    PresetsController,
    PreviewController,
    QueueController,
    LibraryController,
    ConversionController,
    TrayWatchController,
    UpdatesController,
    QMainWindow,
):
    """Главное окно FBC GUI — тонкий координатор страниц, тем, жизненного цикла и контроллеров."""

    def __init__(self):
        init_app_runtime()
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1380, 880)

        # Рабочие пути и метаданные, используемые контроллерами без связи с глобальными переменными
        self.base_dir = BASE_DIR
        self.fbc_config_path = FBC_CONFIG
        self.css_path = CSS_PATH
        self.bundled_css_path = BUNDLED_CSS_PATH
        self.fonts_dir = FONTS_DIR
        self.icons_dir = ICONS_DIR
        self.settings_path = SETTINGS_PATH
        self.presets_dir = PRESETS_DIR
        self.bundled_presets_dir = BUNDLED_PRESETS_DIR
        self.log_path = LOG_PATH
        self.app_name = APP_NAME
        self.app_version = APP_VERSION
        self.build_number = BUILD_NUMBER
        self.third_party_version = THIRD_PARTY_VERSION

        self.files_data = {}
        self._next_item_id = 0
        self.font_map = {}
        self._loading_css = False
        self._applying_theme = False
        self._update_worker = None
        self._update_dl_worker = None
        self._update_dl_dlg = None
        self._fbc_worker = None
        self._import_worker = None
        self._inpx_index_worker = None
        self._inpx_progress_dlg = None
        self._test_email_worker = None
        self._convert_worker = None
        self._device_sync_worker = None
        self._bg_task_worker = None
        self._closing = False
        self._pending_settings_save = False
        self._pending_fbc_config_save = False
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(400)
        self._settings_save_timer.timeout.connect(self._flush_pending_settings)
        self._fbc_setup_dlg = None
        self._s2k_setup_dlg = None
        self._fbc_ready_callback = None
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

        if os.path.exists(self.css_path):
            self.load_and_parse_css_to_gui()
        else:
            self.save_visual_css(show_alert=False)

        self.apply_theme(self.app_settings["theme"])

        # Подписка на смену системной темы ОС (для режима "Авто")
        app_inst = QApplication.instance()
        if app_inst and hasattr(app_inst.styleHints(), "colorSchemeChanged"):
            try:
                app_inst.styleHints().colorSchemeChanged.connect(self._on_system_appearance_changed)
            except Exception as e:
                logger.debug("Не удалось подписаться на смену системной темы ОС: %s", e)

        self.setAcceptDrops(True)
        self._setup_shortcuts()
        self.refresh_preview()
        self.init_tray_and_watch()
        QTimer.singleShot(150, self._ensure_fbc_on_startup)
        QTimer.singleShot(2500, self._schedule_startup_update_check)

    def _setup_shortcuts(self):
        self._sc_open = QShortcut(QKeySequence.StandardKey.Open, self)
        self._sc_open.activated.connect(self.load_files)
        self._sc_find = QShortcut(QKeySequence.StandardKey.Find, self)
        self._sc_find.activated.connect(self.focus_table_search)
        self._sc_convert_all = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._sc_convert_all.activated.connect(self.convert_all)
        self._sc_convert_sel = QShortcut(QKeySequence("Ctrl+Shift+Return"), self)
        self._sc_convert_sel.activated.connect(self.convert_selected)

    def _get_active_workers(self, names=None):
        worker_names = names or (
            "_convert_worker",
            "_import_worker",
            "_inpx_index_worker",
            "_fbc_worker",
            "_update_worker",
            "_update_dl_worker",
            "_test_email_worker",
            "_device_sync_worker",
            "_bg_task_worker",
        )
        active = []
        for attr in worker_names:
            worker = getattr(self, attr, None)
            if worker is not None:
                try:
                    if worker.isRunning():
                        active.append((attr, worker))
                except RuntimeError:
                    pass
        return active

    def _has_blocking_workers(self):
        return bool(self._get_active_workers((
            "_convert_worker",
            "_import_worker",
            "_inpx_index_worker",
            "_test_email_worker",
            "_device_sync_worker",
            "_bg_task_worker",
        )))

    def _detach_preview_native_view(self):
        browser = getattr(self, "preview_browser", None)
        if browser is not None and hasattr(browser, "_detach_native_view"):
            try:
                browser._detach_native_view()
            except Exception as e:
                logger.debug("Ошибка отключения нативного предпросмотра: %s", e)

    def _stop_background_workers(self, timeout_ms=3000):
        for timer_attr in ("_import_dlg_timer", "_inpx_dlg_timer", "_lib_search_timer"):
            timer = getattr(self, timer_attr, None)
            if timer is not None:
                try:
                    if timer.isActive():
                        timer.stop()
                except RuntimeError:
                    pass

        for dlg_attr in ("_convert_progress_dlg", "_import_progress_dlg", "_inpx_progress_dlg", "_fbc_setup_dlg", "_s2k_setup_dlg", "_update_dl_dlg"):
            dlg = getattr(self, dlg_attr, None)
            if dlg is not None:
                try:
                    if hasattr(dlg, "finish_and_close"):
                        dlg.finish_and_close()
                    else:
                        dlg.close()
                except RuntimeError:
                    pass
                setattr(self, dlg_attr, None)

        from core.workers import stop_qthread_safely

        active = self._get_active_workers()
        for _, worker in active:
            try:
                if hasattr(worker, "cancel"):
                    worker.cancel()
                worker.requestInterruption()
            except RuntimeError:
                pass

        for name, worker in active:
            stop_qthread_safely(worker, timeout_ms=timeout_ms, label=name)

    def closeEvent(self, event):
        if (
            not getattr(self, "_force_quit", False)
            and hasattr(self, "should_minimize_to_tray_on_close")
            and self.should_minimize_to_tray_on_close()
        ):
            event.ignore()
            self.hide_to_tray()
            return
        self._closing = True
        self._flush_pending_settings()
        watch_mgr = getattr(self, "watch_manager", None)
        if watch_mgr is not None:
            watch_mgr.stop()
        tray = getattr(self, "_tray_icon", None)
        if tray is not None:
            try:
                tray.hide()
            except RuntimeError:
                pass
        self._stop_background_workers()
        self._detach_preview_native_view()
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

    def on_header_day_night_toggled(self, mode):
        """Переключение режима оформления (auto / light / dark) из верхнего переключателя."""
        m = str(mode).lower()
        self.app_settings["theme_mode"] = m if m in ("auto", "light", "dark") else "auto"
        valid_families = {val for _, val in get_theme_choices()}
        family = self.app_settings.get("theme_family", "Modern")
        if family not in valid_families:
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
                mode_setting,
            )

            if hasattr(self, "theme_toggle"):
                self.theme_toggle.set_mode(mode_setting)

            qss = build_theme_qss(mapped_choice, eff_family, mode_setting)
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
            getattr(self, "_current_eff_mode", "dark"),
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
        act_docs = help_menu.addAction(tr("menu.user_guide"))
        act_docs.setShortcut(QKeySequence.StandardKey.HelpContents)
        act_docs.triggered.connect(self.open_user_guide)
        help_menu.addSeparator()
        act_check_updates = help_menu.addAction(tr("menu.check_updates"))
        act_check_updates.triggered.connect(lambda: self.check_for_updates(manual=True))
        help_menu.addSeparator()
        act_about = help_menu.addAction(tr("menu.about", app=APP_NAME))
        act_about.triggered.connect(lambda: self.switch_page(4))

    def open_user_guide(self):
        url = get_user_guide_url(LOCALE.lang_code)
        if is_safe_http_url(url, allow_relative=False, require_https=True):
            webbrowser.open(url)

    def apply_language(self, lang_code, save=True):
        if getattr(self, "_applying_language", False):
            return
        if self._has_blocking_workers():
            logger.warning("Смена языка отклонена: активны фоновые задачи")
            if hasattr(self, "lang_selector"):
                try:
                    self.lang_selector.set(LOCALE.lang_code)
                except RuntimeError:
                    pass
            show_themed_message(self, tr("common.warning"), tr("common.busy_workers_warning"), "warning")
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
            if hasattr(self, "refresh_tray_menu"):
                self.refresh_tray_menu()
        finally:
            self._applying_language = False

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p = url.toLocalFile()
                if p and (os.path.isdir(p) or p.lower().endswith(('.fb2', '.zip') + VALID_FONT_EXTENSIONS)):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event: QDropEvent):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        font_paths = [p for p in paths if os.path.isfile(p) and p.lower().endswith(VALID_FONT_EXTENSIONS)]
        book_paths = [p for p in paths if p not in font_paths]
        if font_paths:
            self._install_font_files(font_paths)
        if book_paths:
            self.process_files(book_paths)

    def create_widgets(self):
        self._detach_preview_native_view()
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
            (tr("nav.library"), PAGE_LIBRARY_INDEX),
            (tr("nav.converter"), 0),
            (tr("nav.styles"), 1),
            (tr("nav.preview"), 2),
            (tr("nav.settings"), 3),
            (tr("nav.about"), 4),
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

        self.page_library = QWidget()
        self.create_library_page(self.page_library)
        self.pages.addWidget(self.page_library)

        self._update_library_nav_visibility()
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
        elif idx == PAGE_LIBRARY_INDEX:
            self.on_library_page_opened()

    def create_library_page(self, parent):
        build_library_page(self, parent)

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

    def create_about_page(self, parent):
        build_about_page(
            self,
            parent,
            APP_NAME, APP_VERSION, APP_AUTHOR, APP_EMAIL, APP_URL,
            THIRD_PARTY_NAME, getattr(self, "fbc_version", THIRD_PARTY_VERSION) or THIRD_PARTY_VERSION, THIRD_PARTY_URL,
            S2K_THIRD_PARTY_NAME, S2K_THIRD_PARTY_URL,
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


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-V"):
        print(APP_VERSION)
        sys.exit(0)
    start_minimized = any(a in ("--minimized", "--background") for a in sys.argv[1:])
    set_windows_app_user_model_id()
    init_app_runtime()
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
    if start_minimized and window.is_tray_active() and not startup_paths:
        window.hide_to_tray()
    else:
        window.show()
    if startup_paths:
        QTimer.singleShot(0, lambda p=startup_paths: window.enqueue_import_paths(p))
    if app._pending_open_files:
        QTimer.singleShot(150, app._flush_pending_files)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

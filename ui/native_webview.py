import os
import sys

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QTextEdit

from core.logger import get_logger

logger = get_logger("native_webview")


class FallbackTextPreviewWidget(QTextEdit):
    """Резервный виджет предпросмотра на базе QTextEdit."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setStyleSheet(
            "background-color: #FDFBF7; color: #222222; border-radius: 10px; padding: 20px;"
        )

    def set_preview_html(self, html_text, base_dir=""):
        self.setHtml(html_text)


class MacOSWKWebViewWidget(QWidget):
    """Нативный macOS WKWebView (WebKit) через PyObjC, встроенный как Cocoa subview в QWidget."""

    def __init__(self, parent=None):
        app = QApplication.instance()
        if app is None or app.platformName() != "cocoa":
            raise RuntimeError(
                f"WKWebView требует Qt platform 'cocoa', текущий: {app.platformName() if app else None}"
            )

        import objc
        from AppKit import NSViewWidthSizable, NSViewHeightSizable
        from Foundation import NSURL, NSMakeRect
        from WebKit import WKWebView, WKWebViewConfiguration, WKWebsiteDataStore

        self._objc = objc
        self._NSURL = NSURL
        self._attached = False
        self._pending_html = None
        self._pending_base_dir = ""

        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)

        cfg = WKWebViewConfiguration.alloc().init()
        try:
            cfg.setWebsiteDataStore_(WKWebsiteDataStore.nonPersistentDataStore())
        except Exception:
            pass
        try:
            prefs = cfg.defaultWebpagePreferences()
            if prefs is not None and hasattr(prefs, "setAllowsContentJavaScript_"):
                prefs.setAllowsContentJavaScript_(False)
        except Exception:
            pass

        self._wk_view = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, max(100, self.width()), max(100, self.height())),
            cfg,
        )
        self._wk_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.destroyed.connect(self._detach_native_view)

    def _get_host_nsview(self):
        wid = int(self.winId())
        if wid <= 0x10000:
            return None
        return self._objc.objc_object(c_void_p=wid)

    def _attach_to_native_host(self):
        if getattr(self, "_attached", False):
            return
        try:
            host_view = self._get_host_nsview()
            if host_view is None:
                return
            host_view.addSubview_(self._wk_view)
            self._wk_view.setFrame_(host_view.bounds())
            self._attached = True
        except Exception as e:
            logger.warning("Не удалось прикрепить WKWebView к NSView: %s", e)

    def _detach_native_view(self, *args):
        if getattr(self, "_attached", False):
            try:
                self._wk_view.removeFromSuperview()
            except Exception:
                pass
            self._attached = False

    def showEvent(self, event):
        super().showEvent(event)
        if not hasattr(self, "_wk_view"):
            return
        self._attach_to_native_host()
        self._sync_frame()
        if getattr(self, "_pending_html", None) is not None:
            html_text, base_dir = self._pending_html, self._pending_base_dir
            self._pending_html = None
            self.set_preview_html(html_text, base_dir)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_frame()

    def closeEvent(self, event):
        self._detach_native_view()
        super().closeEvent(event)

    def _sync_frame(self):
        if not getattr(self, "_attached", False) or not hasattr(self, "_wk_view"):
            return
        try:
            host_view = self._get_host_nsview()
            if host_view is not None:
                self._wk_view.setFrame_(host_view.bounds())
        except Exception:
            pass

    def set_preview_html(self, html_text, base_dir=""):
        if not self._attached:
            self._attach_to_native_host()
        if not self._attached:
            self._pending_html = html_text
            self._pending_base_dir = base_dir
            return
        if base_dir and os.path.isdir(base_dir):
            render_path = os.path.join(base_dir, ".preview_render.html")
            try:
                with open(render_path, "w", encoding="utf-8") as f:
                    f.write(html_text)
                file_url = self._NSURL.fileURLWithPath_(os.path.abspath(render_path))
                dir_url = self._NSURL.fileURLWithPath_isDirectory_(os.path.abspath(base_dir), True)
                self._wk_view.loadFileURL_allowingReadAccessToURL_(file_url, dir_url)
                return
            except Exception as e:
                logger.warning("WKWebView loadFileURL fallback: %s", e)

        base_url = self._NSURL.fileURLWithPath_isDirectory_(os.path.abspath(base_dir or os.getcwd()), True)
        self._wk_view.loadHTMLString_baseURL_(html_text, base_url)


class WindowsWebView2Widget(QWidget):
    """Нативный Windows Microsoft Edge WebView2 через лёгкую обёртку qtwebview2."""

    def __init__(self, parent=None):
        import qtwebview2

        widget_cls = (
            getattr(qtwebview2, "QtWebView", None)
            or getattr(qtwebview2, "WebView2Widget", None)
            or getattr(qtwebview2, "QWebView2", None)
        )
        if widget_cls is None:
            raise ImportError("Не найден класс виджета в qtwebview2")

        super().__init__(parent)
        self._wv = widget_cls(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._wv)

    def set_preview_html(self, html_text, base_dir=""):
        if base_dir and os.path.isdir(base_dir):
            render_path = os.path.join(base_dir, ".preview_render.html")
            try:
                with open(render_path, "w", encoding="utf-8") as f:
                    f.write(html_text)
                file_url = QUrl.fromLocalFile(os.path.abspath(render_path)).toString()
                if hasattr(self._wv, "load"):
                    self._wv.load(QUrl.fromLocalFile(os.path.abspath(render_path)))
                    return
                if hasattr(self._wv, "setUrl"):
                    self._wv.setUrl(QUrl.fromLocalFile(os.path.abspath(render_path)))
                    return
                if hasattr(self._wv, "navigate"):
                    self._wv.navigate(file_url)
                    return
            except Exception as e:
                logger.warning("WebView2 file load fallback: %s", e)

        if hasattr(self._wv, "setHtml"):
            self._wv.setHtml(html_text)
        elif hasattr(self._wv, "load_html"):
            self._wv.load_html(html_text)
        elif hasattr(self._wv, "navigate_to_string"):
            self._wv.navigate_to_string(html_text)


class QtWebEnginePreviewWidget(QWidget):
    """Опциональная обёртка для QWebEngineView, если пакет PyQt6-WebEngine установлен."""

    def __init__(self, parent=None):
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWebEngineCore import QWebEngineSettings

        super().__init__(parent)
        self._view = QWebEngineView(self)
        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._view)

    def set_preview_html(self, html_text, base_dir=""):
        base_url = QUrl.fromLocalFile(os.path.abspath(base_dir or os.getcwd()) + os.sep)
        self._view.setHtml(html_text, base_url)


def create_preview_widget(parent=None):
    """
    Создаёт лучший доступный виджет предпросмотра и возвращает (widget, engine_kind):
    - macOS: 'wkwebview' (нативный WebKit)
    - Windows: 'webview2' (нативный Edge WebView2 через qtwebview2)
    - fallback: 'webengine' (если установлен PyQt6-WebEngine) -> 'fallback' (QTextEdit)
    """
    if sys.platform == "darwin":
        try:
            return MacOSWKWebViewWidget(parent), "wkwebview"
        except Exception as e:
            logger.warning("Не удалось инициализировать macOS WKWebView: %s", e)

    if sys.platform == "win32":
        try:
            return WindowsWebView2Widget(parent), "webview2"
        except Exception as e:
            logger.warning("Не удалось инициализировать Windows Edge WebView2: %s", e)

    try:
        return QtWebEnginePreviewWidget(parent), "webengine"
    except Exception:
        pass

    return FallbackTextPreviewWidget(parent), "fallback"

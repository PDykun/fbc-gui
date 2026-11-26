import re
import sys
import threading

from core.logger import get_logger

logger = get_logger("fb2_processor")
_DEST_MOVE_LOCK = threading.Lock()

_TITLE_INFO_XSD_ORDER = (
    "genre", "author", "book-title", "annotation", "keywords", "date",
    "coverpage", "lang", "src-lang", "translator", "sequence",
)
_AUTHOR_XSD_ORDER = (
    "first-name", "middle-name", "last-name", "nickname", "home-page", "email", "id",
)
_PUBLISH_INFO_XSD_ORDER = (
    "book-name", "publisher", "city", "year", "isbn", "sequence",
)
_DESCRIPTION_XSD_ORDER = (
    "title-info", "src-title-info", "document-info", "publish-info", "custom-info", "output",
)

_ISBN_PREFIX_RE = re.compile(r"^\s*isbn(?:[-\s]*(?:10|13))?\s*[:#]?\s*", re.IGNORECASE)
_ISBN_CLEAN_RE = re.compile(r"[\s\-\u2010-\u2015]+")
_ISBN10_RE = re.compile(r"\d{9}[\dX]")
_ISBN13_RE = re.compile(r"\d{13}")
_WHITESPACE_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def get_facade_attr(name, default):
    """Возвращает атрибут фасада core.fb2_processor, сохраняя совместимость с unittest.mock.patch."""
    mod = sys.modules.get("core.fb2_processor")
    if mod is not None and hasattr(mod, name):
        return getattr(mod, name)
    return default


def normalize_isbn(raw):
    """Нормализует ISBN-10 / ISBN-13 (убирает префикс ISBN, дефисы и пробелы) или возвращает '' при невалидном значении."""
    if not raw:
        return ""
    text = _ISBN_PREFIX_RE.sub("", str(raw).strip())
    cleaned = _ISBN_CLEAN_RE.sub("", text).upper()
    if len(cleaned) == 10 and _ISBN10_RE.fullmatch(cleaned):
        total = sum((10 - idx) * (10 if ch == "X" else int(ch)) for idx, ch in enumerate(cleaned))
        return cleaned if total % 11 == 0 else ""
    if len(cleaned) == 13 and _ISBN13_RE.fullmatch(cleaned):
        total = sum((1 if idx % 2 == 0 else 3) * int(ch) for idx, ch in enumerate(cleaned[:12]))
        check = (10 - (total % 10)) % 10
        return cleaned if check == int(cleaned[12]) else ""
    return ""


def is_valid_isbn(raw):
    """Возвращает True, если строка является корректным ISBN-10 или ISBN-13."""
    return bool(normalize_isbn(raw))


def copy_meta_dict(meta):
    """Создаёт безопасную копию словаря метаданных (включая копирование списков вроде genres)."""
    if not isinstance(meta, dict):
        return {}
    out = dict(meta)
    if "genres" in out:
        out["genres"] = list(out["genres"] or [])
    return out


class ConversionCancelledError(Exception):
    """Исключение, выбрасываемое при немедленной отмене конвертации пользователем."""


try:
    from PIL import Image, ImageOps
    HAS_PIL = True
except ImportError:
    Image = None
    ImageOps = None
    HAS_PIL = False

try:
    from lxml import etree as LXML_ET
    HAS_LXML = True
except ImportError:
    LXML_ET = None
    HAS_LXML = False

DEFAULT_OUTPUT_FORMAT = "epub3"

COVER_TARGET_SIZE = (600, 900)
COVER_PREVIEW_SIZE = (180, 270)

FORMAT_EXT_MAP = {
    "epub2": ".epub", "epub3": ".epub",
    "kepub": ".kepub.epub", "kepub3": ".kepub.epub",
    "azw3": ".azw3", "kfx": ".kfx", "azw8": ".azw8",
    "pdf": ".pdf", "txt": ".txt", "md": ".md",
}
EPUB_BASED_FORMATS = {"epub2", "epub3", "kepub", "kepub3"}

FILENAME_TAG_IDS = ("title", "series", "series_abbr", "num", "last", "first", "mid", "format")
TITLE_TAG_IDS = ("title", "series", "series_abbr", "num", "last", "first", "mid")

LEGACY_DEFAULT_FILENAME_TOKENS = [
    {"type": "tag", "id": "last"},
    {"type": "text", "value": " - "},
    {"type": "text", "value": "("},
    {"type": "tag", "id": "series_abbr"},
    {"type": "text", "value": " - "},
    {"type": "tag", "id": "num"},
    {"type": "text", "value": ") "},
    {"type": "tag", "id": "title"},
]

DEFAULT_FILENAME_TOKENS = [
    {"type": "tag", "id": "last"},
    {"type": "text", "value": " - "},
    {"type": "text", "value": "("},
    {"type": "tag", "id": "series_abbr"},
    {"type": "text", "value": "-"},
    {"type": "tag", "id": "num"},
    {"type": "text", "value": ")"},
    {"type": "text", "value": " - "},
    {"type": "tag", "id": "title"},
]

DEFAULT_TITLE_TOKENS = [
    {"type": "text", "value": "("},
    {"type": "tag", "id": "series_abbr"},
    {"type": "text", "value": " - "},
    {"type": "tag", "id": "num"},
    {"type": "text", "value": ") "},
    {"type": "tag", "id": "title"},
]

FB2_NS = "http://www.gribuser.ru/xml/fictionbook/2.0"
XLINK_NS = "http://www.w3.org/1999/xlink"
NS = {'fb': FB2_NS, 'l': XLINK_NS}

import xml.etree.ElementTree as _ET
_ET.register_namespace('', FB2_NS)
_ET.register_namespace('l', XLINK_NS)

# Верхний предел размера одного FB2 XML из ZIP-архива (защита от zip-бомб)
MAX_FB2_XML_BYTES = 128 * 1024 * 1024

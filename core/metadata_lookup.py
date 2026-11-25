"""Онлайн-подбор метаданных и обложек книг (FantLab, LitRes, Open Library, Google Books).

Работает без дополнительных сторонних зависимостей (stdlib urllib + certifi + Pillow).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from difflib import SequenceMatcher
import base64
import hashlib
import html
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from xml.parsers import expat as _xml_expat

from core.fb2_genres import KNOWN_GENRE_CODES, normalize_genre_list
from core.fb2_processor import COVER_TARGET_SIZE, HAS_PIL, normalize_isbn
from core.logger import get_logger
from core.updater import _build_ssl_context, is_safe_http_url, safe_urlopen

if HAS_PIL:
    from PIL import Image, ImageOps

logger = get_logger("metadata_lookup")

LOOKUP_USER_AGENT = "FBC-GUI/2.10 (Book Metadata Lookup)"
MAX_JSON_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_COVER_IMAGE_BYTES = 12 * 1024 * 1024
DEFAULT_TIMEOUT_SEC = 8.0

DEFAULT_PROVIDER_ORDER = ("fantlab", "litres", "openlibrary", "googlebooks", "opds")
DEFAULT_ENABLED_PROVIDERS = ("fantlab", "litres", "openlibrary")
PROVIDER_LABELS = {
    "fantlab": "FantLab",
    "litres": "LitRes",
    "openlibrary": "Open Library",
    "googlebooks": "Google Books",
    "opds": "OPDS",
}


def _https_url(host, path="", query=None):
    """Собирает безопасный HTTPS URL из хоста, пути и параметров запроса."""
    q_str = urllib.parse.urlencode(query) if query else ""
    return urllib.parse.urlunsplit(("https", host, path, q_str, ""))


_LANG_MAP = {
    "ru": "ru", "rus": "ru", "russian": "ru", "русский": "ru", "рус": "ru",
    "en": "en", "eng": "en", "english": "en", "английский": "en",
    "uk": "uk", "ukr": "uk", "ukrainian": "uk", "украинский": "uk",
    "be": "be", "bel": "be", "belarusian": "be", "белорусский": "be",
    "de": "de", "deu": "de", "ger": "de", "german": "de", "немецкий": "de",
    "fr": "fr", "fra": "fr", "fre": "fr", "french": "fr", "французский": "fr",
    "es": "es", "spa": "es", "spanish": "es", "испанский": "es",
    "it": "it", "ita": "it", "italian": "it", "итальянский": "it",
    "pl": "pl", "pol": "pl", "polish": "pl", "польский": "pl",
    "zh": "zh", "zho": "zh", "chi": "zh", "chinese": "zh", "китайский": "zh",
    "ja": "ja", "jpn": "ja", "japanese": "ja", "японский": "ja",
}

_GENRE_KEYWORD_RULES = (
    # Фантастика и фэнтези
    (("киберпанк", "cyberpunk"), "sf_cyberpunk"),
    (("космическая фантастика", "космоопера", "space opera"), "sf_space"),
    (("альтернативная история", "alternate history", "alternative history"), "sf_history"),
    (("боевая фантастика", "military science fiction", "military sf"), "sf_action"),
    (("эпическая фантастика", "эпическое фэнтези", "epic fantasy"), "sf_epic"),
    (("героическое фэнтези", "героическая фантастика", "heroic fantasy"), "sf_heroic"),
    (("детективная фантастика", "фантастический детектив"), "sf_detective"),
    (("социальная фантастика", "антиутопия", "dystopia"), "sf_social"),
    (("ужасы", "мистика", "хоррор", "horror", "gothic"), "sf_horror"),
    (("юмористическая фантастика", "юмористическое фэнтези", "comic fantasy"), "sf_humor"),
    (("фэнтези", "fantasy"), "sf_fantasy"),
    (("научная фантастика", "фантастика", "science fiction", "sci-fi"), "sf"),
    # Детективы и триллеры
    (("триллер", "thriller", "suspense"), "thriller"),
    (("шпионский детектив", "шпионский", "espionage", "spy"), "det_espionage"),
    (("исторический детектив", "historical mystery"), "det_history"),
    (("полицейский детектив", "police procedural"), "det_police"),
    (("иронический детектив", "cozy mystery"), "det_irony"),
    (("боевик", "action & adventure"), "det_action"),
    (("криминал", "криминальный", "crime"), "det_crime"),
    (("классический детектив", "classic mystery"), "det_classic"),
    (("детектив", "mystery", "detective"), "detective"),
    # Проза
    (("русская классика", "russian classics"), "prose_rus_classic"),
    (("советская классика", "soviet"), "prose_su_classics"),
    (("историческая проза", "исторический роман", "historical fiction"), "prose_history"),
    (("классическая проза", "классика", "classic literature", "classics"), "prose_classic"),
    (("современная проза", "современная литература", "contemporary fiction", "literary fiction"), "prose_contemporary"),
    (("проза", "fiction", "novel"), "prose"),
    # Любовные романы
    (("исторический любовный", "historical romance"), "love_history"),
    (("современный любовный", "contemporary romance"), "love_contemporary"),
    (("любовный роман", "любовные романы", "romance"), "love"),
    # Приключения
    (("вестерн", "western"), "adv_western"),
    (("морские приключения", "sea stories"), "adv_maritime"),
    (("путешествия", "travel"), "adv_geo"),
    (("приключения", "adventure"), "adventure"),
    # Детское
    (("сказки", "сказка", "fairy tales"), "child_tale"),
    (("детская фантастика", "juvenile fantasy", "young adult fantasy"), "child_sf"),
    (("детская литература", "детские книги", "children", "juvenile fiction"), "children"),
    # Поэзия и драматургия
    (("поэзия", "стихи", "poetry"), "poetry"),
    (("драматургия", "пьесы", "drama"), "dramaturgy"),
    # Наука, бизнес, IT, нон-фикшн
    (("программирование", "programming", "software engineering", "python", "algorithms"), "comp_programming"),
    (("компьютеры", "информатика", "computer science", "computers"), "computers"),
    (("бизнес", "экономика", "менеджмент", "business", "economics", "finance"), "sci_business"),
    (("психология", "саморазвитие", "psychology", "self-help"), "sci_psychology"),
    (("философия", "philosophy"), "sci_philosophy"),
    (("история", "history"), "sci_history"),
    (("политика", "политология", "political science"), "sci_politics"),
    (("медицина", "medicine"), "sci_medicine"),
    (("физика", "physics"), "sci_phys"),
    (("математика", "mathematics"), "sci_math"),
    (("биология", "biology"), "sci_biology"),
    (("научпоп", "научно-популярная", "science"), "science"),
    (("биография", "мемуары", "biography", "memoir", "autobiography"), "nonf_biography"),
    (("публицистика", "essays", "journalism"), "nonf_publicism"),
    (("документальная", "нон-фикшн", "nonfiction", "non-fiction"), "nonfiction"),
    (("религия", "religion"), "religion"),
    (("юмор", "сатира", "humor", "comedy"), "humor"),
    (("кулинария", "cooking"), "home_cooking"),
)


@dataclass
class BookMetadataCandidate:
    """Нормализованный кандидат метаданных и обложек от онлайн-провайдера."""

    provider: str
    provider_id: str = ""
    source_url: str = ""
    title: str = ""
    first: str = ""
    last: str = ""
    mid: str = ""
    series: str = ""
    num: str = ""
    genres: list = field(default_factory=list)
    lang: str = ""
    annotation: str = ""
    translator_first: str = ""
    translator_last: str = ""
    translator_middle: str = ""
    publisher: str = ""
    isbn: str = ""
    year: str = ""
    cover_urls: list = field(default_factory=list)
    score: float = 0.0

    def to_meta_patch(self):
        """Возвращает словарь полей, совместимый с форматом data['meta'] в FBC GUI."""
        return {
            "title": self.title,
            "first": self.first,
            "last": self.last,
            "mid": self.mid,
            "series": self.series,
            "num": self.num,
            "genres": list(self.genres),
            "lang": self.lang,
            "annotation": self.annotation,
            "translator_first": self.translator_first,
            "translator_last": self.translator_last,
            "translator_middle": self.translator_middle,
            "publisher": self.publisher,
            "isbn": self.isbn,
        }


@dataclass
class LookupResult:
    """Агрегированный результат онлайн-поиска по всем выбранным провайдерам."""

    candidates: list = field(default_factory=list)
    errors: dict = field(default_factory=dict)


def clean_annotation_text(raw):
    """Очищает HTML и BB-теги (FantLab/LitRes) в чистый текст аннотации с абзацами."""
    if not raw:
        return ""
    text = str(raw)
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*(?:p|div|li|h[1-6])\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[/?(?:b|i|u|s|p|quote|spoiler|url|color|size|left|right|center)(?:=[^\]]*)?\]", "", text, flags=re.IGNORECASE)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paras = []
    for chunk in re.split(r"\n{2,}", text):
        lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in chunk.split("\n")]
        cleaned_chunk = "\n".join(ln for ln in lines if ln)
        if cleaned_chunk:
            paras.append(cleaned_chunk)
    return "\n\n".join(paras).strip()


def split_author_name(full_name):
    """Разбирает строку имени автора в кортеж (first, mid, last)."""
    raw = re.sub(r"\s+", " ", str(full_name or "")).strip()
    if not raw:
        return "", "", ""
    if "," in raw:
        left, right = [p.strip() for p in raw.split(",", 1)]
        r_parts = right.split()
        if not r_parts:
            return "", "", left
        if len(r_parts) == 1:
            return r_parts[0], "", left
        return r_parts[0], " ".join(r_parts[1:]), left

    parts = raw.split()
    if len(parts) == 1:
        return "", "", parts[0]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    if re.search(r"(?:ович|евич|ич|овна|евна|ична|инична)$", parts[2], re.IGNORECASE):
        return parts[1], parts[2], parts[0]
    return parts[0], " ".join(parts[1:-1]), parts[-1]


def normalize_lang_code(raw):
    """Приводит код или название языка к 2-буквенному коду FB2 (ru, en, ...)."""
    if not raw:
        return ""
    token = str(raw).strip().lower().replace("_", "-")
    if "-" in token:
        token = token.split("-", 1)[0]
    if token in _LANG_MAP:
        return _LANG_MAP[token]
    if re.fullmatch(r"[a-z]{2}", token):
        return token
    return ""


def map_external_genres_to_fb2(raw_genres):
    """Преобразует внешние жанры/темы в канонические коды FictionBook 2.1."""
    if not raw_genres:
        return []
    items = [raw_genres] if isinstance(raw_genres, str) else list(raw_genres)

    mapped = []
    for item in items:
        raw_str = str(item or "").strip().lower()
        if not raw_str:
            continue
        if raw_str in KNOWN_GENRE_CODES:
            mapped.append(raw_str)
            continue
        for keywords, fb2_code in _GENRE_KEYWORD_RULES:
            if any(kw in raw_str for kw in keywords):
                mapped.append(fb2_code)
                break
    return normalize_genre_list(mapped)[:5]


def _normalize_compare_text(text):
    cleaned = re.sub(r"[^0-9a-zа-яё]+", " ", str(text or "").lower().replace("ё", "е"))
    return re.sub(r"\s+", " ", cleaned).strip()


def score_candidate(candidate, query_title="", query_author="", query_isbn=""):
    """Оценивает релевантность кандидата в диапазоне [0.0, 1.0]."""
    norm_q_isbn = normalize_isbn(query_isbn)
    norm_c_isbn = normalize_isbn(candidate.isbn)

    q_title = _normalize_compare_text(query_title)
    c_title = _normalize_compare_text(candidate.title)
    q_author = _normalize_compare_text(query_author)
    c_author = _normalize_compare_text(" ".join(p for p in (candidate.last, candidate.first) if p))

    title_sim = SequenceMatcher(None, q_title, c_title).ratio() if (q_title and c_title) else 0.0
    if q_title and c_title and (q_title in c_title or c_title in q_title):
        title_sim = max(title_sim, 0.85)

    author_sim = 0.0
    if q_author and c_author:
        q_tokens = set(q_author.split())
        c_tokens = set(c_author.split())
        if q_tokens & c_tokens:
            author_sim = max(
                len(q_tokens & c_tokens) / max(1, len(q_tokens)),
                SequenceMatcher(None, q_author, c_author).ratio(),
            )
        else:
            author_sim = SequenceMatcher(None, q_author, c_author).ratio()

    isbn_exact = bool(norm_q_isbn and norm_c_isbn and norm_q_isbn == norm_c_isbn)

    if norm_q_isbn:
        score = (0.55 if isbn_exact else 0.0) + 0.25 * title_sim + 0.12 * author_sim
    elif q_title and q_author:
        score = 0.62 * title_sim + 0.30 * author_sim
    elif q_title:
        score = 0.85 * title_sim
    elif q_author:
        score = 0.80 * author_sim
    else:
        score = 0.30

    completeness = 0.0
    if candidate.cover_urls:
        completeness += 0.04
    if candidate.annotation:
        completeness += 0.02
    if candidate.series:
        completeness += 0.01
    if candidate.genres:
        completeness += 0.01

    return round(min(1.0, max(0.0, score + completeness)), 4)


def _http_get_bytes(
    url,
    timeout=DEFAULT_TIMEOUT_SEC,
    headers=None,
    max_bytes=MAX_JSON_RESPONSE_BYTES,
    require_https=True,
):
    if not is_safe_http_url(url, allow_relative=False, require_https=require_https):
        raise ValueError(f"Unsupported URL scheme: {url}")
    req_headers = {
        "User-Agent": LOOKUP_USER_AGENT,
        "Accept": "application/json, application/atom+xml, application/xml, text/xml, */*;q=0.8",
    }
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    parsed = urllib.parse.urlsplit(url)
    ctx = _build_ssl_context() if parsed.scheme.lower() == "https" else None
    with safe_urlopen(req, timeout=timeout, context=ctx, require_https=require_https) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"Response exceeds size limit ({max_bytes} bytes)")
    return data


def _mask_secrets_in_text(text):
    """Маскирует API-ключи и Basic-токены в сообщениях об ошибках и логах."""
    s = str(text or "")
    s = re.sub(r"([?&]key=)[^&\s'\"]+", r"\1***", s, flags=re.IGNORECASE)
    s = re.sub(r"(Basic\s+)[A-Za-z0-9+/=]+", r"\1***", s, flags=re.IGNORECASE)
    return s


def _http_get_json(url, timeout=DEFAULT_TIMEOUT_SEC, headers=None, max_bytes=MAX_JSON_RESPONSE_BYTES):
    raw = _http_get_bytes(url, timeout=timeout, headers=headers, max_bytes=max_bytes, require_https=True)
    return json.loads(raw.decode("utf-8"))


def _basic_auth_header(username, password):
    user = str(username or "")
    pwd = str(password or "")
    if not user and not pwd:
        return {}
    token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _same_origin(url_a, url_b):
    try:
        pa = urllib.parse.urlsplit(str(url_a or ""))
        pb = urllib.parse.urlsplit(str(url_b or ""))
        if not pa.scheme or not pa.netloc or not pb.scheme or not pb.netloc:
            return False
        return pa.scheme.lower() == pb.scheme.lower() and pa.netloc.lower() == pb.netloc.lower()
    except Exception:
        return False


def _safe_parse_xml(raw_bytes):
    """Безопасно парсит XML (OPDS/OpenSearch) с защитой от XXE и Billion Laughs (включая UTF-16/UTF-32)."""
    if not raw_bytes:
        raise ValueError("Empty XML response")
    if len(raw_bytes) > MAX_JSON_RESPONSE_BYTES:
        raise ValueError("XML response exceeds size limit")
    lower_head = raw_bytes[:65536].lower()
    if b"<!doctype" in lower_head or b"<!entity" in lower_head:
        raise ValueError("XML DOCTYPE/ENTITY declarations are not allowed")
    def _reject_doctype(*_args):
        raise ValueError("XML DOCTYPE/ENTITY declarations are not allowed")
    expat_parser = _xml_expat.ParserCreate()
    expat_parser.StartDoctypeDeclHandler = _reject_doctype
    expat_parser.EntityDeclHandler = _reject_doctype
    try:
        expat_parser.Parse(raw_bytes, True)
    except _xml_expat.ExpatError:
        pass
    return ET.fromstring(raw_bytes)


def _xml_local_name(tag):
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower() if "}" in tag else tag.lower()


def _to_https_url(url, base_host=""):
    raw = str(url or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/") and base_host:
        raw = _https_url(base_host, raw)
    elif raw.lower().startswith("http://"):
        raw = "https://" + raw[7:]
    return raw if is_safe_http_url(raw, allow_relative=False, require_https=True) else ""


def _resolve_opds_url(href, base_url):
    raw = str(href or "").strip()
    if not raw:
        return ""
    resolved = urllib.parse.urljoin(str(base_url or ""), raw)
    return resolved if is_safe_http_url(resolved, allow_relative=False, require_https=False) else ""


def _detect_image_mime_from_bytes(raw_bytes):
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw_bytes.startswith(b"RIFF") and raw_bytes[8:12] == b"WEBP":
        return "image/webp"
    if raw_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return ""


def fit_cover_bytes_to_target(raw_bytes, mime="image/jpeg", target_size=COVER_TARGET_SIZE):
    """Подгоняет байты скачанной обложки под стандартный размер FB2-обложки."""
    if not raw_bytes:
        raise ValueError("Empty image data")
    if HAS_PIL:
        with Image.open(io.BytesIO(raw_bytes)) as im:
            im = im.convert("RGB")
            fitted = ImageOps.fit(im, target_size, method=Image.Resampling.LANCZOS)
            out = io.BytesIO()
            fitted.save(out, format="JPEG", quality=92)
            return out.getvalue(), "image/jpeg"
    return raw_bytes, (mime or "image/jpeg")


def download_cover_image(
    url,
    timeout=10.0,
    max_bytes=MAX_COVER_IMAGE_BYTES,
    allow_http=False,
    headers=None,
):
    """Безопасно скачивает и валидирует изображение обложки; возвращает (bytes, mime, width, height)."""
    if allow_http:
        target_url = str(url or "").strip()
        if not is_safe_http_url(target_url, allow_relative=False, require_https=False):
            raise ValueError(f"Invalid cover URL: {url}")
    else:
        target_url = _to_https_url(url)
        if not target_url:
            raise ValueError(f"Invalid cover URL: {url}")
    req_headers = {"Accept": "image/jpeg,image/png,image/webp,image/*;q=0.8"}
    if headers:
        req_headers.update(headers)
    raw = _http_get_bytes(
        target_url,
        timeout=timeout,
        headers=req_headers,
        max_bytes=max_bytes,
        require_https=not allow_http,
    )
    if len(raw) < 128:
        raise ValueError("Downloaded cover is too small or placeholder")

    mime = _detect_image_mime_from_bytes(raw)
    width = height = 0
    if HAS_PIL:
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            width, height = im.size
            fmt = (im.format or "").upper()
            fmt_mime = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "WEBP": "image/webp",
                "GIF": "image/gif",
            }.get(fmt)
            if fmt_mime:
                mime = fmt_mime
        if width < 60 or height < 80:
            raise ValueError(f"Cover dimensions too small ({width}x{height})")
    elif not mime:
        raise ValueError("Downloaded data is not a supported image")

    return raw, (mime or "image/jpeg"), width, height


def fetch_candidate_covers(
    candidates,
    max_covers=8,
    timeout=10.0,
    opds_url="",
    opds_username="",
    opds_password="",
    cancel_event=None,
):
    """Фаза 2: загружает и дедуплицирует обложки из списка кандидатов (по SHA-256)."""
    url_queue = []
    seen_urls = set()
    for cand in (candidates or []):
        is_opds = (cand.provider == "opds")
        for cu in (cand.cover_urls or []):
            norm_u = str(cu or "").strip() if is_opds else _to_https_url(cu)
            if is_opds and not is_safe_http_url(norm_u, allow_relative=False, require_https=False):
                norm_u = ""
            if norm_u and norm_u not in seen_urls:
                seen_urls.add(norm_u)
                url_queue.append((cand.provider, norm_u))
            if len(url_queue) >= max_covers * 2:
                break

    opds_auth = _basic_auth_header(opds_username, opds_password)
    results = []
    seen_hashes = set()
    for provider, url in url_queue:
        if cancel_event is not None and cancel_event.is_set():
            break
        if len(results) >= max_covers:
            break
        try:
            allow_http = (provider == "opds")
            extra_headers = opds_auth if (allow_http and opds_auth and _same_origin(url, opds_url)) else None
            raw, mime, w, h = download_cover_image(
                url,
                timeout=timeout,
                allow_http=allow_http,
                headers=extra_headers,
            )
            digest = hashlib.sha256(raw).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            results.append({
                "provider": provider,
                "url": url,
                "bytes": raw,
                "mime": mime,
                "width": w,
                "height": h,
                "sha256": digest,
            })
        except Exception as e:
            logger.debug("Не удалось загрузить обложку %s (%s): %s", url, provider, e)
    return results


class FantLabProvider:
    """Публичный API Лаборатории Фантастики (api.fantlab.ru) — без ключа."""

    provider_id = "fantlab"
    API_HOST = "api.fantlab.ru"
    WEB_HOST = "fantlab.ru"

    def search(self, title="", author="", isbn="", limit=4, timeout=DEFAULT_TIMEOUT_SEC, cancel_event=None):
        norm_isbn = normalize_isbn(isbn)
        query = norm_isbn or " ".join(p for p in (title.strip(), author.strip()) if p).strip()
        if not query:
            return []

        url = _https_url(self.API_HOST, "/search-works.json", {"q": query, "page": 1})
        data = _http_get_json(url, timeout=timeout)
        matches = data.get("matches") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        if not isinstance(matches, list):
            return []

        candidates = []
        for item in matches[:limit]:
            if cancel_event is not None and cancel_event.is_set():
                break
            if not isinstance(item, dict):
                continue
            work_id = item.get("work_id") or item.get("id")
            if not work_id:
                continue
            cand = self._candidate_from_search_item(item, str(work_id))
            try:
                details_url = _https_url(self.API_HOST, f"/work/{work_id}/extended")
                details = _http_get_json(details_url, timeout=timeout)
                if isinstance(details, dict):
                    self._enrich_from_work_details(cand, details)
            except Exception as e:
                logger.debug("FantLab work/%s details skipped: %s", work_id, e)
            candidates.append(cand)
        return candidates

    def _candidate_from_search_item(self, item, work_id):
        title = str(item.get("rusname") or item.get("name") or item.get("work_name") or "").strip()
        raw_author = str(item.get("autor_rusname") or item.get("autor") or item.get("author") or "").strip()
        if "," in raw_author and len(raw_author.split(",")) > 1:
            first_part = raw_author.split(",")[0].strip()
            if " " in first_part:
                raw_author = first_part
        first, mid, last = split_author_name(raw_author)
        year = str(item.get("year") or "").strip()
        return BookMetadataCandidate(
            provider=self.provider_id,
            provider_id=work_id,
            source_url=_https_url(self.WEB_HOST, f"/work{work_id}"),
            title=title,
            first=first,
            last=last,
            mid=mid,
            year=year if year != "0" else "",
        )

    def _enrich_from_work_details(self, cand, details):
        if details.get("work_name"):
            cand.title = str(details["work_name"]).strip()
        authors = details.get("authors")
        if isinstance(authors, list) and authors:
            a0 = authors[0]
            if isinstance(a0, dict) and a0.get("name"):
                cand.first, cand.mid, cand.last = split_author_name(a0["name"])

        if details.get("work_description"):
            cand.annotation = clean_annotation_text(details["work_description"])
        if details.get("work_year"):
            cand.year = str(details["work_year"]).strip()

        parents = details.get("parents")
        if isinstance(parents, dict):
            cycles = parents.get("cycles") or []
            if isinstance(cycles, list) and cycles:
                c0 = cycles[0]
                if isinstance(c0, list) and c0:
                    c0 = c0[0]
                if isinstance(c0, dict) and c0.get("work_name"):
                    cand.series = str(c0["work_name"]).strip()

        raw_genres = []
        for g_key in ("classificatory", "genres"):
            g_block = details.get(g_key)
            if isinstance(g_block, dict):
                for entry in (g_block.get("genre_group") or []):
                    if isinstance(entry, dict):
                        for g in (entry.get("genre") or []):
                            if isinstance(g, dict) and g.get("label"):
                                raw_genres.append(g["label"])
            elif isinstance(g_block, list):
                for g in g_block:
                    if isinstance(g, dict) and (g.get("label") or g.get("name")):
                        raw_genres.append(g.get("label") or g.get("name"))
                    elif isinstance(g, str):
                        raw_genres.append(g)
        if raw_genres:
            cand.genres = map_external_genres_to_fb2(raw_genres)

        img = _to_https_url(details.get("image") or details.get("image_preview"), self.WEB_HOST)
        if img and img not in cand.cover_urls:
            cand.cover_urls.append(img)

        editions_blocks = details.get("editions_blocks")
        if isinstance(editions_blocks, dict):
            for block in editions_blocks.values():
                if not isinstance(block, dict):
                    continue
                for ed in (block.get("list") or []):
                    if not isinstance(ed, dict):
                        continue
                    ed_id = ed.get("edition_id")
                    if ed_id:
                        big_url = _https_url(self.WEB_HOST, f"/images/editions/big/{ed_id}")
                        if big_url not in cand.cover_urls and len(cand.cover_urls) < 4:
                            cand.cover_urls.append(big_url)
                    if not cand.isbn and ed.get("isbn"):
                        cand.isbn = str(ed["isbn"]).strip()
                    if not cand.publisher and ed.get("creators"):
                        pub_val = ed["creators"]
                        if isinstance(pub_val, str):
                            cand.publisher = pub_val.strip()
                    if not cand.lang and ed.get("lang_code"):
                        cand.lang = normalize_lang_code(ed["lang_code"])

        translations = details.get("translations")
        if isinstance(translations, list) and translations:
            t0 = translations[0]
            if isinstance(t0, dict):
                tr_list = t0.get("translators") or []
                if isinstance(tr_list, list) and tr_list and isinstance(tr_list[0], dict):
                    tr_name = tr_list[0].get("name") or ""
                    cand.translator_first, cand.translator_middle, cand.translator_last = split_author_name(tr_name)

        if not cand.lang:
            cand.lang = "ru"


class LitResProvider:
    """Публичный витринный JSON-поиск LitRes (опциональный, изолирован от сбоев)."""

    provider_id = "litres"
    API_HOST = "api.litres.ru"
    WEB_HOST = "www.litres.ru"

    def search(self, title="", author="", isbn="", limit=5, timeout=DEFAULT_TIMEOUT_SEC, cancel_event=None):
        norm_isbn = normalize_isbn(isbn)
        query = norm_isbn or " ".join(p for p in (title.strip(), author.strip()) if p).strip()
        if not query:
            return []

        url = _https_url(
            self.API_HOST,
            "/foundation/api/search",
            {"q": query, "limit": max(1, min(limit, 10)), "types": "text_book"},
        )
        data = _http_get_json(url, timeout=timeout)
        payload = data.get("payload") if isinstance(data, dict) else {}
        items = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return []

        candidates = []
        for entry in items[:limit]:
            if cancel_event is not None and cancel_event.is_set():
                break
            if not isinstance(entry, dict):
                continue
            inst = entry.get("instance") if isinstance(entry.get("instance"), dict) else entry
            cand = self._parse_instance(inst)
            if cand and cand.title:
                candidates.append(cand)
        return candidates

    def _parse_instance(self, inst):
        title = str(inst.get("title") or "").strip()
        if not title:
            return None

        first = mid = last = ""
        tr_first = tr_mid = tr_last = ""
        for person in (inst.get("persons") or []):
            if not isinstance(person, dict):
                continue
            role = str(person.get("role") or "").lower()
            full_name = str(person.get("full_name") or "").strip()
            if not full_name:
                continue
            if role in ("author", "writer", "") and not last:
                first, mid, last = split_author_name(full_name)
            elif role == "translator" and not tr_last:
                tr_first, tr_mid, tr_last = split_author_name(full_name)

        series = ""
        num = ""
        series_list = inst.get("series") or []
        if isinstance(series_list, list) and series_list:
            s0 = series_list[0]
            if isinstance(s0, dict):
                series = str(s0.get("name") or "").strip()
                if s0.get("art_order") is not None:
                    num = str(s0["art_order"]).strip()

        raw_genres = []
        for g in (inst.get("genres") or []):
            if isinstance(g, dict) and g.get("name"):
                raw_genres.append(g["name"])
            elif isinstance(g, str):
                raw_genres.append(g)

        cover_urls = []
        for ckey in ("cover_url", "cover"):
            cu = _to_https_url(inst.get(ckey), self.WEB_HOST)
            if cu and cu not in cover_urls:
                cover_urls.append(cu)

        art_id = str(inst.get("id") or "")
        rel_url = str(inst.get("url") or "").strip()
        source_url = _to_https_url(rel_url, self.WEB_HOST) if rel_url else ""
        publisher = ""
        pub_raw = inst.get("publisher")
        if isinstance(pub_raw, dict):
            publisher = str(pub_raw.get("name") or "").strip()
        elif isinstance(pub_raw, str):
            publisher = pub_raw.strip()

        isbn_val = str(inst.get("isbn") or "").strip()
        if not isbn_val and isinstance(inst.get("isbns"), list) and inst["isbns"]:
            isbn_val = str(inst["isbns"][0]).strip()

        anno = clean_annotation_text(inst.get("annotation") or inst.get("html_annotation") or "")
        lang = normalize_lang_code(inst.get("language_code") or inst.get("lang") or "ru")

        return BookMetadataCandidate(
            provider=self.provider_id,
            provider_id=art_id,
            source_url=source_url,
            title=title,
            first=first,
            last=last,
            mid=mid,
            series=series,
            num=num,
            genres=map_external_genres_to_fb2(raw_genres),
            lang=lang,
            annotation=anno,
            translator_first=tr_first,
            translator_last=tr_last,
            translator_middle=tr_mid,
            publisher=publisher,
            isbn=isbn_val,
            year=str(inst.get("year") or "").strip(),
            cover_urls=cover_urls,
        )


class OpenLibraryProvider:
    """Публичный Open Library Search + Covers API (без ключа)."""

    provider_id = "openlibrary"
    WEB_HOST = "openlibrary.org"
    COVERS_HOST = "covers.openlibrary.org"

    def search(self, title="", author="", isbn="", limit=5, timeout=DEFAULT_TIMEOUT_SEC, cancel_event=None):
        norm_isbn = normalize_isbn(isbn)
        params = {
            "limit": max(1, min(limit, 10)),
            "fields": "key,title,author_name,isbn,publisher,first_publish_year,language,cover_i,subject",
        }
        if norm_isbn:
            params["isbn"] = norm_isbn
        else:
            if title.strip():
                params["title"] = title.strip()
            if author.strip():
                params["author"] = author.strip()
            if "title" not in params and "author" not in params:
                return []

        url = _https_url(self.WEB_HOST, "/search.json", params)
        data = _http_get_json(url, timeout=timeout)
        docs = data.get("docs") if isinstance(data, dict) else []
        if not isinstance(docs, list):
            return []

        candidates = []
        for doc in docs[:limit]:
            if cancel_event is not None and cancel_event.is_set():
                break
            if not isinstance(doc, dict):
                continue
            doc_title = str(doc.get("title") or "").strip()
            if not doc_title:
                continue
            authors = doc.get("author_name") or []
            first, mid, last = split_author_name(authors[0] if isinstance(authors, list) and authors else "")
            isbns = doc.get("isbn") or []
            chosen_isbn = norm_isbn if (norm_isbn and norm_isbn in [normalize_isbn(x) for x in isbns]) else (
                str(isbns[0]).strip() if isinstance(isbns, list) and isbns else ""
            )
            pubs = doc.get("publisher") or []
            publisher = str(pubs[0]).strip() if isinstance(pubs, list) and pubs else ""
            langs = doc.get("language") or []
            lang = normalize_lang_code(langs[0] if isinstance(langs, list) and langs else "")

            cover_urls = []
            cover_i = doc.get("cover_i")
            if cover_i:
                cover_urls.append(_https_url(self.COVERS_HOST, f"/b/id/{cover_i}-L.jpg", {"default": "false"}))
            norm_chosen = normalize_isbn(chosen_isbn)
            if norm_chosen:
                isbn_cov = _https_url(self.COVERS_HOST, f"/b/isbn/{norm_chosen}-L.jpg", {"default": "false"})
                if isbn_cov not in cover_urls:
                    cover_urls.append(isbn_cov)

            key = str(doc.get("key") or "").strip()
            source_url = _to_https_url(key, self.WEB_HOST) if key else ""
            subjects = doc.get("subject") if isinstance(doc.get("subject"), list) else []

            candidates.append(BookMetadataCandidate(
                provider=self.provider_id,
                provider_id=key,
                source_url=source_url,
                title=doc_title,
                first=first,
                last=last,
                mid=mid,
                genres=map_external_genres_to_fb2(subjects[:12]),
                lang=lang,
                publisher=publisher,
                isbn=chosen_isbn,
                year=str(doc.get("first_publish_year") or "").strip(),
                cover_urls=cover_urls,
            ))
        return candidates


class GoogleBooksProvider:
    """Google Books API v1 — активируется только при наличии пользовательского API-ключа."""

    provider_id = "googlebooks"
    API_HOST = "www.googleapis.com"

    def __init__(self, api_key=""):
        self.api_key = str(api_key or "").strip()

    def search(self, title="", author="", isbn="", limit=5, timeout=DEFAULT_TIMEOUT_SEC, cancel_event=None):
        if not self.api_key:
            return []
        norm_isbn = normalize_isbn(isbn)
        q = f"isbn:{norm_isbn}" if norm_isbn else " ".join(p for p in (title.strip(), author.strip()) if p).strip()
        if not q:
            return []

        url = _https_url(
            self.API_HOST,
            "/books/v1/volumes",
            {"q": q, "maxResults": max(1, min(limit, 10))},
        )
        data = _http_get_json(url, timeout=timeout, headers={"X-Goog-Api-Key": self.api_key})
        items = data.get("items") if isinstance(data, dict) else []
        if not isinstance(items, list):
            return []

        candidates = []
        for item in items[:limit]:
            if cancel_event is not None and cancel_event.is_set():
                break
            if not isinstance(item, dict):
                continue
            vi = item.get("volumeInfo")
            if not isinstance(vi, dict):
                continue
            v_title = str(vi.get("title") or "").strip()
            if not v_title:
                continue
            authors = vi.get("authors") or []
            first, mid, last = split_author_name(authors[0] if isinstance(authors, list) and authors else "")

            isbn_val = ""
            for ident in (vi.get("industryIdentifiers") or []):
                if not isinstance(ident, dict):
                    continue
                itype = str(ident.get("type") or "").upper()
                ival = str(ident.get("identifier") or "").strip()
                if itype == "ISBN_13" and ival:
                    isbn_val = ival
                    break
                if itype == "ISBN_10" and ival and not isbn_val:
                    isbn_val = ival

            cover_urls = []
            img_links = vi.get("imageLinks")
            if isinstance(img_links, dict):
                for size_key in ("extraLarge", "large", "medium", "thumbnail", "smallThumbnail"):
                    cu = _to_https_url(img_links.get(size_key))
                    if cu and cu not in cover_urls:
                        cover_urls.append(cu)

            pub_date = str(vi.get("publishedDate") or "").strip()
            year = pub_date[:4] if len(pub_date) >= 4 and pub_date[:4].isdigit() else ""
            categories = vi.get("categories") if isinstance(vi.get("categories"), list) else []

            candidates.append(BookMetadataCandidate(
                provider=self.provider_id,
                provider_id=str(item.get("id") or ""),
                source_url=_to_https_url(vi.get("infoLink") or vi.get("canonicalVolumeLink")),
                title=v_title,
                first=first,
                last=last,
                mid=mid,
                genres=map_external_genres_to_fb2(categories),
                lang=normalize_lang_code(vi.get("language") or ""),
                annotation=clean_annotation_text(vi.get("description") or ""),
                publisher=str(vi.get("publisher") or "").strip(),
                isbn=isbn_val,
                year=year,
                cover_urls=cover_urls,
            ))
        return candidates


class OpdsProvider:
    """Универсальный OPDS-провайдер (Atom XML + OpenSearch, HTTP/HTTPS, опциональная Basic Auth)."""

    provider_id = "opds"

    def __init__(self, opds_url="", username="", password=""):
        self.opds_url = str(opds_url or "").strip()
        self.username = str(username or "").strip()
        self.password = str(password or "")
        self._search_template = None

    def _headers_for(self, url):
        hdrs = {"Accept": "application/atom+xml, application/opensearchdescription+xml, application/xml, text/xml, */*;q=0.5"}
        auth = _basic_auth_header(self.username, self.password)
        if auth and _same_origin(url, self.opds_url):
            hdrs.update(auth)
        return hdrs

    def _fetch_xml(self, url, timeout=DEFAULT_TIMEOUT_SEC):
        raw = _http_get_bytes(
            url,
            timeout=timeout,
            headers=self._headers_for(url),
            max_bytes=MAX_JSON_RESPONSE_BYTES,
            require_https=False,
        )
        return _safe_parse_xml(raw)

    def _discover_search_template(self, timeout=DEFAULT_TIMEOUT_SEC):
        if self._search_template:
            return self._search_template
        if "{searchTerms}" in self.opds_url:
            self._search_template = self.opds_url
            return self._search_template

        root = self._fetch_xml(self.opds_url, timeout=timeout)
        search_links = []
        for child in root:
            if _xml_local_name(child.tag) != "link":
                continue
            rel = str(child.attrib.get("rel") or "").strip().lower()
            if rel != "search":
                continue
            href = _resolve_opds_url(child.attrib.get("href"), self.opds_url)
            ltype = str(child.attrib.get("type") or "").strip().lower()
            if href:
                search_links.append((ltype, href))

        # 1. Прямой шаблон {searchTerms} в Atom-ссылке (Calibre-Web, Kavita и др.)
        for ltype, href in search_links:
            if "{searchTerms}" in href and ("atom+xml" in ltype or not ltype):
                self._search_template = href
                return self._search_template

        # 2. OpenSearch Description XML (Flibusta и стандартные OPDS 1.2 каталоги)
        for ltype, href in search_links:
            if "opensearchdescription" in ltype or href.lower().endswith(".xml"):
                try:
                    os_root = self._fetch_xml(href, timeout=timeout)
                    tpl = self._extract_opensearch_template(os_root, href)
                    if tpl:
                        self._search_template = tpl
                        return self._search_template
                except Exception as e:
                    logger.debug("OPDS OpenSearch fetch failed (%s): %s", href, e)

        # 3. Если rel="search" вернул обычный URL без шаблона
        if search_links:
            href = search_links[0][1]
            sep = "&" if "?" in href else "?"
            self._search_template = f"{href}{sep}searchTerm={{searchTerms}}"
            return self._search_template

        # 4. Fallback для каталогов без <link rel="search">
        base = self.opds_url.rstrip("/")
        self._search_template = f"{base}/search?searchTerm={{searchTerms}}&searchType=books"
        return self._search_template

    def _extract_opensearch_template(self, os_root, base_url):
        fallback_tpl = ""
        for el in os_root.iter():
            if _xml_local_name(el.tag) != "url":
                continue
            tpl = str(el.attrib.get("template") or "").strip()
            if not tpl:
                continue
            resolved = _resolve_opds_url(tpl, base_url)
            if not resolved:
                continue
            ltype = str(el.attrib.get("type") or "").strip().lower()
            if "atom+xml" in ltype:
                return resolved
            if not fallback_tpl:
                fallback_tpl = resolved
        return fallback_tpl

    def _build_search_url(self, template, query):
        encoded = urllib.parse.quote_plus(query)
        url = template.replace("{searchTerms}", encoded)
        url = re.sub(r"\{[a-zA-Z0-9_:]+\?\}", "", url)
        url = re.sub(r"\{[a-zA-Z0-9_:]+\}", "", url)
        return url

    def search(self, title="", author="", isbn="", limit=5, timeout=DEFAULT_TIMEOUT_SEC, cancel_event=None):
        if not is_safe_http_url(self.opds_url, allow_relative=False, require_https=False):
            return []
        norm_isbn = normalize_isbn(isbn)
        query = norm_isbn or " ".join(p for p in (title.strip(), author.strip()) if p).strip()
        if not query:
            return []

        template = self._discover_search_template(timeout=timeout)
        if cancel_event is not None and cancel_event.is_set():
            return []

        search_url = self._build_search_url(template, query)
        feed_root = self._fetch_xml(search_url, timeout=timeout)

        candidates = []
        for el in feed_root:
            if cancel_event is not None and cancel_event.is_set():
                break
            if _xml_local_name(el.tag) != "entry":
                continue
            cand = self._parse_entry(el, search_url)
            if cand is not None:
                candidates.append(cand)
            if len(candidates) >= limit:
                break
        return candidates

    def _parse_entry(self, entry, base_url):
        title = ""
        entry_id = ""
        author_name = ""
        lang = ""
        publisher = ""
        year = ""
        isbn = ""
        annotation = ""
        raw_genres = []
        full_covers = []
        thumb_covers = []
        source_url = ""
        has_acquisition = False

        for child in entry:
            lname = _xml_local_name(child.tag)
            txt = "".join(child.itertext()).strip()
            if lname == "title" and not title:
                title = txt
            elif lname == "id" and not entry_id:
                entry_id = txt
            elif lname == "author" and not author_name:
                for sub in child:
                    if _xml_local_name(sub.tag) == "name":
                        author_name = "".join(sub.itertext()).strip()
                        if author_name:
                            break
            elif lname == "category":
                label = str(child.attrib.get("label") or child.attrib.get("term") or "").strip()
                if label:
                    raw_genres.append(label)
            elif lname == "language" and not lang:
                lang = normalize_lang_code(txt)
            elif lname == "publisher" and not publisher:
                publisher = txt
            elif lname in ("issued", "date", "published") and not year:
                m_yr = re.search(r"\b((?:1[5-9]|20)\d{2})\b", txt)
                if m_yr:
                    year = m_yr.group(1)
            elif lname == "identifier" and not isbn:
                cleaned_id = re.sub(r"^urn:isbn:", "", txt, flags=re.IGNORECASE).strip()
                if normalize_isbn(cleaned_id):
                    isbn = cleaned_id
            elif lname in ("content", "summary"):
                cleaned = clean_annotation_text(txt)
                if cleaned and (not annotation or lname == "content"):
                    annotation = cleaned
            elif lname == "link":
                rel = str(child.attrib.get("rel") or "").strip().lower()
                href = _resolve_opds_url(child.attrib.get("href"), base_url)
                ltype = str(child.attrib.get("type") or "").strip().lower()
                if not href:
                    continue
                if "opds-spec.org/acquisition" in rel:
                    has_acquisition = True
                if rel.endswith("/image") or rel == "x-stanza-cover-image":
                    if href not in full_covers:
                        full_covers.append(href)
                elif rel.endswith("/image/thumbnail") or rel == "x-stanza-cover-image-thumbnail":
                    if href not in thumb_covers:
                        thumb_covers.append(href)
                elif rel == "alternate" and not source_url:
                    if "html" in ltype or not ltype:
                        source_url = href

        if not title:
            return None
        # Пропускаем чисто навигационные узлы каталога
        if not (author_name or full_covers or thumb_covers or has_acquisition or annotation or isbn):
            return None

        first, mid, last = split_author_name(author_name)
        cover_urls = full_covers + [u for u in thumb_covers if u not in full_covers]

        return BookMetadataCandidate(
            provider=self.provider_id,
            provider_id=entry_id,
            source_url=source_url,
            title=title,
            first=first,
            last=last,
            mid=mid,
            genres=map_external_genres_to_fb2(raw_genres),
            lang=lang,
            annotation=annotation,
            publisher=publisher,
            isbn=isbn,
            year=year,
            cover_urls=cover_urls[:4],
        )


def build_providers(
    enabled_providers=None,
    google_books_api_key="",
    opds_url="",
    opds_username="",
    opds_password="",
):
    """Создаёт список активных провайдеров в заданном порядке."""
    order = tuple(enabled_providers) if enabled_providers else DEFAULT_PROVIDER_ORDER
    providers = []
    for pid in order:
        key = str(pid or "").strip().lower()
        if key == "fantlab":
            providers.append(FantLabProvider())
        elif key == "litres":
            providers.append(LitResProvider())
        elif key == "openlibrary":
            providers.append(OpenLibraryProvider())
        elif key == "googlebooks" and str(google_books_api_key or "").strip():
            providers.append(GoogleBooksProvider(api_key=google_books_api_key))
        elif key == "opds" and is_safe_http_url(str(opds_url or "").strip(), allow_relative=False, require_https=False):
            providers.append(OpdsProvider(opds_url=opds_url, username=opds_username, password=opds_password))
    return providers


def search_book_metadata(
    title="",
    author="",
    isbn="",
    enabled_providers=None,
    google_books_api_key="",
    opds_url="",
    opds_username="",
    opds_password="",
    limit_per_provider=4,
    min_score=0.25,
    timeout=DEFAULT_TIMEOUT_SEC,
    cancel_event=None,
):
    """Фаза 1: параллельно опрашивает активные провайдеры, ранжирует и фильтрует кандидатов."""
    providers = build_providers(
        enabled_providers=enabled_providers,
        google_books_api_key=google_books_api_key,
        opds_url=opds_url,
        opds_username=opds_username,
        opds_password=opds_password,
    )
    if not providers:
        return LookupResult()

    all_candidates = []
    errors = {}

    def _run_one(prov):
        if cancel_event is not None and cancel_event.is_set():
            return []
        return prov.search(
            title=title,
            author=author,
            isbn=isbn,
            limit=limit_per_provider,
            timeout=timeout,
            cancel_event=cancel_event,
        )

    max_workers = min(5, len(providers))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(_run_one, p): p.provider_id for p in providers}
        for fut in as_completed(future_map):
            pid = future_map[fut]
            try:
                items = fut.result() or []
                all_candidates.extend(items)
            except Exception as e:
                safe_err = _mask_secrets_in_text(e)
                logger.warning("Провайдер метаданных %s завершился с ошибкой: %s", pid, safe_err)
                errors[pid] = safe_err

    scored = []
    for cand in all_candidates:
        cand.score = score_candidate(cand, query_title=title, query_author=author, query_isbn=isbn)
        if cand.score >= min_score:
            scored.append(cand)

    scored.sort(key=lambda c: c.score, reverse=True)
    return LookupResult(candidates=scored, errors=errors)

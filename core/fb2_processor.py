import os
import re
import io
import html
import shutil
import base64
import zipfile
import tempfile
import threading
import subprocess
import xml.etree.ElementTree as ET

from core.logger import get_logger

logger = get_logger("fb2_processor")
_DEST_MOVE_LOCK = threading.Lock()


class ConversionCancelledError(Exception):
    """Исключение, выбрасываемое при немедленной отмене конвертации пользователем."""

try:
    from lxml import etree as LXML_ET
    HAS_LXML = True
except ImportError:
    LXML_ET = None
    HAS_LXML = False

try:
    from PIL import Image, ImageOps
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

DEFAULT_OUTPUT_FORMAT = "epub3"

COVER_TARGET_SIZE = (600, 900)
COVER_PREVIEW_SIZE = (180, 270)

FORMAT_EXT_MAP = {
    "epub2": ".epub", "epub3": ".epub", "kepub": ".kepub.epub",
    "kepub3": ".kepub.epub", "azw3": ".azw3", "kfx": ".kfx", "azw8": ".azw8",
    "pdf": ".pdf", "txt": ".txt", "md": ".md"
}
EPUB_BASED_FORMATS = {"epub2", "epub3", "kepub", "kepub3"}

FILENAME_TAG_IDS = ("title", "series", "series_abbr", "num", "last", "first", "mid", "format")
TITLE_TAG_IDS = ("title", "series", "series_abbr", "num", "last", "first", "mid")

DEFAULT_FILENAME_TOKENS = [
    {"type": "tag", "id": "last"},
    {"type": "text", "value": " - "},
    {"type": "text", "value": "("},
    {"type": "tag", "id": "series_abbr"},
    {"type": "text", "value": " - "},
    {"type": "tag", "id": "num"},
    {"type": "text", "value": ") "},
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
ET.register_namespace('', FB2_NS)
ET.register_namespace('l', XLINK_NS)


def extract_fb2_xml(filepath):
    if filepath.lower().endswith('.zip'):
        with zipfile.ZipFile(filepath, 'r') as z:
            for name in z.namelist():
                if name.lower().endswith('.fb2'):
                    return z.read(name)
    else:
        with open(filepath, 'rb') as f:
            return f.read()
    return None


def collect_book_paths(paths):
    """Рекурсивно собирает пути к .fb2 и .zip файлам из списка файлов и папок."""
    collected = []
    seen = set()

    def _add(fp):
        norm = os.path.abspath(fp)
        if norm not in seen:
            seen.add(norm)
            collected.append(fp)

    for raw_path in paths:
        if not raw_path:
            continue
        if os.path.isdir(raw_path):
            for root_dir, dirs, files in os.walk(raw_path):
                dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d != '__MACOSX')
                for fname in sorted(files):
                    if fname.startswith('._'):
                        continue
                    if fname.lower().endswith(('.fb2', '.zip')):
                        _add(os.path.join(root_dir, fname))
        elif os.path.isfile(raw_path):
            bname = os.path.basename(raw_path)
            if not bname.startswith('._') and raw_path.lower().endswith(('.fb2', '.zip')):
                _add(raw_path)

    return collected


def collect_startup_paths(argv):
    """Извлекает пути к файлам/папкам из аргументов командной строки, игнорируя флаги (в т.ч. macOS -psn_*)."""
    paths = []
    seen = set()
    for arg in (argv or [])[1:]:
        if not arg or arg.startswith("-"):
            continue
        candidate = arg
        if candidate.startswith("file://"):
            from urllib.parse import urlparse, unquote
            parsed = urlparse(candidate)
            candidate = unquote(parsed.path)
            if os.name == "nt" and len(candidate) >= 3 and candidate[0] == "/" and candidate[2] == ":":
                candidate = candidate[1:]
        if not os.path.exists(candidate):
            continue
        if os.path.isdir(candidate) or candidate.lower().endswith(('.fb2', '.zip')):
            norm = os.path.abspath(candidate)
            if norm not in seen:
                seen.add(norm)
                paths.append(candidate)
    return paths


def book_matches_filter(data, query="", status_filter="all", target_name=""):
    """Проверяет, соответствует ли запись книги текстовому поиску и фильтру статуса."""
    if not isinstance(data, dict):
        return False

    sf = (status_filter or "all").strip().lower()
    st = (data.get("status") or "").strip().lower()
    if sf == "ok" and st != "ok":
        return False
    if sf == "error" and st != "error":
        return False
    if sf == "pending" and st in ("ok", "error"):
        return False

    q = (query or "").strip().lower()
    if not q:
        return True

    meta = data.get("meta") or {}
    haystack_parts = [
        data.get("display_name") or "",
        os.path.basename(data.get("path") or ""),
        meta.get("last") or "",
        meta.get("first") or "",
        meta.get("mid") or "",
        meta.get("series") or "",
        meta.get("num") or "",
        meta.get("title") or "",
        target_name or "",
    ]
    haystack = " ".join(str(p) for p in haystack_parts if p).lower()
    return all(token in haystack for token in q.split())


def iter_fb2_from_file(filepath):
    """Генерирует кортежи (source_key, archive_entry, display_name, xml_bytes) для всех FB2 внутри файла или ZIP."""
    abs_path = os.path.abspath(filepath)
    base_name = os.path.basename(filepath)

    if filepath.lower().endswith('.zip'):
        try:
            with zipfile.ZipFile(filepath, 'r') as z:
                fb2_names = []
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    name = info.filename
                    parts = name.replace('\\', '/').split('/')
                    if '__MACOSX' in parts or (parts and parts[-1].startswith('._')):
                        continue
                    if name.lower().endswith('.fb2'):
                        fb2_names.append(name)

                fb2_names.sort()
                multi = len(fb2_names) > 1
                for entry_name in fb2_names:
                    try:
                        xml_bytes = z.read(entry_name)
                    except Exception:
                        continue
                    if not xml_bytes:
                        continue
                    inner_base = os.path.basename(entry_name.replace('\\', '/'))
                    display_name = f"{base_name} / {inner_base}" if multi else base_name
                    source_key = f"{abs_path}::{entry_name}"
                    yield (source_key, entry_name, display_name, xml_bytes)
        except Exception:
            return
    else:
        try:
            with open(filepath, 'rb') as f:
                xml_bytes = f.read()
            if xml_bytes:
                yield (abs_path, None, base_name, xml_bytes)
        except Exception:
            return


def extract_all_fb2_from_file(filepath):
    """Возвращает список (source_key, display_name, xml_bytes) для всех FB2 внутри файла или ZIP-архива."""
    return [(sk, dn, xb) for sk, _ae, dn, xb in iter_fb2_from_file(filepath)]


def load_book_xml(filepath, archive_entry=None):
    """Лениво загружает сырые байты FB2 с диска или из конкретного файла внутри ZIP-архива."""
    if not filepath or not os.path.isfile(filepath):
        return None
    try:
        if archive_entry is not None:
            with zipfile.ZipFile(filepath, 'r') as z:
                return z.read(archive_entry)
        if filepath.lower().endswith('.zip'):
            return extract_fb2_xml(filepath)
        with open(filepath, 'rb') as f:
            return f.read()
    except Exception as e:
        logger.warning("Не удалось прочитать исходный FB2 %s (%s): %s", filepath, archive_entry or "", e)
        return None


def get_book_xml(data):
    """Возвращает XML книги из кэша (если есть) или загружает с диска по требованию."""
    if not isinstance(data, dict):
        return None
    cached = data.get('xml')
    if cached:
        return cached
    return load_book_xml(data.get('path'), data.get('archive_entry'))


_XML_ILLEGAL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')
_XML_ENCODING_RE = re.compile(rb'encoding\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_BARE_AMP_RE = re.compile(r'&(?!(?:[a-zA-Z][a-zA-Z0-9._-]*|#\d+|#x[0-9a-fA-F]+);)')


def _decode_fb2_text(xml_bytes):
    """Декодирует байты FB2 с учётом BOM, объявленной кодировки и фоллбэков (UTF-8 / Windows-1251 / KOI8-R)."""
    if isinstance(xml_bytes, str):
        text = xml_bytes
    else:
        raw = xml_bytes.lstrip(b'\xef\xbb\xbf\r\n\t ')
        first_lt = raw.find(b'<')
        if first_lt > 0:
            raw = raw[first_lt:]
        encodings = []
        m_enc = _XML_ENCODING_RE.search(raw[:256])
        if m_enc:
            try:
                encodings.append(m_enc.group(1).decode('ascii', errors='ignore').strip())
            except Exception:
                pass
        for enc in ('utf-8', 'windows-1251', 'koi8-r', 'latin1'):
            if enc not in [e.lower() for e in encodings]:
                encodings.append(enc)
        text = None
        for enc in encodings:
            try:
                text = raw.decode(enc)
                break
            except (LookupError, UnicodeDecodeError):
                continue
        if text is None:
            text = raw.decode('utf-8', errors='replace')
    return _XML_ILLEGAL_CHARS_RE.sub('', text)


def _sanitize_fb2_xml_text(text):
    """Исправляет частые дефекты битых FB2: неэкранированные &, кодировку в заголовке и отсутствующий xmlns:l."""
    clean = _BARE_AMP_RE.sub('&amp;', text)
    clean = re.sub(
        r'(<\?xml\b[^>]*?encoding\s*=\s*)(["\'])[^"\']+\2',
        r'\1\2utf-8\2',
        clean,
        count=1,
        flags=re.IGNORECASE,
    )
    m_root = re.search(r'<FictionBook\b[^>]*>', clean, re.IGNORECASE)
    if m_root:
        root_tag = m_root.group(0)
        updated_tag = root_tag
        if 'l:href' in clean and 'xmlns:l=' not in updated_tag:
            updated_tag = updated_tag[:-1] + f' xmlns:l="{XLINK_NS}">'
        if 'xlink:href' in clean and 'xmlns:xlink=' not in updated_tag:
            updated_tag = updated_tag[:-1] + f' xmlns:xlink="{XLINK_NS}">'
        if updated_tag != root_tag:
            clean = clean[:m_root.start()] + updated_tag + clean[m_root.end():]
    return clean


def _parse_fb2_root(xml_bytes):
    """Пытается распарсить FB2: сначала напрямую, затем после санитизации и через lxml (если доступен)."""
    try:
        return ET.fromstring(xml_bytes)
    except Exception:
        pass

    clean_bytes = None
    try:
        clean_text = _sanitize_fb2_xml_text(_decode_fb2_text(xml_bytes))
        clean_bytes = clean_text.encode('utf-8')
        return ET.fromstring(clean_bytes)
    except Exception:
        pass

    if HAS_LXML:
        try:
            parser = LXML_ET.XMLParser(recover=True)
            l_root = LXML_ET.fromstring(clean_bytes or xml_bytes, parser=parser)
            if l_root is not None:
                return ET.fromstring(LXML_ET.tostring(l_root, encoding='utf-8'))
        except Exception:
            pass

    return None


def _get_root_ns_uri(root):
    if root is not None and root.tag.startswith('{'):
        return root.tag[1:].split('}', 1)[0]
    return ""


def _qtag(ns_uri, local_name):
    return f'{{{ns_uri}}}{local_name}' if ns_uri else local_name


def _find_title_info(root):
    ns_uri = _get_root_ns_uri(root)
    if ns_uri:
        ti = root.find(f'.//{{{ns_uri}}}description/{{{ns_uri}}}title-info')
        if ti is not None:
            return ti, ns_uri
    ti = root.find('.//description/title-info')
    if ti is not None:
        return ti, ""
    for el in root.iter():
        if el.tag.endswith('title-info'):
            el_ns = el.tag[1:].split('}', 1)[0] if el.tag.startswith('{') else ""
            return el, el_ns
    return None, ns_uri


def _extract_cover_fallback(xml_bytes):
    """Резервное извлечение обложки из битого FB2 регулярными выражениями."""
    text = _decode_fb2_text(xml_bytes)
    cover_id = None
    m_cp = re.search(r'<coverpage\b[^>]*>(.*?)</coverpage>', text, re.IGNORECASE | re.DOTALL)
    if m_cp:
        m_href = re.search(r'href\s*=\s*["\']#([^"\']+)["\']', m_cp.group(1), re.IGNORECASE)
        if m_href:
            cover_id = html.unescape(m_href.group(1).strip())

    first_img = None
    for m_bin in re.finditer(r'<binary\b([^>]*)>(.*?)</binary>', text, re.IGNORECASE | re.DOTALL):
        attrs, b64_body = m_bin.group(1), m_bin.group(2)
        m_id = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        m_ct = re.search(r'content-type\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        bin_id = html.unescape(m_id.group(1).strip()) if m_id else ""
        ctype = m_ct.group(1).strip() if m_ct else "image/jpeg"
        if cover_id and bin_id == cover_id:
            try:
                return base64.b64decode("".join(b64_body.split())), ctype
            except Exception:
                pass
        if first_img is None and ctype.lower().startswith('image/'):
            try:
                first_img = (base64.b64decode("".join(b64_body.split())), ctype)
            except Exception:
                pass
    return first_img if first_img else (None, None)


def extract_cover_from_fb2(xml_bytes):
    try:
        root = _parse_fb2_root(xml_bytes)
        if root is None:
            return _extract_cover_fallback(xml_bytes)
        ti, ns_uri = _find_title_info(root)
        cover_id = None
        if ti is not None:
            cp = ti.find(_qtag(ns_uri, 'coverpage'))
            cover_img = cp.find(_qtag(ns_uri, 'image')) if cp is not None else None
            if cover_img is not None:
                for k, v in cover_img.attrib.items():
                    if k.endswith('href') and v.startswith('#'):
                        cover_id = v[1:]
                        break
        root_ns = _get_root_ns_uri(root)
        binaries = root.findall(_qtag(root_ns, 'binary'))
        if not binaries:
            binaries = [el for el in root.iter() if el.tag.endswith('binary')]
        if cover_id:
            for bin_el in binaries:
                if bin_el.attrib.get('id') == cover_id and bin_el.text:
                    return base64.b64decode("".join(bin_el.text.split())), bin_el.attrib.get('content-type', 'image/jpeg')
        for bin_el in binaries:
            if bin_el.attrib.get('content-type', '').startswith('image/') and bin_el.text:
                return base64.b64decode("".join(bin_el.text.split())), bin_el.attrib.get('content-type')
    except Exception:
        try:
            return _extract_cover_fallback(xml_bytes)
        except Exception:
            pass
    return None, None


def fit_image_to_cover_size(image_path, target_size=COVER_TARGET_SIZE):
    target_w, target_h = target_size
    if HAS_PIL:
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            fitted = ImageOps.fit(im, (target_w, target_h), method=Image.Resampling.LANCZOS)
            out = io.BytesIO()
            fitted.save(out, format="JPEG", quality=92)
            return out.getvalue(), "image/jpeg"
    with open(image_path, "rb") as f:
        return f.read(), "image/jpeg"


def _get_tag_values(meta, output_format=DEFAULT_OUTPUT_FORMAT):
    title = (meta.get("title") or "").strip()
    series = (meta.get("series") or "").strip()
    num_raw = (meta.get("num") or "").strip()
    series_abbr = "".join(w[0].upper() for w in series.split() if w) if series else ""
    if num_raw and num_raw.isdigit() and int(num_raw) > 0:
        num_str = f"{int(num_raw):02d}"
    else:
        num_str = num_raw if (num_raw and num_raw != "0") else ""
    return {
        "title": title,
        "series": series,
        "series_abbr": series_abbr,
        "num": num_str,
        "last": (meta.get("last") or "").strip(),
        "first": (meta.get("first") or "").strip(),
        "mid": (meta.get("mid") or "").strip(),
        "format": (output_format or DEFAULT_OUTPUT_FORMAT).lower(),
    }


def _parse_token_segments(tokens):
    """Разбивает плоский список токенов на сегменты верхнего уровня, выделяя группы в скобках (...)/[...]."""
    norm = []
    for t in (tokens or []):
        if not isinstance(t, dict):
            continue
        ttype = t.get("type")
        if ttype == "tag" and t.get("id") in FILENAME_TAG_IDS:
            norm.append({"type": "tag", "id": t["id"]})
        elif ttype == "text" and t.get("value"):
            val = str(t["value"])
            buf = ""
            for ch in val:
                if ch in ("(", ")", "[", "]"):
                    if buf:
                        norm.append({"type": "text", "value": buf})
                        buf = ""
                    norm.append({"type": "text", "value": ch})
                else:
                    buf += ch
            if buf:
                norm.append({"type": "text", "value": buf})

    segments = []
    i = 0
    n = len(norm)
    while i < n:
        tok = norm[i]
        if tok["type"] == "text" and tok["value"] in ("(", "["):
            open_br = tok["value"]
            close_br = ")" if open_br == "(" else "]"
            j = i + 1
            inner = []
            found_close = False
            has_tag = False
            while j < n:
                if norm[j]["type"] == "text" and norm[j]["value"] == close_br:
                    found_close = True
                    break
                if norm[j]["type"] == "tag":
                    has_tag = True
                inner.append(norm[j])
                j += 1
            if found_close and has_tag:
                segments.append({"type": "group", "open": open_br, "close": close_br, "items": inner})
                i = j + 1
                continue
        segments.append(tok)
        i += 1
    return segments


def _join_items_smart(items, eval_fn):
    """Соединяет непустые элементы, автоматически скрывая разделители вокруг пустых тегов."""
    out_parts = []
    pending_sep = ""
    has_any = False
    skipped_empty = False
    for it in items:
        if it["type"] == "text":
            pending_sep += it["value"]
        else:
            val = eval_fn(it)
            if val:
                if has_any and pending_sep:
                    sep = re.sub(r' {2,}', ' ', pending_sep) if skipped_empty else pending_sep
                    out_parts.append(sep)
                out_parts.append(val)
                pending_sep = ""
                has_any = True
                skipped_empty = False
            else:
                skipped_empty = True
                if not has_any:
                    pending_sep = ""
    return "".join(out_parts)


def render_filename_from_tokens(tokens, meta, output_format=DEFAULT_OUTPUT_FORMAT, for_metadata_title=False):
    values = _get_tag_values(meta, output_format)
    segments = _parse_token_segments(tokens)

    def _eval_seg(seg):
        if seg["type"] == "tag":
            return values.get(seg["id"], "")
        if seg["type"] == "group":
            inner_txt = _join_items_smart(seg["items"], lambda x: values.get(x["id"], ""))
            return f"{seg['open']}{inner_txt}{seg['close']}" if inner_txt else ""
        return ""

    rendered = _join_items_smart(segments, _eval_seg).strip()
    if not rendered:
        rendered = values["title"] or "book"
    if for_metadata_title:
        return rendered
    return rendered.replace("/", "\u2215").replace("\\", "\u2215")


def render_title_metadata_preview(tokens, meta):
    """Формирует превью заголовка книги в метаданных (без расширения файла и замены слешей)."""
    return render_filename_from_tokens(tokens, meta, for_metadata_title=True)


def _go_quote(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def build_fbc_output_name_template(tokens, for_metadata_title=False):
    """Генерирует Go text/template для config.yaml (output_name_template или metainformation.title_template)."""
    segments = _parse_token_segments(tokens)
    if for_metadata_title:
        lines = ['{{- $title := .Title -}}']
    else:
        lines = [
            '{{- $title := replace "/" "\u2215" .Title -}}',
            '{{- $title = replace "\\\\" "\u2215" $title -}}',
        ]
    lines.extend([
        '{{- $series := "" -}}{{- $series_abbr := "" -}}{{- $num := "" -}}',
        '{{- if gt (len .Series) 0 -}}',
        '{{-   $s := index .Series 0 -}}',
        '{{-   $series = $s.Name -}}',
        '{{-   $letters := list -}}',
        '{{-   range $w := splitList " " $s.Name -}}{{- if $w -}}{{- $letters = append $letters (upper (first (splitList "" $w))) -}}{{- end -}}{{- end -}}',
        '{{-   $series_abbr = join "" $letters -}}',
        '{{-   if gt $s.Number 0 -}}{{- $num = printf "%02d" $s.Number -}}{{- end -}}',
        '{{- end -}}',
        '{{- $last := "" -}}{{- $first := "" -}}{{- $mid := "" -}}',
        '{{- if gt (len .Authors) 0 -}}',
        '{{-   $a := index .Authors 0 -}}',
        '{{-   $last = $a.LastName -}}{{- $first = $a.FirstName -}}{{- $mid = $a.MiddleName -}}',
        '{{- end -}}',
        '{{- $format := .Format -}}',
    ])

    def _emit_join(items, out_var, val_expr_fn):
        sep_var = f"{out_var}_sep"
        has_var = f"{out_var}_has"
        lines.append(f'{{{{- {out_var} := "" -}}}}{{{{- {sep_var} := "" -}}}}{{{{- {has_var} := false -}}}}')
        for it in items:
            if it["type"] == "text":
                lines.append(f'{{{{- {sep_var} = printf "%s%s" {sep_var} {_go_quote(it["value"])} -}}}}')
            else:
                v_expr = val_expr_fn(it)
                lines.append(f'{{{{- if {v_expr} -}}}}')
                lines.append(f'{{{{-   if and {has_var} {sep_var} -}}}}{{{{- {out_var} = printf "%s%s" {out_var} {sep_var} -}}}}{{{{- end -}}}}')
                lines.append(f'{{{{-   {out_var} = printf "%s%s" {out_var} {v_expr} -}}}}')
                lines.append(f'{{{{-   {sep_var} = "" -}}}}{{{{- {has_var} = true -}}}}')
                lines.append('{{- else -}}')
                lines.append(f'{{{{-   if not {has_var} -}}}}{{{{- {sep_var} = "" -}}}}{{{{- end -}}}}')
                lines.append('{{- end -}}')

    top_items = []
    grp_idx = 0
    for seg in segments:
        if seg["type"] == "group":
            grp_var = f"$grp{grp_idx}"
            grp_idx += 1
            _emit_join(seg["items"], grp_var, lambda x: f"${x['id']}")
            lines.append(f'{{{{- if {grp_var} -}}}}{{{{- {grp_var} = printf "%s%s%s" {_go_quote(seg["open"])} {grp_var} {_go_quote(seg["close"])} -}}}}{{{{- end -}}}}')
            top_items.append({"type": "var", "var": grp_var})
        elif seg["type"] == "tag":
            top_items.append({"type": "var", "var": f"${seg['id']}"}) 
        else:
            top_items.append(seg)

    _emit_join(top_items, "$out", lambda x: x["var"])
    lines.extend([
        '{{- $out = regexReplaceAll " {2,}" (trim $out) " " -}}',
        '{{- if not $out -}}{{- $out = $title -}}{{- end -}}',
    ])
    if not for_metadata_title:
        lines.extend([
            '{{- $out = replace "/" "\u2215" $out -}}',
            '{{- $out = replace "\\\\" "\u2215" $out -}}',
        ])
    lines.append('{{ $out -}}')
    return "\n".join(lines)


def simulate_fbc_target(meta, output_format=DEFAULT_OUTPUT_FORMAT, filename_mode="default", filename_tokens=None):
    if filename_mode == "custom" and filename_tokens:
        target_name = render_filename_from_tokens(filename_tokens, meta, output_format)
        return target_name + FORMAT_EXT_MAP.get(output_format, ".epub")

    title, series, num = meta.get('title', ''), meta.get('series', ''), meta.get('num', '')
    prefix = ""
    if series:
        abbr = "".join([w[0].upper() for w in series.split() if w])
        if abbr:
            prefix = f"({abbr}" + (f" - {int(num):02d}" if num and num.isdigit() else "") + ") "
    target_name = (prefix + title).replace("/", "\u2215").replace("\\", "\u2215")
    return target_name + FORMAT_EXT_MAP.get(output_format, ".epub")


def _parse_metadata_fallback(xml_bytes):
    """Резервное извлечение метаданных из фрагмента <title-info>, если основной XML повреждён."""
    meta = {"first": "", "last": "", "mid": "", "series": "", "num": "", "title": ""}
    text = _sanitize_fb2_xml_text(_decode_fb2_text(xml_bytes))
    m_ti = re.search(r'<title-info\b[^>]*>.*?</title-info>', text, re.IGNORECASE | re.DOTALL)
    fragment = m_ti.group(0) if m_ti else text[:16384]

    try:
        ti_el = ET.fromstring(fragment.encode('utf-8'))
        t_el = ti_el.find('book-title')
        if t_el is not None and t_el.text:
            meta['title'] = t_el.text.strip()
        a_el = ti_el.find('author')
        if a_el is not None:
            for tag, key in [('first-name', 'first'), ('last-name', 'last'), ('middle-name', 'mid')]:
                el = a_el.find(tag)
                if el is not None and el.text:
                    meta[key] = el.text.strip()
        s_el = ti_el.find('sequence')
        if s_el is not None:
            meta['series'] = s_el.attrib.get('name', '').strip()
            meta['num'] = s_el.attrib.get('number', '').strip()
        return meta
    except Exception:
        pass

    def _rx_tag(src, tag_name):
        m = re.search(rf'<{tag_name}\b[^>]*>(.*?)</{tag_name}>', src, re.IGNORECASE | re.DOTALL)
        return html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip() if m else ""

    meta['title'] = _rx_tag(fragment, 'book-title')
    m_auth = re.search(r'<author\b[^>]*>(.*?)</author>', fragment, re.IGNORECASE | re.DOTALL)
    if m_auth:
        auth_blk = m_auth.group(1)
        meta['first'] = _rx_tag(auth_blk, 'first-name')
        meta['last'] = _rx_tag(auth_blk, 'last-name')
        meta['mid'] = _rx_tag(auth_blk, 'middle-name')
    m_seq = re.search(r'<sequence\b([^>]*)/?>', fragment, re.IGNORECASE)
    if m_seq:
        attrs = m_seq.group(1)
        m_name = re.search(r'\bname\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        m_num = re.search(r'\bnumber\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        if m_name:
            meta['series'] = html.unescape(m_name.group(1)).strip()
        if m_num:
            meta['num'] = html.unescape(m_num.group(1)).strip()
    return meta


def parse_metadata(xml_bytes):
    meta = {"first": "", "last": "", "mid": "", "series": "", "num": "", "title": ""}
    try:
        root = _parse_fb2_root(xml_bytes)
        if root is None:
            return _parse_metadata_fallback(xml_bytes)
        title_info, ns_uri = _find_title_info(root)
        if title_info is not None:
            t_el = title_info.find(_qtag(ns_uri, 'book-title'))
            if t_el is not None and t_el.text:
                meta['title'] = t_el.text
            author_el = title_info.find(_qtag(ns_uri, 'author'))
            if author_el is not None:
                for tag, key in [('first-name', 'first'), ('last-name', 'last'), ('middle-name', 'mid')]:
                    el = author_el.find(_qtag(ns_uri, tag))
                    if el is not None and el.text:
                        meta[key] = el.text
            seq_el = title_info.find(_qtag(ns_uri, 'sequence'))
            if seq_el is not None:
                meta['series'] = seq_el.attrib.get('name', '')
                meta['num'] = seq_el.attrib.get('number', '')
    except Exception:
        try:
            return _parse_metadata_fallback(xml_bytes)
        except Exception:
            pass
    return meta


def update_fb2_xml(xml_bytes, meta, cover_bytes=None, cover_mime="image/jpeg", cover_modified=False):
    root = _parse_fb2_root(xml_bytes)
    if root is None:
        # Если тело FB2 сильно повреждено и XML не восстанавливается целиком,
        # отдаём санитизированные байты движку fbc без падения на ParseError.
        try:
            return _sanitize_fb2_xml_text(_decode_fb2_text(xml_bytes)).encode('utf-8')
        except Exception:
            return xml_bytes

    title_info, ns_uri = _find_title_info(root)
    root_ns = _get_root_ns_uri(root)
    if title_info is not None:
        t_el = title_info.find(_qtag(ns_uri, 'book-title'))
        if t_el is not None:
            t_el.text = meta['title']
        a_el = title_info.find(_qtag(ns_uri, 'author'))
        if a_el is None:
            a_el = ET.SubElement(title_info, _qtag(ns_uri, 'author'))
        for tag, key in [('first-name', 'first'), ('last-name', 'last'), ('middle-name', 'mid')]:
            el = a_el.find(_qtag(ns_uri, tag))
            if el is not None:
                el.text = meta[key]
            elif meta[key]:
                ET.SubElement(a_el, _qtag(ns_uri, tag)).text = meta[key]

        seq_el = title_info.find(_qtag(ns_uri, 'sequence'))
        if meta['series']:
            if seq_el is None:
                seq_el = ET.SubElement(title_info, _qtag(ns_uri, 'sequence'))
            seq_el.set('name', meta['series'])
            if meta['num']:
                seq_el.set('number', meta['num'])
            else:
                seq_el.attrib.pop('number', None)
        elif seq_el is not None:
            title_info.remove(seq_el)

        if cover_modified and cover_bytes:
            coverpage_el = title_info.find(_qtag(ns_uri, 'coverpage'))
            if coverpage_el is None:
                coverpage_el = ET.SubElement(title_info, _qtag(ns_uri, 'coverpage'))
            image_el = coverpage_el.find(_qtag(ns_uri, 'image'))
            if image_el is None:
                image_el = ET.SubElement(coverpage_el, _qtag(ns_uri, 'image'))
            image_el.set(f'{{{XLINK_NS}}}href', '#cover.jpg')

            target_bin = None
            for bin_el in root.findall(_qtag(root_ns, 'binary')):
                if bin_el.attrib.get('id') == 'cover.jpg':
                    target_bin = bin_el
                    break
            if target_bin is None:
                target_bin = ET.SubElement(root, _qtag(root_ns, 'binary'))
                target_bin.set('id', 'cover.jpg')
            target_bin.set('content-type', cover_mime or 'image/jpeg')
            target_bin.text = base64.encodebytes(cover_bytes).decode('ascii')

    body = root.find(_qtag(root_ns, 'body'))
    if body is not None:
        body_title = body.find(_qtag(root_ns, 'title'))
        if body_title is not None:
            paras = body_title.findall(_qtag(root_ns, 'p'))
            if len(paras) >= 1 and meta.get('title'):
                paras[-1].text = meta['title']

    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def save_book_changes_to_source(data):
    """Атомарно сохраняет изменённые метаданные и обложку обратно в исходный .fb2 или .zip файл."""
    src_path = data.get("path")
    if not src_path or not os.path.isfile(src_path):
        raise FileNotFoundError(f"Исходный файл не найден: {src_path}")

    xml_bytes = get_book_xml(data)
    if not xml_bytes:
        raise RuntimeError(f"Не удалось прочитать исходный FB2: {src_path}")

    new_xml_bytes = update_fb2_xml(
        xml_bytes,
        data["meta"],
        cover_bytes=data.get("cover_bytes"),
        cover_mime=data.get("cover_mime", "image/jpeg"),
        cover_modified=bool(data.get("cover_modified", False)),
    )

    parent_dir = os.path.dirname(os.path.abspath(src_path)) or "."
    if src_path.lower().endswith(".zip"):
        target_entry = data.get("archive_entry")
        fd, tmp_zip = tempfile.mkstemp(prefix=".fbc_save_", suffix=".zip", dir=parent_dir)
        os.close(fd)
        try:
            with zipfile.ZipFile(src_path, "r") as zin:
                names = zin.namelist()
                if not target_entry:
                    for n in names:
                        if n.lower().endswith(".fb2"):
                            target_entry = n
                            break
                if not target_entry or target_entry not in names:
                    raise RuntimeError(f"В архиве {os.path.basename(src_path)} не найден исходный FB2")

                with zipfile.ZipFile(tmp_zip, "w") as zout:
                    for info in zin.infolist():
                        if info.filename == target_entry:
                            zout.writestr(info, new_xml_bytes, compress_type=zipfile.ZIP_DEFLATED)
                        else:
                            zout.writestr(info, zin.read(info.filename))
            os.replace(tmp_zip, src_path)
        except Exception:
            if os.path.exists(tmp_zip):
                os.remove(tmp_zip)
            raise
    else:
        fd, tmp_fb2 = tempfile.mkstemp(prefix=".fbc_save_", suffix=".fb2", dir=parent_dir)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(new_xml_bytes)
            os.replace(tmp_fb2, src_path)
        except Exception:
            if os.path.exists(tmp_fb2):
                os.remove(tmp_fb2)
            raise

    if data.get("cover_modified"):
        data["orig_cover_bytes"] = data.get("cover_bytes")
        data["orig_cover_mime"] = data.get("cover_mime")
        data["cover_modified"] = False
    if "xml" in data:
        data["xml"] = new_xml_bytes
    logger.info("Метаданные/обложка сохранены в исходный файл: %s", data.get("display_name") or src_path)
    return src_path


def patch_html_title_elements(html_text, author_css, title_css, meta=None):
    pattern = re.compile(
        r'(<(?P<tag>p|h[1-6])\b[^>]*class=["\'][^"\']*body-title-header[^"\']*["\'][^>]*>)(?P<inner>[\s\S]*?)(</(?P=tag)>)',
        re.IGNORECASE
    )
    matches = list(pattern.finditer(html_text))
    valid = [m for m in matches if re.sub(r'<[^>]+>', '', m.group('inner')).strip()]

    if len(valid) >= 2:
        title_m = valid[-1]
        author_ms = valid[:-1]
        t_tag = title_m.group('tag')
        t_repl = f'<{t_tag} class="body-title-header book-title" style="{title_css}">{title_m.group("inner")}</{t_tag}>'
        html_text = html_text[:title_m.start()] + t_repl + html_text[title_m.end():]
        for a_m in reversed(author_ms):
            a_tag = a_m.group('tag')
            a_repl = f'<{a_tag} class="body-title-header book-author" style="{author_css}">{a_m.group("inner")}</{a_tag}>'
            html_text = html_text[:a_m.start()] + a_repl + html_text[a_m.end():]
        return html_text

    elif len(valid) == 1:
        m = valid[0]
        tag, inner = m.group('tag'), m.group('inner')
        lines_raw = re.sub(r'<(?:br|/p|/div|/span|p|div|span)\b[^>]*>', '\n', inner, flags=re.IGNORECASE)
        lines = [re.sub(r'<[^>]+>', '', line).strip() for line in lines_raw.split('\n') if re.sub(r'<[^>]+>', '', line).strip()]

        if len(lines) >= 2:
            spans = [f'<span class="book-author" style="display: block; {author_css}">{a_line}</span>' for a_line in lines[:-1]]
            spans.append(f'<span class="book-title" style="display: block; {title_css}">{lines[-1]}</span>')
            repl = (
                f'<{tag} class="body-title-header" '
                f'style="font-size: 100% !important; font-weight: normal !important; font-style: normal !important; text-indent: 0; margin: 0; padding: 0;">'
                f'{"".join(spans)}</{tag}>'
            )
            return html_text[:m.start()] + repl + html_text[m.end():]

    return html_text


def patch_epub_title_classes(epub_path, style_params, meta=None):
    if not os.path.exists(epub_path):
        return False

    h1_sz = style_params["h1_sz"]
    h1_cl = style_params["h1_cl"]
    h1_al = style_params["h1_al"]
    auth_sz = style_params["auth_sz"]
    auth_cl = style_params["auth_cl"]
    auth_al = style_params["auth_al"]
    auth_style = style_params["auth_style"]

    author_css = (
        f"font-family: 'author-font', 'paragraph', serif !important; font-size: {auth_sz} !important; "
        f"color: {auth_cl} !important; font-style: {auth_style} !important; font-weight: bold !important; "
        f"text-align: {auth_al} !important; margin-top: 0.4em !important; margin-bottom: 0.4em !important;"
    )
    title_css = (
        f"font-family: 'title-font', 'paragraph', serif !important; font-size: {h1_sz} !important; "
        f"color: {h1_cl} !important; font-style: normal !important; font-weight: bold !important; "
        f"text-align: {h1_al} !important; margin-top: 0.8em !important; margin-bottom: 0.5em !important;"
    )

    temp_epub = epub_path + ".tmp"
    try:
        with zipfile.ZipFile(epub_path, 'r') as zin, zipfile.ZipFile(temp_epub, 'w') as zout:
            if "mimetype" in zin.namelist():
                zout.writestr("mimetype", zin.read("mimetype"), compress_type=zipfile.ZIP_STORED)
            for item in zin.infolist():
                if item.filename == "mimetype":
                    continue
                content = zin.read(item.filename)
                if item.filename.lower().endswith(('.xhtml', '.html', '.htm')):
                    try:
                        text = content.decode('utf-8')
                        if 'body-title-header' in text or 'body-title' in text:
                            patched = patch_html_title_elements(text, author_css, title_css, meta)
                            if patched != text:
                                content = patched.encode('utf-8')
                    except Exception:
                        pass
                zout.writestr(item, content, compress_type=zipfile.ZIP_DEFLATED)
        os.replace(temp_epub, epub_path)
        return True
    except Exception:
        if os.path.exists(temp_epub):
            os.remove(temp_epub)
        return False


def _local_tag(el):
    tag = el.tag if isinstance(el.tag, str) else ""
    return tag.rsplit("}", 1)[-1].lower()


def _fb2_inline_to_html(el):
    """Преобразует содержимое FB2-элемента (<p>, <v>) в безопасный HTML с поддержкой emphasis/strong/sup/sub."""
    parts = []
    if el.text:
        parts.append(html.escape(el.text))
    for child in el:
        cname = _local_tag(child)
        inner = _fb2_inline_to_html(child)
        if cname == "emphasis":
            parts.append(f"<i>{inner}</i>")
        elif cname == "strong":
            parts.append(f"<b>{inner}</b>")
        elif cname == "sup":
            parts.append(f"<sup>{inner}</sup>")
        elif cname == "sub":
            parts.append(f"<sub>{inner}</sub>")
        elif cname == "strikethrough":
            parts.append(f"<s>{inner}</s>")
        elif cname == "a":
            parts.append(f'<sup style="color: #2563eb; font-weight: bold; font-size: 75%;">{inner}</sup>')
        else:
            parts.append(inner)
        if child.tail:
            parts.append(html.escape(child.tail))
    return "".join(parts)


def extract_book_preview_data(xml_bytes, meta=None, cover_bytes=None, cover_mime=None, max_paragraphs=14):
    """Извлекает реальные фрагменты книги FB2 (обложка, аннотация, эпиграф, первая глава, сноска) для превью."""
    if not xml_bytes:
        return None
    root = _parse_fb2_root(xml_bytes)
    parsed_meta = parse_metadata(xml_bytes) if meta is None else dict(meta)

    author_parts = [p for p in (parsed_meta.get("first"), parsed_meta.get("mid"), parsed_meta.get("last")) if (p or "").strip()]
    author = " ".join(p.strip() for p in author_parts)
    title = (parsed_meta.get("title") or "").strip()
    series = (parsed_meta.get("series") or "").strip()
    num = (parsed_meta.get("num") or "").strip()
    series_line = f"{series} #{num}" if (series and num) else series

    cover_data_uri = ""
    if cover_bytes:
        mime = (cover_mime or "image/jpeg").strip()
        b64 = base64.b64encode(cover_bytes).decode("ascii")
        cover_data_uri = f"data:{mime};base64,{b64}"

    annotation_paras = []
    epigraph_lines = []
    epigraph_author = ""
    chapter_title = ""
    blocks = []
    footnote_title = ""
    footnote_paras = []

    if root is not None:
        ti, ns_uri = _find_title_info(root)
        if ti is not None:
            anno_el = ti.find(_qtag(ns_uri, "annotation"))
            if anno_el is not None:
                for ch in anno_el:
                    if _local_tag(ch) == "p":
                        txt = _fb2_inline_to_html(ch).strip()
                        if txt:
                            annotation_paras.append(txt)

        root_ns = _get_root_ns_uri(root)
        bodies = root.findall(_qtag(root_ns, "body"))
        if not bodies:
            bodies = [el for el in root if _local_tag(el) == "body"]

        main_body = None
        notes_body = None
        for b in bodies:
            bname = (b.attrib.get("name") or "").strip().lower()
            if not bname and main_body is None:
                main_body = b
            elif bname in ("notes", "comments", "примечания", "комментарии") and notes_body is None:
                notes_body = b
        if main_body is None and bodies:
            main_body = bodies[0]

        def _extract_epigraph(parent_el):
            nonlocal epigraph_lines, epigraph_author
            if epigraph_lines:
                return
            for ch in parent_el:
                if _local_tag(ch) == "epigraph":
                    for ec in ch:
                        ec_name = _local_tag(ec)
                        if ec_name == "p":
                            t = _fb2_inline_to_html(ec).strip()
                            if t:
                                epigraph_lines.append(t)
                        elif ec_name == "text-author":
                            t = _fb2_inline_to_html(ec).strip()
                            if t:
                                epigraph_author = t
                    if epigraph_lines:
                        return

        if main_body is not None:
            _extract_epigraph(main_body)
            # Ищем первую содержательную секцию
            def _find_first_content_section(el):
                secs = [c for c in el if _local_tag(c) == "section"]
                for sec in secs:
                    has_direct_p = any(_local_tag(c) in ("p", "poem", "cite") for c in sec)
                    if has_direct_p:
                        return sec
                    sub = _find_first_content_section(sec)
                    if sub is not None:
                        return sub
                return secs[0] if secs else None

            first_sec = _find_first_content_section(main_body)
            if first_sec is not None:
                _extract_epigraph(first_sec)
                for ch in first_sec:
                    cname = _local_tag(ch)
                    if cname == "title" and not chapter_title:
                        t_parts = [_fb2_inline_to_html(p).strip() for p in ch if _local_tag(p) == "p"]
                        chapter_title = " — ".join(p for p in t_parts if p)
                    elif cname == "p":
                        txt = _fb2_inline_to_html(ch).strip()
                        if txt:
                            blocks.append(("p", txt))
                    elif cname == "subtitle":
                        txt = _fb2_inline_to_html(ch).strip()
                        if txt:
                            blocks.append(("subtitle", txt))
                    elif cname == "empty-line":
                        blocks.append(("empty", ""))
                    elif cname == "poem":
                        verses = []
                        for st_el in ch:
                            if _local_tag(st_el) == "stanza":
                                for v_el in st_el:
                                    if _local_tag(v_el) == "v":
                                        vt = _fb2_inline_to_html(v_el).strip()
                                        if vt:
                                            verses.append(vt)
                        if verses:
                            blocks.append(("poem", "<br>".join(verses[:8])))
                    elif cname == "cite":
                        c_ps = [_fb2_inline_to_html(p).strip() for p in ch if _local_tag(p) == "p"]
                        if c_ps:
                            blocks.append(("cite", "<br>".join(p for p in c_ps[:3] if p)))
                    if len(blocks) >= max_paragraphs:
                        break

        if notes_body is not None:
            note_secs = [c for c in notes_body if _local_tag(c) == "section"]
            if note_secs:
                ns0 = note_secs[0]
                for ch in ns0:
                    cname = _local_tag(ch)
                    if cname == "title" and not footnote_title:
                        footnote_title = " ".join(_fb2_inline_to_html(p).strip() for p in ch if _local_tag(p) == "p").strip()
                    elif cname == "p":
                        pt = _fb2_inline_to_html(ch).strip()
                        if pt:
                            footnote_paras.append(pt)
                            if len(footnote_paras) >= 2:
                                break

    return {
        "author": author,
        "title": title,
        "series": series_line,
        "cover_data_uri": cover_data_uri,
        "annotation": annotation_paras[:3],
        "epigraph_lines": epigraph_lines[:3],
        "epigraph_author": epigraph_author,
        "chapter_title": chapter_title,
        "blocks": blocks,
        "footnote_title": footnote_title,
        "footnote_paras": footnote_paras,
    }


def _run_cancellable_process(cmd, cwd, cancel_event=None):
    """Запускает внешний процесс через Popen и немедленно завершает его при срабатывании cancel_event."""
    if cancel_event is not None and cancel_event.is_set():
        raise ConversionCancelledError("Conversion cancelled")

    popen_kwargs = {
        "cwd": cwd,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.Popen(cmd, **popen_kwargs)
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                proc.terminate()
                try:
                    proc.communicate(timeout=1.5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                raise ConversionCancelledError("Conversion cancelled")
            try:
                stdout, stderr = proc.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                continue
    except ConversionCancelledError:
        raise
    except Exception:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        raise

    if cancel_event is not None and cancel_event.is_set():
        raise ConversionCancelledError("Conversion cancelled")

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout, stderr=stderr)
    return stdout, stderr


def _save_debug_report_if_present(tmp_work_dir, dest_dir, data):
    """Сохраняет сформированный fbc-report.zip рядом с итоговым файлом при запуске с --debug."""
    report_src = os.path.join(tmp_work_dir, "fbc-report.zip")
    if not os.path.isfile(report_src):
        return None
    base_label = data.get("display_name") or os.path.basename(data.get("path") or "book")
    stem = os.path.splitext(base_label.replace("/", "_").replace("\\", "_"))[0].strip() or "book"
    report_dst = os.path.join(dest_dir, f"{stem}_fbc-report.zip")
    try:
        with _DEST_MOVE_LOCK:
            os.makedirs(dest_dir, exist_ok=True)
            if os.path.exists(report_dst):
                os.remove(report_dst)
            shutil.move(report_src, report_dst)
        logger.info("Сохранён отладочный отчёт fbc: %s", report_dst)
        return report_dst
    except Exception as e:
        logger.warning("Не удалось сохранить fbc-report.zip: %s", e)
        return None


def _attach_fonts_dir(base_dir, fbc_config, tmp_work_dir):
    """Делает каталог fonts доступным из рабочей папки fbc (для url("fonts/...") в CSS)."""
    candidates = []
    if base_dir:
        candidates.append(os.path.join(base_dir, "fonts"))
    if fbc_config:
        cfg_fonts = os.path.join(os.path.dirname(os.path.abspath(fbc_config)), "fonts")
        if cfg_fonts not in candidates:
            candidates.append(cfg_fonts)

    src_fonts = next((p for p in candidates if os.path.isdir(p)), None)
    if not src_fonts:
        return None

    dst_fonts = os.path.join(tmp_work_dir, "fonts")
    try:
        os.symlink(src_fonts, dst_fonts, target_is_directory=True)
    except (OSError, NotImplementedError):
        shutil.copytree(src_fonts, dst_fonts)
    return dst_fonts


def _attach_stylesheet_file(base_dir, fbc_config, tmp_work_dir):
    """Делает ebook_styles.css доступным из рабочей папки fbc при относительном stylesheet_path."""
    candidates = []
    if fbc_config:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(fbc_config)), "ebook_styles.css"))
    if base_dir:
        base_css = os.path.join(base_dir, "ebook_styles.css")
        if base_css not in candidates:
            candidates.append(base_css)

    src_css = next((p for p in candidates if os.path.isfile(p)), None)
    if not src_css:
        return None

    dst_css = os.path.join(tmp_work_dir, "ebook_styles.css")
    try:
        os.symlink(src_css, dst_css)
    except (OSError, NotImplementedError):
        shutil.copy2(src_css, dst_css)
    return dst_css


def convert_book_file(
    fbc_cmd,
    fbc_config,
    base_dir,
    data,
    dest_dir,
    selected_format,
    title_style_params,
    compression=None,
    cancel_event=None,
    debug=False,
    no_cover=False
):
    """Конвертирует одну книгу через fbc в изолированной временной папке и при необходимости патчит заголовки EPUB."""
    if cancel_event is not None and cancel_event.is_set():
        raise ConversionCancelledError("Conversion cancelled")

    is_epub_format = selected_format in EPUB_BASED_FORMATS
    xml_bytes = get_book_xml(data)
    if not xml_bytes:
        src_label = data.get("display_name") or data.get("path") or "unknown"
        raise RuntimeError(f"Не удалось прочитать исходный файл FB2: {src_label}")

    new_xml_bytes = update_fb2_xml(
        xml_bytes, data['meta'],
        cover_bytes=data.get('cover_bytes'),
        cover_mime=data.get('cover_mime', 'image/jpeg'),
        cover_modified=data.get('cover_modified', False)
    )
    with tempfile.NamedTemporaryFile(delete=False, suffix=".fb2") as tmp:
        tmp.write(new_xml_bytes)
        tmp_path = tmp.name

    try:
        with tempfile.TemporaryDirectory() as tmp_root:
            tmp_work_dir = os.path.join(tmp_root, "work")
            tmp_out_dir = os.path.join(tmp_root, "out")
            os.makedirs(tmp_work_dir, exist_ok=True)
            os.makedirs(tmp_out_dir, exist_ok=True)
            linked_fonts = _attach_fonts_dir(base_dir, fbc_config, tmp_work_dir)
            linked_css = _attach_stylesheet_file(base_dir, fbc_config, tmp_work_dir)

            try:
                cmd = [fbc_cmd]
                if debug:
                    cmd.append("--debug")
                cmd.extend(["convert", "--overwrite", "--to", selected_format])
                if compression and selected_format in ("azw3", "kfx", "azw8"):
                    cmd.extend(["--compression", compression])
                if no_cover and selected_format in ("epub2", "epub3", "kepub", "kepub3", "pdf"):
                    cmd.append("--no-cover")
                cmd.extend(["--config", fbc_config, tmp_path, tmp_out_dir])

                try:
                    _run_cancellable_process(cmd, cwd=tmp_work_dir, cancel_event=cancel_event)
                except subprocess.CalledProcessError as e:
                    if debug:
                        _save_debug_report_if_present(tmp_work_dir, dest_dir, data)
                    err_out = (e.stderr or e.stdout or "").strip()
                    if not err_out:
                        fbc_log_path = os.path.join(tmp_work_dir, "fbc.log")
                        if os.path.isfile(fbc_log_path):
                            try:
                                with open(fbc_log_path, "r", encoding="utf-8", errors="replace") as lf:
                                    err_out = lf.read().strip()
                            except Exception:
                                pass
                    if err_out:
                        err_tail = "\n".join(err_out.splitlines()[-8:])
                        logger.error("Ошибка fbc (код %s) для %s:\n%s", e.returncode, data.get("display_name") or data.get("path"), err_tail)
                        raise RuntimeError(f"fbc exit code {e.returncode}:\n{err_tail}") from e
                    logger.error("Ошибка fbc (код %s) для %s", e.returncode, data.get("display_name") or data.get("path"))
                    raise RuntimeError(f"fbc exit code {e.returncode}") from e

                if debug:
                    _save_debug_report_if_present(tmp_work_dir, dest_dir, data)

                if cancel_event is not None and cancel_event.is_set():
                    raise ConversionCancelledError("Conversion cancelled")

                produced_tmp = []
                for root_dir, _, files in os.walk(tmp_out_dir):
                    for fname in sorted(files):
                        produced_tmp.append(os.path.join(root_dir, fname))

                if is_epub_format:
                    for ep in produced_tmp:
                        if ep.lower().endswith(('.epub', '.kepub.epub')):
                            patch_epub_title_classes(ep, title_style_params, data['meta'])

                if cancel_event is not None and cancel_event.is_set():
                    raise ConversionCancelledError("Conversion cancelled")

                created_final = []
                with _DEST_MOVE_LOCK:
                    os.makedirs(dest_dir, exist_ok=True)
                    for src_fp in produced_tmp:
                        dst_fp = os.path.join(dest_dir, os.path.basename(src_fp))
                        if os.path.exists(dst_fp):
                            os.remove(dst_fp)
                        shutil.move(src_fp, dst_fp)
                        created_final.append(dst_fp)

                return created_final
            finally:
                for linked_path in (linked_fonts, linked_css):
                    if linked_path and os.path.islink(linked_path):
                        try:
                            os.unlink(linked_path)
                        except OSError:
                            pass
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

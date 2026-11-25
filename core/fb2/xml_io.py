import base64
import html
import io
import os
import re
import zipfile
import xml.etree.ElementTree as ET

from core.fb2.common import (
    COVER_TARGET_SIZE,
    HAS_LXML,
    HAS_PIL,
    Image,
    ImageOps,
    LXML_ET,
    MAX_FB2_XML_BYTES,
    XLINK_NS,
    get_facade_attr,
    logger,
    normalize_isbn,
)

_XML_ILLEGAL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')
_XML_ENCODING_RE = re.compile(rb'encoding\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_BARE_AMP_RE = re.compile(r'&(?!(?:[a-zA-Z][a-zA-Z0-9._-]*|#\d+|#x[0-9a-fA-F]+);)')
_XML_DECL_ENC_RE = re.compile(r'(<\?xml[^>]*?encoding\s*=\s*)(["\'])[^"\']+\2', re.IGNORECASE)
_FICTIONBOOK_TAG_RE = re.compile(r'<FictionBook\b[^>]*>', re.IGNORECASE)
_COVERPAGE_RE = re.compile(r'<coverpage\b[^>]*>(.*?)</coverpage>', re.IGNORECASE | re.DOTALL)
_COVER_HREF_RE = re.compile(r'href\s*=\s*["\']#([^"\']+)["\']', re.IGNORECASE)
_BINARY_TAG_RE = re.compile(r'<binary\b([^>]*)>(.*?)</binary>', re.IGNORECASE | re.DOTALL)
_ATTR_ID_RE = re.compile(r'\bid\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_ATTR_CTYPE_RE = re.compile(r'content-type\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def _read_zip_entry_limited(zf, member_name, max_bytes=MAX_FB2_XML_BYTES):
    """Безопасно читает запись из ZIP-архива с защитой от zip-бомб."""
    info = zf.getinfo(member_name)
    if info.file_size > max_bytes:
        raise ValueError(f"FB2 entry exceeds size limit ({max_bytes} bytes): {member_name}")
    with zf.open(info, "r") as fh:
        data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"FB2 entry exceeds size limit ({max_bytes} bytes): {member_name}")
    return data


def _read_plain_file_limited(filepath, max_bytes=MAX_FB2_XML_BYTES):
    """Безопасно читает обычный .fb2-файл с ограничением максимального размера."""
    if os.path.getsize(filepath) > max_bytes:
        raise ValueError(f"FB2 file exceeds size limit ({max_bytes} bytes): {filepath}")
    with open(filepath, 'rb') as f:
        data = f.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"FB2 file exceeds size limit ({max_bytes} bytes): {filepath}")
    return data


def extract_fb2_xml(filepath):
    if filepath.lower().endswith('.zip'):
        with zipfile.ZipFile(filepath, 'r') as z:
            for name in z.namelist():
                if name.lower().endswith('.fb2'):
                    return _read_zip_entry_limited(z, name)
    else:
        return _read_plain_file_limited(filepath)
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
    if sf == "warnings" and not (data.get("warnings") or []):
        return False

    q = (query or "").strip().lower()
    if not q:
        return True

    meta = data.get("meta") or {}
    genres_str = " ".join(meta.get("genres") or [])
    haystack_parts = [
        data.get("display_name") or "",
        os.path.basename(data.get("path") or ""),
        meta.get("last") or "",
        meta.get("first") or "",
        meta.get("mid") or "",
        meta.get("series") or "",
        meta.get("num") or "",
        meta.get("title") or "",
        genres_str,
        meta.get("lang") or "",
        meta.get("publisher") or "",
        meta.get("isbn") or "",
        normalize_isbn(meta.get("isbn") or ""),
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
                        xml_bytes = _read_zip_entry_limited(z, entry_name)
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
            xml_bytes = _read_plain_file_limited(filepath)
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
                return _read_zip_entry_limited(z, archive_entry)
        if filepath.lower().endswith('.zip'):
            return extract_fb2_xml(filepath)
        return _read_plain_file_limited(filepath)
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
            except Exception as e:
                logger.debug("Не удалось извлечь объявленную кодировку XML: %s", e)
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
    m_root = _FICTIONBOOK_TAG_RE.search(clean)
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


def _has_disallowed_xml_declarations(raw_bytes):
    head = raw_bytes[:65536].lower() if isinstance(raw_bytes, (bytes, bytearray)) else str(raw_bytes)[:65536].lower().encode('utf-8', errors='ignore')
    return b'<!doctype' in head or b'<!entity' in head


def _parse_fb2_root(xml_bytes):
    """Пытается распарсить FB2: сначала напрямую, затем после санитизации и через lxml (если доступен)."""
    if _has_disallowed_xml_declarations(xml_bytes):
        logger.warning("Отклонён FB2 с объявлением DOCTYPE/ENTITY")
        return None
    try:
        return ET.fromstring(xml_bytes)
    except Exception as e:
        logger.debug("Прямой XML-парсинг FB2 не удался, пробуем санитизацию: %s", e)

    clean_bytes = None
    try:
        clean_text = _sanitize_fb2_xml_text(_decode_fb2_text(xml_bytes))
        clean_bytes = clean_text.encode('utf-8')
        return ET.fromstring(clean_bytes)
    except Exception as e:
        logger.debug("XML-парсинг FB2 после санитизации не удался: %s", e)

    has_lxml = get_facade_attr("HAS_LXML", HAS_LXML)
    lxml_et = get_facade_attr("LXML_ET", LXML_ET)
    if has_lxml and lxml_et is not None:
        try:
            parser = lxml_et.XMLParser(
                recover=True,
                resolve_entities=False,
                no_network=True,
                huge_tree=False,
            )
            l_root = lxml_et.fromstring(clean_bytes or xml_bytes, parser=parser)
            if l_root is not None:
                return ET.fromstring(lxml_et.tostring(l_root, encoding='utf-8'))
        except Exception as e:
            logger.debug("Восстанавливающий парсинг FB2 через lxml не удался: %s", e)

    return None


def _get_root_ns_uri(root):
    if root is not None and root.tag.startswith('{'):
        return root.tag[1:].split('}', 1)[0]
    return ""


def _qtag(ns_uri, local_name):
    return f'{{{ns_uri}}}{local_name}' if ns_uri else local_name


def _local_tag(el):
    tag = el.tag if isinstance(el.tag, str) else ""
    return tag.rsplit("}", 1)[-1].lower()


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
    m_cp = _COVERPAGE_RE.search(text)
    if m_cp:
        m_href = _COVER_HREF_RE.search(m_cp.group(1))
        if m_href:
            cover_id = html.unescape(m_href.group(1).strip())

    first_img = None
    for m_bin in _BINARY_TAG_RE.finditer(text):
        attrs, b64_body = m_bin.group(1), m_bin.group(2)
        m_id = _ATTR_ID_RE.search(attrs)
        m_ct = _ATTR_CTYPE_RE.search(attrs)
        bin_id = html.unescape(m_id.group(1).strip()) if m_id else ""
        ctype = m_ct.group(1).strip() if m_ct else "image/jpeg"
        if cover_id and bin_id == cover_id:
            try:
                return base64.b64decode("".join(b64_body.split())), ctype
            except Exception as e:
                logger.debug("Не удалось декодировать обложку (fallback, id=%s): %s", bin_id, e)
        if first_img is None and ctype.lower().startswith('image/'):
            try:
                first_img = (base64.b64decode("".join(b64_body.split())), ctype)
            except Exception as e:
                logger.debug("Не удалось декодировать запасное изображение (id=%s): %s", bin_id, e)
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
        except Exception as e:
            logger.debug("Fallback-извлечение обложки FB2 не удалось: %s", e)
    return None, None


def fit_image_to_cover_size(image_path, target_size=COVER_TARGET_SIZE):
    target_w, target_h = target_size
    if get_facade_attr("HAS_PIL", HAS_PIL) and Image is not None and ImageOps is not None:
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            fitted = ImageOps.fit(im, (target_w, target_h), method=Image.Resampling.LANCZOS)
            out = io.BytesIO()
            fitted.save(out, format="JPEG", quality=92)
            return out.getvalue(), "image/jpeg"
    ext = os.path.splitext(image_path)[1].lower()
    mime = {
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/jpeg")
    with open(image_path, "rb") as f:
        return f.read(), mime


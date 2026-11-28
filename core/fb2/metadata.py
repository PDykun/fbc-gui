import base64
import html
import os
import re
import stat
import tempfile
import zipfile
import xml.etree.ElementTree as ET

from core.fb2_genres import normalize_genre_list
from core.fb2.common import (
    XLINK_NS,
    _AUTHOR_XSD_ORDER,
    _DESCRIPTION_XSD_ORDER,
    _HTML_TAG_RE,
    _PUBLISH_INFO_XSD_ORDER,
    _TITLE_INFO_XSD_ORDER,
    copy_meta_dict,
    logger,
)
from core.fb2.xml_io import (
    _decode_fb2_text,
    _find_title_info,
    _get_root_ns_uri,
    _has_disallowed_xml_declarations,
    _local_tag,
    _parse_fb2_root,
    _qtag,
    _read_zip_entry_limited,
    _sanitize_fb2_xml_text,
    get_book_xml,
)

_TITLE_INFO_RE = re.compile(r'<title-info\b[^>]*>.*?</title-info>', re.IGNORECASE | re.DOTALL)
_PUBLISH_INFO_RE = re.compile(r'<publish-info\b[^>]*>.*?</publish-info>', re.IGNORECASE | re.DOTALL)
_GENRE_RE = re.compile(r'<genre\b[^>]*>(.*?)</genre>', re.IGNORECASE | re.DOTALL)
_AUTHOR_RE = re.compile(r'<author\b[^>]*>(.*?)</author>', re.IGNORECASE | re.DOTALL)
_TRANSLATOR_RE = re.compile(r'<translator\b[^>]*>(.*?)</translator>', re.IGNORECASE | re.DOTALL)
_SEQUENCE_RE = re.compile(r'<sequence\b([^>]*)/?>', re.IGNORECASE)
_ATTR_NAME_RE = re.compile(r'\bname\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)
_ATTR_NUMBER_RE = re.compile(r'\bnumber\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)


def _empty_meta():
    return {
        "first": "",
        "last": "",
        "mid": "",
        "series": "",
        "num": "",
        "title": "",
        "genres": [],
        "lang": "",
        "annotation": "",
        "annotation_has_rich_xml": False,
        "translator_last": "",
        "translator_first": "",
        "translator_middle": "",
        "extra_translators_count": 0,
        "publisher": "",
        "isbn": "",
    }


def _extract_annotation_text_and_rich_flag(anno_el):
    """Извлекает плоский текст аннотации (абзацы через \\n\\n) и определяет наличие сложной XML-разметки."""
    if anno_el is None:
        return "", False
    has_rich = False
    parts = []
    for child in anno_el:
        cname = _local_tag(child)
        if cname == "p":
            if len(child) > 0:
                has_rich = True
            txt = "".join(child.itertext()).strip()
            if txt:
                parts.append(txt)
        elif cname == "empty-line":
            parts.append("")
        else:
            has_rich = True
            txt = "".join(child.itertext()).strip()
            if txt:
                parts.append(txt)
    if not parts:
        raw = "".join(anno_el.itertext()).strip()
        if raw:
            parts.append(raw)
    return "\n\n".join(parts).strip(), has_rich


def _find_description_and_publish_info(root):
    ns_uri = _get_root_ns_uri(root)
    desc = None
    if ns_uri:
        desc = root.find(f'./{{{ns_uri}}}description')
    if desc is None:
        desc = root.find('./description')
    if desc is None:
        for el in root.iter():
            if _local_tag(el) == 'description':
                desc = el
                break
    if desc is None:
        return None, None, ns_uri
    desc_ns = desc.tag[1:].split('}', 1)[0] if desc.tag.startswith('{') else ""
    pub = desc.find(_qtag(desc_ns, 'publish-info'))
    return desc, pub, desc_ns


def _insert_in_xsd_order(parent, elem, tag_order):
    """Вставляет элемент в parent строго по порядку XSD (перед первым тегом, идущим позже в tag_order)."""
    target_name = _local_tag(elem)
    order_index = {name: idx for idx, name in enumerate(tag_order)}
    target_pos = order_index.get(target_name, len(tag_order))
    insert_at = len(parent)
    for idx, child in enumerate(parent):
        c_pos = order_index.get(_local_tag(child), len(tag_order))
        if c_pos > target_pos:
            insert_at = idx
            break
    parent.insert(insert_at, elem)
    return elem


def _parse_metadata_fallback(xml_bytes):
    """Резервное извлечение метаданных из фрагмента <title-info>, если основной XML повреждён."""
    meta = _empty_meta()
    text = _sanitize_fb2_xml_text(_decode_fb2_text(xml_bytes))
    m_ti = _TITLE_INFO_RE.search(text)
    fragment = m_ti.group(0) if m_ti else text[:16384]
    m_pub = _PUBLISH_INFO_RE.search(text)

    def _rx_tag(src, tag_name):
        m = re.search(rf'<{tag_name}\b[^>]*>(.*?)</{tag_name}>', src, re.IGNORECASE | re.DOTALL)
        return html.unescape(_HTML_TAG_RE.sub('', m.group(1))).strip() if m else ""

    if m_pub:
        meta['publisher'] = _rx_tag(m_pub.group(0), 'publisher')
        meta['isbn'] = _rx_tag(m_pub.group(0), 'isbn')

    try:
        frag_bytes = fragment.encode('utf-8')
        if _has_disallowed_xml_declarations(frag_bytes):
            raise ValueError("Disallowed XML declaration in title-info fragment")
        ti_el = ET.fromstring(frag_bytes)
        meta['genres'] = normalize_genre_list([el.text for el in ti_el.findall('genre') if el.text])
        t_el = ti_el.find('book-title')
        if t_el is not None and t_el.text:
            meta['title'] = t_el.text.strip()
        a_el = ti_el.find('author')
        if a_el is not None:
            for tag, key in [('first-name', 'first'), ('last-name', 'last'), ('middle-name', 'mid')]:
                el = a_el.find(tag)
                if el is not None and el.text:
                    meta[key] = el.text.strip()
        l_el = ti_el.find('lang')
        if l_el is not None and l_el.text:
            meta['lang'] = l_el.text.strip().lower()
        anno_text, anno_rich = _extract_annotation_text_and_rich_flag(ti_el.find('annotation'))
        meta['annotation'] = anno_text
        meta['annotation_has_rich_xml'] = anno_rich
        translators = ti_el.findall('translator')
        if translators:
            tr0 = translators[0]
            for tag, key in [('first-name', 'translator_first'), ('last-name', 'translator_last'), ('middle-name', 'translator_middle')]:
                el = tr0.find(tag)
                if el is not None and el.text:
                    meta[key] = el.text.strip()
            meta['extra_translators_count'] = max(0, len(translators) - 1)
        s_el = ti_el.find('sequence')
        if s_el is not None:
            meta['series'] = s_el.attrib.get('name', '').strip()
            meta['num'] = s_el.attrib.get('number', '').strip()
        return meta
    except Exception as e:
        logger.debug("XML-разбор фрагмента title-info не удался, переходим к regex: %s", e)

    meta['genres'] = normalize_genre_list(_GENRE_RE.findall(fragment))
    meta['title'] = _rx_tag(fragment, 'book-title')
    meta['lang'] = _rx_tag(fragment, 'lang').lower()
    m_auth = _AUTHOR_RE.search(fragment)
    if m_auth:
        auth_blk = m_auth.group(1)
        meta['first'] = _rx_tag(auth_blk, 'first-name')
        meta['last'] = _rx_tag(auth_blk, 'last-name')
        meta['mid'] = _rx_tag(auth_blk, 'middle-name')
    m_tr_all = _TRANSLATOR_RE.findall(fragment)
    if m_tr_all:
        tr_blk = m_tr_all[0]
        meta['translator_first'] = _rx_tag(tr_blk, 'first-name')
        meta['translator_last'] = _rx_tag(tr_blk, 'last-name')
        meta['translator_middle'] = _rx_tag(tr_blk, 'middle-name')
        meta['extra_translators_count'] = max(0, len(m_tr_all) - 1)
    m_seq = _SEQUENCE_RE.search(fragment)
    if m_seq:
        attrs = m_seq.group(1)
        m_name = _ATTR_NAME_RE.search(attrs)
        m_num = _ATTR_NUMBER_RE.search(attrs)
        if m_name:
            meta['series'] = html.unescape(m_name.group(1)).strip()
        if m_num:
            meta['num'] = html.unescape(m_num.group(1)).strip()
    return meta


def parse_metadata(xml_bytes, root=None):
    meta = _empty_meta()
    try:
        if root is None:
            root = _parse_fb2_root(xml_bytes)
        if root is None:
            return _parse_metadata_fallback(xml_bytes)
        title_info, ns_uri = _find_title_info(root)
        if title_info is not None:
            meta['genres'] = normalize_genre_list([
                el.text for el in title_info.findall(_qtag(ns_uri, 'genre')) if el.text
            ])
            t_el = title_info.find(_qtag(ns_uri, 'book-title'))
            if t_el is not None and t_el.text:
                meta['title'] = t_el.text
            author_el = title_info.find(_qtag(ns_uri, 'author'))
            if author_el is not None:
                for tag, key in [('first-name', 'first'), ('last-name', 'last'), ('middle-name', 'mid')]:
                    el = author_el.find(_qtag(ns_uri, tag))
                    if el is not None and el.text:
                        meta[key] = el.text
            lang_el = title_info.find(_qtag(ns_uri, 'lang'))
            if lang_el is not None and lang_el.text:
                meta['lang'] = lang_el.text.strip().lower()
            anno_text, anno_rich = _extract_annotation_text_and_rich_flag(
                title_info.find(_qtag(ns_uri, 'annotation'))
            )
            meta['annotation'] = anno_text
            meta['annotation_has_rich_xml'] = anno_rich
            translators = title_info.findall(_qtag(ns_uri, 'translator'))
            if translators:
                tr0 = translators[0]
                for tag, key in [('first-name', 'translator_first'), ('last-name', 'translator_last'), ('middle-name', 'translator_middle')]:
                    el = tr0.find(_qtag(ns_uri, tag))
                    if el is not None and el.text:
                        meta[key] = el.text.strip()
                meta['extra_translators_count'] = max(0, len(translators) - 1)
            seq_el = title_info.find(_qtag(ns_uri, 'sequence'))
            if seq_el is not None:
                meta['series'] = seq_el.attrib.get('name', '')
                meta['num'] = seq_el.attrib.get('number', '')
        _desc, pub_info, desc_ns = _find_description_and_publish_info(root)
        if pub_info is not None:
            pub_el = pub_info.find(_qtag(desc_ns, 'publisher'))
            if pub_el is not None and pub_el.text:
                meta['publisher'] = pub_el.text.strip()
            isbn_el = pub_info.find(_qtag(desc_ns, 'isbn'))
            if isbn_el is not None and isbn_el.text:
                meta['isbn'] = isbn_el.text.strip()
    except Exception:
        try:
            return _parse_metadata_fallback(xml_bytes)
        except Exception as e:
            logger.debug("Fallback-разбор метаданных FB2 не удался: %s", e)
    return meta


def _build_annotation_element(ns_uri, text):
    anno_el = ET.Element(_qtag(ns_uri, 'annotation'))
    raw = (text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not raw:
        return anno_el
    blocks = raw.split('\n\n')
    for blk in blocks:
        lines = [ln.strip() for ln in blk.split('\n')]
        non_empty = [ln for ln in lines if ln]
        if not non_empty:
            ET.SubElement(anno_el, _qtag(ns_uri, 'empty-line'))
        else:
            for ln in non_empty:
                p_el = ET.SubElement(anno_el, _qtag(ns_uri, 'p'))
                p_el.text = ln
    return anno_el


def _apply_cover_to_xml(root, title_info, ns_uri, root_ns, cover_bytes, cover_mime):
    norm_mime = (cover_mime or 'image/jpeg').strip().lower()
    ext_map = {'image/png': '.png', 'image/webp': '.webp', 'image/gif': '.gif'}
    cover_id = 'cover' + ext_map.get(norm_mime, '.jpg')

    coverpage_el = title_info.find(_qtag(ns_uri, 'coverpage'))
    if coverpage_el is None:
        coverpage_el = _insert_in_xsd_order(title_info, ET.Element(_qtag(ns_uri, 'coverpage')), _TITLE_INFO_XSD_ORDER)
    image_el = coverpage_el.find(_qtag(ns_uri, 'image'))
    if image_el is None:
        image_el = ET.SubElement(coverpage_el, _qtag(ns_uri, 'image'))

    old_cover_id = None
    for k, v in list(image_el.attrib.items()):
        if k.endswith('href') and v.startswith('#'):
            old_cover_id = v[1:]
            if k != f'{{{XLINK_NS}}}href':
                del image_el.attrib[k]
    image_el.set(f'{{{XLINK_NS}}}href', f'#{cover_id}')

    target_bin = None
    old_bin = None
    for bin_el in root.findall(_qtag(root_ns, 'binary')):
        bid = bin_el.attrib.get('id')
        if bid == cover_id:
            target_bin = bin_el
        elif old_cover_id and bid == old_cover_id:
            old_bin = bin_el
    if old_bin is not None and old_cover_id != cover_id:
        body_refs = set()
        for b_el in root.findall(_qtag(root_ns, 'body')):
            for img in b_el.iter():
                for ak, av in img.attrib.items():
                    if ak.endswith('href') and av.startswith('#'):
                        body_refs.add(av[1:])
        if old_cover_id not in body_refs:
            root.remove(old_bin)
    if target_bin is None:
        target_bin = ET.SubElement(root, _qtag(root_ns, 'binary'))
        target_bin.set('id', cover_id)
    target_bin.set('content-type', norm_mime or 'image/jpeg')
    target_bin.text = base64.encodebytes(cover_bytes).decode('ascii')


def _apply_publish_info_field(root, field_name, meta, current_meta):
    if field_name not in meta:
        return
    new_val = (meta.get(field_name) or '').strip()
    old_val = (current_meta.get(field_name) or '').strip()
    if new_val == old_val:
        return
    desc, pub_info, desc_ns = _find_description_and_publish_info(root)
    if desc is None:
        return
    if new_val:
        if pub_info is None:
            pub_info = _insert_in_xsd_order(desc, ET.Element(_qtag(desc_ns, 'publish-info')), _DESCRIPTION_XSD_ORDER)
        field_el = pub_info.find(_qtag(desc_ns, field_name))
        if field_el is None:
            field_el = _insert_in_xsd_order(pub_info, ET.Element(_qtag(desc_ns, field_name)), _PUBLISH_INFO_XSD_ORDER)
        field_el.text = new_val
    elif pub_info is not None:
        field_el = pub_info.find(_qtag(desc_ns, field_name))
        if field_el is not None:
            pub_info.remove(field_el)
        if len(pub_info) == 0:
            desc.remove(pub_info)


def _apply_title_info_metadata(root, title_info, ns_uri, root_ns, meta, current_meta, *, cover_bytes=None, cover_mime="image/jpeg", cover_modified=False):
    # 1. Жанры (минимальный патч: трогаем только если явно переданы и изменились)
    if 'genres' in meta:
        new_genres = normalize_genre_list(meta.get('genres'))
        old_genres = normalize_genre_list(current_meta.get('genres'))
        if new_genres != old_genres:
            for g_el in list(title_info.findall(_qtag(ns_uri, 'genre'))):
                title_info.remove(g_el)
            for idx, code in enumerate(new_genres):
                g_el = ET.Element(_qtag(ns_uri, 'genre'))
                g_el.text = code
                title_info.insert(idx, g_el)

    # 2. Автор
    a_el = title_info.find(_qtag(ns_uri, 'author'))
    if a_el is None:
        a_el = _insert_in_xsd_order(title_info, ET.Element(_qtag(ns_uri, 'author')), _TITLE_INFO_XSD_ORDER)
    for tag, key in [('first-name', 'first'), ('last-name', 'last'), ('middle-name', 'mid')]:
        el = a_el.find(_qtag(ns_uri, tag))
        val = meta.get(key, '')
        if el is not None:
            el.text = val
        elif val:
            new_el = ET.Element(_qtag(ns_uri, tag))
            new_el.text = val
            _insert_in_xsd_order(a_el, new_el, _AUTHOR_XSD_ORDER)

    # 3. Название
    t_el = title_info.find(_qtag(ns_uri, 'book-title'))
    if t_el is not None:
        t_el.text = meta.get('title', '')
    elif meta.get('title'):
        new_t = ET.Element(_qtag(ns_uri, 'book-title'))
        new_t.text = meta['title']
        _insert_in_xsd_order(title_info, new_t, _TITLE_INFO_XSD_ORDER)

    # 4. Аннотация (не трогаем богатую XML-разметку, если текст не менялся)
    if 'annotation' in meta:
        new_anno = (meta.get('annotation') or '').strip()
        old_anno = (current_meta.get('annotation') or '').strip()
        if new_anno != old_anno:
            old_anno_el = title_info.find(_qtag(ns_uri, 'annotation'))
            if old_anno_el is not None:
                title_info.remove(old_anno_el)
            if new_anno:
                new_anno_el = _build_annotation_element(ns_uri, new_anno)
                _insert_in_xsd_order(title_info, new_anno_el, _TITLE_INFO_XSD_ORDER)

    # 5. Обложка
    if cover_modified and cover_bytes:
        _apply_cover_to_xml(root, title_info, ns_uri, root_ns, cover_bytes, cover_mime)

    # 6. Язык (<lang>, не затрагивая <src-lang>)
    if 'lang' in meta:
        new_lang = (meta.get('lang') or '').strip().lower()
        old_lang = (current_meta.get('lang') or '').strip().lower()
        if new_lang != old_lang:
            lang_el = title_info.find(_qtag(ns_uri, 'lang'))
            if new_lang:
                if lang_el is None:
                    lang_el = _insert_in_xsd_order(title_info, ET.Element(_qtag(ns_uri, 'lang')), _TITLE_INFO_XSD_ORDER)
                lang_el.text = new_lang
            elif lang_el is not None:
                title_info.remove(lang_el)

    # 7. Переводчик (обновляем только первого <translator>, остальных сохраняем)
    tr_keys = ('translator_first', 'translator_middle', 'translator_last')
    if any(k in meta for k in tr_keys):
        new_tr = tuple((meta.get(k) or '').strip() for k in tr_keys)
        old_tr = tuple((current_meta.get(k) or '').strip() for k in tr_keys)
        if new_tr != old_tr:
            translators = title_info.findall(_qtag(ns_uri, 'translator'))
            if any(new_tr):
                tr0 = translators[0] if translators else _insert_in_xsd_order(
                    title_info, ET.Element(_qtag(ns_uri, 'translator')), _TITLE_INFO_XSD_ORDER
                )
                for tag, val in zip(('first-name', 'middle-name', 'last-name'), new_tr):
                    el = tr0.find(_qtag(ns_uri, tag))
                    if val:
                        if el is None:
                            el = ET.Element(_qtag(ns_uri, tag))
                            _insert_in_xsd_order(tr0, el, _AUTHOR_XSD_ORDER)
                        el.text = val
                    elif el is not None:
                        tr0.remove(el)
            elif translators:
                title_info.remove(translators[0])

    # 8. Серия
    seq_els = list(title_info.findall(_qtag(ns_uri, 'sequence')))
    seq_el = seq_els[0] if seq_els else None
    if meta.get('series'):
        if seq_el is None:
            seq_el = _insert_in_xsd_order(title_info, ET.Element(_qtag(ns_uri, 'sequence')), _TITLE_INFO_XSD_ORDER)
        seq_el.set('name', meta['series'])
        if meta.get('num'):
            seq_el.set('number', meta['num'])
        else:
            seq_el.attrib.pop('number', None)
    elif seq_els:
        for extra_seq in seq_els:
            title_info.remove(extra_seq)


def apply_updates_to_fb2_root(
    root,
    meta,
    cover_bytes=None,
    cover_mime="image/jpeg",
    cover_modified=False,
    orig_meta=None,
    xml_bytes=None,
):
    """Применяет изменения метаданных и обложки напрямую к уже распарсенному XML-дереву FB2."""
    current_meta = orig_meta if isinstance(orig_meta, dict) else parse_metadata(xml_bytes, root=root)
    title_info, ns_uri = _find_title_info(root)
    root_ns = _get_root_ns_uri(root)
    if title_info is not None:
        _apply_title_info_metadata(
            root,
            title_info,
            ns_uri,
            root_ns,
            meta,
            current_meta,
            cover_bytes=cover_bytes,
            cover_mime=cover_mime,
            cover_modified=cover_modified,
        )

    _apply_publish_info_field(root, 'publisher', meta, current_meta)
    _apply_publish_info_field(root, 'isbn', meta, current_meta)

    new_title = meta.get('title') or ''
    old_title = current_meta.get('title') or ''
    if new_title and new_title != old_title:
        body = root.find(_qtag(root_ns, 'body'))
        if body is not None:
            body_title = body.find(_qtag(root_ns, 'title'))
            if body_title is not None:
                paras = body_title.findall(_qtag(root_ns, 'p'))
                if len(paras) >= 1:
                    paras[-1].clear()
                    paras[-1].text = new_title
    return root


def update_fb2_xml(xml_bytes, meta, cover_bytes=None, cover_mime="image/jpeg", cover_modified=False, orig_meta=None):
    root = _parse_fb2_root(xml_bytes)
    if root is None:
        # Если тело FB2 сильно повреждено и XML не восстанавливается целиком,
        # отдаём санитизированные байты движку fbc без падения на ParseError.
        try:
            return _sanitize_fb2_xml_text(_decode_fb2_text(xml_bytes)).encode('utf-8')
        except Exception:
            return xml_bytes

    apply_updates_to_fb2_root(
        root,
        meta,
        cover_bytes=cover_bytes,
        cover_mime=cover_mime,
        cover_modified=cover_modified,
        orig_meta=orig_meta,
        xml_bytes=xml_bytes,
    )
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
        orig_meta=data.get("orig_meta"),
    )

    orig_mode = None
    if os.name != "nt":
        try:
            orig_mode = stat.S_IMODE(os.stat(src_path).st_mode)
        except OSError:
            orig_mode = 0o644

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
                            zout.writestr(info, _read_zip_entry_limited(zin, info.filename))
            with zipfile.ZipFile(tmp_zip, "r") as zchk:
                bad_member = zchk.testzip()
                if bad_member is not None:
                    raise RuntimeError(f"Ошибка проверки целостности ZIP ({bad_member})")
            if orig_mode is not None:
                try:
                    os.chmod(tmp_zip, orig_mode)
                except OSError:
                    pass
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
                fh.flush()
                os.fsync(fh.fileno())
            if orig_mode is not None:
                try:
                    os.chmod(tmp_fb2, orig_mode)
                except OSError:
                    pass
            os.replace(tmp_fb2, src_path)
        except Exception:
            if os.path.exists(tmp_fb2):
                os.remove(tmp_fb2)
            raise

    if data.get("cover_modified"):
        data["orig_cover_bytes"] = data.get("cover_bytes")
        data["orig_cover_mime"] = data.get("cover_mime")
        data["cover_modified"] = False
    data["orig_meta"] = copy_meta_dict(data["meta"])
    if "xml" in data:
        data["xml"] = new_xml_bytes
    from core.fb2.diagnostics import refresh_book_warnings
    refresh_book_warnings(data, xml_bytes=new_xml_bytes)
    logger.info("Метаданные/обложка сохранены в исходный файл: %s", data.get("display_name") or src_path)
    return src_path


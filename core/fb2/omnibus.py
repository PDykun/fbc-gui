"""Объединение нескольких книг FB2 (например, серии) в один том (Омнибус)."""

import os
import tempfile
import xml.etree.ElementTree as ET

from core.fb2.common import FB2_NS, MAX_FB2_XML_BYTES, XLINK_NS, logger
from core.fb2.xml_io import _find_title_info, _local_tag, _parse_fb2_root, _qtag, get_book_xml


def _normalize_element_tree(el, prefix, target_ns=FB2_NS):
    """Клонирует поддерево XML в пространство имён FB2 и добавляет префикс ко всем id и локальным #href."""
    local = _local_tag(el)
    new_el = ET.Element(_qtag(target_ns, local))
    for k, v in el.attrib.items():
        if k == "id" and v:
            new_el.set("id", f"{prefix}{v}")
        elif k.endswith("href"):
            new_k = f"{{{XLINK_NS}}}href"
            if v.startswith("#") and len(v) > 1:
                new_el.set(new_k, f"#{prefix}{v[1:]}")
            else:
                new_el.set(new_k, v)
        else:
            new_el.set(k, v)
    new_el.text = el.text
    new_el.tail = el.tail
    for child in el:
        new_el.append(_normalize_element_tree(child, prefix, target_ns=target_ns))
    return new_el


def _atomic_write_bytes(filepath, data):
    abs_path = os.path.abspath(filepath)
    parent = os.path.dirname(abs_path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".fbc_omnibus_", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp_path, abs_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def merge_fb2_books_to_omnibus(
    items,
    output_path,
    title=None,
    series=None,
    *,
    default_omnibus_suffix="Omnibus",
    default_collection_title="Collection",
    default_unknown_author="Unknown Author",
    default_book_prefix="Book",
    max_xml_bytes=MAX_FB2_XML_BYTES,
):
    """
    Объединяет 2+ книг FB2 в единый валидный файл .fb2 (Омнибус) с общим оглавлением,
    изоляцией всех внутренних ID/сносок/иллюстраций и метаданными серии.
    """
    if not items or len(items) < 2:
        raise ValueError("At least 2 books are required to build an omnibus")

    parsed_books = []
    for idx, data in enumerate(items, start=1):
        xml_bytes = get_book_xml(data)
        if not xml_bytes:
            label = data.get("display_name") or os.path.basename(data.get("path") or f"book_{idx}")
            raise ValueError(f"Failed to read source FB2: {label}")
        orig_meta = data.get("orig_meta")
        meta = data.get("meta") or {}
        if data.get("cover_modified") or (isinstance(orig_meta, dict) and meta != orig_meta):
            from core.fb2.metadata import update_fb2_xml

            xml_bytes = update_fb2_xml(
                xml_bytes,
                meta,
                cover_bytes=data.get("cover_bytes"),
                cover_mime=data.get("cover_mime", "image/jpeg"),
                cover_modified=bool(data.get("cover_modified", False)),
                orig_meta=orig_meta,
            )
        root = _parse_fb2_root(xml_bytes)
        if root is None:
            label = data.get("display_name") or os.path.basename(data.get("path") or f"book_{idx}")
            raise ValueError(f"Failed to parse book XML: {label}")
        parsed_books.append((idx, data, root))

    first_meta = (parsed_books[0][1].get("meta") or {})
    detected_series = str(series if series is not None else (first_meta.get("series") or "")).strip()
    if title and str(title).strip():
        omnibus_title = str(title).strip()
    elif detected_series:
        omnibus_title = f"{detected_series} ({default_omnibus_suffix})"
    else:
        first_title = (first_meta.get("title") or "").strip() or default_collection_title
        omnibus_title = f"{first_title} (+{len(parsed_books) - 1})"

    out_root = ET.Element(_qtag(FB2_NS, "FictionBook"))
    desc_el = ET.SubElement(out_root, _qtag(FB2_NS, "description"))
    ti_el = ET.SubElement(desc_el, _qtag(FB2_NS, "title-info"))

    # Жанры (объединённый уникальный список из всех книг)
    seen_genres = set()
    for _, data, _ in parsed_books:
        for g in ((data.get("meta") or {}).get("genres") or []):
            g_str = str(g).strip()
            if g_str and g_str not in seen_genres:
                seen_genres.add(g_str)
                g_el = ET.SubElement(ti_el, _qtag(FB2_NS, "genre"))
                g_el.text = g_str
    if not seen_genres:
        g_el = ET.SubElement(ti_el, _qtag(FB2_NS, "genre"))
        g_el.text = "prose"

    # Автор (из первой книги)
    author_el = ET.SubElement(ti_el, _qtag(FB2_NS, "author"))
    for key, tag in (("first", "first-name"), ("mid", "middle-name"), ("last", "last-name")):
        val = (first_meta.get(key) or "").strip()
        if val:
            sub = ET.SubElement(author_el, _qtag(FB2_NS, tag))
            sub.text = val
    if len(author_el) == 0:
        sub = ET.SubElement(author_el, _qtag(FB2_NS, "last-name"))
        sub.text = default_unknown_author

    bt_el = ET.SubElement(ti_el, _qtag(FB2_NS, "book-title"))
    bt_el.text = omnibus_title

    # Аннотация со списком вошедших книг
    anno_el = ET.SubElement(ti_el, _qtag(FB2_NS, "annotation"))
    for idx, data, _ in parsed_books:
        m = data.get("meta") or {}
        b_title = (m.get("title") or data.get("display_name") or f"{default_book_prefix} {idx}").strip()
        p_el = ET.SubElement(anno_el, _qtag(FB2_NS, "p"))
        p_el.text = f"{idx}. {b_title}"

    # Обложка из первой книги, у которой она есть (с учётом её префикса b{idx}_)
    for idx, _data, root in parsed_books:
        ti, ns = _find_title_info(root)
        if ti is not None:
            cp = ti.find(_qtag(ns, "coverpage"))
            if cp is not None and len(cp) > 0:
                ti_el.append(_normalize_element_tree(cp, f"b{idx}_", target_ns=FB2_NS))
                break

    lang_val = (first_meta.get("lang") or "ru").strip() or "ru"
    lang_el = ET.SubElement(ti_el, _qtag(FB2_NS, "lang"))
    lang_el.text = lang_val

    if detected_series:
        seq_el = ET.SubElement(ti_el, _qtag(FB2_NS, "sequence"))
        seq_el.set("name", detected_series)

    # Главный <body> с оглавлением по книгам
    main_body = ET.SubElement(out_root, _qtag(FB2_NS, "body"))
    body_title = ET.SubElement(main_body, _qtag(FB2_NS, "title"))
    author_line = " ".join(
        p for p in ((first_meta.get("first") or "").strip(), (first_meta.get("last") or "").strip()) if p
    )
    if author_line:
        p_auth = ET.SubElement(body_title, _qtag(FB2_NS, "p"))
        p_auth.text = author_line
    p_bt = ET.SubElement(body_title, _qtag(FB2_NS, "p"))
    p_bt.text = omnibus_title

    notes_sections = []
    all_binaries = []

    for idx, data, root in parsed_books:
        prefix = f"b{idx}_"
        m = data.get("meta") or {}
        b_title = (m.get("title") or data.get("display_name") or f"{default_book_prefix} {idx}").strip()
        book_sec = ET.SubElement(main_body, _qtag(FB2_NS, "section"))
        book_sec.set("id", f"{prefix}book_root")
        sec_title = ET.SubElement(book_sec, _qtag(FB2_NS, "title"))
        sec_title_p = ET.SubElement(sec_title, _qtag(FB2_NS, "p"))
        sec_title_p.text = b_title

        bodies = [child for child in root if _local_tag(child) == "body"]
        for b_idx, body in enumerate(bodies):
            b_name = (body.attrib.get("name") or "").strip().lower()
            if b_name in ("notes", "comments") or (b_idx > 0 and b_name):
                for child in body:
                    if _local_tag(child) == "section":
                        notes_sections.append(_normalize_element_tree(child, prefix, target_ns=FB2_NS))
            else:
                for child in body:
                    if _local_tag(child) == "title":
                        continue
                    book_sec.append(_normalize_element_tree(child, prefix, target_ns=FB2_NS))

        for child in root:
            if _local_tag(child) == "binary":
                all_binaries.append(_normalize_element_tree(child, prefix, target_ns=FB2_NS))

    if notes_sections:
        notes_body = ET.SubElement(out_root, _qtag(FB2_NS, "body"))
        notes_body.set("name", "notes")
        for nsec in notes_sections:
            notes_body.append(nsec)

    for bin_el in all_binaries:
        out_root.append(bin_el)

    xml_out = ET.tostring(out_root, encoding="utf-8", xml_declaration=True)
    if max_xml_bytes and len(xml_out) > max_xml_bytes:
        raise ValueError(
            f"Merged omnibus exceeds maximum FB2 size limit ({len(xml_out)} > {max_xml_bytes} bytes)"
        )
    _atomic_write_bytes(output_path, xml_out)
    logger.info("Создан омнибус (%d книг): %s", len(parsed_books), output_path)
    return {
        "path": os.path.abspath(output_path),
        "books_count": len(parsed_books),
        "title": omnibus_title,
        "series": detected_series,
    }

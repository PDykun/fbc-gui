import os
import re

from core.i18n import tr


DEFAULT_CSS_UI_STATE = {
    "font_para": "PT-Astra-Serif_Regular.ttf",
    "font_drop": "PomorskyUnicode.otf",
    "font_title": "PT-Astra-Serif_Regular.ttf",
    "font_author": "PT-Astra-Serif_Regular.ttf",
    "pdf_frame": "0",
    "h1_sz": "150%",
    "h1_cl": "red",
    "h1_al": "center",
    "auth_sz": "110%",
    "auth_cl": "green",
    "auth_al": "center",
    "auth_style": "italic",
    "h2_sz": "130%",
    "h2_cl": "blue",
    "h2_al": "center",
    "h3_sz": "120%",
    "h3_cl": "dimgray",
    "h3_al": "center",
    "h4_sz": "120%",
    "h4_cl": "green",
    "h4_al": "center",
    "h5_sz": "120%",
    "h5_cl": "magenta",
    "h5_al": "center",
    "p_align": "justify",
    "text_indent": "1em",
    "sub_align": "center",
    "drop_color": "red",
    "drop_size": "4em",
    "anno_size": "70%",
    "anno_color": "blue",
    "anno_align": "center",
    "anno_style": "normal",
    "epi_size": "100%",
    "epi_color": "dimgray",
    "epi_align": "right",
    "epi_style": "italic",
    "poem_size": "70%",
    "poem_color": "purple",
    "poem_align": "left",
    "poem_style": "italic",
    "note_size": "70%",
    "note_color": "black",
    "note_bg": "#e6e6fa",
    "note_border": "1px #505050 solid",
    "note_style": "italic",
    "img_align": "center",
    "img_width": "100%",
    "img_cap_sz": "85%",
    "img_cap_cl": "dimgray",
    "img_cap_st": "italic",
}

MONOCHROME_CSS_UI_STATE = {
    **DEFAULT_CSS_UI_STATE,
    "h1_cl": "black",
    "auth_cl": "dimgray",
    "h2_cl": "black",
    "h3_cl": "dimgray",
    "h4_cl": "black",
    "h5_cl": "dimgray",
    "drop_color": "black",
    "anno_color": "dimgray",
    "epi_color": "dimgray",
    "poem_color": "black",
    "note_color": "black",
    "note_bg": "#f4f4f4",
    "note_border": "1px #505050 solid",
    "img_cap_cl": "dimgray",
}


def get_default_css_ui_state():
    """Возвращает эталонное состояние стилей (как сразу после установки, цветной вариант)."""
    return dict(DEFAULT_CSS_UI_STATE)


def get_monochrome_css_ui_state():
    """Возвращает эталонное чёрно-белое состояние стилей для монохромных ридеров."""
    return dict(MONOCHROME_CSS_UI_STATE)


def parse_css_file_to_state(css_path):
    """Разбирает ebook_styles.css в словарь параметров интерфейса."""
    st = {}
    if not os.path.exists(css_path):
        return st

    with open(css_path, 'r', encoding='utf-8') as f:
        content = f.read()

    def parse_prop(block_text, prop_name):
        m = re.search(rf'(?:^|[\s;{{]){re.escape(prop_name)}\s*:\s*([^;!}}]+)', block_text)
        return m.group(1).strip() if m else None

    def parse_block(selector_regex, sz_key=None, cl_key=None, al_key=None, st_key=None):
        m = re.search(selector_regex + r'\s*\{([^}]+)\}', content)
        if not m:
            return
        blk = m.group(1)
        if sz_key:
            v = parse_prop(blk, 'font-size')
            if v:
                st[sz_key] = v
        if cl_key:
            v = parse_prop(blk, 'color')
            if v:
                st[cl_key] = v
        if al_key:
            v = parse_prop(blk, 'text-align')
            if v:
                st[al_key] = v
        if st_key:
            v = parse_prop(blk, 'font-style')
            if v:
                st[st_key] = v

    st["pdf_frame"] = "0"
    m_pf = re.search(r'@page\s*\{[^}]*-fbc-page-frame\s*:\s*([^;\s}]+)', content)
    if m_pf:
        pf_val = m_pf.group(1).strip()
        st["pdf_frame"] = "0" if pf_val in ("0", "0pt", "0px", "none") else pf_val

    for name, key in [
        ("dropcaps", "font_drop"),
        ("paragraph", "font_para"),
        ("title-font", "font_title"),
        ("author-font", "font_author")
    ]:
        m = re.search(rf'font-family:\s*"{name}"\s*;\s*src:\s*url\("fonts/([^"]+)"\)', content)
        st[key] = m.group(1) if m else "__none__"

    parse_block(r'\.book-title[^{]*', "h1_sz", "h1_cl", "h1_al")
    parse_block(r'\.book-author[^{]*', "auth_sz", "auth_cl", "auth_al", "auth_style")
    parse_block(r'\.chapter-title-header[^{]*', "h2_sz", "h2_cl", "h2_al")
    parse_block(r'\.section-title-h2\s+\.section-title-header[^{]*', "h3_sz", "h3_cl", "h3_al")
    parse_block(r'\.section-title-h3\s+\.section-title-header[^{]*', "h4_sz", "h4_cl", "h4_al")
    parse_block(r'\.section-title-h4\s+\.section-title-header[^{]*', "h5_sz", "h5_cl", "h5_al")

    parse_block(r'\.section-subtitle[^{]*', al_key="sub_align")
    p_m = re.search(r'(?:^|\n)p\s*\{([^}]+)\}', content)
    if p_m:
        p_blk = p_m.group(1)
        ind = parse_prop(p_blk, 'text-indent')
        if ind:
            st["text_indent"] = ind
        pal = parse_prop(p_blk, 'text-align')
        if pal:
            st["p_align"] = pal

    parse_block(r'\.dropcap[^{]*', sz_key="drop_size", cl_key="drop_color")

    parse_block(r'\.annotation\b[^{]*', "anno_size", "anno_color", "anno_align", "anno_style")
    parse_block(r'\.epigraph\b[^{]*', "epi_size", "epi_color", "epi_align", "epi_style")
    parse_block(r'\.poem\b[^{]*', "poem_size", "poem_color", "poem_align", "poem_style")
    parse_block(r'\.footnote[^{]*', "note_size", "note_color", st_key="note_style")

    fn_m = re.search(r'\.footnote[^{]*\{([^}]+)\}', content)
    if fn_m:
        fn_blk = fn_m.group(1)
        bg = parse_prop(fn_blk, 'background')
        if bg:
            st["note_bg"] = bg
        brd = parse_prop(fn_blk, 'border')
        if brd:
            st["note_border"] = brd

    parse_block(r'\.image\b[^{]*', al_key="img_align")
    im_m = re.search(r'\.image\s+img[^{]*\{([^}]+)\}', content)
    if im_m:
        mw = parse_prop(im_m.group(1), 'max-width')
        if mw:
            st["img_width"] = mw
    parse_block(r'\.image-caption[^{]*', sz_key="img_cap_sz", cl_key="img_cap_cl", st_key="img_cap_st")

    return st


def generate_css_content(st, fonts_dir):
    """Генерирует содержимое ebook_styles.css на основе словаря стилей."""
    h1_sz, h1_cl, h1_al = st["h1_sz"], st["h1_cl"], st["h1_al"]
    auth_sz, auth_cl, auth_al, auth_style = st["auth_sz"], st["auth_cl"], st["auth_al"], st["auth_style"]
    h2_sz, h2_cl, h2_al = st["h2_sz"], st["h2_cl"], st["h2_al"]
    h3_sz, h3_cl, h3_al = st["h3_sz"], st["h3_cl"], st["h3_al"]
    h4_sz, h4_cl, h4_al = st["h4_sz"], st["h4_cl"], st["h4_al"]
    h5_sz, h5_cl, h5_al = st["h5_sz"], st["h5_cl"], st["h5_al"]
    p_al, sub_al, indent_val = st["p_align"], st["sub_align"], st["text_indent"]
    drop_cl, drop_sz = st["drop_color"], st["drop_size"]
    anno_sz, anno_cl, anno_al, anno_style = st["anno_size"], st["anno_color"], st["anno_align"], st["anno_style"]
    epi_sz, epi_cl, epi_al, epi_style = st["epi_size"], st["epi_color"], st["epi_align"], st["epi_style"]
    poem_sz, poem_cl, poem_al, poem_style = st["poem_size"], st["poem_color"], st["poem_align"], st["poem_style"]
    note_sz, note_cl, note_bg, note_border, note_style = st["note_size"], st["note_color"], st["note_bg"], st["note_border"], st["note_style"]
    img_al, img_w = st["img_align"], st["img_width"]
    img_cap_sz, img_cap_cl, img_cap_st = st["img_cap_sz"], st["img_cap_cl"], st["img_cap_st"]

    def _norm_font(val, default):
        if val in ("__none__", "Нет", "None"):
            return "__none__"
        return val or default

    para_font = _norm_font(st.get("font_para"), "PT-Astra-Serif_Regular.ttf")
    title_font = _norm_font(st.get("font_title"), "PT-Astra-Serif_Regular.ttf")
    author_font = _norm_font(st.get("font_author"), "PT-Astra-Serif_Regular.ttf")
    drop_font = _norm_font(st.get("font_drop"), "PomorskyUnicode.otf")

    has_para = para_font != "__none__"
    has_title = title_font != "__none__"
    has_author = author_font != "__none__"
    has_drop = drop_font != "__none__"

    extra_para_faces = ""
    if has_para and para_font.startswith("PT-Astra-Serif") and os.path.exists(os.path.join(fonts_dir, "PT-Astra-Serif_Regular.ttf")):
        para_reg = "PT-Astra-Serif_Regular.ttf"
        para_it = "PT-Astra-Serif_Italic.ttf" if os.path.exists(os.path.join(fonts_dir, "PT-Astra-Serif_Italic.ttf")) else para_reg
        para_bo = "PT-Astra-Serif_Bold.ttf" if os.path.exists(os.path.join(fonts_dir, "PT-Astra-Serif_Bold.ttf")) else para_reg
        para_boit = "PT-Astra-Serif_Bold-Italic.ttf" if os.path.exists(os.path.join(fonts_dir, "PT-Astra-Serif_Bold-Italic.ttf")) else para_bo
        extra_para_faces = "\n".join([
            f'@font-face {{ font-family: "paragraph"; src: url("fonts/{para_it}"); font-style: italic; font-weight: normal; }}',
            f'@font-face {{ font-family: "paragraph"; src: url("fonts/{para_bo}"); font-style: normal; font-weight: bold; }}',
            f'@font-face {{ font-family: "paragraph"; src: url("fonts/{para_boit}"); font-style: italic; font-weight: bold; }}'
        ])
        para_font = para_reg

    para_decl = 'font-family: "paragraph"; ' if has_para else ''
    drop_decl = 'font-family: "dropcaps"; ' if has_drop else ''

    if has_title and has_para:
        title_decl_imp = 'font-family: "title-font", "paragraph" !important; '
        title_decl = 'font-family: "title-font", "paragraph"; '
    elif has_title:
        title_decl_imp = 'font-family: "title-font" !important; '
        title_decl = 'font-family: "title-font"; '
    elif has_para:
        title_decl_imp = 'font-family: "paragraph" !important; '
        title_decl = 'font-family: "paragraph"; '
    else:
        title_decl_imp = ''
        title_decl = ''

    if has_author and has_para:
        author_decl_imp = 'font-family: "author-font", "paragraph" !important; '
    elif has_author:
        author_decl_imp = 'font-family: "author-font" !important; '
    elif has_para:
        author_decl_imp = 'font-family: "paragraph" !important; '
    else:
        author_decl_imp = ''

    pdf_frame_val = st.get("pdf_frame", "0")
    css_lines = [
        f'body {{ {para_decl}font-weight: normal; font-style: normal; line-height: 100%; }}',
        f'@page {{ margin-left: 10px; margin-right: 10px; margin-top: 10px; margin-bottom: 5px; {f"-fbc-page-frame: {pdf_frame_val}; " if pdf_frame_val != "0" else ""} }}',
    ]
    if has_drop or has_para or has_title or has_author:
        css_lines.append('')
    if has_drop:
        css_lines.append('@font-face { font-family: "dropcaps"; src: url("fonts/' + drop_font + '"); }')
    if has_para:
        css_lines.append('@font-face { font-family: "paragraph"; src: url("fonts/' + para_font + '"); font-weight: normal; font-style: normal; }')
        if extra_para_faces:
            css_lines.append(extra_para_faces)
    if has_title:
        css_lines.extend([
            '@font-face { font-family: "title-font"; src: url("fonts/' + title_font + '"); font-weight: bold; font-style: normal; }',
            '@font-face { font-family: "title-font"; src: url("fonts/' + title_font + '"); font-weight: normal; font-style: normal; }',
        ])
    if has_author:
        css_lines.extend([
            '@font-face { font-family: "author-font"; src: url("fonts/' + author_font + '"); font-style: italic; font-weight: normal; }',
            '@font-face { font-family: "author-font"; src: url("fonts/' + author_font + '"); font-style: normal; font-weight: normal; }',
            '@font-face { font-family: "author-font"; src: url("fonts/' + author_font + '"); font-style: italic; font-weight: bold; }',
            '@font-face { font-family: "author-font"; src: url("fonts/' + author_font + '"); font-style: normal; font-weight: bold; }',
        ])

    css_lines.extend([
        '',
        '.body-title { page-break-before: always; margin-top: 2em; margin-bottom: 1.5em; text-indent: 0; text-align: center; }',
        '',
        '.book-author, span.book-author, .body-title .book-author, .body-title-header.book-author, .body-title-header .book-author, .text-author, .author {',
        f'    {author_decl_imp}font-size: {auth_sz} !important; font-weight: bold !important;',
        f'    font-style: {auth_style} !important; color: {auth_cl} !important; text-align: {auth_al} !important;',
        '    margin-top: 0.4em !important; margin-bottom: 0.4em !important; page-break-before: avoid;',
        '}',
        '',
        '.book-title, span.book-title, .body-title .book-title, .body-title-header.book-title, .body-title-header .book-title {',
        f'    {title_decl_imp}font-size: {h1_sz} !important; font-weight: bold !important;',
        '    font-style: normal !important; color: ' + h1_cl + ' !important; text-align: ' + h1_al + ' !important;',
        '    margin-top: 0.8em !important; margin-bottom: 0.5em !important;',
        '}',
        '',
        f'.body-title-header, .body-title h1, h1.body-title-header {{ {title_decl}font-size: {h1_sz}; font-weight: bold; color: {h1_cl}; text-align: {h1_al}; }}',
        '',
        '.chapter-title { page-break-before: always; margin-top: 2em; margin-bottom: 1em; text-indent: 0; }',
        f'.chapter-title-header, .chapter-title h1, .chapter-title h2, h1.chapter-title-header {{ {para_decl}font-size: {h2_sz}; font-weight: bold; color: {h2_cl}; text-align: {h2_al}; margin-top: 1em; margin-bottom: 0.8em; }}',
        '',
        '.section-title-h2 { page-break-before: always; margin-top: 1.5em; margin-bottom: 0.8em; text-indent: 0; }',
        f'.section-title-h2 .section-title-header, .section-title-h2 h2, .section-title-h2 h3 {{ {para_decl}font-size: {h3_sz}; font-weight: bold; color: {h3_cl}; text-align: {h3_al}; }}',
        '',
        f'.section-title-h3 .section-title-header, .section-title-h3 h3, .section-title-h3 h4 {{ {para_decl}font-size: {h4_sz}; font-weight: bold; color: {h4_cl}; text-align: {h4_al}; }}',
        '',
        f'.section-title-h4 .section-title-header, .section-title-h4 h4, .section-title-h4 h5 {{ {para_decl}font-size: {h5_sz}; font-weight: bold; color: {h5_cl}; text-align: {h5_al}; }}',
        '',
        f'.section-subtitle, .subtitle, p.subtitle {{ {para_decl}page-break-after: avoid; text-align: {sub_al}; font-weight: bold; font-style: italic; margin-bottom: 0.8em; margin-top: 0.5em; text-indent: 0em; }}',
        '',
        f'p {{ {para_decl}font-weight: normal; font-style: normal; text-indent: {indent_val}; margin-bottom: 0pt; margin-top: 0pt; text-align: {p_al}; }}',
        '.emptyline { margin-top: 1em; }',
        '',
        '.dropcap, span.dropcaps, span.dropcap {',
        f'    {drop_decl}float: left; font-weight: bold; color: ' + drop_cl + '; font-size: ' + drop_sz + ';',
        '    line-height: 0.85; margin-top: 0em; margin-bottom: -0.2em; margin-right: 0.08em; padding-right: .1em;',
        '}',
        f'.has-dropcap, p.has-dropcap {{ text-indent: 0 !important; text-align: {p_al}; }}',
        '',
        f'.annotation {{ {para_decl}margin: 1.5em; font-size: {anno_sz}; text-align: {anno_al}; font-style: {anno_style}; color: {anno_cl}; }}',
        '',
        f'.epigraph {{ {para_decl}margin-left: 35%; text-align: {epi_al}; margin-top: 0.5em; margin-bottom: 0.3em; font-style: {epi_style}; font-size: {epi_sz}; color: {epi_cl}; }}',
        '',
        f'.poem {{ {para_decl}text-indent: 0em; margin: 0.8em 0 0.8em 2.5em; font-style: {poem_style}; font-size: {poem_sz}; color: {poem_cl}; text-align: {poem_al}; }}',
        '',
        f'.footnote, .blocknote {{ {para_decl}font-style: {note_style}; font-size: {note_sz}; border-radius: 4px; background: {note_bg}; padding: 6px 10px; border: {note_border}; color: {note_cl}; margin-top: 1em; margin-bottom: 1em; }}',
        '',
        f'.image, .image-block, div.image {{ text-align: {img_al}; text-indent: 0; margin: 0.8em 0; page-break-inside: avoid; }}',
        f'.image img, .image svg, img.image-inline, svg {{ max-width: {img_w}; height: auto; }}',
        f'.image-caption, p.image-caption {{ {para_decl}font-size: {img_cap_sz}; color: {img_cap_cl}; font-style: {img_cap_st}; text-align: {img_al}; text-indent: 0; margin-top: 0.3em; margin-bottom: 0.8em; }}'
    ])
    return '\n'.join(css_lines) + '\n'


def build_full_preview_html(
    st,
    font_families,
    svg_mode,
    fonts_dir,
    app_name,
    app_version,
    p_al_lbl,
    img_al_lbl,
    for_browser=False,
    grayscale=False,
    book_preview=None,
    dropcaps_enable=True,
    use_web_engine=False,
):
    """Собирает HTML-страницу для встроенного превью (QWebEngineView / QTextEdit) или открытия в браузере."""
    h1_sz, h1_cl, h1_al = st["h1_sz"], st["h1_cl"], st["h1_al"]
    auth_sz, auth_cl, auth_al, auth_style = st["auth_sz"], st["auth_cl"], st["auth_al"], st["auth_style"]
    h2_sz, h2_cl, h2_al = st["h2_sz"], st["h2_cl"], st["h2_al"]
    h3_sz, h3_cl, h3_al = st["h3_sz"], st["h3_cl"], st["h3_al"]
    h4_sz, h4_cl, h4_al = st["h4_sz"], st["h4_cl"], st["h4_al"]
    h5_sz, h5_cl, h5_al = st["h5_sz"], st["h5_cl"], st["h5_al"]
    p_al, sub_al, indent_val = st["p_align"], st["sub_align"], st["text_indent"]
    drop_cl, drop_sz = st["drop_color"], st["drop_size"]
    anno_sz, anno_cl, anno_al, anno_style = st["anno_size"], st["anno_color"], st["anno_align"], st["anno_style"]
    epi_sz, epi_cl, epi_al, epi_style = st["epi_size"], st["epi_color"], st["epi_align"], st["epi_style"]
    poem_sz, poem_cl, poem_al, poem_style = st["poem_size"], st["poem_color"], st["poem_align"], st["poem_style"]
    note_sz, note_cl, note_bg, note_border, note_style = st["note_size"], st["note_color"], st["note_bg"], st["note_border"], st["note_style"]
    img_al, img_w = st["img_align"], st["img_width"]
    img_cap_sz, img_cap_cl, img_cap_st = st["img_cap_sz"], st["img_cap_cl"], st["img_cap_st"]

    para_file = st.get("font_para") or "PT-Astra-Serif_Regular.ttf"
    title_file = st.get("font_title") or "PT-Astra-Serif_Regular.ttf"
    author_file = st.get("font_author") or "PT-Astra-Serif_Regular.ttf"
    drop_file = st.get("font_drop") or "PomorskyUnicode.otf"

    para_fam = font_families.get("para", "Georgia")
    title_fam = font_families.get("title", "Georgia")
    author_fam = font_families.get("author", "Georgia")
    drop_fam = font_families.get("drop", "Georgia")

    rich_html = bool(for_browser or use_web_engine)
    fonts_url_dir = fonts_dir.replace("\\", "/")
    font_faces = ""
    if rich_html:
        ff_lines = []
        seen_ff = set()
        for fam, fname in [
            (para_fam, para_file),
            (title_fam, title_file),
            (author_fam, author_file),
            (drop_fam, drop_file),
        ]:
            if fname and fname not in ("__none__", "Нет", "None") and (fam, fname) not in seen_ff:
                seen_ff.add((fam, fname))
                ff_lines.append(f'@font-face {{ font-family: "{fam}"; src: url("file://{fonts_url_dir}/{fname}"); }}')
        font_faces = "\n        ".join(ff_lines)

    def _disp_font(fname):
        return tr("styles.font_none") if fname in ("__none__", "Нет", "None", "") else fname

    para_disp = _disp_font(para_file)
    title_disp = _disp_font(title_file)
    author_disp = _disp_font(author_file)
    drop_disp = _disp_font(drop_file)

    note_bg_css = note_bg if note_bg != "transparent" else "#FDFBF7"
    pf_val = st.get("pdf_frame", "0")
    page_outline_css = f"outline: {pf_val} solid #EBE8E0;" if pf_val != "0" else ""

    if book_preview and (book_preview.get("title") or book_preview.get("blocks")):
        import html as _html
        parts = []
        if book_preview.get("cover_data_uri"):
            gray_css = "filter: grayscale(100%);" if grayscale else ""
            parts.append(
                f'<div style="text-align: {img_al}; margin: 0 0 18px 0;">'
                f'<img src="{book_preview["cover_data_uri"]}" style="max-height: 240px; max-width: {img_w}; border-radius: 4px; box-shadow: 0 3px 12px rgba(0,0,0,0.16); {gray_css}">'
                f'</div>'
            )
        if book_preview.get("author"):
            parts.append(
                f'<div style="font-family: \'{author_fam}\', Georgia, serif; font-size: {auth_sz}; color: {auth_cl}; text-align: {auth_al}; font-style: {auth_style}; font-weight: bold; margin-top: 4px; margin-bottom: 6px;">'
                f'{_html.escape(book_preview["author"])}</div>'
            )
        if book_preview.get("title"):
            parts.append(
                f'<div style="font-family: \'{title_fam}\', Georgia, serif; font-size: {h1_sz}; color: {h1_cl}; text-align: {h1_al}; font-weight: bold; font-style: normal; margin-top: 4px; margin-bottom: 8px;">'
                f'{_html.escape(book_preview["title"])}</div>'
            )
        if book_preview.get("series"):
            parts.append(
                f'<div style="font-family: \'{para_fam}\', Georgia, serif; text-align: {sub_al}; font-style: italic; font-weight: bold; color: #555555; margin-bottom: 14px;">'
                f'{_html.escape(book_preview["series"])}</div>'
            )
        if book_preview.get("annotation"):
            anno_html = "<br>".join(book_preview["annotation"])
            parts.append(
                f'<div style="font-family: \'{para_fam}\', Georgia, serif; font-size: {anno_sz}; color: {anno_cl}; text-align: {anno_al}; font-style: {anno_style}; margin: 14px 28px;">'
                f'{anno_html}</div>'
            )
        if book_preview.get("epigraph_lines"):
            epi_html = "<br>".join(book_preview["epigraph_lines"])
            parts.append(
                f'<div style="font-family: \'{para_fam}\', Georgia, serif; font-size: {epi_sz}; color: {epi_cl}; text-align: {epi_al}; font-style: {epi_style}; margin-left: 32%; margin-top: 12px; margin-bottom: 4px;">'
                f'{epi_html}</div>'
            )
            if book_preview.get("epigraph_author"):
                parts.append(
                    f'<div style="font-family: \'{para_fam}\', Georgia, serif; font-size: {epi_sz}; color: {epi_cl}; text-align: {epi_al}; font-weight: bold; margin-left: 32%; margin-bottom: 16px;">'
                    f'{book_preview["epigraph_author"]}</div>'
                )

        parts.append('<hr class="divider">')

        if book_preview.get("chapter_title"):
            parts.append(
                f'<div style="font-family: \'{para_fam}\', Georgia, serif; font-size: {h2_sz}; color: {h2_cl}; text-align: {h2_al}; font-weight: bold; margin-top: 16px; margin-bottom: 10px;">'
                f'{book_preview["chapter_title"]}</div>'
            )

        dropcap_used = False
        for btype, bcontent in book_preview.get("blocks", []):
            if btype == "p":
                if dropcaps_enable and not dropcap_used:
                    m_lead = re.match(r'^([^A-Za-zА-Яа-яЁё<]*)([A-Za-zА-Яа-яЁё])([\s\S]*)$', bcontent)
                    if m_lead:
                        lead_punct, first_ch, rest = m_lead.group(1), m_lead.group(2), m_lead.group(3)
                        dropcap_used = True
                        parts.append(
                            f'<p style="font-family: \'{para_fam}\', Georgia, serif; font-weight: normal; font-style: normal; text-indent: 0; text-align: {p_al}; margin: 6px 0;">'
                            f'{lead_punct}<span style="font-family: \'{drop_fam}\', Georgia, serif; font-size: {drop_sz}; color: {drop_cl}; font-weight: bold; float: left; line-height: 0.85; margin-right: 6px;">{first_ch}</span>{rest}</p>'
                        )
                        continue
                parts.append(
                    f'<p style="font-family: \'{para_fam}\', Georgia, serif; font-weight: normal; font-style: normal; text-indent: {indent_val}; text-align: {p_al}; margin: 6px 0;">'
                    f'{bcontent}</p>'
                )
            elif btype == "subtitle":
                parts.append(
                    f'<div style="font-family: \'{para_fam}\', Georgia, serif; text-align: {sub_al}; font-style: italic; font-weight: bold; color: #555555; margin: 12px 0;">'
                    f'{bcontent}</div>'
                )
            elif btype == "empty":
                parts.append('<div style="height: 0.8em;"></div>')
            elif btype == "poem":
                parts.append(
                    f'<div style="font-family: \'{para_fam}\', Georgia, serif; font-size: {poem_sz}; color: {poem_cl}; text-align: {poem_al}; font-style: {poem_style}; margin: 12px 2.5em;">'
                    f'{bcontent}</div>'
                )
            elif btype == "cite":
                parts.append(
                    f'<div style="font-family: \'{para_fam}\', Georgia, serif; font-size: {epi_sz}; color: {epi_cl}; font-style: italic; margin: 10px 2em; padding-left: 12px; border-left: 2px solid #cbd5e1;">'
                    f'{bcontent}</div>'
                )

        if book_preview.get("footnote_paras"):
            fn_hdr = f'<div style="font-weight: bold; margin-bottom: 4px;">[{book_preview["footnote_title"]}]</div>' if book_preview.get("footnote_title") else ""
            fn_body = "<br>".join(book_preview["footnote_paras"])
            parts.append(
                f'<div style="font-family: \'{para_fam}\', Georgia, serif; font-size: {note_sz}; color: {note_cl}; background-color: {note_bg_css}; border: {note_border}; font-style: {note_style}; padding: 8px 12px; border-radius: 4px; margin: 14px 0;">'
                f'{fn_hdr}{fn_body}</div>'
            )

        parts.append(
            f'<div style="text-align: center; font-size: 85%; font-style: italic; color: #888888; margin-top: 20px;">'
            f'{tr("preview.sample_footer", app=app_name, ver=app_version)}</div>'
        )
        body_inner = "\n    ".join(parts)
        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{tr("preview.html_title", app=app_name)}</title>
<style>
    {font_faces}
    body {{
        background-color: {"#EDEAE4" if rich_html else "#FDFBF7"};
        color: #222222;
        font-family: "{para_fam}", Georgia, serif;
        margin: 0;
        padding: {"24px" if rich_html else "8px"};
        line-height: 1.55;
    }}
    .page {{
        max-width: 720px;
        margin: 0 auto;
        background-color: #FDFBF7;
        padding: {"36px 46px" if rich_html else "10px 18px"};
        {page_outline_css}
        {"box-shadow: 0 4px 18px rgba(0,0,0,0.12); border-radius: 8px;" if rich_html else ""}
    }}
    .divider {{
        border: none;
        border-top: 1px dashed #d5cfc2;
        margin: 18px 0;
    }}
</style>
</head>
<body>
<div class="page">
    {body_inner}
</div>
</body>
</html>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{tr("preview.html_title", app=app_name)}</title>
<style>
    {font_faces}
    body {{
        background-color: {"#EDEAE4" if rich_html else "#FDFBF7"};
        color: #222222;
        font-family: "{para_fam}", Georgia, serif;
        margin: 0;
        padding: {"24px" if rich_html else "8px"};
        line-height: 1.5;
    }}
    .page {{
        max-width: 720px;
        margin: 0 auto;
        background-color: #FDFBF7;
        padding: {"40px 50px" if rich_html else "10px 18px"};
        {page_outline_css}
        {"box-shadow: 0 4px 18px rgba(0,0,0,0.12); border-radius: 6px;" if rich_html else ""}
    }}
    .divider {{
        border: none;
        border-top: 1px dashed #d5cfc2;
        margin: 18px 0;
    }}
</style>
</head>
<body>
<div class="page">
    <div style="font-family: '{author_fam}', Georgia, serif; font-size: {auth_sz}; color: {auth_cl}; text-align: {auth_al}; font-style: {auth_style}; font-weight: bold; margin-top: 4px; margin-bottom: 6px;">
        {tr("preview.sample_author")}
    </div>
    <div style="font-family: '{title_fam}', Georgia, serif; font-size: {h1_sz}; color: {h1_cl}; text-align: {h1_al}; font-weight: bold; font-style: normal; margin-top: 4px; margin-bottom: 10px;">
        {tr("preview.sample_title")}
    </div>
    <div style="font-family: '{para_fam}', Georgia, serif; text-align: {sub_al}; font-style: italic; font-weight: bold; color: #555555; margin-bottom: 16px;">
        {tr("preview.sample_subtitle")}
    </div>

    <div style="font-family: '{para_fam}', Georgia, serif; font-size: {anno_sz}; color: {anno_cl}; text-align: {anno_al}; font-style: {anno_style}; margin: 14px 28px;">
        <b>{tr("preview.sample_anno_lbl")}</b> {tr("preview.sample_anno_txt")}
    </div>

    <div style="font-family: '{para_fam}', Georgia, serif; font-size: {epi_sz}; color: {epi_cl}; text-align: {epi_al}; font-style: {epi_style}; margin-left: 32%; margin-top: 12px; margin-bottom: 4px;">
        {tr("preview.sample_epi_txt")}
    </div>
    <div style="font-family: '{para_fam}', Georgia, serif; font-size: {epi_sz}; color: {epi_cl}; text-align: {epi_al}; font-weight: bold; margin-left: 32%; margin-bottom: 18px;">
        {tr("preview.sample_epi_auth")}
    </div>

    <hr class="divider">

    <div style="font-family: '{para_fam}', Georgia, serif; font-size: {h2_sz}; color: {h2_cl}; text-align: {h2_al}; font-weight: bold; margin-top: 16px; margin-bottom: 10px;">
        {tr("preview.sample_h2")}
    </div>

    <p style="font-family: '{para_fam}', Georgia, serif; font-weight: normal; font-style: normal; text-indent: 0; text-align: {p_al}; margin: 6px 0;">
        <span style="font-family: '{drop_fam}', Georgia, serif; font-size: {drop_sz}; color: {drop_cl}; font-weight: bold; float: left; line-height: 0.85; margin-right: 6px;">{tr("preview.sample_drop_letter")}</span>{tr("preview.sample_p1")}
    </p>

    <p style="font-family: '{para_fam}', Georgia, serif; font-weight: normal; font-style: normal; text-indent: {indent_val}; text-align: {p_al}; margin: 6px 0;">
        {tr("preview.sample_p2", indent=indent_val)}
    </p>

    <div style="text-align: {img_al}; margin: 14px 0;">
        <div style="display: inline-block; width: {img_w}; max-width: 440px; border: 1px solid #d5cfc2; border-radius: 6px; padding: 10px 14px; background-color: #FAF7F0;">
            <svg width="180" height="36" viewBox="0 0 180 36" xmlns="http://www.w3.org/2000/svg" style="{"filter: grayscale(100%);" if grayscale else ""}">
                <line x1="10" y1="18" x2="68" y2="18" stroke="{h2_cl}" stroke-width="1.5"/>
                <polygon points="90,6 98,18 90,30 82,18" fill="{h1_cl}"/>
                <line x1="112" y1="18" x2="170" y2="18" stroke="{h2_cl}" stroke-width="1.5"/>
            </svg>
            <div style="font-family: '{para_fam}', Georgia, serif; font-size: {img_cap_sz}; color: {img_cap_cl}; font-style: {img_cap_st}; margin-top: 4px;">
                {tr("preview.sample_img_cap", w=img_w, svg_mode=svg_mode)}
            </div>
        </div>
    </div>

    <div style="font-family: '{para_fam}', Georgia, serif; text-align: {sub_al}; font-style: italic; font-weight: bold; color: #555555; margin: 12px 0;">
        {tr("preview.sample_scene_sub")}
    </div>

    <div style="font-family: '{para_fam}', Georgia, serif; font-size: {h3_sz}; color: {h3_cl}; text-align: {h3_al}; font-weight: bold; margin-top: 16px; margin-bottom: 8px;">
        {tr("preview.sample_h3")}
    </div>

    <p style="font-family: '{para_fam}', Georgia, serif; font-weight: normal; font-style: normal; text-indent: {indent_val}; text-align: {p_al}; margin: 6px 0;">
        {tr("preview.sample_p3")}
    </p>

    <div style="font-family: '{para_fam}', Georgia, serif; font-size: {poem_sz}; color: {poem_cl}; text-align: {poem_al}; font-style: {poem_style}; margin: 12px 2.5em;">
        {tr("preview.sample_poem")}
    </div>

    <div style="font-family: '{para_fam}', Georgia, serif; font-size: {h4_sz}; color: {h4_cl}; text-align: {h4_al}; font-weight: bold; margin-top: 16px; margin-bottom: 8px;">
        {tr("preview.sample_h4")}
    </div>

    <div style="font-family: '{para_fam}', Georgia, serif; font-size: {note_sz}; color: {note_cl}; background-color: {note_bg_css}; border: {note_border}; font-style: {note_style}; padding: 8px 12px; border-radius: 4px; margin: 10px 0;">
        <div style="font-weight: bold; margin-bottom: 4px;">{tr("preview.sample_note_hdr")}</div>
        {tr("preview.sample_note_txt", sz=note_sz, cl=note_cl, bg=note_bg, brd=note_border)}
    </div>

    <div style="font-family: '{para_fam}', Georgia, serif; font-size: {h5_sz}; color: {h5_cl}; text-align: {h5_al}; font-weight: bold; margin-top: 16px; margin-bottom: 8px;">
        {tr("preview.sample_h5")}
    </div>

    <table style="width: 100%; border-collapse: collapse; margin-top: 8px; margin-bottom: 14px; font-family: '{para_fam}', Georgia, serif; font-size: 90%; color: #222222;" border="1" bordercolor="#999999" cellpadding="5" cellspacing="0">
        <tr style="background-color: #EAE6DC; font-weight: bold;">
            <th align="left">{tr("preview.tbl_col_elem")}</th>
            <th align="left">{tr("preview.tbl_col_font")}</th>
            <th align="left">{tr("preview.tbl_col_style")}</th>
        </tr>
        <tr>
            <td>{tr("preview.tbl_row_author")}</td>
            <td>{author_disp}</td>
            <td>{auth_cl}, {auth_sz}, {auth_style}</td>
        </tr>
        <tr>
            <td>{tr("preview.tbl_row_title")}</td>
            <td>{title_disp}</td>
            <td>{h1_cl}, {h1_sz}</td>
        </tr>
        <tr>
            <td>{tr("preview.tbl_row_body")}</td>
            <td>{para_disp}</td>
            <td>{tr("preview.tbl_row_body_val", indent=indent_val, align=p_al_lbl)}</td>
        </tr>
        <tr>
            <td>{tr("preview.tbl_row_drop")}</td>
            <td>{drop_disp}</td>
            <td>{drop_cl}, {drop_sz}</td>
        </tr>
        <tr>
            <td>{tr("preview.tbl_row_img")}</td>
            <td>{svg_mode}</td>
            <td>{tr("preview.tbl_row_img_val", w=img_w, align=img_al_lbl)}</td>
        </tr>
    </table>

    <div style="text-align: center; font-size: 85%; font-style: italic; color: #888888; margin-top: 18px;">
        {tr("preview.sample_footer", app=app_name, ver=app_version)}
    </div>
</div>
</body>
</html>"""

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


def _is_italic_font_file(fname):
    stem = os.path.splitext(os.path.basename(fname or ""))[0].lower()
    return bool(re.search(r'(?:italic|oblique|boit|(?:^|[-_\d])it)$', stem))


def _is_bold_font_file(fname):
    stem = os.path.splitext(os.path.basename(fname or ""))[0].lower()
    return bool(re.search(r'(?:bold|black|semibold|demibold|(?:^|[-_\d])bo(?:it)?)$', stem))


def _find_sibling_font_variants(fonts_dir, base_file):
    """Ищет родственные начертания (Italic / Bold / BoldItalic) рядом с выбранным обычным шрифтом."""
    variants = {}
    if not base_file or not fonts_dir or not os.path.isdir(fonts_dir):
        return variants
    if _is_italic_font_file(base_file) or _is_bold_font_file(base_file):
        return variants

    stem, ext = os.path.splitext(base_file)
    candidates = {
        ("normal", "italic"): [],
        ("bold", "normal"): [],
        ("bold", "italic"): [],
    }
    if stem.endswith("_Regular"):
        prefix = stem[:-8]
        candidates[("normal", "italic")].extend([f"{prefix}_Italic{ext}", f"{prefix}-Italic{ext}"])
        candidates[("bold", "normal")].extend([f"{prefix}_Bold{ext}", f"{prefix}-Bold{ext}"])
        candidates[("bold", "italic")].extend([f"{prefix}_Bold-Italic{ext}", f"{prefix}_BoldItalic{ext}", f"{prefix}-BoldItalic{ext}"])
    elif stem.endswith("-Regular"):
        prefix = stem[:-8]
        candidates[("normal", "italic")].extend([f"{prefix}-Italic{ext}", f"{prefix}_Italic{ext}"])
        candidates[("bold", "normal")].extend([f"{prefix}-Bold{ext}", f"{prefix}_Bold{ext}"])
        candidates[("bold", "italic")].extend([f"{prefix}-BoldItalic{ext}", f"{prefix}-Bold-Italic{ext}", f"{prefix}_BoldItalic{ext}"])
    else:
        candidates[("normal", "italic")].extend([f"{stem}It{ext}", f"{stem}-Italic{ext}", f"{stem}_Italic{ext}"])
        candidates[("bold", "normal")].extend([f"{stem}Bo{ext}", f"{stem}-Bold{ext}", f"{stem}_Bold{ext}"])
        candidates[("bold", "italic")].extend([f"{stem}BoIt{ext}", f"{stem}-BoldItalic{ext}", f"{stem}_BoldItalic{ext}"])

    for key, names in candidates.items():
        for cand in names:
            if os.path.isfile(os.path.join(fonts_dir, cand)):
                variants[key] = cand
                break
    return variants


def _build_preview_font_faces(fonts_dir, para_file, title_file, author_file, drop_file):
    """
    Генерирует изолированные @font-face для превью (fbc-para, fbc-title, fbc-author, fbc-drop),
    чтобы файлы одного семейства (например Newton15.ttf / Newton15Bo.ttf / Newton15It.ttf)
    не перезаписывали друг друга в WebKit/браузере.
    """
    fonts_url_dir = fonts_dir.replace("\\", "/")
    none_vals = ("__none__", "Нет", "None", "")

    has_para = para_file not in none_vals
    has_title = title_file not in none_vals
    has_author = author_file not in none_vals
    has_drop = drop_file not in none_vals

    ff_lines = []

    def _add_face(fam, fname, weight="normal", style="normal"):
        ff_lines.append(
            f'@font-face {{ font-family: "{fam}"; src: url("file://{fonts_url_dir}/{fname}"); '
            f'font-weight: {weight}; font-style: {style}; }}'
        )

    if has_para:
        _add_face("fbc-para", para_file, "normal", "normal")
        for (wt, st_val), sib_file in _find_sibling_font_variants(fonts_dir, para_file).items():
            _add_face("fbc-para", sib_file, wt, st_val)

    if has_title:
        _add_face("fbc-title", title_file, "normal", "normal")
        if _is_bold_font_file(title_file):
            _add_face("fbc-title", title_file, "bold", "normal")
        else:
            sibs = _find_sibling_font_variants(fonts_dir, title_file)
            if ("bold", "normal") in sibs:
                _add_face("fbc-title", sibs[("bold", "normal")], "bold", "normal")

    if has_author:
        if _is_italic_font_file(author_file):
            _add_face("fbc-author", author_file, "normal", "italic")
            _add_face("fbc-author", author_file, "normal", "normal")
            if _is_bold_font_file(author_file):
                _add_face("fbc-author", author_file, "bold", "italic")
                _add_face("fbc-author", author_file, "bold", "normal")
            else:
                _add_face("fbc-author", author_file, "bold", "italic")
                _add_face("fbc-author", author_file, "bold", "normal")
        else:
            _add_face("fbc-author", author_file, "normal", "normal")
            if _is_bold_font_file(author_file):
                _add_face("fbc-author", author_file, "bold", "normal")
            else:
                sibs = _find_sibling_font_variants(fonts_dir, author_file)
                for (wt, st_val), sib_file in sibs.items():
                    _add_face("fbc-author", sib_file, wt, st_val)

    if has_drop:
        ff_lines.append(
            f'@font-face {{ font-family: "fbc-drop"; src: url("file://{fonts_url_dir}/{drop_file}"); }}'
        )

    para_stack = "'fbc-para', Georgia, serif" if has_para else "Georgia, serif"
    title_stack = (
        f"'fbc-title', {para_stack}" if has_title else para_stack
    )
    author_stack = (
        f"'fbc-author', {para_stack}" if has_author else para_stack
    )
    drop_stack = (
        f"'fbc-drop', {para_stack}" if has_drop else para_stack
    )

    return "\n        ".join(ff_lines), {
        "para": para_stack,
        "title": title_stack,
        "author": author_stack,
        "drop": drop_stack,
    }


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
    """Собирает HTML-страницу для встроенного превью (WKWebView / WebView2 / QWebEngineView / QTextEdit) или браузера."""
    import html as _html

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

    rich_html = bool(for_browser or use_web_engine)
    if rich_html:
        font_faces, stacks = _build_preview_font_faces(
            fonts_dir, para_file, title_file, author_file, drop_file
        )
        para_stack = stacks["para"]
        title_stack = stacks["title"]
        author_stack = stacks["author"]
        drop_stack = stacks["drop"]
    else:
        font_faces = ""
        para_stack = f"'{font_families.get('para', 'Georgia')}', Georgia, serif"
        title_stack = f"'{font_families.get('title', 'Georgia')}', Georgia, serif"
        author_stack = f"'{font_families.get('author', 'Georgia')}', Georgia, serif"
        drop_stack = f"'{font_families.get('drop', 'Georgia')}', Georgia, serif"

    def _disp_font(fname):
        return tr("styles.font_none") if fname in ("__none__", "Нет", "None", "") else fname

    para_disp = _disp_font(para_file)
    title_disp = _disp_font(title_file)
    author_disp = _disp_font(author_file)
    drop_disp = _disp_font(drop_file)

    note_bg_css = note_bg if note_bg != "transparent" else "#FDFBF7"
    pf_val = st.get("pdf_frame", "0")
    page_outline_css = f"outline: {pf_val} solid #EBE8E0;" if pf_val != "0" else ""
    gray_css = "filter: grayscale(100%);" if grayscale else ""

    def _render_cover_placeholder(author_text, title_text, series_text=""):
        a_esc = _html.escape(author_text or "")
        t_esc = _html.escape(title_text or "")
        s_esc = _html.escape(series_text or "")
        s_html = f'<div class="cover-ph-series">{s_esc}</div>' if s_esc else ""
        return (
            f'<div class="cover-placeholder" style="{gray_css}">'
            f'  <div class="cover-ph-inner">'
            f'    <div class="cover-ph-author" style="font-family: {author_stack}; font-style: {auth_style};">{a_esc}</div>'
            f'    <div class="cover-ph-ornament">&#10086;</div>'
            f'    <div class="cover-ph-title" style="font-family: {title_stack};">{t_esc}</div>'
            f'    {s_html}'
            f'  </div>'
            f'</div>'
        )

    is_book_mode = bool(book_preview and (book_preview.get("title") or book_preview.get("blocks")))

    if is_book_mode:
        running_title = book_preview.get("title") or ""
        if book_preview.get("series"):
            running_title = f'{book_preview["series"]} — {running_title}' if running_title else book_preview["series"]

        if book_preview.get("cover_data_uri"):
            cover_html = (
                f'<img class="book-cover-img" src="{book_preview["cover_data_uri"]}" '
                f'style="{gray_css}">'
            )
        else:
            cover_html = _render_cover_placeholder(
                book_preview.get("author", ""),
                book_preview.get("title", ""),
                book_preview.get("series", ""),
            )

        right_parts = []
        if book_preview.get("author"):
            right_parts.append(
                f'<div class="book-author" style="font-family: {author_stack}; font-size: {auth_sz}; color: {auth_cl}; '
                f'text-align: {auth_al}; font-style: {auth_style}; font-weight: bold; margin: 4px 0 6px 0;">'
                f'{_html.escape(book_preview["author"])}</div>'
            )
        if book_preview.get("title"):
            right_parts.append(
                f'<div class="book-title" style="font-family: {title_stack}; font-size: {h1_sz}; color: {h1_cl}; '
                f'text-align: {h1_al}; font-weight: bold; font-style: normal; margin: 4px 0 8px 0;">'
                f'{_html.escape(book_preview["title"])}</div>'
            )
        if book_preview.get("series"):
            right_parts.append(
                f'<div style="font-family: {para_stack}; text-align: {sub_al}; font-style: italic; font-weight: bold; '
                f'color: #555555; margin-bottom: 14px;">{_html.escape(book_preview["series"])}</div>'
            )
        if book_preview.get("annotation"):
            anno_html = "<br>".join(book_preview["annotation"])
            right_parts.append(
                f'<div style="font-family: {para_stack}; font-size: {anno_sz}; color: {anno_cl}; text-align: {anno_al}; '
                f'font-style: {anno_style}; font-weight: normal; margin: 14px 12px;">{anno_html}</div>'
            )
        if book_preview.get("epigraph_lines"):
            epi_html = "<br>".join(book_preview["epigraph_lines"])
            right_parts.append(
                f'<div style="font-family: {para_stack}; font-size: {epi_sz}; color: {epi_cl}; text-align: {epi_al}; '
                f'font-style: {epi_style}; margin-left: 22%; margin-top: 14px; margin-bottom: 4px;">{epi_html}</div>'
            )
            if book_preview.get("epigraph_author"):
                right_parts.append(
                    f'<div style="font-family: {para_stack}; font-size: {epi_sz}; color: {epi_cl}; text-align: {epi_al}; '
                    f'font-weight: bold; font-style: normal; margin-left: 22%; margin-bottom: 10px;">'
                    f'{book_preview["epigraph_author"]}</div>'
                )

        body_parts = []
        if book_preview.get("chapter_title"):
            body_parts.append(
                f'<div class="chapter-heading" style="font-family: {para_stack}; font-size: {h2_sz}; color: {h2_cl}; '
                f'text-align: {h2_al}; font-weight: bold; font-style: normal; margin: 0 0 12px 0;">'
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
                        body_parts.append(
                            f'<p class="has-dropcap" style="font-family: {para_stack}; font-weight: normal; font-style: normal; '
                            f'text-indent: 0; text-align: {p_al}; margin: 0;">'
                            f'{lead_punct}<span class="dropcap" style="font-family: {drop_stack}; font-size: {drop_sz}; '
                            f'color: {drop_cl}; font-weight: bold; font-style: normal; float: left; line-height: 0.82; '
                            f'margin: 2px 6px 0 0;">{first_ch}</span>{rest}</p>'
                        )
                        continue
                body_parts.append(
                    f'<p style="font-family: {para_stack}; font-weight: normal; font-style: normal; '
                    f'text-indent: {indent_val}; text-align: {p_al}; margin: 0;">{bcontent}</p>'
                )
            elif btype == "subtitle":
                body_parts.append(
                    f'<div style="font-family: {para_stack}; text-align: {sub_al}; font-style: italic; font-weight: bold; '
                    f'color: #555555; margin: 10px 0; break-after: avoid;">{bcontent}</div>'
                )
            elif btype == "empty":
                body_parts.append('<div style="height: 0.8em;"></div>')
            elif btype == "poem":
                body_parts.append(
                    f'<div style="font-family: {para_stack}; font-size: {poem_sz}; color: {poem_cl}; text-align: {poem_al}; '
                    f'font-style: {poem_style}; margin: 10px 1.8em; break-inside: avoid;">{bcontent}</div>'
                )
            elif btype == "cite":
                body_parts.append(
                    f'<div style="font-family: {para_stack}; font-size: {epi_sz}; color: {epi_cl}; font-style: italic; '
                    f'margin: 10px 1.2em; padding-left: 10px; border-left: 2px solid #cbd5e1; break-inside: avoid;">{bcontent}</div>'
                )

        if book_preview.get("footnote_paras"):
            fn_hdr = f'<div style="font-weight: bold; margin-bottom: 4px;">[{book_preview["footnote_title"]}]</div>' if book_preview.get("footnote_title") else ""
            fn_body = "<br>".join(book_preview["footnote_paras"])
            body_parts.append(
                f'<div style="font-family: {para_stack}; font-size: {note_sz}; color: {note_cl}; '
                f'background-color: {note_bg_css}; border: {note_border}; font-style: {note_style}; '
                f'padding: 8px 12px; border-radius: 4px; margin: 12px 0; break-inside: avoid;">'
                f'{fn_hdr}{fn_body}</div>'
            )

        # Заполняем правую страницу первого разворота (стр. 2) началом главы, чтобы она была заполнена полностью наравне с обложкой
        def _plain_len(html_chunk):
            return len(re.sub(r'<[^>]+>', '', html_chunk or '').strip())

        front_chars = sum(_plain_len(p) for p in right_parts)
        target_right_chars = 1650
        if body_parts:
            right_parts.append('<hr class="divider">')
            taken = 0
            acc_chars = front_chars
            min_take = 4 if front_chars < 900 else 3
            while taken < len(body_parts):
                chunk = body_parts[taken]
                chunk_len = _plain_len(chunk)
                if taken == 0 and 'class="chapter-heading"' in chunk:
                    right_parts.append(chunk)
                    acc_chars += chunk_len + 120
                    taken += 1
                    continue
                if taken >= min_take and acc_chars + chunk_len > target_right_chars:
                    break
                right_parts.append(chunk)
                acc_chars += max(chunk_len, 80)
                taken += 1
                if acc_chars >= target_right_chars and taken >= min_take:
                    break
            body_parts = body_parts[taken:]

        extra_table_html = ""
    else:
        running_title = tr("preview.sample_title")
        cover_html = _render_cover_placeholder(
            tr("preview.sample_author"),
            tr("preview.sample_title"),
        )
        right_parts = [
            f'<div class="book-author" style="font-family: {author_stack}; font-size: {auth_sz}; color: {auth_cl}; '
            f'text-align: {auth_al}; font-style: {auth_style}; font-weight: bold; margin: 4px 0 6px 0;">'
            f'{tr("preview.sample_author")}</div>',
            f'<div class="book-title" style="font-family: {title_stack}; font-size: {h1_sz}; color: {h1_cl}; '
            f'text-align: {h1_al}; font-weight: bold; font-style: normal; margin: 4px 0 10px 0;">'
            f'{tr("preview.sample_title")}</div>',
            f'<div style="font-family: {para_stack}; text-align: {sub_al}; font-style: italic; font-weight: bold; '
            f'color: #555555; margin-bottom: 14px;">{tr("preview.sample_subtitle")}</div>',
            f'<div style="font-family: {para_stack}; font-size: {anno_sz}; color: {anno_cl}; text-align: {anno_al}; '
            f'font-style: {anno_style}; font-weight: normal; margin: 14px 12px;">'
            f'<b>{tr("preview.sample_anno_lbl")}</b> {tr("preview.sample_anno_txt")}</div>',
            f'<div style="font-family: {para_stack}; font-size: {epi_sz}; color: {epi_cl}; text-align: {epi_al}; '
            f'font-style: {epi_style}; margin-left: 22%; margin-top: 14px; margin-bottom: 4px;">'
            f'{tr("preview.sample_epi_txt")}</div>',
            f'<div style="font-family: {para_stack}; font-size: {epi_sz}; color: {epi_cl}; text-align: {epi_al}; '
            f'font-weight: bold; font-style: normal; margin-left: 22%; margin-bottom: 10px;">'
            f'{tr("preview.sample_epi_auth")}</div>',
            '<hr class="divider">',
            f'<div class="chapter-heading" style="font-family: {para_stack}; font-size: {h2_sz}; color: {h2_cl}; '
            f'text-align: {h2_al}; font-weight: bold; font-style: normal; margin: 0 0 10px 0;">'
            f'{tr("preview.sample_h2")}</div>',
            f'<p class="has-dropcap" style="font-family: {para_stack}; font-weight: normal; font-style: normal; '
            f'text-indent: 0; text-align: {p_al}; margin: 0;">'
            f'<span class="dropcap" style="font-family: {drop_stack}; font-size: {drop_sz}; color: {drop_cl}; '
            f'font-weight: bold; font-style: normal; float: left; line-height: 0.82; margin: 2px 6px 0 0;">'
            f'{tr("preview.sample_drop_letter")}</span>{tr("preview.sample_p1")}</p>',
            f'<p style="font-family: {para_stack}; font-weight: normal; font-style: normal; '
            f'text-indent: {indent_val}; text-align: {p_al}; margin: 0;">'
            f'{tr("preview.sample_p2", indent=indent_val)}</p>',
        ]
        body_parts = [
            f'<div style="text-align: {img_al}; margin: 12px 0; break-inside: avoid;">'
            f'  <div style="display: inline-block; width: {img_w}; max-width: 100%; box-sizing: border-box; border: 1px solid #d5cfc2; '
            f'border-radius: 6px; padding: 8px 10px; background-color: #FAF7F0;">'
            f'    <svg width="160" height="32" viewBox="0 0 180 36" xmlns="http://www.w3.org/2000/svg" style="{gray_css}">'
            f'      <line x1="10" y1="18" x2="68" y2="18" stroke="{h2_cl}" stroke-width="1.5"/>'
            f'      <polygon points="90,6 98,18 90,30 82,18" fill="{h1_cl}"/>'
            f'      <line x1="112" y1="18" x2="170" y2="18" stroke="{h2_cl}" stroke-width="1.5"/>'
            f'    </svg>'
            f'    <div style="font-family: {para_stack}; font-size: {img_cap_sz}; color: {img_cap_cl}; '
            f'font-style: {img_cap_st}; margin-top: 4px;">'
            f'{tr("preview.sample_img_cap", w=img_w, svg_mode=svg_mode)}</div>'
            f'  </div>'
            f'</div>',
            f'<div style="font-family: {para_stack}; text-align: {sub_al}; font-style: italic; font-weight: bold; '
            f'color: #555555; margin: 10px 0; break-after: avoid;">{tr("preview.sample_scene_sub")}</div>',
            f'<div style="font-family: {para_stack}; font-size: {h3_sz}; color: {h3_cl}; text-align: {h3_al}; '
            f'font-weight: bold; font-style: normal; margin: 12px 0 6px 0; break-after: avoid;">{tr("preview.sample_h3")}</div>',
            f'<p style="font-family: {para_stack}; font-weight: normal; font-style: normal; '
            f'text-indent: {indent_val}; text-align: {p_al}; margin: 0;">{tr("preview.sample_p3")}</p>',
            f'<div style="font-family: {para_stack}; font-size: {poem_sz}; color: {poem_cl}; text-align: {poem_al}; '
            f'font-style: {poem_style}; margin: 10px 1.8em; break-inside: avoid;">{tr("preview.sample_poem")}</div>',
            f'<div style="font-family: {para_stack}; font-size: {h4_sz}; color: {h4_cl}; text-align: {h4_al}; '
            f'font-weight: bold; font-style: normal; margin: 12px 0 6px 0; break-after: avoid;">{tr("preview.sample_h4")}</div>',
            f'<div style="font-family: {para_stack}; font-size: {note_sz}; color: {note_cl}; '
            f'background-color: {note_bg_css}; border: {note_border}; font-style: {note_style}; '
            f'padding: 8px 12px; border-radius: 4px; margin: 10px 0; break-inside: avoid;">'
            f'<div style="font-weight: bold; margin-bottom: 4px;">{tr("preview.sample_note_hdr")}</div>'
            f'{tr("preview.sample_note_txt", sz=note_sz, cl=note_cl, bg=note_bg, brd=note_border)}</div>',
            f'<div style="font-family: {para_stack}; font-size: {h5_sz}; color: {h5_cl}; text-align: {h5_al}; '
            f'font-weight: bold; font-style: normal; margin: 12px 0 6px 0; break-after: avoid;">{tr("preview.sample_h5")}</div>',
        ]
        extra_table_html = f"""
    <div class="book-meta-card">
        <table style="width: 100%; border-collapse: collapse; font-family: {para_stack}; font-size: 90%; color: #222222;" border="1" bordercolor="#ccc5b8" cellpadding="6" cellspacing="0">
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
    </div>"""

    right_inner = "\n            ".join(right_parts)
    body_inner = "\n            ".join(body_parts)
    running_header_esc = _html.escape(running_title)
    footer_note = tr("preview.sample_footer", app=app_name, ver=app_version)

    # Для резервного QTextEdit (rich_html=False) отдаём двухколоночные развороты на таблицах HTML
    if not rich_html:
        fallback_spread2 = ""
        if body_parts:
            weights = [max(len(re.sub(r'<[^>]+>', '', p)), 60) for p in body_parts]
            half = sum(weights) / 2.0
            acc = 0
            split_idx = max(1, len(body_parts) // 2)
            for idx_p, w_p in enumerate(weights):
                acc += w_p
                if acc >= half:
                    split_idx = idx_p + 1
                    break
            left_col_html = "\n".join(body_parts[:split_idx])
            right_col_html = "\n".join(body_parts[split_idx:])
            fallback_spread2 = f"""
<hr class="divider">
<div style="text-align: center; font-size: 85%; color: #8A857C; margin-bottom: 10px;">{running_header_esc}</div>
<table width="100%" cellpadding="14" cellspacing="0">
    <tr>
        <td width="50%" valign="top" style="border-right: 1px solid #E5DFD3; padding-right: 22px;">{left_col_html}</td>
        <td width="50%" valign="top" style="padding-left: 22px;">{right_col_html}</td>
    </tr>
    <tr>
        <td align="center" style="font-size: 85%; color: #8A857C; padding-top: 8px;">3</td>
        <td align="center" style="font-size: 85%; color: #8A857C; padding-top: 8px;">4</td>
    </tr>
</table>"""

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{tr("preview.html_title", app=app_name)}</title>
<style>
    body {{
        background-color: #FDFBF7;
        color: #222222;
        font-family: {para_stack};
        font-style: normal;
        font-weight: normal;
        margin: 0;
        padding: 12px;
        line-height: 1.48;
    }}
    p {{
        margin: 0;
        font-style: normal;
        font-weight: normal;
    }}
    .divider {{ border: none; border-top: 1px dashed #d5cfc2; margin: 14px 0; }}
</style>
</head>
<body>
<table width="100%" cellpadding="14" cellspacing="0">
    <tr>
        <td width="46%" align="center" valign="middle" style="border-right: 1px solid #E5DFD3; padding: 0;">{cover_html}</td>
        <td width="54%" valign="top" style="padding-left: 22px;">
            <div style="text-align: center; font-size: 85%; color: #8A857C; margin-bottom: 10px;">{running_header_esc}</div>
            {right_inner}
        </td>
    </tr>
    <tr>
        <td align="center" style="font-size: 85%; color: #8A857C;"></td>
        <td align="center" style="font-size: 85%; color: #8A857C;">2</td>
    </tr>
</table>
{fallback_spread2}
{extra_table_html}
<div style="text-align: center; font-size: 85%; font-style: italic; color: #888888; margin-top: 18px;">{footer_note}</div>
</body>
</html>"""

    text_spread_html = ""
    if body_parts:
        text_spread_html = f"""
    <section class="book-spread text-spread">
        <div class="spread-header">{running_header_esc}</div>
        <div class="book-columns">
            {body_inner}
        </div>
        <div class="spread-footer">
            <span class="page-num">3</span>
            <span class="page-num">4</span>
        </div>
    </section>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{tr("preview.html_title", app=app_name)}</title>
<style>
    {font_faces}
    * {{
        box-sizing: border-box;
    }}
    body {{
        background-color: #E5E1D8;
        color: #1E1E1E;
        font-family: {para_stack};
        font-weight: normal;
        font-style: normal;
        font-size: 15px;
        margin: 0;
        padding: 24px 20px 32px 20px;
        line-height: 1.48;
    }}
    .book-container {{
        max-width: 1120px;
        margin: 0 auto;
        display: flex;
        flex-direction: column;
        gap: 28px;
    }}
    .book-spread {{
        position: relative;
        background-color: #FDFBF7;
        border-radius: 6px;
        box-shadow: 0 8px 28px rgba(0, 0, 0, 0.14), 0 1px 4px rgba(0, 0, 0, 0.08);
        {page_outline_css}
        overflow: hidden;
    }}
    .title-spread {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        min-height: 600px;
    }}
    .book-page {{
        position: relative;
        display: flex;
        flex-direction: column;
        min-width: 0;
    }}
    .cover-page {{
        align-items: stretch;
        justify-content: stretch;
        padding: 0;
        background: #FDFBF7;
        border-right: 1px solid #E5DFD3;
        overflow: hidden;
    }}
    .cover-page::after {{
        content: "";
        position: absolute;
        top: 0;
        right: 0;
        bottom: 0;
        width: 22px;
        background: linear-gradient(to right, rgba(0, 0, 0, 0) 0%, rgba(0, 0, 0, 0.14) 100%);
        pointer-events: none;
    }}
    .book-cover-img {{
        display: block;
        width: 100%;
        height: 100%;
        min-height: 600px;
        object-fit: cover;
        object-position: center;
        border-radius: 0;
        box-shadow: none;
    }}
    .cover-placeholder {{
        width: 100%;
        height: 100%;
        min-height: 600px;
        background: linear-gradient(155deg, #FBF8F1 0%, #EFE8D8 100%);
        border: none;
        border-radius: 0;
        padding: 28px;
        box-shadow: none;
        display: flex;
        align-items: stretch;
        justify-content: center;
    }}
    .cover-ph-inner {{
        flex: 1;
        border: 2px double #B8AA92;
        padding: 28px 20px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
        gap: 14px;
    }}
    .cover-ph-author {{
        font-size: 16px;
        color: #4A4338;
        letter-spacing: 0.03em;
    }}
    .cover-ph-ornament {{
        font-size: 20px;
        color: #9C8B70;
    }}
    .cover-ph-title {{
        font-size: 24px;
        font-weight: bold;
        color: #2B241B;
        line-height: 1.25;
    }}
    .cover-ph-series {{
        font-size: 13px;
        color: #6B6254;
        font-style: italic;
        margin-top: 6px;
    }}
    .title-page {{
        justify-content: space-between;
        padding: 22px 44px 18px 46px;
        background: linear-gradient(to left, #FDFBF7 94%, #F6F2EA 100%);
        box-shadow: inset 18px 0 24px -18px rgba(0, 0, 0, 0.14);
    }}
    .running-header, .spread-header {{
        text-align: center;
        font-size: 12px;
        font-style: normal;
        font-weight: normal;
        color: #8A857C;
        letter-spacing: 0.01em;
        min-height: 18px;
    }}
    .title-page-body {{
        margin: auto 0;
        padding: 14px 0;
    }}
    .page-num {{
        display: block;
        text-align: center;
        font-size: 12px;
        font-style: normal;
        font-weight: normal;
        color: #8A857C;
    }}
    .text-spread {{
        padding: 22px 44px 18px 44px;
    }}
    .text-spread::before {{
        content: "";
        position: absolute;
        top: 0;
        bottom: 0;
        left: 50%;
        width: 36px;
        transform: translateX(-50%);
        background: linear-gradient(
            to right,
            rgba(0, 0, 0, 0) 0%,
            rgba(0, 0, 0, 0.055) 48%,
            rgba(0, 0, 0, 0.09) 50%,
            rgba(0, 0, 0, 0.045) 52%,
            rgba(0, 0, 0, 0) 100%
        );
        pointer-events: none;
    }}
    .spread-header {{
        margin-bottom: 16px;
    }}
    .book-columns {{
        column-count: 2;
        column-gap: 72px;
        column-fill: balance;
        min-height: 520px;
        hyphens: auto;
        -webkit-hyphens: auto;
    }}
    .book-columns p {{
        font-style: normal;
        font-weight: normal;
        line-height: 1.45;
        margin: 0;
        orphans: 2;
        widows: 2;
    }}
    .chapter-heading {{
        break-after: avoid;
        -webkit-column-break-after: avoid;
    }}
    .spread-footer {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 72px;
        margin-top: 18px;
    }}
    .divider {{
        border: none;
        border-top: 1px dashed #d5cfc2;
        margin: 14px 0;
    }}
    .book-meta-card {{
        background-color: #FDFBF7;
        border-radius: 6px;
        padding: 18px 24px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.10);
    }}
    .preview-footer {{
        text-align: center;
        font-size: 12px;
        font-style: italic;
        color: #777268;
        margin-top: 2px;
    }}
    @media (max-width: 760px) {{
        .title-spread {{
            grid-template-columns: 1fr;
        }}
        .cover-page {{
            border-right: none;
            border-bottom: 1px solid #E5DFD3;
            box-shadow: none;
        }}
        .cover-page::after {{
            display: none;
        }}
        .book-cover-img {{
            min-height: 0;
            max-height: 75vh;
        }}
        .title-page {{
            box-shadow: none;
        }}
        .text-spread::before {{
            display: none;
        }}
        .book-columns {{
            column-count: 1;
        }}
        .spread-footer {{
            grid-template-columns: 1fr;
        }}
    }}
</style>
</head>
<body>
<div class="book-container">
    <section class="book-spread title-spread">
        <div class="book-page cover-page">
            {cover_html}
        </div>
        <div class="book-page title-page">
            <div class="running-header">{running_header_esc}</div>
            <div class="title-page-body">
                {right_inner}
            </div>
            <div class="page-num">1</div>
        </div>
    </section>
    {text_spread_html}
    {extra_table_html}
    <div class="preview-footer">{footer_note}</div>
</div>
</body>
</html>"""

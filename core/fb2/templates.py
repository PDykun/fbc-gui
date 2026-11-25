import re

from core.fb2.common import (
    DEFAULT_OUTPUT_FORMAT,
    FILENAME_TAG_IDS,
    FORMAT_EXT_MAP,
)

_MULTI_SPACE_RE = re.compile(r' {2,}')


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
                    sep = _MULTI_SPACE_RE.sub(' ', pending_sep) if skipped_empty else pending_sep
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


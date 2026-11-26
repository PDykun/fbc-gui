"""Cover Studio — local typographic e-book cover generator for FBC GUI.

Renders high-resolution (2x supersampled) typographic covers using Pillow and
fonts from the application ``fonts/`` directory, with deterministic per-series
color palettes, 5 built-in templates, smart Cyrillic/Latin text wrapping, and
integration with ``core/image_optimizer.py`` E Ink display profiles.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from core.logger import get_logger

logger = get_logger("cover_studio")

__all__ = [
    "CoverMetadata",
    "CoverPalette",
    "CoverSpec",
    "PALETTES",
    "SERIES_COLOR_POOL",
    "TEMPLATES",
    "apply_eink_profile",
    "discover_available_fonts",
    "fit_text_block",
    "render_cover_bytes",
    "render_cover_image",
    "render_template_thumbnail",
    "resolve_font_path",
    "resolve_palette",
    "wrap_text",
]

# Internal render canvas (2x supersampling for crisp borders and typography)
_CANVAS_W = 1200
_CANVAS_H = 1800

_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")

# Short prepositions/conjunctions that should stay attached to the next word
_NO_ORPHAN_WORDS = frozenset({
    "а", "в", "и", "к", "о", "с", "у", "я", "во", "до", "за", "из", "ко",
    "на", "не", "ни", "но", "об", "от", "по", "со", "то",
    "a", "an", "at", "by", "in", "of", "on", "or", "to", "the",
})

# Map short aliases to core.image_optimizer profile IDs
_EINK_PROFILE_ALIASES = {
    "": "none",
    "none": "none",
    "color": "none",
    "carta": "eink_bw",
    "eink_bw": "eink_bw",
    "bw16": "eink_bw_16_dither",
    "eink_bw_16_dither": "eink_bw_16_dither",
    "kaleido3": "eink_kaleido3",
    "eink_kaleido3": "eink_kaleido3",
    "gallery3": "eink_gallery3",
    "eink_gallery3": "eink_gallery3",
}


@dataclass(frozen=True)
class CoverPalette:
    """Color tokens for a Cover Studio palette."""

    id: str
    name_ru: str
    name_en: str
    bg: str
    fg: str
    accent: str
    badge_bg: str
    badge_fg: str


PALETTES: dict[str, CoverPalette] = {
    "eink_paper": CoverPalette(
        id="eink_paper",
        name_ru="Бумага E Ink",
        name_en="E Ink Paper",
        bg="#F8F6F1",
        fg="#141414",
        accent="#3B3B3B",
        badge_bg="#E6E2D8",
        badge_fg="#141414",
    ),
    "graphite": CoverPalette(
        id="graphite",
        name_ru="Графит",
        name_en="Graphite",
        bg="#1E2229",
        fg="#F3F4F6",
        accent="#60A5FA",
        badge_bg="#2C3340",
        badge_fg="#93C5FD",
    ),
    "emerald": CoverPalette(
        id="emerald",
        name_ru="Изумруд",
        name_en="Emerald",
        bg="#12352C",
        fg="#F5F0E6",
        accent="#C9A227",
        badge_bg="#1D4D40",
        badge_fg="#F3D677",
    ),
    "burgundy": CoverPalette(
        id="burgundy",
        name_ru="Бордо",
        name_en="Burgundy",
        bg="#4A1822",
        fg="#FAF3E8",
        accent="#D4AF37",
        badge_bg="#662331",
        badge_fg="#F5DA81",
    ),
    "indigo": CoverPalette(
        id="indigo",
        name_ru="Индиго",
        name_en="Indigo",
        bg="#1C2B4B",
        fg="#F4F7FC",
        accent="#7AA2F7",
        badge_bg="#293D66",
        badge_fg="#B4CBFA",
    ),
    "parchment": CoverPalette(
        id="parchment",
        name_ru="Пергамент",
        name_en="Parchment",
        bg="#EFE6D5",
        fg="#2C2218",
        accent="#8C3B2B",
        badge_bg="#E0D2BA",
        badge_fg="#6E2B1E",
    ),
    # Extended series-pool palettes for greater visual variety across cycles
    "slate_teal": CoverPalette(
        id="slate_teal",
        name_ru="Морской сланец",
        name_en="Slate Teal",
        bg="#1B3A42",
        fg="#F2F7F8",
        accent="#76C7C0",
        badge_bg="#27505A",
        badge_fg="#B5E5E0",
    ),
    "ochre_brown": CoverPalette(
        id="ochre_brown",
        name_ru="Охра",
        name_en="Ochre Brown",
        bg="#3D2B1F",
        fg="#FAF3E6",
        accent="#E0A458",
        badge_bg="#543C2C",
        badge_fg="#F3CB92",
    ),
    "plum": CoverPalette(
        id="plum",
        name_ru="Слива",
        name_en="Plum",
        bg="#3A1F3B",
        fg="#F8F1FA",
        accent="#D89CE0",
        badge_bg="#512D52",
        badge_fg="#ECC6F2",
    ),
}

SERIES_COLOR_POOL: tuple[str, ...] = (
    "graphite",
    "emerald",
    "burgundy",
    "indigo",
    "parchment",
    "slate_teal",
    "ochre_brown",
    "plum",
)

TEMPLATES: dict[str, dict[str, str]] = {
    "classic_serif": {
        "name_ru": "Классический переплёт",
        "name_en": "Classic Binding",
    },
    "eink_minimal": {
        "name_ru": "Минимализм E Ink",
        "name_en": "E Ink Minimal",
    },
    "series_edition": {
        "name_ru": "Серийное издание",
        "name_en": "Series Edition",
    },
    "modern_band": {
        "name_ru": "Современный постер",
        "name_en": "Modern Poster",
    },
    "chronicle": {
        "name_ru": "Летопись",
        "name_en": "Chronicle",
    },
}


@dataclass(frozen=True)
class CoverMetadata:
    """Book metadata rendered onto a generated cover."""

    title: str
    author: str = ""
    series: str = ""
    series_number: str = ""
    genre: str = ""
    subtitle: str = ""

    @classmethod
    def from_book_data(cls, book: Any, *, lang: str = "ru") -> "CoverMetadata":
        """Build CoverMetadata from an FBC GUI queue entry ``data``, ``meta`` dict, or object."""
        if isinstance(book, Mapping) and isinstance(book.get("meta"), Mapping):
            src: Any = book["meta"]
        else:
            src = book

        if isinstance(src, Mapping):
            getter = src.get
        else:
            getter = lambda key, default="": getattr(src, key, default)

        title = str(getter("title", "") or "").strip() or "Без названия"
        author = str(getter("author", "") or "").strip()
        if not author:
            first = str(getter("first", getter("author_first", "")) or "").strip()
            mid = str(getter("mid", getter("author_middle", "")) or "").strip()
            last = str(getter("last", getter("author_last", "")) or "").strip()
            author = " ".join(p for p in (first, mid, last) if p)

        series = str(getter("series", "") or "").strip()
        raw_num = getter("num", getter("series_number", getter("sequence_number", "")))
        series_number = "" if raw_num is None else str(raw_num).strip()

        raw_genre = getter("genre", getter("genres", ""))
        if isinstance(raw_genre, (list, tuple)):
            genre_code = str(raw_genre[0]).strip() if raw_genre else ""
        else:
            genre_code = str(raw_genre or "").strip()

        genre = genre_code
        if genre_code:
            try:
                from core.fb2_genres import format_genre_label  # type: ignore

                label = format_genre_label(genre_code, lang=lang)
                if label:
                    genre = label
            except Exception as e:
                logger.debug("Не удалось отформатировать жанр %r в Cover Studio: %s", genre_code, e)

        subtitle = str(getter("subtitle", "") or "").strip()
        return cls(
            title=title,
            author=author,
            series=series,
            series_number=series_number,
            genre=genre,
            subtitle=subtitle,
        )


@dataclass(frozen=True)
class CoverSpec:
    """Serializable configuration for Cover Studio rendering."""

    template_id: str = "eink_minimal"
    palette_id: str = "auto_series"
    custom_bg: str = ""
    custom_fg: str = ""
    custom_accent: str = ""
    title_font: str = "PT Astra Serif"
    meta_font: str = "PT Astra Serif"
    show_author: bool = True
    show_series: bool = True
    show_series_number: bool = True
    show_genre_badge: bool = False
    custom_subtitle: str = ""
    eink_profile: str = "none"  # none | eink_bw | eink_bw_16_dither | eink_kaleido3 | eink_gallery3
    output_size: tuple[int, int] = (600, 900)
    output_format: str = "JPEG"  # JPEG | PNG
    jpeg_quality: int = 90

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict for presets and settings."""
        data = asdict(self)
        data["output_size"] = list(self.output_size)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "CoverSpec":
        """Deserialize safely with defaults for unknown or missing fields."""
        if not isinstance(data, Mapping):
            return cls()
        defaults = cls()
        raw_size = data.get("output_size", defaults.output_size)
        if (
            isinstance(raw_size, (list, tuple))
            and len(raw_size) == 2
            and all(isinstance(v, (int, float)) and v >= 64 for v in raw_size)
        ):
            size = (int(raw_size[0]), int(raw_size[1]))
        else:
            size = defaults.output_size

        tpl = str(data.get("template_id", defaults.template_id))
        if tpl not in TEMPLATES:
            tpl = defaults.template_id

        fmt = str(data.get("output_format", defaults.output_format)).upper()
        if fmt not in ("JPEG", "PNG"):
            fmt = defaults.output_format

        quality = data.get("jpeg_quality", defaults.jpeg_quality)
        try:
            quality = max(50, min(100, int(quality)))
        except (TypeError, ValueError):
            quality = defaults.jpeg_quality

        raw_profile = str(data.get("eink_profile", defaults.eink_profile) or "none").strip().lower()
        profile = _EINK_PROFILE_ALIASES.get(raw_profile, raw_profile)

        return cls(
            template_id=tpl,
            palette_id=str(data.get("palette_id", defaults.palette_id)),
            custom_bg=str(data.get("custom_bg", "") or ""),
            custom_fg=str(data.get("custom_fg", "") or ""),
            custom_accent=str(data.get("custom_accent", "") or ""),
            title_font=str(data.get("title_font", defaults.title_font) or defaults.title_font),
            meta_font=str(data.get("meta_font", defaults.meta_font) or defaults.meta_font),
            show_author=bool(data.get("show_author", defaults.show_author)),
            show_series=bool(data.get("show_series", defaults.show_series)),
            show_series_number=bool(data.get("show_series_number", defaults.show_series_number)),
            show_genre_badge=bool(data.get("show_genre_badge", defaults.show_genre_badge)),
            custom_subtitle=str(data.get("custom_subtitle", "") or ""),
            eink_profile=profile,
            output_size=size,
            output_format=fmt,
            jpeg_quality=quality,
        )


def _normalize_hex(value: str) -> str:
    """Validate and normalize a 6-digit hex color string, or return ''."""
    cleaned = (value or "").strip()
    if not _HEX_RE.match(cleaned):
        return ""
    return "#" + cleaned.lstrip("#").upper()


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, rgb[0])),
        max(0, min(255, rgb[1])),
        max(0, min(255, rgb[2])),
    )


def _blend_hex(c1: str, c2: str, ratio: float) -> str:
    """Blend two hex colors: ratio=0 -> c1, ratio=1 -> c2."""
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex((
        round(r1 + (r2 - r1) * ratio),
        round(g1 + (g2 - g1) * ratio),
        round(b1 + (b2 - b1) * ratio),
    ))


def _auto_contrast_fg(bg_hex: str) -> str:
    """Pick dark or light foreground with strong contrast against bg_hex."""
    r, g, b = _hex_to_rgb(bg_hex)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    return "#141414" if luminance > 0.52 else "#F5F5F5"


def resolve_palette(spec: CoverSpec, series: str = "") -> CoverPalette:
    """Resolve effective CoverPalette, handling auto_series and custom hex overrides."""
    if spec.palette_id == "auto_series":
        norm_series = re.sub(r"\s+", " ", (series or "").strip().lower())
        if norm_series:
            digest = hashlib.sha256(norm_series.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % len(SERIES_COLOR_POOL)
            base = PALETTES[SERIES_COLOR_POOL[idx]]
        else:
            base = PALETTES["eink_paper"]
    else:
        base = PALETTES.get(spec.palette_id, PALETTES["eink_paper"])

    c_bg = _normalize_hex(spec.custom_bg)
    c_fg = _normalize_hex(spec.custom_fg)
    c_acc = _normalize_hex(spec.custom_accent)

    if not (c_bg or c_fg or c_acc):
        return base

    bg = c_bg or base.bg
    fg = c_fg or (_auto_contrast_fg(bg) if c_bg else base.fg)
    accent = c_acc or base.accent
    badge_bg = _blend_hex(bg, accent, 0.22)
    badge_fg = _auto_contrast_fg(badge_bg)
    return CoverPalette(
        id=f"{base.id}_custom",
        name_ru=base.name_ru,
        name_en=base.name_en,
        bg=bg,
        fg=fg,
        accent=accent,
        badge_bg=badge_bg,
        badge_fg=badge_fg,
    )


def _default_fonts_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "fonts"


def discover_available_fonts(fonts_dir: Path | str | None = None) -> list[str]:
    """Return deduplicated human-readable font family names discovered in ``fonts/``."""
    directory = Path(fonts_dir) if fonts_dir is not None else _default_fonts_dir()
    families: list[str] = []
    seen: set[str] = set()

    if directory.is_dir():
        for p in sorted(directory.iterdir()):
            if not p.is_file() or p.suffix.lower() not in (".ttf", ".otf"):
                continue
            # Skip Church Slavonic decorative fonts that lack modern Russian Cyrillic glyphs
            if "pomorsky" in p.stem.lower():
                continue
            stem = re.sub(
                r"[-_ ]?(regular|bold|italic|bolditalic|medium|semibold|light)$",
                "",
                p.stem,
                flags=re.IGNORECASE,
            )
            label = re.sub(r"[-_]+", " ", stem).strip() or p.stem
            key = label.lower()
            if key not in seen:
                seen.add(key)
                families.append(label)

    if not families:
        families = ["PT Astra Serif"]
    return families


def _system_font_candidates(bold: bool = False, serif: bool = True) -> list[Path]:
    """Return common cross-platform system font paths supporting Cyrillic & Latin."""
    if serif:
        names = (
            [
                "DejaVuSerif-Bold.ttf",
                "NotoSerif-Bold.ttf",
                "LiberationSerif-Bold.ttf",
                "Georgia Bold.ttf",
                "georgiab.ttf",
                "Times New Roman Bold.ttf",
            ]
            if bold
            else [
                "DejaVuSerif.ttf",
                "NotoSerif-Regular.ttf",
                "LiberationSerif-Regular.ttf",
                "Georgia.ttf",
                "georgia.ttf",
                "Times New Roman.ttf",
            ]
        )
    else:
        names = (
            [
                "DejaVuSans-Bold.ttf",
                "NotoSans-Bold.ttf",
                "LiberationSans-Bold.ttf",
                "Arial Bold.ttf",
                "arialbd.ttf",
            ]
            if bold
            else [
                "DejaVuSans.ttf",
                "NotoSans-Regular.ttf",
                "LiberationSans-Regular.ttf",
                "Arial.ttf",
                "arial.ttf",
            ]
        )

    search_roots = [
        Path("/usr/share/fonts"),
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
        Path("C:/Windows/Fonts"),
    ]
    found: list[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        for name in names:
            direct = root / name
            if direct.is_file():
                found.append(direct)
        if not found and root == Path("/usr/share/fonts"):
            for name in names:
                for match in root.rglob(name):
                    found.append(match)
                    break
                if found:
                    break
    return found


def resolve_font_path(
    font_name: str,
    *,
    bold: bool = False,
    fonts_dir: Path | str | None = None,
) -> Path | None:
    """Locate a TrueType/OpenType font file in fonts_dir or OS font folders."""
    directory = Path(fonts_dir) if fonts_dir is not None else _default_fonts_dir()
    normalized = re.sub(r"[^a-z0-9]+", "", (font_name or "").lower())

    if directory.is_dir():
        font_files = sorted(
            p for p in directory.iterdir()
            if p.is_file() and p.suffix.lower() in (".ttf", ".otf")
        )
        matched = [
            p for p in font_files
            if normalized and normalized in re.sub(r"[^a-z0-9]+", "", p.stem.lower())
        ]
        if matched:
            if bold:
                for p in matched:
                    if "bold" in p.stem.lower() and "italic" not in p.stem.lower():
                        return p
            for p in matched:
                if "regular" in p.stem.lower() or (
                    "bold" not in p.stem.lower() and "italic" not in p.stem.lower()
                ):
                    return p
            return matched[0]
        if font_files:
            for p in font_files:
                if "astra" in p.stem.lower():
                    if not bold or "bold" in p.stem.lower():
                        return p
            return font_files[0]

    prefer_serif = "sans" not in normalized and "inter" not in normalized
    candidates = _system_font_candidates(bold=bold, serif=prefer_serif)
    if not candidates:
        candidates = _system_font_candidates(bold=bold, serif=not prefer_serif)
    return candidates[0] if candidates else None


def _load_font(font_path: Path | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path is not None:
        try:
            return ImageFont.truetype(str(font_path), size=size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: Any) -> float:
    if not text:
        return 0.0
    bbox = draw.textbbox((0, 0), text, font=font)
    return float(bbox[2] - bbox[0])


def _line_height(draw: ImageDraw.ImageDraw, font: Any) -> float:
    bbox = draw.textbbox((0, 0), "АБВГДЙЁjg", font=font)
    return max(12.0, float(bbox[3] - bbox[1]))


def _break_long_word(
    draw: ImageDraw.ImageDraw,
    word: str,
    font: Any,
    max_width: float,
) -> list[str]:
    """Split an overlong word so every chunk fits within max_width."""
    chunks: list[str] = []
    current = ""
    for ch in word:
        candidate = current + ch
        if current and _text_width(draw, candidate, font) > max_width:
            chunks.append(current)
            current = ch
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [word]


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: Any,
    max_width: float,
) -> list[str]:
    """Word-wrap text within max_width while avoiding hanging short prepositions."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []

    raw_words = cleaned.split(" ")
    words: list[str] = []
    for word in raw_words:
        if _text_width(draw, word, font) > max_width:
            words.extend(_break_long_word(draw, word, font, max_width))
        else:
            words.append(word)

    lines: list[str] = []
    current_words: list[str] = []

    for word in words:
        candidate = " ".join(current_words + [word])
        if not current_words or _text_width(draw, candidate, font) <= max_width:
            current_words.append(word)
        else:
            if len(current_words) > 1 and current_words[-1].lower().strip("«\"(") in _NO_ORPHAN_WORDS:
                orphan = current_words.pop()
                lines.append(" ".join(current_words))
                moved = f"{orphan} {word}"
                if _text_width(draw, moved, font) <= max_width:
                    current_words = [orphan, word]
                else:
                    lines.append(orphan)
                    current_words = [word]
            else:
                lines.append(" ".join(current_words))
                current_words = [word]

    if current_words:
        lines.append(" ".join(current_words))
    return lines


def _truncate_last_line(
    draw: ImageDraw.ImageDraw,
    line: str,
    font: Any,
    max_width: float,
) -> str:
    ellipsis = "…"
    trimmed = line.rstrip(" .,;:-")
    while trimmed and _text_width(draw, trimmed + ellipsis, font) > max_width:
        trimmed = trimmed[:-1].rstrip()
    return (trimmed + ellipsis) if trimmed else ellipsis


def fit_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Path | None,
    *,
    max_width: float,
    max_height: float,
    max_size: int,
    min_size: int,
    max_lines: int = 5,
    line_spacing: float = 1.22,
) -> tuple[Any, list[str], float]:
    """Scale font down from max_size to min_size until wrapped text fits cleanly."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        font = _load_font(font_path, min_size)
        return font, [], _line_height(draw, font) * line_spacing

    for size in range(max_size, min_size - 1, -2):
        font = _load_font(font_path, size)
        lines = wrap_text(draw, cleaned, font, max_width)
        lh = _line_height(draw, font)
        step = lh * line_spacing
        total_h = lh + max(0, len(lines) - 1) * step
        if len(lines) <= max_lines and total_h <= max_height:
            return font, lines, step

    font = _load_font(font_path, min_size)
    lines = wrap_text(draw, cleaned, font, max_width)
    lh = _line_height(draw, font)
    step = lh * line_spacing
    allowed_lines = max(1, min(max_lines, int((max_height - lh) // step) + 1))
    if len(lines) > allowed_lines:
        kept = lines[:allowed_lines]
        kept[-1] = _truncate_last_line(draw, kept[-1], font, max_width)
        lines = kept
    return font, lines, step


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: Sequence[str],
    font: Any,
    *,
    x: float,
    y: float,
    step: float,
    color: str,
    align: str = "center",
    block_width: float = 0.0,
) -> float:
    cur_y = y
    for line in lines:
        w = _text_width(draw, line, font)
        if align == "center":
            lx = x + (block_width - w) / 2.0
        elif align == "right":
            lx = x + (block_width - w)
        else:
            lx = x
        draw.text((lx, cur_y), line, font=font, fill=color)
        cur_y += step
    return cur_y


def _format_series_label(meta: CoverMetadata, spec: CoverSpec) -> str:
    if not spec.show_series or not meta.series:
        return ""
    if spec.show_series_number and meta.series_number:
        return f"{meta.series} · № {meta.series_number}"
    return meta.series


def _draw_pill(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: Any,
    *,
    x: float,
    y: float,
    bg: str,
    fg: str,
    pad_x: int = 28,
    pad_y: int = 14,
    center_in_width: float | None = None,
) -> tuple[float, float]:
    tw = _text_width(draw, text, font)
    th = _line_height(draw, font)
    pw = tw + pad_x * 2
    ph = th + pad_y * 2
    px = x if center_in_width is None else x + (center_in_width - pw) / 2.0
    draw.rounded_rectangle(
        (px, y, px + pw, y + ph),
        radius=int(ph / 2),
        fill=bg,
    )
    draw.text((px + pad_x, y + pad_y - 2), text, font=font, fill=fg)
    return pw, ph


def _render_classic_serif(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    meta: CoverMetadata,
    spec: CoverSpec,
    pal: CoverPalette,
    title_font_path: Path | None,
    meta_font_path: Path | None,
) -> None:
    margin = 68
    draw.rectangle((margin, margin, _CANVAS_W - margin, _CANVAS_H - margin), outline=pal.accent, width=4)
    inner = margin + 18
    draw.rectangle((inner, inner, _CANVAS_W - inner, _CANVAS_H - inner), outline=pal.accent, width=2)
    sq = 14
    for cx in (margin, _CANVAS_W - margin - sq):
        for cy in (margin, _CANVAS_H - margin - sq):
            draw.rectangle((cx, cy, cx + sq, cy + sq), fill=pal.accent)

    content_x = 136
    content_w = _CANVAS_W - content_x * 2

    if spec.show_author and meta.author:
        a_font, a_lines, a_step = fit_text_block(
            draw, meta.author.upper(), meta_font_path,
            max_width=content_w, max_height=180, max_size=44, min_size=28, max_lines=3,
        )
        _draw_lines(draw, a_lines, a_font, x=content_x, y=175, step=a_step, color=pal.fg, align="center", block_width=content_w)

    series_text = _format_series_label(meta, spec)
    subtitle_text = (spec.custom_subtitle or meta.subtitle).strip()
    has_footer = bool(series_text or (spec.show_genre_badge and meta.genre))
    title_zone_top = 460 if (spec.show_author and meta.author) else 380
    title_zone_bottom = 1280 if has_footer else 1420

    t_font, t_lines, t_step = fit_text_block(
        draw, meta.title, title_font_path,
        max_width=content_w, max_height=title_zone_bottom - title_zone_top - 120,
        max_size=108, min_size=50, max_lines=6, line_spacing=1.18,
    )
    t_block_h = len(t_lines) * t_step
    t_y = title_zone_top + max(0.0, (title_zone_bottom - title_zone_top - t_block_h) / 2.0)

    draw.line((_CANVAS_W / 2 - 90, t_y - 46, _CANVAS_W / 2 + 90, t_y - 46), fill=pal.accent, width=4)
    after_title_y = _draw_lines(draw, t_lines, t_font, x=content_x, y=t_y, step=t_step, color=pal.fg, align="center", block_width=content_w)
    draw.line((_CANVAS_W / 2 - 90, after_title_y + 26, _CANVAS_W / 2 + 90, after_title_y + 26), fill=pal.accent, width=4)

    if subtitle_text:
        s_font, s_lines, s_step = fit_text_block(
            draw, subtitle_text, meta_font_path,
            max_width=content_w, max_height=120, max_size=36, min_size=24, max_lines=2,
        )
        _draw_lines(
            draw, s_lines, s_font, x=content_x, y=after_title_y + 62, step=s_step,
            color=_blend_hex(pal.fg, pal.bg, 0.25), align="center", block_width=content_w,
        )

    footer_y = 1440.0
    if series_text:
        ser_font, ser_lines, ser_step = fit_text_block(
            draw, series_text, meta_font_path,
            max_width=content_w, max_height=140, max_size=38, min_size=26, max_lines=2,
        )
        footer_y = _draw_lines(
            draw, ser_lines, ser_font, x=content_x, y=footer_y, step=ser_step,
            color=pal.accent, align="center", block_width=content_w,
        ) + 22

    if spec.show_genre_badge and meta.genre:
        g_font = _load_font(meta_font_path, 30)
        _draw_pill(draw, meta.genre, g_font, x=content_x, y=min(footer_y, 1580.0), bg=pal.badge_bg, fg=pal.badge_fg, center_in_width=content_w)


def _render_eink_minimal(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    meta: CoverMetadata,
    spec: CoverSpec,
    pal: CoverPalette,
    title_font_path: Path | None,
    meta_font_path: Path | None,
) -> None:
    left_x = 120
    content_w = _CANVAS_W - left_x * 2
    draw.rectangle((left_x, 110, _CANVAS_W - left_x, 126), fill=pal.accent)

    cur_y = 178.0
    if spec.show_author and meta.author:
        a_font, a_lines, a_step = fit_text_block(
            draw, meta.author.upper(), meta_font_path,
            max_width=content_w, max_height=170, max_size=46, min_size=30, max_lines=3,
        )
        cur_y = _draw_lines(draw, a_lines, a_font, x=left_x, y=cur_y, step=a_step, color=pal.fg, align="left")

    t_font, t_lines, t_step = fit_text_block(
        draw, meta.title, title_font_path,
        max_width=content_w, max_height=760, max_size=122, min_size=54,
        max_lines=6, line_spacing=1.15,
    )
    title_y = max(cur_y + 110, 460.0)
    after_title_y = _draw_lines(draw, t_lines, t_font, x=left_x, y=title_y, step=t_step, color=pal.fg, align="left")
    draw.rectangle((left_x, after_title_y + 36, _CANVAS_W - left_x, after_title_y + 42), fill=pal.accent)

    subtitle_text = (spec.custom_subtitle or meta.subtitle).strip()
    if subtitle_text:
        s_font, s_lines, s_step = fit_text_block(
            draw, subtitle_text, meta_font_path,
            max_width=content_w, max_height=130, max_size=38, min_size=26, max_lines=2,
        )
        _draw_lines(
            draw, s_lines, s_font, x=left_x, y=after_title_y + 74, step=s_step,
            color=_blend_hex(pal.fg, pal.bg, 0.28), align="left",
        )

    bottom_y = 1480.0
    series_text = _format_series_label(meta, spec)
    if series_text:
        ser_font, ser_lines, ser_step = fit_text_block(
            draw, series_text, meta_font_path,
            max_width=content_w, max_height=130, max_size=40, min_size=28, max_lines=2,
        )
        bottom_y = _draw_lines(draw, ser_lines, ser_font, x=left_x, y=bottom_y, step=ser_step, color=pal.fg, align="left") + 24

    if spec.show_genre_badge and meta.genre:
        g_font = _load_font(meta_font_path, 30)
        _draw_pill(draw, meta.genre, g_font, x=left_x, y=min(bottom_y, 1610.0), bg=pal.badge_bg, fg=pal.badge_fg)


def _render_series_edition(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    meta: CoverMetadata,
    spec: CoverSpec,
    pal: CoverPalette,
    title_font_path: Path | None,
    meta_font_path: Path | None,
) -> None:
    band_h = 310
    band_color = _blend_hex(pal.bg, pal.accent, 0.24)
    draw.rectangle((0, 0, _CANVAS_W, band_h), fill=band_color)
    draw.rectangle((0, band_h, _CANVAS_W, band_h + 10), fill=pal.accent)

    left_x = 110
    content_w = _CANVAS_W - left_x * 2

    vol_reserve = 0
    if spec.show_series_number and meta.series_number:
        vol_text = f"#{meta.series_number}"
        v_font = _load_font(title_font_path, 66)
        vw = _text_width(draw, vol_text, v_font) + 56
        vh = 118
        vx = _CANVAS_W - left_x - vw
        vy = (band_h - vh) / 2.0
        draw.rounded_rectangle((vx, vy, vx + vw, vy + vh), radius=24, fill=pal.accent)
        draw.text((vx + 28, vy + 20), vol_text, font=v_font, fill=_auto_contrast_fg(pal.accent))
        vol_reserve = int(vw + 36)

    header_label = meta.series if (spec.show_series and meta.series) else (meta.author or "Издание")
    h_font, h_lines, h_step = fit_text_block(
        draw, header_label.upper(), meta_font_path,
        max_width=content_w - vol_reserve, max_height=200,
        max_size=46, min_size=28, max_lines=3,
    )
    h_block_h = len(h_lines) * h_step
    _draw_lines(draw, h_lines, h_font, x=left_x, y=(band_h - h_block_h) / 2.0, step=h_step, color=pal.fg, align="left")

    t_font, t_lines, t_step = fit_text_block(
        draw, meta.title, title_font_path,
        max_width=content_w, max_height=740, max_size=114, min_size=52,
        max_lines=6, line_spacing=1.16,
    )
    after_title_y = _draw_lines(draw, t_lines, t_font, x=left_x, y=450, step=t_step, color=pal.fg, align="left")

    subtitle_text = (spec.custom_subtitle or meta.subtitle).strip()
    if subtitle_text:
        s_font, s_lines, s_step = fit_text_block(
            draw, subtitle_text, meta_font_path,
            max_width=content_w, max_height=130, max_size=38, min_size=26, max_lines=2,
        )
        _draw_lines(
            draw, s_lines, s_font, x=left_x, y=after_title_y + 42, step=s_step,
            color=_blend_hex(pal.fg, pal.bg, 0.25), align="left",
        )

    footer_y = 1450.0
    if spec.show_author and meta.author and header_label != meta.author:
        a_font, a_lines, a_step = fit_text_block(
            draw, meta.author, meta_font_path,
            max_width=content_w, max_height=130, max_size=48, min_size=30, max_lines=2,
        )
        footer_y = _draw_lines(draw, a_lines, a_font, x=left_x, y=footer_y, step=a_step, color=pal.accent, align="left") + 26

    if spec.show_genre_badge and meta.genre:
        g_font = _load_font(meta_font_path, 30)
        _draw_pill(draw, meta.genre, g_font, x=left_x, y=min(footer_y, 1600.0), bg=pal.badge_bg, fg=pal.badge_fg)


def _render_modern_band(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    meta: CoverMetadata,
    spec: CoverSpec,
    pal: CoverPalette,
    title_font_path: Path | None,
    meta_font_path: Path | None,
) -> None:
    draw.rectangle((0, 0, 34, _CANVAS_H), fill=pal.accent)
    band_top = 1190
    lower_bg = _blend_hex(pal.bg, pal.accent, 0.26)
    draw.polygon(
        [(34, band_top + 70), (_CANVAS_W, band_top), (_CANVAS_W, _CANVAS_H), (34, _CANVAS_H)],
        fill=lower_bg,
    )
    draw.line([(34, band_top + 70), (_CANVAS_W, band_top)], fill=pal.accent, width=8)

    left_x = 128
    content_w = _CANVAS_W - left_x - 100

    top_y = 140.0
    if spec.show_genre_badge and meta.genre:
        g_font = _load_font(meta_font_path, 30)
        _, ph = _draw_pill(draw, meta.genre, g_font, x=left_x, y=top_y, bg=pal.badge_bg, fg=pal.badge_fg)
        top_y += ph + 54

    if spec.show_author and meta.author:
        a_font, a_lines, a_step = fit_text_block(
            draw, meta.author, meta_font_path,
            max_width=content_w, max_height=180, max_size=48, min_size=30, max_lines=3,
        )
        top_y = _draw_lines(draw, a_lines, a_font, x=left_x, y=top_y, step=a_step, color=pal.accent, align="left") + 48

    t_font, t_lines, t_step = fit_text_block(
        draw, meta.title, title_font_path,
        max_width=content_w, max_height=max(260.0, band_top - top_y - 60),
        max_size=118, min_size=50, max_lines=6, line_spacing=1.16,
    )
    _draw_lines(draw, t_lines, t_font, x=left_x, y=top_y + 20, step=t_step, color=pal.fg, align="left")

    lower_y = band_top + 140.0
    series_text = _format_series_label(meta, spec)
    if series_text:
        ser_font, ser_lines, ser_step = fit_text_block(
            draw, series_text, meta_font_path,
            max_width=content_w, max_height=160, max_size=44, min_size=28, max_lines=2,
        )
        lower_y = _draw_lines(draw, ser_lines, ser_font, x=left_x, y=lower_y, step=ser_step, color=pal.fg, align="left") + 28

    subtitle_text = (spec.custom_subtitle or meta.subtitle).strip()
    if subtitle_text:
        s_font, s_lines, s_step = fit_text_block(
            draw, subtitle_text, meta_font_path,
            max_width=content_w, max_height=160, max_size=36, min_size=24, max_lines=3,
        )
        _draw_lines(
            draw, s_lines, s_font, x=left_x, y=lower_y, step=s_step,
            color=_blend_hex(pal.fg, lower_bg, 0.22), align="left",
        )


def _render_chronicle(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    meta: CoverMetadata,
    spec: CoverSpec,
    pal: CoverPalette,
    title_font_path: Path | None,
    meta_font_path: Path | None,
) -> None:
    outer = 58
    draw.rectangle((outer, outer, _CANVAS_W - outer, _CANVAS_H - outer), outline=pal.accent, width=8)
    mid = outer + 20
    draw.rectangle((mid, mid, _CANVAS_W - mid, _CANVAS_H - mid), outline=pal.accent, width=2)

    for cx in (outer + 34, _CANVAS_W - outer - 34):
        for cy in (outer + 34, _CANVAS_H - outer - 34):
            r = 16
            draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=pal.accent)

    content_x = 150
    content_w = _CANVAS_W - content_x * 2

    if spec.show_author and meta.author:
        a_font, a_lines, a_step = fit_text_block(
            draw, meta.author, meta_font_path,
            max_width=content_w, max_height=170, max_size=46, min_size=30, max_lines=3,
        )
        _draw_lines(draw, a_lines, a_font, x=content_x, y=190, step=a_step, color=pal.accent, align="center", block_width=content_w)

    cx = _CANVAS_W / 2.0
    cy_top = 420.0
    draw.line((cx - 180, cy_top, cx - 26, cy_top), fill=pal.accent, width=3)
    draw.line((cx + 26, cy_top, cx + 180, cy_top), fill=pal.accent, width=3)
    draw.polygon([(cx, cy_top - 14), (cx + 14, cy_top), (cx, cy_top + 14), (cx - 14, cy_top)], fill=pal.accent)

    t_font, t_lines, t_step = fit_text_block(
        draw, meta.title, title_font_path,
        max_width=content_w, max_height=680, max_size=104, min_size=48,
        max_lines=6, line_spacing=1.22,
    )
    t_block_h = len(t_lines) * t_step
    t_y = 480.0 + max(0.0, (700.0 - t_block_h) / 2.0)
    after_title_y = _draw_lines(draw, t_lines, t_font, x=content_x, y=t_y, step=t_step, color=pal.fg, align="center", block_width=content_w)

    cy_bot = min(after_title_y + 48, 1290.0)
    draw.line((cx - 180, cy_bot, cx - 26, cy_bot), fill=pal.accent, width=3)
    draw.line((cx + 26, cy_bot, cx + 180, cy_bot), fill=pal.accent, width=3)
    draw.polygon([(cx, cy_bot - 14), (cx + 14, cy_bot), (cx, cy_bot + 14), (cx - 14, cy_bot)], fill=pal.accent)

    footer_y = 1390.0
    series_text = _format_series_label(meta, spec)
    if series_text:
        ser_font, ser_lines, ser_step = fit_text_block(
            draw, series_text, meta_font_path,
            max_width=content_w, max_height=130, max_size=38, min_size=26, max_lines=2,
        )
        footer_y = _draw_lines(draw, ser_lines, ser_font, x=content_x, y=footer_y, step=ser_step, color=pal.fg, align="center", block_width=content_w) + 22

    if spec.show_genre_badge and meta.genre:
        g_font = _load_font(meta_font_path, 30)
        _draw_pill(draw, meta.genre, g_font, x=content_x, y=min(footer_y, 1550.0), bg=pal.badge_bg, fg=pal.badge_fg, center_in_width=content_w)


_TEMPLATE_RENDERERS = {
    "classic_serif": _render_classic_serif,
    "eink_minimal": _render_eink_minimal,
    "series_edition": _render_series_edition,
    "modern_band": _render_modern_band,
    "chronicle": _render_chronicle,
}


def apply_eink_profile(
    image: Image.Image,
    profile: str,
    *,
    simulate_preview: bool = False,
) -> Image.Image:
    """Apply E Ink optimization (and optional display simulation) via core.image_optimizer."""
    mode = _EINK_PROFILE_ALIASES.get((profile or "none").strip().lower(), (profile or "none").strip().lower())
    if mode in ("", "none") and not simulate_preview:
        return image

    try:
        from core.image_optimizer import optimize_and_preview_image_bytes

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        out_bytes, _ = optimize_and_preview_image_bytes(
            buf.getvalue(),
            mime="image/png",
            profile_id=mode,
            simulate_eink=simulate_preview,
        )
        with Image.open(io.BytesIO(out_bytes)) as processed:
            return processed.convert("RGB")
    except Exception as e:
        logger.debug("Фолбэк E Ink профиля (%s) в Cover Studio: %s", mode, e)

    # Standalone Pillow fallback
    if mode in ("eink_bw", "eink_bw_16_dither"):
        gray = ImageOps.grayscale(image)
        gray = ImageEnhance.Contrast(gray).enhance(1.12)
        return gray.convert("RGB")
    if mode == "eink_kaleido3":
        return ImageEnhance.Color(image).enhance(0.55)
    if mode == "eink_gallery3":
        return ImageEnhance.Color(image).enhance(0.78)
    return image


def render_cover_image(
    meta: CoverMetadata,
    spec: CoverSpec | None = None,
    *,
    fonts_dir: Path | str | None = None,
    simulate_eink_preview: bool = False,
) -> Image.Image:
    """Render a typographic book cover as a PIL Image."""
    effective_spec = spec or CoverSpec()
    pal = resolve_palette(effective_spec, meta.series)

    title_font_path = resolve_font_path(effective_spec.title_font, bold=True, fonts_dir=fonts_dir)
    meta_font_path = resolve_font_path(effective_spec.meta_font, bold=False, fonts_dir=fonts_dir)

    canvas = Image.new("RGB", (_CANVAS_W, _CANVAS_H), color=pal.bg)
    draw = ImageDraw.Draw(canvas)

    renderer = _TEMPLATE_RENDERERS.get(effective_spec.template_id, _render_eink_minimal)
    renderer(canvas, draw, meta, effective_spec, pal, title_font_path, meta_font_path)

    target_w, target_h = effective_spec.output_size
    if (target_w, target_h) != (_CANVAS_W, _CANVAS_H):
        result = canvas.resize((target_w, target_h), Image.Resampling.LANCZOS)
    else:
        result = canvas

    return apply_eink_profile(
        result,
        effective_spec.eink_profile,
        simulate_preview=simulate_eink_preview,
    )


def render_cover_bytes(
    meta: CoverMetadata,
    spec: CoverSpec | None = None,
    *,
    fonts_dir: Path | str | None = None,
    simulate_eink_preview: bool = False,
) -> bytes:
    """Render cover and encode as Baseline JPEG or PNG bytes for FB2 embedding."""
    effective_spec = spec or CoverSpec()
    img = render_cover_image(
        meta,
        effective_spec,
        fonts_dir=fonts_dir,
        simulate_eink_preview=simulate_eink_preview,
    )
    buf = io.BytesIO()
    fmt = effective_spec.output_format.upper()
    if fmt == "PNG":
        img.save(buf, format="PNG", optimize=True)
    else:
        img.save(
            buf,
            format="JPEG",
            quality=effective_spec.jpeg_quality,
            optimize=True,
            progressive=False,
        )
    return buf.getvalue()


def render_template_thumbnail(
    template_id: str,
    *,
    palette_id: str = "emerald",
    size: tuple[int, int] = (108, 162),
    fonts_dir: Path | str | None = None,
) -> Image.Image:
    """Render a compact preview thumbnail for template picker cards in Cover Studio UI."""
    sample = CoverMetadata(
        title="Пикник на обочине",
        author="А. и Б. Стругацкие",
        series="Мир Полудня",
        series_number="1",
        genre="Фантастика",
    )
    spec = CoverSpec(
        template_id=template_id if template_id in TEMPLATES else "eink_minimal",
        palette_id=palette_id,
        show_genre_badge=True,
        output_size=size,
    )
    return render_cover_image(sample, spec, fonts_dir=fonts_dir)

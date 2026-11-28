"""Расширяемая оптимизация иллюстраций и обложек под типы экранов ридеров (E Ink) и имитация в превью."""

import base64
from collections import OrderedDict
import copy
import hashlib
import io
import json
import threading
import xml.etree.ElementTree as ET

from core.logger import get_logger

logger = get_logger("image_optimizer")

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    HAS_PIL = True
except ImportError:
    Image = ImageEnhance = ImageFilter = ImageOps = None
    HAS_PIL = False

MAX_OPTIMIZE_IMAGE_PIXELS = 40_000_000  # Защита от decompression bomb (как в xml_io.py)
_PREVIEW_CACHE_MAX_ITEMS = 24
_PREVIEW_CACHE = OrderedDict()
_PREVIEW_CACHE_LOCK = threading.Lock()

# Декларативный реестр профилей экранов ридеров.
# Чтобы добавить новый тип экрана (например, Kaleido 4, Spectra 6, Carta 1400),
# достаточно добавить одну запись сюда или зарегистрировать через register_image_display_profile().
IMAGE_DISPLAY_PROFILES = {
    "none": {
        "label_key": "styles.img_profile.none",
        "fallback_label": "Off (Original)",
        "mode": "original",
        "optimize": None,
        "simulate": None,
    },
    "eink_bw": {
        "label_key": "styles.img_profile.eink_bw",
        "fallback_label": "B&W E Ink (Carta 1200/1300)",
        "mode": "grayscale",
        "optimize": {
            "gamma": 1.15,
            "autocontrast_cutoff": 1.0,
            "contrast": 1.06,
            "saturation": 1.0,
            "sharpen": (1.0, 45, 3),
            "quantize_levels": None,
            "dither": False,
        },
        "simulate": {
            "grayscale_levels": 16,
            "color_bits_per_channel": None,
            "saturation_scale": 0.0,
            "black_floor": 30,
            "white_ceiling": 234,
            "paper_bg": "#ECEAE2",
            "paper_text": "#242422",
        },
    },
    "eink_bw_16_dither": {
        "label_key": "styles.img_profile.eink_bw_16_dither",
        "fallback_label": "B&W E Ink — 16 Gray Levels (Dithered)",
        "mode": "grayscale",
        "optimize": {
            "gamma": 1.15,
            "autocontrast_cutoff": 1.0,
            "contrast": 1.05,
            "saturation": 1.0,
            "sharpen": (0.8, 35, 3),
            "quantize_levels": 16,
            "dither": True,
        },
        "simulate": {
            "grayscale_levels": 16,
            "color_bits_per_channel": None,
            "saturation_scale": 0.0,
            "black_floor": 32,
            "white_ceiling": 232,
            "paper_bg": "#EBE9E0",
            "paper_text": "#242422",
        },
    },
    "eink_kaleido3": {
        "label_key": "styles.img_profile.eink_kaleido3",
        "fallback_label": "Color E Ink (Kaleido 3 — 4096 colors)",
        "mode": "color",
        "optimize": {
            "gamma": 1.18,
            "autocontrast_cutoff": 0.5,
            "contrast": 1.08,
            "saturation": 1.30,
            "sharpen": (1.0, 40, 3),
            "quantize_levels": None,
            "dither": False,
        },
        "simulate": {
            "grayscale_levels": None,
            "color_bits_per_channel": 4,  # 16^3 = 4096 цветов
            "saturation_scale": 0.56,
            "black_floor": 38,
            "white_ceiling": 208,
            "paper_bg": "#D8D7D2",
            "paper_text": "#2A2A28",
        },
    },
    "eink_gallery3": {
        "label_key": "styles.img_profile.eink_gallery3",
        "fallback_label": "Color E Ink (Gallery 3 / Canvas Color)",
        "mode": "color",
        "optimize": {
            "gamma": 1.08,
            "autocontrast_cutoff": 0.5,
            "contrast": 1.04,
            "saturation": 1.12,
            "sharpen": (0.9, 30, 3),
            "quantize_levels": None,
            "dither": False,
        },
        "simulate": {
            "grayscale_levels": None,
            "color_bits_per_channel": 5,  # ~32k бумажных оттенков CMYW
            "saturation_scale": 0.78,
            "black_floor": 32,
            "white_ceiling": 228,
            "paper_bg": "#E7E4DC",
            "paper_text": "#262523",
        },
    },
}


def register_image_display_profile(profile_id, spec):
    """Регистрирует новый профиль экрана (или обновляет существующий) для пресетов и превью."""
    key = str(profile_id or "").strip()
    if not key:
        raise ValueError("profile_id must be a non-empty string")
    if not isinstance(spec, dict):
        raise ValueError("profile spec must be a dictionary")
    IMAGE_DISPLAY_PROFILES[key] = copy.deepcopy(spec)
    clear_preview_image_cache()
    return key


def get_image_display_profile_ids():
    """Возвращает упорядоченный кортеж всех зарегистрированных идентификаторов профилей экрана."""
    return tuple(IMAGE_DISPLAY_PROFILES.keys())


def get_image_display_profile_choices(translator=None):
    """Возвращает список пар (label, profile_id) для выпадающего списка UI."""
    choices = []
    for pid, spec in IMAGE_DISPLAY_PROFILES.items():
        lkey = spec.get("label_key") or ""
        fallback = spec.get("fallback_label") or pid
        if translator is not None and lkey:
            label = translator(lkey)
            if not label or label == lkey:
                label = fallback
        else:
            label = fallback
        choices.append((label, pid))
    return choices


def resolve_image_display_profile(profile_id, custom_profile=None):
    """Возвращает словарь профиля экрана по ID и/или с учётом inline-переопределений из пресета."""
    pid = str(profile_id or "none").strip()
    base = IMAGE_DISPLAY_PROFILES.get(pid)
    if base is None:
        base = IMAGE_DISPLAY_PROFILES["none"]
    resolved = copy.deepcopy(base)
    if isinstance(custom_profile, dict) and custom_profile:
        for section in ("mode", "label_key", "fallback_label"):
            if section in custom_profile:
                resolved[section] = custom_profile[section]
        for section in ("optimize", "simulate"):
            if isinstance(custom_profile.get(section), dict):
                cur = dict(resolved.get(section) or {})
                cur.update(custom_profile[section])
                resolved[section] = cur
    return resolved


def clear_preview_image_cache():
    """Очищает кэш обработанных превью-изображений."""
    with _PREVIEW_CACHE_LOCK:
        _PREVIEW_CACHE.clear()


def _apply_gamma_lut(img, gamma):
    """Применяет гамма-коррекцию (gamma > 1.0 осветляет тени, gamma < 1.0 затемняет)."""
    try:
        g = float(gamma)
    except (TypeError, ValueError):
        return img
    if abs(g - 1.0) < 1e-3 or g <= 0.05:
        return img
    inv_g = 1.0 / g
    lut = [min(255, max(0, int(round(((i / 255.0) ** inv_g) * 255.0)))) for i in range(256)]
    if img.mode == "L":
        return img.point(lut)
    if img.mode == "RGB":
        return img.point(lut * 3)
    return img


def _quantize_grayscale_levels(gray_img, levels, dither=True):
    """Квантует 8-bit grayscale изображение до указанного числа градаций (например, 16) с опциональным дизерингом."""
    lvl = max(2, min(256, int(levels)))
    if lvl >= 256:
        return gray_img
    step_vals = [int(round(i * 255.0 / (lvl - 1))) for i in range(lvl)]
    pal_img = Image.new("P", (1, 1))
    palette = []
    for v in step_vals:
        palette.extend((v, v, v))
    palette.extend([0, 0, 0] * (256 - lvl))
    pal_img.putpalette(palette)
    dither_flag = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    quantized = gray_img.convert("RGB").quantize(palette=pal_img, dither=dither_flag)
    return quantized.convert("L")


def _quantize_rgb_bits(rgb_img, bits_per_channel):
    """Квантует каждый RGB-канал до заданного числа бит (например, 4 бита = 16 уровней = 4096 цветов)."""
    bits = max(1, min(8, int(bits_per_channel)))
    if bits >= 8:
        return rgb_img
    levels = (1 << bits) - 1
    lut = [int(round(round(i * levels / 255.0) * 255.0 / levels)) for i in range(256)]
    return rgb_img.point(lut * 3)


def _remap_dynamic_range(img, black_floor, white_ceiling):
    """Сжимает динамический диапазон [0..255] в физический диапазон отражения E Ink [black_floor..white_ceiling]."""
    lo = max(0, min(200, int(black_floor)))
    hi = max(lo + 10, min(255, int(white_ceiling)))
    span = hi - lo
    lut = [int(round(lo + (i / 255.0) * span)) for i in range(256)]
    if img.mode == "L":
        return img.point(lut)
    if img.mode == "RGB":
        return img.point(lut * 3)
    return img


def _encode_pil_image(img, orig_mime, jpeg_quality=95, keep_alpha=False, fast_encode=False):
    """Кодирует обработанное PIL-изображение в байты (JPEG или PNG) и возвращает (bytes, mime)."""
    out = io.BytesIO()
    low_mime = str(orig_mime or "").lower()
    use_png = keep_alpha or low_mime == "image/png"
    if use_png:
        if fast_encode:
            img.save(out, format="PNG", compress_level=1)
        else:
            img.save(out, format="PNG", optimize=True)
        return out.getvalue(), "image/png"
    save_img = img if img.mode in ("L", "RGB") else img.convert("RGB")
    q = max(40, min(100, int(jpeg_quality or 95)))
    save_img.save(out, format="JPEG", quality=q, optimize=(not fast_encode))
    return out.getvalue(), "image/jpeg"


def open_raster_image_safely(raw_bytes, max_pixels=MAX_OPTIMIZE_IMAGE_PIXELS, *, load=True):
    """Безопасно открывает растровое изображение в Pillow с проверкой лимита пикселей (защита от decompression bomb)."""
    if not HAS_PIL or not raw_bytes:
        return None
    img = Image.open(io.BytesIO(raw_bytes))
    try:
        w, h = img.size
        if w <= 0 or h <= 0 or (w * h) > int(max_pixels):
            raise ValueError(f"Image dimensions ({w}x{h}) exceed safety limit")
        if load:
            img.load()
        return img
    except Exception:
        img.close()
        raise


def _open_raster_safely(raw_bytes):
    """Внутренняя обёртка для безопасного открытия растрового изображения."""
    return open_raster_image_safely(raw_bytes, max_pixels=MAX_OPTIMIZE_IMAGE_PIXELS, load=True)


def optimize_image_bytes(
    raw_bytes,
    mime="image/jpeg",
    profile_id="none",
    *,
    jpeg_quality=95,
    custom_profile=None,
    fast_encode=False,
):
    """
    Оптимизирует растровое изображение (обложку или иллюстрацию) под профиль экрана ридера.
    Возвращает кортеж (out_bytes, out_mime). Для SVG или profile_id='none' возвращает исходные байты.
    """
    if not raw_bytes or not HAS_PIL:
        return raw_bytes, (mime or "image/jpeg")
    low_mime = str(mime or "").lower()
    if "svg" in low_mime:
        return raw_bytes, mime

    prof = resolve_image_display_profile(profile_id, custom_profile=custom_profile)
    opt = prof.get("optimize")
    mode = prof.get("mode", "original")
    if not opt or mode == "original":
        return raw_bytes, (mime or "image/jpeg")

    img = _open_raster_safely(raw_bytes)
    if img is None:
        return raw_bytes, (mime or "image/jpeg")

    try:
        alpha = None
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            alpha = rgba.getchannel("A")
            work = rgba.convert("RGB")
        else:
            work = img.convert("RGB")

        if mode == "grayscale":
            work = work.convert("L")
            cutoff = float(opt.get("autocontrast_cutoff") or 0.0)
            if cutoff > 0.0:
                work = ImageOps.autocontrast(work, cutoff=cutoff)
            work = _apply_gamma_lut(work, opt.get("gamma", 1.0))
            contrast = float(opt.get("contrast") or 1.0)
            if abs(contrast - 1.0) >= 1e-3:
                work = ImageEnhance.Contrast(work).enhance(contrast)
            sharpen = opt.get("sharpen")
            if isinstance(sharpen, (tuple, list)) and len(sharpen) == 3:
                work = work.filter(
                    ImageFilter.UnsharpMask(
                        radius=float(sharpen[0]),
                        percent=int(sharpen[1]),
                        threshold=int(sharpen[2]),
                    )
                )
            q_levels = opt.get("quantize_levels")
            if q_levels:
                work = _quantize_grayscale_levels(work, q_levels, dither=bool(opt.get("dither", True)))
            if alpha is not None and low_mime == "image/png":
                out_img = Image.merge("LA", (work, alpha))
                return _encode_pil_image(out_img, "image/png", jpeg_quality=jpeg_quality, keep_alpha=True, fast_encode=fast_encode)
            return _encode_pil_image(work, mime, jpeg_quality=jpeg_quality, keep_alpha=False, fast_encode=fast_encode)

        # Цветной профиль (Kaleido 3, Gallery 3 и любые будущие цветные E Ink)
        cutoff = float(opt.get("autocontrast_cutoff") or 0.0)
        if cutoff > 0.0:
            work = ImageOps.autocontrast(work, cutoff=cutoff)
        work = _apply_gamma_lut(work, opt.get("gamma", 1.0))
        sat = float(opt.get("saturation") or 1.0)
        if abs(sat - 1.0) >= 1e-3:
            work = ImageEnhance.Color(work).enhance(sat)
        contrast = float(opt.get("contrast") or 1.0)
        if abs(contrast - 1.0) >= 1e-3:
            work = ImageEnhance.Contrast(work).enhance(contrast)
        sharpen = opt.get("sharpen")
        if isinstance(sharpen, (tuple, list)) and len(sharpen) == 3:
            work = work.filter(
                ImageFilter.UnsharpMask(
                    radius=float(sharpen[0]),
                    percent=int(sharpen[1]),
                    threshold=int(sharpen[2]),
                )
            )
        if alpha is not None and low_mime == "image/png":
            out_img = work.convert("RGBA")
            out_img.putalpha(alpha)
            return _encode_pil_image(out_img, "image/png", jpeg_quality=jpeg_quality, keep_alpha=True, fast_encode=fast_encode)
        return _encode_pil_image(work, mime, jpeg_quality=jpeg_quality, keep_alpha=False, fast_encode=fast_encode)
    finally:
        img.close()


def simulate_eink_preview_bytes(
    raw_bytes,
    mime="image/jpeg",
    profile_id="none",
    *,
    custom_profile=None,
):
    """
    Симулирует физическое отображение изображения на выбранном экране E Ink
    (16 градаций Carta, приглушённые 4096 цветов Kaleido 3, бумажная палитра Gallery 3 и др.).
    """
    if not raw_bytes or not HAS_PIL:
        return raw_bytes, (mime or "image/jpeg")
    if "svg" in str(mime or "").lower():
        return raw_bytes, mime

    eff_id = profile_id if (profile_id and profile_id != "none") else "eink_bw"
    prof = resolve_image_display_profile(eff_id, custom_profile=custom_profile)
    sim = prof.get("simulate")
    if not sim:
        return raw_bytes, (mime or "image/jpeg")

    img = _open_raster_safely(raw_bytes)
    if img is None:
        return raw_bytes, (mime or "image/jpeg")

    try:
        gray_levels = sim.get("grayscale_levels")
        if gray_levels:
            work = img.convert("L")
            work = _quantize_grayscale_levels(work, gray_levels, dither=True)
            work = _remap_dynamic_range(
                work,
                sim.get("black_floor", 30),
                sim.get("white_ceiling", 234),
            )
            return _encode_pil_image(work, "image/png", jpeg_quality=92, keep_alpha=False)

        work = img.convert("RGB")
        sat_scale = float(sim.get("saturation_scale", 1.0))
        if abs(sat_scale - 1.0) >= 1e-3:
            work = ImageEnhance.Color(work).enhance(sat_scale)
        bits = sim.get("color_bits_per_channel")
        if bits:
            work = _quantize_rgb_bits(work, bits)
        work = _remap_dynamic_range(
            work,
            sim.get("black_floor", 32),
            sim.get("white_ceiling", 228),
        )
        return _encode_pil_image(work, "image/jpeg", jpeg_quality=90, keep_alpha=False)
    finally:
        img.close()


def optimize_and_preview_image_bytes(
    raw_bytes,
    mime="image/jpeg",
    profile_id="none",
    *,
    simulate_eink=False,
    jpeg_quality=95,
    custom_profile=None,
):
    """
    Единая кэшируемая точка входа для превью: сначала применяет ту же оптимизацию,
    что пойдёт в книгу, а при simulate_eink=True дополнительно имитирует экран ридера.
    """
    if not raw_bytes:
        return raw_bytes, (mime or "image/jpeg")
    if (not profile_id or profile_id == "none") and not simulate_eink and not custom_profile:
        return raw_bytes, (mime or "image/jpeg")

    digest = hashlib.sha256(raw_bytes).hexdigest()
    custom_sig = json.dumps(custom_profile, sort_keys=True, ensure_ascii=False) if custom_profile else ""
    cache_key = (digest, str(mime or ""), str(profile_id or "none"), bool(simulate_eink), int(jpeg_quality), custom_sig)

    with _PREVIEW_CACHE_LOCK:
        cached = _PREVIEW_CACHE.get(cache_key)
        if cached is not None:
            _PREVIEW_CACHE.move_to_end(cache_key)
            return cached

    out_bytes, out_mime = optimize_image_bytes(
        raw_bytes,
        mime=mime,
        profile_id=profile_id,
        jpeg_quality=jpeg_quality,
        custom_profile=custom_profile,
    )
    if simulate_eink:
        out_bytes, out_mime = simulate_eink_preview_bytes(
            out_bytes,
            mime=out_mime,
            profile_id=profile_id,
            custom_profile=custom_profile,
        )

    result = (out_bytes, out_mime)
    with _PREVIEW_CACHE_LOCK:
        _PREVIEW_CACHE[cache_key] = result
        while len(_PREVIEW_CACHE) > _PREVIEW_CACHE_MAX_ITEMS:
            _PREVIEW_CACHE.popitem(last=False)
    return result


def get_eink_paper_preview_style(profile_id="none", *, simulate_eink=False, custom_profile=None):
    """Возвращает параметры бумажной подложки и CSS-фильтра для симуляции экрана E Ink в превью."""
    if not simulate_eink:
        return None
    eff_id = profile_id if (profile_id and profile_id != "none") else "eink_bw"
    prof = resolve_image_display_profile(eff_id, custom_profile=custom_profile)
    sim = prof.get("simulate") or {}
    mode = prof.get("mode", "grayscale")
    return {
        "profile_id": eff_id,
        "mode": mode,
        "paper_bg": sim.get("paper_bg", "#ECEAE2"),
        "paper_text": sim.get("paper_text", "#242422"),
        "page_filter": (
            "grayscale(100%) contrast(0.92)"
            if mode == "grayscale"
            else f"saturate({sim.get('saturation_scale', 0.72):.2f}) contrast(0.92)"
        ),
    }


EINK_BW_16_LEVELS = tuple(f"#{v:02x}{v:02x}{v:02x}" for v in range(0, 256, 17))
EINK_BW_QUICK_COLORS = (
    "black", "#222222", "#333333", "#444444", "dimgray", "#777777", "#888888", "#aaaaaa",
)
DEFAULT_COLOR_QUICK_COLORS = (
    "red", "blue", "purple", "green", "magenta", "fuchsia", "black", "navy", "darkred", "dimgray",
)
_EINK_COLOR_RAW_SWATCHES = (
    # Тёмные и насыщенные книжные оттенки (8 в ряду)
    "#000000", "#222222", "#444444", "#666666", "#888888", "#aaaaaa", "#cccccc", "#ffffff",
    "#660000", "#880000", "#aa2222", "#cc3322", "#883300", "#aa5500", "#bb7711", "#886622",
    "#004400", "#116622", "#227733", "#338844", "#005555", "#117777", "#228888", "#447766",
    "#002266", "#113388", "#2244aa", "#3366bb", "#221166", "#442288", "#662288", "#883399",
    "#661144", "#881155", "#aa2266", "#bb4477", "#553322", "#774422", "#885533", "#665544",
)
_GALLERY3_EXTRA_SWATCHES = (
    "#331111", "#992211", "#cc6622", "#336611", "#115566", "#223377", "#552266", "#773355",
)
_KALEIDO3_QUICK_COLORS = (
    "black", "dimgray", "#880000", "#aa2222", "#113388", "#2244aa", "#116622", "#662288", "#774422", "#005555",
)
_GALLERY3_QUICK_COLORS = (
    "black", "dimgray", "darkred", "#aa2222", "navy", "#2244aa", "#116622", "purple", "#774422", "#005555",
)


def _parse_hex_rgb(hex_color):
    s = str(hex_color or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return (0, 0, 0)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def quantize_hex_for_display_profile(hex_color, profile_id="none", *, grayscale=False, custom_profile=None):
    """Квантует HEX-цвет к ближайшему цвету, поддерживаемому выбранным профилем экрана ридера."""
    r, g, b = _parse_hex_rgb(hex_color)
    eff_id = profile_id if (profile_id and profile_id != "none") else ("eink_bw" if grayscale else "none")
    prof = resolve_image_display_profile(eff_id, custom_profile=custom_profile)
    mode = "grayscale" if (grayscale or prof.get("mode") == "grayscale") else prof.get("mode", "original")
    sim = prof.get("simulate") or {}

    if mode == "grayscale":
        levels = max(2, min(256, int(sim.get("grayscale_levels") or 16)))
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        step_idx = int(round(luma * (levels - 1) / 255.0))
        v = int(round(step_idx * 255.0 / (levels - 1)))
        return f"#{v:02x}{v:02x}{v:02x}"

    if mode == "color":
        bits = sim.get("color_bits_per_channel")
        if bits:
            levels = (1 << max(1, min(8, int(bits)))) - 1
            qr = int(round(round(r * levels / 255.0) * 255.0 / levels))
            qg = int(round(round(g * levels / 255.0) * 255.0 / levels))
            qb = int(round(round(b * levels / 255.0) * 255.0 / levels))
            return f"#{qr:02x}{qg:02x}{qb:02x}"

    return f"#{r:02x}{g:02x}{b:02x}"


def simulate_hex_for_display_profile(hex_color, profile_id="none", *, grayscale=False, custom_profile=None):
    """Имитирует физический вид HEX-цвета на экране выбранного ридера (насыщенность + диапазон E Ink)."""
    q_hex = quantize_hex_for_display_profile(
        hex_color, profile_id, grayscale=grayscale, custom_profile=custom_profile
    )
    r, g, b = _parse_hex_rgb(q_hex)
    eff_id = profile_id if (profile_id and profile_id != "none") else ("eink_bw" if grayscale else "none")
    prof = resolve_image_display_profile(eff_id, custom_profile=custom_profile)
    sim = prof.get("simulate")
    if not sim:
        return q_hex

    sat_scale = float(sim.get("saturation_scale", 1.0))
    if grayscale or prof.get("mode") == "grayscale":
        sat_scale = 0.0
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    r = luma + (r - luma) * sat_scale
    g = luma + (g - luma) * sat_scale
    b = luma + (b - luma) * sat_scale

    lo = max(0, min(200, int(sim.get("black_floor", 30))))
    hi = max(lo + 10, min(255, int(sim.get("white_ceiling", 234))))
    span = hi - lo
    sr = int(round(lo + (max(0.0, min(255.0, r)) / 255.0) * span))
    sg = int(round(lo + (max(0.0, min(255.0, g)) / 255.0) * span))
    sb = int(round(lo + (max(0.0, min(255.0, b)) / 255.0) * span))
    return f"#{sr:02x}{sg:02x}{sb:02x}"


def get_display_color_palette(profile_id="none", *, grayscale=False, custom_profile=None):
    """Возвращает адаптивную палитру цветов и метаданные диалога выбора цвета для текущего экрана ридера."""
    pid = str(profile_id or "none").strip()
    eff_id = pid if (pid and pid != "none") else ("eink_bw" if grayscale else "none")
    prof = resolve_image_display_profile(eff_id, custom_profile=custom_profile)
    mode = "grayscale" if (grayscale or prof.get("mode") == "grayscale") else prof.get("mode", "original")
    sim = prof.get("simulate") or {}

    if mode == "grayscale":
        levels = max(2, min(256, int(sim.get("grayscale_levels") or 16)))
        swatches = tuple(
            "#" + f"{int(round(i * 255.0 / (levels - 1))):02x}" * 3
            for i in range(levels)
        )
        return {
            "mode": "grayscale",
            "profile_id": eff_id,
            "quick_colors": list(EINK_BW_QUICK_COLORS),
            "swatches": list(swatches),
            "paper_bg": sim.get("paper_bg", "#ECEAE2"),
            "paper_text": sim.get("paper_text", "#242422"),
            "allow_custom_dialog": False,
            "monochrome_note_bg": True,
            "gray_levels": levels,
            "color_bits": None,
        }

    if mode == "color":
        raw_list = _EINK_COLOR_RAW_SWATCHES + (_GALLERY3_EXTRA_SWATCHES if eff_id == "eink_gallery3" else ())
        swatches = []
        seen = set()
        for raw_hex in raw_list:
            q_hex = quantize_hex_for_display_profile(raw_hex, eff_id, custom_profile=custom_profile)
            if q_hex not in seen:
                seen.add(q_hex)
                swatches.append(q_hex)
        quick = list(_GALLERY3_QUICK_COLORS if eff_id == "eink_gallery3" else _KALEIDO3_QUICK_COLORS)
        return {
            "mode": "color_eink",
            "profile_id": eff_id,
            "quick_colors": quick,
            "swatches": swatches,
            "paper_bg": sim.get("paper_bg", "#D8D7D2"),
            "paper_text": sim.get("paper_text", "#2A2A28"),
            "allow_custom_dialog": True,
            "monochrome_note_bg": False,
            "gray_levels": None,
            "color_bits": sim.get("color_bits_per_channel"),
        }

    return {
        "mode": "full",
        "profile_id": "none",
        "quick_colors": list(DEFAULT_COLOR_QUICK_COLORS),
        "swatches": [],
        "paper_bg": "#FDFBF7",
        "paper_text": "#1E1E1E",
        "allow_custom_dialog": True,
        "monochrome_note_bg": False,
        "gray_levels": None,
        "color_bits": None,
    }


def optimize_fb2_root_binaries(
    root,
    profile_id="none",
    *,
    jpeg_quality=95,
    custom_profile=None,
    fast_encode=False,
):
    """Оптимизирует растровые <binary> напрямую в уже распарсенном XML-дереве; возвращает True при изменениях."""
    if root is None or not HAS_PIL:
        return False
    prof = resolve_image_display_profile(profile_id, custom_profile=custom_profile)
    if not prof.get("optimize") or prof.get("mode") == "original":
        return False

    from core.fb2.xml_io import _local_tag

    changed = False
    for child in root:
        if _local_tag(child) != "binary":
            continue
        mime = (child.attrib.get("content-type") or "image/jpeg").strip()
        if not mime.lower().startswith("image/") or "svg" in mime.lower():
            continue
        raw_b64 = "".join(child.itertext()).strip()
        if not raw_b64:
            continue
        try:
            raw_bytes = base64.b64decode(raw_b64)
            opt_bytes, opt_mime = optimize_image_bytes(
                raw_bytes,
                mime=mime,
                profile_id=profile_id,
                jpeg_quality=jpeg_quality,
                custom_profile=custom_profile,
                fast_encode=fast_encode,
            )
            if opt_bytes and (opt_bytes != raw_bytes or opt_mime != mime):
                child.text = base64.b64encode(opt_bytes).decode("ascii")
                child.set("content-type", opt_mime)
                changed = True
        except Exception as e:
            logger.debug("Пропущена оптимизация <binary id=%s>: %s", child.attrib.get("id", ""), e)
    return changed


def optimize_fb2_binaries_for_profile(
    xml_bytes,
    profile_id="none",
    *,
    jpeg_quality=95,
    custom_profile=None,
    fast_encode=False,
):
    """
    Оптимизирует все растровые теги <binary> (обложку и иллюстрации) внутри временного FB2 XML
    под выбранный профиль экрана ридера, не затрагивая исходный файл на диске.
    """
    if not xml_bytes or not HAS_PIL:
        return xml_bytes
    prof = resolve_image_display_profile(profile_id, custom_profile=custom_profile)
    if not prof.get("optimize") or prof.get("mode") == "original":
        return xml_bytes

    from core.fb2.xml_io import _parse_fb2_root

    root = _parse_fb2_root(xml_bytes)
    if root is None:
        return xml_bytes

    changed = optimize_fb2_root_binaries(
        root,
        profile_id=profile_id,
        jpeg_quality=jpeg_quality,
        custom_profile=custom_profile,
        fast_encode=fast_encode,
    )
    if not changed:
        return xml_bytes
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)

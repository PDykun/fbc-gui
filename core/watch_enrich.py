"""Предконвертационная подготовка книг для Watch Folder: Auto-Repair, Auto-Enrich и фолбэк Cover Studio."""

from difflib import SequenceMatcher
import re

from core.cover_studio import CoverMetadata, CoverSpec, render_cover_bytes
from core.fb2_processor import (
    extract_cover_from_fb2,
    normalize_isbn,
    parse_metadata,
    repair_and_optimize_fb2,
    save_book_changes_to_source,
)
from core.logger import get_logger
from core.metadata_lookup import (
    fetch_candidate_covers,
    fit_cover_bytes_to_target,
    search_book_metadata,
)

logger = get_logger("watch_folder")

WATCH_ENRICH_MODES = ("off", "cover_only", "empty_only")
WATCH_ENRICH_CONFIDENCE_PRESETS = {
    "strict": 0.92,
    "balanced": 0.88,
    "relaxed": 0.80,
}
_TITLE_NOISE_RE = re.compile(r"(?:\(|\[)\s*(?:си|samizdat|самиздат|черновик)\s*(?:\)|\])", re.IGNORECASE)


def _norm_match_text(text, *, strip_noise=False):
    raw = str(text or "")
    if strip_noise:
        raw = _TITLE_NOISE_RE.sub("", raw)
    cleaned = re.sub(r"[^0-9a-zа-яё]+", " ", raw.lower().replace("ё", "е"))
    return re.sub(r"\s+", " ", cleaned).strip()


def match_best_enrich_candidate(candidates, meta, min_confidence=0.88):
    """Выбирает наиболее достоверного кандидата для фонового Auto-Enrich с жёсткой проверкой автора."""
    if not candidates:
        return None, 0.0

    meta = meta or {}
    q_isbn = normalize_isbn(meta.get("isbn") or "")
    q_title = _norm_match_text(meta.get("title") or "", strip_noise=True)
    q_last = _norm_match_text(meta.get("last") or "")
    q_series = _norm_match_text(meta.get("series") or "")

    best_cand = None
    best_score = 0.0
    max_seen = 0.0

    for cand in candidates:
        c_isbn = normalize_isbn(getattr(cand, "isbn", "") or "")
        if q_isbn and c_isbn and q_isbn == c_isbn:
            return cand, 1.0

        c_title = _norm_match_text(getattr(cand, "title", "") or "", strip_noise=True)
        c_last = _norm_match_text(getattr(cand, "last", "") or "")
        c_series = _norm_match_text(getattr(cand, "series", "") or "")

        if not c_title or not q_title:
            continue

        title_sim = SequenceMatcher(None, q_title, c_title).ratio()
        if q_title == c_title:
            title_sim = 1.0

        if q_last and c_last:
            author_sim = SequenceMatcher(None, q_last, c_last).ratio()
            # Жёсткий фильтр: не подставляем книгу другого автора даже при похожем названии
            if author_sim < 0.75:
                continue
        elif q_last and not c_last:
            author_sim = 0.50
        else:
            author_sim = 0.85

        series_bonus = 0.06 if (q_series and c_series and q_series == c_series) else 0.0
        weighted = min(1.0, 0.60 * title_sim + 0.36 * author_sim + series_bonus)
        cand_score = round(weighted, 4)
        max_seen = max(max_seen, cand_score)

        if cand_score >= float(min_confidence) and cand_score > best_score:
            best_score = cand_score
            best_cand = cand

    return best_cand, (best_score if best_cand is not None else max_seen)


def _needs_enrichment(meta, cover_bytes, mode):
    if mode == "cover_only":
        return not cover_bytes
    if mode == "empty_only":
        if not cover_bytes:
            return True
        for key in ("series", "annotation", "publisher", "isbn", "translator_last"):
            if not str(meta.get(key) or "").strip():
                return True
        if not (meta.get("genres") or []):
            return True
    return False


def _merge_empty_meta_fields(meta, candidate):
    """Заполняет только пустые поля в meta из candidate; возвращает True, если что-то изменилось."""
    patch = candidate.to_meta_patch() if hasattr(candidate, "to_meta_patch") else {}
    changed = False
    for key in (
        "series",
        "num",
        "lang",
        "annotation",
        "translator_first",
        "translator_last",
        "translator_middle",
        "publisher",
        "isbn",
    ):
        new_val = str(patch.get(key) or "").strip()
        if new_val and not str(meta.get(key) or "").strip():
            meta[key] = new_val
            if key == "annotation":
                meta["annotation_has_rich_xml"] = False
            changed = True

    new_genres = list(patch.get("genres") or [])
    if new_genres and not (meta.get("genres") or []):
        meta["genres"] = new_genres
        changed = True
    return changed


def prepare_watch_book_item(
    item_data,
    xml_bytes,
    rule,
    base_app_settings=None,
    *,
    fonts_dir=None,
    enrich_cache=None,
    cancel_event=None,
    normalize_rule_fn=None,
    search_metadata_fn=None,
    fetch_covers_fn=None,
):
    """Выполняет предконвертационную подготовку книги в Watch Folder: Auto-Repair, Auto-Enrich и Cover Studio."""
    stats = {
        "repaired": False,
        "enriched": False,
        "cover_generated": False,
        "matched_score": 0.0,
        "written_back": False,
    }
    if normalize_rule_fn is None:
        from core.watch_folder import normalize_watch_rule as normalize_rule_fn
    if search_metadata_fn is None:
        search_metadata_fn = search_book_metadata
    if fetch_covers_fn is None:
        fetch_covers_fn = fetch_candidate_covers

    norm_rule = normalize_rule_fn(rule)
    settings = base_app_settings or {}
    meta = item_data.setdefault("meta", {})

    # 1. Auto-Repair повреждённого FB2 во временной копии
    if norm_rule["auto_repair"] and xml_bytes:
        try:
            repaired_xml, rep_stats = repair_and_optimize_fb2(xml_bytes)
            if (
                rep_stats.get("xml_fixed")
                or rep_stats.get("removed_binaries", 0) > 0
                or rep_stats.get("optimized_images", 0) > 0
            ):
                xml_bytes = repaired_xml
                item_data["xml"] = repaired_xml
                stats["repaired"] = True
                # Обновляем метаданные и обложку из починенного XML, если ранее не распарсились
                if not (meta.get("title") or "").strip():
                    re_meta = parse_metadata(repaired_xml)
                    for k, v in re_meta.items():
                        if v and not meta.get(k):
                            meta[k] = v
                if not item_data.get("cover_bytes"):
                    cb, cm = extract_cover_from_fb2(repaired_xml)
                    if cb:
                        item_data["cover_bytes"] = cb
                        item_data["cover_mime"] = cm
        except Exception as e:
            logger.warning("Watch Folder Auto-Repair пропущен для %s: %s", item_data.get("display_name", ""), e)

    # 2. Auto-Enrich онлайн-метаданных и обложек с порогом совпадения и кэшем сессии
    enrich_mode = norm_rule["auto_enrich_mode"]
    if enrich_mode != "off" and _needs_enrichment(meta, item_data.get("cover_bytes"), enrich_mode):
        q_title = str(meta.get("title") or "").strip()
        q_author = " ".join(p for p in (meta.get("first") or "", meta.get("last") or "") if p.strip()).strip()
        q_isbn = str(meta.get("isbn") or "").strip()

        if q_title or q_isbn:
            cache_key = (
                _norm_match_text(q_author),
                _norm_match_text(q_title, strip_noise=True),
                normalize_isbn(q_isbn),
                tuple(norm_rule["enrich_providers"]),
            )
            lookup_res = None
            if isinstance(enrich_cache, dict) and cache_key in enrich_cache:
                lookup_res = enrich_cache[cache_key]
            else:
                try:
                    lookup_res = search_metadata_fn(
                        title=q_title,
                        author=q_author,
                        isbn=q_isbn,
                        enabled_providers=norm_rule["enrich_providers"],
                        google_books_api_key=settings.get("google_books_api_key", ""),
                        opds_url=settings.get("opds_url", ""),
                        opds_username=settings.get("opds_username", ""),
                        opds_password=settings.get("opds_password", ""),
                        limit_per_provider=4,
                        min_score=0.25,
                        timeout=norm_rule["enrich_timeout_sec"],
                        cancel_event=cancel_event,
                    )
                    if isinstance(enrich_cache, dict):
                        enrich_cache[cache_key] = lookup_res
                except Exception as e:
                    logger.warning("Watch Folder Auto-Enrich ошибка сети для '%s': %s", q_title, e)

            if lookup_res is not None and lookup_res.candidates:
                best_cand, score = match_best_enrich_candidate(
                    lookup_res.candidates,
                    meta,
                    min_confidence=norm_rule["enrich_min_confidence"],
                )
                stats["matched_score"] = score
                if best_cand is not None:
                    changed_any = False
                    if enrich_mode == "empty_only":
                        changed_any = _merge_empty_meta_fields(meta, best_cand)
                    if not item_data.get("cover_bytes") and getattr(best_cand, "cover_urls", None):
                        try:
                            covers = fetch_covers_fn(
                                [best_cand],
                                max_covers=1,
                                timeout=norm_rule["enrich_timeout_sec"],
                                opds_url=settings.get("opds_url", ""),
                                opds_username=settings.get("opds_username", ""),
                                opds_password=settings.get("opds_password", ""),
                                cancel_event=cancel_event,
                            )
                            if covers:
                                fitted, mime = fit_cover_bytes_to_target(
                                    covers[0]["bytes"], covers[0].get("mime", "image/jpeg")
                                )
                                item_data["cover_bytes"] = fitted
                                item_data["cover_mime"] = mime
                                item_data["cover_modified"] = True
                                changed_any = True
                        except Exception as e:
                            logger.debug("Watch Folder не удалось скачать обложку для '%s': %s", q_title, e)
                    if changed_any:
                        stats["enriched"] = True

    # 3. Фолбэк Cover Studio, если обложка всё ещё отсутствует
    if norm_rule["fallback_cover_enabled"] and not item_data.get("cover_bytes"):
        try:
            cover_meta = CoverMetadata.from_book_data(item_data)
            cover_spec = CoverSpec(
                template_id=norm_rule["fallback_cover_template"],
                palette_id="auto_series" if norm_rule["fallback_cover_series_color"] else "eink_paper",
            )
            item_data["cover_bytes"] = render_cover_bytes(cover_meta, cover_spec, fonts_dir=fonts_dir)
            item_data["cover_mime"] = "image/jpeg"
            item_data["cover_modified"] = True
            stats["cover_generated"] = True
        except Exception as e:
            logger.warning("Watch Folder Cover Studio фолбэк пропущен для %s: %s", item_data.get("display_name", ""), e)

    # 4. Опциональное атомарное сохранение в исходный файл
    if norm_rule["write_back_source"] and (
        stats["repaired"] or stats["enriched"] or stats["cover_generated"]
    ):
        try:
            save_book_changes_to_source(item_data)
            stats["written_back"] = True
        except Exception as e:
            logger.warning("Watch Folder не удалось записать правки в исходник %s: %s", item_data.get("path", ""), e)

    return stats

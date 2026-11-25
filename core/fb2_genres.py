"""Канонический справочник жанров FictionBook 2.1 и вспомогательные функции нормализации."""

FB2_GENRE_GROUPS = (
    ("sf", (
        "sf_history", "sf_action", "sf_epic", "sf_heroic", "sf_detective",
        "sf_cyberpunk", "sf_space", "sf_social", "sf_horror", "sf_humor",
        "sf_fantasy", "sf",
    )),
    ("detective", (
        "det_classic", "det_police", "det_action", "det_irony", "det_history",
        "det_espionage", "det_crime", "det_political", "det_maniac",
        "det_hard", "thriller", "detective",
    )),
    ("prose", (
        "prose_classic", "prose_history", "prose_contemporary",
        "prose_counter", "prose_rus_classic", "prose_su_classics", "prose",
    )),
    ("love", (
        "love_contemporary", "love_history", "love_detective", "love_short",
        "love_erotica", "love",
    )),
    ("adventure", (
        "adv_western", "adv_history", "adv_indian", "adv_maritime",
        "adv_geo", "adv_animal", "adventure",
    )),
    ("children", (
        "child_tale", "child_verse", "child_prose", "child_sf",
        "child_det", "child_adv", "child_education", "children",
    )),
    ("poetry", (
        "poetry", "dramaturgy",
    )),
    ("antique", (
        "antique_ant", "antique_european", "antique_russian",
        "antique_east", "antique_myths", "antique",
    )),
    ("science", (
        "sci_history", "sci_psychology", "sci_culture", "sci_religion",
        "sci_philosophy", "sci_politics", "sci_business", "sci_juris",
        "sci_linguistic", "sci_medicine", "sci_phys", "sci_math",
        "sci_chem", "sci_biology", "sci_tech", "science",
    )),
    ("computers", (
        "comp_www", "comp_programming", "comp_hard", "comp_soft",
        "comp_db", "comp_osnet", "computers",
    )),
    ("reference", (
        "ref_encyc", "ref_dict", "ref_ref", "ref_guide", "reference",
    )),
    ("nonfiction", (
        "nonf_biography", "nonf_publicism", "nonf_criticism",
        "design", "nonfiction",
    )),
    ("religion", (
        "religion_rel", "religion_esoterics", "religion_self", "religion",
    )),
    ("humor", (
        "humor_anecdote", "humor_prose", "humor_verse", "humor",
    )),
    ("home", (
        "home_cooking", "home_pets", "home_crafts", "home_entertain",
        "home_health", "home_garden", "home_diy", "home_sport",
        "home_sex", "home",
    )),
    ("other", (
        "other",
    )),
)

KNOWN_GENRE_CODES = frozenset(
    code for _, codes in FB2_GENRE_GROUPS for code in codes
)

COMMON_LANG_CODES = (
    "ru", "en", "uk", "be", "de", "fr", "es", "it", "pl", "zh", "ja",
)


def normalize_genre_code(raw):
    """Нормализует одиночный код жанра FB2."""
    if raw is None:
        return ""
    return str(raw).strip().lower()


def normalize_genre_list(genres):
    """Возвращает упорядоченный список уникальных непустых кодов жанров."""
    if genres is None:
        return []
    if isinstance(genres, str):
        items = genres.split(",")
    else:
        items = genres
    out = []
    seen = set()
    for item in items:
        code = normalize_genre_code(item)
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def get_genre_label(code, tr_fn):
    """Возвращает локализованное название канонического жанра или сам код для нестандартного."""
    norm = normalize_genre_code(code)
    if not norm:
        return ""
    if norm in KNOWN_GENRE_CODES:
        key = f"genres.{norm}"
        label = tr_fn(key)
        if label and label != key:
            return label
    return norm


def get_genre_group_label(group_id, tr_fn):
    """Возвращает локализованное название группы жанров."""
    key = f"genre_groups.{group_id}"
    label = tr_fn(key)
    return label if (label and label != key) else group_id

"""Локальная библиотека книг в формате INPX с быстрым SQLite FTS5 кэш-индексом."""

import os
import re
import sqlite3
import zipfile

from core.fb2_processor import extract_cover_from_fb2, load_book_xml, parse_metadata
from core.logger import get_logger

logger = get_logger("inpx_library")

INPX_CACHE_SCHEMA_VERSION = "4"
MAX_INPX_ENTRY_BYTES = 128 * 1024 * 1024  # 128 МБ лимит на один .inp-файл (защита от zip-bomb)
MAX_INPX_SEARCH_LIMIT = 500
MAX_INPX_LANGUAGES = 100

# Каноническая схема MyHomeLib / Flibusta / Lib.rus.ec (14 колонок без structure.info)
DEFAULT_INP_FIELDS = (
    "AUTHOR",
    "GENRE",
    "TITLE",
    "SERIES",
    "SERNO",
    "FILE",
    "SIZE",
    "LIBID",
    "DEL",
    "EXT",
    "DATE",
    "LANG",
    "LIBRATE",
    "KEYWORDS",
)

_FTS_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
_LANG_CODE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,4})?$")


def _split_inpx_authors(raw_author):
    """Разбирает поле AUTHOR формата 'Фамилия,Имя,Отчество:Фамилия2,Имя2:' в список уникальных имён."""
    if not raw_author:
        return []
    authors = []
    seen = set()
    for chunk in str(raw_author).split(":"):
        parts = [p.strip() for p in chunk.split(",") if p.strip()]
        if parts:
            name = " ".join(parts)
            low = name.lower()
            if low not in seen:
                seen.add(low)
                authors.append(name)
    return authors


def _format_inpx_authors(raw_author):
    """Преобразует формат INPX 'Фамилия,Имя,Отчество:Фамилия2,Имя2:' в читаемую строку."""
    return ", ".join(_split_inpx_authors(raw_author))


def _split_inpx_genres(raw_genres):
    """Разбирает 'sf_fantasy:prose:' в список уникальных кодов жанров в нижнем регистре."""
    if not raw_genres:
        return []
    out = []
    seen = set()
    for g in str(raw_genres).split(":"):
        code = g.strip().lower()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _format_inpx_genres(raw_genres):
    """Преобразует 'sf_fantasy:prose:' в 'sf_fantasy, prose'."""
    return ", ".join(_split_inpx_genres(raw_genres))


def _parse_serno_int(serno_str):
    s = str(serno_str or "").strip()
    if s.isdigit():
        return int(s)
    m = re.match(r"^(\d+)", s)
    return int(m.group(1)) if m else 999999


def _parse_int_clamped(val_str, min_val=0, max_val=None):
    s = str(val_str or "").strip()
    try:
        n = int(s)
    except (TypeError, ValueError):
        return min_val
    if n < min_val:
        return min_val
    if max_val is not None and n > max_val:
        return max_val
    return n


def _parse_size_int(size_str):
    return _parse_int_clamped(size_str, min_val=0)


def _read_zip_entry_text(zf, info, max_bytes=MAX_INPX_ENTRY_BYTES):
    if info.file_size > max_bytes:
        raise ValueError(f"INPX entry {info.filename} exceeds size limit ({max_bytes} bytes)")
    with zf.open(info, "r") as fh:
        data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"INPX entry {info.filename} exceeds decompressed size limit")
    return data.decode("utf-8", errors="replace")


def _parse_structure_info(zf):
    for info in zf.infolist():
        if info.filename.lower() == "structure.info":
            text = _read_zip_entry_text(zf, info, max_bytes=65536).strip()
            if text:
                sep = ";" if ";" in text else ","
                cols = [c.strip().upper() for c in text.split(sep) if c.strip()]
                if cols:
                    return tuple(cols)
    return DEFAULT_INP_FIELDS


def _parse_collection_and_version(zf):
    collection_name = ""
    version_str = ""
    for info in zf.infolist():
        low = info.filename.lower()
        if low == "collection.info":
            text = _read_zip_entry_text(zf, info, max_bytes=65536)
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if lines:
                collection_name = lines[0]
        elif low == "version.info":
            text = _read_zip_entry_text(zf, info, max_bytes=4096).strip()
            if text:
                version_str = text.splitlines()[0].strip()
    return collection_name, version_str


def _is_within_dir(root_real, candidate_path):
    """Проверяет, что реальный путь candidate_path находится внутри root_real (защита от path traversal)."""
    try:
        cand_real = os.path.realpath(candidate_path)
        return os.path.commonpath([root_real, cand_real]) == root_real
    except (ValueError, OSError):
        return False


def _find_zip_entry_name(zip_path, file_stem, ext):
    """Возвращает точное имя записи внутри ZIP-архива (<file>.<ext> или совпадение без учёта регистра)."""
    target = f"{file_stem}.{ext}" if ext else file_stem
    target_low = target.lower()
    stem_low = file_stem.lower()
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if target in names:
                return target
            for name in names:
                base = os.path.basename(name.replace("\\", "/"))
                low = base.lower()
                if low == target_low or (ext and low == f"{stem_low}.{ext.lower()}"):
                    return name
    except (OSError, zipfile.BadZipFile) as e:
        logger.debug("Не удалось прочитать ZIP-архив библиотеки %s: %s", zip_path, e)
    return None


def resolve_book_source(inpx_path, book_row):
    """
    Находит физический путь к книге из записи INPX:
    возвращает dict {'path', 'archive_entry', 'display_name'} или None, если файл/архив не найден.
    """
    if not inpx_path or not isinstance(book_row, dict):
        return None
    inpx_dir = os.path.dirname(os.path.abspath(inpx_path))
    if not os.path.isdir(inpx_dir):
        return None
    root_real = os.path.realpath(inpx_dir)

    file_stem = str(book_row.get("file") or "").strip()
    ext = str(book_row.get("ext") or "fb2").strip().lstrip(".") or "fb2"
    folder = str(book_row.get("folder") or "").strip().replace("\\", "/")
    inp_name = str(book_row.get("inp_name") or "").strip()
    if not file_stem:
        return None

    # 1. Кандидаты ZIP-архивов
    zip_names = []
    if folder:
        f_clean = folder.strip("/")
        if f_clean.lower().endswith(".zip"):
            zip_names.append(f_clean)
        else:
            zip_names.append(f"{f_clean}.zip")
    if inp_name:
        inp_zip = f"{inp_name}.zip"
        if inp_zip not in zip_names:
            zip_names.append(inp_zip)

    search_subdirs = ("", "fb2", "arch", "archives", "books")
    checked_zips = set()
    for zname in zip_names:
        for sub in search_subdirs:
            cand = os.path.join(inpx_dir, sub, zname) if sub else os.path.join(inpx_dir, zname)
            norm = os.path.normcase(os.path.abspath(cand))
            if norm in checked_zips:
                continue
            checked_zips.add(norm)
            if os.path.isfile(cand) and _is_within_dir(root_real, cand):
                entry = _find_zip_entry_name(cand, file_stem, ext)
                if entry:
                    return {
                        "path": cand,
                        "archive_entry": entry,
                        "display_name": f"{os.path.basename(cand)} / {os.path.basename(entry.replace('\\', '/'))}",
                    }

    # 2. Распакованные файлы на диске
    filename = f"{file_stem}.{ext}"
    plain_candidates = []
    if folder and not folder.lower().endswith(".zip"):
        plain_candidates.append(os.path.join(inpx_dir, folder.strip("/"), filename))
    if inp_name:
        plain_candidates.append(os.path.join(inpx_dir, inp_name, filename))
    plain_candidates.append(os.path.join(inpx_dir, filename))
    for sub in ("fb2", "books"):
        plain_candidates.append(os.path.join(inpx_dir, sub, filename))

    for cand in plain_candidates:
        if os.path.isfile(cand) and _is_within_dir(root_real, cand):
            return {
                "path": cand,
                "archive_entry": None,
                "display_name": os.path.basename(cand),
            }

    return None


def load_book_preview_details(inpx_path, book_row):
    """Извлекает аннотацию, обложку и физический путь к файлу/архиву для панели предпросмотра библиотеки."""
    src = resolve_book_source(inpx_path, book_row)
    result = {
        "found": False,
        "path": "",
        "archive_entry": None,
        "archive_size": 0,
        "annotation": "",
        "cover_bytes": None,
        "cover_mime": None,
    }
    if not src:
        return result
    result["found"] = True
    result["path"] = src["path"]
    result["archive_entry"] = src["archive_entry"]
    try:
        result["archive_size"] = os.path.getsize(src["path"])
    except OSError:
        result["archive_size"] = 0

    try:
        xml_bytes = load_book_xml(src["path"], src["archive_entry"])
        if xml_bytes:
            meta = parse_metadata(xml_bytes)
            result["annotation"] = (meta.get("annotation") or "").strip()
            cover_bytes, cover_mime = extract_cover_from_fb2(xml_bytes)
            result["cover_bytes"] = cover_bytes
            result["cover_mime"] = cover_mime
    except Exception as e:
        logger.debug("Не удалось извлечь аннотацию/обложку для %s: %s", src.get("display_name"), e)
    return result


def _has_fts5_support(conn):
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _fts5_probe")
        return True
    except sqlite3.Error:
        return False


def _build_fts_match_expr(query, field="all"):
    tokens = [t for t in _FTS_TOKEN_RE.findall(str(query or "").strip()) if t]
    if not tokens:
        return ""
    col_prefix = ""
    if field in ("author", "title", "series", "genres"):
        col_prefix = f"{field}:"
    parts = [f'{col_prefix}"{tok}"*' for tok in tokens]
    return " AND ".join(parts)


def _prefix_range_clause(col_name, prefix_low, where_list, params_list):
    """Добавляет быструю Unicode-безопасную фильтрацию по начальной букве или '#' (цифры/символы)."""
    p = str(prefix_low or "").strip().lower()
    if not p or p == "*":
        return
    if p == "#":
        where_list.append(f"({col_name} < 'a' OR ({col_name} > 'z' AND {col_name} < 'а'))")
        return
    hi = p[:-1] + chr(ord(p[-1]) + 1)
    where_list.append(f"({col_name} >= ? AND {col_name} < ?)")
    params_list.extend([p, hi])


class InpxLibraryIndex:
    """Управляет SQLite FTS5 кэш-индексом для локального INPX-файла."""

    def __init__(self, db_path):
        self.db_path = os.path.abspath(db_path)
        self._ro_conn = None
        self._ro_stat = None

    def close(self):
        """Закрывает кэшированное read-only соединение SQLite (необходимо перед заменой файла или выходом)."""
        conn = self._ro_conn
        self._ro_conn = None
        self._ro_stat = None
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    def _connect(self, readonly=False):
        if readonly and os.path.isfile(self.db_path):
            try:
                st = os.stat(self.db_path)
                sig = (st.st_mtime_ns, st.st_size)
            except OSError:
                sig = None
            if self._ro_conn is not None and self._ro_stat == sig:
                return self._ro_conn
            self.close()
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            # Прогрев read-only соединения: memory-mapped I/O (128 МБ) и кэш страниц в ОЗУ (16 МБ)
            for pragma in (
                "PRAGMA query_only = ON",
                "PRAGMA temp_store = MEMORY",
                "PRAGMA cache_size = -16000",
                "PRAGMA mmap_size = 134217728",
            ):
                try:
                    conn.execute(pragma)
                except sqlite3.Error:
                    pass
            self._ro_conn = conn
            self._ro_stat = sig
            return conn
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def get_meta(self):
        if not os.path.isfile(self.db_path):
            return {}
        try:
            with self._connect(readonly=True) as conn:
                rows = conn.execute("SELECT key, value FROM meta").fetchall()
                return {r["key"]: r["value"] for r in rows}
        except sqlite3.Error:
            return {}

    def needs_reindex(self, inpx_path):
        if not inpx_path or not os.path.isfile(inpx_path):
            return False
        meta = self.get_meta()
        if not meta or meta.get("schema_version") != INPX_CACHE_SCHEMA_VERSION:
            return True
        if os.path.abspath(meta.get("inpx_path", "")) != os.path.abspath(inpx_path):
            return True
        try:
            st = os.stat(inpx_path)
        except OSError:
            return True
        return (
            meta.get("inpx_mtime_ns") != str(st.st_mtime_ns)
            or meta.get("inpx_size") != str(st.st_size)
        )

    def build_index(self, inpx_path, progress_callback=None, cancel_event=None):
        """Парсит INPX в изолированный временный SQLite-файл с предвычисленными сводками и атомарно подменяет кэш."""
        if not inpx_path or not os.path.isfile(inpx_path):
            raise FileNotFoundError(f"INPX file not found: {inpx_path}")

        abs_inpx = os.path.abspath(inpx_path)
        st = os.stat(abs_inpx)
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        tmp_db = f"{self.db_path}.tmp.{os.getpid()}"
        if os.path.exists(tmp_db):
            try:
                os.remove(tmp_db)
            except OSError:
                pass

        total_books = 0
        collection_name = ""
        version_str = ""
        use_fts5 = False

        try:
            with zipfile.ZipFile(abs_inpx, "r") as zf:
                fields = _parse_structure_info(zf)
                field_idx = {name: i for i, name in enumerate(fields)}
                collection_name, version_str = _parse_collection_and_version(zf)
                if not collection_name:
                    collection_name = os.path.splitext(os.path.basename(abs_inpx))[0]

                inp_entries = [
                    info for info in zf.infolist()
                    if not info.is_dir() and info.filename.lower().endswith(".inp")
                ]
                total_inps = len(inp_entries)

                conn = sqlite3.connect(tmp_db)
                try:
                    conn.execute("PRAGMA synchronous = OFF")
                    conn.execute("PRAGMA journal_mode = OFF")
                    conn.execute("PRAGMA temp_store = MEMORY")
                    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
                    conn.execute(
                        """
                        CREATE TABLE books (
                            id INTEGER PRIMARY KEY,
                            author TEXT NOT NULL,
                            author_low TEXT NOT NULL,
                            title TEXT NOT NULL,
                            title_low TEXT NOT NULL,
                            series TEXT NOT NULL,
                            series_low TEXT NOT NULL,
                            serno TEXT NOT NULL,
                            serno_num INTEGER NOT NULL,
                            genres TEXT NOT NULL,
                            lang TEXT NOT NULL,
                            size INTEGER NOT NULL,
                            librate INTEGER NOT NULL,
                            file TEXT NOT NULL,
                            ext TEXT NOT NULL,
                            folder TEXT NOT NULL,
                            inp_name TEXT NOT NULL,
                            deleted INTEGER NOT NULL,
                            date TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE authors (
                            id INTEGER PRIMARY KEY,
                            name TEXT NOT NULL,
                            name_low TEXT NOT NULL UNIQUE,
                            count_active INTEGER NOT NULL,
                            count_all INTEGER NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE series_summary (
                            series_low TEXT PRIMARY KEY,
                            name TEXT NOT NULL,
                            count_active INTEGER NOT NULL,
                            count_all INTEGER NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE genre_summary (
                            genre TEXT PRIMARY KEY,
                            count_active INTEGER NOT NULL,
                            count_all INTEGER NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE lang_summary (
                            lang TEXT PRIMARY KEY,
                            count_active INTEGER NOT NULL,
                            count_all INTEGER NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE book_authors (
                            book_id INTEGER NOT NULL,
                            author_id INTEGER NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE book_genres (
                            book_id INTEGER NOT NULL,
                            genre TEXT NOT NULL
                        )
                        """
                    )

                    idx_author = field_idx.get("AUTHOR")
                    idx_genre = field_idx.get("GENRE")
                    idx_title = field_idx.get("TITLE")
                    idx_series = field_idx.get("SERIES")
                    idx_serno = field_idx.get("SERNO")
                    idx_file = field_idx.get("FILE")
                    idx_size = field_idx.get("SIZE")
                    idx_del = field_idx.get("DEL")
                    idx_ext = field_idx.get("EXT")
                    idx_date = field_idx.get("DATE")
                    idx_folder = field_idx.get("FOLDER")
                    idx_lang = field_idx.get("LANG")
                    idx_librate = field_idx.get("LIBRATE")

                    def _get_col(parts, col_idx):
                        if col_idx is None or col_idx >= len(parts):
                            return ""
                        return parts[col_idx]

                    insert_book_sql = (
                        "INSERT INTO books (id, author, author_low, title, title_low, series, series_low, "
                        "serno, serno_num, genres, lang, size, librate, file, ext, folder, inp_name, deleted, date) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                    )
                    insert_ba_sql = "INSERT INTO book_authors (book_id, author_id) VALUES (?, ?)"
                    insert_bg_sql = "INSERT INTO book_genres (book_id, genre) VALUES (?, ?)"

                    # Предвычисляемые счётчики в памяти (для мгновенного отклика левой панели без тяжёлых JOIN)
                    author_map = {}  # name_low -> [author_id, display_name, count_active, count_all]
                    series_map = {}  # series_low -> [display_name, count_active, count_all]
                    genre_map = {}   # genre_code -> [count_active, count_all]
                    lang_map = {}    # lang_code -> [count_active, count_all]
                    next_author_id = 1
                    book_batch = []
                    ba_batch = []
                    bg_batch = []

                    def _flush_batches():
                        if book_batch:
                            conn.executemany(insert_book_sql, book_batch)
                            book_batch.clear()
                        if ba_batch:
                            conn.executemany(insert_ba_sql, ba_batch)
                            ba_batch.clear()
                        if bg_batch:
                            conn.executemany(insert_bg_sql, bg_batch)
                            bg_batch.clear()

                    for inp_pos, info in enumerate(inp_entries, start=1):
                        if cancel_event is not None and cancel_event.is_set():
                            raise InterruptedError("INPX indexing cancelled")
                        inp_stem = os.path.splitext(os.path.basename(info.filename.replace("\\", "/")))[0]
                        if progress_callback:
                            progress_callback(inp_pos, max(1, total_inps), info.filename)

                        text = _read_zip_entry_text(zf, info)
                        for raw_line in text.splitlines():
                            if not raw_line:
                                continue
                            parts = raw_line.split("\x04")
                            ext = (_get_col(parts, idx_ext) or "fb2").strip().lower().lstrip(".")
                            if ext != "fb2":
                                continue
                            file_stem = _get_col(parts, idx_file).strip()
                            if not file_stem:
                                continue

                            total_books += 1
                            book_id = total_books

                            authors_list = _split_inpx_authors(_get_col(parts, idx_author))
                            author_str = ", ".join(authors_list)
                            title = _get_col(parts, idx_title).strip()
                            series = _get_col(parts, idx_series).strip()
                            series_low = series.lower()
                            serno = _get_col(parts, idx_serno).strip()
                            serno_num = _parse_serno_int(serno)
                            genres_list = _split_inpx_genres(_get_col(parts, idx_genre))
                            genres_str = ", ".join(genres_list)
                            raw_lang = _get_col(parts, idx_lang).strip().lower()
                            lang = raw_lang if _LANG_CODE_RE.match(raw_lang) else ""
                            size_b = _parse_size_int(_get_col(parts, idx_size))
                            librate = _parse_int_clamped(_get_col(parts, idx_librate), min_val=0, max_val=5)
                            folder = _get_col(parts, idx_folder).strip()
                            deleted = 1 if _get_col(parts, idx_del).strip() == "1" else 0
                            is_active = 0 if deleted else 1
                            date_str = _get_col(parts, idx_date).strip()

                            book_batch.append((
                                book_id, author_str, author_str.lower(), title, title.lower(),
                                series, series_low, serno, serno_num, genres_str, lang,
                                size_b, librate, file_stem, ext, folder, inp_stem, deleted, date_str,
                            ))

                            for a_name in authors_list:
                                a_low = a_name.lower()
                                entry = author_map.get(a_low)
                                if entry is None:
                                    a_id = next_author_id
                                    next_author_id += 1
                                    author_map[a_low] = [a_id, a_name, is_active, 1]
                                else:
                                    a_id = entry[0]
                                    entry[2] += is_active
                                    entry[3] += 1
                                ba_batch.append((book_id, a_id))

                            if series_low:
                                s_entry = series_map.get(series_low)
                                if s_entry is None:
                                    series_map[series_low] = [series, is_active, 1]
                                else:
                                    s_entry[1] += is_active
                                    s_entry[2] += 1

                            for g_code in genres_list:
                                g_entry = genre_map.get(g_code)
                                if g_entry is None:
                                    genre_map[g_code] = [is_active, 1]
                                else:
                                    g_entry[0] += is_active
                                    g_entry[1] += 1
                                bg_batch.append((book_id, g_code))

                            if lang:
                                l_entry = lang_map.get(lang)
                                if l_entry is None:
                                    lang_map[lang] = [is_active, 1]
                                else:
                                    l_entry[0] += is_active
                                    l_entry[1] += 1

                            if len(book_batch) >= 5000:
                                _flush_batches()

                    _flush_batches()

                    if author_map:
                        conn.executemany(
                            "INSERT INTO authors (id, name, name_low, count_active, count_all) VALUES (?, ?, ?, ?, ?)",
                            [(v[0], v[1], k, v[2], v[3]) for k, v in author_map.items()],
                        )
                    if series_map:
                        conn.executemany(
                            "INSERT INTO series_summary (series_low, name, count_active, count_all) VALUES (?, ?, ?, ?)",
                            [(k, v[0], v[1], v[2]) for k, v in series_map.items()],
                        )
                    if genre_map:
                        conn.executemany(
                            "INSERT INTO genre_summary (genre, count_active, count_all) VALUES (?, ?, ?)",
                            [(k, v[0], v[1]) for k, v in genre_map.items()],
                        )
                    if lang_map:
                        conn.executemany(
                            "INSERT INTO lang_summary (lang, count_active, count_all) VALUES (?, ?, ?)",
                            [(k, v[0], v[1]) for k, v in lang_map.items()],
                        )

                    conn.execute("CREATE INDEX idx_books_series_low ON books(series_low)")
                    conn.execute("CREATE INDEX idx_books_lang_del ON books(deleted, lang)")
                    conn.execute("CREATE INDEX idx_ba_author ON book_authors(author_id, book_id)")
                    conn.execute("CREATE INDEX idx_ba_book ON book_authors(book_id, author_id)")
                    conn.execute("CREATE INDEX idx_bg_genre ON book_genres(genre, book_id)")
                    conn.execute("CREATE INDEX idx_bg_book ON book_genres(book_id, genre)")

                    use_fts5 = _has_fts5_support(conn)
                    if use_fts5:
                        conn.execute(
                            """
                            CREATE VIRTUAL TABLE books_fts USING fts5(
                                author, title, series, genres,
                                content='books', content_rowid='id',
                                tokenize='unicode61 remove_diacritics 2'
                            )
                            """
                        )
                        conn.execute(
                            "INSERT INTO books_fts(rowid, author, title, series, genres) "
                            "SELECT id, author, title, series, genres FROM books"
                        )

                    meta_rows = [
                        ("schema_version", INPX_CACHE_SCHEMA_VERSION),
                        ("inpx_path", abs_inpx),
                        ("inpx_mtime_ns", str(st.st_mtime_ns)),
                        ("inpx_size", str(st.st_size)),
                        ("collection_name", collection_name),
                        ("version", version_str),
                        ("total_books", str(total_books)),
                        ("has_fts5", "1" if use_fts5 else "0"),
                    ]
                    conn.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", meta_rows)
                    conn.execute("ANALYZE")
                    conn.commit()
                finally:
                    conn.close()

            self.close()
            os.replace(tmp_db, self.db_path)
            logger.info(
                "Индекс INPX построен: %s (книг FB2: %d, авторов: %d, серий: %d, FTS5=%s)",
                abs_inpx, total_books, len(author_map), len(series_map), use_fts5,
            )
            return {
                "inpx_path": abs_inpx,
                "collection_name": collection_name,
                "version": version_str,
                "total_books": total_books,
                "has_fts5": use_fts5,
            }
        except Exception:
            if os.path.exists(tmp_db):
                try:
                    os.remove(tmp_db)
                except OSError:
                    pass
            raise

    def list_languages(self, hide_deleted=True, limit=MAX_INPX_LANGUAGES):
        """Возвращает список языков, присутствующих в библиотеке, по убыванию числа книг (мгновенно из lang_summary)."""
        if not os.path.isfile(self.db_path):
            return []
        cnt_col = "count_active" if hide_deleted else "count_all"
        lim = max(1, min(MAX_INPX_LANGUAGES, int(limit or MAX_INPX_LANGUAGES)))
        with self._connect(readonly=True) as conn:
            rows = conn.execute(
                f"SELECT lang FROM lang_summary WHERE {cnt_col} > 0 ORDER BY {cnt_col} DESC, lang LIMIT ?",
                (lim,),
            ).fetchall()
            return [r["lang"] for r in rows]

    def list_authors(self, prefix="", filter_text="", lang="all", hide_deleted=True, limit=1500):
        """Возвращает список уникальных авторов с количеством книг для левой панели."""
        if not os.path.isfile(self.db_path):
            return []
        lang_f = str(lang or "all").strip().lower()
        lim = int(limit or 1500)

        # Быстрый путь без фильтра по языку — прямое чтение по B-tree индексу таблицы authors (< 2 мс)
        if not lang_f or lang_f == "all":
            cnt_col = "count_active" if hide_deleted else "count_all"
            where = [f"{cnt_col} > 0"]
            params = []
            _prefix_range_clause("name_low", prefix, where, params)
            ft = str(filter_text or "").strip().lower()
            if ft:
                where.append("name_low LIKE ?")
                params.append(f"%{ft}%")
            sql = (
                f"SELECT id, name, {cnt_col} AS cnt FROM authors "
                f"WHERE {' AND '.join(where)} "
                f"ORDER BY name_low LIMIT ?"
            )
            with self._connect(readonly=True) as conn:
                rows = conn.execute(sql, params + [lim]).fetchall()
                return [{"id": r["id"], "name": r["name"], "count": int(r["cnt"])} for r in rows]

        # Путь с фильтром по языку — опирается на индексы authors(name_low), book_authors(author_id, book_id) и books(id)
        where_a = []
        params = []
        _prefix_range_clause("a.name_low", prefix, where_a, params)
        ft = str(filter_text or "").strip().lower()
        if ft:
            where_a.append("a.name_low LIKE ?")
            params.append(f"%{ft}%")
        del_cond = "AND b.deleted = 0" if hide_deleted else ""
        where_a_sql = ("WHERE " + " AND ".join(where_a)) if where_a else ""
        sql = (
            f"SELECT a.id, a.name, COUNT(b.id) AS cnt "
            f"FROM authors a "
            f"CROSS JOIN book_authors ba ON ba.author_id = a.id "
            f"CROSS JOIN books b ON b.id = ba.book_id AND b.lang = ? {del_cond} "
            f"{where_a_sql} "
            f"GROUP BY a.id, a.name "
            f"ORDER BY a.name_low LIMIT ?"
        )
        with self._connect(readonly=True) as conn:
            rows = conn.execute(sql, [lang_f] + params + [lim]).fetchall()
            return [{"id": r["id"], "name": r["name"], "count": int(r["cnt"])} for r in rows]

    def list_series(self, prefix="", filter_text="", lang="all", hide_deleted=True, limit=1500):
        """Возвращает список уникальных серий с количеством книг для левой панели."""
        if not os.path.isfile(self.db_path):
            return []
        lang_f = str(lang or "all").strip().lower()
        lim = int(limit or 1500)

        if not lang_f or lang_f == "all":
            cnt_col = "count_active" if hide_deleted else "count_all"
            where = [f"{cnt_col} > 0"]
            params = []
            _prefix_range_clause("series_low", prefix, where, params)
            ft = str(filter_text or "").strip().lower()
            if ft:
                where.append("series_low LIKE ?")
                params.append(f"%{ft}%")
            sql = (
                f"SELECT name, {cnt_col} AS cnt FROM series_summary "
                f"WHERE {' AND '.join(where)} "
                f"ORDER BY series_low LIMIT ?"
            )
            with self._connect(readonly=True) as conn:
                rows = conn.execute(sql, params + [lim]).fetchall()
                return [{"name": r["name"], "count": int(r["cnt"])} for r in rows]

        where = ["b.series_low != ''", "b.lang = ?"]
        params = [lang_f]
        if hide_deleted:
            where.append("b.deleted = 0")
        _prefix_range_clause("b.series_low", prefix, where, params)
        ft = str(filter_text or "").strip().lower()
        if ft:
            where.append("b.series_low LIKE ?")
            params.append(f"%{ft}%")
        sql = (
            f"SELECT MIN(b.series) AS name, COUNT(*) AS cnt "
            f"FROM books b "
            f"WHERE {' AND '.join(where)} "
            f"GROUP BY b.series_low "
            f"ORDER BY b.series_low LIMIT ?"
        )
        with self._connect(readonly=True) as conn:
            rows = conn.execute(sql, params + [lim]).fetchall()
            return [{"name": r["name"], "count": int(r["cnt"])} for r in rows]

    def list_genres(self, lang="all", hide_deleted=True):
        """Возвращает список жанров с количеством книг."""
        if not os.path.isfile(self.db_path):
            return []
        lang_f = str(lang or "all").strip().lower()
        if not lang_f or lang_f == "all":
            cnt_col = "count_active" if hide_deleted else "count_all"
            with self._connect(readonly=True) as conn:
                rows = conn.execute(
                    f"SELECT genre AS code, {cnt_col} AS cnt FROM genre_summary "
                    f"WHERE {cnt_col} > 0 ORDER BY {cnt_col} DESC, genre"
                ).fetchall()
                return [{"code": r["code"], "count": int(r["cnt"])} for r in rows]

        where = ["b.lang = ?"]
        params = [lang_f]
        if hide_deleted:
            where.append("b.deleted = 0")
        sql = (
            f"SELECT bg.genre AS code, COUNT(bg.book_id) AS cnt "
            f"FROM books b "
            f"JOIN book_genres bg ON bg.book_id = b.id "
            f"WHERE {' AND '.join(where)} "
            f"GROUP BY bg.genre "
            f"ORDER BY cnt DESC, bg.genre"
        )
        with self._connect(readonly=True) as conn:
            rows = conn.execute(sql, params).fetchall()
            return [{"code": r["code"], "count": int(r["cnt"])} for r in rows]

    def get_books_by_author(self, author_id, lang="all", hide_deleted=True, limit=500):
        """Возвращает все книги выбранного автора (включая соавторство)."""
        if not author_id or not os.path.isfile(self.db_path):
            return []
        where = ["ba.author_id = ?"]
        params = [int(author_id)]
        if hide_deleted:
            where.append("b.deleted = 0")
        lang_f = str(lang or "all").strip().lower()
        if lang_f and lang_f != "all":
            where.append("b.lang = ?")
            params.append(lang_f)
        sql = (
            f"SELECT b.* FROM book_authors ba "
            f"JOIN books b ON b.id = ba.book_id "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY b.series_low, b.serno_num, b.title_low "
            f"LIMIT ?"
        )
        with self._connect(readonly=True) as conn:
            rows = conn.execute(sql, params + [int(limit or 500)]).fetchall()
            return [dict(r) for r in rows]

    def get_books_by_series(self, series_name, lang="all", hide_deleted=True, limit=500):
        """Возвращает все книги выбранной серии."""
        ser_low = str(series_name or "").strip().lower()
        if not ser_low or not os.path.isfile(self.db_path):
            return []
        where = ["b.series_low = ?"]
        params = [ser_low]
        if hide_deleted:
            where.append("b.deleted = 0")
        lang_f = str(lang or "all").strip().lower()
        if lang_f and lang_f != "all":
            where.append("b.lang = ?")
            params.append(lang_f)
        sql = (
            f"SELECT b.* FROM books b "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY b.author_low, b.serno_num, b.title_low "
            f"LIMIT ?"
        )
        with self._connect(readonly=True) as conn:
            rows = conn.execute(sql, params + [int(limit or 500)]).fetchall()
            return [dict(r) for r in rows]

    def get_books_by_genre(self, genre_code, lang="all", hide_deleted=True, limit=500):
        """Возвращает книги выбранного жанра."""
        g = str(genre_code or "").strip().lower()
        if not g or not os.path.isfile(self.db_path):
            return {"items": [], "total": 0, "truncated": False}
        lim = max(1, min(MAX_INPX_SEARCH_LIMIT, int(limit or 500)))
        where = ["bg.genre = ?"]
        params = [g]
        if hide_deleted:
            where.append("b.deleted = 0")
        lang_f = str(lang or "all").strip().lower()
        if lang_f and lang_f != "all":
            where.append("b.lang = ?")
            params.append(lang_f)
        where_sql = " AND ".join(where)
        with self._connect(readonly=True) as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM book_genres bg JOIN books b ON b.id = bg.book_id WHERE {where_sql}",
                params,
            ).fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT b.* FROM book_genres bg JOIN books b ON b.id = bg.book_id "
                f"WHERE {where_sql} "
                f"ORDER BY b.author_low, b.series_low, b.serno_num, b.title_low LIMIT ?",
                params + [lim],
            ).fetchall()
            return {"items": [dict(r) for r in rows], "total": int(total), "truncated": int(total) > len(rows)}

    def search_advanced(self, title="", author="", series="", genre="", lang="all", hide_deleted=True, limit=500):
        """Многополевой поиск для вкладки «Поиск». При пустых полях возвращает пустой результат."""
        if not os.path.isfile(self.db_path):
            return {"items": [], "total": 0, "truncated": False}
        q_title = str(title or "").strip()
        q_author = str(author or "").strip()
        q_series = str(series or "").strip()
        q_genre = str(genre or "").strip()
        if not (q_title or q_author or q_series or q_genre):
            return {"items": [], "total": 0, "truncated": False}

        lim = max(1, min(MAX_INPX_SEARCH_LIMIT, int(limit or 500)))
        meta = self.get_meta()
        has_fts5 = meta.get("has_fts5") == "1"

        where_clauses = []
        params = []
        if hide_deleted:
            where_clauses.append("b.deleted = 0")
        lang_f = str(lang or "all").strip().lower()
        if lang_f and lang_f != "all":
            where_clauses.append("b.lang = ?")
            params.append(lang_f)

        fts_parts = []
        if has_fts5:
            for val, col in ((q_title, "title"), (q_author, "author"), (q_series, "series"), (q_genre, "genres")):
                if val:
                    expr = _build_fts_match_expr(val, field=col)
                    if expr:
                        fts_parts.append(f"({expr})")

        with self._connect(readonly=True) as conn:
            if has_fts5 and fts_parts:
                fts_query = " AND ".join(fts_parts)
                where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""
                total = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM books_fts f JOIN books b ON b.id = f.rowid "
                    f"WHERE books_fts MATCH ?{where_sql}",
                    [fts_query] + params,
                ).fetchone()["cnt"]
                rows = conn.execute(
                    f"SELECT b.* FROM books_fts f JOIN books b ON b.id = f.rowid "
                    f"WHERE books_fts MATCH ?{where_sql} "
                    f"ORDER BY b.author_low, b.series_low, b.serno_num, b.title_low LIMIT ?",
                    [fts_query] + params + [lim],
                ).fetchall()
                return {"items": [dict(r) for r in rows], "total": int(total), "truncated": int(total) > len(rows)}

            if q_title:
                where_clauses.append("b.title_low LIKE ?")
                params.append(f"%{q_title.lower()}%")
            if q_author:
                where_clauses.append("b.author_low LIKE ?")
                params.append(f"%{q_author.lower()}%")
            if q_series:
                where_clauses.append("b.series_low LIKE ?")
                params.append(f"%{q_series.lower()}%")
            if q_genre:
                where_clauses.append("b.genres LIKE ?")
                params.append(f"%{q_genre.lower()}%")

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            total = conn.execute(f"SELECT COUNT(*) AS cnt FROM books b{where_sql}", params).fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT b.* FROM books b{where_sql} "
                f"ORDER BY b.author_low, b.series_low, b.serno_num, b.title_low LIMIT ?",
                params + [lim],
            ).fetchall()
            return {"items": [dict(r) for r in rows], "total": int(total), "truncated": int(total) > len(rows)}

    def search(self, query="", field="all", lang="all", hide_deleted=True, limit=300):
        """Универсальный поиск книг в SQLite FTS5 индексе (с фолбэком на LIKE)."""
        if not os.path.isfile(self.db_path):
            return {"items": [], "total": 0, "truncated": False}
        lim = max(1, min(MAX_INPX_SEARCH_LIMIT, int(limit or 300)))
        q = str(query or "").strip()
        lang_f = str(lang or "all").strip().lower()
        meta = self.get_meta()
        has_fts5 = meta.get("has_fts5") == "1"

        where_clauses = []
        params = []
        if hide_deleted:
            where_clauses.append("b.deleted = 0")
        if lang_f and lang_f != "all":
            where_clauses.append("b.lang = ?")
            params.append(lang_f)

        with self._connect(readonly=True) as conn:
            if q and has_fts5:
                fts_expr = _build_fts_match_expr(q, field=field)
                if fts_expr:
                    where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""
                    count_sql = (
                        f"SELECT COUNT(*) AS cnt FROM books_fts f "
                        f"JOIN books b ON b.id = f.rowid "
                        f"WHERE books_fts MATCH ?{where_sql}"
                    )
                    total = conn.execute(count_sql, [fts_expr] + params).fetchone()["cnt"]
                    rows_sql = (
                        f"SELECT b.* FROM books_fts f "
                        f"JOIN books b ON b.id = f.rowid "
                        f"WHERE books_fts MATCH ?{where_sql} "
                        f"ORDER BY b.author_low, b.series_low, b.serno_num, b.title_low "
                        f"LIMIT ?"
                    )
                    rows = conn.execute(rows_sql, [fts_expr] + params + [lim]).fetchall()
                    return {
                        "items": [dict(r) for r in rows],
                        "total": int(total),
                        "truncated": int(total) > len(rows),
                    }

            if q:
                like_val = f"%{q.lower()}%"
                if field == "author":
                    where_clauses.append("b.author_low LIKE ?")
                    params.append(like_val)
                elif field == "title":
                    where_clauses.append("b.title_low LIKE ?")
                    params.append(like_val)
                elif field == "series":
                    where_clauses.append("b.series_low LIKE ?")
                    params.append(like_val)
                elif field == "genres":
                    where_clauses.append("b.genres LIKE ?")
                    params.append(like_val)
                else:
                    where_clauses.append(
                        "(b.author_low LIKE ? OR b.title_low LIKE ? "
                        "OR b.series_low LIKE ? OR b.genres LIKE ?)"
                    )
                    params.extend([like_val, like_val, like_val, like_val])

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            total = conn.execute(f"SELECT COUNT(*) AS cnt FROM books b{where_sql}", params).fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT b.* FROM books b{where_sql} "
                f"ORDER BY b.author_low, b.series_low, b.serno_num, b.title_low "
                f"LIMIT ?",
                params + [lim],
            ).fetchall()
            return {
                "items": [dict(r) for r in rows],
                "total": int(total),
                "truncated": int(total) > len(rows),
            }

    def get_series_books(self, series_name, author_hint="", hide_deleted=True, limit=500):
        """Возвращает все книги указанной серии (с опциональным уточнением автора), отсортированные по номеру."""
        ser_low = str(series_name or "").strip().lower()
        if not ser_low or not os.path.isfile(self.db_path):
            return []
        where = ["series_low = ?"]
        params = [ser_low]
        if hide_deleted:
            where.append("deleted = 0")
        if author_hint:
            first_last = str(author_hint).split(",")[0].strip().split()[0].strip().lower() if str(author_hint).strip() else ""
            if first_last:
                where.append("author_low LIKE ?")
                params.append(f"%{first_last}%")
        with self._connect(readonly=True) as conn:
            rows = conn.execute(
                f"SELECT * FROM books WHERE {' AND '.join(where)} "
                f"ORDER BY serno_num, serno, title_low LIMIT ?",
                params + [int(limit or 500)],
            ).fetchall()
            return [dict(r) for r in rows]

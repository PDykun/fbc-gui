"""Локальная библиотека книг в формате INPX с быстрым SQLite FTS5 кэш-индексом."""

import os
import re
import sqlite3
import zipfile

from core.logger import get_logger

logger = get_logger("inpx_library")

INPX_CACHE_SCHEMA_VERSION = "1"
MAX_INPX_ENTRY_BYTES = 128 * 1024 * 1024  # 128 МБ лимит на один .inp-файл (защита от zip-bomb)
MAX_INPX_SEARCH_LIMIT = 500

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
    "INSNO",
    "FOLDER",
    "LANG",
    "LIBRATE",
    "KEYWORDS",
)

_FTS_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def _format_inpx_authors(raw_author):
    """Преобразует формат INPX 'Фамилия,Имя,Отчество:Фамилия2,Имя2:' в читаемую строку."""
    if not raw_author:
        return ""
    authors = []
    for chunk in str(raw_author).split(":"):
        parts = [p.strip() for p in chunk.split(",") if p.strip()]
        if parts:
            authors.append(" ".join(parts))
    return ", ".join(authors)


def _format_inpx_genres(raw_genres):
    """Преобразует 'sf_fantasy:prose:' в 'sf_fantasy, prose'."""
    if not raw_genres:
        return ""
    items = [g.strip() for g in str(raw_genres).split(":") if g.strip()]
    return ", ".join(items)


def _parse_serno_int(serno_str):
    s = str(serno_str or "").strip()
    if s.isdigit():
        return int(s)
    m = re.match(r"^(\d+)", s)
    return int(m.group(1)) if m else 999999


def _parse_size_int(size_str):
    s = str(size_str or "").strip()
    try:
        return max(0, int(s))
    except (TypeError, ValueError):
        return 0


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
    Поддерживает:
      1) ZIP-архив по полю FOLDER (или FOLDER.zip) в папке .inpx или подпапках fb2/arch;
      2) ZIP-архив с именем .inp-файла (<inp_name>.zip) в папке .inpx или подпапках fb2/arch;
      3) распакованный файл <file>.<ext> в папке <FOLDER> или корне библиотеки.
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


class InpxLibraryIndex:
    """Управляет SQLite FTS5 кэш-индексом для локального INPX-файла."""

    def __init__(self, db_path):
        self.db_path = os.path.abspath(db_path)

    def _connect(self, readonly=False):
        if readonly and os.path.isfile(self.db_path):
            conn = sqlite3.connect(self.db_path, timeout=10)
        else:
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
        """Парсит INPX в изолированный временный SQLite-файл и атомарно подменяет кэш."""
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
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            author TEXT NOT NULL,
                            title TEXT NOT NULL,
                            series TEXT NOT NULL,
                            serno TEXT NOT NULL,
                            serno_num INTEGER NOT NULL,
                            genres TEXT NOT NULL,
                            lang TEXT NOT NULL,
                            size INTEGER NOT NULL,
                            file TEXT NOT NULL,
                            ext TEXT NOT NULL,
                            folder TEXT NOT NULL,
                            inp_name TEXT NOT NULL,
                            deleted INTEGER NOT NULL,
                            date TEXT NOT NULL
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

                    def _get_col(parts, col_idx):
                        if col_idx is None or col_idx >= len(parts):
                            return ""
                        return parts[col_idx]

                    insert_sql = (
                        "INSERT INTO books (author, title, series, serno, serno_num, genres, lang, size, "
                        "file, ext, folder, inp_name, deleted, date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                    )

                    batch = []
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

                            author = _format_inpx_authors(_get_col(parts, idx_author))
                            title = _get_col(parts, idx_title).strip()
                            series = _get_col(parts, idx_series).strip()
                            serno = _get_col(parts, idx_serno).strip()
                            serno_num = _parse_serno_int(serno)
                            genres = _format_inpx_genres(_get_col(parts, idx_genre))
                            lang = _get_col(parts, idx_lang).strip().lower()
                            size_b = _parse_size_int(_get_col(parts, idx_size))
                            folder = _get_col(parts, idx_folder).strip()
                            deleted = 1 if _get_col(parts, idx_del).strip() == "1" else 0
                            date_str = _get_col(parts, idx_date).strip()

                            batch.append((
                                author, title, series, serno, serno_num, genres, lang,
                                size_b, file_stem, ext, folder, inp_stem, deleted, date_str,
                            ))
                            total_books += 1
                            if len(batch) >= 5000:
                                conn.executemany(insert_sql, batch)
                                batch.clear()

                    if batch:
                        conn.executemany(insert_sql, batch)
                        batch.clear()

                    conn.execute("CREATE INDEX idx_books_series ON books(series COLLATE NOCASE)")
                    conn.execute("CREATE INDEX idx_books_lang_del ON books(deleted, lang)")

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
                    conn.commit()
                finally:
                    conn.close()

            os.replace(tmp_db, self.db_path)
            logger.info(
                "Индекс INPX построен: %s (книг FB2: %d, FTS5=%s)",
                abs_inpx, total_books, use_fts5,
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

    def search(self, query="", field="all", lang="all", hide_deleted=True, limit=300):
        """Ищет книги в SQLite FTS5 индексе (с фолбэком на LIKE) и возвращает {'items', 'total', 'truncated'}."""
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
                        f"ORDER BY b.author COLLATE NOCASE, b.series COLLATE NOCASE, b.serno_num, b.title COLLATE NOCASE "
                        f"LIMIT ?"
                    )
                    rows = conn.execute(rows_sql, [fts_expr] + params + [lim]).fetchall()
                    return {
                        "items": [dict(r) for r in rows],
                        "total": int(total),
                        "truncated": int(total) > len(rows),
                    }

            if q:
                like_val = f"%{q}%"
                if field in ("author", "title", "series", "genres"):
                    where_clauses.append(f"b.{field} LIKE ? COLLATE NOCASE")
                    params.append(like_val)
                else:
                    where_clauses.append(
                        "(b.author LIKE ? COLLATE NOCASE OR b.title LIKE ? COLLATE NOCASE "
                        "OR b.series LIKE ? COLLATE NOCASE OR b.genres LIKE ? COLLATE NOCASE)"
                    )
                    params.extend([like_val, like_val, like_val, like_val])

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            total = conn.execute(f"SELECT COUNT(*) AS cnt FROM books b{where_sql}", params).fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT b.* FROM books b{where_sql} "
                f"ORDER BY b.author COLLATE NOCASE, b.series COLLATE NOCASE, b.serno_num, b.title COLLATE NOCASE "
                f"LIMIT ?",
                params + [lim],
            ).fetchall()
            return {
                "items": [dict(r) for r in rows],
                "total": int(total),
                "truncated": int(total) > len(rows),
            }

    def get_series_books(self, series_name, author_hint="", hide_deleted=True, limit=500):
        """Возвращает все книги указанной серии (с опциональным уточнением автора), отсортированные по номеру в серии."""
        ser = str(series_name or "").strip()
        if not ser or not os.path.isfile(self.db_path):
            return []
        where = ["series = ? COLLATE NOCASE"]
        params = [ser]
        if hide_deleted:
            where.append("deleted = 0")
        if author_hint:
            # Уточняем по фамилии первого автора, если в библиотеке есть тёзки-серии разных авторов
            first_last = str(author_hint).split(",")[0].strip().split()[0].strip() if str(author_hint).strip() else ""
            if first_last:
                where.append("author LIKE ? COLLATE NOCASE")
                params.append(f"%{first_last}%")
        with self._connect(readonly=True) as conn:
            rows = conn.execute(
                f"SELECT * FROM books WHERE {' AND '.join(where)} "
                f"ORDER BY serno_num, serno, title COLLATE NOCASE LIMIT ?",
                params + [int(limit or 500)],
            ).fetchall()
            return [dict(r) for r in rows]

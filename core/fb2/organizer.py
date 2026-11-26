import os
import re
import shutil

from core.fb2.common import _WHITESPACE_RE
from core.fb2.templates import render_filename_from_tokens

_INVALID_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def _sanitize_fs_component(text, fallback="_"):
    cleaned = _INVALID_PATH_CHARS_RE.sub(" ", str(text or "")).strip(" .")
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    return cleaned or fallback


def plan_organize_fb2_files(items, dest_root, pattern_mode="author_series", filename_mode="default", filename_tokens=None):
    """Строит план переименования и раскладки исходных .fb2/.zip по папкам (dry-run таблица Было -> Стало)."""
    plan = []
    claimed = set()
    seen_sources = set()

    for data in (items or []):
        src_path = data.get("path")
        if not src_path or not os.path.isfile(src_path):
            continue
        norm_src = os.path.normcase(os.path.abspath(src_path))
        if norm_src in seen_sources:
            continue
        seen_sources.add(norm_src)

        meta = data.get("meta") or {}
        author_parts = [p for p in (meta.get("last"), meta.get("first")) if (p or "").strip()]
        author_dir = _sanitize_fs_component(" ".join(author_parts), fallback="Unknown Author")
        series_dir = _sanitize_fs_component(meta.get("series"), fallback="") if (meta.get("series") or "").strip() else ""

        src_low = src_path.lower()
        if src_low.endswith(".fb2.zip"):
            ext = ".fb2.zip"
        else:
            ext = os.path.splitext(src_path)[1] or ".fb2"

        if filename_mode == "custom" and filename_tokens:
            stem = render_filename_from_tokens(filename_tokens, meta, "fb2")
        else:
            title = (meta.get("title") or os.path.splitext(os.path.basename(src_path))[0]).strip()
            num = (meta.get("num") or "").strip()
            prefix = f"{int(num):02d} - " if (series_dir and num.isdigit()) else ""
            stem = f"{prefix}{title}"
        stem = _sanitize_fs_component(stem, fallback="book")

        sub_parts = []
        if pattern_mode == "author_series":
            sub_parts.append(author_dir)
            if series_dir:
                sub_parts.append(series_dir)
        elif pattern_mode == "author":
            sub_parts.append(author_dir)

        target_dir = os.path.join(dest_root, *sub_parts) if sub_parts else dest_root
        dst_path = os.path.join(target_dir, f"{stem}{ext}")
        norm_dst = os.path.normcase(os.path.abspath(dst_path))
        suffix_n = 2
        while norm_dst in claimed:
            dst_path = os.path.join(target_dir, f"{stem} ({suffix_n}){ext}")
            norm_dst = os.path.normcase(os.path.abspath(dst_path))
            suffix_n += 1
        claimed.add(norm_dst)

        plan.append({
            "item_id": data.get("item_id", ""),
            "src_path": os.path.abspath(src_path),
            "dst_path": os.path.abspath(dst_path),
            "dest_root": os.path.abspath(dest_root),
            "display_name": data.get("display_name") or os.path.basename(src_path),
        })
    return plan


def execute_organize_fb2_plan(plan, copy_mode=True, dest_root=None):
    """Выполняет план копирования или перемещения исходных FB2/ZIP, возвращая (count, errors, path_map)."""
    succeeded = 0
    errors = []
    path_map = {}
    for entry in (plan or []):
        src = entry["src_path"]
        dst = entry["dst_path"]
        try:
            root_guard = dest_root or entry.get("dest_root")
            if root_guard:
                abs_root = os.path.abspath(root_guard)
                abs_dst = os.path.abspath(dst)
                if os.path.commonpath([abs_root, abs_dst]) != abs_root:
                    raise ValueError(f"Destination path escapes target root: {dst}")
            if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
                succeeded += 1
                path_map[src] = dst
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            final_dst = dst
            if os.path.exists(final_dst):
                low = final_dst.lower()
                if low.endswith(".fb2.zip"):
                    base, ext = final_dst[:-8], final_dst[-8:]
                else:
                    base, ext = os.path.splitext(final_dst)
                n = 2
                while os.path.exists(f"{base} ({n}){ext}"):
                    n += 1
                final_dst = f"{base} ({n}){ext}"
            if copy_mode:
                shutil.copy2(src, final_dst)
            else:
                shutil.move(src, final_dst)
            succeeded += 1
            path_map[src] = final_dst
        except Exception as e:
            errors.append((entry.get("display_name") or os.path.basename(src), str(e)))
    return succeeded, errors, path_map


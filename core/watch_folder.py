"""Фоновый мониторинг папок автоконвертации (Watch Folder) с изолированным применением пресетов и доставкой."""

import copy
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from collections import deque

from PyQt6.QtCore import QFile, QFileSystemWatcher, QObject, QThread, QTimer, pyqtSignal

from core.config import (
    DEFAULT_OUTPUT_FORMAT,
    atomic_write_text,
    update_fbc_config_file,
)
from core.cover_studio import TEMPLATES as COVER_TEMPLATES
from core.css_preview import generate_css_content as build_css_content, get_default_css_ui_state
from core.email_sender import send_converted_files_via_email
from core.fb2_processor import (
    ConversionCancelledError,
    convert_book_file,
    copy_meta_dict,
    extract_cover_from_fb2,
    iter_fb2_from_file,
    parse_metadata,
)
from core.logger import get_logger
from core.metadata_lookup import (
    DEFAULT_ENABLED_PROVIDERS,
    DEFAULT_PROVIDER_ORDER,
    fetch_candidate_covers,
    search_book_metadata,
)
from core.presets import apply_preset_to_settings, list_presets, load_preset_file
from core.watch_enrich import (
    WATCH_ENRICH_CONFIDENCE_PRESETS as WATCH_ENRICH_CONFIDENCE_PRESETS,
    WATCH_ENRICH_MODES as WATCH_ENRICH_MODES,
    _TITLE_NOISE_RE as _TITLE_NOISE_RE,
    _merge_empty_meta_fields as _merge_empty_meta_fields,
    _needs_enrichment as _needs_enrichment,
    _norm_match_text as _norm_match_text,
    match_best_enrich_candidate as match_best_enrich_candidate,
    prepare_watch_book_item as _prepare_watch_book_item,
)

logger = get_logger("watch_folder")

PRESET_CURRENT_TOKEN = "__current__"
WATCH_DELIVERY_MODES = ("folder", "email", "device_sync")
WATCH_POST_ACTIONS = ("move_processed", "keep", "trash")
WATCH_SUPPORTED_EXTS = (".fb2", ".zip")
WATCH_IGNORED_TEMP_EXTS = (
    ".crdownload",
    ".part",
    ".download",
    ".tmp",
    ".temp",
    ".opdownload",
    ".filepart",
    ".!qb",
)
WATCH_INTERNAL_SUBDIRS = ("Processed", "Failed", "Converted")
from core.s2k_manager import DEVICE_SYNC_EXEC_LOCK

WATCH_STATE_FILENAME = "watch_state.json"
WATCH_RETRY_BASE_SEC = 30.0
WATCH_RETRY_MAX_SEC = 600.0


def normalize_watch_rule(raw):
    """Приводит описание правила Watch Folder к канонической схеме с безопасными дефолтами."""
    src = raw if isinstance(raw, dict) else {}
    rule_id = str(src.get("id") or "").strip() or uuid.uuid4().hex[:12]
    folder = str(src.get("folder") or "").strip()
    name = str(src.get("name") or "").strip()
    if not name and folder:
        name = os.path.basename(os.path.normpath(folder)) or folder

    preset_name = str(src.get("preset_name") or "").strip() or PRESET_CURRENT_TOKEN
    delivery_mode = str(src.get("delivery_mode") or "folder").strip().lower()
    if delivery_mode not in WATCH_DELIVERY_MODES:
        delivery_mode = "folder"

    post_action = str(src.get("post_action") or "move_processed").strip().lower()
    if post_action not in WATCH_POST_ACTIONS:
        post_action = "move_processed"

    dev_mode = str(src.get("device_sync_mode") or "").strip().lower()
    if dev_mode not in ("", "mtp", "usb", "folder"):
        dev_mode = ""

    enrich_mode = str(src.get("auto_enrich_mode") or "off").strip().lower()
    if enrich_mode not in WATCH_ENRICH_MODES:
        enrich_mode = "off"

    try:
        min_conf = float(src.get("enrich_min_confidence", 0.88))
    except (TypeError, ValueError):
        min_conf = 0.88
    min_conf = round(max(0.50, min(0.99, min_conf)), 2)

    raw_provs = src.get("enrich_providers")
    if isinstance(raw_provs, (list, tuple)):
        valid_provs = [
            str(p).strip().lower()
            for p in raw_provs
            if str(p).strip().lower() in DEFAULT_PROVIDER_ORDER
        ]
        enrich_providers = list(dict.fromkeys(valid_provs)) or list(DEFAULT_ENABLED_PROVIDERS)
    else:
        enrich_providers = list(DEFAULT_ENABLED_PROVIDERS)

    try:
        enrich_timeout = float(src.get("enrich_timeout_sec", 10.0))
    except (TypeError, ValueError):
        enrich_timeout = 10.0
    enrich_timeout = round(max(3.0, min(30.0, enrich_timeout)), 1)

    fb_tpl = str(src.get("fallback_cover_template") or "eink_minimal").strip()
    if fb_tpl not in COVER_TEMPLATES:
        fb_tpl = "eink_minimal"

    return {
        "id": rule_id,
        "enabled": bool(src.get("enabled", True)),
        "name": name,
        "folder": folder,
        "recursive": bool(src.get("recursive", False)),
        "preset_name": preset_name,
        "delivery_mode": delivery_mode,
        "output_dir": str(src.get("output_dir") or "").strip(),
        "email_to": str(src.get("email_to") or "").strip(),
        "device_sync_mode": dev_mode,
        "device_sync_target": str(src.get("device_sync_target") or "").strip(),
        "post_action": post_action,
        "auto_repair": bool(src.get("auto_repair", False)),
        "auto_enrich_mode": enrich_mode,
        "enrich_min_confidence": min_conf,
        "enrich_providers": enrich_providers,
        "enrich_timeout_sec": enrich_timeout,
        "fallback_cover_enabled": bool(src.get("fallback_cover_enabled", False)),
        "fallback_cover_template": fb_tpl,
        "fallback_cover_series_color": bool(src.get("fallback_cover_series_color", True)),
        "write_back_source": bool(src.get("write_back_source", False)),
    }


def prepare_watch_book_item(
    item_data,
    xml_bytes,
    rule,
    base_app_settings=None,
    *,
    fonts_dir=None,
    enrich_cache=None,
    cancel_event=None,
):
    """Фасад предконвертационной подготовки книги с сохранением точек подмены в core.watch_folder."""
    return _prepare_watch_book_item(
        item_data,
        xml_bytes,
        rule,
        base_app_settings=base_app_settings,
        fonts_dir=fonts_dir,
        enrich_cache=enrich_cache,
        cancel_event=cancel_event,
        normalize_rule_fn=normalize_watch_rule,
        search_metadata_fn=search_book_metadata,
        fetch_covers_fn=fetch_candidate_covers,
    )


def normalize_watch_rules(raw_list):
    """Нормализует список правил Watch Folder и отфильтровывает некорректные записи."""
    if not isinstance(raw_list, list):
        return []
    result = []
    seen_ids = set()
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        rule = normalize_watch_rule(item)
        if not rule["folder"]:
            continue
        if rule["id"] in seen_ids:
            rule["id"] = uuid.uuid4().hex[:12]
        seen_ids.add(rule["id"])
        result.append(rule)
    return result


def is_ignored_watch_path(filepath, watch_root):
    """Возвращает True для служебных, скрытых, временных файлов и внутренних подпапок Processed/Failed/Converted."""
    if not filepath:
        return True
    name = os.path.basename(filepath)
    if not name or name.startswith(".") or name.startswith("~$") or name.startswith("._"):
        return True
    low = name.lower()
    if any(low.endswith(ext) for ext in WATCH_IGNORED_TEMP_EXTS):
        return True
    if watch_root:
        try:
            rel = os.path.relpath(os.path.abspath(filepath), os.path.abspath(watch_root))
            parts = rel.split(os.sep)
            if parts and parts[0] in WATCH_INTERNAL_SUBDIRS:
                return True
            if any(p.startswith(".") for p in parts):
                return True
        except ValueError:
            pass
    return False


def is_supported_watch_book(filepath):
    """Проверяет, является ли путь поддерживаемым файлом книги (.fb2 или .zip)."""
    if not filepath or not os.path.isfile(filepath):
        return False
    return filepath.lower().endswith(WATCH_SUPPORTED_EXTS)


def is_file_readable_and_ready(filepath):
    """Проверяет, что файл не пуст, доступен для чтения (не заблокирован) и валиден как ZIP при расширении .zip."""
    try:
        st = os.stat(filepath)
        if st.st_size <= 0:
            return False
        with open(filepath, "rb") as fh:
            head = fh.read(64)
            if not head:
                return False
        if filepath.lower().endswith(".zip"):
            if not zipfile.is_zipfile(filepath):
                return False
            with zipfile.ZipFile(filepath, "r") as zf:
                zf.infolist()
        return True
    except (OSError, zipfile.BadZipFile):
        return False


def _unique_dest_path(dest_dir, filename):
    """Возвращает путь внутри dest_dir без перезаписи существующего файла."""
    os.makedirs(dest_dir, exist_ok=True)
    candidate = os.path.join(dest_dir, filename)
    if not os.path.exists(candidate):
        return candidate
    stem, ext = os.path.splitext(filename)
    idx = 2
    while True:
        candidate = os.path.join(dest_dir, f"{stem} ({idx}){ext}")
        if not os.path.exists(candidate):
            return candidate
        idx += 1


def apply_post_action(src_path, watch_root, post_action, *, success=True):
    """Выполняет действие с исходным файлом после обработки: move_processed / keep / trash."""
    if not src_path or not os.path.isfile(src_path):
        return None
    action = str(post_action or "move_processed").lower()
    if action == "keep":
        return src_path

    if not success:
        failed_dir = os.path.join(watch_root, "Failed")
        dst = _unique_dest_path(failed_dir, os.path.basename(src_path))
        shutil.move(src_path, dst)
        return dst

    if action == "trash":
        try:
            ok, trash_path = QFile.moveToTrash(src_path)
            if ok:
                return trash_path or ""
        except Exception as e:
            logger.warning("Не удалось переместить в Корзину %s (%s); перенос в Processed/", src_path, e)

    processed_dir = os.path.join(watch_root, "Processed")
    dst = _unique_dest_path(processed_dir, os.path.basename(src_path))
    shutil.move(src_path, dst)
    return dst


class WatchStateStore:
    """Хранилище состояния уже обработанных файлов (watch_state.json) для исключения повторной конвертации."""

    MAX_ENTRIES_PER_RULE = 5000

    def __init__(self, state_path):
        self.state_path = state_path
        self._lock = threading.Lock()
        self._data = {"version": 1, "rules": {}}
        self.load()

    @staticmethod
    def _norm_key(filepath):
        return os.path.normcase(os.path.abspath(filepath))

    def load(self):
        with self._lock:
            if not self.state_path or not os.path.isfile(self.state_path):
                return
            try:
                with open(self.state_path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                if isinstance(raw, dict) and isinstance(raw.get("rules"), dict):
                    self._data = raw
            except Exception as e:
                logger.warning("Не удалось прочитать %s: %s", self.state_path, e)

    def save(self):
        if not self.state_path:
            return
        with self._lock:
            payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        try:
            atomic_write_text(self.state_path, payload)
        except Exception as e:
            logger.warning("Не удалось сохранить %s: %s", self.state_path, e)

    def is_processed(self, rule_id, filepath, size, mtime):
        key = self._norm_key(filepath)
        with self._lock:
            rec = (self._data.get("rules") or {}).get(rule_id, {}).get(key)
            if not isinstance(rec, dict):
                return False
            return (
                int(rec.get("size", -1)) == int(size)
                and abs(float(rec.get("mtime", -1.0)) - float(mtime)) < 0.01
            )

    def mark_processed(self, rule_id, filepath, size, mtime, status="ok", error=""):
        self.mark_processed_batch(
            rule_id,
            [{"path": filepath, "size": size, "mtime": mtime, "status": status, "error": error}],
        )

    def mark_processed_batch(self, rule_id, entries):
        """Помечает пакет файлов обработанными с одной атомарной записью watch_state.json."""
        if not entries:
            return
        now_ts = int(time.time())
        with self._lock:
            rules_map = self._data.setdefault("rules", {})
            rule_bucket = rules_map.setdefault(rule_id, {})
            for item in entries:
                key = self._norm_key(item["path"])
                rule_bucket[key] = {
                    "size": int(item["size"]),
                    "mtime": float(item["mtime"]),
                    "status": str(item.get("status", "ok")),
                    "error": str(item.get("error", "") or "")[:300],
                    "processed_at": now_ts,
                }
            if len(rule_bucket) > self.MAX_ENTRIES_PER_RULE:
                sorted_keys = sorted(
                    rule_bucket.keys(),
                    key=lambda k: rule_bucket[k].get("processed_at", 0),
                )
                for old_k in sorted_keys[: len(rule_bucket) - self.MAX_ENTRIES_PER_RULE]:
                    rule_bucket.pop(old_k, None)
        self.save()

    def prune_unknown_rules(self, valid_rule_ids):
        valid = set(valid_rule_ids or ())
        changed = False
        with self._lock:
            rules_map = self._data.get("rules") or {}
            for rid in list(rules_map.keys()):
                if rid not in valid:
                    rules_map.pop(rid, None)
                    changed = True
        if changed:
            self.save()


def _extract_title_style_params(app_settings):
    css_state = app_settings.get("css_ui_state")
    if not isinstance(css_state, dict):
        css_state = get_default_css_ui_state()
    else:
        css_state = {**get_default_css_ui_state(), **css_state}
    return {
        "h1_sz": css_state.get("h1_sz", "150%"),
        "h1_cl": css_state.get("h1_cl", "black"),
        "h1_al": css_state.get("h1_al", "center"),
        "auth_sz": css_state.get("auth_sz", "110%"),
        "auth_cl": css_state.get("auth_cl", "dimgray"),
        "auth_al": css_state.get("auth_al", "center"),
        "auth_style": css_state.get("auth_style", "italic"),
    }


def build_isolated_conversion_env(
    work_dir,
    base_config_path,
    base_css_path,
    fonts_dir,
    base_app_settings,
    presets_dir,
    preset_name,
):
    """
    Создаёт изолированную копию config.yaml и ebook_styles.css в work_dir под указанный пресет,
    не затрагивая активные настройки и файлы главного окна.
    """
    os.makedirs(work_dir, exist_ok=True)
    merged = copy.deepcopy(base_app_settings or {})
    tmp_cfg = os.path.join(work_dir, "config.yaml")
    tmp_css = os.path.join(work_dir, "ebook_styles.css")

    if base_config_path and os.path.isfile(base_config_path):
        shutil.copy2(base_config_path, tmp_cfg)
    else:
        atomic_write_text(tmp_cfg, "version: 1\n")

    preset_payload = None
    if preset_name and preset_name != PRESET_CURRENT_TOKEN and presets_dir:
        for item in list_presets(presets_dir):
            if item.get("name") == preset_name and item.get("path"):
                try:
                    preset_payload = load_preset_file(item["path"])
                except Exception as e:
                    logger.warning("Не удалось загрузить пресет '%s': %s", preset_name, e)
                break

    if preset_payload is not None:
        apply_preset_to_settings(merged, preset_payload)
        css_content = preset_payload.get("css_content") or ""
        preset_settings = preset_payload.get("settings") or {}
        if css_content:
            atomic_write_text(tmp_css, css_content)
        elif isinstance(preset_settings.get("css_ui_state"), dict) and preset_settings["css_ui_state"]:
            merged_css_state = {**get_default_css_ui_state(), **preset_settings["css_ui_state"]}
            atomic_write_text(tmp_css, build_css_content(merged_css_state, fonts_dir or ""))
        elif base_css_path and os.path.isfile(base_css_path):
            shutil.copy2(base_css_path, tmp_css)
        else:
            atomic_write_text(tmp_css, build_css_content(get_default_css_ui_state(), fonts_dir or ""))
    else:
        if base_css_path and os.path.isfile(base_css_path):
            shutil.copy2(base_css_path, tmp_css)
        else:
            atomic_write_text(tmp_css, build_css_content(get_default_css_ui_state(), fonts_dir or ""))

    update_fbc_config_file(tmp_cfg, tmp_css, merged)
    return merged, tmp_cfg, tmp_css, _extract_title_style_params(merged)


class WatchJobWorker(QThread):
    """Фоновый поток обработки одного пакета файлов для правила Watch Folder."""

    job_finished = pyqtSignal(dict)

    def __init__(
        self,
        rule,
        filepaths,
        *,
        fbc_cmd,
        base_config_path,
        base_css_path,
        fonts_dir,
        presets_dir,
        base_dir,
        base_app_settings,
        app_name="FBC GUI",
        app_version="",
        parent=None,
    ):
        super().__init__(parent)
        self.rule = copy.deepcopy(rule)
        self.filepaths = list(filepaths or [])
        self.fbc_cmd = fbc_cmd
        self.base_config_path = base_config_path
        self.base_css_path = base_css_path
        self.fonts_dir = fonts_dir
        self.presets_dir = presets_dir
        self.base_dir = base_dir
        self.base_app_settings = copy.deepcopy(base_app_settings or {})
        self.app_name = app_name
        self.app_version = app_version
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()
        self.requestInterruption()

    def _deliver_via_device_sync(self, converted_files, source_dir):
        from core.fb2_processor import _run_cancellable_process
        from core.s2k_manager import (
            build_s2k_sync_command,
            resolve_local_s2k,
            stage_books_for_s2k,
            sync_folder_to_mounted_device,
            write_s2k_sync_config,
        )

        mode = (self.rule.get("device_sync_mode") or self.base_app_settings.get("device_sync_mode") or "mtp").lower()
        target_dir = self.rule.get("device_sync_target") or self.base_app_settings.get("device_sync_target") or "documents/books"
        ignore_rem = str(self.base_app_settings.get("device_sync_ignore_removals", "true")).lower() == "true"

        with DEVICE_SYNC_EXEC_LOCK:
            if mode == "folder":
                sync_folder_to_mounted_device(
                    source_dir,
                    target_dir,
                    dry_run=False,
                    explicit_files=converted_files,
                )
                return

            info = resolve_local_s2k(self.base_dir, raise_on_missing_lib=True)
            if not info:
                raise RuntimeError("sync2kindle is not installed; run Device Sync once from Settings to install it")

            work_dir = self.base_dir if (self.base_dir and os.path.isdir(self.base_dir)) else os.path.dirname(info["path"])
            staging_dir = tempfile.mkdtemp(prefix="s2k_watch_", dir=work_dir)
            tmp_cfg_path = None
            try:
                staged = stage_books_for_s2k(source_dir, staging_dir, explicit_files=converted_files)
                if not staged:
                    raise RuntimeError("No converted books available for device sync")
                fd, tmp_cfg_path = tempfile.mkstemp(prefix="s2k_watch_cfg_", suffix=".yaml", dir=work_dir)
                os.close(fd)
                write_s2k_sync_config(tmp_cfg_path, staging_dir, target_dir)
                cmd = build_s2k_sync_command(
                    info["path"],
                    mode,
                    staging_dir,
                    target_dir,
                    dry_run=False,
                    ignore_device_removals=ignore_rem,
                    config_path=tmp_cfg_path,
                )
                _run_cancellable_process(cmd, cwd=work_dir, cancel_event=self._cancel_event)
            finally:
                if tmp_cfg_path and os.path.exists(tmp_cfg_path):
                    try:
                        os.remove(tmp_cfg_path)
                    except OSError:
                        pass
                shutil.rmtree(staging_dir, ignore_errors=True)

    def _convert_watch_sources(
        self,
        summary,
        merged_settings,
        tmp_cfg,
        title_style,
        dest_dir,
        selected_format,
        compression,
        no_cover,
    ):
        claimed_outputs = set()
        source_outcomes = []
        enrich_cache = {}

        for src_path in self.filepaths:
            if self._cancel_event.is_set() or self.isInterruptionRequested():
                summary["cancelled"] = True
                break
            if not os.path.isfile(src_path):
                continue
            try:
                st = os.stat(src_path)
                src_size, src_mtime = st.st_size, st.st_mtime
            except OSError:
                continue

            src_created = []
            src_err = ""
            try:
                entries = list(iter_fb2_from_file(src_path))
                if not entries:
                    raise RuntimeError("No valid FB2 entries found")
                for source_key, archive_entry, display_name, xml_bytes in entries:
                    if self._cancel_event.is_set() or self.isInterruptionRequested():
                        raise ConversionCancelledError("Cancelled")
                    if not xml_bytes:
                        continue
                    meta = parse_metadata(xml_bytes)
                    cover_bytes, cover_mime = extract_cover_from_fb2(xml_bytes)
                    item_data = {
                        "path": src_path,
                        "archive_entry": archive_entry,
                        "source_key": source_key,
                        "display_name": display_name,
                        "meta": meta,
                        "orig_meta": copy_meta_dict(meta),
                        "cover_bytes": cover_bytes,
                        "cover_mime": cover_mime,
                        "cover_modified": False,
                    }
                    prep_stats = prepare_watch_book_item(
                        item_data,
                        xml_bytes,
                        self.rule,
                        self.base_app_settings,
                        fonts_dir=self.fonts_dir,
                        enrich_cache=enrich_cache,
                        cancel_event=self._cancel_event,
                    )
                    if prep_stats.get("repaired"):
                        summary["repaired_count"] += 1
                    if prep_stats.get("enriched"):
                        summary["enriched_count"] += 1
                    if prep_stats.get("cover_generated"):
                        summary["covers_generated_count"] += 1
                    try:
                        wf_jpeg_q = int(merged_settings.get("jpeg_quality_level", "95"))
                    except (TypeError, ValueError):
                        wf_jpeg_q = 95
                    created = convert_book_file(
                        self.fbc_cmd,
                        tmp_cfg,
                        self.base_dir,
                        item_data,
                        dest_dir,
                        selected_format,
                        title_style,
                        compression=compression,
                        cancel_event=self._cancel_event,
                        debug=False,
                        no_cover=no_cover,
                        claimed_outputs=claimed_outputs,
                        image_color_profile=merged_settings.get("image_color_profile", "none"),
                        jpeg_quality=wf_jpeg_q,
                        image_color_profile_custom=merged_settings.get("image_color_profile_custom"),
                    )
                    src_created.extend(created)
            except ConversionCancelledError:
                summary["cancelled"] = True
                break
            except Exception as e:
                src_err = str(e)
                logger.error("Watch Folder ошибка конвертации %s: %s", os.path.basename(src_path), e)

            source_outcomes.append((src_path, src_size, src_mtime, src_created, src_err))
        return source_outcomes

    def _deliver_watch_outputs(self, all_created, delivery_mode, dest_dir):
        if not all_created:
            return ""
        if delivery_mode == "email":
            try:
                email_settings = dict(self.base_app_settings)
                if self.rule.get("email_to"):
                    email_settings["email_to"] = self.rule["email_to"]
                send_converted_files_via_email(
                    email_settings,
                    all_created,
                    self.app_name,
                    self.app_version,
                    cancel_event=self._cancel_event,
                )
            except Exception as e:
                logger.error("Watch Folder ошибка отправки по Email: %s", e)
                return str(e)
        elif delivery_mode == "device_sync":
            try:
                self._deliver_via_device_sync(all_created, dest_dir)
            except Exception as e:
                logger.error("Watch Folder ошибка доставки на ридер: %s", e)
                return str(e)
        return ""

    def _finalize_watch_outcomes(self, summary, source_outcomes, delivery_mode, delivery_err):
        for src_path, src_size, src_mtime, src_created, src_err in source_outcomes:
            final_err = src_err or (delivery_err if src_created else "")
            ok = (not final_err) and bool(src_created)
            if ok:
                summary["success_count"] += len(src_created)
                summary["converted_files"].extend(src_created)
            else:
                summary["error_count"] += 1
                summary["errors"].append((os.path.basename(src_path), final_err or "Conversion failed"))

            try:
                # При ошибке доставки на ридер исходник лучше оставить на месте, чтобы не потерять его
                if delivery_err and delivery_mode == "device_sync":
                    moved_to = src_path
                else:
                    moved_to = apply_post_action(
                        src_path,
                        self.rule["folder"],
                        self.rule.get("post_action", "move_processed"),
                        success=ok,
                    )
            except Exception as post_err:
                logger.warning("Ошибка пост-обработки %s: %s", src_path, post_err)
                moved_to = src_path

            summary["processed_sources"].append({
                "path": src_path,
                "size": src_size,
                "mtime": src_mtime,
                "ok": ok,
                "error": final_err,
                "moved_to": moved_to,
            })

    def run(self):
        summary = {
            "rule_id": self.rule["id"],
            "rule_name": self.rule.get("name") or os.path.basename(self.rule["folder"]),
            "folder": self.rule["folder"],
            "delivery_mode": self.rule["delivery_mode"],
            "success_count": 0,
            "error_count": 0,
            "repaired_count": 0,
            "enriched_count": 0,
            "covers_generated_count": 0,
            "converted_files": [],
            "errors": [],
            "processed_sources": [],
            "cancelled": False,
        }

        if not self.fbc_cmd or not os.path.isfile(self.fbc_cmd):
            summary["error_count"] = len(self.filepaths)
            summary["errors"].append(("fb2cng", "fb2cng binary not found"))
            self.job_finished.emit(summary)
            return

        with tempfile.TemporaryDirectory(prefix="fbc_watch_env_") as env_dir:
            try:
                merged_settings, tmp_cfg, _tmp_css, title_style = build_isolated_conversion_env(
                    env_dir,
                    self.base_config_path,
                    self.base_css_path,
                    self.fonts_dir,
                    self.base_app_settings,
                    self.presets_dir,
                    self.rule.get("preset_name", PRESET_CURRENT_TOKEN),
                )
            except Exception as e:
                logger.exception("Ошибка подготовки окружения Watch Folder '%s': %s", summary["rule_name"], e)
                summary["error_count"] = len(self.filepaths)
                summary["errors"].append((summary["rule_name"], str(e)))
                self.job_finished.emit(summary)
                return

            selected_format = merged_settings.get("output_format", DEFAULT_OUTPUT_FORMAT)
            compression = None
            if selected_format == "azw3":
                compression = merged_settings.get("azw3_compression", "standard")
            elif selected_format in ("kfx", "azw8"):
                compression = merged_settings.get("kfx_compression", "none")
            no_cover = str(merged_settings.get("no_cover", "false")).lower() == "true"

            delivery_mode = self.rule["delivery_mode"]
            if delivery_mode == "folder":
                dest_dir = self.rule.get("output_dir") or os.path.join(self.rule["folder"], "Converted")
                os.makedirs(dest_dir, exist_ok=True)
            else:
                dest_dir = os.path.join(env_dir, "out")
                os.makedirs(dest_dir, exist_ok=True)

            source_outcomes = self._convert_watch_sources(
                summary,
                merged_settings,
                tmp_cfg,
                title_style,
                dest_dir,
                selected_format,
                compression,
                no_cover,
            )
            if summary["cancelled"]:
                self.job_finished.emit(summary)
                return

            all_created = [fp for _, _, _, created, err in source_outcomes if not err for fp in created]
            delivery_err = self._deliver_watch_outputs(all_created, delivery_mode, dest_dir)
            self._finalize_watch_outcomes(summary, source_outcomes, delivery_mode, delivery_err)

        self.job_finished.emit(summary)


MAX_WATCHED_SUBDIRS = 256


class WatchScanWorker(QThread):
    """Фоновый поток рекурсивного сканирования папок Watch Folder без блокировки GUI-потока."""

    scan_finished = pyqtSignal(list)  # list of dicts: {rule_id, folder, status, files}

    def __init__(self, rules, parent=None):
        super().__init__(parent)
        self._rules = [copy.deepcopy(r) for r in (rules or [])]

    def run(self):
        results = []
        for rule in self._rules:
            if self.isInterruptionRequested():
                break
            rid = rule["id"]
            folder = rule.get("folder", "")
            if not folder or not os.path.isdir(folder):
                results.append({"rule_id": rid, "folder": folder, "status": "missing", "files": []})
                continue
            try:
                files = []
                if rule.get("recursive"):
                    for cur_dir, subdirs, fnames in os.walk(folder):
                        if self.isInterruptionRequested():
                            break
                        subdirs[:] = [
                            d for d in subdirs
                            if not d.startswith(".") and d not in WATCH_INTERNAL_SUBDIRS
                        ]
                        for fname in sorted(fnames):
                            files.append(os.path.join(cur_dir, fname))
                else:
                    for fname in sorted(os.listdir(folder)):
                        files.append(os.path.join(folder, fname))
                results.append({"rule_id": rid, "folder": folder, "status": "ok", "files": files})
            except PermissionError:
                results.append({"rule_id": rid, "folder": folder, "status": "permission_error", "files": []})
            except OSError:
                results.append({"rule_id": rid, "folder": folder, "status": "error", "files": []})
        if not self.isInterruptionRequested():
            self.scan_finished.emit(results)


class WatchFolderManager(QObject):
    """Координатор нескольких папок автоконвертации с QFileSystemWatcher, fallback-опросом и debounce."""

    status_changed = pyqtSignal()
    activity_changed = pyqtSignal(bool, str)
    batch_completed = pyqtSignal(dict)
    folder_error = pyqtSignal(str, str)

    def __init__(
        self,
        *,
        base_dir,
        get_fbc_cmd,
        get_app_settings,
        fbc_config_path,
        css_path,
        fonts_dir,
        presets_dir,
        app_name="FBC GUI",
        app_version="",
        poll_interval_ms=5000,
        stability_interval_ms=1500,
        parent=None,
    ):
        super().__init__(parent)
        self.base_dir = base_dir
        self._get_fbc_cmd = get_fbc_cmd
        self._get_app_settings = get_app_settings
        self.fbc_config_path = fbc_config_path
        self.css_path = css_path
        self.fonts_dir = fonts_dir
        self.presets_dir = presets_dir
        self.app_name = app_name
        self.app_version = app_version

        self.state_store = WatchStateStore(os.path.join(base_dir, WATCH_STATE_FILENAME) if base_dir else "")
        self._rules = []
        self._paused = False
        self._running = False
        self._rule_statuses = {}
        self._pending_files = {}  # (rule_id, norm_path) -> {"path": str, "size": int, "mtime": float, "stable": int}
        self._in_flight_files = set()  # {(rule_id, norm_path)} файлов в очереди или обработке
        self._retry_backoff = {}  # (rule_id, norm_path) -> {"attempts": int, "next_retry_at": float}
        self._job_queue = deque()
        self._active_worker = None
        self._scan_worker = None
        self._active_label = ""
        self.recent_history = deque(maxlen=10)

        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.directoryChanged.connect(self._on_directory_changed)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(int(poll_interval_ms))
        self._poll_timer.timeout.connect(self.scan_all_rules)

        self._stability_timer = QTimer(self)
        self._stability_timer.setInterval(int(stability_interval_ms))
        self._stability_timer.timeout.connect(self._check_pending_stability)

    @property
    def rules(self):
        return list(self._rules)

    @property
    def paused(self):
        return self._paused

    @property
    def is_busy(self):
        return self._active_worker is not None and self._active_worker.isRunning()

    def active_rules_count(self):
        return sum(1 for r in self._rules if r.get("enabled"))

    def get_rule_status(self, rule_id):
        return self._rule_statuses.get(rule_id, "disabled")

    def set_rules(self, rules):
        self._rules = normalize_watch_rules(rules)
        valid_ids = {r["id"] for r in self._rules}
        self.state_store.prune_unknown_rules(valid_ids)
        for k in list(self._retry_backoff.keys()):
            if k[0] not in valid_ids:
                self._retry_backoff.pop(k, None)
        self._rewatch_directories()
        if self._running and not self._paused:
            self.scan_all_rules()
        self.status_changed.emit()

    def set_paused(self, paused):
        self._paused = bool(paused)
        if not self._paused and self._running:
            self.scan_all_rules()
            self._start_next_job()
        self.status_changed.emit()

    def start(self):
        self._running = True
        self._rewatch_directories()
        if not self._poll_timer.isActive():
            self._poll_timer.start()
        if not self._paused:
            self.scan_all_rules()
        self.status_changed.emit()

    def stop(self, timeout_ms=3000):
        from core.workers import stop_qthread_safely

        self._running = False
        self._poll_timer.stop()
        self._stability_timer.stop()
        dirs = self._fs_watcher.directories()
        if dirs:
            self._fs_watcher.removePaths(dirs)
        self._job_queue.clear()
        self._pending_files.clear()
        self._in_flight_files.clear()
        self._retry_backoff.clear()
        scan_worker = self._scan_worker
        self._scan_worker = None
        if scan_worker is not None:
            stop_qthread_safely(scan_worker, timeout_ms=timeout_ms, label="WatchScanWorker")
        active_worker = self._active_worker
        self._active_worker = None
        if active_worker is not None:
            stop_qthread_safely(active_worker, timeout_ms=timeout_ms, label="WatchJobWorker")
        self.status_changed.emit()

    def _rewatch_directories(self):
        current = self._fs_watcher.directories()
        if current:
            self._fs_watcher.removePaths(current)
        self._rule_statuses.clear()

        watch_dirs = []
        for rule in self._rules:
            rid = rule["id"]
            if not rule.get("enabled"):
                self._rule_statuses[rid] = "disabled"
                continue
            folder = rule.get("folder", "")
            if not folder or not os.path.isdir(folder):
                self._rule_statuses[rid] = "missing"
                continue
            try:
                os.listdir(folder)
            except PermissionError:
                self._rule_statuses[rid] = "permission_error"
                self.folder_error.emit(rid, folder)
                continue
            except OSError:
                self._rule_statuses[rid] = "missing"
                continue

            self._rule_statuses[rid] = "paused" if self._paused else "active"
            watch_dirs.append(folder)
            if rule.get("recursive"):
                added_subdirs = 0
                for root_d, subdirs, _ in os.walk(folder):
                    subdirs[:] = [
                        d for d in subdirs
                        if not d.startswith(".") and d not in WATCH_INTERNAL_SUBDIRS
                    ]
                    for sd in subdirs:
                        if added_subdirs >= MAX_WATCHED_SUBDIRS:
                            subdirs[:] = []
                            logger.warning(
                                "Превышен лимит отслеживаемых подпапок (%d) для '%s'; остальное покроет фоновый опрос",
                                MAX_WATCHED_SUBDIRS,
                                folder,
                            )
                            break
                        watch_dirs.append(os.path.join(root_d, sd))
                        added_subdirs += 1
                    if added_subdirs >= MAX_WATCHED_SUBDIRS:
                        break

        if watch_dirs and self._running:
            self._fs_watcher.addPaths(list(dict.fromkeys(watch_dirs)))

    def _on_directory_changed(self, changed_dir):
        if not self._running or self._paused:
            return
        norm_changed = os.path.normcase(os.path.abspath(changed_dir))
        matched_recursive = []
        for rule in self._rules:
            if not rule.get("enabled"):
                continue
            rfolder = rule.get("folder", "")
            if not rfolder:
                continue
            norm_root = os.path.normcase(os.path.abspath(rfolder))
            if norm_changed == norm_root or (rule.get("recursive") and norm_changed.startswith(norm_root + os.sep)):
                if rule.get("recursive"):
                    matched_recursive.append(rule)
                else:
                    self._scan_rule(rule)
        if matched_recursive:
            self._start_background_scan(matched_recursive)

    def scan_all_rules(self):
        if not self._running or self._paused:
            return
        recursive_rules = []
        for rule in self._rules:
            if not rule.get("enabled"):
                continue
            if rule.get("recursive"):
                recursive_rules.append(rule)
            else:
                self._scan_rule(rule)
        if recursive_rules:
            self._start_background_scan(recursive_rules)

    def _start_background_scan(self, rules):
        if not rules or not self._running or self._paused:
            return
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        worker = WatchScanWorker(rules, parent=self)
        self._scan_worker = worker
        worker.scan_finished.connect(self._on_background_scan_finished)
        worker.start()

    def _on_background_scan_finished(self, results):
        worker = self._scan_worker
        self._scan_worker = None
        if worker is not None:
            try:
                worker.wait(500)
                worker.deleteLater()
            except RuntimeError:
                pass
        if not self._running or self._paused:
            return
        for res in (results or []):
            rid = res.get("rule_id", "")
            folder = res.get("folder", "")
            status = res.get("status", "")
            if status == "missing":
                self._rule_statuses[rid] = "missing"
                continue
            if status == "permission_error":
                if self._rule_statuses.get(rid) != "permission_error":
                    self._rule_statuses[rid] = "permission_error"
                    self.folder_error.emit(rid, folder)
                continue
            if status != "ok":
                continue
            self._ingest_rule_candidates(rid, folder, res.get("files") or [])

    def _iter_rule_files(self, rule):
        root = rule["folder"]
        if rule.get("recursive"):
            for cur_dir, subdirs, files in os.walk(root):
                subdirs[:] = [
                    d for d in subdirs
                    if not d.startswith(".") and d not in WATCH_INTERNAL_SUBDIRS
                ]
                for fname in sorted(files):
                    yield os.path.join(cur_dir, fname)
        else:
            for fname in sorted(os.listdir(root)):
                yield os.path.join(root, fname)

    def _scan_rule(self, rule):
        rid = rule["id"]
        folder = rule.get("folder", "")
        if not folder or not os.path.isdir(folder):
            self._rule_statuses[rid] = "missing"
            return
        try:
            candidates = list(self._iter_rule_files(rule))
        except PermissionError:
            if self._rule_statuses.get(rid) != "permission_error":
                self._rule_statuses[rid] = "permission_error"
                self.folder_error.emit(rid, folder)
            return
        except OSError:
            return
        self._ingest_rule_candidates(rid, folder, candidates)

    def _ingest_rule_candidates(self, rid, folder, candidates):
        self._rule_statuses[rid] = "paused" if self._paused else "active"
        found_new = False
        for fp in candidates:
            if is_ignored_watch_path(fp, folder) or not is_supported_watch_book(fp):
                continue
            try:
                st = os.stat(fp)
            except OSError:
                continue
            if self.state_store.is_processed(rid, fp, st.st_size, st.st_mtime):
                continue
            key = (rid, os.path.normcase(os.path.abspath(fp)))
            if key in self._in_flight_files:
                continue
            backoff = self._retry_backoff.get(key)
            if backoff and time.monotonic() < backoff.get("next_retry_at", 0.0):
                continue
            if key not in self._pending_files:
                self._pending_files[key] = {
                    "path": fp,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "stable": 0,
                }
                found_new = True

        if found_new and not self._stability_timer.isActive():
            self._stability_timer.start()

    def _check_pending_stability(self):
        if not self._pending_files:
            self._stability_timer.stop()
            return
        if self._paused or not self._running:
            return

        ready_by_rule = {}
        to_remove = []

        for key, info in list(self._pending_files.items()):
            rid, _ = key
            fp = info["path"]
            if not os.path.isfile(fp):
                to_remove.append(key)
                continue
            try:
                st = os.stat(fp)
            except OSError:
                to_remove.append(key)
                continue

            if st.st_size == info["size"] and abs(st.st_mtime - info["mtime"]) < 0.01:
                info["stable"] += 1
            else:
                info["size"] = st.st_size
                info["mtime"] = st.st_mtime
                info["stable"] = 0

            if info["stable"] >= 1 and is_file_readable_and_ready(fp):
                ready_by_rule.setdefault(rid, []).append(fp)
                to_remove.append(key)

        for key in to_remove:
            self._pending_files.pop(key, None)
        if not self._pending_files:
            self._stability_timer.stop()

        if ready_by_rule:
            rules_by_id = {r["id"]: r for r in self._rules if r.get("enabled")}
            for rid, paths in ready_by_rule.items():
                rule = rules_by_id.get(rid)
                if rule and paths:
                    sorted_paths = sorted(paths)
                    for fp in sorted_paths:
                        self._in_flight_files.add((rid, os.path.normcase(os.path.abspath(fp))))
                    self._job_queue.append((copy.deepcopy(rule), sorted_paths))
            self._start_next_job()

    def _start_next_job(self):
        if self._paused or not self._running:
            return
        if self._active_worker is not None and self._active_worker.isRunning():
            return
        if not self._job_queue:
            self._active_label = ""
            self.activity_changed.emit(False, "")
            self.status_changed.emit()
            return

        rule, filepaths = self._job_queue.popleft()
        self._active_label = rule.get("name") or os.path.basename(rule["folder"])
        worker = WatchJobWorker(
            rule,
            filepaths,
            fbc_cmd=self._get_fbc_cmd(),
            base_config_path=self.fbc_config_path,
            base_css_path=self.css_path,
            fonts_dir=self.fonts_dir,
            presets_dir=self.presets_dir,
            base_dir=self.base_dir,
            base_app_settings=self._get_app_settings(),
            app_name=self.app_name,
            app_version=self.app_version,
            parent=self,
        )
        self._active_worker = worker
        worker.job_finished.connect(self._on_job_finished)
        self.activity_changed.emit(True, self._active_label)
        self.status_changed.emit()
        worker.start()

    def _on_job_finished(self, summary):
        worker = self._active_worker
        self._active_worker = None
        worker_paths = list(getattr(worker, "filepaths", None) or []) if worker is not None else []
        if worker is not None:
            try:
                worker.wait(500)
                worker.deleteLater()
            except RuntimeError:
                pass

        rule_id = summary.get("rule_id", "")
        for fp in worker_paths:
            self._in_flight_files.discard((rule_id, os.path.normcase(os.path.abspath(fp))))
        for rec in summary.get("processed_sources") or []:
            if rec.get("path"):
                self._in_flight_files.discard((rule_id, os.path.normcase(os.path.abspath(rec["path"]))))
        batch_state_entries = []
        now_mono = time.monotonic()
        now_ts = int(time.time())
        for rec in summary.get("processed_sources") or []:
            bkey = (rule_id, os.path.normcase(os.path.abspath(rec["path"])))
            # Если доставка на ридер не удалась (например, ридер не подключён), применяем экспоненциальный backoff
            if not rec.get("ok") and summary.get("delivery_mode") == "device_sync":
                prev = self._retry_backoff.get(bkey) or {}
                attempts = int(prev.get("attempts", 0)) + 1
                delay = min(WATCH_RETRY_MAX_SEC, WATCH_RETRY_BASE_SEC * (2 ** (attempts - 1)))
                self._retry_backoff[bkey] = {
                    "attempts": attempts,
                    "next_retry_at": now_mono + delay,
                }
                continue
            self._retry_backoff.pop(bkey, None)
            batch_state_entries.append({
                "path": rec["path"],
                "size": rec["size"],
                "mtime": rec["mtime"],
                "status": "ok" if rec.get("ok") else "error",
                "error": rec.get("error", ""),
            })
            self.recent_history.appendleft({
                "rule_name": summary.get("rule_name", ""),
                "filename": os.path.basename(rec["path"]),
                "ok": bool(rec.get("ok")),
                "error": rec.get("error", ""),
                "timestamp": now_ts,
            })
        if batch_state_entries:
            self.state_store.mark_processed_batch(rule_id, batch_state_entries)

        if not summary.get("cancelled"):
            self.batch_completed.emit(summary)

        self._start_next_job()

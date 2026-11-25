# FBC GUI v2.9.1 (Build 77) — Release Notes

## Русская версия (RU)

**Версия 2.9.1 (Ноябрь 2026) — Усиление безопасности, стабильность FB2/CSS/превью, локализации и потокобезопасность • сборка 77**

### ✨ Новые возможности и усиление безопасности

- **Безопасность предпросмотра книг (`core/fb2_processor.py`, `core/css_preview.py`, `ui/native_webview.py`)**:
  - Валидация MIME-типа встроенных обложек по белому списку (`image/jpeg`, `image/png`, `image/webp`, `image/gif`) и экранирование атрибута `src` в HTML-превью.
  - Отключение JavaScript в `WindowsWebView2Widget` по аналогии с macOS `WKWebView` и `QWebEngineView`.
- **Строгий HTTPS и защита загрузок (`core/updater.py`, `core/fbc_manager.py`)**:
  - Требование защищённого протокола `https://` для манифеста обновлений, установщиков и архивов `fb2cng`.
  - Очистка имени актива через `os.path.basename`, лимит размера HTTP-потока и отказ от кэширования локального бинарника в `fbc_verified.json` без подтверждённого хеша.
- **Умное разрешение конфликтов имён и автообновление локализаций**:
  - При пакетной конвертации книги с одинаковым целевым именем автоматически получают суффиксы `(2)`, `(3)` и не перезаписывают друг друга.
  - Автоматическое обновление встроенных `locales/*.json` при апгрейде приложения и отложенное сохранение (debounce 400 мс) для полей SMTP и экрана.
  - Обобщённое автоподключение начертаний Bold/Italic в `ebook_styles.css` для любых семейств шрифтов.

#### _Исправления ошибок и техническое обслуживание_

- _Сохранение исходных POSIX-прав доступа в `atomic_write_text` и `save_book_changes_to_source` вместо сброса до `0600`._
- _Исправления `update_fb2_xml`: создание отсутствующего `<book-title>`, очистка дочерних тегов `body/title/p`, согласование `id`/расширения обложки и удаление осиротевшего `<binary>`._
- _Исправления предпросмотра и UI: формирование `file:///` через `Path.as_uri()` (пробелы, кириллица, Windows), нумерация страниц (`2` → `3`, `4`), обновление живого превью имени в `BookEditDialog` при правке автора, корректная работа `move_selected_rows` при активном фильтре._
- _Стабильность на Windows и в сети: сборка SMTP-вложений по одному пакету, циклическое чтение IPC в `SingleInstanceManager`, закрытие `HTTPError` (без `ResourceWarning`), очистка временных папок обновлений при сбое, `chcp 65001` и таймаут 60 с в `.bat`-скрипте портативного обновления, явный `utf-8` для `fbc`._
- _Убраны побочные эффекты при импорте `fbc_gui.py`, согласованы зависимости `requirements.txt` и проверка `$LASTEXITCODE` в CI; набор юнит-тестов расширен до 93 тестов._

---

## English Version (EN)

**Version 2.9.1 (November 2026) — Security Hardening, FB2/CSS/Preview Fixes, Localization Refresh, CI & Thread-Safety Improvements • build 77**

### ✨ New Features & Security Hardening

- **Book Preview Security (`core/fb2_processor.py`, `core/css_preview.py`, `ui/native_webview.py`)**:
  - Whitelisted embedded cover MIME types (`image/jpeg`, `image/png`, `image/webp`, `image/gif`) and HTML-escaped cover `src` attributes in preview HTML.
  - Disabled JavaScript in `WindowsWebView2Widget` to match macOS `WKWebView` and `QWebEngineView`.
- **Strict HTTPS & Download Hardening (`core/updater.py`, `core/fbc_manager.py`)**:
  - Enforced `https://` for update manifests, installers, and `fb2cng` release archives.
  - Sanitized asset names via `os.path.basename`, enforced HTTP download size caps, and stopped caching unhashed local binaries in `fbc_verified.json`.
- **Same-Batch Collision Disambiguation & Localization Refresh**:
  - Books producing identical target filenames in the same batch now automatically receive `(2)`, `(3)` suffixes instead of overwriting each other.
  - Bundled `locales/*.json` now refresh automatically on frozen-app upgrades, SMTP/screen fields use 400 ms debounced saves, and Bold/Italic `@font-face` discovery works for any font family.

#### _Bug Fixes & Maintenance_

- _Preserved original POSIX file permissions in `atomic_write_text` and `save_book_changes_to_source` instead of resetting to `0600`._
- _Fixed `update_fb2_xml` to create missing `<book-title>`, clear child elements on `body/title/p` updates, match cover `id`/extension to MIME type, and remove orphaned cover `<binary>` nodes._
- _Fixed preview & UI edge cases: `Path.as_uri()` for font URLs, page numbering (`2` → `3`, `4`), live filename preview in `BookEditDialog` on author edits, and `move_selected_rows` with active filters and sorting._
- _Hardened Windows & networking: single-batch SMTP assembly, looped IPC reads in `SingleInstanceManager`, closed `HTTPError` objects, temp-dir cleanup on failed downloads, `chcp 65001` & 60 s timeout in Windows portable `.bat` updater, explicit `utf-8` for `fbc` subprocesses._
- _Removed import-time side effects in `fbc_gui.py`, aligned `requirements.txt` & CI PowerShell `$LASTEXITCODE` checks, and expanded unit tests to 93 passing tests._

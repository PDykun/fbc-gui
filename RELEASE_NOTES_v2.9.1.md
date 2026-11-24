# FBC GUI v2.9.1 (Build 76) — Release Notes

## Русская версия (RU)

**Версия 2.9.1 (Ноябрь 2026) — Усиление безопасности, исправление работы с FB2/CSS/превью, локализациями, CI и потокобезопасностью • сборка 76**

### Что изменилось с версии 2.9 до 2.9.1

- **Безопасность предпросмотра книг (`core/fb2_processor.py`, `core/css_preview.py`, `ui/native_webview.py`)**:
  - Добавлена валидация MIME-типа встроенных обложек по белому списку (`image/jpeg`, `image/png`, `image/webp`, `image/gif`) при формировании data-URI и экранирование атрибута `src` в HTML-превью.
  - В `WindowsWebView2Widget` добавлено отключение JavaScript (по аналогии с macOS `WKWebView` и `QWebEngineView`).
- **Усиление проверки обновлений и движка `fb2cng` (`core/updater.py`, `core/fbc_manager.py`, `fbc_gui.py`)**:
  - Для манифеста обновлений, скачивания установщиков и архивов `fb2cng` теперь требуется строго защищённый протокол `https://`.
  - Имя скачиваемого актива `fb2cng` очищается через `os.path.basename`, ограничен размер HTTP-потока при скачивании архива и добавлен безопасный разбор `Content-Length`; убрано кэширование локального бинарника в `fbc_verified.json` без подтверждённой контрольной суммы; закрываются перехваченные `HTTPError` (устранено `ResourceWarning`); при ошибке загрузки обновления удаляется временная папка.
- **Обработка FB2, права файлов и пакетная конвертация (`core/fb2_processor.py`, `core/config.py`, `core/workers.py`, `core/email_sender.py`)**:
  - `atomic_write_text` и `save_book_changes_to_source` сохраняют исходные права доступа файлов на POSIX вместо сброса до `0600`.
  - В `update_fb2_xml` исправлено создание отсутствующего `<book-title>`, очистка дочерних тегов при обновлении `body/title/p`, согласование `id`/расширения новой обложки и удаление осиротевшего старого `<binary>`.
  - При пакетной конвертации книги с одинаковым целевым именем больше не перезаписывают друг друга (автоматически добавляется суффикс `(2)`, `(3)` и т.д.).
  - В `email_sender.py` письма с вложениями собираются по одному пакету внутри цикла отправки, без загрузки всех вложений в RAM одновременно; в `SingleInstanceManager` реализовано циклическое чтение IPC-сообщений до конца потока.
- **CSS, предпросмотр и интерфейс (`core/css_preview.py`, `ui/dialogs.py`, `fbc_gui.py`)**:
  - URL локальных шрифтов в превью формируются через `Path.as_uri()` (корректная работа с пробелами, кириллицей и путями Windows); автоподключение начертаний Bold/Italic в `ebook_styles.css` обобщено для любых семейств шрифтов; исправлена нумерация страниц в превью (`2` -> `3`, `4`).
  - В `BookEditDialog` живое превью имени файла теперь обновляется также при изменении фамилии, имени и отчества автора.
  - Автоматическое обновление встроенных локализаций (`locales/*.json`) при апгрейде установленного приложения; отложенное сохранение (debounce 400 мс) для полей SMTP и экрана; убраны побочные эффекты при импорте `fbc_gui.py`; в `ConversionWorker` передаются копии записей книг, а `move_selected_rows` корректно работает при активном фильтре и сохраняет возможность сортировки.
- **Стабильность на Windows (`core/updater.py`, `core/fb2_processor.py`)**:
  - В `.bat`-скрипт портативного обновления Windows добавлены `chcp 65001 >NUL`, экранирование `%` в путях, точное сопоставление PID через `tasklist /FO CSV /NH | findstr` и ограничение ожидания (60 с).
  - Для процесса `fbc` явно задана кодировка `utf-8` (`errors="replace"`).
- **Сборка, зависимости и техдолг (`requirements.txt`, `.github/workflows/release.yml`, `setup_and_build_win.bat`, `ui/theme.py`, `core/presets.py`)**:
  - Согласованы ограничения версий зависимостей (включая `keyring` и совместимые диапазоны для fallback-установки на `win_arm64` и в `setup_and_build_win.bat`), исправлена проверка `$LASTEXITCODE` в PowerShell-шаге CI.
  - Удалены неиспользуемые импорты и лишний реэкспорт диалогов из `ui/theme.py`; добавлена проверка типов для `css_ui_state` и списков токенов при загрузке пресетов.
- **Тесты (`tests/`)**:
  - Набор юнит-тестов расширен до **93 тестов** (включая автоматическую проверку паритета ключей и плейсхолдеров `locales/ru.json` / `locales/en.json`, edge-кейсы пресетов, UI-превью `BookEditDialog`, валидацию `smtp_security` и отмену SMTP, сброс устаревших `assets` в `update_version_json.py`, деградацию без Pillow/lxml/QtNetwork, лимит скачивания и экранирование `findstr`; все проходят без ошибок и предупреждений).

---

## English Version (EN)

**Version 2.9.1 (November 2026) — Security Hardening, FB2/CSS/Preview Fixes, Localization Refresh, CI & Thread-Safety Improvements • build 76**

### Changes from v2.9 to v2.9.1

- **Book Preview Security (`core/fb2_processor.py`, `core/css_preview.py`, `ui/native_webview.py`)**:
  - Whitelisted embedded cover MIME types (`image/jpeg`, `image/png`, `image/webp`, `image/gif`) for data URIs and HTML-escaped the cover `src` attribute in preview HTML.
  - Disabled JavaScript in `WindowsWebView2Widget` to match macOS `WKWebView` and `QWebEngineView`.
- **Auto-Updater & `fb2cng` Verification Hardening (`core/updater.py`, `core/fbc_manager.py`, `fbc_gui.py`)**:
  - Enforced `https://` for update manifests, installer downloads, and `fb2cng` release archives.
  - Sanitized downloaded `fb2cng` filenames with `os.path.basename`, enforced an HTTP download size limit and safe `Content-Length` parsing, stopped caching unhashed local binaries in `fbc_verified.json`, closed caught `HTTPError` objects (eliminating `ResourceWarning`), and cleaned up temporary update directories on download errors.
- **FB2 Processing, File Permissions & Batch Conversion (`core/fb2_processor.py`, `core/config.py`, `core/workers.py`, `core/email_sender.py`)**:
  - Preserved original POSIX file permissions in `atomic_write_text` and `save_book_changes_to_source` instead of resetting to `0600`.
  - Fixed `update_fb2_xml` to create missing `<book-title>`, clear child elements when updating `body/title/p`, match cover `id`/extension to MIME type, and remove orphaned cover `<binary>` elements.
  - Prevented same-batch filename collisions in `convert_book_file` by appending `(2)`, `(3)`, etc. when multiple books produce the same target name.
  - Built SMTP attachment messages one batch at a time in `email_sender.py` to avoid loading all attachments into RAM at once, and updated `SingleInstanceManager` to read IPC payloads in a loop.
- **CSS, Preview & UI (`core/css_preview.py`, `ui/dialogs.py`, `fbc_gui.py`)**:
  - Generated preview font `file:///` URLs via `Path.as_uri()` (fixing spaces, non-ASCII paths, and Windows paths), generalized Bold/Italic `@font-face` discovery in `generate_css_content`, and fixed preview page numbering (`2` -> `3`, `4`).
  - Connected `BookEditDialog` live target filename preview to author fields (`last`, `first`, `mid`).
  - Refreshed bundled `locales/*.json` on frozen-app upgrades, debounced (400 ms) SMTP/screen settings saves, removed import-time side effects in `fbc_gui.py`, passed copied book dicts to `ConversionWorker`, tracked the conversion progress dialog on shutdown, and fixed `move_selected_rows` with active filters and column sorting.
- **Windows Stability (`core/updater.py`, `core/fb2_processor.py`)**:
  - Hardened the Windows portable updater `.bat` script with `chcp 65001 >NUL`, `%` escaping, exact CSV PID matching, and a 60-second wait timeout.
  - Explicitly set `encoding="utf-8", errors="replace"` for `fbc` subprocess output decoding.
- **Build, Dependencies & Tech Debt (`requirements.txt`, `.github/workflows/release.yml`, `setup_and_build_win.bat`, `ui/theme.py`, `core/presets.py`)**:
  - Aligned dependency constraints (including `keyring` and compatible bounds for `win_arm64` fallback and `setup_and_build_win.bat`), and fixed PowerShell `$LASTEXITCODE` checks in CI.
  - Removed unused imports and redundant dialog re-exports from `ui/theme.py`; hardened type checks for `css_ui_state` and token lists in preset loading.
- **Tests (`tests/`)**:
  - Expanded the unit test suite to **93 tests** (including automated `locales/ru.json` / `locales/en.json` key & placeholder parity, preset edge cases, `BookEditDialog` live preview, `smtp_security` validation & SMTP cancellation, stale asset reset in `update_version_json.py`, graceful degradation without Pillow/lxml/QtNetwork, download limits, and `findstr` escaping), passing with zero warnings.

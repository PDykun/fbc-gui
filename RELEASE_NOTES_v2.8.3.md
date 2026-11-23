# FBC GUI v2.8.3 (Build 67) — Release Notes

## Русская версия (RU)

**Версия 2.8.3 (Ноябрь 2026) — Книжный разворот в предпросмотре, безопасность и стабильность • macOS и Windows (сборка 67)**

### Что изменилось с версии 2.8.2 до 2.8.3

- **Предпросмотр книги (Preview) и шрифты (`core/css_preview.py`, `core/fb2_processor.py`, `ebook_styles.css`)**:
  - Предпросмотр переработан в виде двухстраничного книжного разворота с обложкой на левой странице и титулом/началом главы на правой.
  - Обложка книги на левой странице разворота теперь отображается на всю страницу (`object-fit: cover`) с мягкой тенью корешка.
  - Исправлена изоляция разных начертаний одного семейства шрифтов (например, Regular / Bold / Italic) в `@font-face`, чтобы они не перезаписывали друг друга в WebKit и браузере.
  - Увеличен объём предпросмотра текста книги (`max_paragraphs=24`) для полноценного заполнения разворота.
- **Безопасность и защита данных (`core/config.py`, `core/fb2_processor.py`, `core/updater.py`, `core/email_sender.py`, `core/fbc_manager.py`, `fbc_gui.py`)**:
  - Хранение SMTP-пароля в macOS Keychain переведено с передачи через аргументы командной строки на защищённый ввод через `stdin` (`security -i` + `-X <hex>`).
  - Парсер `lxml` в `core/fb2_processor.py` усилен против XXE/DoS (`resolve_entities=False`, `no_network=True`, `huge_tree=False`).
  - Добавлена проверка схем URL (`http`/`https`) перед загрузкой манифестов, бинарников и открытием ссылок в браузере, а также жёсткие лимиты размера для манифеста обновлений, метаданных GitHub, распаковываемых архивов `fb2cng` и локальных IPC-сообщений.
  - Настроена проверка TLS-сертификатов через `certifi` в SMTP (`SMTP_SSL` и `STARTTLS`), обновлении и загрузке `fb2cng`; добавлена валидация диапазона SMTP-порта (`1–65535`).
- **Надёжность, атомарная запись и архитектура (`core/workers.py`, `core/presets.py`, `core/i18n.py`, `core/logger.py`, `ui/theme.py`, `ui/native_webview.py`)**:
  - Введена атомарная запись через временный файл + `fsync` + `os.replace` (`atomic_write_text`) для `settings.json`, `config.yaml`, `ebook_styles.css`, пресетов, `fbc_verified.json` и HTML-файлов предпросмотра; при повреждении `settings.json` автоматически создаётся резервная копия `.bak`.
  - Усилено управление жизненным циклом фоновых потоков при закрытии окна, смене языка и применении пресетов; добавлена защита от повторного запуска конвертации.
  - Фоновые воркеры (`FileImportWorker`, `ConversionWorker`, `TestEmailWorker`) и `SingleInstanceManager` вынесены из `fbc_gui.py` в отдельный модуль `core/workers.py`.
  - Диагностические `print()` в `core/i18n.py` и `ui/theme.py` переведены на централизованный логгер `fbc_gui.log`.
- **Сборка, CI и тесты (`.github/workflows/release.yml`, `requirements.txt`, `tests/`)**:
  - В `requirements.txt` и пайплайны сборки macOS/Windows добавлена упаковка сертификатов `certifi` (`--collect-data certifi`) и `keyring`.
  - Набор юнит-тестов расширен до **69 тестов** (добавлены `test_i18n.py`, `test_theme.py`, `test_workers.py` и новые проверки безопасности/надёжности в существующих наборах).

---

## English Version (EN)

**Version 2.8.3 (November 2026) — Book-Spread Preview, Security & Stability Hardening • macOS & Windows (build 67)**

### Changes from v2.8.2 to v2.8.3

- **Book-Spread Preview & Font Rendering (`core/css_preview.py`, `core/fb2_processor.py`, `ebook_styles.css`)**:
  - Redesigned preview as a two-page book spread with the cover on the left page and title/opening chapter on the right page.
  - Made the book cover fill the entire left page (`object-fit: cover`) with a subtle spine shadow.
  - Fixed `@font-face` isolation for font families with multiple weight/style files (Regular / Bold / Italic) so variants no longer overwrite each other in WebKit or browsers.
  - Increased extracted preview length (`max_paragraphs=24`) to populate the spread naturally.
- **Security & Data Protection (`core/config.py`, `core/fb2_processor.py`, `core/updater.py`, `core/email_sender.py`, `core/fbc_manager.py`, `fbc_gui.py`)**:
  - Switched macOS Keychain SMTP password storage from command-line arguments to `stdin` (`security -i` + `-X <hex>`).
  - Hardened `lxml` XML parsing in `core/fb2_processor.py` against XXE and entity-expansion attacks (`resolve_entities=False`, `no_network=True`, `huge_tree=False`).
  - Added strict `http`/`https` URL validation for update manifests, downloads, and browser links, plus size caps for update manifests, GitHub metadata, extracted `fb2cng` archives, and single-instance IPC payloads.
  - Enabled `certifi`-backed TLS verification for SMTP (`SMTP_SSL` and `STARTTLS`), auto-updates, and `fb2cng` downloads, and added SMTP port range validation (`1–65535`).
- **Reliability, Atomic Writes & Architecture (`core/workers.py`, `core/presets.py`, `core/i18n.py`, `core/logger.py`, `ui/theme.py`, `ui/native_webview.py`)**:
  - Added atomic writes (`atomic_write_text` via temp file + `fsync` + `os.replace`) for `settings.json`, `config.yaml`, `ebook_styles.css`, presets, `fbc_verified.json`, and preview HTML files, with automatic `.bak` backup on corrupted `settings.json`.
  - Hardened background worker lifecycle on window close, language switching, and preset application, and added a re-entry guard for conversion runs.
  - Extracted `FileImportWorker`, `ConversionWorker`, `TestEmailWorker`, and `SingleInstanceManager` from `fbc_gui.py` into `core/workers.py`.
  - Replaced diagnostic `print()` calls in `core/i18n.py` and `ui/theme.py` with centralized `fbc_gui.log` logging.
- **Build, CI & Tests (`.github/workflows/release.yml`, `requirements.txt`, `tests/`)**:
  - Added `certifi` (`--collect-data certifi`) and `keyring` to `requirements.txt` and macOS/Windows PyInstaller pipelines.
  - Expanded the unit test suite to **69 tests** (added `test_i18n.py`, `test_theme.py`, `test_workers.py`, and additional security/reliability coverage).

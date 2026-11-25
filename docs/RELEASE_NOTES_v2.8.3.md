# FBC GUI v2.8.3 (Build 67) — Release Notes

## Русская версия (RU)

**Версия 2.8.3 (Ноябрь 2026) — Книжный разворот в предпросмотре, безопасность и стабильность • macOS и Windows (сборка 67)**

### ✨ Новые возможности

- **Двухстраничный книжный разворот в предпросмотре (`core/css_preview.py`, `core/fb2_processor.py`)**:
  - Предпросмотр переработан в виде реалистичного книжного разворота с обложкой на всю левую страницу (`object-fit: cover`, мягкая тень корешка) и титулом/началом главы на правой.
  - Увеличен объём извлекаемого текста книги (`max_paragraphs=24`) для естественного заполнения разворота.
- **Усиленная безопасность данных и сети (`core/config.py`, `core/fb2_processor.py`, `core/updater.py`, `core/email_sender.py`, `core/fbc_manager.py`)**:
  - Передача SMTP-пароля в macOS Keychain через `stdin` (`security -i` + `-X <hex>`) вместо аргументов командной строки.
  - Защита парсера `lxml` от XXE/DoS (`resolve_entities=False`, `no_network=True`, `huge_tree=False`).
  - Валидация схем URL (`http`/`https`), лимиты размера загрузок и IPC, проверка TLS-сертификатов через `certifi` и валидация SMTP-порта (`1–65535`).
- **Атомарная запись конфигураций (`atomic_write_text`)**:
  - Запись через временный файл + `fsync` + `os.replace` для `settings.json`, `config.yaml`, `ebook_styles.css`, пресетов, `fbc_verified.json` и HTML-превью, с автоматическим `.bak` при повреждении `settings.json`.

#### _Исправления ошибок и техническое обслуживание_

- _Исправлена изоляция начертаний одного семейства шрифтов (Regular / Bold / Italic) в `@font-face` для WebKit и браузера._
- _Усилено управление жизненным циклом фоновых потоков при закрытии окна, смене языка и применении пресетов; добавлена защита от повторного запуска конвертации._
- _Фоновые воркеры и `SingleInstanceManager` вынесены в `core/workers.py`; диагностические `print()` переведены на `fbc_gui.log`; в сборки добавлены `certifi` и `keyring`; набор юнит-тестов расширен до 69 тестов._

---

## English Version (EN)

**Version 2.8.3 (November 2026) — Book-Spread Preview, Security & Stability Hardening • macOS & Windows (build 67)**

### ✨ New Features

- **Two-Page Book-Spread Preview (`core/css_preview.py`, `core/fb2_processor.py`)**:
  - Redesigned preview as a realistic two-page book spread with a full-bleed cover on the left (`object-fit: cover` + subtle spine shadow) and title/opening chapter on the right.
  - Increased extracted preview length (`max_paragraphs=24`) to populate the spread naturally.
- **Security & Data Protection Hardening (`core/config.py`, `core/fb2_processor.py`, `core/updater.py`, `core/email_sender.py`, `core/fbc_manager.py`)**:
  - Switched macOS Keychain SMTP password storage to `stdin` (`security -i` + `-X <hex>`).
  - Hardened `lxml` parsing against XXE/DoS (`resolve_entities=False`, `no_network=True`, `huge_tree=False`).
  - Added strict `http`/`https` URL validation, download/IPC size caps, `certifi`-backed TLS verification, and SMTP port validation (`1–65535`).
- **Atomic Configuration Writes (`atomic_write_text`)**:
  - Temp-file + `fsync` + `os.replace` writes for `settings.json`, `config.yaml`, `ebook_styles.css`, presets, `fbc_verified.json`, and preview HTML, with automatic `.bak` backup on corrupted `settings.json`.

#### _Bug Fixes & Maintenance_

- _Fixed `@font-face` isolation for multi-weight font families (Regular / Bold / Italic) in WebKit and browsers._
- _Hardened background worker lifecycle on window close, language switch, and preset apply, plus conversion re-entry guard._
- _Extracted background workers and `SingleInstanceManager` into `core/workers.py`, replaced `print()` calls with `fbc_gui.log`, bundled `certifi` & `keyring`, and expanded unit tests to 69 tests._

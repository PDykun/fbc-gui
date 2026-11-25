# FBC GUI v2.9.2 (Build 78) — Release Notes

## Русская версия (RU)

**Версия 2.9.2 (Ноябрь 2026) — Расширение тестового покрытия и очистка вывода тестов • сборка 78**

### ✨ Новые возможности

- **Расширенное тестирование пользовательских тем и обложек**:
  - Добавлена проверка сохранения пользовательского семейства тем (`theme_family`) в `load_app_settings` (`tests/test_config.py`).
  - Расширена проверка `fit_image_to_cover_size` в режиме работы без Pillow — проверяется корректное определение MIME-типа для `.jpg`, `.png`, `.webp`, `.gif` (`tests/test_fb2_processor.py`).

#### _Исправления ошибок и техническое обслуживание_

- _Подавлен побочный вывод `stdout` при проверке `update_manifest` в `tests/test_updater.py`._
- _В локальный `.gitignore` добавлена папка `habr_screenshots/`; набор юнит-тестов увеличен до 94 тестов (все проходят без ошибок и предупреждений)._

---

## English Version (EN)

**Version 2.9.2 (November 2026) — Expanded Test Coverage & Clean Test Output • build 78**

### ✨ New Features

- **Expanded Custom Theme & Cover Fallback Test Coverage**:
  - Added unit test verifying custom `theme_family` preservation in `load_app_settings` (`tests/test_config.py`).
  - Expanded `fit_image_to_cover_size` fallback tests without Pillow to cover extension-based MIME detection for `.jpg`, `.png`, `.webp`, and `.gif` (`tests/test_fb2_processor.py`).

#### _Bug Fixes & Maintenance_

- _Suppressed side-effect `stdout` output during `update_manifest` tests in `tests/test_updater.py`._
- _Added `habr_screenshots/` to local `.gitignore`; unit test suite expanded to 94 passing tests with zero warnings._

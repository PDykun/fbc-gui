# FBC GUI v2.6 (Build 50) — Release Notes

## Русская версия (RU)

**Версия 2.6 (Ноябрь 2026) — Фоновый импорт, мгновенная отмена, интеграция с ОС и расширенные настройки `fb2cng` • сборка 50**

### ✨ Новые возможности

- **Фоновый импорт и экономия памяти**: добавление больших папок и многокнижных ZIP-архивов выполняется в фоновом потоке (`FileImportWorker`) с прогресс-индикатором и отменой; сырой XML загружается с диска лениво только при открытии превью или старте конвертации.
- **Мгновенная отмена конвертации**: активные процессы `fbc` завершаются сразу после нажатия «Отмена» через `subprocess.Popen.terminate()`.
- **Интеграция с ОС («Открыть с помощью…»)**: поддержка `sys.argv`, macOS `QFileOpenEvent` (Finder / Dock drag-and-drop) и опционального пункта контекстного меню Проводника Windows в установщике Inno Setup.
- **Колонка статуса, режим `--debug` и повтор ошибок**: живые статусы (`⏳ В работе`, `✓ Готово`, `✕ Ошибка`, `⊘ Отменено`), генерация отладочных отчётов (`*_fbc-report.zip`) и кнопка **«Повторить с ошибками»**.
- **Сортировка, порядок строк и горячие клавиши**: сортировка таблицы по колонкам, перемещение строк (`Alt+↑` / `Alt+↓`) и глобальные горячие клавиши (`Cmd/Ctrl+O`, `Cmd/Ctrl+Enter`, `Cmd/Ctrl+Shift+Enter`).
- **Расширенные настройки `fb2cng`**: типографика (`text_transformations`: прямая речь, тире, диалоги), отдельная страница аннотации, размещение видимого оглавления (`toc_page.placement`), открытие с обложки (`open_from_cover`), автогенерация обложки (`cover.generate`) и `--no-cover`.

#### _Исправления ошибок и техническое обслуживание_

- _В Windows-сборку гарантированно включён `keyring` (Windows Credential Manager) с предупреждением при отсутствии защищённого хранилища._
- _Диалоговые окна вынесены в `ui/dialogs.py`; расширено покрытие модульными тестами (`tests/test_css_preview.py`, ленивый XML, отмена процессов, CLI-пути, `config.yaml`)._

---

## English Version (EN)

**Version 2.6 (November 2026) — Background Import, Instant Cancel, OS Integration & Extended `fb2cng` Controls • build 50**

### ✨ New Features

- **Background Import & Lower RAM Usage**: importing folders and multi-book ZIPs runs in a background worker (`FileImportWorker`) with a cancellable progress dialog and lazy on-demand XML loading.
- **Instant Conversion Cancellation**: clicking Cancel terminates active `fbc` subprocesses immediately via `subprocess.Popen.terminate()`.
- **Native OS Integration ("Open With")**: added `sys.argv`, macOS `QFileOpenEvent` (Finder / Dock drag-and-drop), and an optional Windows Explorer context menu entry in Inno Setup.
- **Queue Status Column, `--debug` Reports & Retry Failed**: per-book live status (`⏳ Running`, `✓ Done`, `✕ Error`, `⊘ Cancelled`), `--debug` diagnostic ZIP reports, and a **Retry Failed** button.
- **Sorting, Row Reordering & Keyboard Shortcuts**: column sorting, `Alt+↑` / `Alt+↓` row moves, and global shortcuts (`Cmd/Ctrl+O`, `Cmd/Ctrl+Enter`, `Cmd/Ctrl+Shift+Enter`).
- **Extended `fb2cng` Controls**: `text_transformations` (speech, dashes, dialogue), separate annotation page, `toc_page.placement`, `open_from_cover`, `cover.generate`, and `--no-cover`.

#### _Bug Fixes & Maintenance_

- _Bundled `keyring` (Windows Credential Manager) in Windows builds with a visible Settings warning if secure storage is unavailable._
- _Extracted dialogs into `ui/dialogs.py` and expanded unit test coverage (`tests/test_css_preview.py`, lazy XML, process cancellation, CLI paths, `config.yaml`)._

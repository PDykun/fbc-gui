# FBC GUI v2.6 (Build 50) — Release Notes & Материалы для сайта

## 1. Release Notes (RU / EN)

### Русская версия (RU)
**FBC GUI v2.6 (сборка 50) — Фоновый импорт, мгновенная отмена, интеграция с ОС и расширенные настройки `fb2cng`**
- **Фоновый импорт и экономия памяти**: добавление больших папок и многокнижных ZIP-архивов теперь выполняется в фоновом потоке (`FileImportWorker`) с прогресс-индикатором и отменой; сырой XML загружается с диска лениво — только при открытии превью или старте конвертации.
- **Мгновенная отмена конвертации**: запущенные процессы `fbc` завершаются сразу после нажатия «Отмена» через `subprocess.Popen.terminate()`, не дожидаясь окончания текущей книги.
- **Интеграция с ОС («Открыть с помощью…»)**: добавлена обработка аргументов командной строки (`sys.argv`) и событий macOS `QFileOpenEvent` (перетаскивание `.fb2`/`.zip` на иконку в Dock и «Открыть в приложении»); в установщик Windows добавлен опциональный пункт контекстного меню «Открыть в FBC GUI».
- **Безопасность SMTP на Windows**: в Windows-сборку гарантированно включён `keyring` (Windows Credential Manager), а при отсутствии защищённого хранилища в настройках отображается предупреждение.
- **Колонка статуса, режим `--debug` и повтор ошибок**: в таблицу очереди добавлена колонка статуса (`⏳ В работе`, `✓ Готово`, `✕ Ошибка` с подсказкой, `⊘ Отменено`), пункт контекстного меню для запуска с отладочным отчётом (`--debug` → `*_fbc-report.zip`) и кнопка «Повторить с ошибками» в окне результатов.
- **Сортировка, порядок строк и горячие клавиши**: включена сортировка таблицы по колонкам, перемещение выбранных строк вверх/вниз (`Alt+↑` / `Alt+↓` и через контекстное меню) и горячие клавиши (`Cmd/Ctrl+O`, `Cmd/Ctrl+Enter`, `Cmd/Ctrl+Shift+Enter`).
- **Новые настройки `fb2cng` в интерфейсе**: добавлены переключатели типографики (`text_transformations`: прямая речь, тире, диалоги), отдельной страницы аннотации, размещения видимого оглавления (`toc_page.placement`), открытия с обложки (`open_from_cover`), автогенерации обложки (`cover.generate`) и сборки без обложки (`--no-cover`).
- **Архитектура и тесты**: диалоговые окна вынесены в отдельный модуль `ui/dialogs.py`, расширено покрытие модульными тестами (`tests/test_css_preview.py`, тесты ленивого XML, отмены процессов, CLI-путей и новых опций `config.yaml`).

### English Version (EN)
**FBC GUI v2.6 (Build 50) — Background Import, Instant Cancel, OS Integration & Extended `fb2cng` Controls**
- **Background Import & Lower Memory Usage**: importing large folders and multi-book ZIP archives now runs in a background worker (`FileImportWorker`) with a cancellable progress dialog; raw FB2 XML is loaded lazily on demand for preview and conversion instead of staying in RAM.
- **Instant Conversion Cancellation**: active `fbc` subprocesses now terminate immediately when clicking Cancel via `subprocess.Popen.terminate()` instead of waiting for the current book to finish.
- **Native OS Integration ("Open With")**: added `sys.argv` and macOS `QFileOpenEvent` support (Finder "Open With" and Dock drag-and-drop for `.fb2`/`.zip`), plus an optional "Open with FBC GUI" Windows Explorer context menu entry in the Inno Setup installer.
- **Windows SMTP Credential Security**: bundled `keyring` (Windows Credential Manager) in the Windows build pipeline and added a visible warning in Settings if secure credential storage is unavailable.
- **Queue Status Column, `--debug` Reports & Retry Failed**: added a live Status column (`⏳ Running`, `✓ Done`, `✕ Error` with full error tooltip, `⊘ Cancelled`), a context-menu option to convert with `--debug` (saving `*_fbc-report.zip`), and a "Retry Failed" button in the conversion summary dialog.
- **Sorting, Row Reordering & Keyboard Shortcuts**: enabled column sorting, moving selected rows up/down (`Alt+↑` / `Alt+↓` and context menu), and global shortcuts (`Cmd/Ctrl+O`, `Cmd/Ctrl+Enter`, `Cmd/Ctrl+Shift+Enter`).
- **Extended `fb2cng` Settings**: exposed typography transformations (`text_transformations`: direct speech, dashes, dialogue), separate annotation page, visible TOC placement (`toc_page.placement`), open-from-cover, auto-generated fallback covers (`cover.generate`), and `--no-cover`.
- **Refactoring & Tests**: extracted dialog classes into `ui/dialogs.py` and expanded unit test coverage (`tests/test_css_preview.py`, lazy XML, process cancellation, startup CLI paths, and `config.yaml` round-trips).

---

## 2. Информационные блоки для размещения на сайте программы

### Блок 1: Быстрая работа с большими библиотеками и мгновенная отмена
**Заголовок (RU):** Фоновая загрузка книг без зависаний и мгновенная остановка конвертации  
**Описание (RU):**  
Добавление целых папок и многокнижных ZIP-архивов теперь работает в фоновом потоке с индикатором прогресса, а сама программа больше не держит полные XML-файлы в оперативной памяти. При нажатии «Отмена» во время пакетной конвертации активные процессы `fb2cng` останавливаются мгновенно.

**Title (EN):** Non-Blocking Background Import & Instant Cancellation  
**Description (EN):**  
Dropping large folders or multi-book ZIP archives now runs in a background thread with a progress indicator while loading raw XML lazily on demand. Clicking Cancel during batch conversion immediately terminates active `fb2cng` processes.

### Блок 2: Нативная интеграция с macOS и Windows + полный контроль очереди
**Заголовок (RU):** «Открыть с помощью FBC GUI», статусы очереди и отладочные отчёты  
**Описание (RU):**  
Открывайте `.fb2` и `.zip` прямо из Finder на macOS или контекстного меню Проводника Windows. В таблице появилась колонка статуса для каждой книги, сортировка, перемещение строк (`Alt+↑`/`Alt+↓`), горячие клавиши, кнопка «Повторить с ошибками» и запуск проблемных книг с флагом `--debug`.

**Title (EN):** Native OS Integration, Live Queue Status & Debug Reports  
**Description (EN):**  
Open `.fb2` and `.zip` files directly from macOS Finder or the Windows Explorer context menu. Track per-book conversion status live in the queue, reorder rows with `Alt+↑`/`Alt+↓`, use keyboard shortcuts, retry only failed books, or run `--debug` diagnostics on tricky files.

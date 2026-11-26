# FBC GUI v2.11 (build 115)

## Русская версия

**Режим Watch Folder (папки автоконвертации), системный трей / macOS Menu Bar, оптимизация иллюстраций и имитация экранов E Ink, объединение книг FB2 в омнибус, автоопределение ридеров и обновлённый интерфейс.**

**✨ Новые возможности**
- **Режим Watch Folder (папки автоконвертации)**: можно назначить одну или несколько папок одновременно (например, `~/Downloads/ToKindle` и `~/Downloads/ToKobo`) и связать каждую со своим пресетом конвертации, способом доставки (папка, электронная почта или ридер) и действием с исходником (`Processed/`, оставить на месте или переместить в Корзину). Новые `.fb2` и `.zip` обрабатываются в фоне изолированно с защитой от недокачанных файлов (`.crdownload`, `.part`, `.tmp`).
- **Системный трей Windows и macOS Menu Bar, уведомления и автозапуск**: значок со статусом наблюдения, быстрым открытием окна, паузой/возобновлением, списком отслеживаемых папок и историей; опция сворачивания в трей при закрытии окна, скрытие значка из Dock на macOS, сводные системные уведомления ОС и опциональный автозапуск при входе в систему (по умолчанию выключен).
- **Оптимизация иллюстраций и обложек под экраны E Ink + имитация E Ink в превью**: на вкладке «Стили» добавлен выбор профиля экрана ридера (`Выкл (оригинал)`, `Ч/Б E Ink (Carta 1200/1300)`, `Ч/Б E Ink — 16 градаций (дизеринг)`, `Цветной E Ink (Kaleido 3 — 4096 цветов)`, `Цветной E Ink (Gallery 3 / Canvas Color)`), синхронизированный со всеми 8 встроенными пресетами устройств. В превью добавлена кнопка **«Имитация экрана E Ink»** для оценки вида обложки и страниц на физическом экране ридера.
- **Объединение книг FB2 в один том (Омнибус)**: пункт контекстного меню **«Объединить в один том (N)...»** собирает выбранные книги в единый валидный `.fb2` с общим оглавлением, аннотацией со списком томов и автоматической изоляцией внутренних ID, сносок и иллюстраций.
- **Автоопределение подключённых USB-ридеров и облачных папок Kobo**: кнопка **«Найти ридер»** в секции доставки на ридер автоматически обнаруживает подключённые устройства (Kobo, Kindle, PocketBook, ONYX BOOX) и локальные облачные папки Kobo.
- **Обновлённый интерфейс вкладок и конструктора шаблонов**:
  - Вкладки в модальных диалогах «Инспектор структуры FB2» и «Редактирование книги» переведены на стиль **«сегментированная капсула»** во всех 4 QSS-темах (`Modern` / `Golden`, светлая и тёмная) с высокой контрастностью текста.
  - Исправлено перетаскивание плашек в конструкторах шаблонов имени файла и заголовка: центрирование под курсором, скруглённый силуэт капсулы, курсор сжатой руки и вертикальный индикатор точного места вставки.

*_Исправления ошибок и техническое обслуживание_*
- *Исправлено падение приложения при удалении наблюдаемой папки (Watch Folder): в диалог подтверждения `show_themed_confirm` передан текст кнопки подтверждения и добавлено безопасное значение по умолчанию.*
- *Исправлена ошибка конвертации на Windows (`The path cannot be traversed because it contains an untrusted mount point`): вместо симлинков во временной рабочей папке `fbc` теперь используется копирование `ebook_styles.css` и каталога `fonts` (на Windows), а путь временного каталога раскрывается через `os.path.realpath`.*
- *Усилена безопасность и стабильность: проверка разрешённых хостов в автообновлении, изоляция HTML-превью во временном каталоге (`WKWebView` / `WebView2`), предварительная проверка превышения лимита размера вложений SMTP, таймауты обращений к macOS Keychain, защита от выхода за пределы целевого каталога в организаторе FB2 и отклонение `DOCTYPE/ENTITY`.*
- *Ускорен поиск и обновление строк таблицы очереди (`O(1)`-индекс), выделен единый модуль метаданных `core/version.py`, добавлены модули `core/watch_folder.py`, `core/notifier.py`, `core/autostart.py`, `core/fb2/omnibus.py`, `core/image_optimizer.py`, `ui/controllers/tray_controller.py`, `ui/dialogs/watch_folder.py`.*
- *Обновлены все 8 встроенных пресетов устройств (`presets_defaults/`), конфигурация сборки и CI (`.github/workflows/release.yml`, иконки трея и Menu Bar), удалены неиспользуемые импорты (`ruff`), расширен набор юнит-тестов до 192 тестов (включая `test_watch_folder.py`, `test_image_optimizer.py`, `test_ui_smoke.py`).*

---

## English Version

**Watch Folder auto-conversion mode, Windows System Tray / macOS Menu Bar, E Ink image optimization & preview simulation, FB2 Omnibus merging, automatic USB reader detection, and UI refinements.**

**✨ New Features**
- **Watch Folder Mode (Multiple Folders)**: Configure one or more watched folders simultaneously (e.g., `~/Downloads/ToKindle` and `~/Downloads/ToKobo`), each linked to its own conversion preset, delivery method (output folder, email, or e-reader sync), and source post-action (`Processed/`, keep in place, or move to Trash). Incoming `.fb2` and `.zip` files are processed in an isolated background environment with partial-download protection (`.crdownload`, `.part`, `.tmp`).
- **Windows System Tray, macOS Menu Bar, Notifications & Autostart**: Status-aware tray/menu bar icon with quick window restore, pause/resume toggle, watched folder shortcuts, and recent history; optional minimize-to-tray on close, macOS Dock icon hiding, coalesced native OS notifications, and opt-in launch at system login (disabled by default).
- **E Ink Image Optimization & Display Simulation**: Added an extensible **Reader Display** profile selector in **Styles** (`Off (Original)`, `B&W E Ink (Carta 1200/1300)`, `B&W E Ink — 16 Gray Levels (Dithered)`, `Color E Ink (Kaleido 3 — 4096 colors)`, `Color E Ink (Gallery 3 / Canvas Color)`), synchronized across all 8 built-in device presets. Preview now includes a **Simulate E Ink Display** toggle to inspect how covers and pages will render on physical e-ink screens.
- **Merge FB2 Books into an Omnibus**: Context menu action **Merge into Omnibus (N)...** combines selected books into a single valid `.fb2` volume with a unified table of contents, volume list annotation, and automatic isolation of internal IDs, footnotes, and embedded images.
- **Automatic USB Reader & Kobo Cloud Detection**: A new **Detect Reader** button in Device Delivery automatically discovers mounted USB e-readers (Kobo, Kindle, PocketBook, ONYX BOOX) and local Kobo cloud sync folders.
- **Refined Modal Tabs & Template Builder Drag-and-Drop**:
  - Modal dialog tabs in **FB2 Structure Inspector** and **Edit Book** now use a high-contrast **segmented pill** style across all 4 QSS themes (`Modern` / `Golden`, Light & Dark).
  - Improved template pill dragging in both filename and title builders: centered under the cursor, rounded capsule drag preview, closed-hand cursor, and a vertical insertion indicator line.

*_Bug Fixes & Maintenance_*
- *Fixed a crash when deleting a Watch Folder rule by passing the required confirmation button label to `show_themed_confirm` and adding a safe default.*
- *Fixed a Windows conversion error (`The path cannot be traversed because it contains an untrusted mount point`): `ebook_styles.css` and the `fonts` directory are now copied into the temporary `fbc` work folder on Windows instead of symlinked, and the temporary directory path is resolved via `os.path.realpath`.*
- *Hardened security and reliability: update host allowlist validation, isolated temporary staging for native HTML preview (`WKWebView` / `WebView2`), pre-send SMTP oversized attachment checks, macOS Keychain subprocess timeouts, path-traversal protection in FB2 Organizer, and `DOCTYPE/ENTITY` rejection.*
- *Added O(1) queue row indexing, centralized version metadata in `core/version.py`, and introduced modular components (`core/watch_folder.py`, `core/notifier.py`, `core/autostart.py`, `core/fb2/omnibus.py`, `core/image_optimizer.py`, `ui/controllers/tray_controller.py`, `ui/dialogs/watch_folder.py`).*
- *Updated all 8 built-in device presets (`presets_defaults/`), CI/packaging configuration (`.github/workflows/release.yml`, tray/Menu Bar icons), cleaned up unused imports (`ruff`), and expanded the unit test suite to 192 passing tests (including `test_watch_folder.py`, `test_image_optimizer.py`, `test_ui_smoke.py`).*

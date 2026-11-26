# FBC GUI v2.11 (build 108)

## Русская версия

**Режим Watch Folder (несколько папок автоконвертации), системный трей Windows / macOS Menu Bar, автозапуск и системные уведомления.**

**✨ Новые возможности**
- **Режим Watch Folder (папки автоконвертации)**: можно назначить одну или несколько папок одновременно (например, `~/Downloads/ToKindle` и `~/Downloads/ToKobo`) и связать каждую со своим пресетом конвертации, способом доставки (папка, электронная почта или ридер) и действием с исходником (`Processed/`, оставить на месте или переместить в Корзину).
- **Изолированная фоновая обработка**: новые `.fb2` и `.zip` обрабатываются в фоне с защитой от недокачанных файлов (игнорирование `.crdownload`, `.part`, `.tmp`, проверка стабильности размера и целостности ZIP) и не затрагивают текущие настройки, стили CSS и ручную очередь главного окна.
- **Системный трей Windows и macOS Menu Bar**: иконка со статусом наблюдения, быстрым переходом к окну, паузой/возобновлением, списком отслеживаемых папок и историей недавно обработанных книг; опция сворачивания в трей при закрытии окна.
- **Скрытие значка из Dock на macOS**: отдельная опция в Настройках позволяет скрывать иконку приложения из Dock, когда окно свёрнуто в строку меню.
- **Системные уведомления ОС**: сводные уведомления macOS и Windows о завершении пакетной обработки, доставке или ошибках доступа.
- **Автозапуск при входе в систему**: кроссплатформенная опция (`LaunchAgents` на macOS и реестр пользователя на Windows) с запуском в свёрнутом виде; по умолчанию выключена.

*_Исправления ошибок и техническое обслуживание_*
- *Добавлен модульный стек `core/watch_folder.py`, `core/notifier.py`, `core/autostart.py`, контроллер `ui/controllers/tray_controller.py` и диалог `ui/dialogs/watch_folder.py`.*
- *Обновлена сборка для macOS и Windows (включены шаблонная иконка macOS Menu Bar и многоразмерная иконка трея Windows).*
- *Расширен набор юнит-тестов (`tests/test_watch_folder.py`).*

---

## English Version

**Watch Folder auto-conversion mode (multiple simultaneous folders), Windows System Tray / macOS Menu Bar icon, optional login autostart, and OS notifications.**

**✨ New Features**
- **Watch Folder Mode (Multiple Folders)**: Configure one or more folders simultaneously (e.g., `~/Downloads/ToKindle` and `~/Downloads/ToKobo`), each linked to its own conversion preset, delivery method (output folder, email, or e-reader sync), and source post-action (`Processed/`, keep in place, or move to Trash).
- **Isolated Background Processing**: Incoming `.fb2` and `.zip` files are processed automatically with partial-download protection (ignoring `.crdownload`, `.part`, `.tmp`, waiting for file size stability and valid ZIP headers) without altering the main window's active settings, CSS, or manual queue.
- **Windows System Tray & macOS Menu Bar**: Status-aware tray/menu bar icon with quick window restore, pause/resume toggle, watched folder shortcuts, recent history, and optional minimize-to-tray on window close.
- **Hide macOS Dock Icon**: Optional setting to hide the application icon from the macOS Dock while minimized to the Menu Bar.
- **Native OS Notifications**: Coalesced macOS and Windows notifications summarizing completed batches, delivery status, or folder permission issues.
- **Launch at System Login**: Cross-platform autostart option (`LaunchAgents` on macOS, `HKCU` Run registry key on Windows) launching minimized to tray; disabled by default.

*_Bug Fixes & Maintenance_*
- *Added modular core and UI components (`core/watch_folder.py`, `core/notifier.py`, `core/autostart.py`, `ui/controllers/tray_controller.py`, `ui/dialogs/watch_folder.py`).*
- *Updated macOS and Windows packaging scripts and CI workflow to bundle template Menu Bar and tray icons.*
- *Expanded unit test suite with `tests/test_watch_folder.py`.*

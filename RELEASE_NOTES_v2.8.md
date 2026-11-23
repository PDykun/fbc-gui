# FBC GUI v2.8 (Build 52) — Release Notes & Материалы для сайта (v2.6 – v2.8)

## 1. Release Notes (RU / EN)

### Русская версия (RU)

**Версия 2.8 (Ноябрь 2026) — Релиз • macOS и Windows (сборка 52)**
- **Актуальный релизный пакет**: объединяет все улучшения версий v2.6 и v2.7, обновлённую сборку для macOS и Windows и синхронизацию метаданных обновлений (`version.json`).
- **Обновлённая документация и витрина**: на сайте опубликованы полные примечания к релизам начиная с v2.5, новые скриншоты интерфейса в светлой и тёмной темах (RU / EN) и описания всех новых возможностей.

**Версия 2.7 (Ноябрь 2026) — Пресеты, Поиск и Undo/Redo • macOS и Windows (сборка 51)**
- **Пользовательские пресеты (настройки + CSS)**: сохранение, переключение, удаление, экспорт и импорт именованных наборов параметров конвертации `fb2cng` и стилей CSS в папке `presets/` (`*.fbcpreset.json`) с автоматическим исключением паролей SMTP и локальных путей.
- **Поиск, фильтр по статусам и счётчик очереди**: панель быстрого поиска (`Cmd/Ctrl+F`, сброс по `Esc`) по имени файла, автору, серии, номеру, названию и целевому имени, фильтр статусов (**Все / Ожидают / Готовые / С ошибками**) и счётчик видимых книг (`Показано: X из Y`).
- **Отмена и повтор действий (Undo / Redo)**: полноценный стек `QUndoStack` с меню «Правка» (`Cmd/Ctrl+Z`, `Shift+Cmd+Z` / `Ctrl+Y`) и кнопками **↩ / ↪** для всех операций редактирования очереди, метаданных, обложек и порядка строк.
- **Визуальный конструктор заголовка книги (`metainformation.title_template`)**: настройка формата названия книги в библиотеке ридера с живым предпросмотром в разделе «Настройки → Текст, сноски и типографика».
- **Единый экземпляр приложения и сохранение в исходный FB2**: повторное открытие файлов передаёт книги в уже запущенное окно, а отредактированные метаданные и обложку можно записать обратно в исходный `.fb2` или `.zip`.

**Версия 2.6 (Ноябрь 2026) — Фоновый импорт, Отмена и Интеграция с ОС • macOS и Windows (сборка 50)**
- **Фоновый импорт и экономия памяти**: загрузка больших папок и многокнижных ZIP-архивов в отдельном потоке с индикатором прогресса и ленивой подгрузкой XML только при превью или конвертации.
- **Мгновенная отмена конвертации**: активные процессы `fbc` завершаются сразу после нажатия «Отмена».
- **Нативная интеграция с ОС («Открыть с помощью…»)**: открытие `.fb2` и `.zip` через Finder / перетаскивание на иконку в Dock на macOS и опциональный пункт контекстного меню Проводника Windows.
- **Безопасность SMTP на Windows**: интеграция с Windows Credential Manager (`keyring`) и предупреждение в настройках при отсутствии системного хранилища паролей.
- **Колонка статуса, режим `--debug` и повтор ошибок**: живые статусы (`⏳ В работе`, `✓ Готово`, `✕ Ошибка`, `⊘ Отменено`), запуск с отчётом `--debug` (`*_fbc-report.zip`) и кнопка «Повторить с ошибками».
- **Сортировка, перемещение строк и горячие клавиши**: сортировка по колонкам, перемещение строк (`Alt+↑`/`Alt+↓`), горячие клавиши (`Cmd/Ctrl+O`, `Cmd/Ctrl+Enter`, `Cmd/Ctrl+Shift+Enter`).
- **Расширенные настройки `fb2cng`**: типографика (`text_transformations`: прямая речь, тире, диалоги), отдельная страница аннотации, размещение оглавления (`toc_page.placement`), открытие с обложки (`open_from_cover`), автогенерация обложки (`cover.generate`) и сборка без обложки (`--no-cover`).

---

### English Version (EN)

**Version 2.8 (November 2026) — Release • macOS & Windows (build 52)**
- **Updated Release Package**: consolidates all v2.6–v2.7 capabilities into the latest macOS and Windows distribution with updated `version.json` metadata.
- **Synchronized Documentation & Website**: full release notes since v2.5, new Dark/Light and RU/EN interface screenshots, and dedicated feature cards.

**Version 2.7 (November 2026) — Presets, Queue Search & Undo/Redo • macOS & Windows (build 51)**
- **User Presets (Settings + CSS)**: save, switch, delete, export, and import named `fb2cng` + CSS presets (`*.fbcpreset.json`) while automatically stripping private SMTP credentials and local paths.
- **Queue Search, Status Filters & Visible Counter**: instant search bar (`Cmd/Ctrl+F`, `Esc` to reset), status filter (**All / Pending / Done / Failed**), and live counter (`Shown: X of Y`).
- **Full Undo / Redo**: `QUndoStack` with an Edit menu (`Cmd/Ctrl+Z`, `Shift+Cmd+Z` / `Ctrl+Y`) and **↩ / ↪** toolbar buttons covering cell edits, dialogs, batch edits, series auto-numbering, covers, row reordering, and removals.
- **Visual `title_template` Builder**: configure how book titles appear in your e-reader library (`metainformation.title_template`) with a live preview.
- **Single Instance & Save Back to Source FB2**: opening additional files routes them into the already running window, and edited metadata/covers can be written back into the original `.fb2` or `.zip`.

**Version 2.6 (November 2026) — Background Import, Instant Cancel & OS Integration • macOS & Windows (build 50)**
- **Background Import & Lower RAM Usage**: folders and multi-book ZIPs load in a background thread with a cancellable progress dialog and lazy on-demand XML loading.
- **Instant Conversion Cancellation**: clicking Cancel terminates active `fbc` processes immediately.
- **Native OS Integration ("Open With")**: Finder / Dock drag-and-drop on macOS and optional Windows Explorer context menu integration.
- **Windows SMTP Credential Security**: Windows Credential Manager (`keyring`) support with a visible Settings warning if unavailable.
- **Status Column, `--debug` Reports & Retry Failed**: per-book live status, `--debug` diagnostic ZIP reports, and a "Retry Failed" button.
- **Sorting, Row Reordering & Shortcuts**: column sorting, `Alt+↑`/`Alt+↓` row moves, and global shortcuts (`Cmd/Ctrl+O`, `Cmd/Ctrl+Enter`, `Cmd/Ctrl+Shift+Enter`).
- **Extended `fb2cng` Controls**: `text_transformations`, separate annotation page, `toc_page.placement`, `open_from_cover`, `cover.generate`, and `--no-cover`.

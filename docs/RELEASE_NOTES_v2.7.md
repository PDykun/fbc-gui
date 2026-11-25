# FBC GUI v2.7 (Build 51) — Release Notes

## Русская версия (RU)

**Версия 2.7 (Ноябрь 2026) — Пресеты, Поиск, Undo/Redo, конструктор `title_template` и сохранение в исходный FB2 • сборка 51**

### ✨ Новые возможности

- **Пользовательские пресеты (настройки + CSS, `core/presets.py`)**:
  - Сохранение, переключение, удаление, экспорт и импорт именованных наборов параметров `fb2cng` и визуальных стилей CSS (`*.fbcpreset.json`) с автоматическим исключением паролей SMTP и локальных путей.
- **Поиск, фильтр по статусам и счётчик очереди**:
  - Панель быстрого поиска (`Cmd/Ctrl+F`, сброс по `Esc`) по имени файла, автору, серии, номеру, названию и целевому имени.
  - Фильтр по статусу (**Все / Ожидают / Готовые / С ошибками**) и счётчик видимых книг (`Показано: X из Y`).
- **Полная отмена и повтор действий (Undo / Redo, `core/undo_commands.py`)**:
  - Стек `QUndoStack` с меню **«Правка»** (`Cmd/Ctrl+Z`, `Shift+Cmd+Z` / `Ctrl+Y`) и кнопками **↩ / ↪** для всех операций редактирования очереди, метаданных, обложек и порядка строк.
- **Визуальный конструктор заголовка книги (`metainformation.title_template`)**:
  - Настройка формата названия книги в библиотеке ридера с живым предпросмотром в разделе «Настройки → Текст, сноски и типографика».
- **Единый экземпляр приложения и сохранение в исходный FB2**:
  - `SingleInstanceManager` передаёт повторно открытые файлы в уже запущенное окно.
  - Запись отредактированных метаданных и обложки обратно в исходный `.fb2` или `.zip` из контекстного меню или диалога редактирования книги.

#### _Исправления ошибок и техническое обслуживание_

- _Операция конвертации выбранных строк автоматически пропускает скрытые фильтром строки._
- _Добавлены юнит-тесты для `core/presets.py`, `core/undo_commands.py`, `book_matches_filter()`, `render_title_metadata_preview()`, `save_book_changes_to_source()` и `SingleInstanceManager` (всего 38 тестов)._

---

## English Version (EN)

**Version 2.7 (November 2026) — Presets, Queue Search, Undo/Redo, Visual `title_template` Builder & Save-Back • build 51**

### ✨ New Features

- **User Presets (Settings + CSS, `core/presets.py`)**:
  - Save, switch, delete, export, and import named `fb2cng` + CSS bundles (`*.fbcpreset.json`) while automatically excluding SMTP credentials and local paths.
- **Queue Search, Status Filters & Visible Counter**:
  - Instant search bar (`Cmd/Ctrl+F`, `Esc` to reset) across filename, author, series, number, title, and output name.
  - Status filter (**All / Pending / Done / Errors**) and live counter (`Showing X of Y`).
- **Full Undo / Redo (`core/undo_commands.py`)**:
  - `QUndoStack` with an **Edit** menu (`Cmd/Ctrl+Z`, `Shift+Cmd+Z` / `Ctrl+Y`) and **↩ / ↪** toolbar buttons covering cell edits, dialogs, batch edits, auto-numbering, covers, row moves, and removals.
- **Visual `title_template` Builder (`metainformation.title_template`)**:
  - Configure how book titles appear in your e-reader library with a live preview in Settings.
- **Single Instance & Save Back to Source FB2**:
  - `SingleInstanceManager` routes newly opened files into the already running window.
  - Write edited metadata and covers back into the original `.fb2` or `.zip` from the context menu or Edit dialog.

#### _Bug Fixes & Maintenance_

- _Converting selected rows automatically skips rows hidden by the active filter._
- _Added unit tests for presets, undo commands, filtering, title template preview, save-back, and single-instance IPC (38 passing tests)._

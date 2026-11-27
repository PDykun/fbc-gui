# FBC GUI v2.13 (build 143)

## Русская версия

**Подключение локальной библиотеки в формате INPX с быстрым полнотекстовым поиском и передачей книг и целых серий в конвертер, а также настройка базового размера шрифта и адаптивные палитры цветов под экран выбранного ридера.**

**✨ Новые возможности**
- **Локальная библиотека INPX (новая вкладка «Библиотека»)**:
  - **Управление видимостью в Настройках**: в верхней части вкладки «Настройки» добавлен переключатель **«Вкладка «Библиотека»»** (по умолчанию выключен, состояние сохраняется между запусками). При включении вкладка **«Библиотека»** появляется слева от «Конвертер» в верхнем меню навигации.
  - **Подключение прямо на экране библиотеки**: выбор файла `.inpx`, кнопка **«Переиндексировать»** и статус коллекции (название, версия, количество книг FB2) интегрированы в верхнюю панель вкладки.
  - **Быстрый локальный кэш SQLite FTS5**: автоматический разбор стандартного и пользовательского (`structure.info`) формата INPX, фоновая индексация с индикатором прогресса и отменой, мгновенный поиск по автору, названию, серии и жанрам, фильтрация по языку и скрытие удалённых записей (`DEL=1`).
  - **Прямая передача в конвертер без распаковки архивов**: выбранные книги (кнопкой, двойным кликом или из контекстного меню) и **целая серия одним действием** (**«Добавить всю серию в конвертер»**) попадают напрямую в очередь конвертера с использованием нативной поддержки ZIP-записей, при этом пользователь остаётся на вкладке «Библиотека».
- **Адаптивные палитры цветов под экран ридера (вкладка «Стили»)**: выбор цвета и быстрые списки оттенков автоматически подстраиваются под выбранный профиль устройства / «Экран ридера» и режим «Оттенки серого» (16 градаций для Ч/Б E Ink Carta, палитры Kaleido 3 и Gallery 3, монохромный фильтр фона сносок, универсальный образец текста `Пример текста АаБбВв AaBbCc 123`).
- **Выбор базового размера шрифта в стилях (`1. ШРИФТЫ КНИГИ`)**: добавлен параметр **«Базовый размер шрифта»** (`По умолчанию (ридер)` и `8pt`–`24pt`) с пропорциональным масштабированием заголовков/отступов и динамическим перестроением страниц в предпросмотре.

*_Безопасность, исправления и техническое обслуживание_*
- *Реализована защита от zip-bomb при чтении `.inp`-файлов (лимит 128 МБ на запись), строгая проверка `os.path.realpath` против path traversal при поиске архивов и файлов книг рядом с `.inpx`, параметризованные SQL-запросы и атомарная подмена кэша `library_cache.sqlite`.*
- *Настройки локальной библиотеки (`library_enabled`, `library_inpx_path`) исключены из переносимых пользовательских пресетов.*
- *Обновлены русская и английская локализации (`locales/ru.json`, `locales/en.json`), расширено покрытие юнит-тестами (`tests/test_inpx_library.py`, `tests/test_controllers.py`) до 262 тестов.*

---

## English Version

**Local INPX library browser with fast full-text search and direct transfer of books and complete series to the converter, plus base book font size selection and display-aware e-reader color palettes.**

**✨ New Features**
- **Local INPX Library (new «Library» tab)**:
  - **Opt-in toggle in Settings**: added a **Library tab** switch at the top of Settings (Off by default, persisted across restarts). When enabled, the **Library** tab appears to the left of Converter in the top navigation bar.
  - **Integrated connection bar**: `.inpx` file picker, **Reindex** button, and collection status (name, version, FB2 count) live directly at the top of the Library screen.
  - **Fast local SQLite FTS5 cache**: parses standard and custom (`structure.info`) INPX catalogs in a background thread with progress and cancellation, enabling instant search across Author, Title, Series, and Genres with language filtering and hide-deleted (`DEL=1`) toggle.
  - **Zero-unpack transfer to Converter**: send selected books (via button, double-click, or context menu) or an **entire series in one click** (**Add entire series to Converter**) directly into the Converter queue using native ZIP-entry support while staying on the Library tab.
- **Display-Aware Color Palettes (Styles Tab)**: color pickers and dropdowns adapt to the selected device / Reader Display profile and Grayscale mode (16-level B&W E Ink Carta, Kaleido 3, Gallery 3, monochrome footnote background filtering, neutral preview sample `Sample text AaBbCc АаБбВв 123`).
- **Base Font Size Selector (`1. BOOK FONTS`)**: added **Base font size** (`Default (reader)` and `8pt`–`24pt`) with proportional heading/indent scaling and dynamic page reflow in Book preview.

*_Security, Bug Fixes & Maintenance_*
- *Enforced zip-bomb limits (128 MB per `.inp` entry), strict `os.path.realpath` path-traversal guards when resolving archives/files next to `.inpx`, parameterized SQL queries, and atomic SQLite cache replacement.*
- *Excluded local library paths and toggle state from portable user presets.*
- *Updated RU/EN localizations (`locales/ru.json`, `locales/en.json`) and expanded the unit test suite (`tests/test_inpx_library.py`, `tests/test_controllers.py`) to 262 tests.*

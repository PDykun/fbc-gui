# FBC GUI v2.13 (build 147)

## Русская версия

**Локальная библиотека INPX в стиле freeLib (навигация по авторам, сериям, жанрам и многополевому поиску, алфавитная линейка, иерархическое дерево книг с чекбоксами, карточка с аннотацией и обложкой) с прямой передачей книг и целых серий в конвертер, а также базовый размер шрифта и адаптивные палитры цветов под экран ридера.**

**✨ Новые возможности**
- **Локальная библиотека INPX в стиле freeLib (новая вкладка «Библиотека»)**:
  - **Управление видимостью в Настройках**: в верхней части вкладки «Настройки» добавлен переключатель **«Вкладка «Библиотека»»** (по умолчанию выключен, состояние сохраняется между запусками). При включении вкладка **«Библиотека»** появляется слева от «Конвертер» в верхнем меню навигации.
  - **Подключение прямо на экране библиотеки**: компактная верхняя строка с путём к `.inpx`, кнопками **«Выбрать INPX...»**, **«Переиндексировать»** и статусом коллекции.
  - **Двухпанельная навигация и алфавитная линейка**: слева — режимы **«Авторы»**, **«Серии»**, **«Жанры»** (с быстрым фильтром и счётчиками книг) и вкладка **«Поиск»** (многополевой поиск по названию, автору, серии и жанру; результаты показываются только после запуска поиска); справа — языковой фильтр, скрытие удалённых (`DEL=1`) и двухрядная алфавитная панель (`А–Я`, `*`, `#`, `A–Z`).
  - **Дерево книг, карточка описания и обложка**: иерархическое дерево `Автор → Серия → Книги` с колонками `Название`, `№`, `Размер`, `Оценка`, `Добавлена`, `Жанр` и каскадными чекбоксами; снизу — карточка выбранной книги с кликабельными ссылками автора/серии/жанра, подгружаемой из FB2 аннотацией, сведениями о файле/архиве и обложкой.
  - **Прямая передача в конвертер без распаковки архивов**: отмеченные чекбоксами или выделенные книги (кнопкой, двойным кликом или из контекстного меню) и **целая серия одним действием** (**«Добавить всю серию в конвертер»**) попадают напрямую в очередь конвертера через нативную поддержку ZIP-записей; пользователь остаётся на вкладке «Библиотека».
- **Адаптивные палитры цветов под экран ридера (вкладка «Стили»)**: выбор цвета и быстрые списки оттенков автоматически подстраиваются под выбранный профиль устройства / «Экран ридера» и режим «Оттенки серого» (16 градаций для Ч/Б E Ink Carta, палитры Kaleido 3 и Gallery 3, монохромный фильтр фона сносок, универсальный образец текста `Пример текста АаБбВв AaBbCc 123`).
- **Выбор базового размера шрифта в стилях (`1. ШРИФТЫ КНИГИ`)**: добавлен параметр **«Базовый размер шрифта»** (`По умолчанию (ридер)` и `8pt`–`24pt`) с пропорциональным масштабированием заголовков/отступов и динамическим перестроением страниц в предпросмотре.

*_Безопасность, исправления и техническое обслуживание_*
- *SQLite-кэш `library_cache.sqlite` (схема v4) исправляет канонический порядок 14 колонок Flibusta/Lib.rus.ec (`DATE;LANG;LIBRATE;KEYWORDS`) с валидацией кодов языков и лимитом списка языков, хранит предвычисленные сводки по авторам, сериям, жанрам и языкам с покрывающими индексами (`idx_ba_book`, `idx_bg_book`, `ANALYZE`) и переиспользует read-only соединение с `mmap_size` (128 МБ) и `cache_size` (16 МБ), обеспечивая мгновенное (< 1 мс) открытие и переключение вкладки даже на коллекциях в 700+ тыс. книг.*
- *Реализована защита от zip-bomb при чтении `.inp`-файлов (лимит 128 МБ на запись), строгая проверка `os.path.realpath` против path traversal при поиске архивов и файлов книг рядом с `.inpx`, параметризованные SQL-запросы и атомарная подмена кэша.*
- *Настройки локальной библиотеки (`library_enabled`, `library_inpx_path`) исключены из переносимых пользовательских пресетов.*
- *Обновлены русская и английская локализации (`locales/ru.json`, `locales/en.json`), расширено покрытие юнит-тестами (`tests/test_inpx_library.py`, `tests/test_controllers.py`) до 262 тестов.*

---

## English Version

**freeLib-inspired local INPX library browser (Authors / Series / Genres / multi-field Search navigation, alphabet bar, hierarchical book tree with cascading checkboxes, annotation & cover preview pane) with direct transfer of books and complete series to the converter, plus base book font size selection and display-aware e-reader color palettes.**

**✨ New Features**
- **freeLib-Style Local INPX Library (new «Library» tab)**:
  - **Opt-in toggle in Settings**: added a **Library tab** switch at the top of Settings (Off by default, persisted across restarts). When enabled, the **Library** tab appears to the left of Converter in the top navigation bar.
  - **Integrated connection bar**: compact top strip with `.inpx` path, **Choose INPX...**, **Reindex**, and collection status.
  - **Two-pane navigation & alphabet bar**: left pane switches between **Authors**, **Series**, **Genres** (with instant filter & book counts), and **Search** (multi-field title/author/series/genre search; right tree stays empty until a search is executed); right pane features language filter, hide-deleted (`DEL=1`), and a two-row alphabet bar (`А–Я`, `*`, `#`, `A–Z`).
  - **Hierarchical book tree, details & cover preview**: `Author → Series → Books` tree with `Title`, `#`, `Size`, `Rating`, `Added`, `Genre` columns and cascading checkboxes; bottom pane shows clickable author/series/genre links, on-demand FB2 annotation, file/archive metadata, and cover image.
  - **Zero-unpack transfer to Converter**: send checked or selected books (via button, double-click, or context menu) or an **entire series in one click** (**Add entire series to Converter**) directly into the Converter queue using native ZIP-entry support while staying on the Library tab.
- **Display-Aware Color Palettes (Styles Tab)**: color pickers and dropdowns adapt to the selected device / Reader Display profile and Grayscale mode (16-level B&W E Ink Carta, Kaleido 3, Gallery 3, monochrome footnote background filtering, neutral preview sample `Sample text AaBbCc АаБбВв 123`).
- **Base Font Size Selector (`1. BOOK FONTS`)**: added **Base font size** (`Default (reader)` and `8pt`–`24pt`) with proportional heading/indent scaling and dynamic page reflow in Book preview.

*_Security, Bug Fixes & Maintenance_*
- *SQLite cache `library_cache.sqlite` (schema v4) aligns default 14-column Flibusta/Lib.rus.ec layout (`DATE;LANG;LIBRATE;KEYWORDS`) with strict language-code validation and dropdown limits, stores precomputed author/series/genre/language summary tables with covering indexes (`idx_ba_book`, `idx_bg_book`, `ANALYZE`), and reuses a warm read-only connection with `mmap_size` (128 MB) and `cache_size` (16 MB) for instant (< 1 ms) tab switching even on 700k+ book libraries.*
- *Enforced zip-bomb limits (128 MB per `.inp` entry), strict `os.path.realpath` path-traversal guards when resolving archives/files next to `.inpx`, parameterized SQL queries, and atomic SQLite cache replacement.*
- *Excluded local library paths and toggle state from portable user presets.*
- *Updated RU/EN localizations (`locales/ru.json`, `locales/en.json`) and expanded the unit test suite (`tests/test_inpx_library.py`, `tests/test_controllers.py`) to 262 tests.*

# FBC GUI v2.10 (Build 103) — Release Notes

## Русская версия (RU)

**Версия 2.10 (Ноябрь 2026) — Онлайн-подбор обложек и метаданных (включая OPDS), Инспектор с автоисправлением, доставка на ридер, организатор FB2, менеджер шрифтов и архитектурный рефакторинг • сборка 103**

### ✨ Новые возможности

- **Расширенный редактор метаданных книги (`BookEditDialog`)**:
  - Диалог разделён на две вкладки — **«Основное»** и **«Дополнительно»**.
  - Визуальный редактор **жанров FB2**: интерактивные чипы, живой поиск по названию и коду, сгруппированное дерево категорий FictionBook 2.1 (`core/fb2_genres.py`, 16 групп) и поддержка пользовательских тегов (`litrpg` и др.).
  - Поля **Язык** (`<lang>`), **Переводчик** (`<translator>`, с сохранением сопереводчиков), **Издатель** (`<publish-info><publisher>`), **ISBN** (`<publish-info><isbn>`, с валидацией ISBN-10/13 и поиском в очереди) и **Аннотация** (`<annotation>`) со счётчиком символов и предупреждением о богатой XML-разметке.
- **Пакетное редактирование жанров и языка (`BatchEditDialog`)**:
  - Массовое изменение **жанров** в режимах **«Добавить»**, **«Заменить»** и **«Удалить»** (с быстрым выбором из справочника) и массовое назначение **языка** с полной поддержкой Undo/Redo (`Cmd/Ctrl+Z`).
- **Инспектор структуры и предпроверка FB2 (`BookInspectorDialog`)**:
  - Легковесная предпроверка при импорте (`quick_check_fb2`): обнаружение дефектов XML, отсутствующей обложки, пустого названия или автора без лишней нагрузки на память.
  - Индикатор предупреждений (`⚠ N`) в колонке статуса и фильтр-пилюля **«⚠ Проблемы»** в панели поиска очереди.
  - Диалог **«Инспектор FB2...»** из контекстного меню книги с вкладками **Сводка и проверки**, **Оглавление (TOC)** и **Иллюстрации и сноски** (размеры, вес, флаг `> 2 МБ` / повреждено) + кнопка быстрого запуска `--debug`.
- **Менеджер пользовательских шрифтов (`core/css_preview.py`, вкладка «Стили»)**:
  - Переработана секция **«1. Шрифты книги»**: компактная сетка выбора шрифтов слева и отдельная пунктирная **Drop-зона** справа (счётчик шрифтов, подсветка при перетаскивании, клик для выбора и кнопки **«Добавить шрифты...»** / **«Папка шрифтов»**).
  - Поддержка Drag & Drop файлов `.ttf`, `.otf`, `.woff`, `.woff2` с проверкой расширения и magic bytes, мгновенное обновление списков и превью без перезапуска.
- **Расширенные параметры `fb2cng` (вкладка «Настройки»)**:
  - Двусторонняя синхронизация с `config.yaml` для **аннотации в оглавлении** (`annotation.in_toc`), **типа оглавления** (`toc_type`: обычный / старый Kindle / плоский), **глав без заголовка** (`toc_page.include_chapters_without_title`), **карты страниц EPUB** (`page_map` с режимом Adobe DE), **совместимости ZIP** (`fix_zip`) и **масштаба изображений** (`images.scale_factor`: `0.5–2.0`).
- **Дедупликация очереди и пропуск уже сконвертированных книг**:
  - Автоматический поиск логических дубликатов (по автору, серии, номеру и названию), бейдж **«≈ Дубликат»** и кнопка **«Удалить дубликаты (N)»** с Undo/Redo.
  - Переключатель **«Пропускать готовые»** (`skip_existing`): актуальные выходные файлы помечаются статусом **«↷ Пропущено»** без повторного запуска `fb2cng`.
- **Доставка книг на ридер по USB / MTP (`core/s2k_manager.py`, `DeviceSyncWorker`)**:
  - Вкладка **«Настройки» → «Доставка на ридер»** и кнопка **«На ридер»** на панели конвертера.
  - Поддержка **MTP** (Kindle Scribe, PW12, Colorsoft) и **USB** (старые Kindle) через `sync2kindle` (`s2k` скачивается автоматически с GitHub с проверкой контрольной суммы при первом запуске), а также прямое копирование в смонтированную папку (Kobo, PocketBook) с пропуском актуальных файлов.
  - Безопасный режим **«Пробный запуск»** и защита от удаления локальных книг.
- **Автоисправление и оптимизация FB2 из Инспектора (`BookInspectorDialog`)**:
  - Кнопка **«Исправить и оптимизировать FB2»** в диалоге Инспектора (активна при ошибках XML, битых `<binary>` или иллюстрациях `> 2 МБ`): восстанавливает и сохраняет валидный UTF-8 XML, удаляет пустые/повреждённые вложения, сжимает тяжёлые изображения (JPEG, макс. 1600 px) и атомарно записывает результат в `.fb2` / `.zip`.
- **Организатор исходных FB2 без конвертации (`OrganizeBooksDialog`)**:
  - Пункт контекстного меню **«Разложить / переименовать исходные FB2...»** раскладывает выбранные `.fb2` / `.fb2.zip` по структуре **Автор / Серия / Файл**, **Автор / Файл** или **Без подпапок** с живым предпросмотром **Было → Стало**, режимами **Копировать** и **Переместить** (с обновлением путей в очереди).
- **Онлайн-подбор обложек и метаданных (`MetadataLookupDialog`, `core/metadata_lookup.py`)**:
  - Доступен по кнопке **«Получить онлайн»** под **«Вернуть исходную»** на панели обложки конвертера и в `BookEditDialog`, а также из контекстного меню книги (**«Подобрать обложку и метаданные онлайн...»**) с полной поддержкой Undo/Redo (`Cmd/Ctrl+Z`).
  - Поддерживает **FantLab**, **LitRes** (оптимально для русскоязычных изданий), **Open Library** (без ключа), опциональный **Google Books** (по API-ключу) и универсальный **OPDS-провайдер** (Atom XML + автообнаружение OpenSearch, HTTP/HTTPS, опциональная Basic Auth с хранением пароля в системном Keychain / `keyring` и защитой от XXE).
  - Таблица сравнения **Было → Найдено** с поштучными чекбоксами, быстрыми пресетами (**«Только пустые»**, **«Все найденные»**, **«Только обложка»**) и галереей обложек с дедупликацией по SHA-256.
- **Пользовательская документация в `docs/`**:
  - Подготовлены полные руководства пользователя на русском и английском языках (`docs/USER_GUIDE_RU.md`, `docs/USER_GUIDE_EN.md`, включая пример подключения Flibusta через OPDS) с открытием прямо из меню **«Справка»** и вкладки **«О программе»**.

#### _Исправления ошибок и техническое обслуживание_

- _Минимальный XSD save-back (`core/fb2_processor.py`): запись изменений в `.fb2` и многофайловые `.zip` патчит только изменённые поля в строгом порядке XSD FictionBook 2.1, сохраняя нетронутую разметку `<annotation>`, `<genre match="...">`, `<src-lang>` и сопереводчиков; добавлены `os.fsync()` и `ZipFile.testzip()`._
- _Исправлено отображение компактных кнопок Undo/Redo (`↩`/`↪`) в панели очереди (убрано обрезание символов из-за горизонтальных отступов, добавлен показ подсказок в неактивном состоянии); убраны CLI-ключи из подписей кнопок._
- _Аудит безопасности и качества кода (сборка 92): добавлена единая обёртка `safe_urlopen` с контролем HTTP-редиректов (запрет даунгрейда HTTPS→HTTP, лимит переходов, снятие `Authorization`/`X-Goog-Api-Key` на чужой домен); ключ Google Books перенесён в заголовок `X-Goog-Api-Key` с маскированием секретов в логах; усилена защита от XXE через `expat` (включая UTF-16); исправлена регистронезависимая проверка контрольных сумм и лимит распаковки `sync2kindle`; добавлен лимит размера FB2 при чтении из ZIP, санитизация CSS/HTML-превью от инъекций, валидация имён аккаунтов Keychain, фильтрация расширений IPC-путей и принцип наименьших привилегий в GitHub Actions; добавлены 8 настроек v2.10 в `PRESET_SETTING_KEYS`, единый реестр провайдеров и предупреждение keyring в секции онлайн-поиска._
- _Архитектурный рефакторинг (сборки 93–94): `core/fb2_processor.py` декомпозирован на 7 доменных модулей в `core/fb2/` с сохранением совместимого фасада и предкомпиляцией регулярных выражений; `ui/dialogs.py` преобразован в пакет `ui/dialogs/` (7 модулей); из `MainWindow` выделены 6 контроллеров в `ui/controllers/` со свёртыванием шаблонных обработчиков настроек (`fbc_gui.py` сокращён с 3 497 до 774 строк); разбиты `build_settings_page` и `build_full_preview_html`; 29 блоков `except Exception: pass` переведены на `logger.debug(...)`; добавлен smoke-тест запуска `MainWindow` и всех 5 страниц._
- _Добавлено окно прогресса загрузки и проверки `sync2kindle` (`s2k`) с отображением МБ/процентов и возможностью отмены, диагностика отсутствующей `libmtp` на macOS (`brew install libmtp`) с выводом `stderr`, защита от случайной синхронизации `~`, универсальная проверка прав доступа к папкам `check_directory_access` для всех режимов доставки (MTP, USB, «Папка ридера») с кнопкой быстрого перехода в настройки доступа macOS, прямой staging известных сконвертированных файлов в `user_data_dir` с передачей `source`/`target` через временный YAML-конфиг (`-c`), умная кнопка «На ридер» и подсказка на кнопке выбора папки ридера (сборки 95–101)._
- _Исправлено расхождение имён файлов и заголовков на ридере для FB2 с несколькими тегами `<sequence>` (сборка 102): шаблоны по умолчанию `DEFAULT_OUTPUT_NAME_TEMPLATE` и `DEFAULT_TITLE_META_TEMPLATE` теперь используют только основную серию (`index .Series 0`), совпадающую с таблицей главного окна, без склейки через `/` и случайного разбиения пути на подпапки._
- _Единый прогресс-диалог с двумя шкалами при отправке на ридер (сборка 103): сверху отображается прогресс конвертации, снизу — живой прогресс отправки книг на ридер (по аналогии с отправкой по e-mail); подробный технический вывод `s2k` записывается в лог-файлы, а в итоговом окне выводится чистая сводка по количеству сконвертированных и отправленных книг._
- _Поиск в очереди расширен на жанры, язык, издателя и ISBN; все файлы `RELEASE_NOTES` перенесены в папку `docs/`; в GitHub Actions добавлен `QT_QPA_PLATFORM: offscreen` и обновление заметок релиза при пересборке тега; набор юнит-тестов расширен до 141 теста._

---

## English Version (EN)

**Version 2.10 (November 2026) — Online Cover & Metadata Lookup (including OPDS), Inspector Auto-Repair, Device Delivery, FB2 Organizer, Font Manager & Architectural Refactoring • build 103**

### ✨ New Features

- **Extended Book Metadata Editor (`BookEditDialog`)**:
  - Split into two clean tabs: **Basic** and **Extended**.
  - Visual **FB2 Genres** editor with removable chips, live search by name or code, grouped FictionBook 2.1 taxonomy tree (`core/fb2_genres.py`, 16 groups), and custom tag support (e.g. `litrpg`).
  - Added **Language** (`<lang>`), **Translator** (`<translator>`, preserving co-translators), **Publisher** (`<publish-info><publisher>`), **ISBN** (`<publish-info><isbn>`, with ISBN-10/13 validation and queue search), and **Annotation** (`<annotation>`) with character count and rich-XML warning.
- **Batch Genres & Language Editing (`BatchEditDialog`)**:
  - Batch **Genres** editing with **Add / Replace / Remove** modes (plus quick picker) and batch **Language** assignment with full Undo/Redo (`Cmd/Ctrl+Z`).
- **FB2 Pre-Flight Diagnostics & Structure Inspector (`BookInspectorDialog`)**:
  - Lightweight import checks (`quick_check_fb2`) detect XML defects, missing cover, or empty title/author without breaking lazy XML loading.
  - Warning badge (`⚠ N`) in the Status column and **⚠ Warnings** filter pill in the queue bar.
  - **FB2 Inspector...** context-menu dialog with **Summary & Checks**, **Table of Contents (TOC)**, and **Images & Footnotes** tabs (dimensions, size, `> 2 MB` / corrupted flags) plus one-click `--debug` conversion.
- **User Font Manager (`core/css_preview.py`, Styles page)**:
  - Redesigned **1. Book Fonts** with a compact left grid and a dedicated dashed **Font Drop Zone** card on the right (installed font counter, drag highlight, click-to-browse, and **Add Fonts...** / **Fonts Folder** buttons).
  - Supports Drag & Drop of `.ttf`, `.otf`, `.woff`, and `.woff2` files with extension and magic-byte validation, immediately refreshing pickers and live preview.
- **Expanded `fb2cng` Configuration (Settings page)**:
  - Bidirectional `config.yaml` sync for **Annotation in TOC** (`annotation.in_toc`), **TOC Type** (`toc_type`: Normal / Old Kindle / Flat), **Untitled Chapters in TOC** (`toc_page.include_chapters_without_title`), **EPUB Page Map** (`page_map` + Adobe DE mode), **Legacy ZIP Compatibility** (`fix_zip`), and **Illustration Scale Factor** (`images.scale_factor`: `0.5–2.0`).
- **Queue Deduplication & Skip Existing Books**:
  - Automatically detects logical duplicates (author, series, number, title), flags them with **≈ Duplicate**, and provides a **Remove Duplicates (N)** action backed by Undo/Redo.
  - **Skip existing** toggle (`skip_existing`) marks already up-to-date unedited books as **↷ Skipped** without re-running `fb2cng`.
- **Direct Device Delivery via USB / MTP (`core/s2k_manager.py`, `DeviceSyncWorker`)**:
  - Added **Settings → Device Delivery** section and a quick **To Reader** button on the Converter toolbar.
  - Supports **MTP** (Kindle Scribe, PW12, Colorsoft) and **USB** (legacy Kindle) via `sync2kindle` (`s2k` is automatically downloaded from GitHub with checksum verification on first use), plus direct mounted-folder sync (Kobo, PocketBook) that skips up-to-date files.
  - Includes **Dry Run** preview and local-file protection.
- **One-Click FB2 Auto-Repair & Image Optimization (`BookInspectorDialog`)**:
  - Added **Repair & Optimize FB2** button in the Inspector (enabled when broken XML, corrupted `<binary>` entries, or `> 2 MB` images are detected): repairs XML to clean UTF-8, strips empty/corrupted binaries, downsizes oversized images (JPEG, max 1600 px), and atomically writes back to `.fb2` / `.zip`.
- **Source FB2 Organizer Without Conversion (`OrganizeBooksDialog`)**:
  - Added **Organize / Rename Source FB2...** in the queue context menu to copy or move `.fb2` / `.fb2.zip` files into **Author / Series / File**, **Author / File**, or **Flat** layouts with a live **Before → After** preview table (automatically updating queue paths in Move mode).
- **Online Cover & Metadata Lookup (`MetadataLookupDialog`, `core/metadata_lookup.py`)**:
  - Accessible via **Fetch Online** right below **Restore Original** on the cover panel and inside `BookEditDialog`, as well as from the queue context menu (**Find Cover & Metadata Online...**) with full Undo/Redo (`Cmd/Ctrl+Z`).
  - Supports **FantLab**, **LitRes** (ideal for Russian editions), **Open Library** (no API key required), optional **Google Books** (user API key), and a universal **OPDS** provider (Atom XML + OpenSearch auto-discovery, HTTP/HTTPS, optional Basic Auth stored in system Keychain / `keyring`, and XXE protection).
  - Interactive **Current → Found** comparison table with per-field checkboxes, quick presets (**Empty Only**, **All Found**, **Cover Only**), and a deduplicated multi-source cover gallery.
- **Bilingual User Documentation (`docs/`)**:
  - Added full user guides in Russian and English (`docs/USER_GUIDE_RU.md`, `docs/USER_GUIDE_EN.md`, including a Flibusta OPDS setup example), accessible directly from **Help → User Guide...** and the **About** page.

#### _Bug Fixes & Maintenance_

- _Minimal-diff XSD save-back (`core/fb2_processor.py`): patches only modified fields in strict FictionBook 2.1 XSD order, preserving untouched rich `<annotation>` markup, `<genre match="...">`, `<src-lang>`, and extra `<translator>` nodes; hardened with `os.fsync()` and `ZipFile.testzip()`._
- _Fixed compact Undo/Redo (`↩`/`↪`) button rendering in the queue toolbar (removed horizontal padding clipping and enabled tooltips while disabled); removed CLI flags from button labels._
- _Security & code-quality hardening (build 92): added unified `safe_urlopen` with redirect policy (blocks HTTPS→HTTP downgrade, caps redirect hops, strips `Authorization`/`X-Goog-Api-Key` cross-origin); moved Google Books API key to `X-Goog-Api-Key` header with secret masking in logs; hardened XML XXE protection via `expat` handlers (including UTF-16); fixed case-insensitive `sync2kindle` checksum lookup and limited archive extraction; added FB2 ZIP entry size cap, CSS/HTML preview injection sanitization, Keychain account validation, IPC path extension filtering, and least-privilege GitHub Actions permissions; added 8 v2.10 settings to `PRESET_SETTING_KEYS`, unified provider registry, and keyring warning in Online Lookup settings._
- _Architectural refactoring (builds 93–94): decomposed `core/fb2_processor.py` into 7 domain modules under `core/fb2/` with a backward-compatible facade and precompiled regexes; converted `ui/dialogs.py` into the `ui/dialogs/` package (7 modules); extracted 6 window controllers into `ui/controllers/` with consolidated settings handlers (reducing `fbc_gui.py` from 3,497 to 774 lines); split `build_settings_page` and `build_full_preview_html` into focused helpers; migrated 29 `except Exception: pass` blocks to `logger.debug(...)`; added a `MainWindow` startup smoke test covering all 5 pages._
- _Added a progress and verification dialog (with MB/percentage readout and cancel button) when automatically downloading `sync2kindle` (`s2k`), friendly macOS missing-`libmtp` diagnostics (`brew install libmtp`) with full `stderr` reporting, a safeguard against accidentally syncing `~`, universal directory access check (`check_directory_access`) across all delivery modes (MTP, USB, Reader Folder) with a one-click macOS Privacy & Security button, direct staging of converted files into `user_data_dir` with temporary YAML config (`-c`), smart «Send to Reader» flow, and a tooltip on the reader folder picker button (builds 95–101)._
- _Fixed filename and on-device title mismatch for FB2 books with multiple `<sequence>` tags (build 102): default `DEFAULT_OUTPUT_NAME_TEMPLATE` and `DEFAULT_TITLE_META_TEMPLATE` now use only the primary series (`index .Series 0`) matching the main window table, without joining via `/` or splitting output filenames into subdirectories._
- _Unified dual-progress dialog for Send to Reader (build 103): top bar tracks conversion and bottom bar tracks live delivery to the reader (matching email delivery); raw `s2k` output is written to log files while the summary dialog shows clean counts of converted and delivered books._
- _Queue search now includes genres, language, publisher, and ISBN; moved all `RELEASE_NOTES` into `docs/`; added `QT_QPA_PLATFORM: offscreen` and existing-release notes updates to GitHub Actions; expanded the unit test suite to 141 tests._

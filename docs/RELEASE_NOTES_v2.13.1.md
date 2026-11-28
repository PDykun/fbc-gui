# FBC GUI v2.13.1 (build 153)

## Русская версия

**Исправлено падение при отправке на ридер, ошибка sync2kindle с историей синхронизации, добавлены отдельная папка вывода для Библиотеки и опция удаления сконвертированных файлов после отправки, а также ускорена конвертация и импорт FB2.**

**✨ Новые возможности**
- **Отдельная папка вывода для Библиотеки INPX**: в Настройках добавлен параметр **«Папка вывода для Библиотеки»** (по умолчанию `Downloads` / Загрузки) для обычной конвертации — исходная папка библиотеки больше не засоряется сконвертированными файлами. При отправке книг из Библиотеки кнопкой **«На ридер»** они всегда конвертируются во временный каталог и автоматически удаляются после отправки.
- **Удаление сконвертированных файлов после отправки на ридер**: в секции «Доставка на ридер» переключатель «Не удалять локальные книги» заменён на **«Удалять сконвертированные файлы после отправки на ридер»** — при включении все книги, отправляемые кнопкой **«На ридер»**, конвертируются во временный каталог и автоматически очищаются после завершения доставки.

*_Исправления ошибок и техническое обслуживание_*
- *Исправлено падение приложения (`SIGABRT`) при нажатии кнопки **«На ридер»** на панели Конвертера: сигнал `QPushButton.clicked(bool)` передавал `False` в параметр `target_items` метода `send_to_reader_clicked`.*
- *Исправлена ошибка отправки на Kindle через `sync2kindle` (`remove .../s2k_stage_...: no such file or directory`): временный конфиг `s2k` теперь использует изолированный временный каталог `history`, не смешиваясь со старыми путями временных папок в `~/.s2k/history`.*
- *Ускорена конвертация и импорт FB2: остановка Expat-проверки `DOCTYPE`/`ENTITY` сразу после пролога, пропуск `update_fb2_xml` при неизменённых метаданных, однопроходное обновление XML и оптимизация `<binary>` с быстрым кодированием перед `fb2cng`, а также переиспользование XML-дерева и открытых ZIP-архивов при пакетном импорте из Библиотеки.*

---

## English Version

**Fixed a crash when sending books to a reader and a sync2kindle history error, added a dedicated Library output folder and an option to delete converted files after sending, and accelerated FB2 conversion and Library import.**

**✨ New Features**
- **Dedicated Output Folder for Local INPX Library**: added a **Library output folder** setting (defaults to `Downloads`) for standard conversions so converted files no longer clutter the library directory. Books sent from the Library via **Send to Reader** are always converted into a temporary folder and automatically cleaned up after delivery.
- **Delete Converted Files After Sending to Reader**: replaced the **Keep local books** toggle in Device Delivery with **Delete converted files after sending to reader** — when enabled, all books sent via **Send to Reader** are converted into a temporary folder and automatically removed once delivery completes.

*_Bug Fixes & Maintenance_*
- *Fixed a crash (`SIGABRT`) when clicking **Send to Reader** in the Converter toolbar: `QPushButton.clicked(bool)` passed `False` into `send_to_reader_clicked(target_items=...)`.*
- *Fixed a `sync2kindle` MTP/USB error (`remove .../s2k_stage_...: no such file or directory`) by passing an isolated temporary `history` directory in the generated `s2k` YAML config so ephemeral staging paths never conflict with `~/.s2k/history`.*
- *Accelerated FB2 conversion and Library import: stop Expat `DOCTYPE`/`ENTITY` check immediately after the XML prolog, skip `update_fb2_xml` when metadata/cover are unchanged, combine XML metadata and `<binary>` image optimization into a single parse/serialize pass with fast intermediate encoding before `fb2cng`, and reuse parsed XML trees and open ZIP handles during batch import.*

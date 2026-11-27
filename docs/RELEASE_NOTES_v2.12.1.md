# FBC GUI v2.12.1 (build 140)

## Русская версия

**Настройка базового размера шрифта книги в редакторе стилей с пропорциональным масштабированием всех элементов, динамическим перестроением страниц в предпросмотре и полной поддержкой всех форматов конвертации.**

**✨ Новые возможности**
- **Выбор базового размера шрифта в стилях (`1. ШРИФТЫ КНИГИ`)**: добавлен параметр **«Базовый размер шрифта»** с режимом **«По умолчанию (ридер)»** (размер задаёт само устройство) и набором типографских кеглей в пунктах (`8pt`, `9pt`, `10pt`, `10.5pt`, `11pt`, `12pt`, `13pt`, `14pt`, `16pt`, `18pt`, `20pt`, `22pt`, `24pt`).
  - Значение записывается в `body { font-size: ... }` файла `ebook_styles.css`, благодаря чему все относительные размеры заголовков (`%`), буквицы и красной строки (`em`) масштабируются пропорционально, а страницы PDF и книг во всех форматах (`PDF`, `EPUB`, `KEPUB`, `AZW3`, `KFX`) корректно перестраиваются.
  - Режим **«По умолчанию (ридер)»** оставлен значением по умолчанию для новых установок и всех встроенных пресетов устройств для 100% обратной совместимости.
- **Обновлённый предпросмотр книги и образца стилей**: базовый размер шрифта применяется в встроенном превью и при открытии в браузере; в режиме реальной книги пересчитывается объём текста на страницах разворота при увеличении или уменьшении кегля, а в сводной таблице образца отображается текущий базовый размер.

*_Исправления ошибок и техническое обслуживание_*
- *Добавлена санитизация и обратный парсинг `body { font-size }` (включая сохранение пользовательских значений из вручную отредактированного CSS), обновлены локализации RU/EN и встроенные пресеты устройств (`presets_defaults/*.fbcpreset.json`).*
- *Расширено покрытие юнит-тестами (`tests/test_css_preview.py`) до 255 тестов.*

---

## English Version

**Base book font size selector in the Styles editor with proportional scaling of all book elements, dynamic page reflow in preview, and full conversion format support.**

**✨ New Features**
- **Base Font Size Selector (`1. BOOK FONTS`)**: added the **Base font size** control with **Default (reader)** mode (lets the e-reader control base text size) and typographic point presets (`8pt`, `9pt`, `10pt`, `10.5pt`, `11pt`, `12pt`, `13pt`, `14pt`, `16pt`, `18pt`, `20pt`, `22pt`, `24pt`).
  - Writes `font-size` directly to `body` in `ebook_styles.css`, proportionally scaling all relative headings (`%`), drop caps, and indents (`em`) and reflowing pages across `PDF`, `EPUB`, `KEPUB`, `AZW3`, and `KFX` output.
  - Keeps **Default (reader)** as the default for fresh installations and all built-in device presets for full backward compatibility.
- **Synchronized Book & Style Sample Preview**: applies the selected base font size to both rich WebView/browser and fallback previews, dynamically reflows page 2 / spread 3–4 text volume in Book mode when changing font size, and displays the active base size in the Style Sample summary table.

*_Bug Fixes & Maintenance_*
- *Added CSS sanitization and round-trip parsing for `body { font-size }` (preserving custom values from hand-edited stylesheets), updated RU/EN localizations, and synced built-in device presets (`presets_defaults/*.fbcpreset.json`).*
- *Expanded the unit test suite (`tests/test_css_preview.py`) to 255 tests.*

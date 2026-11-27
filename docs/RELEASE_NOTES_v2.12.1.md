# FBC GUI v2.12.1 (build 142)

## Русская версия

**Настройка базового размера шрифта книги и адаптивные палитры выбора цвета под экран выбранного ридера (Ч/Б E Ink 16 градаций, цветные E Ink Kaleido 3 и Gallery 3) с монохромным фильтром фона сносок.**

**✨ Новые возможности**
- **Адаптивные палитры цветов под экран ридера (вкладка «Стили»)**: выбор цвета и быстрые списки оттенков автоматически подстраиваются под выбранный профиль устройства / «Экран ридера» и режим «Оттенки серого»:
  - **Ч/Б E Ink (Carta 1200/1300, 16 градаций, «Оттенки серого»)**: вместо полного RGB-диалога открывается тематизированный диалог **«Палитра Ч/Б E Ink (16 градаций серого)»** с 16 реальными градациями Carta, ползунком оттенка, кодом HEX и живым превью текста на бумаге E Ink с оценкой контраста; для фона сносок отображаются только монохромные варианты (`Серый`, `Белый`, `Без фона`).
  - **Цветные E Ink (Kaleido 3 — 4096 цветов, Gallery 3)**: открывается палитра книжных оттенков, квантованных под реальную разрядность экрана (4 или 5 бит на канал), с имитацией вида текста на бумаге конкретного ридера и кнопкой **«Произвольный цвет...»** с автоматической привязкой к ближайшему цвету экрана.
  - **Выкл (оригинал / PDF / планшет)**: сохраняется полный RGB-диалог выбора цвета.
- **Выбор базового размера шрифта в стилях (`1. ШРИФТЫ КНИГИ`)**: добавлен параметр **«Базовый размер шрифта»** с режимом **«По умолчанию (ридер)»** (размер задаёт само устройство) и набором типографских кеглей в пунктах (`8pt`, `9pt`, `10pt`, `10.5pt`, `11pt`, `12pt`, `13pt`, `14pt`, `16pt`, `18pt`, `20pt`, `22pt`, `24pt`).
  - Значение записывается в `body { font-size: ... }` файла `ebook_styles.css`, благодаря чему все относительные размеры заголовков (`%`), буквицы и красной строки (`em`) масштабируются пропорционально, а страницы PDF и книг во всех форматах (`PDF`, `EPUB`, `KEPUB`, `AZW3`, `KFX`) корректно перестраиваются.
  - Режим **«По умолчанию (ридер)»** оставлен значением по умолчанию для новых установок и всех встроенных пресетов устройств для 100% обратной совместимости.
- **Обновлённый предпросмотр книги и образца стилей**: базовый размер шрифта применяется в встроенном превью и при открытии в браузере; в режиме реальной книги пересчитывается объём текста на страницах разворота при увеличении или уменьшении кегля, а в сводной таблице образца отображается текущий базовый размер.

*_Исправления ошибок и техническое обслуживание_*
- *Уточнён универсальный текст примера в диалоге палитры ридера (`Пример текста АаБбВв AaBbCc 123` / `Sample text AaBbCc АаБбВв 123`) для корректного соответствия всем цветовым настройкам стилей.*
- *Добавлена санитизация и обратный парсинг `body { font-size }` (включая сохранение пользовательских значений из вручную отредактированного CSS), обновлены локализации RU/EN и встроенные пресеты устройств (`presets_defaults/*.fbcpreset.json`).*
- *При переключении профиля ридера уже заданные пользователем цвета не затираются — обновляется только доступная палитра для нового выбора.*
- *Расширено покрытие юнит-тестами (`tests/test_css_preview.py`, `tests/test_image_optimizer.py`) до 257 тестов.*

---

## English Version

**Base book font size selector and display-aware color palettes tailored to the selected e-reader screen (16-level B&W E Ink, Kaleido 3, and Gallery 3) with monochrome footnote background filtering.**

**✨ New Features**
- **Display-Aware Color Palettes (Styles Tab)**: color pickers and quick dropdowns automatically adapt to the selected device / Reader Display profile and Grayscale setting:
  - **B&W E Ink (Carta 1200/1300, 16 Gray Levels, Grayscale)**: replaces the full RGB picker with a themed **B&W E Ink Palette (16 Gray Levels)** dialog featuring 16 hardware Carta gray swatches, a 16-step shade slider, HEX input, and a live E Ink paper text preview with contrast feedback; footnote background options are filtered to monochrome choices (`Gray`, `White`, `No background`).
  - **Color E Ink (Kaleido 3 — 4096 Colors, Gallery 3)**: opens a curated book-typography palette quantized to the display's hardware bit depth (4-bit or 5-bit per channel) with simulated E Ink paper preview and a **Custom Color...** button that automatically maps any chosen color to the nearest display color.
  - **Off (Original / PDF / Tablet)**: retains the full RGB color dialog.
- **Base Font Size Selector (`1. BOOK FONTS`)**: added the **Base font size** control with **Default (reader)** mode (lets the e-reader control base text size) and typographic point presets (`8pt`, `9pt`, `10pt`, `10.5pt`, `11pt`, `12pt`, `13pt`, `14pt`, `16pt`, `18pt`, `20pt`, `22pt`, `24pt`).
  - Writes `font-size` directly to `body` in `ebook_styles.css`, proportionally scaling all relative headings (`%`), drop caps, and indents (`em`) and reflowing pages across `PDF`, `EPUB`, `KEPUB`, `AZW3`, and `KFX` output.
  - Keeps **Default (reader)** as the default for fresh installations and all built-in device presets for full backward compatibility.
- **Synchronized Book & Style Sample Preview**: applies the selected base font size to both rich WebView/browser and fallback previews, dynamically reflows page 2 / spread 3–4 text volume in Book mode when changing font size, and displays the active base size in the Style Sample summary table.

*_Bug Fixes & Maintenance_*
- *Updated the e-reader palette dialog preview text to a neutral sample (`Sample text AaBbCc АаБбВв 123` / `Пример текста АаБбВв AaBbCc 123`) applicable to all style color settings.*
- *Added CSS sanitization and round-trip parsing for `body { font-size }` (preserving custom values from hand-edited stylesheets), updated RU/EN localizations, and synced built-in device presets (`presets_defaults/*.fbcpreset.json`).*
- *Switching reader display profiles preserves existing user-chosen colors while updating the available palette for new selections.*
- *Expanded the unit test suite (`tests/test_css_preview.py`, `tests/test_image_optimizer.py`) to 257 tests.*

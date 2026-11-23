# FBC GUI v2.5 (Build 49) — Release Notes & Материалы для сайта

## 1. Release Notes (RU / EN)

### Русская версия (RU)
**FBC GUI v2.5 (сборка 49) — Оптимизация набора шрифтов и режим «Нет» (шрифты ридера)**
- **Облегчённый дистрибутив шрифтов**: из скомпилированной программы и установочных пакетов исключены все лишние встроенные шрифты — в комплекте оставлены только **PT Astra Serif** (Regular, Italic, Bold, Bold-Italic) и **Pomorsky Unicode**.
- **Новые шрифты по умолчанию**: при установке и первоначальной генерации `newtondrcps.css` для основного текста, названия книги и имени автора по умолчанию используется **PT Astra Serif** (`PT-Astra-Serif_Regular.ttf` с автоматическим подключением начертаний для основного текста), а для буквицы — **Pomorsky Unicode** (`PomorskyUnicode.otf`).
- **Режим «Нет» в выборе шрифтов**: в начало каждого выпадающего списка шрифтов на вкладке «Стили» добавлен пункт **«Нет»**. При его выборе `@font-face` и `font-family` не записываются в CSS, шрифты не встраиваются в сконвертированный файл, а электронная книга отображается шрифтами, установленными в самом ридере.
- **Поддержка пользовательских шрифтов**: если добавить собственные файлы шрифтов (`.ttf`, `.otf`, `.woff`, `.woff2`) в папку `fonts`, они автоматически появляются в выпадающих списках программы для выбора.

### English Version (EN)
**FBC GUI v2.5 (Build 49) — Streamlined Font Bundle & "None" (Reader Fonts) Mode**
- **Streamlined Font Distribution**: removed all extra bundled fonts from the compiled application and installers — only **PT Astra Serif** (Regular, Italic, Bold, Bold-Italic) and **Pomorsky Unicode** are now included.
- **Updated Default Fonts**: on fresh installation and initial `newtondrcps.css` generation, **PT Astra Serif** (`PT-Astra-Serif_Regular.ttf` with full family styles for body text) is set as the default for body text, book title, and author name, while **Pomorsky Unicode** (`PomorskyUnicode.otf`) is set as the default for drop caps.
- **"None" Option in Font Selectors**: added a **None** option at the top of every font dropdown on the Styles tab. Selecting it omits `@font-face` and `font-family` rules from CSS so no fonts are embedded in the converted e-book and the reader's own fonts are used.
- **Custom User Fonts Preserved**: any custom font files (`.ttf`, `.otf`, `.woff`, `.woff2`) placed in the `fonts` folder continue to appear in the font selection dropdowns automatically.

---

## 2. Информационные блоки для размещения на сайте программы

### Блок 1: Чистая типографика по умолчанию — PT Astra Serif и Pomorsky Unicode
**Заголовок (RU):** Оптимальный набор шрифтов из коробки: PT Astra Serif и Pomorsky Unicode  
**Описание (RU):**  
Дистрибутив FBC GUI стал компактнее: из сборки убраны лишние шрифты, а по умолчанию настроена проверенная книжная пара — **PT Astra Serif** для основного текста, заголовков и автора и декоративный **Pomorsky Unicode** для буквицы. При необходимости вы в любой момент можете добавить собственные шрифты в папку `fonts`, и они сразу появятся в списке выбора.

**Title (EN):** Clean Out-of-the-Box Typography: PT Astra Serif & Pomorsky Unicode  
**Description (EN):**  
The FBC GUI distribution is now leaner: extra bundled fonts have been removed in favor of a curated default pairing — **PT Astra Serif** for body text, book titles, and author names, and **Pomorsky Unicode** for drop caps. You can still drop any custom fonts into the `fonts` folder at any time to make them selectable in the app.

---

### Блок 2: Режим «Нет» — используйте встроенные шрифты вашего ридера
**Заголовок (RU):** Режим «Нет» для шрифтов: полное доверие настройкам ридера  
**Описание (RU):**  
В самом верху выпадающих списков выбора шрифтов появился пункт **«Нет»**. Если выбрать его, FBC GUI не добавляет правила `@font-face` и `font-family` в CSS-стили и не встраивает шрифты в итоговый EPUB или другой формат — книга будет использовать шрифты, выбранные на вашем устройстве для чтения.

**Title (EN):** "None" Font Mode: Use Your E-Reader's Built-In Fonts  
**Description (EN):**  
A new **None** option sits at the top of every font dropdown. When selected, FBC GUI omits `@font-face` and `font-family` declarations from the generated CSS so no fonts are embedded in the converted file and your e-reader's native fonts take over.

**Иллюстрации:**
- Вкладка «Стили» (Modern Dark): `/Applications/fbc/screenshots_v2.5/styles_modern_dark.png`
- Кроп секции шрифтов (Modern Dark): `/Applications/fbc/screenshots_v2.5/crop_fonts_modern_dark.png`
- Вкладка «Стили» (Golden Dark): `/Applications/fbc/screenshots_v2.5/styles_golden_dark.png`
- Кроп секции шрифтов (Golden Dark): `/Applications/fbc/screenshots_v2.5/crop_fonts_golden_dark.png`

# FBC GUI v2.5 (Build 49) — Release Notes

## Русская версия (RU)

**Версия 2.5 (Ноябрь 2026) — Оптимизация набора шрифтов и режим «Нет» (шрифты ридера) • сборка 49**

### ✨ Новые возможности

- **Режим «Нет» в выборе шрифтов**: в начало каждого выпадающего списка шрифтов на вкладке «Стили» добавлен пункт **«Нет»** — при его выборе `@font-face` и `font-family` не записываются в CSS, шрифты не встраиваются в книгу, и используются шрифты самого ридера.
- **Новые шрифты по умолчанию**: **PT Astra Serif** (Regular, Italic, Bold, Bold-Italic) для основного текста, названия и автора, и декоративный **Pomorsky Unicode** для буквицы.
- **Поддержка пользовательских шрифтов**: файлы `.ttf`, `.otf`, `.woff`, `.woff2` из папки `fonts/` автоматически появляются в списках выбора.

#### _Исправления ошибок и техническое обслуживание_

- _Облегчённый дистрибутив шрифтов: из скомпилированной программы и установочных пакетов исключены лишние встроенные шрифты._

---

## English Version (EN)

**Version 2.5 (November 2026) — Streamlined Font Bundle & "None" (Reader Fonts) Mode • build 49**

### ✨ New Features

- **"None" Option in Font Selectors**: added **None** at the top of every font dropdown on the Styles tab — omits `@font-face` and `font-family` rules so no fonts are embedded and the e-reader's native fonts are used.
- **Updated Default Fonts**: **PT Astra Serif** (Regular, Italic, Bold, Bold-Italic) for body text, book title, and author name, plus **Pomorsky Unicode** for drop caps.
- **Custom User Fonts**: `.ttf`, `.otf`, `.woff`, and `.woff2` files placed in `fonts/` automatically appear in the font selectors.

#### _Bug Fixes & Maintenance_

- _Streamlined font distribution by removing extra bundled fonts from the application and installers._

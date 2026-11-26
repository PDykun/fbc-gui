# FBC GUI v2.10.1 (Build 107) — Release Notes

## Русская версия (RU)

**Версия 2.10.1 (Ноябрь 2026) — Обновлённая логика шаблона имени файла и заголовка в метаданных, пункт «Нет» в пресетах и очистка подписей настроек • сборка 107**

### ✨ Новые возможности

- **Обновлённая логика шаблона имени выходного файла**:
  - Шаблон имени файла **«По умолчанию»** изменён на формат **`Автор - (АБВ-01) - Название книги`** (без пробелов вокруг дефиса внутри скобок, например: `Толстой - (ВИМ-01) - Том первый.epub`). Для книг без серии лишние разделители автоматически схлопываются до одного дефиса (`Толстой - Том первый.epub`).
  - При первом переключении на режим **«Пользовательский»** конструктор открывается с тем же шаблоном по умолчанию (`Фамилия → - → ( → Аббр. серии → - → № в серии → ) → - → Название`), при этом любые самостоятельно внесённые пользователем изменения сохраняются и не перезаписываются.
- **Синхронизация шаблона заголовка книги в метаданных с именем файла**:
  - В настройке **«Шаблон заголовка книги в метаданных»** удалена кнопка **«По умолчанию»** и добавлена кнопка **«Имя файла»** (активна по умолчанию).
  - В режиме **«Имя файла»** заголовок книги в метаданных (`title_template`) полностью повторяет текущую настройку шаблона имени файла — как в режиме «По умолчанию», так и в режиме «Пользовательский». При любом изменении шаблона имени файла шаблон заголовка в метаданных обновляется автоматически.
  - Для независимой настройки заголовка по-прежнему доступен режим **«Пользовательский»**.
- **Пункт «Нет» в списке «Сохранённые пресеты»**:
  - В выпадающий список **«Сохранённые пресеты»** добавлен пункт **«Нет»** (выбран по умолчанию, если активный пресет не задан).
  - Выбор пункта **«Нет»** (в списке или по кнопке **«Применить»**) отменяет ранее применённые пресеты и ручные правки и сбрасывает настройки конвертации, шаблоны имён/заголовков и стили CSS (`ebook_styles.css`) к значениям по умолчанию, сохраняя личные параметры (SMTP, ключи API, папки и тему интерфейса).
- **Чистые подписи настроек без технических имён**:
  - Из названий и описаний пунктов в разделе **«Настройки»** (в русской и английской локализациях) удалены технические имена параметров конфигурации в скобках (например, `(text_transformations.dashes)`, `(metainformation.title_template)`, `(page_map)`, `(fix_zip)` и др.).

#### _Исправления ошибок и техническое обслуживание_

- _Исправлено схлопывание двойных разделителей вокруг пустых тегов и пустой группы серии как в Python-превью (`render_filename_from_tokens`), так и в генерируемом Go-шаблоне для `fb2cng` (`build_fbc_output_name_template`) — книги без серии больше не получают двойной дефис (`- -`)._
- _Добавлена мягкая миграция настроек при загрузке `settings.json` и применении старых пресетов: устаревший дефолтный шаблон имени файла в режиме `default` автоматически обновляется на новый (не затрагивая пользовательские варианты), а прежний режим `title_template_mode: "default"` переводится на `"filename"`._
- _Обновлены все 8 встроенных пресетов устройств в `presets_defaults/`; расширен набор юнит-тестов до 148 тестов (все проходят без ошибок)._

---

## English Version (EN)

**Version 2.10.1 (November 2026) — Updated Filename & Metadata Title Template Logic, Preset «None» Reset Option & Cleaner Settings Labels • build 107**

### ✨ New Features

- **Updated Output Filename Template Logic**:
  - The **Default** filename template now uses the format **`Author - (ABC-01) - Book Title`** (no spaces around the hyphen inside parentheses, e.g., `Tolstoy - (WAP-01) - Volume One.epub`). For books without a series, surrounding separators collapse cleanly to a single hyphen (`Tolstoy - Volume One.epub`).
  - Switching to **Custom** for the first time opens with this same default template (`Last Name → - → ( → Series Abbr → - → Series # → ) → - → Title`), while any custom edits made by the user are preserved across restarts and mode switches.
- **Metadata Book Title Template Linked to Filename**:
  - Removed the **Default** button in **Book title metadata template** and replaced it with **File name** (selected by default).
  - In **File name** mode, the metadata title template (`title_template`) mirrors the active output filename template — both in Default and Custom modes — and automatically updates whenever the filename template changes.
  - **Custom** mode remains available whenever you want a separate metadata title pattern.
- **«None» Option in Saved Presets**:
  - Added a default **None** option at the top of the **Saved presets** dropdown.
  - Selecting **None** (from the dropdown or via **Apply**) resets conversion settings, filename/title templates, and CSS styles (`ebook_styles.css`) back to application defaults while preserving private/local settings (SMTP credentials, API keys, custom paths, and UI theme).
- **Cleaner Settings Labels**:
  - Removed internal configuration parameter names in parentheses (such as `(text_transformations.dashes)`, `(metainformation.title_template)`, `(page_map)`, `(fix_zip)`, etc.) from all Settings labels and descriptions in both Russian and English locales.

#### _Bug Fixes & Maintenance_

- _Fixed separator collapsing around empty tags and empty series groups in both Python preview (`render_filename_from_tokens`) and generated `fb2cng` Go templates (`build_fbc_output_name_template`), preventing double hyphens (`- -`) for standalone books._
- _Added backward-compatible settings migration in `load_app_settings` and preset application: legacy default `filename_tokens` in `default` mode upgrade automatically without overwriting user-edited templates, and legacy `title_template_mode: "default"` migrates to `"filename"`._
- _Updated all 8 built-in device presets in `presets_defaults/`; expanded the unit test suite to 148 passing tests._

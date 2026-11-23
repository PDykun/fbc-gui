# FBC GUI v2.1 (Build 45) — Release Notes & Материалы для сайта

## 1. Release Notes (RU / EN)

### Русская версия (RU)
**FBC GUI v2.1 (сборка 45) — Внешние темы QSS, дизайн Modern и переключатель День / Ночь**
- **Внешняя архитектура тем оформления (`themes/*.qss`)**: все стили интерфейса вынесены из кода приложения во внешние файлы QSS (`modern_dark.qss`, `modern_light.qss`, `golden_dark.qss`, `golden_light.qss`), что позволяет легко редактировать и добавлять собственные темы без пересборки программы.
- **Новая тема оформления Modern**: внедрён новый современный дизайн интерфейса в двух вариантах — **Nighttime (Deep Midnight Slate)** и **Daytime (Nordic Minimalism / macOS Style)** с семантическими акцентами кнопок (`Добавить файлы`, `Заменить обложку`, `Сконвертировать всё и отправить`).
- **Объединённая тема Golden**: классические палитры `Midnight` (ночная) и `Light` (дневная) объединены в единое семейство **Golden**; устаревшая тема `Nordic Slate` удалена.
- **Быстрый переключатель День / Ночь (`☀` / `☾`)**: в центральной верхней части главного окна добавлен переключатель принудительной смены дневного и ночного режима с плавным переходом (cross-fade).
- **Обновлённые режимы выбора темы**: в разделе «Настройки → Оформление интерфейса» доступны режимы **Авто** (синхронизация с темой macOS / Windows), **Golden** и **Modern**.

### English Version (EN)
**FBC GUI v2.1 (Build 45) — External QSS Themes, Modern Design & Day/Night Toggle**
- **External Theme Architecture (`themes/*.qss`)**: UI stylesheets are now decoupled from application code into external `.qss` files (`modern_dark.qss`, `modern_light.qss`, `golden_dark.qss`, `golden_light.qss`) for effortless customization and extensibility.
- **New Modern Theme**: introduced the sleek **Modern** design featuring both **Nighttime (Deep Midnight Slate)** and **Daytime (Nordic Minimalism / macOS Style)** variants with semantic primary and secondary action accents.
- **Unified Golden Theme**: combined the classic `Midnight` (night) and `Light` (day) palettes into the **Golden** theme family; removed the legacy `Nordic Slate` theme.
- **Header Day / Night Switch (`☀` / `☾`)**: added a centered top-bar pill toggle on the main window for instant manual switching between daytime and nighttime modes with smooth cross-fade animation.
- **Streamlined Theme Selector**: Settings now offer **Auto** (tracks OS system appearance), **Golden**, and **Modern**.

---

## 2. Информационные блоки для размещения на сайте программы

### Блок 1: Новый интерфейс Modern и мгновенное переключение День / Ночь (`☀` / `☾`)
**Заголовок (RU):** Современный дизайн Modern и переключатель День / Ночь в один клик  
**Описание (RU):**  
В версии 2.1 представлена новая тема **Modern**, созданная специально для комфортной работы как при дневном освещении, так и в тёмное время суток. В центре верхней панели главного окна расположен переключатель **День / Ночь (`☀` / `☾`)**, позволяющий мгновенно менять светлое и тёмное оформление любой выбранной темы без перехода в настройки.

**Title (EN):** Modern Interface Design & One-Click Day / Night Switch  
**Description (EN):**  
Version 2.1 introduces the **Modern** theme, crafted for effortless readability in both daylight and low-light environments. A new **Day / Night (`☀` / `☾`)** pill switch centered in the top bar lets you toggle between light and dark modes instantly from any tab.

**Иллюстрации и кропы:**
- Полный скриншот (Modern Dark): `/Applications/fbc/new_theme/screenshots/modern_dark_converter.png`
- Полный скриншот (Modern Light): `/Applications/fbc/new_theme/screenshots/modern_light_converter.png`
- Кроп шапки с переключателем (Dark): `/Applications/fbc/new_theme/screenshots/crop_header_toggle_dark.png`
- Кроп шапки с переключателем (Light): `/Applications/fbc/new_theme/screenshots/crop_header_toggle_light.png`

---

### Блок 2: Открытая система внешних тем QSS (`Авто`, `Golden`, `Modern`)
**Заголовок (RU):** Гибкая система внешних стилей QSS и темы Golden / Modern  
**Описание (RU):**  
Все таблицы стилей интерфейса теперь хранятся во внешних файлах `.qss` в папке `themes/`. Вы можете выбрать автоматическое следование системной теме macOS/Windows (**Авто**), фирменную тему **Golden** (включающую ночной режим *Midnight* и дневной *Light*) или новую тему **Modern**, а также свободно модифицировать и дополнять файлы оформления.

**Title (EN):** Open External QSS Styling Engine (`Auto`, `Golden`, `Modern`)  
**Description (EN):**  
All interface stylesheets now live in external `.qss` files inside the `themes/` folder. Choose **Auto** to follow your macOS/Windows system appearance, **Golden** (*Midnight* night & *Light* day), or **Modern**, and easily customize or add new `.qss` themes.

**Иллюстрации и кропы:**
- Кроп настроек тем (Dark): `/Applications/fbc/new_theme/screenshots/crop_settings_themes_dark.png`
- Кроп настроек тем (Light): `/Applications/fbc/new_theme/screenshots/crop_settings_themes_light.png`
- Полный скриншот Golden (Midnight Dark): `/Applications/fbc/new_theme/screenshots/golden_dark_converter.png`
- Полный скриншот Golden (Light Day): `/Applications/fbc/new_theme/screenshots/golden_light_converter.png`

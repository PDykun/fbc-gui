# FBC GUI v2.3 (Build 47) — Release Notes & Материалы для сайта

## 1. Release Notes (RU / EN)

### Русская версия (RU)
**FBC GUI v2.3 (сборка 47) — Контекстное меню списка книг, редактор метаданных и быстрый выбор формата**
- **Контекстное меню списка книг**: при клике правой кнопкой мыши по строке книги в таблице конвертации открывается меню с действиями **«Редактировать»** и **«Удалить»**.
- **Окно редактирования книги**: выбор пункта «Редактировать» открывает отдельное тематическое окно со всеми редактируемыми метаданными (фамилия, имя, отчество, серия, номер в серии, название), живым предпросмотром итогового имени файла, а также просмотром, заменой и сбросом обложки конкретной книги. Кнопки **«Применить»** и **«Отменить»** позволяют либо сохранить изменения в строку таблицы, либо закрыть окно без изменений.
- **Быстрое удаление строк**: пункт «Удалить» мгновенно исключает выбранную книгу из списка конвертации.
- **Выпадающий список форматов на главном экране**: на панели управления главного окна добавлен стилизованный выпадающий список целевых форматов (`EPUB2`, `EPUB3`, `KEPUB`, `KEPUB3`, `AZW3`, `KFX`, `AZW8`, `PDF`, `TXT`, `MD`) с двусторонней синхронизацией с разделом «Настройки».

### English Version (EN)
**FBC GUI v2.3 (Build 47) — Book Row Context Menu, Metadata Editor & Quick Format Selector**
- **Book List Context Menu**: right-clicking any book row in the conversion table opens a themed context menu with **Edit** and **Delete** actions.
- **Book Metadata & Cover Editor**: selecting **Edit** opens a dedicated dialog with all editable metadata fields (last name, first name, middle name, series, series number, title), a live output filename preview, and cover preview/replacement/reset for that specific book, with **Apply** and **Cancel** buttons.
- **Quick Row Removal**: selecting **Delete** removes the selected book from the conversion list.
- **Main-Screen Format Dropdown**: added a styled target format dropdown (`EPUB2`, `EPUB3`, `KEPUB`, `KEPUB3`, `AZW3`, `KFX`, `AZW8`, `PDF`, `TXT`, `MD`) on the converter toolbar with two-way synchronization with Settings.

---

## 2. Информационные блоки для размещения на сайте программы

### Блок 1: Контекстное меню и полноценный редактор метаданных и обложки книги
**Заголовок (RU):** Удобное управление каждой книгой: контекстное меню и редактор метаданных  
**Описание (RU):**  
Нажмите правой кнопкой мыши на любую строку в списке конвертации, чтобы быстро открыть редактор книги или удалить её из очереди. В окне редактирования собраны все поля метаданных (автор, серия, номер, название) с предпросмотром итогового имени файла и встроенным просмотром и заменой обложки — изменения применяются к строке только после нажатия «Применить».

**Title (EN):** Per-Book Context Menu & Full Metadata and Cover Editor  
**Description (EN):**  
Right-click any row in the conversion queue to edit the book or remove it from the list. The dedicated editor dialog brings together all metadata fields (author, series, number, title), live output filename preview, and per-book cover preview and replacement — applying changes to the table only when you click Apply.

**Иллюстрации:**
- Окно редактирования книги (Modern Dark): `/Applications/fbc/screenshots_v2.3/edit_dialog_modern_dark.png`

---

### Блок 2: Быстрая смена целевого формата прямо на главном экране
**Заголовок (RU):** Мгновенное переключение формата конвертации на главной панели  
**Описание (RU):**  
Теперь не нужно переходить в раздел настроек, чтобы сменить выходной формат: на верхней панели конвертера рядом с кнопкой запуска появился выпадающий список форматов (`EPUB2`, `EPUB3`, `KEPUB`, `AZW3`, `KFX`, `PDF` и др.). Выбор на главном экране автоматически синхронизируется с настройками и наоборот.

**Title (EN):** Quick Target Format Switcher on the Main Toolbar  
**Description (EN):**  
Switch the target e-book format directly from the main converter toolbar without leaving the queue (`EPUB2`, `EPUB3`, `KEPUB`, `AZW3`, `KFX`, `PDF`, and more). Changes made in the main window stay in two-way sync with Settings.

**Иллюстрации:**
- Главный экран с выбором формата (Modern Dark): `/Applications/fbc/screenshots_v2.3/main_modern_dark.png`
- Главный экран (Modern Light): `/Applications/fbc/screenshots_v2.3/main_modern_light.png`
- Главный экран (Golden Dark): `/Applications/fbc/screenshots_v2.3/main_golden_dark.png`

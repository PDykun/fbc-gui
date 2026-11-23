# FBC GUI v2.8.2 (Build 59) — Release Notes

## Русская версия (RU)

**Версия 2.8.2 (Ноябрь 2026) — Автосборка и публикация дистрибутивов на GitHub • macOS и Windows (сборка 59)**

### Что изменилось с версии 2.8.1 до 2.8.2

- **Автономная сборка дистрибутивов в GitHub Actions (`.github/workflows/release.yml`)**:
  - Workflow сборки сделан полностью самодостаточным (без зависимости от локальных скриптов): автоматически собирает `FBC_GUI_v2.8.2_mac.dmg` для macOS и установщик `FBC_GUI_Setup_v2.8.2.exe` (Inno Setup) для Windows, предварительно прогоняя все 52 юнит-теста на обеих платформах.
  - Исправлены пути ресурсов PyInstaller для Windows (`--add-data`, иконка, метаданные версии `VSVersionInfo`, генерация `installer.iss` в CI).
  - Добавлена проверка отсутствия стороннего бинарника `fbc` и обязательного наличия лицензии шрифтов `fonts/OFL-1.1.txt` в собранном бандле, а также генерация `SHA256SUMS.txt` и автоматическая публикация релиза с приложением Release Notes по тегу `v*`.
- **Перенос дистрибутивов и обновлений на GitHub Releases**:
  - Прямые ссылки на загрузку дистрибутивов в манифесте автообновления (`version.json`) и на официальном сайте переведены на GitHub Releases ([PDykun/fbc-gui](https://github.com/PDykun/fbc-gui)).
- **Обновление версии и документации**:
  - Версия приложения обновлена до `2.8.2` (сборка `59`).
  - Добавлен отдельный файл `RELEASE_NOTES_v2.8.2.md` и исправлены синтаксис бейджей и команда `git clone` в `README.md`.

### Ключевые особенности открытой ветки v2.8.1–v2.8.2

- **Чистый дистрибутив без встроенных сторонних бинарников**: исполняемые файлы `fb2cng` (`fbc` / `fbc.exe`) удалены из исходного кода, `.app`/`.dmg` для macOS и установщика `.exe` для Windows.
- **Автопоиск, проверка и загрузка `fb2cng` при запуске (`core/fbc_manager.py`)**: при первом запуске программа находит `fbc` в `PATH` / стандартных каталогах ОС или автоматически загружает актуальную сборку с [rupor-github/fb2cng](https://github.com/rupor-github/fb2cng) с проверкой версии (`>= 2.1.1`) и контрольных сумм SHA256/MD5 (`FbcSetupDialog`).
- **Переносимость `config.yaml` и стилей CSS**: относительный `stylesheet_path: "ebook_styles.css"` автоматически пробрасывается в изолированную рабочую папку конвертера (`_attach_stylesheet_file`).
- **Открытый исходный код и лицензии**: проект опубликован на GitHub ([PDykun/fbc-gui](https://github.com/PDykun/fbc-gui)) под лицензией **GNU GPL v3.0** (`LICENSE`), включена лицензия **SIL Open Font License 1.1** (`fonts/OFL-1.1.txt`) для шрифтов **PT Astra Serif** и **Pomorsky Unicode**.

---

## English Version (EN)

**Version 2.8.2 (November 2026) — Automated GitHub Releases & Builds • macOS & Windows (build 59)**

### Changes from v2.8.1 to v2.8.2

- **Self-Contained GitHub Actions Release Pipeline (`.github/workflows/release.yml`)**:
  - Made the release workflow fully self-contained (no dependency on gitignored local build scripts): automatically builds `FBC_GUI_v2.8.2_mac.dmg` for macOS and `FBC_GUI_Setup_v2.8.2.exe` (Inno Setup) for Windows after passing all 52 unit tests on both platforms.
  - Fixed Windows PyInstaller resource paths (`--add-data`, icon, `VSVersionInfo`, and CI-generated `installer.iss`).
  - Added bundle verification checks ensuring no third-party `fbc` binary is bundled and `fonts/OFL-1.1.txt` is present, plus `SHA256SUMS.txt` checksum generation and automated GitHub Release creation with release notes on `v*` tags.
- **Distribution & Auto-Updater Migration to GitHub Releases**:
  - Direct download links in the auto-updater manifest (`version.json`) and on the official website now point to GitHub Releases ([PDykun/fbc-gui](https://github.com/PDykun/fbc-gui)).
- **Version Bump & Documentation Fixes**:
  - Bumped application version to `2.8.2` (build `59`).
  - Added dedicated `RELEASE_NOTES_v2.8.2.md` and fixed badge syntax and the `git clone` command in `README.md`.

### Highlights of the Open-Source v2.8.1–v2.8.2 Series

- **Clean Distribution Without Bundled Third-Party Binaries**: `fb2cng` (`fbc` / `fbc.exe`) executables are excluded from the repository, macOS `.app`/`.dmg`, and Windows `.exe` installer.
- **Automatic `fb2cng` Discovery, Verification & Download (`core/fbc_manager.py`)**: on startup, FBC GUI locates `fbc` in `PATH` or standard OS directories, or downloads and verifies the matching release from [rupor-github/fb2cng](https://github.com/rupor-github/fb2cng) with version (`>= 2.1.1`) and SHA256/MD5 checks (`FbcSetupDialog`).
- **Portable `config.yaml` & CSS Resolution**: relative `stylesheet_path: "ebook_styles.css"` is linked into the isolated conversion working directory (`_attach_stylesheet_file`).
- **Open-Source Licensing & Font Notices**: published on GitHub ([PDykun/fbc-gui](https://github.com/PDykun/fbc-gui)) under **GNU GPL v3.0** (`LICENSE`), with full **SIL Open Font License 1.1** (`fonts/OFL-1.1.txt`) notices for **PT Astra Serif** and **Pomorsky Unicode**.

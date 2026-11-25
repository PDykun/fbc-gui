# FBC GUI v2.8.2 (Build 59) — Release Notes

## Русская версия (RU)

**Версия 2.8.2 (Ноябрь 2026) — Автосборка и публикация дистрибутивов на GitHub • macOS и Windows (сборка 59)**

### ✨ Новые возможности

- **Автономная сборка дистрибутивов в GitHub Actions (`.github/workflows/release.yml`)**:
  - Полностью самодостаточный пайплайн сборки `FBC_GUI_v2.8.2_mac.dmg` (macOS) и `FBC_GUI_Setup_v2.8.2.exe` (Windows, Inno Setup) с обязательным прогоном юнит-тестов на обеих платформах, генерацией `SHA256SUMS.txt` и автопубликацией релиза по тегу `v*`.
  - Встроенные проверки отсутствия стороннего `fbc` и наличия лицензии `fonts/OFL-1.1.txt` в собранных бандлах.
- **Перенос дистрибутивов и автообновлений на GitHub Releases**:
  - Прямые ссылки на дистрибутивы в манифесте обновлений (`version.json`) и на сайте переведены на [PDykun/fbc-gui](https://github.com/PDykun/fbc-gui).
- **Ключевые особенности открытой ветки v2.8.1–v2.8.2**:
  - **Чистый дистрибутив без сторонних бинарников**: `fb2cng` (`fbc`/`fbc.exe`) исключён из репозитория и установщиков.
  - **Автопоиск, проверка и загрузка `fb2cng` (`core/fbc_manager.py`)**: поиск в `PATH` или автоматическая загрузка с [rupor-github/fb2cng](https://github.com/rupor-github/fb2cng) с проверкой версии (`>= 2.1.1`) и хешей SHA256/MD5 (`FbcSetupDialog`).
  - **Переносимость `config.yaml` и CSS** (`_attach_stylesheet_file`) и открытые лицензии **GNU GPL v3.0** + **SIL OFL 1.1** (`fonts/OFL-1.1.txt`).

#### _Исправления ошибок и техническое обслуживание_

- _Исправлены пути ресурсов PyInstaller для Windows (`--add-data`, иконка, `VSVersionInfo`, генерация `installer.iss` в CI)._
- _Исправлены синтаксис бейджей и команда `git clone` в `README.md`; версия обновлена до `2.8.2` (сборка 59)._

---

## English Version (EN)

**Version 2.8.2 (November 2026) — Automated GitHub Releases & Builds • macOS & Windows (build 59)**

### ✨ New Features

- **Self-Contained GitHub Actions Release Pipeline (`.github/workflows/release.yml`)**:
  - Fully self-contained CI builds for `FBC_GUI_v2.8.2_mac.dmg` (macOS) and `FBC_GUI_Setup_v2.8.2.exe` (Windows, Inno Setup) after passing unit tests on both platforms, with `SHA256SUMS.txt` generation and automated releases on `v*` tags.
  - Automated bundle checks verifying no third-party `fbc` binary is bundled and `fonts/OFL-1.1.txt` is included.
- **Distribution & Auto-Updater Migration to GitHub Releases**:
  - Direct download links in `version.json` and on the official website now point to [PDykun/fbc-gui](https://github.com/PDykun/fbc-gui).
- **Highlights of the Open-Source v2.8.1–v2.8.2 Series**:
  - **Clean Distribution Without Bundled Binaries**: `fb2cng` (`fbc`/`fbc.exe`) excluded from repo and installers.
  - **Automatic `fb2cng` Discovery, Verification & Download (`core/fbc_manager.py`)**: locates `fbc` in `PATH` or downloads/verifies from [rupor-github/fb2cng](https://github.com/rupor-github/fb2cng) (`>= 2.1.1`, SHA256/MD5, `FbcSetupDialog`).
  - **Portable `config.yaml` & CSS Resolution** (`_attach_stylesheet_file`) and open-source licensing (**GNU GPL v3.0** + **SIL OFL 1.1** in `fonts/OFL-1.1.txt`).

#### _Bug Fixes & Maintenance_

- _Fixed Windows PyInstaller resource paths (`--add-data`, icon, `VSVersionInfo`, and CI-generated `installer.iss`)._
- _Fixed badge syntax and `git clone` command in `README.md`; bumped version to `2.8.2` (build 59)._

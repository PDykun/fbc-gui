# FBC GUI v2.9 (Build 69) — Release Notes

## Русская версия (RU)

**Версия 2.9 (Ноябрь 2026) — Новая система обновлений через GitHub Releases (SHA-256) и нативные сборки для macOS ARM/Intel и Windows x64/ARM • сборка 69**

### ✨ Новые возможности

- **Нативная поддержка 4 платформ и матричная сборка в GitHub Actions (`.github/workflows/release.yml`, `installer.iss`)**:
  - Автоматическая сборка дистрибутивов для всех четырёх целевых архитектур:
    - **macOS Apple Silicon (ARM64)**: `FBC_GUI_v2.9_macos_arm64.dmg`
    - **macOS Intel (x64)**: `FBC_GUI_v2.9_macos_x64.dmg`
    - **Windows Intel/AMD (x64)**: `FBC_GUI_Setup_v2.9_win_x64.exe`
    - **Windows ARM (ARM64)**: `FBC_GUI_Setup_v2.9_win_arm64.exe`
  - Параметризация Inno Setup (`/DMyAppArch`) и поддержка тихого обновления (`/SILENT`) с автозакрытием и перезапуском.
- **Гибридная система автообновлений через GitHub Releases (`core/updater.py`, `fbc_gui.py`, `ui/dialogs.py`)**:
  - Проверка обновлений по постоянному CDN-адресу `releases/latest/download/version.json` без лимитов GitHub REST API.
  - Семантическое сравнение версий (`packaging.version.Version`) и точный подбор дистрибутива по ОС и архитектуре (`macos-arm64`, `macos-x64`, `windows-x64`, `windows-arm64`).
  - Новый пункт **«Проверить обновления...»** в меню **«Справка»** в дополнение к вкладке «О программе» и фоновой проверке при старте.
- **Встроенная загрузка с проверкой SHA-256 и нативная установка**:
  - Тематический диалог загрузки обновления с прогрессом в МБ, статусами и отменой.
  - Обязательная проверка **SHA-256** по манифесту `version.json` с автоматическим удалением файла при несовпадении.
  - Тихое обновление установщиком Inno Setup на Windows (или `.bat`-подмена для portable) и автоматическое монтирование `.dmg` в Finder на macOS.

#### _Исправления ошибок и техническое обслуживание_

- _Автоматическая генерация `version.json` с SHA-256 хешами всех 4 платформ в GitHub Actions и `update_version_json.py`._
- _Набор юнит-тестов расширен до 76 тестов (`tests/test_updater.py`)._

---

## English Version (EN)

**Version 2.9 (November 2026) — GitHub Releases Auto-Updater (SHA-256) & Native Builds for macOS ARM/Intel and Windows x64/ARM • build 69**

### ✨ New Features

- **Native 4-Platform Support & GitHub Actions Matrix Builds (`.github/workflows/release.yml`, `installer.iss`)**:
  - Automated builds for all four target platforms:
    - **macOS Apple Silicon (ARM64)**: `FBC_GUI_v2.9_macos_arm64.dmg`
    - **macOS Intel (x64)**: `FBC_GUI_v2.9_macos_x64.dmg`
    - **Windows Intel/AMD (x64)**: `FBC_GUI_Setup_v2.9_win_x64.exe`
    - **Windows ARM (ARM64)**: `FBC_GUI_Setup_v2.9_win_arm64.exe`
  - Parameterized Inno Setup (`/DMyAppArch`) with silent upgrade (`/SILENT`) and automatic relaunch.
- **Hybrid GitHub Releases Auto-Updater (`core/updater.py`, `fbc_gui.py`, `ui/dialogs.py`)**:
  - Checks `releases/latest/download/version.json` via CDN redirect with no REST API rate limits.
  - Semantic version comparison (`packaging.version.Version`) and strict OS/architecture matching (`macos-arm64`, `macos-x64`, `windows-x64`, `windows-arm64`).
  - Added **Check for Updates...** to the **Help** menu bar alongside the About page button and non-blocking startup check.
- **In-App Download, SHA-256 Verification & OS-Native Installation**:
  - Themed download progress dialog with MB progress, stage labels, and cancellation.
  - Strict **SHA-256** verification against `version.json` with immediate removal of corrupted/mismatched downloads.
  - Silent Inno Setup upgrade on Windows (and self-cleaning `.bat` swapper for portable builds) plus automatic `.dmg` mounting in Finder on macOS.

#### _Bug Fixes & Maintenance_

- _Automated `version.json` generation with SHA-256 checksums for all 4 platforms in GitHub Actions and `update_version_json.py`._
- _Expanded unit test suite to 76 tests (`tests/test_updater.py`)._

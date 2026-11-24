# FBC GUI v2.9 (Build 69) — Release Notes

## Русская версия (RU)

**Версия 2.9 (Ноябрь 2026) — Новая система обновлений через GitHub Releases (SHA-256) и нативные сборки для macOS ARM/Intel и Windows x64/ARM • сборка 69**

### Что изменилось с версии 2.8.3 до 2.9

- **Нативная поддержка 4 платформ и автоматическая сборка в GitHub Actions (`.github/workflows/release.yml`, `installer.iss`, `make_dmg.sh`, `make_installer.bat`, `setup_and_build_win.bat`)**:
  - Настроена автоматическая матричная сборка дистрибутивов и установщиков для всех четырёх целевых систем:
    - **macOS Apple Silicon (ARM64)**: `FBC_GUI_v2.9_macos_arm64.dmg`
    - **macOS Intel (x64)**: `FBC_GUI_v2.9_macos_x64.dmg`
    - **Windows Intel/AMD (x64)**: `FBC_GUI_Setup_v2.9_win_x64.exe`
    - **Windows ARM (ARM64)**: `FBC_GUI_Setup_v2.9_win_arm64.exe`
  - Имена всех дистрибутивов унифицированы и явно содержат целевую ОС и архитектуру.
  - Скрипт Inno Setup (`installer.iss`) параметризован через `/DMyAppArch` (`arm64` / `x64compatible`) и поддерживает тихое обновление (`/SILENT`) с автоматическим закрытием и перезапуском программы.
- **Гибридная система обновлений на базе GitHub Releases (`core/updater.py`, `fbc_gui.py`, `ui/dialogs.py`)**:
  - Проверка обновлений переведена с личного сайта на постоянный адрес GitHub Releases (`releases/latest/download/version.json`), использующий прямой редирект на CDN без лимитов REST API.
  - Сравнение версий переведено на семантический парсер `packaging.version.Version` (корректная обработка `2.10 > 2.9`, `0.10 > 0.9`, предрелизов и номера сборки).
  - Система обновлений автоматически определяет ОС и архитектуру (`macos-arm64`, `macos-x64`, `windows-x64`, `windows-arm64`) и загружает строго подходящий дистрибутив (x64-системы защищены от загрузки ARM64-сборок).
  - Добавлен пункт **«Проверить обновления...»** в главное меню **«Справка»** (в дополнение к кнопке на вкладке «О программе» и асинхронной фоновой проверке через 2,5 секунды после старта).
- **Проверка целостности SHA-256 и установка с учётом ОС (`core/updater.py`, `ui/dialogs.py`)**:
  - Добавлен тематический диалог загрузки обновления с отображением прогресса в мегабайтах, статусами этапов и возможностью отмены.
  - Перед запуском любого обновления сверяется контрольная сумма **SHA-256** по манифесту `version.json`; при несовпадении файл автоматически удаляется.
  - **Windows**: установщик Inno Setup скачивается во временную папку, проверяется по SHA-256 и запускается в тихом режиме (`/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`); для портативной `.exe`-версии создаётся `.bat`-скрипт подмены файла после завершения процесса.
  - **macOS**: подходящий `.dmg` (ARM64 или Intel x64) скачивается прямо из программы, проверяется по SHA-256 и автоматически монтируется и открывается в Finder.
- **CI/CD, манифест и тесты (`.github/workflows/release.yml`, `update_version_json.py`, `publish_release.sh`, `tests/test_updater.py`)**:
  - В GitHub Actions добавлена автоматическая генерация `version.json` с SHA-256 хешами всех 4 сборок и прикрепление его к релизу.
  - Набор юнит-тестов расширен до **76 тестов**.

---

## English Version (EN)

**Version 2.9 (November 2026) — GitHub Releases Auto-Updater (SHA-256) & Native Builds for macOS ARM/Intel and Windows x64/ARM • build 69**

### Changes from v2.8.3 to v2.9

- **Native 4-Platform Support & Automated GitHub Actions Matrix Builds (`.github/workflows/release.yml`, `installer.iss`, `make_dmg.sh`, `make_installer.bat`, `setup_and_build_win.bat`)**:
  - Configured automated matrix builds for all four target platforms:
    - **macOS Apple Silicon (ARM64)**: `FBC_GUI_v2.9_macos_arm64.dmg`
    - **macOS Intel (x64)**: `FBC_GUI_v2.9_macos_x64.dmg`
    - **Windows Intel/AMD (x64)**: `FBC_GUI_Setup_v2.9_win_x64.exe`
    - **Windows ARM (ARM64)**: `FBC_GUI_Setup_v2.9_win_arm64.exe`
  - Unified distributable filenames to explicitly include target OS and CPU architecture.
  - Parameterized Inno Setup (`installer.iss`) with `/DMyAppArch` (`arm64` / `x64compatible`) plus `CloseApplications=yes` and silent relaunch for `/SILENT` upgrades.
- **Hybrid GitHub Releases Update Architecture (`core/updater.py`, `fbc_gui.py`, `ui/dialogs.py`)**:
  - Migrated update checks to GitHub Releases permanent download URL (`releases/latest/download/version.json`) via CDN redirect with no REST API rate limits.
  - Switched version comparison to `packaging.version.Version` semantic versioning (`2.10 > 2.9`, `0.10 > 0.9`, prereleases, build numbers).
  - Platform-aware asset selection matches the running OS and architecture (`macos-arm64`, `macos-x64`, `windows-x64`, `windows-arm64`) and prevents x64 systems from downloading ARM64 builds.
  - Added **Check for Updates...** to the **Help** menu bar alongside the About page button and non-blocking startup check (2.5 s after launch).
- **SHA-256 Integrity Check & OS-Specific Installation (`core/updater.py`, `ui/dialogs.py`)**:
  - Added a themed update download dialog with MB progress, stage indicators, and cancellation.
  - Verifies **SHA-256** against `version.json` before launch and deletes corrupted/mismatched files immediately.
  - **Windows**: downloads Inno Setup installer to temp, verifies SHA-256, launches `/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`, and exits (portable `.exe` builds use a self-cleaning `.bat` swapper).
  - **macOS**: downloads the matching `.dmg` (ARM64 or Intel x64), verifies SHA-256, and mounts/opens the volume in Finder.
- **CI/CD, Manifest & Tests (`.github/workflows/release.yml`, `update_version_json.py`, `publish_release.sh`, `tests/test_updater.py`)**:
  - GitHub Actions automatically generates and attaches `version.json` containing SHA-256 hashes for all four platform builds.
  - Expanded the unit test suite to **76 tests**.

# FBC GUI v2.8.2 (Build 59) — Release Notes

## Русская версия (RU)

**Версия 2.8.2 (Ноябрь 2026) — Первая открытая публикация на GitHub • macOS и Windows (сборка 59)**

- **Чистый дистрибутив без встроенных сторонних бинарников**: исполняемые файлы `fb2cng` (`fbc` / `fbc.exe`) удалены из исходного кода, `.app`/`.dmg` для macOS и установщика `.exe` для Windows.
- **Автопоиск, проверка и загрузка `fb2cng` при запуске (`core/fbc_manager.py`)**:
  - При старте программа ищет `fbc` / `fbc.exe` в системном `PATH`, стандартных каталогах ОС (`/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin`, `Program Files\fb2cng`, `%LOCALAPPDATA%\Programs\fb2cng`) и папке данных приложения.
  - Идентифицирует утилиту через `--version` (отсекая сторонние программы с тем же именем), проверяет совместимость версии (`>= 2.1.1`, ветка `2.x`) и сверяет контрольные суммы MD5/SHA256 с официальными релизами [rupor-github/fb2cng](https://github.com/rupor-github/fb2cng) и локальным кэшем проверок (`fbc_verified.json`).
  - Если утилита не найдена, устарела или не прошла проверку целостности — автоматически скачивает нужную сборку под текущую ОС и архитектуру с GitHub с прогресс-баром (`FbcSetupDialog`), проверкой SHA256/MD5 архива и возможностью отмены или повтора.
- **Переносимость `config.yaml` и стилей CSS**: относительный `stylesheet_path: "ebook_styles.css"` теперь автоматически пробрасывается в изолированную рабочую папку конвертера (`_attach_stylesheet_file`), что устраняет зависимость от локальных путей на машине разработчика.
- **Лицензирование и открытый код**:
  - Проект опубликован на GitHub под лицензией **GNU GPL v3.0** (`LICENSE`).
  - Добавлен полный текст лицензии **SIL Open Font License 1.1** (`fonts/OFL-1.1.txt`) для встроенных шрифтов **PT Astra Serif** (с сохранением Reserved Font Name) и **Pomorsky Unicode**, включённый как в репозиторий, так и в дистрибутивы macOS и Windows, а также раздел `License & Third-Party Notices` в `README.md`.
- **CI/CD и автоматическая сборка релизов**: настроены GitHub Actions для прогона юнит-тестов на macOS и Windows (52 теста, включая 10 новых тестов `test_fbc_manager.py`) и автоматической сборки `.dmg`, `_Setup.exe` и `SHA256SUMS.txt` при публикации тега `v*`.

---

## English Version (EN)

**Version 2.8.2 (November 2026) — First Open-Source GitHub Release • macOS & Windows (build 59)**

- **Clean Distribution Without Bundled Third-Party Binaries**: `fb2cng` (`fbc` / `fbc.exe`) executables have been removed from the repository, macOS `.app`/`.dmg` bundle, and Windows `.exe` installer.
- **Automatic `fb2cng` Discovery, Verification & Download (`core/fbc_manager.py`)**:
  - On startup, FBC GUI searches the OS `PATH`, standard installation directories (`/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin`, `Program Files\fb2cng`, `%LOCALAPPDATA%\Programs\fb2cng`), and the application data directory.
  - Verifies binary identity via `--version` (rejecting unrelated tools named `fbc`), checks version compatibility (`>= 2.1.1`, `2.x` branch), and validates MD5/SHA256 checksums against official [rupor-github/fb2cng](https://github.com/rupor-github/fb2cng) releases and the local verification cache (`fbc_verified.json`).
  - Automatically downloads the matching OS/architecture release from GitHub when missing, outdated, or failing verification, featuring a themed progress dialog (`FbcSetupDialog`), archive SHA256/MD5 verification, cancel, and retry support.
- **Portable `config.yaml` & CSS Resolution**: relative `stylesheet_path: "ebook_styles.css"` is now linked into the isolated conversion working directory (`_attach_stylesheet_file`), removing any dependency on machine-specific absolute paths.
- **Open-Source Licensing & Font Notices**:
  - Published on GitHub under the **GNU General Public License v3.0** (`LICENSE`).
  - Added the full **SIL Open Font License 1.1** text (`fonts/OFL-1.1.txt`) for the bundled **PT Astra Serif** (with Reserved Font Name) and **Pomorsky Unicode** fonts across both the repository and macOS/Windows installers, plus a dedicated `License & Third-Party Notices` section in `README.md`.
- **CI/CD & Automated Release Builds**: added GitHub Actions workflows for cross-platform unit testing (52 tests, including 10 new tests in `test_fbc_manager.py`) and automated macOS `.dmg`, Windows Inno Setup `.exe`, and `SHA256SUMS.txt` release builds on `v*` tags.

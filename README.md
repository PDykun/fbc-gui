
# FBC GUI

Cross-platform desktop GUI (PyQt6) for the `fb2cng` (`fbc`) e-book converter (FB2 / FB2.ZIP → EPUB, KEPUB, AZW3, MOBI) on macOS and Windows.

## Features
- Batch FB2 / ZIP import with inline metadata editing, Undo/Redo, and save-back to source FB2
- Visual CSS & typography editor with live preview (including grayscale e-ink mode) and custom font embedding
- Device presets (Kindle, Kobo, PocketBook, ONYX BOOX, reMarkable) with import/export
- Custom output filename and metadata title template builder
- Send-to-Kindle / SMTP email delivery with Keychain / Windows Credential Manager support
- Bilingual UI (English / Russian) with Modern and Golden light/dark themes

## Requirements
- Python 3.11+
- `fb2cng` (`fbc` / `fbc.exe`) is **not** bundled in this repository or in the installers. On startup, FBC GUI searches your OS `PATH` and standard locations, verifies the binary identity, version (`>= 2.1.1`), and checksum against [rupor-github/fb2cng](https://github.com/rupor-github/fb2cng), and automatically downloads the required version from GitHub if missing or incompatible.

## Running from Source
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 fbc_gui.py
```

## License & Third-Party Notices
- **FBC GUI** source code is licensed under the [GNU General Public License v3.0](LICENSE).
- **Bundled Fonts** (distributed as separate unmodified assets under their own open font license, not relicensed under GPLv3 — full license text in [fonts/OFL-1.1.txt](fonts/OFL-1.1.txt)):
  - **PT Astra Serif** (`fonts/PT-Astra-Serif_*.ttf`) — Copyright © 2016 JSC «RPA RusBITech» (designed by A. Korolkova & I. Chaeva, ParaType Ltd), licensed under the **SIL Open Font License 1.1 (OFL-1.1)** with Reserved Font Name `PT Astra Serif`.
  - **Pomorsky Unicode** (`fonts/PomorskyUnicode.otf`) — Copyright 1999–2000 Nikita Simmons; Copyright 2015 Aleksandr Andreev and Nikita Simmons (Church Slavonic Initiative / Ponomar Project), licensed under the **SIL Open Font License 1.1 (OFL-1.1)**.
- **fb2cng (`fbc`)** — external third-party converter ([rupor-github/fb2cng](https://github.com/rupor-github/fb2cng), GPL-3.0). Not bundled with FBC GUI; located on the user's system or downloaded on demand from GitHub.
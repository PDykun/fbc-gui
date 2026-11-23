
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
- `fb2cng` binary (`fbc` on macOS, `fbc.exe` on Windows) placed in the project root

## Running from Source
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 fbc_gui.py
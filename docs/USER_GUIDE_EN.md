# 📚 FBC GUI User Guide

**Русская версия:** [Руководство пользователя (RU)](USER_GUIDE_RU.md) • **Release History:** [docs/README.md](README.md)

**FBC GUI** is a cross-platform desktop studio for macOS (Apple Silicon & Intel) and Windows (x64 & ARM64) designed for batch converting, editing metadata, visually styling, and delivering **FB2** and **FB2.ZIP** e-books using the `fb2cng` engine.

## Table of Contents

1. [Installation & First Launch](#1-installation--first-launch)
2. [Converter Tab: Queue, Metadata & Covers](#2-converter-tab-queue-metadata--covers)
3. [FB2 Structure Inspector & `--debug` Reports](#3-fb2-structure-inspector----debug-reports)
4. [Styles Tab: Visual CSS & Font Manager](#4-styles-tab-visual-css--font-manager)
5. [Preview Tab: Live Book Spread](#5-preview-tab-live-book-spread)
6. [Settings Tab: Device Profiles, Presets & Template Builders](#6-settings-tab-device-profiles-presets--template-builders)
7. [Send-to-Kindle & Email Delivery (SMTP)](#7-send-to-kindle--email-delivery-smtp)
8. [Auto-Updates, Themes & Keyboard Shortcuts](#8-auto-updates-themes--keyboard-shortcuts)
9. [Troubleshooting & Diagnostics](#9-troubleshooting--diagnostics)

## 1. Installation & First Launch

### Downloading an Installer
Download the native installer for your platform from the GitHub Releases page (linked in [README](../README.md)):
- **macOS (Apple Silicon M1–M4):** `FBC_GUI_v*_macos_arm64.dmg` — open the image and drag **FBC GUI** into **Applications**.
- **macOS (Intel):** `FBC_GUI_v*_macos_x64.dmg`.
- **Windows (x64 / ARM64):** `FBC_GUI_Setup_v*_win_x64.exe` or `FBC_GUI_Setup_v*_win_arm64.exe` — optionally enable the **"Open with FBC GUI"** Explorer context menu for `.fb2` and `.zip` files during setup.

### Automatic `fb2cng` Setup
The third-party `fb2cng` (`fbc` / `fbc.exe`) converter is not bundled with installers. On first launch, FBC GUI:
1. Scans your system `PATH` and standard install directories for a compatible `fb2cng` (`>= 2.1.1`).
2. If not found, offers to download the official GitHub release automatically with **SHA-256 / MD5** checksum verification.

### User Data Directory
Application settings and user assets are stored in the `FBC_GUI` folder inside your OS application data directory (`settings.json`, `config.yaml`, `ebook_styles.css`, `fonts/`, `presets/`, `themes/`, `locales/`, and `fbc_gui.log`).

## 2. Converter Tab: Queue, Metadata & Covers

### Adding Books
- Drag and drop `.fb2` files, `.zip` archives (including multi-book archives), or entire folders onto the window.
- Click **Add Files** (`Cmd+O` / `Ctrl+O`).
- Use OS **"Open With FBC GUI"** (macOS Finder / Dock or Windows Explorer context menu) — books are routed directly into the running window.

Importing runs in a background thread with lazy on-demand XML loading so large libraries keep RAM usage low.

### Editing Metadata & Genres
- **Inline table editing:** double-click any editable cell (Last Name, First Name, Middle Name, Series, #, Title).
- **Edit Book dialog:** right-click a row → **Edit**.
  - **Basic tab:** author, series, number, title, live output filename preview, and cover management.
  - **Extended tab:** visual **FB2 Genres** editor (removable chips, live search across FictionBook 2.1 taxonomy, plus custom tags such as `litrpg`), **Language**, **Translator** (co-translators in the file are preserved), **Publisher**, **ISBN** (with ISBN-10/13 validation), and **Annotation**.
- **Online Cover & Metadata Lookup:** click **Fetch Online** right below **Restore Original** on the right cover panel (or inside the Edit Book dialog), or right-click a book → **Find Cover & Metadata Online...**. Searches **FantLab**, **LitRes** (ideal for Russian editions), **Open Library** (no key required), optional **Google Books** (using your own API key), and a universal **OPDS** catalog provider. Review the **Current → Found** comparison table, pick fields via checkboxes or presets (**Empty Only**, **All Found**, **Cover Only**), and select a cover from the deduplicated gallery — all backed by Undo/Redo.
- **Batch editing:** select multiple books → right-click → **Batch Edit...** to update author, series, language, or **Add / Replace / Remove genres** in one step.
- **Series auto-numbering:** select books in order → right-click → **Auto-number Series** (`1, 2, 3…`). Reorder rows anytime with `Alt+↑` / `Alt+↓`.
- **Save back to source FB2:** check the option in the Edit dialog or choose **Save Metadata to Source FB2** from the context menu. Writes are atomic and use minimal-diff FictionBook 2.1 XSD ordering so untouched rich markup is preserved.
- **Source FB2 Organizer (without conversion):** select one or more books → right-click → **Organize / Rename Source FB2...**. Pick a destination folder, layout (**Author / Series / File**, **Author / File**, or **Flat**), and action (**Copy** or **Move**), review the **Before → After** preview table, and click **Run**.
- **Merge into Omnibus:** select 2 or more books in the desired order → right-click → **Merge into Omnibus (N)...** to combine them into a single valid `.fb2` volume with a unified table of contents, volume list annotation, and isolated internal IDs, footnotes, and images.

### Undo / Redo
Every metadata edit, online lookup, batch update, cover replacement, row reorder, removal, or list clear supports multi-level **Undo / Redo** (`Cmd+Z` / `Ctrl+Z`, `Shift+Cmd+Z` / `Ctrl+Y`, or the **↩ / ↪** buttons).

### Search, Filters, Deduplication & Skip Existing
- **Instant search (`Cmd+F` / `Ctrl+F`, `Esc` to reset):** matches filenames, authors, series, titles, genres, language, publisher, ISBN, and output names.
- **Status filter pills:** **All / Pending / Done / Errors / ⚠ Warnings**.
- **Queue deduplication:** books sharing normalized author, series, number, and title are flagged **≈ Duplicate**. Click **Remove Duplicates (N)** to clean the queue in one step (Undo supported).
- **Skip existing:** when enabled, books whose target output file already exists, is at least as new as the source, and have no unsaved metadata/cover edits are marked **↷ Skipped** instead of re-converting.

### Covers
Select a book to inspect its cover and dimensions in the right panel. **Replace Cover...** automatically fits the image to `600×900 px` (LANCZOS), **Restore Original** reverts to the embedded cover, and **Fetch Online** immediately opens the online cover & metadata lookup dialog for the selected book.

### Running Conversion
- Choose the target format from the toolbar dropdown (`EPUB2`, `EPUB3`, `KEPUB`, `KEPUB3`, `AZW3`, `KFX`, `AZW8`, `PDF`, `TXT`, `MD`).
- Click **Convert All** (`Cmd+Enter` / `Ctrl+Enter`) or **Selected (N)** (`Shift+Cmd+Enter` / `Ctrl+Shift+Enter`).
- Clicking **Cancel** terminates active `fbc` processes immediately. If any books fail, click **Retry Failed** in the summary dialog.

## 3. FB2 Structure Inspector & `--debug` Reports

During import, each book runs a lightweight pre-flight check: XML defects, missing covers, or empty title/author are flagged with **`⚠ N`** in the Status column.

Right-click any book and select **FB2 Inspector...** for a full audit:
- **Summary & Checks:** declared encoding, XML size, strict/recovered XML status, chapter/paragraph/footnote counts, and diagnostic warnings.
- **Table of Contents (TOC):** full nested chapter tree.
- **Images:** table of embedded `<binary>` items with pixel dimensions, file size, and badges (`cover`, `> 2 MB`, `Corrupted`).
- **Repair & Optimize FB2:** when broken XML, corrupted `<binary>` entries, or `> 2 MB` images are detected, click **Repair & Optimize FB2** to repair XML to clean UTF-8, remove empty/corrupted attachments, downsize oversized images, and atomically write back to the source file.
- **Convert with `--debug`:** runs conversion with `--debug` to produce a `*_fbc-report.zip` diagnostic archive next to the output file.

## 4. Styles Tab: Visual CSS & Font Manager

Every setting auto-saves to `ebook_styles.css` and updates the live preview immediately:
- **1. Book Fonts:** choose fonts for body text, drop caps, book title, and author name, plus the optional PDF page frame. Selecting **None** omits `@font-face` rules so your e-reader's built-in fonts are used.
  - On the right, the **Font Drop Zone** accepts `.ttf`, `.otf`, `.woff`, and `.woff2` files via Drag & Drop (or click the zone / **Add Fonts...**). FBC GUI validates each font header, copies it to `fonts/`, and refreshes all pickers and preview instantly.
- **2. Title Page & Headings:** size, color, alignment, and font style for book title, author, and `H2–H5`.
- **3. Body Text & Drop Cap:** paragraph alignment, first-line indent, scene subtitles, drop cap color and size.
- **4. Annotation, Epigraphs, Poems & Footnotes:** typography, background fill, and border styling.
- **5. Illustrations & SVG:** alignment, max width, captions, **Reader Display** optimization profile (`Off`, `B&W E Ink Carta 1200/1300`, `B&W 16 Gray Levels Dithered`, `Color E Ink Kaleido 3`, `Color E Ink Gallery 3 / Canvas Color`), **Grayscale (Luma)**, fit-to-screen, and cover resize mode.

## 5. Preview Tab: Live Book Spread

Preview renders either your **currently selected book** (full-bleed cover with spine shadow on the left page, title/annotation/epigraph/opening chapter on the right) or a **comprehensive style sample**.
- Uses native **WebKit (WKWebView)** on macOS and **Edge WebView2** on Windows.
- Toggle **Simulate E Ink Display** to preview how covers and pages will render on the selected physical e-ink display type (synced with Styles and device presets).
- Click **Open in Browser** to export and inspect the preview in your default browser.

## 6. Settings Tab: Device Profiles, Presets & Template Builders

- **User Presets (Settings + CSS):** save complete conversion + CSS bundles as `.fbcpreset.json`, switch in one click, restore built-in defaults, or share via **Export / Import** (SMTP credentials and local paths are automatically stripped).
- **Device Profiles:** 8 built-in e-reader profiles (**Kindle Paperwhite 2024**, **Kindle Scribe 2022/2024/2025/Colorsoft**, **Kobo Libra Colour**, **PocketBook InkPad 4**, **ONYX BOOX Go 10.3**, **reMarkable Paper Pro**) + **PDF A5**.
- **Visual Template Builders:** drag and drop metadata pills (`Last Name`, `First Name`, `Series`, `Series Abbr`, `Series #`, `Title`, `Format`) and separators for both:
  - **Output filename template** (`output_name_template`);
  - **E-reader library title template** (`metainformation.title_template`).
- **Typography & Navigation (`fb2cng`):** footnotes mode (linked / popup / renumbered), soft hyphenation, drop caps, direct speech/dash/dialogue typography, separate annotation page & annotation-in-TOC (`annotation.in_toc`), visible TOC placement (`None / Before / After`), TOC hierarchy (`Normal / Old Kindle / Flat`), untitled chapters in TOC, **EPUB Page Map (`page_map`)** with Adobe DE compatibility, `fix_zip` for legacy readers, and illustration `scale_factor` (`0.5–2.0`).
- **Conversion Threads:** `Auto` or `1–8` parallel `fb2cng` workers.
- **Online Metadata & Cover Lookup:** choose active catalogs (**FantLab**, **LitRes**, **Open Library**, **Google Books**, **OPDS**), optionally enter your Google Books API key, and configure a custom OPDS catalog (URL plus optional Basic Auth credentials — secrets are stored securely in system Keychain / `keyring`).

### Connecting a Custom OPDS Catalog (Flibusta Example)
The universal OPDS provider works with any standard **OPDS (Atom XML + OpenSearch)** catalog — both self-hosted servers (**Calibre-Web**, **Kavita**, or a local `archiveopds` instance on a NAS over `http://` or `https://`) and public OPDS libraries.

Example setup for **Flibusta**:
1. Open **Settings → Online Metadata & Cover Lookup**.
2. Enable **OPDS** under **Search providers**.
3. In **Custom OPDS catalog URL**, enter the root OPDS catalog address:
   - `https://flibusta.is/opds` (FBC GUI automatically discovers the OpenSearch template),
   - or enter a direct search URL template: `https://flibusta.site/opds/search?searchTerm={searchTerms}&searchType=books`.
4. Leave **Username** and **Password** blank for public search (fill them in only for Basic Auth protected catalogs such as private Calibre-Web / Kavita servers).
5. Click **Fetch Online** on the cover panel — **OPDS** will appear alongside the other active catalogs.

> **Note:** if direct access to a domain is restricted in your region, use an accessible mirror, VPN, or a self-hosted OPDS server on your local network (e.g., `http://192.168.x.x:8083/opds`).

## 7. Device Delivery (USB / MTP) & Email Delivery (SMTP)

### Email Delivery (SMTP)
In **Settings → Email Delivery**:
1. Enable **Auto-send converted files**.
2. Enter your SMTP host, port (`465` for SSL or `587` for STARTTLS), encryption, username, app password, and recipient address (e.g. your `@kindle.com` address).
3. Click **Send Test Email** to verify connectivity.

Passwords are stored in your OS secret vault (**macOS Keychain** or **Windows Credential Manager**). Large batches are automatically split into **20 MB** email chunks.

### Direct Device Delivery (USB / MTP / sync2kindle)
In **Settings → Device Delivery** (or via the **To Reader** button on the Converter toolbar):
- **MTP (Kindle)** for modern Kindles (Scribe, Paperwhite 12, Colorsoft) and **USB (Kindle)** for legacy USB mass-storage Kindles. On first use, FBC GUI automatically downloads `sync2kindle` (`s2k`) from GitHub with checksum verification.
- **Reader Folder** copies converted e-books (`.epub`, `.azw3`, `.kfx`, `.azw8`, `.pdf`, `.mobi`) directly to a mounted Kobo / PocketBook / ONYX BOOX folder while skipping already up-to-date files. Click **Detect Reader** to automatically discover connected USB e-readers and local Kobo cloud sync folders.
- Use **Dry Run** to preview changes safely; **Keep local books** prevents deleting local files on your computer.

### Watch Folder Mode & System Tray / macOS Menu Bar
In **Settings → Auto-Conversion (Watch Folders) & Tray**:
- Add **multiple watched folders simultaneously** (e.g., `ToKindle` and `ToKobo`), linking each to its own conversion preset, delivery method (**Folder**, **Email**, or **Reader**), and source post-action (**Move to Processed folder**, **Keep in place**, or **Move to Trash**).
- Incoming `.fb2` and `.zip` files are converted in an isolated background environment (without modifying the main window's active settings or queue), with partial-download protection (`.crdownload`, `.part`, `.tmp`) and coalesced OS notifications.
- Enable **System tray / Menu Bar icon** for background status, pause/resume, folder shortcuts, and recent history; macOS includes an optional **Hide Dock icon when minimized** toggle, and both macOS and Windows support opt-in **Launch at system login** (disabled by default).

## 8. Auto-Updates, Themes & Keyboard Shortcuts

- **Auto-Updates:** checks GitHub Releases automatically (or via **Help → Check for Updates...** / **About**), downloads the exact build for your OS & CPU architecture, and verifies **SHA-256** before installation.
- **Themes & Languages:** 2 theme families (**Modern** and **Golden**) with **Auto / Light / Dark** modes (header `☀ / ☾` toggle) and instant **English / Russian** switching.

### Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Cmd+O` / `Ctrl+O` | Add FB2 / ZIP files |
| `Cmd+F` / `Ctrl+F` | Focus queue search (`Esc` resets filter) |
| `Cmd+Z` / `Ctrl+Z` | Undo last action |
| `Shift+Cmd+Z` / `Ctrl+Y` | Redo |
| `Alt+↑` / `Alt+↓` | Move selected rows up / down |
| `Delete` / `Backspace` | Remove selected books |
| `Cmd+Enter` / `Ctrl+Enter` | Convert all books |
| `Shift+Cmd+Enter` / `Ctrl+Shift+Enter` | Convert selected books only |

## 9. Troubleshooting & Diagnostics

- **Conversion failure or layout issue:** open **FB2 Inspector...** to check XML/images, then run **Convert with Debug Report (`--debug`)** to generate `*_fbc-report.zip`.
- **Application log:** open **About → Open Log** (`fbc_gui.log`).
- **Report a bug:** open an issue in the `PDykun/fbc-gui` repository on GitHub with your FBC GUI version and relevant lines from `fbc_gui.log`.

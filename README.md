# Bamboo Filament Manager

A desktop application for managing your filament spool inventory. Scan RFID tags from your spools using a Proxmark3 reader, track usage, and organize your collection.

![Built with PyQt6](https://img.shields.io/badge/Built%20with-PyQt6-green)
![Platform](https://img.shields.io/badge/Platform-Windows-blue)

## Features

- **Scan RFID Tags** — Read filament spool RFID tags using a Proxmark3 reader. Automatically derives MIFARE keys and parses all tag data.
- **Bulk Scan** — Scan multiple spools in sequence without closing the dialog.
- **Add by Barcode/SKU** — Add spools by scanning a box barcode or typing a SKU code.
- **Add Manually** — Create entries by hand for spools without tags.
- **Import Dump Files** — Import `.bin`, `.json`, or `.nfc` tag dump files.
- **Edit & Inline Editing** — Edit filament details in a full dialog or directly in the table.
- **Weigh Spool** — Enter a scale reading to calculate remaining filament weight and length.
- **Remove by Scan** — Scan a used-up spool's tag to quickly remove it from your inventory.
- **Export/Import CSV** — Export your inventory to CSV for use in Excel, and import it back.
- **Compress Database** — Prune duplicate deleted entries to keep the database lean.
- **Color Swatches** — Visual color display with support for dual-color filaments.
- **Summary Panel** — At-a-glance spool counts and total remaining weight by filament type.

## Requirements

### Hardware
- **Proxmark3** (Easy, RDV2, or RDV4) with an **HF antenna**
  - The HF antenna is the small inner coil, not the large outer ring (that's LF)
  - Removing the LF antenna board exposes the HF coil for easier scanning

### Software
- **Proxmark3 Iceman firmware** — [github.com/RfidResearchGroup/proxmark3](https://github.com/RfidResearchGroup/proxmark3)
  - The app calls `proxmark3.exe` as a subprocess, so the Iceman client must be installed
  - On first run, point the app to your `proxmark3.exe` location (or it will try to auto-detect)
- **Windows 10/11**

## Installation

### From Installer
Download `BambooFilamentManager_Setup_0.1.0.exe` from the Releases page and run it. No admin rights required.

### From Source
```bash
git clone https://github.com/jvogel/BambooFilamentManager.git
cd BambooFilamentManager
pip install -r requirements.txt
python main.py
```

## Quick Start

1. **Connect your Proxmark3** and note the COM port (check Device Manager).
2. **Launch the app** and click **Scan Tag**.
3. **Select your COM port** and set the path to `proxmark3.exe` if not auto-detected.
4. **Click Start Scan**, then hold a filament spool's tag near the HF antenna.
5. After the scan completes, optionally enter a barcode, SKU, and color name, then click **Add to Library**.
6. Your spool appears in the table with all parsed data.

## Usage Tips

- **Double-click** any cell to edit it inline (type, weight, diameter, location, etc.).
- **Right-click** a row for quick access to Edit, Weigh, Set Color Name, or Delete.
- **Weigh Spool** calculates remaining filament from a scale reading minus the empty spool weight (tare).
- **Export CSV** produces an Excel-friendly file. UIDs, barcodes, and other long numbers are preserved as text.
- **Import CSV** matches rows by ID — existing entries are updated, new ones are added.
- The database is stored in `%APPDATA%\BambooFilamentManager\filaments.json`. Use **Open Data Folder** to find it.

## How the RFID Tags Work

Filament spools contain a MIFARE Classic 1K tag (Fudan fm11rf08s, 13.56 MHz). The tag is embedded in a clear plastic strip that threads through the spool hub.

The tags use custom MIFARE keys derived from the tag's UID via HKDF+SHA256. This app handles key derivation automatically — just scan and go.

Each tag stores: filament type, color(s), weight, length, diameter, temperature settings, material ID, production date, and more.

## Building

### PyInstaller
```bash
pip install pyinstaller
pyinstaller BambooFilamentManager.spec -y
```
Output goes to `dist\BambooFilamentManager\`.

### Installer (Inno Setup)
Install [Inno Setup 6](https://jrsoftware.org/isinfo.php), then:
```bash
iscc installer.iss
```
Output: `installer_output\BambooFilamentManager_Setup_0.1.0.exe`

## Credits

Written by **Claude Code** with testing and guidance by **Jon Vogel**.

Created by Jon Vogel.

## License

See [LICENSE](LICENSE) for details.

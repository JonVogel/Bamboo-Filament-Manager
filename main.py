# -*- coding: utf-8 -*-

# Bamboo Filament Manager — entry point.

import ctypes
import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication

# Tell Windows to use our own AppUserModelID so the taskbar shows our icon
# instead of the generic Python icon.
if sys.platform == "win32":
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        "BambooFilamentManager.BambooFilamentManager"
    )

from database import FilamentDB
from ui.main_window import MainWindow

APP_NAME = "BambooFilamentManager"


def get_data_dir() -> Path:
    """Return the app data directory, creating it if needed.
    Uses %APPDATA%/BambooFilamentManager on Windows, ~/.BambooFilamentManager elsewhere."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home()
    data_dir = base / APP_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def main():
    # Qt6 enables high-DPI scaling automatically — no setAttribute needed.
    app = QApplication(sys.argv)
    app.setOrganizationName("BambooFilamentManager")
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    # Bump the default font size for readability on high-res displays
    font = app.font()
    font.setPointSize(11)
    app.setFont(font)
    icon_path = Path(__file__).parent / "FilamentRoll.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    db_path = get_data_dir() / "filaments.json"

    # Migrate from old "BambuFilamentManager" data directory or app directory
    if not db_path.exists():
        import shutil
        old_appdata = db_path.parent.parent / "BambuFilamentManager" / "filaments.json"
        legacy = Path(__file__).parent / "filaments.json"
        if old_appdata.exists():
            shutil.copy2(old_appdata, db_path)
        elif legacy.exists():
            shutil.copy2(legacy, db_path)

    db = FilamentDB(db_path)
    window = MainWindow(db)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

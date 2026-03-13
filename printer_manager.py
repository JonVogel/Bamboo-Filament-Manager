# -*- coding: utf-8 -*-

"""
Label printer abstraction — selects the right driver based on Settings.

Drivers:
  - nelko_p21: Nelko P21 via Bluetooth serial
  - windows:   Windows default printer (os.startfile)
  - preview:   Just open the image (no printing)
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QSettings

from label_printer import generate_label


# Driver registry: key → (display name, print function)
# Each print function takes (image_path: Path, copies: int)

def _print_nelko(path: Path, copies: int = 1):
    from PIL import Image
    from nelko_printer import NelkoPrinter
    port = QSettings().value("printer/nelko_port", "COM11")
    img = Image.open(str(path))
    with NelkoPrinter(port) as printer:
        printer.print_image(img, copies=copies)


def _print_windows(path: Path, copies: int = 1):
    os.startfile(str(path), "print")


def _print_preview(path: Path, copies: int = 1):
    if os.name == "nt":
        os.startfile(str(path))


DRIVERS = {
    "nelko_p21": ("Nelko P21 (Bluetooth)", _print_nelko),
    "windows":   ("Windows Default Printer", _print_windows),
    "preview":   ("Preview Only", _print_preview),
}


def driver_names() -> list[tuple[str, str]]:
    """Return list of (key, display_name) for all drivers."""
    return [(k, v[0]) for k, v in DRIVERS.items()]


def print_label(entry: dict, copies: int = 1) -> Path:
    """Generate a label and send it to the configured printer."""
    path = generate_label(entry)
    key = QSettings().value("printer/driver", "windows")
    _, print_fn = DRIVERS.get(key, DRIVERS["windows"])
    print_fn(path, copies)
    return path

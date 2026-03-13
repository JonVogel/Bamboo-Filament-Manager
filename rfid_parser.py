# -*- coding: utf-8 -*-

# RFID tag parser for Bambu Lab filament spools.
# Adapted from https://github.com/Bambu-Research-Group/RFID-Tag-Guide/blob/main/parse.py
# Original author: Vinyl Da.i'gyu-Kazotetsu, 2024

import json
import re
import struct
from datetime import datetime
from pathlib import Path

BYTES_PER_BLOCK = 16
BLOCKS_PER_TAG = [64, 72]  # 64 = 1KB, 72 = output from Proxmark fm11rf08 script
TOTAL_BYTES = [b * BYTES_PER_BLOCK for b in BLOCKS_PER_TAG]

COMPARISON_BLOCKS = [1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14]
IMPORTANT_BLOCKS = [0] + COMPARISON_BLOCKS


# ---------------------------------------------------------------------------
# Byte conversion helpers
# ---------------------------------------------------------------------------

def bytes_to_string(data: bytes) -> str:
    return data.decode('ascii', errors='replace').replace('\x00', ' ').strip()


def bytes_to_hex(data: bytes, chunkify: bool = False) -> str:
    out = data.hex().upper()
    return " ".join(out[i:i+2] for i in range(0, len(out), 2)) if chunkify else out


def bytes_to_int(data: bytes) -> int:
    return int.from_bytes(data, 'little')


def bytes_to_float(data: bytes) -> float:
    return struct.unpack('<f', data)[0]


def bytes_to_date(data: bytes) -> datetime | str:
    string = bytes_to_string(data)
    parts = string.split("_")
    if len(parts) < 5:
        return string
    try:
        return datetime(
            year=int(parts[0]),
            month=int(parts[1]),
            day=int(parts[2]),
            hour=int(parts[3]),
            minute=int(parts[4]),
        )
    except ValueError:
        return string


# ---------------------------------------------------------------------------
# Flipper NFC file support
# ---------------------------------------------------------------------------

def strip_flipper_data(raw: bytes) -> bytes:
    pattern = re.compile(r"^[\w\s]+: [\w\s\d?]+$", re.M)
    data = dict(x.split(": ") for x in pattern.findall(raw.decode()))
    assert data.get("Version") == "4"
    assert data.get("Data format version") == "2"
    assert data.get("Device type") == "Mifare Classic"
    assert data.get("Mifare Classic type") == "1K"
    output = b""
    for key in data:
        if key.startswith("Block "):
            output += bytes.fromhex(data[key].replace("??", "00"))
    return output


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TagLengthMismatchError(TypeError):
    def __init__(self, actual_length: int):
        super().__init__(
            f"Not a valid MIFARE 1K tag "
            f"({actual_length} bytes / {actual_length // BYTES_PER_BLOCK} blocks, "
            f"expected {TOTAL_BYTES} bytes / {BLOCKS_PER_TAG} blocks)."
        )


# ---------------------------------------------------------------------------
# Tag class
# ---------------------------------------------------------------------------

class Tag:
    """
    Parses filament spool RFID tag data into structured fields.

    Accepts:
      - Raw binary data (bytes) from a .bin dump
      - Flipper NFC file data (bytes starting with "Filetype: Flipper NFC")
      - A proxmark3 JSON dict (the 'blocks' sub-dict with str keys "0".."63")
      - A list of 16-byte block bytes (from live scanner)
    """

    def __init__(self, source, data=None):
        # source may be a filename/Path (legacy) or block list; data is raw bytes when filename given
        if isinstance(source, list):
            # Called as Tag(block_list) from scanner
            blocks = source
            self.filename = None
        else:
            self.filename = source
            raw = data

            if raw is None:
                raise ValueError("data must be provided when source is a filename")

            if raw.startswith(b"Filetype: Flipper NFC"):
                raw = strip_flipper_data(raw)

            if len(raw) not in TOTAL_BYTES:
                raise TagLengthMismatchError(len(raw))

            blocks = [raw[i:i+BYTES_PER_BLOCK] for i in range(0, len(raw), BYTES_PER_BLOCK)]

        self.blocks = blocks
        self.warnings = []

        for bi in IMPORTANT_BLOCKS:
            if self.blocks[bi] == b'\x00' * BYTES_PER_BLOCK:
                self.warnings.append(f"Block {bi} is blank!")

        has_extra_color_info = self.blocks[16][0:2] == b'\x02\x00'

        self.data = {
            "uid": bytes_to_hex(self.blocks[0][0:4]),
            "filament_type": bytes_to_string(self.blocks[2]),
            "detailed_filament_type": bytes_to_string(self.blocks[4]),
            "filament_color_count": bytes_to_int(self.blocks[16][2:4]) if has_extra_color_info else 1,
            "filament_color": "#" + bytes_to_hex(self.blocks[5][0:4]),
            "spool_weight": bytes_to_int(self.blocks[5][4:6]),      # grams
            "filament_length": bytes_to_int(self.blocks[14][4:6]),  # meters
            "filament_diameter": round(bytes_to_float(self.blocks[5][8:12]), 4),  # mm
            "spool_width": bytes_to_int(self.blocks[10][4:6]) / 100,  # mm
            "material_id": bytes_to_string(self.blocks[1][8:16]),
            "variant_id": bytes_to_string(self.blocks[1][0:8]),
            "nozzle_diameter": round(bytes_to_float(self.blocks[8][12:16]), 1),  # mm
            "temperatures": {
                "min_hotend": bytes_to_int(self.blocks[6][10:12]),
                "max_hotend": bytes_to_int(self.blocks[6][8:10]),
                "bed_temp": bytes_to_int(self.blocks[6][6:8]),
                "bed_temp_type": bytes_to_int(self.blocks[6][4:6]),
                "drying_time": bytes_to_int(self.blocks[6][2:4]),
                "drying_temp": bytes_to_int(self.blocks[6][0:2]),
            },
            "x_cam_info": bytes_to_hex(self.blocks[8][0:12]),
            "tray_uid": bytes_to_hex(self.blocks[9]),
            "production_date": bytes_to_date(self.blocks[12]),
        }

        if self.data["filament_color_count"] == 2:
            second = bytes_to_hex(self.blocks[16][4:8][::-1])
            self.data["filament_color2"] = "#" + second
        else:
            self.data["filament_color2"] = None

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict of all tag fields."""
        d = {}
        for k, v in self.data.items():
            if k == "temperatures":
                d[k] = dict(v)
            elif isinstance(v, datetime):
                d[k] = v.isoformat()
            else:
                d[k] = v
        return d

    @classmethod
    def from_json_dump(cls, json_data: dict) -> "Tag":
        """
        Load a Tag from a proxmark3 JSON dump dict.
        Accepts the full JSON or just the 'blocks' sub-dict.
        """
        blocks_raw = json_data.get("blocks", json_data)
        # Build 64-block list (skip key blocks, fill with zeros)
        blocks = []
        for i in range(64):
            hex_str = blocks_raw.get(str(i), "00" * 16)
            blocks.append(bytes.fromhex(hex_str))
        return cls(blocks)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        lines = []
        for k, v in self.data.items():
            if isinstance(v, dict):
                lines.append(f"  {k}:")
                for sk, sv in v.items():
                    lines.append(f"    {sk}: {sv}")
            else:
                lines.append(f"  {k}: {v}")
        if self.warnings:
            lines.append("  warnings:")
            for w in self.warnings:
                lines.append(f"    - {w}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# File loading helpers
# ---------------------------------------------------------------------------

def load_bin_file(path: str | Path) -> Tag:
    """Load a .bin or Flipper .nfc file."""
    filepath = Path(path)
    with open(filepath, "rb") as f:
        return Tag(filepath, f.read())


def load_json_file(path: str | Path) -> Tag:
    """Load a proxmark3 JSON dump file."""
    filepath = Path(path)
    with open(filepath, "r") as f:
        return Tag.from_json_dump(json.load(f))


def load_file(path: str | Path) -> Tag:
    """Auto-detect .bin/.nfc vs .json and load accordingly."""
    p = Path(path)
    if p.suffix.lower() == ".json":
        return load_json_file(p)
    return load_bin_file(p)

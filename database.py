# -*- coding: utf-8 -*-

# JSON-backed filament inventory database.

import json
import uuid
from datetime import datetime
from pathlib import Path


DEFAULT_DB_PATH = Path("filaments.json")


class FilamentDB:
    """
    Manages a local JSON file that stores the filament inventory.

    Each entry is a dict with tag-parsed fields plus an '__inventory__' sub-dict
    for user-managed fields (remaining weight/length, location, notes).
    """

    def __init__(self, path: str | Path = DEFAULT_DB_PATH):
        self.path = Path(path)
        self._entries: list[dict] = []
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self):
        """Load entries from disk. Creates an empty DB if the file doesn't exist."""
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self._entries = json.load(f)
        else:
            self._entries = []
        self._backfill_spool_numbers()

    def _backfill_spool_numbers(self):
        """Assign spool numbers to any entries that don't have one yet."""
        needs_number = [e for e in self._entries if not e.get("spool_number")]
        if not needs_number:
            return
        next_num = self._next_spool_number()  # starts after current max
        # Assign in order of scanned_at so older entries get lower numbers
        needs_number.sort(key=lambda e: e.get("scanned_at", ""))
        for e in needs_number:
            e["spool_number"] = next_num
            next_num += 1
        self.save()

    def save(self):
        """Write all entries to disk."""
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._entries, f, indent=2, default=str)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, tag_dict: dict) -> dict:
        """
        Add a new filament entry from a parsed tag dict (Tag.to_dict()).
        Generates a UUID, timestamps the scan, and initialises inventory fields.
        Auto-populates color_name from existing entries with the same color.

        If this is an RFID scan (has a UID) and there is an existing entry
        without a UID that matches on product identifiers, the RFID data is
        merged into the existing entry instead of creating a duplicate.

        Returns the complete stored entry.
        """
        entry = dict(tag_dict)

        # Ensure filament_color always has # prefix
        fc = entry.get("filament_color", "")
        if fc and not fc.startswith("#"):
            entry["filament_color"] = "#" + fc

        # If this scan has a UID, look for an existing UID-less entry to merge into
        # (e.g. a spool added via barcode scan that is now being RFID-scanned)
        merged = self._try_merge_rfid(entry)
        if merged:
            return merged

        entry["id"] = str(uuid.uuid4())
        entry["scanned_at"] = datetime.now().isoformat()
        if not entry.get("spool_number"):
            entry["spool_number"] = self._next_spool_number()

        # Auto-populate fields from existing entries with the same product
        self._learn_from_existing(entry)

        entry["physically_present"] = True

        # Initialise inventory fields with sensible defaults
        entry.setdefault("__inventory__", {})
        inv = entry["__inventory__"]
        inv.setdefault("remaining_weight_g", tag_dict.get("spool_weight"))
        inv.setdefault("remaining_length_m", tag_dict.get("filament_length"))
        inv.setdefault("location", "")
        inv.setdefault("notes", "")

        self._entries.append(entry)
        self.save()
        return entry

    def _try_merge_rfid(self, entry: dict) -> dict | None:
        """If entry has a UID and there is an existing active entry without a UID
        that matches on variant_id, material_id, or barcode, merge the RFID data
        into it and return the updated entry. Returns None if no merge candidate."""
        uid = entry.get("uid", "")
        if not uid:
            return None

        # Don't merge if this UID already exists in the database
        if self.get_by_uid(uid):
            return None

        variant_id = entry.get("variant_id", "")
        material_id = entry.get("material_id", "")
        barcode = entry.get("barcode", "")

        candidate = None
        for e in self._entries:
            if e.get("uid") or e.get("deleted"):
                continue  # skip entries that already have a UID or are deleted
            vid_match = variant_id and (e.get("variant_id") or "").upper() == variant_id.upper()
            mid_match = material_id and (e.get("material_id") or "").upper() == material_id.upper()
            bc_match = barcode and (e.get("barcode") or "") == barcode
            if vid_match or mid_match or bc_match:
                candidate = e
                break

        if not candidate:
            return None

        # Merge: RFID data fills in missing fields on the existing entry
        for key, value in entry.items():
            if key in ("id", "scanned_at", "__inventory__"):
                continue
            if value and not candidate.get(key):
                candidate[key] = value

        candidate["physically_present"] = True
        # Always set the UID and production date from the RFID scan
        candidate["uid"] = uid
        if entry.get("production_date"):
            candidate["production_date"] = entry["production_date"]

        # Update remaining weight/length if inventory was at defaults
        inv = candidate.get("__inventory__", {})
        spool_weight = entry.get("spool_weight")
        if spool_weight and not inv.get("remaining_weight_g"):
            inv.setdefault("remaining_weight_g", spool_weight)
        filament_length = entry.get("filament_length")
        if filament_length and not inv.get("remaining_length_m"):
            inv.setdefault("remaining_length_m", filament_length)

        # Ensure the entry has a spool number
        if not candidate.get("spool_number"):
            candidate["spool_number"] = self._next_spool_number()

        # Back-fill product code from the candidate to other matching entries
        self._learn_from_existing(candidate)

        self.save()
        return candidate

    def _next_spool_number(self) -> int:
        """Return the next spool number. Increments from the current max, wrapping
        at 9999. Auto-compacts the database at the limit to free up numbers."""
        used = {e.get("spool_number", 0) or 0 for e in self._entries}
        max_num = max(used) if used else 0
        # Try the next sequential number
        candidate = max_num + 1
        if candidate <= 9999:
            return candidate
        # Hit the limit — compact to free numbers from permanently deleted entries
        self.compress()
        used = {e.get("spool_number", 0) or 0 for e in self._entries}
        # Find the lowest unused number
        for n in range(1, 10000):
            if n not in used:
                return n
        # All 9999 genuinely in use — shouldn't happen in practice
        return 10000

    def get_by_spool_number(self, num: int) -> dict | None:
        """Find an active entry by its spool number."""
        for e in self._entries:
            if not e.get("deleted") and e.get("spool_number") == num:
                return e
        return None

    def get_all(self) -> list[dict]:
        """Return all active (non-deleted) entries."""
        return [e for e in self._entries if not e.get("deleted")]

    def get_all_including_deleted(self) -> list[dict]:
        """Return every entry, including soft-deleted ones."""
        return list(self._entries)

    def get_by_id(self, entry_id: str) -> dict | None:
        """Return a single entry by its UUID, or None."""
        for e in self._entries:
            if e.get("id") == entry_id:
                return e
        return None

    def get_by_uid(self, uid: str) -> dict | None:
        """Return a single entry by its tag UID (primary or secondary), or None.
        Each spool has two RFID tags with different chip UIDs; uid2 stores the
        alternate tag's UID once discovered.
        Searches all entries including deleted ones so re-scans can restore them."""
        uid_upper = uid.upper()
        for e in self._entries:
            if (e.get("uid") or "").upper() == uid_upper:
                return e
            if (e.get("uid2") or "").upper() == uid_upper:
                return e
        return None

    def get_by_tray_uid(self, tray_uid: str) -> dict | None:
        """Return a single entry by its tray UID (physical spool ID), or None.
        Each spool has two RFID tags with different chip UIDs but the same tray_uid."""
        tray_upper = tray_uid.upper()
        for e in self._entries:
            if (e.get("tray_uid") or "").upper() == tray_upper:
                return e
        return None

    def update(self, entry_id: str, fields: dict) -> dict | None:
        """
        Merge `fields` into the entry with the given UUID.
        Nested dicts (e.g. 'temperatures', '__inventory__') are merged shallowly.
        Returns the updated entry, or None if not found.
        """
        entry = self.get_by_id(entry_id)
        if entry is None:
            return None
        for key, value in fields.items():
            if isinstance(value, dict) and isinstance(entry.get(key), dict):
                entry[key].update(value)
            else:
                entry[key] = value
        self.save()
        return entry

    def delete(self, entry_id: str) -> bool:
        """Soft-delete an entry by UUID. Marks it as deleted but keeps it in
        the database so its properties (color names, barcodes, etc.) can still
        be referenced when new spools of the same type are scanned.
        Returns True if found and marked deleted."""
        entry = self.get_by_id(entry_id)
        if entry is None:
            return False
        entry["deleted"] = True
        entry["deleted_at"] = datetime.now().isoformat()
        self.save()
        return True

    def undelete(self, entry_id: str) -> bool:
        """Restore a soft-deleted entry. Returns True if found."""
        for e in self._entries:
            if e.get("id") == entry_id and e.get("deleted"):
                e.pop("deleted", None)
                e.pop("deleted_at", None)
                self.save()
                return True
        return False

    # ------------------------------------------------------------------
    # Summary helpers
    # ------------------------------------------------------------------

    def get_by_barcode(self, barcode: str) -> dict | None:
        """Return the best entry matching a barcode (EAN-13 / GTIN).
        Prefers non-deleted entries with the most data."""
        bc = barcode.strip()
        best = None
        best_score = -1
        for e in self._entries:
            if (e.get("barcode") or "") == bc:
                # Score: prefer non-deleted, then most populated fields
                score = sum(1 for v in e.values() if v) + (100 if not e.get("deleted") else 0)
                if score > best_score:
                    best = e
                    best_score = score
        return best

    def get_by_material_id(self, material_id: str) -> dict | None:
        """Return the best entry matching a material_id (e.g. 'GFB50').
        Prefers non-deleted entries with the most data."""
        mid = material_id.upper()
        best = None
        best_score = -1
        for e in self._entries:
            if (e.get("material_id") or "").upper() == mid:
                score = sum(1 for v in e.values() if v) + (100 if not e.get("deleted") else 0)
                if score > best_score:
                    best = e
                    best_score = score
        return best

    def summary_by_type(self) -> dict[str, int]:
        """Return count of active spools per detailed filament type."""
        counts: dict[str, int] = {}
        for e in self.get_all():
            t = e.get("detailed_filament_type") or e.get("filament_type") or "Unknown"
            counts[t] = counts.get(t, 0) + 1
        return counts

    def total_remaining_weight(self) -> float:
        """Sum of remaining_weight_g across all active entries (ignores None)."""
        return sum(
            e.get("__inventory__", {}).get("remaining_weight_g") or 0
            for e in self.get_all()
        )

    def find_sku(self, variant_id: str) -> str:
        """Find a SKU from any entry (including deleted) with the same variant_id."""
        if not variant_id:
            return ""
        vid = variant_id.upper()
        for e in self._entries:
            if (e.get("variant_id") or "").upper() == vid and e.get("sku"):
                return e["sku"]
        return ""

    def generate_sku(self, tag_dict: dict) -> str:
        """Generate a SKU from tag data: {variant_id}-{diameter}-{weight}-SPL.
        First checks if an existing entry with the same variant_id already has a SKU."""
        variant_id = tag_dict.get("variant_id", "")
        if not variant_id:
            return ""

        # Check existing entries first
        existing_sku = self.find_sku(variant_id)
        if existing_sku:
            return existing_sku

        # Generate from tag data
        diameter = tag_dict.get("filament_diameter") or 1.75
        weight = tag_dict.get("spool_weight") or 1000
        # Format diameter without trailing zeros
        diam_str = f"{diameter:g}"
        return f"{variant_id}-{diam_str}-{int(weight)}-SPL"

    # ------------------------------------------------------------------
    # Physical inventory
    # ------------------------------------------------------------------

    def clear_all_present_flags(self):
        """Set physically_present to False on all active entries."""
        for e in self._entries:
            if not e.get("deleted"):
                e["physically_present"] = False
        self.save()

    def mark_present(self, entry_id: str) -> bool:
        """Mark an entry as physically present. Returns True if found."""
        entry = self.get_by_id(entry_id)
        if entry is None:
            return False
        entry["physically_present"] = True
        self.save()
        return True

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    # Fields that define the filament *product* — if two entries match on all
    # of these, one deleted copy is redundant and can be pruned.
    _PRODUCT_KEYS = (
        "filament_type", "detailed_filament_type", "filament_color",
        "filament_color2", "filament_color_count", "spool_weight",
        "filament_length", "filament_diameter", "spool_width",
        "material_id", "variant_id", "nozzle_diameter", "temperatures",
        "x_cam_info", "color_name", "sku", "barcode",
    )

    def _product_key(self, entry: dict) -> tuple:
        """Return a hashable key representing the filament product."""
        vals = []
        for k in self._PRODUCT_KEYS:
            v = entry.get(k)
            if isinstance(v, dict):
                v = tuple(sorted(v.items()))
            vals.append(v)
        return tuple(vals)

    def compress(self) -> int:
        """Remove deleted entries that are duplicates of another entry (deleted
        or active) with the same product settings. Returns the number of
        entries permanently removed."""
        # Build a set of product keys seen across all entries
        seen: set[tuple] = set()
        to_remove: list[dict] = []

        # Process non-deleted entries first so their keys are in `seen`
        non_deleted = [e for e in self._entries if not e.get("deleted")]
        deleted = [e for e in self._entries if e.get("deleted")]

        for e in non_deleted:
            seen.add(self._product_key(e))

        for e in deleted:
            key = self._product_key(e)
            if key in seen:
                to_remove.append(e)
            else:
                # Keep this deleted entry (it's the only record of this product)
                seen.add(key)

        if to_remove:
            for e in to_remove:
                self._entries.remove(e)
            self.save()

        return len(to_remove)

    # Fields that are numeric (int or float) in the JSON database.
    _INT_FIELDS = {
        "filament_color_count", "spool_weight", "filament_length",
        "nozzle_diameter", "tare_weight",
        "min_hotend", "max_hotend", "bed_temp", "bed_temp_type",
        "drying_time", "drying_temp",
        "remaining_weight_g", "remaining_length_m",
    }
    _FLOAT_FIELDS = {"filament_diameter", "spool_width"}

    def export_db(self, path: str | Path):
        """Export the full database (including deleted entries) to a JSON file."""
        import copy
        with open(path, "w", encoding="utf-8") as f:
            json.dump(copy.deepcopy(self._entries), f, indent=2, default=str)

    def import_db(self, path: str | Path) -> tuple[int, int]:
        """Import entries from a JSON database export.
        Matches by id; updates if found, adds if new.
        Returns (added, updated) counts."""
        with open(path, "r", encoding="utf-8") as f:
            incoming = json.load(f)
        if not isinstance(incoming, list):
            raise ValueError("Expected a JSON array of entries")

        added = updated = 0
        existing_ids = {e["id"]: e for e in self._entries if "id" in e}

        for entry in incoming:
            eid = entry.get("id")
            if eid and eid in existing_ids:
                # Merge into existing entry
                target = existing_ids[eid]
                for k, v in entry.items():
                    if k == "__inventory__":
                        target.setdefault("__inventory__", {}).update(v)
                    elif k == "temperatures":
                        target.setdefault("temperatures", {}).update(v)
                    else:
                        target[k] = v
                updated += 1
            else:
                if not eid:
                    entry["id"] = str(uuid.uuid4())
                entry.setdefault("__inventory__", {})
                self._entries.append(entry)
                added += 1

        self._backfill_spool_numbers()
        self.save()
        return added, updated

    def import_csv(self, path: str | Path) -> tuple[int, int]:
        """Import entries from a CSV file exported by Export CSV.
        Matches rows to existing entries by id; updates if found, adds if new.
        Returns (added, updated) counts."""
        import csv
        added = 0
        updated = 0

        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Strip whitespace/tabs from all values (export adds tab prefix for Excel)
                row = {k: (v.strip() if v else "") for k, v in row.items()}
                entry = self._unflatten_row(row)
                entry_id = entry.get("id", "")
                existing = self.get_by_id(entry_id) if entry_id else None
                if existing:
                    # Update existing entry with CSV values
                    for key, value in entry.items():
                        if key == "id":
                            continue
                        if isinstance(value, dict) and isinstance(existing.get(key), dict):
                            existing[key].update(value)
                        else:
                            existing[key] = value
                    updated += 1
                else:
                    # New entry — assign an id if missing
                    if not entry.get("id"):
                        entry["id"] = str(uuid.uuid4())
                    if not entry.get("scanned_at"):
                        entry["scanned_at"] = datetime.now().isoformat()
                    entry.setdefault("__inventory__", {})
                    inv = entry["__inventory__"]
                    inv.setdefault("remaining_weight_g", entry.get("spool_weight"))
                    inv.setdefault("remaining_length_m", entry.get("filament_length"))
                    inv.setdefault("location", "")
                    inv.setdefault("notes", "")
                    self._entries.append(entry)
                    added += 1

        if added or updated:
            self.save()
        return added, updated

    def _unflatten_row(self, row: dict) -> dict:
        """Convert a flat CSV row back into a nested entry dict."""
        entry = {}
        temps = {}
        inv = {}
        for col, val in row.items():
            if not val and val != 0:
                continue
            if col.startswith("temperatures."):
                key = col.split(".", 1)[1]
                temps[key] = self._parse_numeric(key, val)
            elif col in ("remaining_weight_g", "remaining_length_m", "location", "notes"):
                inv[col] = self._parse_numeric(col, val) if col != "location" and col != "notes" else val
            else:
                entry[col] = self._parse_numeric(col, val)
        if temps:
            entry["temperatures"] = temps
        if inv:
            entry["__inventory__"] = inv
        return entry

    def _parse_numeric(self, field: str, val: str):
        """Convert string value to int/float if the field is numeric."""
        if field in self._FLOAT_FIELDS:
            try:
                return float(val)
            except (ValueError, TypeError):
                return val
        if field in self._INT_FIELDS:
            try:
                f = float(val)
                return int(f) if f == int(f) else f
            except (ValueError, TypeError):
                return val
        return val

    # Fields that can be learned from one entry to another
    _LEARNABLE_KEYS = (
        "barcode", "sku", "color_name", "tare_weight",
        "variant_id", "material_id", "filament_type",
        "detailed_filament_type", "filament_color",
        "spool_weight", "filament_length", "filament_diameter",
        "nozzle_diameter", "spool_width", "temperatures",
    )

    def _learn_from_existing(self, entry: dict):
        """Two-way learning: populate the new entry from existing matches,
        and back-fill existing entries with any new data from this entry.
        Matches by variant_id, material_id, or barcode."""
        # Find a matching product entry
        match = None
        variant_id = entry.get("variant_id", "")
        material_id = entry.get("material_id", "")
        barcode = entry.get("barcode", "")

        if variant_id:
            vid = variant_id.upper()
            for e in self._entries:
                if (e.get("variant_id") or "").upper() == vid:
                    match = e
                    break
        if not match and material_id:
            match = self.get_by_material_id(material_id)
        if not match and barcode:
            match = self.get_by_barcode(barcode)

        if match:
            # Copy missing fields FROM existing match TO new entry
            for key in self._LEARNABLE_KEYS:
                if not entry.get(key) and match.get(key):
                    entry[key] = match[key]

            # Back-fill: copy missing fields FROM new entry TO existing match
            updated = False
            for key in self._LEARNABLE_KEYS:
                if entry.get(key) and not match.get(key):
                    match[key] = entry[key]
                    updated = True
            if updated:
                self.save()

        # Back-fill ALL matching entries (not just the first match)
        # Re-read variant_id/material_id since they may have been learned above
        variant_id = entry.get("variant_id", "")
        material_id = entry.get("material_id", "")
        barcode = entry.get("barcode", "")
        if variant_id or material_id or barcode:
            any_updated = False
            for e in self._entries:
                if e is match:
                    continue
                vid_match = variant_id and (e.get("variant_id") or "").upper() == variant_id.upper()
                mid_match = material_id and (e.get("material_id") or "").upper() == material_id.upper()
                bc_match = barcode and (e.get("barcode") or "") == barcode
                if vid_match or mid_match or bc_match:
                    for key in self._LEARNABLE_KEYS:
                        if entry.get(key) and not e.get(key):
                            e[key] = entry[key]
                            any_updated = True
            if any_updated:
                self.save()

        # Fall back to color hex matching for color_name
        if not entry.get("color_name"):
            learned_name = self._find_color_name(
                entry.get("filament_color", ""),
                entry.get("detailed_filament_type") or entry.get("filament_type", ""),
            )
            if learned_name:
                entry["color_name"] = learned_name

    @staticmethod
    def _normalize_color(hex_color: str) -> str:
        """Normalize a color string to uppercase #RRGGBB for comparison."""
        c = hex_color.strip().upper()
        if not c:
            return ""
        if not c.startswith("#"):
            c = "#" + c
        return c[:7]  # strip alpha channel

    def _find_color_name(self, hex_color: str, detailed_type: str = "") -> str:
        """Find a color_name from any entry with the same color hex and filament type.

        Special case: Bambu #000000 is "Charcoal" for PLA Matte, "Black" for everything else.
        """
        if not hex_color:
            return ""
        target = self._normalize_color(hex_color)
        if not target:
            return ""
        # Bambu naming quirk: matte black (#000000) is "Charcoal", other black is "Black"
        if target == "#000000":
            is_matte = (detailed_type or "").strip().lower() == "pla matte"
            return "Charcoal" if is_matte else "Black"
        # First pass: match color AND detailed filament type
        if detailed_type:
            for e in self._entries:
                c = self._normalize_color(e.get("filament_color") or "")
                etype = e.get("detailed_filament_type") or e.get("filament_type") or ""
                name = e.get("color_name", "")
                if c == target and etype == detailed_type and name:
                    return name
        # Second pass: match color only (fallback)
        for e in self._entries:
            c = self._normalize_color(e.get("filament_color") or "")
            name = e.get("color_name", "")
            if c == target and name:
                return name
        return ""

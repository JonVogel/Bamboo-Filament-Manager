# -*- coding: utf-8 -*-

# Proxmark3 scanner thread for reading filament spool RFID tags.
# Uses the proxmark3 client (proxmark3.exe) to read tags via subprocess.

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, QSettings

from rfid_parser import Tag


# ---------------------------------------------------------------------------
# Proxmark3 client discovery
# ---------------------------------------------------------------------------

def find_pm3(saved_path: str = "") -> Path | None:
    """Return the path to the proxmark3 executable, or None if not found."""

    # 1. Explicitly saved path (from app settings)
    if saved_path:
        p = Path(saved_path)
        if p.is_file():
            return p

    # 2. Bundled pm3 in app directory
    bundled = Path(__file__).parent / "pm3" / "proxmark3.exe"
    if bundled.is_file():
        return bundled

    # 3. PROXMARK3_DIR environment variable
    env_dir = os.environ.get("PROXMARK3_DIR")
    if env_dir:
        for name in ("proxmark3.exe", "proxmark3", "pm3.exe", "pm3"):
            candidate = Path(env_dir) / name
            if candidate.is_file():
                return candidate
        for name in ("proxmark3.exe", "proxmark3"):
            candidate = Path(env_dir) / "client" / name
            if candidate.is_file():
                return candidate

    # 4. proxmark3 on system PATH
    which_cmd = ["where", "proxmark3"] if os.name == "nt" else ["which", "proxmark3"]
    result = _run_quietly(which_cmd)
    if result:
        return Path(result.strip().splitlines()[0])

    return None


def get_saved_pm3_path() -> str:
    """Read the saved proxmark3 path from QSettings."""
    return QSettings().value("proxmark3/path", "")


def save_pm3_path(path: str):
    """Save the proxmark3 path to QSettings."""
    QSettings().setValue("proxmark3/path", path)


def _run_quietly(cmd: list) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Scanner thread
# ---------------------------------------------------------------------------

class ScannerThread(QThread):
    """
    Background thread that uses the Proxmark3 client to:
      1. Detect a filament spool RFID tag and read its UID
      2. Generate keys using hf mf keygen (KDF 4 = Bambu key derivation)
      3. Dump all tag blocks using the generated key file
      4. Parse the dump and emit the result

    Signals:
        status_update(str)  — progress messages for the UI
        scan_complete(dict) — Tag.to_dict() on success
        scan_error(str)     — human-readable error on failure
    """

    status_update = pyqtSignal(str)
    scan_complete = pyqtSignal(dict)
    uid_found = pyqtSignal(str)
    scan_error = pyqtSignal(str)

    def __init__(self, port: str = "", pm3_path: str = "", db=None, parent=None):
        super().__init__(parent)
        self.port = port
        self.pm3_path = pm3_path
        self._db = db
        self._stop = False

    def stop(self):
        self._stop = True

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self):
        pm3 = find_pm3(self.pm3_path)
        if pm3 is None:
            self.scan_error.emit(
                "Proxmark3 client not found.\n\n"
                "Use the 'Browse' button to locate proxmark3.exe,\n"
                "or set the PROXMARK3_DIR environment variable."
            )
            return

        try:
            self._scan(pm3)
        except Exception as exc:
            self.scan_error.emit(f"Unexpected error: {exc}")

    # ------------------------------------------------------------------
    # Scan sequence
    # ------------------------------------------------------------------

    def _pm3_cmd(self, pm3: Path, command: str, timeout: int = 30) -> tuple[bool, str]:
        """Run a pm3 command and return (success, combined_output)."""
        cmd = [str(pm3)]
        if self.port:
            cmd += ["-p", self.port]
        cmd += ["-c", command]

        print(f"[debug] Running: {' '.join(cmd)}")

        # Run from the directory containing proxmark3.exe so it finds its DLLs.
        # Also add ProxSpace MinGW paths to PATH if they exist.
        cwd = str(Path(pm3).parent)
        env = os.environ.copy()
        proxspace_bin = self._find_proxspace_bin(pm3)
        if proxspace_bin:
            env["PATH"] = proxspace_bin + os.pathsep + env.get("PATH", "")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=env,
            )
            output = result.stdout + result.stderr
            print(f"[debug] returncode={result.returncode}")
            print(f"[debug] output:\n{output}")
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "Command timed out."
        except Exception as exc:
            return False, str(exc)

    def _scan(self, pm3: Path):
        if self._stop:
            return

        # Ensure spooldata directory exists for storing dump files
        spooldata_dir = Path(__file__).parent / "spooldata"
        spooldata_dir.mkdir(exist_ok=True)

        # ----------------------------------------------------------------
        # Step 1 — Detect tag and read UID (retry until found or stopped)
        # ----------------------------------------------------------------
        self.status_update.emit("Waiting for tag...")

        uid = None
        while not self._stop:
            ok, output = self._pm3_cmd(pm3, "hf 14a reader")

            if self._stop:
                return

            if ok:
                uid = self._extract_uid(output)
                if uid:
                    break

            time.sleep(1)

        if not uid:
            return

        self.status_update.emit(f"Tag found: {uid.upper()}")
        self._beep(880, 150)

        if self._stop:
            return

        # Early exit if UID already in database — skip the slow dump
        if self._db:
            existing = self._db.get_by_uid(uid.upper())
            if existing:
                if existing.get("deleted", False):
                    self._db.undelete(existing["id"])
                self.scan_complete.emit({"uid": uid.upper()})
                return

        # ----------------------------------------------------------------
        # Step 2 — Clean up old key/dump files for this UID
        # ----------------------------------------------------------------
        pm3_dir = Path(pm3).parent
        uid_upper = uid.upper()
        for old_file in pm3_dir.glob(f"hf-mf-{uid_upper}-*"):
            try:
                old_file.unlink()
                print(f"[debug] Removed old file: {old_file}")
            except Exception:
                pass

        # ----------------------------------------------------------------
        # Step 3 — Derive keys and dump in one call
        # ----------------------------------------------------------------
        self.status_update.emit("Reading tag data...")

        # Chain keygen + dump in a single pm3 session to avoid reconnecting
        combined_cmd = (
            f"hf mf keygen -u {uid_upper} -d -k 4; "
            f"hf mf dump --keys hf-mf-{uid_upper}-key.bin"
        )
        ok, output = self._pm3_cmd(pm3, combined_cmd, timeout=60)
        if self._stop:
            return
        if not ok:
            self.scan_error.emit(f"Key generation / dump failed:\n{output}")
            return

        # Find the JSON dump file from the pm3 output
        json_path = self._extract_json_dump_path(output)
        if not json_path:
            # Fallback: search the pm3 working directory
            json_path_obj = self._find_dump_json(str(pm3_dir), uid)
            if json_path_obj:
                json_path = str(json_path_obj)

        if not json_path:
            self.scan_error.emit(
                "Dump succeeded but could not find JSON output file.\n"
                f"Output:\n{output}"
            )
            return

        # Copy dump file to spooldata directory
        src = Path(json_path)
        dest = spooldata_dir / src.name
        try:
            shutil.copy2(str(src), str(dest))
            json_path = str(dest)
            print(f"[debug] Dump file copied to: {dest}")
        except Exception as exc:
            print(f"[debug] Warning: could not copy dump to spooldata: {exc}")

        # ----------------------------------------------------------------
        # Step 3 — Parse and emit
        # ----------------------------------------------------------------
        try:
            with open(json_path, "r") as f:
                raw = json.load(f)
            tag = Tag.from_json_dump(raw)
            tag_dict = tag.to_dict()

            # Print spool data to command line
            print("\n" + "=" * 60)
            print("  SPOOL DATA")
            print("=" * 60)
            for key, value in tag_dict.items():
                if isinstance(value, dict):
                    print(f"  {key}:")
                    for k2, v2 in value.items():
                        print(f"    {k2}: {v2}")
                else:
                    print(f"  {key}: {value}")
            print("=" * 60 + "\n")

            self._beep(1175, 150)  # Scan complete
            self.status_update.emit("Done!")
            self.scan_complete.emit(tag_dict)
        except Exception as exc:
            self.scan_error.emit(f"Failed to parse dump: {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _beep(freq: int = 880, duration: int = 150):
        """Play a single tone. Higher pitch = done, lower = started."""
        try:
            import winsound
            winsound.Beep(freq, duration)
        except Exception:
            print("\a", end="", flush=True)

    @staticmethod
    def _find_proxspace_bin(pm3: Path) -> str | None:
        """Find additional DLL directories if needed."""
        # If using bundled pm3, DLLs are in the same directory — no extra path needed.
        # For external installs, check for ProxSpace.
        for parent in pm3.parents:
            candidate = parent / "msys2" / "mingw64" / "bin"
            if candidate.is_dir():
                return str(candidate)
            for sibling in parent.iterdir():
                if sibling.is_dir() and "proxspace" in sibling.name.lower():
                    candidate = sibling / "msys2" / "mingw64" / "bin"
                    if candidate.is_dir():
                        return str(candidate)
            break
        return None

    def _extract_uid(self, output: str) -> str | None:
        """Parse the UID from 'hf search' or 'hf 14a reader' output."""
        match = re.search(
            r"UID\s*:?\s*([0-9A-Fa-f]{2}(?:\s+[0-9A-Fa-f]{2}){3}|[0-9A-Fa-f]{8})",
            output,
        )
        if match:
            return match.group(1).replace(" ", "")
        return None

    def _extract_json_dump_path(self, output: str) -> str | None:
        """Extract the JSON dump file path from pm3 output."""
        for line in output.splitlines():
            if "saved" not in line.lower():
                continue
            # Match lines like: Saved to json file C:/.../hf-mf-UID-dump.json
            # or: Saved to json file `C:/.../hf-mf-UID-dump.json`
            m = re.search(r'json file\s+`?([^`\s]+\.json)`?', line, re.IGNORECASE)
            if m:
                return m.group(1)
        return None

    def _find_dump_json(self, directory: str, uid: str) -> Path | None:
        """Find the JSON dump file pm3 created (filename includes UID).
        Returns the most recently modified match."""
        base = Path(directory)
        # Look for any dump file matching this UID (handles -001, -002 suffixes)
        matches = sorted(
            base.glob(f"hf-mf-{uid.upper()}-dump*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if matches:
            return matches[0]
        return None

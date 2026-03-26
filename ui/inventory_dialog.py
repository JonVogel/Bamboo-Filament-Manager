# -*- coding: utf-8 -*-

# Dialog for performing a physical inventory by scanning spool labels.

import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QPushButton, QMessageBox,
)


class InventoryDialog(QDialog):
    """Scan spool labels to reconcile physical stock with the database."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._scanned_ids: set[str] = set()
        self.setWindowTitle("Physical Inventory")
        self.setMinimumSize(500, 400)
        self._build_ui()
        self._start_inventory()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "Scan spool labels to verify physical stock.\n"
            "When finished, click Finished to see missing spools."
        ))

        # Scan input
        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("Scan:"))
        self._input = QLineEdit()
        self._input.setPlaceholderText("Scan a spool label barcode...")
        self._input.returnPressed.connect(self._on_scan)
        input_row.addWidget(self._input)
        layout.addLayout(input_row)

        # Counter
        self._lbl_count = QLabel("Scanned: 0")
        layout.addWidget(self._lbl_count)

        # Log area
        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        layout.addWidget(self._log_area)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_finish = QPushButton("Finished")
        self._btn_finish.clicked.connect(self._on_finish)
        btn_row.addWidget(self._btn_finish)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_cancel)
        layout.addLayout(btn_row)

    def _start_inventory(self):
        """Snapshot current flags, then clear all to begin inventory."""
        self._prior_flags = {
            e["id"]: e.get("physically_present", False)
            for e in self.db.get_all()
        }
        self.db.clear_all_present_flags()
        self._log("Inventory started. All spools marked as not present.")
        self._log("Please start scanning spool labels.\n")
        self._input.setFocus()

    def _on_scan(self):
        """Handle a scanned barcode label."""
        text = self._input.text().strip()
        self._input.clear()
        if not text:
            return

        # Parse SPL-NNNN format
        m = re.match(r"SPL-(\d+)", text, re.IGNORECASE)
        if not m:
            self._log(f"  [?] Unrecognized format: {text}")
            return

        spool_num = int(m.group(1))
        entry = self.db.get_by_spool_number(spool_num)

        if entry is None:
            QMessageBox.warning(
                self, "Spool Not Found",
                f"SPL-{spool_num:04d} was not found in the database.\n\n"
                "Set this spool aside. You can re-enter it after "
                "the inventory is complete."
            )
            self._log(f"  [!] SPL-{spool_num:04d} — NOT FOUND")
            return

        # Mark as present (in-memory only — saved on finish/cancel)
        entry["physically_present"] = True
        self._scanned_ids.add(entry["id"])

        color = entry.get("color_name", "")
        dtype = (entry.get("detailed_filament_type")
                 or entry.get("filament_type") or "")
        self._log(f"  SPL-{spool_num:04d}  {dtype}  {color}")
        self._lbl_count.setText(f"Scanned: {len(self._scanned_ids)}")

    def _on_finish(self):
        """End inventory and report missing spools."""
        self.db.save()
        missing = [e for e in self.db.get_all()
                   if not e.get("physically_present")]

        if not missing:
            QMessageBox.information(
                self, "Inventory Complete",
                f"All {len(self._scanned_ids)} spools accounted for!"
            )
            self.accept()
            return

        # Build summary of missing spools
        lines = []
        for e in missing:
            num = e.get("spool_number", 0)
            color = e.get("color_name", "")
            dtype = (e.get("detailed_filament_type")
                     or e.get("filament_type") or "")
            lines.append(f"SPL-{num:04d}  {dtype}  {color}")

        msg = (
            f"Scanned {len(self._scanned_ids)} spools. "
            f"{len(missing)} not found:\n\n" + "\n".join(lines) +
            "\n\nYou can filter the table by the Present column "
            "to review missing spools."
        )
        QMessageBox.warning(self, "Inventory Complete — Missing Spools", msg)
        self.accept()

    def _log(self, message: str):
        self._log_area.append(message)

    def reject(self):
        """Confirm before cancelling — restore prior flags on cancel."""
        reply = QMessageBox.question(
            self, "Cancel Inventory?",
            "Cancel the inventory and restore previous state?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Restore the snapshot
        for entry in self.db.get_all():
            eid = entry["id"]
            if eid in self._prior_flags:
                entry["physically_present"] = self._prior_flags[eid]
        self.db.save()
        super().reject()

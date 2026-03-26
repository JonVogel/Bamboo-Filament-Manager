# -*- coding: utf-8 -*-

# Dialog for scanning multiple filament spool RFID tags in sequence.

from PyQt6.QtCore import Qt, QSettings, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QGroupBox, QSizePolicy,
    QLineEdit, QFormLayout,
)

from scanner import ScannerThread, get_saved_pm3_path


class BulkScanDialog(QDialog):
    """
    Bulk scanning dialog — scans one tag at a time, shows results,
    lets the user save or skip, then immediately gets ready for the next.

    After closing, self.added_count holds the number of spools saved.

    Signals:
        spool_saved — emitted each time a spool is saved/updated.
    """

    spool_saved = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bulk Scan Filament Tags")
        self.setMinimumWidth(550)
        self.setMinimumHeight(650)
        self.db = db
        self.added_count = 0
        self._updated_count = 0
        self._skipped_count = 0
        self._thread: ScannerThread | None = None
        self._current_tag: dict | None = None
        self._scanning = False
        self._closing = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Log area
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(180)
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.log)

        # Tag result panel
        self.result_group = QGroupBox("Scanned Tag")
        result_layout = QVBoxLayout(self.result_group)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        result_layout.addWidget(self.summary_label)

        # Barcode and SKU entry fields
        extras_form = QFormLayout()
        self.barcode_edit = QLineEdit()
        self.barcode_edit.setPlaceholderText("Scan or type product code")
        self.barcode_edit.returnPressed.connect(lambda: self.sku_edit.setFocus())
        extras_form.addRow("Product Code:", self.barcode_edit)
        self.sku_edit = QLineEdit()
        self.sku_edit.setPlaceholderText("e.g. PA1-002-US2")
        self.sku_edit.returnPressed.connect(lambda: self.color_name_edit.setFocus())
        extras_form.addRow("SKU:", self.sku_edit)
        self.color_name_edit = QLineEdit()
        self.color_name_edit.setPlaceholderText("e.g. Charcoal, Yellow, White")
        self.color_name_edit.returnPressed.connect(lambda: self.save_btn.setFocus())
        extras_form.addRow("Color Name:", self.color_name_edit)
        result_layout.addLayout(extras_form)

        # Save / Skip buttons for current tag
        tag_btn_row = QHBoxLayout()
        self.save_btn = QPushButton("Save to Inventory")
        self.save_btn.setAutoDefault(False)
        self.save_btn.clicked.connect(self._save_current)
        self.save_btn.setEnabled(False)
        tag_btn_row.addWidget(self.save_btn)

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setAutoDefault(False)
        self.skip_btn.clicked.connect(self._skip_current)
        self.skip_btn.setEnabled(False)
        tag_btn_row.addWidget(self.skip_btn)
        result_layout.addLayout(tag_btn_row)

        self.result_group.hide()
        layout.addWidget(self.result_group)

        # Counter
        self.counter_label = QLabel("")
        self.counter_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.counter_label)

        layout.addStretch()

        # Bottom buttons
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start Scanning")
        self.start_btn.setAutoDefault(False)
        self.start_btn.clicked.connect(self._start_next_scan)
        btn_row.addWidget(self.start_btn)

        self.finished_btn = QPushButton("Finished")
        self.finished_btn.setAutoDefault(False)
        self.finished_btn.clicked.connect(self._on_finished)
        btn_row.addWidget(self.finished_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, message: str):
        self.log.append(message)

    def _update_counter(self):
        parts = [f"Added: {self.added_count}"]
        if self._updated_count:
            parts.append(f"Updated: {self._updated_count}")
        if self._skipped_count:
            parts.append(f"Skipped: {self._skipped_count}")
        self.counter_label.setText("  |  ".join(parts))

    def _set_config_enabled(self, enabled: bool):
        pass  # PM3 path and COM port are now in Settings

    # ------------------------------------------------------------------
    # Scan loop
    # ------------------------------------------------------------------

    def _start_next_scan(self):
        settings = QSettings()
        port = settings.value("proxmark3/port", "")
        if not port:
            self._log("No COM port configured. Please set one in Settings.")
            return

        pm3_text = get_saved_pm3_path() or ""

        # Reset UI for next scan
        self._current_tag = None
        self.save_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.result_group.hide()
        self.summary_label.setText("")
        self.barcode_edit.clear()
        self.sku_edit.clear()
        self.color_name_edit.clear()
        self.log.clear()
        self._set_config_enabled(False)
        self.start_btn.setEnabled(False)
        self._scanning = True

        self._log("Place the next spool tag on the Proxmark3...")

        self._thread = ScannerThread(
            port=port,
            pm3_path=pm3_text,
            db=self.db,
            parent=self,
        )
        self._thread.status_update.connect(self._log)
        self._thread.scan_complete.connect(self._on_scan_complete)
        self._thread.scan_error.connect(self._on_scan_error)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_thread_finished(self):
        self._scanning = False
        if not self._closing:
            self._set_config_enabled(True)

    def _on_scan_complete(self, tag_dict: dict):
        if self._closing:
            return
        self._current_tag = tag_dict
        self._log("Scan complete!")

        uid = tag_dict.get("uid", "")

        # Fast path: scanner already matched UID in DB (early-exit, UID-only scan)
        # Auto-acknowledge and move to the next scan immediately.
        existing = self.db.get_by_uid(uid) if uid else None
        # Also check tray_uid — each spool has two RFID tags with different
        # chip UIDs but the same tray_uid (physical spool identifier)
        if not existing:
            tray_uid = tag_dict.get("tray_uid", "")
            if tray_uid:
                existing = self.db.get_by_tray_uid(tray_uid)
                if existing and uid:
                    self.db.update(existing["id"], {"uid2": uid})
        if existing and len(tag_dict) == 1:
            existing_type = existing.get("detailed_filament_type") or existing.get("filament_type", "Unknown")
            spool_num = existing.get("spool_number", 0)
            spool_id = f"SPL-{spool_num:04d}" if spool_num else "entry"
            was_deleted = existing.get("deleted", False)
            if was_deleted:
                self.db.undelete(existing["id"])
                self._log(f"Restored {spool_id}: {existing_type}")
                self._updated_count += 1
            else:
                self._log(f"Already in inventory: {spool_id}: {existing_type}")
                self._skipped_count += 1
            self._current_tag = None
            self._update_counter()
            self.spool_saved.emit()
            # Auto-start next scan
            self._start_next_scan()
            return

        color = tag_dict.get("filament_color", "")
        dtype = tag_dict.get("detailed_filament_type", tag_dict.get("filament_type", ""))
        weight = tag_dict.get("spool_weight", "?")

        # Check for duplicate (includes soft-deleted entries)
        if existing:
            existing_type = existing.get("detailed_filament_type") or existing.get("filament_type", "Unknown")
            was_deleted = existing.get("deleted", False)
            status_msg = "Previously deleted — save will restore it." if was_deleted else "Save will update the existing entry."
            self.summary_label.setText(
                f"<b>Type:</b> {dtype}<br>"
                f"<b>Color:</b> {color}<br>"
                f"<b>Weight:</b> {weight} g<br>"
                f"<b>UID:</b> {uid}<br><br>"
                f"<span style='color: #c70;'>Already in inventory as '{existing_type}'.<br>"
                f"{status_msg}</span>"
            )
        else:
            # Check for unlinked Product Code entry
            candidate = self._find_unlinked_product_entry(tag_dict)
            if candidate:
                spool_num = candidate.get("spool_number", 0)
                spool_id = f"SPL-{spool_num:04d}" if spool_num else "entry"
                cand_type = candidate.get("detailed_filament_type") or candidate.get("filament_type", "Unknown")
                self.summary_label.setText(
                    f"<b>Type:</b> {dtype}<br>"
                    f"<b>Color:</b> {color}<br>"
                    f"<b>Weight:</b> {weight} g<br>"
                    f"<b>UID:</b> {uid}<br><br>"
                    f"<span style='color: #070;'>Matches {spool_id} ({cand_type}) — "
                    f"save will link RFID data to it.</span>"
                )
            else:
                self.summary_label.setText(
                    f"<b>Type:</b> {dtype}<br>"
                    f"<b>Color:</b> {color}<br>"
                    f"<b>Weight:</b> {weight} g<br>"
                    f"<b>UID:</b> {uid}"
                )

        # Pre-populate barcode, SKU, and color name from existing entries
        variant_id = tag_dict.get("variant_id", "")
        material_id = tag_dict.get("material_id", "")
        match = None
        if variant_id:
            vid = variant_id.upper()
            for e in self.db._entries:
                if (e.get("variant_id") or "").upper() == vid:
                    match = e
                    break
        if not match and material_id:
            match = self.db.get_by_material_id(material_id)

        if match:
            if match.get("barcode"):
                self.barcode_edit.setText(match["barcode"])
            if match.get("color_name"):
                self.color_name_edit.setText(match["color_name"])

        generated_sku = self.db.generate_sku(tag_dict)
        if generated_sku:
            self.sku_edit.setText(generated_sku)

        # Fall back to color hex matching for color name
        if not self.color_name_edit.text():
            learned = self.db._find_color_name(
                tag_dict.get("filament_color", ""),
                tag_dict.get("detailed_filament_type") or tag_dict.get("filament_type", ""),
            )
            if learned:
                self.color_name_edit.setText(learned)

        self.result_group.show()
        self.save_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
        self.barcode_edit.setFocus()

    def _on_scan_error(self, message: str):
        if self._closing:
            return
        self._log(f"ERROR: {message}")
        # Allow user to retry
        self.start_btn.setEnabled(True)

    def _save_current(self):
        if not self._current_tag:
            return

        # Merge barcode and SKU from the entry fields
        barcode = self.barcode_edit.text().strip()
        sku = self.sku_edit.text().strip()
        if barcode:
            self._current_tag["barcode"] = barcode
        if sku:
            self._current_tag["sku"] = sku
        color_name = self.color_name_edit.text().strip()
        if color_name:
            self._current_tag["color_name"] = color_name

        uid = self._current_tag.get("uid", "")
        existing = self.db.get_by_uid(uid) if uid else None

        if existing:
            was_deleted = existing.get("deleted", False)
            self.db.update(existing["id"], self._current_tag)
            if was_deleted:
                self.db.undelete(existing["id"])
                self._log("Restored previously deleted entry.")
            else:
                self._log("Updated existing entry.")
            self._updated_count += 1
        else:
            # Check for a Product Code entry (no UID) with matching material_id
            candidate = self._find_unlinked_product_entry(self._current_tag)
            if candidate:
                spool_num = candidate.get("spool_number", 0)
                spool_id = f"SPL-{spool_num:04d}" if spool_num else "entry"
                self.db.update(candidate["id"], self._current_tag)
                self._log(f"Linked RFID data to existing {spool_id}.")
                self._updated_count += 1
            else:
                self.db.add(self._current_tag)
                self.added_count += 1
                self._log("Saved to inventory.")

        self._current_tag = None
        self._update_counter()
        self.spool_saved.emit()
        self.save_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)

        # Auto-start next scan
        self._start_next_scan()

    def _find_unlinked_product_entry(self, tag_data: dict) -> dict | None:
        """Find a Product Code entry with no UID that matches the scanned tag's material."""
        material_id = tag_data.get("material_id", "")
        if not material_id:
            return None
        for entry in self.db.get_all():
            if entry.get("uid"):
                continue
            if entry.get("material_id") == material_id:
                return entry
        return None

    def _skip_current(self):
        self._current_tag = None
        self._skipped_count += 1
        self._update_counter()
        self._log("Skipped.")
        self.save_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)

        # Ready for next scan
        self.start_btn.setEnabled(True)
        self.start_btn.setFocus()

    # ------------------------------------------------------------------
    # Window close
    # ------------------------------------------------------------------

    def _on_finished(self):
        self._closing = True
        if self._thread and self._thread.isRunning():
            self._thread.stop()
            self._thread.wait(3000)
        self.accept()

    def closeEvent(self, event):
        self._closing = True
        if self._thread and self._thread.isRunning():
            self._thread.stop()
            self._thread.wait(3000)
        super().closeEvent(event)

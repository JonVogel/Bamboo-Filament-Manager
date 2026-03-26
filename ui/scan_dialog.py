# -*- coding: utf-8 -*-

# Dialog for scanning a filament spool RFID tag with a Proxmark3 reader.

from PyQt6.QtCore import Qt, QSettings, QTimer
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QDialogButtonBox, QSizePolicy,
    QLineEdit, QFormLayout, QWidget,
)

from scanner import ScannerThread, get_saved_pm3_path


class ScanDialog(QDialog):
    """
    Scans a filament spool RFID tag via Proxmark3.

    Scanning starts automatically when the dialog opens and retries
    continuously until a tag is found or the user cancels.

    If the scanned UID already exists in the database (and mode != "remove"),
    the dialog auto-accepts so the caller can just select the existing row.
    """

    def __init__(self, parent=None, mode="add", db=None):
        super().__init__(parent)
        self._mode = mode
        self._db = db
        self.setWindowTitle("Remove Spool by Scan" if mode == "remove" else "Scan Filament Tag")
        self.setMinimumWidth(500)
        self.tag_data: dict | None = None
        self.auto_closed = False  # True if dialog auto-accepted for existing spool
        self._thread: ScannerThread | None = None

        self._build_ui()

        # Auto-start scanning after the dialog is shown
        QTimer.singleShot(0, self._start_scan)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Status / log area
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(120)
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.log)

        # Tag summary (shown after successful scan)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        layout.addWidget(self.summary_label)

        # Barcode and SKU entry fields (shown after scan)
        self.extras_widget = QWidget()
        extras_form = QFormLayout(self.extras_widget)
        extras_form.setContentsMargins(0, 0, 0, 0)
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
        extras_form.addRow("Color Name:", self.color_name_edit)
        self.extras_widget.hide()
        layout.addWidget(self.extras_widget)

        # OK / Cancel buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_label = "Remove from Inventory" if self._mode == "remove" else "Add to Inventory"
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText(ok_label)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self._on_cancel)
        layout.addWidget(self.button_box)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, message: str):
        self.log.append(message)

    # ------------------------------------------------------------------
    # Scan control
    # ------------------------------------------------------------------

    def _start_scan(self):
        settings = QSettings()
        port = settings.value("proxmark3/port", "")
        if not port:
            self._log("No COM port configured. Please set one in Settings.")
            return

        pm3_text = get_saved_pm3_path() or ""

        self.tag_data = None
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.summary_label.hide()
        self.extras_widget.hide()
        self.barcode_edit.clear()
        self.sku_edit.clear()
        self.color_name_edit.clear()
        self.log.clear()

        self._thread = ScannerThread(
            port=port,
            pm3_path=pm3_text,
            db=self._db,
            parent=self,
        )
        self._thread.status_update.connect(self._log)
        self._thread.scan_complete.connect(self._on_scan_complete)
        self._thread.scan_error.connect(self._on_scan_error)
        self._thread.start()

    def _stop_scan(self):
        if self._thread:
            self._thread.stop()

    # ------------------------------------------------------------------
    # Scanner signal handlers
    # ------------------------------------------------------------------

    def _on_scan_complete(self, tag_dict: dict):
        self.tag_data = tag_dict
        self._log("Scan complete!")

        color = tag_dict.get("filament_color", "")
        dtype = tag_dict.get("detailed_filament_type", tag_dict.get("filament_type", ""))
        weight = tag_dict.get("spool_weight", "?")
        uid = tag_dict.get("uid", "")

        # Auto-close for existing spools — no need to show "Add to Inventory"
        db = self._db or (getattr(self.parent(), 'db', None) if self.parent() else None)
        if db and self._mode != "remove":
            existing = db.get_by_uid(uid) if uid else None
            # Also check tray_uid — each spool has two RFID tags with different
            # chip UIDs but the same tray_uid (physical spool identifier)
            if not existing:
                tray_uid = tag_dict.get("tray_uid", "")
                if tray_uid:
                    existing = db.get_by_tray_uid(tray_uid)
                    if existing and uid:
                        # Store the alternate UID so the caller can update the entry
                        tag_dict["_matched_entry_id"] = existing["id"]
            if existing:
                self.auto_closed = True
                self.accept()
                return

        summary = (
            f"<b>Type:</b> {dtype}<br>"
            f"<b>Color:</b> {color}<br>"
            f"<b>Weight:</b> {weight} g<br>"
            f"<b>UID:</b> {uid}"
        )
        self.summary_label.setText(summary)
        self.summary_label.show()

        if self._mode == "remove":
            self.extras_widget.hide()
        else:
            self.extras_widget.show()

        # Pre-populate barcode, SKU, and color name from existing entries
        if db:
            # Find a matching product by variant_id or material_id
            variant_id = tag_dict.get("variant_id", "")
            material_id = tag_dict.get("material_id", "")
            match = None
            if variant_id:
                vid = variant_id.upper()
                for e in db._entries:
                    if (e.get("variant_id") or "").upper() == vid:
                        match = e
                        break
            if not match and material_id:
                match = db.get_by_material_id(material_id)

            if match:
                if match.get("barcode"):
                    self.barcode_edit.setText(match["barcode"])
                if match.get("color_name"):
                    self.color_name_edit.setText(match["color_name"])

            generated_sku = db.generate_sku(tag_dict)
            if generated_sku:
                self.sku_edit.setText(generated_sku)

            # Fall back to color hex matching for color name
            if not self.color_name_edit.text():
                learned = db._find_color_name(
                    tag_dict.get("filament_color", ""),
                    tag_dict.get("detailed_filament_type") or tag_dict.get("filament_type", ""),
                )
                if learned:
                    self.color_name_edit.setText(learned)

        # Disable autoDefault on all buttons so Enter in the text fields
        # doesn't trigger "Add to Inventory" (barcode scanners send Enter)
        ok_btn = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setEnabled(True)
        ok_btn.setDefault(False)
        ok_btn.setAutoDefault(False)
        cancel_btn = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setAutoDefault(False)

        self.barcode_edit.setFocus()

    def _on_accept(self):
        # Merge barcode and SKU into tag data before accepting
        if self.tag_data:
            barcode = self.barcode_edit.text().strip()
            sku = self.sku_edit.text().strip()
            if barcode:
                self.tag_data["barcode"] = barcode
            if sku:
                self.tag_data["sku"] = sku
            color_name = self.color_name_edit.text().strip()
            if color_name:
                self.tag_data["color_name"] = color_name
        self.accept()

    def _on_scan_error(self, message: str):
        self._log(f"ERROR: {message}")

    def _on_cancel(self):
        self._stop_scan()
        self.reject()

    def closeEvent(self, event):
        self._stop_scan()
        super().closeEvent(event)

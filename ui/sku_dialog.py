# -*- coding: utf-8 -*-

# Dialog for adding a filament spool via barcode scan or SKU entry.

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QDialogButtonBox, QGroupBox, QFormLayout, QMessageBox,
)

from sku_parser import parse_sku


class SkuDialog(QDialog):
    """
    Dialog where the user scans an EAN-13 barcode or types a text SKU.

    - Numeric input (EAN-13): looks up in the local database by barcode.
      If found, copies all properties from the matching entry.
      If not found, creates a new entry (user fills in details via Edit).
    - Text input (SKU format): parses the SKU to extract material/weight/diameter
      and tries to learn from previously scanned spools.

    After acceptance, self.tag_data holds a partial filament dict.
    """

    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Filament by Product Code")
        self.setMinimumWidth(450)
        self.tag_data: dict | None = None
        self._db = db
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Input row
        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("Product Code / SKU:"))
        self.sku_input = QLineEdit()
        self.sku_input.setPlaceholderText("Scan product code or type SKU")
        self.sku_input.returnPressed.connect(self._on_parse)
        input_row.addWidget(self.sku_input, 1)
        self.parse_btn = QPushButton("Look Up")
        self.parse_btn.clicked.connect(self._on_parse)
        input_row.addWidget(self.parse_btn)
        layout.addLayout(input_row)

        # Result display
        self.result_group = QGroupBox("Product Info")
        self.result_form = QFormLayout(self.result_group)
        self.lbl_barcode = QLabel("-")
        self.lbl_type = QLabel("-")
        self.lbl_color = QLabel("-")
        self.lbl_weight = QLabel("-")
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color: #2a7; font-style: italic;")
        self.result_form.addRow("Product Code:", self.lbl_barcode)
        self.result_form.addRow("Type:", self.lbl_type)
        self.result_form.addRow("Color:", self.lbl_color)
        self.result_form.addRow("Weight:", self.lbl_weight)
        self.result_form.addRow("", self.lbl_status)
        self.result_group.hide()
        layout.addWidget(self.result_group)

        # Error label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: red;")
        layout.addWidget(self.status_label)

        layout.addStretch()

        # Buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Add to Inventory")
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.sku_input.setFocus()

    def _on_parse(self):
        text = self.sku_input.text().strip()
        if not text:
            return

        # Determine if this is a numeric barcode or a text SKU
        if text.isdigit() and len(text) >= 8:
            self._lookup_barcode(text)
        else:
            self._parse_sku(text)

    def _lookup_barcode(self, barcode: str):
        """Handle numeric EAN-13 / UPC barcode input."""
        self.status_label.setText("")

        # Check if we already have an entry with this barcode
        learned_fields = {}
        existing = self._db.get_by_barcode(barcode) if self._db else None

        if existing:
            # Copy all useful properties from the matching entry
            for key in ("filament_type", "detailed_filament_type",
                        "filament_color", "material_id", "variant_id",
                        "temperatures", "nozzle_diameter", "spool_width",
                        "filament_length", "filament_diameter",
                        "spool_weight", "tare_weight",
                        "sku", "color_name"):
                if existing.get(key):
                    learned_fields[key] = existing[key]

            dtype = existing.get("detailed_filament_type") or existing.get("filament_type", "")
            color = existing.get("filament_color", "")
            weight = existing.get("spool_weight", "")

            self.lbl_barcode.setText(barcode)
            self.lbl_type.setText(dtype or "-")
            self.lbl_color.setText(color or "-")
            self.lbl_weight.setText(f"{weight} g" if weight else "-")
            self.lbl_status.setText(
                f"Known product code — matched to '{dtype}'.\n"
                "All properties will be copied to the new spool."
            )
        else:
            QMessageBox.information(
                self, "Product Code Not Found",
                f"Product code {barcode} was not found in the database.\n\n"
                "A new entry will be created. Fill in details via Edit after adding."
            )
            self.lbl_barcode.setText(barcode)
            self.lbl_type.setText("Unknown")
            self.lbl_color.setText("Unknown")
            self.lbl_weight.setText("-")
            self.lbl_status.setText(
                "New product code — not yet in the database.\n"
                "Fill in details via Edit after adding."
            )
            self.lbl_status.setStyleSheet("color: #c70; font-style: italic;")

        self.result_group.show()

        # Build tag_data
        self.tag_data = {
            "barcode": barcode,
            "source": "barcode",
            "uid": "",
            "filament_type": "",
            "detailed_filament_type": "",
            "filament_color": "",
            "material_id": "",
            "variant_id": "",
            "spool_weight": 0,
            "filament_length": 0,
            "filament_diameter": 1.75,
            "nozzle_diameter": 0.4,
            "spool_width": 0.0,
            "temperatures": {},
            "production_date": "",
        }
        self.tag_data.update(learned_fields)

        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def _parse_sku(self, text: str):
        """Handle text SKU input (e.g. B50-K0-1.75-1000-SPL)."""
        parsed = parse_sku(text)
        if not parsed:
            self.status_label.setText(
                f"Could not parse: '{text}'\n"
                "Expected a numeric product code or SKU like B50-K0-1.75-1000-SPL"
            )
            self.result_group.hide()
            self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            self.tag_data = None
            return

        self.status_label.setText("")

        # Try to learn from previously scanned spools with the same material_id
        learned_fields = {}
        if self._db:
            existing = self._db.get_by_material_id(parsed["material_id"])
            if existing:
                for key in ("filament_type", "detailed_filament_type",
                            "filament_color", "temperatures",
                            "nozzle_diameter", "spool_width",
                            "filament_length"):
                    if existing.get(key):
                        learned_fields[key] = existing[key]

                dtype = existing.get("detailed_filament_type") or existing.get("filament_type", "")
                status_msg = f"Matched existing spool: {dtype}\nType, color, and temperatures will be copied."
            else:
                status_msg = "No previously scanned spool of this material found.\nYou can fill in details via Edit after adding."
        else:
            status_msg = ""

        self.lbl_barcode.setText("-")
        self.lbl_type.setText(learned_fields.get("detailed_filament_type", parsed["material_id"]))
        self.lbl_color.setText(learned_fields.get("filament_color", "-"))
        self.lbl_weight.setText(f"{parsed['spool_weight']} g")
        self.lbl_status.setText(status_msg)
        self.lbl_status.setStyleSheet("color: #2a7; font-style: italic;")
        self.result_group.show()

        # Build the tag_data dict
        self.tag_data = parsed.copy()
        self.tag_data.update(learned_fields)
        self.tag_data.setdefault("filament_type", "")
        self.tag_data.setdefault("detailed_filament_type", "")
        self.tag_data.setdefault("filament_color", "")
        self.tag_data.setdefault("uid", "")
        self.tag_data.setdefault("filament_length", 0)
        self.tag_data.setdefault("nozzle_diameter", 0.4)
        self.tag_data.setdefault("spool_width", 0.0)
        self.tag_data.setdefault("temperatures", {})
        self.tag_data.setdefault("production_date", "")

        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

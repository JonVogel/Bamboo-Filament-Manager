# -*- coding: utf-8 -*-

# Dialog for viewing and editing all fields of a filament entry.

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit,
    QPushButton, QDialogButtonBox, QColorDialog, QScrollArea,
    QWidget, QSizePolicy,
)


class ColorButton(QPushButton):
    """A button that shows a color swatch and opens a color picker on click."""

    def __init__(self, hex_color: str = "#FFFFFF", parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 24)
        self.set_color(hex_color)
        self.clicked.connect(self._pick_color)

    def set_color(self, hex_color: str):
        # Accept #RRGGBB or #RRGGBBAA — strip alpha for display
        self._hex = hex_color[:7] if hex_color else "#FFFFFF"
        self.setStyleSheet(f"background-color: {self._hex}; border: 1px solid #666;")

    def color(self) -> str:
        return self._hex

    def _pick_color(self):
        chosen = QColorDialog.getColor(QColor(self._hex), self, "Choose Color")
        if chosen.isValid():
            self.set_color(chosen.name())


class EditDialog(QDialog):
    """
    Edit all fields of a filament inventory entry.

    Pass the full entry dict on construction; call result_fields() after
    acceptance to get the merged update dict.
    """

    def __init__(self, entry: dict, parent=None, adding: bool = False, db=None):
        super().__init__(parent)
        self._adding = adding
        self._db = db
        self.setWindowTitle("Add Filament" if adding else "Edit Filament")
        self.setMinimumWidth(520)
        self._entry = entry
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(10)

        layout.addWidget(self._build_identity_group())
        layout.addWidget(self._build_physical_group())
        layout.addWidget(self._build_temperature_group())
        layout.addWidget(self._build_inventory_group())

        scroll.setWidget(content)
        outer.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setAutoDefault(False)
        ok_btn.setDefault(False)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setAutoDefault(False)
        cancel_btn.setDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # ------------------------------------------------------------------
    # Field groups
    # ------------------------------------------------------------------

    def _build_identity_group(self) -> QGroupBox:
        grp = QGroupBox("Filament Identity")
        form = QFormLayout(grp)

        if self._adding:
            self.uid_edit = QLineEdit(self._entry.get("uid", ""))
            self.uid_edit.setPlaceholderText("Tag UID (optional)")
        else:
            self.uid_edit = self._ro_line(self._entry.get("uid", ""))
        self.barcode_edit = QLineEdit(self._entry.get("barcode", ""))
        self.barcode_edit.setPlaceholderText("EAN-13 product code")
        self.barcode_edit.returnPressed.connect(self._on_barcode_entered)
        self.sku_edit = QLineEdit(self._entry.get("sku", ""))
        self.sku_edit.setPlaceholderText("e.g. PA1-002-US2")
        self.sku_edit.returnPressed.connect(lambda: self.type_edit.setFocus())
        self.type_edit = QLineEdit(self._entry.get("filament_type", ""))
        self.type_edit.returnPressed.connect(lambda: self.dtype_edit.setFocus())
        self.dtype_edit = QLineEdit(self._entry.get("detailed_filament_type", ""))
        self.dtype_edit.returnPressed.connect(lambda: self.mat_id_edit.setFocus())
        self.mat_id_edit = QLineEdit(self._entry.get("material_id", ""))
        self.mat_id_edit.returnPressed.connect(lambda: self.var_id_edit.setFocus())
        self.var_id_edit = QLineEdit(self._entry.get("variant_id", ""))
        self.store_id_edit = QLineEdit(self._entry.get("store_variant_id", ""))
        self.store_id_edit.setPlaceholderText("Shopify variant ID from store URL (?id=...)")
        self.prod_date_edit = self._ro_line(str(self._entry.get("production_date", "")))

        # Color
        color_row = QHBoxLayout()
        self.color_btn = ColorButton(self._entry.get("filament_color", "#FFFFFF"))
        self.color_hex = QLineEdit(self._entry.get("filament_color", ""))
        self.color_hex.setMaximumWidth(90)
        self.color_btn.clicked.connect(
            lambda: self.color_hex.setText(self.color_btn.color())
        )
        self.color_hex.textChanged.connect(
            lambda t: self.color_btn.set_color(t) if len(t) in (7, 9) and t.startswith("#") else None
        )
        self.color_name_edit = QLineEdit(self._entry.get("color_name", ""))
        self.color_name_edit.setPlaceholderText("e.g. Charcoal, Yellow, White")
        color_row.addWidget(self.color_btn)
        color_row.addWidget(self.color_hex)
        color_row.addWidget(self.color_name_edit, 1)

        form.addRow("UID:", self.uid_edit)
        form.addRow("Product Code:", self.barcode_edit)
        form.addRow("SKU:", self.sku_edit)
        form.addRow("Filament Type:", self.type_edit)
        form.addRow("Detailed Type:", self.dtype_edit)
        form.addRow("Material ID:", self.mat_id_edit)
        form.addRow("Variant ID:", self.var_id_edit)
        form.addRow("Store Variant:", self.store_id_edit)
        form.addRow("Color:", color_row)
        form.addRow("Production Date:", self.prod_date_edit)
        return grp

    def _build_physical_group(self) -> QGroupBox:
        grp = QGroupBox("Physical Properties")
        form = QFormLayout(grp)

        self.weight_spin = QSpinBox()
        self.weight_spin.setRange(0, 10000)
        self.weight_spin.setSuffix(" g")
        self.weight_spin.setValue(int(self._entry.get("spool_weight") or 0))

        self.length_spin = QSpinBox()
        self.length_spin.setRange(0, 99999)
        self.length_spin.setSuffix(" m")
        self.length_spin.setValue(int(self._entry.get("filament_length") or 0))

        self.diameter_spin = QDoubleSpinBox()
        self.diameter_spin.setRange(0.0, 5.0)
        self.diameter_spin.setDecimals(2)
        self.diameter_spin.setSuffix(" mm")
        self.diameter_spin.setValue(float(self._entry.get("filament_diameter") or 1.75))

        self.nozzle_spin = QDoubleSpinBox()
        self.nozzle_spin.setRange(0.0, 2.0)
        self.nozzle_spin.setDecimals(1)
        self.nozzle_spin.setSuffix(" mm")
        self.nozzle_spin.setValue(float(self._entry.get("nozzle_diameter") or 0.4))

        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.0, 200.0)
        self.width_spin.setDecimals(2)
        self.width_spin.setSuffix(" mm")
        self.width_spin.setValue(float(self._entry.get("spool_width") or 0))

        self.tare_spin = QSpinBox()
        self.tare_spin.setRange(0, 5000)
        self.tare_spin.setSuffix(" g")
        self.tare_spin.setValue(int(self._entry.get("tare_weight") or 250))

        form.addRow("Filament Weight:", self.weight_spin)
        form.addRow("Filament Length:", self.length_spin)
        form.addRow("Diameter:", self.diameter_spin)
        form.addRow("Nozzle Diameter:", self.nozzle_spin)
        form.addRow("Spool Width:", self.width_spin)
        form.addRow("Empty Spool Weight:", self.tare_spin)
        return grp

    def _build_temperature_group(self) -> QGroupBox:
        grp = QGroupBox("Temperatures")
        form = QFormLayout(grp)
        temps = self._entry.get("temperatures", {})

        def temp_spin(value, lo=0, hi=400):
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setSuffix(" °C")
            s.setValue(int(value or 0))
            return s

        self.min_hotend_spin = temp_spin(temps.get("min_hotend"))
        self.max_hotend_spin = temp_spin(temps.get("max_hotend"))
        self.bed_spin = temp_spin(temps.get("bed_temp"))
        self.dry_temp_spin = temp_spin(temps.get("drying_temp"))
        self.dry_time_spin = QSpinBox()
        self.dry_time_spin.setRange(0, 168)
        self.dry_time_spin.setSuffix(" h")
        self.dry_time_spin.setValue(int(temps.get("drying_time") or 0))

        form.addRow("Min Hotend:", self.min_hotend_spin)
        form.addRow("Max Hotend:", self.max_hotend_spin)
        form.addRow("Bed Temp:", self.bed_spin)
        form.addRow("Drying Temp:", self.dry_temp_spin)
        form.addRow("Drying Time:", self.dry_time_spin)
        return grp

    def _build_inventory_group(self) -> QGroupBox:
        grp = QGroupBox("Inventory")
        form = QFormLayout(grp)
        inv = self._entry.get("__inventory__", {})

        self.rem_weight_spin = QSpinBox()
        self.rem_weight_spin.setRange(0, 10000)
        self.rem_weight_spin.setSuffix(" g")
        self.rem_weight_spin.setValue(int(inv.get("remaining_weight_g") or 0))

        self.rem_length_spin = QSpinBox()
        self.rem_length_spin.setRange(0, 99999)
        self.rem_length_spin.setSuffix(" m")
        self.rem_length_spin.setValue(int(inv.get("remaining_length_m") or 0))

        self.location_edit = QLineEdit(inv.get("location", ""))
        self.location_edit.setPlaceholderText("e.g. Dry Box 1, Shelf A")

        self.notes_edit = QTextEdit(inv.get("notes", ""))
        self.notes_edit.setFixedHeight(80)

        form.addRow("Remaining Weight:", self.rem_weight_spin)
        form.addRow("Remaining Length:", self.rem_length_spin)
        form.addRow("Location:", self.location_edit)
        form.addRow("Notes:", self.notes_edit)
        return grp

    # ------------------------------------------------------------------
    # Barcode lookup
    # ------------------------------------------------------------------

    def _on_barcode_entered(self):
        """Look up product code in the database and auto-fill fields from a matching entry."""
        if self._db:
            barcode = self.barcode_edit.text().strip()
            if barcode:
                existing = self._db.get_by_barcode(barcode)
                if existing:
                    # Auto-fill empty fields from the matching entry
                    if not self.sku_edit.text().strip():
                        self.sku_edit.setText(existing.get("sku", ""))
                    if not self.color_name_edit.text().strip():
                        self.color_name_edit.setText(existing.get("color_name", ""))
                    if not self.type_edit.text().strip():
                        self.type_edit.setText(existing.get("filament_type", ""))
                    if not self.dtype_edit.text().strip():
                        self.dtype_edit.setText(existing.get("detailed_filament_type", ""))
                    if not self.mat_id_edit.text().strip():
                        self.mat_id_edit.setText(existing.get("material_id", ""))
                    if not self.var_id_edit.text().strip():
                        self.var_id_edit.setText(existing.get("variant_id", ""))
                    if not self.color_hex.text().strip() or self.color_hex.text().strip() == "#FFFFFFFF":
                        color = existing.get("filament_color", "")
                        if color:
                            self.color_hex.setText(color)
                            self.color_btn.set_color(color)
                    # Auto-fill temperatures if all zeros
                    existing_temps = existing.get("temperatures", {})
                    if self.max_hotend_spin.value() == 0 and existing_temps.get("max_hotend"):
                        self.min_hotend_spin.setValue(int(existing_temps.get("min_hotend", 0)))
                        self.max_hotend_spin.setValue(int(existing_temps.get("max_hotend", 0)))
                        self.bed_spin.setValue(int(existing_temps.get("bed_temp", 0)))
                        self.dry_temp_spin.setValue(int(existing_temps.get("drying_temp", 0)))
                        self.dry_time_spin.setValue(int(existing_temps.get("drying_time", 0)))
                    # Auto-fill physical properties
                    if self.weight_spin.value() == 0 or self.weight_spin.value() == 1000:
                        w = existing.get("spool_weight")
                        if w:
                            self.weight_spin.setValue(int(w))
                    if self.length_spin.value() == 0:
                        l = existing.get("filament_length")
                        if l:
                            self.length_spin.setValue(int(l))
        self.sku_edit.setFocus()

    # ------------------------------------------------------------------
    # Event overrides
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        # Prevent Enter/Return from closing the dialog (barcode scanners send Enter),
        # but let QLineEdit widgets handle it first so returnPressed signals fire.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            focused = self.focusWidget()
            if isinstance(focused, QLineEdit):
                # Let the QLineEdit process Enter (fires returnPressed)
                focused.event(event)
            # Either way, don't let the dialog close
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _ro_line(self, text: str) -> QLineEdit:
        w = QLineEdit(text)
        w.setReadOnly(True)
        w.setStyleSheet("color: #888;")
        return w

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def result_fields(self) -> dict:
        """Return a dict of all edited fields, suitable for FilamentDB.update()."""
        fields = {
            "filament_type": self.type_edit.text().strip(),
            "detailed_filament_type": self.dtype_edit.text().strip(),
            "material_id": self.mat_id_edit.text().strip(),
            "variant_id": self.var_id_edit.text().strip(),
            "store_variant_id": self.store_id_edit.text().strip(),
            "barcode": self.barcode_edit.text().strip(),
            "sku": self.sku_edit.text().strip(),
            "filament_color": self.color_hex.text().strip(),
            "color_name": self.color_name_edit.text().strip(),
            "spool_weight": self.weight_spin.value(),
            "tare_weight": self.tare_spin.value(),
            "filament_length": self.length_spin.value(),
            "filament_diameter": self.diameter_spin.value(),
            "nozzle_diameter": self.nozzle_spin.value(),
            "spool_width": self.width_spin.value(),
            "temperatures": {
                "min_hotend": self.min_hotend_spin.value(),
                "max_hotend": self.max_hotend_spin.value(),
                "bed_temp": self.bed_spin.value(),
                "drying_temp": self.dry_temp_spin.value(),
                "drying_time": self.dry_time_spin.value(),
            },
            "__inventory__": {
                "remaining_weight_g": self.rem_weight_spin.value(),
                "remaining_length_m": self.rem_length_spin.value(),
                "location": self.location_edit.text().strip(),
                "notes": self.notes_edit.toPlainText().strip(),
            },
        }
        if self._adding:
            uid = self.uid_edit.text().strip()
            if uid:
                fields["uid"] = uid
        return fields

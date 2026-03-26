# -*- coding: utf-8 -*-

# Settings dialogs for configuring Proxmark3 path/COM port and label printer.

import serial.tools.list_ports
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QLineEdit, QFileDialog, QDialogButtonBox,
    QFormLayout, QMessageBox, QApplication,
)

from scanner import find_pm3, get_saved_pm3_path, save_pm3_path, check_pm3_connection
from printer_manager import driver_names


def _populate_ports_combo(combo: QComboBox):
    """Fill a QComboBox with available serial ports."""
    combo.clear()
    ports = [p.device for p in serial.tools.list_ports.comports()]
    if ports:
        combo.addItems(ports)
    else:
        combo.addItem("No ports found")


class SettingsDialog(QDialog):
    """Configure Proxmark3 client path and COM port."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Proxmark3 Settings")
        self.setMinimumWidth(500)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        # Proxmark3 path
        pm3_row = QHBoxLayout()
        self.pm3_path = QLineEdit()
        self.pm3_path.setPlaceholderText("Path to proxmark3.exe (leave blank to auto-detect)")
        saved = get_saved_pm3_path()
        if saved:
            self.pm3_path.setText(saved)
        else:
            found = find_pm3()
            if found:
                self.pm3_path.setText(str(found))
        pm3_row.addWidget(self.pm3_path, 1)
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.setAutoDefault(False)
        self.browse_btn.clicked.connect(self._browse_pm3)
        pm3_row.addWidget(self.browse_btn)
        form.addRow("Proxmark3:", pm3_row)

        # COM port
        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        _populate_ports_combo(self.port_combo)
        saved_port = QSettings().value("proxmark3/port", "")
        if saved_port:
            idx = self.port_combo.findText(saved_port)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)
        port_row.addWidget(self.port_combo, 1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setAutoDefault(False)
        self.refresh_btn.clicked.connect(
            lambda: _populate_ports_combo(self.port_combo)
        )
        port_row.addWidget(self.refresh_btn)
        self.test_btn = QPushButton("Test")
        self.test_btn.setAutoDefault(False)
        self.test_btn.clicked.connect(self._on_test)
        port_row.addWidget(self.test_btn)
        form.addRow("COM Port:", port_row)

        # Status label for test results
        self._status = QLabel("")
        self._status.setWordWrap(True)
        form.addRow("", self._status)

        layout.addLayout(form)

        # OK / Cancel
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _browse_pm3(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Locate Proxmark3 Client", "",
            "Executables (*.exe);;All files (*)",
        )
        if path:
            self.pm3_path.setText(path)

    def _on_test(self):
        """Test connectivity to the Proxmark3 reader."""
        pm3_text = self.pm3_path.text().strip()
        port = self.port_combo.currentText()
        if not port or port == "No ports found":
            self._status.setStyleSheet("color: red;")
            self._status.setText("No COM port selected.")
            return

        self._status.setStyleSheet("color: #666;")
        self._status.setText("Testing connection...")
        QApplication.processEvents()

        ok, msg = check_pm3_connection(pm3_text, port)
        if ok:
            self._status.setStyleSheet("color: green;")
        else:
            self._status.setStyleSheet("color: red;")
        self._status.setText(msg)

    def _on_accept(self):
        settings = QSettings()
        pm3_text = self.pm3_path.text().strip()
        if pm3_text:
            save_pm3_path(pm3_text)
        port = self.port_combo.currentText()
        if port and port != "No ports found":
            settings.setValue("proxmark3/port", port)
        self.accept()


class PrinterSettingsDialog(QDialog):
    """Configure label printer driver, barcode type, and Nelko port."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Printer Settings")
        self.setMinimumWidth(500)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        # Printer driver
        self.printer_combo = QComboBox()
        for key, name in driver_names():
            self.printer_combo.addItem(name, key)
        saved_driver = QSettings().value("printer/driver", "windows")
        idx = self.printer_combo.findData(saved_driver)
        if idx >= 0:
            self.printer_combo.setCurrentIndex(idx)
        self.printer_combo.currentIndexChanged.connect(self._on_printer_changed)
        form.addRow("Printer:", self.printer_combo)

        # Barcode type
        self.barcode_combo = QComboBox()
        self.barcode_combo.addItem("QR Code (2D)", "qr")
        self.barcode_combo.addItem("Code 128 (1D)", "code128")
        saved_barcode = QSettings().value("printer/barcode_type", "qr")
        idx = self.barcode_combo.findData(saved_barcode)
        if idx >= 0:
            self.barcode_combo.setCurrentIndex(idx)
        form.addRow("Label Barcode:", self.barcode_combo)

        # Nelko port (only visible when Nelko is selected)
        nelko_row = QHBoxLayout()
        self.nelko_port_combo = QComboBox()
        _populate_ports_combo(self.nelko_port_combo)
        saved_nelko = QSettings().value("printer/nelko_port", "COM11")
        idx = self.nelko_port_combo.findText(saved_nelko)
        if idx >= 0:
            self.nelko_port_combo.setCurrentIndex(idx)
        nelko_row.addWidget(self.nelko_port_combo, 1)
        self.nelko_refresh_btn = QPushButton("Refresh")
        self.nelko_refresh_btn.setAutoDefault(False)
        self.nelko_refresh_btn.clicked.connect(
            lambda: _populate_ports_combo(self.nelko_port_combo)
        )
        nelko_row.addWidget(self.nelko_refresh_btn)
        self.nelko_port_label = QLabel("Nelko Port:")
        form.addRow(self.nelko_port_label, nelko_row)
        self._nelko_row_widgets = [self.nelko_port_label, self.nelko_port_combo, self.nelko_refresh_btn]

        layout.addLayout(form)

        # Show/hide Nelko port based on current selection
        self._on_printer_changed()

        # OK / Cancel
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _on_printer_changed(self):
        is_nelko = self.printer_combo.currentData() == "nelko_p21"
        for w in self._nelko_row_widgets:
            w.setVisible(is_nelko)

    def _on_accept(self):
        settings = QSettings()
        driver_key = self.printer_combo.currentData()
        settings.setValue("printer/driver", driver_key)
        settings.setValue("printer/barcode_type", self.barcode_combo.currentData())
        nelko_port = self.nelko_port_combo.currentText()
        if nelko_port and nelko_port != "No ports found":
            settings.setValue("printer/nelko_port", nelko_port)
        self.accept()

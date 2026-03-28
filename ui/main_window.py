# -*- coding: utf-8 -*-

# Main application window — filament inventory table with toolbar.

from PyQt6.QtCore import Qt, QSize, QSettings, QEvent, QPoint
from PyQt6.QtGui import QBrush, QColor, QIcon, QFont, QLinearGradient, QPainter, QAction, QKeyEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QToolBar, QToolButton, QLabel, QFileDialog,
    QMessageBox, QStatusBar, QFrame, QSplitter,
    QGroupBox, QGridLayout, QMenu, QInputDialog, QLineEdit, QComboBox,
    QStyledItemDelegate, QStyleOptionViewItem,
    QAbstractItemView, QStyle, QWidgetAction, QCheckBox,
)

import webbrowser

from database import FilamentDB
from rfid_parser import load_file
from ui.bulk_scan_dialog import BulkScanDialog
from ui.edit_dialog import EditDialog
from ui.scan_dialog import ScanDialog
from ui.inventory_dialog import InventoryDialog
from ui.settings_dialog import SettingsDialog, PrinterSettingsDialog
from ui.sku_dialog import SkuDialog


# Bambu Lab store product slugs keyed by detailed_filament_type
_STORE_SLUGS = {
    "PLA Basic":          "pla-basic-filament",
    "PLA Matte":          "pla-matte",
    "PLA Silk":           "pla-silk-upgrade",
    "PLA Silk+":          "pla-silk-upgrade",
    "PLA Tough":          "pla-tough-upgrade",
    "PLA Tough+":         "pla-tough-upgrade",
    "PLA Translucent":    "pla-translucent",
    "PLA-CF":             "pla-cf",
    "PLA Sparkle":        "pla-sparkle",
    "PLA Metal":          "pla-metal",
    "PLA Marble":         "pla-marble",
    "PLA Galaxy":         "pla-galaxy",
    "PLA Wood":           "pla-wood",
    "PLA Glow":           "pla-glow",
    "PLA Aero":           "pla-aero",
    "PETG HF":            "petg-hf",
    "PETG Translucent":   "petg-translucent",
    "PETG-CF":            "petg-cf",
    "ABS":                "abs-filament",
    "ABS-GF":             "abs-gf",
    "ASA":                "asa-filament",
    "ASA-CF":             "asa-cf",
    "TPU for AMS":        "tpu-for-ams",
    "TPU 95A HF":         "tpu-95a-hf",
    "TPU 95A":            "tpu-95a-hf",
    "TPU 85A":            "tpu-85a-tpu-90a",
    "TPU 90A":            "tpu-85a-tpu-90a",
    "PAHT-CF":            "paht-cf",
    "PA6-CF":             "pa6-cf",
    "PA6-GF":             "pa6-gf",
    "PC":                 "pc-filament",
    "PET-CF":             "pet-cf",
    "PPA-CF":             "ppa-cf",
    "PPS-CF":             "pps-cf",
    "Support for PLA":    "support_for_pla_new",
}

_STORE_BASE = "https://us.store.bambulab.com/products/"


def _store_url(entry: dict) -> str | None:
    """Return the Bambu Lab store URL for a filament entry, or None."""
    dtype = entry.get("detailed_filament_type") or entry.get("filament_type", "")
    slug = _STORE_SLUGS.get(dtype)
    if not slug and dtype:
        slug = dtype.lower().replace(" ", "-").replace("+", "")
    if not slug:
        return None
    url = _STORE_BASE + slug
    store_vid = entry.get("store_variant_id", "")
    if store_vid:
        url += f"?id={store_vid}"
    return url


# Column indices
COL_SPOOL   = 0
COL_COLOR   = 1
COL_TYPE    = 2
COL_WEIGHT  = 3
COL_REM     = 4
COL_DIAM    = 5
COL_NOZZLE  = 6
COL_SKU      = 7
COL_BARCODE  = 8
COL_STORE_ID = 9
COL_LOCATION = 10
COL_SCANNED  = 11
COL_UID      = 12
COL_MAT_ID   = 13
COL_VAR_ID   = 14
COL_REM_LEN  = 15
COL_FIL_LEN  = 16
COL_SPOOL_W  = 17
COL_NOZ_DIAM = 18
COL_TARE     = 19
COL_BED_TEMP = 20
COL_DRY_TEMP = 21
COL_DRY_TIME = 22
COL_PROD_DATE = 23
COL_NOTES    = 24
COL_TRAY_UID = 25
COL_XCAM     = 26
COL_COLOR2   = 27
COL_COLOR_CT = 28
COL_UID2     = 29
COL_PRESENT  = 30

COLUMN_LABELS = [
    "Spool ID", "Color", "Type", "Weight", "Remaining", "Diameter",
    "Nozzle Temp", "SKU", "Product Code", "Store ID", "Location", "Scanned",
    "UID", "Material ID", "Variant ID", "Remaining Length", "Filament Length",
    "Spool Width", "Nozzle Diameter", "Tare Weight", "Bed Temp",
    "Drying Temp", "Drying Time", "Production Date", "Notes",
    "Tray UID", "X-Cam Info", "Color 2", "Color Count", "UID 2", "Present",
]

# Columns hidden by default (user can toggle via column chooser)
_DEFAULT_HIDDEN = {
    COL_DIAM, COL_NOZZLE, COL_STORE_ID,
    COL_UID, COL_MAT_ID, COL_VAR_ID, COL_REM_LEN, COL_FIL_LEN,
    COL_SPOOL_W, COL_NOZ_DIAM, COL_TARE, COL_BED_TEMP, COL_DRY_TEMP,
    COL_DRY_TIME, COL_PROD_DATE, COL_NOTES, COL_TRAY_UID, COL_XCAM,
    COL_COLOR2, COL_COLOR_CT, COL_UID2, COL_PRESENT,
}


class ColorItem(QTableWidgetItem):
    """Table cell that shows a solid or diagonal-split color swatch with a name."""

    ROLE_COLOR2 = Qt.ItemDataRole.UserRole + 1

    def __init__(self, hex_color: str, color_name: str = "", hex_color2: str = ""):
        display = color_name or hex_color[:7] if hex_color else ""
        super().__init__(display)
        self._hex1 = hex_color[:7] if hex_color else "#888888"
        self._hex2 = hex_color2[:7] if hex_color2 else ""
        # Store color2 for the delegate
        self.setData(self.ROLE_COLOR2, self._hex2)
        self.setBackground(QColor(self._hex1))
        # Pick white or black text based on dominant color
        c = QColor(self._hex1)
        luma = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        self.setForeground(QColor("#000000") if luma > 140 else QColor("#FFFFFF"))
        self.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable)
        tip = hex_color
        if hex_color2:
            tip += f" / {hex_color2}"
        self.setToolTip(tip)


class ColorDelegate(QStyledItemDelegate):
    """Paints a diagonal split swatch for dual-color filaments."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        color2 = index.data(ColorItem.ROLE_COLOR2)
        color1_hex = index.data(Qt.ItemDataRole.BackgroundRole)

        painter.save()
        rect = option.rect

        c1 = color1_hex if isinstance(color1_hex, QColor) else QColor(color1_hex or "#888888")

        # Fill with primary color
        painter.fillRect(rect, c1)

        if color2:
            # Draw secondary color as bottom-right triangle
            from PyQt6.QtGui import QPainterPath
            from PyQt6.QtCore import QPointF
            c2 = QColor(color2)
            path = QPainterPath()
            path.moveTo(QPointF(float(rect.right()), float(rect.top())))
            path.lineTo(QPointF(float(rect.right()), float(rect.bottom())))
            path.lineTo(QPointF(float(rect.left()), float(rect.bottom())))
            path.closeSubpath()
            painter.fillPath(path, c2)

        # Draw selection border (no overlay — preserves exact swatch color)
        if option.state & QStyle.StateFlag.State_Selected:
            from PyQt6.QtGui import QPen
            pen = QPen(QColor(0, 120, 215), 3)
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(1, 1, -2, -2))

        # Draw text
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if text:
            luma1 = 0.299 * c1.red() + 0.587 * c1.green() + 0.114 * c1.blue()
            if color2:
                c2 = QColor(color2)
                luma2 = 0.299 * c2.red() + 0.587 * c2.green() + 0.114 * c2.blue()
                avg_luma = (luma1 + luma2) / 2
            else:
                avg_luma = luma1
            painter.setPen(QColor("#000000") if avg_luma > 140 else QColor("#FFFFFF"))
            painter.drawText(rect.adjusted(4, 0, -4, 0),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

        painter.restore()


class MainWindow(QMainWindow):
    # Columns that can be edited inline
    EDITABLE_COLS = {COL_COLOR, COL_TYPE, COL_WEIGHT, COL_REM, COL_DIAM, COL_NOZZLE, COL_STORE_ID, COL_LOCATION}

    def __init__(self, db: FilamentDB):
        super().__init__()
        self.db = db
        self._refreshing = False
        self._grouped_view = False
        self._saved_column_visibility = {}
        self._scan_buffer = ""  # Keystroke buffer for barcode scanner input
        self.setWindowTitle("Bamboo Filament Manager")
        self.resize(1000, 600)

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()

        self.refresh_table()
        self._restore_geometry()
        self.table.setFocus()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setObjectName("MainToolBar")
        tb.setIconSize(QSize(16, 16))
        tb.setMovable(False)
        self.addToolBar(tb)

        # -- Add Filament dropdown --
        add_menu = QMenu("Add Filament", self)
        self.act_scan = add_menu.addAction("Scan Tag")
        self.act_scan.setStatusTip("Scan a single filament spool RFID tag")
        self.act_scan.triggered.connect(self._on_scan)
        self.act_sku = add_menu.addAction("Scan Product Code")
        self.act_sku.setStatusTip("Add a filament by scanning a product code or typing a SKU")
        self.act_sku.triggered.connect(self._on_sku)
        self.act_add = add_menu.addAction("Add Manual")
        self.act_add.setStatusTip("Manually add a filament entry")
        self.act_add.triggered.connect(self._on_add_manual)
        self.act_bulk_scan = add_menu.addAction("Bulk Scan")
        self.act_bulk_scan.setStatusTip("Scan multiple RFID tags in sequence")
        self.act_bulk_scan.triggered.connect(self._on_bulk_scan)

        btn_add = QToolButton()
        btn_add.setText("Add Filament")
        btn_add.setMenu(add_menu)
        btn_add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tb.addWidget(btn_add)

        # -- Delete Filament dropdown --
        del_menu = QMenu("Delete Filament", self)
        self.act_delete = del_menu.addAction("Delete Selected")
        self.act_delete.setStatusTip("Delete the selected filament")
        self.act_delete.triggered.connect(self._on_delete)
        self.act_remove_scan = del_menu.addAction("Scan Tag")
        self.act_remove_scan.setStatusTip("Scan an RFID tag to remove a used-up spool")
        self.act_remove_scan.triggered.connect(self._on_remove_by_scan)
        self.act_delete_by_spool_id = del_menu.addAction("Scan Spool ID")
        self.act_delete_by_spool_id.setStatusTip("Delete a spool by scanning its barcode label")
        self.act_delete_by_spool_id.triggered.connect(self._on_delete_by_spool_id)

        btn_del = QToolButton()
        btn_del.setText("Delete Filament")
        btn_del.setMenu(del_menu)
        btn_del.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tb.addWidget(btn_del)

        # -- Edit (direct button) --
        self.act_edit = QAction("Edit", self)
        self.act_edit.setStatusTip("Edit the selected filament")
        self.act_edit.triggered.connect(self._on_edit)
        tb.addAction(self.act_edit)

        # -- Weigh Spool (direct button) --
        self.act_weigh = QAction("Weigh Spool", self)
        self.act_weigh.setStatusTip("Enter scale weight to calculate remaining filament")
        self.act_weigh.triggered.connect(self._on_weigh)
        tb.addAction(self.act_weigh)

        # -- Import/Export dropdown --
        io_menu = QMenu("Import/Export", self)
        self.act_export_csv = io_menu.addAction("Export CSV")
        self.act_export_csv.setStatusTip("Export the filament inventory to a CSV file")
        self.act_export_csv.triggered.connect(self._on_export_csv)
        self.act_import_csv = io_menu.addAction("Import CSV")
        self.act_import_csv.setStatusTip("Import filament data from a CSV file")
        self.act_import_csv.triggered.connect(self._on_import_csv)
        self.act_import = io_menu.addAction("Import Dump File")
        self.act_import.setStatusTip("Import a .bin or .json dump file")
        self.act_import.triggered.connect(self._on_import)
        io_menu.addSeparator()
        self.act_export_db = io_menu.addAction("Export Database")
        self.act_export_db.setStatusTip("Export the full database to a JSON file for backup or transfer")
        self.act_export_db.triggered.connect(self._on_export_db)
        self.act_import_db = io_menu.addAction("Import Database")
        self.act_import_db.setStatusTip("Import a database JSON file (merges with existing data)")
        self.act_import_db.triggered.connect(self._on_import_db)

        btn_io = QToolButton()
        btn_io.setText("Import/Export")
        btn_io.setMenu(io_menu)
        btn_io.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tb.addWidget(btn_io)

        # -- Settings dropdown --
        settings_menu = QMenu("Settings", self)
        self.act_settings = settings_menu.addAction("Proxmark3 Settings")
        self.act_settings.setStatusTip("Configure Proxmark3 path and COM port")
        self.act_settings.triggered.connect(self._on_settings)
        self.act_printer_settings = settings_menu.addAction("Printer Settings")
        self.act_printer_settings.setStatusTip("Configure label printer")
        self.act_printer_settings.triggered.connect(self._on_printer_settings)
        settings_menu.addSeparator()
        self.act_inventory = settings_menu.addAction("Physical Inventory")
        self.act_inventory.setStatusTip("Reconcile physical stock by scanning spool labels")
        self.act_inventory.triggered.connect(self._on_physical_inventory)
        self.act_compress = settings_menu.addAction("Compress DB")
        self.act_compress.setStatusTip("Remove duplicate deleted entries to shrink the database")
        self.act_compress.triggered.connect(self._on_compress)
        self.act_open_data = settings_menu.addAction("Open Data Folder")
        self.act_open_data.setStatusTip("Show the database file location")
        self.act_open_data.triggered.connect(self._on_open_data_folder)

        btn_settings = QToolButton()
        btn_settings.setText("Settings")
        btn_settings.setMenu(settings_menu)
        btn_settings.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tb.addWidget(btn_settings)

        tb.addSeparator()

        # -- Quick access: Open Spools filter --
        self.act_filter_open = QAction("Open Spools", self)
        self.act_filter_open.setCheckable(True)
        self.act_filter_open.setStatusTip("Show only spools that have been opened (remaining < full weight)")
        self.act_filter_open.toggled.connect(self._apply_filters)
        tb.addAction(self.act_filter_open)

        self.act_group_view = QAction("Group by Color", self)
        self.act_group_view.setCheckable(True)
        self.act_group_view.setStatusTip("Group inventory by color and filament type")
        self.act_group_view.toggled.connect(self._on_group_toggled)
        tb.addAction(self.act_group_view)

        # -- Quick access: Search box with history dropdown --
        self._search_combo = QComboBox()
        self._search_combo.setEditable(True)
        self._search_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._search_combo.setMaximumWidth(200)
        self._search_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._search_combo.setMinimumContentsLength(15)
        self.search_box = self._search_combo.lineEdit()
        self.search_box.setPlaceholderText("Search...")
        self.search_box.setClearButtonEnabled(True)
        self._search_building = False  # True while user is typing a search
        self.search_box.textChanged.connect(self._on_search_changed)
        # Restore search history from previous session
        history = QSettings().value("search/history", [], type=list)
        if history:
            self._search_combo.addItems([str(h) for h in history])
            self._search_combo.setCurrentIndex(-1)
            self.search_box.clear()
        tb.addWidget(self._search_combo)

        # -- Quick access: Columns --
        self.act_columns = QAction("Columns", self)
        self.act_columns.setStatusTip("Choose which columns to display")
        self.act_columns.triggered.connect(self._on_columns_button)
        tb.addAction(self.act_columns)

        tb.addSeparator()

        # -- Help & About at the end --
        self.act_help = QAction("Help", self)
        self.act_help.setStatusTip("How to use Bamboo Filament Manager")
        self.act_help.triggered.connect(self._on_help)
        tb.addAction(self.act_help)

        self.act_about = QAction("About", self)
        self.act_about.setStatusTip("About Bamboo Filament Manager")
        self.act_about.triggered.connect(self._on_about)
        tb.addAction(self.act_about)

    def _build_central(self):
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(6, 6, 6, 6)

        self.splitter = splitter = QSplitter(Qt.Orientation.Vertical)

        # Main table
        self.table = QTableWidget()
        self.table.setColumnCount(len(COLUMN_LABELS))
        self.table.setHorizontalHeaderLabels(COLUMN_LABELS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_COLOR, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_TYPE, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_SKU, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_BARCODE, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_LOCATION, QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setSectionsMovable(True)
        self.table.setColumnWidth(COL_TYPE, 120)
        self.table.setColumnWidth(COL_SKU, 160)
        self.table.setColumnWidth(COL_BARCODE, 120)
        self.table.setColumnWidth(COL_LOCATION, 100)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_action_states)
        self.table.itemChanged.connect(self._on_cell_edited)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.setItemDelegateForColumn(COL_COLOR, ColorDelegate(self.table))
        self.table.installEventFilter(self)  # Catch scanner keystrokes before table
        self.installEventFilter(self)  # Also catch when table doesn't have focus

        # Column chooser — right-click header to toggle column visibility
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._on_header_context_menu)

        splitter.addWidget(self.table)

        # Summary panel
        self.summary_box = self._build_summary_panel()
        splitter.addWidget(self.summary_box)
        splitter.setSizes([480, 120])

        central_layout.addWidget(splitter)
        self.setCentralWidget(central)

    def _build_summary_panel(self) -> QGroupBox:
        grp = QGroupBox("Summary")
        layout = QHBoxLayout(grp)

        self.lbl_total_spools = QLabel("Spools: 0")
        self.lbl_total_weight = QLabel("Total remaining: 0 g")
        self.lbl_types = QLabel("")
        self.lbl_types.setWordWrap(True)
        self.lbl_types.linkActivated.connect(self._on_type_clicked)

        layout.addWidget(self.lbl_total_spools)
        layout.addWidget(QLabel("|"))
        layout.addWidget(self.lbl_total_weight)
        layout.addWidget(QLabel("|"))
        layout.addWidget(self.lbl_types, 1)
        return grp

    def _build_statusbar(self):
        self.status = QStatusBar()
        self.setStatusBar(self.status)

    # ------------------------------------------------------------------
    # Table management
    # ------------------------------------------------------------------

    def refresh_table(self):
        self._refreshing = True
        self.table.setSortingEnabled(False)
        entries = self.db.get_all()

        if self._grouped_view:
            self._populate_grouped(entries)
            self.table.setSortingEnabled(True)
            self._apply_filters()
            self._update_summary()
            self._update_action_states()
            self._refreshing = False
            return

        self.table.setRowCount(len(entries))

        for row, entry in enumerate(entries):
            inv = entry.get("__inventory__", {})
            temps = entry.get("temperatures", {})
            dtype = entry.get("detailed_filament_type") or entry.get("filament_type", "")
            color = entry.get("filament_color", "")
            color2 = entry.get("filament_color2") or ""
            color_name = entry.get("color_name", "")
            weight = entry.get("spool_weight")
            remaining = inv.get("remaining_weight_g")
            diameter = entry.get("filament_diameter")
            location = inv.get("location", "")
            scanned = (entry.get("scanned_at") or "")[:10]

            min_hotend = temps.get("min_hotend", 0)
            max_hotend = temps.get("max_hotend", 0)
            nozzle_str = f"{min_hotend}-{max_hotend}°C" if max_hotend else ""

            spool_num = entry.get("spool_number", "")
            spool_label = f"SPL-{spool_num:04d}" if spool_num else ""
            self.table.setItem(row, COL_SPOOL, self._ro_cell(spool_label))
            self.table.setItem(row, COL_COLOR, ColorItem(color, color_name, color2))
            self.table.setItem(row, COL_TYPE, self._editable_cell(dtype))
            self.table.setItem(row, COL_WEIGHT, self._editable_cell(f"{weight} g" if weight else ""))
            self.table.setItem(row, COL_REM, self._editable_cell(f"{remaining} g" if remaining is not None else ""))
            self.table.setItem(row, COL_DIAM, self._editable_cell(f"{diameter}" if diameter else ""))
            self.table.setItem(row, COL_NOZZLE, self._editable_cell(nozzle_str))
            self.table.setItem(row, COL_SKU, self._editable_cell(entry.get("sku", "")))
            self.table.setItem(row, COL_BARCODE, self._editable_cell(entry.get("barcode", "")))
            self.table.setItem(row, COL_STORE_ID, self._editable_cell(entry.get("store_variant_id", "")))
            self.table.setItem(row, COL_LOCATION, self._editable_cell(location))
            self.table.setItem(row, COL_SCANNED, self._ro_cell(scanned))

            # Extended columns
            self.table.setItem(row, COL_UID, self._ro_cell(entry.get("uid", "")))
            self.table.setItem(row, COL_MAT_ID, self._editable_cell(entry.get("material_id", "")))
            self.table.setItem(row, COL_VAR_ID, self._editable_cell(entry.get("variant_id", "")))
            rem_len = inv.get("remaining_length_m")
            self.table.setItem(row, COL_REM_LEN, self._editable_cell(f"{rem_len} m" if rem_len else ""))
            fil_len = entry.get("filament_length")
            self.table.setItem(row, COL_FIL_LEN, self._editable_cell(f"{fil_len} m" if fil_len else ""))
            spool_w = entry.get("spool_width")
            self.table.setItem(row, COL_SPOOL_W, self._editable_cell(f"{spool_w} mm" if spool_w else ""))
            noz_diam = entry.get("nozzle_diameter")
            self.table.setItem(row, COL_NOZ_DIAM, self._editable_cell(f"{noz_diam} mm" if noz_diam else ""))
            tare = entry.get("tare_weight")
            self.table.setItem(row, COL_TARE, self._editable_cell(f"{tare} g" if tare else ""))
            bed_temp = temps.get("bed_temp")
            self.table.setItem(row, COL_BED_TEMP, self._editable_cell(f"{bed_temp}°C" if bed_temp else ""))
            dry_temp = temps.get("drying_temp")
            self.table.setItem(row, COL_DRY_TEMP, self._editable_cell(f"{dry_temp}°C" if dry_temp else ""))
            dry_time = temps.get("drying_time")
            self.table.setItem(row, COL_DRY_TIME, self._editable_cell(f"{dry_time} h" if dry_time else ""))
            prod_date = (entry.get("production_date") or "")[:10]
            self.table.setItem(row, COL_PROD_DATE, self._ro_cell(prod_date))
            self.table.setItem(row, COL_NOTES, self._editable_cell(inv.get("notes", "")))
            self.table.setItem(row, COL_TRAY_UID, self._ro_cell(entry.get("tray_uid", "")))
            self.table.setItem(row, COL_XCAM, self._ro_cell(str(entry.get("x_cam_info", ""))))
            self.table.setItem(row, COL_COLOR2, self._ro_cell(entry.get("filament_color2", "")))
            self.table.setItem(row, COL_COLOR_CT, self._ro_cell(str(entry.get("filament_color_count", ""))))
            self.table.setItem(row, COL_UID2, self._ro_cell(entry.get("uid2", "")))
            present = entry.get("physically_present")
            self.table.setItem(row, COL_PRESENT, self._ro_cell(
                "Yes" if present else ("No" if present is False else "")))

            # Store entry id in column 0 user data
            self.table.item(row, COL_SPOOL).setData(Qt.ItemDataRole.UserRole, entry["id"])

        self.table.setSortingEnabled(True)
        self._apply_filters()
        self._update_summary()
        self._update_action_states()
        self._refreshing = False

    def _on_group_toggled(self, checked: bool):
        self._grouped_view = checked
        if checked:
            self._saved_column_visibility = {
                col: not self.table.isColumnHidden(col)
                for col in range(self.table.columnCount())
            }
            self.table.setHorizontalHeaderItem(
                COL_SPOOL, QTableWidgetItem("Count"))
        else:
            self.table.setHorizontalHeaderItem(
                COL_SPOOL, QTableWidgetItem(COLUMN_LABELS[COL_SPOOL]))
            for col, visible in self._saved_column_visibility.items():
                self.table.setColumnHidden(col, not visible)
            self._saved_column_visibility = {}
        self.refresh_table()

    def _populate_grouped(self, entries):
        from collections import defaultdict

        groups = defaultdict(list)
        for entry in entries:
            color_name = (entry.get("color_name") or "").strip()
            ftype = (entry.get("detailed_filament_type")
                     or entry.get("filament_type", "")).strip()
            key = (color_name.lower(), ftype.lower())
            groups[key].append(entry)

        # Show only relevant columns
        GROUPED_COLS = {COL_SPOOL, COL_COLOR, COL_TYPE, COL_WEIGHT, COL_REM,
                        COL_LOCATION}
        for col in range(self.table.columnCount()):
            self.table.setColumnHidden(col, col not in GROUPED_COLS)

        self.table.setRowCount(len(groups))

        for row, ((_ck, _tk), group) in enumerate(
            sorted(groups.items(), key=lambda x: x[0])
        ):
            rep = group[0]
            count = len(group)
            color_hex = rep.get("filament_color", "")
            color_name = rep.get("color_name", "")
            color2 = rep.get("filament_color2") or ""
            dtype = (rep.get("detailed_filament_type")
                     or rep.get("filament_type", ""))

            total_weight = sum(e.get("spool_weight") or 0 for e in group)
            total_remaining = sum(
                (e.get("__inventory__", {}).get("remaining_weight_g") or 0)
                for e in group
            )
            locations = sorted(set(
                e.get("__inventory__", {}).get("location", "")
                for e in group
            ) - {""})

            self.table.setItem(row, COL_SPOOL, self._ro_cell(f"x{count}"))
            self.table.setItem(row, COL_COLOR,
                               ColorItem(color_hex, color_name, color2))
            item_color = self.table.item(row, COL_COLOR)
            item_color.setFlags(
                Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, COL_TYPE, self._ro_cell(dtype))
            self.table.setItem(row, COL_WEIGHT,
                               self._ro_cell(f"{total_weight} g"
                                             if total_weight else ""))
            self.table.setItem(row, COL_REM,
                               self._ro_cell(f"{total_remaining} g"
                                             if total_remaining else ""))
            self.table.setItem(row, COL_LOCATION,
                               self._ro_cell(", ".join(locations)))

            # No entry id for grouped rows
            self.table.item(row, COL_SPOOL).setData(
                Qt.ItemDataRole.UserRole, None)

    def _apply_filters(self):
        """Show/hide rows based on active filter toggles and search text."""
        show_open_only = self.act_filter_open.isChecked()
        search = self.search_box.text().strip().lower()
        for row in range(self.table.rowCount()):
            hidden = False

            spool_item = self.table.item(row, COL_SPOOL)
            entry_id = spool_item.data(Qt.ItemDataRole.UserRole) if spool_item else None
            entry = self.db.get_by_id(entry_id) if entry_id else None

            # Open spool filter (skip in grouped mode)
            if show_open_only and not hidden and not self._grouped_view:
                if entry:
                    inv = entry.get("__inventory__", {})
                    remaining = inv.get("remaining_weight_g")
                    full_weight = entry.get("spool_weight")
                    is_open = (remaining is not None and full_weight
                               and remaining < full_weight)
                    if not is_open:
                        hidden = True
                else:
                    hidden = True

            # Search filter — match against all cell text and key entry fields
            if search and not hidden:
                # Check visible cell text
                matched = False
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item and search in item.text().lower():
                        matched = True
                        break
                # Also check entry fields not shown in visible columns
                if not matched and entry:
                    for val in entry.values():
                        if isinstance(val, str) and search in val.lower():
                            matched = True
                            break
                        if isinstance(val, dict):
                            for v in val.values():
                                if isinstance(v, str) and search in v.lower():
                                    matched = True
                                    break
                            if matched:
                                break
                if not matched:
                    hidden = True

            self.table.setRowHidden(row, hidden)

    def _editable_cell(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(str(text))
        item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable)
        return item

    def _ro_cell(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(str(text))
        item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        return item

    def _on_cell_edited(self, item: QTableWidgetItem):
        """Save inline edits back to the database."""
        if self._refreshing or self._grouped_view:
            return
        row = item.row()
        col = item.column()
        spool_item = self.table.item(row, COL_SPOOL)
        if not spool_item:
            return
        entry_id = spool_item.data(Qt.ItemDataRole.UserRole)
        if not entry_id:
            return

        text = item.text().strip()

        # Parse the value and map to the right database field
        def parse_num(s):
            """Strip units and parse as number."""
            s = s.replace("°C", "").replace("g", "").replace("mm", "").strip()
            if not s:
                return 0
            try:
                return float(s) if "." in s else int(s)
            except ValueError:
                return 0

        fields = {}
        if col == COL_COLOR:
            fields["color_name"] = text
        elif col == COL_TYPE:
            fields["detailed_filament_type"] = text
        elif col == COL_WEIGHT:
            fields["spool_weight"] = parse_num(text)
        elif col == COL_REM:
            scale_weight = parse_num(text)
            entry = self.db.get_by_id(entry_id)
            tare = (entry.get("tare_weight") or 250) if entry else 250
            remaining = max(0, scale_weight - tare)
            inv = {"remaining_weight_g": remaining}
            # Also estimate remaining length if we know the full spool specs
            if entry:
                filament_weight = entry.get("spool_weight") or 0
                filament_length = entry.get("filament_length") or 0
                if filament_weight > 0 and filament_length > 0:
                    inv["remaining_length_m"] = round(filament_length * (remaining / filament_weight))
            fields["__inventory__"] = inv
        elif col == COL_DIAM:
            fields["filament_diameter"] = parse_num(text)
        elif col == COL_NOZZLE:
            # Parse "190-230°C" format
            parts = text.replace("°C", "").split("-")
            if len(parts) == 2:
                fields["temperatures"] = {
                    "min_hotend": parse_num(parts[0]),
                    "max_hotend": parse_num(parts[1]),
                }
            elif parts[0].strip():
                fields["temperatures"] = {"max_hotend": parse_num(parts[0])}
        elif col == COL_SKU:
            fields["sku"] = text
        elif col == COL_BARCODE:
            fields["barcode"] = text
        elif col == COL_STORE_ID:
            fields["store_variant_id"] = text
        elif col == COL_LOCATION:
            fields["__inventory__"] = {"location": text}
        elif col == COL_MAT_ID:
            fields["material_id"] = text
        elif col == COL_VAR_ID:
            fields["variant_id"] = text
        elif col == COL_REM_LEN:
            fields["__inventory__"] = {"remaining_length_m": parse_num(text)}
        elif col == COL_FIL_LEN:
            fields["filament_length"] = parse_num(text)
        elif col == COL_SPOOL_W:
            fields["spool_width"] = parse_num(text)
        elif col == COL_NOZ_DIAM:
            fields["nozzle_diameter"] = parse_num(text)
        elif col == COL_TARE:
            fields["tare_weight"] = parse_num(text)
        elif col == COL_BED_TEMP:
            fields["temperatures"] = {"bed_temp": parse_num(text)}
        elif col == COL_DRY_TEMP:
            fields["temperatures"] = {"drying_temp": parse_num(text)}
        elif col == COL_DRY_TIME:
            fields["temperatures"] = {"drying_time": parse_num(text)}
        elif col == COL_NOTES:
            fields["__inventory__"] = {"notes": text}
        else:
            return

        if fields:
            self.db.update(entry_id, fields)
            self._update_summary()

            # Re-format cells with unit suffixes
            self._refreshing = True
            if col == COL_WEIGHT:
                val = parse_num(text)
                if val:
                    item.setText(f"{val} g")
            elif col == COL_REM:
                # Show the tare-subtracted value
                item.setText(f"{remaining} g" if remaining else "")
            elif col == COL_NOZZLE:
                parts = text.replace("°C", "").split("-")
                if len(parts) == 2:
                    item.setText(f"{parts[0].strip()}-{parts[1].strip()}°C")
                elif parts[0].strip():
                    item.setText(f"{parts[0].strip()}°C")
            elif col == COL_REM_LEN:
                val = parse_num(text)
                if val:
                    item.setText(f"{val} m")
            elif col == COL_FIL_LEN:
                val = parse_num(text)
                if val:
                    item.setText(f"{val} m")
            elif col in (COL_SPOOL_W, COL_NOZ_DIAM):
                val = parse_num(text)
                if val:
                    item.setText(f"{val} mm")
            elif col == COL_TARE:
                val = parse_num(text)
                if val:
                    item.setText(f"{val} g")
            elif col in (COL_BED_TEMP, COL_DRY_TEMP):
                val = parse_num(text)
                if val:
                    item.setText(f"{val}°C")
            elif col == COL_DRY_TIME:
                val = parse_num(text)
                if val:
                    item.setText(f"{val} h")
            self._refreshing = False

    def _on_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return
        row = item.row()
        spool_item = self.table.item(row, COL_SPOOL)
        if not spool_item:
            return
        entry_id = spool_item.data(Qt.ItemDataRole.UserRole)
        if not entry_id:
            return

        entry = self.db.get_by_id(entry_id)
        dtype = entry.get("detailed_filament_type") or entry.get("filament_type", "this filament") if entry else "this filament"

        col = self.table.columnAt(pos.x())

        menu = QMenu(self)
        # Spool ID label printing
        print_label_action = menu.addAction("Print Label...")
        menu.addSeparator()
        # Color-specific option
        color_name_action = None
        if col == COL_COLOR:
            current_name = entry.get("color_name", "") if entry else ""
            color_name_action = menu.addAction("Set Color Name...")
            menu.addSeparator()
        edit_action = menu.addAction("Edit Details...")
        weigh_action = menu.addAction("Weigh Spool...")
        # Reorder link
        reorder_action = None
        store_url = _store_url(entry) if entry else None
        if store_url:
            reorder_action = menu.addAction("Reorder from Bambu Lab...")
        menu.addSeparator()
        delete_action = menu.addAction(f"Delete '{dtype}'")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == print_label_action:
            self._print_spool_label(entry)
        elif color_name_action and action == color_name_action:
            current_name = entry.get("color_name", "") if entry else ""
            name, ok = QInputDialog.getText(
                self, "Color Name",
                "Enter a color name (e.g. Charcoal, Yellow):",
                text=current_name,
            )
            if ok:
                self.db.update(entry_id, {"color_name": name.strip()})
                self.refresh_table()
        elif reorder_action and action == reorder_action:
            webbrowser.open(store_url)
        elif action == edit_action:
            self._on_edit()
        elif action == weigh_action:
            self._on_weigh()
        elif action == delete_action:
            self.db.delete(entry_id)
            self.refresh_table()
            self.status.showMessage("Filament deleted.", 3000)

    def _print_spool_label(self, entry: dict):
        from printer_manager import print_label
        try:
            spool_num = entry.get("spool_number", 0)
            spool_id = f"SPL-{spool_num:04d}" if spool_num else "label"
            path = print_label(entry)
            self.status.showMessage(f"Printed label for {spool_id}.", 3000)
        except Exception as exc:
            QMessageBox.warning(self, "Label Error", f"Failed to print label:\n{exc}")

    def _selected_id(self) -> str | None:
        rows = self.table.selectedItems()
        if not rows:
            return None
        row = self.table.currentRow()
        spool_item = self.table.item(row, COL_SPOOL)
        return spool_item.data(Qt.ItemDataRole.UserRole) if spool_item else None

    def _update_action_states(self):
        if self._grouped_view:
            self.act_edit.setEnabled(False)
            self.act_delete.setEnabled(False)
            self.act_weigh.setEnabled(False)
            return
        has_selection = self._selected_id() is not None
        self.act_edit.setEnabled(has_selection)
        self.act_delete.setEnabled(has_selection)
        self.act_weigh.setEnabled(has_selection)

    def _update_summary(self):
        entries = self.db.get_all()
        self.lbl_total_spools.setText(f"Spools: {len(entries)}")
        self.lbl_total_weight.setText(f"Total remaining: {int(self.db.total_remaining_weight())} g")

        counts = self.db.summary_by_type()
        parts = []
        for t, n in sorted(counts.items()):
            parts.append(f'<a href="{t}" style="text-decoration:none">{t}: {n}</a>')
        self.lbl_types.setText("  |  ".join(parts))

    def _on_type_clicked(self, filament_type: str):
        """Filter the table to show only the clicked filament type."""
        current = self.search_box.text().strip()
        if current == filament_type:
            # Clicking the same type again clears the filter
            self.search_box.clear()
        else:
            self.search_box.setText(filament_type)

    def _on_search_changed(self, text: str):
        """Update search history live as the user types, then apply filters."""
        combo = self._search_combo
        stripped = text.strip()
        if not stripped:
            # User cleared the box — finalize the current search
            self._search_building = False
        elif self._search_building:
            # Still typing — replace the top entry with the longer string
            if combo.count() > 0:
                combo.setItemText(0, stripped)
        else:
            # Starting a new search — insert a new entry at the top
            self._search_building = True
            # Remove duplicate if it already exists
            idx = combo.findText(stripped)
            if idx >= 0:
                combo.removeItem(idx)
            combo.insertItem(0, stripped)
            # Trim to 10 entries
            while combo.count() > 10:
                combo.removeItem(combo.count() - 1)
        self._save_search_history()
        if hasattr(self, "table"):
            self._apply_filters()

    def _save_search_history(self):
        """Persist the search dropdown entries to QSettings."""
        combo = self._search_combo
        items = [combo.itemText(i) for i in range(combo.count()) if combo.itemText(i).strip()]
        QSettings().setValue("search/history", items)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_add_manual(self):
        empty = {
            "filament_type": "",
            "detailed_filament_type": "",
            "filament_color": "#FFFFFFFF",
            "spool_weight": 1000,
            "filament_length": 0,
            "filament_diameter": 1.75,
            "nozzle_diameter": 0.4,
            "temperatures": {},
            "__inventory__": {},
        }
        dlg = EditDialog(empty, self, adding=True, db=self.db)
        if dlg.exec() == EditDialog.DialogCode.Accepted:
            fields = dlg.result_fields()
            self.db.add(fields)
            self.refresh_table()
            dtype = fields.get("detailed_filament_type") or fields.get("filament_type") or "entry"
            self.status.showMessage(f"Added {dtype}", 5000)

    def _on_bulk_scan(self):
        dlg = BulkScanDialog(self.db, self)
        dlg.spool_saved.connect(self.refresh_table)
        dlg.exec()
        if dlg.added_count or dlg._updated_count:
            self.refresh_table()
            msg = f"Bulk scan: {dlg.added_count} added"
            if dlg._updated_count:
                msg += f", {dlg._updated_count} updated"
            self.status.showMessage(msg, 5000)

    def _on_scan(self):
        dlg = ScanDialog(self, db=self.db)
        if dlg.exec() == ScanDialog.DialogCode.Accepted and dlg.tag_data:
            uid = dlg.tag_data.get("uid", "")

            # 1) Check for exact UID match or tray_uid match (re-scan of known spool)
            #    Each spool has two RFID tags with different chip UIDs but the
            #    same tray_uid, so we must check both.
            existing = self.db.get_by_uid(uid) if uid else None
            if not existing:
                tray_uid = dlg.tag_data.get("tray_uid", "")
                if tray_uid:
                    existing = self.db.get_by_tray_uid(tray_uid)
                    if existing and uid:
                        # Store the second tag's UID on the entry
                        self.db.update(existing["id"], {"uid2": uid})
            if existing:
                if dlg.auto_closed:
                    # Dialog auto-closed — undelete if needed, then select the row
                    was_deleted = existing.get("deleted", False)
                    if was_deleted:
                        self.db.undelete(existing["id"])
                    existing["physically_present"] = True
                    self.db.update(existing["id"], {"physically_present": True})
                    dtype = existing.get("detailed_filament_type") or existing.get("filament_type", "Unknown")
                    color = existing.get("color_name", "")
                    label = f"{dtype} — {color}" if color else dtype
                    self.refresh_table()
                    self._select_entry(existing["id"])
                    action = "Restored" if was_deleted else "Found existing"
                    self.status.showMessage(f"{action} spool: {label}", 3000)
                    return
                dtype = existing.get("detailed_filament_type") or existing.get("filament_type", "Unknown")
                was_deleted = existing.get("deleted", False)
                msg = f"This spool (UID: {uid}) is already in the inventory as '{dtype}'."
                if was_deleted:
                    msg += "\n(It was previously deleted.)"
                msg += "\n\nDo you want to update it with the new scan data?"
                reply = QMessageBox.question(
                    self,
                    "Duplicate Spool",
                    msg,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.db.update(existing["id"], dlg.tag_data)
                    if was_deleted:
                        self.db.undelete(existing["id"])
                    self.refresh_table()
                    action = "restored and updated" if was_deleted else "updated"
                    self.status.showMessage(f"Filament {action} from re-scan.", 3000)
                else:
                    self.status.showMessage(f"Selected existing entry: {dtype}", 3000)
                self._select_entry(existing["id"])
                return

            # 2) Check for a Product Code entry without RFID data that matches
            #    (same material_id, no uid yet)
            candidate = self._find_unlinked_product_entry(dlg.tag_data)
            if candidate:
                spool_num = candidate.get("spool_number", 0)
                spool_id = f"SPL-{spool_num:04d}" if spool_num else "entry"
                dtype = candidate.get("detailed_filament_type") or candidate.get("filament_type", "Unknown")
                reply = QMessageBox.question(
                    self,
                    "Link to Existing Entry",
                    f"Found an existing entry ({spool_id}: {dtype}) that matches "
                    f"this spool but has no RFID data.\n\n"
                    f"Link this RFID tag to {spool_id}?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.db.update(candidate["id"], dlg.tag_data)
                    self.refresh_table()
                    self.status.showMessage(f"RFID data linked to {spool_id}.", 3000)
                self._select_entry(candidate["id"])
                return

            # 3) No match — add as new entry
            entry = self.db.add(dlg.tag_data)
            self.refresh_table()
            self._select_entry(entry["id"])
            self.status.showMessage("Filament added from scan.", 3000)

    def _find_unlinked_product_entry(self, tag_data: dict) -> dict | None:
        """Find a Product Code entry with no UID that matches the scanned tag's material."""
        material_id = tag_data.get("material_id", "")
        if not material_id:
            return None
        for entry in self.db.get_all():
            if entry.get("uid"):
                continue  # already has RFID data
            if entry.get("material_id") == material_id:
                return entry
        return None

    def _on_import(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Tag Dump",
            "",
            "Tag dumps (*.bin *.json *.nfc);;All files (*)",
        )
        added = 0
        skipped = 0
        for path in paths:
            try:
                tag = load_file(path)
                tag_dict = tag.to_dict()
                uid = tag_dict.get("uid", "")
                if uid and self.db.get_by_uid(uid):
                    skipped += 1
                    continue
                self.db.add(tag_dict)
                added += 1
            except Exception as exc:
                QMessageBox.warning(self, "Import Error", f"{path}:\n{exc}")

        if added or skipped:
            self.refresh_table()
            msg = f"{added} filament(s) imported."
            if skipped:
                msg += f" {skipped} duplicate(s) skipped."
            self.status.showMessage(msg, 5000)

    def _on_sku(self):
        dlg = SkuDialog(db=self.db, parent=self)
        if dlg.exec() == SkuDialog.DialogCode.Accepted and dlg.tag_data:
            entry = self.db.add(dlg.tag_data)
            self.refresh_table()
            # Open edit dialog so the user can fill in missing fields
            edit_dlg = EditDialog(entry, self, db=self.db)
            if edit_dlg.exec() == EditDialog.DialogCode.Accepted:
                self.db.update(entry["id"], edit_dlg.result_fields())
                self.refresh_table()
            self.status.showMessage("Filament added from SKU.", 3000)

    def _on_edit(self):
        entry_id = self._selected_id()
        if not entry_id:
            return
        entry = self.db.get_by_id(entry_id)
        if not entry:
            return

        dlg = EditDialog(entry, self, db=self.db)
        if dlg.exec() == EditDialog.DialogCode.Accepted:
            self.db.update(entry_id, dlg.result_fields())
            self.refresh_table()
            self.status.showMessage("Filament updated.", 3000)

    def _on_weigh(self):
        entry_id = self._selected_id()
        if not entry_id:
            return
        entry = self.db.get_by_id(entry_id)
        if not entry:
            return

        tare = entry.get("tare_weight") or 250
        filament_weight = entry.get("spool_weight") or 0
        filament_length = entry.get("filament_length") or 0
        dtype = entry.get("detailed_filament_type") or entry.get("filament_type", "filament")
        color_name = entry.get("color_name") or (entry.get("filament_color") or "")[:7]

        scale_weight, ok = QInputDialog.getInt(
            self,
            "Weigh Spool",
            f"Place '{dtype}' ({color_name}) on the scale.\n"
            f"Empty spool weight: {tare} g\n\n"
            "Enter scale reading (grams):",
            value=filament_weight + tare,
            min=0,
            max=20000,
        )
        if not ok:
            return

        remaining_weight = max(0, scale_weight - tare)

        remaining_length = 0
        if filament_weight > 0 and filament_length > 0:
            remaining_length = round(filament_length * (remaining_weight / filament_weight))

        self.db.update(entry_id, {
            "__inventory__": {
                "remaining_weight_g": remaining_weight,
                "remaining_length_m": remaining_length,
            },
        })
        self.refresh_table()

        msg = f"Remaining: {remaining_weight} g"
        if remaining_length:
            msg += f" / {remaining_length} m"
        self.status.showMessage(msg, 5000)

    # ------------------------------------------------------------------
    # Window geometry persistence
    # ------------------------------------------------------------------

    def _restore_geometry(self):
        settings = QSettings()
        geometry = settings.value("mainwindow/geometry")
        state = settings.value("mainwindow/state")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)
        header_state = settings.value("mainwindow/header_state")
        header_cols = settings.value("mainwindow/header_col_count", 0, type=int)
        if header_state and header_cols == self.table.columnCount():
            self.table.horizontalHeader().restoreState(header_state)
        else:
            # First run or column count changed — apply default hidden columns
            for col in _DEFAULT_HIDDEN:
                self.table.setColumnHidden(col, True)
        # Re-assert after restoreState (which overwrites it from the old saved value)
        self.table.horizontalHeader().setSectionsMovable(True)
        splitter_state = settings.value("mainwindow/splitter_state")
        if splitter_state:
            self.splitter.restoreState(splitter_state)

    # ------------------------------------------------------------------
    # Column chooser
    # ------------------------------------------------------------------

    def _show_column_menu(self, pos: QPoint):
        menu = QMenu(self)
        header = self.table.horizontalHeader()
        for col in range(self.table.columnCount()):
            action = menu.addAction(COLUMN_LABELS[col])
            action.setCheckable(True)
            action.setChecked(not header.isSectionHidden(col))
            action.setData(col)
            action.toggled.connect(lambda checked, c=col: self.table.setColumnHidden(c, not checked))
        menu.exec(pos)

    def _on_header_context_menu(self, pos):
        self._show_column_menu(self.table.horizontalHeader().mapToGlobal(pos))

    def _on_columns_button(self):
        # Show the menu below the Columns toolbar button
        tb = self.findChild(QToolBar, "MainToolBar")
        if tb:
            btn = tb.widgetForAction(self.act_columns)
            if btn:
                self._show_column_menu(btn.mapToGlobal(QPoint(0, btn.height())))
                return
        self._show_column_menu(self.mapToGlobal(QPoint(100, 50)))

    def closeEvent(self, event):
        settings = QSettings()
        settings.setValue("mainwindow/geometry", self.saveGeometry())
        settings.setValue("mainwindow/state", self.saveState())
        settings.setValue("mainwindow/header_state", self.table.horizontalHeader().saveState())
        settings.setValue("mainwindow/header_col_count", self.table.columnCount())
        settings.setValue("mainwindow/splitter_state", self.splitter.saveState())
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Barcode scanner input
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        """Intercept keystrokes to capture barcode scanner input."""
        if event.type() == QEvent.Type.KeyPress and (obj is self.table or obj is self):
            # Don't intercept anything while a cell is being edited
            if self.table.state() == QAbstractItemView.State.EditingState:
                return False
            # Don't intercept if a child widget (search box, etc.) has focus
            focus = self.focusWidget()
            if focus and focus is not self.table and focus is not self:
                return False

            key = event.key()

            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._scan_buffer:
                    self._handle_scan_input(self._scan_buffer.strip())
                    self._scan_buffer = ""
                    return True  # consume
            elif key == Qt.Key.Key_Escape:
                self._scan_buffer = ""
            elif event.text() and event.text().isprintable():
                self._scan_buffer += event.text()
                return True  # consume so table doesn't react

        return super().eventFilter(obj, event)

    def _handle_scan_input(self, text: str):
        """Process scanned barcode text — look up spool and select it."""
        import re
        # Match SPL-0001 format (from our labels)
        m = re.match(r"SPL-(\d+)", text, re.IGNORECASE)
        if m:
            spool_num = int(m.group(1))
            entry = self.db.get_by_spool_number(spool_num)
            if not entry:
                # Check deleted entries
                for e in self.db.get_all_including_deleted():
                    if e.get("deleted") and e.get("spool_number") == spool_num:
                        entry = e
                        break
                if entry:
                    dtype = entry.get("detailed_filament_type") or entry.get("filament_type", "Unknown")
                    color = entry.get("color_name", "")
                    label = f"{dtype} — {color}" if color else dtype
                    reply = QMessageBox.question(
                        self, "Restore Deleted Spool?",
                        f"SPL-{spool_num:04d} ({label}) was previously deleted.\n\n"
                        "Restore it to the inventory?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        self.db.undelete(entry["id"])
                        self.db.update(entry["id"], {"physically_present": True})
                        self.refresh_table()
                        self._select_entry(entry["id"])
                        self.status.showMessage(f"Restored SPL-{spool_num:04d}: {label}", 3000)
                    return
            if entry:
                self.db.update(entry["id"], {"physically_present": True})
                self._select_entry(entry["id"])
                spool_id = f"SPL-{spool_num:04d}"
                dtype = entry.get("detailed_filament_type") or entry.get("filament_type", "")
                color = entry.get("color_name", "")
                label = f"{dtype} — {color}" if color else dtype
                self.status.showMessage(f"Found {spool_id}: {label}", 3000)
            else:
                QMessageBox.warning(
                    self, "Spool Not Found",
                    f"SPL-{spool_num:04d} was not found in the inventory.",
                )
            return

        # Not a spool label — might be a product barcode, try SKU lookup
        self.status.showMessage(f"Scanned: {text} (not a spool label)", 3000)

    def _select_entry(self, entry_id: str):
        """Select and scroll to the table row matching entry_id."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_SPOOL)
            if item and item.data(Qt.ItemDataRole.UserRole) == entry_id:
                self.table.selectRow(row)
                self.table.scrollToItem(item)
                return

    def _on_delete(self):
        entry_id = self._selected_id()
        if not entry_id:
            return
        entry = self.db.get_by_id(entry_id)
        dtype = entry.get("detailed_filament_type") or entry.get("filament_type", "this filament")
        color = entry.get("color_name", "")
        label = f"'{dtype} — {color}'" if color else f"'{dtype}'"

        reply = QMessageBox.question(
            self,
            "Delete Filament",
            f"Delete {label} from the inventory?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete(entry_id)
            self.refresh_table()
            self.status.showMessage("Filament deleted.", 3000)

    def _on_remove_by_scan(self):
        dlg = ScanDialog(self, mode="remove", db=self.db)
        if dlg.exec() != ScanDialog.DialogCode.Accepted or not dlg.tag_data:
            return
        uid = dlg.tag_data.get("uid", "")
        if not uid:
            QMessageBox.warning(self, "Remove by Scan", "No UID found on scanned tag.")
            return
        existing = self.db.get_by_uid(uid)
        if not existing:
            QMessageBox.information(
                self, "Remove by Scan",
                f"No spool with UID {uid} found in the inventory.",
            )
            return
        if existing.get("deleted"):
            QMessageBox.information(
                self, "Remove by Scan",
                f"This spool is already deleted.",
            )
            return
        dtype = existing.get("detailed_filament_type") or existing.get("filament_type", "Unknown")
        reply = QMessageBox.question(
            self,
            "Remove by Scan",
            f"Delete '{dtype}' (UID: {uid}) from the inventory?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete(existing["id"])
            self.refresh_table()
            self.status.showMessage(f"Spool '{dtype}' removed.", 3000)

    def _on_delete_by_spool_id(self):
        text, ok = QInputDialog.getText(
            self, "Delete by Spool ID",
            "Scan or type the Spool ID (e.g. SPL-0042):",
        )
        if not ok or not text.strip():
            return
        text = text.strip()
        # Parse SPL-XXXX format
        import re
        m = re.match(r"SPL-(\d+)", text, re.IGNORECASE)
        if not m:
            QMessageBox.warning(self, "Delete by Spool ID", f"Invalid Spool ID format: {text}")
            return
        spool_num = int(m.group(1))
        # Find entry by spool_number
        entry = None
        for e in self.db.get_all():
            if e.get("spool_number") == spool_num:
                entry = e
                break
        if not entry:
            QMessageBox.information(
                self, "Delete by Spool ID",
                f"No spool with ID SPL-{spool_num:04d} found in the inventory.",
            )
            return
        dtype = entry.get("detailed_filament_type") or entry.get("filament_type", "Unknown")
        color = entry.get("color_name", "")
        label = f"'{dtype} — {color}'" if color else f"'{dtype}'"
        reply = QMessageBox.question(
            self,
            "Delete by Spool ID",
            f"Delete {label} (SPL-{spool_num:04d}) from the inventory?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete(entry["id"])
            self.refresh_table()
            self.status.showMessage(f"Spool SPL-{spool_num:04d} removed.", 3000)

    def _on_physical_inventory(self):
        dlg = InventoryDialog(self.db, self)
        dlg.exec()
        self.refresh_table()

    def _on_compress(self):
        removed = self.db.compress()
        if removed:
            self.refresh_table()
            QMessageBox.information(
                self, "Compress Database",
                f"Removed {removed} duplicate deleted entr{'y' if removed == 1 else 'ies'}.",
            )
        else:
            QMessageBox.information(
                self, "Compress Database",
                "No duplicate deleted entries found.",
            )

    # Flat CSV column order — nested dicts are expanded with dot notation.
    _CSV_COLUMNS = [
        "id", "spool_number", "uid", "filament_type", "detailed_filament_type",
        "filament_color", "filament_color2", "filament_color_count",
        "color_name", "spool_weight", "filament_length", "filament_diameter",
        "spool_width", "material_id", "variant_id", "nozzle_diameter",
        "temperatures.min_hotend", "temperatures.max_hotend",
        "temperatures.bed_temp", "temperatures.bed_temp_type",
        "temperatures.drying_time", "temperatures.drying_temp",
        "x_cam_info", "tray_uid", "production_date",
        "sku", "barcode", "store_variant_id", "tare_weight",
        "remaining_weight_g", "remaining_length_m", "location", "notes",
        "scanned_at",
    ]

    # Columns whose values should be forced to text in Excel (hex strings,
    # UUIDs, barcodes, etc. that Excel would otherwise convert to numbers).
    _TEXT_COLUMNS = {"id", "uid", "tray_uid", "x_cam_info", "barcode"}

    def _flatten_entry(self, entry: dict) -> dict:
        """Flatten an entry's nested dicts into dot-notation keys for CSV."""
        flat = {}
        inv = entry.get("__inventory__", {})
        temps = entry.get("temperatures", {})
        for col in self._CSV_COLUMNS:
            if col.startswith("temperatures."):
                val = temps.get(col.split(".", 1)[1], "")
            elif col in ("remaining_weight_g", "remaining_length_m", "location", "notes"):
                val = inv.get(col, "")
            else:
                val = entry.get(col, "")
            # Force text in Excel by prefixing with a tab character
            if col in self._TEXT_COLUMNS and val:
                val = f"\t{val}"
            flat[col] = val
        return flat

    def _on_export_csv(self):
        import csv
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "filaments.csv", "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return
        entries = self.db.get_all()
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._CSV_COLUMNS)
                writer.writeheader()
                for entry in entries:
                    writer.writerow(self._flatten_entry(entry))
            self.status.showMessage(f"Exported {len(entries)} entries to {path}", 3000)
        except OSError as e:
            QMessageBox.warning(self, "Export CSV", f"Failed to write file:\n{e}")

    def _on_import_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import CSV", "", "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return
        try:
            added, updated = self.db.import_csv(path)
            self.refresh_table()
            parts = []
            if added:
                parts.append(f"{added} added")
            if updated:
                parts.append(f"{updated} updated")
            msg = ", ".join(parts) if parts else "No changes"
            self.status.showMessage(f"CSV import: {msg}.", 3000)
            QMessageBox.information(self, "Import CSV", f"Import complete: {msg}.")
        except Exception as e:
            QMessageBox.warning(self, "Import CSV", f"Failed to import:\n{e}")

    def _on_export_db(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Database", "filaments-backup.json",
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            self.db.export_db(path)
            total = len(self.db.get_all_including_deleted())
            self.status.showMessage(f"Exported {total} entries to {path}", 3000)
        except OSError as e:
            QMessageBox.warning(self, "Export Database", f"Failed to write file:\n{e}")

    def _on_import_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Database", "",
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            added, updated = self.db.import_db(path)
            self.refresh_table()
            parts = []
            if added:
                parts.append(f"{added} added")
            if updated:
                parts.append(f"{updated} updated")
            msg = ", ".join(parts) if parts else "No changes"
            self.status.showMessage(f"Database import: {msg}.", 3000)
            QMessageBox.information(self, "Import Database", f"Import complete: {msg}.")
        except Exception as e:
            QMessageBox.warning(self, "Import Database", f"Failed to import:\n{e}")

    def _on_open_data_folder(self):
        import os
        os.startfile(str(self.db.path.parent))

    def _on_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()

    def _on_printer_settings(self):
        dlg = PrinterSettingsDialog(self)
        dlg.exec()

    def _on_help(self):
        from PyQt6.QtWidgets import QDialog, QTextBrowser
        dlg = QDialog(self)
        dlg.setWindowTitle("Bamboo Filament Manager — Help")
        dlg.resize(620, 520)
        layout = QVBoxLayout(dlg)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(
            "<h2>Getting Started</h2>"
            "<ol>"
            "<li>Connect your <b>Proxmark3</b> to your PC via USB.</li>"
            "<li>Check Device Manager for the COM port (e.g. COM8).</li>"
            "<li>Click <b>Scan Tag</b> in the toolbar.</li>"
            "<li>Go to <b>Settings</b> to set your COM port and path to <code>proxmark3.exe</code> "
            "if it wasn't auto-detected.</li>"
            "<li>Click <b>Start Scan</b>, then hold a filament spool's RFID tag near "
            "the Proxmark3's <b>HF antenna</b> (the small inner coil).</li>"
            "<li>After the scan completes, optionally enter a product code, SKU, and color name, "
            "then click <b>Add to Inventory</b>.</li>"
            "</ol>"

            "<h2>Toolbar Buttons</h2>"
            "<table cellpadding='4'>"
            "<tr><td><b>Scan Tag</b></td><td>Scan a single filament spool RFID tag and add it to your inventory.</td></tr>"
            "<tr><td><b>Bulk Scan</b></td><td>Scan multiple tags in sequence without closing the dialog.</td></tr>"
            "<tr><td><b>Add Manual</b></td><td>Manually create a filament entry (no RFID reader needed).</td></tr>"
            "<tr><td><b>Import File</b></td><td>Import a .bin, .json, or .nfc tag dump file.</td></tr>"
            "<tr><td><b>Scan Product Code</b></td><td>Add a spool by scanning a product code or typing a SKU.</td></tr>"
            "<tr><td><b>Settings</b></td><td>Configure Proxmark3 path and COM port.</td></tr>"
            "<tr><td><b>Edit</b></td><td>Open a full edit dialog for the selected spool.</td></tr>"
            "<tr><td><b>Delete</b></td><td>Soft-delete the selected spool (can be restored on re-scan).</td></tr>"
            "<tr><td><b>Remove by Scan</b></td><td>Scan a used-up spool's tag to delete it from your inventory.</td></tr>"
            "<tr><td><b>Weigh Spool</b></td><td>Enter a scale reading to calculate remaining filament.</td></tr>"
            "<tr><td><b>Physical Inventory</b></td><td>Scan spool labels to verify which spools are physically present. Missing spools are shown for review.</td></tr>"
            "<tr><td><b>Compress DB</b></td><td>Remove duplicate deleted entries to shrink the database.</td></tr>"
            "<tr><td><b>Export CSV</b></td><td>Export your full inventory to a CSV file for Excel.</td></tr>"
            "<tr><td><b>Import CSV</b></td><td>Import data from a CSV file. Matches by ID to update existing entries.</td></tr>"
            "<tr><td><b>Open Data Folder</b></td><td>Open the folder containing your database file.</td></tr>"
            "</table>"

            "<h2>Editing</h2>"
            "<p><b>Double-click</b> any cell in the table to edit it inline (type, weight, "
            "remaining, diameter, nozzle temp, SKU, product code, location).</p>"
            "<p><b>Right-click</b> a row to access Edit, Weigh, Set Color Name, or Delete.</p>"

            "<h2>Reordering Filament</h2>"
            "<p><b>Right-click</b> a spool and select <b>Reorder from Bambu Lab...</b> "
            "to open the product page in your browser. The app will get you as close "
            "to the right place in the store as possible by matching the filament type.</p>"
            "<p>For an exact match (including color), enable the <b>Store ID</b> column "
            "(via Columns) and paste the variant ID from the store URL. "
            "To find it: go to the Bambu Lab store, navigate to your filament, and "
            "select your color. The URL will update to include "
            "<code>?id=12345</code> — copy that number into the Store ID field. "
            "The Reorder link will then take you directly to the exact filament and color.</p>"

            "<h2>Weighing Spools</h2>"
            "<p>Select a spool and click <b>Weigh Spool</b>. Place the spool on a scale "
            "and enter the total reading in grams. The app subtracts the empty spool weight "
            "(tare) to calculate the remaining filament weight and estimates remaining length.</p>"

            "<h2>CSV Round-Trip</h2>"
            "<p><b>Export CSV</b> creates an Excel-friendly file with all spool data. "
            "UIDs, product codes, and other long numbers are preserved as text.</p>"
            "<p><b>Import CSV</b> reads a CSV file and matches rows by ID. "
            "Existing entries are updated with the CSV values; new rows are added.</p>"

            "<h2>Handy Accessories</h2>"
            "<p><b>USB Barcode Scanner</b> — Scan the product code on the "
            "filament box to quickly populate the Product Code field. Most barcode scanners "
            "act as a keyboard and type the code followed by Enter.</p>"
            "<p><b>Nelko P21 Label Printer</b> — Print spool labels with a QR code or barcode "
            "for quick identification. Configure it under Settings &gt; Printer Settings.</p>"

            "<h2>RFID Tag Tips</h2>"
            "<ul>"
            "<li>Tags are in a clear plastic strip through the spool hub, not the label.</li>"
            "<li>The HF antenna is the <b>small inner coil</b> on the Proxmark3, not the large outer ring.</li>"
            "<li>Removing the LF antenna board (top board) makes scanning much easier.</li>"
            "<li>A gentle swipe or wiggle can help with detection.</li>"
            "</ul>"

            "<h2>Data Storage</h2>"
            "<p>Your inventory is stored in:<br>"
            "<code>%APPDATA%\\BambooFilamentManager\\filaments.json</code></p>"
            "<p>Use <b>Open Data Folder</b> to find it. Back up this file before major changes.</p>"
        )
        layout.addWidget(browser)
        dlg.exec()

    def _on_about(self):
        QMessageBox.about(
            self,
            "About Bamboo Filament Manager",
            "<h2>Bamboo Filament Manager</h2>"
            "<p>Version 0.2.1</p>"
            "<p>Manage your filament spool inventory.<br>"
            "Scan RFID tags, track usage, and organize your collection.</p>"
            "<p><b>Requirements:</b> Proxmark3 (Iceman fork) with an HF antenna.<br>"
            "Download from <a href='https://github.com/RfidResearchGroup/proxmark3'>"
            "github.com/RfidResearchGroup/proxmark3</a></p>"
            "<p>Built with PyQt6 &amp; Proxmark3</p>"
            "<p>Written by Claude Code<br>"
            "with testing &amp; guidance by Jon Vogel</p>"
            "<p>Licensed under the <a href='https://www.gnu.org/licenses/gpl-3.0.html'>GNU GPL v3</a>.</p>",
        )

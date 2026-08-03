from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import load_private_data, provider_statuses, update_last_lookup
from .kicad_parser import KiCadItem, load_footprint, load_symbol, load_symbol_names


SANDBOX_ROOT = Path(r"C:\Users\phoen\Documents\KiCAD\CUSTOM_LIBRARIES_TEST")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KiCad Metadata Lookup")
        self.resize(1040, 720)

        self.current_item: KiCadItem | None = None
        self.current_symbol_library: Path | None = None
        self.private_data = load_private_data()

        self.source_label = QLabel("No KiCad item loaded.")
        self.source_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.item_label = QLabel("")
        self.item_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.open_footprint_button = QPushButton("Open Footprint")
        self.open_footprint_button.clicked.connect(self.open_footprint)
        self.open_symbol_library_button = QPushButton("Open Symbol Library")
        self.open_symbol_library_button.clicked.connect(self.open_symbol_library)

        self.symbol_combo = QComboBox()
        self.symbol_combo.setEnabled(False)
        self.symbol_combo.currentTextChanged.connect(self.symbol_selected)

        self.provider_combo = QComboBox()
        self._load_providers()
        self.mpn_edit = QLineEdit()
        self.manufacturer_edit = QLineEdit()
        self.lookup_button = QPushButton("Lookup Metadata")
        self.lookup_button.clicked.connect(self.lookup_metadata)

        self.metadata_table = QTableWidget(0, 3)
        self.metadata_table.setHorizontalHeaderLabels(["Field", "Current Value", "Suggested Value"])
        self.metadata_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.metadata_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.metadata_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.metadata_table.verticalHeader().setVisible(False)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)

        self.statusBar().showMessage("Ready")
        self.setCentralWidget(self._build_content())

    def _build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)

        source_row = QHBoxLayout()
        source_row.addWidget(self.open_footprint_button)
        source_row.addWidget(self.open_symbol_library_button)
        source_row.addWidget(QLabel("Symbol:"))
        source_row.addWidget(self.symbol_combo, stretch=1)
        layout.addLayout(source_row)

        layout.addWidget(self.source_label)
        layout.addWidget(self.item_label)

        lookup_form = QFormLayout()
        lookup_form.addRow("Provider", self.provider_combo)
        lookup_form.addRow("MPN", self.mpn_edit)
        lookup_form.addRow("Manufacturer", self.manufacturer_edit)
        lookup_form.addRow("", self.lookup_button)
        layout.addLayout(lookup_form)

        layout.addWidget(self.metadata_table, stretch=1)
        layout.addWidget(self.log)
        return root

    def open_footprint(self) -> None:
        path_text, _ = QFileDialog.getOpenFileName(
            self,
            "Open KiCad Footprint",
            str(self._dialog_root()),
            "KiCad footprints (*.kicad_mod);;All files (*.*)",
        )
        if not path_text:
            return
        try:
            item = load_footprint(Path(path_text))
        except Exception as exc:
            self._show_error("Footprint Load Failed", str(exc))
            return

        self.current_symbol_library = None
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        self.symbol_combo.setEnabled(False)
        self.symbol_combo.blockSignals(False)
        self._set_item(item)

    def open_symbol_library(self) -> None:
        path_text, _ = QFileDialog.getOpenFileName(
            self,
            "Open KiCad Symbol Library",
            str(self._dialog_root()),
            "KiCad symbol libraries (*.kicad_sym);;All files (*.*)",
        )
        if not path_text:
            return

        path = Path(path_text)
        try:
            names = load_symbol_names(path)
        except Exception as exc:
            self._show_error("Symbol Library Load Failed", str(exc))
            return

        self.current_symbol_library = path
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        self.symbol_combo.addItems(names)
        self.symbol_combo.setEnabled(bool(names))
        self.symbol_combo.blockSignals(False)
        self.source_label.setText(f"Symbol library: {path}")
        self.item_label.setText(f"{len(names)} symbols found. Choose one symbol to inspect.")
        self.metadata_table.setRowCount(0)
        self.log_message(f"Opened symbol library with {len(names)} symbols: {path.name}")
        if names:
            self.symbol_combo.setCurrentIndex(0)
            self.symbol_selected(names[0])

    def symbol_selected(self, symbol_name: str) -> None:
        if not symbol_name or self.current_symbol_library is None:
            return
        try:
            item = load_symbol(self.current_symbol_library, symbol_name)
        except Exception as exc:
            self._show_error("Symbol Load Failed", str(exc))
            return
        self._set_item(item)

    def lookup_metadata(self) -> None:
        provider = self.provider_combo.currentData()
        mpn = self.mpn_edit.text().strip()
        manufacturer = self.manufacturer_edit.text().strip()

        if not provider:
            self._show_error("Lookup Not Ready", "Configure at least one provider in kml_private_data.json.")
            return
        if not mpn:
            self._show_error("Lookup Needs MPN", "Enter or load a manufacturer part number before lookup.")
            return

        update_last_lookup(mpn, manufacturer, str(provider))
        self.log_message(
            "Lookup UI is wired to the selected item and private config. "
            "Provider API calls and field suggestions are the next milestone."
        )
        self.statusBar().showMessage(f"Ready for {provider} lookup: {mpn}")

    def _set_item(self, item: KiCadItem) -> None:
        self.current_item = item
        self.source_label.setText(f"{item.item_type} source: {item.path}")
        self.item_label.setText(f"{item.item_type}: {item.name}")
        self._seed_lookup_fields(item)
        self._populate_metadata_table(item)
        self.log_message(f"Loaded {item.item_type.lower()}: {item.name}")
        self.statusBar().showMessage(f"Loaded {item.item_type}: {item.name}")

    def _seed_lookup_fields(self, item: KiCadItem) -> None:
        value = item.properties.get("Value", "")
        manufacturer = (
            item.properties.get("MANUFACTURER", "")
            or item.properties.get("Manufacturer", "")
            or item.properties.get("manufacturer", "")
        )
        self.mpn_edit.setText(value)
        self.manufacturer_edit.setText(manufacturer)

    def _populate_metadata_table(self, item: KiCadItem) -> None:
        fields = sorted(item.properties.items(), key=lambda pair: pair[0].casefold())
        self.metadata_table.setRowCount(len(fields))
        for row, (name, value) in enumerate(fields):
            field_item = QTableWidgetItem(name)
            field_item.setFlags(field_item.flags() & ~Qt.ItemIsEditable)
            current_item = QTableWidgetItem(value)
            suggestion_item = QTableWidgetItem("")
            self.metadata_table.setItem(row, 0, field_item)
            self.metadata_table.setItem(row, 1, current_item)
            self.metadata_table.setItem(row, 2, suggestion_item)

    def _load_providers(self) -> None:
        statuses = provider_statuses(self.private_data)
        for status in statuses:
            label = status.name
            if status.enabled and status.configured:
                label += " (configured)"
            elif status.configured:
                label += " (key present, disabled)"
            else:
                label += " (not configured)"
            self.provider_combo.addItem(label, status.name)

        last_provider = self.private_data.get("gui", {}).get("last_provider", "")
        if last_provider:
            index = self.provider_combo.findData(last_provider)
            if index >= 0:
                self.provider_combo.setCurrentIndex(index)

    def _dialog_root(self) -> Path:
        return SANDBOX_ROOT if SANDBOX_ROOT.exists() else Path.home()

    def log_message(self, message: str) -> None:
        self.log.append(message)

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)
        self.statusBar().showMessage(message)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()

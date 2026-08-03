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

from .config import load_private_data, provider_secret, provider_statuses, update_last_lookup
from .kicad_parser import KiCadItem, load_footprint, load_symbol, load_symbol_names
from .providers import LookupError, LookupResult, ProviderPart
from .providers.mouser import lookup_part_number as mouser_lookup_part_number


SANDBOX_ROOT = Path(r"C:\Users\phoen\Documents\KiCAD\CUSTOM_LIBRARIES_TEST")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KiCad Metadata Lookup")
        self.resize(1040, 720)

        self.current_item: KiCadItem | None = None
        self.current_symbol_library: Path | None = None
        self.current_lookup_result: LookupResult | None = None
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
        self.result_previous_button = QPushButton("<")
        self.result_previous_button.setToolTip("Previous lookup result")
        self.result_previous_button.clicked.connect(self.previous_lookup_result)
        self.result_position_edit = QLineEdit("0 / 0")
        self.result_position_edit.setAlignment(Qt.AlignCenter)
        self.result_position_edit.setReadOnly(True)
        self.result_position_edit.setMaximumWidth(90)
        self.result_next_button = QPushButton(">")
        self.result_next_button.setToolTip("Next lookup result")
        self.result_next_button.clicked.connect(self.next_lookup_result)
        self.result_combo = QComboBox()
        self.result_combo.setEnabled(False)
        self.result_combo.currentIndexChanged.connect(self.lookup_result_selected)

        self.metadata_table = QTableWidget(0, 4)
        self.metadata_table.setHorizontalHeaderLabels(
            ["Import", "Field", "Current Value", "Suggested Value"]
        )
        self.metadata_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.metadata_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.metadata_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.metadata_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.metadata_table.verticalHeader().setVisible(False)
        self._sync_result_navigation()

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
        result_nav = QWidget()
        result_nav_layout = QHBoxLayout(result_nav)
        result_nav_layout.setContentsMargins(0, 0, 0, 0)
        result_nav_layout.addStretch(1)
        result_nav_layout.addWidget(self.result_previous_button)
        result_nav_layout.addWidget(self.result_position_edit)
        result_nav_layout.addWidget(self.result_next_button)
        result_nav_layout.addStretch(1)
        lookup_form.addRow("Match", result_nav)
        lookup_form.addRow("Result", self.result_combo)
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

        provider_name = str(provider)
        self.lookup_button.setEnabled(False)
        self.statusBar().showMessage(f"Looking up {mpn} with {provider_name}...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        error_message = ""
        try:
            result = self._run_lookup(provider_name, mpn, manufacturer)
        except LookupError as exc:
            error_message = str(exc)
            result = None
        finally:
            QApplication.restoreOverrideCursor()
            self.lookup_button.setEnabled(True)

        if error_message or result is None:
            self._show_error("Lookup Failed", error_message or "Lookup did not return a result.")
            return

        update_last_lookup(mpn, manufacturer, provider_name)
        self.current_lookup_result = result
        self._load_lookup_results(result)
        if result.parts:
            self.log_message(f"{provider_name} returned {len(result.parts)} result(s) for {mpn}.")
            self.statusBar().showMessage(f"{provider_name} returned {len(result.parts)} result(s).")
        else:
            self.log_message(f"{provider_name} returned no results for {mpn}.")
            self.statusBar().showMessage(f"No {provider_name} results for {mpn}.")

    def _run_lookup(self, provider: str, mpn: str, manufacturer: str) -> LookupResult:
        if provider == "mouser":
            api_key = provider_secret(self.private_data, "mouser", "api_key")
            return mouser_lookup_part_number(api_key, mpn, manufacturer)
        raise LookupError(f"Provider is not wired yet: {provider}")

    def _load_lookup_results(self, result: LookupResult) -> None:
        self.result_combo.blockSignals(True)
        self.result_combo.clear()
        for part in result.parts:
            mpn = part.fields.get("Value", "")
            manufacturer = part.fields.get("MANUFACTURER", "")
            mouser_part = part.fields.get("MouserPartNumber", "")
            label_bits = [bit for bit in [mpn, manufacturer, mouser_part] if bit]
            self.result_combo.addItem(" | ".join(label_bits) or "Unnamed result", part)
        self.result_combo.setEnabled(bool(result.parts))
        if result.parts:
            self.result_combo.setCurrentIndex(0)
        self.result_combo.blockSignals(False)
        self._sync_result_navigation()
        if result.parts:
            self.apply_suggestions(result.parts[0])
        else:
            self.apply_suggestions(None)

    def lookup_result_selected(self, index: int) -> None:
        if index < 0:
            return
        part = self.result_combo.itemData(index)
        if isinstance(part, ProviderPart):
            self.apply_suggestions(part)
        self._sync_result_navigation()

    def previous_lookup_result(self) -> None:
        index = self.result_combo.currentIndex()
        if index > 0:
            self.result_combo.setCurrentIndex(index - 1)
        self._sync_result_navigation()

    def next_lookup_result(self) -> None:
        index = self.result_combo.currentIndex()
        if index < self.result_combo.count() - 1:
            self.result_combo.setCurrentIndex(index + 1)
        self._sync_result_navigation()

    def _set_item(self, item: KiCadItem) -> None:
        self.current_item = item
        self.current_lookup_result = None
        self.result_combo.blockSignals(True)
        self.result_combo.clear()
        self.result_combo.setEnabled(False)
        self.result_combo.blockSignals(False)
        self._sync_result_navigation()
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
            import_item = self._build_import_item(enabled=False, checked=False)
            field_item = QTableWidgetItem(name)
            field_item.setFlags(field_item.flags() & ~Qt.ItemIsEditable)
            current_item = QTableWidgetItem(value)
            suggestion_item = QTableWidgetItem("")
            self.metadata_table.setItem(row, 0, import_item)
            self.metadata_table.setItem(row, 1, field_item)
            self.metadata_table.setItem(row, 2, current_item)
            self.metadata_table.setItem(row, 3, suggestion_item)

    def apply_suggestions(self, part: ProviderPart | None) -> None:
        suggestions = part.fields if part else {}
        for row in range(self.metadata_table.rowCount()):
            self.metadata_table.setItem(row, 0, self._build_import_item(enabled=False, checked=False))
            self.metadata_table.setItem(row, 3, QTableWidgetItem(""))

        existing_fields = {
            self.metadata_table.item(row, 1).text(): row
            for row in range(self.metadata_table.rowCount())
            if self.metadata_table.item(row, 1) is not None
        }

        for field, value in suggestions.items():
            row = existing_fields.get(field)
            if row is None:
                row = self.metadata_table.rowCount()
                self.metadata_table.insertRow(row)
                self.metadata_table.setItem(row, 0, self._build_import_item(enabled=False, checked=False))
                field_item = QTableWidgetItem(field)
                field_item.setFlags(field_item.flags() & ~Qt.ItemIsEditable)
                self.metadata_table.setItem(row, 1, field_item)
                self.metadata_table.setItem(row, 2, QTableWidgetItem(""))
                existing_fields[field] = row

            suggestion_item = QTableWidgetItem(value)
            current_value = ""
            current_item = self.metadata_table.item(row, 2)
            if current_item is not None:
                current_value = current_item.text().strip()
            if value and current_value and value != current_value:
                suggestion_item.setBackground(Qt.yellow)
            self.metadata_table.setItem(
                row,
                0,
                self._build_import_item(
                    enabled=bool(value),
                    checked=bool(value) and value != current_value,
                ),
            )
            self.metadata_table.setItem(row, 3, suggestion_item)

    def _build_import_item(self, enabled: bool, checked: bool) -> QTableWidgetItem:
        item = QTableWidgetItem("")
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        flags = Qt.ItemIsUserCheckable
        if enabled:
            flags |= Qt.ItemIsEnabled | Qt.ItemIsSelectable
        item.setFlags(flags)
        return item

    def _sync_result_navigation(self) -> None:
        count = self.result_combo.count()
        index = self.result_combo.currentIndex()
        has_results = count > 0 and index >= 0
        self.result_position_edit.setText(f"{index + 1} / {count}" if has_results else "0 / 0")
        self.result_previous_button.setEnabled(has_results and index > 0)
        self.result_next_button.setEnabled(has_results and index < count - 1)

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

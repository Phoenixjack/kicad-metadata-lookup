from __future__ import annotations

import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import load_private_data, provider_secret, provider_statuses, save_private_data, update_last_lookup
from .kicad_parser import KiCadItem, load_footprint, load_symbol, load_symbol_names
from .kicad_writer import MetadataSaveError, save_metadata_changes
from .providers import LookupError, LookupResult, ProviderPart
from .providers.digikey import lookup_part_number as digikey_lookup_part_number
from .providers.digikey import test_credentials as digikey_test_credentials
from .providers.mouser import lookup_part_number as mouser_lookup_part_number


SANDBOX_ROOT = Path(r"C:\Users\phoen\Documents\KiCAD\CUSTOM_LIBRARIES_TEST")
ALL_CONFIGURED_PROVIDERS = "__all_configured__"
WIRED_PROVIDERS = {"digikey", "mouser"}
PROVIDER_LABELS = {
    "digikey": "DigiKey",
    "mouser": "Mouser",
    "octopart_nexar": "Octopart Nexar",
}
FIELD_LABELS = {
    "api_key": "API Key",
    "client_id": "Client ID",
    "client_secret": "Client Secret / Password",
}
DEFAULT_TEST_QUERY = "KML-CREDENTIAL-TEST-NO-RESULTS"
FIELD_COLUMN = 0
CURRENT_VALUE_COLUMN = 1
NEW_VALUE_COLUMN = 2
SUGGESTED_FIELD_COLUMN = 0
SUGGESTED_VALUE_COLUMN = 1
ASSIGN_TO_COLUMN = 2


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KiCad Metadata Lookup")
        self.resize(1040, 720)

        self.current_item: KiCadItem | None = None
        self.current_symbol_library: Path | None = None
        self.current_lookup_result: LookupResult | None = None
        self.suggestion_assignments: dict[int, tuple[str, str]] = {}
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
        self.configure_api_button = QPushButton("Configure APIs")
        self.configure_api_button.clicked.connect(self.configure_selected_provider)
        self.mpn_edit = QLineEdit()
        self.manufacturer_edit = QLineEdit()
        self.lookup_button = QPushButton("Lookup Metadata")
        self.lookup_button.clicked.connect(self.lookup_metadata)
        self.mpn_edit.returnPressed.connect(self.lookup_metadata)
        self.manufacturer_edit.returnPressed.connect(self.lookup_metadata)
        self.review_changes_button = QPushButton("Review Changes")
        self.review_changes_button.clicked.connect(self.review_staged_changes)
        self.assign_selected_button = QPushButton("<- Assign")
        self.assign_selected_button.clicked.connect(self.assign_selected_suggestion)
        self.clear_staged_button = QPushButton("Clear Staged")
        self.clear_staged_button.clicked.connect(self._clear_staging)
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

        self.current_table = QTableWidget(0, 3)
        self.current_table.setHorizontalHeaderLabels(["Field", "Current Value", "New Value"])
        self.current_table.horizontalHeader().setSectionResizeMode(FIELD_COLUMN, QHeaderView.ResizeToContents)
        self.current_table.horizontalHeader().setSectionResizeMode(CURRENT_VALUE_COLUMN, QHeaderView.Stretch)
        self.current_table.horizontalHeader().setSectionResizeMode(NEW_VALUE_COLUMN, QHeaderView.Stretch)
        self.current_table.verticalHeader().setVisible(False)
        self.current_table.cellDoubleClicked.connect(self._open_current_table_url)

        self.suggested_table = QTableWidget(0, 3)
        self.suggested_table.setHorizontalHeaderLabels(["Suggested Field", "Suggested Value", "Assign To"])
        self.suggested_table.horizontalHeader().setSectionResizeMode(SUGGESTED_FIELD_COLUMN, QHeaderView.ResizeToContents)
        self.suggested_table.horizontalHeader().setSectionResizeMode(SUGGESTED_VALUE_COLUMN, QHeaderView.Stretch)
        self.suggested_table.horizontalHeader().setSectionResizeMode(ASSIGN_TO_COLUMN, QHeaderView.ResizeToContents)
        self.suggested_table.verticalHeader().setVisible(False)
        self.suggested_table.cellDoubleClicked.connect(self._open_suggested_table_url)
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

        provider_row = QWidget()
        provider_row_layout = QHBoxLayout(provider_row)
        provider_row_layout.setContentsMargins(0, 0, 0, 0)
        provider_row_layout.addWidget(self.provider_combo, stretch=1)
        provider_row_layout.addWidget(self.configure_api_button)

        lookup_form = QFormLayout()
        lookup_form.addRow("Provider", provider_row)
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

        layout.addWidget(self._build_metadata_panes(), stretch=1)
        layout.addWidget(self.log)
        return root

    def _build_metadata_panes(self) -> QSplitter:
        splitter = QSplitter(Qt.Horizontal)

        current_group = QGroupBox("Current Metadata")
        current_layout = QVBoxLayout(current_group)
        current_layout.addWidget(self.current_table)

        action_panel = QWidget()
        action_layout = QVBoxLayout(action_panel)
        action_layout.addStretch(1)
        action_layout.addWidget(self.assign_selected_button)
        action_layout.addWidget(self.clear_staged_button)
        action_layout.addWidget(self.review_changes_button)
        action_layout.addStretch(1)

        suggested_group = QGroupBox("Lookup Suggestions")
        suggested_layout = QVBoxLayout(suggested_group)
        suggested_layout.addWidget(self.suggested_table)

        splitter.addWidget(current_group)
        splitter.addWidget(action_panel)
        splitter.addWidget(suggested_group)
        splitter.setSizes([500, 110, 500])
        return splitter

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
        self.current_table.setRowCount(0)
        self.suggested_table.setRowCount(0)
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
        if provider_name != ALL_CONFIGURED_PROVIDERS and not self._ensure_provider_configured(provider_name):
            return

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
        if provider == ALL_CONFIGURED_PROVIDERS:
            parts: list[ProviderPart] = []
            skipped: list[str] = []
            for status in provider_statuses(self.private_data):
                if not status.configured:
                    continue
                if status.name not in WIRED_PROVIDERS:
                    skipped.append(status.name)
                    continue
                provider_result = self._run_lookup(status.name, mpn, manufacturer)
                parts.extend(provider_result.parts)
            if skipped:
                self.log_message(f"Skipped provider(s) not wired yet: {', '.join(skipped)}")
            if not parts:
                raise LookupError("No configured provider returned lookup results.")
            parts.sort(key=lambda part: part.score, reverse=True)
            return LookupResult(provider="all_configured", query=mpn, parts=parts)

        if provider == "mouser":
            api_key = provider_secret(self.private_data, "mouser", "api_key")
            return mouser_lookup_part_number(api_key, mpn, manufacturer)
        if provider == "digikey":
            client_id = provider_secret(self.private_data, "digikey", "client_id")
            client_secret = provider_secret(self.private_data, "digikey", "client_secret")
            return digikey_lookup_part_number(client_id, client_secret, mpn, manufacturer)
        raise LookupError(f"Provider is not wired yet: {provider}")

    def _ensure_provider_configured(self, provider_name: str) -> bool:
        required_fields = self._provider_config_fields(provider_name)
        if not required_fields:
            return True
        if all(provider_secret(self.private_data, provider_name, field) for field in required_fields):
            return True
        return self._open_provider_config_dialog(provider_name, required_fields)

    def configure_selected_provider(self) -> None:
        provider_name = str(self.provider_combo.currentData() or "")
        if not provider_name or provider_name == ALL_CONFIGURED_PROVIDERS:
            provider_name = "mouser"
        self._open_provider_config_dialog(provider_name, self._provider_config_fields(provider_name))

    def _provider_config_fields(self, provider_name: str) -> list[str]:
        if provider_name == "mouser":
            return ["api_key"]
        if provider_name in {"digikey", "octopart_nexar"}:
            return ["client_id", "client_secret"]
        return ["api_key"]

    def _open_provider_config_dialog(self, provider_name: str, required_fields: list[str]) -> bool:
        dialog = QDialog(self)
        provider_label = PROVIDER_LABELS.get(provider_name, provider_name)
        dialog.setWindowTitle(f"Configure {provider_label}")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        edits: dict[str, QLineEdit] = {}

        for field in required_fields:
            edit = QLineEdit(provider_secret(self.private_data, provider_name, field))
            edit.setEchoMode(QLineEdit.Password)
            edit.setMinimumWidth(360)
            edits[field] = edit
            form.addRow(FIELD_LABELS.get(field, field.replace("_", " ").title()), edit)

        test_button = QPushButton("Test Credentials")
        test_button.clicked.connect(
            lambda: self._test_provider_config(provider_name, {key: edit.text().strip() for key, edit in edits.items()})
        )
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).clicked.connect(dialog.accept)
        buttons.button(QDialogButtonBox.Cancel).clicked.connect(dialog.reject)

        layout.addLayout(form)
        layout.addWidget(test_button)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return False

        self.private_data.setdefault("api_integrations", {})
        self.private_data["api_integrations"].setdefault("providers", {})
        provider_settings = self.private_data["api_integrations"]["providers"].setdefault(provider_name, {})
        provider_settings["enabled"] = True
        for field, edit in edits.items():
            provider_settings[field] = edit.text().strip()
        save_private_data(self.private_data)

        self.private_data = load_private_data()
        self.provider_combo.clear()
        self._load_providers()
        index = self.provider_combo.findData(provider_name)
        if index >= 0:
            self.provider_combo.setCurrentIndex(index)
        return True

    def _test_provider_config(self, provider_name: str, values: dict[str, str]) -> None:
        mpn = self.mpn_edit.text().strip() or DEFAULT_TEST_QUERY
        manufacturer = self.manufacturer_edit.text().strip()
        missing_fields = [field for field, value in values.items() if not value.strip()]
        if missing_fields:
            missing = ", ".join(field.replace("_", " ").title() for field in missing_fields)
            QMessageBox.warning(self, "Test Needs Credentials", f"Enter {missing} before testing {provider_name}.")
            return
        provider_label = PROVIDER_LABELS.get(provider_name, provider_name)
        try:
            if provider_name == "mouser":
                result = mouser_lookup_part_number(values.get("api_key", ""), mpn, manufacturer)
            elif provider_name == "digikey":
                result = digikey_test_credentials(
                    values.get("client_id", ""),
                    values.get("client_secret", ""),
                    mpn,
                )
            else:
                QMessageBox.information(
                    self,
                    "Provider Test Not Wired",
                    f"{provider_label} credential storage is available, but test lookup is not wired yet.",
                )
                return
        except LookupError as exc:
            QMessageBox.warning(self, f"{provider_label} Test Failed", str(exc))
            return
        QMessageBox.information(
            self,
            f"{provider_label} Test Passed",
            f"{provider_label} accepted the credentials and returned {len(result.parts)} result(s) for {mpn}.",
        )

    def _provider_label(self, provider_name: str) -> str:
        return PROVIDER_LABELS.get(provider_name, provider_name)

    def _lookup_result_label(self, part: ProviderPart) -> str:
        mpn = part.fields.get("Value", "")
        manufacturer = part.fields.get("MANUFACTURER", "")
        provider_part = part.fields.get("MouserPartNumber", "") or part.fields.get("DigiKeyPartNumber", "")
        label_bits = [bit for bit in [self._provider_label(part.provider), mpn, manufacturer, provider_part] if bit]
        return " | ".join(label_bits) or "Unnamed result"

    def _provider_status_label(self, name: str) -> str:
        return PROVIDER_LABELS.get(name, name)

    def _load_lookup_results(self, result: LookupResult) -> None:
        self.result_combo.blockSignals(True)
        self.result_combo.clear()
        for part in result.parts:
            self.result_combo.addItem(self._lookup_result_label(part), part)
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
        self.suggestion_assignments.clear()
        self.result_combo.blockSignals(True)
        self.result_combo.clear()
        self.result_combo.setEnabled(False)
        self.result_combo.blockSignals(False)
        self._sync_result_navigation()
        self.source_label.setText(f"{item.item_type} source: {item.path}")
        self.item_label.setText(f"{item.item_type}: {item.name}")
        self._seed_lookup_fields(item)
        self._populate_metadata_tables(item)
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

    def _populate_metadata_tables(self, item: KiCadItem) -> None:
        fields = sorted(item.properties.items(), key=lambda pair: pair[0].casefold())
        self.current_table.setRowCount(len(fields))
        self.suggested_table.setRowCount(0)
        self.suggestion_assignments.clear()
        for row, (name, value) in enumerate(fields):
            field_item = QTableWidgetItem(name)
            field_item.setFlags(field_item.flags() & ~Qt.ItemIsEditable)
            current_item = QTableWidgetItem(value)
            current_item.setFlags(current_item.flags() & ~Qt.ItemIsEditable)
            self.current_table.setItem(row, FIELD_COLUMN, field_item)
            self.current_table.setItem(row, CURRENT_VALUE_COLUMN, current_item)
            self.current_table.setItem(row, NEW_VALUE_COLUMN, QTableWidgetItem(""))

    def apply_suggestions(self, part: ProviderPart | None) -> None:
        suggestions = part.fields if part else {}
        self.suggested_table.setRowCount(0)
        self.suggestion_assignments.clear()

        field_names = self._current_field_names()
        self.suggested_table.setRowCount(len(suggestions))
        for row, (field, value) in enumerate(suggestions.items()):
            suggestion_field_item = QTableWidgetItem(field)
            suggestion_field_item.setFlags(suggestion_field_item.flags() & ~Qt.ItemIsEditable)
            suggestion_value_item = QTableWidgetItem(value)
            suggestion_value_item.setFlags(suggestion_value_item.flags() & ~Qt.ItemIsEditable)
            self.suggested_table.setItem(row, SUGGESTED_FIELD_COLUMN, suggestion_field_item)
            self.suggested_table.setItem(row, SUGGESTED_VALUE_COLUMN, suggestion_value_item)
            self._set_assign_combo(row, field, field_names)

    def _set_assign_combo(self, row: int, suggested_field: str, field_names: list[str]) -> None:
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItem("")
        if suggested_field and suggested_field.casefold() not in {name.casefold() for name in field_names}:
            combo.addItem(f"ADD TO: {suggested_field}")
        combo.addItems(field_names)
        combo.currentIndexChanged.connect(lambda _index, source_row=row: self.assign_suggestion(source_row))
        if combo.lineEdit() is not None:
            combo.lineEdit().editingFinished.connect(lambda source_row=row: self.assign_suggestion(source_row))
        self.suggested_table.setCellWidget(row, ASSIGN_TO_COLUMN, combo)

    def assign_suggestion(self, source_row: int) -> None:
        combo = self.suggested_table.cellWidget(source_row, ASSIGN_TO_COLUMN)
        if not isinstance(combo, QComboBox):
            return
        target_field = self._assign_target_field(combo.currentText())
        suggested_value_item = self.suggested_table.item(source_row, SUGGESTED_VALUE_COLUMN)
        suggested_value = suggested_value_item.text() if suggested_value_item is not None else ""
        if not target_field or not suggested_value:
            return

        previous_assignment = self.suggestion_assignments.get(source_row)
        if previous_assignment == (target_field, suggested_value):
            target_row = self._find_current_field_row(target_field)
            target_value_item = (
                self.current_table.item(target_row, NEW_VALUE_COLUMN)
                if target_row is not None
                else None
            )
            if target_value_item is not None and target_value_item.text() == suggested_value:
                return

        if previous_assignment is not None:
            previous_field, previous_value = previous_assignment
            if previous_field.casefold() != target_field.casefold():
                previous_row = self._find_current_field_row(previous_field)
                if previous_row is not None:
                    previous_new_item = self.current_table.item(previous_row, NEW_VALUE_COLUMN)
                    if previous_new_item is not None and previous_new_item.text() == previous_value:
                        self.current_table.setItem(previous_row, NEW_VALUE_COLUMN, QTableWidgetItem(""))

        target_row = self._find_current_field_row(target_field)
        if target_row is None:
            target_row = self._append_current_field(target_field)

        self.current_table.setItem(target_row, NEW_VALUE_COLUMN, QTableWidgetItem(suggested_value))
        self.suggestion_assignments[source_row] = (target_field, suggested_value)
        self.log_message(f"Staged {target_field} from lookup suggestion.")

    def assign_selected_suggestion(self) -> None:
        suggestion_row = self.suggested_table.currentRow()
        current_row = self.current_table.currentRow()
        if suggestion_row < 0 or current_row < 0:
            self._show_error("Selection Needed", "Select one current field and one lookup suggestion.")
            return
        field_item = self.current_table.item(current_row, FIELD_COLUMN)
        combo = self.suggested_table.cellWidget(suggestion_row, ASSIGN_TO_COLUMN)
        if field_item is None or not isinstance(combo, QComboBox):
            return
        combo.setCurrentText(field_item.text())
        self.assign_suggestion(suggestion_row)

    def _assign_target_field(self, assign_text: str) -> str:
        target_field = assign_text.strip()
        if target_field.casefold().startswith("add to:"):
            target_field = target_field[7:].strip()
        elif target_field.casefold().startswith("add:"):
            target_field = target_field[4:].strip()
        return target_field

    def review_staged_changes(self) -> None:
        review_rows = self._build_review_rows()
        if not review_rows:
            self._show_error("No Fields Loaded", "Open a footprint or symbol before reviewing changes.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Review Metadata Changes")
        dialog.resize(840, 460)

        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(review_rows), 4)
        table.setHorizontalHeaderLabels(["Apply", "Field", "Current Value", "New Value"])
        table.horizontalHeaderItem(0).setTextAlignment(Qt.AlignCenter)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)

        for row, review_row in enumerate(review_rows):
            apply_checkbox = QCheckBox()
            apply_checkbox.setChecked(bool(review_row["new_value"]))
            apply_cell = QWidget()
            apply_layout = QHBoxLayout(apply_cell)
            apply_layout.setContentsMargins(0, 0, 0, 0)
            apply_layout.addStretch(1)
            apply_layout.addWidget(apply_checkbox)
            apply_layout.addStretch(1)
            field_item = QTableWidgetItem(review_row["field"])
            field_item.setFlags(field_item.flags() & ~Qt.ItemIsEditable)
            current_item = QTableWidgetItem(review_row["current_value"])
            current_item.setFlags(current_item.flags() & ~Qt.ItemIsEditable)
            new_item = QTableWidgetItem(review_row["new_value"] or "no change")
            new_item.setFlags(new_item.flags() & ~Qt.ItemIsEditable)
            table.setCellWidget(row, 0, apply_cell)
            table.setItem(row, 1, field_item)
            table.setItem(row, 2, current_item)
            table.setItem(row, 3, new_item)

        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(dialog.accept)
        buttons.button(QDialogButtonBox.Cancel).clicked.connect(dialog.reject)

        layout.addWidget(table)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        changes = self._reviewed_changes(review_rows, table)
        if not changes:
            self._show_error("No Changes Selected", "Select at least one staged value to apply.")
            return
        if self.current_item is None:
            self._show_error("No Item Loaded", "Open a footprint or symbol before applying changes.")
            return
        if not self._confirm_save_target(self.current_item.path):
            return

        try:
            save_result = save_metadata_changes(self.current_item, changes)
        except (MetadataSaveError, OSError) as exc:
            self._show_error("Save Failed", str(exc))
            return

        changed_count = self._apply_saved_changes(changes, set(save_result.changed_fields))
        self._clear_staging()
        self.log_message(
            f"Saved {changed_count} metadata change(s) to {save_result.path.name}. "
            f"Backup: {save_result.backup_path.name}"
        )
        self.statusBar().showMessage(f"Saved {changed_count} metadata change(s).")

    def _build_review_rows(self) -> list[dict[str, str]]:
        review_rows: list[dict[str, str]] = []
        for row in range(self.current_table.rowCount()):
            field_item = self.current_table.item(row, FIELD_COLUMN)
            if field_item is None or not field_item.text().strip():
                continue
            current_item = self.current_table.item(row, CURRENT_VALUE_COLUMN)
            new_item = self.current_table.item(row, NEW_VALUE_COLUMN)
            review_rows.append(
                {
                    "row": str(row),
                    "field": field_item.text().strip(),
                    "current_value": current_item.text() if current_item is not None else "",
                    "new_value": new_item.text() if new_item is not None else "",
                }
            )
        return review_rows

    def _reviewed_changes(
        self,
        review_rows: list[dict[str, str]],
        review_table: QTableWidget,
    ) -> dict[str, str]:
        changes: dict[str, str] = {}
        for review_index, review_row in enumerate(review_rows):
            if not self._review_row_is_checked(review_table, review_index):
                continue
            new_value = review_row["new_value"]
            if not new_value:
                continue
            changes[review_row["field"]] = new_value
        return changes

    def _apply_saved_changes(self, changes: dict[str, str], saved_fields: set[str]) -> int:
        changed_count = 0
        saved_field_keys = {field.casefold() for field in saved_fields}
        for field, new_value in changes.items():
            if field.casefold() not in saved_field_keys:
                continue
            row = self._find_current_field_row(field)
            if row is None:
                continue
            current_item = QTableWidgetItem(new_value)
            current_item.setFlags(current_item.flags() & ~Qt.ItemIsEditable)
            self.current_table.setItem(row, CURRENT_VALUE_COLUMN, current_item)
            if self.current_item is not None:
                self.current_item.properties[field] = new_value
                if field in self.current_item.summary:
                    self.current_item.summary[field] = new_value
            changed_count += 1
        return changed_count

    def _review_row_is_checked(self, review_table: QTableWidget, row: int) -> bool:
        widget = review_table.cellWidget(row, 0)
        if widget is not None:
            checkbox = widget.findChild(QCheckBox)
            if checkbox is not None:
                return checkbox.isChecked()
        apply_item = review_table.item(row, 0)
        return apply_item is not None and apply_item.checkState() == Qt.Checked

    def _clear_staging(self) -> None:
        for row in range(self.current_table.rowCount()):
            self.current_table.setItem(row, NEW_VALUE_COLUMN, QTableWidgetItem(""))
        for row in range(self.suggested_table.rowCount()):
            combo = self.suggested_table.cellWidget(row, ASSIGN_TO_COLUMN)
            if isinstance(combo, QComboBox):
                combo.setCurrentText("")
        self.suggestion_assignments.clear()

    def _append_current_field(self, field_name: str) -> int:
        row = self.current_table.rowCount()
        self.current_table.insertRow(row)
        field_item = QTableWidgetItem(field_name)
        field_item.setFlags(field_item.flags() & ~Qt.ItemIsEditable)
        self.current_table.setItem(row, FIELD_COLUMN, field_item)
        self.current_table.setItem(row, CURRENT_VALUE_COLUMN, QTableWidgetItem(""))
        self.current_table.setItem(row, NEW_VALUE_COLUMN, QTableWidgetItem(""))
        self._refresh_assign_combos()
        return row

    def _refresh_assign_combos(self) -> None:
        field_names = self._current_field_names()
        for row in range(self.suggested_table.rowCount()):
            combo = self.suggested_table.cellWidget(row, ASSIGN_TO_COLUMN)
            if not isinstance(combo, QComboBox):
                continue
            current_text = combo.currentText()
            suggested_field_item = self.suggested_table.item(row, SUGGESTED_FIELD_COLUMN)
            suggested_field = suggested_field_item.text().strip() if suggested_field_item is not None else ""
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("")
            if suggested_field and suggested_field.casefold() not in {name.casefold() for name in field_names}:
                combo.addItem(f"ADD TO: {suggested_field}")
            combo.addItems(field_names)
            combo.setCurrentText(current_text)
            combo.blockSignals(False)

    def _find_current_field_row(self, field_name: str) -> int | None:
        for row in range(self.current_table.rowCount()):
            item = self.current_table.item(row, FIELD_COLUMN)
            if item is not None and item.text().casefold() == field_name.casefold():
                return row
        return None

    def _current_field_names(self) -> list[str]:
        names: list[str] = []
        for row in range(self.current_table.rowCount()):
            item = self.current_table.item(row, FIELD_COLUMN)
            if item is None:
                continue
            name = item.text().strip()
            if name:
                names.append(name)
        return names

    def _sync_result_navigation(self) -> None:
        count = self.result_combo.count()
        index = self.result_combo.currentIndex()
        has_results = count > 0 and index >= 0
        self.result_position_edit.setText(f"{index + 1} / {count}" if has_results else "0 / 0")
        self.result_previous_button.setEnabled(has_results and index > 0)
        self.result_next_button.setEnabled(has_results and index < count - 1)

    def _load_providers(self) -> None:
        self.provider_combo.addItem("All configured APIs", ALL_CONFIGURED_PROVIDERS)
        statuses = provider_statuses(self.private_data)
        for status in statuses:
            label = self._provider_status_label(status.name)
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

    def _open_current_table_url(self, row: int, column: int) -> None:
        if column == FIELD_COLUMN:
            return
        item = self.current_table.item(row, column)
        self._open_url_from_item(item)

    def _open_suggested_table_url(self, row: int, column: int) -> None:
        if column == ASSIGN_TO_COLUMN:
            return
        item = self.suggested_table.item(row, column)
        self._open_url_from_item(item)

    def _open_url_from_item(self, item: QTableWidgetItem | None) -> None:
        if item is None:
            return
        url = item.text().strip()
        if not _is_url(url):
            return
        answer = QMessageBox.question(
            self,
            "Open URL?",
            f"Open this URL in your default browser?\n\n{url}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        webbrowser.open(url)
        self.log_message(f"Opened URL: {url}")

    def _confirm_save_target(self, path: Path) -> bool:
        if _path_is_under(path, SANDBOX_ROOT):
            return True
        answer = QMessageBox.question(
            self,
            "Save Outside Sandbox?",
            f"This will update the KiCad file outside the sandbox:\n\n{path}\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def log_message(self, message: str) -> None:
        self.log.append(message)

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)
        self.statusBar().showMessage(message)


def _is_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()

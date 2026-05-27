from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portefeuille_viewer.config import get_stockdata_db_path
from portefeuille_viewer.data.option_reference_repository import (
    OptionReferenceColumn,
    delete_option_reference_row,
    list_option_reference_columns,
    list_option_reference_rows,
    upsert_option_reference_row,
)
from portefeuille_viewer.signals import signals


class _OptionReferenceLoadWorker(QThread):
    loaded = Signal(list, list)
    error = Signal(str)

    def run(self) -> None:
        try:
            columns = list_option_reference_columns()
            rows = list_option_reference_rows()
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.loaded.emit(columns, rows)


class _OptionReferenceSaveWorker(QThread):
    done = Signal(int)
    error = Signal(str)

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self._payload = payload

    def run(self) -> None:
        try:
            row_id = upsert_option_reference_row(self._payload)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(row_id)


class _OptionReferenceDeleteWorker(QThread):
    done = Signal()
    error = Signal(str)

    def __init__(self, row_id: int, parent=None):
        super().__init__(parent)
        self._row_id = int(row_id)

    def run(self) -> None:
        try:
            delete_option_reference_row(self._row_id)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit()


class _SortableTableItem(QTableWidgetItem):
    def __init__(self, text: str, *, numeric: bool = False):
        super().__init__(text)
        self._numeric = bool(numeric)

    def __lt__(self, other) -> bool:
        if self._numeric and isinstance(other, QTableWidgetItem):
            left = self._to_float(self.text())
            right = self._to_float(other.text())
            if left is not None and right is not None:
                return left < right
        return super().__lt__(other)

    @staticmethod
    def _to_float(value: str) -> float | None:
        text = str(value or "").strip().replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except Exception:
            return None


class OptionReferenceEditorTab(QWidget):
    FILTER_COLUMNS = ("asset_rollup", "opt_exchange", "opt_tradingclass", "opt_week")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns: list[OptionReferenceColumn] = []
        self._rows: list[dict] = []
        self._display_rows: list[dict] = []
        self._filter_combos: dict[str, QComboBox] = {}
        self._sort_column: str | None = None
        self._sort_order = Qt.AscendingOrder
        self._selected_id: int | None = None
        self._load_worker = None
        self._save_worker = None
        self._delete_worker = None
        self._has_new_row = False

        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "Beheer optie_referentie_data. Opslaan ververst de snapshot en triggert de optie-resolver opnieuw."
            )
        )

        top = QHBoxLayout()
        root.addLayout(top)
        self.lbl_database = QLabel(self)
        top.addWidget(self.lbl_database, 1)
        self.lbl_status = QLabel("", self)
        top.addWidget(self.lbl_status)

        tools = QHBoxLayout()
        root.addLayout(tools)
        tools.addWidget(QLabel("Filter"))
        self.input_filter = QLineEdit(self)
        self.input_filter.setPlaceholderText("Zoek asset, exchange, trading class, details...")
        tools.addWidget(self.input_filter, 1)
        self.btn_reload = QPushButton("Vernieuwen", self)
        self.btn_new = QPushButton("Nieuw", self)
        self.btn_copy = QPushButton("Copy", self)
        self.btn_save = QPushButton("Opslaan", self)
        self.btn_delete = QPushButton("Verwijderen", self)
        for button in (self.btn_reload, self.btn_new, self.btn_copy, self.btn_save, self.btn_delete):
            tools.addWidget(button)

        self.filter_bar = QHBoxLayout()
        root.addLayout(self.filter_bar)

        self.table = QTableWidget(self)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.SelectedClicked
            | QAbstractItemView.EditKeyPressed
        )
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_section_clicked)
        root.addWidget(self.table, 1)

        self.input_filter.textChanged.connect(self._apply_filter)
        self.btn_reload.clicked.connect(self.reload)
        self.btn_new.clicked.connect(self._new_row)
        self.btn_copy.clicked.connect(self._copy_row)
        self.btn_save.clicked.connect(self._save_row)
        self.btn_delete.clicked.connect(self._delete_row)
        signals.databaseChanged.connect(self._on_database_changed)

        self.lbl_database.setText(f"Stock DB: {get_stockdata_db_path()}")
        self.lbl_status.setText("Nog niet geladen")
        self.btn_copy.setEnabled(False)
        self.btn_delete.setEnabled(False)

    def set_active(self, active: bool) -> None:
        if active and not self._rows and self._load_worker is None:
            self.reload()

    def reload(self) -> None:
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        self.lbl_database.setText(f"Stock DB: {get_stockdata_db_path()}")
        self._set_busy(True, "Laden...")
        self._load_worker = _OptionReferenceLoadWorker(self)
        self._load_worker.loaded.connect(self._on_loaded)
        self._load_worker.error.connect(self._on_error)
        self._load_worker.finished.connect(self._on_load_finished)
        self._load_worker.start()

    def _on_loaded(self, columns: list, rows: list) -> None:
        self._columns = list(columns or [])
        self._rows = list(rows or [])
        self._has_new_row = False
        self._build_filter_controls()
        self._apply_filter()
        self.lbl_status.setText(f"Rijen geladen: {len(self._rows)}")

    def _on_error(self, message: str) -> None:
        self.lbl_status.setText(f"Laden mislukt: {message}")
        QMessageBox.warning(self, "Optie Referentie Data", f"Laden mislukt: {message}")

    def _on_load_finished(self) -> None:
        self._load_worker = None
        self._set_busy(False)

    def _apply_filter(self) -> None:
        needle = self.input_filter.text().strip().lower()
        active_filters = {
            column: combo.currentData()
            for column, combo in self._filter_combos.items()
            if combo.currentData() not in (None, "")
        }
        rows = []
        for row in self._rows:
            if needle and needle not in " ".join("" if value is None else str(value) for value in row.values()).lower():
                continue
            if all(self._normalized_filter_value(row.get(col)) == expected for col, expected in active_filters.items()):
                rows.append(row)
        self._display_rows = list(rows)
        self._sort_display_rows()
        self._has_new_row = False
        self._fill_table()

    def _fill_table(self) -> None:
        selected_id = self._selected_id
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.clearContents()
            self.table.setColumnCount(len(self._columns))
            self.table.setHorizontalHeaderLabels([col.name for col in self._columns])
            self.table.setRowCount(len(self._display_rows))
            for row_idx, row in enumerate(self._display_rows):
                for col_idx, column in enumerate(self._columns):
                    item = _SortableTableItem(self._format_value(row.get(column.name)), numeric=column.is_numeric)
                    if column.is_counter or column.is_primary_key:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    if column.is_numeric:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.table.setItem(row_idx, col_idx, item)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
        self.table.resizeColumnsToContents()
        if selected_id is not None and not self._restore_selection(selected_id):
            self._selected_id = None
            self.btn_delete.setEnabled(False)

    def _build_filter_controls(self) -> None:
        while self.filter_bar.count():
            item = self.filter_bar.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._filter_combos = {}
        available = {column.name for column in self._columns}
        for column in self.FILTER_COLUMNS:
            if column not in available:
                continue
            combo = QComboBox(self)
            combo.setMinimumWidth(130)
            combo.addItem(column, "")
            values = sorted(
                {
                    self._normalized_filter_value(row.get(column))
                    for row in self._rows
                    if self._normalized_filter_value(row.get(column))
                },
                key=str.lower,
            )
            for value in values:
                combo.addItem(value, value)
            combo.currentIndexChanged.connect(self._apply_filter)
            self._filter_combos[column] = combo
            self.filter_bar.addWidget(combo)
        self.filter_bar.addStretch(1)

    def _normalized_filter_value(self, value) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _on_header_section_clicked(self, section: int) -> None:
        if section < 0 or section >= len(self._columns):
            return
        column_name = self._columns[section].name
        if self._sort_column == column_name:
            self._sort_order = Qt.DescendingOrder if self._sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self._sort_column = column_name
            self._sort_order = Qt.AscendingOrder
        self.table.horizontalHeader().setSortIndicator(section, self._sort_order)
        self._sort_display_rows()
        self._fill_table()

    def _sort_display_rows(self) -> None:
        if not self._sort_column:
            return
        column = next((col for col in self._columns if col.name == self._sort_column), None)
        if column is None:
            return
        new_rows = []
        body_rows = []
        for row in self._display_rows:
            row_id = row.get("Id")
            if self._has_new_row and row_id in ("", None):
                new_rows.append(row)
            else:
                body_rows.append(row)
        reverse = self._sort_order == Qt.DescendingOrder
        body_rows.sort(key=lambda row: self._sort_key(row.get(column.name), column), reverse=reverse)
        self._display_rows = new_rows + body_rows

    def _sort_key(self, value, column: OptionReferenceColumn):
        if value is None or value == "":
            return (1, "")
        if column.is_numeric:
            try:
                return (0, float(str(value).strip().replace(",", ".")))
            except Exception:
                return (1, str(value).casefold())
        return (0, str(value).strip().casefold())

    def _format_value(self, value) -> str:
        if value is None:
            return ""
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        return str(value)

    def _on_table_selection_changed(self) -> None:
        row_idx = self.table.currentRow()
        if row_idx < 0:
            self._selected_id = None
            self.btn_copy.setEnabled(False)
            self.btn_delete.setEnabled(False)
            return
        row_id = self._table_value(row_idx, "Id")
        self._selected_id = int(row_id) if row_id not in ("", None) else None
        self.btn_copy.setEnabled(True)
        self.btn_delete.setEnabled(self._selected_id is not None)

    def _new_row(self) -> None:
        if not self._columns:
            return
        if self.input_filter.text():
            self.input_filter.clear()
        if self._has_new_row:
            self.table.selectRow(0)
            self.table.setCurrentCell(0, self._first_editable_column_index())
            return
        self._selected_id = None
        defaults_by_name = {
            "opt_exchange": "SMART",
            "opt_week": "0",
            "opt_multiplier": "100",
        }
        new_row = {
            column.name: defaults_by_name.get(column.name.lower(), "")
            for column in self._columns
        }
        self._display_rows.insert(0, new_row)
        self._has_new_row = True
        self._fill_table()
        self.table.selectRow(0)
        self.table.setCurrentCell(0, self._first_editable_column_index())
        self.btn_delete.setEnabled(False)
        self.lbl_status.setText("Nieuwe rij bovenaan toegevoegd. Vul de cellen en klik Opslaan.")

    def _copy_row(self) -> None:
        if not self._columns:
            return
        source_idx = self.table.currentRow()
        if source_idx < 0:
            QMessageBox.information(self, "Optie Referentie Data", "Selecteer eerst een rij om te kopiëren.")
            return
        if self.input_filter.text():
            self.input_filter.clear()
        copied = self._payload_from_table_row(source_idx)
        for column in self._columns:
            if column.is_counter or column.is_primary_key:
                copied[column.name] = ""
        self._selected_id = None
        self._display_rows.insert(0, copied)
        self._has_new_row = True
        self._fill_table()
        self.table.selectRow(0)
        self.table.setCurrentCell(0, self._first_editable_column_index())
        self.btn_copy.setEnabled(True)
        self.btn_delete.setEnabled(False)
        self.lbl_status.setText("Rij gekopieerd als nieuw record bovenaan. Pas waar nodig aan en klik Opslaan.")

    def _save_row(self) -> None:
        if self._save_worker is not None and self._save_worker.isRunning():
            return
        row_idx = self.table.currentRow()
        if row_idx < 0:
            QMessageBox.information(self, "Optie Referentie Data", "Selecteer eerst een rij om op te slaan.")
            return
        payload = self._payload_from_table_row(row_idx)
        self._set_busy(True, "Opslaan...")
        self._save_worker = _OptionReferenceSaveWorker(payload, self)
        self._save_worker.done.connect(self._on_save_done)
        self._save_worker.error.connect(self._on_save_error)
        self._save_worker.finished.connect(self._on_save_finished)
        self._save_worker.start()

    def _on_save_done(self, row_id: int) -> None:
        self._selected_id = int(row_id)
        self._has_new_row = False
        self.lbl_status.setText("Record opgeslagen. Snapshot vernieuwd; optie-resolver wordt opnieuw opgebouwd...")
        self.reload()

    def _on_save_error(self, message: str) -> None:
        QMessageBox.warning(self, "Optie Referentie Data", f"Opslaan mislukt: {message}")

    def _on_save_finished(self) -> None:
        self._save_worker = None
        self._set_busy(False)

    def _delete_row(self) -> None:
        if self._selected_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Optie Referentie Data",
            "Geselecteerd record verwijderen?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._set_busy(True, "Verwijderen...")
        self._delete_worker = _OptionReferenceDeleteWorker(self._selected_id, self)
        self._delete_worker.done.connect(self._on_delete_done)
        self._delete_worker.error.connect(self._on_delete_error)
        self._delete_worker.finished.connect(self._on_delete_finished)
        self._delete_worker.start()

    def _on_delete_done(self) -> None:
        self._has_new_row = False
        self._selected_id = None
        self.lbl_status.setText("Record verwijderd. Snapshot vernieuwd; optie-resolver wordt opnieuw opgebouwd...")
        self.reload()

    def _on_delete_error(self, message: str) -> None:
        QMessageBox.warning(self, "Optie Referentie Data", f"Verwijderen mislukt: {message}")

    def _on_delete_finished(self) -> None:
        self._delete_worker = None
        self._set_busy(False)

    def _on_database_changed(self, _db_name: str) -> None:
        self._has_new_row = False
        self._selected_id = None
        self.reload()

    def _first_editable_column_index(self) -> int:
        for idx, column in enumerate(self._columns):
            if not column.is_counter and not column.is_primary_key:
                return idx
        return 0

    def _payload_from_table_row(self, row_idx: int) -> dict:
        payload = {}
        for col_idx, column in enumerate(self._columns):
            item = self.table.item(row_idx, col_idx)
            payload[column.name] = item.text().strip() if item is not None else ""
        if "Id" in payload and not payload["Id"]:
            payload["Id"] = None
        return payload

    def _column_index(self, column_name: str) -> int:
        target = str(column_name or "").lower()
        for idx, column in enumerate(self._columns):
            if column.name.lower() == target:
                return idx
        return -1

    def _table_value(self, row_idx: int, column_name: str) -> str:
        col_idx = self._column_index(column_name)
        if col_idx < 0:
            return ""
        item = self.table.item(row_idx, col_idx)
        return item.text().strip() if item is not None else ""

    def _restore_selection(self, selected_id: int | None) -> bool:
        if selected_id is None:
            return False
        id_col = self._column_index("Id")
        if id_col < 0:
            return False
        for row_idx in range(self.table.rowCount()):
            item = self.table.item(row_idx, id_col)
            try:
                row_id = int(item.text()) if item is not None and item.text().strip() else None
            except Exception:
                row_id = None
            if row_id == selected_id:
                self.table.selectRow(row_idx)
                return True
        return False

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        for widget in (self.btn_reload, self.btn_new, self.btn_copy, self.btn_save, self.btn_delete, self.input_filter, self.table):
            widget.setEnabled(not busy)
        if self.table.currentRow() < 0:
            self.btn_copy.setEnabled(False)
        if self._selected_id is None:
            self.btn_delete.setEnabled(False)
        if status:
            self.lbl_status.setText(status)

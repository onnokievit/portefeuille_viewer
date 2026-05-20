from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from portefeuille_viewer.data import repository as data_repository
from portefeuille_viewer.data.asset_rollup_repository import (
    AssetRollupColumn,
    delete_asset_rollup_row,
    list_asset_rollup_columns,
    list_asset_rollup_rows,
    upsert_asset_rollup_row,
)
from portefeuille_viewer.services.single_asset_long_history_runner import SingleAssetLongHistoryRunner
from portefeuille_viewer.signals import signals


class _AssetRollupLoadWorker(QThread):
    loaded = Signal(list, list)
    error = Signal(str)

    def run(self) -> None:
        try:
            columns = list_asset_rollup_columns()
            rows = list_asset_rollup_rows()
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.loaded.emit(columns, rows)


class _AssetRollupSaveWorker(QThread):
    done = Signal(int)
    error = Signal(str)

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self._payload = payload

    def run(self) -> None:
        try:
            row_id = upsert_asset_rollup_row(self._payload)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(row_id)


class _AssetRollupDeleteWorker(QThread):
    done = Signal()
    error = Signal(str)

    def __init__(self, row_id: int, parent=None):
        super().__init__(parent)
        self._row_id = int(row_id)

    def run(self) -> None:
        try:
            delete_asset_rollup_row(self._row_id)
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


class _LongHistoryOutputDialog(QDialog):
    def __init__(self, asset_rollup: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Lange historie ophalen - {asset_rollup}")
        self.resize(1100, 720)
        root = QVBoxLayout(self)
        self.lbl_status = QLabel("Start...", self)
        root.addWidget(self.lbl_status)
        self.output = QTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QTextEdit.NoWrap)
        root.addWidget(self.output, 1)
        buttons = QHBoxLayout()
        root.addLayout(buttons)
        buttons.addStretch(1)
        self.btn_close = QPushButton("Sluiten", self)
        self.btn_close.clicked.connect(self.close)
        buttons.addWidget(self.btn_close)

    def append_output(self, text: str) -> None:
        self.output.moveCursor(self.output.textCursor().MoveOperation.End)
        self.output.insertPlainText(str(text or ""))
        self.output.moveCursor(self.output.textCursor().MoveOperation.End)

    def set_status(self, text: str) -> None:
        self.lbl_status.setText(text)


class AssetRollupEditorTab(QWidget):
    FILTER_COLUMNS = (
        "value_grow",
        "sector",
        "type",
        "regio",
        "ib_currency",
        "exchange",
        "prim_exchange",
        "home_index",
        "quote_unit",
        "indicator_rol",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns: list[AssetRollupColumn] = []
        self._rows: list[dict] = []
        self._display_rows: list[dict] = []
        self._filter_combos: dict[str, QComboBox] = {}
        self._sort_column: str | None = None
        self._sort_order = Qt.AscendingOrder
        self._selected_id: int | None = None
        self._load_worker = None
        self._save_worker = None
        self._delete_worker = None
        self._history_runner: SingleAssetLongHistoryRunner | None = None
        self._history_dialog: _LongHistoryOutputDialog | None = None
        self._has_new_row = False

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Beheer asset_rollup_data voor de actieve database."))

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
        self.input_filter.setPlaceholderText("Zoek in asset_rollup, type, sector, regio, IB symbol...")
        tools.addWidget(self.input_filter, 1)
        self.btn_reload = QPushButton("Vernieuwen", self)
        self.btn_new = QPushButton("Nieuw", self)
        self.btn_save = QPushButton("Opslaan", self)
        self.btn_delete = QPushButton("Verwijderen", self)
        self.btn_long_history = QPushButton("Lange historie ophalen", self)
        for button in (self.btn_reload, self.btn_new, self.btn_save, self.btn_delete, self.btn_long_history):
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
        self.table.setStyleSheet(
            "QTableWidget::item:selected { background-color: #F4B183; color: #000000; }"
            "QTableWidget::item:selected:active { background-color: #F4B183; color: #000000; }"
            "QTableWidget::item:selected:!active { background-color: #F8CBAD; color: #000000; }"
        )
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_section_clicked)
        root.addWidget(self.table, 1)

        self.input_filter.textChanged.connect(self._apply_filter)
        self.btn_reload.clicked.connect(self.reload)
        self.btn_new.clicked.connect(self._new_row)
        self.btn_save.clicked.connect(self._save_row)
        self.btn_delete.clicked.connect(self._delete_row)
        self.btn_long_history.clicked.connect(self._run_long_history_for_selection)
        signals.databaseChanged.connect(self._on_database_changed)

        self.lbl_database.setText(f"Database: {data_repository.db_path}")
        self.lbl_status.setText("Nog niet geladen")
        self.btn_delete.setEnabled(False)
        self.btn_long_history.setEnabled(False)

    def set_active(self, active: bool) -> None:
        if active and not self._rows and self._load_worker is None:
            self.reload()

    def reload(self) -> None:
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        self.lbl_database.setText(f"Database: {data_repository.db_path}")
        self._set_busy(True, "Laden...")
        self._load_worker = _AssetRollupLoadWorker(self)
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
        QMessageBox.warning(self, "Asset Rollup Data", f"Laden mislukt: {message}")

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
            matches = True
            for column, expected in active_filters.items():
                if self._normalized_filter_value(row.get(column)) != expected:
                    matches = False
                    break
            if matches:
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
                    item = _SortableTableItem(
                        self._format_value(row.get(column.name)),
                        numeric=column.is_numeric,
                    )
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
            self.btn_long_history.setEnabled(False)

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
            combo.setMinimumWidth(115)
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
            self._sort_order = (
                Qt.DescendingOrder
                if self._sort_order == Qt.AscendingOrder
                else Qt.AscendingOrder
            )
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

    def _sort_key(self, value, column: AssetRollupColumn):
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
            self.btn_delete.setEnabled(False)
            self.btn_long_history.setEnabled(False)
            return
        row_id = self._table_value(row_idx, "Id")
        self._selected_id = int(row_id) if row_id not in ("", None) else None
        self.btn_delete.setEnabled(self._selected_id is not None)
        self.btn_long_history.setEnabled(self._selected_id is not None and not self._history_is_running())

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
            "ib_currency": "EUR",
            "exchange": "SMART",
            "incl_excl": "1",
            "quote_unit": "1",
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
        self.btn_long_history.setEnabled(False)
        self.lbl_status.setText("Nieuwe rij bovenaan toegevoegd. Vul de cellen en klik Opslaan.")

    def _save_row(self) -> None:
        if self._save_worker is not None and self._save_worker.isRunning():
            return
        row_idx = self.table.currentRow()
        if row_idx < 0:
            QMessageBox.information(self, "Asset Rollup Data", "Selecteer eerst een rij om op te slaan.")
            return
        payload = self._payload_from_table_row(row_idx)
        self._last_save_subscription_payload = {
            "reason": "asset_rollup_saved",
            "asset_rollup": str(payload.get("asset_rollup") or "").strip(),
        }
        self._set_busy(True, "Opslaan...")
        self._save_worker = _AssetRollupSaveWorker(payload, self)
        self._save_worker.done.connect(self._on_save_done)
        self._save_worker.error.connect(self._on_save_error)
        self._save_worker.finished.connect(self._on_save_finished)
        self._save_worker.start()

    def _on_save_done(self, row_id: int) -> None:
        self._selected_id = int(row_id)
        self._has_new_row = False
        self.lbl_status.setText("Record opgeslagen. Tabel vernieuwen...")
        payload = getattr(self, "_last_save_subscription_payload", None) or {"reason": "asset_rollup_saved"}
        signals.assetSubscriptionsRefreshRequested.emit(payload)
        self.reload()

    def _on_save_error(self, message: str) -> None:
        QMessageBox.warning(self, "Asset Rollup Data", f"Opslaan mislukt: {message}")

    def _on_save_finished(self) -> None:
        self._save_worker = None
        self._set_busy(False)

    def _delete_row(self) -> None:
        if self._selected_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Asset Rollup Data",
            "Geselecteerd record verwijderen?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._set_busy(True, "Verwijderen...")
        self._delete_worker = _AssetRollupDeleteWorker(self._selected_id, self)
        self._delete_worker.done.connect(self._on_delete_done)
        self._delete_worker.error.connect(self._on_delete_error)
        self._delete_worker.finished.connect(self._on_delete_finished)
        self._delete_worker.start()

    def _on_delete_done(self) -> None:
        self._has_new_row = False
        self._selected_id = None
        self.lbl_status.setText("Record verwijderd. Tabel vernieuwen...")
        signals.assetSubscriptionsRefreshRequested.emit({"reason": "asset_rollup_deleted"})
        self.reload()

    def _on_delete_error(self, message: str) -> None:
        QMessageBox.warning(self, "Asset Rollup Data", f"Verwijderen mislukt: {message}")

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

    def _selected_asset_rollup(self) -> str:
        row_idx = self.table.currentRow()
        if row_idx < 0:
            return ""
        return self._table_value(row_idx, "asset_rollup")

    def _run_long_history_for_selection(self) -> None:
        if self._history_is_running():
            return
        if self._selected_id is None:
            QMessageBox.information(
                self,
                "Lange historie ophalen",
                "Selecteer eerst een bestaande asset_rollup-regel.",
            )
            return
        asset_rollup = self._selected_asset_rollup()
        if not asset_rollup:
            QMessageBox.warning(self, "Lange historie ophalen", "De geselecteerde rij heeft geen asset_rollup.")
            return
        self._history_dialog = _LongHistoryOutputDialog(asset_rollup, self)
        self._history_dialog.show()
        self._history_dialog.raise_()
        self._history_dialog.activateWindow()

        runner = SingleAssetLongHistoryRunner(self)
        runner.started.connect(self._on_long_history_started)
        runner.stepStarted.connect(self._on_long_history_step_started)
        runner.output.connect(self._on_long_history_output)
        runner.finished.connect(self._on_long_history_finished)
        runner.failed.connect(self._on_long_history_failed)
        self._history_runner = runner
        self._set_history_busy(True, f"Lange historie bezig voor {asset_rollup}...")
        runner.start(asset_rollup)

    def _on_long_history_started(self, payload: dict) -> None:
        asset = payload.get("asset_rollup", "")
        self._append_history_output(f"Runner gestart voor {asset}\n")

    def _on_long_history_step_started(self, payload: dict) -> None:
        label = payload.get("label", "")
        step = payload.get("step_index", "")
        steps = payload.get("steps", "")
        status = f"Stap {step}/{steps}: {label}"
        self.lbl_status.setText(status)
        if self._history_dialog is not None:
            self._history_dialog.set_status(status)

    def _on_long_history_output(self, text: str) -> None:
        self._append_history_output(text)

    def _on_long_history_finished(self, payload: dict) -> None:
        asset = payload.get("asset_rollup", "")
        self._append_history_output(f"\nKlaar voor {asset}.\n")
        if self._history_dialog is not None:
            self._history_dialog.set_status(f"Klaar: {asset}")
        signals.assetSubscriptionsRefreshRequested.emit(
            {"reason": "single_asset_long_history_finished", "asset_rollup": str(asset or "").strip()}
        )
        self._history_runner = None
        self._set_history_busy(False, f"Lange historie klaar voor {asset}")

    def _on_long_history_failed(self, message: str) -> None:
        self._append_history_output(f"\nFout: {message}\n")
        if self._history_dialog is not None:
            self._history_dialog.set_status(f"Fout: {message}")
        self._history_runner = None
        self._set_history_busy(False, f"Lange historie mislukt: {message}")
        QMessageBox.warning(self, "Lange historie ophalen", message)

    def _append_history_output(self, text: str) -> None:
        if self._history_dialog is not None:
            self._history_dialog.append_output(text)

    def _history_is_running(self) -> bool:
        return self._history_runner is not None and self._history_runner.is_running

    def _set_history_busy(self, busy: bool, status: str = "") -> None:
        self.btn_long_history.setEnabled((not busy) and self._selected_id is not None)
        self.btn_reload.setEnabled(not busy)
        self.btn_new.setEnabled(not busy)
        self.btn_save.setEnabled(not busy)
        self.btn_delete.setEnabled((not busy) and self._selected_id is not None)
        if status:
            self.lbl_status.setText(status)

    def _set_busy(self, busy: bool, status: str = "") -> None:
        self.btn_reload.setEnabled(not busy)
        self.btn_new.setEnabled(not busy)
        self.btn_save.setEnabled(not busy)
        self.btn_delete.setEnabled((not busy) and self._selected_id is not None)
        self.btn_long_history.setEnabled((not busy) and self._selected_id is not None and not self._history_is_running())
        self.table.setEnabled(not busy)
        self.lbl_status.setText(status if busy else self.lbl_status.text())

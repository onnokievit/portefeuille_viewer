from __future__ import annotations

from PySide6.QtCore import Qt, QDate, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from portefeuille_viewer.data.cash_management_repository import (
    delete_cash_management_entry,
    list_cash_management_entries,
    upsert_cash_management_entry,
)
from portefeuille_viewer.data import repository as data_repository


BROKERS = ["degiro", "interactive", "lynx"]
ENTRY_TYPES = ["deposit", "withdrawal", "fx_conversion_in", "fx_conversion_out"]


class _CashEntriesLoadWorker(QThread):
    loaded = Signal(list)
    error = Signal(str)

    def run(self) -> None:
        try:
            rows = list_cash_management_entries(limit=3000)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.loaded.emit(rows)


class _CashEntriesSaveWorker(QThread):
    done = Signal(int)
    error = Signal(str)

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self._payload = payload

    def run(self) -> None:
        try:
            row_id = upsert_cash_management_entry(self._payload)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(row_id)


class _CashEntriesDeleteWorker(QThread):
    done = Signal()
    error = Signal(str)

    def __init__(self, entry_id: int, parent=None):
        super().__init__(parent)
        self._entry_id = int(entry_id)

    def run(self) -> None:
        try:
            delete_cash_management_entry(self._entry_id)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit()


class CashManagementEntriesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cash Mutaties")
        self.resize(1280, 780)
        self._selected_id: int | None = None
        self._current_rows: list[dict] = []
        self._load_worker = None
        self._save_worker = None
        self._delete_worker = None

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Beheer cash mutaties. Selecteer een rij om te wijzigen of maak een nieuw record."))
        self.lbl_database = QLabel(self)
        root.addWidget(self.lbl_database)
        self.lbl_status = QLabel("", self)
        root.addWidget(self.lbl_status)

        self.table = QTableWidget(self)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["id", "datum", "broker", "type", "amount", "currency", "fx_rate", "transfer_group"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        root.addWidget(self.table, 1)

        form_wrap = QGridLayout()
        root.addLayout(form_wrap)

        left_form = QFormLayout()
        right_form = QFormLayout()
        form_wrap.addLayout(left_form, 0, 0)
        form_wrap.addLayout(right_form, 0, 1)

        self.input_datum = QDateEdit(self)
        self.input_datum.setCalendarPopup(True)
        self.input_datum.setDisplayFormat("dd-MM-yyyy")
        self.input_datum.setDate(QDate.currentDate())
        left_form.addRow("Datum", self.input_datum)

        self.input_broker = QComboBox(self)
        self.input_broker.addItems(BROKERS)
        left_form.addRow("Broker", self.input_broker)

        self.input_type = QComboBox(self)
        self.input_type.addItems(ENTRY_TYPES)
        left_form.addRow("Type", self.input_type)

        self.input_amount = QDoubleSpinBox(self)
        self.input_amount.setDecimals(2)
        self.input_amount.setRange(-1_000_000_000, 1_000_000_000)
        self.input_amount.setSingleStep(100.0)
        right_form.addRow("Amount", self.input_amount)

        self.input_currency = QLineEdit(self)
        self.input_currency.setText("EUR")
        right_form.addRow("Currency", self.input_currency)

        self.input_fx_rate = QDoubleSpinBox(self)
        self.input_fx_rate.setDecimals(6)
        self.input_fx_rate.setRange(0, 1_000_000)
        self.input_fx_rate.setSingleStep(0.01)
        self.input_fx_rate.setSpecialValueText("")
        right_form.addRow("FX rate", self.input_fx_rate)

        self.input_transfer_group = QLineEdit(self)
        right_form.addRow("Transfer group", self.input_transfer_group)

        self.input_comment = QTextEdit(self)
        self.input_comment.setFixedHeight(90)
        root.addWidget(QLabel("Comment"))
        root.addWidget(self.input_comment)

        buttons = QHBoxLayout()
        root.addLayout(buttons)
        self.btn_new = QPushButton("Nieuw", self)
        self.btn_save = QPushButton("Opslaan", self)
        self.btn_delete = QPushButton("Verwijderen", self)
        self.btn_reset = QPushButton("Reset", self)
        self.btn_close = QPushButton("Sluiten", self)
        for btn in (self.btn_new, self.btn_save, self.btn_delete, self.btn_reset, self.btn_close):
            buttons.addWidget(btn)
        buttons.addStretch(1)

        self.btn_new.clicked.connect(self._new_entry)
        self.btn_save.clicked.connect(self._save_entry)
        self.btn_delete.clicked.connect(self._delete_entry)
        self.btn_reset.clicked.connect(self._reset_form)
        self.btn_close.clicked.connect(self.close)

        self._reset_form()
        self.reload()

    def reload(self) -> None:
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        self.lbl_database.setText(f"Database: {data_repository.db_path}")
        self._set_busy(True, "Laden...")
        self._load_worker = _CashEntriesLoadWorker(self)
        self._load_worker.loaded.connect(self._on_rows_loaded)
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.finished.connect(self._on_load_finished)
        self._load_worker.start()

    def _on_rows_loaded(self, rows: list) -> None:
        self._current_rows = list(rows or [])
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.clearContents()
            self.table.setRowCount(len(self._current_rows))
            for row_idx, row in enumerate(self._current_rows):
                values = [
                    row.get("id"),
                    self._fmt_datetime(row.get("datum")),
                    row.get("broker", ""),
                    row.get("entry_type", ""),
                    self._fmt_number(row.get("amount")),
                    row.get("currency_code", ""),
                    self._fmt_number(row.get("fx_rate")),
                    row.get("transfer_group", ""),
                ]
                for col_idx, value in enumerate(values):
                    item = QTableWidgetItem("" if value is None else str(value))
                    self.table.setItem(row_idx, col_idx, item)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
        self.table.resizeColumnsToContents()
        self.btn_delete.setEnabled(self._selected_id is not None)
        self.lbl_status.setText(f"Rijen geladen: {len(self._current_rows)}")

    def _on_load_error(self, message: str) -> None:
        self.lbl_status.setText(f"Laden mislukt: {message}")
        QMessageBox.warning(self, "Cash mutaties", f"Laden mislukt: {message}")

    def _on_load_finished(self) -> None:
        self._load_worker = None
        self._set_busy(False)

    def _fmt_datetime(self, value) -> str:
        if value is None:
            return ""
        if hasattr(value, "strftime"):
            return value.strftime("%d-%m-%Y")
        return str(value)

    def _fmt_number(self, value) -> str:
        if value in (None, ""):
            return ""
        try:
            return f"{float(value):.2f}"
        except Exception:
            return str(value)

    def _on_table_selection_changed(self) -> None:
        row_idx = self.table.currentRow()
        if row_idx < 0 or row_idx >= len(self._current_rows):
            return
        row = self._current_rows[row_idx]
        self._selected_id = int(row["id"])
        self._load_form(row)
        self.btn_delete.setEnabled(True)

    def _load_form(self, row: dict) -> None:
        datum = row.get("datum")
        if hasattr(datum, "date"):
            datum = datum.date()
        if datum is None:
            self.input_datum.setDate(QDate.currentDate())
        else:
            self.input_datum.setDate(QDate(datum.year, datum.month, datum.day))
        self._set_combo_value(self.input_broker, str(row.get("broker") or "").lower())
        self._set_combo_value(self.input_type, str(row.get("entry_type") or "").lower())
        self.input_amount.setValue(float(row.get("amount") or 0.0))
        self.input_currency.setText(str(row.get("currency_code") or "EUR"))
        fx_rate = row.get("fx_rate")
        self.input_fx_rate.setValue(float(fx_rate or 0.0))
        self.input_transfer_group.setText(str(row.get("transfer_group") or ""))
        self.input_comment.setPlainText(str(row.get("comment_text") or ""))

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        idx = combo.findText(value, Qt.MatchFixedString)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _new_entry(self) -> None:
        self.table.clearSelection()
        self._reset_form()

    def _reset_form(self) -> None:
        self._selected_id = None
        self.input_datum.setDate(QDate.currentDate())
        self.input_broker.setCurrentIndex(0)
        self.input_type.setCurrentIndex(0)
        self.input_amount.setValue(0.0)
        self.input_currency.setText("EUR")
        self.input_fx_rate.setValue(0.0)
        self.input_transfer_group.clear()
        self.input_comment.clear()
        self.btn_delete.setEnabled(False)

    def _save_entry(self) -> None:
        if self._save_worker is not None and self._save_worker.isRunning():
            return
        broker = self.input_broker.currentText().strip().lower()
        payload = {
            "id": self._selected_id,
            "datum": self.input_datum.date().toPython(),
            "broker": broker,
            "account_name": broker,
            "entry_type": self.input_type.currentText().strip().lower(),
            "amount": self.input_amount.value(),
            "currency_code": self.input_currency.text().strip().upper() or "EUR",
            "fx_rate": self.input_fx_rate.value() if self.input_fx_rate.value() > 0 else None,
            "transfer_group": self.input_transfer_group.text().strip(),
            "comment_text": self.input_comment.toPlainText().strip(),
        }
        self._set_busy(True, "Opslaan...")
        self._save_worker = _CashEntriesSaveWorker(payload, self)
        self._save_worker.done.connect(self._on_save_done)
        self._save_worker.error.connect(self._on_save_error)
        self._save_worker.finished.connect(self._on_save_finished)
        self._save_worker.start()

    def _on_save_done(self, row_id: int) -> None:
        self._selected_id = int(row_id)
        self.lbl_status.setText("Record opgeslagen. Tabel vernieuwen...")
        self.reload()

    def _on_save_error(self, message: str) -> None:
        QMessageBox.warning(self, "Cash mutaties", f"Opslaan mislukt: {message}")

    def _on_save_finished(self) -> None:
        self._save_worker = None
        self._set_busy(False)

    def _delete_entry(self) -> None:
        if self._selected_id is None:
            return
        if self._delete_worker is not None and self._delete_worker.isRunning():
            return
        answer = QMessageBox.question(
            self,
            "Cash mutaties",
            "Geselecteerd record verwijderen?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._set_busy(True, "Verwijderen...")
        self._delete_worker = _CashEntriesDeleteWorker(self._selected_id, self)
        self._delete_worker.done.connect(self._on_delete_done)
        self._delete_worker.error.connect(self._on_delete_error)
        self._delete_worker.finished.connect(self._on_delete_finished)
        self._delete_worker.start()

    def _on_delete_done(self) -> None:
        self._reset_form()
        self.lbl_status.setText("Record verwijderd. Tabel vernieuwen...")
        self.reload()

    def _on_delete_error(self, message: str) -> None:
        QMessageBox.warning(self, "Cash mutaties", f"Verwijderen mislukt: {message}")

    def _on_delete_finished(self) -> None:
        self._delete_worker = None
        self._set_busy(False)

    def _set_busy(self, busy: bool, status: str = "") -> None:
        self.btn_new.setEnabled(not busy)
        self.btn_save.setEnabled(not busy)
        self.btn_delete.setEnabled((not busy) and self._selected_id is not None)
        self.btn_reset.setEnabled(not busy)
        self.btn_close.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self.lbl_status.setText(status if busy else self.lbl_status.text())
        self.setWindowTitle("Cash Mutaties" + (f" - {status}" if busy and status else ""))


_CASH_MANAGEMENT_ENTRIES_DIALOG_INSTANCE: CashManagementEntriesDialog | None = None


def open_cash_management_entries_dialog(parent=None) -> None:
    global _CASH_MANAGEMENT_ENTRIES_DIALOG_INSTANCE
    if _CASH_MANAGEMENT_ENTRIES_DIALOG_INSTANCE is None:
        _CASH_MANAGEMENT_ENTRIES_DIALOG_INSTANCE = CashManagementEntriesDialog(parent)
        _CASH_MANAGEMENT_ENTRIES_DIALOG_INSTANCE.destroyed.connect(
            lambda *_args: _clear_cash_management_entries_dialog_instance()
        )
    else:
        _CASH_MANAGEMENT_ENTRIES_DIALOG_INSTANCE.reload()
    _CASH_MANAGEMENT_ENTRIES_DIALOG_INSTANCE.show()
    _CASH_MANAGEMENT_ENTRIES_DIALOG_INSTANCE.raise_()
    _CASH_MANAGEMENT_ENTRIES_DIALOG_INSTANCE.activateWindow()


def _clear_cash_management_entries_dialog_instance() -> None:
    global _CASH_MANAGEMENT_ENTRIES_DIALOG_INSTANCE
    _CASH_MANAGEMENT_ENTRIES_DIALOG_INSTANCE = None

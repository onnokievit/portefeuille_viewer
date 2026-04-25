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

from portefeuille_viewer.data import repository as data_repository
from portefeuille_viewer.data.account_daily_balance_repository import (
    delete_account_daily_balance,
    list_account_daily_balances,
    upsert_account_daily_balance,
)


BROKERS = ["degiro", "interactive", "lynx"]
SOURCES = ["manual", "api"]


class _AccountBalancesLoadWorker(QThread):
    loaded = Signal(list)
    error = Signal(str)

    def run(self) -> None:
        try:
            rows = list_account_daily_balances(limit=3000)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.loaded.emit(rows)


class _AccountBalancesSaveWorker(QThread):
    done = Signal(int)
    error = Signal(str)

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self._payload = payload

    def run(self) -> None:
        try:
            row_id = upsert_account_daily_balance(self._payload)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(row_id)


class _AccountBalancesDeleteWorker(QThread):
    done = Signal()
    error = Signal(str)

    def __init__(self, balance_id: int, parent=None):
        super().__init__(parent)
        self._balance_id = int(balance_id)

    def run(self) -> None:
        try:
            delete_account_daily_balance(self._balance_id)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit()


class AccountDailyBalancesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dag-eindstanden")
        self.resize(1100, 720)
        self._selected_id: int | None = None
        self._current_rows: list[dict] = []
        self._load_worker = None
        self._save_worker = None
        self._delete_worker = None

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Beheer dagelijkse eindstand per broker. Selecteer een rij om te wijzigen."))
        root.addWidget(QLabel(f"Database: {data_repository.db_path}"))
        self.lbl_status = QLabel("", self)
        root.addWidget(self.lbl_status)

        tables_wrap = QHBoxLayout()
        root.addLayout(tables_wrap, 1)

        self.table = QTableWidget(self)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["id", "datum", "broker", "ending_balance", "currency", "source", "comment"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        tables_wrap.addWidget(self.table, 3)

        pivot_wrap = QVBoxLayout()
        tables_wrap.addLayout(pivot_wrap, 2)
        pivot_wrap.addWidget(QLabel("Laatste 10 dagen"))
        self.pivot_table = QTableWidget(self)
        self.pivot_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.pivot_table.setSelectionMode(QTableWidget.SingleSelection)
        self.pivot_table.setEditTriggers(QTableWidget.NoEditTriggers)
        pivot_wrap.addWidget(self.pivot_table, 1)

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

        self.input_ending_balance = QDoubleSpinBox(self)
        self.input_ending_balance.setDecimals(2)
        self.input_ending_balance.setRange(-1_000_000_000, 1_000_000_000)
        self.input_ending_balance.setSingleStep(100.0)
        right_form.addRow("Eindstand", self.input_ending_balance)

        self.input_currency = QLineEdit(self)
        self.input_currency.setText("EUR")
        right_form.addRow("Currency", self.input_currency)

        self.input_source = QComboBox(self)
        self.input_source.addItems(SOURCES)
        right_form.addRow("Source", self.input_source)

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

        self.btn_new.clicked.connect(self._new_balance)
        self.btn_save.clicked.connect(self._save_balance)
        self.btn_delete.clicked.connect(self._delete_balance)
        self.btn_reset.clicked.connect(self._reset_form)
        self.btn_close.clicked.connect(self.close)

        self._reset_form()
        self.reload()

    def reload(self) -> None:
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        self._set_busy(True, "Laden...")
        self._load_worker = _AccountBalancesLoadWorker(self)
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
                    self._fmt_number(row.get("ending_balance")),
                    row.get("currency_code", ""),
                    row.get("source_name", ""),
                    row.get("comment_text", ""),
                ]
                for col_idx, value in enumerate(values):
                    item = QTableWidgetItem("" if value is None else str(value))
                    self.table.setItem(row_idx, col_idx, item)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
        self.table.resizeColumnsToContents()
        self._refresh_pivot()
        self.btn_delete.setEnabled(self._selected_id is not None)
        self.lbl_status.setText(f"Rijen geladen: {len(self._current_rows)}")

    def _on_load_error(self, message: str) -> None:
        self.lbl_status.setText(f"Laden mislukt: {message}")
        QMessageBox.warning(self, "Dag-eindstanden", f"Laden mislukt: {message}")

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

    def _date_key(self, value) -> str:
        if value is None:
            return ""
        if hasattr(value, "date"):
            value = value.date()
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _refresh_pivot(self) -> None:
        date_keys = []
        brokers = set(BROKERS)
        values_by_date: dict[str, dict[str, float]] = {}

        for row in self._current_rows:
            date_key = self._date_key(row.get("datum"))
            broker = str(row.get("broker") or "").strip().lower()
            if not date_key or not broker:
                continue
            if date_key not in values_by_date:
                values_by_date[date_key] = {}
                date_keys.append(date_key)
            brokers.add(broker)
            if broker not in values_by_date[date_key]:
                try:
                    values_by_date[date_key][broker] = float(row.get("ending_balance") or 0.0)
                except Exception:
                    values_by_date[date_key][broker] = 0.0

        latest_dates = sorted(set(date_keys), reverse=True)[:10]
        ordered_brokers = [broker for broker in BROKERS if broker in brokers]
        ordered_brokers.extend(sorted(broker for broker in brokers if broker not in BROKERS))

        headers = ["datum", *ordered_brokers, "totaal"]
        self.pivot_table.setUpdatesEnabled(False)
        try:
            self.pivot_table.clearContents()
            self.pivot_table.setColumnCount(len(headers))
            self.pivot_table.setHorizontalHeaderLabels(headers)
            self.pivot_table.setRowCount(len(latest_dates))

            for row_idx, date_key in enumerate(latest_dates):
                display_date = self._fmt_pivot_date(date_key)
                self.pivot_table.setItem(row_idx, 0, QTableWidgetItem(display_date))
                total = 0.0
                for col_idx, broker in enumerate(ordered_brokers, start=1):
                    value = values_by_date.get(date_key, {}).get(broker)
                    if value is None:
                        text = ""
                    else:
                        total += value
                        text = self._fmt_number(value)
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.pivot_table.setItem(row_idx, col_idx, item)
                total_item = QTableWidgetItem(self._fmt_number(total))
                total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.pivot_table.setItem(row_idx, len(headers) - 1, total_item)
        finally:
            self.pivot_table.setUpdatesEnabled(True)
        self.pivot_table.resizeColumnsToContents()

    def _fmt_pivot_date(self, value: str) -> str:
        if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
            return f"{value[8:10]}-{value[5:7]}-{value[0:4]}"
        return value

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
        self.input_ending_balance.setValue(float(row.get("ending_balance") or 0.0))
        self.input_currency.setText(str(row.get("currency_code") or "EUR"))
        self._set_combo_value(self.input_source, str(row.get("source_name") or "manual").lower())
        self.input_comment.setPlainText(str(row.get("comment_text") or ""))

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        idx = combo.findText(value, Qt.MatchFixedString)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _new_balance(self) -> None:
        self.table.clearSelection()
        self._reset_form()

    def _reset_form(self) -> None:
        self._selected_id = None
        self.input_datum.setDate(QDate.currentDate())
        self.input_broker.setCurrentIndex(0)
        self.input_ending_balance.setValue(0.0)
        self.input_currency.setText("EUR")
        self.input_source.setCurrentIndex(0)
        self.input_comment.clear()
        self.btn_delete.setEnabled(False)

    def _save_balance(self) -> None:
        if self._save_worker is not None and self._save_worker.isRunning():
            return
        broker = self.input_broker.currentText().strip().lower()
        payload = {
            "id": self._selected_id,
            "datum": self.input_datum.date().toPython(),
            "broker": broker,
            "ending_balance": self.input_ending_balance.value(),
            "currency_code": self.input_currency.text().strip().upper() or "EUR",
            "source_name": self.input_source.currentText().strip().lower() or "manual",
            "comment_text": self.input_comment.toPlainText().strip(),
        }
        self._set_busy(True, "Opslaan...")
        self._save_worker = _AccountBalancesSaveWorker(payload, self)
        self._save_worker.done.connect(self._on_save_done)
        self._save_worker.error.connect(self._on_save_error)
        self._save_worker.finished.connect(self._on_save_finished)
        self._save_worker.start()

    def _on_save_done(self, row_id: int) -> None:
        self._selected_id = int(row_id)
        self.lbl_status.setText("Record opgeslagen. Tabel vernieuwen...")
        self.reload()

    def _on_save_error(self, message: str) -> None:
        QMessageBox.warning(self, "Dag-eindstanden", f"Opslaan mislukt: {message}")

    def _on_save_finished(self) -> None:
        self._save_worker = None
        self._set_busy(False)

    def _delete_balance(self) -> None:
        if self._selected_id is None:
            return
        if self._delete_worker is not None and self._delete_worker.isRunning():
            return
        answer = QMessageBox.question(
            self,
            "Dag-eindstanden",
            "Geselecteerd record verwijderen?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._set_busy(True, "Verwijderen...")
        self._delete_worker = _AccountBalancesDeleteWorker(self._selected_id, self)
        self._delete_worker.done.connect(self._on_delete_done)
        self._delete_worker.error.connect(self._on_delete_error)
        self._delete_worker.finished.connect(self._on_delete_finished)
        self._delete_worker.start()

    def _on_delete_done(self) -> None:
        self._reset_form()
        self.lbl_status.setText("Record verwijderd. Tabel vernieuwen...")
        self.reload()

    def _on_delete_error(self, message: str) -> None:
        QMessageBox.warning(self, "Dag-eindstanden", f"Verwijderen mislukt: {message}")

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
        self.pivot_table.setEnabled(not busy)
        self.lbl_status.setText(status if busy else self.lbl_status.text())
        self.setWindowTitle("Dag-eindstanden" + (f" - {status}" if busy and status else ""))


_ACCOUNT_DAILY_BALANCES_DIALOG_INSTANCE: AccountDailyBalancesDialog | None = None


def open_account_daily_balances_dialog(parent=None) -> None:
    global _ACCOUNT_DAILY_BALANCES_DIALOG_INSTANCE
    if _ACCOUNT_DAILY_BALANCES_DIALOG_INSTANCE is None:
        _ACCOUNT_DAILY_BALANCES_DIALOG_INSTANCE = AccountDailyBalancesDialog(parent)
        _ACCOUNT_DAILY_BALANCES_DIALOG_INSTANCE.destroyed.connect(
            lambda *_args: _clear_account_daily_balances_dialog_instance()
        )
    else:
        _ACCOUNT_DAILY_BALANCES_DIALOG_INSTANCE.reload()
    _ACCOUNT_DAILY_BALANCES_DIALOG_INSTANCE.show()
    _ACCOUNT_DAILY_BALANCES_DIALOG_INSTANCE.raise_()
    _ACCOUNT_DAILY_BALANCES_DIALOG_INSTANCE.activateWindow()


def _clear_account_daily_balances_dialog_instance() -> None:
    global _ACCOUNT_DAILY_BALANCES_DIALOG_INSTANCE
    _ACCOUNT_DAILY_BALANCES_DIALOG_INSTANCE = None

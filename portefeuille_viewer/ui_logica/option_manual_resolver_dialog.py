from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class OptionManualResolverDialog(QDialog):
    def __init__(self, option_timevalue_service, unresolved_items: list[dict[str, Any]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Handmatige Optie Resolve")
        self.resize(1100, 560)
        self._svc = option_timevalue_service
        self._unresolved_items = unresolved_items or []
        self._candidates: list[dict[str, Any]] = []

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Selecteer unresolved serie en kies daarna een kandidaat-contract."))

        split = QHBoxLayout()
        root.addLayout(split, 1)

        left = QVBoxLayout()
        split.addLayout(left, 0)
        left.addWidget(QLabel("Unresolved series"))
        self.lst_unresolved = QListWidget(self)
        left.addWidget(self.lst_unresolved, 1)

        right = QVBoxLayout()
        split.addLayout(right, 1)
        self.lbl_selected = QLabel("-", self)
        right.addWidget(self.lbl_selected)
        self.btn_load_candidates = QPushButton("Laad kandidaten", self)
        right.addWidget(self.btn_load_candidates, 0, Qt.AlignmentFlag.AlignLeft)
        self.tbl_candidates = QTableWidget(self)
        self.tbl_candidates.setColumnCount(9)
        self.tbl_candidates.setHorizontalHeaderLabels(
            ["conid", "local_symbol", "trading_class", "exchange", "mult", "sec_type", "expiry", "symbol", "ccy"]
        )
        self.tbl_candidates.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_candidates.setSelectionMode(QTableWidget.SingleSelection)
        self.tbl_candidates.setEditTriggers(QTableWidget.NoEditTriggers)
        right.addWidget(self.tbl_candidates, 1)

        bottom = QHBoxLayout()
        root.addLayout(bottom)
        self.btn_apply = QPushButton("Schrijf naar master + lock", self)
        self.btn_close = QPushButton("Cancel", self)
        bottom.addWidget(self.btn_apply)
        bottom.addWidget(self.btn_close)
        bottom.addStretch(1)

        self.btn_close.clicked.connect(self.reject)
        self.btn_load_candidates.clicked.connect(self._load_candidates_for_selected)
        self.btn_apply.clicked.connect(self._apply_selected_candidate)
        self.lst_unresolved.currentRowChanged.connect(self._on_unresolved_row_changed)

        self._fill_unresolved()
        if self.lst_unresolved.count() > 0:
            self.lst_unresolved.setCurrentRow(0)

    def _fill_unresolved(self):
        self.lst_unresolved.clear()
        for item in self._unresolved_items:
            label = (
                f"{item.get('asset','')} {item.get('exp','')} {item.get('c_p','')} "
                f"{item.get('strike','')} {item.get('ccy','')} | {item.get('reason','')}"
            )
            w = QListWidgetItem(label)
            w.setData(Qt.UserRole, item)
            self.lst_unresolved.addItem(w)

    def _on_unresolved_row_changed(self, _row: int):
        item = self._current_unresolved_item()
        self._candidates = []
        self.tbl_candidates.setRowCount(0)
        if not item:
            self.lbl_selected.setText("-")
            return
        self.lbl_selected.setText(
            f"Geselecteerd: {item.get('asset','')} {item.get('exp','')} {item.get('c_p','')} "
            f"{item.get('strike','')} {item.get('ccy','')}"
        )

    def _current_unresolved_item(self) -> dict[str, Any] | None:
        it = self.lst_unresolved.currentItem()
        if not it:
            return None
        return it.data(Qt.UserRole)

    def _load_candidates_for_selected(self):
        unresolved = self._current_unresolved_item()
        if not unresolved:
            QMessageBox.information(self, "Resolver", "Selecteer eerst een unresolved serie.")
            return
        self.btn_load_candidates.setEnabled(False)
        try:
            self._candidates = self._svc.get_manual_resolve_candidates(unresolved)
        except Exception as exc:
            self._candidates = []
            QMessageBox.warning(self, "Resolver", f"Kandidaten laden mislukt: {exc}")
        finally:
            self.btn_load_candidates.setEnabled(True)
        self._render_candidates()

    def _render_candidates(self):
        self.tbl_candidates.setRowCount(len(self._candidates))
        for r, c in enumerate(self._candidates):
            vals = [
                c.get("conid", ""),
                c.get("local_symbol", ""),
                c.get("trading_class", ""),
                c.get("exchange_code", ""),
                c.get("multiplier", ""),
                c.get("sec_type", ""),
                c.get("last_trade_date", ""),
                c.get("underlying_symbol", ""),
                c.get("currency", ""),
            ]
            for i, v in enumerate(vals):
                self.tbl_candidates.setItem(r, i, QTableWidgetItem(str(v)))
        self.tbl_candidates.resizeColumnsToContents()
        if self.tbl_candidates.rowCount() > 0:
            self.tbl_candidates.selectRow(0)

    def _apply_selected_candidate(self):
        unresolved = self._current_unresolved_item()
        if not unresolved:
            QMessageBox.information(self, "Resolver", "Selecteer eerst een unresolved serie.")
            return
        row = self.tbl_candidates.currentRow()
        if row < 0 or row >= len(self._candidates):
            QMessageBox.information(self, "Resolver", "Selecteer eerst een kandidaat.")
            return
        candidate = self._candidates[row]
        ok, msg = self._svc.apply_manual_resolution(unresolved, candidate, lock_row=True)
        if not ok:
            QMessageBox.warning(self, "Resolver", msg)
            return
        QMessageBox.information(self, "Resolver", msg)
        cur = self.lst_unresolved.currentRow()
        self._unresolved_items.pop(cur)
        self._fill_unresolved()
        if self.lst_unresolved.count() <= 0:
            self.accept()
            return
        self.lst_unresolved.setCurrentRow(min(cur, self.lst_unresolved.count() - 1))

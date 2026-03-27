from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyodbc
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from state_engine.common import DEFAULT_DB_PATH

DEFAULT_REVIEW_DB_PATH = (
    r"C:\Users\onno\OneDrive\Beleggen\00-Archief\20250319 BACKUP - portefeuille database 02.03 - ONNO - kopie (2).accdb"
)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_cp(value: Any) -> str:
    cp = _clean(value).lower()
    if cp in {"c", "call"}:
        return "call"
    if cp in {"p", "put"}:
        return "put"
    return cp


@dataclass
class DoorrolOrderIssue:
    order_id: int
    rows: list[dict]
    cp_values: set[str]


def load_doorrol_rows(conn: pyodbc.Connection, table: str) -> list[dict]:
    sql = f"""
        SELECT
            Id,
            datum,
            broker,
            asset_rollup,
            transactie_type,
            transactie_aantal,
            optie_exp_date,
            optie_strike,
            optie_call_put,
            order_id,
            order_id_number,
            transactie_oorsprong
        FROM {table}
        WHERE order_id IS NOT NULL
          AND order_id <> 0
          AND transactie_oorsprong IS NOT NULL
          AND UCASE(TRIM(transactie_oorsprong)) = 'DOORROL'
          AND asset_type IS NOT NULL
          AND UCASE(TRIM(asset_type)) = 'OPTIE'
        ORDER BY order_id, order_id_number, Id
    """
    cur = conn.cursor()
    rows = cur.execute(sql).fetchall()
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in rows]


def find_orders_with_call_put_mix(rows: list[dict]) -> list[DoorrolOrderIssue]:
    by_order: dict[int, list[dict]] = {}
    for row in rows:
        try:
            order_id = int(row.get("order_id"))
        except Exception:
            continue
        by_order.setdefault(order_id, []).append(row)

    issues: list[DoorrolOrderIssue] = []
    for order_id, items in by_order.items():
        cp_values = {_normalize_cp(r.get("optie_call_put")) for r in items if _normalize_cp(r.get("optie_call_put"))}
        if "call" in cp_values and "put" in cp_values:
            issues.append(DoorrolOrderIssue(order_id=order_id, rows=items, cp_values=cp_values))

    issues.sort(key=lambda x: x.order_id)
    return issues


class IssueApplier:
    def __init__(self, conn: pyodbc.Connection, table: str, dry_run: bool) -> None:
        self.conn = conn
        self.table = table
        self.dry_run = dry_run
        self.approved = 0
        self.rejected = 0

    def approve(self, issue: DoorrolOrderIssue) -> int:
        if not self.dry_run:
            cur = self.conn.cursor()
            for row in issue.rows:
                cur.execute(
                    f"""
                    UPDATE {self.table}
                    SET transactie_oorsprong=NULL,
                        transactie_oorsprong_detail=NULL,
                        order_id=NULL,
                        order_id_number=NULL
                    WHERE Id=?
                    """,
                    (int(row["Id"]),),
                )
            self.conn.commit()
        self.approved += 1
        return issue.order_id

    def reject(self) -> None:
        self.rejected += 1


class ReviewWindow(QWidget):
    def __init__(self, issues: list[DoorrolOrderIssue], applier: IssueApplier) -> None:
        super().__init__()
        self.issues = issues
        self.applier = applier
        self.index = 0
        self.setWindowTitle("DOORROL call/put mix review")
        self.resize(1400, 520)

        layout = QVBoxLayout(self)
        self.lbl_progress = QLabel("")
        self.lbl_meta = QLabel("")
        self.tbl = QTableWidget(0, 10)
        self.tbl.setHorizontalHeaderLabels(
            [
                "Id",
                "order_id",
                "order_no",
                "datum",
                "broker",
                "asset",
                "type",
                "qty",
                "exp",
                "c/p",
            ]
        )
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl.setSelectionMode(QTableWidget.NoSelection)

        btns = QHBoxLayout()
        self.btn_prev = QPushButton("Vorige")
        self.btn_approve = QPushButton("Approve")
        self.btn_reject = QPushButton("Reject")
        self.btn_skip = QPushButton("Skip")
        self.btn_approve_all = QPushButton("Approve all rest")
        self.btn_close = QPushButton("Sluiten")
        for b in [self.btn_prev, self.btn_approve, self.btn_reject, self.btn_skip, self.btn_approve_all, self.btn_close]:
            btns.addWidget(b)

        layout.addWidget(self.lbl_progress)
        layout.addWidget(self.lbl_meta)
        layout.addWidget(self.tbl)
        layout.addLayout(btns)

        self.btn_prev.clicked.connect(self.prev_issue)
        self.btn_approve.clicked.connect(self.approve_current)
        self.btn_reject.clicked.connect(self.reject_current)
        self.btn_skip.clicked.connect(self.next_issue)
        self.btn_approve_all.clicked.connect(self.approve_all_rest)
        self.btn_close.clicked.connect(self.close)
        self.render()

    def _item(self, value: Any) -> QTableWidgetItem:
        return QTableWidgetItem("" if value is None else str(value))

    def render(self) -> None:
        total = len(self.issues)
        if total == 0:
            self.lbl_progress.setText("Geen DOORROL orders met call/put mix gevonden.")
            self.lbl_meta.setText("")
            self.tbl.setRowCount(0)
            self.btn_prev.setEnabled(False)
            self.btn_approve.setEnabled(False)
            self.btn_reject.setEnabled(False)
            self.btn_skip.setEnabled(False)
            self.btn_approve_all.setEnabled(False)
            return

        self.index = max(0, min(self.index, total - 1))
        issue = self.issues[self.index]
        cp_txt = ", ".join(sorted(issue.cp_values))
        self.lbl_progress.setText(
            f"Order {self.index + 1}/{total} | order_id={issue.order_id} | cp_mix={cp_txt} | approved={self.applier.approved} rejected={self.applier.rejected} | dry_run={self.applier.dry_run}"
        )
        self.lbl_meta.setText(
            "Approve actie: transactie_oorsprong, transactie_oorsprong_detail, order_id en order_id_number worden leeggemaakt voor alle regels in dit order."
        )

        rows = sorted(issue.rows, key=lambda x: (str(x.get("order_id_number")), int(x.get("Id", 0))))
        self.tbl.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.tbl.setItem(i, 0, self._item(row.get("Id")))
            self.tbl.setItem(i, 1, self._item(row.get("order_id")))
            self.tbl.setItem(i, 2, self._item(row.get("order_id_number")))
            self.tbl.setItem(i, 3, self._item(row.get("datum")))
            self.tbl.setItem(i, 4, self._item(row.get("broker")))
            self.tbl.setItem(i, 5, self._item(row.get("asset_rollup")))
            self.tbl.setItem(i, 6, self._item(row.get("transactie_type")))
            self.tbl.setItem(i, 7, self._item(row.get("transactie_aantal")))
            self.tbl.setItem(i, 8, self._item(row.get("optie_exp_date")))
            self.tbl.setItem(i, 9, self._item(row.get("optie_call_put")))
        self.tbl.resizeColumnsToContents()

    def next_issue(self) -> None:
        if self.index < len(self.issues) - 1:
            self.index += 1
        self.render()

    def prev_issue(self) -> None:
        if self.index > 0:
            self.index -= 1
        self.render()

    def approve_current(self) -> None:
        if not self.issues:
            return
        issue = self.issues[self.index]
        self.applier.approve(issue)
        self.next_issue()

    def reject_current(self) -> None:
        self.applier.reject()
        self.next_issue()

    def approve_all_rest(self) -> None:
        if not self.issues:
            return
        start = self.index
        for i in range(start, len(self.issues)):
            self.applier.approve(self.issues[i])
        self.index = len(self.issues) - 1
        self.render()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Review DOORROL orders met hetzelfde order_id die zowel call als put bevatten."
    )
    parser.add_argument("--db", default=DEFAULT_REVIEW_DB_PATH, help="Pad naar Access DB.")
    parser.add_argument("--table", default="transacties_bron_data_org", help="Brontransactie tabel.")
    parser.add_argument("--dry-run", action="store_true", help="Niet schrijven, alleen reviewen.")
    args = parser.parse_args()

    conn_str = r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + args.db
    conn = pyodbc.connect(conn_str)
    try:
        rows = load_doorrol_rows(conn=conn, table=args.table)
        issues = find_orders_with_call_put_mix(rows)

        print(f"Loaded DOORROL optie rows met order_id: {len(rows)}")
        print(f"Orders met call/put mix: {len(issues)}")
        app = QApplication([])
        applier = IssueApplier(conn=conn, table=args.table, dry_run=args.dry_run)
        w = ReviewWindow(issues=issues, applier=applier)
        w.show()
        return app.exec()
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

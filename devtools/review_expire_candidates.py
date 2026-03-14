from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyodbc
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from state_engine.common import DEFAULT_DB_PATH

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))




def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _clean(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except Exception:
        text = _clean(value).replace(",", ".")
        try:
            return float(text)
        except Exception:
            return 0.0


@dataclass
class ExpireCandidate:
    row: dict
    notes: list[str]


class ExpireFinder:
    def __init__(
        self,
        conn: pyodbc.Connection,
        table: str,
        price_zero_tol: float = 1e-9,
        exp_window_days: int = 2,
    ) -> None:
        self.conn = conn
        self.table = table
        self.price_zero_tol = price_zero_tol
        self.exp_window_days = max(0, int(exp_window_days))

    def load_rows(self) -> list[dict]:
        sql = f"""
            SELECT
                Id,
                datum,
                broker,
                asset_rollup,
                asset_type,
                transactie_type,
                transactie_aantal,
                transactie_prijs,
                optie_exp_date,
                optie_strike,
                optie_call_put,
                order_id,
                order_id_number,
                transactie_oorsprong,
                transactie_oorsprong_detail,
                uniek_id
            FROM {self.table}
            WHERE asset_type='optie'
              AND (order_id IS NULL OR order_id=0)
              AND (transactie_oorsprong IS NULL OR TRIM(transactie_oorsprong)='')
            ORDER BY datum, asset_rollup, Id
        """
        cur = self.conn.cursor()
        rows = cur.execute(sql).fetchall()
        cols = [c[0] for c in cur.description]
        out: list[dict] = []
        for row in rows:
            d = dict(zip(cols, row))
            d["datum_only"] = _to_date(d.get("datum"))
            d["exp_only"] = _to_date(d.get("optie_exp_date"))
            d["qty"] = to_float(d.get("transactie_aantal"))
            d["price"] = to_float(d.get("transactie_prijs"))
            d["asset_type"] = _clean(d.get("asset_type")).lower()
            d["transactie_type"] = _clean(d.get("transactie_type")).lower()
            out.append(d)
        return out

    def _has_assign_like_stock_match(self, option_row: dict) -> bool:
        # Uitsluiten als er op dezelfde dag + broker + asset een aandelen-transactie is
        # met gelijk absoluut aantal (typisch ASSIGN-patroon).
        sql = f"""
            SELECT COUNT(*)
            FROM {self.table}
            WHERE asset_type='aandeel'
              AND asset_rollup=?
              AND broker=?
              AND datum=?
              AND ABS(transactie_aantal)=?
        """
        params = (
            _clean(option_row.get("asset_rollup")),
            _clean(option_row.get("broker")),
            option_row.get("datum"),
            abs(to_float(option_row.get("transactie_aantal"))),
        )
        cur = self.conn.cursor()
        row = cur.execute(sql, params).fetchone()
        return bool(row and int(row[0] or 0) > 0)

    def find_candidates(self, rows: list[dict]) -> list[ExpireCandidate]:
        out: list[ExpireCandidate] = []
        for r in rows:
            if r.get("asset_type") != "optie":
                continue
            if r.get("transactie_type") != "koop":
                continue
            if r.get("qty", 0.0) <= 0:
                continue
            if abs(r.get("price", 0.0)) > self.price_zero_tol:
                continue
            datum = r.get("datum_only")
            exp = r.get("exp_only")
            if datum is None or exp is None:
                continue
            day_diff = abs((datum - exp).days)
            if day_diff > self.exp_window_days:
                continue
            if self._has_assign_like_stock_match(r):
                continue
            notes = [f"|datum-exp|={day_diff}d<=window({self.exp_window_days})", "geen tegenoverliggende aandelenmatch"]
            out.append(ExpireCandidate(row=r, notes=notes))
        return out


class ExpireApplier:
    def __init__(self, conn: pyodbc.Connection, table: str, dry_run: bool) -> None:
        self.conn = conn
        self.table = table
        self.dry_run = dry_run
        self.next_order_id = self._get_next_order_id()
        self.approved = 0
        self.rejected = 0

    def _get_next_order_id(self) -> int:
        cur = self.conn.cursor()
        row = cur.execute(f"SELECT MAX(order_id) FROM {self.table}").fetchone()
        if not row or row[0] is None:
            return 1
        return int(row[0]) + 1

    def approve(self, cand: ExpireCandidate) -> int:
        row_id = int(cand.row["Id"])
        order_id = self.next_order_id
        self.next_order_id += 1
        if not self.dry_run:
            cur = self.conn.cursor()
            cur.execute(
                f"""
                UPDATE {self.table}
                SET order_id=?,
                    order_id_number=1,
                    transactie_oorsprong='EXPIRE'
                WHERE Id=?
                """,
                (order_id, row_id),
            )
            self.conn.commit()
        self.approved += 1
        return order_id

    def reject(self) -> None:
        self.rejected += 1


class ReviewWindow(QWidget):
    def __init__(self, cands: list[ExpireCandidate], applier: ExpireApplier) -> None:
        super().__init__()
        self.cands = cands
        self.applier = applier
        self.index = 0

        self.setWindowTitle("EXPIRE kandidaat review")
        self.resize(1200, 380)
        layout = QVBoxLayout(self)
        self.lbl_progress = QLabel("")
        self.lbl_meta = QLabel("")
        self.tbl = QTableWidget(1, 12)
        self.tbl.setHorizontalHeaderLabels(
            [
                "Id",
                "datum",
                "broker",
                "asset",
                "transactie_type",
                "qty",
                "price",
                "exp",
                "strike",
                "c/p",
                "oorsprong",
                "notes",
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

        self.btn_prev.clicked.connect(self.prev_item)
        self.btn_approve.clicked.connect(self.approve_current)
        self.btn_reject.clicked.connect(self.reject_current)
        self.btn_skip.clicked.connect(self.next_item)
        self.btn_approve_all.clicked.connect(self.approve_all_rest)
        self.btn_close.clicked.connect(self.close)

        self.render()

    def _item(self, txt: Any) -> QTableWidgetItem:
        return QTableWidgetItem("" if txt is None else str(txt))

    def render(self) -> None:
        total = len(self.cands)
        if total == 0:
            self.lbl_progress.setText("Geen EXPIRE kandidaten gevonden.")
            self.lbl_meta.setText("")
            self.tbl.clearContents()
            self.btn_prev.setEnabled(False)
            self.btn_approve.setEnabled(False)
            self.btn_reject.setEnabled(False)
            self.btn_skip.setEnabled(False)
            self.btn_approve_all.setEnabled(False)
            return
        if self.index < 0:
            self.index = 0
        if self.index >= total:
            self.index = total - 1
        c = self.cands[self.index]
        r = c.row
        self.lbl_progress.setText(
            f"Kandidaat {self.index + 1}/{total} | approved={self.applier.approved} rejected={self.applier.rejected} | dry_run={self.applier.dry_run}"
        )
        self.lbl_meta.setText("Regels: optie koop, qty>0, prijs=0, exp binnen marge rond datum, geen aandelenmatch.")

        self.tbl.setItem(0, 0, self._item(r.get("Id")))
        self.tbl.setItem(0, 1, self._item(r.get("datum_only")))
        self.tbl.setItem(0, 2, self._item(r.get("broker")))
        self.tbl.setItem(0, 3, self._item(r.get("asset_rollup")))
        self.tbl.setItem(0, 4, self._item(r.get("transactie_type")))
        self.tbl.setItem(0, 5, self._item(r.get("qty")))
        self.tbl.setItem(0, 6, self._item(r.get("price")))
        self.tbl.setItem(0, 7, self._item(r.get("exp_only")))
        self.tbl.setItem(0, 8, self._item(r.get("optie_strike")))
        self.tbl.setItem(0, 9, self._item(r.get("optie_call_put")))
        self.tbl.setItem(0, 10, self._item(r.get("transactie_oorsprong")))
        self.tbl.setItem(0, 11, self._item(", ".join(c.notes)))
        self.tbl.resizeColumnsToContents()

    def next_item(self) -> None:
        if self.index < len(self.cands) - 1:
            self.index += 1
        self.render()

    def prev_item(self) -> None:
        if self.index > 0:
            self.index -= 1
        self.render()

    def approve_current(self) -> None:
        if not self.cands:
            return
        c = self.cands[self.index]
        order_id = self.applier.approve(c)
        mode = "DRY-RUN: would write" if self.applier.dry_run else "Weggeschreven"
        QMessageBox.information(self, "EXPIRE", f"{mode} met order_id={order_id} (Id {c.row['Id']})")
        self.next_item()

    def reject_current(self) -> None:
        self.applier.reject()
        self.next_item()

    def approve_all_rest(self) -> None:
        if not self.cands:
            return
        start = self.index
        for i in range(start, len(self.cands)):
            self.applier.approve(self.cands[i])
        QMessageBox.information(
            self,
            "EXPIRE",
            f"Alle resterende kandidaten verwerkt vanaf {start + 1}. approved={self.applier.approved}",
        )
        self.index = len(self.cands) - 1
        self.render()


def main() -> int:
    parser = argparse.ArgumentParser(description="Vind en review EXPIRE-kandidaten in transacties.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Pad naar Access DB.")
    parser.add_argument("--table", default="transacties_bron_data_org", help="Brontransactie tabel.")
    parser.add_argument("--dry-run", action="store_true", help="Niet schrijven, alleen reviewen.")
    parser.add_argument("--price-zero-tol", type=float, default=1e-9, help="Absolute tolerantie voor optie prijs == 0.")
    parser.add_argument("--exp-window-days", type=int, default=2, help="Toegestane afwijking in dagen tussen transactie datum en optie_exp_date.")
    args = parser.parse_args()

    conn_str = r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + args.db
    conn = pyodbc.connect(conn_str)
    finder = ExpireFinder(
        conn=conn,
        table=args.table,
        price_zero_tol=args.price_zero_tol,
        exp_window_days=args.exp_window_days,
    )
    rows = finder.load_rows()
    cands = finder.find_candidates(rows)
    print(f"Loaded rows: {len(rows)} | EXPIRE candidates: {len(cands)}")

    app = QApplication([])
    applier = ExpireApplier(conn=conn, table=args.table, dry_run=args.dry_run)
    w = ReviewWindow(cands=cands, applier=applier)
    w.show()
    rc = app.exec()
    conn.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

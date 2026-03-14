from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
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


def _norm_dec_for_id(x) -> str:
    if x is None:
        return ""
    if isinstance(x, Decimal):
        x = float(x)
    s = str(x).strip().replace(",", ".")
    try:
        f = float(s)
        return str(int(f)) if f.is_integer() else f"{f}".rstrip("0").rstrip(".")
    except ValueError:
        return s


def _date_for_id(x) -> str:
    d = _to_date(x)
    return d.isoformat() if d else ""


def build_uniek_id_like_repository(values: dict) -> str:
    broker = _clean(values.get("broker"))
    at = _clean(values.get("asset_type")).lower()
    if at == "optie":
        rollup = _clean(values.get("asset_rollup"))
        exp = _date_for_id(values.get("optie_exp_date"))
        cp = _clean(values.get("optie_call_put")).lower()
        strike = _norm_dec_for_id(values.get("optie_strike"))
        return f"{broker}-{rollup}-{at}-{exp}-{cp}-{strike}"
    if at == "aandeel":
        return f"{broker}-{_clean(values.get('asset_rollup'))}-aandeel"
    return f"{broker}-{_clean(values.get('asset_rollup'))}-{at}"


@dataclass
class AssignPair:
    option_row: dict
    stock_row: dict
    score: float
    notes: list[str]


class AssignFinder:
    def __init__(
        self,
        conn: pyodbc.Connection,
        table: str,
        price_zero_tol: float = 1e-9,
        strike_match_tol: float = 1e-6,
    ) -> None:
        self.conn = conn
        self.table = table
        self.price_zero_tol = price_zero_tol
        self.strike_match_tol = strike_match_tol

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
            WHERE (asset_type='optie' OR asset_type='aandeel')
              AND (order_id IS NULL OR order_id=0)
              AND (transactie_oorsprong IS NULL OR TRIM(transactie_oorsprong)='')
            ORDER BY datum, asset_rollup, Id
        """
        cur = self.conn.cursor()
        rows = cur.execute(sql).fetchall()
        columns = [c[0] for c in cur.description]
        out: list[dict] = []
        for row in rows:
            d = dict(zip(columns, row))
            d["datum_only"] = _to_date(d.get("datum"))
            d["qty"] = to_float(d.get("transactie_aantal"))
            d["qty_abs"] = abs(d["qty"])
            d["price"] = to_float(d.get("transactie_prijs"))
            d["cp"] = _clean(d.get("optie_call_put")).lower()
            d["asset_type"] = _clean(d.get("asset_type")).lower()
            out.append(d)
        return out

    def find_candidates(self, rows: list[dict]) -> list[AssignPair]:
        groups: dict[tuple, list[dict]] = {}
        for r in rows:
            if r.get("datum_only") is None:
                continue
            key = (r["datum_only"], _clean(r.get("asset_rollup")).upper(), _clean(r.get("broker")).lower())
            groups.setdefault(key, []).append(r)

        pairs: list[AssignPair] = []
        used_ids: set[int] = set()

        for _key, bucket in groups.items():
            opts = [r for r in bucket if r.get("asset_type") == "optie" and int(r["Id"]) not in used_ids]
            stocks = [r for r in bucket if r.get("asset_type") == "aandeel" and int(r["Id"]) not in used_ids]
            if not opts or not stocks:
                continue

            for op in sorted(opts, key=lambda x: int(x["Id"])):
                if int(op["Id"]) in used_ids:
                    continue
                if not math.isclose(op.get("price", 0.0), 0.0, abs_tol=self.price_zero_tol):
                    continue
                cp = op.get("cp")
                if cp not in {"call", "put"}:
                    continue

                best: AssignPair | None = None
                for st in stocks:
                    if int(st["Id"]) in used_ids:
                        continue
                    if op.get("qty_abs", 0.0) <= 0 or st.get("qty_abs", 0.0) <= 0:
                        continue
                    if not math.isclose(op["qty_abs"], st["qty_abs"], rel_tol=1e-9, abs_tol=1e-9):
                        continue
                    ok_sign, sign_note = self._sign_rule_ok(cp, op.get("qty", 0.0), st.get("qty", 0.0))
                    if not ok_sign:
                        continue
                    strike = to_float(op.get("optie_strike"))
                    stock_price = to_float(st.get("transactie_prijs"))
                    if not math.isclose(strike, stock_price, abs_tol=self.strike_match_tol, rel_tol=0.0):
                        continue
                    score, notes = self._score_pair(op, st, sign_note)
                    cand = AssignPair(option_row=op, stock_row=st, score=score, notes=notes)
                    if best is None or cand.score > best.score:
                        best = cand
                if best is not None:
                    pairs.append(best)
                    used_ids.add(int(best.option_row["Id"]))
                    used_ids.add(int(best.stock_row["Id"]))

        pairs.sort(key=lambda p: (-p.score, p.option_row["datum_only"], p.option_row["asset_rollup"], p.option_row["Id"]))
        return pairs

    def _sign_rule_ok(self, cp: str, qty_option: float, qty_stock: float) -> tuple[bool, str]:
        # Volgens jouw beschrijving:
        # call assign -> optie qty positief, aandelen qty negatief
        # put assign -> optie qty positief, aandelen qty positief
        if cp == "call":
            return (qty_option > 0 and qty_stock < 0), "call-sign"
        if cp == "put":
            return (qty_option > 0 and qty_stock > 0), "put-sign"
        return False, "unknown-sign"

    def _score_pair(self, op: dict, st: dict, sign_note: str) -> tuple[float, list[str]]:
        score = 0.0
        notes: list[str] = [sign_note]

        strike = to_float(op.get("optie_strike"))
        stock_price = to_float(st.get("transactie_prijs"))
        if strike > 0 and stock_price > 0:
            diff = abs(strike - stock_price)
            if diff <= self.strike_match_tol:
                score += 3.0
                notes.append("stock prijs == strike")
            else:
                notes.append(f"prijs/strike diff={diff:.4f}")
        else:
            notes.append("geen strike/prijs check")

        ttype = _clean(op.get("transactie_type")).lower()
        cp = _clean(op.get("cp")).lower()
        if (cp == "call" and ttype == "verkoop") or (cp == "put" and ttype == "koop"):
            score += 1.5
            notes.append("transactie_type match hint")
        return score, notes


class AssignApplier:
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

    def approve(self, pair: AssignPair) -> int:
        order_id = self.next_order_id
        self.next_order_id += 1
        op = pair.option_row
        st = pair.stock_row
        uid_op = _clean(op.get("uniek_id")) or build_uniek_id_like_repository(op)
        uid_st = _clean(st.get("uniek_id")) or build_uniek_id_like_repository(st)

        if not self.dry_run:
            cur = self.conn.cursor()
            # Conventie: optie = order_id_number 1, aandeel = 2
            cur.execute(
                f"""
                UPDATE {self.table}
                SET order_id=?,
                    order_id_number=1,
                    transactie_oorsprong='ASSIGN',
                    transactie_oorsprong_detail=?
                WHERE Id=?
                """,
                (order_id, uid_st, int(op["Id"])),
            )
            cur.execute(
                f"""
                UPDATE {self.table}
                SET order_id=?,
                    order_id_number=2,
                    transactie_oorsprong='ASSIGN',
                    transactie_oorsprong_detail=?
                WHERE Id=?
                """,
                (order_id, uid_op, int(st["Id"])),
            )
            self.conn.commit()

        self.approved += 1
        return order_id

    def reject(self) -> None:
        self.rejected += 1


class ReviewWindow(QWidget):
    def __init__(self, pairs: list[AssignPair], applier: AssignApplier) -> None:
        super().__init__()
        self.pairs = pairs
        self.applier = applier
        self.index = 0

        self.setWindowTitle("ASSIGN kandidaat review")
        self.resize(1300, 430)
        layout = QVBoxLayout(self)
        self.lbl_progress = QLabel("")
        self.lbl_meta = QLabel("")
        self.tbl = QTableWidget(2, 13)
        self.tbl.setHorizontalHeaderLabels(
            [
                "Id",
                "asset_type",
                "datum",
                "broker",
                "asset",
                "transactie_type",
                "qty",
                "price",
                "exp",
                "strike",
                "c/p",
                "score",
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

        self.btn_prev.clicked.connect(self.prev_pair)
        self.btn_approve.clicked.connect(self.approve_current)
        self.btn_reject.clicked.connect(self.reject_current)
        self.btn_skip.clicked.connect(self.next_pair)
        self.btn_approve_all.clicked.connect(self.approve_all_rest)
        self.btn_close.clicked.connect(self.close)

        self.render()

    def _item(self, txt: Any) -> QTableWidgetItem:
        return QTableWidgetItem("" if txt is None else str(txt))

    def render(self) -> None:
        total = len(self.pairs)
        if total == 0:
            self.lbl_progress.setText("Geen ASSIGN kandidaten gevonden.")
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
        p = self.pairs[self.index]
        self.lbl_progress.setText(
            f"Kandidaat {self.index + 1}/{total} | approved={self.applier.approved} rejected={self.applier.rejected} | dry_run={self.applier.dry_run}"
        )
        self.lbl_meta.setText(
            "Regels: zelfde datum+asset+broker, optie prijs=0, optie/aandeel qty gelijk, call/put signregel."
        )
        rows = [p.option_row, p.stock_row]
        for r, row in enumerate(rows):
            self.tbl.setItem(r, 0, self._item(row.get("Id")))
            self.tbl.setItem(r, 1, self._item(row.get("asset_type")))
            self.tbl.setItem(r, 2, self._item(row.get("datum_only")))
            self.tbl.setItem(r, 3, self._item(row.get("broker")))
            self.tbl.setItem(r, 4, self._item(row.get("asset_rollup")))
            self.tbl.setItem(r, 5, self._item(row.get("transactie_type")))
            self.tbl.setItem(r, 6, self._item(row.get("qty")))
            self.tbl.setItem(r, 7, self._item(row.get("price")))
            self.tbl.setItem(r, 8, self._item(_to_date(row.get("optie_exp_date"))))
            self.tbl.setItem(r, 9, self._item(row.get("optie_strike")))
            self.tbl.setItem(r, 10, self._item(row.get("cp")))
            self.tbl.setItem(r, 11, self._item(f"{p.score:.2f}" if r == 0 else ""))
            self.tbl.setItem(r, 12, self._item(", ".join(p.notes) if r == 0 else ""))
        self.tbl.resizeColumnsToContents()

    def next_pair(self) -> None:
        if self.index < len(self.pairs) - 1:
            self.index += 1
        self.render()

    def prev_pair(self) -> None:
        if self.index > 0:
            self.index -= 1
        self.render()

    def approve_current(self) -> None:
        if not self.pairs:
            return
        p = self.pairs[self.index]
        order_id = self.applier.approve(p)
        mode = "DRY-RUN: would write" if self.applier.dry_run else "Weggeschreven"
        QMessageBox.information(
            self,
            "ASSIGN",
            f"{mode} met order_id={order_id} (optie Id {p.option_row['Id']}, aandeel Id {p.stock_row['Id']})",
        )
        self.next_pair()

    def reject_current(self) -> None:
        self.applier.reject()
        self.next_pair()

    def approve_all_rest(self) -> None:
        if not self.pairs:
            return
        start = self.index
        for i in range(start, len(self.pairs)):
            self.applier.approve(self.pairs[i])
        QMessageBox.information(
            self,
            "ASSIGN",
            f"Alle resterende kandidaten verwerkt vanaf {start + 1}. approved={self.applier.approved}",
        )
        self.index = len(self.pairs) - 1
        self.render()


def main() -> int:
    parser = argparse.ArgumentParser(description="Vind en review ASSIGN-kandidaten in transacties.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Pad naar Access DB.")
    parser.add_argument("--table", default="transacties_bron_data_org", help="Brontransactie tabel.")
    parser.add_argument("--dry-run", action="store_true", help="Niet schrijven, alleen reviewen.")
    parser.add_argument("--price-zero-tol", type=float, default=1e-9, help="Absolute tolerantie voor optie prijs == 0.")
    parser.add_argument("--strike-match-tol", type=float, default=1e-6, help="Absolute tolerantie voor aandeel prijs == optie strike.")
    args = parser.parse_args()

    conn_str = r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + args.db
    conn = pyodbc.connect(conn_str)
    finder = AssignFinder(
        conn=conn,
        table=args.table,
        price_zero_tol=args.price_zero_tol,
        strike_match_tol=args.strike_match_tol,
    )
    rows = finder.load_rows()
    pairs = finder.find_candidates(rows)
    print(f"Loaded rows: {len(rows)} | ASSIGN candidates: {len(pairs)}")

    app = QApplication([])
    applier = AssignApplier(conn=conn, table=args.table, dry_run=args.dry_run)
    w = ReviewWindow(pairs=pairs, applier=applier)
    w.show()
    rc = app.exec()
    conn.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

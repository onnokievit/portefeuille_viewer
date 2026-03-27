from __future__ import annotations

import argparse
import math
import re
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


def _asset_rollup_price_insensitive(value: Any) -> str:
    text = _clean(value).upper()
    if not text:
        return ""
    # Allow matching across different strike/price values by normalizing all numeric parts.
    return re.sub(r"\d+(?:[.,]\d+)?", "#", text)


def build_uniek_id_like_repository(values: dict) -> str:
    broker = _clean(values.get("broker"))
    at = _clean(values.get("asset_type")).lower()
    if at == "optie":
        rollup = _clean(values.get("asset_rollup"))
        exp = _date_for_id(values.get("optie_exp_date"))
        cp = _clean(values.get("optie_call_put")).lower()
        strike = _norm_dec_for_id(values.get("optie_strike"))
        return f"{broker}-{rollup}-{at}-{exp}-{cp}-{strike}"
    return f"{broker}-{_clean(values.get('asset_rollup'))}-{at}"


def normalize_side(row: dict) -> str:
    side = _clean(row.get("transactie_type")).lower()
    if side in {"koop", "buy"}:
        return "koop"
    if side in {"verkoop", "sell"}:
        return "verkoop"
    qty = to_float(row.get("transactie_aantal"))
    if qty > 0:
        return "koop"
    if qty < 0:
        return "verkoop"
    return ""


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
class CandidatePair:
    left: dict
    right: dict
    score: float
    notes: list[str]


class DoorrolFinder:
    def __init__(self, conn: pyodbc.Connection, table: str) -> None:
        self.conn = conn
        self.table = table

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
        columns = [c[0] for c in cur.description]
        out = []
        for row in rows:
            d = dict(zip(columns, row))
            d["datum_only"] = _to_date(d.get("datum"))
            d["qty"] = to_float(d.get("transactie_aantal"))
            d["qty_abs"] = abs(d["qty"])
            d["side"] = normalize_side(d)
            out.append(d)
        return out

    def find_candidates(self, rows: list[dict]) -> list[CandidatePair]:
        grouped: dict[tuple, list[dict]] = {}
        for row in rows:
            d = row.get("datum_only")
            exp = _to_date(row.get("optie_exp_date"))
            if d is None or exp is None:
                continue
            qty_abs = row.get("qty_abs", 0.0)
            if qty_abs <= 0:
                continue
            key = (d, _asset_rollup_price_insensitive(row.get("asset_rollup")), qty_abs)
            grouped.setdefault(key, []).append(row)

        pairs: list[CandidatePair] = []
        used_ids: set[int] = set()
        for _key, bucket in grouped.items():
            buys = [r for r in bucket if r.get("side") == "koop" and int(r.get("Id")) not in used_ids]
            sells = [r for r in bucket if r.get("side") == "verkoop" and int(r.get("Id")) not in used_ids]
            if not buys or not sells:
                continue
            for b in sorted(buys, key=lambda x: int(x.get("Id"))):
                if int(b.get("Id")) in used_ids:
                    continue
                best: CandidatePair | None = None
                for s in sells:
                    if int(s.get("Id")) in used_ids:
                        continue
                    if _clean(b.get("broker")).lower() != _clean(s.get("broker")).lower():
                        continue
                    score, notes = self._score_pair(b, s)
                    cand = CandidatePair(left=b, right=s, score=score, notes=notes)
                    if best is None or cand.score > best.score:
                        best = cand
                if best is not None:
                    pairs.append(best)
                    used_ids.add(int(best.left.get("Id")))
                    used_ids.add(int(best.right.get("Id")))

        pairs.sort(key=lambda p: (-p.score, p.left.get("datum_only"), p.left.get("asset_rollup"), p.left.get("Id")))
        return pairs

    def _score_pair(self, a: dict, b: dict) -> tuple[float, list[str]]:
        score = 0.0
        notes: list[str] = []

        if _clean(a.get("broker")).lower() == _clean(b.get("broker")).lower():
            score += 3.0
            notes.append("zelfde broker")
        else:
            notes.append("verschillende broker")

        if _clean(a.get("optie_call_put")).lower() == _clean(b.get("optie_call_put")).lower():
            score += 3.0
            notes.append("zelfde call/put")
        else:
            notes.append("verschillende call/put")

        strike_a = to_float(a.get("optie_strike"))
        strike_b = to_float(b.get("optie_strike"))
        strike_diff = abs(strike_a - strike_b)
        if math.isclose(strike_diff, 0.0, abs_tol=1e-9):
            score += 2.0
            notes.append("zelfde strike")
        else:
            score += max(0.0, 1.0 - min(strike_diff / 20.0, 1.0))
            notes.append(f"strike diff={strike_diff:.2f}")

        exp_a = _to_date(a.get("optie_exp_date"))
        exp_b = _to_date(b.get("optie_exp_date"))
        if exp_a and exp_b:
            day_diff = abs((exp_a - exp_b).days)
            score += max(0.0, 2.0 - min(day_diff / 365.0, 2.0))
            notes.append(f"expiry diff={day_diff}d")
        return score, notes


class DoorrolApplier:
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

    def approve(self, pair: CandidatePair) -> int:
        order_id = self.next_order_id
        self.next_order_id += 1

        a = pair.left
        b = pair.right
        uid_a = _clean(a.get("uniek_id")) or build_uniek_id_like_repository(a)
        uid_b = _clean(b.get("uniek_id")) or build_uniek_id_like_repository(b)
        rows = sorted([(int(a["Id"]), uid_b), (int(b["Id"]), uid_a)], key=lambda x: x[0])

        if not self.dry_run:
            cur = self.conn.cursor()
            for idx, (row_id, detail_uid) in enumerate(rows, start=1):
                cur.execute(
                    f"""
                    UPDATE {self.table}
                    SET order_id=?,
                        order_id_number=?,
                        transactie_oorsprong='DOORROL',
                        transactie_oorsprong_detail=?
                    WHERE Id=?
                    """,
                    (order_id, idx, detail_uid, row_id),
                )
            self.conn.commit()

        self.approved += 1
        return order_id

    def reject(self) -> None:
        self.rejected += 1


class ReviewWindow(QWidget):
    def __init__(self, pairs: list[CandidatePair], applier: DoorrolApplier) -> None:
        super().__init__()
        self.pairs = pairs
        self.applier = applier
        self.index = 0
        self.setWindowTitle("Doorrol kandidaat review")
        self.resize(1200, 420)

        layout = QVBoxLayout(self)
        self.lbl_progress = QLabel("")
        self.lbl_meta = QLabel("")
        self.tbl = QTableWidget(2, 11)
        self.tbl.setHorizontalHeaderLabels(
            [
                "Id",
                "datum",
                "broker",
                "asset",
                "side",
                "qty",
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
            self.lbl_progress.setText("Geen kandidaten gevonden.")
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
            "Regels: zelfde dag + asset (prijs mag verschillen) + abs qty, tegengesteld, expiry mag gelijk of verschillend zijn, order_id/origin nog leeg."
        )
        for r, row in enumerate([p.left, p.right]):
            self.tbl.setItem(r, 0, self._item(row.get("Id")))
            self.tbl.setItem(r, 1, self._item(row.get("datum_only")))
            self.tbl.setItem(r, 2, self._item(row.get("broker")))
            self.tbl.setItem(r, 3, self._item(row.get("asset_rollup")))
            self.tbl.setItem(r, 4, self._item(row.get("side")))
            self.tbl.setItem(r, 5, self._item(row.get("qty")))
            self.tbl.setItem(r, 6, self._item(_to_date(row.get("optie_exp_date"))))
            self.tbl.setItem(r, 7, self._item(row.get("optie_strike")))
            self.tbl.setItem(r, 8, self._item(row.get("optie_call_put")))
            self.tbl.setItem(r, 9, self._item(f"{p.score:.2f}" if r == 0 else ""))
            self.tbl.setItem(r, 10, self._item(", ".join(p.notes) if r == 0 else ""))
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
        self.applier.approve(p)
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
        self.index = len(self.pairs) - 1
        self.render()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Vind en review doorrol-optietransacties zonder order_id/transactie_oorsprong."
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Pad naar Access DB.")
    parser.add_argument("--table", default="transacties_bron_data_org", help="Brontransactie tabel.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Niet schrijven, alleen reviewen/tonen.",
    )
    args = parser.parse_args()

    conn_str = r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + args.db
    conn = pyodbc.connect(conn_str)
    finder = DoorrolFinder(conn=conn, table=args.table)
    rows = finder.load_rows()
    pairs = finder.find_candidates(rows)
    print(f"Loaded rows: {len(rows)} | candidates: {len(pairs)}")

    app = QApplication([])
    applier = DoorrolApplier(conn=conn, table=args.table, dry_run=args.dry_run)
    w = ReviewWindow(pairs=pairs, applier=applier)
    w.show()
    rc = app.exec()
    conn.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

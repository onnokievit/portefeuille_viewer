from __future__ import annotations

import argparse
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


def build_uniek_id_like_repository(values: dict) -> str:
    broker = _clean(values.get("broker"))
    at = _clean(values.get("asset_type")).lower()
    if at == "sprinter":
        detail = _clean(values.get("asset_detail"))
        return f"{broker}-{detail}-{at}"
    if at == "optie":
        rollup = _clean(values.get("asset_rollup"))
        exp = _to_date(values.get("optie_exp_date"))
        cp = _clean(values.get("optie_call_put")).lower()
        strike = _norm_dec_for_id(values.get("optie_strike"))
        exp_txt = exp.isoformat() if exp else ""
        return f"{broker}-{rollup}-{at}-{exp_txt}-{cp}-{strike}"
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


@dataclass
class SprinterDoorrolPair:
    left: dict
    right: dict
    score: float
    notes: list[str]


class Finder:
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
                asset_detail,
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
            WHERE asset_type='sprinter'
              AND (order_id IS NULL OR order_id=0)
              AND (transactie_oorsprong IS NULL OR TRIM(transactie_oorsprong)='')
            ORDER BY datum, broker, asset_rollup, asset_detail, Id
        """
        cur = self.conn.cursor()
        rows = cur.execute(sql).fetchall()
        cols = [c[0] for c in cur.description]
        out = []
        for row in rows:
            d = dict(zip(cols, row))
            d["datum_only"] = _to_date(d.get("datum"))
            d["exp_only"] = _to_date(d.get("optie_exp_date"))
            d["qty"] = to_float(d.get("transactie_aantal"))
            d["qty_abs"] = abs(d["qty"])
            d["side"] = normalize_side(d)
            d["cp"] = _clean(d.get("optie_call_put")).lower()
            d["strike_f"] = to_float(d.get("optie_strike"))
            out.append(d)
        return out

    def find_pairs(self, rows: list[dict]) -> list[SprinterDoorrolPair]:
        groups: dict[tuple, list[dict]] = {}
        for r in rows:
            if r.get("datum_only") is None or r.get("exp_only") is None:
                continue
            if r.get("cp") != "call":
                continue
            if r.get("qty_abs", 0.0) <= 0:
                continue
            key = (
                r["datum_only"],
                _clean(r.get("broker")).lower(),
                _clean(r.get("asset_rollup")).upper(),
                _clean(r.get("asset_detail")).upper(),
                r["qty_abs"],
                r["strike_f"],
            )
            groups.setdefault(key, []).append(r)

        used_ids: set[int] = set()
        out: list[SprinterDoorrolPair] = []
        for _key, bucket in groups.items():
            buys = [r for r in bucket if r.get("side") == "koop" and int(r["Id"]) not in used_ids]
            sells = [r for r in bucket if r.get("side") == "verkoop" and int(r["Id"]) not in used_ids]
            for b in sorted(buys, key=lambda x: int(x["Id"])):
                if int(b["Id"]) in used_ids:
                    continue
                best: SprinterDoorrolPair | None = None
                for s in sells:
                    if int(s["Id"]) in used_ids:
                        continue
                    # Expiry moet verschillend zijn (hard rule)
                    if b.get("exp_only") == s.get("exp_only"):
                        continue
                    score, notes = self._score(b, s)
                    cand = SprinterDoorrolPair(left=b, right=s, score=score, notes=notes)
                    if best is None or cand.score > best.score:
                        best = cand
                if best is not None:
                    out.append(best)
                    used_ids.add(int(best.left["Id"]))
                    used_ids.add(int(best.right["Id"]))
        out.sort(key=lambda p: (-p.score, p.left["datum_only"], p.left["broker"], p.left["asset_rollup"], p.left["Id"]))
        return out

    def _score(self, a: dict, b: dict) -> tuple[float, list[str]]:
        notes = ["zelfde dag/broker/asset/asset_detail", "call/call", "zelfde strike", "verschillende optie_exp_date"]
        day_diff = abs((a["exp_only"] - b["exp_only"]).days) if a.get("exp_only") and b.get("exp_only") else 0
        score = 10.0 + min(day_diff / 30.0, 2.0)
        notes.append(f"expiry diff={day_diff}d")
        return score, notes


class Applier:
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

    def approve(self, pair: SprinterDoorrolPair) -> int:
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
    def __init__(self, pairs: list[SprinterDoorrolPair], applier: Applier) -> None:
        super().__init__()
        self.pairs = pairs
        self.applier = applier
        self.index = 0
        self.setWindowTitle("Sprinters doorrol review")
        self.resize(1400, 440)

        layout = QVBoxLayout(self)
        self.lbl_progress = QLabel("")
        self.lbl_meta = QLabel("")
        self.tbl = QTableWidget(2, 13)
        self.tbl.setHorizontalHeaderLabels(
            [
                "Id",
                "datum",
                "broker",
                "asset",
                "asset_detail",
                "transactie_type",
                "qty",
                "exp",
                "strike",
                "c/p",
                "score",
                "notes",
                "uniek_id",
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
            self.lbl_progress.setText("Geen sprinter-doorrol kandidaten gevonden.")
            self.lbl_meta.setText("")
            self.tbl.clearContents()
            self.btn_prev.setEnabled(False)
            self.btn_approve.setEnabled(False)
            self.btn_reject.setEnabled(False)
            self.btn_skip.setEnabled(False)
            self.btn_approve_all.setEnabled(False)
            return

        self.index = max(0, min(self.index, total - 1))
        p = self.pairs[self.index]
        self.lbl_progress.setText(
            f"Kandidaat {self.index + 1}/{total} | approved={self.applier.approved} rejected={self.applier.rejected} | dry_run={self.applier.dry_run}"
        )
        self.lbl_meta.setText("Hard rules: zelfde dag/broker/asset/asset_detail, sprinter, koop+verkoop, zelfde abs qty, call+call, zelfde strike, verschillende optie_exp_date.")

        for r, row in enumerate([p.left, p.right]):
            self.tbl.setItem(r, 0, self._item(row.get("Id")))
            self.tbl.setItem(r, 1, self._item(row.get("datum_only")))
            self.tbl.setItem(r, 2, self._item(row.get("broker")))
            self.tbl.setItem(r, 3, self._item(row.get("asset_rollup")))
            self.tbl.setItem(r, 4, self._item(row.get("asset_detail")))
            self.tbl.setItem(r, 5, self._item(row.get("transactie_type")))
            self.tbl.setItem(r, 6, self._item(row.get("qty")))
            self.tbl.setItem(r, 7, self._item(row.get("exp_only")))
            self.tbl.setItem(r, 8, self._item(row.get("optie_strike")))
            self.tbl.setItem(r, 9, self._item(row.get("cp")))
            self.tbl.setItem(r, 10, self._item(f"{p.score:.2f}" if r == 0 else ""))
            self.tbl.setItem(r, 11, self._item(", ".join(p.notes) if r == 0 else ""))
            self.tbl.setItem(r, 12, self._item(row.get("uniek_id")))
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
        QMessageBox.information(self, "Sprinter doorrol", f"{mode} met order_id={order_id} (Ids {p.left['Id']}, {p.right['Id']})")
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
            "Sprinter doorrol",
            f"Alle resterende kandidaten verwerkt vanaf {start + 1}. approved={self.applier.approved}",
        )
        self.index = len(self.pairs) - 1
        self.render()


def main() -> int:
    parser = argparse.ArgumentParser(description="Vind en review sprinter-doorrol kandidaten.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Pad naar Access DB.")
    parser.add_argument("--table", default="transacties_bron_data_org", help="Brontransactie tabel.")
    parser.add_argument("--dry-run", action="store_true", help="Niet schrijven, alleen reviewen.")
    args = parser.parse_args()

    conn_str = r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + args.db
    conn = pyodbc.connect(conn_str)
    finder = Finder(conn=conn, table=args.table)
    rows = finder.load_rows()
    pairs = finder.find_pairs(rows)
    print(f"Loaded rows: {len(rows)} | sprinter doorrol candidates: {len(pairs)}")

    app = QApplication([])
    applier = Applier(conn=conn, table=args.table, dry_run=args.dry_run)
    w = ReviewWindow(pairs=pairs, applier=applier)
    w.show()
    rc = app.exec()
    conn.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())


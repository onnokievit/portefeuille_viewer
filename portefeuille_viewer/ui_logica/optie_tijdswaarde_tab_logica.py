from __future__ import annotations

from datetime import datetime
import os

import polars as pl
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals


def _fmt_nl(v, decimals=2) -> str:
    if v is None:
        return ""
    try:
        s = f"{float(v):,.{decimals}f}"
    except Exception:
        return str(v)
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


class OptieTijdswaardeTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._use_projection_v2 = os.getenv("UI_OPTIE_TIJDSWAARDE_LEGACY_FROM_PROJECTION_V2", "0").strip() == "1"
        self.label_ticker = QLabel("starting...")
        self.label_summary = QLabel("")
        self.table = QTableWidget(0, 20)
        self.table.setHorizontalHeaderLabels(
            [
                "broker",
                "asset",
                "exp",
                "c/p",
                "strike",
                "qty_open",
                "mult",
                "ccy",
                "last_px",
                "px_source",
                "bid",
                "ask",
                "und_px",
                "intrinsic",
                "time_per_unit",
                "time_total",
                "iv",
                "delta",
                "gamma",
                "theta",
            ]
        )
        self.table.setSortingEnabled(True)
        top = QHBoxLayout()
        top.addWidget(self.label_ticker, 1)
        top.addWidget(self.label_summary, 2)
        lay = QVBoxLayout()
        lay.addLayout(top)
        lay.addWidget(self.table)
        self.setLayout(lay)
        signals.snapshotUpdated.connect(self._on_snapshot_updated)
        self.refresh_table()

    def _on_snapshot_updated(self, snapshot_key: str):
        keys = {
            "snapshot_optie_timevalue_live",
            "snapshot_optie_timevalue_summary",
            "snapshot_optie_timevalue_meta",
        }
        if self._use_projection_v2:
            keys = {
                "snapshot_optie_tijdswaarde_projection_v2",
                "snapshot_optie_tijdswaarde_projection_v2_patch",
                "snapshot_optie_tijdswaarde_projection_v2_meta",
            }
        if snapshot_key in keys:
            self.refresh_table()

    def refresh_table(self):
        if self._use_projection_v2:
            df = getattr(SNAPSHOT_STORE, "snapshot_optie_tijdswaarde_projection_v2", None)
        else:
            df = SNAPSHOT_STORE.snapshot_optie_timevalue_live
        if df is None or not isinstance(df, pl.DataFrame) or df.is_empty():
            self.table.setRowCount(0)
            self.label_ticker.setText("no option timevalue rows")
            self.label_summary.setText("")
            return
        records = df.to_dicts()
        by_ccy = {}
        if self._use_projection_v2:
            for r in records:
                ccy = r.get("ccy")
                time_total = r.get("time_total")
                if ccy is None or time_total is None:
                    continue
                try:
                    by_ccy[str(ccy)] = by_ccy.get(str(ccy), 0.0) + float(time_total)
                except Exception:
                    continue
        else:
            summary_df = SNAPSHOT_STORE.snapshot_optie_timevalue_summary
            if isinstance(summary_df, pl.DataFrame) and not summary_df.is_empty():
                by_ccy = {
                    str(r.get("ccy")): float(r.get("time_value_abs"))
                    for r in summary_df.to_dicts()
                    if r.get("ccy") is not None and r.get("time_value_abs") is not None
                }

        self.table.setSortingEnabled(False)
        footer_rows = len(by_ccy)
        self.table.setRowCount(len(records) + footer_rows)
        for i, r in enumerate(records):
            vals = [
                r.get("broker"),
                r.get("asset"),
                r.get("exp"),
                r.get("c_p"),
                r.get("strike"),
                r.get("qty_open"),
                r.get("mult"),
                r.get("ccy"),
                r.get("last_px"),
                r.get("px_source"),
                r.get("bid"),
                r.get("ask"),
                r.get("und_px"),
                r.get("intrinsic"),
                r.get("time_per_unit"),
                r.get("time_total"),
                r.get("iv"),
                r.get("delta"),
                r.get("gamma"),
                r.get("theta"),
            ]
            for c, v in enumerate(vals):
                if c in (4, 5, 6):
                    txt = _fmt_nl(v, 1)
                elif c in (8, 10, 11, 12, 13, 14, 15):
                    txt = _fmt_nl(v, 2)
                elif c in (16, 17, 18, 19):
                    txt = _fmt_nl(v, 3)
                elif isinstance(v, datetime):
                    txt = v.strftime("%Y-%m-%d")
                else:
                    txt = "" if v is None else str(v)
                item = QTableWidgetItem(txt)
                if c >= 4 and c != 9:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, c, item)

        row_idx = len(records)
        for ccy, total in sorted(by_ccy.items()):
            vals = [
                "TOTAL",
                "",
                "",
                "",
                "",
                "",
                "",
                ccy,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                _fmt_nl(total, 2),
                "",
                "",
                "",
                "",
            ]
            for c, txt in enumerate(vals):
                it = QTableWidgetItem(txt)
                it.setBackground(Qt.lightGray)
                if c in (0, 7):
                    it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                else:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row_idx, c, it)
            row_idx += 1

        if self._use_projection_v2:
            meta = getattr(SNAPSHOT_STORE, "snapshot_optie_tijdswaarde_projection_v2_meta", None)
            if isinstance(meta, dict) and meta:
                self.label_ticker.setText(
                    f"Projection v{meta.get('version', '?')} | rows: {meta.get('rows', len(records))} | changes: {meta.get('changes', 0)}"
                )
            else:
                self.label_ticker.setText(f"{len(records)} rows")
        else:
            meta = SNAPSHOT_STORE.snapshot_optie_timevalue_meta
            if isinstance(meta, pl.DataFrame) and not meta.is_empty():
                m = meta.to_dicts()[0]
                self.label_ticker.setText(
                    f"[{m.get('ts')}] ticks with price={int(m.get('priced') or 0)}/{int(m.get('total') or 0)}"
                )
            else:
                self.label_ticker.setText(f"{len(records)} rows")
        ccy_txt = " | ".join([f"{k}:{_fmt_nl(v, 2)}" for k, v in sorted(by_ccy.items())]) if by_ccy else "-"
        self.label_summary.setText(f"time_value_signed_by_ccy: {ccy_txt}")
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()

    def set_active(self, active: bool):
        _ = active

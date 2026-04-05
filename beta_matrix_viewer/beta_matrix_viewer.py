from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyodbc
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover
    QWebEngineView = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from portefeuille_viewer.config import get_settings  # noqa: E402
from portefeuille_viewer.services.historical_price_update_runner import STOCKDATA_DB_PATH  # noqa: E402


LOOKBACK_MONTHS: dict[str, int] = {"3m": 3, "6m": 6, "12m": 12}
MIN_OBS = 10


class BetaMatrixViewer(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Beta Matrix Viewer")
        self.resize(1560, 920)
        self._web_ready = False
        self._pending_payload: dict | None = None
        self._returns_wide = pd.DataFrame()
        self._indices: list[str] = []

        if QWebEngineView is None:
            raise RuntimeError("PySide6 QtWebEngine is niet beschikbaar.")

        self.combo_lookback = QComboBox(self)
        self.combo_lookback.addItems(["12m", "6m", "3m"])
        self.combo_lookback.setCurrentText("12m")
        self.combo_lookback.currentTextChanged.connect(self._rebuild_matrix)

        self.label_info = QLabel("Nog geen matrix geladen.", self)
        self.label_db = QLabel(f"DB: {STOCKDATA_DB_PATH}", self)
        self.label_db.setStyleSheet("color:#666;")

        top = QHBoxLayout()
        top.addWidget(QLabel("Lookback:", self))
        top.addWidget(self.combo_lookback)
        top.addSpacing(12)
        top.addWidget(self.label_info, 1)
        top.addWidget(self.label_db)

        self.web = QWebEngineView(self)
        self.web.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.web.loadFinished.connect(self._on_web_loaded)
        self.web.setHtml(self._html_template())

        wrapper = QWidget(self)
        layout = QVBoxLayout(wrapper)
        layout.addLayout(top)
        layout.addWidget(self.web, 1)
        self.setCentralWidget(wrapper)

        self._load_source_data()
        QTimer.singleShot(0, self._rebuild_matrix)

    def _connect(self):
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={STOCKDATA_DB_PATH};"
        return pyodbc.connect(conn_str)

    def _load_source_data(self) -> None:
        enabled = {str(v).strip().upper() for v in get_settings().get_enabled_beta_drivers()}
        with self._connect() as conn:
            cur = conn.cursor()
            meta_rows = cur.execute(
                """
                SELECT asset_rollup
                FROM asset_rollup_data
                WHERE [type] = 'index'
                  AND INCL_EXCL = 1
                  AND asset_rollup IS NOT NULL
                ORDER BY asset_rollup
                """
            ).fetchall()
            all_indices = [str(row[0]).strip().upper() for row in meta_rows if row and row[0]]
            if enabled:
                self._indices = [idx for idx in all_indices if idx in enabled]
            else:
                self._indices = all_indices
            if not self._indices:
                self._returns_wide = pd.DataFrame()
                return
            placeholders = ",".join("?" for _ in self._indices)
            price_rows = cur.execute(
                f"""
                SELECT datum, asset_rollup, [close] AS close_price
                FROM historical_data_correct
                WHERE asset_rollup IN ({placeholders})
                  AND [close] IS NOT NULL
                ORDER BY datum, asset_rollup
                """,
                self._indices,
            ).fetchall()

        records = []
        for datum, asset_rollup, close_price in price_rows:
            try:
                close_val = float(close_price)
            except Exception:
                continue
            dt = pd.to_datetime(datum, errors="coerce")
            if pd.isna(dt):
                continue
            records.append(
                {
                    "datum": dt,
                    "asset_rollup": str(asset_rollup).strip().upper(),
                    "close_price": close_val,
                }
            )
        if not records:
            self._returns_wide = pd.DataFrame()
            return
        prices = pd.DataFrame.from_records(records)
        prices = prices.dropna(subset=["datum", "asset_rollup", "close_price"])
        prices = prices.sort_values(["asset_rollup", "datum"]).drop_duplicates(["asset_rollup", "datum"], keep="last")
        wide = prices.pivot(index="datum", columns="asset_rollup", values="close_price").sort_index()
        returns = wide.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna(axis=0, how="all")
        self._returns_wide = returns

    def _on_web_loaded(self, ok: bool) -> None:
        self._web_ready = bool(ok)
        if self._web_ready and self._pending_payload is not None:
            self._push_payload(self._pending_payload)
            self._pending_payload = None

    def _rebuild_matrix(self) -> None:
        lookback_code = str(self.combo_lookback.currentText() or "12m").strip().lower()
        months = LOOKBACK_MONTHS.get(lookback_code, 12)
        payload = self._build_payload(lookback_code, months)
        self.label_info.setText(payload["meta_text"])
        if not self._web_ready:
            self._pending_payload = payload
            return
        self._push_payload(payload)

    def _build_payload(self, lookback_code: str, months: int) -> dict:
        if self._returns_wide is None or self._returns_wide.empty or not self._indices:
            return {
                "rows": [],
                "columns": [],
                "meta_text": "Geen indexdata beschikbaar.",
                "title": "Index Beta Matrix",
            }
        latest_date = self._returns_wide.index.max()
        start_date = latest_date - pd.DateOffset(months=months)
        window = self._returns_wide.loc[self._returns_wide.index >= start_date]
        rows: list[dict] = []
        for target in self._indices:
            row = {"target_index": target}
            target_series = window[target] if target in window.columns else None
            for driver in self._indices:
                key = f"col__{driver}"
                if target == driver:
                    row[key] = None
                    continue
                if target_series is None or driver not in window.columns:
                    row[key] = None
                    continue
                pair = pd.concat(
                    [target_series.rename("target"), window[driver].rename("driver")],
                    axis=1,
                ).dropna()
                if len(pair) < MIN_OBS:
                    row[key] = None
                    continue
                driver_var = float(np.var(pair["driver"].to_numpy(dtype=float), ddof=1))
                if not np.isfinite(driver_var) or driver_var <= 0.0:
                    row[key] = None
                    continue
                cov = float(np.cov(pair["target"].to_numpy(dtype=float), pair["driver"].to_numpy(dtype=float), ddof=1)[0, 1])
                beta_value = cov / driver_var
                row[key] = float(beta_value) if np.isfinite(beta_value) else None
            rows.append(row)
        columns = ["target_index"] + [f"col__{driver}" for driver in self._indices]
        obs = int(len(window))
        meta_text = (
            f"{len(self._indices)} indices | lookback {lookback_code.upper()} | "
            f"{obs} returnpunten | laatste datum {pd.Timestamp(latest_date).date().isoformat()}"
        )
        return {
            "rows": rows,
            "columns": columns,
            "indices": self._indices,
            "meta_text": meta_text,
            "title": "Index Beta Matrix",
        }

    def _push_payload(self, payload: dict) -> None:
        js = json.dumps(payload, ensure_ascii=False)
        self.web.page().runJavaScript(f"window.renderMatrix({js});")

    def _html_template(self) -> str:
        return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <style>
      * { box-sizing:border-box; }
      html, body { margin:0; padding:0; height:100%; overflow:hidden; }
      body {
        font-family: Segoe UI, Arial, sans-serif;
        background: linear-gradient(180deg, #f7f3ea 0%, #efe6d4 100%);
        color:#2a2a2a;
      }
      .page {
        height:100%;
        display:flex;
        flex-direction:column;
        padding:14px;
        gap:10px;
      }
      .hero {
        background: rgba(255,255,255,0.82);
        border: 1px solid #dbcdb3;
        border-radius: 18px;
        box-shadow: 0 8px 24px rgba(120, 95, 40, 0.08);
        padding: 18px 20px;
      }
      .hero h1 {
        margin:0 0 6px 0;
        font-size: 26px;
        font-weight: 700;
        letter-spacing: 0.2px;
      }
      .hero p {
        margin:0;
        color:#6b624f;
        font-size:13px;
      }
      .table-shell {
        min-height:0;
        flex:1;
        background: rgba(255,255,255,0.78);
        border: 1px solid #dbcdb3;
        border-radius: 18px;
        overflow: auto;
        box-shadow: 0 8px 24px rgba(120, 95, 40, 0.08);
      }
      table {
        border-collapse: separate;
        border-spacing: 0;
        width: max-content;
        min-width: 100%;
      }
      thead th {
        position: sticky;
        top: 0;
        z-index: 3;
        background: #e8dcc1;
        color:#443a28;
        font-weight:700;
        border-bottom:1px solid #cdbb94;
      }
      th, td {
        padding: 7px 10px;
        border-right: 1px solid #eadfca;
        border-bottom: 1px solid #eadfca;
        white-space: nowrap;
        font-size: 12px;
      }
      th:first-child, td:first-child {
        position: sticky;
        left: 0;
        z-index: 2;
        background: #f4edde;
        font-weight: 700;
        box-shadow: 1px 0 0 #d9ccb0;
      }
      thead th:first-child { z-index: 4; }
      td.num { text-align: right; font-variant-numeric: tabular-nums; }
      td.empty { background:#f7f1e5; color:#b3a78f; }
      td.pos { color:#0f6b31; background: rgba(127, 214, 132, 0.22); }
      td.neg { color:#9d2222; background: rgba(240, 126, 126, 0.22); }
      td.neutral { color:#5b513f; background: rgba(197, 180, 150, 0.16); }
    </style>
  </head>
  <body>
    <div class="page">
      <div class="hero">
        <h1 id="title">Index Beta Matrix</h1>
        <p id="meta">Nog geen data.</p>
      </div>
      <div class="table-shell">
        <table id="matrix"></table>
      </div>
    </div>
    <script>
      function fmt(v) {
        if (v === null || v === undefined || Number.isNaN(Number(v))) return "";
        return Number(v).toLocaleString("nl-NL", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
      }
      function cls(v) {
        const n = Number(v);
        if (!Number.isFinite(n)) return "empty";
        if (Math.abs(n) < 0.05) return "neutral";
        return n >= 0 ? "pos" : "neg";
      }
      window.renderMatrix = function(payload) {
        const title = document.getElementById("title");
        const meta = document.getElementById("meta");
        const tbl = document.getElementById("matrix");
        title.textContent = payload.title || "Index Beta Matrix";
        meta.textContent = payload.meta_text || "";
        const rows = Array.isArray(payload.rows) ? payload.rows : [];
        const indices = Array.isArray(payload.indices) ? payload.indices : [];

        let html = "<thead><tr><th>Target \\\\ Driver</th>";
        for (const driver of indices) html += `<th>${driver}</th>`;
        html += "</tr></thead><tbody>";
        for (const row of rows) {
          html += `<tr><td>${row.target_index || ""}</td>`;
          for (const driver of indices) {
            const key = `col__${driver}`;
            const val = row[key];
            if (val === null || val === undefined || row.target_index === driver) {
              html += '<td class="num empty"></td>';
            } else {
              html += `<td class="num ${cls(val)}">${fmt(val)}</td>`;
            }
          }
          html += "</tr>";
        }
        html += "</tbody>";
        tbl.innerHTML = html;
      };
    </script>
  </body>
</html>
"""


def main() -> int:
    app = QApplication(sys.argv)
    viewer = BetaMatrixViewer()
    viewer.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

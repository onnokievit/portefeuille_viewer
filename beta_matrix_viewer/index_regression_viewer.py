from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
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

from portefeuille_viewer.config import get_settings, get_stockdata_db_path  # noqa: E402
from portefeuille_viewer.data import repository  # noqa: E402


LOOKBACK_MONTHS: dict[str, int] = {"3m": 3, "6m": 6, "12m": 12}
MIN_OBS = 10


class IndexRegressionViewer(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Index Regression Viewer")
        self.resize(1560, 980)
        self._web_ready = False
        self._pending_payload: dict | None = None
        self._returns_wide = pd.DataFrame()
        self._indices: list[str] = []

        if QWebEngineView is None:
            raise RuntimeError("PySide6 QtWebEngine is niet beschikbaar.")

        self.combo_x = QComboBox(self)
        self.combo_y = QComboBox(self)
        self.combo_lookback = QComboBox(self)
        self.combo_lookback.addItems(["12m", "6m", "3m"])
        self.combo_lookback.setCurrentText("12m")

        self.combo_x.currentTextChanged.connect(self._rebuild_chart)
        self.combo_y.currentTextChanged.connect(self._rebuild_chart)
        self.combo_lookback.currentTextChanged.connect(self._rebuild_chart)

        self.label_info = QLabel("Nog geen regressie geladen.", self)
        self.label_db = QLabel(f"DB: {get_stockdata_db_path()}", self)
        self.label_db.setStyleSheet("color:#666;")

        top = QHBoxLayout()
        top.addWidget(QLabel("Index X:", self))
        top.addWidget(self.combo_x)
        top.addSpacing(10)
        top.addWidget(QLabel("Index Y:", self))
        top.addWidget(self.combo_y)
        top.addSpacing(10)
        top.addWidget(QLabel("Lookback:", self))
        top.addWidget(self.combo_lookback)
        top.addSpacing(16)
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
        self._populate_combos()
        QTimer.singleShot(0, self._rebuild_chart)

    def _connect(self):
        return repository.get_stockdata_connection()

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

    def _populate_combos(self) -> None:
        self.combo_x.blockSignals(True)
        self.combo_y.blockSignals(True)
        self.combo_x.clear()
        self.combo_y.clear()
        self.combo_x.addItems(self._indices)
        self.combo_y.addItems(self._indices)
        if self._indices:
            self.combo_x.setCurrentIndex(0)
            y_idx = 1 if len(self._indices) > 1 else 0
            self.combo_y.setCurrentIndex(y_idx)
        self.combo_x.blockSignals(False)
        self.combo_y.blockSignals(False)

    def _on_web_loaded(self, ok: bool) -> None:
        self._web_ready = bool(ok)
        if self._web_ready and self._pending_payload is not None:
            self._push_payload(self._pending_payload)
            self._pending_payload = None

    def _rebuild_chart(self) -> None:
        lookback_code = str(self.combo_lookback.currentText() or "12m").strip().lower()
        payload = self._build_payload(lookback_code, LOOKBACK_MONTHS.get(lookback_code, 12))
        self.label_info.setText(payload.get("meta_text", ""))
        if not self._web_ready:
            self._pending_payload = payload
            return
        self._push_payload(payload)

    def _build_payload(self, lookback_code: str, months: int) -> dict:
        x_asset = str(self.combo_x.currentText() or "").strip().upper()
        y_asset = str(self.combo_y.currentText() or "").strip().upper()
        empty = {
            "title": "Index Regression Viewer",
            "meta_text": "Geen indexdata beschikbaar.",
            "question": "Wat is het intercept? En wat is de slope?",
            "points": [],
            "x_label": x_asset or "Index X",
            "y_label": y_asset or "Index Y",
            "line": None,
            "stats": None,
            "explanation": [],
        }
        if self._returns_wide is None or self._returns_wide.empty or not x_asset or not y_asset:
            return empty
        if x_asset not in self._returns_wide.columns or y_asset not in self._returns_wide.columns:
            empty["meta_text"] = "Geselecteerde index niet beschikbaar."
            return empty

        latest_date = self._returns_wide.index.max()
        start_date = latest_date - pd.DateOffset(months=months)
        window = self._returns_wide.loc[self._returns_wide.index >= start_date, [x_asset, y_asset]].dropna()
        if len(window) < MIN_OBS:
            empty["meta_text"] = f"Te weinig overlap tussen {x_asset} en {y_asset} in {lookback_code.upper()}."
            return empty

        x = window[x_asset].to_numpy(dtype=float)
        y = window[y_asset].to_numpy(dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        corr = float(np.corrcoef(x, y)[0, 1]) if len(window) >= 2 else np.nan
        r_squared = float(corr * corr) if np.isfinite(corr) else np.nan
        fitted = intercept + (slope * x)

        points = [
            {
                "x": float(xi * 100.0),
                "y": float(yi * 100.0),
                "label": str(idx.date()),
            }
            for idx, xi, yi in zip(window.index, x, y)
        ]

        x_min = float(np.min(x))
        x_max = float(np.max(x))
        line = {
            "x1": x_min * 100.0,
            "y1": float((intercept + (slope * x_min)) * 100.0),
            "x2": x_max * 100.0,
            "y2": float((intercept + (slope * x_max)) * 100.0),
        }

        intercept_pct = float(intercept * 100.0)
        sample_x = float(np.mean(x) * 100.0)
        sample_y = float((intercept + (slope * (sample_x / 100.0))) * 100.0)
        sample_y_plus = float((intercept + (slope * ((sample_x + 1.0) / 100.0))) * 100.0)
        delta_y = sample_y_plus - sample_y

        explanation = [
            (
                f"Intercept: bij X = 0% is de verwachte Y = "
                f"{intercept_pct:.2f}%."
            ),
            (
                f"Slope: als {x_asset} met 1,00 procentpunt beweegt, "
                f"beweegt {y_asset} gemiddeld met {slope:.3f} procentpunt."
            ),
            (
                f"Voorbeeld op de regressielijn: rond X = {sample_x:.2f}% stijgt Y van "
                f"{sample_y:.2f}% naar {sample_y_plus:.2f}%."
                f" Dat is {delta_y:.2f} procentpunt per +1,00 op X."
            ),
        ]

        obs = int(len(window))
        meta_text = (
            f"{x_asset} -> X | {y_asset} -> Y | lookback {lookback_code.upper()} | "
            f"{obs} observaties | laatste datum {pd.Timestamp(latest_date).date().isoformat()}"
        )
        return {
            "title": "Index Regression Viewer",
            "meta_text": meta_text,
            "question": "Wat is het intercept? En wat is de slope?",
            "points": points,
            "x_label": f"{x_asset} daily return (%)",
            "y_label": f"{y_asset} daily return (%)",
            "line": line,
            "stats": {
                "x_asset": x_asset,
                "y_asset": y_asset,
                "slope": float(slope),
                "intercept_pct": intercept_pct,
                "corr": corr if np.isfinite(corr) else None,
                "r_squared": r_squared if np.isfinite(r_squared) else None,
                "obs": obs,
                "mean_abs_residual_pct": float(np.mean(np.abs((y - fitted) * 100.0))),
            },
            "explanation": explanation,
        }

    def _push_payload(self, payload: dict) -> None:
        js = json.dumps(payload, ensure_ascii=False)
        self.web.page().runJavaScript(f"window.renderRegression({js});")

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
        background: linear-gradient(180deg, #f6f2e7 0%, #efe3cf 100%);
        color:#1f1a14;
      }
      .page {
        height:100%;
        display:flex;
        flex-direction:column;
        padding:18px;
        gap:14px;
      }
      .hero, .panel {
        background: rgba(255,255,255,0.82);
        border: 1px solid #dbcdb3;
        border-radius: 20px;
        box-shadow: 0 10px 28px rgba(120, 95, 40, 0.08);
      }
      .hero {
        padding: 18px 22px;
      }
      .hero h1 {
        margin:0 0 6px 0;
        font-size: 28px;
        font-weight: 700;
      }
      .hero p {
        margin:0;
        color:#6b624f;
        font-size:13px;
      }
      .question {
        font-size: 42px;
        line-height: 1.08;
        font-weight: 500;
        padding: 18px 26px 0 26px;
      }
      .chart-wrap {
        flex:1;
        min-height: 420px;
        padding: 6px 18px 10px 18px;
      }
      .stats {
        display:grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 10px;
        padding: 0 18px 18px 18px;
      }
      .stat {
        background: rgba(244, 237, 222, 0.95);
        border: 1px solid #e1d2b4;
        border-radius: 16px;
        padding: 12px 14px;
      }
      .stat .k {
        color:#6b624f;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }
      .stat .v {
        font-size: 24px;
        font-weight: 700;
        margin-top: 4px;
      }
      .explain {
        padding: 0 26px 24px 26px;
        font-size: 26px;
        line-height: 1.26;
      }
      .explain p {
        margin: 0 0 10px 0;
      }
      svg {
        width:100%;
        height:100%;
        display:block;
      }
      .axis { stroke:#8a8a8a; stroke-width:1.5; }
      .grid { stroke:#d8d8d8; stroke-width:1; }
      .tick { stroke:#787878; stroke-width:1; }
      .tick-label {
        font-size: 12px;
        fill:#4c4c4c;
        font-variant-numeric: tabular-nums;
      }
      .point {
        fill:#1947ff;
        opacity:0.9;
      }
      .line {
        stroke:#ff4d4d;
        stroke-width:2.5;
      }
      .axis-label {
        font-size: 14px;
        fill:#3d3528;
        font-weight:600;
      }
      .empty {
        height:100%;
        display:flex;
        align-items:center;
        justify-content:center;
        color:#7d735f;
        font-size:22px;
      }
    </style>
  </head>
  <body>
    <div class="page">
      <div class="hero">
        <h1 id="title">Index Regression Viewer</h1>
        <p id="meta">Nog geen data.</p>
      </div>
      <div class="panel" style="flex:1; min-height:0; display:flex; flex-direction:column;">
        <div class="question" id="question">Wat is het intercept? En wat is de slope?</div>
        <div class="chart-wrap" id="chart"></div>
        <div class="stats" id="stats"></div>
        <div class="explain" id="explain"></div>
      </div>
    </div>
    <script>
      function fmt(v, digits=2) {
        if (v === null || v === undefined || !Number.isFinite(Number(v))) return "n.v.t.";
        return Number(v).toLocaleString("nl-NL", { minimumFractionDigits: digits, maximumFractionDigits: digits });
      }
      function padDomain(minVal, maxVal) {
        if (!Number.isFinite(minVal) || !Number.isFinite(maxVal)) return [-1, 1];
        if (minVal === maxVal) {
          const bump = Math.max(Math.abs(minVal) * 0.2, 1);
          return [minVal - bump, maxVal + bump];
        }
        const span = maxVal - minVal;
        const pad = span * 0.12;
        return [minVal - pad, maxVal + pad];
      }
      function ticksFor(domainMin, domainMax, desired) {
        const span = domainMax - domainMin;
        if (!(span > 0)) return [domainMin];
        const rawStep = span / desired;
        const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
        const norm = rawStep / mag;
        let step = mag;
        if (norm > 5) step = 10 * mag;
        else if (norm > 2) step = 5 * mag;
        else if (norm > 1) step = 2 * mag;
        const start = Math.ceil(domainMin / step) * step;
        const out = [];
        for (let v = start; v <= domainMax + step * 0.5; v += step) out.push(Number(v.toFixed(8)));
        return out;
      }
      function esc(text) {
        return String(text ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;");
      }
      function renderChart(payload) {
        const host = document.getElementById("chart");
        const pts = Array.isArray(payload.points) ? payload.points : [];
        if (!pts.length || !payload.line) {
          host.innerHTML = '<div class="empty">Geen bruikbare overlap voor deze combinatie.</div>';
          return;
        }

        const width = Math.max(host.clientWidth || 900, 900);
        const height = Math.max(host.clientHeight || 480, 480);
        const m = { top: 24, right: 20, bottom: 54, left: 72 };
        const innerW = width - m.left - m.right;
        const innerH = height - m.top - m.bottom;

        const xs = pts.map(p => Number(p.x));
        const ys = pts.map(p => Number(p.y));
        xs.push(Number(payload.line.x1), Number(payload.line.x2), 0);
        ys.push(Number(payload.line.y1), Number(payload.line.y2), 0);

        const [xMin, xMax] = padDomain(Math.min(...xs), Math.max(...xs));
        const [yMin, yMax] = padDomain(Math.min(...ys), Math.max(...ys));

        const xScale = x => m.left + ((x - xMin) / (xMax - xMin)) * innerW;
        const yScale = y => m.top + innerH - ((y - yMin) / (yMax - yMin)) * innerH;

        const xTicks = ticksFor(xMin, xMax, 7);
        const yTicks = ticksFor(yMin, yMax, 6);
        const xAxisY = (0 >= yMin && 0 <= yMax) ? yScale(0) : yScale(yMin);
        const yAxisX = (0 >= xMin && 0 <= xMax) ? xScale(0) : xScale(xMin);

        let svg = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">`;

        for (const t of xTicks) {
          const px = xScale(t);
          svg += `<line class="grid" x1="${px}" y1="${m.top}" x2="${px}" y2="${m.top + innerH}"></line>`;
          svg += `<line class="tick" x1="${px}" y1="${xAxisY}" x2="${px}" y2="${xAxisY + 7}"></line>`;
          svg += `<text class="tick-label" x="${px}" y="${m.top + innerH + 24}" text-anchor="middle">${fmt(t, 1)}</text>`;
        }
        for (const t of yTicks) {
          const py = yScale(t);
          svg += `<line class="grid" x1="${m.left}" y1="${py}" x2="${m.left + innerW}" y2="${py}"></line>`;
          svg += `<line class="tick" x1="${yAxisX - 7}" y1="${py}" x2="${yAxisX}" y2="${py}"></line>`;
          svg += `<text class="tick-label" x="${m.left - 12}" y="${py + 4}" text-anchor="end">${fmt(t, 1)}</text>`;
        }

        svg += `<line class="axis" x1="${m.left}" y1="${xAxisY}" x2="${m.left + innerW}" y2="${xAxisY}"></line>`;
        svg += `<line class="axis" x1="${yAxisX}" y1="${m.top}" x2="${yAxisX}" y2="${m.top + innerH}"></line>`;
        svg += `<line class="line" x1="${xScale(payload.line.x1)}" y1="${yScale(payload.line.y1)}" x2="${xScale(payload.line.x2)}" y2="${yScale(payload.line.y2)}"></line>`;

        for (const p of pts) {
          svg += `<circle class="point" cx="${xScale(p.x)}" cy="${yScale(p.y)}" r="3.2"><title>${esc(p.label)} | X=${fmt(p.x, 2)} | Y=${fmt(p.y, 2)}</title></circle>`;
        }

        svg += `<text class="axis-label" x="${m.left + innerW / 2}" y="${height - 10}" text-anchor="middle">${esc(payload.x_label || "X")}</text>`;
        svg += `<text class="axis-label" transform="translate(18 ${m.top + innerH / 2}) rotate(-90)" text-anchor="middle">${esc(payload.y_label || "Y")}</text>`;
        svg += `</svg>`;
        host.innerHTML = svg;
      }
      window.renderRegression = function(payload) {
        document.getElementById("title").textContent = payload.title || "Index Regression Viewer";
        document.getElementById("meta").textContent = payload.meta_text || "";
        document.getElementById("question").textContent = payload.question || "";

        renderChart(payload);

        const stats = payload.stats || {};
        const statsHost = document.getElementById("stats");
        statsHost.innerHTML = `
          <div class="stat"><div class="k">Slope</div><div class="v">${fmt(stats.slope, 3)}</div></div>
          <div class="stat"><div class="k">Intercept</div><div class="v">${fmt(stats.intercept_pct, 2)}%</div></div>
          <div class="stat"><div class="k">Correlatie</div><div class="v">${fmt(stats.corr, 3)}</div></div>
          <div class="stat"><div class="k">R²</div><div class="v">${fmt(stats.r_squared, 3)}</div></div>
          <div class="stat"><div class="k">Observaties</div><div class="v">${fmt(stats.obs, 0)}</div></div>
        `;

        const explain = Array.isArray(payload.explanation) ? payload.explanation : [];
        document.getElementById("explain").innerHTML = explain.map(x => `<p>${esc(x)}</p>`).join("");
      };
      window.addEventListener("resize", () => {
        if (window.__lastPayload) window.renderRegression(window.__lastPayload);
      });
      const originalRender = window.renderRegression;
      window.renderRegression = function(payload) {
        window.__lastPayload = payload;
        originalRender(payload);
      };
    </script>
  </body>
</html>
"""


def main() -> int:
    app = QApplication(sys.argv)
    viewer = IndexRegressionViewer()
    viewer.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

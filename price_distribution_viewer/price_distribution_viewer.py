from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pyodbc

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
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

from portefeuille_viewer.config import get_databases, get_default_database  # noqa: E402


PERIOD_MONTHS = (12, 9, 6, 3)
PERIOD_COLORS = {
    3: "#4f7cf7",
    6: "#f08c2e",
    9: "#1f9d63",
    12: "#b54bd8",
}
TARGET_BUCKETS_12M = 96


@dataclass
class PriceRow:
    datum: date
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    volume: float | None


def resolve_db_path() -> str:
    databases = get_databases()
    default_name = get_default_database()
    if default_name and default_name in databases:
        return str(databases[default_name]["path"])
    return ""


def shift_months(base: date, months_back: int) -> date:
    month = base.month - months_back
    year = base.year
    while month <= 0:
        month += 12
        year -= 1
    day = min(base.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _safe_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except Exception:
            continue
    return None


def _nice_step(target: float) -> float:
    if target <= 0:
        return 1.0
    exponent = math.floor(math.log10(target))
    fraction = target / (10 ** exponent)
    if fraction <= 1:
        nice = 1
    elif fraction <= 2:
        nice = 2
    elif fraction <= 2.5:
        nice = 2.5
    elif fraction <= 5:
        nice = 5
    else:
        nice = 10
    return nice * (10 ** exponent)


class PriceDistributionViewer(QMainWindow):
    def __init__(self, db_path: str):
        super().__init__()
        self.db_path = db_path
        self.setWindowTitle("Price Distribution Viewer")
        self.resize(1380, 860)
        self._asset_rows: list[PriceRow] = []
        self._web_ready = False
        self._pending_payload: dict | None = None

        if QWebEngineView is None:
            raise RuntimeError("PySide6 QtWebEngine is niet beschikbaar.")

        self.combo_assets = QComboBox(self)
        self.combo_assets.setEditable(True)
        self.combo_assets.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo_assets.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.combo_assets.setMinimumWidth(260)
        self.combo_assets.currentTextChanged.connect(self._on_asset_changed)

        self.label_db = QLabel(f"DB: {self.db_path}", self)
        self.label_db.setStyleSheet("color:#666;")
        self.label_info = QLabel("Nog geen asset geladen.", self)
        self.label_info.setStyleSheet("color:#555;")

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Asset:", self))
        top_row.addWidget(self.combo_assets)
        top_row.addStretch(1)
        top_row.addWidget(self.label_db)

        self.web = QWebEngineView(self)
        self.web.loadFinished.connect(self._on_web_loaded)
        self.web.setHtml(self._html_template())

        wrapper = QWidget(self)
        layout = QVBoxLayout(wrapper)
        layout.addLayout(top_row)
        layout.addWidget(self.label_info)
        layout.addWidget(self.web, 1)
        self.setCentralWidget(wrapper)

        self._load_assets()

    def _connect(self):
        conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={self.db_path};"
        return pyodbc.connect(conn_str)

    def _load_assets(self) -> None:
        if not self.db_path:
            raise RuntimeError("Geen default database gevonden in de settings.")
        sql = """
            SELECT DISTINCT asset_rollup
            FROM historical_data_correct
            WHERE asset_rollup IS NOT NULL
            ORDER BY asset_rollup
        """
        with self._connect() as conn:
            rows = conn.cursor().execute(sql).fetchall()
        assets = [str(row[0]).strip().upper() for row in rows if row and row[0]]
        self.combo_assets.blockSignals(True)
        try:
            self.combo_assets.clear()
            self.combo_assets.addItems(assets)
        finally:
            self.combo_assets.blockSignals(False)
        if assets:
            self.combo_assets.setCurrentIndex(0)
            self._on_asset_changed(assets[0])

    def _on_web_loaded(self, ok: bool) -> None:
        self._web_ready = bool(ok)
        if self._web_ready and self._pending_payload is not None:
            self._push_payload(self._pending_payload)
            self._pending_payload = None

    def _fetch_asset_rows(self, asset_rollup: str) -> list[PriceRow]:
        sql = """
            SELECT
                datum,
                asset_rollup,
                [open] AS open_price,
                [high] AS high_price,
                [low] AS low_price,
                [close] AS close_price,
                [volume] AS volume_value
            FROM historical_data_correct
            WHERE asset_rollup = ?
            ORDER BY datum
        """
        out: list[PriceRow] = []
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, asset_rollup)
            for row in cursor.fetchall():
                datum = _safe_date(row[0])
                if datum is None:
                    continue
                out.append(
                    PriceRow(
                        datum=datum,
                        open_price=_safe_float(row[2]),
                        high_price=_safe_float(row[3]),
                        low_price=_safe_float(row[4]),
                        close_price=_safe_float(row[5]),
                        volume=_safe_float(row[6]),
                    )
                )
        return out

    def _current_price(self, rows: list[PriceRow]) -> float | None:
        for row in reversed(rows):
            if row.close_price is not None:
                return row.close_price
            values = [v for v in (row.open_price, row.high_price, row.low_price) if v is not None]
            if values:
                return sum(values) / len(values)
        return None

    def _row_range(self, row: PriceRow) -> tuple[float, float] | None:
        values = [v for v in (row.open_price, row.high_price, row.low_price, row.close_price) if v is not None]
        if not values:
            return None
        low = row.low_price if row.low_price is not None else min(values)
        high = row.high_price if row.high_price is not None else max(values)
        low = min(low, min(values))
        high = max(high, max(values))
        if high < low:
            low, high = high, low
        return low, high

    def _build_payload(self, asset_rollup: str, rows: list[PriceRow]) -> dict:
        current_price = self._current_price(rows)
        if current_price is None:
            return {"asset": asset_rollup, "error": "Geen bruikbare prijsdata gevonden."}

        latest_date = max(row.datum for row in rows)
        rows_12m = [row for row in rows if row.datum >= shift_months(latest_date, 12)]
        valid_ranges_12m = [self._row_range(row) for row in rows_12m]
        valid_ranges_12m = [r for r in valid_ranges_12m if r is not None]
        if not valid_ranges_12m:
            return {"asset": asset_rollup, "error": "Geen OHLC/close data beschikbaar."}

        min_price = min(lo for lo, _hi in valid_ranges_12m)
        max_price = max(hi for _lo, hi in valid_ranges_12m)
        visible_span = max(max_price - min_price, max(current_price * 0.08, 1.0))
        padded_span = visible_span * 1.10
        raw_step = padded_span / TARGET_BUCKETS_12M
        step_cap = max(current_price * 0.01, 0.25)
        step = min(_nice_step(raw_step), step_cap)
        step = max(step, 0.01)
        lower = math.floor((min(min_price, current_price) - 2 * step) / step) * step
        upper = math.ceil((max(max_price, current_price) + 2 * step) / step) * step
        bucket_count = max(24, int(math.ceil((upper - lower) / step)))
        upper = lower + bucket_count * step
        centers = [lower + (idx + 0.5) * step for idx in range(bucket_count)]

        time_series = []
        time_summaries = []
        volume_series = []
        volume_summaries = []
        for months in PERIOD_MONTHS:
            cutoff = shift_months(latest_date, months)
            subset = [row for row in rows if row.datum >= cutoff]
            time_distribution = self._occupancy_distribution(subset, lower, step, bucket_count, weight_mode="time")
            volume_distribution = self._occupancy_distribution(subset, lower, step, bucket_count, weight_mode="volume")
            if not time_distribution:
                continue
            percentile = self._percentile_for_price(time_distribution, lower, step, current_price)
            touched_buckets = sum(1 for value in time_distribution if value > 0)
            time_series.append(
                {
                    "label": f"{months}m",
                    "months": months,
                    "color": PERIOD_COLORS[months],
                    "style": "histogram" if months == 12 else "line",
                    "points": [{"x": centers[idx], "y": time_distribution[idx]} for idx in range(bucket_count)],
                }
            )
            time_summaries.append(
                {
                    "label": f"{months}m",
                    "months": months,
                    "color": PERIOD_COLORS[months],
                    "percentile": percentile,
                    "tail_below": round(percentile, 1),
                    "tail_above": round(max(0.0, 100.0 - percentile), 1),
                    "data_points": len(subset),
                    "buckets": touched_buckets,
                }
            )
            if volume_distribution:
                volume_percentile = self._percentile_for_price(volume_distribution, lower, step, current_price)
                volume_touched_buckets = sum(1 for value in volume_distribution if value > 0)
                valid_volume_points = sum(1 for row in subset if row.volume is not None and row.volume > 0)
                volume_series.append(
                    {
                        "label": f"{months}m",
                        "months": months,
                        "color": PERIOD_COLORS[months],
                        "style": "histogram" if months == 12 else "line",
                        "points": [{"x": centers[idx], "y": volume_distribution[idx]} for idx in range(bucket_count)],
                    }
                )
                volume_summaries.append(
                    {
                        "label": f"{months}m",
                        "months": months,
                        "color": PERIOD_COLORS[months],
                        "percentile": volume_percentile,
                        "tail_below": round(volume_percentile, 1),
                        "tail_above": round(max(0.0, 100.0 - volume_percentile), 1),
                        "data_points": valid_volume_points,
                        "buckets": volume_touched_buckets,
                    }
                )

        return {
            "asset": asset_rollup,
            "current_price": current_price,
            "latest_date": latest_date.isoformat(),
            "step": step,
            "x_min": lower,
            "x_max": upper,
            "time_series": time_series,
            "time_summaries": time_summaries,
            "volume_series": volume_series,
            "volume_summaries": volume_summaries,
        }

    def _occupancy_distribution(
        self,
        rows: list[PriceRow],
        lower: float,
        step: float,
        bucket_count: int,
        *,
        weight_mode: str,
    ) -> list[float]:
        weights = [0.0] * bucket_count
        total_weight = 0.0
        for row in rows:
            range_values = self._row_range(row)
            if range_values is None:
                continue
            row_weight = 1.0
            if weight_mode == "volume":
                row_weight = float(row.volume) if row.volume is not None and row.volume > 0 else 0.0
                if row_weight <= 0:
                    continue
            low, high = range_values
            start_idx = int(math.floor((low - lower) / step))
            end_idx = int(math.floor(((high - lower) / step) - 1e-9))
            if end_idx < start_idx:
                end_idx = start_idx
            start_idx = max(0, start_idx)
            end_idx = min(bucket_count - 1, end_idx)
            if end_idx < 0 or start_idx >= bucket_count:
                continue
            touched = end_idx - start_idx + 1
            if touched <= 0:
                continue
            total_weight += row_weight
            weight = row_weight / touched
            for idx in range(start_idx, end_idx + 1):
                weights[idx] += weight
        if total_weight <= 0:
            return []
        return [value * 100.0 / total_weight for value in weights]

    def _percentile_for_price(self, distribution: list[float], lower: float, step: float, price: float) -> float:
        if not distribution:
            return 0.0
        idx = int(math.floor((price - lower) / step))
        idx = max(0, min(len(distribution) - 1, idx))
        below = sum(distribution[:idx])
        in_bucket = distribution[idx] / 2.0
        return round(min(100.0, max(0.0, below + in_bucket)), 1)

    def _on_asset_changed(self, asset_rollup: str) -> None:
        asset = str(asset_rollup or "").strip().upper()
        if not asset:
            return
        try:
            rows = self._fetch_asset_rows(asset)
            if not rows:
                raise RuntimeError(f"Geen historical rows gevonden voor {asset}.")
            self._asset_rows = rows
            payload = self._build_payload(asset, rows)
            if payload.get("error"):
                raise RuntimeError(str(payload["error"]))
            latest_date = str(payload.get("latest_date") or "")
            current_price = float(payload.get("current_price") or 0.0)
            self.label_info.setText(
                f"{asset} | laatste datapunt: {latest_date} | huidige koersmarker: {current_price:,.2f} | "
                f"auto bucket-step: {float(payload.get('step') or 0.0):,.2f}"
            )
            self._push_payload(payload)
        except Exception as exc:
            self.label_info.setText(str(exc))
            self._push_payload({"asset": asset, "error": str(exc)})

    def _push_payload(self, payload: dict) -> None:
        if not self._web_ready:
            self._pending_payload = dict(payload)
            return
        self.web.page().runJavaScript(f"window.renderChart({json.dumps(payload, ensure_ascii=False)});")

    def _html_template(self) -> str:
        return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <style>
      :root{
        --bg:#f5f3ee;
        --panel:#fffdf8;
        --line:#d8d2c4;
        --text:#2d2a26;
        --muted:#6f6a61;
        --accent:#232323;
      }
      *{ box-sizing:border-box; }
      body{
        margin:0;
        padding:14px;
        background:linear-gradient(180deg,#f1ede3 0%, #faf8f3 100%);
        color:var(--text);
        font-family:Segoe UI, Arial, sans-serif;
      }
      .shell{
        height:100vh;
        display:flex;
        flex-direction:column;
        gap:12px;
      }
      .card{
        background:var(--panel);
        border:1px solid var(--line);
        border-radius:16px;
        box-shadow:0 12px 24px rgba(47, 40, 27, .08);
      }
      .hero{
        padding:16px 18px 8px 18px;
      }
      .title{
        font-size:24px;
        font-weight:800;
        margin:0 0 6px 0;
      }
        .subtitle{
        font-size:13px;
        color:var(--muted);
        margin:0;
      }
      .stats{
        display:grid;
        grid-template-columns:repeat(4, minmax(0, 1fr));
        gap:10px;
        padding:0 18px 16px 18px;
      }
      .stat{
        border:1px solid var(--line);
        border-radius:12px;
        padding:10px 12px;
        background:#fffaf0;
      }
      .stat .k{
        font-size:12px;
        color:var(--muted);
        margin-bottom:6px;
        font-weight:700;
        text-transform:uppercase;
        letter-spacing:.05em;
      }
      .stat .v{
        font-size:22px;
        font-weight:800;
      }
      .section{
        display:flex;
        flex-direction:column;
        gap:8px;
      }
      .section-title{
        font-size:13px;
        font-weight:800;
        color:var(--muted);
        letter-spacing:.04em;
        text-transform:uppercase;
        padding:0 4px;
      }
      .chart-wrap{
        min-height:420px;
        padding:8px 18px 18px 18px;
      }
      .stats{
        display:grid;
        grid-template-columns:repeat(4, minmax(0, 1fr));
        gap:10px;
        padding:0 0 8px 0;
      }
      .chart{
        width:100%;
        height:100%;
        min-height:560px;
        display:block;
      }
      .legend{
        display:flex;
        gap:14px;
        flex-wrap:wrap;
        margin-top:4px;
        padding:0 18px 10px 18px;
      }
      .legend-item{
        display:flex;
        align-items:center;
        gap:8px;
        font-size:12px;
        color:var(--muted);
      }
      .legend-line{
        width:22px;
        height:0;
        border-top:3px solid #000;
      }
      .empty{
        display:flex;
        align-items:center;
        justify-content:center;
        min-height:420px;
        color:var(--muted);
        font-size:16px;
      }
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="card hero">
        <h1 class="title" id="title">Price Occupancy Distribution</h1>
        <p class="subtitle" id="subtitle">Selecteer een asset om de 3m/6m/9m/12m verdelingen te tonen.</p>
      </div>
      <div class="section">
        <div class="section-title">Time Weighted Distribution</div>
        <div class="stats" id="stats-time"></div>
        <div class="card chart-wrap">
          <svg class="chart" id="chart-time" viewBox="0 0 1200 620" preserveAspectRatio="none"></svg>
        </div>
      </div>
      <div class="section">
        <div class="section-title">Volume Weighted Distribution</div>
        <div class="stats" id="stats-volume"></div>
        <div class="card chart-wrap">
          <svg class="chart" id="chart-volume" viewBox="0 0 1200 620" preserveAspectRatio="none"></svg>
        </div>
      </div>
      <div class="legend" id="legend"></div>
    </div>
    <script>
      function fmtPrice(v){
        if(v===null||v===undefined||!Number.isFinite(v)) return "";
        return v.toLocaleString("nl-NL", {minimumFractionDigits: 0, maximumFractionDigits: 2});
      }
      function fmtPct(v){
        if(v===null||v===undefined||!Number.isFinite(v)) return "";
        return v.toLocaleString("nl-NL", {minimumFractionDigits: 1, maximumFractionDigits: 1}) + "%";
      }
      function clearSvg(svg){
        while(svg.firstChild) svg.removeChild(svg.firstChild);
      }
      function svgEl(tag, attrs){
        const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
        Object.entries(attrs||{}).forEach(([k,v]) => el.setAttribute(k, String(v)));
        return el;
      }
      function updateStats(targetId, summaries){
        const wrap = document.getElementById(targetId);
        wrap.innerHTML = "";
        (summaries || []).forEach(item => {
          const div = document.createElement("div");
          div.className = "stat";
          div.innerHTML = `
            <div class="k" style="color:${item.color}">${item.label}</div>
            <div class="v">${fmtPct(item.percentile)}</div>
            <div style="font-size:12px;color:#6f6a61;margin-top:6px;">
              onder: ${fmtPct(item.tail_below)} | boven: ${fmtPct(item.tail_above)}
            </div>
            <div style="font-size:12px;color:#6f6a61;margin-top:4px;">
              datapunten: ${item.data_points || 0} | buckets: ${item.buckets || 0}
            </div>
          `;
          wrap.appendChild(div);
        });
      }
      function updateLegend(payload){
        const wrap = document.getElementById("legend");
        wrap.innerHTML = "";
        (payload.series || []).forEach(item => {
          const div = document.createElement("div");
          div.className = "legend-item";
          div.innerHTML = `<span class="legend-line" style="border-color:${item.color}"></span><span>${item.label}</span>`;
          wrap.appendChild(div);
        });
      }
      function renderEmpty(message){
        document.getElementById("title").textContent = "Price Occupancy Distribution";
        document.getElementById("subtitle").textContent = message || "Geen data.";
        document.getElementById("stats-time").innerHTML = "";
        document.getElementById("stats-volume").innerHTML = "";
        document.getElementById("legend").innerHTML = "";
        ["chart-time", "chart-volume"].forEach(id => {
          const svg = document.getElementById(id);
          clearSvg(svg);
          const foreign = svgEl("foreignObject", {x:0, y:0, width:1200, height:620});
          const div = document.createElement("div");
          div.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
          div.className = "empty";
          div.textContent = message || "Geen data.";
          foreign.appendChild(div);
          svg.appendChild(foreign);
        });
      }
      function renderPlot(svgId, seriesList, currentPrice, xMin, xMax){
        const svg = document.getElementById(svgId);
        clearSvg(svg);
        const width = 1200, height = 620;
        const margin = {left:76, right:28, top:28, bottom:56};
        const plotW = width - margin.left - margin.right;
        const plotH = height - margin.top - margin.bottom;
        const allY = (seriesList || []).flatMap(s => (s.points || []).map(p => p.y || 0));
        const yMax = Math.max(1, ...allY);
        const xToPx = x => margin.left + ((x - xMin) / Math.max(1e-9, (xMax - xMin))) * plotW;
        const yToPx = y => margin.top + plotH - (y / yMax) * plotH;

        svg.appendChild(svgEl("rect", {x:0,y:0,width,height,fill:"#fffdf8"}));

        for(let i=0;i<=5;i++){
          const y = margin.top + (plotH/5)*i;
          svg.appendChild(svgEl("line", {x1:margin.left, y1:y, x2:margin.left+plotW, y2:y, stroke:"#ddd7ca", "stroke-width":1}));
          const value = ((5-i)/5)*yMax;
          const t = svgEl("text", {x:margin.left-10, y:y+4, "text-anchor":"end", fill:"#6f6a61", "font-size":12});
          t.textContent = fmtPct(value);
          svg.appendChild(t);
        }

        const ticks = 8;
        for(let i=0;i<=ticks;i++){
          const x = margin.left + (plotW/ticks)*i;
          const value = xMin + ((xMax - xMin)/ticks)*i;
          svg.appendChild(svgEl("line", {x1:x, y1:margin.top, x2:x, y2:margin.top+plotH, stroke:"#eee7d8", "stroke-width":1}));
          const t = svgEl("text", {x:x, y:margin.top+plotH+24, "text-anchor":"middle", fill:"#6f6a61", "font-size":12});
          t.textContent = fmtPrice(value);
          svg.appendChild(t);
        }

        svg.appendChild(svgEl("line", {x1:margin.left, y1:margin.top+plotH, x2:margin.left+plotW, y2:margin.top+plotH, stroke:"#867f73", "stroke-width":1.5}));
        svg.appendChild(svgEl("line", {x1:margin.left, y1:margin.top, x2:margin.left, y2:margin.top+plotH, stroke:"#867f73", "stroke-width":1.5}));

        const markerX = xToPx(currentPrice);
        svg.appendChild(svgEl("line", {
          x1:markerX, y1:margin.top, x2:markerX, y2:margin.top+plotH,
          stroke:"#101010", "stroke-width":2, "stroke-dasharray":"7 6"
        }));
        const markerLabel = svgEl("text", {
          x:markerX, y:margin.top-8, "text-anchor":"middle", fill:"#101010", "font-size":13, "font-weight":"700"
        });
        markerLabel.textContent = `nu ${fmtPrice(currentPrice)}`;
        svg.appendChild(markerLabel);

        (seriesList || []).forEach(series => {
          if(series.style === "histogram"){
            const barWidth = Math.max(2, (plotW / Math.max(1, (series.points || []).length)) * 0.92);
            (series.points || []).forEach(point => {
              const x = xToPx(point.x) - barWidth / 2;
              const y = yToPx(point.y);
              const h = margin.top + plotH - y;
              svg.appendChild(svgEl("rect", {
                x, y, width:barWidth, height:h,
                fill:series.color, opacity:"0.28", stroke:series.color, "stroke-width":"0.5"
              }));
            });
          } else {
            const points = (series.points || []).map(p => `${xToPx(p.x)},${yToPx(p.y)}`).join(" ");
            svg.appendChild(svgEl("polyline", {
              points,
              fill:"none",
              stroke:series.color,
              "stroke-width":3,
              "stroke-linejoin":"round",
              "stroke-linecap":"round"
            }));
          }
        });
      }
      window.renderChart = function(payload){
        if(!payload || payload.error || !(payload.time_series||[]).length){
          renderEmpty(payload && payload.error ? payload.error : "Geen data.");
          return;
        }
        document.getElementById("title").textContent = `${payload.asset} price occupancy`;
        document.getElementById("subtitle").textContent =
          `Koersverdeling op basis van daily low-high buckets. Huidige koersmarker: ${fmtPrice(payload.current_price)} | laatste datapunt: ${payload.latest_date} | bucket-step: ${fmtPrice(payload.step)}`;
        updateStats("stats-time", payload.time_summaries || []);
        updateStats("stats-volume", payload.volume_summaries || []);
        updateLegend({series: payload.time_series || []});
        renderPlot("chart-time", payload.time_series || [], payload.current_price, payload.x_min, payload.x_max);
        renderPlot("chart-volume", payload.volume_series || [], payload.current_price, payload.x_min, payload.x_max);
      };
    </script>
  </body>
</html>
"""


def main() -> int:
    app = QApplication(sys.argv)
    try:
        viewer = PriceDistributionViewer(resolve_db_path())
    except Exception as exc:
        QMessageBox.critical(None, "Start mislukt", str(exc))
        return 1
    viewer.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

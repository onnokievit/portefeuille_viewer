from __future__ import annotations

import json

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.ui_logica.chart_dialog_settings import (
    cash_series_definitions,
    create_line_settings_table,
    filter_payload_by_chart_start_date,
    inject_line_settings,
    make_start_date_controls,
    populate_line_settings_table,
)
from portefeuille_viewer.services.cash_management_result_chart_service import (
    build_cash_management_result_chart_payload,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:
    QWebEngineView = None


CHART_ID = "cash_management_year_result_percent"

_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
*{box-sizing:border-box}
html,body{width:100%;height:100%;overflow:hidden}
body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#ffffff;color:#202020}
.app{display:flex;flex-direction:column;height:100vh}
.top{display:flex;justify-content:space-between;align-items:center;padding:8px 14px;background:#ffffff;border-bottom:1px solid #d8d8d8}
.title{font-size:16px;font-weight:700}
.meta{font-size:12px;color:#666}
.controls{display:flex;gap:8px;align-items:center}
.mode{border:1px solid #b8c3d3;background:#fff;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px}
.mode.active{background:#dbeafe;border-color:#2f80ed}
.legend{display:flex;gap:24px;align-items:center;justify-content:center;flex-wrap:wrap;padding:8px 10px;font-size:12px;color:#555;border-bottom:1px solid #e2e2e2}
.leg{display:flex;align-items:center;gap:8px}
.sw{width:28px;height:0;border-top-width:2px;border-top-style:dashed}
.chart-wrap{flex:1;padding:16px;overflow:hidden}
.chart-card{height:100%;border:1px solid #dddddd;background:#fff;position:relative}
#chart{width:100%;height:100%}
#tooltip{position:fixed;display:none;pointer-events:none;background:rgba(32,32,32,.92);color:#fff;padding:6px 8px;border-radius:4px;font-size:12px;z-index:9999;white-space:nowrap}
.empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#777;font-size:14px}
</style>
</head>
<body>
<div class="app">
  <div class="top">
    <div>
      <div class="title">% jaarresultaat per broker</div>
      <div class="meta" id="meta">Geen data geladen</div>
    </div>
    <div class="controls">
      <button class="mode" id="modeStart">Startkapitaal</button>
      <button class="mode active" id="modeAverage">Gemiddeld kapitaal</button>
    </div>
  </div>
  <div class="legend" id="legend"></div>
  <div class="chart-wrap">
    <div class="chart-card" id="chartBox">
      <svg id="chart"></svg>
      <div class="empty" id="empty">Geen data</div>
    </div>
  </div>
</div>
<div id="tooltip"></div>
<script>
const COLORS = {
  degiro: "#22b7ff",
  lynx: "#ff2f2f",
  interactive: "#2cc96f",
  total: "#4f7fd9"
};
let __lastPayload = null;
let __resizeTimer = null;
let __denominatorMode = "average";

function fmtPct(v){
  if(v===null || v===undefined || Number.isNaN(v)) return "-";
  return new Intl.NumberFormat("nl-NL", {minimumFractionDigits:1, maximumFractionDigits:1}).format(v) + "%";
}

function fmtDateShort(isoDate){
  if(!isoDate || typeof isoDate !== "string" || isoDate.length < 10) return "";
  return `${isoDate.slice(8,10)}-${isoDate.slice(5,7)}-${isoDate.slice(2,4)}`;
}

function yearOf(isoDate){ return String(isoDate || "").slice(0,4); }
function brokerColor(name){ return COLORS[name] || "#7b8794"; }
function floorToStep(value, step){ return Math.floor(value / step) * step; }
function ceilToStep(value, step){ return Math.ceil(value / step) * step; }

function niceStep(range){
  const rough = Math.max(1, range / 12);
  if(rough <= 2) return 2;
  if(rough <= 5) return 5;
  if(rough <= 10) return 10;
  if(rough <= 20) return 20;
  if(rough <= 50) return 50;
  return 100;
}

function buildLegend(brokers){
  const legend = document.getElementById("legend");
  legend.innerHTML = "";
  (brokers || []).forEach((broker)=>{
    const el = document.createElement("div");
    el.className = "leg";
    el.innerHTML = `<span class="sw" style="border-top-color:${brokerColor(broker)}"></span><span>% pj ${broker}</span>`;
    legend.appendChild(el);
  });
  const total = document.createElement("div");
  total.className = "leg";
  total.innerHTML = `<span class="sw" style="border-top-color:${COLORS.total}"></span><span>% pj totaal</span>`;
  legend.appendChild(total);
}

function linePath(points, xScale, yScale){
  if(!points.length) return "";
  return points.map((p, idx)=>`${idx===0 ? "M":"L"}${xScale(idx)},${yScale(p.y)}`).join(" ");
}

function splitSeriesByYear(series){
  const groups = [];
  let currentYear = null;
  let current = [];
  series.forEach((p)=>{
    const yr = yearOf(p.date);
    if(currentYear !== null && yr !== currentYear){
      if(current.length) groups.push(current);
      current = [];
    }
    currentYear = yr;
    current.push(p);
  });
  if(current.length) groups.push(current);
  return groups;
}

function yearlyPercentSeries(rawSeries, valueKey, capitalKey){
  const states = new Map();
  return rawSeries.filter((p)=>{
    const capital = Number(p[capitalKey]);
    return Number.isFinite(capital) && Math.abs(capital) > 0.000001;
  }).map((p)=>{
    const yr = yearOf(p.date);
    if(!states.has(yr)){
      states.set(yr, {
        baseValue: p[valueKey],
        baseCapital: p[capitalKey],
        capitalSum: 0,
        capitalCount: 0
      });
    }
    const state = states.get(yr);
    const capital = Number(p[capitalKey]);
    if(Number.isFinite(capital)){
      state.capitalSum += capital;
      state.capitalCount += 1;
    }
    const result = Number(p[valueKey]) - Number(state.baseValue);
    const denominator = __denominatorMode === "average"
      ? (state.capitalCount ? state.capitalSum / state.capitalCount : null)
      : Number(state.baseCapital);
    const pct = denominator && Number.isFinite(denominator) && Math.abs(denominator) > 0.000001
      ? (result / denominator) * 100
      : null;
    return {...p, y: pct};
  }).filter((p)=>p.y!==null && p.y!==undefined && Number.isFinite(p.y));
}

function drawSegmentedSeries(svg, series, dateIndex, xScale, yScale, color, width, style){
  splitSeriesByYear(series).forEach((segment)=>{
    if(!segment.length) return;
    const path = document.createElementNS("http://www.w3.org/2000/svg","path");
    path.setAttribute("d", linePath(segment.map((p)=>({y:p.y})), (idx)=>{
      const globalIdx = dateIndex.get(segment[idx].date);
      return xScale(globalIdx);
    }, yScale));
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", color);
    path.setAttribute("stroke-width", width);
    if(style === "dashed"){
      path.setAttribute("stroke-dasharray", "7 6");
    }
    svg.appendChild(path);
  });
}

function setMode(mode){
  __denominatorMode = mode;
  document.getElementById("modeStart").classList.toggle("active", mode === "start");
  document.getElementById("modeAverage").classList.toggle("active", mode === "average");
  if(__lastPayload) render(__lastPayload);
}

function render(payload){
  __lastPayload = payload;
  const points = Array.isArray(payload?.points) ? payload.points : [];
  const brokers = Array.isArray(payload?.brokers) ? payload.brokers : [];
  const stats = payload?.stats || {};
  const lineWidth = Number(payload?.line_width || 1.6);
  const lineWidths = payload?.line_widths || {};
  const lineStyles = payload?.line_styles || {};
  buildLegend(brokers);

  const meta = document.getElementById("meta");
  const modeLabel = __denominatorMode === "average" ? "gemiddeld kapitaal" : "startkapitaal";
  meta.textContent = points.length
    ? `${stats.start_date || "-"} t/m ${stats.end_date || "-"} | noemer=${modeLabel}`
    : "Geen data geladen";

  const empty = document.getElementById("empty");
  const svg = document.getElementById("chart");
  const box = document.getElementById("chartBox");
  const tip = document.getElementById("tooltip");
  const width = Math.max(800, box.clientWidth || 800);
  const height = Math.max(460, box.clientHeight || 460);
  svg.setAttribute("width", String(width));
  svg.setAttribute("height", String(height));
  svg.innerHTML = "";

  if(!points.length){
    empty.style.display = "flex";
    return;
  }
  empty.style.display = "none";

  const byDate = new Map();
  points.forEach((row)=>{
    if(!byDate.has(row.date)){
      byDate.set(row.date, {date: row.date, total_profit: row.total_profit, total_value: row.total_value, brokers:{}});
    }
    byDate.get(row.date).brokers[row.broker] = row;
  });
  const dates = Array.from(byDate.values()).sort((a,b)=> String(a.date).localeCompare(String(b.date)));
  const dateIndex = new Map();
  dates.forEach((d, idx)=> dateIndex.set(d.date, idx));

  const totalRaw = dates
    .filter((d)=>d.total_profit!==null && d.total_profit!==undefined && d.total_value!==null && d.total_value!==undefined && Math.abs(Number(d.total_value)) > 0.000001)
    .map((d)=>({date:d.date, profit:Number(d.total_profit), capital:Number(d.total_value)}));
  const totalSeries = yearlyPercentSeries(totalRaw, "profit", "capital");

  const brokerSeries = {};
  brokers.forEach((broker)=>{
    const raw = dates.map((d)=>({
      date: d.date,
      profit: d.brokers[broker]?.profit,
      capital: d.brokers[broker]?.ending_balance
    })).filter((d)=>d.profit!==null && d.profit!==undefined && d.capital!==null && d.capital!==undefined && Math.abs(Number(d.capital)) > 0.000001);
    brokerSeries[broker] = yearlyPercentSeries(raw, "profit", "capital");
  });

  const pctByDate = new Map();
  totalSeries.forEach((p)=>{
    if(!pctByDate.has(p.date)) pctByDate.set(p.date, {brokers:{}});
    pctByDate.get(p.date).total = p.y;
  });
  Object.entries(brokerSeries).forEach(([broker, series])=>{
    series.forEach((p)=>{
      if(!pctByDate.has(p.date)) pctByDate.set(p.date, {brokers:{}});
      pctByDate.get(p.date).brokers[broker] = p.y;
    });
  });

  const allVals = [0];
  totalSeries.forEach((p)=>allVals.push(p.y));
  Object.values(brokerSeries).forEach((series)=>series.forEach((p)=>allVals.push(p.y)));
  const minRaw = Math.min(...allVals);
  const maxRaw = Math.max(...allVals);
  const step = niceStep(maxRaw - minRaw || 1);
  const yMin = floorToStep(minRaw, step);
  const yMax = ceilToStep(maxRaw, step);
  const plot = {l:42,r:76,t:14,b:52};
  const innerW = width - plot.l - plot.r;
  const innerH = height - plot.t - plot.b;
  const xScale = (idx)=> plot.l + (dates.length <= 1 ? innerW/2 : (idx/(dates.length-1))*innerW);
  const yScale = (val)=> plot.t + innerH - ((val - yMin)/(yMax - yMin || 1)) * innerH;

  for(let yVal = yMin; yVal <= yMax + step/2; yVal += step){
    const y = yScale(yVal);
    const line = document.createElementNS("http://www.w3.org/2000/svg","line");
    line.setAttribute("x1", plot.l);
    line.setAttribute("x2", width-plot.r);
    line.setAttribute("y1", y);
    line.setAttribute("y2", y);
    line.setAttribute("stroke", yVal === 0 ? "#969696" : "#dfdfdf");
    line.setAttribute("stroke-width", yVal === 0 ? "1.4" : "1");
    svg.appendChild(line);

    const txt = document.createElementNS("http://www.w3.org/2000/svg","text");
    txt.setAttribute("x", width-plot.r+8);
    txt.setAttribute("y", y+4);
    txt.setAttribute("font-size", "11");
    txt.setAttribute("fill", "#555");
    txt.textContent = fmtPct(yVal);
    svg.appendChild(txt);
  }

  const stride = Math.max(1, Math.floor(dates.length / 18));
  dates.forEach((d, idx)=>{
    if(idx % stride !== 0 && idx !== dates.length-1) return;
    const x = xScale(idx);
    const txt = document.createElementNS("http://www.w3.org/2000/svg","text");
    txt.setAttribute("x", x);
    txt.setAttribute("y", height-plot.b+18);
    txt.setAttribute("font-size", "11");
    txt.setAttribute("fill", "#555");
    txt.setAttribute("text-anchor", "middle");
    txt.setAttribute("transform", `rotate(-45 ${x} ${height-plot.b+18})`);
    txt.textContent = fmtDateShort(d.date);
    svg.appendChild(txt);
  });

  brokers.forEach((broker)=>{
    const seriesId = `broker:${broker}`;
    drawSegmentedSeries(svg, brokerSeries[broker] || [], dateIndex, xScale, yScale, brokerColor(broker), String(Number(lineWidths[seriesId] || lineWidth)), lineStyles[seriesId] || "dashed");
  });
  drawSegmentedSeries(svg, totalSeries, dateIndex, xScale, yScale, COLORS.total, String(Number(lineWidths["total_year_percent"] || lineWidth)), lineStyles["total_year_percent"] || "dashed");

  dates.forEach((d, idx)=>{
    const x = xScale(idx);
    const hit = document.createElementNS("http://www.w3.org/2000/svg","line");
    hit.setAttribute("x1", x);
    hit.setAttribute("x2", x);
    hit.setAttribute("y1", plot.t);
    hit.setAttribute("y2", height-plot.b);
    hit.setAttribute("stroke", "transparent");
    hit.setAttribute("stroke-width", "10");
    hit.addEventListener("mousemove", (ev)=>{
      const pct = pctByDate.get(d.date) || {brokers:{}};
      const brokerBits = brokers.map((broker)=>`${broker}: ${fmtPct(pct.brokers[broker])}`).join(" | ");
      tip.style.display = "block";
      tip.style.left = (ev.clientX + 12) + "px";
      tip.style.top = (ev.clientY + 12) + "px";
      tip.textContent = `${d.date} | totaal ${fmtPct(pct.total)} | ${brokerBits}`;
    });
    hit.addEventListener("mouseleave", ()=> tip.style.display = "none");
    svg.appendChild(hit);
  });
}

document.getElementById("modeStart").addEventListener("click", ()=>setMode("start"));
document.getElementById("modeAverage").addEventListener("click", ()=>setMode("average"));
window.renderYearResultPercentChart = render;
window.addEventListener("resize", ()=>{
  if(!__lastPayload) return;
  window.clearTimeout(__resizeTimer);
  __resizeTimer = window.setTimeout(()=>render(__lastPayload), 80);
});
</script>
</body>
</html>
"""


class _CashYearResultPercentChartWorker(QThread):
    payload_ready = Signal(dict)
    error_ready = Signal(str)

    def run(self) -> None:
        try:
            payload = build_cash_management_result_chart_payload()
        except Exception as exc:
            self.error_ready.emit(f"{type(exc).__name__}: {exc}")
            return
        self.payload_ready.emit(payload)


class CashManagementYearResultPercentChartDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("% Jaarresultaat Chart")
        self.resize(1400, 900)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._settings = get_settings()
        self._worker = None
        self._pending_payload = None
        self._page_ready = False

        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self._status = QLabel("Laden...")
        toolbar.addWidget(self._status)
        toolbar.addStretch(1)
        start_checkbox, start_edit, clear_start = make_start_date_controls(
            self,
            self._settings,
            CHART_ID,
            self._rerender_current_payload,
        )
        toolbar.addWidget(start_checkbox)
        toolbar.addWidget(start_edit)
        toolbar.addWidget(clear_start)
        self._refresh_button = QPushButton("Refresh")
        self._refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(self._refresh_button)
        root.addLayout(toolbar)
        self._line_settings_table = create_line_settings_table(self)
        root.addWidget(self._line_settings_table)

        if QWebEngineView is None:
            fallback = QLabel("QWebEngineView niet beschikbaar.")
            fallback.setAlignment(Qt.AlignCenter)
            root.addWidget(fallback)
            self._web = None
            return

        self._web = QWebEngineView(self)
        root.addWidget(self._web, 1)
        self._web.loadFinished.connect(self._on_load_finished)
        self._web.setHtml(_HTML)
        self.refresh()

    def refresh(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._status.setText("% jaarresultaat chart laden...")
        self._refresh_button.setEnabled(False)
        self._worker = _CashYearResultPercentChartWorker(self)
        self._worker.payload_ready.connect(self._on_payload_ready)
        self._worker.error_ready.connect(self._on_payload_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_load_finished(self, ok: bool) -> None:
        self._page_ready = bool(ok)
        if ok and self._pending_payload is not None:
            self._render_payload(self._pending_payload)

    def _on_payload_ready(self, payload: dict) -> None:
        self._pending_payload = payload
        self._populate_line_settings(payload)
        points = payload.get("points") or []
        stats = payload.get("stats") or {}
        self._status.setText(
            f"{stats.get('start_date') or '-'} t/m {stats.get('end_date') or '-'} | "
            f"brokers={stats.get('brokers') or 0} | punten={stats.get('points') or 0}"
        )
        if self._page_ready:
            self._render_payload(payload)
        elif not points:
            self._status.setText("Geen % jaarresultaat chart data gevonden.")

    def _on_payload_error(self, message: str) -> None:
        self._status.setText(f"Fout bij laden: {message}")

    def _on_worker_finished(self) -> None:
        self._refresh_button.setEnabled(True)
        self._worker = None

    def _render_payload(self, payload: dict) -> None:
        if self._web is None:
            return
        payload = filter_payload_by_chart_start_date(payload, self._settings, CHART_ID)
        payload = inject_line_settings(payload, self._settings, CHART_ID)
        js = f"window.renderYearResultPercentChart({json.dumps(payload)});"
        self._web.page().runJavaScript(js)

    def _rerender_current_payload(self) -> None:
        if self._pending_payload is not None and self._page_ready:
            self._render_payload(self._pending_payload)

    def _populate_line_settings(self, payload: dict) -> None:
        populate_line_settings_table(
            self._line_settings_table,
            self,
            self._settings,
            CHART_ID,
            cash_series_definitions(
                payload.get("brokers") or [],
                "total_year_percent",
                "% pj totaal",
                "% pj",
                "dashed",
            ),
            self._rerender_current_payload,
        )


_CASH_MANAGEMENT_YEAR_RESULT_PERCENT_CHART_DIALOG_INSTANCE: CashManagementYearResultPercentChartDialog | None = None


def open_cash_management_year_result_percent_chart_dialog(parent=None) -> None:
    global _CASH_MANAGEMENT_YEAR_RESULT_PERCENT_CHART_DIALOG_INSTANCE
    if _CASH_MANAGEMENT_YEAR_RESULT_PERCENT_CHART_DIALOG_INSTANCE is None:
        _CASH_MANAGEMENT_YEAR_RESULT_PERCENT_CHART_DIALOG_INSTANCE = CashManagementYearResultPercentChartDialog(parent)
        _CASH_MANAGEMENT_YEAR_RESULT_PERCENT_CHART_DIALOG_INSTANCE.destroyed.connect(
            lambda *_args: _clear_cash_management_year_result_percent_chart_dialog_instance()
        )
    else:
        _CASH_MANAGEMENT_YEAR_RESULT_PERCENT_CHART_DIALOG_INSTANCE.refresh()
    _CASH_MANAGEMENT_YEAR_RESULT_PERCENT_CHART_DIALOG_INSTANCE.show()
    _CASH_MANAGEMENT_YEAR_RESULT_PERCENT_CHART_DIALOG_INSTANCE.raise_()
    _CASH_MANAGEMENT_YEAR_RESULT_PERCENT_CHART_DIALOG_INSTANCE.activateWindow()


def _clear_cash_management_year_result_percent_chart_dialog_instance() -> None:
    global _CASH_MANAGEMENT_YEAR_RESULT_PERCENT_CHART_DIALOG_INSTANCE
    _CASH_MANAGEMENT_YEAR_RESULT_PERCENT_CHART_DIALOG_INSTANCE = None

from __future__ import annotations

import json

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget, QHBoxLayout

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.ui_logica.chart_dialog_settings import (
    cash_series_definitions,
    create_line_settings_table,
    filter_payload_by_chart_start_date,
    inject_line_settings,
    make_start_date_controls,
    populate_line_settings_table,
)
from portefeuille_viewer.services.cash_management_chart_service import (
    build_cash_management_chart_payload,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:
    QWebEngineView = None


CHART_ID = "cash_management_value"

_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
*{box-sizing:border-box}
html,body{width:100%;height:100%;overflow:hidden}
body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#f4f7fb;color:#10243e}
.app{display:flex;flex-direction:column;height:100vh}
.top{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:#ffffff;border-bottom:1px solid #d7e0ea}
.title{font-size:18px;font-weight:700}
.meta{font-size:12px;color:#58708c}
.chart-wrap{flex:1;padding:10px 14px 14px 14px;overflow:hidden}
.card{height:100%;background:#ffffff;border:1px solid #d7e0ea;border-radius:12px;padding:10px 10px 6px 10px;display:flex;flex-direction:column}
.legend{display:flex;gap:18px;align-items:center;flex-wrap:wrap;padding:2px 4px 8px 4px;font-size:12px;color:#34506e}
.leg{display:flex;align-items:center;gap:8px}
.sw{width:24px;height:0;border-top-width:3px;border-top-style:solid}
.sw.dash{border-top-style:dashed}
#chartBox{position:relative;flex:1;min-height:320px;overflow:hidden}
#chart{width:100%;height:100%}
#tooltip{position:fixed;display:none;pointer-events:none;background:rgba(16,36,62,.92);color:#fff;padding:6px 8px;border-radius:6px;font-size:12px;z-index:9999;white-space:nowrap}
.empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#7f92a8;font-size:14px}
</style>
</head>
<body>
<div class="app">
  <div class="top">
    <div>
      <div class="title">Cash Management Chart</div>
      <div class="meta" id="meta">Geen data geladen</div>
    </div>
  </div>
  <div class="chart-wrap">
    <div class="card">
      <div class="legend" id="legend"></div>
      <div id="chartBox">
        <svg id="chart"></svg>
        <div class="empty" id="empty">Geen data</div>
      </div>
    </div>
  </div>
</div>
<div id="tooltip"></div>
<script>
const COLORS = {
  degiro: "#ff3b30",
  lynx: "#2ea8ff",
  interactive: "#1fbf75"
};
let __lastPayload = null;
let __resizeTimer = null;

function fmt(v){
  if(v===null || v===undefined || Number.isNaN(v)) return "-";
  return new Intl.NumberFormat("nl-NL", {maximumFractionDigits:0}).format(v);
}

function fmtDateShort(isoDate){
  if(!isoDate || typeof isoDate !== "string" || isoDate.length < 10) return "";
  const yyyy = isoDate.slice(0,4);
  const mm = isoDate.slice(5,7);
  const dd = isoDate.slice(8,10);
  return `${dd}-${mm}-${yyyy.slice(2)}`;
}

function floorToStep(value, step){
  return Math.floor(value / step) * step;
}

function ceilToStep(value, step){
  return Math.ceil(value / step) * step;
}

function brokerColor(name){
  return COLORS[name] || "#7b8794";
}

function buildLegend(brokers){
  const legend = document.getElementById("legend");
  legend.innerHTML = "";
  const total = document.createElement("div");
  total.className = "leg";
  total.innerHTML = `<span class="sw" style="border-top-color:#111111"></span><span>Total value</span>`;
  legend.appendChild(total);
  (brokers || []).forEach((broker)=>{
    const el = document.createElement("div");
    el.className = "leg";
    el.innerHTML = `<span class="sw dash" style="border-top-color:${brokerColor(broker)}"></span><span>${broker}</span>`;
    legend.appendChild(el);
  });
}

function linePath(points, xScale, yScale){
  if(!points.length) return "";
  let d = "";
  points.forEach((p, idx)=>{
    const x = xScale(idx);
    const y = yScale(p.y);
    d += `${idx===0 ? "M":"L"}${x},${y} `;
  });
  return d.trim();
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
  meta.textContent = points.length
    ? `${stats.start_date || "-"} t/m ${stats.end_date || "-"} | brokers=${stats.brokers || 0} | punten=${stats.points || 0}`
    : "Geen data geladen";

  const empty = document.getElementById("empty");
  const svg = document.getElementById("chart");
  const box = document.getElementById("chartBox");
  const tip = document.getElementById("tooltip");
  const width = Math.max(700, box.clientWidth || 700);
  const height = Math.max(420, box.clientHeight || 420);
  svg.setAttribute("width", String(width));
  svg.setAttribute("height", String(height));
  svg.removeAttribute("viewBox");
  svg.innerHTML = "";

  if(!points.length){
    empty.style.display = "flex";
    return;
  }
  empty.style.display = "none";

  const byDate = new Map();
  points.forEach((row)=>{
    if(!byDate.has(row.date)){
      byDate.set(row.date, {date: row.date, total_value: row.total_value, total_invested: row.total_invested, total_profit: row.total_profit, brokers:{}});
    }
    byDate.get(row.date).brokers[row.broker] = row;
  });
  const dates = Array.from(byDate.values()).sort((a,b)=> String(a.date).localeCompare(String(b.date)));
  const dateIndex = new Map();
  dates.forEach((d, idx)=> dateIndex.set(d.date, idx));
  const totalSeries = dates.filter(d=>d.total_value!==null && d.total_value!==undefined).map((d)=>({date:d.date,y:Number(d.total_value)}));
  const brokerSeries = {};
  brokers.forEach((broker)=>{
    brokerSeries[broker] = dates.map((d)=>({
      date: d.date,
      y: d.brokers[broker]?.invested_stacked
    })).filter((d)=>d.y!==null && d.y!==undefined);
  });

  const allVals = [];
  totalSeries.forEach((p)=>allVals.push(p.y));
  Object.values(brokerSeries).forEach((series)=>series.forEach((p)=>allVals.push(p.y)));
  const minRaw = Math.min(...allVals, 0);
  const maxRaw = Math.max(...allVals, 0);
  const gridStep = 25000;
  const yMin = minRaw < 0 ? floorToStep(minRaw, gridStep) : 0;
  const yMax = Math.max(gridStep, ceilToStep(maxRaw, gridStep));
  const plot = {l:60,r:70,t:10,b:42};
  const innerW = width - plot.l - plot.r;
  const innerH = height - plot.t - plot.b;
  const xScale = (idx)=> plot.l + (dates.length <= 1 ? innerW/2 : (idx/(dates.length-1))*innerW);
  const yScale = (val)=> plot.t + innerH - ((val - yMin)/(yMax - yMin || 1)) * innerH;

  for(let yVal = yMin; yVal <= yMax; yVal += gridStep){
    const y = yScale(yVal);
    const line = document.createElementNS("http://www.w3.org/2000/svg","line");
    line.setAttribute("x1", plot.l);
    line.setAttribute("x2", width-plot.r);
    line.setAttribute("y1", y);
    line.setAttribute("y2", y);
    line.setAttribute("stroke", "#d6d6d6");
    line.setAttribute("stroke-width", "1");
    svg.appendChild(line);

    const txt = document.createElementNS("http://www.w3.org/2000/svg","text");
    txt.setAttribute("x", width-plot.r+6);
    txt.setAttribute("y", y+4);
    txt.setAttribute("font-size", "11");
    txt.setAttribute("fill", "#5c738e");
    txt.textContent = fmt(yVal);
    svg.appendChild(txt);
  }

  const axis = document.createElementNS("http://www.w3.org/2000/svg","line");
  axis.setAttribute("x1", plot.l);
  axis.setAttribute("x2", width-plot.r);
  axis.setAttribute("y1", height-plot.b);
  axis.setAttribute("y2", height-plot.b);
  axis.setAttribute("stroke", "#8fa1b3");
  svg.appendChild(axis);

  const stride = Math.max(1, Math.floor(dates.length / 16));
  dates.forEach((d, idx)=>{
    if(idx % stride !== 0 && idx !== dates.length-1) return;
    const x = xScale(idx);
    const tick = document.createElementNS("http://www.w3.org/2000/svg","line");
    tick.setAttribute("x1", x);
    tick.setAttribute("x2", x);
    tick.setAttribute("y1", height-plot.b);
    tick.setAttribute("y2", height-plot.b+5);
    tick.setAttribute("stroke", "#8fa1b3");
    svg.appendChild(tick);

    const txt = document.createElementNS("http://www.w3.org/2000/svg","text");
    txt.setAttribute("x", x);
    txt.setAttribute("y", height-plot.b+18);
    txt.setAttribute("font-size", "11");
    txt.setAttribute("fill", "#5c738e");
    txt.setAttribute("text-anchor", "middle");
    txt.setAttribute("transform", `rotate(-45 ${x} ${height-plot.b+18})`);
    txt.textContent = fmtDateShort(d.date);
    svg.appendChild(txt);
  });

  brokers.forEach((broker)=>{
    const series = brokerSeries[broker] || [];
    if(!series.length) return;
    const path = document.createElementNS("http://www.w3.org/2000/svg","path");
    path.setAttribute("d", linePath(series.map((p)=>({y:p.y})), (idx)=>{
      const globalIdx = dateIndex.get(series[idx].date);
      return xScale(globalIdx);
    }, yScale));
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", brokerColor(broker));
    const seriesId = `broker:${broker}`;
    path.setAttribute("stroke-width", String(Number(lineWidths[seriesId] || lineWidth)));
    if((lineStyles[seriesId] || "dashed") === "dashed"){
      path.setAttribute("stroke-dasharray", "7 6");
    }
    svg.appendChild(path);
  });

  if(totalSeries.length){
    const path = document.createElementNS("http://www.w3.org/2000/svg","path");
    path.setAttribute("d", linePath(totalSeries.map((p)=>({y:p.y})), (idx)=>{
      const globalIdx = dateIndex.get(totalSeries[idx].date);
      return xScale(globalIdx);
    }, yScale));
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "#111111");
    path.setAttribute("stroke-width", String(Number(lineWidths["total_value"] || lineWidth)));
    if((lineStyles["total_value"] || "solid") === "dashed"){
      path.setAttribute("stroke-dasharray", "7 6");
    }
    svg.appendChild(path);
  }

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
      const brokerBits = brokers.map((broker)=>{
        const own = d.brokers[broker]?.invested_cumulative;
        const stacked = d.brokers[broker]?.invested_stacked;
        return `${broker}: own ${fmt(own)} | stacked ${fmt(stacked)}`;
      }).join(" | ");
      tip.style.display = "block";
      tip.style.left = (ev.clientX + 12) + "px";
      tip.style.top = (ev.clientY + 12) + "px";
      tip.textContent = `${d.date} | total ${fmt(d.total_value)} | invested ${fmt(d.total_invested)} | profit ${fmt(d.total_profit)} | ${brokerBits}`;
    });
    hit.addEventListener("mouseleave", ()=> tip.style.display = "none");
    svg.appendChild(hit);
  });
}

window.renderChart = render;
window.addEventListener("resize", ()=>{
  if(!__lastPayload) return;
  window.clearTimeout(__resizeTimer);
  __resizeTimer = window.setTimeout(()=>{
    render(__lastPayload);
  }, 80);
});
</script>
</body>
</html>
"""


class _CashChartWorker(QThread):
    payload_ready = Signal(dict)
    error_ready = Signal(str)

    def run(self) -> None:
        try:
            payload = build_cash_management_chart_payload()
        except Exception as exc:
            self.error_ready.emit(f"{type(exc).__name__}: {exc}")
            return
        self.payload_ready.emit(payload)


class CashManagementChartDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cash Management Chart")
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
        self._status.setText("Chart laden...")
        self._refresh_button.setEnabled(False)
        self._worker = _CashChartWorker(self)
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
            self._status.setText("Geen cash chart data gevonden.")

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
        js = f"window.renderChart({json.dumps(payload)});"
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
                "total_value",
                "Total value",
                "",
                "solid",
            ),
            self._rerender_current_payload,
        )


_CASH_MANAGEMENT_CHART_DIALOG_INSTANCE: CashManagementChartDialog | None = None


def open_cash_management_chart_dialog(parent=None) -> None:
    global _CASH_MANAGEMENT_CHART_DIALOG_INSTANCE
    if _CASH_MANAGEMENT_CHART_DIALOG_INSTANCE is None:
        _CASH_MANAGEMENT_CHART_DIALOG_INSTANCE = CashManagementChartDialog(parent)
        _CASH_MANAGEMENT_CHART_DIALOG_INSTANCE.destroyed.connect(
            lambda *_args: _clear_cash_management_chart_dialog_instance()
        )
    else:
        _CASH_MANAGEMENT_CHART_DIALOG_INSTANCE.refresh()
    _CASH_MANAGEMENT_CHART_DIALOG_INSTANCE.show()
    _CASH_MANAGEMENT_CHART_DIALOG_INSTANCE.raise_()
    _CASH_MANAGEMENT_CHART_DIALOG_INSTANCE.activateWindow()


def _clear_cash_management_chart_dialog_instance() -> None:
    global _CASH_MANAGEMENT_CHART_DIALOG_INSTANCE
    _CASH_MANAGEMENT_CHART_DIALOG_INSTANCE = None

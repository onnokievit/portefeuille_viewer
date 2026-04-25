from __future__ import annotations

import json

from PySide6.QtCore import QDate, QItemSelectionModel, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDateEdit,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QComboBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.services.year_result_vs_indices_service import (
    build_year_result_vs_indices_payload,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:
    QWebEngineView = None


PORTFOLIO_OPTIONS = [
    ("total", "Totaal"),
    ("degiro", "Degiro"),
    ("lynx", "Lynx"),
    ("interactive", "Interactive"),
]
CHART_ID = "year_result_vs_indices"


_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
*{box-sizing:border-box}
html,body{width:100%;height:100%;overflow:hidden}
body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#fff;color:#202020}
.app{display:flex;flex-direction:column;height:100vh}
.top{padding:8px 14px;background:#fff;border-bottom:1px solid #ddd}
.title{font-size:16px;font-weight:700}
.meta{font-size:12px;color:#666}
.legend{display:flex;gap:22px;align-items:center;justify-content:center;flex-wrap:wrap;padding:8px 10px;font-size:12px;color:#555;border-bottom:1px solid #e2e2e2}
.leg{display:flex;align-items:center;gap:7px}
.sw{width:28px;height:0;border-top:2px solid #000}
.dash{border-top-style:dashed}
.chart-wrap{flex:1;padding:16px;overflow:hidden}
.chart-card{height:100%;border:1px solid #ddd;position:relative}
#chart{width:100%;height:100%}
#tooltip{position:fixed;display:none;pointer-events:none;background:rgba(32,32,32,.92);color:#fff;padding:6px 8px;border-radius:4px;font-size:12px;z-index:9999;white-space:nowrap}
.empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#777;font-size:14px}
</style>
</head>
<body>
<div class="app">
  <div class="top">
    <div class="title">% jaarresultaat vs indices</div>
    <div class="meta" id="meta">Geen data geladen</div>
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
let __lastPayload = null;
let __resizeTimer = null;
function fmtPct(v){
  if(v===null || v===undefined || Number.isNaN(v)) return "-";
  return new Intl.NumberFormat("nl-NL", {minimumFractionDigits:1, maximumFractionDigits:1}).format(v) + "%";
}
function fmtDateShort(isoDate){
  if(!isoDate || typeof isoDate !== "string" || isoDate.length < 10) return "";
  return `${isoDate.slice(8,10)}-${isoDate.slice(5,7)}-${isoDate.slice(2,4)}`;
}
function yearOf(isoDate){ return String(isoDate || "").slice(0,4); }
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
function linePath(points, xScale, yScale){
  if(!points.length) return "";
  return points.map((p, idx)=>`${idx===0 ? "M":"L"}${xScale(p.date)},${yScale(p.y)}`).join(" ");
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
function buildLegend(series){
  const legend = document.getElementById("legend");
  legend.innerHTML = "";
  (series || []).forEach((item)=>{
    const el = document.createElement("div");
    el.className = "leg";
    el.innerHTML = `<span class="sw dash" style="border-top-color:${item.color}"></span><span>${item.label}</span>`;
    legend.appendChild(el);
  });
}
function render(payload){
  __lastPayload = payload;
  const series = Array.isArray(payload?.series) ? payload.series : [];
  const stats = payload?.stats || {};
  const lineWidth = Number(payload?.line_width || 1.6);
  const lineWidths = payload?.line_widths || {};
  const lineStyles = payload?.line_styles || {};
  buildLegend(series);
  document.getElementById("meta").textContent = series.length
    ? `${stats.start_date || "-"} t/m ${stats.end_date || "-"} | series=${stats.series || 0} | punten=${stats.points || 0}`
    : "Geen data geladen";
  const empty = document.getElementById("empty");
  const svg = document.getElementById("chart");
  const box = document.getElementById("chartBox");
  const tip = document.getElementById("tooltip");
  const width = Math.max(850, box.clientWidth || 850);
  const height = Math.max(480, box.clientHeight || 480);
  svg.setAttribute("width", String(width));
  svg.setAttribute("height", String(height));
  svg.innerHTML = "";
  if(!series.length){ empty.style.display = "flex"; return; }
  empty.style.display = "none";

  const dates = Array.from(new Set(series.flatMap((s)=>s.points.map((p)=>p.date)))).sort();
  const dateIndex = new Map();
  dates.forEach((d, idx)=>dateIndex.set(d, idx));
  const values = [0];
  series.forEach((s)=>s.points.forEach((p)=>values.push(Number(p.y))));
  const minRaw = Math.min(...values);
  const maxRaw = Math.max(...values);
  const step = niceStep(maxRaw - minRaw || 1);
  const yMin = floorToStep(minRaw, step);
  const yMax = ceilToStep(maxRaw, step);
  const plot = {l:42,r:76,t:14,b:52};
  const innerW = width - plot.l - plot.r;
  const innerH = height - plot.t - plot.b;
  const xScale = (date)=> plot.l + (dates.length <= 1 ? innerW/2 : (dateIndex.get(date)/(dates.length-1))*innerW);
  const yScale = (val)=> plot.t + innerH - ((val - yMin)/(yMax - yMin || 1)) * innerH;

  for(let yVal = yMin; yVal <= yMax + step/2; yVal += step){
    const y = yScale(yVal);
    const line = document.createElementNS("http://www.w3.org/2000/svg","line");
    line.setAttribute("x1", plot.l); line.setAttribute("x2", width-plot.r);
    line.setAttribute("y1", y); line.setAttribute("y2", y);
    line.setAttribute("stroke", yVal === 0 ? "#999" : "#dfdfdf");
    line.setAttribute("stroke-width", yVal === 0 ? "1.4" : "1");
    svg.appendChild(line);
    const txt = document.createElementNS("http://www.w3.org/2000/svg","text");
    txt.setAttribute("x", width-plot.r+8); txt.setAttribute("y", y+4);
    txt.setAttribute("font-size", "11"); txt.setAttribute("fill", "#555");
    txt.textContent = fmtPct(yVal);
    svg.appendChild(txt);
  }

  const stride = Math.max(1, Math.floor(dates.length / 18));
  dates.forEach((d, idx)=>{
    if(idx % stride !== 0 && idx !== dates.length-1) return;
    const x = xScale(d);
    const txt = document.createElementNS("http://www.w3.org/2000/svg","text");
    txt.setAttribute("x", x); txt.setAttribute("y", height-plot.b+18);
    txt.setAttribute("font-size", "11"); txt.setAttribute("fill", "#555");
    txt.setAttribute("text-anchor", "middle");
    txt.setAttribute("transform", `rotate(-45 ${x} ${height-plot.b+18})`);
    txt.textContent = fmtDateShort(d);
    svg.appendChild(txt);
  });

  series.forEach((item)=>{
    splitSeriesByYear(item.points || []).forEach((segment)=>{
      const path = document.createElementNS("http://www.w3.org/2000/svg","path");
      path.setAttribute("d", linePath(segment, xScale, yScale));
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", item.color || "#333");
      const width = Number(lineWidths[item.id] || lineWidth);
      path.setAttribute("stroke-width", String(width));
      const style = lineStyles[item.id] || "dashed";
      if(style === "dashed"){
        path.setAttribute("stroke-dasharray", "7 6");
      }
      svg.appendChild(path);
    });
  });

  const byDate = new Map();
  series.forEach((item)=>item.points.forEach((p)=>{
    if(!byDate.has(p.date)) byDate.set(p.date, []);
    byDate.get(p.date).push(`${item.label}: ${fmtPct(p.y)}`);
  }));
  dates.forEach((d)=>{
    const x = xScale(d);
    const hit = document.createElementNS("http://www.w3.org/2000/svg","line");
    hit.setAttribute("x1", x); hit.setAttribute("x2", x);
    hit.setAttribute("y1", plot.t); hit.setAttribute("y2", height-plot.b);
    hit.setAttribute("stroke", "transparent"); hit.setAttribute("stroke-width", "10");
    hit.addEventListener("mousemove", (ev)=>{
      tip.style.display = "block";
      tip.style.left = (ev.clientX + 12) + "px";
      tip.style.top = (ev.clientY + 12) + "px";
      tip.textContent = `${d} | ${(byDate.get(d) || []).join(" | ")}`;
    });
    hit.addEventListener("mouseleave", ()=> tip.style.display = "none");
    svg.appendChild(hit);
  });
}
window.renderYearResultVsIndicesChart = render;
window.addEventListener("resize", ()=>{
  if(!__lastPayload) return;
  window.clearTimeout(__resizeTimer);
  __resizeTimer = window.setTimeout(()=>render(__lastPayload), 80);
});
</script>
</body>
</html>
"""


class _YearResultVsIndicesWorker(QThread):
    payload_ready = Signal(dict)
    error_ready = Signal(str)

    def __init__(
        self,
        selected_indices: list[str],
        selected_portfolio: list[str],
        start_date: str,
        force_reload: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._selected_indices = selected_indices
        self._selected_portfolio = selected_portfolio
        self._start_date = start_date
        self._force_reload = force_reload

    def run(self) -> None:
        try:
            payload = build_year_result_vs_indices_payload(
                selected_indices=self._selected_indices,
                selected_portfolio=self._selected_portfolio,
                start_date=self._start_date,
                force_reload=self._force_reload,
            )
        except Exception as exc:
            self.error_ready.emit(f"{type(exc).__name__}: {exc}")
            return
        self.payload_ready.emit(payload)


class YearResultVsIndicesChartDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("% Jaarresultaat vs Indices")
        self.resize(1500, 900)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._settings = get_settings()
        self._worker = None
        self._pending_payload = None
        self._page_ready = False
        self._loading_lists = False
        self._refresh_requested = False
        self._refresh_force_requested = False
        self._scheduled_force_reload = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self._run_scheduled_refresh)

        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self._status = QLabel("Laden...")
        toolbar.addWidget(self._status)
        toolbar.addStretch(1)
        self._use_start_checkbox = QCheckBox("Startdatum", self)
        self._use_start_checkbox.setChecked(bool(self._start_date_setting()))
        self._use_start_checkbox.toggled.connect(self._on_use_start_toggled)
        toolbar.addWidget(self._use_start_checkbox)
        self._start_date_edit = QDateEdit(self)
        self._start_date_edit.setCalendarPopup(True)
        self._start_date_edit.setDisplayFormat("dd-MM-yyyy")
        self._start_date_edit.setMinimumDate(QDate(2000, 1, 1))
        self._start_date_edit.setMaximumDate(QDate(2099, 12, 31))
        self._start_date_edit.setDate(self._load_start_qdate())
        self._start_date_edit.setEnabled(self._use_start_checkbox.isChecked())
        self._start_date_edit.dateChanged.connect(self._on_start_date_changed)
        toolbar.addWidget(self._start_date_edit)
        self._clear_start_button = QPushButton("Geen start")
        self._clear_start_button.clicked.connect(self._clear_start_date)
        toolbar.addWidget(self._clear_start_button)
        self._refresh_button = QPushButton("Refresh")
        self._refresh_button.clicked.connect(lambda: self.refresh(force_reload=True))
        toolbar.addWidget(self._refresh_button)
        root.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal, self)
        root.addWidget(splitter, 1)
        side = QWidget(self)
        side_layout = QVBoxLayout(side)
        self._portfolio_list = QListWidget(self)
        side_layout.addWidget(
            self._create_selector_group(
                "PORTFOLIO",
                self._portfolio_list,
                self._select_all_portfolio,
                self._select_no_portfolio,
            )
        )
        self._indices_list = QListWidget(self)
        side_layout.addWidget(
            self._create_selector_group(
                "INDICES",
                self._indices_list,
                self._select_all_indices,
                self._select_no_indices,
            ),
            1,
        )
        side_layout.addWidget(QLabel("LIJNDIKTE"))
        self._line_width_table = QTableWidget(self)
        self._line_width_table.setColumnCount(3)
        self._line_width_table.setHorizontalHeaderLabels(["Lijn", "px", "Type"])
        self._line_width_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._line_width_table.setSelectionMode(QAbstractItemView.NoSelection)
        side_layout.addWidget(self._line_width_table, 1)
        splitter.addWidget(side)

        if QWebEngineView is None:
            fallback = QLabel("QWebEngineView niet beschikbaar.")
            fallback.setAlignment(Qt.AlignCenter)
            splitter.addWidget(fallback)
            self._web = None
        else:
            self._web = QWebEngineView(self)
            self._web.loadFinished.connect(self._on_load_finished)
            self._web.setHtml(_HTML)
            splitter.addWidget(self._web)
        splitter.setSizes([260, 1240])

        self._populate_portfolio_list()
        self._portfolio_list.itemSelectionChanged.connect(self._on_selection_changed)
        self._indices_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.refresh()

    def _load_start_qdate(self) -> QDate:
        raw = self._start_date_setting()
        if raw:
            try:
                year, month, day = [int(part) for part in raw.split("-")]
                return QDate(year, month, day)
            except Exception:
                pass
        return QDate(2021, 1, 1)

    def _current_start_date_text(self) -> str:
        if not self._use_start_checkbox.isChecked():
            return ""
        date_value = self._start_date_edit.date()
        return date_value.toString("yyyy-MM-dd")

    def _on_start_date_changed(self, _date: QDate) -> None:
        if getattr(self, "_loading_lists", False):
            return
        self._set_start_date_setting(self._current_start_date_text())
        self._schedule_refresh()

    def _on_use_start_toggled(self, checked: bool) -> None:
        self._start_date_edit.setEnabled(checked)
        self._set_start_date_setting(self._current_start_date_text())
        self._schedule_refresh()

    def _clear_start_date(self) -> None:
        self._use_start_checkbox.setChecked(False)

    def _create_selector_group(
        self,
        title: str,
        list_widget: QListWidget,
        select_all_slot,
        select_none_slot,
    ) -> QGroupBox:
        group = QGroupBox(title, self)
        group.setStyleSheet(
            """
            QGroupBox {
                font-weight: 700;
                border: 1px solid #d8c7aa;
                border-radius: 10px;
                margin-top: 8px;
                padding: 10px 8px 8px 8px;
                background: #fbf7ef;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }
            QGroupBox QPushButton {
                background: #e7dbc6;
                border: 1px solid #d1bea0;
                border-radius: 8px;
                padding: 6px 12px;
                font-weight: 700;
            }
            QGroupBox QListWidget {
                background: #ffffff;
                border: 1px solid #d8c7aa;
                border-radius: 6px;
                padding: 2px;
            }
            QGroupBox QListWidget::item {
                padding: 2px 4px;
            }
            QGroupBox QListWidget::item:selected {
                background: #c9c9c9;
                color: #202020;
            }
            """
        )
        layout = QVBoxLayout(group)
        buttons = QHBoxLayout()
        all_button = QPushButton("Alles", group)
        all_button.clicked.connect(select_all_slot)
        none_button = QPushButton("Niets", group)
        none_button.clicked.connect(select_none_slot)
        buttons.addWidget(all_button)
        buttons.addWidget(none_button)
        layout.addLayout(buttons)
        list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(list_widget, 1)
        return group

    def _selected_values(self, widget: QListWidget) -> list[str]:
        return [str(item.data(Qt.UserRole)) for item in widget.selectedItems()]

    def _set_all_selected(self, widget: QListWidget, selected: bool) -> None:
        self._loading_lists = True
        try:
            for idx in range(widget.count()):
                widget.item(idx).setSelected(selected)
        finally:
            self._loading_lists = False
        self._on_selection_changed()

    def _select_all_portfolio(self) -> None:
        self._set_all_selected(self._portfolio_list, True)

    def _select_no_portfolio(self) -> None:
        self._set_all_selected(self._portfolio_list, False)

    def _select_all_indices(self) -> None:
        self._set_all_selected(self._indices_list, True)

    def _select_no_indices(self) -> None:
        self._set_all_selected(self._indices_list, False)

    def _populate_portfolio_list(self) -> None:
        selected = set(self._settings.get_year_result_vs_indices_selected_portfolio())
        current_value = self._current_list_value(self._portfolio_list)
        had_focus = self._portfolio_list.hasFocus()
        self._loading_lists = True
        try:
            self._portfolio_list.clear()
            current_row = -1
            for value, label in PORTFOLIO_OPTIONS:
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, value)
                self._portfolio_list.addItem(item)
                item.setSelected(value in selected)
                if value == current_value:
                    current_row = self._portfolio_list.row(item)
            self._restore_current_row(self._portfolio_list, current_row, had_focus)
        finally:
            self._loading_lists = False

    def _populate_indices_list(self, options: list[str], selected: list[str]) -> None:
        current_selected = set(
            selected if selected is not None else self._settings.get_year_result_vs_indices_selected_indices()
        )
        current_value = self._current_list_value(self._indices_list)
        had_focus = self._indices_list.hasFocus()
        self._loading_lists = True
        try:
            self._indices_list.clear()
            current_row = -1
            for value in options or []:
                item = QListWidgetItem(value)
                item.setData(Qt.UserRole, value)
                self._indices_list.addItem(item)
                item.setSelected(value in current_selected)
                if value == current_value:
                    current_row = self._indices_list.row(item)
            self._restore_current_row(self._indices_list, current_row, had_focus)
        finally:
            self._loading_lists = False

    def _current_list_value(self, widget: QListWidget) -> str:
        item = widget.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "")

    def _restore_current_row(self, widget: QListWidget, current_row: int, had_focus: bool) -> None:
        if current_row < 0:
            selected_items = widget.selectedItems()
            if selected_items:
                current_row = widget.row(selected_items[0])
        if current_row >= 0:
            widget.setCurrentRow(current_row, QItemSelectionModel.NoUpdate)
        if had_focus:
            widget.setFocus(Qt.OtherFocusReason)

    def _populate_line_width_table(self, series: list[dict]) -> None:
        self._line_width_table.setUpdatesEnabled(False)
        self._line_width_table.blockSignals(True)
        try:
            self._line_width_table.clearContents()
            self._line_width_table.setRowCount(len(series or []))
            line_widths = self._settings.get_chart_line_widths_for_chart(CHART_ID)
            line_styles = self._settings.get_chart_line_styles_for_chart(CHART_ID)
            default_width = self._settings.get_chart_line_width_px()
            for row_idx, item in enumerate(series or []):
                series_id = str(item.get("id") or "")
                label = str(item.get("label") or series_id)
                label_item = QTableWidgetItem(label)
                label_item.setData(Qt.UserRole, series_id)
                self._line_width_table.setItem(row_idx, 0, label_item)
                spin = QDoubleSpinBox(self)
                spin.setRange(0.5, 8.0)
                spin.setDecimals(1)
                spin.setSingleStep(0.1)
                spin.setSuffix(" px")
                spin.setValue(float(line_widths.get(series_id, default_width)))
                spin.valueChanged.connect(
                    lambda value, sid=series_id: self._on_line_width_changed(sid, value)
                )
                self._line_width_table.setCellWidget(row_idx, 1, spin)
                combo = QComboBox(self)
                combo.addItem("Gestreept", "dashed")
                combo.addItem("Doorlopend", "solid")
                style = line_styles.get(series_id, "dashed")
                combo.setCurrentIndex(max(0, combo.findData(style)))
                combo.currentIndexChanged.connect(
                    lambda _idx, sid=series_id, widget=combo: self._on_line_style_changed(
                        sid,
                        str(widget.currentData() or "dashed"),
                    )
                )
                self._line_width_table.setCellWidget(row_idx, 2, combo)
        finally:
            self._line_width_table.blockSignals(False)
            self._line_width_table.setUpdatesEnabled(True)
        self._line_width_table.resizeColumnsToContents()

    def _on_line_width_changed(self, series_id: str, value: float) -> None:
        self._settings.set_chart_line_width_for_series(CHART_ID, series_id, value)
        if self._pending_payload is not None:
            self._render_payload(self._pending_payload)

    def _on_line_style_changed(self, series_id: str, style: str) -> None:
        self._settings.set_chart_line_style_for_series(CHART_ID, series_id, style)
        if self._pending_payload is not None:
            self._render_payload(self._pending_payload)

    def _on_selection_changed(self) -> None:
        if self._loading_lists:
            return
        self._settings.set_year_result_vs_indices_selected_portfolio(
            self._selected_values(self._portfolio_list)
        )
        self._settings.set_year_result_vs_indices_selected_indices(
            self._selected_values(self._indices_list)
        )
        self._schedule_refresh()

    def refresh(self, force_reload: bool = False) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._refresh_requested = True
            self._refresh_force_requested = self._refresh_force_requested or force_reload
            return
        self._refresh_requested = False
        self._refresh_force_requested = False
        self._status.setText("Chart laden...")
        self._refresh_button.setEnabled(False)
        self._worker = _YearResultVsIndicesWorker(
            selected_indices=self._settings.get_year_result_vs_indices_selected_indices(),
            selected_portfolio=self._settings.get_year_result_vs_indices_selected_portfolio(),
            start_date=self._start_date_setting(),
            force_reload=force_reload,
            parent=self,
        )
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
        self._populate_indices_list(
            payload.get("index_options") or [],
            self._settings.get_year_result_vs_indices_selected_indices(),
        )
        self._populate_line_width_table(payload.get("series") or [])
        stats = payload.get("stats") or {}
        self._status.setText(
            f"{stats.get('start_date') or '-'} t/m {stats.get('end_date') or '-'} | "
            f"series={stats.get('series') or 0} | punten={stats.get('points') or 0}"
        )
        if self._page_ready:
            self._render_payload(payload)

    def _on_payload_error(self, message: str) -> None:
        self._status.setText(f"Fout bij laden: {message}")

    def _on_worker_finished(self) -> None:
        self._refresh_button.setEnabled(True)
        self._worker = None
        if self._refresh_requested:
            self._schedule_refresh(force_reload=self._refresh_force_requested)

    def _render_payload(self, payload: dict) -> None:
        if self._web is None:
            return
        payload = dict(payload or {})
        payload["line_width"] = self._settings.get_chart_line_width_px()
        payload["line_widths"] = self._settings.get_chart_line_widths_for_chart(CHART_ID)
        payload["line_styles"] = self._settings.get_chart_line_styles_for_chart(CHART_ID)
        self._web.page().runJavaScript(
            f"window.renderYearResultVsIndicesChart({json.dumps(payload)});"
        )

    def _schedule_refresh(self, force_reload: bool = False) -> None:
        self._scheduled_force_reload = self._scheduled_force_reload or force_reload
        self._refresh_timer.start()

    def _run_scheduled_refresh(self) -> None:
        force_reload = self._scheduled_force_reload
        self._scheduled_force_reload = False
        self.refresh(force_reload=force_reload)

    def _start_date_setting(self) -> str:
        return (
            self._settings.get_chart_start_date(CHART_ID)
            or self._settings.get_year_result_vs_indices_start_date()
        )

    def _set_start_date_setting(self, value: str) -> None:
        self._settings.set_chart_start_date(CHART_ID, value)
        self._settings.set_year_result_vs_indices_start_date(value)


_YEAR_RESULT_VS_INDICES_DIALOG_INSTANCE: YearResultVsIndicesChartDialog | None = None


def open_year_result_vs_indices_chart_dialog(parent=None) -> None:
    global _YEAR_RESULT_VS_INDICES_DIALOG_INSTANCE
    if _YEAR_RESULT_VS_INDICES_DIALOG_INSTANCE is None:
        _YEAR_RESULT_VS_INDICES_DIALOG_INSTANCE = YearResultVsIndicesChartDialog(parent)
        _YEAR_RESULT_VS_INDICES_DIALOG_INSTANCE.destroyed.connect(
            lambda *_args: _clear_year_result_vs_indices_dialog_instance()
        )
    else:
        _YEAR_RESULT_VS_INDICES_DIALOG_INSTANCE.refresh()
    _YEAR_RESULT_VS_INDICES_DIALOG_INSTANCE.show()
    _YEAR_RESULT_VS_INDICES_DIALOG_INSTANCE.raise_()
    _YEAR_RESULT_VS_INDICES_DIALOG_INSTANCE.activateWindow()


def _clear_year_result_vs_indices_dialog_instance() -> None:
    global _YEAR_RESULT_VS_INDICES_DIALOG_INSTANCE
    _YEAR_RESULT_VS_INDICES_DIALOG_INSTANCE = None

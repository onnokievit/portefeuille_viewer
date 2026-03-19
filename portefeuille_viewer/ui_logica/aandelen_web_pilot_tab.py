from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals
from portefeuille_viewer.ui.filter_popup import ColumnFilterPopup

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - optional runtime dependency
    QWebChannel = None
    QWebEngineView = None


class AandelenWebPilotTab(QWidget):
    """
    Minimal WebEngine pilot tab.

    - Uses a lightweight HTML frame/card layout.
    - Exposes a JS endpoint to apply tiny value updates.
    - Keeps existing PySide tabs untouched (feature-flag style integration).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._js_ready = False
        self._pending_js_calls: list[tuple[str, object]] = []
        self.selected_brokers: set[str] | None = None
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.btn_select_brokers = QPushButton("Selecteer brokers (ALL)")
        self.btn_select_brokers.clicked.connect(self._open_broker_popup)
        self.btn_clear_brokers = QPushButton("Wis brokers")
        self.btn_clear_brokers.clicked.connect(self._clear_backend_broker_filter)
        toolbar.addWidget(self.btn_select_brokers)
        toolbar.addWidget(self.btn_clear_brokers)
        toolbar.addStretch(1)
        self.btn_export = QPushButton("Export snapshot")
        self.btn_export.clicked.connect(self._export_snapshot)
        toolbar.addWidget(self.btn_export)
        layout.addLayout(toolbar)
        if QWebEngineView is None:
            layout.addWidget(QLabel("QtWebEngine niet beschikbaar in deze runtime."))
            return
        self.web = QWebEngineView(self)
        layout.addWidget(self.web)
        if QWebChannel is not None:
            self.channel = QWebChannel(self.web.page())
            self.web.page().setWebChannel(self.channel)
        self.web.loadFinished.connect(self._on_web_loaded)
        self.web.setHtml(self._html_template())
        signals.snapshotUpdated.connect(self._on_snapshot_updated)

    def push_value(self, frame_id: str, value_text: str) -> None:
        if not hasattr(self, "web"):
            return
        payload = json.dumps({"id": frame_id, "value": value_text})
        self.web.page().runJavaScript(f"window.applyDelta({payload});")

    def _on_web_loaded(self, ok: bool):
        self._js_ready = bool(ok)
        if not self._js_ready:
            return
        for func_name, payload in self._pending_js_calls:
            self._run_js(func_name, payload)
        self._pending_js_calls.clear()
        self._publish_full_snapshot()
        self._publish_meta()

    def _on_snapshot_updated(self, snapshot_key: str):
        if snapshot_key == "snapshot_aandelen_projection_v2":
            self._publish_full_snapshot()
        elif snapshot_key == "snapshot_aandelen_projection_v2_patch":
            self._publish_patch()
        elif snapshot_key == "snapshot_aandelen_projection_v2_meta":
            self._publish_meta()

    def _publish_full_snapshot(self):
        df = getattr(SNAPSHOT_STORE, "snapshot_aandelen_projection_v2", None)
        if df is None:
            return
        try:
            rows = df.to_dicts() if hasattr(df, "to_dicts") else []
        except Exception:
            rows = []
        self._call_js("renderSnapshot", {"rows": rows})

    def _publish_patch(self):
        patch = getattr(SNAPSHOT_STORE, "snapshot_aandelen_projection_v2_patch", None)
        if not patch:
            return
        self._call_js("applyPatch", {"changes": list(patch)})

    def _publish_meta(self):
        meta = getattr(SNAPSHOT_STORE, "snapshot_aandelen_projection_v2_meta", None)
        if not isinstance(meta, dict):
            return
        selected = meta.get("selected_brokers")
        if isinstance(selected, list):
            normalized = {str(x).strip().lower() for x in selected if str(x).strip()}
            self.selected_brokers = normalized if normalized else None
            self._update_broker_button_text()
        self._call_js("renderMeta", meta)

    def _call_js(self, func_name: str, payload: object):
        if not hasattr(self, "web"):
            return
        if not self._js_ready:
            self._pending_js_calls.append((func_name, payload))
            return
        self._run_js(func_name, payload)

    def _run_js(self, func_name: str, payload: object):
        js_payload = json.dumps(payload, ensure_ascii=False, default=self._json_default)
        self.web.page().runJavaScript(f"window.{func_name}({js_payload});")

    def _open_broker_popup(self):
        brokers = self._available_brokers()
        if not brokers:
            QMessageBox.information(self, "Brokers", "Geen brokerwaarden beschikbaar.")
            return
        pre_selected = (
            set(self.selected_brokers)
            if self.selected_brokers
            else set(str(b).lower() for b in brokers)
        )
        popup = ColumnFilterPopup("Selecteer brokers", brokers, pre_selected, self)
        popup.acceptedSelection.connect(self._set_broker_selection)
        popup.exec()

    def _available_brokers(self) -> list[str]:
        values = set()
        try:
            for broker in get_settings().get_brokers() or []:
                s = str(broker).strip().lower()
                if s:
                    values.add(s)
        except Exception:
            pass

        df = getattr(SNAPSHOT_STORE, "aggregator_snapshot_aandelen_live", None)
        if df is not None and not (hasattr(df, "is_empty") and df.is_empty()) and "broker" in getattr(df, "columns", []):
            for broker in df["broker"].to_list():
                if broker is None:
                    continue
                s = str(broker).strip().lower()
                if s:
                    values.add(s)
        return sorted(values)

    def _set_broker_selection(self, selected: set):
        normalized = {str(x).strip().lower() for x in selected if str(x).strip()}
        self.selected_brokers = normalized if normalized else None
        self._update_broker_button_text()
        signals.queued_emit_aandelenProjectionFilterChanged(
            {"selected_brokers": sorted(self.selected_brokers) if self.selected_brokers else []}
        )

    def _clear_backend_broker_filter(self):
        self.selected_brokers = None
        self._update_broker_button_text()
        signals.queued_emit_aandelenProjectionFilterChanged({"selected_brokers": []})

    def _update_broker_button_text(self):
        if not self.selected_brokers:
            self.btn_select_brokers.setText("Selecteer brokers (ALL)")
            return
        self.btn_select_brokers.setText(f"Selecteer brokers ({len(self.selected_brokers)})")

    def _export_snapshot(self):
        df = getattr(SNAPSHOT_STORE, "snapshot_aandelen_projection_v2", None)
        if df is None or (hasattr(df, "is_empty") and df.is_empty()):
            QMessageBox.information(self, "Export", "Geen projection snapshot beschikbaar.")
            return
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "Export Aandelen Projection Snapshot",
            "aandelen_projection_snapshot.xlsx",
            "Excel Files (*.xlsx);;CSV Files (*.csv)",
        )
        if not fname:
            return
        try:
            pdf = df.to_pandas()
            if fname.lower().endswith(".csv"):
                pdf.to_csv(fname, index=False)
            else:
                if not fname.lower().endswith(".xlsx"):
                    fname = f"{fname}.xlsx"
                pdf.to_excel(fname, index=False)
            QMessageBox.information(self, "Export", f"Export voltooid:\n{fname}")
        except Exception as exc:
            QMessageBox.warning(self, "Export mislukt", str(exc))

    @staticmethod
    def _json_default(value):
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    def _html_template(self) -> str:
        return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <style>
      body { font-family: Segoe UI, Arial, sans-serif; margin: 12px; background:#f5f6f8; }
      .meta { margin: 0 0 10px 0; color:#44536b; font-size:12px; }
      .filters {
        display:flex;
        gap:8px;
        margin:0 0 8px 0;
        flex-wrap:wrap;
      }
      .filters input {
        font-size:12px;
        padding:4px 6px;
        border:1px solid #c7d1de;
        border-radius:6px;
        min-width:120px;
      }
      .filters button {
        font-size:12px;
        padding:4px 8px;
        border:1px solid #b8c3d3;
        background:#f4f7fb;
        border-radius:6px;
        cursor:pointer;
      }
      .table-wrap { border:1px solid #d8dde6; border-radius:8px; overflow:auto; background:#fff; max-height:78vh; }
      table { width:100%; border-collapse:collapse; font-size:12px; table-layout: fixed; }
      col { width: 110px; }
      thead th {
        position: sticky; top: 0; z-index: 2;
        background:#eef2f7; color:#223247; font-weight:700;
        border-bottom:1px solid #d8dde6;
        padding:6px 8px; text-align:left; cursor:pointer; white-space:nowrap;
        user-select: none;
      }
      thead th:first-child {
        left: 0;
        z-index: 4;
      }
      tbody td {
        border-top:1px solid #eef1f5;
        padding:4px 8px; white-space:nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      tbody td:first-child {
        position: sticky;
        left: 0;
        z-index: 1;
        background: #ffffff;
        box-shadow: 1px 0 0 #e4e9f0;
      }
      tbody tr:nth-child(even) td:first-child {
        background:#fafbfd;
      }
      tbody tr:nth-child(even) { background:#fafbfd; }
      td.num { text-align:right; font-variant-numeric: tabular-nums; }
      td.total-pos { background:#c6f7c6; }
      td.total-neg { background:#f7c6c6; }
      td.total-zero { background:#ffffff; }
      tfoot td {
        position: sticky;
        bottom: 0;
        z-index: 3;
        background:#e6ebf2;
        border-top:1px solid #c8d2df;
        padding:5px 8px;
        font-weight:700;
      }
      tfoot td.num { text-align:right; }
      th .resize-handle {
        position:absolute;
        top:0;
        right:0;
        width:7px;
        height:100%;
        cursor:col-resize;
      }
      th.sorted-asc::after { content: " \\2191"; }
      th.sorted-desc::after { content: " \\2193"; }
    </style>
  </head>
  <body>
    <div class="meta" id="meta">Projection v- | rows: 0 | changes: 0</div>
    <div class="filters">
      <input id="f_global" placeholder="Zoek alle kolommen..." />
      <input id="f_asset" placeholder="Filter asset_rollup" />
      <input id="f_regio" placeholder="Filter regio" />
      <input id="f_sector" placeholder="Filter sector" />
      <input id="f_status" placeholder="Filter status" />
      <button id="btn_clear_filters">Wis filters</button>
    </div>
    <div class="table-wrap">
      <table id="tbl">
        <colgroup id="colgroup"></colgroup>
        <thead><tr id="thead-row"></tr></thead>
        <tbody id="tbody"></tbody>
        <tfoot><tr id="tfoot-row"></tr></tfoot>
      </table>
    </div>
    <script>
      const PREFERRED_ORDER = [
        "asset_rollup",
        "koers_prev",
        "koers",
        "pct_change",
        "eq_aantal_bezit",
        "open_sp_aantal",
        "eq_total_result",
        "clos_opt_transactie_euro_totaal",
        "clos_sp_transactie_euro_totaal",
        "open_opt_total_result",
        "open_sp_result",
        "div_en_bel",
        "totaal_ex_fee",
        "totaal_inc_fee",
        "net_change",
        "totaal_fee",
        "regio",
        "sector",
        "value_grow",
        "status",
        "portfolio_total_waarde_lineair_pct",
        "portfolio_total_waarde_delta_pct",
        "optie_tijdswaarde_signed_eur"
      ];
      const WIDTH_KEY = "pv_aandelen_web_colwidths_v1";
      const state = {
        cols: [],
        rows: new Map(),
        sortCol: "asset_rollup",
        sortDir: "asc",
        colWidths: {},
        hasSnapshot: false,
        filters: {
          global: "",
          asset_rollup: "",
          regio: "",
          sector: "",
          status: ""
        }
      };

      function fmt(v) {
        if (v === null || v === undefined) return "";
        if (typeof v === "number") return Number.isFinite(v) ? v.toFixed(2) : "";
        return String(v);
      }

      function isNum(v) {
        return typeof v === "number" && Number.isFinite(v);
      }

      function compareRows(a, b, col, dir) {
        const av = a[col];
        const bv = b[col];
        let c = 0;
        if (isNum(av) && isNum(bv)) c = av - bv;
        else c = String(av ?? "").localeCompare(String(bv ?? ""));
        return dir === "asc" ? c : -c;
      }

      function orderedCols(cols) {
        const left = PREFERRED_ORDER.filter(c => cols.includes(c));
        const rest = cols.filter(c => !left.includes(c));
        return left.concat(rest);
      }

      function loadColWidths() {
        try {
          const raw = localStorage.getItem(WIDTH_KEY);
          if (!raw) return {};
          const parsed = JSON.parse(raw);
          return parsed && typeof parsed === "object" ? parsed : {};
        } catch (_) {
          return {};
        }
      }

      function saveColWidths() {
        try {
          localStorage.setItem(WIDTH_KEY, JSON.stringify(state.colWidths || {}));
        } catch (_) {}
      }

      function defaultColWidth(col) {
        if (col === "asset_rollup") return 180;
        if (col === "sector" || col === "status") return 130;
        if (col === "regio" || col === "value_grow") return 90;
        return 110;
      }

      function colWidth(col) {
        const w = Number(state.colWidths[col]);
        if (Number.isFinite(w) && w >= 70) return w;
        return defaultColWidth(col);
      }

      function applyColWidths() {
        const cg = document.getElementById("colgroup");
        if (!cg) return;
        cg.innerHTML = "";
        for (const col of state.cols) {
          const c = document.createElement("col");
          c.style.width = `${colWidth(col)}px`;
          cg.appendChild(c);
        }
      }

      function pctBgStyle(v) {
        if (!isNum(v)) return "";
        const min = -0.02, mid = 0.0, max = 0.02;
        const cmin = [255, 102, 102];
        const cmid = [255, 255, 255];
        const cmax = [153, 255, 153];
        let r=255,g=255,b=255;
        if (v <= min) [r,g,b] = cmin;
        else if (v >= max) [r,g,b] = cmax;
        else if (v < mid) {
          const t = (v - min) / (mid - min);
          r = Math.round(cmin[0] + t * (cmid[0] - cmin[0]));
          g = Math.round(cmin[1] + t * (cmid[1] - cmin[1]));
          b = Math.round(cmin[2] + t * (cmid[2] - cmin[2]));
        } else {
          const t = (v - mid) / (max - mid);
          r = Math.round(cmid[0] + t * (cmax[0] - cmid[0]));
          g = Math.round(cmid[1] + t * (cmax[1] - cmid[1]));
          b = Math.round(cmid[2] + t * (cmax[2] - cmid[2]));
        }
        return `rgb(${r}, ${g}, ${b})`;
      }

      function applyCellStyle(td, col, v) {
        td.classList.remove("total-pos", "total-neg", "total-zero");
        td.style.backgroundColor = "";
        if (col === "pct_change" && isNum(v)) {
          td.style.backgroundColor = pctBgStyle(v);
          return;
        }
        const totalCols = ["totaal_ex_fee", "totaal_inc_fee", "net_change", "totaal_fee"];
        if (totalCols.includes(col) && isNum(v)) {
          if (v > 0) td.classList.add("total-pos");
          else if (v < 0) td.classList.add("total-neg");
          else td.classList.add("total-zero");
        }
      }

      function renderHeader() {
        const tr = document.getElementById("thead-row");
        tr.innerHTML = "";
        state.cols.forEach((col, idx) => {
          const th = document.createElement("th");
          th.style.position = "sticky";
          th.style.width = `${colWidth(col)}px`;
          th.textContent = col;
          if (col === state.sortCol) th.className = state.sortDir === "asc" ? "sorted-asc" : "sorted-desc";
          th.onclick = () => {
            if (state.sortCol === col) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
            else { state.sortCol = col; state.sortDir = "asc"; }
            renderHeader();
            renderBody();
          };
          const handle = document.createElement("div");
          handle.className = "resize-handle";
          handle.onmousedown = (ev) => startResize(ev, col, idx);
          th.appendChild(handle);
          tr.appendChild(th);
        });
        applyColWidths();
      }

      function rowId(v) {
        return encodeURIComponent(String(v ?? ""));
      }

      function startResize(ev, col, idx) {
        ev.preventDefault();
        ev.stopPropagation();
        const startX = ev.clientX;
        const startW = colWidth(col);
        const onMove = (mv) => {
          const delta = mv.clientX - startX;
          const w = Math.max(70, startW + delta);
          state.colWidths[col] = w;
          const cg = document.getElementById("colgroup");
          if (cg && cg.children[idx]) cg.children[idx].style.width = `${w}px`;
          const th = document.getElementById("thead-row")?.children?.[idx];
          if (th) th.style.width = `${w}px`;
        };
        const onUp = () => {
          saveColWidths();
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      }

      function renderBody() {
        const body = document.getElementById("tbody");
        body.innerHTML = "";
        const rows = visibleRows();
        rows.sort((a, b) => compareRows(a, b, state.sortCol, state.sortDir));
        for (const row of rows) {
          const tr = document.createElement("tr");
          tr.id = "r_" + rowId(row.asset_rollup);
          for (const col of state.cols) {
            const td = document.createElement("td");
            td.id = "c_" + rowId(row.asset_rollup) + "_" + col;
            const v = row[col];
            td.textContent = fmt(v);
            if (isNum(v)) td.classList.add("num");
            applyCellStyle(td, col, v);
            tr.appendChild(td);
          }
          body.appendChild(tr);
        }
        renderFooter(rows);
      }

      function contains(hay, needle) {
        if (!needle) return true;
        return String(hay ?? "").toLowerCase().includes(String(needle).toLowerCase());
      }

      function visibleRows() {
        const rows = Array.from(state.rows.values());
        return rows.filter((r) => {
          if (!contains(r.asset_rollup, state.filters.asset_rollup)) return false;
          if (!contains(r.regio, state.filters.regio)) return false;
          if (!contains(r.sector, state.filters.sector)) return false;
          if (!contains(r.status, state.filters.status)) return false;
          if (state.filters.global) {
            const needle = state.filters.global.toLowerCase();
            const hit = state.cols.some((c) => String(r[c] ?? "").toLowerCase().includes(needle));
            if (!hit) return false;
          }
          return true;
        });
      }

      function renderFooter(rows) {
        const tr = document.getElementById("tfoot-row");
        tr.innerHTML = "";
        for (const col of state.cols) {
          const td = document.createElement("td");
          if (col === "asset_rollup") {
            td.textContent = `TOTAAL (${rows.length})`;
          } else {
            let sum = 0;
            let hasNum = false;
            for (const r of rows) {
              const v = r[col];
              if (isNum(v)) {
                sum += v;
                hasNum = true;
              }
            }
            td.textContent = hasNum ? fmt(sum) : "";
            if (hasNum) td.classList.add("num");
          }
          tr.appendChild(td);
        }
      }

      function updateQualityBadge() {
        const rows = Array.from(state.rows.values());
        let koersNull = 0;
        let koersPrevNull = 0;
        for (const r of rows) {
          const k = r.koers;
          const kp = r.koers_prev;
          const kEmpty = k === null || k === undefined || (typeof k === "number" && !Number.isFinite(k));
          const kpEmpty = kp === null || kp === undefined || (typeof kp === "number" && !Number.isFinite(kp));
          if (kEmpty) koersNull += 1;
          if (kpEmpty) koersPrevNull += 1;
        }
        const el = document.getElementById("meta");
        if (!el) return;
        const base = el.dataset.baseText || el.textContent || "";
        el.textContent = `${base} | dq koers_null: ${koersNull} | koers_prev_null: ${koersPrevNull}`;
      }

      function bindFilters() {
        const map = [
          ["f_global", "global"],
          ["f_asset", "asset_rollup"],
          ["f_regio", "regio"],
          ["f_sector", "sector"],
          ["f_status", "status"]
        ];
        for (const [id, key] of map) {
          const el = document.getElementById(id);
          if (!el) continue;
          el.addEventListener("input", () => {
            state.filters[key] = el.value || "";
            renderBody();
          });
        }
        const clear = document.getElementById("btn_clear_filters");
        if (clear) {
          clear.addEventListener("click", () => {
            for (const [id, key] of map) {
              const el = document.getElementById(id);
              if (el) el.value = "";
              state.filters[key] = "";
            }
            renderBody();
          });
        }
      }

      window.renderMeta = function(meta) {
        const el = document.getElementById("meta");
        if (!el || !meta) return;
        const v = meta.version ?? "-";
        const r = meta.rows ?? 0;
        const c = meta.changes ?? 0;
        const u = meta.updated_at ?? "-";
        const reason = meta.reason ?? "-";
        const d = meta.diag || {};
        const dk = d.koers_null ?? 0;
        const dkp = d.koers_prev_null ?? 0;
        const dkRel = d.koers_null_relevant ?? dk;
        const dkExp = d.koers_null_expected ?? 0;
        const dkpRel = d.koers_prev_null_relevant ?? dkp;
        const dkpExp = d.koers_prev_null_expected ?? 0;
        const dr = d.fallback_row_repairs ?? 0;
        const m = meta.metrics || {};
        const ml = m.last || {};
        const ms = m.summary || {};
        const mRec = Number(ml.recompute_ms ?? 0).toFixed(1);
        const mPub = Number(ml.publish_ms ?? 0).toFixed(1);
        const mTot = Number(ml.total_ms ?? 0).toFixed(1);
        const mQ = Number(ml.queue_wait_ms ?? 0).toFixed(1);
        const mInflight = ml.inflight ? 1 : 0;
        const mP95 = Number(ms.total_ms_p95 ?? 0).toFixed(1);
        const b = Array.isArray(meta.selected_brokers) && meta.selected_brokers.length
          ? meta.selected_brokers.join(",")
          : "ALL";
        const txt = `Projection v${v} | rows: ${r} | changes: ${c} | updated: ${u} | reason: ${reason} | brokers: ${b} | perf q:${mQ}ms rec:${mRec}ms pub:${mPub}ms tot:${mTot}ms p95:${mP95}ms inflight:${mInflight} | diag k_null:${dkRel} (exp:${dkExp}) kp_null:${dkpRel} (exp:${dkpExp}) repaired:${dr}`;
        el.dataset.baseText = txt;
        el.textContent = txt;
        updateQualityBadge();
      };

      window.renderSnapshot = function(payload) {
        const rows = (payload && payload.rows) ? payload.rows : [];
        state.rows.clear();
        if (rows.length === 0) {
          state.cols = [];
          state.hasSnapshot = false;
          renderHeader();
          renderBody();
          return;
        }
        const colSet = new Set();
        for (const row of rows) {
          if (!row || !row.asset_rollup) continue;
          state.rows.set(String(row.asset_rollup), row);
          Object.keys(row).forEach(k => colSet.add(k));
        }
        state.cols = orderedCols(Array.from(colSet));
        state.colWidths = loadColWidths();
        if (!state.cols.includes(state.sortCol)) state.sortCol = "asset_rollup";
        state.hasSnapshot = true;
        renderHeader();
        renderBody();
        updateQualityBadge();
      };

      function patchCell(rowIdValue, field, value) {
        const rid = String(rowIdValue);
        if (!state.rows.has(rid)) return;
        const row = state.rows.get(rid);
        row[field] = value;
        if (!state.cols.includes(field)) {
          state.cols.push(field);
          state.cols = orderedCols(state.cols);
          renderHeader();
          renderBody();
          return;
        }
        const td = document.getElementById("c_" + rowId(rid) + "_" + field);
        if (td) {
          td.textContent = fmt(value);
          if (isNum(value)) td.classList.add("num");
          else td.classList.remove("num");
          applyCellStyle(td, field, value);
          if (state.sortCol === field) renderBody();
          updateQualityBadge();
        } else {
          renderBody();
          updateQualityBadge();
        }
      };

      window.applyPatch = function(payload) {
        if (!state.hasSnapshot) return;
        const changes = (payload && payload.changes) ? payload.changes : [];
        for (const ch of changes) {
          if (!ch || !ch.row_id) continue;
          if (ch.field === "__deleted__") {
            state.rows.delete(String(ch.row_id));
            const tr = document.getElementById("r_" + rowId(ch.row_id));
            if (tr && tr.parentNode) tr.parentNode.removeChild(tr);
            updateQualityBadge();
            continue;
          }
          patchCell(ch.row_id, ch.field, ch.value);
        }
      };

      window.applyDelta = function(delta) {
        if (!delta || !delta.id) return;
        const el = document.getElementById(delta.id);
        if (el) el.textContent = String(delta.value ?? "");
      };

      bindFilters();
    </script>
  </body>
</html>
"""

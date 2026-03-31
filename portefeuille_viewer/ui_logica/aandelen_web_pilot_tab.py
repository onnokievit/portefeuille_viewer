from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal

from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals
from portefeuille_viewer.services.scenario_aandelen_overlay import build_aandelen_scenario_overlay_df
from portefeuille_viewer.ui.filter_popup import ColumnFilterPopup

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - optional runtime dependency
    QWebChannel = None
    QWebEngineView = None


AANDELEN_WEB_DEBUG = os.getenv("AANDELEN_WEB_DEBUG", "0").strip() == "1"


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
        self._is_active = False
        self._pending_js_calls: list[tuple[str, object]] = []
        self._needs_snapshot = False
        self._needs_patch = False
        self._needs_meta = False
        self._active_render_ms = max(100, int(os.getenv("UI_WEB_ACTIVE_RENDER_MS", "1000")))
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(self._active_render_ms)
        self._render_timer.timeout.connect(self._flush_scheduled_render)
        self.selected_brokers: set[str] | None = None
        layout = QVBoxLayout(self)
        if QWebEngineView is None:
            layout.addWidget(QLabel("QtWebEngine niet beschikbaar in deze runtime."))
            return
        self.web = QWebEngineView(self)
        layout.addWidget(self.web)
        if QWebChannel is not None:
            self.channel = QWebChannel(self.web.page())
            self.bridge = _AandelenWebBridge(self)
            self.channel.registerObject("aandelenBridge", self.bridge)
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
        self._publish_saved_column_widths()
        self._publish_full_snapshot()
        self._publish_meta()
        self._needs_snapshot = False
        self._needs_patch = False
        self._needs_meta = False

    def _on_snapshot_updated(self, snapshot_key: str):
        if AANDELEN_WEB_DEBUG:
            print(f"[aandelen-web-debug] snapshotUpdated key={snapshot_key} active={self._is_active} js_ready={self._js_ready} needs_snapshot={self._needs_snapshot} needs_patch={self._needs_patch} needs_meta={self._needs_meta}")
        use_scenario = bool(getattr(SNAPSHOT_STORE, "runtime_test_orders_enabled", False))
        if snapshot_key in {"snapshot_aandelen_projection_v2", "snapshot_aandelen_projection_v2_scenario"}:
            self._needs_snapshot = True
            self._needs_patch = False
            self._schedule_render()
        elif snapshot_key == "snapshot_aandelen_projection_v2_patch":
            if use_scenario:
                self._needs_snapshot = True
                self._needs_patch = False
            else:
                self._needs_patch = True
            self._schedule_render()
        elif snapshot_key == "snapshot_aandelen_projection_v2_meta":
            self._needs_meta = True
            self._schedule_render()

    def set_active(self, active: bool):
        self._is_active = bool(active)
        if AANDELEN_WEB_DEBUG:
            print(f"[aandelen-web-debug] set_active active={self._is_active} js_ready={self._js_ready} current_needs_snapshot={self._needs_snapshot} current_needs_patch={self._needs_patch} current_needs_meta={self._needs_meta}")
        if not self._is_active:
            self._render_timer.stop()
            return
        if not self._js_ready:
            return
        self._needs_snapshot = True
        self._needs_patch = False
        self._needs_meta = True
        self._render_timer.stop()
        self._flush_scheduled_render()

    def _schedule_render(self):
        if not self._is_active or not self._js_ready:
            return
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _flush_scheduled_render(self):
        if AANDELEN_WEB_DEBUG:
            print(f"[aandelen-web-debug] flush active={self._is_active} js_ready={self._js_ready} snapshot={self._needs_snapshot} patch={self._needs_patch} meta={self._needs_meta}")
        if not self._is_active or not self._js_ready:
            return
        if self._needs_snapshot:
            self._publish_full_snapshot()
            self._needs_snapshot = False
            self._needs_patch = False
        elif self._needs_patch:
            self._publish_patch()
            self._needs_patch = False
        if self._needs_meta:
            self._publish_meta()
            self._needs_meta = False

    def _publish_full_snapshot(self):
        df = self._current_snapshot_df()
        if df is None:
            return
        if AANDELEN_WEB_DEBUG:
            rows = int(df.height) if hasattr(df, "height") else -1
            print(f"[aandelen-web-debug] publish_full_snapshot rows={rows}")
        try:
            rows = df.to_dicts() if hasattr(df, "to_dicts") else []
        except Exception:
            rows = []
        self._call_js("renderSnapshot", {"rows": rows})
        self._debug_probe_js("full")

    def _publish_patch(self):
        patch = getattr(SNAPSHOT_STORE, "snapshot_aandelen_projection_v2_patch", None)
        if not patch:
            return
        if AANDELEN_WEB_DEBUG:
            row_ids = sorted({str(item.get("row_id") or "").strip() for item in list(patch) if str(item.get("row_id") or "").strip()})[:10]
            print(f"[aandelen-web-debug] publish_patch size={len(list(patch))} row_ids={row_ids}")
        self._call_js("applyPatch", {"changes": list(patch)})
        self._debug_probe_js("patch")

    def _publish_meta(self):
        meta = getattr(SNAPSHOT_STORE, "snapshot_aandelen_projection_v2_meta", None)
        if not isinstance(meta, dict):
            return
        selected = meta.get("selected_brokers")
        if isinstance(selected, list):
            normalized = {str(x).strip().lower() for x in selected if str(x).strip()}
            self.selected_brokers = normalized if normalized else None
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
        if AANDELEN_WEB_DEBUG and func_name in {"renderSnapshot", "applyPatch", "renderMeta"}:
            script = f"""
(() => {{
  try {{
    window.{func_name}({js_payload});
    const tbody = document.getElementById("tbody");
    return JSON.stringify({{
      ok: true,
      func: "{func_name}",
      rows: tbody ? tbody.children.length : -1,
      abnTotaal: document.getElementById("c_ABN_totaal_inc_fee")?.textContent ?? null,
      abnStatus: document.getElementById("c_ABN_status")?.textContent ?? null,
      abnQty: document.getElementById("c_ABN_eq_aantal_bezit")?.textContent ?? null
    }});
  }} catch (e) {{
    return JSON.stringify({{
      ok: false,
      func: "{func_name}",
      error: String(e),
      stack: (e && e.stack) ? String(e.stack) : null
    }});
  }}
}})()
"""
            def _on_result(result):
                print(f"[aandelen-web-debug] js_call_result result={result}")
            self.web.page().runJavaScript(script, 0, _on_result)
            return
        self.web.page().runJavaScript(f"window.{func_name}({js_payload});")

    def _debug_probe_js(self, label: str) -> None:
        if not AANDELEN_WEB_DEBUG or not hasattr(self, "web") or not self._js_ready:
            return
        script = """
(() => {
  try {
    const tbody = document.getElementById("tbody");
    const rows = tbody ? tbody.children.length : -1;
    const abnTotaal = document.getElementById("c_ABN_totaal_inc_fee")?.textContent ?? null;
    const abnStatus = document.getElementById("c_ABN_status")?.textContent ?? null;
    const abnQty = document.getElementById("c_ABN_eq_aantal_bezit")?.textContent ?? null;
    return JSON.stringify({ ok: true, rows, abnTotaal, abnStatus, abnQty });
  } catch (e) {
    return JSON.stringify({ ok: false, error: String(e), stack: (e && e.stack) ? String(e.stack) : null });
  }
})()
"""
        def _on_result(result):
            print(f"[aandelen-web-debug] dom_probe label={label} result={result}")
        self.web.page().runJavaScript(script, 0, _on_result)

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
        signals.queued_emit_aandelenProjectionFilterChanged(
            {"selected_brokers": sorted(self.selected_brokers) if self.selected_brokers else []}
        )

    def _clear_backend_broker_filter(self):
        self.selected_brokers = None
        signals.queued_emit_aandelenProjectionFilterChanged({"selected_brokers": []})

    def _reset_column_widths(self):
        self._call_js("resetColumnWidths", {})

    def _publish_saved_column_widths(self):
        widths = {}
        try:
            widths = get_settings().get_aandelen_web_col_widths() or {}
        except Exception:
            widths = {}
        self._call_js("applySavedColumnWidths", {"widths": widths})

    def _save_column_widths(self, payload_json: str):
        try:
            raw = json.loads(payload_json or "{}")
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        clean: dict[str, int] = {}
        for k, v in raw.items():
            key = str(k).strip()
            if not key:
                continue
            try:
                iv = int(v)
            except Exception:
                continue
            if iv > 0:
                clean[key] = iv
        try:
            get_settings().set_aandelen_web_col_widths(clean)
        except Exception as exc:
            print(f"[aandelen-web] save column widths failed: {exc}")

    def _export_snapshot(self):
        df = self._current_snapshot_df()
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

    def _current_snapshot_df(self):
        use_scenario = bool(getattr(SNAPSHOT_STORE, "runtime_test_orders_enabled", False))
        if use_scenario:
            try:
                scenario_id = getattr(SNAPSHOT_STORE, "runtime_active_test_order_scenario_id", None)
                df_scenario = build_aandelen_scenario_overlay_df(
                    scenario_id=scenario_id,
                    enabled=True,
                )
                if df_scenario is not None:
                    return df_scenario
            except Exception:
                pass
            df = getattr(SNAPSHOT_STORE, "snapshot_aandelen_projection_v2_scenario", None)
            if df is not None:
                return df
        return getattr(SNAPSHOT_STORE, "snapshot_aandelen_projection_v2", None)

    def _html_template(self) -> str:
        return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
      * { box-sizing: border-box; }
      html, body { height:100%; margin:0; padding:0; overflow:hidden; }
      body { font-family: Segoe UI, Arial, sans-serif; padding:12px; background:#f5f6f8; display:flex; flex-direction:column; min-height:0; }
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
      .filters select {
        font-size:12px;
        padding:4px 6px;
        border:1px solid #c7d1de;
        border-radius:6px;
        min-width:120px;
        background:#fff;
      }
      .filters button {
        font-size:12px;
        padding:4px 8px;
        border:1px solid #b8c3d3;
        background:#f4f7fb;
        border-radius:6px;
        cursor:pointer;
      }
      .table-shell { border:1px solid #d8dde6; border-radius:8px; background:#fff; flex:1 1 auto; min-height:0; display:flex; flex-direction:column; overflow:hidden; }
      .table-scroll { flex:1 1 auto; min-height:0; overflow-y:auto; overflow-x:auto; }
      .table-scroll { scrollbar-width: none; -ms-overflow-style: none; }
      .table-scroll::-webkit-scrollbar { width:0px; height:0px; }
      .footer-wrap { flex:0 0 auto; overflow-x:auto; overflow-y:hidden; border-top:1px solid #c8d2df; padding-right:0; }
      table { width:max-content; min-width:0; border-collapse:collapse; font-size:12px; table-layout: fixed; }
      col { width: 110px; }
      thead th {
        position: sticky; top: 0; z-index: 2;
        background:#eef2f7; color:#223247; font-weight:700;
        border-bottom:1px solid #d8dde6;
        padding:6px 8px; text-align:left; cursor:pointer; white-space:nowrap;
        user-select: none;
        overflow: hidden;
        text-overflow: ellipsis;
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
        background:#e6ebf2;
        padding:5px 8px;
        font-weight:700;
      }
      tfoot td:first-child {
        position: sticky;
        left: 0;
        z-index: 4;
        background:#e6ebf2;
        box-shadow: 1px 0 0 #c8d2df;
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
      <button id="btn_select_brokers">Selecteer brokers</button>
      <button id="btn_clear_brokers">Wis brokers</button>
      <input id="f_global" placeholder="Zoek alle kolommen..." />
      <input id="f_asset" placeholder="Filter asset_rollup" />
      <select id="f_regio">
        <option value="__ALL__">Alle regio's</option>
      </select>
      <select id="f_sector">
        <option value="__ALL__">Alle sectoren</option>
      </select>
      <select id="f_status">
        <option value="__ALL__">Alle assets</option>
      </select>
      <button id="btn_clear_filters">Wis filters</button>
      <label style="display:flex;align-items:center;gap:4px;font-size:12px;color:#33485f;">
        <input id="f_table_live_update" type="checkbox" />
        Table live update
      </label>
      <button id="btn_export_snapshot">Export snapshot</button>
    </div>
    <div class="table-shell">
      <div class="table-scroll" id="table-scroll">
        <table id="tbl-main">
          <colgroup id="colgroup-main"></colgroup>
          <thead><tr id="thead-row"></tr></thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>
      <div class="footer-wrap" id="footer-wrap">
        <table id="tbl-footer">
          <colgroup id="colgroup-footer"></colgroup>
          <tfoot><tr id="tfoot-row-footer"></tr></tfoot>
        </table>
      </div>
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
      const LEGACY_COL_WIDTHS = {
        asset_rollup: 170,
        koers_prev: 90,
        koers: 90,
        pct_change: 90,
        eq_aantal_bezit: 110,
        open_sp_aantal: 100,
        eq_total_result: 115,
        clos_opt_transactie_euro_totaal: 130,
        clos_sp_transactie_euro_totaal: 130,
        open_opt_total_result: 120,
        open_sp_result: 110,
        div_en_bel: 95,
        totaal_ex_fee: 115,
        totaal_inc_fee: 115,
        net_change: 105,
        totaal_fee: 95,
        regio: 70,
        sector: 120,
        value_grow: 90,
        status: 90,
        portfolio_total_waarde_lineair_pct: 120,
        portfolio_total_waarde_delta_pct: 120,
        optie_tijdswaarde_signed_eur: 130
      };
      const state = {
        cols: [],
        rows: new Map(),
        sortCol: "asset_rollup",
        sortDir: "asc",
        liveSortEnabled: false,
        frozenOrder: [],
        frozenPos: {},
        colWidths: {},
        savedWidths: {},
        hasSnapshot: false,
        filters: {
          global: "",
          asset_rollup: "",
          regio: "__ALL__",
          sector: "__ALL__",
          status: "__ALL__"
        }
      };

      const PCT_COLS = new Set([
        "pct_change",
        "portfolio_total_waarde_lineair_pct",
        "portfolio_total_waarde_delta_pct"
      ]);
      const QTY_COLS = new Set(["eq_aantal_bezit", "open_sp_aantal"]);
      const MONEY_COLS = new Set([
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
        "optie_tijdswaarde_signed_eur",
        "koers_prev",
        "koers"
      ]);
      const FOOTER_BLANK_COLS = new Set([
        "koers_prev",
        "koers",
        "pct_change",
        "eq_aantal_bezit",
        "open_sp_aantal"
      ]);

      function fmtNlNumber(v, decimals) {
        if (!isNum(v)) return "";
        return Number(v).toLocaleString("nl-NL", {
          minimumFractionDigits: decimals,
          maximumFractionDigits: decimals
        });
      }

      function fmtCell(col, v) {
        if (v === null || v === undefined) return "";
        if (!isNum(v)) return String(v);
        if (PCT_COLS.has(col)) return `${fmtNlNumber(v * 100, 2)}%`;
        if (QTY_COLS.has(col)) return fmtNlNumber(v, 3);
        if (MONEY_COLS.has(col)) return fmtNlNumber(v, 2);
        return fmtNlNumber(v, 2);
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
        if (c === 0) {
          c = rowStableKey(a).localeCompare(rowStableKey(b));
        }
        return dir === "asc" ? c : -c;
      }

      function rowStableKey(row) {
        return String(
          row?.uniek_id
          ?? row?.asset_rollup
          ?? row?.row_id
          ?? ""
        );
      }

      function _rebuildFrozenPos() {
        const pos = {};
        state.frozenOrder.forEach((rid, idx) => { pos[rid] = idx; });
        state.frozenPos = pos;
      }

      function _seedFrozenOrderFromCurrentSort() {
        const rows = visibleRows();
        rows.sort((a, b) => compareRows(a, b, state.sortCol, state.sortDir));
        state.frozenOrder = rows.map((r) => rowStableKey(r));
        _rebuildFrozenPos();
      }

      function _syncFrozenOrderWithRows() {
        const currentKeys = Array.from(state.rows.values()).map((r) => rowStableKey(r));
        const keySet = new Set(currentKeys);
        const kept = state.frozenOrder.filter((k) => keySet.has(k));
        const keptSet = new Set(kept);
        const added = currentKeys.filter((k) => !keptSet.has(k));
        state.frozenOrder = kept.concat(added);
        _rebuildFrozenPos();
      }

      function _displayRows() {
        const rows = visibleRows();
        if (state.liveSortEnabled) {
          rows.sort((a, b) => compareRows(a, b, state.sortCol, state.sortDir));
          return rows;
        }
        if (!state.frozenOrder.length) {
          _seedFrozenOrderFromCurrentSort();
        }
        rows.sort((a, b) => {
          const ka = rowStableKey(a);
          const kb = rowStableKey(b);
          const pa = Object.prototype.hasOwnProperty.call(state.frozenPos, ka) ? state.frozenPos[ka] : Number.MAX_SAFE_INTEGER;
          const pb = Object.prototype.hasOwnProperty.call(state.frozenPos, kb) ? state.frozenPos[kb] : Number.MAX_SAFE_INTEGER;
          if (pa !== pb) return pa - pb;
          return compareRows(a, b, state.sortCol, state.sortDir);
        });
        return rows;
      }

      function orderedCols(cols) {
        const left = PREFERRED_ORDER.filter(c => cols.includes(c));
        const rest = cols.filter(c => !left.includes(c));
        return left.concat(rest);
      }

      function saveColWidths() {
        state.savedWidths = Object.assign({}, state.colWidths || {});
        if (state.bridge && state.bridge.saveColumnWidths) {
          try {
            state.bridge.saveColumnWidths(JSON.stringify(state.colWidths || {}));
          } catch (_) {}
        }
      }

      function defaultColWidth(col) {
        if (Object.prototype.hasOwnProperty.call(LEGACY_COL_WIDTHS, col)) {
          return LEGACY_COL_WIDTHS[col];
        }
        if (col === "asset_rollup") return 180;
        if (col === "sector" || col === "status") return 130;
        if (col === "regio" || col === "value_grow") return 90;
        return 110;
      }

      function colWidth(col) {
        const w = Number(state.colWidths[col]);
        if (Number.isFinite(w) && w >= 28) return w;
        return defaultColWidth(col);
      }

      function applyColWidths() {
        const ids = ["colgroup-main", "colgroup-footer"];
        for (const id of ids) {
          const cg = document.getElementById(id);
          if (!cg) continue;
          cg.innerHTML = "";
          for (const col of state.cols) {
            const c = document.createElement("col");
            c.style.width = `${colWidth(col)}px`;
            cg.appendChild(c);
          }
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
          const cw = colWidth(col);
          th.style.width = `${cw}px`;
          th.style.minWidth = `${cw}px`;
          th.style.maxWidth = `${cw}px`;
          th.textContent = col;
          if (col === state.sortCol) th.className = state.sortDir === "asc" ? "sorted-asc" : "sorted-desc";
          th.onclick = () => {
            if (state.sortCol === col) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
            else { state.sortCol = col; state.sortDir = "asc"; }
            if (!state.liveSortEnabled) {
              _seedFrozenOrderFromCurrentSort();
            }
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
          const w = Math.max(28, startW + delta);
          state.colWidths[col] = w;
          const cg = document.getElementById("colgroup");
          if (cg && cg.children[idx]) cg.children[idx].style.width = `${w}px`;
          const th = document.getElementById("thead-row")?.children?.[idx];
          if (th) {
            th.style.width = `${w}px`;
            th.style.minWidth = `${w}px`;
            th.style.maxWidth = `${w}px`;
          }
          const trf = document.getElementById("tfoot-row-footer");
          const tf = trf?.children?.[idx];
          if (tf) {
            tf.style.width = `${w}px`;
            tf.style.minWidth = `${w}px`;
            tf.style.maxWidth = `${w}px`;
          }
          const rows = document.querySelectorAll("#tbody tr");
          for (const row of rows) {
            const td = row.children?.[idx];
            if (!td) continue;
            td.style.width = `${w}px`;
            td.style.minWidth = `${w}px`;
            td.style.maxWidth = `${w}px`;
          }
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
        const rows = _displayRows();
        for (const row of rows) {
          const tr = document.createElement("tr");
          tr.id = "r_" + rowId(row.asset_rollup);
          for (const col of state.cols) {
            const td = document.createElement("td");
            td.id = "c_" + rowId(row.asset_rollup) + "_" + col;
            const cw = colWidth(col);
            td.style.width = `${cw}px`;
            td.style.minWidth = `${cw}px`;
            td.style.maxWidth = `${cw}px`;
            const v = row[col];
            td.textContent = fmtCell(col, v);
            if (isNum(v)) td.classList.add("num");
            applyCellStyle(td, col, v);
            tr.appendChild(td);
          }
          body.appendChild(tr);
        }
        renderFooter(rows);
        const bodyWrap = document.getElementById("table-scroll");
        const footWrap = document.getElementById("footer-wrap");
        if (bodyWrap && footWrap) {
          const sw = Math.max(0, bodyWrap.offsetWidth - bodyWrap.clientWidth);
          footWrap.style.paddingRight = `${sw}px`;
        }
      }

      function contains(hay, needle) {
        if (!needle) return true;
        return String(hay ?? "").toLowerCase().includes(String(needle).toLowerCase());
      }

      function visibleRows() {
        const rows = Array.from(state.rows.values());
        return rows.filter((r) => {
          if (!contains(r.asset_rollup, state.filters.asset_rollup)) return false;
          if (state.filters.regio && state.filters.regio !== "__ALL__") {
            const rowRegio = String(r.regio ?? "").trim().toLowerCase();
            const wantedRegio = String(state.filters.regio).trim().toLowerCase();
            if (rowRegio !== wantedRegio) return false;
          }
          if (state.filters.sector && state.filters.sector !== "__ALL__") {
            const rowSector = String(r.sector ?? "").trim().toLowerCase();
            const wantedSector = String(state.filters.sector).trim().toLowerCase();
            if (rowSector !== wantedSector) return false;
          }
          if (state.filters.status && state.filters.status !== "__ALL__") {
            const rowStatus = String(r.status ?? "").trim().toLowerCase();
            const wanted = String(state.filters.status).trim().toLowerCase();
            if (rowStatus !== wanted) return false;
          }
          if (state.filters.global) {
            const terms = String(state.filters.global)
              .split(",")
              .map((t) => t.trim().toLowerCase())
              .filter((t) => t.length > 0);
            for (const needle of terms) {
              const hit = state.cols.some((c) =>
                String(r[c] ?? "").toLowerCase().includes(needle)
              );
              if (!hit) return false;
            }
          }
          return true;
        });
      }

      function renderStatusOptions() {
        const sel = document.getElementById("f_status");
        if (!sel) return;
        const prev = String(state.filters.status || "__ALL__");
        const values = new Set();
        for (const row of state.rows.values()) {
          const s = String(row?.status ?? "").trim();
          if (s) values.add(s);
        }
        sel.innerHTML = "";
        const allOpt = document.createElement("option");
        allOpt.value = "__ALL__";
        allOpt.textContent = "Alle assets";
        sel.appendChild(allOpt);
        Array.from(values)
          .sort((a, b) => a.localeCompare(b))
          .forEach((v) => {
            const opt = document.createElement("option");
            opt.value = v;
            opt.textContent = v;
            sel.appendChild(opt);
          });
        const hasPrev = Array.from(sel.options).some((o) => o.value === prev);
        state.filters.status = hasPrev ? prev : "__ALL__";
        sel.value = state.filters.status;
      }

      function renderSelectOptions(selectId, key, allLabel) {
        const sel = document.getElementById(selectId);
        if (!sel) return;
        const prev = String(state.filters[key] || "__ALL__");
        const values = new Set();
        for (const row of state.rows.values()) {
          const s = String(row?.[key] ?? "").trim();
          if (s) values.add(s);
        }
        sel.innerHTML = "";
        const allOpt = document.createElement("option");
        allOpt.value = "__ALL__";
        allOpt.textContent = allLabel;
        sel.appendChild(allOpt);
        Array.from(values)
          .sort((a, b) => a.localeCompare(b))
          .forEach((v) => {
            const opt = document.createElement("option");
            opt.value = v;
            opt.textContent = v;
            sel.appendChild(opt);
          });
        const hasPrev = Array.from(sel.options).some((o) => o.value === prev);
        state.filters[key] = hasPrev ? prev : "__ALL__";
        sel.value = state.filters[key];
      }

      function renderFooter(rows) {
        const tr = document.getElementById("tfoot-row-footer");
        tr.innerHTML = "";
        for (const col of state.cols) {
          const td = document.createElement("td");
          const cw = colWidth(col);
          td.style.width = `${cw}px`;
          td.style.minWidth = `${cw}px`;
          td.style.maxWidth = `${cw}px`;
          if (col === "asset_rollup") {
            td.textContent = `total: ${rows.length}`;
          } else if (FOOTER_BLANK_COLS.has(col)) {
            td.textContent = "";
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
            td.textContent = hasNum ? fmtCell(col, sum) : "";
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
          ["f_asset", "asset_rollup"]
        ];
        for (const [id, key] of map) {
          const el = document.getElementById(id);
          if (!el) continue;
          el.addEventListener("input", () => {
            state.filters[key] = el.value || "";
            renderBody();
          });
        }
        const regioEl = document.getElementById("f_regio");
        if (regioEl) {
          regioEl.addEventListener("change", () => {
            state.filters.regio = regioEl.value || "__ALL__";
            renderBody();
          });
        }
        const sectorEl = document.getElementById("f_sector");
        if (sectorEl) {
          sectorEl.addEventListener("change", () => {
            state.filters.sector = sectorEl.value || "__ALL__";
            renderBody();
          });
        }
        const statusEl = document.getElementById("f_status");
        if (statusEl) {
          statusEl.addEventListener("change", () => {
            state.filters.status = statusEl.value || "__ALL__";
            renderBody();
          });
        }
        const liveEl = document.getElementById("f_table_live_update");
        if (liveEl) {
          liveEl.checked = !!state.liveSortEnabled;
          liveEl.addEventListener("change", () => {
            state.liveSortEnabled = !!liveEl.checked;
            if (!state.liveSortEnabled) {
              _seedFrozenOrderFromCurrentSort();
            }
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
            if (regioEl) regioEl.value = "__ALL__";
            if (sectorEl) sectorEl.value = "__ALL__";
            if (statusEl) statusEl.value = "__ALL__";
            state.filters.regio = "__ALL__";
            state.filters.sector = "__ALL__";
            state.filters.status = "__ALL__";
            renderBody();
          });
        }
        const btnSelectBrokers = document.getElementById("btn_select_brokers");
        if (btnSelectBrokers) {
          btnSelectBrokers.addEventListener("click", () => {
            if (state.bridge && state.bridge.selectBrokers) {
              try { state.bridge.selectBrokers(); } catch (_) {}
            }
          });
        }
        const btnClearBrokers = document.getElementById("btn_clear_brokers");
        if (btnClearBrokers) {
          btnClearBrokers.addEventListener("click", () => {
            if (state.bridge && state.bridge.clearBrokers) {
              try { state.bridge.clearBrokers(); } catch (_) {}
            }
          });
        }
        const btnExport = document.getElementById("btn_export_snapshot");
        if (btnExport) {
          btnExport.addEventListener("click", () => {
            if (state.bridge && state.bridge.exportSnapshot) {
              try { state.bridge.exportSnapshot(); } catch (_) {}
            }
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
        if (state.savedWidths && Object.keys(state.savedWidths).length > 0) {
          state.colWidths = Object.assign({}, state.savedWidths);
        }
        if (!state.colWidths || Object.keys(state.colWidths).length === 0) {
          const seeded = {};
          for (const c of state.cols) seeded[c] = defaultColWidth(c);
          state.colWidths = seeded;
        } else {
          for (const c of state.cols) {
            if (!Object.prototype.hasOwnProperty.call(state.colWidths, c)) {
              state.colWidths[c] = defaultColWidth(c);
            }
          }
        }
        if (!state.cols.includes(state.sortCol)) state.sortCol = "asset_rollup";
        if (!state.liveSortEnabled) {
          if (state.frozenOrder.length > 0) _syncFrozenOrderWithRows();
          else _seedFrozenOrderFromCurrentSort();
        }
        state.hasSnapshot = true;
        renderSelectOptions("f_regio", "regio", "Alle regio's");
        renderSelectOptions("f_sector", "sector", "Alle sectoren");
        renderStatusOptions();
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
          td.textContent = fmtCell(field, value);
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
            const rid = String(ch.row_id);
            state.frozenOrder = state.frozenOrder.filter((x) => x !== rid);
            _rebuildFrozenPos();
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

      window.resetColumnWidths = function(_) {
        state.colWidths = {};
        if (state.hasSnapshot) {
          const seeded = {};
          for (const c of state.cols) seeded[c] = defaultColWidth(c);
          state.colWidths = seeded;
          saveColWidths();
          renderHeader();
          renderBody();
        }
      };

      window.applySavedColumnWidths = function(payload) {
        const w = payload && payload.widths;
        if (!w || typeof w !== "object") return;
        const parsed = {};
        for (const [k, v] of Object.entries(w)) {
          const key = String(k || "").trim();
          const iv = Number(v);
          if (!key || !Number.isFinite(iv) || iv <= 0) continue;
          parsed[key] = Math.round(iv);
        }
        state.savedWidths = parsed;
        state.colWidths = Object.assign({}, parsed);
        if (state.hasSnapshot) {
          renderHeader();
          renderBody();
        }
      };

      if (window.qt && window.QWebChannel) {
        new QWebChannel(qt.webChannelTransport, function(channel) {
          state.bridge = channel.objects.aandelenBridge || null;
        });
      }

      (function syncHorizontalScroll(){
        const body = document.getElementById("table-scroll");
        const foot = document.getElementById("footer-wrap");
        if (!body || !foot) return;
        function syncFooterCompensation(){
          const sw = Math.max(0, body.offsetWidth - body.clientWidth);
          foot.style.paddingRight = `${sw}px`;
        }
        let lock = false;
        body.addEventListener("scroll", () => {
          if (lock) return;
          lock = true;
          foot.scrollLeft = body.scrollLeft;
          lock = false;
        });
        foot.addEventListener("scroll", () => {
          if (lock) return;
          lock = true;
          body.scrollLeft = foot.scrollLeft;
          lock = false;
        });
        body.addEventListener("wheel", (ev) => {
          const dx = (Math.abs(Number(ev.deltaX || 0)) > 0)
            ? Number(ev.deltaX || 0)
            : (ev.shiftKey ? Number(ev.deltaY || 0) : 0);
          if (!dx) return;
          ev.preventDefault();
          foot.scrollLeft += dx;
          body.scrollLeft = foot.scrollLeft;
        }, { passive: false });
        window.addEventListener("resize", syncFooterCompensation);
        syncFooterCompensation();
      })();

      bindFilters();
    </script>
  </body>
</html>
"""


class _AandelenWebBridge(QObject):
    def __init__(self, tab: AandelenWebPilotTab):
        super().__init__(tab)
        self._tab = tab

    @Slot(str)
    def saveColumnWidths(self, payload_json: str) -> None:
        self._tab._save_column_widths(payload_json)

    @Slot()
    def selectBrokers(self) -> None:
        self._tab._open_broker_popup()

    @Slot()
    def clearBrokers(self) -> None:
        self._tab._clear_backend_broker_filter()

    @Slot()
    def exportSnapshot(self) -> None:
        self._tab._export_snapshot()

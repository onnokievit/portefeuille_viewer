from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QVBoxLayout, QWidget

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover
    QWebChannel = None
    QWebEngineView = None


class SprintersOpenWebPilotTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._js_ready = False
        self._pending_js_calls: list[tuple[str, object]] = []
        layout = QVBoxLayout(self)
        if QWebEngineView is None:
            layout.addWidget(QLabel("QtWebEngine niet beschikbaar in deze runtime."))
            return
        self.web = QWebEngineView(self)
        layout.addWidget(self.web)
        if QWebChannel is not None:
            self.channel = QWebChannel(self.web.page())
            self.bridge = _SprintersOpenWebBridge(self)
            self.channel.registerObject("sprintersBridge", self.bridge)
            self.web.page().setWebChannel(self.channel)
        self.web.loadFinished.connect(self._on_web_loaded)
        self.web.setHtml(self._html_template())
        signals.snapshotUpdated.connect(self._on_snapshot_updated)

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
        if snapshot_key == "snapshot_sprinters_open_projection_v2":
            self._publish_full_snapshot()
        elif snapshot_key == "snapshot_sprinters_open_projection_v2_patch":
            self._publish_patch()
        elif snapshot_key == "snapshot_sprinters_open_projection_v2_meta":
            self._publish_meta()

    def _publish_full_snapshot(self):
        df = getattr(SNAPSHOT_STORE, "snapshot_sprinters_open_projection_v2", None)
        if df is None:
            return
        try:
            rows = df.to_dicts() if hasattr(df, "to_dicts") else []
        except Exception:
            rows = []
        self._call_js("renderSnapshot", {"rows": rows})

    def _publish_patch(self):
        patch = getattr(SNAPSHOT_STORE, "snapshot_sprinters_open_projection_v2_patch", None)
        if not patch:
            return
        self._call_js("applyPatch", {"changes": list(patch)})

    def _publish_meta(self):
        meta = getattr(SNAPSHOT_STORE, "snapshot_sprinters_open_projection_v2_meta", None)
        if not isinstance(meta, dict):
            return
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

    def _export_snapshot(self):
        df = getattr(SNAPSHOT_STORE, "snapshot_sprinters_open_projection_v2", None)
        if df is None or (hasattr(df, "is_empty") and df.is_empty()):
            QMessageBox.information(self, "Export", "Geen projection snapshot beschikbaar.")
            return
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "Export Sprinters Open Projection Snapshot",
            "sprinters_open_projection_snapshot.xlsx",
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
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
      body { font-family: Segoe UI, Arial, sans-serif; margin: 12px; background:#f5f6f8; }
      .meta { margin: 0 0 10px 0; color:#44536b; font-size:12px; }
      .filters { display:flex; gap:8px; margin:0 0 8px 0; flex-wrap:wrap; }
      .filters input { font-size:12px; padding:4px 6px; border:1px solid #c7d1de; border-radius:6px; min-width:150px; }
      .filters button { font-size:12px; padding:4px 8px; border:1px solid #b8c3d3; background:#f4f7fb; border-radius:6px; cursor:pointer; }
      .table-wrap { border:1px solid #d8dde6; border-radius:8px; overflow:auto; background:#fff; max-height:78vh; }
      table { width:100%; border-collapse:collapse; font-size:12px; table-layout: fixed; }
      thead th { position: sticky; top: 0; z-index: 2; background:#eef2f7; color:#223247; font-weight:700; border-bottom:1px solid #d8dde6; padding:6px 8px; text-align:left; cursor:pointer; white-space:nowrap; }
      tbody td { border-top:1px solid #eef1f5; padding:4px 8px; white-space:nowrap; overflow: hidden; text-overflow: ellipsis; }
      tbody tr:nth-child(even) { background:#fafbfd; }
      td.num { text-align:right; font-variant-numeric: tabular-nums; }
      th.sorted-asc::after { content: " \\2191"; }
      th.sorted-desc::after { content: " \\2193"; }
    </style>
  </head>
  <body>
    <div class="meta" id="meta">Sprinters Projection v- | rows: 0</div>
    <div class="filters">
      <input id="f_global" placeholder="Zoek alle kolommen..." />
      <input id="f_asset" placeholder="Filter asset_rollup" />
      <input id="f_broker" placeholder="Filter broker" />
      <button id="btn_clear_filters">Wis filters</button>
      <button id="btn_export_snapshot">Export snapshot</button>
    </div>
    <div class="table-wrap">
      <table id="tbl"><thead><tr id="thead-row"></tr></thead><tbody id="tbody"></tbody></table>
    </div>
    <script>
      const state = { cols: [], rows: new Map(), sortCol: "asset_rollup", sortDir: "asc", hasSnapshot:false, filters:{global:"",asset_rollup:"",broker:""}, bridge:null };
      function fmt(v){ if(v===null||v===undefined) return ""; if(typeof v==="number") return Number.isFinite(v)?v.toFixed(2):""; return String(v); }
      function isNum(v){ return typeof v==="number" && Number.isFinite(v); }
      function compareRows(a,b,col,dir){ const av=a[col], bv=b[col]; let c=0; if(isNum(av)&&isNum(bv)) c=av-bv; else c=String(av??"").localeCompare(String(bv??"")); return dir==="asc"?c:-c; }
      function contains(h,n){ if(!n) return true; return String(h??"").toLowerCase().includes(String(n).toLowerCase()); }
      function visibleRows(){ const rows=Array.from(state.rows.values()); return rows.filter(r=>{ if(!contains(r.asset_rollup,state.filters.asset_rollup)) return false; if(!contains(r.broker,state.filters.broker)) return false; if(state.filters.global){ const needle=state.filters.global.toLowerCase(); if(!state.cols.some(c=>String(r[c]??"").toLowerCase().includes(needle))) return false; } return true;});}
      function renderHeader(){ const tr=document.getElementById("thead-row"); tr.innerHTML=""; state.cols.forEach(col=>{ const th=document.createElement("th"); th.textContent=col; if(col===state.sortCol) th.className=state.sortDir==="asc"?"sorted-asc":"sorted-desc"; th.onclick=()=>{ if(state.sortCol===col) state.sortDir=state.sortDir==="asc"?"desc":"asc"; else {state.sortCol=col; state.sortDir="asc";} renderHeader(); renderBody(); }; tr.appendChild(th); }); }
      function renderBody(){ const body=document.getElementById("tbody"); body.innerHTML=""; const rows=visibleRows(); rows.sort((a,b)=>compareRows(a,b,state.sortCol,state.sortDir)); for(const row of rows){ const tr=document.createElement("tr"); for(const col of state.cols){ const td=document.createElement("td"); const v=row[col]; td.textContent=fmt(v); if(isNum(v)) td.classList.add("num"); tr.appendChild(td);} body.appendChild(tr);} }
      function bindFilters(){ const map=[["f_global","global"],["f_asset","asset_rollup"],["f_broker","broker"]]; for(const [id,key] of map){ const el=document.getElementById(id); if(!el) continue; el.addEventListener("input",()=>{state.filters[key]=el.value||""; renderBody();}); } const clear=document.getElementById("btn_clear_filters"); if(clear){ clear.addEventListener("click",()=>{ for(const [id,key] of map){ const el=document.getElementById(id); if(el) el.value=""; state.filters[key]=""; } renderBody();});}}
      function bindActions(){
        const btn=document.getElementById("btn_export_snapshot");
        if(btn && state.bridge && state.bridge.exportSnapshot){
          btn.addEventListener("click",()=>state.bridge.exportSnapshot());
        }
      }
      window.renderMeta = function(meta){ const el=document.getElementById("meta"); if(!el||!meta) return; const v=meta.version??"-"; const r=meta.rows??0; const c=meta.changes??0; const u=meta.updated_at??"-"; const reason=meta.reason??"-"; const m=meta.metrics||{}; const ml=m.last||{}; const ms=m.summary||{}; const txt=`Sprinters Projection v${v} | rows:${r} | changes:${c} | updated:${u} | reason:${reason} | perf rec:${Number(ml.recompute_ms??0).toFixed(1)}ms pub:${Number(ml.publish_ms??0).toFixed(1)}ms tot:${Number(ml.total_ms??0).toFixed(1)}ms p95:${Number(ms.total_ms_p95??0).toFixed(1)}ms`; el.textContent=txt; };
      window.renderSnapshot = function(payload){ const rows=(payload&&payload.rows)?payload.rows:[]; state.rows.clear(); if(rows.length===0){ state.cols=[]; state.hasSnapshot=false; renderHeader(); renderBody(); return; } const colSet=new Set(); for(const row of rows){ if(!row||!row.row_id) continue; state.rows.set(String(row.row_id), row); Object.keys(row).forEach(k=>colSet.add(k)); } state.cols=Array.from(colSet); if(!state.cols.includes(state.sortCol)) state.sortCol=state.cols.includes("asset_rollup")?"asset_rollup":state.cols[0]; state.hasSnapshot=true; renderHeader(); renderBody(); };
      window.applyPatch = function(payload){ if(!state.hasSnapshot) return; const changes=(payload&&payload.changes)?payload.changes:[]; for(const ch of changes){ if(!ch||!ch.row_id) continue; const rid=String(ch.row_id); if(ch.field==="__deleted__"){ state.rows.delete(rid); continue; } const row=state.rows.get(rid); if(!row) continue; row[ch.field]=ch.value; } renderBody(); };
      if (window.qt && window.QWebChannel) {
        new QWebChannel(qt.webChannelTransport, function(channel) {
          state.bridge = channel.objects.sprintersBridge || null;
          bindActions();
        });
      }
      bindFilters();
    </script>
  </body>
</html>
"""


class _SprintersOpenWebBridge(QObject):
    def __init__(self, tab: SprintersOpenWebPilotTab):
        super().__init__(tab)
        self._tab = tab

    @Slot()
    def exportSnapshot(self) -> None:
        self._tab._export_snapshot()

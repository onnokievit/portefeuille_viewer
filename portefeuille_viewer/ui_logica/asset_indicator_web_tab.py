from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from PySide6.QtCore import QObject, QSettings, QTimer, Slot
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.services.asset_indicator_service import rebuild_asset_indicator_snapshots
from portefeuille_viewer.signals import signals

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover
    QWebEngineView = None

try:
    from PySide6.QtWebChannel import QWebChannel
except Exception:  # pragma: no cover
    QWebChannel = None


ASSET_INDICATOR_COLUMN_ORDER_SETTING = "asset_indicator/column_order_v1"


class _AssetIndicatorWebBridge(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("portefeuille_viewer", "portefeuille_viewer")

    @Slot(str)
    def saveColumnOrder(self, payload: str):
        try:
            value = json.loads(payload)
        except Exception:
            return
        if not isinstance(value, list):
            return
        cleaned = [str(item) for item in value if str(item).strip()]
        if not cleaned:
            return
        self._settings.setValue(ASSET_INDICATOR_COLUMN_ORDER_SETTING, json.dumps(cleaned))
        self._settings.sync()


class AssetIndicatorWebTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._js_ready = False
        self._is_active = False
        self._needs_render = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(300)
        self._render_timer.timeout.connect(self._publish_snapshot)

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.btn_run = QPushButton("Run indicator", self)
        self.btn_refresh = QPushButton("Refresh view", self)
        self.status_label = QLabel("Nog niet gedraaid.", self)
        toolbar.addWidget(self.btn_run)
        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.status_label, 1)
        layout.addLayout(toolbar)

        if QWebEngineView is None:
            layout.addWidget(QLabel("QtWebEngine niet beschikbaar in deze runtime."))
            return

        self.web = QWebEngineView(self)
        layout.addWidget(self.web, 1)
        self.channel = None
        self.bridge = _AssetIndicatorWebBridge(self)
        if QWebChannel is not None:
            self.channel = QWebChannel(self.web.page())
            self.channel.registerObject("assetIndicatorBridge", self.bridge)
            self.web.page().setWebChannel(self.channel)
        self.web.loadFinished.connect(self._on_web_loaded)
        self.web.setHtml(self._html_template())
        self.btn_run.clicked.connect(self.run_indicator)
        self.btn_refresh.clicked.connect(self._publish_snapshot)
        signals.snapshotUpdated.connect(self._on_snapshot_updated)

    def set_active(self, active: bool):
        self._is_active = bool(active)
        if self._is_active and self._js_ready:
            live_df = getattr(SNAPSHOT_STORE, "snapshot_asset_indicator_live", None)
            if live_df is None:
                self.run_indicator()
            else:
                self._publish_snapshot()
        elif not self._is_active:
            self._render_timer.stop()

    def run_indicator(self):
        self.status_label.setText("Indicator draait...")
        result = rebuild_asset_indicator_snapshots()
        if result.status == "ok":
            self.status_label.setText(
                f"OK | total {result.assets_total} | scored {result.assets_scored} | "
                f"insufficient {result.assets_insufficient_data} | {result.duration_ms:.0f} ms"
            )
        else:
            self.status_label.setText(f"Fout: {result.error}")
        self._publish_snapshot()

    def _on_web_loaded(self, ok: bool):
        self._js_ready = bool(ok)
        if self._js_ready:
            self._publish_snapshot()

    def _on_snapshot_updated(self, snapshot_key: str):
        if snapshot_key in {
            "snapshot_asset_indicator_live",
            "snapshot_asset_indicator_summary",
            "snapshot_asset_indicator_meta",
        }:
            self._schedule_render()
        elif snapshot_key == "snapshot_optie_timevalue_live":
            self.status_label.setText("Timevalue bijgewerkt. Run indicator om theta mee te nemen.")

    def _schedule_render(self):
        if not self._is_active or not self._js_ready:
            self._needs_render = True
            return
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _publish_snapshot(self):
        if not self._js_ready or not hasattr(self, "web"):
            return
        live_df = getattr(SNAPSHOT_STORE, "snapshot_asset_indicator_live", None)
        summary_df = getattr(SNAPSHOT_STORE, "snapshot_asset_indicator_summary", None)
        meta_df = getattr(SNAPSHOT_STORE, "snapshot_asset_indicator_meta", None)
        tv_df = getattr(SNAPSHOT_STORE, "snapshot_optie_timevalue_live", None)
        payload = {
            "live": [] if live_df is None or live_df.is_empty() else live_df.to_dicts(),
            "summary": [] if summary_df is None or summary_df.is_empty() else summary_df.to_dicts(),
            "meta": [] if meta_df is None or meta_df.is_empty() else meta_df.to_dicts(),
            "timevalue_rows": 0 if tv_df is None else int(getattr(tv_df, "height", 0) or 0),
        }
        self._run_js("renderData", payload)
        self._needs_render = False

    def _run_js(self, func_name: str, payload: object):
        js_payload = json.dumps(payload, ensure_ascii=False, default=self._json_default)
        self.web.page().runJavaScript(f"window.{func_name}({js_payload});")

    @staticmethod
    def _json_default(value):
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    def _load_column_order_setting(self) -> list[str]:
        raw = QSettings("portefeuille_viewer", "portefeuille_viewer").value(
            ASSET_INDICATOR_COLUMN_ORDER_SETTING, ""
        )
        if not raw:
            return []
        if isinstance(raw, list):
            return [str(item) for item in raw if str(item).strip()]
        try:
            value = json.loads(str(raw))
        except Exception:
            return []
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    def _html_template(self) -> str:
        initial_column_order_json = json.dumps(self._load_column_order_setting(), ensure_ascii=False)
        html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <style>
    html, body { height:100%; margin:0; overflow:hidden; font-family: Segoe UI, Arial, sans-serif; background:#f5f6f7; color:#1d232b; font-size:13px; }
    * { box-sizing:border-box; }
    .wrap { height:100%; padding:10px; display:flex; flex-direction:column; gap:8px; }
    .summary { display:grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap:8px; }
    .card { background:#fff; border:1px solid #d8dde3; border-radius:6px; padding:8px 10px; }
    .card .k { color:#5d6673; font-size:12px; }
    .card .v { font-size:18px; font-weight:650; }
    .toolbar { background:#fff; border:1px solid #d8dde3; border-radius:6px; padding:8px; display:grid; grid-template-columns:1.2fr repeat(5, minmax(130px, 190px)) auto; gap:8px; align-items:end; }
    label { display:block; color:#5d6673; font-size:12px; margin-bottom:3px; }
    input, select { width:100%; height:28px; border:1px solid #bfc7d1; border-radius:4px; background:#fff; padding:3px 7px; font:inherit; }
    input[type="checkbox"] { width:16px; height:16px; margin:0; padding:0; flex:0 0 16px; }
    .reset-btn { height:28px; border:1px solid #bfc7d1; border-radius:4px; background:#fff; padding:0 10px; font:inherit; cursor:pointer; white-space:nowrap; color:#5d6673; }
    .reset-btn:hover { background:#eef2f6; }
    .count { color:#5d6673; font-size:12px; }
    .table-wrap { flex:1; overflow:auto; border:1px solid #d8dde3; background:#fff; }
    table { width:100%; border-collapse:collapse; }
    th, td { border-bottom:1px solid #e5e9ee; border-right:1px solid #eef1f4; padding:5px 7px; white-space:nowrap; vertical-align:top; }
    th { position:sticky; top:0; background:#eef2f6; z-index:1; cursor:grab; text-align:left; user-select:none; }
    th.filtered { background:#dbeafe; }
    th.dragging { opacity:0.35; cursor:grabbing; }
    th.drag-over { box-shadow:inset -3px 0 0 #3b82f6; }
    td.num { text-align:right; font-variant-numeric:tabular-nums; }
    td.reasons { white-space:normal; min-width:350px; max-width:620px; }
    tr.long_houden { background:#dff4e5; }
    tr.schrijf_puts { background:#e3eefc; }
    tr.theta_harvest { background:#e0f7f2; }
    tr.risico_verlagen { background:#ffd6d6; }
    tr.reduce_via_covered_call { background:#fff3c4; }
    tr.geen_advies_onvoldoende_data { background:#eceff3; color:#59616d; }
    .pill { display:inline-block; padding:2px 6px; border-radius:999px; border:1px solid #ccd3dc; background:#fff; }
    .small { color:#5d6673; font-size:12px; }
    .context-menu { position:fixed; display:none; min-width:230px; background:#fff; border:1px solid #aeb7c2; border-radius:6px; box-shadow:0 8px 20px rgba(0,0,0,.18); z-index:20; padding:5px; }
    .context-menu button { display:block; width:100%; height:30px; border:0; background:#fff; text-align:left; padding:5px 10px; font:inherit; cursor:pointer; border-radius:4px; }
    .context-menu button:hover { background:#eef2f6; }
    .context-menu button:disabled { color:#aab; cursor:default; }
    .context-menu button:disabled:hover { background:#fff; }
    .context-menu .sep { height:1px; background:#e5e9ee; margin:5px 0; }
    .modal-backdrop { position:fixed; inset:0; display:none; align-items:center; justify-content:center; background:rgba(25,31,38,.25); z-index:30; }
    .filter-dialog { width:420px; max-height:78vh; background:#f7f7f7; border:1px solid #b9c1cb; border-radius:6px; box-shadow:0 10px 28px rgba(0,0,0,.22); padding:12px; display:flex; flex-direction:column; gap:8px; }
    .filter-title { display:flex; justify-content:space-between; align-items:center; color:#5d6673; font-size:14px; }
    .close-btn { width:30px; height:28px; border:0; background:#ddd; cursor:pointer; }
    .check-all { display:flex; gap:7px; align-items:center; justify-content:flex-start; font-weight:600; min-height:22px; line-height:20px; }
    .value-list { flex:1; min-height:160px; max-height:380px; overflow:auto; background:#fff; border:1px solid #e5e9ee; border-radius:6px; padding:6px; }
    .value-row { display:flex; gap:7px; align-items:center; justify-content:flex-start; min-height:22px; line-height:20px; padding:1px 4px; border-radius:4px; color:#111827; }
    .value-row:hover { background:#f1f5f9; }
    .dialog-buttons { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
    .dialog-buttons button { height:30px; border:1px solid #bfc7d1; border-radius:4px; background:#fff; cursor:pointer; font:inherit; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="summary" id="summary"></div>
    <div class="toolbar">
      <div><label>Zoek</label><input id="q" placeholder="Komma zoeken: AHOLD, VFC, range..."/></div>
      <div><label>Primary action</label><select id="action"></select></div>
      <div><label>Indicator rol</label><select id="role"></select></div>
      <div><label>Asset fase</label><select id="mode"></select></div>
      <div><label>Data quality</label><select id="quality"></select></div>
      <div><label>Secondary</label><select id="secondary"></select></div>
      <div><label>&nbsp;</label><button class="reset-btn" id="resetColsBtn" title="Kolom volgorde herstellen naar standaard">&#8635; kolommen</button></div>
    </div>
    <div class="count" id="count"></div>
    <div class="table-wrap">
      <table>
        <thead><tr id="thead-row"></tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </div>
  <div id="contextMenu" class="context-menu">
    <button data-action="sortAsc">Sorteren A &#8594; Z</button>
    <button data-action="sortDesc">Sorteren Z &#8594; A</button>
    <div class="sep"></div>
    <button data-action="clearFilter">Filter wissen</button>
    <button data-action="chooseValues">Waarden kiezen...</button>
  </div>
  <div id="filterModal" class="modal-backdrop">
    <div class="filter-dialog">
      <div class="filter-title"><span id="filterTitle">Filter</span><button id="filterClose" class="close-btn">x</button></div>
      <input id="filterSearch" placeholder="Zoek..."/>
      <label class="check-all"><input type="checkbox" id="filterAll"> (Alles selecteren)</label>
      <div id="filterValues" class="value-list"></div>
      <div class="dialog-buttons">
        <button id="filterOk">OK</button>
        <button id="filterClear">Wissen</button>
        <button id="filterCancel">Cancel</button>
      </div>
    </div>
  </div>
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <script>
    // ── Column definitions ────────────────────────────────────────────────────
    const COLS = [
      {key:"asset_rollup",                    label:"Asset",      render:r=>`<strong>${esc(r.asset_rollup)}</strong>`},
      {key:"asset_name",                      label:"Name",       render:r=>esc(r.asset_name)},
      {key:"indicator_role",                  label:"Rol",        render:r=>esc(r.indicator_role)},
      {key:"direction_score",                 label:"Direction",  num:true},
      {key:"long_term_direction_score",       label:"LT",         num:true},
      {key:"short_term_direction_score",      label:"ST",         num:true},
      {key:"range_position_pct",              label:"Range %",    num:true},
      {key:"trend_phase",                     label:"Trend fase", render:r=>esc(r.trend_phase)},
      {key:"realized_volatility_score",       label:"RV score",   num:true},
      {key:"atr_pct",                         label:"ATR %",      num:true},
      {key:"choppiness_score",                label:"Chop",       num:true},
      {key:"ibkr_hv_proxy_pct",              label:"HV %",       num:true},
      {key:"ibkr_iv_proxy_pct",              label:"IV %",       num:true},
      {key:"iv_vs_realized_volatility_score", label:"IV/RV",      num:true},
      {key:"theta_opportunity_proxy_score",   label:"Asset theta proxy",  num:true},
      {key:"theta_score",                     label:"Optie theta",        num:true},
      {key:"volume_score",                    label:"Volume",     num:true},
      {key:"asset_fase",                      label:"Asset fase", render:r=>`<span class="pill">${esc(r.asset_fase)}</span>`},
      {key:"primary_action",                  label:"Action",     render:r=>`<span class="pill">${esc(r.primary_action)}</span>`},
      {key:"secondary_action",               label:"Secondary",  render:r=>esc(r.secondary_action)},
      {key:"data_quality",                    label:"Quality",    render:r=>esc(r.data_quality)},
      {key:"_reasons", label:"Reasons", wide:true, noSort:true, noFilter:true,
       render:r=>`<div>${esc(r.reason_1)}</div><div class="small">${esc(r.reason_2)}</div><div class="small">${esc(r.reason_3)}</div>`},
    ];
    const COL_MAP = Object.fromEntries(COLS.map(c=>[c.key,c]));
    const DEFAULT_ORDER = COLS.map(c=>c.key);
    const LS_KEY = "asset_indicator_col_order_v1";
    const INITIAL_COLUMN_ORDER = __INITIAL_COLUMN_ORDER_JSON__;
    let qtBridge = null;

    // ── Column order: QSettings persistence, localStorage fallback ────────────
    function normalizeColOrder(saved) {
      if (!Array.isArray(saved)) return null;
      const all = new Set(DEFAULT_ORDER);
      const valid = saved.map(k=>String(k)).filter(k=>all.has(k));
      DEFAULT_ORDER.forEach(k=>{ if(!valid.includes(k)) valid.push(k); });
      return valid.length ? valid : null;
    }
    function loadColOrder() {
      const initial = normalizeColOrder(INITIAL_COLUMN_ORDER);
      if (initial) return initial;
      try {
        const saved = JSON.parse(localStorage.getItem(LS_KEY)||"null");
        const valid = normalizeColOrder(saved);
        if (valid) return valid;
      } catch(e){}
      return [...DEFAULT_ORDER];
    }
    function saveColOrderToQt() {
      try {
        if (qtBridge && qtBridge.saveColumnOrder) {
          qtBridge.saveColumnOrder(JSON.stringify(columnOrder));
        }
      } catch(e){}
    }
    function saveColOrder() {
      try { localStorage.setItem(LS_KEY, JSON.stringify(columnOrder)); } catch(e){}
      saveColOrderToQt();
    }
    function resetColOrder() { columnOrder=[...DEFAULT_ORDER]; saveColOrder(); render(); }
    let columnOrder = loadColOrder();
    function orderedCols() { return columnOrder.map(k=>COL_MAP[k]).filter(Boolean); }
    function connectQtBridge() {
      if (window.qt && window.QWebChannel) {
        new QWebChannel(qt.webChannelTransport, function(channel) {
          qtBridge = channel.objects.assetIndicatorBridge || null;
          saveColOrderToQt();
        });
      }
    }

    // ── App state ─────────────────────────────────────────────────────────────
    let rows=[], summaryRows=[], metaRows=[], timevalueRows=0;
    let contextKey=null, dialogKey=null, dialogSelection=new Set();
    const columnFilters={};
    const state={sortKey:"primary_action", sortDir:"asc", q:"", action:"__ALL__", role:"__ALL__", mode:"__ALL__", quality:"__ALL__", secondary:"__ALL__"};

    // ── Helpers ───────────────────────────────────────────────────────────────
    function fmt(v){ if(v===null||v===undefined||v==="") return "-"; if(typeof v==="number") return Number.isFinite(v)?v.toFixed(1):"-"; return String(v); }
    function esc(v){ return String(v??"").replace(/[&<>"']/g, ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch])); }
    function attr(v){ return String(v??"").replace(/[^a-zA-Z0-9_-]/g,"_"); }
    function unique(key){ return Array.from(new Set(rows.map(r=>String(r[key]??"").trim()).filter(Boolean))).sort(); }
    function fill(id,values){ const el=document.getElementById(id); const old=state[id]||"__ALL__"; el.innerHTML=""; el.append(new Option("Alle","__ALL__")); values.forEach(v=>el.append(new Option(v,v))); el.value=values.includes(old)?old:"__ALL__"; state[id]=el.value; }
    function text(r){ return [r.asset_rollup,r.asset_name,r.indicator_role,r.trend_phase,r.asset_fase,r.primary_action,r.secondary_action,r.data_quality,r.reason_1,r.reason_2,r.reason_3].map(x=>String(x??"").toLowerCase()).join(" "); }
    function searchTerms(){ return state.q.split(",").map(x=>x.trim().toLowerCase()).filter(Boolean); }

    // ── Filtering / sorting ───────────────────────────────────────────────────
    function filtered(){
      const terms=searchTerms();
      return rows.filter(r=>
        (state.action==="__ALL__"||r.primary_action===state.action)&&
        (state.role==="__ALL__"||r.indicator_role===state.role)&&
        (state.mode==="__ALL__"||r.asset_fase===state.mode)&&
        (state.quality==="__ALL__"||r.data_quality===state.quality)&&
        (state.secondary==="__ALL__"||r.secondary_action===state.secondary)&&
        Object.entries(columnFilters).every(([k,allowed])=>!allowed||allowed.has(String(r[k]??"")))&&
        (!terms.length||terms.some(t=>text(r).includes(t)))
      ).sort((a,b)=>{
        const av=a[state.sortKey],bv=b[state.sortKey];
        const an=typeof av==="number"&&Number.isFinite(av),bn=typeof bv==="number"&&Number.isFinite(bv);
        let c=(an||bn)?((an?av:-Infinity)-(bn?bv:-Infinity)):String(av??"").localeCompare(String(bv??""));
        return state.sortDir==="asc"?c:-c;
      });
    }

    // ── Thead: dynamic render + drag-drop ─────────────────────────────────────
    let dragKey=null;
    function renderThead(){
      document.getElementById("thead-row").innerHTML=orderedCols().map(col=>
        `<th data-key="${col.key}" draggable="true"
             class="${columnFilters[col.key]?"filtered":""}"
             title="${col.noSort?"Sleep om te herordenen | Rechtermuisknop voor filter":"Klik om te sorteren | Sleep om te herordenen | Rechtermuisknop voor filter"}">${col.label}</th>`
      ).join("");
      document.querySelectorAll("#thead-row th").forEach(th=>{
        const key=th.dataset.key, col=COL_MAP[key]||{};
        th.addEventListener("click",()=>{
          if(col.noSort) return;
          if(state.sortKey===key) state.sortDir=state.sortDir==="asc"?"desc":"asc";
          else { state.sortKey=key; state.sortDir="asc"; }
          render();
        });
        th.addEventListener("contextmenu",ev=>openContextMenu(ev,key));
        th.addEventListener("dragstart",ev=>{
          dragKey=key; ev.dataTransfer.effectAllowed="move";
          setTimeout(()=>th.classList.add("dragging"),0);
        });
        th.addEventListener("dragend",()=>{
          dragKey=null;
          document.querySelectorAll("#thead-row th").forEach(el=>el.classList.remove("dragging","drag-over"));
        });
        th.addEventListener("dragover",ev=>{ ev.preventDefault(); ev.dataTransfer.dropEffect="move"; th.classList.add("drag-over"); });
        th.addEventListener("dragleave",()=>th.classList.remove("drag-over"));
        th.addEventListener("drop",ev=>{
          ev.preventDefault(); th.classList.remove("drag-over");
          if(!dragKey||dragKey===key) return;
          const si=columnOrder.indexOf(dragKey), di=columnOrder.indexOf(key);
          if(si<0||di<0) return;
          columnOrder.splice(si,1); columnOrder.splice(di,0,dragKey);
          saveColOrder(); render();
        });
      });
    }

    // ── Tbody render ──────────────────────────────────────────────────────────
    function render(){
      const out=filtered();
      document.getElementById("count").textContent=`${out.length} van ${rows.length} assets`;
      renderThead();
      const cols=orderedCols();
      document.getElementById("tbody").innerHTML=out.map(r=>{
        const cells=cols.map(col=>{
          if(col.wide) return `<td class="reasons">${col.render(r)}</td>`;
          if(col.num) return `<td class="num">${fmt(r[col.key])}</td>`;
          return `<td>${col.render?col.render(r):esc(r[col.key])}</td>`;
        }).join("");
        return `<tr class="${attr(r.primary_action)}">${cells}</tr>`;
      }).join("");
    }

    // ── Summary cards ─────────────────────────────────────────────────────────
    function renderSummary(){
      const byAction=summaryRows.filter(r=>r.group_type==="primary_action");
      const meta=metaRows[0]||{};
      const items=[
        {k:"Assets",v:meta.assets_total??rows.length,s:`scored ${meta.assets_scored??"-"} | insufficient ${meta.assets_insufficient_data??"-"}`},
        {k:"Timevalue rows",v:timevalueRows,s:"snapshot_optie_timevalue_live"},
        ...byAction.map(r=>({k:r.group_key,v:r.asset_count,s:`dir ${fmt(r.avg_direction_score)} | theta ${fmt(r.avg_theta_score)} | vol ${fmt(r.avg_volume_score)}`}))
      ];
      document.getElementById("summary").innerHTML=items.map(x=>`<div class="card"><div class="k">${esc(x.k)}</div><div class="v">${esc(x.v)}</div><div class="small">${esc(x.s)}</div></div>`).join("");
    }

    // ── Context menu ──────────────────────────────────────────────────────────
    function closeContextMenu(){ document.getElementById("contextMenu").style.display="none"; contextKey=null; }
    function openContextMenu(ev,key){
      ev.preventDefault(); contextKey=key;
      const col=COL_MAP[key]||{}, menu=document.getElementById("contextMenu");
      menu.querySelector('[data-action="sortAsc"]').disabled=!!col.noSort;
      menu.querySelector('[data-action="sortDesc"]').disabled=!!col.noSort;
      menu.querySelector('[data-action="chooseValues"]').disabled=!!col.noFilter;
      menu.style.display="block";
      const x=Math.min(ev.clientX,window.innerWidth-menu.offsetWidth-8);
      const y=Math.min(ev.clientY,window.innerHeight-menu.offsetHeight-8);
      menu.style.left=`${Math.max(8,x)}px`; menu.style.top=`${Math.max(8,y)}px`;
    }

    // ── Value filter dialog ───────────────────────────────────────────────────
    function openValueDialog(key){
      dialogKey=key; dialogSelection=new Set(columnFilters[key]||filterValuesForDialog());
      document.getElementById("filterTitle").textContent=`Filter: ${key}`;
      document.getElementById("filterSearch").value="";
      document.getElementById("filterModal").style.display="flex";
      renderFilterValues();
    }
    function closeValueDialog(){ document.getElementById("filterModal").style.display="none"; dialogKey=null; }
    function filterValuesForDialog(){
      if(!dialogKey) return [];
      return Array.from(new Set(rows.map(r=>String(r[dialogKey]??"")))).sort((a,b)=>a.localeCompare(b));
    }
    function renderFilterValues(){
      const q=document.getElementById("filterSearch").value.trim().toLowerCase();
      const values=filterValuesForDialog().filter(v=>!q||v.toLowerCase().includes(q));
      document.getElementById("filterAll").checked=values.length>0&&values.every(v=>dialogSelection.has(v));
      document.getElementById("filterValues").innerHTML=values.map(v=>
        `<label class="value-row"><input type="checkbox" class="filter-value" value="${esc(v)}" ${dialogSelection.has(v)?"checked":""}> ${esc(v||"(leeg)")}</label>`
      ).join("");
      document.querySelectorAll(".filter-value").forEach(cb=>cb.addEventListener("change",e=>{
        if(e.target.checked) dialogSelection.add(e.target.value); else dialogSelection.delete(e.target.value);
        const vis=Array.from(document.querySelectorAll(".filter-value"));
        document.getElementById("filterAll").checked=vis.length>0&&vis.every(i=>i.checked);
      }));
    }
    function applyDialogFilter(){
      if(!dialogKey) return;
      const all=filterValuesForDialog(), checked=[...dialogSelection];
      if(checked.length===all.length) delete columnFilters[dialogKey];
      else columnFilters[dialogKey]=new Set(checked);
      closeValueDialog(); render();
    }

    // ── Data entry point ──────────────────────────────────────────────────────
    function renderData(payload){
      rows=payload.live||[]; summaryRows=payload.summary||[]; metaRows=payload.meta||[]; timevalueRows=payload.timevalue_rows||0;
      fill("action",unique("primary_action")); fill("role",unique("indicator_role")); fill("mode",unique("asset_fase")); fill("quality",unique("data_quality")); fill("secondary",unique("secondary_action"));
      renderSummary(); render();
    }

    // ── Static event wiring ───────────────────────────────────────────────────
    ["action","role","mode","quality","secondary"].forEach(id=>document.getElementById(id).addEventListener("change",e=>{ state[id]=e.target.value; render(); }));
    document.getElementById("q").addEventListener("input",e=>{ state.q=e.target.value; render(); });
    document.getElementById("resetColsBtn").addEventListener("click",resetColOrder);
    document.addEventListener("click",ev=>{ if(!ev.target.closest("#contextMenu")) closeContextMenu(); });
    document.getElementById("contextMenu").addEventListener("click",ev=>{
      const action=ev.target.dataset.action; if(!action||!contextKey) return;
      const col=COL_MAP[contextKey]||{};
      if(action==="sortAsc"&&!col.noSort){ state.sortKey=contextKey; state.sortDir="asc"; render(); }
      if(action==="sortDesc"&&!col.noSort){ state.sortKey=contextKey; state.sortDir="desc"; render(); }
      if(action==="clearFilter"){ delete columnFilters[contextKey]; render(); }
      if(action==="chooseValues"&&!col.noFilter) openValueDialog(contextKey);
      closeContextMenu();
    });
    document.getElementById("filterSearch").addEventListener("input",renderFilterValues);
    document.getElementById("filterAll").addEventListener("change",e=>{
      document.querySelectorAll(".filter-value").forEach(cb=>{ cb.checked=e.target.checked; if(e.target.checked) dialogSelection.add(cb.value); else dialogSelection.delete(cb.value); });
    });
    document.getElementById("filterOk").addEventListener("click",applyDialogFilter);
    document.getElementById("filterClear").addEventListener("click",()=>{ if(dialogKey) delete columnFilters[dialogKey]; closeValueDialog(); render(); });
    document.getElementById("filterCancel").addEventListener("click",closeValueDialog);
    document.getElementById("filterClose").addEventListener("click",closeValueDialog);
    document.getElementById("filterModal").addEventListener("click",ev=>{ if(ev.target.id==="filterModal") closeValueDialog(); });
    window.renderData=renderData;
    connectQtBridge();
    renderData({live:[], summary:[], meta:[], timevalue_rows:0});
  </script>
</body>
</html>
"""
        return html.replace("__INITIAL_COLUMN_ORDER_JSON__", initial_column_order_json)

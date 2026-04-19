from __future__ import annotations

import json

import polars as pl
from PySide6.QtCore import Slot
from PySide6.QtWidgets import QDialog, QLabel, QSizePolicy, QVBoxLayout, QWidget

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:
    QWebEngineView = None

_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;font-size:12px;display:flex;flex-direction:column;height:100vh;overflow:hidden;background:#f5f5f5}

/* ── Top bar: grouping selector ── */
#top-bar{
  display:flex;align-items:center;gap:6px;padding:6px 10px;
  background:#fff;border-bottom:1px solid #ddd;flex-shrink:0
}
#top-bar span{font-size:12px;color:#666;white-space:nowrap}
.gb{
  font-size:12px;padding:3px 12px;border:1px solid #bbb;
  border-radius:3px;cursor:pointer;background:#f0f0f0;white-space:nowrap
}
.gb:hover{background:#e4e4e4}
.gb.active{background:#4285F4;color:#fff;border-color:#3367d6}

/* ── Body row: sidebar + chart ── */
#body-row{display:flex;flex:1;overflow:hidden}

/* ── Sidebar ── */
#sidebar{
  width:195px;min-width:195px;
  overflow-y:auto;overflow-x:hidden;
  padding:8px 8px 16px;
  background:#fff;border-right:1px solid #ddd;
}
/* custom scrollbar */
#sidebar::-webkit-scrollbar{width:6px}
#sidebar::-webkit-scrollbar-track{background:#f0f0f0}
#sidebar::-webkit-scrollbar-thumb{background:#bbb;border-radius:3px}
#sidebar::-webkit-scrollbar-thumb:hover{background:#999}

.fg{margin-bottom:10px}
.fg h3{font-size:12px;font-weight:600;margin-bottom:3px;color:#333}
.tog{display:flex;gap:4px;margin-bottom:4px}
.tog button{
  flex:1;font-size:11px;padding:2px 4px;cursor:pointer;
  border:1px solid #bbb;border-radius:3px;background:#f0f0f0
}
.tog button:hover{background:#e0e0e0}
.cb-item{
  display:flex;align-items:center;gap:5px;
  padding:2px 0;cursor:pointer;user-select:none;line-height:1.3
}
.cb-item input{margin:0;cursor:pointer;flex-shrink:0}

/* ── Chart area ── */
#main{flex:1;display:flex;flex-direction:column;overflow:hidden;padding:6px}
#chart-wrap{flex:1;position:relative;overflow:hidden}
svg{display:block}
#no-data{
  position:absolute;top:50%;left:50%;
  transform:translate(-50%,-50%);color:#aaa;font-size:14px
}

/* ── Tooltip ── */
#tip{
  position:fixed;background:rgba(0,0,0,0.78);color:#fff;
  padding:4px 9px;border-radius:4px;font-size:12px;
  pointer-events:none;display:none;z-index:999;white-space:nowrap
}
</style>
</head>
<body>

<!-- Grouping selector -->
<div id="top-bar">
  <span>Groeperen op:</span>
  <button class="gb active" data-gb="broker"  onclick="setGroupBy('broker')">Broker</button>
  <button class="gb"        data-gb="asset"   onclick="setGroupBy('asset')">Asset</button>
  <button class="gb"        data-gb="regio"   onclick="setGroupBy('regio')">Regio</button>
  <button class="gb"        data-gb="sector"  onclick="setGroupBy('sector')">Sector</button>
  <button class="gb"        data-gb="cat"     onclick="setGroupBy('cat')">Categorie</button>
</div>

<!-- Main body -->
<div id="body-row">

  <!-- Scrollable sidebar -->
  <div id="sidebar">
    <div class="fg">
      <h3>Broker</h3>
      <div class="tog">
        <button onclick="selAll('broker','broker')">Alles</button>
        <button onclick="selNone('broker')">Niets</button>
      </div>
      <div id="items-broker"></div>
    </div>
    <div class="fg">
      <h3>Sector</h3>
      <div class="tog">
        <button onclick="selAll('sector','sector')">Alles</button>
        <button onclick="selNone('sector')">Niets</button>
      </div>
      <div id="items-sector"></div>
    </div>
    <div class="fg">
      <h3>Regio</h3>
      <div class="tog">
        <button onclick="selAll('regio','regio')">Alles</button>
        <button onclick="selNone('regio')">Niets</button>
      </div>
      <div id="items-regio"></div>
    </div>
    <div class="fg">
      <h3>Categorie</h3>
      <div class="tog">
        <button onclick="selAll('cat','value_grow')">Alles</button>
        <button onclick="selNone('cat')">Niets</button>
      </div>
      <div id="items-cat"></div>
    </div>
    <div class="fg">
      <h3>Asset</h3>
      <div class="tog">
        <button onclick="selAll('asset','asset')">Alles</button>
        <button onclick="selNone('asset')">Niets</button>
      </div>
      <div id="items-asset"></div>
    </div>
  </div>

  <!-- Chart -->
  <div id="main">
    <div id="chart-wrap">
      <svg id="chart"></svg>
      <div id="no-data">Geen data</div>
    </div>
  </div>

</div>
<div id="tip"></div>

<script>
const COLORS=["#4285F4","#EA4335","#34A853","#FBBC05","#673AB7","#00ACC1",
               "#FF9800","#E91E63","#795548","#607D8B","#009688","#8BC34A"];

let _data=[];
let _groupBy='broker';  // active grouping dimension

// stateKey → dataKey in row object
const _DIM={broker:'broker',asset:'asset',regio:'regio',sector:'sector',cat:'value_grow'};
const _sel={broker:new Set(),sector:new Set(),regio:new Set(),cat:new Set(),asset:new Set()};

// ── Entry point called from Python ──────────────────────────────────
window.init=function(data){
  _data=Array.isArray(data)?data:[];
  buildAllFilters();
  redraw();
};

// ── Filter building ─────────────────────────────────────────────────
function buildAllFilters(){
  buildGroup('broker','broker','items-broker');
  buildGroup('sector','sector','items-sector');
  buildGroup('regio','regio','items-regio');
  buildGroup('cat','value_grow','items-cat');
  buildGroup('asset','asset','items-asset');
}

function buildGroup(sk,dk,cid){
  const vals=uniq(_data.map(d=>d[dk])).sort((a,b)=>a.localeCompare(b));
  _sel[sk]=new Set(vals);
  const c=document.getElementById(cid);
  c.innerHTML='';
  vals.forEach(v=>{
    const lbl=document.createElement('label');
    lbl.className='cb-item';
    const cb=document.createElement('input');
    cb.type='checkbox';cb.checked=true;
    cb.dataset.key=sk;cb.dataset.val=v;
    cb.onchange=()=>{cb.checked?_sel[sk].add(v):_sel[sk].delete(v);redraw();};
    lbl.appendChild(cb);
    const txt=document.createTextNode('\u00a0'+v);
    lbl.appendChild(txt);
    c.appendChild(lbl);
  });
}

function selAll(sk,dk){
  _sel[sk]=new Set(uniq(_data.map(d=>d[dk])));
  document.querySelectorAll(`input[data-key="${sk}"]`).forEach(cb=>cb.checked=true);
  redraw();
}
function selNone(sk){
  _sel[sk].clear();
  document.querySelectorAll(`input[data-key="${sk}"]`).forEach(cb=>cb.checked=false);
  redraw();
}
function uniq(arr){return[...(new Set(arr.filter(v=>v&&v!==''&&v!=='null'&&v!=='None')))];}

// ── Grouping selector ───────────────────────────────────────────────
function setGroupBy(gb){
  _groupBy=gb;
  document.querySelectorAll('.gb').forEach(b=>b.classList.toggle('active',b.dataset.gb===gb));
  redraw();
}

// ── Data filtering + pivoting ───────────────────────────────────────
function filtered(){
  return _data.filter(d=>
    (!_sel.broker.size||_sel.broker.has(d.broker))&&
    (!_sel.sector.size||_sel.sector.has(d.sector))&&
    (!_sel.regio.size ||_sel.regio.has(d.regio)) &&
    (!_sel.cat.size   ||_sel.cat.has(d.value_grow))&&
    (!_sel.asset.size ||_sel.asset.has(d.asset))
  );
}

function redraw(){
  const data=filtered();
  const dimField=_DIM[_groupBy]||'broker';
  const pivot={};const expSet=new Set();const dimSet=new Set();

  data.forEach(d=>{
    if(!d.exp)return;
    const dv=d[dimField];if(!dv)return;
    expSet.add(d.exp);dimSet.add(dv);
    if(!pivot[d.exp])pivot[d.exp]={};
    pivot[d.exp][dv]=(pivot[d.exp][dv]||0)+(d.time_total||0);
  });

  const exps=[...expSet].sort();
  const dims=[...dimSet].sort((a,b)=>a.localeCompare(b));
  const nd=document.getElementById('no-data');
  if(!exps.length||!dims.length){
    nd.style.display='block';
    document.getElementById('chart').innerHTML='';
    return;
  }
  nd.style.display='none';
  drawChart(exps,dims,pivot);
}

// ── SVG chart ───────────────────────────────────────────────────────
function drawChart(exps,dims,pivot){
  const wrap=document.getElementById('chart-wrap');
  const W=wrap.clientWidth,H=wrap.clientHeight;
  const m={top:16,right:Math.min(180,dims.length*90+20),bottom:74,left:80};
  const cw=W-m.left-m.right,ch=H-m.top-m.bottom;
  if(cw<20||ch<20)return;

  const totals=exps.map(exp=>dims.reduce((s,d)=>s+(pivot[exp]?.[d]||0),0));
  const maxV=Math.max(...totals,1);
  const barW=Math.max(6,Math.min(cw/exps.length*0.68,52));
  const step=cw/exps.length;

  const svg=document.getElementById('chart');
  svg.setAttribute('width',W);svg.setAttribute('height',H);
  svg.innerHTML='';

  const g=se('g',{transform:`translate(${m.left},${m.top})`});
  svg.appendChild(g);

  // y-grid + labels
  for(let i=0;i<=5;i++){
    const v=maxV*i/5,y=ch*(1-i/5);
    g.appendChild(se('line',{x1:0,y1:y,x2:cw,y2:y,stroke:'#e0e0e0','stroke-width':1}));
    const t=se('text',{x:-6,y:y+4,'text-anchor':'end','font-size':11,fill:'#555'});
    t.textContent=fmt(v);g.appendChild(t);
  }

  // Bars
  exps.forEach((exp,xi)=>{
    const cx=xi*step+step/2;let cum=0;
    dims.forEach((dim,di)=>{
      const v=pivot[exp]?.[dim]||0;if(!v)return;
      const bh=(v/maxV)*ch,by=ch-(cum+v)/maxV*ch;
      const r=se('rect',{x:cx-barW/2,y:by,width:barW,height:bh,
        fill:COLORS[di%COLORS.length],stroke:'white','stroke-width':0.5,rx:1});
      const tip=`${dim}: ${fmt(v)}`;
      r.addEventListener('mouseenter',e=>showTip(e,tip));
      r.addEventListener('mousemove',moveTip);
      r.addEventListener('mouseleave',hideTip);
      g.appendChild(r);cum+=v;
    });
    // rotated x-label
    const lx=cx,ly=ch+13;
    const t=se('text',{x:lx,y:ly,'text-anchor':'end',
      transform:`rotate(-40,${lx},${ly})`,'font-size':10,fill:'#333'});
    t.textContent=exp;g.appendChild(t);
  });

  // Axes
  g.appendChild(se('line',{x1:0,y1:0,x2:0,y2:ch,stroke:'#999','stroke-width':1}));
  g.appendChild(se('line',{x1:0,y1:ch,x2:cw,y2:ch,stroke:'#999','stroke-width':1}));

  // y-axis title
  const yt=se('text',{'text-anchor':'middle',
    transform:`translate(-56,${ch/2}) rotate(-90)`,'font-size':12,fill:'#666'});
  yt.textContent='Tijdswaarde (\u20ac)';g.appendChild(yt);

  // Legend
  dims.forEach((d,di)=>{
    const ly=di*20;
    g.appendChild(se('rect',{x:cw+10,y:ly,width:13,height:13,
      fill:COLORS[di%COLORS.length],rx:2}));
    const t=se('text',{x:cw+27,y:ly+10,'font-size':12,fill:'#333'});
    t.textContent=d;g.appendChild(t);
  });
}

function se(tag,attrs){
  const e=document.createElementNS("http://www.w3.org/2000/svg",tag);
  Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));return e;
}
function fmt(v){
  return new Intl.NumberFormat('nl-NL',{maximumFractionDigits:0}).format(v);
}
function showTip(e,txt){
  const t=document.getElementById('tip');
  t.textContent=txt;t.style.display='block';moveTip(e);
}
function moveTip(e){
  const t=document.getElementById('tip');
  t.style.left=(e.clientX+12)+'px';t.style.top=(e.clientY-28)+'px';
}
function hideTip(){document.getElementById('tip').style.display='none';}
window.addEventListener('resize',redraw);
</script>
</body>
</html>
"""


class TimeValueChartWebDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Theta Analyse")
        self.resize(1200, 700)
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if QWebEngineView is None:
            layout.addWidget(QLabel("QtWebEngine niet beschikbaar."))
            self._web = None
            return

        self._web = QWebEngineView()
        self._web.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._web)
        self._loaded = False
        self._pending_refresh = False
        self._web.loadFinished.connect(self._on_loaded)
        self._web.setHtml(_HTML)

        signals.snapshotUpdated.connect(self._on_snapshot_updated)

    @Slot(str)
    def _on_snapshot_updated(self, key: str) -> None:
        if key in ("snapshot_optie_timevalue_live", "repository_snapshot_asset_rollup_data"):
            self._push_data()

    def _on_loaded(self, ok: bool) -> None:
        self._loaded = bool(ok)
        if self._loaded and self._pending_refresh:
            self._pending_refresh = False
            self._push_data()

    def refresh(self) -> None:
        if not self._loaded:
            self._pending_refresh = True
        else:
            self._push_data()

    def _build_rows(self) -> list[dict]:
        tv = SNAPSHOT_STORE.snapshot_optie_timevalue_live
        if tv is None or tv.is_empty():
            return []
        asset_data = SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
        if asset_data is not None and not asset_data.is_empty():
            tv = tv.join(
                asset_data.select(["asset_rollup", "sector", "regio", "value_grow"]),
                left_on="asset",
                right_on="asset_rollup",
                how="left",
            )
        else:
            tv = tv.with_columns([
                pl.lit(None).cast(pl.Utf8).alias("sector"),
                pl.lit(None).cast(pl.Utf8).alias("regio"),
                pl.lit(None).cast(pl.Utf8).alias("value_grow"),
            ])

        rows = []
        for r in tv.select(["broker", "asset", "exp", "time_total",
                             "sector", "regio", "value_grow"]).to_dicts():
            exp = r.get("exp")
            rows.append({
                "broker":     r.get("broker") or "",
                "asset":      r.get("asset") or "",
                "exp":        str(exp) if exp is not None else "",
                "time_total": float(r.get("time_total") or 0),
                "sector":     r.get("sector") or "",
                "regio":      r.get("regio") or "",
                "value_grow": r.get("value_grow") or "",
            })
        return rows

    def _push_data(self) -> None:
        if self._web is None or not self._loaded:
            return
        payload = json.dumps(self._build_rows(), ensure_ascii=False)
        self._web.page().runJavaScript(f"if(window.init){{window.init({payload});}}")

    def closeEvent(self, event):
        event.ignore()
        self.hide()

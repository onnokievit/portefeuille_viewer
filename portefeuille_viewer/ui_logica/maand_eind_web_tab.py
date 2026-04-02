from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import polars as pl
from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover
    QWebChannel = None
    QWebEngineView = None


def _coerce_to_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except Exception:
            continue
    return None


def _iter_daily_dates(start_date: date, end_date: date) -> list[date]:
    out: list[date] = []
    current = start_date
    while current <= end_date:
        out.append(current)
        current += timedelta(days=1)
    return out


def _iter_friday_dates(start_date: date, end_date: date) -> list[date]:
    out: list[date] = []
    current = start_date
    while current.weekday() != 4:
        current += timedelta(days=1)
    while current <= end_date:
        out.append(current)
        current += timedelta(days=7)
    return out


def _third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    offset = (4 - first.weekday()) % 7
    return first + timedelta(days=offset + 14)


def _iter_third_friday_dates(start_date: date, end_date: date) -> list[date]:
    out: list[date] = []
    year = start_date.year
    month = start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        candidate = _third_friday(year, month)
        if start_date <= candidate <= end_date:
            out.append(candidate)
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return out


def _schedule_dates(start_date: date, end_date: date, mode: str) -> list[date]:
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    if mode == "daily":
        return _iter_daily_dates(start_date, end_date)
    if mode == "weekly_friday":
        return _iter_friday_dates(start_date, end_date)
    return _iter_third_friday_dates(start_date, end_date)


class MaandEindWebTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._js_ready = False
        self._is_active = False
        self._loaded_once = False
        self._pending_js_calls: list[tuple[str, object]] = []
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(150)
        self._render_timer.timeout.connect(self._publish_snapshot)
        self._start_date = date.today() - timedelta(days=365)
        self._end_date = date.today()
        self._frequency = "third_friday"
        self._filter_regio = ""
        self._filter_value_grow = ""
        self._filter_sector = ""

        layout = QVBoxLayout(self)
        if QWebEngineView is None:
            layout.addWidget(QLabel("QtWebEngine niet beschikbaar in deze runtime."))
            return
        self.web = QWebEngineView(self)
        layout.addWidget(self.web)
        if QWebChannel is not None:
            self.channel = QWebChannel(self.web.page())
            self.bridge = _MaandEindWebBridge(self)
            self.channel.registerObject("maandEindBridge", self.bridge)
            self.web.page().setWebChannel(self.channel)
        self.web.loadFinished.connect(self._on_web_loaded)
        self.web.setHtml(self._html_template())
        signals.snapshotUpdated.connect(self._on_snapshot_updated)
        signals.stateRebuildFinished.connect(self._on_state_rebuild_finished)
        signals.databaseChanged.connect(self._on_database_changed)

    def set_active(self, active: bool):
        self._is_active = bool(active)
        if not self._is_active:
            self._render_timer.stop()
            return
        if not self._js_ready:
            return
        self._publish_controls()
        self._publish_snapshot()

    def _on_web_loaded(self, ok: bool):
        self._js_ready = bool(ok)
        if not self._js_ready:
            return
        for func_name, payload in self._pending_js_calls:
            self._run_js(func_name, payload)
        self._pending_js_calls.clear()
        self._publish_controls()
        if self._is_active:
            self._publish_snapshot()

    def _on_snapshot_updated(self, snapshot_key: str):
        if self._is_active and snapshot_key in {
            "repository_snapshot_per_dag_asset_result_v2",
            "repository_snapshot_asset_rollup_data",
        }:
            self._publish_controls()
            self._schedule_publish()

    def _on_state_rebuild_finished(self, payload: dict | None):
        if self._is_active and (payload or {}).get("status") == "ok":
            self._schedule_publish()

    def _on_database_changed(self, _db_name: str):
        self._loaded_once = False
        if self._is_active:
            self._publish_controls()
            self._schedule_publish()

    def _schedule_publish(self):
        if not self._is_active or not self._js_ready:
            return
        if not self._render_timer.isActive():
            self._render_timer.start()

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

    @staticmethod
    def _json_default(value):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    def _metadata_df(self) -> pl.DataFrame:
        df_meta = getattr(SNAPSHOT_STORE, "repository_snapshot_asset_rollup_data", None)
        if df_meta is None or df_meta.is_empty() or "asset_rollup" not in df_meta.columns:
            return pl.DataFrame(
                schema={
                    "asset_rollup": pl.Utf8,
                    "regio": pl.Utf8,
                    "value_grow": pl.Utf8,
                    "sector": pl.Utf8,
                }
            )
        exprs = [
            pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("asset_rollup"),
            (pl.col("regio").cast(pl.Utf8, strict=False).fill_null("").alias("regio") if "regio" in df_meta.columns else pl.lit("").alias("regio")),
            (
                pl.col("value_grow").cast(pl.Utf8, strict=False).fill_null("").alias("value_grow")
                if "value_grow" in df_meta.columns
                else pl.lit("").alias("value_grow")
            ),
            (pl.col("sector").cast(pl.Utf8, strict=False).fill_null("").alias("sector") if "sector" in df_meta.columns else pl.lit("").alias("sector")),
        ]
        return (
            df_meta.with_columns(exprs)
            .select(["asset_rollup", "regio", "value_grow", "sector"])
            .unique(subset=["asset_rollup"], keep="first")
            .sort("asset_rollup")
        )

    def _publish_controls(self):
        meta_df = self._metadata_df()

        def _options(col: str) -> list[str]:
            if meta_df.is_empty() or col not in meta_df.columns:
                return []
            return sorted({str(v) for v in meta_df[col].to_list() if v is not None and str(v).strip()})

        self._call_js(
            "syncControls",
            {
                "start_date": self._start_date.isoformat(),
                "end_date": self._end_date.isoformat(),
                "frequency": self._frequency,
                "filter_regio": self._filter_regio,
                "filter_value_grow": self._filter_value_grow,
                "filter_sector": self._filter_sector,
                "regio_options": _options("regio"),
                "value_grow_options": _options("value_grow"),
                "sector_options": _options("sector"),
            },
        )

    def _build_matrix(self, df_source: pl.DataFrame, schedule: list[date]) -> pl.DataFrame:
        if not schedule or df_source is None or df_source.is_empty():
            return pl.DataFrame({"asset_rollup": []})
        if "datum" not in df_source.columns or "asset_rollup" not in df_source.columns or "totaal_v2" not in df_source.columns:
            return pl.DataFrame({"asset_rollup": []})

        meta_df = self._metadata_df()
        eurusd = float(get_settings().get_eurusd() or 1.0)
        work = (
            df_source.with_columns(
                [
                    pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("asset_rollup"),
                    pl.col("totaal_v2").cast(pl.Float64, strict=False).alias("waarde"),
                ]
            )
            .join(meta_df, on="asset_rollup", how="left")
            .with_columns(
                [
                    pl.col("regio").fill_null(""),
                    pl.col("value_grow").fill_null(""),
                    pl.col("sector").fill_null(""),
                    pl.when(pl.col("regio") == "US").then(pl.col("waarde") / eurusd).otherwise(pl.col("waarde")).alias("waarde"),
                ]
            )
            .filter(pl.col("datum").is_not_null() & (pl.col("datum") <= schedule[-1]))
        )
        if self._filter_regio:
            work = work.filter(pl.col("regio") == self._filter_regio)
        if self._filter_value_grow:
            work = work.filter(pl.col("value_grow") == self._filter_value_grow)
        if self._filter_sector:
            work = work.filter(pl.col("sector") == self._filter_sector)
        work = work.select(["datum", "asset_rollup", "value_grow", "sector", "regio", "waarde"]).sort(["asset_rollup", "datum"])
        if work.is_empty():
            return pl.DataFrame({"asset_rollup": []})

        assets = (
            work.select(["asset_rollup", "value_grow", "sector", "regio"])
            .unique()
            .sort("asset_rollup")
            .with_columns(pl.lit(1).alias("_k"))
        )
        schedule_df = (
            pl.DataFrame({"datum": schedule})
            .with_columns(pl.lit(1).alias("_k"))
            .join(assets, on="_k", how="inner")
            .drop("_k")
            .with_columns([pl.lit(None).cast(pl.Float64).alias("waarde"), pl.lit(1).alias("_is_schedule")])
        )
        combined = (
            pl.concat([work.with_columns(pl.lit(0).alias("_is_schedule")), schedule_df], how="diagonal_relaxed")
            .sort(["asset_rollup", "datum", "_is_schedule"])
            .with_columns(pl.col("waarde").fill_null(strategy="forward").over("asset_rollup"))
            .filter(pl.col("_is_schedule") == 1)
            .sort(["asset_rollup", "datum"])
        )
        if combined.is_empty():
            return pl.DataFrame({"asset_rollup": []})

        pivot = combined.pivot(index=["asset_rollup", "value_grow", "sector", "regio"], on="datum", values="waarde")
        rename_map = {}
        for col in pivot.columns:
            if col in {"asset_rollup", "value_grow", "sector", "regio"}:
                continue
            dt = _coerce_to_date(col)
            if dt is not None:
                rename_map[col] = dt.strftime("%d-%m-%y")
        if rename_map:
            pivot = pivot.rename(rename_map)
        first_cols = ["asset_rollup", "value_grow", "sector", "regio"]
        date_cols = [c for c in pivot.columns if c not in first_cols]
        return pivot.select(first_cols + date_cols).sort("asset_rollup")

    def _publish_snapshot(self):
        if not self._is_active or not self._js_ready:
            return
        schedule = _schedule_dates(self._start_date, self._end_date, self._frequency)
        df_source = getattr(SNAPSHOT_STORE, "repository_snapshot_per_dag_asset_result_v2", None)
        matrix = self._build_matrix(df_source, schedule)
        rows = matrix.to_dicts() if hasattr(matrix, "to_dicts") else []
        cols = list(matrix.columns)
        self._loaded_once = True
        self._call_js(
            "renderSnapshot",
            {
                "rows": rows,
                "cols": cols,
                "meta": {
                    "asset_count": int(matrix.height),
                    "moment_count": max(int(matrix.width) - 4, 0),
                    "frequency": self._frequency,
                    "loaded_once": self._loaded_once,
                },
            },
        )

    def _set_start_date(self, value: str):
        parsed = _coerce_to_date(value)
        if parsed is None:
            return
        self._start_date = parsed
        self._schedule_publish()

    def _set_end_date(self, value: str):
        parsed = _coerce_to_date(value)
        if parsed is None:
            return
        self._end_date = parsed
        self._schedule_publish()

    def _set_frequency(self, value: str):
        mode = str(value or "").strip()
        if mode not in {"daily", "weekly_friday", "third_friday"}:
            return
        self._frequency = mode
        self._schedule_publish()

    def _set_filter_regio(self, value: str):
        self._filter_regio = str(value or "").strip()
        self._schedule_publish()

    def _set_filter_value_grow(self, value: str):
        self._filter_value_grow = str(value or "").strip()
        self._schedule_publish()

    def _set_filter_sector(self, value: str):
        self._filter_sector = str(value or "").strip()
        self._schedule_publish()

    def _html_template(self) -> str:
        return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
      :root{
        --bg:#f4f1e8;
        --panel:#fbfaf6;
        --line:#d4c8af;
        --line-strong:#a38f67;
        --head:#d9ccb1;
        --head-2:#eee4d1;
        --text:#2b261d;
        --muted:#6c6557;
        --pos-bg:#d8efcf;
        --pos-fg:#14611f;
        --neg-bg:#f5cfcf;
        --neg-fg:#9d1717;
      }
      *{ box-sizing:border-box; }
      body{ margin:0; padding:14px; background:linear-gradient(180deg,#efe8d8 0%,#f7f4ec 100%); color:var(--text); font-family:Segoe UI, Arial, sans-serif; }
      .shell{ display:flex; flex-direction:column; gap:10px; }
      .toolbar{ display:flex; gap:10px; align-items:end; flex-wrap:wrap; padding:12px; border:1px solid var(--line); border-radius:12px; background:rgba(251,250,246,.92); box-shadow:0 10px 24px rgba(73,57,22,.08); }
      .field{ display:flex; flex-direction:column; gap:4px; min-width:150px; }
      .field label{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); font-weight:700; }
      .field input,.field select{ height:34px; padding:0 10px; border:1px solid var(--line); border-radius:8px; background:#fffdf8; color:var(--text); }
      .field input.filter{ min-width:220px; }
      .toolbar button{ height:34px; padding:0 14px; border:1px solid var(--line-strong); border-radius:8px; background:#8d7651; color:#fffdf8; cursor:pointer; font-weight:700; }
      .meta{ padding:0 2px; font-size:12px; color:var(--muted); }
      .table-wrap{ border:1px solid var(--line); border-radius:14px; overflow:auto; background:var(--panel); max-height:78vh; box-shadow:0 12px 30px rgba(73,57,22,.08); }
      table{ border-collapse:separate; border-spacing:0; min-width:max-content; width:max-content; font-size:12px; }
      thead th{ position:sticky; top:0; z-index:3; padding:7px 10px; background:var(--head); border-bottom:1px solid var(--line-strong); border-right:1px solid var(--line); white-space:nowrap; text-align:right; font-weight:700; font-variant-numeric:tabular-nums; cursor:pointer; user-select:none; }
      thead th.asset{ left:0; z-index:4; text-align:left; background:var(--head-2); min-width:160px; }
      thead th.meta-col{ text-align:left; min-width:120px; }
      thead th[data-sort="asc"]::after{ content:" ↑"; }
      thead th[data-sort="desc"]::after{ content:" ↓"; }
      tbody td{ padding:5px 10px; border-right:1px solid #e5dcc9; border-bottom:1px solid #ece4d4; white-space:nowrap; text-align:right; font-variant-numeric:tabular-nums; background:#fbfaf6; }
      tbody td.asset{ position:sticky; left:0; z-index:2; text-align:left; font-weight:700; background:#f3ecdd; min-width:160px; }
      tbody td.meta-col{ text-align:left; }
      tbody tr:nth-child(even) td{ background:#f8f4eb; }
      tbody tr:nth-child(even) td.asset{ background:#eee5d3; }
      tbody tr.total-row td{ background:#e4d6b8 !important; font-weight:800; border-top:2px solid var(--line-strong); }
      tbody tr.total-row td.asset{ background:#d9c8a3 !important; }
      td.pos{ background:var(--pos-bg) !important; color:var(--pos-fg); font-weight:700; }
      td.neg{ background:var(--neg-bg) !important; color:var(--neg-fg); font-weight:700; }
      td.empty{ color:#b3a995; }
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="toolbar">
        <div class="field">
          <label>Start date</label>
          <input id="start_date" type="date" />
        </div>
        <div class="field">
          <label>Eind date</label>
          <input id="end_date" type="date" />
        </div>
        <div class="field">
          <label>Frequentie</label>
          <select id="frequency">
            <option value="third_friday">3e vrijdag maand</option>
            <option value="weekly_friday">Elke vrijdag</option>
            <option value="daily">Elke dag</option>
          </select>
        </div>
        <div class="field">
          <label>Regio</label>
          <select id="filter_regio"><option value="">Alle regio's</option></select>
        </div>
        <div class="field">
          <label>Value/Grow</label>
          <select id="filter_value_grow"><option value="">Alles</option></select>
        </div>
        <div class="field">
          <label>Sector</label>
          <select id="filter_sector"><option value="">Alle sectoren</option></select>
        </div>
        <div class="field">
          <label>Asset filter</label>
          <input id="asset_filter" class="filter" placeholder="Zoek asset_rollup" />
        </div>
        <button id="btn_refresh">Refresh</button>
      </div>
      <div class="meta" id="meta">Nog niet geladen.</div>
      <div class="table-wrap">
        <table id="tbl">
          <thead><tr id="thead-row"></tr></thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>
    </div>
    <script>
      const META_COLS = new Set(["asset_rollup","value_grow","sector","regio"]);
      const state = { cols: [], rows: [], filters: { asset: "" }, sort: { col: "asset_rollup", dir: "asc" }, bridge: null };
      function refillSelect(id, options, current, emptyLabel){
        const el=document.getElementById(id);
        if(!el) return;
        el.innerHTML = "";
        const base=document.createElement("option");
        base.value="";
        base.textContent=emptyLabel;
        el.appendChild(base);
        (options||[]).forEach(v=>{
          const opt=document.createElement("option");
          opt.value=String(v);
          opt.textContent=String(v);
          el.appendChild(opt);
        });
        el.value = current || "";
      }
      function fmt(v){
        if(v===null||v===undefined||v==="") return "";
        if(typeof v==="number" && Number.isFinite(v)) return Math.round(v).toString().replace(/\\B(?=(\\d{3})+(?!\\d))/g,".");
        return String(v);
      }
      function num(v){ return (typeof v==="number" && Number.isFinite(v)) ? v : null; }
      function cssFor(v){
        if(typeof v!=="number" || !Number.isFinite(v)) return "empty";
        if(v>0) return "pos";
        if(v<0) return "neg";
        return "";
      }
      function compareRows(a,b,col,dir){
        if(META_COLS.has(col)){
          const cmp = String(a[col]||"").localeCompare(String(b[col]||""));
          return dir==="asc" ? cmp : -cmp;
        }
        const av = num(a[col]);
        const bv = num(b[col]);
        if(av===null && bv===null) return 0;
        if(av===null) return 1;
        if(bv===null) return -1;
        const cmp = av-bv;
        return dir==="asc" ? cmp : -cmp;
      }
      function visibleRows(){
        const needle=(state.filters.asset||"").trim().toLowerCase();
        if(!needle) return state.rows;
        return state.rows.filter(r => String(r.asset_rollup||"").toLowerCase().includes(needle));
      }
      function buildTotalRow(rows){
        const out = { asset_rollup: "Totaal", value_grow: "", sector: "", regio: "" };
        for(const col of state.cols){
          if(META_COLS.has(col)) continue;
          let total = 0;
          let hasAny = false;
          for(const row of rows){
            const v = num(row[col]);
            if(v!==null){ total += v; hasAny = true; }
          }
          out[col] = hasAny ? total : null;
        }
        return out;
      }
      function headerLabel(col){
        if(col==="asset_rollup") return "Asset";
        if(col==="value_grow") return "Value/Grow";
        if(col==="sector") return "Sector";
        if(col==="regio") return "Regio";
        return col;
      }
      function renderHeader(){
        const tr=document.getElementById("thead-row");
        tr.innerHTML="";
        state.cols.forEach((col,idx)=>{
          const th=document.createElement("th");
          th.textContent=headerLabel(col);
          if(idx===0) th.className="asset";
          if(col!=="asset_rollup" && META_COLS.has(col)) th.classList.add("meta-col");
          if(col===state.sort.col) th.dataset.sort = state.sort.dir;
          th.onclick = ()=>{
            if(state.sort.col===col){
              state.sort.dir = state.sort.dir==="asc" ? "desc" : "asc";
            } else {
              state.sort.col = col;
              state.sort.dir = META_COLS.has(col) ? "asc" : "desc";
            }
            renderHeader();
            renderBody();
          };
          tr.appendChild(th);
        });
      }
      function renderBody(){
        const body=document.getElementById("tbody");
        body.innerHTML="";
        const rows=visibleRows().slice().sort((a,b)=>compareRows(a,b,state.sort.col,state.sort.dir));
        for(const row of rows){
          const tr=document.createElement("tr");
          state.cols.forEach((col,idx)=>{
            const td=document.createElement("td");
            const v=row[col];
            td.textContent=fmt(v);
            if(idx===0){
              td.className="asset";
            }else if(META_COLS.has(col)){
              td.classList.add("meta-col");
            }else{
              const cls=cssFor(v);
              if(cls) td.classList.add(cls);
            }
            if(v===null||v===undefined||v==="") td.classList.add("empty");
            tr.appendChild(td);
          });
          body.appendChild(tr);
        }
        if(rows.length){
          const totalRow = buildTotalRow(rows);
          const tr=document.createElement("tr");
          tr.className="total-row";
          state.cols.forEach((col,idx)=>{
            const td=document.createElement("td");
            const v=totalRow[col];
            td.textContent=fmt(v);
            if(idx===0){
              td.className="asset";
            }else if(META_COLS.has(col)){
              td.classList.add("meta-col");
            }else{
              const cls=cssFor(v);
              if(cls) td.classList.add(cls);
            }
            if(v===null||v===undefined||v==="") td.classList.add("empty");
            tr.appendChild(td);
          });
          body.appendChild(tr);
        }
      }
      function bindUi(){
        document.getElementById("asset_filter")?.addEventListener("input", (e)=>{ state.filters.asset=e.target.value||""; renderBody(); });
        document.getElementById("btn_refresh")?.addEventListener("click", ()=> state.bridge?.refresh?.());
        document.getElementById("start_date")?.addEventListener("change", (e)=> state.bridge?.setStartDate?.(e.target.value||""));
        document.getElementById("end_date")?.addEventListener("change", (e)=> state.bridge?.setEndDate?.(e.target.value||""));
        document.getElementById("frequency")?.addEventListener("change", (e)=> state.bridge?.setFrequency?.(e.target.value||""));
        document.getElementById("filter_regio")?.addEventListener("change", (e)=> state.bridge?.setFilterRegio?.(e.target.value||""));
        document.getElementById("filter_value_grow")?.addEventListener("change", (e)=> state.bridge?.setFilterValueGrow?.(e.target.value||""));
        document.getElementById("filter_sector")?.addEventListener("change", (e)=> state.bridge?.setFilterSector?.(e.target.value||""));
      }
      window.syncControls = function(payload){
        if(!payload) return;
        refillSelect("filter_regio", payload.regio_options || [], payload.filter_regio || "", "Alle regio's");
        refillSelect("filter_value_grow", payload.value_grow_options || [], payload.filter_value_grow || "", "Alles");
        refillSelect("filter_sector", payload.sector_options || [], payload.filter_sector || "", "Alle sectoren");
        const s=document.getElementById("start_date");
        const e=document.getElementById("end_date");
        const f=document.getElementById("frequency");
        if(s) s.value = payload.start_date || "";
        if(e) e.value = payload.end_date || "";
        if(f) f.value = payload.frequency || "third_friday";
      };
      window.renderSnapshot = function(payload){
        const rows=(payload&&payload.rows)?payload.rows:[];
        const cols=(payload&&payload.cols)?payload.cols:[];
        state.rows = rows;
        state.cols = cols;
        if(!state.cols.includes(state.sort.col)){
          state.sort = { col: "asset_rollup", dir: "asc" };
        }
        renderHeader();
        renderBody();
        const meta=(payload&&payload.meta)?payload.meta:{};
        const label = meta.frequency==="daily" ? "elke dag" : (meta.frequency==="weekly_friday" ? "elke vrijdag" : "3e vrijdag maand");
        document.getElementById("meta").textContent = `${meta.asset_count||0} assets | ${meta.moment_count||0} meetmomenten | bron: per_dag_asset_result_v2.totaal_v2 | US omgerekend via EURUSD | ${label}`;
      };
      if(window.qt && window.QWebChannel){
        new QWebChannel(qt.webChannelTransport, function(channel){
          state.bridge = channel.objects.maandEindBridge || null;
          bindUi();
        });
      } else {
        bindUi();
      }
    </script>
  </body>
</html>
"""


class _MaandEindWebBridge(QObject):
    def __init__(self, tab: MaandEindWebTab):
        super().__init__(tab)
        self._tab = tab

    @Slot(str)
    def setStartDate(self, value: str) -> None:
        self._tab._set_start_date(value)

    @Slot(str)
    def setEndDate(self, value: str) -> None:
        self._tab._set_end_date(value)

    @Slot(str)
    def setFrequency(self, value: str) -> None:
        self._tab._set_frequency(value)

    @Slot(str)
    def setFilterRegio(self, value: str) -> None:
        self._tab._set_filter_regio(value)

    @Slot(str)
    def setFilterValueGrow(self, value: str) -> None:
        self._tab._set_filter_value_grow(value)

    @Slot(str)
    def setFilterSector(self, value: str) -> None:
        self._tab._set_filter_sector(value)

    @Slot()
    def refresh(self) -> None:
        self._tab._publish_snapshot()

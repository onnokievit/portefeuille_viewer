from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

from portefeuille_viewer.services.asset_indicator_change_service import build_asset_indicator_changes

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover
    QWebEngineView = None


class AssetIndicatorChangesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._js_ready = False
        self._is_active = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(200)
        self._render_timer.timeout.connect(self.refresh_view)

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.btn_refresh = QPushButton("Verversen", self)
        self.days_spin = QSpinBox(self)
        self.days_spin.setRange(1, 120)
        self.days_spin.setValue(14)
        self.days_spin.setSuffix(" dagen")
        self.status_label = QLabel("Nog niet geladen.", self)
        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(QLabel("Venster:", self))
        toolbar.addWidget(self.days_spin)
        toolbar.addWidget(self.status_label, 1)
        layout.addLayout(toolbar)

        if QWebEngineView is None:
            layout.addWidget(QLabel("QtWebEngine niet beschikbaar in deze runtime.", self))
            return

        self.web = QWebEngineView(self)
        layout.addWidget(self.web, 1)
        self.web.loadFinished.connect(self._on_web_loaded)
        self.web.setHtml(self._html_template())
        self.btn_refresh.clicked.connect(self.refresh_view)
        self.days_spin.valueChanged.connect(self._schedule_refresh)

    def set_active(self, active: bool):
        self._is_active = bool(active)
        if self._is_active and self._js_ready:
            self.refresh_view()
        elif not self._is_active:
            self._render_timer.stop()

    def _on_web_loaded(self, ok: bool):
        self._js_ready = bool(ok)
        if self._js_ready:
            self.refresh_view()

    def _schedule_refresh(self):
        if self._is_active and self._js_ready and not self._render_timer.isActive():
            self._render_timer.start()

    def refresh_view(self):
        if not self._js_ready or not hasattr(self, "web"):
            return
        days = int(self.days_spin.value())
        self.status_label.setText("Wijzigingen laden...")
        payload = build_asset_indicator_changes(days=days)
        if payload.error:
            self.status_label.setText(f"Fout: {payload.error}")
        else:
            self.status_label.setText(
                f"{len(payload.changes)} assets | {payload.rows_loaded} history rows | {payload.generated_at}"
            )
        self._run_js("renderData", payload.__dict__)

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

    def _html_template(self) -> str:
        return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <style>
    html,body{height:100%;margin:0;overflow:hidden;font-family:Segoe UI,Arial,sans-serif;background:#f5f6f7;color:#1d232b;font-size:13px;}
    *{box-sizing:border-box;}
    .wrap{height:100%;padding:10px;display:flex;flex-direction:column;gap:8px;}
    .compare-banner{background:#fff;border:1px solid #d8dde3;border-radius:6px;padding:8px 10px;display:flex;gap:18px;align-items:center;}
    .compare-banner b{font-size:14px;}
    .summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;}
    .card{background:#fff;border:1px solid #d8dde3;border-radius:6px;padding:8px 10px;}
    .card .k{font-size:12px;color:#5d6673;}
    .card .v{font-size:19px;font-weight:650;}
    .toolbar{background:#fff;border:1px solid #d8dde3;border-radius:6px;padding:8px;display:grid;grid-template-columns:1.4fr repeat(5,minmax(140px,190px)) minmax(120px,150px);gap:8px;align-items:end;}
    label{display:block;color:#5d6673;font-size:12px;margin-bottom:3px;}
    input,select{width:100%;height:28px;border:1px solid #bfc7d1;border-radius:4px;background:#fff;padding:3px 7px;font:inherit;}
    .count{font-size:12px;color:#5d6673;}
    .table-wrap{flex:1;overflow:auto;border:1px solid #d8dde3;background:#fff;}
    table{width:100%;border-collapse:collapse;}
    th,td{border-bottom:1px solid #e5e9ee;border-right:1px solid #eef1f4;padding:5px 7px;white-space:nowrap;vertical-align:top;}
    th{position:sticky;top:0;background:#eef2f6;text-align:left;z-index:1;}
    td:nth-child(4),td:nth-child(5),td:nth-child(6),td:nth-child(7){white-space:normal;min-width:210px;overflow-wrap:anywhere;}
    td:nth-child(7){min-width:300px;}
    td.num{text-align:right;font-variant-numeric:tabular-nums;}
    td.reasons{white-space:normal;min-width:360px;max-width:680px;}
    .pill{display:inline-block;border:1px solid #ccd3dc;border-radius:999px;background:#fff;padding:2px 7px;}
    .label_sterk_verbeterd,.label_verbeterd{background:#dcfce7;border-color:#86efac;color:#14532d;}
    .label_theta_kans_omhoog{background:#e0f7f2;border-color:#5eead4;color:#134e4a;}
    .label_risico_omhoog{background:#fef3c7;border-color:#facc15;color:#713f12;}
    .label_verslechterd,.label_sterk_verslechterd{background:#fee2e2;border-color:#fca5a5;color:#7f1d1d;}
    .label_stabiel{background:#f1f5f9;color:#334155;}
    tr.sterk_verslechterd,tr.verslechterd{background:#fff1f1;}
    tr.risico_omhoog{background:#fff8df;}
    tr.sterk_verbeterd,tr.verbeterd{background:#effaf2;}
    tr.theta_kans_omhoog{background:#ecfffb;}
    .arrow{color:#64748b;margin:0 3px;}
    .small{font-size:12px;color:#64748b;}
    .error{display:none;color:#8a1f1f;background:#ffe0e0;border:1px solid #efb3b3;padding:8px;border-radius:4px;}
    .timeline{display:none;background:#fff;border:1px solid #d8dde3;border-radius:6px;padding:8px 10px;}
    .timeline-title{font-weight:650;margin-bottom:6px;}
    .timeline-row{display:grid;grid-template-columns:96px 1fr 1fr 1fr 70px 70px;gap:8px;border-top:1px solid #eef1f4;padding:5px 0;align-items:start;}
    .timeline-head{color:#5d6673;font-size:12px;border-top:0;}
    .pair{display:grid;grid-template-columns:minmax(88px,1fr) 18px minmax(88px,1fr);gap:4px;align-items:start;}
    .pair .old,.pair .new,.pair-single{min-width:0;white-space:normal;overflow-wrap:anywhere;word-break:break-word;}
    .date{display:block;color:#64748b;font-size:11px;margin-top:2px;line-height:1.2;}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="compare-banner" id="compareBanner"></div>
    <div class="summary" id="summary"></div>
    <div class="toolbar">
      <div><label>Zoek</label><input id="q" placeholder="Asset, fase, actie, reden..."></div>
      <div><label>Change</label><select id="label"><option value="__ALL__">Alle</option></select></div>
      <div><label>Asset fase</label><select id="fase"><option value="__ALL__">Alle</option></select></div>
      <div><label>Action</label><select id="action"><option value="__ALL__">Alle</option></select></div>
      <div><label>Rol</label><select id="role"><option value="__ALL__">Alle</option></select></div>
      <div><label>Asset tijdlijn</label><select id="asset"><option value="__ALL__">Geen</option></select></div>
      <div><label>Min impact</label><input id="impact" type="number" value="0" step="5"></div>
    </div>
    <div class="timeline" id="timeline"></div>
    <div class="error" id="error"></div>
    <div class="count" id="count"></div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Asset</th>
            <th>Change</th>
            <th>Impact</th>
            <th>Asset fase</th>
            <th>Trend fase</th>
            <th>Action</th>
            <th>Secondary</th>
            <th>Rol</th>
            <th>Dir</th>
            <th>Dir Δ</th>
            <th>Theta</th>
            <th>Theta Δ</th>
            <th>Conf</th>
            <th>Redenen</th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </div>
  <script>
    let payload = {changes:[], summary:{}};
    let rows = [];
    const els = {
      q: document.getElementById("q"),
      label: document.getElementById("label"),
      fase: document.getElementById("fase"),
      action: document.getElementById("action"),
      role: document.getElementById("role"),
      asset: document.getElementById("asset"),
      impact: document.getElementById("impact")
    };

    window.renderData = function(data) {
      payload = data || {changes:[], summary:{}};
      rows = payload.changes || [];
      renderCompareBanner();
      renderSummary();
      fillFilters();
      render();
    };

    function renderCompareBanner(){
      const from = payload.comparison_from || "-";
      const to = payload.comparison_to || "-";
      document.getElementById("compareBanner").innerHTML =
        `<b>Vergelijking: ${esc(from)} → ${esc(to)}</b><span class="small">Cutoff-handelsdagen; oude legacy-runs zonder cutoff worden niet als vorige status gebruikt.</span>`;
    }

    function renderSummary(){
      const s = payload.summary || {};
      const cards = [
        ["totaal","Totaal"],
        ["verbeterd","Verbeterd"],
        ["sterk_verbeterd","Sterk verbeterd"],
        ["verslechterd","Verslechterd"],
        ["sterk_verslechterd","Sterk verslechterd"],
        ["risico_omhoog","Risico omhoog"],
        ["theta_kans_omhoog","Theta kans"],
        ["stabiel","Stabiel"]
      ];
      document.getElementById("summary").innerHTML = cards.map(([k,l]) =>
        `<div class="card"><div class="k">${esc(l)}</div><div class="v">${Number(s[k] || 0)}</div></div>`
      ).join("");
      const err = document.getElementById("error");
      if (payload.error) { err.style.display = "block"; err.textContent = payload.error; }
      else { err.style.display = "none"; }
    }

    function fillFilters(){
      fill("label", "change_label");
      fill("fase", "current_asset_fase");
      fill("action", "current_action");
      fill("role", "indicator_role");
      fillAssetTimelineSelect();
    }

    function fill(id, key){
      const select = els[id];
      const old = select.value || "__ALL__";
      const values = [...new Set(rows.map(r => String(r[key] || "").trim()).filter(Boolean))].sort();
      select.innerHTML = `<option value="__ALL__">Alle</option>` + values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
      select.value = values.includes(old) ? old : "__ALL__";
    }

    function filteredRows(){
      const q = els.q.value.trim().toLowerCase();
      const minImpact = Math.abs(Number(els.impact.value || 0));
      return rows.filter(r => {
        if (els.label.value !== "__ALL__" && r.change_label !== els.label.value) return false;
        if (els.fase.value !== "__ALL__" && r.current_asset_fase !== els.fase.value) return false;
        if (els.action.value !== "__ALL__" && r.current_action !== els.action.value) return false;
        if (els.role.value !== "__ALL__" && r.indicator_role !== els.role.value) return false;
        if (Math.abs(Number(r.change_impact_score || 0)) < minImpact) return false;
        if (!q) return true;
        return Object.values(r).join(" ").toLowerCase().includes(q);
      });
    }

    function fillAssetTimelineSelect(){
      const select = els.asset;
      const old = select.value || "__ALL__";
      const values = Object.keys(payload.timeline || {}).sort();
      select.innerHTML = `<option value="__ALL__">Geen</option>` + values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
      select.value = values.includes(old) ? old : "__ALL__";
    }

    function render(){
      const out = filteredRows();
      renderTimeline();
      document.getElementById("count").textContent =
        `${out.length} van ${rows.length} assets | rows ${payload.rows_loaded || 0} | ${payload.generated_at || ""} | ${payload.db_path || ""}`;
      document.getElementById("tbody").innerHTML = out.map(r => `
        <tr class="${esc(r.change_label)}">
          <td><b>${esc(r.asset_rollup)}</b><div class="small">${esc(r.asset_name)}</div></td>
          <td><span class="pill label_${esc(r.change_label)}">${esc(r.change_label)}</span></td>
          <td class="num">${esc(r.change_impact_score)}</td>
          <td>${pair(r.previous_asset_fase, r.current_asset_fase, r.previous_input_cutoff_date, r.current_input_cutoff_date)}</td>
          <td>${pair(r.previous_trend_phase, r.current_trend_phase, r.previous_input_cutoff_date, r.current_input_cutoff_date)}</td>
          <td>${pair(r.previous_action, r.current_action, r.previous_input_cutoff_date, r.current_input_cutoff_date)}</td>
          <td>${pair(r.previous_secondary, r.current_secondary, r.previous_input_cutoff_date, r.current_input_cutoff_date)}</td>
          <td>${esc(r.indicator_role)}</td>
          <td class="num">${esc(r.direction_score)}</td>
          <td class="num">${esc(r.direction_delta)}</td>
          <td class="num">${esc(r.theta_proxy)}</td>
          <td class="num">${esc(r.theta_delta)}</td>
          <td class="num">${esc(r.confidence_score)}</td>
          <td class="reasons">
            <div>${esc(r.change_reason_1)}</div>
            <div>${esc(r.change_reason_2)}</div>
            <div>${esc(r.change_reason_3)}</div>
          </td>
        </tr>
      `).join("");
    }

    function renderTimeline(){
      const asset = els.asset.value;
      const box = document.getElementById("timeline");
      if (!asset || asset === "__ALL__") { box.style.display = "none"; box.innerHTML = ""; return; }
      const items = (payload.timeline || {})[asset] || [];
      box.style.display = "block";
      box.innerHTML = `
        <div class="timeline-title">${esc(asset)} verloop (${items.length} cutoff-dagen)</div>
        <div class="timeline-row timeline-head"><div>Datum</div><div>Asset fase</div><div>Trend fase</div><div>Action</div><div>Dir</div><div>Theta</div></div>
        ${items.map(r => `
          <div class="timeline-row">
            <div>${esc(r.cutoff_date)}</div>
            <div>${esc(r.asset_fase)}</div>
            <div>${esc(r.trend_phase)}</div>
            <div>${esc(r.primary_action)}<div class="small">${esc(r.secondary_action)}</div></div>
            <div class="num">${esc(r.direction_score)}</div>
            <div class="num">${esc(r.theta_proxy)}</div>
          </div>
        `).join("")}`;
    }

    function pair(a,b,oldDate,newDate){
      a = String(a || "-"); b = String(b || "-");
      if (a === b) return `<span class="pair-single">${esc(b)}<span class="date">${esc(newDate || "")}</span></span>`;
      return `<div class="pair"><span class="old">${esc(a)}<span class="date">${esc(oldDate || "")}</span></span><span class="arrow">→</span><b class="new">${esc(b)}<span class="date">${esc(newDate || "")}</span></b></div>`;
    }

    function esc(v){
      return String(v ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[ch]));
    }

    for (const el of Object.values(els)) el.addEventListener("input", render);
  </script>
</body>
</html>
"""

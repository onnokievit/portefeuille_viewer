"""Standalone web report for asset indicator history changes.

Run:
    python devtools/asset_indicator_changes_web.py

The report reads asset_indicator_signal_history from the configured stockdata
database and shows assets whose selected indicator field changed recently.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


os.environ.setdefault("SNAPSHOT_PERF_LOG", "0")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portefeuille_viewer.data import repository  # noqa: E402
from portefeuille_viewer.config import get_stockdata_db_path  # noqa: E402


FIELD_OPTIONS: dict[str, str] = {
    "action": "primary_action",
    "secondary action": "secondary_action",
    "fase": "asset_fase",
    "trend fase": "trend_phase",
    "data quality": "data_quality",
    "direction score": "direction_score",
    "long term direction": "long_term_direction_score",
    "short term direction": "short_term_direction_score",
    "range positie": "range_position_pct",
    "volatility score": "realized_volatility_score",
    "theta score": "theta_score",
    "volume score": "volume_score",
    "confidence score": "confidence_score",
}

HISTORY_COLUMNS = [
    "id",
    "run_id",
    "as_of",
    "created_at",
    "asset_rollup",
    "asset_name",
    "indicator_role",
    "trend_phase",
    "asset_fase",
    "primary_action",
    "secondary_action",
    "data_quality",
    "direction_score",
    "long_term_direction_score",
    "short_term_direction_score",
    "range_position_pct",
    "realized_volatility_score",
    "theta_score",
    "volume_score",
    "confidence_score",
    "reason_1",
    "reason_2",
    "reason_3",
]


@dataclass(frozen=True)
class ReportPayload:
    generated_at: str
    db_path: str
    days: int
    selected_field: str
    rows_loaded: int
    changes: list[dict[str, Any]]
    fields: list[dict[str, str]]
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Web report for asset indicator history changes.")
    parser.add_argument("--host", default="127.0.0.1", help="Host for the local web server.")
    parser.add_argument("--port", type=int, default=8765, help="Port for the local web server.")
    parser.add_argument("--days", type=int, default=2, help="Lookback window for changes.")
    parser.add_argument("--field", default="action", choices=tuple(FIELD_OPTIONS), help="Initial selected field.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = {
        "days": max(1, int(args.days)),
        "field": str(args.field),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/api/changes"):
                self._send_json(build_payload(state["field"], state["days"]).__dict__)
                return
            self._send_html(render_page())

        def do_POST(self) -> None:
            if not self.path.startswith("/api/settings"):
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {}
            field = str(payload.get("field") or state["field"]).strip().lower()
            if field in FIELD_OPTIONS:
                state["field"] = field
            try:
                state["days"] = max(1, int(payload.get("days") or state["days"]))
            except Exception:
                pass
            self._send_json(build_payload(state["field"], state["days"]).__dict__)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_html(self, text: str) -> None:
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((args.host, int(args.port)), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Asset indicator wijzigingenrapport: {url}")
    print(f"Database: {get_stockdata_db_path()}")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGestopt.")
    finally:
        server.server_close()
    return 0


def build_payload(selected_field: str, days: int) -> ReportPayload:
    selected_field = selected_field if selected_field in FIELD_OPTIONS else "action"
    db_column = FIELD_OPTIONS[selected_field]
    try:
        rows = load_history_rows(days=max(1, int(days)))
        changes = find_changes(rows, db_column, days=max(1, int(days)))
        return ReportPayload(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            db_path=str(get_stockdata_db_path() or ""),
            days=max(1, int(days)),
            selected_field=selected_field,
            rows_loaded=len(rows),
            changes=changes,
            fields=[{"label": label, "value": label} for label in FIELD_OPTIONS],
        )
    except Exception as exc:
        return ReportPayload(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            db_path=str(get_stockdata_db_path() or ""),
            days=max(1, int(days)),
            selected_field=selected_field,
            rows_loaded=0,
            changes=[],
            fields=[{"label": label, "value": label} for label in FIELD_OPTIONS],
            error=f"{type(exc).__name__}: {exc}",
        )


def load_history_rows(days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now() - timedelta(days=days + 14)
    select_cols = ", ".join(f"[{col}]" for col in HISTORY_COLUMNS)
    sql = f"""
        SELECT {select_cols}
        FROM asset_indicator_signal_history
        WHERE created_at >= ?
        ORDER BY asset_rollup, created_at, id
    """
    with repository.get_stockdata_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, cutoff)
        columns = [str(desc[0]) for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def find_changes(rows: list[dict[str, Any]], db_column: str, days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now() - timedelta(days=max(1, int(days)))
    by_asset: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        asset = str(row.get("asset_rollup") or "").strip().upper()
        if not asset:
            continue
        by_asset.setdefault(asset, []).append(row)

    changes: list[dict[str, Any]] = []
    for asset, asset_rows in by_asset.items():
        asset_rows.sort(key=lambda r: (_dt_sort_value(r.get("created_at")), int(r.get("id") or 0)))
        previous = None
        for current in asset_rows:
            if previous is None:
                previous = current
                continue
            changed_at = _dt_value(current.get("created_at")) or _dt_value(current.get("as_of"))
            if changed_at is None or changed_at < cutoff:
                previous = current
                continue
            old_value = normalize_value(previous.get(db_column))
            new_value = normalize_value(current.get(db_column))
            if old_value != new_value:
                changes.append(
                    {
                        "asset_rollup": asset,
                        "asset_name": current.get("asset_name") or previous.get("asset_name") or "",
                        "indicator_role": current.get("indicator_role") or "",
                        "changed_at": _fmt_dt(changed_at),
                        "previous_at": _fmt_dt(previous.get("created_at") or previous.get("as_of")),
                        "old_value": old_value,
                        "new_value": new_value,
                        "current_action": current.get("primary_action") or "",
                        "current_fase": current.get("asset_fase") or "",
                        "trend_phase": current.get("trend_phase") or "",
                        "direction_score": _fmt_num(current.get("direction_score")),
                        "volume_score": _fmt_num(current.get("volume_score")),
                        "confidence_score": _fmt_num(current.get("confidence_score")),
                        "reason_1": current.get("reason_1") or "",
                        "reason_2": current.get("reason_2") or "",
                        "reason_3": current.get("reason_3") or "",
                    }
                )
            previous = current

    changes.sort(key=lambda r: (r["changed_at"], r["asset_rollup"]), reverse=True)
    return changes


def normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value).strip()


def _dt_value(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _dt_sort_value(value: Any) -> datetime:
    return _dt_value(value) or datetime.min


def _fmt_dt(value: Any) -> str:
    dt = _dt_value(value)
    return "" if dt is None else dt.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_num(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.1f}"
    except Exception:
        return ""


def render_page() -> str:
    fields_json = html.escape(json.dumps([{"label": k, "value": k} for k in FIELD_OPTIONS]), quote=False)
    return f"""<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Indicator wijzigingen</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f4f6f8; color: #17202a; font-size: 14px; }}
    header {{ background: #1f2933; color: white; padding: 12px 16px; display: flex; justify-content: space-between; gap: 16px; align-items: center; }}
    h1 {{ margin: 0; font-size: 18px; font-weight: 650; }}
    main {{ padding: 14px 16px 22px; }}
    .toolbar {{ background: white; border: 1px solid #d5dce4; border-radius: 6px; padding: 10px; display: grid; grid-template-columns: 240px 120px 120px 1fr; gap: 10px; align-items: end; margin-bottom: 10px; }}
    label {{ display: block; color: #5c6875; font-size: 12px; margin-bottom: 4px; }}
    select, input, button {{ height: 32px; width: 100%; border: 1px solid #b9c3cf; border-radius: 4px; background: white; padding: 4px 8px; font: inherit; }}
    button {{ background: #e9eef5; cursor: pointer; }}
    .meta {{ color: #cbd5df; font-size: 12px; text-align: right; }}
    .status {{ color: #5c6875; margin: 8px 0; }}
    .error {{ color: #8a1f1f; background: #ffe0e0; border: 1px solid #efb3b3; padding: 8px; border-radius: 4px; margin-bottom: 10px; display: none; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #d5dce4; }}
    th, td {{ border-bottom: 1px solid #e6ebf0; border-right: 1px solid #edf1f5; padding: 6px 8px; vertical-align: top; white-space: nowrap; }}
    th {{ position: sticky; top: 0; background: #eef2f6; text-align: left; font-weight: 650; }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    td.reason {{ white-space: normal; min-width: 360px; max-width: 680px; }}
    .pill {{ display: inline-block; border: 1px solid #c9d2dc; border-radius: 999px; padding: 2px 7px; background: #f9fbfd; }}
    .old {{ background: #fff0d7; }}
    .new {{ background: #dff3e6; font-weight: 650; }}
    @media (max-width: 900px) {{ .toolbar {{ grid-template-columns: 1fr 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Indicator wijzigingen</h1>
    <div class="meta" id="meta"></div>
  </header>
  <main>
    <section class="toolbar">
      <div>
        <label for="field">Wijziging in veld</label>
        <select id="field"></select>
      </div>
      <div>
        <label for="days">Dagen</label>
        <input id="days" type="number" min="1" step="1" value="2" />
      </div>
      <div>
        <label>&nbsp;</label>
        <button id="refresh">Ververs</button>
      </div>
      <div>
        <label for="q">Zoek</label>
        <input id="q" placeholder="Asset, actie, fase, reden..." />
      </div>
    </section>
    <div class="error" id="error"></div>
    <div class="status" id="status"></div>
    <table>
      <thead>
        <tr>
          <th>Gewijzigd</th>
          <th>Asset</th>
          <th>Naam</th>
          <th>Rol</th>
          <th>Vorige waarde</th>
          <th>Nieuwe waarde</th>
          <th>Huidige action</th>
          <th>Fase</th>
          <th>Trend</th>
          <th>Dir</th>
          <th>Vol</th>
          <th>Conf</th>
          <th>Redenen</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </main>
  <script id="fields" type="application/json">{fields_json}</script>
  <script>
    const fields = JSON.parse(document.getElementById("fields").textContent);
    let rows = [];
    let payload = null;
    const fieldEl = document.getElementById("field");
    const daysEl = document.getElementById("days");
    const qEl = document.getElementById("q");
    for (const f of fields) fieldEl.append(new Option(f.label, f.value));
    fieldEl.value = "action";

    async function load(post=false) {{
      const opts = post ? {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{field: fieldEl.value, days: Number(daysEl.value || 2)}})
      }} : {{}};
      const res = await fetch(post ? "/api/settings" : "/api/changes", opts);
      payload = await res.json();
      rows = payload.changes || [];
      fieldEl.value = payload.selected_field || fieldEl.value;
      daysEl.value = payload.days || daysEl.value;
      render();
    }}

    function render() {{
      const errorEl = document.getElementById("error");
      if (payload?.error) {{
        errorEl.style.display = "block";
        errorEl.textContent = payload.error;
      }} else {{
        errorEl.style.display = "none";
      }}
      document.getElementById("meta").textContent = `${{payload?.generated_at || ""}} | ${{payload?.db_path || ""}}`;
      const q = qEl.value.trim().toLowerCase();
      const out = rows.filter(r => !q || Object.values(r).join(" ").toLowerCase().includes(q));
      document.getElementById("status").textContent =
        `${{out.length}} wijzigingen getoond | ${{rows.length}} totaal | veld: ${{payload?.selected_field || ""}} | bronregels: ${{payload?.rows_loaded || 0}}`;
      document.getElementById("tbody").innerHTML = out.map(r => `
        <tr>
          <td>${{esc(r.changed_at)}}</td>
          <td><strong>${{esc(r.asset_rollup)}}</strong></td>
          <td>${{esc(r.asset_name)}}</td>
          <td>${{esc(r.indicator_role)}}</td>
          <td class="old">${{esc(r.old_value)}}</td>
          <td class="new">${{esc(r.new_value)}}</td>
          <td><span class="pill">${{esc(r.current_action)}}</span></td>
          <td>${{esc(r.current_fase)}}</td>
          <td>${{esc(r.trend_phase)}}</td>
          <td class="num">${{esc(r.direction_score)}}</td>
          <td class="num">${{esc(r.volume_score)}}</td>
          <td class="num">${{esc(r.confidence_score)}}</td>
          <td class="reason">
            <div>${{esc(r.reason_1)}}</div>
            <div>${{esc(r.reason_2)}}</div>
            <div>${{esc(r.reason_3)}}</div>
          </td>
        </tr>
      `).join("");
    }}

    function esc(v) {{
      return String(v ?? "").replace(/[&<>"']/g, ch => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[ch]));
    }}

    document.getElementById("refresh").addEventListener("click", () => load(true));
    fieldEl.addEventListener("change", () => load(true));
    daysEl.addEventListener("change", () => load(true));
    qEl.addEventListener("input", render);
    load(false);
  </script>
</body>
</html>"""


if __name__ == "__main__":
    raise SystemExit(main())

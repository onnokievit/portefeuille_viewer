"""Run AssetIndicatorService once from the command line.

This is a devtool for inspecting the v1 snapshot-only indicator outside the Qt
app. It loads the required source snapshots from the configured default user DB,
runs the indicator rebuild, and prints compact CLI output.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path


os.environ.setdefault("SNAPSHOT_PERF_LOG", "0")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import polars as pl  # noqa: E402

from portefeuille_viewer.data import repository  # noqa: E402
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE  # noqa: E402
from portefeuille_viewer.services.asset_indicator_service import rebuild_asset_indicator_snapshots  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run asset indicator once and print the resulting snapshots.")
    parser.add_argument("--asset", help="Filter output to one asset_rollup.")
    parser.add_argument("--limit", type=int, default=30, help="Maximum rows to print from the live snapshot.")
    parser.add_argument(
        "--sort",
        choices=("asset", "direction", "volume", "action", "mode", "role"),
        default="action",
        help="Sort live output.",
    )
    parser.add_argument(
        "--only-action",
        help="Filter output to one primary_action, e.g. long_houden or geen_advies_onvoldoende_data.",
    )
    parser.add_argument(
        "--show-reasons",
        action="store_true",
        help="Include reason_1/2/3 in live output.",
    )
    parser.add_argument(
        "--html",
        default=str(ROOT / "devtools" / "asset_indicator_review.html"),
        help="Write an interactive HTML review report to this path.",
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        help="Do not write the HTML review report.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    print("Loading source snapshots...")
    assets_df = repository.load_asset_rollup_data()
    close_df = repository.load_historical_close_snapshot()
    ohlcv_df = getattr(SNAPSHOT_STORE, "repository_snapshot_historical_ohlcv", None)

    print(f"asset_rollup_data rows: {assets_df.height if isinstance(assets_df, pl.DataFrame) else 0}")
    print(f"historical_close rows: {close_df.height if isinstance(close_df, pl.DataFrame) else 0}")
    print(f"historical_ohlcv rows: {ohlcv_df.height if isinstance(ohlcv_df, pl.DataFrame) else 0}")

    print("\nRunning asset indicator...")
    result = rebuild_asset_indicator_snapshots()
    print(
        "run_id={run_id} status={status} assets_total={assets_total} "
        "assets_scored={assets_scored} insufficient={insufficient} duration_ms={duration_ms:.1f}".format(
            run_id=result.run_id,
            status=result.status,
            assets_total=result.assets_total,
            assets_scored=result.assets_scored,
            insufficient=result.assets_insufficient_data,
            duration_ms=result.duration_ms,
        )
    )
    if result.error:
        print(f"error={result.error}")
        return 1

    _print_summary()
    _print_live(args)
    _print_meta()
    if not args.no_html:
        report_path = _write_html_report(args)
        print(f"\nHTML review written: {report_path}")
    return 0


def _print_summary() -> None:
    df = getattr(SNAPSHOT_STORE, "snapshot_asset_indicator_summary", None)
    print("\nSummary")
    if df is None or df.is_empty():
        print("(empty)")
        return
    cols = ["group_type", "group_key", "asset_count", "avg_direction_score", "avg_volume_score", "top_assets"]
    rows = df.select([c for c in cols if c in df.columns]).to_dicts()
    for row in rows:
        print(
            "- {group_type}={group_key}: count={asset_count}, direction={direction}, volume={volume}, top={top}".format(
                group_type=row.get("group_type") or "",
                group_key=row.get("group_key") or "",
                asset_count=row.get("asset_count") or 0,
                direction=_fmt_num(row.get("avg_direction_score")),
                volume=_fmt_num(row.get("avg_volume_score")),
                top=row.get("top_assets") or "",
            )
        )


def _print_live(args: argparse.Namespace) -> None:
    df = getattr(SNAPSHOT_STORE, "snapshot_asset_indicator_live", None)
    print("\nLive rows")
    if df is None or df.is_empty():
        print("(empty)")
        return

    work = df
    if args.asset:
        asset = str(args.asset).strip().upper()
        work = work.filter(pl.col("asset_rollup") == asset)
    if args.only_action:
        work = work.filter(pl.col("primary_action") == str(args.only_action).strip())

    if args.sort == "direction" and "direction_score" in work.columns:
        work = work.sort("direction_score", descending=True, nulls_last=True)
    elif args.sort == "volume" and "volume_score" in work.columns:
        work = work.sort("volume_score", descending=True, nulls_last=True)
    elif args.sort == "mode" and "asset_fase" in work.columns:
        work = work.sort(["asset_fase", "asset_rollup"])
    elif args.sort == "role" and "indicator_role" in work.columns:
        work = work.sort(["indicator_role", "asset_rollup"])
    elif args.sort == "asset" and "asset_rollup" in work.columns:
        work = work.sort("asset_rollup")
    else:
        work = work.sort(["primary_action", "asset_rollup"])

    cols = [
        "asset_rollup",
        "asset_name",
        "indicator_role",
        "direction_score",
        "long_term_direction_score",
        "short_term_direction_score",
        "range_position_pct",
        "trend_phase",
        "realized_volatility_score",
        "atr_pct",
        "choppiness_score",
        "ibkr_hv_proxy_pct",
        "ibkr_iv_proxy_pct",
        "iv_vs_realized_volatility_score",
        "theta_opportunity_proxy_score",
        "volume_score",
        "asset_fase",
        "primary_action",
        "secondary_action",
        "data_quality",
    ]
    if args.show_reasons:
        cols.extend(["reason_1", "reason_2", "reason_3"])
    cols = [c for c in cols if c in work.columns]

    limited = work.head(max(0, int(args.limit)))
    print(f"showing {limited.height} of {work.height} rows")
    for row in limited.select(cols).to_dicts():
        print(
            "- {asset}: role={role} dir={direction} lt={lt} st={st} range={range_pos} phase={phase} rv={rv} atr={atr} chop={chop} hv={hv} iv={iv} ivrv={ivrv} theta_opp={theta_opp} vol={volume} mode={mode} action={action} secondary={secondary} quality={quality}".format(
                asset=row.get("asset_rollup") or "",
                role=row.get("indicator_role") or "",
                direction=_fmt_num(row.get("direction_score")),
                lt=_fmt_num(row.get("long_term_direction_score")),
                st=_fmt_num(row.get("short_term_direction_score")),
                range_pos=_fmt_num(row.get("range_position_pct")),
                phase=row.get("trend_phase") or "",
                rv=_fmt_num(row.get("realized_volatility_score")),
                atr=_fmt_num(row.get("atr_pct")),
                chop=_fmt_num(row.get("choppiness_score")),
                hv=_fmt_num(row.get("ibkr_hv_proxy_pct")),
                iv=_fmt_num(row.get("ibkr_iv_proxy_pct")),
                ivrv=_fmt_num(row.get("iv_vs_realized_volatility_score")),
                theta_opp=_fmt_num(row.get("theta_opportunity_proxy_score")),
                volume=_fmt_num(row.get("volume_score")),
                mode=row.get("asset_fase") or "",
                action=row.get("primary_action") or "",
                secondary=row.get("secondary_action") or "",
                quality=row.get("data_quality") or "",
            )
        )
        if args.show_reasons:
            print(f"  reason_1: {row.get('reason_1') or ''}")
            print(f"  reason_2: {row.get('reason_2') or ''}")
            print(f"  reason_3: {row.get('reason_3') or ''}")


def _print_meta() -> None:
    df = getattr(SNAPSHOT_STORE, "snapshot_asset_indicator_meta", None)
    print("\nMeta")
    if df is None or df.is_empty():
        print("(empty)")
        return
    for row in df.to_dicts():
        print(
            "- status={status} total={total} scored={scored} insufficient={insufficient} version={version}".format(
                status=row.get("last_status") or "",
                total=row.get("assets_total") or 0,
                scored=row.get("assets_scored") or 0,
                insufficient=row.get("assets_insufficient_data") or 0,
                version=row.get("service_version") or "",
            )
        )


def _fmt_num(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.1f}"
    except Exception:
        return "-"


def _write_html_report(args: argparse.Namespace) -> Path:
    out_path = Path(args.html).expanduser()
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    live_df = getattr(SNAPSHOT_STORE, "snapshot_asset_indicator_live", None)
    summary_df = getattr(SNAPSHOT_STORE, "snapshot_asset_indicator_summary", None)
    meta_df = getattr(SNAPSHOT_STORE, "snapshot_asset_indicator_meta", None)
    live_rows = [] if live_df is None or live_df.is_empty() else live_df.to_dicts()
    summary_rows = [] if summary_df is None or summary_df.is_empty() else summary_df.to_dicts()
    meta_rows = [] if meta_df is None or meta_df.is_empty() else meta_df.to_dicts()
    payload = {
        "live": live_rows,
        "summary": summary_rows,
        "meta": meta_rows,
        "initial": {
            "asset": str(args.asset or "").strip().upper(),
            "primary_action": str(args.only_action or "").strip(),
        },
    }
    json_payload = html.escape(json.dumps(payload, default=str, ensure_ascii=False), quote=False)
    out_path.write_text(_html_template(json_payload), encoding="utf-8")
    return out_path


def _html_template(json_payload: str) -> str:
    return f"""<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Asset Indicator Review</title>
  <style>
    :root {{
      --bg: #f5f6f7;
      --panel: #ffffff;
      --line: #d8dde3;
      --text: #1d232b;
      --muted: #5d6673;
      --green: #dff4e5;
      --green2: #bce8ca;
      --blue: #e3eefc;
      --yellow: #fff3c4;
      --orange: #ffe1c7;
      --red: #ffd6d6;
      --gray: #eceff3;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Segoe UI, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      font-size: 13px;
    }}
    header {{
      padding: 12px 16px;
      background: #202833;
      color: white;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    h1 {{
      font-size: 17px;
      margin: 0;
      font-weight: 600;
    }}
    .meta {{
      color: #cbd5e1;
      font-size: 12px;
      text-align: right;
    }}
    .wrap {{ padding: 12px 16px 18px; }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 8px;
      margin-bottom: 10px;
    }}
    .summary-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
    }}
    .summary-card .k {{ color: var(--muted); font-size: 12px; }}
    .summary-card .v {{ font-size: 18px; font-weight: 650; margin-top: 2px; }}
    .toolbar {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      display: grid;
      grid-template-columns: 1.2fr repeat(5, minmax(140px, 190px)) auto;
      gap: 8px;
      align-items: end;
      margin-bottom: 10px;
    }}
    label {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 3px; }}
    input, select, button {{
      width: 100%;
      height: 30px;
      border: 1px solid #bfc7d1;
      border-radius: 4px;
      background: white;
      padding: 4px 7px;
      font: inherit;
    }}
    button {{ cursor: pointer; background: #eef2f7; }}
    .count {{ color: var(--muted); margin: 4px 0 8px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
    }}
    th, td {{
      border-bottom: 1px solid #e5e9ee;
      border-right: 1px solid #eef1f4;
      padding: 5px 7px;
      vertical-align: top;
      white-space: nowrap;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #eef2f6;
      z-index: 1;
      cursor: pointer;
      user-select: none;
      text-align: left;
      font-weight: 650;
    }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    td.reasons {{ white-space: normal; min-width: 330px; max-width: 560px; }}
    tr.long_houden {{ background: var(--green); }}
    tr.schrijf_puts {{ background: var(--blue); }}
    tr.theta_harvest {{ background: #e0f7f2; }}
    tr.risico_verlagen {{ background: var(--red); }}
    tr.geen_advies_onvoldoende_data {{ background: var(--gray); color: #59616d; }}
    .pill {{
      display: inline-block;
      padding: 2px 6px;
      border-radius: 999px;
      border: 1px solid #ccd3dc;
      background: white;
      margin-right: 4px;
    }}
    .small {{ color: var(--muted); font-size: 12px; }}
    @media (max-width: 1100px) {{
      .toolbar {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Asset Indicator Review</h1>
    <div class="meta" id="meta"></div>
  </header>
  <div class="wrap">
    <section class="summary" id="summary"></section>
    <section class="toolbar">
      <div>
        <label for="q">Zoek</label>
        <input id="q" placeholder="Asset, mode, action, reason..." />
      </div>
      <div>
        <label for="action">Primary action</label>
        <select id="action"></select>
      </div>
      <div>
        <label for="role">Indicator rol</label>
        <select id="role"></select>
      </div>
      <div>
        <label for="mode">Asset mode</label>
        <select id="mode"></select>
      </div>
      <div>
        <label for="quality">Data quality</label>
        <select id="quality"></select>
      </div>
      <div>
        <label for="secondary">Secondary</label>
        <select id="secondary"></select>
      </div>
      <div>
        <label>&nbsp;</label>
        <button id="reset">Reset</button>
      </div>
    </section>
    <div class="count" id="count"></div>
    <table>
      <thead>
        <tr>
          <th data-key="asset_rollup">Asset</th>
          <th data-key="asset_name">Name</th>
          <th data-key="indicator_role">Rol</th>
          <th data-key="direction_score">Direction</th>
          <th data-key="long_term_direction_score">LT</th>
          <th data-key="short_term_direction_score">ST</th>
          <th data-key="range_position_pct">Range %</th>
          <th data-key="trend_phase">Trend fase</th>
          <th data-key="realized_volatility_score">RV score</th>
          <th data-key="atr_pct">ATR %</th>
          <th data-key="choppiness_score">Chop</th>
          <th data-key="ibkr_iv_proxy_pct">IV %</th>
          <th data-key="iv_vs_realized_volatility_score">IV/RV</th>
          <th data-key="theta_opportunity_proxy_score">Theta opp</th>
          <th data-key="volume_score">Volume</th>
          <th data-key="asset_fase">Fase</th>
          <th data-key="primary_action">Action</th>
          <th data-key="secondary_action">Secondary</th>
          <th data-key="data_quality">Quality</th>
          <th data-key="reasons">Reasons</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
  <script id="payload" type="application/json">{json_payload}</script>
  <script>
    const payload = JSON.parse(document.getElementById("payload").textContent);
    const rows = payload.live || [];
    const state = {{
      sortKey: "primary_action",
      sortDir: "asc",
      q: "",
      action: payload.initial.primary_action || "__ALL__",
      role: "__ALL__",
      mode: "__ALL__",
      quality: "__ALL__",
      secondary: "__ALL__",
    }};
    const columns = ["asset_rollup","asset_name","indicator_role","direction_score","long_term_direction_score","short_term_direction_score","range_position_pct","trend_phase","realized_volatility_score","atr_pct","choppiness_score","ibkr_iv_proxy_pct","iv_vs_realized_volatility_score","theta_opportunity_proxy_score","volume_score","asset_fase","primary_action","secondary_action","data_quality"];

    function fmt(v) {{
      if (v === null || v === undefined || v === "") return "-";
      if (typeof v === "number") return Number.isFinite(v) ? v.toFixed(1) : "-";
      return String(v);
    }}
    function cmp(a, b) {{
      const av = a[state.sortKey];
      const bv = b[state.sortKey];
      const an = typeof av === "number" && Number.isFinite(av);
      const bn = typeof bv === "number" && Number.isFinite(bv);
      let r = 0;
      if (an || bn) r = (an ? av : -Infinity) - (bn ? bv : -Infinity);
      else r = String(av ?? "").localeCompare(String(bv ?? ""));
      return state.sortDir === "asc" ? r : -r;
    }}
    function unique(key) {{
      return Array.from(new Set(rows.map(r => String(r[key] ?? "").trim()).filter(Boolean))).sort();
    }}
    function fillSelect(id, values, initial) {{
      const el = document.getElementById(id);
      el.innerHTML = "";
      el.append(new Option("Alle", "__ALL__"));
      for (const v of values) el.append(new Option(v, v));
      el.value = initial || "__ALL__";
      el.addEventListener("change", () => {{ state[id] = el.value; render(); }});
    }}
    function rowText(r) {{
      return [
        ...columns.map(k => r[k]),
        r.reason_1, r.reason_2, r.reason_3
      ].map(v => String(v ?? "").toLowerCase()).join(" ");
    }}
    function filteredRows() {{
      const q = state.q.trim().toLowerCase();
      return rows.filter(r => {{
        if (state.action !== "__ALL__" && r.primary_action !== state.action) return false;
        if (state.role !== "__ALL__" && r.indicator_role !== state.role) return false;
        if (state.mode !== "__ALL__" && r.asset_fase !== state.mode) return false;
        if (state.quality !== "__ALL__" && r.data_quality !== state.quality) return false;
        if (state.secondary !== "__ALL__" && r.secondary_action !== state.secondary) return false;
        if (q && !rowText(r).includes(q)) return false;
        return true;
      }}).sort(cmp);
    }}
    function renderSummary() {{
      const summary = document.getElementById("summary");
      const byAction = (payload.summary || []).filter(r => r.group_type === "primary_action");
      summary.innerHTML = byAction.map(r => `
        <div class="summary-card">
          <div class="k">${{escapeHtml(r.group_key || "")}}</div>
          <div class="v">${{r.asset_count ?? 0}}</div>
          <div class="small">dir ${{fmt(r.avg_direction_score)}} | vol ${{fmt(r.avg_volume_score)}}</div>
        </div>
      `).join("");
      const meta = (payload.meta || [{{}}])[0] || {{}};
      document.getElementById("meta").textContent =
        `status=${{meta.last_status || ""}} | total=${{meta.assets_total ?? rows.length}} | scored=${{meta.assets_scored ?? ""}} | version=${{meta.service_version || ""}}`;
    }}
    function render() {{
      const out = filteredRows();
      document.getElementById("count").textContent = `${{out.length}} van ${{rows.length}} assets`;
      document.getElementById("tbody").innerHTML = out.map(r => `
        <tr class="${{escapeAttr(r.primary_action || "")}}">
          <td><strong>${{escapeHtml(r.asset_rollup)}}</strong></td>
          <td>${{escapeHtml(r.asset_name)}}</td>
          <td>${{escapeHtml(r.indicator_role)}}</td>
          <td class="num">${{fmt(r.direction_score)}}</td>
          <td class="num">${{fmt(r.long_term_direction_score)}}</td>
          <td class="num">${{fmt(r.short_term_direction_score)}}</td>
          <td class="num">${{fmt(r.range_position_pct)}}</td>
          <td>${{escapeHtml(r.trend_phase)}}</td>
          <td class="num">${{fmt(r.realized_volatility_score)}}</td>
          <td class="num">${{fmt(r.atr_pct)}}</td>
          <td class="num">${{fmt(r.choppiness_score)}}</td>
          <td class="num">${{fmt(r.ibkr_iv_proxy_pct)}}</td>
          <td class="num">${{fmt(r.iv_vs_realized_volatility_score)}}</td>
          <td class="num">${{fmt(r.theta_opportunity_proxy_score)}}</td>
          <td class="num">${{fmt(r.volume_score)}}</td>
          <td><span class="pill">${{escapeHtml(r.asset_fase)}}</span></td>
          <td><span class="pill">${{escapeHtml(r.primary_action)}}</span></td>
          <td>${{escapeHtml(r.secondary_action)}}</td>
          <td>${{escapeHtml(r.data_quality)}}</td>
          <td class="reasons">
            <div>${{escapeHtml(r.reason_1)}}</div>
            <div class="small">${{escapeHtml(r.reason_2)}}</div>
            <div class="small">${{escapeHtml(r.reason_3)}}</div>
          </td>
        </tr>
      `).join("");
    }}
    function escapeHtml(v) {{
      return String(v ?? "").replace(/[&<>"']/g, ch => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[ch]));
    }}
    function escapeAttr(v) {{
      return String(v ?? "").replace(/[^a-zA-Z0-9_-]/g, "_");
    }}
    document.getElementById("q").addEventListener("input", e => {{ state.q = e.target.value; render(); }});
    document.getElementById("reset").addEventListener("click", () => {{
      state.q = "";
      state.action = "__ALL__";
      state.role = "__ALL__";
      state.mode = "__ALL__";
      state.quality = "__ALL__";
      state.secondary = "__ALL__";
      document.getElementById("q").value = "";
      for (const id of ["action","role","mode","quality","secondary"]) document.getElementById(id).value = "__ALL__";
      render();
    }});
    document.querySelectorAll("th[data-key]").forEach(th => {{
      th.addEventListener("click", () => {{
        const key = th.dataset.key;
        if (key === "reasons") return;
        if (state.sortKey === key) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
        else {{ state.sortKey = key; state.sortDir = "asc"; }}
        render();
      }});
    }});
    fillSelect("action", unique("primary_action"), state.action);
    fillSelect("role", unique("indicator_role"), state.role);
    fillSelect("mode", unique("asset_fase"), state.mode);
    fillSelect("quality", unique("data_quality"), state.quality);
    fillSelect("secondary", unique("secondary_action"), state.secondary);
    renderSummary();
    render();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())

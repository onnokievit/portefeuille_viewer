from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from earnings_dates_cli import (  # noqa: E402
    ONNO_DB_PATH,
    AssetRecord,
    is_us_earnings_asset,
    load_assets,
    normalize_to_date,
    run_nasdaq_us_batch,
)


DOLTHUB_OWNER = "post-no-preference"
DOLTHUB_REPO = "earnings"
DOLTHUB_REF = "master"
DOLTHUB_API_URL = f"https://www.dolthub.com/api/v1alpha1/{DOLTHUB_OWNER}/{DOLTHUB_REPO}/{DOLTHUB_REF}"
DEFAULT_FOCUS_ASSETS = [
    "ISRG",
    "JNJ",
    "MICRON",
    "MMM",
    "NIKE",
    "RTX",
    "SERVICENOW",
    "UNH",
    "VERNOVA",
]


def log(message: str) -> None:
    from datetime import datetime

    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def dolt_query(sql: str, timeout: float = 30.0) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    api_key = os.getenv("DOLTHUB_API_KEY", "").strip()
    if api_key:
        headers["authorization"] = api_key
    response = requests.get(DOLTHUB_API_URL, params={"q": sql}, headers=headers, timeout=timeout)
    log(f"DoltHub HTTP {response.status_code}: {response.url}")
    response.raise_for_status()
    payload = response.json()
    status = str(payload.get("query_execution_status") or "")
    if status and status not in {"Success", "RowLimit"}:
        raise RuntimeError(f"DoltHub query status={status}: {payload.get('query_execution_message')}")
    return payload


def discover_earnings_calendar_columns() -> tuple[str, str, list[str]]:
    payload = dolt_query("DESCRIBE earnings_calendar")
    rows = payload.get("rows") or []
    fields = []
    for row in rows:
        field = row.get("Field") or row.get("field") or row.get("Column") or row.get("column")
        if field:
            fields.append(str(field))
    if not fields:
        raise RuntimeError(f"Kon schema niet lezen uit DESCRIBE earnings_calendar: {rows[:5]}")

    lower_map = {field.lower(): field for field in fields}
    symbol_col = next(
        (lower_map[name] for name in ("act_symbol", "symbol", "ticker") if name in lower_map),
        "",
    )
    date_col = next(
        (lower_map[name] for name in ("date", "earnings_date", "report_date", "period") if name in lower_map),
        "",
    )
    if not symbol_col or not date_col:
        raise RuntimeError(f"Onbekend Dolt schema. fields={fields}")
    log(f"Dolt schema: symbol_col={symbol_col} date_col={date_col} fields={fields}")
    return symbol_col, date_col, fields


def sql_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def fetch_dolt_earnings(symbols: list[str], scan_days: int) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    symbol_col, date_col, fields = discover_earnings_calendar_columns()
    today = date.today()
    # Ruim begrenzen op basis van datumkolom. Als Dolt schema extra datumvelden heeft,
    # printen we die via SELECT * mee zodat inspectie mogelijk blijft.
    symbol_list = ", ".join(sql_quote(symbol) for symbol in symbols)
    query = f"""
        SELECT *
        FROM earnings_calendar
        WHERE `{symbol_col}` IN ({symbol_list})
          AND `{date_col}` >= {sql_quote(today.isoformat())}
        ORDER BY `{symbol_col}`, `{date_col}`
        LIMIT 1000
    """
    payload = dolt_query(query)
    rows = payload.get("rows") or []
    log(f"Dolt rows ontvangen: {len(rows)}")
    found: dict[str, dict[str, Any]] = {}
    max_date = today.fromordinal(today.toordinal() + max(0, int(scan_days)))
    for row in rows:
        symbol = str(row.get(symbol_col) or "").strip().upper()
        row_date = normalize_to_date(row.get(date_col))
        if not symbol or row_date is None:
            continue
        if row_date > max_date:
            continue
        current = found.get(symbol)
        if current is None or row_date < current["date_obj"]:
            found[symbol] = {
                "symbol": symbol,
                "date": row_date.isoformat(),
                "date_obj": row_date,
                "raw": row,
                "date_col": date_col,
                "fields": fields,
            }
    return found


def resolve_target_assets(all_assets: list[AssetRecord], requested_assets: list[str] | None) -> list[AssetRecord]:
    if requested_assets:
        wanted = {value.strip().upper() for value in requested_assets if value.strip()}
    else:
        wanted = set(DEFAULT_FOCUS_ASSETS)
    by_asset = {asset.asset_rollup.upper(): asset for asset in all_assets}
    by_symbol = {asset.ib_symbol.upper(): asset for asset in all_assets if asset.ib_symbol}
    targets: list[AssetRecord] = []
    for value in wanted:
        asset = by_asset.get(value) or by_symbol.get(value)
        if asset is not None:
            targets.append(asset)
        else:
            log(f"WARN target niet gevonden in ONNO asset_rollup_data: {value}")
    return targets


def format_raw_excerpt(row: dict[str, Any]) -> str:
    keep = []
    for key, value in row.items():
        if value in (None, ""):
            continue
        key_l = str(key).lower()
        if key_l in {"act_symbol", "symbol", "ticker", "date", "earnings_date", "report_date", "when", "eps", "eps_estimate", "revenue"}:
            keep.append(f"{key}={value}")
    return "; ".join(keep[:8])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("Vergelijk Nasdaq earnings date scan met DoltHub earnings_calendar.")
    parser.add_argument("--db", default=str(ONNO_DB_PATH), help="Pad naar ONNO Access database.")
    parser.add_argument("--asset", action="append", help="Asset_rollup of IB symbol. Meerdere keren toegestaan.")
    parser.add_argument("--all-us", action="store_true", help="Vergelijk alle US earnings assets i.p.v. focuslijst.")
    parser.add_argument("--nasdaq-scan-days", type=int, default=180)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log("START Nasdaq vs DoltHub earnings compare")
    all_assets = load_assets(Path(args.db))
    us_assets = [asset for asset in all_assets if is_us_earnings_asset(asset)]
    targets = us_assets if args.all_us else resolve_target_assets(all_assets, args.asset)
    targets = [asset for asset in targets if is_us_earnings_asset(asset)]
    if not targets:
        log("Geen US earnings targets gevonden.")
        return 1

    symbols = sorted({asset.ib_symbol.strip().upper() for asset in targets if asset.ib_symbol})
    log(f"Targets: assets={len(targets)} symbols={symbols}")

    nasdaq_results = run_nasdaq_us_batch(targets, args.nasdaq_scan_days)
    nasdaq_by_symbol = {str(row["symbol"]).upper(): row for row in nasdaq_results}
    try:
        dolt_by_symbol = fetch_dolt_earnings(symbols, args.nasdaq_scan_days)
    except Exception as exc:
        log(f"FATAL DoltHub query mislukt: {type(exc).__name__}: {exc}")
        return 2

    print("")
    print("VERGELIJKING")
    print("asset | symbol | nasdaq | dolt | status | dolt_raw")
    for asset in targets:
        symbol = asset.ib_symbol.strip().upper()
        n = nasdaq_by_symbol.get(symbol) or {}
        d = dolt_by_symbol.get(symbol) or {}
        n_date = str(n.get("date") or "-")
        d_date = str(d.get("date") or "-")
        if n_date != "-" and d_date != "-":
            status = "same" if n_date == d_date else "diff"
        elif n_date != "-":
            status = "nasdaq_only"
        elif d_date != "-":
            status = "dolt_only"
        else:
            status = "missing"
        print(
            f"{asset.asset_rollup} | {symbol} | {n_date} | {d_date} | {status} | "
            f"{format_raw_excerpt(d.get('raw') or {})}"
        )

    ok_n = sum(1 for row in nasdaq_results if row.get("status") == "ok")
    ok_d = sum(1 for symbol in symbols if symbol in dolt_by_symbol)
    log(f"KLAAR: targets={len(targets)} nasdaq_found={ok_n} dolt_found={ok_d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

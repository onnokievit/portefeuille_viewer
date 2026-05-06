"""
Standalone Client Portal option-chain reader.

Flow:
  1. /iserver/auth/status
  2. /iserver/secdef/search?symbol=...
  3. /iserver/secdef/strikes per option month
  4. /iserver/secdef/info per month/strike/right to validate option conids

Examples:
  python cp_chain_reader.py META --max-months 2 --max-strikes-per-side 20
  python cp_chain_reader.py MSFT --base-url https://localhost:5000/v1/api --no-validate
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import urllib3

from config_reader import get_stock_db_path


DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

DEFAULT_BASE_URL = "https://localhost:5000/v1/api"


def log(msg: str) -> None:
    print(f"[cp-chain] {msg}", flush=True)


class CpClient:
    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        log(f"GET {url}" + (f" params={params}" if params else ""))
        r = self.session.get(url, params=params, timeout=self.timeout)
        log(f"  -> HTTP {r.status_code}")
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code} for {path}: {r.text[:500]}")
        if not r.text:
            return None
        return r.json()

    def auth_status(self) -> dict[str, Any]:
        return self.get("/iserver/auth/status")

    def search(self, symbol: str, sec_type: str = "STK") -> list[dict[str, Any]]:
        data = self.get("/iserver/secdef/search", {"symbol": symbol, "secType": sec_type})
        if isinstance(data, list):
            return data
        raise RuntimeError(f"Unexpected search response: {data!r}")

    def strikes(self, conid: str | int, month: str, exchange: str = "SMART") -> dict[str, list[float]]:
        data = self.get(
            "/iserver/secdef/strikes",
            {"conid": conid, "sectype": "OPT", "month": month, "exchange": exchange},
        )
        if isinstance(data, dict):
            return data
        raise RuntimeError(f"Unexpected strikes response for {month}: {data!r}")

    def info(
        self,
        conid: str | int,
        month: str,
        strike: float,
        right: str,
        exchange: str = "SMART",
    ) -> list[dict[str, Any]]:
        data = self.get(
            "/iserver/secdef/info",
            {
                "conid": conid,
                "secType": "OPT",
                "month": month,
                "strike": strike,
                "right": right,
                "exchange": exchange,
            },
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return []


def pick_underlying(rows: list[dict[str, Any]], symbol: str) -> tuple[dict[str, Any], dict[str, str]]:
    symbol_u = symbol.upper()
    candidates: list[tuple[int, dict[str, Any], dict[str, str]]] = []
    for row in rows:
        sections = row.get("sections") or []
        opt_section = next((s for s in sections if s.get("secType") == "OPT" and s.get("months")), None)
        if not opt_section:
            continue
        score = 0
        if str(row.get("symbol", "")).upper() == symbol_u:
            score += 10
        if str(row.get("description", "")).upper() in {"NASDAQ", "NYSE", "ARCA"}:
            score += 1
        candidates.append((score, row, opt_section))

    if not candidates:
        raise RuntimeError("No search result with OPT section/months found")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1], candidates[0][2]


def parse_months(opt_section: dict[str, Any], max_months: int | None) -> list[str]:
    months_raw = str(opt_section.get("months") or "")
    months = [m.strip() for m in months_raw.split(";") if m.strip()]
    if max_months:
        months = months[:max_months]
    return months


def parse_exchanges(opt_section: dict[str, Any], exchange_arg: str) -> list[str]:
    if exchange_arg and exchange_arg.upper() != "AUTO":
        return [exchange_arg]
    raw = str(opt_section.get("exchange") or "")
    exchanges = [e.strip() for e in raw.split(";") if e.strip()]
    if "SMART" not in exchanges:
        exchanges.append("SMART")
    return exchanges or ["SMART"]


def load_spot_from_db(symbol: str) -> tuple[float, str, str]:
    import pyodbc

    db_path = get_stock_db_path()
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={db_path};"
    )
    conn = pyodbc.connect(conn_str)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT TOP 1 asset_rollup
            FROM asset_rollup_data
            WHERE ib_symbol = ? OR asset_rollup = ?
            ORDER BY asset_rollup
            """,
            (symbol, symbol),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"No asset_rollup_data row found for symbol {symbol}")
        asset_rollup = str(row[0])

        cur.execute(
            """
            SELECT TOP 1 datum, [close]
            FROM historical_data_correct
            WHERE asset_rollup = ?
              AND [close] IS NOT NULL
            ORDER BY datum DESC
            """,
            (asset_rollup,),
        )
        price_row = cur.fetchone()
        if not price_row:
            raise RuntimeError(f"No historical_data_correct close found for asset_rollup {asset_rollup}")
        datum, close_price = price_row
        return float(close_price), asset_rollup, str(datum)
    finally:
        conn.close()


def limited_strikes(
    values: list[float],
    max_count: int | None,
    spot: float | None,
    moneyness_min: float,
    moneyness_max: float,
) -> list[float]:
    strikes = sorted({float(v) for v in values})
    if spot and spot > 0:
        strikes = [s for s in strikes if moneyness_min <= s / spot <= moneyness_max]
    if max_count and len(strikes) > max_count:
        if spot and spot > 0:
            return sorted(strikes, key=lambda s: (abs(s - spot), s))[:max_count]
        return strikes[:max_count]
    return strikes


def weekday_for_yyyymmdd(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y%m%d").date().strftime("%A")
    except ValueError:
        return ""


def rows_from_info(
    contracts: list[dict[str, Any]],
    symbol: str,
    underlying_conid: str | int,
    month: str,
    cp_base_url: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for c in contracts:
        expiry = str(c.get("maturityDate") or "")
        strike = c.get("strike")
        if not expiry or strike is None:
            continue
        rows.append(
            {
                "symbol": symbol.upper(),
                "currency": c.get("currency") or "",
                "expiry": expiry,
                "strike": float(strike),
                "right": c.get("right") or "",
                "weekday": weekday_for_yyyymmdd(expiry),
                "exchange": c.get("exchange") or "SMART",
                "trading_class": c.get("tradingClass") or symbol.upper(),
                "multiplier": str(c.get("multiplier") or "100"),
                "chain_date": date.today().isoformat(),
                "chain_id": stamp,
                "source": "client_portal",
                "port": "",
                "underlying_conid": str(underlying_conid),
                "option_conid": str(c.get("conid") or ""),
                "month": month,
                "listing_exchange": c.get("listingExchange") or "",
                "valid_exchanges": c.get("validExchanges") or "",
                "description": c.get("desc2") or c.get("description") or "",
                "cp_base_url": cp_base_url,
            }
        )
    return rows


def potential_rows(
    symbol: str,
    currency: str,
    underlying_conid: str | int,
    month: str,
    strikes_by_right: dict[str, list[float]],
    cp_base_url: str,
    exchange: str,
) -> list[dict[str, Any]]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rows: list[dict[str, Any]] = []
    for right_key, right in [("call", "C"), ("put", "P")]:
        for strike in sorted({float(v) for v in strikes_by_right.get(right_key, [])}):
            rows.append(
                {
                    "symbol": symbol.upper(),
                    "currency": currency,
                    "expiry": month,
                    "strike": strike,
                    "right": right,
                    "weekday": "",
                    "exchange": exchange,
                    "trading_class": symbol.upper(),
                    "multiplier": "100",
                    "chain_date": date.today().isoformat(),
                    "chain_id": stamp,
                    "source": "client_portal_potential",
                    "port": "",
                    "underlying_conid": str(underlying_conid),
                    "option_conid": "",
                    "month": month,
                    "listing_exchange": "",
                    "valid_exchanges": "",
                    "description": "Potential strike from /secdef/strikes; not validated",
                    "cp_base_url": cp_base_url,
                }
            )
    return rows


def build_chain(args: argparse.Namespace) -> pd.DataFrame:
    client = CpClient(args.base_url, timeout=args.timeout)

    status = client.auth_status()
    log(f"auth/status: {json.dumps(status, ensure_ascii=False)}")
    if not status.get("authenticated") or not status.get("connected"):
        raise RuntimeError("Client Portal Gateway is not authenticated/connected")

    search_rows = client.search(args.symbol)
    log(f"search returned {len(search_rows)} row(s)")
    underlying, opt_section = pick_underlying(search_rows, args.symbol)
    conid = underlying.get("conid")
    currency = args.currency or underlying.get("currency") or "USD"
    months = parse_months(opt_section, args.max_months)

    log(
        f"selected underlying conid={conid}, symbol={underlying.get('symbol')}, "
        f"company={underlying.get('companyName') or underlying.get('companyHeader')}"
    )
    log(f"option months ({len(months)}): {months}")
    exchange_candidates = parse_exchanges(opt_section, args.exchange)
    log(f"exchange candidates={exchange_candidates}, validate={not args.no_validate}")

    spot = args.spot
    if args.spot_from_db:
        try:
            spot, asset_rollup, spot_date = load_spot_from_db(args.symbol)
            log(f"spot from DB: asset_rollup={asset_rollup}, date={spot_date}, close={spot:.4f}")
        except Exception as exc:
            if getattr(args, "require_spot", False):
                raise
            log(f"WARNING: could not read spot from DB; continuing without spot filter: {exc}")
            spot = None
    elif spot:
        log(f"spot from argument: {spot:.4f}")
    if spot:
        log(f"moneyness filter: {args.moneyness_min:.3f} <= K/S <= {args.moneyness_max:.3f}")

    all_rows: list[dict[str, Any]] = []
    for month_i, month in enumerate(months, start=1):
        log(f"month {month_i}/{len(months)}: {month} strikes")
        strikes = {"call": [], "put": []}
        selected_exchange = exchange_candidates[0]
        for exchange in exchange_candidates:
            strikes = client.strikes(conid, month, exchange=exchange)
            call_count = len(strikes.get("call") or [])
            put_count = len(strikes.get("put") or [])
            log(f"  exchange {exchange}: raw calls={call_count}, puts={put_count}")
            if call_count or put_count:
                selected_exchange = exchange
                break
        calls = limited_strikes(
            strikes.get("call") or [],
            args.max_strikes_per_side,
            spot,
            args.moneyness_min,
            args.moneyness_max,
        )
        puts = limited_strikes(
            strikes.get("put") or [],
            args.max_strikes_per_side,
            spot,
            args.moneyness_min,
            args.moneyness_max,
        )
        log(f"  selected exchange={selected_exchange}; filtered strikes: calls={len(calls)}, puts={len(puts)}")

        if args.no_validate:
            all_rows.extend(
                potential_rows(
                    args.symbol,
                    currency,
                    conid,
                    month,
                    {"call": calls, "put": puts},
                    args.base_url,
                    selected_exchange,
                )
            )
            continue

        for right, values in [("C", calls), ("P", puts)]:
            for idx, strike in enumerate(values, start=1):
                log(f"  validate {month} {right} strike {idx}/{len(values)}: {strike}")
                contracts = client.info(conid, month, strike, right, exchange=selected_exchange)
                rows = rows_from_info(contracts, args.symbol, conid, month, args.base_url)
                log(f"    -> {len(rows)} contract row(s)")
                all_rows.extend(rows)
                if args.sleep:
                    time.sleep(args.sleep)

    df = pd.DataFrame(all_rows)
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["option_conid", "expiry", "strike", "right"], keep="first")
    df = df.sort_values(["expiry", "strike", "right"], kind="stable").reset_index(drop=True)
    return df


def save(df: pd.DataFrame, symbol: str, output: str | None) -> Path:
    if output:
        path = Path(output)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = DATA_DIR / f"CHAIN_{symbol.upper()}_{date.today().isoformat()}_client_portal_{stamp}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    log(f"saved {len(df)} rows -> {path}")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch an option chain from IBKR Client Portal Gateway.")
    ap.add_argument("symbol", help="Underlying ticker, e.g. MSFT, META, INTC")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"CP Gateway base URL (default: {DEFAULT_BASE_URL})")
    ap.add_argument("--currency", default="", help="Optional currency override for potential/non-validated rows")
    ap.add_argument("--exchange", default="AUTO", help="Exchange for strikes/info, or AUTO from /secdef/search (default: AUTO)")
    ap.add_argument("--spot", type=float, default=None, help="Underlying spot used to select strikes around ATM")
    ap.add_argument("--spot-from-db", action="store_true", help="Read latest close from historical_data_correct")
    ap.add_argument("--require-spot", action="store_true", help="Fail when --spot-from-db cannot read a spot")
    ap.add_argument("--moneyness-min", type=float, default=0.90, help="Min K/S when spot is known (default: 0.90)")
    ap.add_argument("--moneyness-max", type=float, default=1.10, help="Max K/S when spot is known (default: 1.10)")
    ap.add_argument("--max-months", type=int, default=None, help="Limit number of option months for testing")
    ap.add_argument("--max-strikes-per-side", type=int, default=None, help="Limit call/put strikes per month for testing")
    ap.add_argument("--no-validate", action="store_true", help="Only save potential strikes; do not call /secdef/info")
    ap.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between /secdef/info calls")
    ap.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout seconds")
    ap.add_argument("--output", default="", help="Explicit parquet output path")
    args = ap.parse_args()

    df = build_chain(args)
    if df.empty:
        log("no rows returned; parquet not written")
        return 2

    log(f"final rows={len(df)}")
    if "expiry" in df:
        log(f"expiries={df['expiry'].nunique()} strikes={df['strike'].nunique()}")
    if "right" in df:
        log(f"rights={df['right'].value_counts(dropna=False).to_dict()}")
    save(df, args.symbol, args.output or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

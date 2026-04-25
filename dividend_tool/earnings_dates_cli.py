from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyodbc


ONNO_DB_PATH = Path(r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - ONNO.accdb")
STOCK_TYPES = {"aandeel", "stock", "etf", "fonds", "fund", ""}
EARNINGS_STOCK_TYPES = {"aandeel", "stock", ""}
US_EXCHANGES = {
    "NASDAQ",
    "NYSE",
    "AMEX",
    "ARCA",
    "BATS",
    "ISLAND",
    "IEX",
    "SMART",
}


@dataclass(frozen=True)
class AssetRecord:
    asset_rollup: str
    asset_type: str
    ib_symbol: str
    ib_currency: str
    exchange: str
    prim_exchange: str
    contractid: int | None


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def configure_yfinance_cache(yf_module) -> None:
    cache_dir = Path(__file__).resolve().parent / ".yfinance_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    if hasattr(yf_module, "set_tz_cache_location"):
        yf_module.set_tz_cache_location(str(cache_dir))
        log(f"yfinance cache directory: {cache_dir}")


def connect_access(db_path: Path) -> pyodbc.Connection:
    conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};"
    log(f"DB connect: {db_path}")
    return pyodbc.connect(conn_str)


def load_assets(db_path: Path, only_assets: set[str] | None = None, limit: int | None = None) -> list[AssetRecord]:
    sql = """
        SELECT
            asset_rollup,
            [type] AS asset_type,
            ib_symbol,
            ib_currency,
            exchange,
            prim_exchange,
            contractid
        FROM asset_rollup_data
        WHERE IIF(INCL_EXCL IS NULL, 0, INCL_EXCL) <> 0
          AND IIF(ib_symbol IS NULL, '', ib_symbol) <> ''
        ORDER BY asset_rollup
    """
    with connect_access(db_path) as conn:
        rows = conn.cursor().execute(sql).fetchall()

    assets: list[AssetRecord] = []
    for row in rows:
        asset_rollup = str(row.asset_rollup or "").strip()
        if only_assets and asset_rollup.upper() not in only_assets:
            continue
        contractid = None
        try:
            contractid = int(row.contractid) if row.contractid is not None else None
        except Exception:
            pass
        asset = AssetRecord(
            asset_rollup=asset_rollup,
            asset_type=str(row.asset_type or "").strip().lower(),
            ib_symbol=str(row.ib_symbol or "").strip(),
            ib_currency=str(row.ib_currency or "USD").strip() or "USD",
            exchange=str(row.exchange or "SMART").strip() or "SMART",
            prim_exchange=str(row.prim_exchange or "").strip(),
            contractid=contractid,
        )
        if asset.asset_type in STOCK_TYPES:
            assets.append(asset)
        else:
            log(f"SKIP {asset.asset_rollup}: type={asset.asset_type!r} is geen aandeel/ETF/fund")
        if limit is not None and len(assets) >= limit:
            break
    log(f"Assets geladen: {len(assets)}")
    return assets


def build_yfinance_candidates(asset: AssetRecord) -> list[str]:
    base = asset.ib_symbol.strip()
    if not base:
        return []

    exchange = (asset.prim_exchange or asset.exchange or "").upper().strip()
    suffix_map = {
        "AEB": ".AS",
        "ENEXT.AS": ".AS",
        "SBF": ".PA",
        "PAR": ".PA",
        "BVME": ".MI",
        "IBIS": ".DE",
        "XETRA": ".DE",
        "FWB": ".F",
        "LSE": ".L",
        "LON": ".L",
        "EBS": ".SW",
        "SWX": ".SW",
        "TSEJ": ".T",
        "TSE": ".T",
        "HKG": ".HK",
        "HKSE": ".HK",
    }
    candidates = []
    suffix = suffix_map.get(exchange, "")
    if suffix:
        candidates.append(f"{base}{suffix}")
    candidates.append(base)

    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def normalize_to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    with _suppress():
        return datetime.fromisoformat(text.replace("Z", "").split("+")[0]).date()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
        with _suppress():
            return datetime.strptime(text[:19] if "%H" in fmt else text, fmt).date()
    return None


def fetch_with_yfinance(symbol: str, limit: int, nasdaq_scan_days: int) -> tuple[str, date | None, str]:
    try:
        import yfinance as yf
    except Exception as exc:
        return "import_error", None, f"yfinance import mislukt: {exc}"

    configure_yfinance_cache(yf)
    try:
        ticker = yf.Ticker(symbol)
    except Exception as exc:
        return "ticker_error", None, f"Ticker object maken mislukt: {type(exc).__name__}: {exc}"

    status, next_date, message = _fetch_earnings_dates_endpoint(ticker, symbol, limit)
    if status == "ok":
        return status, next_date, message
    log(f"  fallback nodig na get_earnings_dates: status={status} message={message}")

    status2, next_date2, message2 = _fetch_calendar_endpoint(ticker, symbol)
    if status2 == "ok":
        return status2, next_date2, message2

    status3, next_date3, message3 = _fetch_yahoo_quote_endpoint(symbol)
    if status3 == "ok":
        return status3, next_date3, message3

    status4, next_date4, message4 = _fetch_nasdaq_earnings_endpoint(symbol)
    if status4 == "ok":
        return status4, next_date4, message4

    status5, next_date5, message5 = _scan_nasdaq_earnings_calendar(symbol, nasdaq_scan_days)
    if status5 == "ok":
        return status5, next_date5, message5
    final_status = "rate_limited" if "429" in f"{message} {message2} {message3}" else status3
    return final_status, next_date5, (
        f"get_earnings_dates: {message}; calendar: {message2}; "
        f"quote: {message3}; nasdaq: {message4}; nasdaq_scan: {message5}"
    )


def _fetch_earnings_dates_endpoint(ticker, symbol: str, limit: int) -> tuple[str, date | None, str]:
    log(f"  HTTP/yfinance request 1: Ticker({symbol!r}).get_earnings_dates(limit={limit})")
    try:
        df = ticker.get_earnings_dates(limit=limit)
    except Exception as exc:
        return "request_error", None, f"get_earnings_dates exception: {type(exc).__name__}: {exc}"

    if df is None:
        return "no_data", None, "get_earnings_dates response is None"
    if getattr(df, "empty", True):
        return "no_data", None, "get_earnings_dates DataFrame is leeg"

    try:
        log(f"  response 1: rows={len(df)} columns={list(df.columns)}")
        log(f"  response 1 index sample: {[str(x) for x in list(df.index)[:5]]}")
    except Exception as exc:
        log(f"  response 1 debug print mislukt: {exc}")

    return _choose_future_date_from_values(list(df.index), "get_earnings_dates index")


def _fetch_calendar_endpoint(ticker, symbol: str) -> tuple[str, date | None, str]:
    log(f"  HTTP/yfinance request 2: Ticker({symbol!r}).get_calendar()")
    try:
        calendar = ticker.get_calendar()
    except Exception as exc:
        return "calendar_error", None, f"get_calendar exception: {type(exc).__name__}: {exc}"

    if calendar is None:
        return "no_data", None, "get_calendar response is None"
    if isinstance(calendar, dict):
        log(f"  response 2: dict keys={list(calendar.keys())}")
        values: list[Any] = []
        for key in ("Earnings Date", "Earnings High", "Earnings Low"):
            raw = calendar.get(key)
            if isinstance(raw, (list, tuple, set)):
                values.extend(raw)
            else:
                values.append(raw)
        return _choose_future_date_from_values(values, "calendarEvents")

    log(f"  response 2: type={type(calendar).__name__}")
    try:
        if getattr(calendar, "empty", True):
            return "no_data", None, "get_calendar DataFrame is leeg"
        values: list[Any] = []
        for col in getattr(calendar, "columns", []):
            if "earning" in str(col).lower():
                values.extend(calendar[col].to_list())
        return _choose_future_date_from_values(values, "calendar DataFrame earnings columns")
    except Exception as exc:
        return "parse_error", None, f"calendar response niet parsebaar: {type(exc).__name__}: {exc}"


def _fetch_yahoo_quote_endpoint(symbol: str) -> tuple[str, date | None, str]:
    log(f"  HTTP/direct request 3: Yahoo quote endpoint for {symbol!r}")
    try:
        import requests
    except Exception as exc:
        return "import_error", None, f"requests import mislukt: {exc}"

    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    params = {
        "symbols": symbol,
        "fields": "earningsTimestamp,earningsTimestampStart,earningsTimestampEnd",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) earnings-dates-cli/1.0",
        "Accept": "application/json,text/plain,*/*",
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
    except Exception as exc:
        return "request_error", None, f"direct quote exception: {type(exc).__name__}: {exc}"

    log(f"  response 3: http_status={response.status_code} url={response.url}")
    if response.status_code == 429:
        return "rate_limited", None, "Yahoo quote endpoint gaf 429 Too Many Requests"
    if response.status_code >= 400:
        preview = response.text[:300].replace("\n", " ")
        return "request_error", None, f"Yahoo quote endpoint HTTP {response.status_code}: {preview}"

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        preview = response.text[:300].replace("\n", " ")
        return "parse_error", None, f"JSON parse mislukt: {exc}; preview={preview}"

    try:
        results = payload.get("quoteResponse", {}).get("result", [])
        log(f"  response 3: result_count={len(results)}")
        if not results:
            return "no_data", None, "quoteResponse.result is leeg"
        row = results[0]
        log(
            "  response 3 fields: "
            f"earningsTimestamp={row.get('earningsTimestamp')} "
            f"earningsTimestampStart={row.get('earningsTimestampStart')} "
            f"earningsTimestampEnd={row.get('earningsTimestampEnd')}"
        )
        values = [
            _date_from_unix(row.get("earningsTimestamp")),
            _date_from_unix(row.get("earningsTimestampStart")),
            _date_from_unix(row.get("earningsTimestampEnd")),
        ]
        return _choose_future_date_from_values(values, "Yahoo quote earningsTimestamp fields")
    except Exception as exc:
        return "parse_error", None, f"quote response niet parsebaar: {type(exc).__name__}: {exc}"


def _fetch_nasdaq_earnings_endpoint(symbol: str) -> tuple[str, date | None, str]:
    log(f"  HTTP/direct request 4: Nasdaq earnings calendar for {symbol!r}")
    try:
        import requests
    except Exception as exc:
        return "import_error", None, f"requests import mislukt: {exc}"

    url = "https://api.nasdaq.com/api/calendar/earnings"
    params = {"symbol": symbol}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) earnings-dates-cli/1.0",
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/",
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
    except Exception as exc:
        return "request_error", None, f"Nasdaq exception: {type(exc).__name__}: {exc}"

    log(f"  response 4: http_status={response.status_code} url={response.url}")
    if response.status_code == 429:
        return "rate_limited", None, "Nasdaq endpoint gaf 429 Too Many Requests"
    if response.status_code >= 400:
        preview = response.text[:300].replace("\n", " ")
        return "request_error", None, f"Nasdaq HTTP {response.status_code}: {preview}"

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        preview = response.text[:300].replace("\n", " ")
        return "parse_error", None, f"Nasdaq JSON parse mislukt: {exc}; preview={preview}"

    try:
        log(f"  response 4: top_keys={list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}")
        data = payload.get("data") if isinstance(payload, dict) else None
        if data is None:
            preview = response.text[:800].replace("\n", " ")
            return "no_data", None, f"Nasdaq data is null/ontbreekt; preview={preview}"
        if not isinstance(data, dict):
            return "parse_error", None, f"Nasdaq data heeft type {type(data).__name__}, verwacht dict"
        log(f"  response 4: data_keys={list(data.keys())}")
        rows = data.get("rows") or []
        log(f"  response 4: rows={len(rows)}")
        if not rows:
            return "no_data", None, f"Nasdaq data.rows is leeg; message={payload.get('message') if isinstance(payload, dict) else ''}"
        values: list[Any] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            log(
                "  response 4 row: "
                f"symbol={row.get('symbol')} date={row.get('date')} "
                f"time={row.get('time')} fiscalQuarterEnding={row.get('fiscalQuarterEnding')}"
            )
            values.append(row.get("date"))
        return _choose_future_date_from_values(values, "Nasdaq data.rows[].date")
    except Exception as exc:
        return "parse_error", None, f"Nasdaq response niet parsebaar: {type(exc).__name__}: {exc}"


def _scan_nasdaq_earnings_calendar(symbol: str, scan_days: int) -> tuple[str, date | None, str]:
    scan_days = max(0, int(scan_days))
    if scan_days <= 0:
        return "skipped", None, "Nasdaq datumscan uitgeschakeld"

    log(f"  HTTP/direct request 5: Nasdaq date scan for {symbol!r}, days={scan_days}")
    today = date.today()
    target_symbol = str(symbol or "").strip().upper()
    checked = 0
    rows_seen = 0
    last_error = ""

    for offset in range(scan_days + 1):
        day = today + timedelta(days=offset)
        status, rows, message = _fetch_nasdaq_earnings_for_date(day)
        checked += 1
        if status == "rate_limited":
            return status, None, f"Nasdaq datumscan gestopt op {day.isoformat()}: {message}"
        if status not in {"ok", "no_data"}:
            last_error = f"{day.isoformat()}: {message}"
            continue
        rows_seen += len(rows)
        for row in rows:
            row_symbol = str(row.get("symbol") or "").strip().upper()
            if row_symbol != target_symbol:
                continue
            raw_date = row.get("date") or day
            hit_date = normalize_to_date(raw_date) or day
            log(
                "  response 5 hit: "
                f"symbol={row.get('symbol')} date={row.get('date')} "
                f"time={row.get('time')} fiscalQuarterEnding={row.get('fiscalQuarterEnding')}"
            )
            return "ok", hit_date, f"gevonden via Nasdaq date scan op {day.isoformat()}"

        if offset in {0, 1, 7, 30, 60, 90, scan_days}:
            log(f"  response 5 progress: checked={checked} through={day.isoformat()} rows_seen={rows_seen}")

    msg = f"geen {target_symbol} gevonden in Nasdaq kalender voor komende {scan_days} dagen; checked={checked} rows_seen={rows_seen}"
    if last_error:
        msg += f"; last_error={last_error}"
    return "no_data", None, msg


def _fetch_nasdaq_earnings_for_date(day: date) -> tuple[str, list[dict[str, Any]], str]:
    try:
        import requests
    except Exception as exc:
        return "import_error", [], f"requests import mislukt: {exc}"

    url = "https://api.nasdaq.com/api/calendar/earnings"
    params = {"date": day.isoformat()}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) earnings-dates-cli/1.0",
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/",
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
    except Exception as exc:
        return "request_error", [], f"Nasdaq date {day.isoformat()} exception: {type(exc).__name__}: {exc}"

    if response.status_code == 429:
        return "rate_limited", [], "Nasdaq date endpoint gaf 429 Too Many Requests"
    if response.status_code >= 400:
        preview = response.text[:200].replace("\n", " ")
        return "request_error", [], f"Nasdaq date HTTP {response.status_code}: {preview}"

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        preview = response.text[:200].replace("\n", " ")
        return "parse_error", [], f"Nasdaq date JSON parse mislukt: {exc}; preview={preview}"

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return "no_data", [], "Nasdaq date data is null/ontbreekt"
    rows = data.get("rows") or []
    if not isinstance(rows, list):
        return "parse_error", [], f"Nasdaq date rows heeft type {type(rows).__name__}"
    return "ok", [row for row in rows if isinstance(row, dict)], f"rows={len(rows)}"


def is_us_earnings_asset(asset: AssetRecord) -> bool:
    asset_type = str(asset.asset_type or "").strip().lower()
    currency = str(asset.ib_currency or "").strip().upper()
    exchange = str(asset.exchange or "").strip().upper()
    prim_exchange = str(asset.prim_exchange or "").strip().upper()
    if asset_type not in EARNINGS_STOCK_TYPES:
        return False
    if currency != "USD":
        return False
    return exchange in US_EXCHANGES or prim_exchange in US_EXCHANGES


def run_nasdaq_us_batch(assets: list[AssetRecord], scan_days: int) -> list[dict[str, Any]]:
    us_assets = [asset for asset in assets if is_us_earnings_asset(asset)]
    symbol_to_assets: dict[str, list[AssetRecord]] = {}
    for asset in us_assets:
        symbol = str(asset.ib_symbol or "").strip().upper()
        if symbol:
            symbol_to_assets.setdefault(symbol, []).append(asset)

    wanted_symbols = set(symbol_to_assets)
    found: dict[str, dict[str, Any]] = {}
    today = date.today()
    log("START Nasdaq batch scan")
    log(f"US earnings assets: {len(us_assets)} | unieke symbols: {len(wanted_symbols)} | scan_days={scan_days}")
    log("Communicatie: per datum 1 call naar https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD")

    checked = 0
    rows_seen = 0
    for offset in range(max(0, int(scan_days)) + 1):
        day = today + timedelta(days=offset)
        status, rows, message = _fetch_nasdaq_earnings_for_date(day)
        checked += 1
        if status == "rate_limited":
            log(f"STOP rate limited op {day.isoformat()}: {message}")
            break
        if status not in {"ok", "no_data"}:
            log(f"WARN {day.isoformat()}: {status} {message}")
            continue
        rows_seen += len(rows)
        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol not in wanted_symbols or symbol in found:
                continue
            hit_date = normalize_to_date(row.get("date")) or day
            found[symbol] = {
                "symbol": symbol,
                "date": hit_date.isoformat(),
                "source_date": day.isoformat(),
                "time": row.get("time") or "",
                "fiscalQuarterEnding": row.get("fiscalQuarterEnding") or "",
                "name": row.get("name") or "",
            }
        if offset in {0, 1, 7, 14, 30, 60, 90, scan_days}:
            log(f"progress: checked={checked} through={day.isoformat()} rows_seen={rows_seen} found_symbols={len(found)}")
        if len(found) >= len(wanted_symbols):
            log("Alle gevraagde symbols gevonden; scan stopt vroeg.")
            break

    results: list[dict[str, Any]] = []
    for asset in us_assets:
        symbol = str(asset.ib_symbol or "").strip().upper()
        hit = found.get(symbol)
        if hit:
            results.append(
                {
                    "asset": asset.asset_rollup,
                    "symbol": symbol,
                    "status": "ok",
                    "date": hit["date"],
                    "source": "nasdaq_date_scan",
                    "message": f"time={hit['time'] or '-'} fiscalQuarterEnding={hit['fiscalQuarterEnding'] or '-'} source_date={hit['source_date']}",
                }
            )
        else:
            results.append(
                {
                    "asset": asset.asset_rollup,
                    "symbol": symbol,
                    "status": "no_data",
                    "date": "",
                    "source": "nasdaq_date_scan",
                    "message": f"niet gevonden in komende {scan_days} dagen",
                }
            )
    log(f"KLAAR Nasdaq batch: checked_days={checked} rows_seen={rows_seen} found_assets={sum(1 for r in results if r['status'] == 'ok')} missing={sum(1 for r in results if r['status'] != 'ok')}")
    return results


def _date_from_unix(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value)).date()
    except Exception:
        return None


def _choose_future_date_from_values(values: list[Any], source: str) -> tuple[str, date | None, str]:
    today = date.today()
    dates = [normalize_to_date(value) for value in values]
    future_dates = sorted(d for d in dates if d is not None and d >= today)
    if future_dates:
        return "ok", future_dates[0], f"gekozen uit {source}: {future_dates[0].isoformat()}"

    valid_dates = sorted(d for d in dates if d is not None)
    if valid_dates:
        return "past_only", None, f"wel datums ontvangen uit {source}, maar niets vanaf vandaag; laatste={valid_dates[-1].isoformat()}"
    return "parse_error", None, f"{source} had geen parsebare datums"


def diagnose_asset(asset: AssetRecord, earnings_limit: int, nasdaq_scan_days: int) -> dict[str, Any]:
    log("")
    log(f"ASSET {asset.asset_rollup}")
    log(
        "  input: "
        f"type={asset.asset_type} ib_symbol={asset.ib_symbol} "
        f"currency={asset.ib_currency} exchange={asset.exchange} "
        f"prim_exchange={asset.prim_exchange or '-'} conid={asset.contractid or '-'}"
    )
    candidates = build_yfinance_candidates(asset)
    log(f"  yfinance candidates: {candidates or 'geen'}")
    if not candidates:
        return {"asset": asset.asset_rollup, "status": "no_candidates", "date": "", "symbol": "", "message": "geen candidates"}

    last_status = "no_data"
    last_message = ""
    for symbol in candidates:
        status, next_date, message = fetch_with_yfinance(symbol, earnings_limit, nasdaq_scan_days)
        log(f"  result {symbol}: status={status} next_date={next_date.isoformat() if next_date else '-'} message={message}")
        if status == "ok" and next_date is not None:
            return {
                "asset": asset.asset_rollup,
                "status": "ok",
                "date": next_date.isoformat(),
                "symbol": symbol,
                "message": message,
            }
        last_status = status
        last_message = message
        time.sleep(0.2)

    return {
        "asset": asset.asset_rollup,
        "status": last_status,
        "date": "",
        "symbol": "",
        "message": last_message,
    }


class _suppress:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnoseer earnings dates via yfinance voor assets uit ONNO asset_rollup_data."
    )
    parser.add_argument("--db", default=str(ONNO_DB_PATH), help="Pad naar ONNO Access database.")
    parser.add_argument("--asset", action="append", help="Filter op asset_rollup. Mag meerdere keren.")
    parser.add_argument("--limit-assets", type=int, default=None, help="Max aantal assets om te testen.")
    parser.add_argument("--earnings-limit", type=int, default=12, help="Aantal yfinance earnings rows per symbool.")
    parser.add_argument("--nasdaq-scan-days", type=int, default=120, help="Aantal dagen vooruit scannen in Nasdaq earnings calendar.")
    parser.add_argument("--batch-nasdaq-us", action="store_true", help="Batchtest: scan Nasdaq per datum en match alle US-aandelen uit ONNO.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    only_assets = {str(a).strip().upper() for a in args.asset or [] if str(a).strip()} or None

    log("START earnings-date diagnose")
    log("Communicatie-overzicht:")
    log("  1. Leest asset_rollup_data uit ONNO via lokale Access ODBC.")
    log("  2. Bouwt per asset een of meer Yahoo/yfinance symbolen.")
    log("  3. yfinance doet HTTP requests naar Yahoo Finance endpoints.")
    log("  4. Dit script schrijft niets naar de database; output is alleen CLI.")

    try:
        assets = load_assets(db_path, only_assets=only_assets, limit=args.limit_assets)
    except Exception as exc:
        log(f"FATAL: assets laden mislukt: {type(exc).__name__}: {exc}")
        return 1

    if args.batch_nasdaq_us:
        results = run_nasdaq_us_batch(assets, args.nasdaq_scan_days)
    else:
        results = [diagnose_asset(asset, args.earnings_limit, args.nasdaq_scan_days) for asset in assets]

    log("")
    log("SAMENVATTING")
    for result in results:
        log(
            f"  {result['asset']}: status={result['status']} "
            f"date={result['date'] or '-'} symbol={result['symbol'] or '-'} "
            f"message={result['message']}"
        )
    ok_count = sum(1 for result in results if result["status"] == "ok")
    log(f"KLAAR: assets={len(results)} ok={ok_count} niet_ok={len(results) - ok_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import random
import sys
import threading
import time
from dataclasses import dataclass

import pandas as pd
import pyodbc
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


CONN_STR = (
    r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
    r"DBQ=C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - STOCKDATA.accdb"
)
TEMP_TABLE = "temp_stock_prices_temp"
INFO_STATUS_CODES = {2103, 2104, 2105, 2106, 2107, 2108, 2158, 2159, 1100, 1101, 1102}


@dataclass
class IndexTarget:
    asset_rollup: str
    symbol: str
    currency: str
    exchange: str
    primary_exchange: str
    contract_id: int | None


class IndexHistApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.done = threading.Event()
        self.error_text: str | None = None
        self.rows: list[dict] = []

    def error(self, reqId, *args):  # noqa: N802
        code = None
        msg = ""
        if len(args) == 2:
            code, msg = args
        elif len(args) == 3:
            code, msg, _ = args
        elif len(args) >= 4:
            _, code, msg, _ = args[:4]
        else:
            return

        try:
            code_int = int(code)
        except Exception:
            code_int = None

        if code_int in INFO_STATUS_CODES:
            return
        if isinstance(msg, str) and "connection is OK" in msg:
            return

        self.error_text = f"IB error {code} (reqId={reqId}): {msg}"
        self.done.set()

    def historicalData(self, reqId, bar):  # noqa: N802
        self.rows.append(
            {
                "date": str(bar.date),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
                "wap": float((float(bar.high) + float(bar.low) + float(bar.close)) / 3.0),
            }
        )

    def historicalDataEnd(self, reqId, start, end):  # noqa: N802
        self.done.set()


def load_index_targets(asset_filter: set[str] | None = None) -> list[IndexTarget]:
    sql = """
        SELECT asset_rollup, ib_symbol, ib_currency, exchange, prim_exchange, contractid
        FROM asset_rollup_data
        WHERE INCL_EXCL = 1
          AND LCASE([type]) = 'index'
          AND ib_symbol IS NOT NULL
          AND ib_currency IS NOT NULL
    """
    with pyodbc.connect(CONN_STR) as conn:
        df = pd.read_sql(sql, conn)
    if df.empty:
        return []

    df = df.fillna("")
    targets: list[IndexTarget] = []
    for _, row in df.iterrows():
        asset_rollup = str(row.get("asset_rollup", "")).strip()
        if not asset_rollup:
            continue
        if asset_filter and asset_rollup.upper() not in asset_filter:
            continue
        symbol = str(row.get("ib_symbol", "")).strip()
        currency = str(row.get("ib_currency", "")).strip()
        exchange = str(row.get("exchange", "")).strip()
        primary_exchange = str(row.get("prim_exchange", "")).strip()
        raw_contract_id = row.get("contractid", None)
        contract_id = None
        try:
            if raw_contract_id is not None and str(raw_contract_id).strip() != "":
                contract_id = int(float(raw_contract_id))
        except Exception:
            contract_id = None
        if not symbol or not currency:
            continue
        if not exchange and primary_exchange:
            exchange = primary_exchange
        if not exchange:
            continue
        targets.append(
            IndexTarget(
                asset_rollup=asset_rollup,
                symbol=symbol,
                currency=currency,
                exchange=exchange,
                primary_exchange=primary_exchange,
                contract_id=contract_id,
            )
        )
    return targets


def fetch_target(
    target: IndexTarget,
    days: int,
    client_id: int,
    exchange_override: str | None = None,
    use_conid: bool = False,
) -> pd.DataFrame:
    app = IndexHistApp()
    app.connect("127.0.0.1", 7496, clientId=client_id)
    t = threading.Thread(target=app.run, daemon=True)
    t.start()
    time.sleep(1.0)

    try:
        app.reqMarketDataType(3)
    except Exception:
        pass

    c = Contract()
    c.symbol = target.symbol
    c.secType = "IND"
    c.exchange = exchange_override or target.exchange
    c.currency = target.currency
    if use_conid and target.contract_id and target.contract_id > 0:
        c.conId = int(target.contract_id)
    if target.primary_exchange:
        c.primaryExchange = target.primary_exchange

    duration_str = f"{days} D"
    if days > 365:
        years = max(int(round(days / 365.0)), 1)
        duration_str = f"{years} Y"

    app.reqHistoricalData(
        reqId=1,
        contract=c,
        endDateTime="",
        durationStr=duration_str,
        barSizeSetting="1 day",
        whatToShow="TRADES",
        useRTH=0,
        formatDate=2,
        keepUpToDate=False,
        chartOptions=[],
    )

    app.done.wait(timeout=60.0)
    app.disconnect()
    t.join(timeout=2.0)
    time.sleep(0.2)

    if app.error_text:
        raise RuntimeError(app.error_text)
    df = pd.DataFrame(app.rows)
    if df.empty:
        return df
    df = df.sort_values("date").reset_index(drop=True)
    df["symbol"] = target.symbol
    df["asset_rollup"] = target.asset_rollup
    return df[["date", "symbol", "asset_rollup", "open", "high", "low", "close", "volume", "wap"]]


def save_df_to_access_temp(df: pd.DataFrame) -> int:
    if df.empty:
        print("Index fetch: no rows to write.")
        return 0

    out = df.copy().rename(columns={"date": "datum"})
    s = out["datum"].astype(str)
    parsed = pd.to_datetime(s, errors="coerce")
    mask_nat = parsed.isna()
    if mask_nat.any():
        parsed2 = pd.to_datetime(s[mask_nat], format="%Y%m%d", errors="coerce")
        parsed[mask_nat] = parsed2
    mask_nat = parsed.isna()
    if mask_nat.any():
        parsed3 = pd.to_datetime(s[mask_nat], format="%Y%m%d %H:%M:%S", errors="coerce")
        parsed[mask_nat] = parsed3
    out["datum"] = parsed.dt.to_pydatetime()
    out = out[["datum", "symbol", "asset_rollup", "open", "high", "low", "close", "volume", "wap"]]

    create_sql = f"""
        CREATE TABLE {TEMP_TABLE} (
            datum DATE,
            symbol TEXT(255),
            asset_rollup TEXT(255),
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            wap DOUBLE
        )
    """
    insert_sql = f"""
        INSERT INTO {TEMP_TABLE}
        (datum, symbol, asset_rollup, open, high, low, close, volume, wap)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = [tuple(row) for row in out.to_numpy()]
    with pyodbc.connect(CONN_STR) as conn:
        cur = conn.cursor()
        try:
            cur.execute(create_sql)
            conn.commit()
        except pyodbc.Error:
            pass
        cur.executemany(insert_sql, rows)
        conn.commit()
    print(f"Index fetch: inserted {len(rows)} rows into {TEMP_TABLE}.")
    return len(rows)


def parse_args() -> tuple[int, set[str] | None]:
    days = 5
    if len(sys.argv) > 1:
        try:
            days = max(int(sys.argv[1]), 1)
        except Exception:
            days = 5

    asset_filter = None
    if len(sys.argv) > 2 and str(sys.argv[2]).strip():
        asset_filter = {x.strip().upper() for x in str(sys.argv[2]).split(",") if x.strip()}
    return days, asset_filter


def exchange_candidates_for_target(target: IndexTarget) -> list[str]:
    candidates: list[str] = []
    ex = (target.exchange or "").strip().upper()
    pex = (target.primary_exchange or "").strip().upper()
    if ex:
        candidates.append(ex)
    if pex and pex not in candidates:
        candidates.append(pex)

    # SMART is often invalid for IND contracts; add symbol-based fallbacks.
    sym = (target.symbol or "").strip().upper()
    hints = {
        "EOE": ["FTA", "AEB"],
        "AEX": ["FTA", "AEB"],
        "DAX": ["EUREX", "DTB"],
        "NDX": ["NASDAQ", "CBOE"],
        "TSX": ["TSE"],
        "TXCX": ["TSE"],
    }.get(sym, [])
    for h in hints:
        if h not in candidates:
            candidates.append(h)

    # Last fallback
    if "SMART" not in candidates:
        candidates.append("SMART")
    return candidates


def main() -> int:
    days, asset_filter = parse_args()
    targets = load_index_targets(asset_filter=asset_filter)
    if not targets:
        print("Index fetch: no index targets found (type='index' and INCL_EXCL=1).")
        return 0

    all_frames: list[pd.DataFrame] = []
    failed = 0
    for i, target in enumerate(targets):
        candidates = exchange_candidates_for_target(target)

        df = None
        last_err = None
        for ex in candidates:
            for use_conid in (False, True):
                if use_conid and not (target.contract_id and target.contract_id > 0):
                    continue
                for attempt in (1, 2):
                    try:
                        cid = random.randint(1000, 9999) + (i * 100) + attempt
                        df = fetch_target(
                            target,
                            days=days,
                            client_id=cid,
                            exchange_override=ex,
                            use_conid=use_conid,
                        )
                        if df is not None and not df.empty:
                            break
                    except Exception as exc:
                        last_err = exc
                        time.sleep(1.0)
                        continue
                if df is not None and not df.empty:
                    break
            if df is not None and not df.empty:
                break

        if df is None or df.empty:
            failed += 1
            print(f"Index fetch FAILED [{target.asset_rollup}/{target.symbol}]: {last_err or 'No data'}")
            continue

        print(
            f"Index fetch OK [{target.asset_rollup}/{target.symbol}] rows={len(df)} "
            f"range={df['date'].iloc[0]}->{df['date'].iloc[-1]}"
        )
        all_frames.append(df)
        time.sleep(1.0)

    if not all_frames:
        print("Index fetch: no rows collected for any index.")
        return 0

    merged = pd.concat(all_frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["date", "symbol"], keep="last").reset_index(drop=True)
    save_df_to_access_temp(merged)
    print(f"Index fetch finished. assets_ok={len(all_frames)} assets_failed={failed} rows={len(merged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

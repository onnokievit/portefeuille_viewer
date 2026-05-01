from __future__ import annotations

import argparse
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pyodbc
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portefeuille_viewer.config import get_stockdata_db_path
from portefeuille_viewer.data.repository import get_stockdata_connection


DEFAULT_DB = get_stockdata_db_path()
TEMP_TABLE = "temp_futures_continuous_close"
HDC_TABLE = "historical_data_correct"
INFO_CODES = {1100, 1101, 1102, 2103, 2104, 2105, 2106, 2107, 2108, 2158, 2159}


@dataclass
class FutContractInfo:
    conid: int
    symbol: str
    local_symbol: str
    trading_class: str
    exchange: str
    currency: str
    expiry: date
    multiplier: str


class IBSyncApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self._lock = threading.Lock()
        self._next_req_id = 9000
        self._errors: list[str] = []
        self._cd_done: dict[int, threading.Event] = {}
        self._cd_rows: dict[int, list[FutContractInfo]] = {}
        self._hist_done: dict[int, threading.Event] = {}
        self._hist_rows: dict[int, list[dict]] = {}

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def error(self, reqId, *args):  # noqa: N802
        code = None
        msg = ""
        if len(args) == 2:
            code, msg = args
        elif len(args) == 3:
            code, msg, _ = args
        elif len(args) >= 4:
            _, code, msg, _ = args[:4]
        if code is None:
            return
        try:
            code_i = int(code)
        except Exception:
            code_i = None
        if code_i in INFO_CODES:
            return
        text = f"IB error reqId={reqId} code={code}: {msg}"
        self._errors.append(text)
        # Mark done to avoid hanging requests on errors.
        if reqId in self._cd_done:
            self._cd_done[reqId].set()
        if reqId in self._hist_done:
            self._hist_done[reqId].set()

    def next_req_id(self) -> int:
        with self._lock:
            self._next_req_id += 1
            return self._next_req_id

    # ---- contractDetails handlers ----
    def contractDetails(self, reqId, contractDetails):  # noqa: N802
        c = contractDetails.contract
        exp = parse_expiry(getattr(c, "lastTradeDateOrContractMonth", ""))
        if exp is None:
            return
        row = FutContractInfo(
            conid=int(getattr(c, "conId", 0) or 0),
            symbol=str(getattr(c, "symbol", "") or ""),
            local_symbol=str(getattr(c, "localSymbol", "") or ""),
            trading_class=str(getattr(c, "tradingClass", "") or ""),
            exchange=str(getattr(c, "exchange", "") or ""),
            currency=str(getattr(c, "currency", "") or ""),
            expiry=exp,
            multiplier=str(getattr(c, "multiplier", "") or ""),
        )
        self._cd_rows.setdefault(reqId, []).append(row)

    def contractDetailsEnd(self, reqId):  # noqa: N802
        ev = self._cd_done.get(reqId)
        if ev:
            ev.set()

    # ---- historicalData handlers ----
    def historicalData(self, reqId, bar):  # noqa: N802
        self._hist_rows.setdefault(reqId, []).append(
            {
                "date": normalize_bar_date(str(bar.date)),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
        )

    def historicalDataEnd(self, reqId, start, end):  # noqa: N802
        ev = self._hist_done.get(reqId)
        if ev:
            ev.set()

    # ---- sync request wrappers ----
    def request_fut_contracts(self, symbol: str, exchange: str, currency: str, timeout_sec: float = 30.0) -> list[FutContractInfo]:
        req_id = self.next_req_id()
        self._cd_done[req_id] = threading.Event()
        self._cd_rows[req_id] = []
        c = Contract()
        c.secType = "FUT"
        c.symbol = symbol
        c.exchange = exchange
        c.currency = currency
        self.reqContractDetails(req_id, c)
        self._cd_done[req_id].wait(timeout=timeout_sec)
        rows = self._cd_rows.pop(req_id, [])
        self._cd_done.pop(req_id, None)
        return rows

    def request_daily_history(
        self,
        conid: int,
        exchange: str,
        currency: str,
        duration: str,
        what_to_show: str = "TRADES",
        timeout_sec: float = 45.0,
    ) -> list[dict]:
        req_id = self.next_req_id()
        self._hist_done[req_id] = threading.Event()
        self._hist_rows[req_id] = []

        c = Contract()
        c.secType = "FUT"
        c.conId = int(conid)
        c.exchange = exchange
        c.currency = currency

        self.reqHistoricalData(
            reqId=req_id,
            contract=c,
            endDateTime="",
            durationStr=duration,
            barSizeSetting="1 day",
            whatToShow=what_to_show,
            useRTH=0,
            formatDate=2,
            keepUpToDate=False,
            chartOptions=[],
        )
        self._hist_done[req_id].wait(timeout=timeout_sec)
        rows = self._hist_rows.pop(req_id, [])
        self._hist_done.pop(req_id, None)
        return rows


def parse_expiry(raw: str) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    # can be YYYYMM or YYYYMMDD
    try:
        if len(s) >= 8:
            return datetime.strptime(s[:8], "%Y%m%d").date()
        if len(s) >= 6:
            return datetime.strptime(s[:6] + "01", "%Y%m%d").date()
    except Exception:
        return None
    return None


def normalize_bar_date(raw: str) -> date:
    s = (raw or "").strip()
    # Prefer YYYYMMDD when present (IB can return this even with formatDate=2).
    if len(s) >= 8 and s[:8].isdigit():
        try:
            return datetime.strptime(s[:8], "%Y%m%d").date()
        except Exception:
            pass
    # formatDate=2 can also return epoch seconds
    if s.isdigit():
        return datetime.utcfromtimestamp(int(s)).date()
    # fallback YYYYMMDD
    return datetime.strptime(s[:8], "%Y%m%d").date()


def choose_conid_for_date(
    day: date,
    roll_days: int,
    contracts: list[FutContractInfo],
    bars_by_conid: dict[int, dict[date, dict]],
) -> int | None:
    eligible = []
    for c in contracts:
        if day not in bars_by_conid.get(c.conid, {}):
            continue
        if day <= (c.expiry - timedelta(days=roll_days)):
            eligible.append(c)
    if eligible:
        eligible.sort(key=lambda x: x.expiry)
        return eligible[0].conid
    # fallback: any contract with a bar on this day, nearest expiry first
    fallback = [c for c in contracts if day in bars_by_conid.get(c.conid, {})]
    if not fallback:
        return None
    fallback.sort(key=lambda x: x.expiry)
    return fallback[0].conid


def build_continuous_series(
    contracts: list[FutContractInfo],
    bars_by_conid: dict[int, dict[date, dict]],
    start_date: date,
    end_date: date,
    roll_days: int,
    back_adjust: bool,
) -> pd.DataFrame:
    meta_by_conid = {c.conid: c for c in contracts}
    all_days = sorted(
        {
            d
            for conid_bars in bars_by_conid.values()
            for d in conid_bars.keys()
            if start_date <= d <= end_date
        }
    )
    rows: list[dict] = []
    prev_conid = None
    for d in all_days:
        conid = choose_conid_for_date(d, roll_days, contracts, bars_by_conid)
        if conid is None:
            continue
        bar = bars_by_conid[conid][d]
        open_raw = float(bar["open"])
        high_raw = float(bar["high"])
        low_raw = float(bar["low"])
        close_raw = float(bar["close"])
        volume_raw = float(bar.get("volume", 0.0) or 0.0)
        wap_raw = (high_raw + low_raw + close_raw) / 3.0
        roll_flag = 1 if prev_conid is not None and conid != prev_conid else 0
        rows.append(
            {
                "datum": d,
                "source_conid": conid,
                "source_local_symbol": meta_by_conid.get(conid).local_symbol if meta_by_conid.get(conid) else "",
                "source_expiry": meta_by_conid.get(conid).expiry if meta_by_conid.get(conid) else None,
                "open_raw": open_raw,
                "high_raw": high_raw,
                "low_raw": low_raw,
                "close_raw": close_raw,
                "volume_raw": volume_raw,
                "wap_raw": wap_raw,
                "roll_flag": roll_flag,
            }
        )
        prev_conid = conid

    if not rows:
        return pd.DataFrame(
            columns=[
                "datum",
                "source_conid",
                "source_local_symbol",
                "source_expiry",
                "open_raw",
                "high_raw",
                "low_raw",
                "close_raw",
                "volume_raw",
                "wap_raw",
                "roll_flag",
                "adj_factor",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "wap",
            ]
        )

    df = pd.DataFrame(rows).sort_values("datum").reset_index(drop=True)
    df["adj_factor"] = 1.0
    df["open"] = df["open_raw"]
    df["high"] = df["high_raw"]
    df["low"] = df["low_raw"]
    df["close"] = df["close_raw"]
    df["volume"] = df["volume_raw"]
    df["wap"] = df["wap_raw"]
    if not back_adjust:
        return df

    # Back-adjust past to latest regime by multiplying dates before each roll.
    conid_bars = bars_by_conid
    rolls = df.index[df["roll_flag"] == 1].tolist()
    for idx in rolls:
        new_conid = int(df.at[idx, "source_conid"])
        old_conid = int(df.at[idx - 1, "source_conid"])
        roll_day = df.at[idx, "datum"]
        prev_day = df.at[idx - 1, "datum"]
        ref_day = prev_day
        old_px = (conid_bars.get(old_conid, {}).get(ref_day) or {}).get("close")
        new_px = (conid_bars.get(new_conid, {}).get(ref_day) or {}).get("close")
        if old_px is None or new_px is None:
            old_px = (conid_bars.get(old_conid, {}).get(roll_day) or {}).get("close")
            new_px = (conid_bars.get(new_conid, {}).get(roll_day) or {}).get("close")
            ref_day = roll_day
        if old_px is None or new_px is None or float(old_px) == 0.0:
            continue
        ratio = float(new_px) / float(old_px)
        df.loc[df["datum"] < roll_day, "adj_factor"] *= ratio

    df["open"] = df["open_raw"] * df["adj_factor"]
    df["high"] = df["high_raw"] * df["adj_factor"]
    df["low"] = df["low_raw"] * df["adj_factor"]
    df["close"] = df["close_raw"] * df["adj_factor"]
    df["volume"] = df["volume_raw"]
    df["wap"] = df["wap_raw"] * df["adj_factor"]
    return df


def ensure_temp_table(conn, table_name: str) -> None:
    cur = conn.cursor()
    create_sql = f"""
        CREATE TABLE {table_name} (
            datum DATE,
            asset_rollup TEXT(64),
            root_symbol TEXT(32),
            source_conid LONG,
            source_local_symbol TEXT(32),
            source_expiry DATE,
            open_raw DOUBLE,
            high_raw DOUBLE,
            low_raw DOUBLE,
            close_raw DOUBLE,
            volume_raw DOUBLE,
            wap_raw DOUBLE,
            adj_factor DOUBLE,
            [open] DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            wap DOUBLE,
            roll_flag BYTE,
            updated_at DATETIME
        )
    """
    required_cols = {
        "datum",
        "asset_rollup",
        "root_symbol",
        "source_conid",
        "source_local_symbol",
        "source_expiry",
        "open_raw",
        "high_raw",
        "low_raw",
        "close_raw",
        "volume_raw",
        "wap_raw",
        "adj_factor",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "wap",
        "roll_flag",
        "updated_at",
    }
    try:
        cur.execute(create_sql)
        conn.commit()
        return
    except pyodbc.Error:
        pass

    existing_cols = set()
    try:
        for c in cur.columns(table=table_name):
            existing_cols.add(str(c.column_name).strip().lower())
    except Exception:
        existing_cols = set()

    if required_cols.issubset(existing_cols):
        return

    # Temp table has incompatible old schema: recreate.
    cur.execute(f"DROP TABLE {table_name}")
    conn.commit()
    cur.execute(create_sql)
    conn.commit()


def write_to_temp_table(db_path: str, table_name: str, asset_rollup: str, root_symbol: str, df: pd.DataFrame) -> int:
    conn = get_stockdata_connection() if db_path == get_stockdata_db_path() else pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")
    ensure_temp_table(conn, table_name)
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {table_name} WHERE asset_rollup=?", asset_rollup)
    conn.commit()
    if df.empty:
        conn.close()
        return 0

    now = datetime.now()
    rows = [
        (
            row["datum"],
            asset_rollup,
            root_symbol,
            int(row["source_conid"]),
            str(row.get("source_local_symbol") or ""),
            row.get("source_expiry"),
            float(row["open_raw"]),
            float(row["high_raw"]),
            float(row["low_raw"]),
            float(row["close_raw"]),
            float(row["volume_raw"]),
            float(row["wap_raw"]),
            float(row["adj_factor"]),
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            float(row["volume"]),
            float(row["wap"]),
            int(row["roll_flag"]),
            now,
        )
        for _, row in df.iterrows()
    ]
    cur.executemany(
        f"""
        INSERT INTO {table_name}
        (datum, asset_rollup, root_symbol, source_conid, source_local_symbol, source_expiry, open_raw, high_raw, low_raw, close_raw, volume_raw, wap_raw, adj_factor, [open], high, low, close, volume, wap, roll_flag, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def upsert_to_historical_data_correct(db_path: str, hdc_table: str, asset_rollup: str, symbol: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    conn = get_stockdata_connection() if db_path == get_stockdata_db_path() else pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {hdc_table} WHERE asset_rollup=?", asset_rollup)
    rows = [
        (
            row["datum"],
            symbol,
            asset_rollup,
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            float(row["volume"]),
            float(row["wap"]),
        )
        for _, row in df.iterrows()
    ]
    cur.executemany(
        f"""
        INSERT INTO {hdc_table}
        (datum, symbol, asset_rollup, [open], high, low, close, volume, wap)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build continuous daily close for a futures root (standalone).")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7496)
    p.add_argument("--client-id", type=int, default=91)
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--asset-rollup", default="MBITCOIN")
    p.add_argument("--root-symbol", default="MBT")
    p.add_argument("--exchange", default="CME")
    p.add_argument("--currency", default="USD")
    p.add_argument("--years", type=int, default=2)
    p.add_argument("--roll-days", type=int, default=5)
    p.add_argument("--duration", default="", help="Optional IB duration override, e.g. '3 Y'")
    p.add_argument("--back-adjust", type=int, choices=[0, 1], default=1)
    p.add_argument("--table", default=TEMP_TABLE)
    p.add_argument("--write-hdc", type=int, choices=[0, 1], default=1)
    p.add_argument("--hdc-table", default=HDC_TABLE)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    end_date = date.today()
    start_date = end_date - timedelta(days=max(args.years, 1) * 365)
    duration = args.duration or f"{max(args.years + 1, 2)} Y"

    app = IBSyncApp()
    app.connect(args.host, args.port, clientId=args.client_id)
    t = threading.Thread(target=app.run, daemon=True)
    t.start()
    if not app.ready.wait(timeout=8.0):
        app.disconnect()
        raise RuntimeError("IB connection not ready (no nextValidId).")

    with threading.Lock():
        pass
    try:
        app.reqMarketDataType(3)
    except Exception:
        pass

    contracts = app.request_fut_contracts(args.root_symbol, args.exchange, args.currency, timeout_sec=30.0)
    contracts = [c for c in contracts if c.conid > 0]
    contracts.sort(key=lambda x: x.expiry)
    if not contracts:
        app.disconnect()
        raise RuntimeError("No FUT contracts found for root.")

    # Keep contracts that can overlap the requested window.
    window_start = start_date - timedelta(days=40)
    window_end = end_date + timedelta(days=40)
    contracts = [c for c in contracts if c.expiry >= window_start and c.expiry <= window_end]
    if not contracts:
        app.disconnect()
        raise RuntimeError("No FUT contracts in target window.")

    bars_by_conid: dict[int, dict[date, dict]] = {}
    for c in contracts:
        bars = app.request_daily_history(
            conid=c.conid,
            exchange=c.exchange or args.exchange,
            currency=c.currency or args.currency,
            duration=duration,
            what_to_show="TRADES",
            timeout_sec=60.0,
        )
        day_bars = {}
        for b in bars:
            d = b.get("date")
            if not isinstance(d, date):
                continue
            if b.get("close") is None:
                continue
            day_bars[d] = {
                "open": float(b.get("open", 0.0) or 0.0),
                "high": float(b.get("high", 0.0) or 0.0),
                "low": float(b.get("low", 0.0) or 0.0),
                "close": float(b.get("close", 0.0) or 0.0),
                "volume": float(b.get("volume", 0.0) or 0.0),
            }
        if day_bars:
            bars_by_conid[c.conid] = day_bars
        time.sleep(0.1)

    app.disconnect()
    time.sleep(0.2)

    if not bars_by_conid:
        raise RuntimeError("No historical bars returned for any contract.")

    df = build_continuous_series(
        contracts=contracts,
        bars_by_conid=bars_by_conid,
        start_date=start_date,
        end_date=end_date,
        roll_days=max(args.roll_days, 0),
        back_adjust=bool(args.back_adjust),
    )

    inserted = write_to_temp_table(
        db_path=args.db,
        table_name=args.table,
        asset_rollup=args.asset_rollup,
        root_symbol=args.root_symbol,
        df=df,
    )
    if df.empty:
        print("No continuous rows built.")
        return 0

    hdc_inserted = 0
    if int(args.write_hdc) == 1:
        hdc_inserted = upsert_to_historical_data_correct(
            db_path=args.db,
            hdc_table=args.hdc_table,
            asset_rollup=args.asset_rollup,
            symbol=args.root_symbol,
            df=df,
        )

    print(
        f"Continuous FUT close built: rows={len(df)} inserted={inserted} "
        f"range={df['datum'].min()}->{df['datum'].max()} "
        f"roll_events={int(df['roll_flag'].sum())} table={args.table} "
        f"hdc_table={args.hdc_table} hdc_rows={hdc_inserted}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

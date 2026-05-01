from __future__ import annotations

import argparse
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pyodbc
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portefeuille_viewer.config import get_stockdata_db_path
from portefeuille_viewer.data.repository import get_stockdata_connection


DEFAULT_STOCK_DB = get_stockdata_db_path()
INFO_CODES = {1100, 1101, 1102, 2103, 2104, 2105, 2106, 2107, 2108, 2158, 2159}
TICK_NAME = {
    1: "bid",
    2: "ask",
    4: "last",
    9: "close",
    66: "delayed_bid",
    67: "delayed_ask",
    68: "delayed_last",
    75: "delayed_close",
}


@dataclass
class UniverseRow:
    user_name: str
    series_id: int
    conid: int
    exchange_code: str
    ib_currency: str
    asset_rollup: str
    underlying_symbol: str
    optie_call_put: str
    strike: float
    expiry: datetime


class OptionLiveApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.req_to_series: dict[int, UniverseRow] = {}
        self.lock = threading.Lock()
        self.prices: dict[int, dict[str, float]] = {}
        self.greeks: dict[int, dict[str, float]] = {}

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()
        print(f"[{_ts()}] Connected. nextValidId={orderId}")

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
        if isinstance(msg, str) and "connection is OK" in msg:
            return
        print(f"[{_ts()}] IB ERROR reqId={reqId} code={code}: {msg}")

    def tickPrice(self, reqId, tickType, price, attrib):  # noqa: N802
        if price is None:
            return
        try:
            p = float(price)
        except Exception:
            return
        name = TICK_NAME.get(int(tickType))
        if not name:
            return
        with self.lock:
            self.prices.setdefault(int(reqId), {})[name] = p
        if p > 0:
            s = self.req_to_series.get(int(reqId))
            if s is not None:
                print(f"[{_ts()}] {s.asset_rollup:<12} {s.optie_call_put:<4} {s.strike:<8} {name:<12} {p}")

    def tickOptionComputation(  # noqa: N802
        self,
        reqId,
        tickType,
        tickAttrib,
        impliedVol,
        delta,
        optPrice,
        pvDividend,
        gamma,
        vega,
        theta,
        undPrice,
    ):
        # We store latest greeks regardless of tickType source.
        values = {
            "iv": _to_num(impliedVol),
            "delta": _to_num(delta),
            "gamma": _to_num(gamma),
            "theta": _to_num(theta),
            "vega": _to_num(vega),
            "model_price": _to_num(optPrice),
            "underlying_price": _to_num(undPrice),
        }
        with self.lock:
            g = self.greeks.setdefault(int(reqId), {})
            for k, v in values.items():
                if v is not None:
                    g[k] = v


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except Exception:
        return None
    # IB uses max float sentinels for missing values.
    if abs(x) > 1e100:
        return None
    return x


def _connect_access(db_path: str) -> pyodbc.Connection:
    if db_path == get_stockdata_db_path():
        return get_stockdata_connection()
    return pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")


def _ensure_snapshot_table(conn: pyodbc.Connection) -> None:
    cur = conn.cursor()
    try:
        cur.execute("SELECT TOP 1 id FROM option_live_snapshot")
        return
    except Exception:
        pass
    cur.execute(
        """
        CREATE TABLE option_live_snapshot (
            id COUNTER PRIMARY KEY,
            snapshot_ts DATETIME,
            user_name TEXT(32),
            series_id LONG,
            conid LONG,
            asset_rollup TEXT(64),
            underlying_symbol TEXT(32),
            optie_call_put TEXT(8),
            strike DOUBLE,
            expiry DATETIME,
            exchange_code TEXT(32),
            ib_currency TEXT(16),
            bid DOUBLE,
            ask DOUBLE,
            last DOUBLE,
            close DOUBLE,
            delayed_bid DOUBLE,
            delayed_ask DOUBLE,
            delayed_last DOUBLE,
            delayed_close DOUBLE,
            iv DOUBLE,
            delta DOUBLE,
            gamma DOUBLE,
            theta DOUBLE,
            vega DOUBLE,
            model_price DOUBLE,
            underlying_price DOUBLE,
            source TEXT(16)
        )
        """
    )
    conn.commit()


def _load_universe(conn: pyodbc.Connection, user: str, table_name: str, limit: int) -> list[UniverseRow]:
    top = f"TOP {int(limit)} " if limit and limit > 0 else ""
    sql = f"""
        SELECT {top}
            user_name, series_id, conid, exchange_code, ib_currency,
            asset_rollup, underlying_symbol, optie_call_put, strike, expiry
        FROM {table_name}
        WHERE user_name=?
          AND conid IS NOT NULL
          AND conid > 0
        ORDER BY asset_rollup, expiry, optie_call_put, strike
    """
    cur = conn.cursor()
    rows = cur.execute(sql, user).fetchall()
    out: list[UniverseRow] = []
    seen_series: set[int] = set()
    for r in rows:
        sid = int(r.series_id)
        if sid in seen_series:
            continue
        seen_series.add(sid)
        out.append(
            UniverseRow(
                user_name=str(r.user_name).strip(),
                series_id=sid,
                conid=int(r.conid),
                exchange_code=str(r.exchange_code or "").strip().upper() or "SMART",
                ib_currency=str(r.ib_currency or "").strip().upper(),
                asset_rollup=str(r.asset_rollup or "").strip(),
                underlying_symbol=str(r.underlying_symbol or "").strip(),
                optie_call_put=str(r.optie_call_put or "").strip().lower(),
                strike=float(r.strike),
                expiry=r.expiry,
            )
        )
    return out


def _build_contract(u: UniverseRow) -> Contract:
    c = Contract()
    c.conId = int(u.conid)
    c.exchange = u.exchange_code or "SMART"
    if u.ib_currency:
        c.currency = u.ib_currency
    return c


def _best_last(p: dict[str, float]) -> float | None:
    for k in ("last", "delayed_last", "close", "delayed_close", "bid", "ask", "delayed_bid", "delayed_ask"):
        v = p.get(k)
        if v is not None and v > 0:
            return v
    return None


def _save_snapshots(conn: pyodbc.Connection, app: OptionLiveApp, universe: list[UniverseRow]) -> int:
    cur = conn.cursor()
    now = datetime.now()
    ins = """
        INSERT INTO option_live_snapshot (
            snapshot_ts, user_name, series_id, conid, asset_rollup, underlying_symbol,
            optie_call_put, strike, expiry, exchange_code, ib_currency,
            bid, ask, last, close, delayed_bid, delayed_ask, delayed_last, delayed_close,
            iv, delta, gamma, theta, vega, model_price, underlying_price, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = []
    by_series = {u.series_id: u for u in universe}
    for req_id, u in app.req_to_series.items():
        p = app.prices.get(req_id, {})
        g = app.greeks.get(req_id, {})
        any_data = (_best_last(p) is not None) or any(g.get(k) is not None for k in ("iv", "delta", "gamma", "theta", "vega"))
        if not any_data:
            continue
        rows.append(
            (
                now,
                u.user_name,
                u.series_id,
                u.conid,
                u.asset_rollup,
                u.underlying_symbol,
                u.optie_call_put,
                u.strike,
                u.expiry,
                u.exchange_code,
                u.ib_currency,
                p.get("bid"),
                p.get("ask"),
                p.get("last"),
                p.get("close"),
                p.get("delayed_bid"),
                p.get("delayed_ask"),
                p.get("delayed_last"),
                p.get("delayed_close"),
                g.get("iv"),
                g.get("delta"),
                g.get("gamma"),
                g.get("theta"),
                g.get("vega"),
                g.get("model_price"),
                g.get("underlying_price"),
                "ib",
            )
        )

    if rows:
        cur.executemany(ins, rows)
        conn.commit()
    return len(rows)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Subscribe live option ticks from option subscription universe and store snapshots.")
    p.add_argument("--user", default="onno")
    p.add_argument("--stock-db", default=DEFAULT_STOCK_DB)
    p.add_argument("--table", default="option_subscription_universe_onno")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7496)
    p.add_argument("--client-id", type=int, default=109)
    p.add_argument("--market-data-type", type=int, default=3, choices=[1, 2, 3, 4])
    p.add_argument("--duration-sec", type=int, default=45)
    p.add_argument("--limit", type=int, default=60, help="Max rows from universe table before series dedupe.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = _connect_access(args.stock_db)
    try:
        _ensure_snapshot_table(conn)
        universe = _load_universe(conn, user=args.user, table_name=args.table, limit=args.limit)
        if not universe:
            print("No universe rows with conid found.")
            return 1
        print(f"[{_ts()}] Universe rows (dedup on series_id): {len(universe)}")

        app = OptionLiveApp()
        app.connect(args.host, args.port, clientId=args.client_id)
        thread = threading.Thread(target=app.run, daemon=True)
        thread.start()
        if not app.ready.wait(timeout=8):
            print(f"[{_ts()}] No nextValidId received.")
            app.disconnect()
            return 1

        app.reqMarketDataType(args.market_data_type)
        req_start = 20000
        for i, u in enumerate(universe):
            req_id = req_start + i
            app.req_to_series[req_id] = u
            c = _build_contract(u)
            app.reqMktData(req_id, c, "", False, False, [])

        print(f"[{_ts()}] Subscribed {len(universe)} option series. Listening {args.duration_sec}s ...")
        end_ts = time.time() + max(1, args.duration_sec)
        while time.time() < end_ts:
            time.sleep(0.2)

        for req_id in list(app.req_to_series.keys()):
            try:
                app.cancelMktData(req_id)
            except Exception:
                pass
        app.disconnect()
        time.sleep(0.2)

        saved = _save_snapshots(conn, app, universe)
        with_data = 0
        with_greeks = 0
        for req_id in app.req_to_series:
            p = app.prices.get(req_id, {})
            g = app.greeks.get(req_id, {})
            if _best_last(p) is not None:
                with_data += 1
            if any(g.get(k) is not None for k in ("iv", "delta", "gamma", "theta", "vega")):
                with_greeks += 1

        print("\n=== subscribe_live_options_from_universe summary ===")
        print(f"user={args.user}")
        print(f"subscribed={len(universe)}")
        print(f"with_price_data={with_data}")
        print(f"with_greeks={with_greeks}")
        print(f"snapshot_rows_inserted={saved}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

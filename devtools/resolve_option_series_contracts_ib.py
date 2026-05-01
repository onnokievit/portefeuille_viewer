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
from ibapi.contract import ContractDetails
from ibapi.wrapper import EWrapper


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portefeuille_viewer.config import get_stockdata_db_path
from portefeuille_viewer.data.repository import get_stockdata_connection


DEFAULT_STOCK_DB = get_stockdata_db_path()
INFO_CODES = {1100, 1101, 1102, 2103, 2104, 2105, 2106, 2107, 2108, 2158, 2159}


@dataclass
class Candidate:
    series_id: int
    asset_rollup: str
    underlying_symbol: str
    cp: str
    strike: float
    expiry: datetime
    ib_currency: str
    exchange_code: str
    trading_class: str


class ContractResolverApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.req_results: dict[int, list[ContractDetails]] = {}
        self.req_done: dict[int, threading.Event] = {}

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
        if isinstance(msg, str) and "connection is OK" in msg:
            return
        # mark request as done on hard contract errors too
        if reqId in self.req_done:
            self.req_done[reqId].set()

    def contractDetails(self, reqId: int, contractDetails: ContractDetails):  # noqa: N802
        with self.lock:
            self.req_results.setdefault(reqId, []).append(contractDetails)

    def contractDetailsEnd(self, reqId: int):  # noqa: N802
        if reqId in self.req_done:
            self.req_done[reqId].set()

    def resolve(self, req_id: int, contract: Contract, timeout_sec: float = 5.0) -> list[ContractDetails]:
        ev = threading.Event()
        self.req_done[req_id] = ev
        self.req_results[req_id] = []
        self.reqContractDetails(req_id, contract)
        ev.wait(timeout=timeout_sec)
        return self.req_results.get(req_id, [])


def connect_access(db_path: str) -> pyodbc.Connection:
    if db_path == get_stockdata_db_path():
        return get_stockdata_connection()
    return pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")


def _clean(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _load_candidates(conn: pyodbc.Connection, user_name: str, only_missing: bool) -> list[Candidate]:
    where_missing = " AND (m.conid IS NULL OR m.conid=0 OR m.local_symbol IS NULL OR m.local_symbol='')" if only_missing else ""
    sql = f"""
        SELECT
            m.series_id,
            m.asset_rollup,
            m.underlying_symbol,
            m.optie_call_put,
            m.strike,
            m.expiry,
            m.ib_currency,
            m.exchange_code,
            m.trading_class
        FROM option_series_master AS m
        INNER JOIN option_series_usage AS u
            ON m.series_id = u.series_id
        WHERE u.user_name=?
          AND u.active=True
          AND m.active=True
          {where_missing}
        ORDER BY m.asset_rollup, m.expiry, m.optie_call_put, m.strike
    """
    cur = conn.cursor()
    out: list[Candidate] = []
    for r in cur.execute(sql, user_name).fetchall():
        out.append(
            Candidate(
                series_id=int(r.series_id),
                asset_rollup=_clean(r.asset_rollup),
                underlying_symbol=_clean(r.underlying_symbol),
                cp=_clean(r.optie_call_put).lower(),
                strike=float(r.strike),
                expiry=r.expiry,
                ib_currency=_clean(r.ib_currency).upper(),
                exchange_code=_clean(r.exchange_code).upper(),
                trading_class=_clean(r.trading_class).upper(),
            )
        )
    return out


def _build_contract(c: Candidate, sec_type: str, exchange_code: str, with_trading_class: bool) -> Contract:
    con = Contract()
    con.secType = sec_type
    con.symbol = c.underlying_symbol
    con.currency = c.ib_currency
    con.exchange = exchange_code
    con.lastTradeDateOrContractMonth = c.expiry.strftime("%Y%m%d")
    con.strike = float(c.strike)
    con.right = "C" if c.cp == "call" else "P"
    if with_trading_class and c.trading_class:
        con.tradingClass = c.trading_class
    return con


def _pick_best(details: list[ContractDetails]) -> ContractDetails | None:
    if not details:
        return None
    # Prefer exact option secType and non-zero conid.
    ranked = sorted(
        details,
        key=lambda d: (
            0 if _clean(getattr(d.contract, "secType", "")) == "OPT" else 1,
            0 if int(getattr(d.contract, "conId", 0) or 0) > 0 else 1,
        ),
    )
    return ranked[0]


def _update_master_row(conn: pyodbc.Connection, series_id: int, det: ContractDetails) -> None:
    cur = conn.cursor()
    con = det.contract
    now = datetime.now()
    conid = int(getattr(con, "conId", 0) or 0)
    local_symbol = _clean(getattr(con, "localSymbol", ""))
    trading_class = _clean(getattr(con, "tradingClass", ""))
    exchange_code = _clean(getattr(con, "exchange", ""))
    multiplier = None
    try:
        mult_txt = _clean(getattr(con, "multiplier", ""))
        if mult_txt:
            multiplier = float(mult_txt)
    except Exception:
        multiplier = None

    cur.execute(
        """
        UPDATE option_series_master
        SET conid=?,
            local_symbol=?,
            trading_class=?,
            exchange_code=?,
            multiplier=?,
            last_verified_ts=?,
            updated_at=?
        WHERE series_id=?
        """,
        (
            conid if conid > 0 else None,
            local_symbol or None,
            trading_class or None,
            exchange_code or None,
            multiplier,
            now,
            now,
            int(series_id),
        ),
    )
    conn.commit()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Resolve IB contract details for option_series_master rows used by a user.")
    p.add_argument("--user", default="onno")
    p.add_argument("--stock-db", default=DEFAULT_STOCK_DB)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7496)
    p.add_argument("--client-id", type=int, default=98)
    p.add_argument("--only-missing", action="store_true", help="Resolve only rows missing conid/local_symbol")
    p.add_argument("--limit", type=int, default=0, help="Optional max candidates")
    p.add_argument("--timeout-sec", type=float, default=5.0)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = connect_access(args.stock_db)
    candidates = _load_candidates(conn, user_name=args.user, only_missing=args.only_missing)
    if args.limit and args.limit > 0:
        candidates = candidates[: args.limit]
    print(f"Candidates: {len(candidates)}")
    if not candidates:
        conn.close()
        return 0

    app = ContractResolverApp()
    app.connect(args.host, args.port, clientId=args.client_id)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    if not app.ready.wait(timeout=8):
        print("IB connection not ready (no nextValidId).")
        app.disconnect()
        conn.close()
        return 1

    ok = 0
    fail = 0
    req_id = 12000
    try:
        for c in candidates:
            attempts: list[tuple[str, str, bool]] = []
            ex = c.exchange_code or "SMART"
            attempts.append(("OPT", ex, True))
            attempts.append(("OPT", ex, False))
            if ex != "SMART":
                attempts.append(("OPT", "SMART", True))
                attempts.append(("OPT", "SMART", False))
            # Fallback path for options on futures (e.g. MBT): secType=FOP.
            attempts.append(("FOP", ex, True))
            attempts.append(("FOP", ex, False))
            if ex != "SMART":
                attempts.append(("FOP", "SMART", True))
                attempts.append(("FOP", "SMART", False))

            chosen: ContractDetails | None = None
            for sec_t, exch, use_tc in attempts:
                req_id += 1
                con = _build_contract(c, sec_type=sec_t, exchange_code=exch, with_trading_class=use_tc)
                details = app.resolve(req_id, con, timeout_sec=args.timeout_sec)
                best = _pick_best(details)
                if best is not None:
                    chosen = best
                    break

            if chosen is None:
                fail += 1
                print(
                    f"FAIL series_id={c.series_id} {c.asset_rollup} {c.cp} {c.strike} "
                    f"{c.expiry:%Y-%m-%d} {c.ib_currency}"
                )
                continue

            if not args.dry_run:
                _update_master_row(conn, c.series_id, chosen)
            ok += 1
            con = chosen.contract
            print(
                f"OK series_id={c.series_id} {c.asset_rollup} -> conid={int(getattr(con,'conId',0) or 0)} "
                f"local={_clean(getattr(con,'localSymbol',''))} tc={_clean(getattr(con,'tradingClass',''))} "
                f"mult={_clean(getattr(con,'multiplier',''))}"
            )
            time.sleep(0.03)
    finally:
        app.disconnect()
        conn.close()

    print("\n=== resolve_option_series_contracts_ib summary ===")
    print(f"user={args.user}")
    print(f"resolved_ok={ok}")
    print(f"failed={fail}")
    print(f"dry_run={args.dry_run}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

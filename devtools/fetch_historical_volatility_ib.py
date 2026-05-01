from __future__ import annotations

import argparse
import csv
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


DEFAULT_DB = get_stockdata_db_path()
INFO_CODES = {1100, 1101, 1102, 2103, 2104, 2105, 2106, 2107, 2108, 2158, 2159}


@dataclass
class AssetMeta:
    asset_rollup: str
    ib_symbol: str
    ib_currency: str
    asset_type: str
    exchange: str
    prim_exchange: str
    contractid: int


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_int(value) -> int:
    try:
        if value is None or str(value).strip() == "":
            return 0
        return int(float(value))
    except Exception:
        return 0


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        s = str(value).strip().replace(",", ".")
        try:
            return float(s)
        except Exception:
            return None


def load_asset_meta(db_path: str, asset_rollup: str) -> AssetMeta:
    conn = get_stockdata_connection() if db_path == get_stockdata_db_path() else pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT TOP 1 asset_rollup, ib_symbol, ib_currency, [type], exchange, prim_exchange, contractid
        FROM asset_rollup_data
        WHERE UCASE(asset_rollup) = UCASE(?)
        """,
        asset_rollup,
    ).fetchone()
    conn.close()
    if not row:
        raise RuntimeError(f"asset_rollup niet gevonden: {asset_rollup}")
    if not row.ib_symbol or not row.ib_currency:
        raise RuntimeError(f"asset_rollup {asset_rollup} mist ib_symbol en/of ib_currency")
    return AssetMeta(
        asset_rollup=str(row.asset_rollup).strip(),
        ib_symbol=str(row.ib_symbol).strip(),
        ib_currency=str(row.ib_currency).strip(),
        asset_type=str(getattr(row, "type", "") or "").strip().lower(),
        exchange=str(row.exchange or "").strip(),
        prim_exchange=str(row.prim_exchange or "").strip(),
        contractid=_to_int(row.contractid),
    )


def resolve_sec_type(asset_type: str) -> str:
    t = (asset_type or "").strip().lower()
    if t == "index":
        return "IND"
    if t in {"future", "fut"}:
        return "FUT"
    return "STK"


def resolve_exchange(sec_type: str, exchange: str, prim_exchange: str) -> str:
    ex = (exchange or "").strip().upper()
    pex = (prim_exchange or "").strip().upper()
    if sec_type == "STK":
        return "SMART"
    if sec_type == "IND":
        return ex or pex or "SMART"
    if sec_type == "FUT":
        return ex or pex or "SMART"
    return ex or "SMART"


def build_contract(meta: AssetMeta, use_conid: bool) -> Contract:
    sec_type = resolve_sec_type(meta.asset_type)
    c = Contract()
    c.symbol = meta.ib_symbol
    c.secType = sec_type
    c.currency = meta.ib_currency
    c.exchange = resolve_exchange(sec_type, meta.exchange, meta.prim_exchange)
    if meta.prim_exchange:
        c.primaryExchange = meta.prim_exchange
    if use_conid and meta.contractid > 0:
        c.conId = int(meta.contractid)
    return c


class HistVolApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.done = threading.Event()
        self.failed = False
        self.error_message = ""
        self.rows: list[dict] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()
        print(f"[{ts()}] Connected. nextValidId={orderId}")

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
            code_int = int(code)
        except Exception:
            code_int = None
        if code_int in INFO_CODES:
            return
        if isinstance(msg, str) and "connection is OK" in msg:
            return
        text = f"IB ERROR reqId={reqId} code={code}: {msg}"
        print(f"[{ts()}] {text}")
        if code_int in {200, 162, 321}:
            self.failed = True
            self.error_message = text
            self.done.set()

    def historicalData(self, reqId, bar):  # noqa: N802
        vol = _to_float(getattr(bar, "close", None))
        self.rows.append(
            {
                "date": str(getattr(bar, "date", "")),
                "volatiliteit": vol,
            }
        )

    def historicalDataEnd(self, reqId, start, end):  # noqa: N802
        print(f"[{ts()}] historicalDataEnd reqId={reqId} start={start} end={end}")
        self.done.set()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch historical/implied volatility from IBKR for one asset_rollup (from STOCKDATA.asset_rollup_data)."
    )
    p.add_argument("--asset-rollup", required=True, help="Bijv. UNILEVER")
    p.add_argument("--years", type=int, default=2, help="Aantal jaren historie (default: 2)")
    p.add_argument("--db", default=DEFAULT_DB, help="Pad naar STOCKDATA DB")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7496)
    p.add_argument("--client-id", type=int, default=99)
    p.add_argument("--timeout-sec", type=int, default=40)
    p.add_argument("--use-rth", type=int, default=1, choices=[0, 1], help="1=RTH only")
    p.add_argument("--use-conid", action="store_true", help="Gebruik contractid uit asset_rollup_data")
    p.add_argument(
        "--what-to-show",
        default="HISTORICAL_VOLATILITY",
        choices=["HISTORICAL_VOLATILITY", "OPTION_IMPLIED_VOLATILITY"],
        help="IB whatToShow",
    )
    p.add_argument("--output-csv", default="", help="Pad voor output CSV (default in devtools)")
    return p.parse_args()


def write_csv(path: Path, rows: list[dict], meta: AssetMeta) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["date", "volatiliteit", "asset_rollup", "symbol", "currency"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "date": r.get("date"),
                    "volatiliteit": r.get("volatiliteit"),
                    "asset_rollup": meta.asset_rollup,
                    "symbol": meta.ib_symbol,
                    "currency": meta.ib_currency,
                }
            )


def print_summary(rows: list[dict], meta: AssetMeta, out_csv: Path, what_to_show: str) -> None:
    if not rows:
        print("Rows: 0")
        print(f"Asset: {meta.asset_rollup} ({meta.ib_symbol})")
        print(f"Saved CSV: {out_csv}")
        return
    dates = [str(r.get("date", "")) for r in rows if r.get("date")]
    values = [float(r["volatiliteit"]) for r in rows if r.get("volatiliteit") is not None]
    print(f"Rows: {len(rows)}")
    if dates:
        print(f"Range: {dates[0]} -> {dates[-1]}")
    if values:
        print(f"Vol min/max: {min(values):.6f} / {max(values):.6f}")
        print(f"Latest vol: {values[-1]:.6f}")
    print(f"Asset: {meta.asset_rollup} ({meta.ib_symbol}) {meta.ib_currency}")
    print(f"whatToShow: {what_to_show}")
    print(f"Saved CSV: {out_csv}")


def main() -> int:
    args = parse_args()
    meta = load_asset_meta(args.db, args.asset_rollup)
    contract = build_contract(meta, use_conid=args.use_conid)
    print(
        f"[{ts()}] Requesting {args.what_to_show} asset={meta.asset_rollup} symbol={meta.ib_symbol} "
        f"secType={contract.secType} exchange={contract.exchange} prim={meta.prim_exchange or '-'} "
        f"currency={meta.ib_currency} conId={getattr(contract, 'conId', 0) or '-'}"
    )

    app = HistVolApp()
    app.connect(args.host, args.port, clientId=args.client_id)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()

    if not app.ready.wait(timeout=8):
        print(f"[{ts()}] No nextValidId received (connection not ready).")
        app.disconnect()
        return 1

    req_id = 9201
    duration = f"{max(1, int(args.years))} Y"
    app.reqHistoricalData(
        req_id,
        contract,
        "",
        duration,
        "1 day",
        args.what_to_show,
        int(args.use_rth),
        1,
        False,
        [],
    )
    print(f"[{ts()}] Sent reqHistoricalData reqId={req_id} duration={duration}")

    if not app.done.wait(timeout=max(5, int(args.timeout_sec))):
        print(f"[{ts()}] Timeout waiting for historical volatility data.")
        app.cancelHistoricalData(req_id)
        app.disconnect()
        return 2

    app.cancelHistoricalData(req_id)
    app.disconnect()
    time.sleep(0.2)

    if app.failed and not app.rows:
        print(f"[{ts()}] Failed: {app.error_message}")
        return 3

    out_csv = (
        Path(args.output_csv)
        if args.output_csv
        else Path(__file__).resolve().parent
        / f"{meta.asset_rollup}_{args.what_to_show.lower()}_{max(1, int(args.years))}Y.csv"
    )
    write_csv(out_csv, app.rows, meta)

    preview = app.rows[-10:] if len(app.rows) > 10 else app.rows
    if preview:
        print("")
        print(f"=== Preview ({len(preview)} rows) ===")
        for r in preview:
            print(f"{str(r.get('date')):>10}  volatiliteit={r.get('volatiliteit')}")
        print("")
    print_summary(app.rows, meta, out_csv, args.what_to_show)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

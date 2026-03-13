from __future__ import annotations

import argparse
import threading
import time
from dataclasses import dataclass
from datetime import datetime

import pyodbc
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


DEFAULT_DB = r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - STOCKDATA.accdb"
INFO_CODES = {1100, 1101, 1102, 2103, 2104, 2105, 2106, 2107, 2108, 2158, 2159}
TICK_NAMES = {
    0: "bid_size",
    1: "bid",
    2: "ask",
    3: "ask_size",
    4: "last",
    5: "last_size",
    8: "volume",
    9: "close",
    45: "last_timestamp",
    68: "delayed_last",
    74: "delayed_open",
    75: "delayed_close",
}


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


def load_asset_meta(db_path: str, asset_rollup: str) -> AssetMeta:
    conn = pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")
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


def resolve_exchange(sec_type: str, symbol: str, exchange: str, prim_exchange: str) -> str:
    ex = (exchange or "").strip().upper()
    pex = (prim_exchange or "").strip().upper()
    if sec_type == "STK":
        return "SMART"
    if sec_type == "IND":
        if ex and ex != "SMART":
            return ex
        if pex and pex != "SMART":
            return pex
        hints = {
            "EOE": "FTA",
            "AEX": "FTA",
            "DAX": "EUREX",
            "NDX": "NASDAQ",
            "SPX": "CBOE",
            "DJI": "CME",
            "INDU": "CME",
            "TSX": "TSE",
            "CAC": "MONEP",
            "PX1": "MONEP",
        }
        return hints.get((symbol or "").strip().upper(), "SMART")
    if sec_type == "FUT":
        return ex or pex or "SMART"
    return ex or "SMART"


def build_contract(meta: AssetMeta) -> Contract:
    sec_type = resolve_sec_type(meta.asset_type)
    c = Contract()
    c.symbol = meta.ib_symbol
    c.secType = sec_type
    c.currency = meta.ib_currency
    c.exchange = resolve_exchange(sec_type, meta.ib_symbol, meta.exchange, meta.prim_exchange)
    if meta.prim_exchange:
        c.primaryExchange = meta.prim_exchange
    if meta.contractid > 0:
        c.conId = int(meta.contractid)
    return c


class LiveAssetApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()

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
        print(f"[{ts()}] IB ERROR reqId={reqId} code={code}: {msg}")

    def tickPrice(self, reqId, tickType, price, attrib):  # noqa: N802
        if price is None or float(price) <= 0:
            return
        name = TICK_NAMES.get(int(tickType), f"tick_{tickType}")
        print(f"[{ts()}] price {name:<16} reqId={reqId} value={float(price):.6f}")

    def tickSize(self, reqId, tickType, size):  # noqa: N802
        name = TICK_NAMES.get(int(tickType), f"tick_{tickType}")
        print(f"[{ts()}] size  {name:<16} reqId={reqId} value={size}")

    def tickString(self, reqId, tickType, value):  # noqa: N802
        if value:
            name = TICK_NAMES.get(int(tickType), f"tick_{tickType}")
            print(f"[{ts()}] str   {name:<16} reqId={reqId} value={value}")

    def tickGeneric(self, reqId, tickType, value):  # noqa: N802
        if value is None:
            return
        name = TICK_NAMES.get(int(tickType), f"tick_{tickType}")
        print(f"[{ts()}] gen   {name:<16} reqId={reqId} value={float(value):.6f}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Subscribe live ticks by asset_rollup from STOCKDATA.asset_rollup_data")
    p.add_argument("--asset-rollup", required=True)
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7496)
    p.add_argument("--client-id", type=int, default=97)
    p.add_argument("--duration-sec", type=int, default=60)
    p.add_argument(
        "--market-data-type",
        type=int,
        default=3,
        choices=[1, 2, 3, 4],
        help="1=live, 2=frozen, 3=delayed, 4=delayed-frozen",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    meta = load_asset_meta(args.db, args.asset_rollup)
    contract = build_contract(meta)
    print(
        f"[{ts()}] Asset={meta.asset_rollup} symbol={meta.ib_symbol} type={meta.asset_type or '-'} "
        f"secType={contract.secType} exchange={contract.exchange} prim={meta.prim_exchange or '-'} "
        f"currency={meta.ib_currency} conId={meta.contractid or '-'}"
    )

    app = LiveAssetApp()
    app.connect(args.host, args.port, clientId=args.client_id)
    t = threading.Thread(target=app.run, daemon=True)
    t.start()

    if not app.ready.wait(timeout=8):
        print(f"[{ts()}] No nextValidId received (connection not ready).")
        app.disconnect()
        return 1

    with threading.Lock():
        pass
    try:
        app.reqMarketDataType(args.market_data_type)
    except Exception as exc:
        print(f"[{ts()}] WARN reqMarketDataType failed: {exc}")

    req_id = 9001
    app.reqMktData(req_id, contract, "", False, False, [])
    print(f"[{ts()}] Subscribed reqId={req_id}. Listening {max(args.duration_sec, 1)}s...")
    end_ts = time.time() + max(args.duration_sec, 1)
    while time.time() < end_ts:
        time.sleep(0.2)

    app.cancelMktData(req_id)
    app.disconnect()
    time.sleep(0.2)
    print(f"[{ts()}] Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

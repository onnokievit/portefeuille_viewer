from __future__ import annotations

import argparse
import threading
import time
from datetime import datetime

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


INFO_CODES = {1100, 1101, 1102, 2103, 2104, 2105, 2106, 2107, 2108, 2158, 2159}
TICK_NAMES = {
    1: "bid",
    2: "ask",
    4: "last",
    9: "close",
    68: "delayed_last",
    75: "delayed_close",
}


class IndexLiveApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.stop = threading.Event()
        self.last_values: dict[int, float] = {}

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
        name = TICK_NAMES.get(int(tickType))
        if not name:
            return
        price_f = float(price)
        self.last_values[int(tickType)] = price_f
        print(f"[{ts()}] tick {name:<13} reqId={reqId} price={price_f:.6f}")

    def tickSize(self, reqId, tickType, size):  # noqa: N802
        if int(tickType) in (0, 3, 5, 8):  # bidSize, askSize, lastSize, volume
            print(f"[{ts()}] size tickType={tickType} reqId={reqId} size={size}")


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_index_contract(symbol: str, exchange: str, currency: str, primary_exchange: str) -> Contract:
    c = Contract()
    c.symbol = symbol
    c.secType = "IND"
    c.exchange = exchange
    c.currency = currency
    if primary_exchange:
        c.primaryExchange = primary_exchange
    return c


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Standalone IB index live subscription tester (CLI).")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7496)
    p.add_argument("--client-id", type=int, default=77)
    p.add_argument("--symbol", default="EOE")
    p.add_argument("--exchange", default="FTA")
    p.add_argument("--currency", default="EUR")
    p.add_argument("--primary-exchange", default="")
    p.add_argument("--duration-sec", type=int, default=60, help="How long to listen for ticks")
    p.add_argument(
        "--market-data-type",
        type=int,
        default=3,
        choices=[1, 2, 3, 4],
        help="1=live,2=frozen,3=delayed,4=delayed-frozen",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    app = IndexLiveApp()
    app.connect(args.host, args.port, clientId=args.client_id)
    t = threading.Thread(target=app.run, daemon=True)
    t.start()

    if not app.ready.wait(timeout=8):
        print(f"[{ts()}] No nextValidId received (connection not ready).")
        app.disconnect()
        return 1

    try:
        app.reqMarketDataType(args.market_data_type)
    except Exception as exc:
        print(f"[{ts()}] WARN reqMarketDataType failed: {exc}")

    contract = build_index_contract(
        symbol=args.symbol,
        exchange=args.exchange,
        currency=args.currency,
        primary_exchange=args.primary_exchange,
    )
    req_id = 9001
    print(
        f"[{ts()}] Subscribing: symbol={args.symbol} secType=IND "
        f"exchange={args.exchange} primary={args.primary_exchange or '-'} currency={args.currency}"
    )
    app.reqMktData(req_id, contract, "", False, False, [])

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

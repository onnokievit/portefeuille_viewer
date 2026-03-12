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


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class FutLiveApp(EWrapper, EClient):
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
        name = TICK_NAMES.get(int(tickType))
        if not name:
            return
        print(f"[{ts()}] tick {name:<13} reqId={reqId} price={float(price):.6f}")

    def tickSize(self, reqId, tickType, size):  # noqa: N802
        if int(tickType) in (0, 3, 5, 8):  # bidSize, askSize, lastSize, volume
            print(f"[{ts()}] size tickType={tickType} reqId={reqId} size={size}")


def build_fut_contract(args: argparse.Namespace) -> Contract:
    c = Contract()
    c.secType = "FUT"
    c.symbol = args.symbol
    c.exchange = args.exchange
    c.currency = args.currency
    if args.conid:
        c.conId = int(args.conid)
    if args.local_symbol:
        c.localSymbol = args.local_symbol
    if args.contract_month:
        c.lastTradeDateOrContractMonth = args.contract_month
    if args.trading_class:
        c.tradingClass = args.trading_class
    if args.multiplier:
        c.multiplier = str(args.multiplier)
    return c


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Standalone IB FUT live subscription tester (CLI).")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7496)
    p.add_argument("--client-id", type=int, default=88)
    p.add_argument("--symbol", required=True, help="Underlying future symbol, e.g. MBT")
    p.add_argument("--exchange", required=True, help="Exchange, e.g. CME")
    p.add_argument("--currency", required=True, help="Currency, e.g. USD")
    p.add_argument("--conid", type=int, default=0, help="Optional IB contract id (recommended)")
    p.add_argument("--local-symbol", default="", help="Optional localSymbol, e.g. MBTH6")
    p.add_argument("--contract-month", default="", help="YYYYMM or YYYYMMDD")
    p.add_argument("--trading-class", default="", help="Optional tradingClass, e.g. MBT")
    p.add_argument("--multiplier", default="", help="Optional multiplier, e.g. 0.1")
    p.add_argument("--duration-sec", type=int, default=60)
    p.add_argument(
        "--market-data-type",
        type=int,
        default=1,
        choices=[1, 2, 3, 4],
        help="1=live,2=frozen,3=delayed,4=delayed-frozen",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    app = FutLiveApp()
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

    c = build_fut_contract(args)
    req_id = 9001
    print(
        f"[{ts()}] Subscribing FUT: symbol={args.symbol} exchange={args.exchange} "
        f"currency={args.currency} conId={args.conid or '-'} localSymbol={args.local_symbol or '-'} "
        f"month={args.contract_month or '-'} tradingClass={args.trading_class or '-'} "
        f"multiplier={args.multiplier or '-'}"
    )
    app.reqMktData(req_id, c, "", False, False, [])

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

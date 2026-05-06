"""
Minimal TWS API option-chain probe.

Target:
  ABN / OPT / FTA / EUR / expiry 2026-05-15 / calls around strike 29

Usage:
  python basic_abn_option_chain.py
  python basic_abn_option_chain.py --port 7498 --strike-window 2
"""
from __future__ import annotations

import argparse
import threading
import time

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


class App(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.done = threading.Event()
        self.rows: list[dict] = []

    def nextValidId(self, orderId: int) -> None:
        print(f"[IB] connected; nextValidId={orderId}")
        self.ready.set()

    def error(self, reqId, errorCode, errorString, advancedOrderReject="") -> None:
        if errorCode in {2103, 2104, 2105, 2106, 2107, 2108, 2158, 2119}:
            return
        print(f"[IB error] reqId={reqId} code={errorCode} msg={errorString}")
        if errorCode in {200, 321}:
            self.done.set()

    def contractDetails(self, reqId, contractDetails) -> None:
        c = contractDetails.contract
        row = {
            "conId": c.conId,
            "symbol": c.symbol,
            "localSymbol": c.localSymbol,
            "tradingClass": c.tradingClass,
            "exchange": c.exchange,
            "primaryExchange": c.primaryExchange,
            "currency": c.currency,
            "lastTradeDate": c.lastTradeDateOrContractMonth,
            "strike": c.strike,
            "right": c.right,
            "multiplier": c.multiplier,
        }
        self.rows.append(row)

    def contractDetailsEnd(self, reqId) -> None:
        print(f"[IB] contractDetailsEnd reqId={reqId}; rows={len(self.rows)}")
        self.done.set()


def make_contract(strike: float | None, args: argparse.Namespace) -> Contract:
    c = Contract()
    c.symbol = args.symbol
    c.secType = "OPT"
    c.exchange = args.exchange
    c.currency = args.currency
    if args.expiry:
        c.lastTradeDateOrContractMonth = args.expiry
    if args.right and args.right != "BOTH":
        c.right = args.right
    if strike is not None:
        c.strike = float(strike)
    if args.multiplier:
        c.multiplier = args.multiplier
    if args.trading_class:
        c.tradingClass = args.trading_class
    return c


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal ABN option contract-details probe.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7496)
    parser.add_argument("--client-id", type=int, default=9915)
    parser.add_argument("--symbol", default="ABN")
    parser.add_argument("--currency", default="EUR")
    parser.add_argument("--exchange", default="FTA")
    parser.add_argument("--expiry", default="20260515")
    parser.add_argument("--right", default="C", choices=["C", "P", "BOTH"])
    parser.add_argument("--center-strike", type=float, default=29.0)
    parser.add_argument("--strike-window", type=float, default=1.0)
    parser.add_argument("--strike-step", type=float, default=0.5)
    parser.add_argument("--min-strike", type=float, default=28.0)
    parser.add_argument("--max-strike", type=float, default=29.0)
    parser.add_argument("--multiplier", default="")
    parser.add_argument("--trading-class", default="")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--show-raw", action="store_true", help="Print every contract returned before range filtering.")
    parser.add_argument(
        "--wildcard",
        action="store_true",
        help="Do one incomplete request for the expiry/right instead of explicit strikes.",
    )
    args = parser.parse_args()

    print(
        "[probe] "
        f"{args.symbol} OPT {args.exchange} {args.currency} expiry={args.expiry or '<ANY>'} "
        f"right={args.right} center={args.center_strike}"
    )

    app = App()
    app.connect(args.host, args.port, args.client_id)
    t = threading.Thread(target=app.run, daemon=True)
    t.start()
    if not app.ready.wait(timeout=args.timeout):
        print("[probe] connection timeout")
        app.disconnect()
        return 2

    req_id = 1000
    if args.wildcard:
        print(
            "[probe] requesting wildcard contractDetails for expiry/right; "
            f"CLI output filtered to {args.min_strike} <= strike <= {args.max_strike}"
        )
        app.reqContractDetails(req_id, make_contract(None, args))
        app.done.wait(timeout=args.timeout)
    else:
        strikes = []
        s = args.center_strike - args.strike_window
        while s <= args.center_strike + args.strike_window + 1e-9:
            strikes.append(round(s, 4))
            s += args.strike_step
        print(f"[probe] requesting explicit strikes: {strikes}")
        for strike in strikes:
            app.done.clear()
            print(f"[probe] reqContractDetails strike={strike}")
            app.reqContractDetails(req_id, make_contract(strike, args))
            app.done.wait(timeout=args.timeout)
            req_id += 1
            time.sleep(0.2)

    if args.show_raw:
        print()
        print(f"[raw] rows={len(app.rows)}")
        for row in sorted(app.rows, key=lambda r: (r["lastTradeDate"], r["strike"], r["right"], r["multiplier"], r["localSymbol"])):
            print(
                "[raw] "
                f"{row['localSymbol']} conId={row['conId']} "
                f"expiry={row['lastTradeDate']} strike={row['strike']} right={row['right']} "
                f"exchange={row['exchange']} tradingClass={row['tradingClass']} mult={row['multiplier']}"
            )

    print()
    rows = app.rows
    if args.wildcard:
        rows = [r for r in rows if args.min_strike <= float(r["strike"]) <= args.max_strike]
        print(f"[contracts] strike filter {args.min_strike} <= strike <= {args.max_strike}; rows={len(rows)} out of {len(app.rows)}")
    else:
        print(f"[contracts] rows={len(rows)}")
    for row in sorted(rows, key=lambda r: (r["lastTradeDate"], r["strike"], r["right"], r["multiplier"], r["localSymbol"])):
        print(
            "[contract] "
            f"{row['localSymbol']} conId={row['conId']} "
            f"expiry={row['lastTradeDate']} strike={row['strike']} right={row['right']} "
            f"exchange={row['exchange']} tradingClass={row['tradingClass']} mult={row['multiplier']}"
        )
    app.disconnect()
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import threading
import time
from datetime import datetime
from typing import Any

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


INFO_CODES = {1100, 1101, 1102, 2103, 2104, 2105, 2106, 2107, 2108, 2158, 2159}

TICK_PRICE_NAME = {
    1: "bid",
    2: "ask",
    4: "last",
    6: "high",
    7: "low",
    9: "close",
    14: "open",
    15: "13w_high",
    16: "13w_low",
    17: "26w_high",
    18: "26w_low",
    19: "52w_high",
    20: "52w_low",
    37: "mark",
    66: "delayed_bid",
    67: "delayed_ask",
    68: "delayed_last",
    72: "delayed_high",
    73: "delayed_low",
    75: "delayed_close",
}

TICK_GENERIC_NAME = {
    23: "option_hist_vol",
    24: "option_implied_vol",
    31: "index_future_premium",
    49: "halted",
    54: "trade_count",
    55: "trade_rate",
    56: "volume_rate",
}

TICK_STRING_NAME = {
    45: "last_timestamp",
    48: "rt_volume",
    59: "dividends",
    77: "rt_trade_volume",
}

OPT_COMP_TICKTYPE = {
    10: "bid_option_comp",
    11: "ask_option_comp",
    12: "last_option_comp",
    13: "model_option_comp",
}


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _to_num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except Exception:
        return None
    if abs(x) > 1e100:
        return None
    return x


class OptionProbeApp(EWrapper, EClient):
    def __init__(self, show_info_errors: bool = False, print_events: bool = True):
        EClient.__init__(self, self)
        self.show_info_errors = bool(show_info_errors)
        self.print_events = bool(print_events)
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.events: list[dict[str, Any]] = []
        self.last_price_by_type: dict[int, float] = {}
        self.last_size_by_type: dict[int, float] = {}
        self.last_generic_by_type: dict[int, float] = {}
        self.last_string_by_type: dict[int, str] = {}
        self.last_option_comp_by_type: dict[int, dict[str, Any]] = {}
        self.market_data_type_by_req: dict[int, int] = {}

    def _record(self, event: dict[str, Any]) -> None:
        event["ts"] = _ts()
        with self.lock:
            self.events.append(event)
        if self.print_events:
            print(json.dumps(event, ensure_ascii=False))

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self._record({"event": "nextValidId", "order_id": int(orderId)})
        self.ready.set()

    def error(self, reqId, *args):  # noqa: N802
        error_time = None
        code = None
        msg = ""
        ext = ""
        if len(args) == 2:
            code, msg = args
        elif len(args) == 3:
            code, msg, ext = args
        elif len(args) >= 4:
            error_time, code, msg, ext = args[:4]
        if code is None:
            return
        try:
            code_i = int(code)
        except Exception:
            code_i = None
        if (code_i in INFO_CODES) and (not self.show_info_errors):
            return
        self._record(
            {
                "event": "error",
                "req_id": int(reqId),
                "error_time": error_time,
                "code": code_i,
                "message": str(msg),
                "extra": str(ext) if ext else "",
            }
        )

    def marketDataType(self, reqId: int, marketDataType: int) -> None:  # noqa: N802
        self.market_data_type_by_req[int(reqId)] = int(marketDataType)
        self._record(
            {
                "event": "marketDataType",
                "req_id": int(reqId),
                "market_data_type": int(marketDataType),
            }
        )

    def tickPrice(self, reqId, tickType, price, attrib):  # noqa: N802
        v = _to_num(price)
        if v is None:
            return
        tt = int(tickType)
        self.last_price_by_type[tt] = v
        self._record(
            {
                "event": "tickPrice",
                "req_id": int(reqId),
                "tick_type": tt,
                "tick_name": TICK_PRICE_NAME.get(tt, "unknown"),
                "value": v,
                "can_auto_execute": bool(getattr(attrib, "canAutoExecute", False)),
                "past_limit": bool(getattr(attrib, "pastLimit", False)),
                "pre_open": bool(getattr(attrib, "preOpen", False)),
            }
        )

    def tickSize(self, reqId, tickType, size):  # noqa: N802
        v = _to_num(size)
        if v is None:
            return
        tt = int(tickType)
        self.last_size_by_type[tt] = v
        self._record(
            {
                "event": "tickSize",
                "req_id": int(reqId),
                "tick_type": tt,
                "value": v,
            }
        )

    def tickGeneric(self, reqId, tickType, value):  # noqa: N802
        v = _to_num(value)
        if v is None:
            return
        tt = int(tickType)
        self.last_generic_by_type[tt] = v
        self._record(
            {
                "event": "tickGeneric",
                "req_id": int(reqId),
                "tick_type": tt,
                "tick_name": TICK_GENERIC_NAME.get(tt, "unknown"),
                "value": v,
            }
        )

    def tickString(self, reqId, tickType, value):  # noqa: N802
        tt = int(tickType)
        val = str(value or "")
        self.last_string_by_type[tt] = val
        self._record(
            {
                "event": "tickString",
                "req_id": int(reqId),
                "tick_type": tt,
                "tick_name": TICK_STRING_NAME.get(tt, "unknown"),
                "value": val,
            }
        )

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
        tt = int(tickType)
        payload = {
            "iv": _to_num(impliedVol),
            "delta": _to_num(delta),
            "opt_price": _to_num(optPrice),
            "pv_dividend": _to_num(pvDividend),
            "gamma": _to_num(gamma),
            "vega": _to_num(vega),
            "theta": _to_num(theta),
            "underlying_price": _to_num(undPrice),
        }
        self.last_option_comp_by_type[tt] = payload
        self._record(
            {
                "event": "tickOptionComputation",
                "req_id": int(reqId),
                "tick_type": tt,
                "tick_name": OPT_COMP_TICKTYPE.get(tt, "unknown"),
                **payload,
            }
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Standalone IBKR option tick probe (all callbacks, no app integration)."
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7496)
    p.add_argument("--client-id", type=int, default=197)

    p.add_argument("--conid", type=int, default=0, help="If set (>0), probe by conId.")
    p.add_argument("--sec-type", default="OPT", help="OPT or FOP")
    p.add_argument("--symbol", default="", help="Underlying symbol (required when conid=0)")
    p.add_argument("--expiry", default="", help="YYYYMMDD (required when conid=0)")
    p.add_argument("--strike", type=float, default=0.0, help="Required when conid=0")
    p.add_argument("--right", default="C", help="C or P (required when conid=0)")
    p.add_argument("--exchange", default="SMART")
    p.add_argument("--currency", default="USD")
    p.add_argument("--trading-class", default="", help="Optional")

    p.add_argument(
        "--market-data-types",
        default="1,3",
        help="Comma list to cycle reqMarketDataType over (1=live,2=frozen,3=delayed,4=delayed-frozen)",
    )
    p.add_argument(
        "--generic-ticks",
        default="100,101,104,105,106,162,165,221,225,233,236,258,293,294,295,375,411,456",
        help="IB generic tick list string for reqMktData.",
    )
    p.add_argument("--duration-sec", type=float, default=20.0)
    p.add_argument("--req-id", type=int, default=9001)
    p.add_argument("--show-info-errors", action="store_true")
    p.add_argument("--quiet", action="store_true", help="Do not print every event live.")
    return p.parse_args()


def _build_contract(args: argparse.Namespace) -> Contract:
    c = Contract()
    sec_type = str(args.sec_type or "OPT").upper()
    c.secType = sec_type
    c.exchange = str(args.exchange or "SMART").upper()
    c.currency = str(args.currency or "").upper()

    if int(args.conid or 0) > 0:
        c.conId = int(args.conid)
        return c

    symbol = str(args.symbol or "").strip().upper()
    expiry = str(args.expiry or "").strip()
    right = str(args.right or "").strip().upper()
    strike = float(args.strike or 0.0)
    if not symbol or not expiry or right not in {"C", "P"} or strike <= 0:
        raise ValueError(
            "When --conid=0, provide --symbol, --expiry YYYYMMDD, --right C/P, --strike > 0."
        )
    c.symbol = symbol
    c.lastTradeDateOrContractMonth = expiry
    c.right = right
    c.strike = strike
    if args.trading_class:
        c.tradingClass = str(args.trading_class).strip().upper()
    return c


def _parse_market_data_types(raw: str) -> list[int]:
    out: list[int] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = int(part)
        except Exception:
            continue
        if v in {1, 2, 3, 4}:
            out.append(v)
    return out or [1]


def main() -> int:
    args = parse_args()
    app = OptionProbeApp(
        show_info_errors=bool(args.show_info_errors),
        print_events=not bool(args.quiet),
    )

    app.connect(args.host, int(args.port), clientId=int(args.client_id))
    t = threading.Thread(target=app.run, daemon=True)
    t.start()

    if not app.ready.wait(timeout=8.0):
        print("[probe] No IB connection (nextValidId timeout).")
        return 2

    contract = _build_contract(args)
    req_id = int(args.req_id)
    md_types = _parse_market_data_types(args.market_data_types)
    seconds_per_mode = max(0.1, float(args.duration_sec) / float(len(md_types)))

    print(
        f"[probe] start req_id={req_id} duration={args.duration_sec}s "
        f"md_types={md_types} contract="
        f"{json.dumps({k: getattr(contract, k, None) for k in ['secType','conId','symbol','lastTradeDateOrContractMonth','strike','right','exchange','currency','tradingClass']}, ensure_ascii=False)}"
    )

    start = time.time()
    for md in md_types:
        app.reqMarketDataType(int(md))
        app._record({"event": "setMarketDataType", "market_data_type": int(md)})
        app.reqMktData(req_id, contract, str(args.generic_ticks or ""), False, False, [])
        until = time.time() + seconds_per_mode
        while time.time() < until:
            time.sleep(0.05)
        app.cancelMktData(req_id)
        app._record({"event": "cancelMktData", "req_id": req_id, "market_data_type": int(md)})

    time.sleep(0.3)
    elapsed = time.time() - start
    with app.lock:
        events = list(app.events)
        price_map = dict(app.last_price_by_type)
        size_map = dict(app.last_size_by_type)
        generic_map = dict(app.last_generic_by_type)
        string_map = dict(app.last_string_by_type)
        comp_map = dict(app.last_option_comp_by_type)
        md_map = dict(app.market_data_type_by_req)

    app.disconnect()

    summary = {
        "elapsed_sec": round(elapsed, 3),
        "events_count": len(events),
        "market_data_type_by_req": md_map,
        "last_price_by_type": {
            str(k): {"name": TICK_PRICE_NAME.get(k, "unknown"), "value": v}
            for k, v in sorted(price_map.items())
        },
        "last_size_by_type": {str(k): v for k, v in sorted(size_map.items())},
        "last_generic_by_type": {
            str(k): {"name": TICK_GENERIC_NAME.get(k, "unknown"), "value": v}
            for k, v in sorted(generic_map.items())
        },
        "last_string_by_type": {
            str(k): {"name": TICK_STRING_NAME.get(k, "unknown"), "value": v}
            for k, v in sorted(string_map.items())
        },
        "last_option_comp_by_type": {
            str(k): {"name": OPT_COMP_TICKTYPE.get(k, "unknown"), **v}
            for k, v in sorted(comp_map.items())
        },
    }

    print("\n[probe] summary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

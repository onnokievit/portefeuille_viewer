from __future__ import annotations

import argparse
import configparser
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.wrapper import EWrapper


INFO_CODES = {1100, 1101, 1102, 2103, 2104, 2105, 2106, 2107, 2108, 2158, 2159}
IB_UNSET_FLOAT_TEXT = "1.7976931348623157E308"


@dataclass
class IbSettings:
    host: str
    port: int
    client_id: int


@dataclass
class PositionRow:
    account: str
    contract: Contract
    position: Decimal
    avg_cost: float


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"?", "N/A", IB_UNSET_FLOAT_TEXT}:
        return None
    try:
        return Decimal(text.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _clean_ib_field(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text == IB_UNSET_FLOAT_TEXT:
        return None
    return text


def load_ib_settings() -> IbSettings:
    root = Path(__file__).resolve().parents[1] / "portefeuille_viewer" / "config"
    shared_path = root / "settings_shared.ini"
    local_path = root / ".user_settings" / "settings_local.ini"

    parser = configparser.ConfigParser()
    parser.read([shared_path, local_path], encoding="utf-8")

    host = parser.get("interactive_brokers", "host", fallback="127.0.0.1")
    port = parser.getint("interactive_brokers", "port", fallback=7496)
    client_id = parser.getint("interactive_brokers", "client_id", fallback=299)
    return IbSettings(host=host, port=port, client_id=client_id)


class MarginProbeApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.positions_done = threading.Event()
        self.whatif_done = threading.Event()
        self.contract_details_done = threading.Event()
        self.lock = threading.Lock()

        self.next_order_id: int | None = None
        self.positions: list[PositionRow] = []
        self.error_messages: list[str] = []
        self.whatif_payload: dict[str, Any] | None = None
        self.contract_details: list[Contract] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_order_id = int(orderId)
        self.ready.set()
        print(f"[{ts()}] Connected. nextValidId={orderId}")

    def error(self, reqId, *args):  # noqa: N802
        code = None
        msg = ""
        ext = ""
        if len(args) == 2:
            code, msg = args
        elif len(args) == 3:
            code, msg, ext = args
        elif len(args) >= 4:
            _, code, msg, ext = args[:4]
        if code is None:
            return

        try:
            code_i = int(code)
        except Exception:
            code_i = None
        text = f"IB ERROR reqId={reqId} code={code_i}: {msg} {ext}".strip()
        if code_i in INFO_CODES:
            print(f"[{ts()}] {text}")
            return
        self.error_messages.append(text)
        print(f"[{ts()}] {text}")
        if code_i in {110, 201, 202, 321, 322, 478, 10147}:
            self.whatif_done.set()

    def position(self, account: str, contract: Contract, position: float, avgCost: float):  # noqa: N802
        row = PositionRow(
            account=str(account or "").strip(),
            contract=contract,
            position=_to_decimal(position),
            avg_cost=float(avgCost or 0.0),
        )
        with self.lock:
            self.positions.append(row)

    def positionEnd(self) -> None:  # noqa: N802
        print(f"[{ts()}] positionEnd received. rows={len(self.positions)}")
        self.positions_done.set()

    def openOrder(self, orderId, contract: Contract, order: Order, orderState):  # noqa: N802
        if not getattr(order, "whatIf", False):
            return
        self.whatif_payload = {
            "order_id": int(orderId),
            "symbol": str(contract.symbol or "").strip(),
            "conid": int(getattr(contract, "conId", 0) or 0),
            "sec_type": str(contract.secType or "").strip(),
            "exchange": str(contract.exchange or "").strip(),
            "currency": str(contract.currency or "").strip(),
            "action": str(order.action or "").strip(),
            "total_quantity": str(order.totalQuantity),
            "init_margin_before": _clean_ib_field(getattr(orderState, "initMarginBefore", "")),
            "init_margin_change": _clean_ib_field(getattr(orderState, "initMarginChange", "")),
            "init_margin_after": _clean_ib_field(getattr(orderState, "initMarginAfter", "")),
            "maint_margin_before": _clean_ib_field(getattr(orderState, "maintMarginBefore", "")),
            "maint_margin_change": _clean_ib_field(getattr(orderState, "maintMarginChange", "")),
            "maint_margin_after": _clean_ib_field(getattr(orderState, "maintMarginAfter", "")),
            "equity_with_loan_before": _clean_ib_field(getattr(orderState, "equityWithLoanBefore", "")),
            "equity_with_loan_change": _clean_ib_field(getattr(orderState, "equityWithLoanChange", "")),
            "equity_with_loan_after": _clean_ib_field(getattr(orderState, "equityWithLoanAfter", "")),
            "commission": _clean_ib_field(getattr(orderState, "commission", "")),
            "warning_text": str(getattr(orderState, "warningText", "") or ""),
        }
        print(f"[{ts()}] whatIf openOrder received for {contract.symbol}")
        self.whatif_done.set()

    def contractDetails(self, reqId, contractDetails):  # noqa: N802
        contract = getattr(contractDetails, "contract", None)
        if contract is None:
            return
        self.contract_details.append(contract)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.contract_details_done.set()


def build_parser(defaults: IbSettings) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Probe estimated margin usage for one existing IBKR portfolio position by running "
            "a WHAT-IF close order on that position."
        )
    )
    p.add_argument("--host", default=defaults.host)
    p.add_argument("--port", type=int, default=defaults.port)
    p.add_argument("--client-id", type=int, default=defaults.client_id + 400)
    p.add_argument("--account", default="", help="Optional IB account filter")
    p.add_argument("--symbol", default="", help="Exact symbol match, e.g. BHP")
    p.add_argument("--conid", type=int, default=0, help="Preferred exact conId match")
    p.add_argument("--timeout-sec", type=int, default=15)
    p.add_argument(
        "--json",
        action="store_true",
        help="Print final result as JSON only",
    )
    return p


def match_position(rows: list[PositionRow], account: str, symbol: str, conid: int) -> PositionRow:
    candidates = rows
    if account:
        candidates = [r for r in candidates if r.account.lower() == account.lower()]
    if conid > 0:
        candidates = [r for r in candidates if int(getattr(r.contract, "conId", 0) or 0) == conid]
    if symbol:
        candidates = [r for r in candidates if str(r.contract.symbol or "").strip().upper() == symbol.strip().upper()]
    candidates = [r for r in candidates if r.position != 0]

    if not candidates:
        raise RuntimeError("Geen passende portfolio-positie gevonden.")
    if len(candidates) > 1:
        formatted = [
            {
                "account": r.account,
                "symbol": r.contract.symbol,
                "conid": int(getattr(r.contract, "conId", 0) or 0),
                "secType": r.contract.secType,
                "position": str(r.position),
            }
            for r in candidates
        ]
        raise RuntimeError(f"Meerdere matches gevonden, maak filter specifieker: {formatted}")
    return candidates[0]


def build_close_order(position: PositionRow) -> Order:
    qty = abs(float(position.position))
    action = "SELL" if position.position > 0 else "BUY"
    order = Order()
    order.action = action
    sec_type = str(position.contract.secType or "").strip().upper()
    if sec_type == "STK":
        order.orderType = "LMT"
        order.lmtPrice = 0.01 if action == "SELL" else 999999.0
    else:
        order.orderType = "MKT"
    order.totalQuantity = qty
    order.tif = "DAY"
    order.whatIf = True
    order.transmit = True
    order.account = position.account
    return order


def build_contract_lookup(source: Contract) -> Contract:
    lookup = Contract()
    conid = int(getattr(source, "conId", 0) or 0)
    if conid > 0:
        lookup.conId = conid
    lookup.symbol = str(source.symbol or "").strip()
    lookup.secType = str(source.secType or "").strip()
    lookup.currency = str(source.currency or "").strip()
    lookup.exchange = "SMART" if lookup.secType.upper() == "STK" else str(source.exchange or "").strip()
    return lookup


def qualify_position_contract(app: MarginProbeApp, source: Contract, timeout_sec: int) -> Contract:
    app.contract_details = []
    app.contract_details_done.clear()
    req_id = 9001
    lookup = build_contract_lookup(source)
    app.reqContractDetails(req_id, lookup)
    if not app.contract_details_done.wait(timeout=timeout_sec):
        raise RuntimeError("Timeout waiting for reqContractDetails.")
    if not app.contract_details:
        raise RuntimeError("Geen contract details ontvangen van IB.")

    exact_conid = int(getattr(source, "conId", 0) or 0)
    if exact_conid > 0:
        for contract in app.contract_details:
            if int(getattr(contract, "conId", 0) or 0) == exact_conid:
                if str(contract.secType or "").strip().upper() == "STK":
                    contract.exchange = "SMART"
                return contract

    contract = app.contract_details[0]
    if str(contract.secType or "").strip().upper() == "STK":
        contract.exchange = "SMART"
    return contract


def estimate_relief(raw_value: str) -> str | None:
    value = _parse_decimal(raw_value)
    if value is None:
        return None
    return str(abs(value))


def summarize(position: PositionRow, payload: dict[str, Any]) -> dict[str, Any]:
    init_relief = estimate_relief(payload.get("init_margin_change", ""))
    maint_relief = estimate_relief(payload.get("maint_margin_change", ""))
    return {
        "account": position.account,
        "symbol": str(position.contract.symbol or "").strip(),
        "local_symbol": str(getattr(position.contract, "localSymbol", "") or "").strip(),
        "conid": int(getattr(position.contract, "conId", 0) or 0),
        "sec_type": str(position.contract.secType or "").strip(),
        "currency": str(position.contract.currency or "").strip(),
        "exchange": str(position.contract.exchange or "").strip(),
        "position": str(position.position),
        "avg_cost": position.avg_cost,
        "whatif_close_action": payload.get("action"),
        "whatif_close_qty": payload.get("total_quantity"),
        "init_margin_before": payload.get("init_margin_before"),
        "init_margin_after": payload.get("init_margin_after"),
        "init_margin_change": payload.get("init_margin_change"),
        "init_margin_estimated_position_usage": init_relief,
        "maint_margin_before": payload.get("maint_margin_before"),
        "maint_margin_after": payload.get("maint_margin_after"),
        "maint_margin_change": payload.get("maint_margin_change"),
        "maint_margin_estimated_position_usage": maint_relief,
        "equity_with_loan_before": payload.get("equity_with_loan_before"),
        "equity_with_loan_after": payload.get("equity_with_loan_after"),
        "equity_with_loan_change": payload.get("equity_with_loan_change"),
        "commission": payload.get("commission"),
        "warning_text": payload.get("warning_text"),
        "note": (
            "estimated_position_usage is derived from the absolute margin change of a WHAT-IF close order. "
            "That is an estimate of margin released by closing the current position."
        ),
    }


def print_human(summary: dict[str, Any]) -> None:
    def fmt(value: Any) -> str:
        if value is None or str(value).strip() == "":
            return "unavailable"
        return str(value)

    print("")
    print("Position")
    print(f"  account:   {summary['account']}")
    print(f"  symbol:    {summary['symbol']}")
    print(f"  conId:     {summary['conid']}")
    print(f"  secType:   {summary['sec_type']}")
    print(f"  position:  {summary['position']}")
    print(f"  avg_cost:  {summary['avg_cost']}")
    print("")
    print("What-if Close Margin")
    print(f"  init before:   {fmt(summary['init_margin_before'])}")
    print(f"  init change:   {fmt(summary['init_margin_change'])}")
    print(f"  init after:    {fmt(summary['init_margin_after'])}")
    print(f"  init usage*:   {fmt(summary['init_margin_estimated_position_usage'])}")
    print(f"  maint before:  {fmt(summary['maint_margin_before'])}")
    print(f"  maint change:  {fmt(summary['maint_margin_change'])}")
    print(f"  maint after:   {fmt(summary['maint_margin_after'])}")
    print(f"  maint usage*:  {fmt(summary['maint_margin_estimated_position_usage'])}")
    if summary.get("warning_text"):
        print("")
        print(f"IB warning: {summary['warning_text']}")
    print("")
    print("* usage = geschatte margin die vrijkomt als deze positie wordt gesloten")


def main() -> int:
    defaults = load_ib_settings()
    parser = build_parser(defaults)
    args = parser.parse_args()

    if not args.symbol and args.conid <= 0:
        parser.error("Gebruik minimaal --symbol of --conid om de positie te kiezen.")

    app = MarginProbeApp()
    app.connect(args.host, args.port, clientId=args.client_id)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()

    if not app.ready.wait(timeout=8):
        print(f"[{ts()}] Geen nextValidId ontvangen. Controleer TWS/Gateway connectie.")
        app.disconnect()
        return 1

    print(f"[{ts()}] Requesting positions...")
    app.reqPositions()
    if not app.positions_done.wait(timeout=args.timeout_sec):
        print(f"[{ts()}] Timeout waiting for positions.")
        app.cancelPositions()
        app.disconnect()
        return 1
    app.cancelPositions()

    try:
        selected = match_position(app.positions, account=args.account, symbol=args.symbol, conid=args.conid)
    except RuntimeError as exc:
        print(f"[{ts()}] {exc}")
        app.disconnect()
        return 1

    try:
        qualified_contract = qualify_position_contract(app, selected.contract, args.timeout_sec)
    except RuntimeError as exc:
        print(f"[{ts()}] {exc}")
        app.disconnect()
        return 1

    order = build_close_order(selected)
    if app.next_order_id is None:
        print(f"[{ts()}] Geen geldig order id beschikbaar.")
        app.disconnect()
        return 1

    print(
        f"[{ts()}] Sending WHAT-IF close order for account={selected.account} "
        f"symbol={qualified_contract.symbol} conId={getattr(qualified_contract, 'conId', 0)} "
        f"secType={qualified_contract.secType} exchange={qualified_contract.exchange} "
        f"prim={getattr(qualified_contract, 'primaryExchange', '') or '-'} "
        f"qty={order.totalQuantity} action={order.action} orderType={order.orderType}"
    )
    app.placeOrder(app.next_order_id, qualified_contract, order)

    if not app.whatif_done.wait(timeout=args.timeout_sec):
        print(f"[{ts()}] Timeout waiting for what-if margin response.")
        app.disconnect()
        return 1

    app.disconnect()
    time.sleep(0.2)

    if app.whatif_payload is None:
        if app.error_messages:
            print("\n".join(app.error_messages))
        return 1

    summary = summarize(selected, app.whatif_payload)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_human(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

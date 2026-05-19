from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


INFO_CODES = {1100, 1101, 1102, 2103, 2104, 2105, 2106, 2107, 2108, 2158, 2159}


@dataclass(frozen=True)
class IbkrRequest:
    symbol: str
    host: str
    port: int
    client_id: int
    duration: str
    currency: str = "USD"


class IbkrVolApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.done = threading.Event()
        self.rows: list[dict[str, Any]] = []
        self.error_message = ""
        self._lock = threading.Lock()

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def historicalData(self, reqId, bar):  # noqa: N802
        with self._lock:
            self.rows.append(
                {
                    "date": getattr(bar, "date", None),
                    "open": getattr(bar, "open", None),
                    "high": getattr(bar, "high", None),
                    "low": getattr(bar, "low", None),
                    "close": getattr(bar, "close", None),
                    "volume": getattr(bar, "volume", None),
                }
            )

    def historicalDataEnd(self, reqId, start, end):  # noqa: N802
        self.done.set()

    def error(self, reqId, *args):  # noqa: N802
        code = None
        message = ""
        if len(args) == 2:
            code, message = args
        elif len(args) == 3:
            code, message, _ = args
        elif len(args) >= 4:
            _, code, message, _ = args[:4]
        try:
            code = int(code)
        except Exception:
            pass
        if code in INFO_CODES:
            return
        if isinstance(message, str) and "fractional share" in message.lower():
            return
        if isinstance(message, str) and "connection is OK" in message:
            return
        if code in {200, 321, 162}:
            self.error_message = f"IBKR error {code}: {message}"
            self.done.set()


def fetch_ibkr_implied_volatility(request: IbkrRequest, *, timeout_sec: int = 30) -> pd.DataFrame:
    app = IbkrVolApp()
    app.connect(request.host, int(request.port), clientId=int(request.client_id))
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    try:
        if not app.ready.wait(timeout=8):
            raise RuntimeError("IBKR connection did not become ready")

        contract = Contract()
        contract.symbol = request.symbol.upper()
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = request.currency.upper() or "USD"

        app.reqHistoricalData(
            1,
            contract,
            "",
            request.duration,
            "1 day",
            "OPTION_IMPLIED_VOLATILITY",
            1,
            1,
            False,
            [],
        )
        if not app.done.wait(timeout=max(10, int(timeout_sec))):
            raise RuntimeError("IBKR implied-volatility request timed out")
        if app.error_message and not app.rows:
            raise RuntimeError(app.error_message)
        with app._lock:
            rows = list(app.rows)
    finally:
        try:
            app.cancelHistoricalData(1)
        except Exception:
            pass
        app.disconnect()
        time.sleep(0.2)

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["implied_vol"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").set_index("date")
    df["implied_vol"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["implied_vol"])


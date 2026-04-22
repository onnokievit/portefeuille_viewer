from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.dividend_calendar_repository import (
    DividendCalendarRow,
    load_asset_universe,
    replace_current_and_append_history,
)


DIVIDEND_TICK_TYPE = 59
DIVIDEND_GENERIC_TICKS = "456"
WORKER_TIMEOUT_SECONDS = 10.0
STOCK_TYPES = {"aandeel", "stock", "etf", "fonds", "fund", ""}
INFO_ERROR_CODES = {2103, 2104, 2106, 2158, 300}


@dataclass
class DividendRefreshResult:
    rows_processed: int
    rows_ok: int
    rows_error: int
    rows_skipped: int
    message: str


def _parse_float(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def parse_dividend_raw(raw_value: str) -> tuple[float | None, float | None, date | None, float | None]:
    parts = [part.strip() for part in str(raw_value or "").split(",")]
    while len(parts) < 4:
        parts.append("")
    trailing_12m = _parse_float(parts[0])
    forward_12m = _parse_float(parts[1])
    next_date = _parse_date(parts[2])
    next_amount = _parse_float(parts[3])
    return trailing_12m, forward_12m, next_date, next_amount


class DividendIbApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.connected_event = threading.Event()
        self.pending_lock = threading.Lock()
        self.pending: dict[int, dict[str, Any]] = {}

    def nextValidId(self, orderId):  # noqa: N802
        self.connected_event.set()

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):  # noqa: N802
        try:
            code = int(errorCode)
        except Exception:
            code = None
        if code in INFO_ERROR_CODES:
            return
        with self.pending_lock:
            state = self.pending.get(int(reqId))
            if state is not None:
                state["error"] = f"IB {errorCode}: {errorString}"
                state["event"].set()

    def tickString(self, reqId, tickType, value):  # noqa: N802
        if int(tickType) != DIVIDEND_TICK_TYPE:
            return
        with self.pending_lock:
            state = self.pending.get(int(reqId))
            if state is not None:
                state["value"] = str(value or "")
                state["event"].set()


class DividendCalendarService:
    def __init__(self, timeout_sec: float = WORKER_TIMEOUT_SECONDS) -> None:
        self.timeout_sec = float(timeout_sec)

    def refresh(self) -> DividendRefreshResult:
        settings = get_settings()
        host = settings.get_ib_host()
        port = settings.get_ib_port()
        client_id = settings.get_ib_client_id() + 50 + random.randint(1, 4999)
        assets = load_asset_universe()
        fetched_at = datetime.now()

        app = DividendIbApp()
        app.connect(host, port, clientId=client_id)
        thread = threading.Thread(target=app.run, daemon=True)
        thread.start()
        if not app.connected_event.wait(timeout=8.0):
            with _suppress():
                app.disconnect()
            raise RuntimeError("Timeout: geen verbinding met IBKR gateway voor dividend refresh")

        rows: list[DividendCalendarRow] = []
        try:
            for asset in assets:
                rows.append(self._fetch_one(app, asset, fetched_at))
                time.sleep(0.05)
        finally:
            with _suppress():
                app.disconnect()

        replace_current_and_append_history(rows)
        rows_ok = sum(1 for row in rows if row.status == "ok")
        rows_error = sum(1 for row in rows if row.status == "error")
        rows_skipped = sum(1 for row in rows if row.status == "skipped")
        return DividendRefreshResult(
            rows_processed=len(rows),
            rows_ok=rows_ok,
            rows_error=rows_error,
            rows_skipped=rows_skipped,
            message=f"Dividend calendar refreshed: processed={len(rows)} ok={rows_ok} error={rows_error} skipped={rows_skipped}",
        )

    def _fetch_one(self, app: DividendIbApp, asset: dict[str, Any], fetched_at: datetime) -> DividendCalendarRow:
        now = datetime.now()
        asset_type = str(asset.get("asset_type") or "").strip().lower()
        if asset_type and asset_type not in STOCK_TYPES:
            return self._build_row(
                asset,
                fetched_at=fetched_at,
                updated_at=now,
                status="skipped",
                message=f"type '{asset_type}' overgeslagen",
            )

        contract = self._build_contract(asset)
        req_id = int(time.time() * 1000) % 1_000_000 + random.randint(1, 999)
        event = threading.Event()
        state: dict[str, Any] = {"event": event, "value": "", "error": ""}
        with app.pending_lock:
            app.pending[req_id] = state
        try:
            app.reqMktData(req_id, contract, DIVIDEND_GENERIC_TICKS, False, False, [])
            event.wait(timeout=self.timeout_sec)
        finally:
            with _suppress():
                app.cancelMktData(req_id)
            with app.pending_lock:
                app.pending.pop(req_id, None)

        raw_value = str(state.get("value") or "").strip()
        error = str(state.get("error") or "").strip()
        if error:
            return self._build_row(
                asset,
                fetched_at=fetched_at,
                updated_at=now,
                status="error",
                message=error,
            )
        if not raw_value:
            return self._build_row(
                asset,
                fetched_at=fetched_at,
                updated_at=now,
                status="no_data",
                message="Geen dividenddata van IBKR ontvangen binnen timeout",
            )
        trailing_12m, forward_12m, next_date, next_amount = parse_dividend_raw(raw_value)
        return self._build_row(
            asset,
            fetched_at=fetched_at,
            updated_at=now,
            status="ok",
            message="Dividend ontvangen",
            trailing_12m_dividend=trailing_12m,
            forward_12m_dividend=forward_12m,
            next_dividend_date=next_date,
            next_dividend_amount=next_amount,
            raw_dividend_value=raw_value,
        )

    @staticmethod
    def _build_contract(asset: dict[str, Any]) -> Contract:
        contract = Contract()
        contract.secType = "STK"
        contract.symbol = str(asset.get("ib_symbol") or "").strip()
        contract.currency = str(asset.get("ib_currency") or "USD").strip() or "USD"
        contract.exchange = str(asset.get("exchange") or "SMART").strip() or "SMART"
        prim_exchange = str(asset.get("prim_exchange") or "").strip()
        if prim_exchange:
            contract.primaryExchange = prim_exchange
        contractid = asset.get("contractid")
        if contractid:
            contract.conId = int(contractid)
        return contract

    @staticmethod
    def _build_row(
        asset: dict[str, Any],
        *,
        fetched_at: datetime,
        updated_at: datetime,
        status: str,
        message: str,
        trailing_12m_dividend: float | None = None,
        forward_12m_dividend: float | None = None,
        next_dividend_date: date | None = None,
        next_dividend_amount: float | None = None,
        raw_dividend_value: str = "",
    ) -> DividendCalendarRow:
        return DividendCalendarRow(
            asset_rollup=str(asset.get("asset_rollup") or "").strip(),
            ib_symbol=str(asset.get("ib_symbol") or "").strip(),
            ib_currency=str(asset.get("ib_currency") or "").strip(),
            next_dividend_date=next_dividend_date,
            next_dividend_amount=next_dividend_amount,
            trailing_12m_dividend=trailing_12m_dividend,
            forward_12m_dividend=forward_12m_dividend,
            next_earnings_date=None,
            source_dividend="IBKR",
            source_earnings="",
            status=str(status),
            message=str(message or ""),
            raw_dividend_value=str(raw_dividend_value or ""),
            fetched_at=fetched_at,
            updated_at=updated_at,
        )


class _suppress:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return True

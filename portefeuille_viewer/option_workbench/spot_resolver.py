from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pyodbc
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper

from .db_access import connect_access, load_latest_spot, table_columns

LogFn = Callable[[str], None]
UNSET_DOUBLE = 1e100


@dataclass(frozen=True)
class SpotQuote:
    price: float | None
    source: str
    detail: str = ""


class SpotMarketDataApp(EWrapper, EClient):
    def __init__(self, log: LogFn | None = None) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.log = log or (lambda _msg: None)
        self.ready = threading.Event()
        self.seen = threading.Event()
        self.bid: float | None = None
        self.ask: float | None = None
        self.last: float | None = None
        self.close: float | None = None
        self.market_data_type: int | None = None
        self.errors: list[tuple[int, str]] = []

    def nextValidId(self, orderId: int) -> None:
        self.ready.set()

    def error(self, reqId, errorCode, errorString, advancedOrderReject="") -> None:
        code = int(errorCode or 0)
        if code in {2103, 2104, 2105, 2106, 2107, 2108, 2119, 2158}:
            return
        msg = str(errorString or "")
        self.errors.append((code, msg))
        self.log(f"[spot ibkr error] reqId={reqId} code={code} msg={msg}")

    def marketDataType(self, reqId, marketDataType: int) -> None:
        self.market_data_type = int(marketDataType or 0)

    def tickPrice(self, reqId, tickType, price, attrib) -> None:
        value = _clean_float(price)
        if value is None or value <= 0:
            return
        tick = int(tickType or -1)
        if tick == 1:
            self.bid = value
        elif tick == 2:
            self.ask = value
        elif tick == 4:
            self.last = value
        elif tick == 9:
            self.close = value
        else:
            return
        self.seen.set()

    def best_price(self) -> tuple[float | None, str]:
        if self.last and self.last > 0:
            return self.last, "last"
        if self.bid and self.ask and self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0, "mid"
        if self.close and self.close > 0:
            return self.close, "close"
        if self.bid and self.bid > 0:
            return self.bid, "bid"
        if self.ask and self.ask > 0:
            return self.ask, "ask"
        return None, ""


def resolve_spot(
    *,
    asset: dict,
    stock_db_path: str | Path,
    host: str,
    port: int,
    client_id_min: int,
    client_id_max: int,
    market_data_type: int = 1,
    log: LogFn | None = None,
    timeout_sec: float = 4.0,
) -> SpotQuote:
    log = log or (lambda _msg: None)
    ib_quote = fetch_ibkr_spot(
        asset=asset,
        host=host,
        port=port,
        client_id_min=client_id_min,
        client_id_max=client_id_max,
        market_data_type=market_data_type,
        log=log,
        timeout_sec=timeout_sec,
    )
    if ib_quote.price is not None:
        return ib_quote

    last_price = load_asset_last_price(stock_db_path, asset)
    if last_price.price is not None:
        return last_price

    close, info = load_latest_spot(stock_db_path, str(asset.get("asset_rollup") or ""))
    if close is not None:
        return SpotQuote(close, "historical_data_correct", str(info))
    return SpotQuote(None, "none", f"geen spot gevonden; ibkr={ib_quote.detail}")


def fetch_ibkr_spot(
    *,
    asset: dict,
    host: str,
    port: int,
    client_id_min: int,
    client_id_max: int,
    market_data_type: int = 1,
    log: LogFn | None = None,
    timeout_sec: float = 4.0,
) -> SpotQuote:
    log = log or (lambda _msg: None)
    client_id = random.randint(min(client_id_min, client_id_max), max(client_id_min, client_id_max))
    app = SpotMarketDataApp(log)
    thread: threading.Thread | None = None
    req_id = 9001
    symbol = str(asset.get("ib_symbol") or asset.get("asset_rollup") or "").upper()
    currency = str(asset.get("ib_currency") or "").upper()
    exchange = _spot_exchange(str(asset.get("exchange") or ""), currency)
    try:
        app.connect(host, int(port), client_id)
        thread = threading.Thread(target=app.run, daemon=True)
        thread.start()
        if not app.ready.wait(timeout=min(10.0, max(1.0, timeout_sec))):
            return SpotQuote(None, "ibkr", "connection timeout")
        app.reqMarketDataType(int(market_data_type or 1))
        app.reqMktData(req_id, _stock_contract(symbol, currency, exchange), "", False, False, [])
        deadline = time.perf_counter() + max(0.5, float(timeout_sec))
        while time.perf_counter() < deadline:
            app.seen.wait(timeout=0.25)
            price, field = app.best_price()
            if price is not None and field in {"last", "mid"}:
                detail = f"{symbol}/{currency} {field} exchange={exchange} md_type={app.market_data_type}"
                return SpotQuote(price, "ibkr_req_mkt_data", detail)
        price, field = app.best_price()
        if price is not None:
            detail = f"{symbol}/{currency} {field} exchange={exchange} md_type={app.market_data_type}"
            return SpotQuote(price, "ibkr_req_mkt_data", detail)
        detail = "; ".join(f"{code}:{msg}" for code, msg in app.errors[-3:]) or "no ticks"
        return SpotQuote(None, "ibkr_req_mkt_data", detail)
    except Exception as exc:
        return SpotQuote(None, "ibkr_req_mkt_data", str(exc))
    finally:
        try:
            app.cancelMktData(req_id)
        except Exception:
            pass
        try:
            app.disconnect()
        except Exception:
            pass
        if thread is not None:
            thread.join(timeout=1.0)


def load_asset_last_price(stock_db_path: str | Path, asset: dict) -> SpotQuote:
    asset_rollup = str(asset.get("asset_rollup") or "").upper()
    symbol = str(asset.get("ib_symbol") or asset_rollup).upper()
    currency = str(asset.get("ib_currency") or "").upper()
    with connect_access(stock_db_path) as conn:
        cur = conn.cursor()
        cols = table_columns(cur, "asset_last_prices")
        required = {"ib_symbol", "ib_currency", "price", "last_update"}
        if not required.issubset(cols):
            return SpotQuote(None, "asset_last_prices", "tabel/kolommen ontbreken")
        candidates = _asset_last_price_candidates(asset_rollup, symbol, currency)
        placeholders = ", ".join("?" for _ in candidates)
        rows = cur.execute(
            f"""
            SELECT [ib_symbol], [ib_currency], [price], [last_update]
            FROM asset_last_prices
            WHERE UCASE([ib_symbol]) IN ({placeholders}) AND UCASE([ib_currency]) = ?
            ORDER BY IIF(UCASE([ib_symbol]) = ?, 0, 1), [last_update] DESC
            """,
            (*candidates, currency, symbol),
        ).fetchall()
    for row in rows:
        try:
            price = float(row[2])
        except Exception:
            continue
        if price > 0:
            return SpotQuote(price, "asset_last_prices", f"{row[0]}/{row[1]} {row[3]}")
    return SpotQuote(None, "asset_last_prices", f"geen prijs voor {symbol}/{currency}")


def _asset_last_price_candidates(asset_rollup: str, symbol: str, currency: str) -> list[str]:
    raw = [symbol, asset_rollup, f"{symbol}.{currency}", f"{symbol}{currency}"]
    out: list[str] = []
    for value in raw:
        clean = str(value or "").upper()
        if clean and clean not in out:
            out.append(clean)
    return out


def _stock_contract(symbol: str, currency: str, exchange: str) -> Contract:
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "STK"
    contract.exchange = exchange or "SMART"
    contract.currency = currency
    return contract


def _spot_exchange(asset_exchange: str, currency: str) -> str:
    ex = str(asset_exchange or "").upper()
    if ex in {"AEB", "FTA", "ENEXT.BE", "SBF"}:
        return "SMART"
    if ex in {"IBIS", "EUREX", "FWB"}:
        return "SMART"
    if currency in {"USD", "EUR", "GBP"}:
        return "SMART"
    return "SMART"


def _clean_float(value) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if abs(out) >= UNSET_DOUBLE or out != out:
        return None
    return out

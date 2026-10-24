import contextlib
import copy
import os
import time
import threading
from datetime import date, datetime, timedelta
from typing import Dict, Tuple, Optional, List

import pandas as pd
from PySide6.QtCore import QObject, Signal, Slot

from portefeuille_viewer.data.asset_last_price_store import ASSET_LAST_PRICE_STORE
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.services.subscription_manager import SubscriptionManager
from portefeuille_viewer.services.quote_delivery_trace import QuoteDeliveryTrace


_PRICE_FEED_PERF_LOG = str(os.getenv("PRICE_FEED_PERF_LOG", "1")).strip() == "1"


# ------------------------------------------------------------
# PriceStore (cache)
# ------------------------------------------------------------
class PriceStore:
    """Houdt actuele koersen per (ib_symbol, currency) bij in een dict/DF-cache."""
    def __init__(self, initial: dict[tuple[str, str], float] | None = None):
        self._cache: dict[tuple[str, str], float] = {}
        self.set_many(initial or {})

    @staticmethod
    def _fx_aliases(sym: str, cur: str) -> list[tuple[str, str]]:
        sym_s = str(sym or "").strip().upper()
        cur_s = str(cur or "").strip().upper()
        aliases: list[tuple[str, str]] = []
        if len(sym_s) == 3 and len(cur_s) == 3 and sym_s.isalpha() and cur_s.isalpha():
            aliases.append((f"{sym_s}.{cur_s}", cur_s))
            aliases.append((f"{sym_s}{cur_s}", cur_s))
        return aliases

    def set(self, sym: str, cur: str, px: float):
        """Voeg of update prijs in de cache."""
        sym_s = str(sym or "").strip().upper()
        cur_s = str(cur or "").strip().upper()
        self._cache[(sym_s, cur_s)] = px
        for alias in self._fx_aliases(sym_s, cur_s):
            self._cache[alias] = px

    def set_many(self, prices: dict[tuple[str, str], float]):
        for key, price in dict(prices or {}).items():
            if isinstance(key, tuple) and len(key) == 2 and price not in (None, 0.0):
                self.set(key[0], key[1], float(price))

    def replace_all(self, prices: dict[tuple[str, str], float]):
        self._cache = {}
        self.set_many(prices)

    def get(self, sym: str, cur: str) -> Optional[float]:
        """Haal prijs op, of None."""
        sym_s = str(sym or "").strip().upper()
        cur_s = str(cur or "").strip().upper()
        return self._cache.get((sym_s, cur_s))

    def snapshot(self) -> dict[tuple[str, str], float]:
        """Geeft dict (sym,cur)->prijs terug."""
        return dict(self._cache)

    def snapshot_df(self) -> pd.DataFrame:
        """Geeft DataFrame met kolommen [_ib_symbol, _ib_currency, Koers]."""
        if not self._cache:
            return pd.DataFrame(columns=["_ib_symbol", "_ib_currency", "Koers"])
        rows = [(sym, cur, px) for (sym, cur), px in self._cache.items()]
        return pd.DataFrame(rows, columns=["_ib_symbol", "_ib_currency", "Koers"])


# ------------------------------------------------------------
# IB API laag (ibapi wrapper)
# ------------------------------------------------------------
def _subscription_logger():
    import logging
    from logging.handlers import RotatingFileHandler
    from pathlib import Path
    logger = logging.getLogger(f"portefeuille.subscriptions.{os.getpid()}")
    if not logger.handlers:
        try:
            folder = Path(__file__).resolve().parents[2] / "logs"
            folder.mkdir(exist_ok=True)
            handler = RotatingFileHandler(folder / f"ibkr_subscriptions_{os.getpid()}.log",
                                          maxBytes=2_000_000, backupCount=2, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        except OSError:
            handler = logging.NullHandler()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


class _SubscriptionTransport:
    def __init__(self, feed):
        self.feed = feed

    def next_id(self):
        return self.feed.next_tid()

    def contract(self, spec, fallback=False):
        feed = self.feed
        meta = spec["meta"]
        if spec["kind"] == "option":
            c = feed._Contract()
            c.secType = "FOP" if fallback else "OPT"
            c.conId = meta["conid"]
            c.exchange = meta["exchange"]
            c.currency = meta["currency"]
            return c
        return feed._build_contract(meta["sym"], meta["cur"], meta["asset_type"],
                                    meta.get("exch"), meta.get("pex"), meta.get("cid"),
                                    use_conid=fallback)

    def start(self, req_id, spec, fallback):
        feed = self.feed
        contract = self.contract(spec, fallback)
        if not feed._can_request_market_data():
            raise RuntimeError("TWS niet gereed")
        with feed._lock:
            if spec["kind"] == "option":
                feed._option_tid_meta[req_id] = dict(spec["meta"])
            else:
                feed._tid_by_key[req_id] = (spec["symbol"], spec["currency"])
                feed._sub_meta[req_id] = dict(spec["meta"])
                # New stream must not inherit an earlier session's Last/bid/ask.
                # PriceStore retains the visible fallback with its old timestamp.
                feed._prices.pop((spec["symbol"], spec["currency"]), None)
        self.event(f"request={req_id} instrument={spec['symbol']} contract={spec['contractid']}")
        feed._app.reqMktData(req_id, contract, "", False, False, [])

    def cancel(self, req_id):
        feed = self.feed
        with feed._lock:
            feed._tid_by_key.pop(req_id, None)
            feed._sub_meta.pop(req_id, None)
            feed._option_tid_meta.pop(req_id, None)
        if feed._app is not None:
            feed._app.cancelMktData(req_id)
        self.event(f"cancel request={req_id}")

    def details(self, req_id, spec, fallback):
        feed = self.feed
        key = spec["key"]
        feed._cd_handlers[req_id] = lambda detail: feed.subscriptions.details(key, req_id, detail)
        feed._cd_end_handlers[req_id] = lambda: feed.subscriptions.details_end(key, req_id)
        contract = self.contract(spec, fallback)
        # Metadata resolution should prefer a known exact contract.
        if spec["kind"] != "option" and spec["meta"].get("cid"):
            contract.conId = int(spec["meta"]["cid"])
        feed._app.reqContractDetails(req_id, contract)

    def event(self, message):
        self.feed.log.emit(f"[subscriptions] {message}")
        self.feed._subscription_logger.info(message)

    def forget_details(self, req_id):
        self.feed._cd_handlers.pop(req_id, None)
        self.feed._cd_end_handlers.pop(req_id, None)


class PriceFeedIB(QObject):
    priceUpdated = Signal(str, str, float)  # ib_symbol, currency, price
    quoteReceived = Signal(str, str, float, dict)  # selected price + receipt provenance
    optionTickUpdated = Signal(dict)  # option tick payload for one series_id
    log = Signal(str)
    ready = Signal()
    statusChanged = Signal(str)
    connectionLost = Signal(str)

    def __init__(self, host: str, port: int, client_id: int, parent=None):
        super().__init__(parent)
        self._lock = threading.RLock()
        self._desired_subscriptions: Dict[Tuple, dict] = {}
        self._active_subscriptions = set()
        self._tid_next = 5200
        self._tid_by_key: Dict[int, Tuple[str, str]] = {}
        self._sub_meta: Dict[int, dict] = {}
        self._desired_option_subscriptions: set[tuple[int, int, str, str]] = set()
        self._active_option_subscriptions = set()
        self._option_tid_meta: Dict[int, dict] = {}
        self._app = None
        self._app_thread = None
        self._prices: Dict[Tuple[str,str], Dict[str, float]] = {}
        self.host, self.port, self.client_id = host, port, client_id
        # Dispatcher dicts
        self._cd_handlers = {}  # reqId -> on_detail
        self._cd_end_handlers = {}  # reqId -> on_end
        self._sd_handlers = {}  # reqId -> on_param
        self._sd_end_handlers = {}  # reqId -> on_end
        # Connection state + reconnect guard
        self._is_ready = False
        self._status = "disconnected"
        self._upstream_connected = True
        self._last_disconnect_reason = ""
        self._reconnect_lock = threading.Lock()
        self._reconnect_inflight = False
        self._shutdown_requested = False
        self._reconnect_attempted = False
        self._heartbeat_interval_sec = max(5.0, float(os.getenv("IB_HEARTBEAT_INTERVAL_SEC", "15")))
        self._heartbeat_timeout_sec = max(5.0, float(os.getenv("IB_HEARTBEAT_TIMEOUT_SEC", "30")))
        self._heartbeat_max_missed = max(1, int(os.getenv("IB_HEARTBEAT_MAX_MISSED", "2")))
        self._last_heartbeat_request_at: float | None = None
        self._last_heartbeat_response_at: float | None = None
        self._last_tick_at: float | None = None
        self._missed_heartbeats = 0
        self._reconnect_attempt_count = 0
        from portefeuille_viewer.config import get_settings
        config = get_settings().get_market_data_settings()
        self._subscription_logger = _subscription_logger()
        self.subscriptions = SubscriptionManager(_SubscriptionTransport(self), **config)
        self._subscription_stop = threading.Event()
        self._subscription_worker = threading.Thread(target=self._subscription_loop, daemon=True,
                                                     name="ibkr-subscriptions")
        self._subscription_worker.start()
        self._watchdog_stop = threading.Event()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()
        if not self._start_session("initial"):
            self._schedule_reconnect(reason="initial_connect_failed", delay=2.0)

    def _set_status(self, status: str) -> None:
        if self._status == status:
            return
        self._status = status
        self._publish_status_snapshot()
        self.statusChanged.emit(status)
        self.log.emit(f"[ibkr] status={status} endpoint={self.host}:{self.port} clientId={self.client_id}")

    def connection_status(self) -> str:
        return self._status

    def endpoint(self) -> tuple[str, int, int]:
        return self.host, int(self.port), int(self.client_id)

    def connection_info(self) -> dict:
        managed = self.subscriptions.counts()
        with self._lock:
            return {
                "status": self._status,
                "host": self.host,
                "port": int(self.port),
                "client_id": int(self.client_id),
                "is_ready": bool(self._is_ready),
                "last_disconnect_reason": self._last_disconnect_reason,
                "last_heartbeat_request_at": self._last_heartbeat_request_at,
                "last_heartbeat_response_at": self._last_heartbeat_response_at,
                "last_tick_at": self._last_tick_at,
                "missed_heartbeats": int(self._missed_heartbeats),
                "reconnect_attempt_count": int(self._reconnect_attempt_count),
                "desired_subscriptions": managed["desired_subscriptions"],
                "active_subscriptions": managed["active_subscriptions"],
                "desired_option_subscriptions": managed["desired_option_subscriptions"],
                "active_option_subscriptions": managed["active_option_subscriptions"],
            }

    def _publish_status_snapshot(self) -> None:
        now = time.monotonic()
        if now - getattr(self, "_status_published_at", 0) < 1:
            return
        self._status_published_at = now
        with contextlib.suppress(Exception):
            SNAPSHOT_STORE.set_live_price_status(self.connection_info())

    def _mark_tick_seen(self) -> None:
        with self._lock:
            self._last_tick_at = time.time()
        self._publish_status_snapshot()

    def _handle_heartbeat_ok(self, ib_time=None) -> None:
        with self._lock:
            self._last_heartbeat_response_at = time.time()
            self._missed_heartbeats = 0
        if self._status == "stale" and self._upstream_connected:
            self._set_status("connected")
        else:
            self._publish_status_snapshot()

    def _request_heartbeat(self) -> None:
        app = self._app
        if app is None or not self._is_ready:
            return
        with self._lock:
            self._last_heartbeat_request_at = time.time()
        with contextlib.suppress(Exception):
            app.reqCurrentTime()
        self._publish_status_snapshot()

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(self._heartbeat_interval_sec):
            if self._shutdown_requested:
                return
            if self._status not in {"connected", "stale"} or not self._is_ready:
                continue
            now = time.time()
            with self._lock:
                req_at = self._last_heartbeat_request_at
                resp_at = self._last_heartbeat_response_at
                heartbeat_outstanding = req_at is not None and (resp_at is None or resp_at < req_at)
                heartbeat_overdue = (
                    heartbeat_outstanding
                    and now - req_at >= self._heartbeat_timeout_sec
                )
                if heartbeat_overdue:
                    self._missed_heartbeats += 1
                    missed = self._missed_heartbeats
                else:
                    missed = self._missed_heartbeats
            if heartbeat_overdue:
                self.log.emit(f"[ibkr] heartbeat missed count={missed}")
                if missed >= self._heartbeat_max_missed:
                    self._handle_connection_lost(f"heartbeat_timeout missed={missed}")
                    continue
                self._set_status("stale")
            elif heartbeat_outstanding:
                self._publish_status_snapshot()
                continue
            self._request_heartbeat()

    def _start_session(self, reason: str = "start") -> bool:
        from ibapi.client import EClient
        from ibapi.wrapper import EWrapper
        from ibapi.contract import Contract

        feed = self

        class App(EWrapper, EClient):
            def __init__(self):
                EClient.__init__(self, self)

            def nextValidId(self, orderId: int):
                if feed._app is not self:
                    return
                with feed._lock:
                    feed._is_ready = True
                    feed._missed_heartbeats = 0
                    feed._last_heartbeat_response_at = time.time()
                    feed._active_subscriptions.clear()
                    feed._active_option_subscriptions.clear()
                    feed._tid_by_key.clear()
                    feed._sub_meta.clear()
                    feed._option_tid_meta.clear()
                feed._upstream_connected = True
                # Prefer delayed feed so indices without realtime entitlement still stream.
                with contextlib.suppress(Exception):
                    self.reqMarketDataType(3)
                feed.subscriptions.reset(True)
                feed._set_status("connected")
                feed._resubscribe_all_desired()
                feed.ready.emit()

            def error(self, reqId, *args):
                if feed._app is not self:
                    return
                # IB 10.25: (errorCode, errorString, advancedOrderRejectJson?)
                # IB 10.37: (errorTime, errorCode, errorString, advancedOrderRejectJson?)
                errorTime = None
                advancedOrderRejectJson = ""
                if len(args) == 2:
                    errorCode, errorString = args
                elif len(args) == 3:
                    if isinstance(args[1], int):
                        errorTime, errorCode, errorString = args
                    else:
                        errorCode, errorString, advancedOrderRejectJson = args
                elif len(args) >= 4:
                    errorTime, errorCode, errorString, advancedOrderRejectJson = args[:4]
                else:
                    return
                # Handle clientId conflict: auto-retry once with incremented clientId
                if errorCode == 326:
                    if not getattr(feed, "_reconnect_attempted", False):
                        feed._reconnect_attempted = True
                        new_id = feed.client_id + 1
                        feed.log.emit(f"ERROR 326: Client ID {feed.client_id} in use; retrying with {new_id}...")
                        feed.reconnect(client_id=new_id, reason="client_id_conflict", delay=0.5)
                    return
                if errorCode not in (2103,2104,2106,2158):
                    # Try to find which symbol caused the error
                    with feed._lock:
                        key = feed._tid_by_key.get(reqId)
                    if key:
                        sym, cur = key
                        feed.log.emit(f"IB ERROR {errorCode} for {sym} ({cur}): {errorString}")
                    else:
                        feed.log.emit(f"IB ERROR {errorCode}: {errorString}")

                try:
                    code = int(errorCode)
                except (TypeError, ValueError):
                    return
                if code == 1100:
                    feed._upstream_connected = False
                    feed.subscriptions.pause(True)
                    feed._set_status("stale")
                elif code == 1101:
                    feed._upstream_connected = True
                    feed._clear_subscription_maps()
                    feed.subscriptions.reset(True)
                    feed._set_status("connected")
                elif code == 1102:
                    feed._upstream_connected = True
                    feed.subscriptions.pause(False)
                    feed._set_status("connected")
                feed._subscription_logger.info("IB error request=%s code=%s %s", reqId, code, errorString)
                feed.subscriptions.error(reqId, code, str(errorString))

            def marketDataType(self, reqId, marketDataType):
                feed.subscriptions.market_type(reqId, marketDataType)

            def tickPrice(self, reqId, tickType, price, attrib):
                if feed._app is not self:
                    return
                field = {1: "bid", 2: "ask", 4: "last", 9: "close",
                         66: "delayed_bid", 67: "delayed_ask", 68: "delayed_last", 75: "delayed_close"}.get(int(tickType))
                if not field or not feed.subscriptions.tick(reqId, field, float(price), delayed=int(tickType) >= 66):
                    return
                with feed._lock:
                    option_meta = feed._option_tid_meta.get(reqId)
                if option_meta:
                    px = float(price)
                    if px > 0:
                        name = {
                            1: "bid",
                            2: "ask",
                            4: "last",
                            9: "close",
                            66: "delayed_bid",
                            67: "delayed_ask",
                            68: "delayed_last",
                            75: "delayed_close",
                        }.get(int(tickType))
                        if name:
                            payload = {
                                "series_id": int(option_meta.get("series_id")),
                                "conid": int(option_meta.get("conid")) if option_meta.get("conid") is not None else None,
                                "req_id": int(reqId),
                                "tick_type": int(tickType),
                                "field": name,
                                "value": px,
                                "ts": time.time(),
                            }
                            feed._mark_tick_seen()
                            feed._emit_option_payload(option_meta, payload)
                    return

                with feed._lock:
                    key = feed._tid_by_key.get(reqId)
                if not key:
                    return
                sym, cur = key
                px = float(price)
                if tickType in (4, 68):  # last + delayed last
                    if px <= 0:
                        return
                    with feed._lock:
                        entry = feed._prices.setdefault((sym, cur), {})
                        entry["last"] = px
                        entry["ts"] = time.time()
                    feed._mark_tick_seen()
                    feed._publish_asset_price(reqId, sym, cur, px, field)
                    return

                if tickType in (9, 75):  # close + delayed close as fallback
                    if px <= 0:
                        return
                    with feed._lock:
                        entry = feed._prices.setdefault((sym, cur), {})
                        has_last = entry.get("last") is not None
                        if not has_last:
                            entry["close"] = px
                            entry["ts"] = time.time()
                    if not has_last:
                        feed._mark_tick_seen()
                        feed._publish_asset_price(reqId, sym, cur, px, field)
                    return

                if tickType in (1, 2, 66, 67):  # bid/ask, also delayed
                    if px <= 0:
                        return
                    with feed._lock:
                        entry = feed._prices.setdefault((sym, cur), {})
                        if tickType in (1, 66):
                            entry["bid"] = px
                        else:
                            entry["ask"] = px
                        entry["ts"] = time.time()
                        bid = entry.get("bid")
                        ask = entry.get("ask")
                        last = entry.get("last")
                    # Shares retain Last (or explicitly tracked close fallback).
                    # FX has no normal trade Last and may use bid/ask midpoint.
                    with feed._lock:
                        asset_type = str(feed._sub_meta.get(reqId, {}).get("asset_type", ""))
                    if asset_type in {"cash", "fx", "forex"} and bid is not None and ask is not None:
                        mid = (bid + ask) / 2.0
                        feed._mark_tick_seen()
                        feed._publish_asset_price(reqId, sym, cur, mid, "mid")

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
                with feed._lock:
                    option_meta = feed._option_tid_meta.get(reqId)
                if not option_meta:
                    return
                payload = {
                    "series_id": int(option_meta.get("series_id")),
                    "conid": int(option_meta.get("conid")) if option_meta.get("conid") is not None else None,
                    "req_id": int(reqId),
                    "tick_type": int(tickType),
                    "iv": None if impliedVol is None else float(impliedVol),
                    "delta": None if delta is None else float(delta),
                    "gamma": None if gamma is None else float(gamma),
                    "theta": None if theta is None else float(theta),
                    "vega": None if vega is None else float(vega),
                    "model_price": None if optPrice is None else float(optPrice),
                    "underlying_price": None if undPrice is None else float(undPrice),
                    "ts": time.time(),
                }
                if feed.subscriptions.tick(reqId, "greeks", None):
                    feed._mark_tick_seen()
                    feed._emit_option_payload(option_meta, payload)

            def currentTime(self, time_):
                if feed._app is not self:
                    return
                feed._handle_heartbeat_ok(time_)

            # Dispatcher for contractDetails
            def contractDetails(self, reqId, contractDetails):
                handler = feed._cd_handlers.get(reqId)
                if handler:
                    handler(contractDetails)

            def contractDetailsEnd(self, reqId):
                end = feed._cd_end_handlers.pop(reqId, None)
                feed._cd_handlers.pop(reqId, None)
                if end:
                    end()

            # Dispatcher for secdef opt params
            def securityDefinitionOptionParameter(self, reqId, exchange, underlyingConId, tradingClass, multiplier, expirations, strikes):
                handler = feed._sd_handlers.get(reqId)
                if handler:
                    handler(exchange, underlyingConId, tradingClass, multiplier, expirations, strikes)

            def securityDefinitionOptionParameterEnd(self, reqId):
                end = feed._sd_end_handlers.pop(reqId, None)
                feed._sd_handlers.pop(reqId, None)
                if end:
                    end()

            def connectionClosed(self):
                if feed._app is not self:
                    return
                feed._handle_connection_lost("connectionClosed")

        self._Contract = Contract
        self._set_status("connecting")
        app = App()
        with self._lock:
            self._app = app
            self._is_ready = False
        try:
            from portefeuille_viewer.services.ib_connection_guard import connect_ib
            self.client_id = connect_ib(app, self.host, self.port, self.client_id, managed_feed=True)
        except Exception as exc:
            self.log.emit(f"[ibkr] connect failed reason={reason}: {exc}")
            self._set_status("disconnected")
            return False
        t = threading.Thread(target=app.run, daemon=True)
        with self._lock:
            self._app_thread = t
        t.start()
        return True

    def _disconnect_current_app(self) -> None:
        self.subscriptions.reset(False)
        app = None
        thread = None
        with self._lock:
            app = self._app
            thread = self._app_thread
            self._app = None
            self._app_thread = None
            self._is_ready = False
            self._active_subscriptions.clear()
            self._active_option_subscriptions.clear()
            self._tid_by_key.clear()
            self._sub_meta.clear()
            self._option_tid_meta.clear()
            self._cd_handlers.clear()
            self._cd_end_handlers.clear()
            self._sd_handlers.clear()
            self._sd_end_handlers.clear()
        with contextlib.suppress(Exception):
            if app is not None:
                app.disconnect()
        if thread is not None and thread is not threading.current_thread():
            with contextlib.suppress(Exception):
                thread.join(timeout=1.0)

    def _handle_connection_lost(self, reason: str) -> None:
        if self._shutdown_requested:
            return
        self.subscriptions.reset(False)
        self._last_disconnect_reason = str(reason or "unknown")
        self.connectionLost.emit(self._last_disconnect_reason)
        self.log.emit(f"[ibkr] connection lost reason={self._last_disconnect_reason}")
        with self._lock:
            self._is_ready = False
            self._active_subscriptions.clear()
            self._active_option_subscriptions.clear()
            self._tid_by_key.clear()
            self._sub_meta.clear()
            self._option_tid_meta.clear()
            self._cd_handlers.clear()
            self._cd_end_handlers.clear()
            self._sd_handlers.clear()
            self._sd_end_handlers.clear()
        self._schedule_reconnect(reason=self._last_disconnect_reason, delay=2.0)

    def _schedule_reconnect(self, reason: str = "connection_lost", delay: float = 0.0) -> None:
        with self._reconnect_lock:
            if self._reconnect_inflight or self._shutdown_requested:
                return
            self._reconnect_inflight = True
        self._set_status("reconnecting")

        def _run():
            try:
                if delay > 0:
                    time.sleep(delay)
                backoffs = [2.0, 5.0, 10.0, 30.0]
                attempt = 0
                while not self._shutdown_requested:
                    attempt += 1
                    with self._lock:
                        self._reconnect_attempt_count = attempt
                    self._disconnect_current_app()
                    self.log.emit(
                        f"[ibkr] reconnect attempt={attempt} reason={reason} "
                        f"endpoint={self.host}:{self.port} clientId={self.client_id}"
                    )
                    started = self._start_session(reason)
                    if started:
                        deadline = time.time() + 8.0
                        while time.time() < deadline and not self._shutdown_requested:
                            if self._is_ready:
                                return
                            time.sleep(0.2)
                    if self._shutdown_requested:
                        return
                    wait_sec = backoffs[min(attempt - 1, len(backoffs) - 1)]
                    self.log.emit(f"[ibkr] reconnect waiting {wait_sec:.1f}s")
                    time.sleep(wait_sec)
            finally:
                with self._reconnect_lock:
                    self._reconnect_inflight = False

        threading.Thread(target=_run, daemon=True).start()

    def reconnect(self, host: str | None = None, port: int | None = None, client_id: int | None = None, reason: str = "manual", delay: float = 0.0) -> None:
        if host is not None:
            self.host = str(host).strip() or self.host
        if port is not None:
            self.port = int(port)
        if client_id is not None:
            self.client_id = int(client_id)
        self._reconnect_attempted = False
        self._schedule_reconnect(reason=reason, delay=delay)

    def _resubscribe_all_desired(self) -> None:
        # The worker rebuilds subscriptions gradually within the shared budget.
        self.log.emit("[ibkr] subscription manager ready; paced subscription recovery")

    def _clear_subscription_maps(self):
        with self._lock:
            self._active_subscriptions.clear()
            self._active_option_subscriptions.clear()
            self._tid_by_key.clear()
            self._sub_meta.clear()
            self._option_tid_meta.clear()

    def _subscription_loop(self):
        while not self._subscription_stop.wait(0.1):
            try:
                self.subscriptions.step()
            except Exception as exc:
                self.log.emit(f"[ibkr] subscription manager: {exc}")
                self._subscription_logger.exception("manager step failed")
                self._subscription_stop.wait(1)

    def _emit_option_payload(self, meta, payload):
        for sid in meta.get("series_ids", [meta["series_id"]]):
            self.optionTickUpdated.emit({**payload, "series_id": sid})

    def _publish_asset_price(self, req_id, symbol, currency, price, source):
        receipt = self.subscriptions.processed(req_id, price, source)
        if receipt is not None:
            self.quoteReceived.emit(symbol, currency, price, receipt)
            self.priceUpdated.emit(symbol, currency, price)

    def next_tid(self):
        with self._lock:
            tid = self._tid_next
            self._tid_next += 1
            return tid

    # API: request contract details (async, per reqId handler)
    def request_contract_details(self, contract, on_detail, on_end):
        tid = self.next_tid()
        self._cd_handlers[tid] = on_detail
        self._cd_end_handlers[tid] = on_end
        self._app.reqContractDetails(tid, contract)
        return tid

    # API: request secdef opt params (async, per reqId handler)
    def request_secdef_opt_params(self, symbol, exchange, secType, conId, on_param, on_end):
        tid = self.next_tid()
        self._sd_handlers[tid] = on_param
        self._sd_end_handlers[tid] = on_end
        self._app.reqSecDefOptParams(tid, symbol, exchange, secType, conId)
        return tid

    def is_ready(self) -> bool:
        return self._is_ready

    def _can_request_market_data(self) -> bool:
        return bool(self._app is not None and self._is_ready)

    def _make_stock(self, symbol, currency, primaryExchange):
        c = self._Contract()
        c.symbol = symbol
        c.secType = "STK"
        c.currency = currency
        c.exchange = "SMART"
        if primaryExchange:
            c.primaryExchange = primaryExchange
        return c

    def _resolve_index_exchange(self, symbol: str, exchange: Optional[str], primary_exchange: Optional[str]) -> str:
        ex = (exchange or "").strip().upper()
        pex = (primary_exchange or "").strip().upper()
        # SMART is usually invalid/ambiguous for IND contracts; prefer concrete venue.
        if ex and ex not in {"SMART"}:
            return ex
        if pex and pex not in {"SMART"}:
            return pex
        # Last-resort symbol hints for common indices.
        sym = (symbol or "").strip().upper()
        hints = {
            "EOE": "FTA",
            "AEX": "FTA",
            "DAX": "EUREX",
            "NDX": "NASDAQ",
            "TSX": "TSE",
            "TXCX": "TSE",
        }
        return hints.get(sym, "SMART")

    def _make_index(self, symbol, currency, exchange, primaryExchange):
        c = self._Contract()
        c.symbol = symbol
        c.secType = "IND"
        c.currency = currency
        c.exchange = self._resolve_index_exchange(symbol, exchange, primaryExchange)
        if primaryExchange:
            c.primaryExchange = primaryExchange
        return c

    def _make_future(self, symbol, currency, exchange, primaryExchange):
        c = self._Contract()
        c.symbol = symbol
        c.secType = "FUT"
        c.currency = currency
        c.exchange = exchange or primaryExchange or "SMART"
        if primaryExchange:
            c.primaryExchange = primaryExchange
        return c

    @staticmethod
    def _parse_cash_pair(symbol: str, currency: str) -> tuple[str, str]:
        sym = str(symbol or "").strip().upper()
        cur = str(currency or "").strip().upper()

        parts = [p for p in sym.replace("-", ".").replace("_", ".").split(".") if p]
        if len(parts) == 2 and all(len(p) == 3 and p.isalpha() for p in parts):
            return parts[0], parts[1]

        compact = "".join(ch for ch in sym if ch.isalpha()).upper()
        if len(compact) == 6:
            return compact[:3], compact[3:]

        if len(sym) == 3 and len(cur) == 3 and sym.isalpha() and cur.isalpha():
            return sym, cur

        return sym, cur

    def _make_cash(self, symbol, currency, exchange, primaryExchange):
        base_ccy, quote_ccy = self._parse_cash_pair(symbol, currency)
        c = self._Contract()
        c.symbol = base_ccy
        c.secType = "CASH"
        c.currency = quote_ccy
        c.exchange = (exchange or primaryExchange or "IDEALPRO").upper()
        return c

    def _build_contract(
        self,
        symbol: str,
        currency: str,
        asset_type: str,
        exchange: Optional[str],
        primary_exchange: Optional[str],
        contract_id: Optional[int] = None,
        use_conid: bool = False,
    ):
        t = (asset_type or "").strip().lower()
        if t == "index":
            c = self._make_index(symbol, currency, exchange, primary_exchange)
        elif t in {"cash", "fx", "forex"}:
            c = self._make_cash(symbol, currency, exchange, primary_exchange)
        elif t in {"future", "fut"}:
            c = self._make_future(symbol, currency, exchange, primary_exchange)
        else:
            c = self._make_stock(symbol, currency, primary_exchange)
        try:
            cid = int(contract_id) if contract_id is not None and str(contract_id).strip() != "" else 0
        except Exception:
            cid = 0
        # For STK/IND: prefer symbol-based resolution; use conId only as fallback.
        # For FUT: conId remains primary when present.
        if cid > 0 and (t in {"future", "fut"} or use_conid):
            c.conId = cid
        return c

    def _normalize_subscription_row(self, row) -> tuple[Tuple | None, dict | None]:
        sym = cur = None
        asset_type = "aandeel"
        exch = None
        pex = None
        cid = None
        if isinstance(row, (list, tuple)):
            if len(row) >= 6:
                sym, cur, asset_type, exch, pex, cid = row[:6]
            elif len(row) >= 5:
                sym, cur, asset_type, exch, pex = row[:5]
            elif len(row) >= 3:
                sym, cur, pex = row[:3]
            elif len(row) >= 2:
                sym, cur = row[:2]
        if not sym or not cur:
            return None, None
        sym_s = str(sym).strip()
        cur_s = str(cur).strip()
        if not sym_s or not cur_s:
            return None, None
        meta = {
            "sym": sym_s,
            "cur": cur_s,
            "asset_type": (asset_type or "aandeel").strip().lower() if isinstance(asset_type, str) else str(asset_type or "aandeel").strip().lower(),
            "exch": str(exch or "").strip(),
            "pex": str(pex or "").strip(),
            "cid": cid,
            "retried_with_conid": False,
        }
        label = (meta["sym"], meta["cur"], meta["asset_type"], meta["exch"], meta["pex"], str(cid or ""))
        return label, meta

    @Slot(list)
    def ensure_subscriptions(self, rows: List[Tuple]):
        specs = []
        for row in rows:
            label, meta = self._normalize_subscription_row(row)
            if not label:
                continue
            cid = str(meta.get("cid") or "").strip()
            key = ("asset", "conid", cid) if cid and cid != "0" else ("asset",) + label
            specs.append({"key": key, "kind": "asset", "label": label,
                          "symbol": meta["sym"], "currency": meta["cur"],
                          "asset_type": meta["asset_type"], "exchange": meta["exch"] or meta["pex"],
                          "contractid": cid, "meta": meta})
        self.subscriptions.set_source("assets", specs)

    @Slot(list)
    def ensure_option_subscriptions(self, rows: List[Tuple]):
        specs = {}
        for row in rows:
            try:
                sid, cid = int(row[0]), int(row[1])
                exchange = str(row[2] if len(row) > 2 else "SMART").upper() or "SMART"
                currency = str(row[3] if len(row) > 3 else "").upper()
                display_name = str(row[4] or "").strip() if len(row) > 4 else ""
            except (ValueError, TypeError, IndexError):
                continue
            if cid <= 0:
                continue
            key = ("option", cid)
            if key in specs:
                specs[key]["meta"]["series_ids"].append(sid)
                continue
            specs[key] = {"key": key, "kind": "option", "label": (sid, cid, exchange, currency),
                          "display_name": display_name,
                          "symbol": f"Optie {sid}", "currency": currency, "asset_type": "optie",
                          "exchange": exchange, "contractid": cid,
                          "meta": {"series_id": sid, "series_ids": [sid], "conid": cid,
                                   "exchange": exchange, "currency": currency}}
        self.subscriptions.set_source("options", list(specs.values()))

    def snapshot_prices(self) -> Dict[Tuple[str,str], Dict[str,float]]:
        with self._lock:
            return {k: v.copy() for k, v in self._prices.items()}

    def shutdown(self):
        self._shutdown_requested = True
        self._subscription_stop.set()
        self._watchdog_stop.set()
        if self._subscription_worker is not threading.current_thread():
            self._subscription_worker.join(timeout=2)
        self._set_status("disconnected")
        with contextlib.suppress(Exception):
            self._disconnect_current_app()


# ------------------------------------------------------------
# PriceFeedService (Qt wrapper rond IB + PriceStore)
# ------------------------------------------------------------
class PriceFeedService(QObject):
    def get_all_prices(self):
        """
        Geeft alle actuele prijzen terug als dict met tuple key.
        Voor aandelen: (sym, cur)
        Voor opties (in de toekomst): (asset_rollup, cur, exp_date, strike, call_put)
        """
        return self.snapshot()
    """
    Qt-vriendelijke wrapper rond PriceFeedIB + PriceStore.
    Deze gebruik je in je UI.
    """
    priceUpdated = Signal(str, str, float)  # ib_symbol, currency, price
    optionTickUpdated = Signal(dict)
    statusChanged = Signal(str)
    connectionLost = Signal(str)

    def __init__(self, host, port, client_id, parent=None, *, feed_factory=None):
        # print("[DEBUG] PriceFeedService aangemaakt:", id(self))
        super().__init__(parent)
        initial_prices = ASSET_LAST_PRICE_STORE.ensure_loaded()
        self.store = PriceStore(initial_prices)
        self._asset_processed_at = {}
        self.quote_delivery = QuoteDeliveryTrace()
        self._feed = (feed_factory or PriceFeedIB)(host, port, client_id)
        self._shared_proxy = bool(getattr(self._feed, "_shared_proxy", False))
        self._feed.quoteReceived.connect(self._on_quote_received)
        self._feed.optionTickUpdated.connect(self._on_option_tick)
        self._feed.statusChanged.connect(self.statusChanged.emit)
        self._feed.connectionLost.connect(self.connectionLost.emit)
        self._option_lock = threading.Lock()
        self._option_prices: Dict[int, dict] = {}
        self._active_option_series_ids: set[int] = set()
        self._active_option_series_known = False
        self._dirty_option_series_ids: set[int] = set()
        self._option_cleanup_date: date | None = None
        self._asset_save_state_lock = threading.Lock()
        self._asset_save_inflight = False
        self._asset_save_pending = False
        self._option_save_state_lock = threading.Lock()
        self._option_save_inflight = False
        self._option_save_pending = False
        self._option_save_idle = threading.Event()
        self._option_save_idle.set()
        self._load_option_last_prices_from_db()

        # Timer voor periodiek opslaan
        from PySide6.QtCore import QTimer
        
        self._save_timer = QTimer(self)
        self._save_timer.timeout.connect(self.save_last_prices_to_db)
        if not self._shared_proxy:
            self._save_timer.start(300_000)  # elke 5 minuten
        self._option_save_timer = QTimer(self)
        self._option_save_timer.timeout.connect(self.save_option_last_prices_to_db)
        option_save_interval_ms = max(
            60_000,
            int(os.getenv("OPTION_LAST_PRICES_SAVE_INTERVAL_MS", "900000")),
        )
        if not self._shared_proxy:
            self._option_save_timer.start(option_save_interval_ms)  # default elke 15 minuten

    @staticmethod
    def _table_columns(cursor, table_name: str) -> set[str]:
        cols: set[str] = set()
        try:
            cursor.execute(f"SELECT TOP 1 * FROM {table_name}")
            cols = {str(d[0]).strip().lower() for d in (cursor.description or [])}
        except Exception:
            return set()
        return cols

    @staticmethod
    def _connect_option_last_prices_db():
        # option_last_prices moet in STOCKDATA staan (zelfde DB als option_series_master)
        from portefeuille_viewer.data import repository
        return repository.get_stockdata_connection()

    @staticmethod
    def _pick_option_price_from_entry(entry: dict) -> tuple[Optional[float], Optional[str]]:
        times = entry.get("field_times", {})
        now = time.time()
        def positive(key):
            try:
                value = float(entry.get(key))
                return value if value > 0 else None
            except (ValueError, TypeError):
                return None
        pairs = []
        for prefix in ("", "delayed_"):
            bid, ask = positive(prefix + "bid"), positive(prefix + "ask")
            received = min(times.get(prefix + "bid", 0), times.get(prefix + "ask", 0))
            if bid is not None and ask is not None and ask >= bid and now - received <= 180:
                pairs.append((received, (bid + ask) / 2, prefix + "mid"))
        if pairs:
            _received, value, source = max(pairs)
            return value, source
        for family in (("last", "delayed_last"), ("model_price",), ("close", "delayed_close")):
            candidates = [(times.get(key, 0), positive(key), key) for key in family
                          if times.get(key) and positive(key) is not None]
            if candidates:
                _received, value, source = max(candidates)
                return value, source
        return None, None

    @staticmethod
    def _ensure_option_last_prices_table(cursor) -> None:
        cols = PriceFeedService._table_columns(cursor, "option_last_prices")
        if cols:
            # Additief uitbreiden: conid kolom indien nog niet aanwezig.
            if "conid" not in cols:
                with contextlib.suppress(Exception):
                    cursor.execute("ALTER TABLE option_last_prices ADD COLUMN conid LONG")
            return
        try:
            cursor.execute(
                """
                CREATE TABLE option_last_prices (
                    series_id LONG,
                    asset_rollup TEXT(64),
                    optie_call_put TEXT(8),
                    optie_strike DOUBLE,
                    optie_exp_date DATETIME,
                    conid LONG,
                    bid DOUBLE,
                    ask DOUBLE,
                    last_price DOUBLE,
                    mid_price DOUBLE,
                    underlying_price DOUBLE,
                    iv DOUBLE,
                    delta_greek DOUBLE,
                    gamma DOUBLE,
                    theta DOUBLE,
                    ts DATETIME
                )
                """
            )
        except Exception:
            pass

    def _load_option_last_prices_from_db(self) -> None:
        loaded: Dict[int, dict] = {}
        try:
            with self._connect_option_last_prices_db() as conn:
                cur = conn.cursor()
                if not getattr(self, "_shared_proxy", False):
                    self._ensure_option_last_prices_table(cur)
                try:
                    cur.execute(
                        """
                        SELECT * FROM option_last_prices
                        """
                    )
                except Exception:
                    return
                col_list = [str(d[0]).strip() for d in (cur.description or [])]
                for row in cur.fetchall():
                    rec = {col_list[i].lower(): row[i] for i in range(len(col_list))}
                    try:
                        sid = int(rec.get("series_id"))
                    except Exception:
                        continue
                    bid = rec.get("bid")
                    ask = rec.get("ask")
                    last_px = rec.get("last_px")
                    if last_px is None:
                        last_px = rec.get("last_price")
                    und_px = rec.get("und_px")
                    if und_px is None:
                        und_px = rec.get("underlying_price")
                    delta = rec.get("delta")
                    if delta is None:
                        delta = rec.get("delta_greek")
                    px_source = rec.get("px_source")
                    if not px_source:
                        px_source = "db_last"
                    loaded[sid] = {
                        "series_id": sid,
                        "conid": rec.get("conid"),
                        "last_px": last_px,
                        "px_source": px_source,
                        "bid": bid,
                        "ask": ask,
                        "underlying_price": und_px,
                        "iv": rec.get("iv"),
                        "delta": delta,
                        "gamma": rec.get("gamma"),
                        "theta": rec.get("theta"),
                        "last_update": rec.get("last_update") or rec.get("ts"),
                    }
        except Exception:
            return
        with self._option_lock:
            self._option_prices = loaded

    def set_active_option_series_ids(self, series_ids) -> None:
        active: set[int] = set()
        for sid in series_ids or []:
            try:
                active.add(int(sid))
            except Exception:
                continue
        with self._option_lock:
            self._active_option_series_ids = active
            self._active_option_series_known = True
            self._option_prices = {
                sid: row for sid, row in self._option_prices.items() if sid in active or sid in self._dirty_option_series_ids
            }

    def _cleanup_expired_option_last_prices_if_due(self) -> None:
        today = date.today()
        if self._option_cleanup_date == today:
            return
        self._option_cleanup_date = today
        grace_days = max(0, int(os.getenv("OPTION_LAST_PRICES_EXPIRY_GRACE_DAYS", "7")))
        cutoff = datetime.combine(today - timedelta(days=grace_days), datetime.min.time())
        try:
            with self._connect_option_last_prices_db() as conn:
                cursor = conn.cursor()
                self._ensure_option_last_prices_table(cursor)
                cols = self._table_columns(cursor, "option_last_prices")
                expiry_col = None
                for candidate in ("optie_exp_date", "expiry", "exp_date"):
                    if candidate in cols:
                        expiry_col = candidate
                        break
                if not expiry_col:
                    return
                cursor.execute(
                    f"DELETE FROM option_last_prices WHERE {expiry_col} IS NOT NULL AND {expiry_col} < ?",
                    (cutoff,),
                )
                deleted = cursor.rowcount
                conn.commit()
                if _PRICE_FEED_PERF_LOG and deleted:
                    print(
                        f"[price-feed] cleanup=option_last_prices_expired rows={deleted} cutoff={cutoff.date().isoformat()}"
                    )
        except Exception as exc:
            if _PRICE_FEED_PERF_LOG:
                print(f"[price-feed] cleanup=option_last_prices_expired failed: {exc}")

    def _save_last_prices_to_db_sync(self, prices: dict[tuple[str, str], float] | None = None, *, force: bool = False):
        t0 = time.perf_counter()
        if prices:
            ASSET_LAST_PRICE_STORE.update_many(prices)
        rows_written = ASSET_LAST_PRICE_STORE.save_to_db(force=force)
        if _PRICE_FEED_PERF_LOG:
            print(
                f"[price-feed] timer=save_last_prices_to_db rows={rows_written} total_ms={(time.perf_counter() - t0) * 1000.0:.1f}"
            )

    def _save_option_last_prices_to_db_sync(self, rows: list[dict]):
        t0 = time.perf_counter()
        self._cleanup_expired_option_last_prices_if_due()
        if not rows:
            if _PRICE_FEED_PERF_LOG:
                print("[price-feed] timer=save_option_last_prices_to_db rows=0 total_ms=0.0")
            return
        now = datetime.now()
        with self._connect_option_last_prices_db() as conn:
            cursor = conn.cursor()
            self._ensure_option_last_prices_table(cursor)
            cols = self._table_columns(cursor, "option_last_prices")
            legacy_mode = {"last_price", "mid_price", "underlying_price", "delta_greek", "ts"}.issubset(cols)
            # Verrijk met serie-metadata zodat option_last_prices ook sleutelvelden bevat.
            series_meta: Dict[int, dict] = {}
            with contextlib.suppress(Exception):
                cursor.execute(
                    """
                    SELECT series_id, asset_rollup, optie_call_put, strike, expiry
                    FROM option_series_master
                    """
                )
                for rr in cursor.fetchall():
                    try:
                        sid = int(rr[0])
                    except Exception:
                        continue
                    series_meta[sid] = {
                        "asset_rollup": rr[1],
                        "optie_call_put": rr[2],
                        "optie_strike": rr[3],
                        "optie_exp_date": rr[4],
                    }
            for r in rows:
                sid = r.get("series_id")
                if sid is None:
                    continue
                try:
                    sid_i = int(sid)
                except Exception:
                    continue
                meta = series_meta.get(sid_i, {})
                asset_rollup = meta.get("asset_rollup")
                optie_call_put = meta.get("optie_call_put")
                optie_strike = meta.get("optie_strike")
                optie_exp_date = meta.get("optie_exp_date")
                bid = r.get("bid")
                ask = r.get("ask")
                last_px = r.get("last_px")
                mid_px = None
                try:
                    if bid is not None and ask is not None:
                        b = float(bid)
                        a = float(ask)
                        if b > 0 and a > 0:
                            mid_px = (b + a) / 2.0
                except Exception:
                    mid_px = None

                if legacy_mode:
                    cursor.execute(
                        """
                        UPDATE option_last_prices
                        SET asset_rollup=?, optie_call_put=?, optie_strike=?, optie_exp_date=?, conid=?,
                            bid=?, ask=?, last_price=?, mid_price=?, underlying_price=?, iv=?, delta_greek=?, gamma=?, theta=?, ts=?
                        WHERE series_id=?
                        """,
                        (
                            asset_rollup,
                            optie_call_put,
                            optie_strike,
                            optie_exp_date,
                            r.get("conid"),
                            bid,
                            ask,
                            last_px,
                            mid_px,
                            r.get("underlying_price"),
                            r.get("iv"),
                            r.get("delta"),
                            r.get("gamma"),
                            r.get("theta"),
                            now,
                            sid,
                        ),
                    )
                    if cursor.rowcount == 0:
                        cursor.execute(
                            """
                            INSERT INTO option_last_prices
                                (series_id, asset_rollup, optie_call_put, optie_strike, optie_exp_date, conid, bid, ask, last_price, mid_price, underlying_price, iv, delta_greek, gamma, theta, ts)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                sid_i,
                                asset_rollup,
                                optie_call_put,
                                optie_strike,
                                optie_exp_date,
                                r.get("conid"),
                                bid,
                                ask,
                                last_px,
                                mid_px,
                                r.get("underlying_price"),
                                r.get("iv"),
                                r.get("delta"),
                                r.get("gamma"),
                                r.get("theta"),
                                now,
                            ),
                        )
                else:
                    cursor.execute(
                        """
                        UPDATE option_last_prices
                        SET asset_rollup=?, optie_call_put=?, optie_strike=?, optie_exp_date=?, conid=?,
                            last_px=?, px_source=?, bid=?, ask=?, und_px=?, iv=?, delta=?, gamma=?, theta=?, last_update=?
                        WHERE series_id=?
                        """,
                        (
                            asset_rollup,
                            optie_call_put,
                            optie_strike,
                            optie_exp_date,
                            r.get("conid"),
                            last_px,
                            r.get("px_source"),
                            bid,
                            ask,
                            r.get("underlying_price"),
                            r.get("iv"),
                            r.get("delta"),
                            r.get("gamma"),
                            r.get("theta"),
                            now,
                            sid,
                        ),
                    )
                    if cursor.rowcount == 0:
                        cursor.execute(
                            """
                            INSERT INTO option_last_prices
                                (series_id, asset_rollup, optie_call_put, optie_strike, optie_exp_date, conid, last_px, px_source, bid, ask, und_px, iv, delta, gamma, theta, last_update)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                sid_i,
                                asset_rollup,
                                optie_call_put,
                                optie_strike,
                                optie_exp_date,
                                r.get("conid"),
                                last_px,
                                r.get("px_source"),
                                bid,
                                ask,
                                r.get("underlying_price"),
                                r.get("iv"),
                                r.get("delta"),
                                r.get("gamma"),
                                r.get("theta"),
                                now,
                            ),
                        )
            conn.commit()
        if _PRICE_FEED_PERF_LOG:
            print(
                f"[price-feed] timer=save_option_last_prices_to_db rows={len(rows)} total_ms={(time.perf_counter() - t0) * 1000.0:.1f}"
            )

    def _run_asset_save_worker(self):
        try:
            while True:
                self._save_last_prices_to_db_sync()
                with self._asset_save_state_lock:
                    if self._asset_save_pending:
                        self._asset_save_pending = False
                        continue
                    self._asset_save_inflight = False
                    break
        except Exception as exc:
            with self._asset_save_state_lock:
                self._asset_save_inflight = False
            print(f"[price-feed] asset last-price save failed: {exc}")

    def _run_option_save_worker(self):
        try:
            while True:
                with self._option_lock:
                    dirty_ids = set(self._dirty_option_series_ids)
                    rows = [
                        copy.deepcopy(self._option_prices[sid])
                        for sid in dirty_ids
                        if sid in self._option_prices
                    ]
                self._save_option_last_prices_to_db_sync(rows)
                with self._option_lock:
                    for saved in rows:
                        sid = saved['series_id']
                        if self._option_prices.get(sid, {}).get('_save_revision', 0) == saved.get('_save_revision', 0):
                            self._dirty_option_series_ids.discard(sid)
                with self._option_save_state_lock:
                    if self._option_save_pending:
                        self._option_save_pending = False
                        continue
                    self._option_save_inflight = False
                    break
        except Exception as exc:
            with self._option_save_state_lock:
                self._option_save_inflight = False
            print(f"[price-feed] option last-price save failed: {exc}")
        finally:
            self._option_save_idle.set()

    def save_last_prices_to_db(self):
        if getattr(self, "_shared_proxy", False):
            return
        with self._asset_save_state_lock:
            if self._asset_save_inflight:
                self._asset_save_pending = True
                return
            self._asset_save_inflight = True
            self._asset_save_pending = False
        threading.Thread(target=self._run_asset_save_worker, daemon=True).start()

    def save_option_last_prices_to_db(self):
        if getattr(self, "_shared_proxy", False):
            return
        with self._option_save_state_lock:
            if self._option_save_inflight:
                self._option_save_pending = True
                return
            self._option_save_inflight = True
            self._option_save_idle.clear()
            self._option_save_pending = False
        threading.Thread(target=self._run_option_save_worker, daemon=True).start()

    def reload_asset_last_prices_from_store(self):
        self.store.replace_all(ASSET_LAST_PRICE_STORE.get_snapshot())
        self.quote_delivery.reset()
        self._asset_processed_at.clear()

    @Slot(str, str, float, dict)
    def _on_quote_received(self, sym, cur, px, receipt):
        self._on_price(sym, cur, px, receipt)

    @Slot(str, str, float)
    def _on_price(self, sym: str, cur: str, px: float, receipt=None):
        self.store.set(sym, cur, px)
        if getattr(self, "_shared_proxy", False):
            ASSET_LAST_PRICE_STORE.update_price(sym, cur, px, persist=False)
        else:
            ASSET_LAST_PRICE_STORE.update_price(sym, cur, px)
        self._asset_processed_at[(sym, cur)] = time.time()
        if receipt is not None:
            self.quote_delivery.processed(sym, cur, px, receipt)
        self.priceUpdated.emit(sym, cur, px)

    @Slot(dict)
    def _on_option_tick(self, payload: dict):
        try:
            sid = int(payload.get("series_id"))
        except Exception:
            sid = None
        if sid is not None:
            is_inactive = False
            with self._option_lock:
                is_inactive = self._active_option_series_known and sid not in self._active_option_series_ids
                if not is_inactive:
                    entry = self._option_prices.get(sid) or {"series_id": sid}
                    conid = payload.get("conid")
                    if conid is not None:
                        entry["conid"] = conid
                    field = payload.get("field")
                    value = payload.get("value")
                    if field:
                        entry[str(field)] = value
                        entry.setdefault("field_times", {})[str(field)] = payload.get("ts", time.time())
                    for gk in ("iv", "delta", "gamma", "theta", "model_price", "underlying_price"):
                        if payload.get(gk) is not None:
                            entry[gk] = payload.get(gk)
                            if gk == "model_price":
                                entry.setdefault("field_times", {})[gk] = payload.get("ts", time.time())
                    last_px, src = self._pick_option_price_from_entry(entry)
                    if last_px is not None:
                        entry["last_px"] = last_px
                        entry["px_source"] = src
                    if last_px is not None:
                        source_fields = (("bid", "ask") if src == "mid" else
                                         ("delayed_bid", "delayed_ask") if src == "delayed_mid" else (str(src),))
                        price_time = min((entry.get("field_times", {}).get(k, 0) for k in source_fields), default=0)
                        if price_time:
                            entry["last_update"] = datetime.fromtimestamp(price_time)
                        self._feed.subscriptions.processed(payload.get("req_id"), last_px, src)
                    entry["_save_revision"] = entry.get("_save_revision", 0) + 1
                    self._option_prices[sid] = entry
                    self._dirty_option_series_ids.add(sid)
        self.optionTickUpdated.emit(payload)

    def get_option_last(self, series_id: int) -> Optional[dict]:
        try:
            sid = int(series_id)
        except Exception:
            return None
        with self._option_lock:
            row = self._option_prices.get(sid)
            return dict(row) if row else None

    # convenience-methodes
    def get(self, sym: str, cur: str) -> Optional[float]:
        return self.store.get(sym, cur)

    def snapshot(self) -> dict[tuple[str, str], float]:
        return self.store.snapshot()

    def snapshot_df(self) -> pd.DataFrame:
        return self.store.snapshot_df()

    def is_ready(self) -> bool:
        return self._feed.is_ready()

    def connection_status(self) -> str:
        return self._feed.connection_status()

    def endpoint(self) -> tuple[str, int, int]:
        return self._feed.endpoint()

    def connection_info(self) -> dict:
        return self._feed.connection_info()

    def last_heartbeat_at(self) -> float | None:
        return self.connection_info().get("last_heartbeat_response_at")

    def last_tick_at(self) -> float | None:
        return self.connection_info().get("last_tick_at")

    def last_disconnect_reason(self) -> str:
        return str(self.connection_info().get("last_disconnect_reason") or "")

    def is_price_stale(self) -> bool:
        return self.connection_status() in {"stale", "reconnecting", "disconnected"}

    def reconnect(self, host: str | None = None, port: int | None = None, client_id: int | None = None):
        self._feed.reconnect(host=host, port=port, client_id=client_id, reason="manual")

    def subscription_snapshot(self):
        result = self._feed.subscriptions.snapshot()
        for row in result["rows"]:
            row["processed_at"] = self._asset_processed_at.get((row["symbol"], row["currency"]))
            if row["kind"] == "asset" and row["asset_type"] in {"aandeel", "stock", "stk"}:
                row["delivery"] = self.quote_delivery.snapshot(
                    row["symbol"], row["currency"], row["fields"].get("display"))
        return result

    def configure_subscriptions(self, **values):
        self._feed.subscriptions.configure(**values)

    def reset_subscription_rejection_counters(self):
        self._feed.subscriptions.reset_rejection_counters()

    def focus_asset(self, asset):
        asset = str(asset or "").strip().upper()
        self._focused_asset = asset
        frame = SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
        pairs = set()
        if asset and frame is not None and not frame.is_empty():
            for row in frame.to_dicts():
                if str(row.get("asset_rollup", "")).strip().upper() == asset:
                    pairs.add((str(row.get("ib_symbol", "")).upper(), str(row.get("ib_currency", "")).upper()))
        snapshot = self.subscription_snapshot()
        keys = [r["key"] for r in snapshot["rows"] if r["kind"] == "asset" and
                (r["symbol"].upper(), r["currency"].upper()) in pairs]
        self._feed.subscriptions.set_focus(keys)

    def ensure_subscriptions(self, rows: List[tuple]):
        self._feed.ensure_subscriptions(rows)
        self.focus_asset(getattr(self, "_focused_asset", ""))

    def ensure_option_subscriptions(self, rows: List[tuple]):
        self._feed.ensure_option_subscriptions(rows)

    def shutdown(self):
        if getattr(self, "_shared_proxy", False):
            self._feed.shutdown()
            return
        with contextlib.suppress(Exception):
            if hasattr(self, "_save_timer") and self._save_timer.isActive():
                self._save_timer.stop()
            if hasattr(self, "_option_save_timer") and self._option_save_timer.isActive():
                self._option_save_timer.stop()
            self._save_last_prices_to_db_sync(force=True)
            if not self._option_save_idle.wait(45):
                raise TimeoutError("Bestaande optieschrijfopdracht is nog bezig; geen overlappende afsluitflush")
            with self._option_lock:
                dirty_ids = set(self._dirty_option_series_ids)
                rows = [
                    copy.deepcopy(self._option_prices[sid])
                    for sid in dirty_ids
                    if sid in self._option_prices
                ]
            self._save_option_last_prices_to_db_sync(rows)
        self._feed.shutdown()

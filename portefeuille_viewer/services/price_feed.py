import contextlib
import os
import time
import threading
from datetime import date, datetime, timedelta
from typing import Dict, Tuple, Optional, List

import pandas as pd
from PySide6.QtCore import QObject, Signal, Slot

from portefeuille_viewer.data.asset_last_price_store import ASSET_LAST_PRICE_STORE


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
class PriceFeedIB(QObject):
    priceUpdated = Signal(str, str, float)  # ib_symbol, currency, price
    optionTickUpdated = Signal(dict)  # option tick payload for one series_id
    log = Signal(str)
    ready = Signal()

    def __init__(self, host: str, port: int, client_id: int, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._subscribed = set()
        self._tid_next = 5200
        self._tid_by_key: Dict[int, Tuple[str, str]] = {}
        self._sub_meta: Dict[int, dict] = {}
        self._option_subscribed = set()
        self._option_tid_meta: Dict[int, dict] = {}
        self._app = None
        self._prices: Dict[Tuple[str,str], Dict[str, float]] = {}
        self.host, self.port, self.client_id = host, port, client_id
        # Dispatcher dicts
        self._cd_handlers = {}  # reqId -> on_detail
        self._cd_end_handlers = {}  # reqId -> on_end
        self._sd_handlers = {}  # reqId -> on_param
        self._sd_end_handlers = {}  # reqId -> on_end
        # Connection state + reconnect guard
        self._is_ready = False
        self._reconnect_attempted = False
        self._start()

    def _start(self):
        from ibapi.client import EClient
        from ibapi.wrapper import EWrapper
        from ibapi.contract import Contract

        feed = self

        class App(EWrapper, EClient):
            def __init__(self):
                EClient.__init__(self, self)

            def nextValidId(self, orderId: int):
                feed._is_ready = True
                # Prefer delayed feed so indices without realtime entitlement still stream.
                with contextlib.suppress(Exception):
                    self.reqMarketDataType(3)
                feed.ready.emit()

            def error(self, reqId, *args):
                # IB 10.25: (errorCode, errorString, advancedOrderRejectJson?)
                # IB 10.37: (errorTime, errorCode, errorString, advancedOrderRejectJson?)
                errorTime = None
                advancedOrderRejectJson = ""
                if len(args) == 2:
                    errorCode, errorString = args
                elif len(args) == 3:
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
                        def _do():
                            try:
                                if feed._app:
                                    feed._app.disconnect()
                                time.sleep(0.5)
                                feed.client_id = new_id
                                feed._is_ready = False
                                feed._app.connect(feed.host, feed.port, clientId=feed.client_id)
                            except Exception as e:
                                feed.log.emit(f"Reconnect failed: {e}")
                        threading.Thread(target=_do, daemon=True).start()
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

                # Fallback: retry STK/IND once with conId when sec-def lookup fails.
                try:
                    err_code_i = int(errorCode)
                except Exception:
                    err_code_i = None
                if err_code_i == 200:
                    if reqId in feed._option_tid_meta:
                        feed._retry_option_as_fop(reqId)
                        return
                    feed._retry_with_conid_if_needed(reqId)

            def tickPrice(self, reqId, tickType, price, attrib):
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
                            feed.optionTickUpdated.emit(payload)
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
                    feed.priceUpdated.emit(sym, cur, px)
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
                        feed.priceUpdated.emit(sym, cur, px)
                    return

                if tickType in (1, 2):  # bid/ask
                    if px <= 0:
                        return
                    with feed._lock:
                        entry = feed._prices.setdefault((sym, cur), {})
                        if tickType == 1:
                            entry["bid"] = px
                        else:
                            entry["ask"] = px
                        entry["ts"] = time.time()
                        bid = entry.get("bid")
                        ask = entry.get("ask")
                        last = entry.get("last")
                    if last is None and bid is not None and ask is not None:
                        mid = (bid + ask) / 2.0
                        feed.priceUpdated.emit(sym, cur, mid)

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
                feed.optionTickUpdated.emit(payload)

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

        self._Contract = Contract
        self._app = App()
        self._app.connect(self.host, self.port, clientId=self.client_id)
        t = threading.Thread(target=self._app.run, daemon=True)
        t.start()

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

    def _retry_with_conid_if_needed(self, req_id: int) -> None:
        if not self._app:
            return
        with self._lock:
            meta = dict(self._sub_meta.get(req_id) or {})
        if not meta:
            return
        if bool(meta.get("retried_with_conid")):
            return
        try:
            cid = int(meta.get("cid") or 0)
        except Exception:
            cid = 0
        if cid <= 0:
            return
        asset_type = str(meta.get("asset_type") or "").strip().lower()
        if asset_type in {"future", "fut"}:
            return
        sym = str(meta.get("sym") or "")
        cur = str(meta.get("cur") or "")
        exch = meta.get("exch")
        pex = meta.get("pex")
        contract = self._build_contract(sym, cur, asset_type, exch, pex, cid, use_conid=True)
        with self._lock:
            new_tid = self._tid_next
            self._tid_next += 1
            self._tid_by_key[new_tid] = (sym, cur)
            meta["retried_with_conid"] = True
            self._sub_meta[new_tid] = meta
        self.log.emit(f"Retry with conId for {sym} ({cur}) after sec-def error.")
        self._app.reqMktData(new_tid, contract, "", False, False, [])

    def _retry_option_as_fop(self, req_id: int) -> None:
        if not self._app:
            return
        with self._lock:
            meta = dict(self._option_tid_meta.get(req_id) or {})
        if not meta:
            return
        if bool(meta.get("retried_fop")):
            return
        try:
            conid = int(meta.get("conid") or 0)
            series_id = int(meta.get("series_id") or 0)
        except Exception:
            return
        if conid <= 0 or series_id <= 0:
            return

        contract = self._Contract()
        contract.secType = "FOP"
        contract.conId = conid
        contract.exchange = str(meta.get("exchange") or "SMART")
        currency = str(meta.get("currency") or "")
        if currency:
            contract.currency = currency

        with self._lock:
            new_tid = self._tid_next
            self._tid_next += 1
            meta["retried_fop"] = True
            self._option_tid_meta[new_tid] = meta
            self._option_tid_meta.pop(req_id, None)
        self.log.emit(f"Retry option as FOP for series_id={series_id} conId={conid}")
        self._app.reqMktData(new_tid, contract, "", False, False, [])

    @Slot(list)
    def ensure_subscriptions(self, rows: List[Tuple]):
        """Vraag marktdata aan voor subscriptions.

        Ondersteunt:
        - legacy: (sym, cur, prim_exch)
        - nieuw:   (sym, cur, asset_type, exchange, prim_exch[, contractid])
        """
        if not self._app:
            return
        for row in rows:
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
                continue
            label = (sym, cur, (asset_type or "").strip().lower(), exch or "", pex or "", str(cid or ""))
            if label in self._subscribed:
                continue
            tid = self._tid_next
            self._tid_next += 1
            self._tid_by_key[tid] = (sym, cur)
            self._sub_meta[tid] = {
                "sym": sym,
                "cur": cur,
                "asset_type": (asset_type or "").strip().lower(),
                "exch": exch,
                "pex": pex,
                "cid": cid,
                "retried_with_conid": False,
            }
            contract = self._build_contract(sym, cur, asset_type, exch, pex, cid, use_conid=False)
            self._app.reqMktData(tid, contract, "", False, False, [])
            self._subscribed.add(label)
            time.sleep(0.01)

    @Slot(list)
    def ensure_option_subscriptions(self, rows: List[Tuple]):
        """Start option market-data subscriptions.

        rows format: (series_id, conid, exchange_code, ib_currency)
        """
        if not self._app:
            return
        desired_labels: set[tuple[int, int, str, str]] = set()
        normalized_rows: list[tuple[int, int, str, str]] = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            try:
                series_id_i = int(row[0])
                conid_i = int(row[1])
            except Exception:
                continue
            if conid_i <= 0:
                continue
            exchange_code = str((row[2] if len(row) > 2 else "SMART") or "SMART").upper()
            ib_currency = str((row[3] if len(row) > 3 else "") or "").upper()
            label = (series_id_i, conid_i, exchange_code, ib_currency)
            desired_labels.add(label)
            normalized_rows.append(label)

        stale_tids: list[int] = []
        with self._lock:
            for tid, meta in list(self._option_tid_meta.items()):
                try:
                    label = (
                        int(meta.get("series_id")),
                        int(meta.get("conid")),
                        str(meta.get("exchange") or "SMART").upper(),
                        str(meta.get("currency") or "").upper(),
                    )
                except Exception:
                    continue
                if label not in desired_labels:
                    stale_tids.append(tid)
                    self._option_tid_meta.pop(tid, None)
                    self._option_subscribed.discard(label)
        for tid in stale_tids:
            with contextlib.suppress(Exception):
                self._app.cancelMktData(tid)

        for series_id_i, conid_i, exchange_code, ib_currency in normalized_rows:
            label = (series_id_i, conid_i, exchange_code, ib_currency)
            if label in self._option_subscribed:
                continue

            contract = self._Contract()
            contract.secType = "OPT"
            contract.conId = conid_i
            contract.exchange = exchange_code or "SMART"
            if ib_currency:
                contract.currency = ib_currency

            with self._lock:
                tid = self._tid_next
                self._tid_next += 1
                self._option_tid_meta[tid] = {
                    "series_id": series_id_i,
                    "conid": conid_i,
                    "exchange": contract.exchange,
                    "currency": contract.currency if hasattr(contract, "currency") else "",
                    "retried_fop": False,
                }

            self._app.reqMktData(tid, contract, "", False, False, [])
            self._option_subscribed.add(label)
            time.sleep(0.01)

    def snapshot_prices(self) -> Dict[Tuple[str,str], Dict[str,float]]:
        with self._lock:
            return {k: v.copy() for k, v in self._prices.items()}

    def shutdown(self):
        with contextlib.suppress(Exception):
            if self._app:
                self._app.disconnect()


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

    def __init__(self, host, port, client_id, parent=None):
        # print("[DEBUG] PriceFeedService aangemaakt:", id(self))
        super().__init__(parent)
        initial_prices = ASSET_LAST_PRICE_STORE.ensure_loaded()
        self.store = PriceStore(initial_prices)
        self._feed = PriceFeedIB(host, port, client_id)
        self._feed.priceUpdated.connect(self._on_price)
        self._feed.optionTickUpdated.connect(self._on_option_tick)
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
        self._load_option_last_prices_from_db()

        # Timer voor periodiek opslaan
        from PySide6.QtCore import QTimer
        
        self._save_timer = QTimer(self)
        self._save_timer.timeout.connect(self.save_last_prices_to_db)
        self._save_timer.start(300_000)  # elke 5 minuten
        self._option_save_timer = QTimer(self)
        self._option_save_timer.timeout.connect(self.save_option_last_prices_to_db)
        option_save_interval_ms = max(
            60_000,
            int(os.getenv("OPTION_LAST_PRICES_SAVE_INTERVAL_MS", "900000")),
        )
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
        bid = entry.get("bid")
        ask = entry.get("ask")
        try:
            bid_f = float(bid) if bid is not None else None
            ask_f = float(ask) if ask is not None else None
        except Exception:
            bid_f = ask_f = None
        if bid_f is not None and ask_f is not None and bid_f > 0 and ask_f > 0:
            return (bid_f + ask_f) / 2.0, "mid"
        for key in ("last", "delayed_last", "model_price", "close", "delayed_close"):
            try:
                v = entry.get(key)
                vf = float(v) if v is not None else None
            except Exception:
                vf = None
            if vf is not None and vf > 0:
                return vf, key
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
                sid: row for sid, row in self._option_prices.items() if sid in active
            }
            self._dirty_option_series_ids.intersection_update(active)

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
                    if self._active_option_series_known:
                        dirty_ids.intersection_update(self._active_option_series_ids)
                    rows = [
                        dict(self._option_prices[sid])
                        for sid in dirty_ids
                        if sid in self._option_prices
                    ]
                self._save_option_last_prices_to_db_sync(rows)
                with self._option_lock:
                    self._dirty_option_series_ids.difference_update(dirty_ids)
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

    def save_last_prices_to_db(self):
        with self._asset_save_state_lock:
            if self._asset_save_inflight:
                self._asset_save_pending = True
                return
            self._asset_save_inflight = True
            self._asset_save_pending = False
        threading.Thread(target=self._run_asset_save_worker, daemon=True).start()

    def save_option_last_prices_to_db(self):
        with self._option_save_state_lock:
            if self._option_save_inflight:
                self._option_save_pending = True
                return
            self._option_save_inflight = True
            self._option_save_pending = False
        threading.Thread(target=self._run_option_save_worker, daemon=True).start()

    def reload_asset_last_prices_from_store(self):
        self.store.replace_all(ASSET_LAST_PRICE_STORE.get_snapshot())

    @Slot(str, str, float)
    def _on_price(self, sym: str, cur: str, px: float):
        self.store.set(sym, cur, px)
        ASSET_LAST_PRICE_STORE.update_price(sym, cur, px)
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
                    for gk in ("iv", "delta", "gamma", "theta", "model_price", "underlying_price"):
                        if payload.get(gk) is not None:
                            entry[gk] = payload.get(gk)
                    last_px, src = self._pick_option_price_from_entry(entry)
                    if last_px is not None:
                        entry["last_px"] = last_px
                        entry["px_source"] = src
                    entry["last_update"] = datetime.now()
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

    def ensure_subscriptions(self, rows: List[tuple]):
        self._feed.ensure_subscriptions(rows)

    def ensure_option_subscriptions(self, rows: List[tuple]):
        self._feed.ensure_option_subscriptions(rows)

    def shutdown(self):
        with contextlib.suppress(Exception):
            if hasattr(self, "_save_timer") and self._save_timer.isActive():
                self._save_timer.stop()
            if hasattr(self, "_option_save_timer") and self._option_save_timer.isActive():
                self._option_save_timer.stop()
            self._save_last_prices_to_db_sync(force=True)
            with self._option_lock:
                dirty_ids = set(self._dirty_option_series_ids)
                if self._active_option_series_known:
                    dirty_ids.intersection_update(self._active_option_series_ids)
                rows = [
                    dict(self._option_prices[sid])
                    for sid in dirty_ids
                    if sid in self._option_prices
                ]
            self._save_option_last_prices_to_db_sync(rows)
        self._feed.shutdown()

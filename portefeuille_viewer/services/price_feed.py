import time, threading
from typing import Dict, Tuple, Optional, List

import pandas as pd
from PySide6.QtCore import QObject, Signal, Slot


# ------------------------------------------------------------
# PriceStore (cache)
# ------------------------------------------------------------
class PriceStore:
    """Houdt actuele koersen per (ib_symbol, currency) bij in een dict/DF-cache."""
    def __init__(self):
        self._cache: dict[tuple[str, str], float] = {}

    def set(self, sym: str, cur: str, px: float):
        """Voeg of update prijs in de cache."""
        self._cache[(sym, cur)] = float(px)

    def get(self, sym: str, cur: str) -> Optional[float]:
        """Haal prijs op, of None."""
        return self._cache.get((sym, cur))

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
    log = Signal(str)
    ready = Signal()

    def __init__(self, host: str, port: int, client_id: int, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._subscribed = set()
        self._tid_next = 5200
        self._tid_by_key: Dict[int, Tuple[str, str]] = {}
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
                feed.ready.emit()

            def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
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

            def tickPrice(self, reqId, tickType, price, attrib):
                with feed._lock:
                    key = feed._tid_by_key.get(reqId)
                if not key:
                    return
                sym, cur = key
                if tickType in (4,9,68,75):  # last/close + delayed varianten
                    with feed._lock:
                        entry = feed._prices.setdefault((sym,cur), {})
                        entry["last"] = float(price)
                        entry["ts"] = time.time()
                    feed.priceUpdated.emit(sym, cur, float(price))

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

    @Slot(list)
    def ensure_subscriptions(self, rows: List[Tuple[str, str, Optional[str]]]):
        """Vraag marktdata aan voor lijst van (sym, cur, prim_exch)."""
        if not self._app:
            return
        for (sym, cur, pex) in rows:
            label = (sym, cur, pex or "")
            if label in self._subscribed:
                continue
            tid = self._tid_next
            self._tid_next += 1
            self._tid_by_key[tid] = (sym, cur)
            self._app.reqMktData(tid, self._make_stock(sym, cur, pex), "", False, False, [])
            self._subscribed.add(label)
            time.sleep(0.01)

    def snapshot_prices(self) -> Dict[Tuple[str,str], Dict[str,float]]:
        with self._lock:
            return {k: v.copy() for k, v in self._prices.items()}

    def shutdown(self):
        try:
            if self._app:
                self._app.disconnect()
        except Exception:
            pass


# ------------------------------------------------------------
# PriceFeedService (Qt wrapper rond IB + PriceStore)
# ------------------------------------------------------------
class PriceFeedService(QObject):
    """
    Qt-vriendelijke wrapper rond PriceFeedIB + PriceStore.
    Deze gebruik je in je UI.
    """
    priceUpdated = Signal(str, str, float)  # ib_symbol, currency, price

    def __init__(self, host, port, client_id, parent=None):
        super().__init__(parent)
        self.store = PriceStore()
        self._feed = PriceFeedIB(host, port, client_id)
        self._feed.priceUpdated.connect(self._on_price)

        # Timer voor periodiek opslaan
        from PySide6.QtCore import QTimer
        import datetime
        from portefeuille_viewer.data.repository import get_connection
        self._save_timer = QTimer(self)
        self._save_timer.timeout.connect(self.save_last_prices_to_db)
        self._save_timer.start(60_000)  # elke 60 sec

    def save_last_prices_to_db(self):
        from portefeuille_viewer.data.repository import get_connection
        import datetime
        prices = self.store.snapshot()
        now = datetime.datetime.now()
        with get_connection() as conn:
            cursor = conn.cursor()
            for (sym, cur), price in prices.items():
                cursor.execute(
                    "UPDATE asset_last_prices SET price=?, last_update=? WHERE ib_symbol=? AND ib_currency=?",
                    (price, now, sym, cur)
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        "INSERT INTO asset_last_prices (ib_symbol, ib_currency, price, last_update) VALUES (?, ?, ?, ?)",
                        (sym, cur, price, now)
                    )
            conn.commit()

    @Slot(str, str, float)
    def _on_price(self, sym: str, cur: str, px: float):
        self.store.set(sym, cur, px)
        self.priceUpdated.emit(sym, cur, float(px))

    # convenience-methodes
    def get(self, sym: str, cur: str) -> Optional[float]:
        return self.store.get(sym, cur)

    def snapshot(self) -> dict[tuple[str, str], float]:
        return self.store.snapshot()

    def snapshot_df(self) -> pd.DataFrame:
        return self.store.snapshot_df()

    def is_ready(self) -> bool:
        return self._feed.is_ready()

    def ensure_subscriptions(self, rows: List[tuple[str, str, Optional[str]]]):
        self._feed.ensure_subscriptions(rows)

    def shutdown(self):
        self._feed.shutdown()

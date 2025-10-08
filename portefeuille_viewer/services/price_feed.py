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
                feed.ready.emit()

            def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
                if errorCode not in (2103,2104,2106,2158):
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

        self._Contract = Contract
        self._app = App()
        self._app.connect(self.host, self.port, clientId=self.client_id)
        t = threading.Thread(target=self._app.run, daemon=True)
        t.start()

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

    def ensure_subscriptions(self, rows: List[tuple[str, str, Optional[str]]]):
        self._feed.ensure_subscriptions(rows)

    def shutdown(self):
        self._feed.shutdown()

import contextlib
import sys
import threading
import time
from typing import Dict, Optional, Tuple, List

from PySide6.QtCore import QObject, Signal, QCoreApplication, QTimer


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
        self.host, self.port, self.client_id = host, port, client_id
        self._is_ready = False
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

            def error(self, reqId, *args):
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
                if errorCode not in (2103, 2104, 2106, 2158):
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
                # Keep tickPrice logging for visibility, but Excel uses RTVolume (generic tick 165)
                if tickType in (4, 9, 68, 75):
                    feed.log.emit(f"IB TICK sym={sym} cur={cur} tickType={tickType} price={price}")

            def tickString(self, reqId, tickType, value):
                # RTVolume (generic tick 165) arrives as tickString type 48
                if tickType != 48:
                    return
                with feed._lock:
                    key = feed._tid_by_key.get(reqId)
                if not key:
                    return
                sym, cur = key
                feed.log.emit(f"IB RT_VOLUME_RAW sym={sym} cur={cur} value={value}")
                try:
                    parts = value.split(";")
                    last_price = float(parts[0]) if parts else None
                except Exception:
                    last_price = None
                if last_price is not None:
                    feed.priceUpdated.emit(sym, cur, float(last_price))

            def marketDataType(self, reqId, marketDataType):
                with feed._lock:
                    key = feed._tid_by_key.get(reqId)
                if key:
                    sym, cur = key
                    feed.log.emit(f"IB MKT_DATA_TYPE sym={sym} cur={cur} type={marketDataType}")
                else:
                    feed.log.emit(f"IB MKT_DATA_TYPE reqId={reqId} type={marketDataType}")
        self._Contract = Contract
        self._app = App()
        self._app.connect(self.host, self.port, clientId=self.client_id)
        t = threading.Thread(target=self._app.run, daemon=True)
        t.start()

    def _make_stock(self, symbol, currency, primaryExchange, con_id: Optional[int] = None):
        c = self._Contract()
        c.symbol = symbol
        c.secType = "STK"
        c.currency = currency
        c.exchange = "SMART"
        if primaryExchange:
            c.primaryExchange = primaryExchange
        if con_id:
            try:
                c.conId = int(con_id)
            except Exception:
                pass
        return c

    def ensure_subscriptions(self, rows: List[Tuple]):
        if not self._app:
            return
        # 1=Live, 2=Frozen, 3=Delayed, 4=Delayed Frozen
        try:
            self._app.reqMarketDataType(1)
        except Exception:
            pass
        for row in rows:
            if len(row) >= 4:
                sym, cur, pex, con_id = row[0], row[1], row[2], row[3]
            else:
                sym, cur, pex = row[0], row[1], row[2] if len(row) > 2 else None
                con_id = None
            label = (sym, cur, pex or "", con_id or "")
            if label in self._subscribed:
                continue
            tid = self._tid_next
            self._tid_next += 1
            self._tid_by_key[tid] = (sym, cur)
            contract = self._make_stock(sym, cur, pex, con_id=con_id)
            # Request generic ticks 165 to mimic Excel RTD (RTVolume)
            # Snapshot=True to force one-shot data (and RTVolume if available)
            self._app.reqMktData(tid, contract, "165", True, False, [])
            self._subscribed.add(label)
            time.sleep(0.01)

    def shutdown(self):
        with contextlib.suppress(Exception):
            if self._app:
                self._app.disconnect()


def main() -> int:
    symbol = "UNVB"
    currency = "EUR"
    primary_exchange = "AEB"
    con_id = 837455595

    app = QCoreApplication(sys.argv)

    feed = PriceFeedIB(host="127.0.0.1", port=7496, client_id=912)
    feed.log.connect(print)

    def on_price(sym: str, cur: str, px: float) -> None:
        if sym != symbol or cur != currency:
            return
        print(f"LAST PRICE: {sym} {cur} {px}")
        app.quit()

    def on_ready() -> None:
        feed.ensure_subscriptions([(symbol, currency, primary_exchange, con_id)])

    feed.priceUpdated.connect(on_price)
    feed.ready.connect(on_ready)

    QTimer.singleShot(30_000, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

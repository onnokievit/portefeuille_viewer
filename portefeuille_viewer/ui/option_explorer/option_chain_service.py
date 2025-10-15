"""
Option Chain Service
Handles IBKR reqContractDetails for option chain retrieval
"""

from datetime import datetime, date
from ibapi.contract import Contract
from PySide6.QtCore import QObject, Signal



import threading
from datetime import datetime, date
from ibapi.contract import Contract
from PySide6.QtCore import QObject, Signal

class OptionChainService(QObject):
    contracts_received = Signal(list)
    error_occurred = Signal(str)
    request_completed = Signal()

    def __init__(self, feed_service):
        super().__init__()
        self.feed_service = feed_service
        self._is_loading = False
        self._secdef_cache = {}  # (symbol, exchange, currency) -> (params, timestamp)
        self._cache_ttl = 1800  # 30 min

    def request_option_chain(self, symbol, currency="USD", exchange="SMART", expiry_from=None, expiry_to=None, strike_min=None, strike_max=None, option_type="both"):
        if self._is_loading:
            self.error_occurred.emit("Request already in progress")
            return
        self._is_loading = True
        self._pending_contracts = []
        self._expiry_from = expiry_from
        self._expiry_to = expiry_to
        self._strike_min = strike_min
        self._strike_max = strike_max
        self._option_type = option_type.lower()
        self._current_symbol = symbol
        self._current_currency = currency
        self._current_exchange = exchange
        # 1. Haal secdef-opt-params op (met cache)
        cache_key = (symbol, exchange, currency)
        now = datetime.now().timestamp()
        params, ts = self._secdef_cache.get(cache_key, (None, 0))
        if params and now - ts < self._cache_ttl:
            self._on_secdef_params(params)
        else:
            self._fetch_secdef_params(symbol, exchange, currency)

    def _fetch_secdef_params(self, symbol, exchange, currency):
        self._secdef_params = []
        self._secdef_ready = threading.Event()
        tried_conid0 = False
        def on_param(exchange, underlyingConId, tradingClass, multiplier, expirations, strikes):
            print(f"[OptionChain] secdef param: exch={exchange}, tClass={tradingClass}, mult={multiplier}, expiries={len(expirations)}, strikes={len(strikes)}")
            self._secdef_params.append({
                'exchange': exchange,
                'tradingClass': tradingClass,
                'multiplier': multiplier,
                'expirations': list(expirations),
                'strikes': list(strikes)
            })
        def on_end():
            nonlocal tried_conid0
            print(f"[OptionChain] secdef end: total exchanges={len(self._secdef_params)} tried_conid0={tried_conid0}")
            if not self._secdef_params and not tried_conid0:
                tried_conid0 = True
                # Retry with conId=0 to broaden lookup across all exchanges
                self._secdef_params = []
                self.feed_service._feed.request_secdef_opt_params(self._current_symbol, "", "STK", 0, on_param, on_end)
                return
            # Prefer requested exchange; otherwise SMART; otherwise first available
            params = next((p for p in self._secdef_params if p['exchange'] == self._current_exchange), None)
            if not params:
                params = next((p for p in self._secdef_params if p['exchange'] == "SMART"), None)
            if not params and self._secdef_params:
                params = self._secdef_params[0]
                self._current_exchange = params['exchange']
            if not params:
                self._is_loading = False
                self.error_occurred.emit(f"No secdef-opt-params for {self._current_symbol} on any exchange")
                self.request_completed.emit()
                return
            # Cache
            cache_key = (self._current_symbol, self._current_exchange, self._current_currency)
            self._secdef_cache[cache_key] = (params, datetime.now().timestamp())
            self._on_secdef_params(params)
        # Eerst conId ophalen
        # Gebruik lege exchange ("") om alle optiemarkten te laten terugkomen; we kiezen later SMART of eerste beschikbare
        self._get_underlying_conid(symbol, lambda conId: self.feed_service._feed.request_secdef_opt_params(symbol, "", "STK", conId, on_param, on_end))

    def _get_underlying_conid(self, symbol, callback):
        self._underlying_conid = None
        event = threading.Event()
        def on_detail(cd):
            self._underlying_conid = cd.contract.conId
        def on_end():
            event.set()
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"
        self.feed_service._feed.request_contract_details(contract, on_detail, on_end)
        event.wait(timeout=5)
        callback(self._underlying_conid or 0)

    def _on_secdef_params(self, params):
        # Filter expiries/strikes
        expiries = sorted(params['expirations'])
        strikes = sorted(params['strikes'])
        # Filter op expiry_from/expiry_to
        if self._expiry_from:
            expiries = [e for e in expiries if self._expiry_from <= datetime.strptime(e, "%Y%m%d").date()]
        if self._expiry_to:
            expiries = [e for e in expiries if datetime.strptime(e, "%Y%m%d").date() <= self._expiry_to]
        # Filter strikes
        if self._strike_min:
            strikes = [s for s in strikes if s >= self._strike_min]
        if self._strike_max:
            strikes = [s for s in strikes if s <= self._strike_max]
        # Kies max 2 expiries, 3 strikes (demo)
        expiries = expiries[:2]
        mid = len(strikes) // 2
        chosen_strikes = strikes[max(0, mid-1):mid+2]
        # Rights
        rights = []
        if self._option_type in ("both", "call"): rights.append("C")
        if self._option_type in ("both", "put"): rights.append("P")
        # 2. Vraag per expiry/strike/right contractDetails op
        self._pending_contracts = []
        self._pending_count = 0
        def make_contract(expiry, strike, right):
            c = Contract()
            c.symbol = self._current_symbol
            c.secType = "OPT"
            c.exchange = self._current_exchange
            c.currency = self._current_currency
            c.lastTradeDateOrContractMonth = expiry
            c.strike = float(strike)
            c.right = right
            c.multiplier = params['multiplier']
            c.tradingClass = params['tradingClass']
            return c
        def on_detail(cd):
            contract = cd.contract
            contract_info = {
                'conId': contract.conId,
                'symbol': contract.symbol,
                'strike': contract.strike,
                'right': contract.right,
                'expiry': contract.lastTradeDateOrContractMonth,
                'multiplier': contract.multiplier,
                'trading_class': contract.tradingClass,
                'exchange': contract.exchange,
                'currency': contract.currency,
            }
            self._pending_contracts.append(contract_info)
        def on_end():
            self._pending_count -= 1
            if self._pending_count == 0:
                self.contracts_received.emit(self._pending_contracts)
                self.request_completed.emit()
                self._is_loading = False
        # Schedule requests
        for expiry in expiries:
            for strike in chosen_strikes:
                for right in rights:
                    contract = make_contract(expiry, strike, right)
                    self._pending_count += 1
                    self.feed_service._feed.request_contract_details(contract, on_detail, on_end)

    def is_loading(self):
        return self._is_loading

    def stop_request(self):
        # Niet geïmplementeerd: zou outstanding requests kunnen cancellen
        self._is_loading = False
        self._pending_contracts = []
        self.error_occurred.emit("Request stopped by user")
        self.request_completed.emit()

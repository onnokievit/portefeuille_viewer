"""
Option Chain Service
Handles IBKR reqContractDetails for option chain retrieval
"""

from datetime import datetime, date
from ibapi.contract import Contract
from PySide6.QtCore import QObject, Signal


class OptionChainService(QObject):
    """
    Service voor het ophalen van option chain data via IBKR API
    """
    
    # Signals
    contracts_received = Signal(list)  # List of contract details
    error_occurred = Signal(str)  # Error message
    request_completed = Signal()  # Request finished
    
    def __init__(self, feed_service):
        """
        Args:
            feed_service: PriceFeedService instance voor IBKR communicatie
        """
        super().__init__()
        self.feed_service = feed_service
        self._pending_contracts = []
        self._request_id = None
        self._is_loading = False
        
    def request_option_chain(
        self,
        symbol: str,
        currency: str = "USD",
        exchange: str = "SMART",
        expiry_from: date = None,
        expiry_to: date = None,
        strike_min: float = None,
        strike_max: float = None,
        option_type: str = "both"  # "both", "call", "put"
    ):
        """
        Request option chain from IBKR
        
        Args:
            symbol: Ticker symbol (e.g., "AAPL")
            currency: Currency (e.g., "USD", "EUR")
            exchange: Exchange (default "SMART")
            expiry_from: Start date voor expiry range (optional)
            expiry_to: End date voor expiry range (optional)
            strike_min: Minimum strike price (optional)
            strike_max: Maximum strike price (optional)
            option_type: "both", "call", or "put"
        """
        if self._is_loading:
            self.error_occurred.emit("Request already in progress")
            return
            
        # Reset state
        self._pending_contracts = []
        self._is_loading = True
        
        # Build contract (zonder strike/expiry/right = ALL options)
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "OPT"
        contract.exchange = exchange
        contract.currency = currency
        
        # Get next available request ID (use simple incrementing ID)
        with self.feed_service._feed._lock:
            self._request_id = self.feed_service._feed._tid_next
            self.feed_service._feed._tid_next += 1
        
        print(f"[OptionChain] Requesting options for {symbol} (reqId={self._request_id})")
        
        # Setup callbacks
        self._setup_callbacks()
        
        # Store filter criteria for post-processing
        self._expiry_from = expiry_from
        self._expiry_to = expiry_to
        self._strike_min = strike_min
        self._strike_max = strike_max
        self._option_type = option_type.lower()
        
        # Send request to IBKR
        try:
            # Access the IBKR app directly
            ib_app = self.feed_service._feed._app
            ib_app.reqContractDetails(self._request_id, contract)
        except Exception as e:
            self._is_loading = False
            self.error_occurred.emit(f"IBKR request failed: {str(e)}")
    
    def _setup_callbacks(self):
        """Setup IBKR callbacks voor contract details"""
        # Access the wrapper
        wrapper = self.feed_service._feed._app
        
        # Store original callbacks if they exist
        if hasattr(wrapper, 'contractDetails'):
            self._original_contract_details = wrapper.contractDetails
        else:
            self._original_contract_details = None
            
        if hasattr(wrapper, 'contractDetailsEnd'):
            self._original_contract_details_end = wrapper.contractDetailsEnd
        else:
            self._original_contract_details_end = None
        
        # Replace with our handlers
        wrapper.contractDetails = self._on_contract_details
        wrapper.contractDetailsEnd = self._on_contract_details_end
    
    def _restore_callbacks(self):
        """Restore original IBKR callbacks"""
        wrapper = self.feed_service._feed._app
        
        if self._original_contract_details is not None:
            wrapper.contractDetails = self._original_contract_details
        if self._original_contract_details_end is not None:
            wrapper.contractDetailsEnd = self._original_contract_details_end
    
    def _on_contract_details(self, reqId: int, contractDetails):
        """IBKR callback: Contract details ontvangen"""
        if reqId != self._request_id:
            return
            
        contract = contractDetails.contract
        
        # Apply filters
        if not self._passes_filters(contract):
            return
        
        # Extract relevant info
        contract_info = {
            'conId': contract.conId,
            'symbol': contract.symbol,
            'strike': contract.strike,
            'right': contract.right,  # "C" or "P"
            'expiry': contract.lastTradeDateOrContractMonth,  # "20251017"
            'multiplier': contract.multiplier,
            'trading_class': contract.tradingClass,
            'exchange': contract.exchange,
            'currency': contract.currency,
        }
        
        self._pending_contracts.append(contract_info)
        print(f"[OptionChain] Received: {contract.symbol} {contract.strike} {contract.right} {contract.lastTradeDateOrContractMonth}")
    
    def _on_contract_details_end(self, reqId: int):
        """IBKR callback: Alle contract details ontvangen"""
        if reqId != self._request_id:
            return
        
        print(f"[OptionChain] Request completed. Received {len(self._pending_contracts)} contracts")
        
        # Restore callbacks
        self._restore_callbacks()
        
        # Emit results
        self.contracts_received.emit(self._pending_contracts)
        self.request_completed.emit()
        
        # Reset state
        self._is_loading = False
        self._request_id = None
    
    def _passes_filters(self, contract) -> bool:
        """Check if contract passes filter criteria"""
        
        # Parse expiry date
        try:
            expiry_str = contract.lastTradeDateOrContractMonth
            expiry_date = datetime.strptime(expiry_str, "%Y%m%d").date()
        except:
            return False
        
        # Filter: Expiry range
        if self._expiry_from and expiry_date < self._expiry_from:
            return False
        if self._expiry_to and expiry_date > self._expiry_to:
            return False
        
        # Filter: Strike range
        if self._strike_min and contract.strike < self._strike_min:
            return False
        if self._strike_max and contract.strike > self._strike_max:
            return False
        
        # Filter: Option type
        if self._option_type == "call" and contract.right != "C":
            return False
        if self._option_type == "put" and contract.right != "P":
            return False
        
        return True
    
    def is_loading(self) -> bool:
        """Check if request is in progress"""
        return self._is_loading
    
    def stop_request(self):
        """Stop current request"""
        if not self._is_loading:
            return
        
        print(f"[OptionChain] Stopping request (reqId={self._request_id})")
        
        # Restore callbacks
        self._restore_callbacks()
        
        # Reset state
        self._is_loading = False
        self._pending_contracts = []
        
        # Emit signals
        self.error_occurred.emit("Request stopped by user")
        self.request_completed.emit()

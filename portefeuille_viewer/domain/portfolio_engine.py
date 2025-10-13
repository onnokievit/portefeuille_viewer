from PySide6.QtCore import QObject, Signal
from portefeuille_viewer.data.live_aggregator_aandelen import LiveAggregatorAandelen

class PortfolioEngine(QObject):
    """
    Orchestrator voor live portfolio updates.
    
    Verantwoordelijkheden:
    - Beheert subscriptions voor alle live data feeds
    - Ontvangt live prijzen van PriceFeedService
    - Triggert gespecialiseerde aggregators voor verwerking
    - Emits signals naar UI voor updates
    
    Doet NIET meer:
    - Eigen DataFrame beheer
    - Eigen berekeningen
    - Direct data opslag
    """
    
    # Signal emitted when any portfolio data is updated
    dataUpdated = Signal()
    
    def __init__(self, pricefeed=None):
        super().__init__()
        self.pricefeed = pricefeed
        
        # Initialize specialized aggregators
        self.live_aggregator_aandelen = LiveAggregatorAandelen()
        
        # TODO: Add when implemented
        # self.live_aggregator_opties = LiveAggregatorOpties()
        # self.live_aggregator_sprinters = LiveAggregatorSprinters()
        
        # Connect pricefeed if provided
        if self.pricefeed:
            self.pricefeed.priceUpdated.connect(self._on_live_price)
        
        # Connect aggregator signals to main signal
        self.live_aggregator_aandelen.aandelenUpdated.connect(self.dataUpdated.emit)
        
        print("PortfolioEngine: Initialized as orchestrator with LiveAggregatorAandelen")
    
    def _on_live_price(self, symbol, currency, price):
        """
        Handle incoming live price updates.
        Triggers relevant aggregators based on symbol type.
        
        Args:
            symbol: IB symbol (e.g. 'AAPL', 'TSLA')
            currency: Price currency 
            price: New price value
        """
        print(f"PortfolioEngine: Received price update {symbol} = {price}")
        
        # Update live prijs in aggregator en trigger update
        self.live_aggregator_aandelen.update_live_price(symbol, price)
        self.live_aggregator_aandelen.process_live_update()
        
        # TODO: Add conditional triggering based on symbol type
        # if symbol.endswith('OPT'):
        #     self.live_aggregator_opties.process_live_update()
        # elif symbol.endswith('SPR'):  
        #     self.live_aggregator_sprinters.process_live_update()
        
        print(f"PortfolioEngine: Triggered aggregators for {symbol}")
    
    def get_symbols_to_subscribe(self):
        """
        Collect all symbols that need live price subscriptions.
        Haalt IB symbolen uit snapshot_asset_rollup_data.
        
        Returns:
            list: All unique IB symbols that should be subscribed
        """
        from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
        
        if SNAPSHOT_STORE.snapshot_asset_rollup_data is None or SNAPSHOT_STORE.snapshot_asset_rollup_data.is_empty():
            print("PortfolioEngine: No asset rollup data available for subscriptions")
            return []
        
        try:
            # Haal alle ib_symbol waarden uit snapshot_asset_rollup_data
            symbols_df = SNAPSHOT_STORE.snapshot_asset_rollup_data.select("ib_symbol").unique()
            symbols = symbols_df.to_series().to_list()
            
            # Filter out None/empty values
            unique_symbols = [s for s in symbols if s is not None and s != ""]
            
            print(f"PortfolioEngine: Collected {len(unique_symbols)} symbols for subscription from asset_rollup_data")
            return unique_symbols
            
        except Exception as e:
            print(f"PortfolioEngine: Error getting symbols for subscription: {e}")
        return unique_symbols


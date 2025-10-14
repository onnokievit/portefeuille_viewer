from PySide6.QtCore import QObject, Signal, QTimer
from portefeuille_viewer.data.live_aggregator_aandelen import LiveAggregatorAandelen
from portefeuille_viewer.data.live_aggregator_opties import LiveAggregatorOpties

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
        self.live_aggregator_opties = LiveAggregatorOpties()
        
        # TODO: Add when implemented
        # self.live_aggregator_sprinters = LiveAggregatorSprinters()
        
        # Throttling: batch updates instead of processing each price immediately
        self._pending_updates = False
        self._update_timer = QTimer()
        self._update_timer.setInterval(1000)  # Process updates max every 1500ms
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._process_batched_updates)
        
        # Connect pricefeed if provided
        if self.pricefeed:
            self.pricefeed.priceUpdated.connect(self._on_live_price)
        
        # Connect aggregator signals to main signal
        self.live_aggregator_aandelen.aandelenUpdated.connect(self.dataUpdated.emit)
        self.live_aggregator_opties.optiesUpdated.connect(self.dataUpdated.emit)
        
        print("PortfolioEngine: Initialized as orchestrator with LiveAggregatorAandelen and LiveAggregatorOpties")
    
    def _on_live_price(self, symbol, currency, price):
        """
        Handle incoming live price updates.
        Stores price in aggregators but batches the actual processing.
        
        Args:
            symbol: IB symbol (e.g. 'AAPL', 'TSLA')
            currency: Price currency 
            price: New price value
        """
        # Update live prijs in beide aggregators (just store, don't process yet)
        self.live_aggregator_aandelen.update_live_price(symbol, price)
        self.live_aggregator_opties.update_live_price(symbol, price)
        
        # Mark that we have pending updates and start/restart timer
        self._pending_updates = True
        if not self._update_timer.isActive():
            self._update_timer.start()
    
    def _process_batched_updates(self):
        """Process all accumulated price updates in one batch."""
        if not self._pending_updates:
            return
        
        # print(f"PortfolioEngine: Processing batched updates...") # Debug log
        
        # Process updates for both aggregators
        self.live_aggregator_aandelen.process_live_update()
        self.live_aggregator_opties.process_live_update()
        
        self._pending_updates = False
        # print(f"PortfolioEngine: Batch processing complete") # Debug log
    
    def start_subscriptions(self):
        """
        Start live price subscriptions voor alle symbolen.
        Moet aangeroepen worden na initialisatie van PortfolioEngine.
        
        Verantwoordelijkheden:
        - Haalt alle symbolen op uit asset_rollup_data
        - Start subscriptions via pricefeed.ensure_subscriptions()
        - Kan later uitgebreid worden met refresh/cleanup logica
        """
        if not self.pricefeed:
            print("PortfolioEngine: No pricefeed available, skipping subscriptions")
            return
        
        symbols_to_subscribe = self.get_symbols_to_subscribe()
        
        if not symbols_to_subscribe:
            print("PortfolioEngine: No symbols to subscribe to")
            return
        
        try:
            # Converteer naar format (ib_symbol, ib_currency, prim_exchange)
            from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
            asset_map = SNAPSHOT_STORE.snapshot_asset_rollup_data
            subs = asset_map.select(["ib_symbol", "ib_currency", "prim_exchange"]).unique().to_numpy().tolist()
            
            print(f"PortfolioEngine: Starting subscriptions for {len(subs)} symbols...")
            self.pricefeed.ensure_subscriptions(subs)
            print("PortfolioEngine: Subscriptions started successfully")
            
        except Exception as e:
            print(f"PortfolioEngine: Error starting subscriptions: {e}")
    
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


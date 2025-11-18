from PySide6.QtCore import QObject, Signal, QTimer
import polars as pl
from portefeuille_viewer.data.live_aggregator_aandelen import LiveAggregatorAandelen
from portefeuille_viewer.data.live_aggregator_opties import LiveAggregatorOpties
from portefeuille_viewer.data.live_aggregator_sprinters import LiveAggregatorSprinters

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
        
        
        # Sprinters aggregator toevoegen
        
        self.live_aggregator_sprinters = LiveAggregatorSprinters()
        
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
        if self.live_aggregator_sprinters:
            self.live_aggregator_sprinters.sprintersUpdated.connect(self.dataUpdated.emit)
        
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
        # Update live prijs in alle aggregators (just store, don't process yet)
        self.live_aggregator_aandelen.update_live_price(symbol, currency, price)
        self.live_aggregator_opties.update_live_price(symbol, currency, price)
        if self.live_aggregator_sprinters:
            self.live_aggregator_sprinters.update_live_price(symbol, currency, price)
        
        # Mark that we have pending updates and start/restart timer
        self._pending_updates = True
        if not self._update_timer.isActive():
            self._update_timer.start()
    
    def _process_batched_updates(self):
        """Process all accumulated price updates in one batch."""
        if not self._pending_updates:
            return
        
        # print(f"PortfolioEngine: Processing batched updates...") # Debug log
        
        # Process updates for all aggregators
        self.live_aggregator_aandelen.process_live_update()
        self.live_aggregator_opties.process_live_update()
        if self.live_aggregator_sprinters:
            self.live_aggregator_sprinters.process_live_update()
        
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

            if asset_map is None or asset_map.is_empty():
                print("PortfolioEngine: asset_rollup_data snapshot empty, nothing to subscribe")
                return

            # If the INCL_EXCL column exists, only include rows where its value signals inclusion (1 / "1" / True)
            if "INCL_EXCL" in asset_map.columns:
                try:
                    filtered = asset_map.filter(
                        (pl.col("INCL_EXCL") == 1) | (pl.col("INCL_EXCL") == "1") | (pl.col("INCL_EXCL"))
                    )
                except Exception:
                    # Fallback: try numeric equality only
                    filtered = asset_map.filter(pl.col("INCL_EXCL") == 1)
            else:
                # Column missing -> include all (backward compatible)
                filtered = asset_map

            subs_df = filtered.select(["ib_symbol", "ib_currency", "prim_exchange"]).unique()
            # Convert to list of tuples for ensure_subscriptions and drop rows with missing symbol/currency
            subs = [tuple(x) for x in subs_df.to_numpy().tolist() if x[0] is not None and x[0] != "" and x[1] is not None and x[1] != ""]

            print(f"PortfolioEngine: Starting subscriptions for {len(subs)} symbol-currency pairs (filtered by INCL_EXCL if present)...")
            if subs:
                self.pricefeed.ensure_subscriptions(subs)
                print("PortfolioEngine: Subscriptions started successfully")
            else:
                print("PortfolioEngine: No valid subscriptions after filtering (no ib_symbol/ib_currency pairs)")

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
            return self._extracted_from_get_symbols_to_subscribe_17(SNAPSHOT_STORE)
        except Exception as e:
            print(f"PortfolioEngine: Error getting symbols for subscription: {e}")
            return []

    # TODO Rename this here and in `get_symbols_to_subscribe`
    def _extracted_from_get_symbols_to_subscribe_17(self, SNAPSHOT_STORE):
        # Haal alle ib_symbol waarden uit snapshot_asset_rollup_data
        asset_map = SNAPSHOT_STORE.snapshot_asset_rollup_data
        if asset_map is None or asset_map.is_empty():
            return []

        # Apply INCL_EXCL filter if available
        if "INCL_EXCL" in asset_map.columns:
            try:
                asset_map = asset_map.filter(
                    (pl.col("INCL_EXCL") == 1) | (pl.col("INCL_EXCL") == "1") | (pl.col("INCL_EXCL"))
                )
            except Exception:
                asset_map = asset_map.filter(pl.col("INCL_EXCL") == 1)

        symbols_df = asset_map.select("ib_symbol").unique()
        symbols = symbols_df.to_series().to_list()

        # Filter out None/empty values
        unique_symbols = [s for s in symbols if s is not None and s != ""]

        print(f"PortfolioEngine: Collected {len(unique_symbols)} symbols for subscription from asset_rollup_data (after INCL_EXCL filter)")
        return unique_symbols

    def shutdown(self):
        # Stop de update timer
        if self._update_timer.isActive():
            self._update_timer.stop()
        # Voeg hier eventueel shutdown/stop-calls toe voor aggregators als die threads/timers gebruiken
        # Bijvoorbeeld:
        # if hasattr(self.live_aggregator_aandelen, "shutdown"):
        #     self.live_aggregator_aandelen.shutdown()
        # if hasattr(self.live_aggregator_opties, "shutdown"):
        #     self.live_aggregator_opties.shutdown()
        # if hasattr(self.live_aggregator_sprinters, "shutdown"):
        #     self.live_aggregator_sprinters.shutdown()

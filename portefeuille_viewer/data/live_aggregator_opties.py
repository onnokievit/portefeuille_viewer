import polars as pl
from PySide6.QtCore import QObject, Signal
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


class LiveAggregatorOpties(QObject):
    """
    Specialized aggregator voor opties met live price updates.
    Laadt data uit snapshot_load_open_opties_from_tx en voegt live koersen toe.
    """
    
    # Signal voor UI updates
    optiesUpdated = Signal()
    
    def __init__(self):
        super().__init__()
        self.df = None
        self.live_prices = {}  # Dict: {asset_rollup: koers}
        self._initialize_data()
    
    def _initialize_data(self):
        """Laad initiële data uit SnapshotStore en bereid DataFrame voor."""
        try:
            self.df = self._load_and_calculate()
            print(f"LiveAggregatorOpties: Initialized with {len(self.df)} rows")
        except Exception as e:
            print(f"LiveAggregatorOpties initialization error: {e}")
            self.df = pl.DataFrame()
    
    def _load_and_prepare_data(self):
        """Laad basisdata uit SnapshotStore en join met asset_map voor IB symbolen."""
        if SNAPSHOT_STORE.snapshot_load_open_opties_from_tx is None:
            raise ValueError("snapshot_load_open_opties_from_tx is niet geladen in SnapshotStore")
        
        # Laad asset_map voor IB symbolen
        asset_map = SNAPSHOT_STORE.snapshot_asset_rollup_data
        if asset_map is None or asset_map.is_empty():
            raise ValueError("snapshot_asset_rollup_data is niet geladen")
        
        # Selecteer relevante velden uit asset_map
        asset_map = asset_map.select([
            "asset_rollup", "ib_symbol"
        ])
        
        # Haal opties data op en join met asset_map
        df = SNAPSHOT_STORE.snapshot_load_open_opties_from_tx.clone()
        df = df.join(asset_map, on="asset_rollup", how="left")
        
        # Voeg LAST kolom toe met live prijzen van onderliggende asset (via ib_symbol)
        df = df.with_columns([
            pl.col("ib_symbol").map_elements(
                lambda symbol: self.live_prices.get(symbol, 0.0) if symbol else 0.0,
                return_dtype=pl.Float64
            ).alias("LAST")
        ])
        
        return df
    
    def _load_and_calculate(self):
        """
        Laad snapshot_load_open_opties_from_tx en voeg berekende kolommen toe.
        """
        # Laad basisdata met LAST kolom
        df = self._load_and_prepare_data()
        
        # Voeg placeholder kolommen toe
        df = self._add_placeholder_columns(df)
        
        # Selecteer en herorden kolommen volgens screenshot
        df = df.select([
            "broker",
            "asset_rollup", 
            "optie_call_put",
            "optie_strike",
            "optie_exp_date",
            "SomVantransactie_aantal",
            "SomVantransactie_euro_totaal",
            "SomVantransactie_fee",
            "LAST",
            "ITM_OTM",
            "W/V"
        ])
        
        return df
    
    def _add_placeholder_columns(self, df):
        """Voeg placeholder kolommen toe voor toekomstige berekeningen."""
        df = df.with_columns([
            pl.lit("").alias("ITM_OTM"),  # Placeholder voor In-The-Money / Out-The-Money
            pl.lit("").alias("W/V"),       # Placeholder voor Winst/Verlies
        ])
        return df
    
    def update_live_price(self, symbol, price):
        """
        Update live prijs voor specifiek symbol (asset_rollup).
        
        Args:
            symbol: Asset symbol (e.g. 'ASML', 'AAPL')
            price: Nieuwe prijs
        """
        if price is not None and price > 0:
            self.live_prices[symbol] = float(price)
            print(f"LiveAggregatorOpties: Updated {symbol} = {price}")
    
    def process_live_update(self):
        """
        Verwerk live update trigger van PortfolioEngine.
        PortfolioEngine roept alleen deze methode aan - geen data doorgeven.
        LiveAggregator laadt zelf snapshot_load_open_opties_from_tx en verwerkt het.
        """
        try:
            # 1. Laad fresh data uit SnapshotStore
            if SNAPSHOT_STORE.snapshot_load_open_opties_from_tx is None:
                print("LiveAggregatorOpties: snapshot_load_open_opties_from_tx niet beschikbaar")
                return
            
            # 2. Laad en bereken complete DataFrame
            self.df = self._load_and_calculate()
            
            # 3. Sla op in snapshot_load_open_opties_from_tx_live
            self._save_to_snapshot_store()
            
            # 4. Signal UI dat opties data is geüpdatet
            self.optiesUpdated.emit()
            
            print(f"LiveAggregatorOpties: Processed live update with {len(self.df)} rows")
            
        except Exception as e:
            print(f"LiveAggregatorOpties process error: {e}")
    
    def _save_to_snapshot_store(self):
        """Sla verwerkte DataFrame op in SnapshotStore."""
        if self.df is not None and not self.df.is_empty():
            SNAPSHOT_STORE.snapshot_load_open_opties_from_tx_live = self.df.clone()
        else:
            print("LiveAggregatorOpties: Geen data om op te slaan")

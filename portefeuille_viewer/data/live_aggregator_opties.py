import polars as pl
from PySide6.QtCore import QObject, Signal
from portefeuille_viewer.signals import signals
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.repository import load_last_prices_dict


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
        self.last_prices = load_last_prices_dict()
        self.live_prices = {}  # Dict: {asset_rollup: koers}
        self._initialize_data()
        signals.snapshotUpdated.connect(self._on_snapshot_updated)
        signals.databaseChanged.connect(self._on_database_changed)
        signals.ordersCommitted.connect(self.refresh_data)

    def _on_database_changed(self, db_name):
        # Indien relevant, herlaad data bij database wissel
        self.refresh_data()
    
    def _on_snapshot_updated(self, snapshot_key):
        if snapshot_key == "repository_snapshot_load_open_opties":
            self.refresh_data()
    def _initialize_data(self):
        """Laad initiële data uit SnapshotStore en bereid DataFrame voor."""
        try:
            self.df = self._load_and_calculate()
            print(f"LiveAggregatorOpties: Initialized with {len(self.df)} rows")
            # Save initial data to snapshot store for immediate UI display
            self._save_to_snapshot_store()
        except Exception as e:
            print(f"LiveAggregatorOpties initialization error: {e}")
            self.df = pl.DataFrame()
    
    def _load_and_prepare_data(self):
        """Laad basisdata uit SnapshotStore en join met asset_map voor IB symbolen."""
        if SNAPSHOT_STORE.repository_snapshot_load_open_opties is None:
            raise ValueError("snapshot_load_open_opties_from_tx is niet geladen in SnapshotStore")
        
        # Laad asset_map voor IB symbolen
        asset_map = SNAPSHOT_STORE.snapshot_asset_rollup_data
        if asset_map is None or asset_map.is_empty():
            raise ValueError("snapshot_asset_rollup_data is niet geladen")
        
        # Selecteer relevante velden uit asset_map
        asset_map = asset_map.select([
            "asset_rollup", "ib_symbol", "ib_currency"
        ])
        
        # Haal opties data op en join met asset_map
        df = SNAPSHOT_STORE.repository_snapshot_load_open_opties.clone()
        df = df.join(asset_map, on="asset_rollup", how="left")

        
        # Voeg Koers kolom toe met live prijzen van onderliggende asset (via ib_symbol)
        df = df.with_columns([
            pl.struct(["ib_symbol", "ib_currency"]).map_elements(
                lambda row: (
                    SNAPSHOT_STORE.live_prices.get((row["ib_symbol"], row["ib_currency"])) if row["ib_symbol"] and row["ib_currency"] and SNAPSHOT_STORE.live_prices and SNAPSHOT_STORE.live_prices.get((row["ib_symbol"], row["ib_currency"])) not in (None, 0.0)
                    else load_last_prices_dict().get((row["ib_symbol"], row["ib_currency"]), 0.0) if row["ib_symbol"] and row["ib_currency"] else 0.0
                ),
                return_dtype=pl.Float64
            ).alias("Koers")
        ])
        
        return df
    

    
    
    
    
    def _load_and_calculate(self):
        """
        Laad snapshot_load_open_opties_from_tx en voeg berekende kolommen toe.
        """
        # Laad basisdata met Koers kolom
        df = self._load_and_prepare_data()
        
        # Bereken ITM/OTM waarde
        df = self._calculate_itm_otm(df)
        
        # Bereken W/V (Winst/Verlies) = SomVantransactie_euro_totaal - ITM_OTM
        df = df.with_columns([
            (pl.col("SomVantransactie_euro_totaal") + pl.col("ITM_OTM")).alias("opt_total_result")
        ])

        # Selecteer en herorden kolommen volgens screenshot
        df = df.select([
            #"transactie_oorsprong",
            "broker",
            "asset_rollup", 
            "ib_symbol",
            "Koers",
            "optie_call_put",
            "optie_strike",
            "optie_exp_date",
            "SomVantransactie_aantal",
            "SomVantransactie_euro_totaal",
            
            "ITM_OTM",
            "opt_total_result",
            "SomVantransactie_fee"
        ])
        
        return df
    
    def _calculate_itm_otm(self, df):
        """
        Bereken ITM/OTM waarde voor opties.
        
        Logica:
        - CALL optie: 
            - Als koers > strike: ITM_OTM = koers - strike
            - Anders: ITM_OTM = 0
        - PUT optie:
            - Als koers < strike: ITM_OTM = strike - koers
            - Anders: ITM_OTM = 0
        
        Returns:
            pl.DataFrame: DataFrame met toegevoegde ITM_OTM kolom
        """
        df = df.with_columns([
            pl.when(
                (pl.col("optie_call_put") == "call") & (pl.col("Koers") > pl.col("optie_strike"))
            ).then(
                (pl.col("Koers") - pl.col("optie_strike"))*pl.col("SomVantransactie_aantal")
            ).when(
                (pl.col("optie_call_put") == "put") & (pl.col("Koers") < pl.col("optie_strike"))
            ).then(
                (pl.col("optie_strike") - pl.col("Koers"))*pl.col("SomVantransactie_aantal")
            ).otherwise(
                0.0
            ).alias("ITM_OTM")
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
            # print(f"LiveAggregatorOpties: Updated {symbol} = {price}") # Debug log
    
    def process_live_update(self):
        """
        Verwerk live update trigger van PortfolioEngine.
        PortfolioEngine roept alleen deze methode aan - geen data doorgeven.
        LiveAggregator laadt zelf snapshot_load_open_opties_from_tx en verwerkt het.
        """
        try:
            # 1. Laad fresh data uit SnapshotStore
            if SNAPSHOT_STORE.repository_snapshot_load_open_opties is None:
                print("LiveAggregatorOpties: snapshot_load_open_opties_from_tx niet beschikbaar")
                return
            
            # 2. Laad en bereken complete DataFrame
            self.df = self._load_and_calculate()
            
            # 3. Sla op in aggregator_snapshot_load_open_opties_from_tx_live
            self._save_to_snapshot_store()
            
            # 4. Signal UI dat opties data is geüpdatet
            self.optiesUpdated.emit()
            
            # print(f"LiveAggregatorOpties: Processed live update with {len(self.df)} rows") # Debug log
        except Exception as e:
            print(f"LiveAggregatorOpties process error: {e}")
    
    def _save_to_snapshot_store(self):
        """Sla verwerkte DataFrame op in SnapshotStore."""
        if self.df is not None and not self.df.is_empty():
            SNAPSHOT_STORE.safe_write("aggregator_snapshot_load_open_opties_from_tx_live", self.df.clone())
        else:
            # Schrijf een lege frame zodat subscribers niet wachten op een niet-bestaande key
            SNAPSHOT_STORE.safe_write("aggregator_snapshot_load_open_opties_from_tx_live", pl.DataFrame())
    
    def refresh_data(self):
        """Herlaad data uit SnapshotStore (voor manual refresh)."""
        self._initialize_data()
        if self.df is not None and not self.df.is_empty():
            self._save_to_snapshot_store()
            self.optiesUpdated.emit()

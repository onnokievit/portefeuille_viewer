from PySide6.QtCore import QObject, Signal
from portefeuille_viewer.signals import signals
import polars as pl
import datetime
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.repository import load_last_prices_dict

class LiveAggregatorAandelen(QObject):
    """
    Gespecialiseerde aggregator voor aandelen (stocks) live data processing.
    Wordt getriggerd door PortfolioEngine wanneer nieuwe live prijzen binnenkomen.
    """
    aandelenUpdated = Signal()
    
    def __init__(self):
        super().__init__()
        self.df = None
        self.last_prices = load_last_prices_dict()
        self.live_prices = {}  # Dict om live prijzen bij te houden: {ib_symbol: price}
        
        self._initialize_data()
        signals.snapshotUpdated.connect(self._on_snapshot_updated)
        signals.databaseChanged.connect(self._on_database_changed)
        signals.ordersCommitted.connect(self.refresh_data)
        
    
    def _on_database_changed(self, db_name):
        # Indien relevant, herlaad data bij database wissel
        self.refresh_data()
    
    def _on_snapshot_updated(self, snapshot_key):
        if snapshot_key == "repository_snapshot_aandelen":
            self.refresh_data()
    
    def _initialize_data(self):
        """Laad initiële data uit SnapshotStore en bereid DataFrame voor."""
        try:
            self.df = self._load_and_calculate()
            print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] LiveAggregatorAandelen: Initialized with {len(self.df)} rows")
            # Save initial data to snapshot store for immediate UI display
            self._save_to_snapshot_store()
        except Exception as e:
            print(f"LiveAggregatorAandelen initialization error: {e}")
            self.df = pl.DataFrame()
    
    def _load_and_prepare_data(self):
        """Laad basisdata uit SnapshotStore en join met asset_map."""
        if SNAPSHOT_STORE.repository_snapshot_aandelen is None:
            raise ValueError("repository_snapshot_aandelen is niet geladen in SnapshotStore")
        
        # Laad asset_map voor IB symbolen
        asset_map = SNAPSHOT_STORE.snapshot_asset_rollup_data
        if asset_map.is_empty():
            return pl.DataFrame()
        
        # Selecteer relevante velden uit asset_map
        asset_map = asset_map.select([
            "asset_rollup", "ib_symbol", "ib_currency", "prim_exchange","regio", "sector", "value_grow"
        ])
        
        # Join met aandelen data
        aandelen = SNAPSHOT_STORE.repository_snapshot_aandelen
        df = asset_map.join(aandelen, on="asset_rollup", how="left")
        
        # print("[DEBUG is live prices in live aggregator?] live_prices sample:", list(self.live_prices.items())[:5])
        # print("[DEBUG is last prices in live aggregator?] last_prices sample:", list(self.last_prices.items())[:5])

        # Voeg Koers kolom toe met live prijzen of 0.0 als fallback
        df = df.with_columns([
            pl.struct(["ib_symbol", "ib_currency"]).map_elements(
                lambda row: (
                    self.live_prices.get((row["ib_symbol"], row["ib_currency"])) if row["ib_symbol"] and row["ib_currency"] and self.live_prices and self.live_prices.get((row["ib_symbol"], row["ib_currency"])) not in (None, 0.0)
                    else self.last_prices.get((row["ib_symbol"], row["ib_currency"]), 0.0) if row["ib_symbol"] and row["ib_currency"] and self.last_prices else 0.0
                ),
                return_dtype=pl.Float64
            ).alias("Koers")
        ])
        

        return df
    
    def update_live_price(self, symbol, currency, price):
        """
        Update live prijs voor specifiek symbol.
        
        Args:
            symbol: IB symbol (e.g. 'AAPL')
            price: Nieuwe prijs
        """
        if price is not None and price > 0:
            self.live_prices[symbol,currency] = float(price)
            # print(f"LiveAggregatorAandelen: Updated {symbol} = {price}")
    
    def process_live_update(self):
        """
        Verwerk live update trigger van PortfolioEngine.
        PortfolioEngine roept alleen deze methode aan - geen data doorgeven.
        LiveAggregator laadt zelf repository_snapshot_aandelen en verwerkt het.
        """
        try:
            # 1. Laad fresh data uit SnapshotStore
            if SNAPSHOT_STORE.repository_snapshot_aandelen is None:
                print("LiveAggregatorAandelen: snapshot_aandelen niet beschikbaar")
                return
            
            # 2. Laad en bereken complete DataFrame
            self.df = self._load_and_calculate()
            
            # 3. Aggregeer en sla op in aggregator_snapshot_aandelen_live
            self._save_to_snapshot_store()
            
            # 4. Signal UI dat aandelen data is geüpdatet
            self.aandelenUpdated.emit()
            
            # print(f"LiveAggregatorAandelen: Processed live update with {len(self.df)} rows") # Debug log
            
        except Exception as e:
            print(f"LiveAggregatorAandelen process error: {e}")
    
    def _load_and_calculate(self):
        """
        Laad snapshot_aandelen en voeg alle berekende kolommen toe.
        """
        # Laad basisdata
        df = self._load_and_prepare_data()
        
        if df.is_empty():
            return df
        
        # Voeg berekende kolommen toe
        df = self._add_calculated_columns(df)
        
        return df
    
    def _add_calculated_columns(self, df):
        """Voeg berekende kolommen toe op basis van Koers kolom."""
        # Eerste stap: basisberekeningen
        df = df.with_columns([
            (pl.col("aantal_bezit") * pl.col("Koers")).alias("eq_bezit"),
            (pl.col("euro_koop") / pl.col("aantal_koop").clip(lower_bound=1)).alias("avg_price"),
            (pl.col("euro_verkoop") + pl.col("euro_koop")).alias("result_realised"),
        ])
        
        # Tweede stap: gebruik avg_price
        df = df.with_columns([
            (pl.col("aantal_bezit") * pl.col("avg_price")).alias("eq_purchase"),
        ])
        
        # Derde stap: niet-gerealiseerde winst/verlies
        df = df.with_columns([
            (pl.col("eq_bezit")).alias("result_non_realised"),
            (pl.col("eq_bezit") + pl.col("result_realised")).alias("total_result"),
        ])
        



        return df
    

    def get_not_aggregated(self):
        """
        Haal geaggregeerde dataset op, gegroepeerd per asset_rollup.
        Gebruikt de data die al verwerkt is door PortfolioEngine.
        
        Returns:
            pl.DataFrame: Geaggregeerde aandelen data
        """
        if self.df is None or self.df.is_empty():
            return pl.DataFrame({
                "broker": [],
                "asset_rollup": [],
                "koers": [],
                "aantal_bezit": [],
                "eq_total_fee": [],
                "total_result": [],
                "regio": []
            })

        return self.df.group_by(
            "broker", "asset_rollup", "regio", "sector", "value_grow"
        ).agg(
            [
                # Gebruik "Koers" zoals PortfolioEngine het heeft berekend
                pl.col("Koers").max().alias("koers"),
                pl.col("aantal_bezit").sum(),
                pl.col("aantal_koop").sum(),
                pl.col("euro_koop").sum(),
                pl.col("aantal_verkoop").sum(),
                pl.col("euro_verkoop").sum(),
                pl.col("eq_total_fee").sum(),
                pl.col("total_result").sum(),
            ]
        )



    
    def get_aggregated(self):
        """
        Haal geaggregeerde dataset op, gegroepeerd per asset_rollup.
        Gebruikt de data die al verwerkt is door PortfolioEngine.
        
        Returns:
            pl.DataFrame: Geaggregeerde aandelen data
        """
        if self.df is None or self.df.is_empty():
            return pl.DataFrame({
                "asset_rollup": [],
                "koers": [],
                "aantal_bezit": [],
                "result_realised": [],
                "result_non_realised": [],
                "eq_total_fee": [],
                "total_result": []
            })

        return self.df.group_by("asset_rollup").agg(
            [
                # Gebruik "Koers" zoals PortfolioEngine het heeft berekend
                pl.col("Koers").max().alias("koers"),
                pl.col("aantal_bezit").sum(),
                pl.col("result_realised").sum(),
                pl.col("result_non_realised").sum(),
                pl.col("eq_total_fee").sum(),
                pl.col("total_result").sum(),
            ]
        )
    
    def _save_to_snapshot_store(self):
        """Sla geaggregeerde data op in SnapshotStore."""
        try:
            aggregated = self.get_not_aggregated()
            SNAPSHOT_STORE.safe_write("aggregator_snapshot_aandelen_live", aggregated)
        except Exception as e:
            print(f"LiveAggregatorAandelen: Error saving to SnapshotStore: {e}")
    
    def refresh_data(self):
        """Herlaad data uit SnapshotStore (voor manual refresh)."""
        self._initialize_data()
        if self.df is not None and not self.df.is_empty():
            self._save_to_snapshot_store()
            self.aandelenUpdated.emit()
    


import polars as pl
from PySide6.QtCore import QObject, Signal
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE

class LiveAggregatorSprinters(QObject):
    """
    Specialized aggregator voor sprinters met live price updates.
    Laadt data uit repository_snapshot_load_open_opties, koppelt met asset_rollup en sprinter_referentie_data,
    voegt live koersen toe en berekent winst (placeholder).
    """
    sprintersUpdated = Signal()

    def __init__(self):
        super().__init__()
        self.df = None
        self.live_prices = {}  # Dict: {ib_symbol: koers}
        self._initialize_data()

    def _initialize_data(self):
        try:
            self.df = self._load_and_calculate()
            print(f"LiveAggregatorSprinters: Initialized with {len(self.df)} rows")
            self._save_to_snapshot_store()
        except Exception as e:
            print(f"LiveAggregatorSprinters initialization error: {e}")
            self.df = pl.DataFrame()

    def _load_and_prepare_data(self):
        if SNAPSHOT_STORE.repository_snapshot_open_sprinters is None:
            raise ValueError("repository_snapshot_open_sprinters is niet geladen in SnapshotStore")
        asset_map = SNAPSHOT_STORE.snapshot_asset_rollup_data
        if asset_map is None or asset_map.is_empty():
            raise ValueError("snapshot_asset_rollup_data is niet geladen")
        sprinter_ref = getattr(SNAPSHOT_STORE, "repository_snapshot_sprinter_referentie_data", None)
        if sprinter_ref is None or sprinter_ref.is_empty():
            raise ValueError("repository_snapshot_sprinter_referentie_data is niet geladen")
        # Join met asset_map voor ib_symbol (zonder asset_detail)
        asset_map = asset_map.select(["asset_rollup", "ib_symbol"])
        df = SNAPSHOT_STORE.repository_snapshot_open_sprinters.clone()
        df = df.join(asset_map, on="asset_rollup", how="left")
        # Join met sprinter_ref altijd op asset_detail (die hoort in df te zitten)
        sprinter_ref = sprinter_ref.select(["asset_detail", "sprinter_funding", "sprinter_ratio"])
        df = df.join(sprinter_ref, on="asset_detail", how="left")
        # Voeg koers toe op basis van ib_symbol
        df = df.with_columns([
            pl.col("ib_symbol").map_elements(
                lambda symbol: self.live_prices.get(symbol, 0.0) if symbol else 0.0,
                return_dtype=pl.Float64
            ).alias("Koers")
        ])
        return df

    def _load_and_calculate(self):
        df = self._load_and_prepare_data()
        # Voeg placeholder winst kolom toe
        df = df.with_columns([
            pl.lit(0.0).alias("winst")  # Placeholder, later vervangen door echte berekening
        ])
        # Selecteer relevante kolommen
        select_cols = [
            "broker", "asset_rollup", "asset_detail", "Koers", # "optie_exp_date", "optie_strike", "optie_call_put",
            "sprinter_funding", "sprinter_ratio", "SomVantransactie_aantal", "SomVantransactie_euro_totaal", "winst"
        ]
        df = df.select([col for col in select_cols if col in df.columns])
        return df

    def update_live_price(self, symbol, price):
        if price is not None and price > 0:
            self.live_prices[symbol] = float(price)

    def process_live_update(self):
        """
        Verwerk live update trigger van PortfolioEngine.
        PortfolioEngine roept alleen deze methode aan - geen data doorgeven.
        LiveAggregator laadt zelf repository_snapshot_open_sprinters en verwerkt het.
        """
        try:
            if SNAPSHOT_STORE.repository_snapshot_open_sprinters is None:
                print("LiveAggregatorSprinters: repository_snapshot_open_sprinters niet beschikbaar")
                return
            self.df = self._load_and_calculate()
            self._save_to_snapshot_store()
            self.sprintersUpdated.emit()
        except Exception as e:
            print(f"LiveAggregatorSprinters process error: {e}")

    def _save_to_snapshot_store(self):
        if self.df is not None and not self.df.is_empty():
            SNAPSHOT_STORE.aggregator_snapshot_open_sprinters_live = self.df.clone()
        else:
            print("LiveAggregatorSprinters: Geen data om op te slaan")

import polars as pl
from PySide6.QtCore import QObject, Signal
from portefeuille_viewer.signals import signals
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.repository import load_last_prices_dict

class LiveAggregatorSprinters(QObject):
    """
    Specialized aggregator voor sprinters met live price updates.
    Laadt data uit repository_snapshot_load_open_opties, koppelt met asset_rollup en sprinter_referentie_data,
    voegt live koersen toe en berekent winst (placeholder).
    """
    sprintersUpdated = Signal()

    def __init__(self, verbose=False):
        super().__init__()
        self.df = None
        self.last_prices = load_last_prices_dict()
        self.live_prices = {}  # Dict: {ib_symbol: koers}
        self.verbose = verbose
        self._initialize_data()
        signals.snapshotUpdated.connect(self._on_snapshot_updated)
        signals.databaseChanged.connect(self._on_database_changed)
        signals.ordersCommitted.connect(self.refresh_data)
    
    def _on_database_changed(self, db_name):
        # Indien relevant, herlaad data bij database wissel
        self.refresh_data()
    
    def _on_snapshot_updated(self, snapshot_key):
        if snapshot_key == "repository_snapshot_open_sprinters":
            self.refresh_data()
    def _initialize_data(self):
        try:
            self.df = self._load_and_calculate()
            if self.verbose:
                print(f"LiveAggregatorSprinters: Initialized with {len(self.df)} rows")
            self._save_to_snapshot_store()
        except Exception as e:
            if self.verbose:
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
        asset_map = asset_map.select(["asset_rollup", "ib_symbol", "ib_currency"])
        df = SNAPSHOT_STORE.repository_snapshot_open_sprinters.clone()
        df = df.join(asset_map, on="asset_rollup", how="left")
        # Join met sprinter_ref altijd op asset_detail (die hoort in df te zitten)
        sprinter_ref = sprinter_ref.select(["asset_detail", "sprinter_funding", "sprinter_ratio"])
        df = df.join(sprinter_ref, on="asset_detail", how="left")
        # Voeg koers toe op basis van ib_symbol

        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        # from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
        # SNAPSHOT_STORE.test_repository_load_input_test_dataframe = df  # of df_sum als je de gesumde versie wilt zien
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken


        df = df.with_columns([
            pl.struct(["ib_symbol", "ib_currency"]).map_elements(
                lambda row: (
                    self.live_prices.get((row["ib_symbol"], row["ib_currency"])) if row["ib_symbol"] and row["ib_currency"] and self.live_prices and self.live_prices.get((row["ib_symbol"], row["ib_currency"])) not in (None, 0.0)
                    else self.last_prices.get((row["ib_symbol"], row["ib_currency"]), 0.0) if row["ib_symbol"] and row["ib_currency"] and self.last_prices else 0.0
                ),
                return_dtype=pl.Float64
            ).alias("Koers")
        ])

        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        # from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
        # SNAPSHOT_STORE.test_repository_load_output_test_dataframe = df  # of df_sum als je de gesumde versie wilt zien
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken


        return df

    def _load_and_calculate(self):
        df = self._load_and_prepare_data()

        # Voeg placeholder winst kolom toe
        df = df.with_columns([
            pl.lit(0.0).alias("winst")  # Placeholder, later vervangen door echte berekening
        ])
        # Selecteer relevante kolommen
        df = self._calculate_sprinter_resultaat(df)

        select_cols = [
            "broker", "asset_rollup", "asset_detail", "Koers", "optie_exp_date", "optie_strike", "optie_call_put",
            "sprinter_funding", "sprinter_ratio", "SomVantransactie_fee","SomVantransactie_aantal", "SomVantransactie_euro_totaal", "sp_result"
        ]
        df = df.select([col for col in select_cols if col in df.columns])



        return df

    def _calculate_sprinter_resultaat(self, df):
        # Placeholder voor echte winstberekening
        """
        berekening winst op een sprinter:
        - als koers > sprrinter_funding: sp_bruto_result = (Koers - sprinter_funding) *  SomVantransactie_aantal
        
        - als koers < sprinter_funding: sp_sp_bruto_result = 0
        - sp_net_result = (sp_bruto_result + SomVantransactie_euro_totaal)/ sprinter_ratio
        """


        df = df.with_columns([
            (pl.col("Koers").cast(pl.Float32) - pl.col("sprinter_funding").cast(pl.Float32)).alias("sp_diff")])
        df = df.with_columns([
            pl.when(pl.col("sp_diff") > 0)
            .then((pl.col("sp_diff")/pl.col("sprinter_ratio")) * pl.col("SomVantransactie_aantal"))
            .otherwise(0.0)
            .alias("sp_bruto_result")
        ])
        
        df = df.with_columns([
            ((pl.col("sp_bruto_result") + pl.col("SomVantransactie_euro_totaal")) ).alias("sp_result")
        ])


        return df



    def update_live_price(self, symbol, currency, price):
        if price is not None and price > 0:
            self.live_prices[(symbol, currency)] = float(price)

    def process_live_update(self):
        """
        Verwerk live update trigger van PortfolioEngine.
        PortfolioEngine roept alleen deze methode aan - geen data doorgeven.
        LiveAggregator laadt zelf repository_snapshot_open_sprinters en verwerkt het.
        """
        try:
            if SNAPSHOT_STORE.repository_snapshot_open_sprinters is None:
                if self.verbose:
                    print("LiveAggregatorSprinters: repository_snapshot_open_sprinters niet beschikbaar")
                return
            self.df = self._load_and_calculate()
            self._save_to_snapshot_store()
            self.sprintersUpdated.emit()
        except Exception as e:
            if self.verbose:
                print(f"LiveAggregatorSprinters process error: {e}")

    def _save_to_snapshot_store(self):
        # Altijd een DataFrame in de snapshot zetten, ook als deze leeg is
        if self.df is not None:
            SNAPSHOT_STORE.safe_write("aggregator_snapshot_open_sprinters_live", self.df.clone())
            if self.df.is_empty() and self.verbose:
                print("LiveAggregatorSprinters: Geen data om op te slaan (lege DataFrame opgeslagen)")
        else:
            SNAPSHOT_STORE.safe_write("aggregator_snapshot_open_sprinters_live", pl.DataFrame())
            if self.verbose:
                print("LiveAggregatorSprinters: Geen data om op te slaan (None, lege DataFrame opgeslagen)")

    def on_scroll(self, _value):
        sb = self.table.verticalScrollBar()
        # marge van ~50 pixels voor ‘bijna onderaan’
        if sb.value() >= sb.maximum() - 50:
            self.load_more_records()

    def refresh_data(self):
        """Herlaad data uit SnapshotStore (voor manual refresh)."""
        self._initialize_data()
        if self.df is not None and not self.df.is_empty():
            self._save_to_snapshot_store()
            self.sprintersUpdated.emit()

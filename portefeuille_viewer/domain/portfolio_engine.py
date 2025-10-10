# ------------------------------------------------------------
# portfolio_engine.py:
# is de centrale regisseur die de datasets uit je snapshots combineert
# en de belangrijkste berekeningen uitvoert.
# bijv. load_snapshots(), build_open_positions()
# ------------------------------------------------------------


import polars as pl
from portefeuille_viewer.data import repository

class PortfolioEngine:
    """
    Centrale engine voor portefeuille-berekeningen en actuele posities op aandelen.
    Houdt een DataFrame in geheugen met live koersen en alle relevante afgeleide kolommen.
    """

    def __init__(self, pricefeed):
        self.pricefeed = pricefeed
        self.df = self._load_and_prepare()
        self.pricefeed.priceUpdated.connect(self._on_live_price)

    def _load_and_prepare(self):
        # Laad de basisdata uit transacties
        df = repository.load_aandelen_from_tx()  # verwacht kolommen: asset_rollup, broker, asset_type, aantal_koop, aantal_verkoop, aantal_bezit, euro_koop, euro_verkoop, fee_koop, fee_verkoop, etc.
        # Voeg ib_symbol, ib_currency, prim_exchange toe via asset_rollup_data
        asset_map = repository.load_asset_rollup_data()
        if not asset_map.is_empty():
            df = df.join(
                asset_map.select(["asset_rollup", "ib_symbol", "ib_currency", "prim_exchange"]),
                on="asset_rollup",
                how="left"
            )
        # Voeg koerskolom toe (default 0.0)
        df = df.with_columns([
            pl.lit(0.0).alias("Koers")
        ])
        # Voeg berekende kolommen toe
        df = self._add_calculated_columns(df)
        return df

    def _add_calculated_columns(self, df):
        # Berekent extra kolommen voor elke rij
        return df.with_columns([
            (pl.col("aantal_bezit") * pl.col("Koers")).alias("eq_bezit"),
            (pl.col("euro_koop") / pl.col("aantal_koop")).alias("avg_price"),
            (pl.col("euro_verkoop") + pl.col("euro_koop")).alias("result_realised"),
            (pl.col("aantal_bezit") * pl.col("avg_price")).alias("eq_purchase"),
            (pl.col("eq_bezit") + pl.col("eq_purchase")).alias("result_non_realised"),
        ])

    def _on_live_price(self, ib_symbol, currency, price):
        # Update alleen de rijen met deze ib_symbol
        if "ib_symbol" not in self.df.columns or self.df.is_empty():
            return
        mask = self.df["ib_symbol"] == ib_symbol
        if not mask.any():
            return
        self.df = self.df.with_columns([
            pl.when(mask).then(pl.lit(price)).otherwise(pl.col("Koers")).alias("Koers")
        ])
        # Herbereken de afgeleide kolommen
        self.df = self._add_calculated_columns(self.df)

    def get_full_df(self):
        """
        Geeft het volledige (niet-geaggregeerde) DataFrame terug (voor analyse, export, etc).
        """
        return self.df

    def get_aggregated(self):
        """
        Geeft een geaggregeerde DataFrame terug op asset_rollup-niveau.
        Kolommen: asset_rollup, koers, aantal_bezit, result_realised, result_non_realised
        """
        if self.df.is_empty():
            return pl.DataFrame({"asset_rollup": [], "koers": [], "aantal_bezit": [], "result_realised": [], "result_non_realised": []})
        return (
            self.df.groupby("asset_rollup")
            .agg([
                pl.col("Koers").max().alias("koers"),
                pl.col("aantal_bezit").sum(),
                pl.col("result_realised").sum(),
                pl.col("result_non_realised").sum(),
            ])
        )
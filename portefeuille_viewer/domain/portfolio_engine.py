import polars as pl
from portefeuille_viewer.data import repository
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE 

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

        if SNAPSHOT_STORE.snapshot_aandelen is None:
            raise ValueError("Aandelen-data is niet geladen in SnapshotStore.")

        # Laad asset_map en selecteer de relevante velden
        asset_map = SNAPSHOT_STORE.snapshot_asset_rollup_data
        if not asset_map.is_empty():
            asset_map = asset_map.select(["asset_rollup", "ib_symbol", "ib_currency", "prim_exchange"])

            # Laad snapshot_aandelen
            aandelen = SNAPSHOT_STORE.snapshot_aandelen

            # Voer een left join uit waarbij asset_map leidend is
            df = asset_map.join(
                aandelen,
                on="asset_rollup",
                how="left"
            )
        else:
            # Als asset_map leeg is, gebruik een lege DataFrame
            df = pl.DataFrame()



        # if SNAPSHOT_STORE.snapshot_aandelen is None:
        #     raise ValueError("Aandelen-data is niet geladen in SnapshotStore.")
        # df = SNAPSHOT_STORE.snapshot_aandelen
        # asset_map = SNAPSHOT_STORE.snapshot_asset_rollup_data

        # if not asset_map.is_empty():
        #     df = df.join(
        #         asset_map.select(["asset_rollup", "ib_symbol", "ib_currency", "prim_exchange"]),
        #         on="asset_rollup",
        #         how="left"
        #     )
        # Voeg koerskolom toe (default 0.0)
        df = df.with_columns([
            pl.lit(0.0).alias("Koers")
        ])
        df = self._add_calculated_columns(df)
        return df

    def _add_calculated_columns(self, df):
        # Eerste stap: kolommen die alleen van de originele kolommen afhangen
        df = df.with_columns([
            (pl.col("aantal_bezit") * pl.col("Koers")).alias("eq_bezit"),
            (pl.col("euro_koop") / pl.col("aantal_koop")).alias("avg_price"),
            (pl.col("euro_verkoop") + pl.col("euro_koop")).alias("result_realised"),
        ])
        # Tweede stap: gebruik van avg_price
        df = df.with_columns([
            (pl.col("aantal_bezit") * pl.col("avg_price")).alias("eq_purchase"),
        ])
        # Derde stap: gebruik van eq_purchase
        df = df.with_columns([
            (pl.col("eq_bezit") ).alias("result_non_realised"),
            (pl.col("eq_bezit") + pl.col("result_realised")).alias("total_result"),
        ])
        return df

    def _on_live_price(self, ib_symbol, currency, price):
        if "ib_symbol" not in self.df.columns or self.df.is_empty():
            return
        mask = self.df["ib_symbol"] == ib_symbol
        if not mask.any():
            return
        self.df = self.df.with_columns([
            pl.when(mask).then(pl.lit(price)).otherwise(pl.col("Koers")).alias("Koers")
        ])
        self.df = self._add_calculated_columns(self.df)

    def get_full_df(self):
        return self.df


    def get_aggregated(self):
        """
        Haal de geaggregeerde dataset op en voeg gesloten opties toe.
        """
        if self.df.is_empty():
            return pl.DataFrame({
                "asset_rollup": [],
                "koers": [],
                "aantal_bezit": [],
                "result_realised": [],
                "result_non_realised": [],
                "eq_total_fee": [],
                "clos_opt_transactie_fee": [],
                "clos_opt_transactie_euro_totaal": [],
                "total_result": []
            })

        # Basisaggregatie
        aggregated_df = (
            self.df.group_by("asset_rollup")
            .agg([
                pl.col("Koers").max().alias("koers"),
                pl.col("aantal_bezit").sum(),
                pl.col("result_realised").sum(),
                pl.col("result_non_realised").sum(),
                pl.col("eq_total_fee").sum(),
                pl.col("total_result").sum()
            ])
        )

        # Voeg gesloten opties toe
        closed_options = SNAPSHOT_STORE.snapshot_gesloten_opties_no_broker
        if closed_options is not None and not closed_options.is_empty():
            aggregated_df = aggregated_df.join(
                closed_options.select(["asset_rollup", "clos_opt_transactie_fee", "clos_opt_transactie_euro_totaal"]),
                on="asset_rollup",
                how="left"
            )
        else:
            aggregated_df = aggregated_df.with_columns([
                pl.lit(0).alias("clos_opt_transactie_fee"),
                pl.lit(0).alias("clos_opt_transactie_euro_totaal"),
            ])

        # Pas de kolomvolgorde aan
        aggregated_df = aggregated_df.select([
            "asset_rollup",
            "koers",
            "aantal_bezit",
            "result_realised",
            "result_non_realised",
            "total_result",
            "clos_opt_transactie_euro_totaal",
            "eq_total_fee",
            "clos_opt_transactie_fee",
            

        ])

        return aggregated_df
    
    
    def get_aggregated2(self):
        if self.df.is_empty():
            return pl.DataFrame({
                "asset_rollup": [],
                "koers": [],
                "aantal_bezit": [],
                "aantal_koop": [],
                "euro_koop": [],
                "aantal_verkoop": [],
                "euro_verkoop": [],
                "result_realised": [],
                "result_non_realised": [],
                "total_result": [],
                "total_fee": []
            })
        return (
            self.df.group_by("asset_rollup")
            .agg([
                pl.col("Koers").max().alias("koers"),
                pl.col("aantal_bezit").sum(),
                pl.col("aantal_koop").sum(),
                pl.col("euro_koop").sum(),
                pl.col("aantal_verkoop").sum(),
                pl.col("euro_verkoop").sum(),
                pl.col("result_realised").sum(),
                pl.col("result_non_realised").sum(),
                pl.col("total_result").sum(),
                pl.col("total_fee").sum()
            ])
        )


from PySide6.QtCore import QObject, Signal
import polars as pl
import datetime
import os
import time

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.repository import load_last_prices_dict
from portefeuille_viewer.data.price_utils import apply_runtime_beta_shift, build_prices_df


class LiveAggregatorAandelen(QObject):
    """
    Gespecialiseerde aggregator voor aandelen live data processing.
    """

    aandelenUpdated = Signal()

    def __init__(self):
        super().__init__()
        self.df = None
        self._last_published_df = None
        self._last_publish_ts = 0.0
        self._publish_min_interval_sec = max(
            0.0,
            float(os.getenv("LIVE_AANDELEN_PUBLISH_MIN_INTERVAL_SEC", "15.0")),
        )
        self.last_prices = load_last_prices_dict()
        self.live_prices = {}
        self._initialize_data()

    def _initialize_data(self):
        try:
            self.df = self._load_and_calculate()
            print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] LiveAggregatorAandelen: Initialized with {len(self.df)} rows")
            self._save_to_snapshot_store()
        except Exception as e:
            print(f"LiveAggregatorAandelen initialization error: {e}")
            self.df = pl.DataFrame()

    def _load_and_prepare_data(self):
        if SNAPSHOT_STORE.repository_snapshot_aandelen is None:
            raise ValueError("repository_snapshot_aandelen is niet geladen in SnapshotStore")

        asset_map = SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
        if asset_map.is_empty():
            return pl.DataFrame()

        asset_map = asset_map.select(
            ["asset_rollup", "ib_symbol", "ib_currency", "prim_exchange", "regio", "sector", "value_grow"]
        )
        aandelen = SNAPSHOT_STORE.repository_snapshot_aandelen
        df = asset_map.join(aandelen, on="asset_rollup", how="left")

        prices_df = build_prices_df(self.live_prices, self.last_prices)
        if not prices_df.is_empty():
            df = df.join(prices_df, on=["ib_symbol", "ib_currency"], how="left")
            df = df.with_columns(pl.col("price").fill_null(0.0).alias("Koers")).drop("price")
        else:
            df = df.with_columns(pl.lit(0.0).alias("Koers"))
        df = apply_runtime_beta_shift(df, "Koers")
        return df

    def update_live_price(self, symbol, currency, price):
        if price is not None and price > 0:
            self.live_prices[(symbol, currency)] = float(price)

    def process_live_update(self):
        try:
            if SNAPSHOT_STORE.repository_snapshot_aandelen is None:
                print("LiveAggregatorAandelen: snapshot_aandelen niet beschikbaar")
                return

            self.df = self._load_and_calculate()
            if self._save_to_snapshot_store():
                self.aandelenUpdated.emit()
        except Exception as e:
            print(f"LiveAggregatorAandelen process error: {e}")

    def _load_and_calculate(self):
        df = self._load_and_prepare_data()
        if df.is_empty():
            return df
        return self._add_calculated_columns(df)

    def _add_calculated_columns(self, df):
        df = df.with_columns(
            [
                (pl.col("aantal_bezit") * pl.col("Koers")).alias("eq_bezit"),
                (pl.col("euro_koop") / pl.col("aantal_koop").clip(lower_bound=1)).alias("avg_price"),
                (pl.col("euro_verkoop") + pl.col("euro_koop")).alias("result_realised"),
            ]
        )
        df = df.with_columns([(pl.col("aantal_bezit") * pl.col("avg_price")).alias("eq_purchase")])
        df = df.with_columns(
            [
                pl.col("eq_bezit").alias("result_non_realised"),
                (pl.col("eq_bezit") + pl.col("result_realised")).alias("total_result"),
            ]
        )
        return df

    def get_not_aggregated(self):
        if self.df is None or self.df.is_empty():
            return pl.DataFrame(
                {
                    "broker": [],
                    "asset_rollup": [],
                    "koers": [],
                    "aantal_bezit": [],
                    "eq_total_fee": [],
                    "total_result": [],
                    "regio": [],
                }
            )

        return self.df.group_by("broker", "asset_rollup", "regio", "sector", "value_grow").agg(
            [
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
        if self.df is None or self.df.is_empty():
            return pl.DataFrame(
                {
                    "asset_rollup": [],
                    "koers": [],
                    "aantal_bezit": [],
                    "result_realised": [],
                    "result_non_realised": [],
                    "eq_total_fee": [],
                    "total_result": [],
                }
            )

        return self.df.group_by("asset_rollup").agg(
            [
                pl.col("Koers").max().alias("koers"),
                pl.col("aantal_bezit").sum(),
                pl.col("result_realised").sum(),
                pl.col("result_non_realised").sum(),
                pl.col("eq_total_fee").sum(),
                pl.col("total_result").sum(),
            ]
        )

    def _df_changed(self, new_df: pl.DataFrame) -> bool:
        old_df = self._last_published_df
        if old_df is None:
            return True
        try:
            return not old_df.equals(new_df)
        except Exception:
            return True

    def _save_to_snapshot_store(self) -> bool:
        try:
            aggregated = self.get_not_aggregated()
            if not self._df_changed(aggregated):
                return False
            now_ts = time.monotonic()
            if self._last_publish_ts and (now_ts - self._last_publish_ts) < self._publish_min_interval_sec:
                return False
            SNAPSHOT_STORE.safe_write("aggregator_snapshot_aandelen_live", aggregated)
            self._last_published_df = aggregated.clone()
            self._last_publish_ts = now_ts
            return True
        except Exception as e:
            print(f"LiveAggregatorAandelen: Error saving to SnapshotStore: {e}")
            return False

    def refresh_data(self):
        self._initialize_data()
        if self.df is not None and not self.df.is_empty():
            if self._save_to_snapshot_store():
                self.aandelenUpdated.emit()

    def reset_for_database_change(self):
        self.df = pl.DataFrame()
        self._last_published_df = None
        self._last_publish_ts = 0.0
        self.last_prices = load_last_prices_dict()
        self.live_prices = {}

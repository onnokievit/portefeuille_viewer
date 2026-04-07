import polars as pl
from PySide6.QtCore import QObject, Signal
import time
import os

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.repository import load_last_prices_dict
from portefeuille_viewer.data.price_utils import apply_runtime_beta_shift, build_prices_df


class LiveAggregatorOpties(QObject):
    """
    Specialized aggregator voor opties met live price updates.
    """

    optiesUpdated = Signal()

    def __init__(self):
        super().__init__()
        self.df = None
        self._last_published_df = None
        self._last_publish_ts = 0.0
        self._publish_min_interval_sec = max(
            0.0,
            float(os.getenv("LIVE_OPTIES_PUBLISH_MIN_INTERVAL_SEC", "15.0")),
        )
        self.last_prices = load_last_prices_dict()
        self.live_prices = {}
        self._initialize_data()

    def _initialize_data(self):
        try:
            self.df = self._load_and_calculate()
            print(f"LiveAggregatorOpties: Initialized with {len(self.df)} rows")
            self._save_to_snapshot_store()
        except Exception as e:
            print(f"LiveAggregatorOpties initialization error: {e}")
            self.df = pl.DataFrame()

    def _load_and_prepare_data(self):
        if SNAPSHOT_STORE.repository_snapshot_load_open_opties is None:
            raise ValueError("snapshot_load_open_opties_from_tx is niet geladen in SnapshotStore")

        asset_map = SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
        if asset_map is None or asset_map.is_empty():
            raise ValueError("repository_snapshot_asset_rollup_data is niet geladen")

        asset_map = asset_map.select(["asset_rollup", "ib_symbol", "ib_currency"])
        df = SNAPSHOT_STORE.repository_snapshot_load_open_opties.clone()
        df = df.join(asset_map, on="asset_rollup", how="left")

        prices_df = build_prices_df(self.live_prices, self.last_prices)
        if not prices_df.is_empty():
            df = df.join(prices_df, on=["ib_symbol", "ib_currency"], how="left")
            df = df.with_columns(pl.col("price").fill_null(0.0).alias("Koers")).drop("price")
        else:
            df = df.with_columns(pl.lit(0.0).alias("Koers"))
        df = apply_runtime_beta_shift(df, "Koers")
        return df

    def _load_and_calculate(self):
        df = self._load_and_prepare_data()
        df = self._calculate_itm_otm(df)
        df = df.with_columns(
            [(pl.col("SomVantransactie_euro_totaal") + pl.col("ITM_OTM")).alias("opt_total_result")]
        )
        return df.select(
            [
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
                "SomVantransactie_fee",
            ]
        )

    def _calculate_itm_otm(self, df):
        return df.with_columns(
            [
                pl.when((pl.col("optie_call_put") == "call") & (pl.col("Koers") > pl.col("optie_strike")))
                .then((pl.col("Koers") - pl.col("optie_strike")) * pl.col("SomVantransactie_aantal"))
                .when((pl.col("optie_call_put") == "put") & (pl.col("Koers") < pl.col("optie_strike")))
                .then((pl.col("optie_strike") - pl.col("Koers")) * pl.col("SomVantransactie_aantal"))
                .otherwise(0.0)
                .alias("ITM_OTM")
            ]
        )

    def update_live_price(self, symbol, currency, price):
        if price is not None and price > 0:
            self.live_prices[(symbol, currency)] = float(price)

    def process_live_update(self):
        try:
            if SNAPSHOT_STORE.repository_snapshot_load_open_opties is None:
                print("LiveAggregatorOpties: snapshot_load_open_opties_from_tx niet beschikbaar")
                return

            self.df = self._load_and_calculate()
            if self._save_to_snapshot_store():
                self.optiesUpdated.emit()
        except Exception as e:
            print(f"LiveAggregatorOpties process error: {e}")

    def _df_changed(self, new_df: pl.DataFrame) -> bool:
        old_df = self._last_published_df
        if old_df is None:
            return True
        try:
            return not old_df.equals(new_df)
        except Exception:
            return True

    def _save_to_snapshot_store(self) -> bool:
        frame = self.df.clone() if self.df is not None and not self.df.is_empty() else pl.DataFrame()
        if not self._df_changed(frame):
            return False
        now_ts = time.monotonic()
        if self._last_publish_ts and (now_ts - self._last_publish_ts) < self._publish_min_interval_sec:
            return False
        SNAPSHOT_STORE.safe_write("aggregator_snapshot_load_open_opties_from_tx_live", frame)
        self._last_published_df = frame.clone()
        self._last_publish_ts = now_ts
        return True

    def refresh_data(self):
        self._initialize_data()
        if self.df is not None and not self.df.is_empty():
            if self._save_to_snapshot_store():
                self.optiesUpdated.emit()

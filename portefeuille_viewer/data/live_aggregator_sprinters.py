import polars as pl
from PySide6.QtCore import QObject, Signal
import time
import os

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.repository import load_last_prices_dict
from portefeuille_viewer.data.price_utils import apply_runtime_beta_shift, build_prices_df


class LiveAggregatorSprinters(QObject):
    """
    Specialized aggregator voor sprinters met live price updates.
    """

    sprintersUpdated = Signal()

    def __init__(self, verbose=False):
        super().__init__()
        self.df = None
        self._last_published_df = None
        self._last_publish_ts = 0.0
        self._publish_min_interval_sec = max(
            0.0,
            float(os.getenv("LIVE_SPRINTERS_PUBLISH_MIN_INTERVAL_SEC", "15.0")),
        )
        self.last_prices = load_last_prices_dict()
        self.live_prices = {}
        self.verbose = verbose
        self._initialize_data()

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
        asset_map = SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
        if asset_map is None or asset_map.is_empty():
            raise ValueError("repository_snapshot_asset_rollup_data is niet geladen")
        sprinter_ref = getattr(SNAPSHOT_STORE, "repository_snapshot_sprinter_referentie_data", None)
        if sprinter_ref is None or sprinter_ref.is_empty():
            raise ValueError("repository_snapshot_sprinter_referentie_data is niet geladen")

        asset_map = asset_map.select(["asset_rollup", "ib_symbol", "ib_currency"])
        df = SNAPSHOT_STORE.repository_snapshot_open_sprinters.clone()
        df = df.join(asset_map, on="asset_rollup", how="left")
        sprinter_ref = sprinter_ref.select(["asset_detail", "sprinter_funding", "sprinter_ratio"])
        df = df.join(sprinter_ref, on="asset_detail", how="left")

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
        df = df.with_columns([pl.lit(0.0).alias("winst")])
        df = self._calculate_sprinter_resultaat(df)
        select_cols = [
            "broker",
            "asset_rollup",
            "asset_detail",
            "Koers",
            "optie_exp_date",
            "optie_strike",
            "optie_call_put",
            "sprinter_funding",
            "sprinter_ratio",
            "SomVantransactie_fee",
            "SomVantransactie_aantal",
            "SomVantransactie_euro_totaal",
            "sp_result",
        ]
        return df.select([col for col in select_cols if col in df.columns])

    def _calculate_sprinter_resultaat(self, df):
        df = df.with_columns(
            [(pl.col("Koers").cast(pl.Float32) - pl.col("sprinter_funding").cast(pl.Float32)).alias("sp_diff")]
        )
        df = df.with_columns(
            [
                pl.when(pl.col("sp_diff") > 0)
                .then((pl.col("sp_diff") / pl.col("sprinter_ratio")) * pl.col("SomVantransactie_aantal"))
                .otherwise(0.0)
                .alias("sp_bruto_result")
            ]
        )
        return df.with_columns(
            [((pl.col("sp_bruto_result") + pl.col("SomVantransactie_euro_totaal"))).alias("sp_result")]
        )

    def update_live_price(self, symbol, currency, price):
        if price is not None and price > 0:
            self.live_prices[(symbol, currency)] = float(price)

    def process_live_update(self, *, force_publish: bool = False):
        try:
            if SNAPSHOT_STORE.repository_snapshot_open_sprinters is None:
                if self.verbose:
                    print("LiveAggregatorSprinters: repository_snapshot_open_sprinters niet beschikbaar")
                return
            self.df = self._load_and_calculate()
            if self._save_to_snapshot_store(force_publish=force_publish):
                self.sprintersUpdated.emit()
        except Exception as e:
            if self.verbose:
                print(f"LiveAggregatorSprinters process error: {e}")

    def _df_changed(self, new_df: pl.DataFrame) -> bool:
        old_df = self._last_published_df
        if old_df is None:
            return True
        try:
            return not old_df.equals(new_df)
        except Exception:
            return True

    def _save_to_snapshot_store(self, *, force_publish: bool = False) -> bool:
        frame = self.df.clone() if self.df is not None else pl.DataFrame()
        if not self._df_changed(frame):
            return False
        now_ts = time.monotonic()
        if (
            not force_publish
            and self._last_publish_ts
            and (now_ts - self._last_publish_ts) < self._publish_min_interval_sec
        ):
            return False
        SNAPSHOT_STORE.safe_write("aggregator_snapshot_open_sprinters_live", frame)
        self._last_published_df = frame.clone()
        self._last_publish_ts = now_ts
        if frame.is_empty() and self.verbose:
            print("LiveAggregatorSprinters: Geen data om op te slaan (lege DataFrame opgeslagen)")
        return True

    def on_scroll(self, _value):
        sb = self.table.verticalScrollBar()
        if sb.value() >= sb.maximum() - 50:
            self.load_more_records()

    def refresh_data(self, *, force_publish: bool = False):
        self._initialize_data()
        if self.df is not None and not self.df.is_empty():
            if self._save_to_snapshot_store(force_publish=force_publish):
                self.sprintersUpdated.emit()

    def reset_for_database_change(self):
        self.df = pl.DataFrame()
        self._last_published_df = None
        self._last_publish_ts = 0.0
        self.last_prices = load_last_prices_dict()
        self.live_prices = {}

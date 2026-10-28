"""Legacy price-distribution calculation, isolated from the original UI."""
from datetime import date, datetime
import math
import polars as pl

class DashboardDistribution:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _as_finite_float(value):
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (TypeError, ValueError):
            return None

    def calculate(self, asset, steps):
        all_rows = self._load_asset_historical_ohlcv(asset)
        rows = self._filter_rows_last_months(all_rows, 12)
        centers, width = self._build_fine_distribution_grid(rows, steps)
        series = {str(months): self._distribution_from_bucket_centers(
            self._filter_rows_last_months(all_rows, months), centers, width, True)
            for months in (24, 12, 6, 3)}
        if not any(series['12']):
            return None
        return dict(centers=centers, width=width, series=series,
                    maximum=max(1., max(max(values, default=0.) for values in series.values()) * 2.))

    @staticmethod
    def _shift_months(base: date, months_back: int) -> date:
        month = base.month - months_back
        year = base.year
        while month <= 0:
            month += 12
            year -= 1
        if month == 12:
            days_in_month = 31
        else:
            days_in_month = (date(year, month + 1, 1) - date(year, month, 1)).days
        return date(year, month, min(base.day, days_in_month))

    def _load_asset_historical_ohlcv(self, asset: str) -> list[dict]:
        asset = str(asset or "").strip().upper()
        if not asset:
            return []
        df = getattr(self.store, "repository_snapshot_historical_ohlcv", None)
        if df is None or df.is_empty():
            return []
        if "asset_rollup" not in df.columns or "datum" not in df.columns:
            return []
        work = df
        try:
            work = (
                work.with_columns(
                    [
                        pl.col("datum").cast(pl.Date, strict=False).alias("datum"),
                        pl.col("asset_rollup").cast(pl.Utf8, strict=False).str.strip_chars().str.to_uppercase().alias("asset_rollup"),
                    ]
                )
                .filter(pl.col("asset_rollup") == asset)
                .sort("datum")
            )
        except Exception:
            return []
        if work.is_empty():
            return []
        out: list[dict] = []
        for row in work.to_dicts():
            raw_date = row.get("datum")
            if isinstance(raw_date, datetime):
                datum = raw_date.date()
            elif isinstance(raw_date, date):
                datum = raw_date
            else:
                continue
            out.append(
                {
                    "datum": datum,
                    "open": self._as_finite_float(row.get("open_price")),
                    "high": self._as_finite_float(row.get("high_price")),
                    "low": self._as_finite_float(row.get("low_price")),
                    "close": self._as_finite_float(row.get("close_price")),
                    "volume": self._as_finite_float(row.get("volume_value")),
                }
            )
        return out

    @staticmethod
    def _filter_rows_last_months(rows: list[dict], months: int) -> list[dict]:
        if not rows:
            return []
        valid_dates = [item.get("datum") for item in rows if isinstance(item.get("datum"), date)]
        if not valid_dates:
            return []
        latest_date = max(valid_dates)
        cutoff = DashboardDistribution._shift_months(latest_date, int(months))
        return [
            item
            for item in rows
            if isinstance(item.get("datum"), date) and item["datum"] >= cutoff
        ]

    @staticmethod
    def _row_price_range(row: dict) -> tuple[float, float] | None:
        values = [row.get("open"), row.get("high"), row.get("low"), row.get("close")]
        values = [float(v) for v in values if v is not None and math.isfinite(float(v))]
        if not values:
            return None
        low = row.get("low")
        high = row.get("high")
        low = float(low) if low is not None and math.isfinite(float(low)) else min(values)
        high = float(high) if high is not None and math.isfinite(float(high)) else max(values)
        low = min(low, min(values))
        high = max(high, max(values))
        if high < low:
            low, high = high, low
        return low, high

    @staticmethod
    def _build_fine_distribution_grid(rows: list[dict], x_values: list[float]) -> tuple[list[float], float]:
        if not rows or not x_values:
            return [], 1.0
        valid_ranges = [DashboardDistribution._row_price_range(row) for row in rows]
        valid_ranges = [r for r in valid_ranges if r is not None]
        if not valid_ranges:
            return [], 1.0

        x_min = float(min(x_values))
        x_max = float(max(x_values))
        min_price = min(lo for lo, _hi in valid_ranges)
        max_price = max(hi for _lo, hi in valid_ranges)
        visible_min = min(x_min, min_price)
        visible_max = max(x_max, max_price)
        span = max(visible_max - visible_min, 1.0)

        target_buckets = 72
        raw_width = span / target_buckets
        if raw_width <= 0:
            raw_width = 1.0
        exponent = math.floor(math.log10(raw_width)) if raw_width > 0 else 0
        fraction = raw_width / (10 ** exponent)
        if fraction <= 1:
            nice = 1.0
        elif fraction <= 2:
            nice = 2.0
        elif fraction <= 2.5:
            nice = 2.5
        elif fraction <= 5:
            nice = 5.0
        else:
            nice = 10.0
        width = nice * (10 ** exponent)
        width = max(width, 0.01)

        left_edge = math.floor((visible_min - width) / width) * width
        right_edge = math.ceil((visible_max + width) / width) * width
        bucket_count = max(24, int(math.ceil((right_edge - left_edge) / width)))
        centers = [left_edge + (idx + 0.5) * width for idx in range(bucket_count)]
        return centers, width

    @staticmethod
    def _distribution_from_bucket_centers(
        rows: list[dict], centers: list[float], width: float, use_volume: bool = True
    ) -> list[float]:
        if not rows or not centers or width <= 0:
            return []
        left_edge = float(centers[0]) - width / 2.0
        weights = [0.0 for _ in centers]
        total_weight = 0.0
        for row in rows:
            price_range = DashboardDistribution._row_price_range(row)
            if price_range is None:
                continue
            low, high = price_range
            start_idx = int(math.floor((low - left_edge) / width))
            end_idx = int(math.floor(((high - left_edge) / width) - 1e-9))
            if end_idx < start_idx:
                end_idx = start_idx
            start_idx = max(0, start_idx)
            end_idx = min(len(centers) - 1, end_idx)
            if end_idx < 0 or start_idx >= len(centers):
                continue
            touched = end_idx - start_idx + 1
            if touched <= 0:
                continue
            if use_volume:
                vol = row.get("volume")
                row_weight = float(vol) if vol is not None and float(vol) > 0 else 1.0
            else:
                row_weight = 1.0
            total_weight += row_weight
            bucket_weight = row_weight / touched
            for idx in range(start_idx, end_idx + 1):
                weights[idx] += bucket_weight
        if total_weight <= 0:
            return []
        return [value * 100.0 / total_weight for value in weights]

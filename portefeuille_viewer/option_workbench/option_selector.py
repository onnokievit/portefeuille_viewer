from __future__ import annotations

import polars as pl

from .iv_models import SurfaceSelectionSettings


def select_option_universe(
    chain: pl.DataFrame,
    spot: float | None,
    settings: SurfaceSelectionSettings,
) -> pl.DataFrame:
    if chain.is_empty():
        return chain

    df = chain.filter(
        (pl.col("dte") >= int(settings.dte_min))
        & (pl.col("dte") <= int(settings.dte_max))
        & (pl.col("right").is_in(_rights(settings.right_mode)))
    )

    if spot and spot > 0:
        df = df.with_columns(
            [
                (pl.col("strike") / float(spot)).alias("moneyness"),
                (pl.col("strike") - float(spot)).abs().alias("_distance_to_spot"),
            ]
        ).filter(
            (pl.col("moneyness") >= float(settings.moneyness_min))
            & (pl.col("moneyness") <= float(settings.moneyness_max))
        )
    else:
        df = df.with_columns(
            [
                pl.lit(None, dtype=pl.Float64).alias("moneyness"),
                pl.col("strike").abs().alias("_distance_to_spot"),
            ]
        )

    cap = int(settings.max_strikes_per_expiry or 0)
    if cap > 0:
        df = (
            df.sort(["expiry", "right", "_distance_to_spot", "strike"])
            .with_columns(pl.int_range(pl.len()).over(["expiry", "right"]).alias("_rank"))
            .filter(pl.col("_rank") < cap)
            .drop("_rank")
        )

    return df.sort(["expiry", "right", "strike"]).drop("_distance_to_spot")


def _rights(mode: str) -> list[str]:
    text = str(mode or "B").upper()
    if text == "C":
        return ["C"]
    if text == "P":
        return ["P"]
    return ["C", "P"]

from __future__ import annotations

import polars as pl


def build_theta_scan(snapshot: pl.DataFrame, fallback_spot: float | None = None) -> pl.DataFrame:
    if snapshot.is_empty():
        return snapshot

    required_numeric = [
        "strike",
        "bid",
        "ask",
        "last",
        "mid",
        "model_opt_price",
        "model_und_price",
        "theta",
        "delta",
        "iv",
        "moneyness",
    ]
    df = _ensure_columns(snapshot, required_numeric + ["right", "dte"])
    df = df.with_columns(
        [
            _num("strike"),
            _num("bid"),
            _num("ask"),
            _num("last"),
            _num("mid"),
            _num("model_opt_price"),
            _num("model_und_price"),
            _num("theta"),
            _num("delta"),
            _num("iv"),
            _num("moneyness"),
            pl.col("right").cast(pl.Utf8).str.to_uppercase(),
            pl.col("dte").cast(pl.Int64, strict=False),
        ]
    )
    spot_expr = pl.coalesce([pl.col("model_und_price"), pl.lit(fallback_spot)]).cast(pl.Float64)
    price_expr = pl.coalesce([pl.col("mid"), pl.col("model_opt_price"), pl.col("last")]).cast(pl.Float64)
    intrinsic_expr = (
        pl.when(pl.col("right") == "C")
        .then(pl.max_horizontal(spot_expr - pl.col("strike"), pl.lit(0.0)))
        .when(pl.col("right") == "P")
        .then(pl.max_horizontal(pl.col("strike") - spot_expr, pl.lit(0.0)))
        .otherwise(None)
    )
    df = df.with_columns(
        [
            spot_expr.alias("spot_used"),
            price_expr.alias("option_price_used"),
            intrinsic_expr.alias("intrinsic_value"),
            (pl.col("ask") - pl.col("bid")).alias("spread"),
        ]
    )
    df = df.with_columns(
        [
            pl.max_horizontal(pl.col("option_price_used") - pl.col("intrinsic_value"), pl.lit(0.0)).alias(
                "extrinsic_value"
            ),
            (pl.col("spread") / pl.col("option_price_used") * 100.0).alias("spread_pct"),
            (-pl.col("theta")).alias("seller_theta_per_day"),
        ]
    )
    df = df.with_columns(
        [
            (pl.col("extrinsic_value") / pl.col("strike") * 100.0).alias("extrinsic_pct_strike"),
            (pl.col("extrinsic_value") / pl.col("strike") * 365.0 / pl.col("dte") * 100.0).alias(
                "extrinsic_yield_ann_pct"
            ),
            (pl.col("seller_theta_per_day") / pl.col("strike") * 365.0 * 100.0).alias("theta_yield_ann_pct"),
            (pl.col("extrinsic_value") / pl.col("spread")).alias("extrinsic_spread_ratio"),
            pl.col("delta").abs().alias("abs_delta"),
        ]
    )
    score = (
        pl.col("extrinsic_yield_ann_pct").fill_null(0.0)
        + pl.col("theta_yield_ann_pct").fill_null(0.0)
        - pl.col("spread_pct").fill_null(100.0) * 0.35
        - (pl.col("abs_delta").fill_null(0.0) - 0.25).abs() * 20.0
    )
    df = df.with_columns(score.alias("theta_score"))
    wanted = [
        "theta_score",
        "asset_rollup",
        "local_symbol",
        "expiry",
        "dte",
        "right",
        "strike",
        "moneyness",
        "delta",
        "abs_delta",
        "iv",
        "bid",
        "ask",
        "mid",
        "spread",
        "spread_pct",
        "option_price_used",
        "intrinsic_value",
        "extrinsic_value",
        "extrinsic_pct_strike",
        "extrinsic_yield_ann_pct",
        "seller_theta_per_day",
        "theta_yield_ann_pct",
        "vega",
        "gamma",
        "volume",
        "call_open_interest",
        "put_open_interest",
        "trading_class",
        "multiplier",
        "conid",
        "request_status",
    ]
    available = [col for col in wanted if col in df.columns]
    return df.select(available).sort("theta_score", descending=True)


def filter_theta_candidates(
    theta_df: pl.DataFrame,
    *,
    max_spread_pct: float = 20.0,
    min_extrinsic: float = 0.05,
    min_dte: int = 5,
    max_dte: int = 90,
    min_abs_delta: float = 0.05,
    max_abs_delta: float = 0.50,
) -> pl.DataFrame:
    if theta_df.is_empty():
        return theta_df
    return theta_df.filter(
        (pl.col("dte") >= min_dte)
        & (pl.col("dte") <= max_dte)
        & (pl.col("extrinsic_value") >= min_extrinsic)
        & (pl.col("spread_pct") <= max_spread_pct)
        & (pl.col("abs_delta") >= min_abs_delta)
        & (pl.col("abs_delta") <= max_abs_delta)
    )


def _num(name: str):
    return pl.col(name).cast(pl.Float64, strict=False)


def _ensure_columns(df: pl.DataFrame, names: list[str]) -> pl.DataFrame:
    out = df
    additions = []
    for name in names:
        if name not in out.columns:
            dtype = pl.Utf8 if name == "right" else pl.Float64
            additions.append(pl.lit(None, dtype=dtype).alias(name))
    if additions:
        out = out.with_columns(additions)
    return out

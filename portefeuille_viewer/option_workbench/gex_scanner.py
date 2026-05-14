from __future__ import annotations

import polars as pl


def build_gex_scan(
    snapshot: pl.DataFrame,
    fallback_spot: float | None = None,
    prefer_fallback_spot: bool = False,
) -> pl.DataFrame:
    if snapshot.is_empty():
        return snapshot

    required = [
        "asset_rollup",
        "local_symbol",
        "expiry",
        "dte",
        "right",
        "strike",
        "moneyness",
        "gamma",
        "model_gamma",
        "model_und_price",
        "multiplier",
        "call_open_interest",
        "put_open_interest",
        "volume",
        "delta",
        "iv",
        "request_status",
        "conid",
    ]
    df = _ensure_columns(snapshot, required)
    df = df.with_columns(
        [
            pl.col("right").cast(pl.Utf8).str.to_uppercase(),
            pl.col("strike").cast(pl.Float64, strict=False),
            pl.col("moneyness").cast(pl.Float64, strict=False),
            pl.col("dte").cast(pl.Int64, strict=False),
            pl.coalesce(
                [
                    pl.col("gamma").cast(pl.Float64, strict=False),
                    pl.col("model_gamma").cast(pl.Float64, strict=False),
                ]
            ).alias("gamma_used"),
            _spot_expr(fallback_spot, prefer_fallback_spot).alias("spot_used"),
            pl.coalesce(
                [
                    pl.col("multiplier").cast(pl.Float64, strict=False),
                    pl.lit(100.0),
                ]
            ).alias("multiplier_used"),
            pl.col("call_open_interest").cast(pl.Float64, strict=False),
            pl.col("put_open_interest").cast(pl.Float64, strict=False),
            pl.col("volume").cast(pl.Float64, strict=False),
            pl.col("delta").cast(pl.Float64, strict=False),
            pl.col("iv").cast(pl.Float64, strict=False),
        ]
    )
    df = df.with_columns(
        pl.when(pl.col("right") == "C")
        .then(pl.col("call_open_interest"))
        .when(pl.col("right") == "P")
        .then(pl.col("put_open_interest"))
        .otherwise(None)
        .alias("open_interest_used")
    )
    df = df.with_columns(
        (
            pl.col("gamma_used")
            * pl.col("open_interest_used")
            * pl.col("multiplier_used")
            * pl.col("spot_used")
            * pl.col("spot_used")
            * 0.01
        ).alias("gex_1pct")
    )
    df = df.with_columns(
        pl.when(pl.col("right") == "P")
        .then(-pl.col("gex_1pct"))
        .otherwise(pl.col("gex_1pct"))
        .alias("dealer_gex_1pct")
    )
    df = df.with_columns(pl.col("dealer_gex_1pct").abs().alias("abs_dealer_gex_1pct"))

    wanted = [
        "asset_rollup",
        "local_symbol",
        "expiry",
        "dte",
        "right",
        "strike",
        "moneyness",
        "spot_used",
        "gamma_used",
        "open_interest_used",
        "call_open_interest",
        "put_open_interest",
        "multiplier_used",
        "gex_1pct",
        "dealer_gex_1pct",
        "abs_dealer_gex_1pct",
        "delta",
        "iv",
        "volume",
        "conid",
        "request_status",
    ]
    available = [col for col in wanted if col in df.columns]
    return (
        df.select(available)
        .filter(
            pl.col("spot_used").is_not_null()
            & (pl.col("spot_used") > 0)
            & pl.col("gamma_used").is_not_null()
            & pl.col("open_interest_used").is_not_null()
            & (pl.col("open_interest_used") > 0)
        )
        .sort("abs_dealer_gex_1pct", descending=True)
    )


def aggregate_gex_by_strike(gex_df: pl.DataFrame) -> pl.DataFrame:
    if gex_df.is_empty():
        return gex_df
    required = {"strike", "dealer_gex_1pct", "gex_1pct", "open_interest_used"}
    if missing := required - set(gex_df.columns):
        raise RuntimeError(f"GEX data mist kolommen: {sorted(missing)}")

    grouped = (
        gex_df.group_by("strike")
        .agg(
            [
                pl.col("dealer_gex_1pct").sum().alias("net_dealer_gex_1pct"),
                pl.col("dealer_gex_1pct").filter(pl.col("right") == "C").sum().alias("call_gex_1pct"),
                pl.col("dealer_gex_1pct").filter(pl.col("right") == "P").sum().alias("put_gex_1pct"),
                pl.col("gex_1pct").sum().alias("gross_gex_1pct"),
                pl.col("open_interest_used").sum().alias("open_interest"),
                pl.col("conid").n_unique().alias("contracts"),
            ]
        )
        .sort("strike")
    )
    grouped = grouped.with_columns(pl.col("net_dealer_gex_1pct").cum_sum().alias("cumulative_dealer_gex_1pct"))
    return grouped.with_columns(pl.col("net_dealer_gex_1pct").abs().alias("abs_net_dealer_gex_1pct")).sort(
        "abs_net_dealer_gex_1pct", descending=True
    )


def estimate_gamma_flip(strike_gex: pl.DataFrame, reference_spot: float | None = None) -> float | None:
    if strike_gex.is_empty() or "cumulative_dealer_gex_1pct" not in strike_gex.columns:
        return None
    rows = strike_gex.sort("strike").select(["strike", "cumulative_dealer_gex_1pct"]).drop_nulls().to_dicts()
    if not rows:
        return None
    flips: list[float] = []
    previous = rows[0]
    if float(previous["cumulative_dealer_gex_1pct"]) == 0:
        flips.append(float(previous["strike"]))
    for current in rows[1:]:
        prev_y = float(previous["cumulative_dealer_gex_1pct"])
        cur_y = float(current["cumulative_dealer_gex_1pct"])
        if cur_y == 0:
            flips.append(float(current["strike"]))
        elif (prev_y < 0 < cur_y) or (prev_y > 0 > cur_y):
            prev_x = float(previous["strike"])
            cur_x = float(current["strike"])
            span = cur_y - prev_y
            if span == 0:
                flips.append(cur_x)
            else:
                flips.append(prev_x + (0.0 - prev_y) * (cur_x - prev_x) / span)
        previous = current
    if not flips:
        return None
    if reference_spot is not None and reference_spot > 0:
        return min(flips, key=lambda value: abs(value - float(reference_spot)))
    return flips[0]


def _ensure_columns(df: pl.DataFrame, names: list[str]) -> pl.DataFrame:
    additions = []
    for name in names:
        if name not in df.columns:
            dtype = pl.Utf8 if name in {"asset_rollup", "local_symbol", "right", "request_status"} else pl.Float64
            additions.append(pl.lit(None, dtype=dtype).alias(name))
    if not additions:
        return df
    return df.with_columns(additions)


def _spot_expr(fallback_spot: float | None, prefer_fallback_spot: bool):
    manual = pl.lit(fallback_spot, dtype=pl.Float64)
    model = pl.col("model_und_price").cast(pl.Float64, strict=False)
    if prefer_fallback_spot and fallback_spot is not None and fallback_spot > 0:
        return manual
    return pl.coalesce([model, manual])

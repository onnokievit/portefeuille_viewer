import polars as pl

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


def build_prices_df(live_prices: dict | None, last_prices: dict | None) -> pl.DataFrame:
    """
    Combineer laatste bekende prijzen met live prijzen.

    - last_prices: basislaag (bijv. uit DB)
    - live_prices: overschrijft last_prices wanneer aanwezig en > 0
    """
    combined: dict[tuple[str, str], float] = {}

    if last_prices:
        for (sym, curr), price in last_prices.items():
            if sym and curr and price is not None:
                combined[(sym, curr)] = float(price)

    if live_prices:
        for key, price in live_prices.items():
            if not isinstance(key, tuple) or len(key) != 2:
                continue
            sym, curr = key
            if sym and curr and price not in (None, 0.0):
                combined[(sym, curr)] = float(price)

    if not combined:
        return pl.DataFrame(
            {"ib_symbol": pl.Series([], dtype=pl.Utf8), "ib_currency": pl.Series([], dtype=pl.Utf8), "price": pl.Series([], dtype=pl.Float64)}
        )

    ib_symbol, ib_currency, price = zip(*[(k[0], k[1], v) for k, v in combined.items()])
    return pl.DataFrame({"ib_symbol": ib_symbol, "ib_currency": ib_currency, "price": price})


def apply_runtime_beta_shift(df: pl.DataFrame, price_col: str = "Koers") -> pl.DataFrame:
    if df is None or df.is_empty() or price_col not in df.columns or "asset_rollup" not in df.columns:
        return df
    if not bool(getattr(SNAPSHOT_STORE, "runtime_beta_shift_enabled", False)):
        return df
    try:
        global_shift_pct = float(getattr(SNAPSHOT_STORE, "runtime_price_shift_pct", 0.0) or 0.0)
    except Exception:
        global_shift_pct = 0.0
    shift_map_raw = getattr(SNAPSHOT_STORE, "runtime_price_shift_by_index", None) or {}
    lookback = str(getattr(SNAPSHOT_STORE, "runtime_price_shift_lookback", "12m") or "12m").strip().lower()
    shift_map: dict[str, float] = {}
    for key, value in dict(shift_map_raw).items():
        idx = str(key or "").strip().upper()
        if not idx:
            continue
        try:
            pct = float(value)
        except Exception:
            continue
        if abs(pct) >= 1e-12:
            shift_map[idx] = pct
    if abs(global_shift_pct) < 1e-12 and not shift_map:
        return df
    beta_df = getattr(SNAPSHOT_STORE, "repository_snapshot_asset_driver_beta", None)
    asset_cfg_df = getattr(SNAPSHOT_STORE, "repository_snapshot_asset_rollup_data", None)
    if (
        beta_df is None or beta_df.is_empty()
        or asset_cfg_df is None or asset_cfg_df.is_empty()
        or "asset_rollup" not in asset_cfg_df.columns
        or "home_index" not in asset_cfg_df.columns
        or "beta_mode" not in asset_cfg_df.columns
    ):
        return df

    def _parse_beta_mode_override(value) -> float | None:
        mode = str(value or "").strip().lower()
        if not mode or mode == "auto":
            return None
        if mode in {"disabled", "disable", "off", "none", "zero", "0"}:
            return 0.0
        if mode in {"one", "1", "fixed_1", "fixed1", "one_to_one"}:
            return 1.0
        try:
            return float(mode.replace(",", "."))
        except Exception:
            return None

    asset_cfg = (
        asset_cfg_df
        .select([
            pl.col("asset_rollup").cast(pl.Utf8, strict=False).str.strip_chars().str.to_uppercase().alias("asset_rollup"),
            pl.col("home_index").cast(pl.Utf8, strict=False).str.strip_chars().str.to_uppercase().alias("home_index"),
            pl.col("beta_mode").cast(pl.Utf8, strict=False).str.strip_chars().str.to_lowercase().alias("beta_mode"),
        ])
        .unique(subset=["asset_rollup"], keep="last")
    )
    if asset_cfg.is_empty():
        return df

    filtered = (
        beta_df
        .filter(pl.col("lookback_code").cast(pl.Utf8, strict=False).str.to_lowercase() == lookback)
        .select([
            pl.col("asset_rollup").cast(pl.Utf8, strict=False).str.strip_chars().str.to_uppercase().alias("asset_rollup"),
            pl.col("driver_index").cast(pl.Utf8, strict=False).str.strip_chars().str.to_uppercase().alias("home_index"),
            pl.col("beta_value").cast(pl.Float64, strict=False).alias("_runtime_beta_value"),
        ])
    )

    return (
        df.with_columns(pl.col("asset_rollup").cast(pl.Utf8, strict=False).str.strip_chars().str.to_uppercase().alias("asset_rollup"))
        .join(asset_cfg, on="asset_rollup", how="left")
        .join(filtered, on=["asset_rollup", "home_index"], how="left")
        .with_columns(
            [
                pl.col("home_index").map_elements(
                    lambda v: float(global_shift_pct + shift_map.get(str(v or "").strip().upper(), 0.0)),
                    return_dtype=pl.Float64,
                ).alias("_runtime_shift_pct"),
                pl.col("beta_mode").map_elements(
                    _parse_beta_mode_override,
                    return_dtype=pl.Float64,
                ).alias("_runtime_beta_override"),
            ]
        )
        .with_columns(
            pl.when(pl.col("_runtime_beta_override").is_not_null())
            .then(pl.col("_runtime_beta_override"))
            .otherwise(pl.col("_runtime_beta_value"))
            .alias("_runtime_effective_beta")
        )
        .with_columns(
            pl.when(
                pl.col("_runtime_effective_beta").is_not_null()
                & pl.col("_runtime_shift_pct").is_not_null()
                & (pl.col("_runtime_shift_pct") != 0.0)
            )
            .then(
                pl.col(price_col)
                * (1.0 + ((pl.col("_runtime_effective_beta") * pl.col("_runtime_shift_pct")) / 100.0))
            )
            .otherwise(pl.col(price_col))
            .alias(price_col)
        )
        .drop("_runtime_beta_value", "_runtime_shift_pct", "_runtime_beta_override", "_runtime_effective_beta", "home_index", "beta_mode")
    )

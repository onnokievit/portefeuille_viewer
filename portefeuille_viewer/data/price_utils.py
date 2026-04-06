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
    shift_pct = float(getattr(SNAPSHOT_STORE, "runtime_price_shift_pct", 0.0) or 0.0)
    driver = str(getattr(SNAPSHOT_STORE, "runtime_price_shift_driver", "") or "").strip().upper()
    lookback = str(getattr(SNAPSHOT_STORE, "runtime_price_shift_lookback", "12m") or "12m").strip().lower()
    if abs(shift_pct) < 1e-12 or not driver:
        return df
    beta_df = getattr(SNAPSHOT_STORE, "repository_snapshot_asset_driver_beta", None)
    if beta_df is None or beta_df.is_empty():
        return df
    filtered = beta_df.filter(
        (pl.col("driver_index") == driver)
        & (pl.col("lookback_code").str.to_lowercase() == lookback)
    )
    if filtered.is_empty():
        return df
    filtered = filtered.select(["asset_rollup", "beta_value"]).rename({"beta_value": "_runtime_beta_value"})
    return (
        df.join(filtered, on="asset_rollup", how="left")
        .with_columns(
            pl.when(pl.col("_runtime_beta_value").is_not_null())
            .then(pl.col(price_col) * (1.0 + ((pl.col("_runtime_beta_value") * shift_pct) / 100.0)))
            .otherwise(pl.col(price_col))
            .alias(price_col)
        )
        .drop("_runtime_beta_value")
    )

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl


def chain_path(parquet_dir: str | Path, asset_rollup: str) -> Path:
    return Path(parquet_dir) / f"CHAIN_{asset_rollup.upper()}.parquet"


def load_chain(parquet_dir: str | Path, asset_rollup: str) -> pl.DataFrame:
    path = chain_path(parquet_dir, asset_rollup)
    if not path.exists():
        raise FileNotFoundError(f"Chain parquet niet gevonden: {path}")
    df = pl.read_parquet(path)
    required = {"conid", "asset_rollup", "ib_symbol", "ib_currency", "sec_type", "exchange", "expiry", "right", "strike"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"{path.name} mist kolommen: {sorted(missing)}")
    return normalize_chain(df)


def normalize_chain(df: pl.DataFrame) -> pl.DataFrame:
    out = df
    if out.schema.get("expiry") != pl.Date:
        out = out.with_columns(pl.col("expiry").cast(pl.Date, strict=False))
    today = date.today()
    out = out.with_columns(
        [
            pl.col("conid").cast(pl.Int64, strict=False),
            pl.col("strike").cast(pl.Float64, strict=False),
            pl.col("right").cast(pl.Utf8).str.to_uppercase(),
            (pl.col("expiry") - pl.lit(today)).dt.total_days().alias("dte"),
        ]
    )
    return out.filter((pl.col("conid") > 0) & pl.col("expiry").is_not_null())


def chain_summary(df: pl.DataFrame) -> dict[str, object]:
    if df.is_empty():
        return {"rows": 0}
    out: dict[str, object] = {"rows": df.height}
    for col in ("expiry", "right", "strike", "trading_class", "multiplier"):
        if col in df.columns:
            out[f"{col}_unique"] = df.select(pl.col(col).n_unique()).item()
    out["dte_min"] = df.select(pl.col("dte").min()).item()
    out["dte_max"] = df.select(pl.col("dte").max()).item()
    return out

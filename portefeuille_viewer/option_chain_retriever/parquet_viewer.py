from __future__ import annotations

from pathlib import Path

import polars as pl


def load_preview(path: str | Path, limit: int = 1000) -> tuple[pl.DataFrame, dict[str, object]]:
    p = Path(path)
    if not p.exists():
        return pl.DataFrame(), {"rows": 0, "error": "bestand bestaat niet"}
    df = pl.read_parquet(p)
    summary: dict[str, object] = {"rows": df.height, "columns": len(df.columns)}
    for col in ("expiry", "right", "strike", "trading_class", "multiplier"):
        if col in df.columns:
            summary[f"{col}_unique"] = df.select(pl.col(col).n_unique()).item()
    if "last_seen_at" in df.columns and df.height:
        summary["last_seen_at_max"] = df.select(pl.col("last_seen_at").max()).item()
    return df.head(limit), summary


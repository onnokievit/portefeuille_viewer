from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import polars as pl

from iv_models import SnapshotPaths


def snapshot_paths(parquet_dir: str | Path, asset_rollup: str, snapshot_ts: datetime | None = None) -> SnapshotPaths:
    stamp = (snapshot_ts or datetime.now()).strftime("%Y%m%d_%H%M%S")
    asset = asset_rollup.upper()
    root = Path(parquet_dir) / "option_market_snapshots" / f"asset_rollup={asset}" / f"date={stamp[:8]}"
    latest_dir = Path(parquet_dir) / "option_market_latest"
    return SnapshotPaths(
        root_dir=root,
        snapshot_path=root / f"IV_{asset}_{stamp}.parquet",
        latest_path=latest_dir / f"LATEST_{asset}.parquet",
    )


def write_snapshot(df: pl.DataFrame, parquet_dir: str | Path, asset_rollup: str) -> SnapshotPaths:
    paths = snapshot_paths(parquet_dir, asset_rollup)
    paths.root_dir.mkdir(parents=True, exist_ok=True)
    paths.latest_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(df, paths.snapshot_path)
    _atomic_write(df, paths.latest_path)
    return paths


def load_latest(parquet_dir: str | Path, asset_rollup: str) -> pl.DataFrame:
    path = Path(parquet_dir) / "option_market_latest" / f"LATEST_{asset_rollup.upper()}.parquet"
    if not path.exists():
        return pl.DataFrame()
    return pl.read_parquet(path)


def _atomic_write(df: pl.DataFrame, path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp")
    df.write_parquet(tmp)
    os.replace(tmp, path)

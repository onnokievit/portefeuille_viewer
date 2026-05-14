from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

import polars as pl


def chain_path(parquet_dir: Path, asset_rollup: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in asset_rollup.strip().upper())
    return parquet_dir / f"CHAIN_{safe}.parquet"


def merge_and_write_chain(parquet_dir: Path, asset_rollup: str, new_rows: list[dict]) -> tuple[Path, int, int, int]:
    parquet_dir.mkdir(parents=True, exist_ok=True)
    path = chain_path(parquet_dir, asset_rollup)
    existing_rows: list[dict] = []
    if path.exists():
        existing_rows = pl.read_parquet(path).to_dicts()

    existing_by_conid: dict[int, dict] = {}
    for row in existing_rows:
        try:
            conid = int(row.get("conid") or 0)
        except Exception:
            conid = 0
        if conid > 0:
            existing_by_conid[conid] = row

    inserted = 0
    updated = 0
    for row in new_rows:
        conid = int(row.get("conid") or 0)
        if conid <= 0:
            continue
        current = existing_by_conid.get(conid)
        if current is None:
            inserted += 1
            existing_by_conid[conid] = row
            continue
        first_seen = current.get("first_seen_at") or row.get("first_seen_at")
        merged = dict(current)
        merged.update(row)
        merged["first_seen_at"] = first_seen
        existing_by_conid[conid] = merged
        updated += 1

    combined = list(existing_by_conid.values())
    if combined:
        df = pl.DataFrame(combined, infer_schema_length=None)
        if "conid" in df.columns:
            df = df.sort(["expiry", "right", "strike", "local_symbol"], nulls_last=True)
    else:
        df = pl.DataFrame()

    _atomic_write_parquet(df, path)
    return path, inserted, updated, len(combined)


def read_chain(path: Path) -> pl.DataFrame:
    if not path.exists():
        return pl.DataFrame()
    return pl.read_parquet(path)


def chain_summary(path: Path) -> dict[str, object]:
    df = read_chain(path)
    if df.is_empty():
        return {"rows": 0}
    out: dict[str, object] = {"rows": df.height}
    for col in ("expiry", "strike", "right", "trading_class", "multiplier"):
        if col in df.columns:
            out[f"{col}_count"] = df.select(pl.col(col).n_unique()).item()
    if "last_seen_at" in df.columns:
        with pl.Config():
            out["last_seen_at_max"] = df.select(pl.col("last_seen_at").max()).item()
    return out


def _atomic_write_parquet(df: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".tmp.parquet", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        df.write_parquet(tmp_path)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


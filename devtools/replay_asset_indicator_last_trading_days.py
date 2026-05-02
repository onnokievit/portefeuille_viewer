from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import polars as pl


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portefeuille_viewer.data import repository  # noqa: E402
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE  # noqa: E402
from portefeuille_viewer.services.asset_indicator_service import AssetIndicatorService  # noqa: E402


def main() -> int:
    args = parse_args()
    print("Loading source snapshots...")
    assets_df = repository.load_asset_rollup_data()
    close_df = repository.load_historical_close_snapshot()
    ohlcv_df = getattr(SNAPSHOT_STORE, "repository_snapshot_historical_ohlcv", None)
    print(f"asset_rollup_data rows={assets_df.height if isinstance(assets_df, pl.DataFrame) else 0}")
    print(f"historical_close rows={close_df.height if isinstance(close_df, pl.DataFrame) else 0}")
    print(f"historical_ohlcv rows={ohlcv_df.height if isinstance(ohlcv_df, pl.DataFrame) else 0}")

    cutoff_dates = latest_trading_days(ohlcv_df, args.days)
    print("cutoff_dates=" + ", ".join(d.isoformat() for d in cutoff_dates))
    if not cutoff_dates:
        print("No cutoff dates found.")
        return 1

    if not args.apply:
        print("dry_run=1")
        print("Gebruik --apply om replay-records naar de stock-db te upserten.")
        return 0

    service = AssetIndicatorService()
    total_scored = 0
    total_assets = 0
    for cutoff in cutoff_dates:
        result = service.rebuild(
            cutoff_date=cutoff,
            publish_snapshots=False,
            persist_history=True,
            include_live_theta=False,
        )
        print(
            f"{cutoff.isoformat()} status={result.status} assets={result.assets_total} "
            f"scored={result.assets_scored} insufficient={result.assets_insufficient_data} "
            f"duration_ms={result.duration_ms:.0f}"
        )
        if result.status != "ok":
            print(f"error={result.error}")
            return 1
        total_assets += result.assets_total
        total_scored += result.assets_scored
    print("dry_run=0")
    print(f"cutoff_days_replayed={len(cutoff_dates)}")
    print(f"asset_rows_processed={total_assets}")
    print(f"asset_rows_scored={total_scored}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay asset indicator voor de laatste N handelsdagen.")
    parser.add_argument("--days", type=int, default=10, help="Aantal laatste handelsdagen.")
    parser.add_argument("--apply", action="store_true", help="Schrijf replay-records naar de stock-db.")
    return parser.parse_args()


def latest_trading_days(df: pl.DataFrame | None, n_days: int) -> list[date]:
    if df is None or df.is_empty() or "datum" not in df.columns:
        return []
    today = date.today()
    dates = (
        df.select(pl.col("datum").cast(pl.Date, strict=False).alias("datum"))
        .filter(pl.col("datum").is_not_null() & (pl.col("datum") < today))
        .unique()
        .sort("datum", descending=True)
        .head(max(1, int(n_days)))
        .get_column("datum")
        .to_list()
    )
    return sorted([d for d in dates if isinstance(d, date)])


if __name__ == "__main__":
    raise SystemExit(main())

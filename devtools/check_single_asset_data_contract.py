from __future__ import annotations

import sys
from typing import Iterable

import polars as pl

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portefeuille_viewer.data import repository
from portefeuille_viewer.data.live_aggregator_aandelen import LiveAggregatorAandelen
from portefeuille_viewer.data.live_aggregator_opties import LiveAggregatorOpties
from portefeuille_viewer.data.live_aggregator_sprinters import LiveAggregatorSprinters
from portefeuille_viewer.projections.aandelen_projection_v2 import AandelenProjectionV2
from portefeuille_viewer.services.aandelen_tab_summary import build_aandelen_tab_summary


NUMERIC_DTYPES = {
    pl.Float64,
    pl.Float32,
    pl.Int64,
    pl.Int32,
    pl.Int16,
    pl.Int8,
    pl.UInt64,
    pl.UInt32,
    pl.UInt16,
    pl.UInt8,
}

CONTRACT = {
    "asset_rollup": "string",
    "koers": "numeric",
    "koers_prev": "numeric",
    "pct_change": "numeric",
    "net_change": "numeric",
    "portfolio_total_waarde_lineair_pct": "numeric",
    "portfolio_total_waarde_delta_pct": "numeric",
}


def hydrate_snapshots() -> None:
    repository.load_alle_transacties()
    repository.load_aandelen_from_tx()
    repository.load_open_opties_from_tx()
    repository.load_gesloten_opties_from_tx()
    repository.load_gesloten_opties_no_broker()
    repository.load_open_sprinters_from_tx()
    repository.load_gesloten_sprinters_from_tx()
    repository.load_asset_rollup_data()
    repository.load_sprinter_referentie_data()
    repository.load_dividend_data()
    repository.load_historical_ohlcv_snapshot()
    repository.load_per_dag_asset_result_v2_snapshot()
    repository.load_optie_referentie_data()
    repository.build_repository_active_asset_rollup_data()
    LiveAggregatorAandelen().process_live_update()
    LiveAggregatorOpties().process_live_update()
    LiveAggregatorSprinters().process_live_update()
    repository.portfolio_value_asset_rollup_opties_put()
    repository.portfolio_value_asset_rollup_aandelen()
    repository.portfolio_value_asset_rollup_sprinters()
    repository.portfolio_value_asset_rollup_combined()


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")


def _ok(msg: str) -> None:
    print(f"PASS: {msg}")


def _validate_contract(df: pl.DataFrame, label: str) -> list[str]:
    errors: list[str] = []
    missing = [c for c in CONTRACT.keys() if c not in df.columns]
    if missing:
        errors.append(f"{label}: missing columns -> {missing}")
        return errors

    for col, expected in CONTRACT.items():
        dtype = df.schema.get(col)
        if expected == "string":
            if dtype != pl.Utf8:
                errors.append(f"{label}: {col} dtype={dtype} expected=String")
            continue
        if expected == "numeric":
            if dtype not in NUMERIC_DTYPES:
                errors.append(f"{label}: {col} dtype={dtype} expected=Numeric")

    if "asset_rollup" in df.columns:
        null_count = int(df.select(pl.col("asset_rollup").is_null().sum()).item())
        if null_count > 0:
            errors.append(f"{label}: asset_rollup has {null_count} null rows")
    return errors


def _print_shape(name: str, df: pl.DataFrame) -> None:
    print(f"{name}: rows={df.height} cols={len(df.columns)}")


def _overlap_stats(classic: pl.DataFrame, projection: pl.DataFrame) -> str:
    c_assets = set(classic.get_column("asset_rollup").cast(pl.Utf8).to_list())
    p_assets = set(projection.get_column("asset_rollup").cast(pl.Utf8).to_list())
    common = len(c_assets & p_assets)
    return (
        f"classic_assets={len(c_assets)} projection_assets={len(p_assets)} "
        f"overlap={common}"
    )


def _emit_errors(errors: Iterable[str]) -> int:
    errs = list(errors)
    if not errs:
        _ok("single-asset data contract validated")
        return 0
    for err in errs:
        _fail(err)
    return 1


def main() -> int:
    hydrate_snapshots()
    classic = build_aandelen_tab_summary()
    proj = AandelenProjectionV2()
    proj.recompute(set())
    projection = proj.snapshot()

    _print_shape("classic_summary", classic)
    _print_shape("projection_v2", projection)

    errors: list[str] = []
    errors.extend(_validate_contract(classic, "classic_summary"))
    errors.extend(_validate_contract(projection, "projection_v2"))

    if not errors:
        _ok(_overlap_stats(classic, projection))

    return _emit_errors(errors)


if __name__ == "__main__":
    raise SystemExit(main())

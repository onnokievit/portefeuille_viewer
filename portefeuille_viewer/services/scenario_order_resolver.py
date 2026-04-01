import polars as pl

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.test_order_repository import (
    BASE_POSITION_UNIEK_ID_COL,
    CHANGE_KIND_COL,
    PARENT_CHANGE_UID_COL,
    SCENARIO_ORDER_UID_COL,
    SOURCE_BUCKET_COL,
    SOURCE_TYPE_COL,
    ensure_default_test_order_scenario,
    get_cached_test_order_scenario_content_map,
    load_test_order_scenarios_cache_from_db,
    load_test_orders_cache_from_db,
)


SCENARIO_RESOLVED_COLS = [
    "scenario_id",
    "scenario_name",
    "enabled",
    "execution_family",
    "expected_outcome",
    "override_price",
    "override_amount",
    "Id",
    SCENARIO_ORDER_UID_COL,
    SOURCE_BUCKET_COL,
    SOURCE_TYPE_COL,
    BASE_POSITION_UNIEK_ID_COL,
    PARENT_CHANGE_UID_COL,
    CHANGE_KIND_COL,
    "broker",
    "asset_rollup",
    "asset_type",
    "transactie_type",
    "transactie_aantal",
    "transactie_prijs",
    "optie_call_put",
    "optie_strike",
    "optie_exp_date",
    "create_date",
    "include",
]


def _empty_resolved_orders_df() -> pl.DataFrame:
    return pl.DataFrame({col: [] for col in SCENARIO_RESOLVED_COLS})


def _ensure_caches_loaded() -> None:
    if not getattr(SNAPSHOT_STORE, "repository_snapshot_test_orders_cache", None):
        load_test_orders_cache_from_db()
    if getattr(SNAPSHOT_STORE, "repository_snapshot_test_order_scenarios", None) is None:
        load_test_order_scenarios_cache_from_db()


def _resolve_scenario_id(scenario_id: int | None = None) -> int:
    _ensure_caches_loaded()
    if scenario_id is not None:
        return int(scenario_id)
    runtime_id = getattr(SNAPSHOT_STORE, "runtime_active_test_order_scenario_id", None)
    if runtime_id is not None:
        return int(runtime_id)
    resolved = ensure_default_test_order_scenario()
    SNAPSHOT_STORE.runtime_active_test_order_scenario_id = int(resolved)
    return int(resolved)


def _get_scenario_name(scenario_id: int) -> str:
    scenarios_df = getattr(SNAPSHOT_STORE, "repository_snapshot_test_order_scenarios", None)
    if scenarios_df is None or scenarios_df.is_empty():
        return ""
    match = scenarios_df.filter(pl.col("scenario_id") == int(scenario_id))
    if match.is_empty():
        return ""
    return str(match["scenario_name"][0] or "")


def resolve_active_scenario_orders_df(
    scenario_id: int | None = None,
    *,
    asset_rollup: str | None = None,
) -> pl.DataFrame:
    resolved_scenario_id = _resolve_scenario_id(scenario_id)
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_orders_cache", {}) or {}
    if not cache:
        return _empty_resolved_orders_df()

    if asset_rollup:
        frames = [cache.get(asset_rollup)]
    else:
        frames = list(cache.values())
    frames = [frame for frame in frames if frame is not None and not frame.is_empty()]
    if not frames:
        return _empty_resolved_orders_df()

    orders_df = pl.concat(frames, how="diagonal_relaxed") if len(frames) > 1 else frames[0]
    if orders_df.is_empty() or SCENARIO_ORDER_UID_COL not in orders_df.columns:
        return _empty_resolved_orders_df()

    content_map = get_cached_test_order_scenario_content_map(resolved_scenario_id)
    if not content_map:
        return _empty_resolved_orders_df()

    scenario_name = _get_scenario_name(resolved_scenario_id)
    enabled_df = pl.DataFrame(
        [
            {
                SCENARIO_ORDER_UID_COL: str(uid or "").strip(),
                "enabled": int(row.get("enabled") or 0),
                "execution_family": row.get("execution_family"),
                "expected_outcome": row.get("expected_outcome"),
                "override_price": row.get("override_price"),
                "override_amount": row.get("override_amount"),
            }
            for uid, row in content_map.items()
            if str(uid or "").strip() and int(row.get("enabled") or 0) == 1
        ]
    )
    if enabled_df.is_empty():
        return _empty_resolved_orders_df()

    joined = orders_df.join(enabled_df, on=SCENARIO_ORDER_UID_COL, how="inner")
    if joined.is_empty():
        return _empty_resolved_orders_df()

    joined = joined.with_columns(
        [
            pl.lit(int(resolved_scenario_id)).alias("scenario_id"),
            pl.lit(scenario_name).alias("scenario_name"),
            pl.lit(1).alias("include"),
        ]
    )

    missing_cols = [col for col in SCENARIO_RESOLVED_COLS if col not in joined.columns]
    if missing_cols:
        joined = joined.with_columns([pl.lit(None).alias(col) for col in missing_cols])
    return joined.select(SCENARIO_RESOLVED_COLS)


def resolve_active_scenario_orders_by_asset(
    scenario_id: int | None = None,
) -> dict[str, pl.DataFrame]:
    resolved_df = resolve_active_scenario_orders_df(scenario_id=scenario_id)
    if resolved_df.is_empty() or "asset_rollup" not in resolved_df.columns:
        return {}
    out: dict[str, pl.DataFrame] = {}
    for asset in resolved_df["asset_rollup"].unique().to_list():
        if asset is None:
            continue
        asset_key = str(asset)
        out[asset_key] = resolved_df.filter(pl.col("asset_rollup") == asset_key)
    return out


def refresh_active_scenario_orders_snapshot(
    scenario_id: int | None = None,
) -> pl.DataFrame:
    resolved_scenario_id = _resolve_scenario_id(scenario_id)
    resolved_df = resolve_active_scenario_orders_df(scenario_id=resolved_scenario_id)
    SNAPSHOT_STORE.runtime_active_test_order_scenario_id = int(resolved_scenario_id)
    SNAPSHOT_STORE.repository_snapshot_active_scenario_orders_flat = resolved_df
    SNAPSHOT_STORE.repository_snapshot_active_scenario_orders_by_asset = (
        resolve_active_scenario_orders_by_asset(scenario_id=resolved_scenario_id)
        if not resolved_df.is_empty()
        else {}
    )
    return resolved_df

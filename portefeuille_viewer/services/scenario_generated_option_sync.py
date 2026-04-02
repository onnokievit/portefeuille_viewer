import math
import uuid
from datetime import datetime

import polars as pl

from portefeuille_viewer.data import repository
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.test_order_repository import (
    BASE_POSITION_UNIEK_ID_COL,
    CHANGE_KIND_COL,
    PARENT_CHANGE_UID_COL,
    SCENARIO_ORDER_UID_COL,
    SOURCE_BUCKET_COL,
    SOURCE_TYPE_COL,
    flush_dirty_test_orders_to_db,
    get_cached_orders,
    get_test_orders,
    load_test_orders_cache_from_db,
    set_cached_orders_for_asset,
)


BUCKET_2 = "bucket_2"
BUCKET_3 = "bucket_3"
CHANGE_KIND_MARKET_CLOSE = "market_close"
CHANGE_KIND_OPTION_EOM = "option_eom"
SOURCE_TYPE_OPEN_POSITION = "open_position"
SOURCE_TYPE_OPTION_EOM_CHILD = "option_eom_child"


def mark_bucket23_out_of_sync(reason: str | None = None) -> None:
    SNAPSHOT_STORE.runtime_bucket23_out_of_sync = True
    SNAPSHOT_STORE.runtime_bucket23_dirty_reason = str(reason or "").strip() or "base_changed"


def clear_bucket23_out_of_sync() -> None:
    SNAPSHOT_STORE.runtime_bucket23_out_of_sync = False
    SNAPSHOT_STORE.runtime_bucket23_dirty_reason = None


def _as_float(value) -> float | None:
    try:
        result = float(value)
    except Exception:
        return None
    return result if math.isfinite(result) else None


def _open_options_df() -> tuple[pl.DataFrame, str]:
    source_name = "none"
    df_base = getattr(SNAPSHOT_STORE, "repository_snapshot_load_open_opties", None)
    if df_base is None or df_base.is_empty():
        with pl.StringCache():
            try:
                repository.load_open_opties_from_tx()
            except Exception:
                pass
        df_base = getattr(SNAPSHOT_STORE, "repository_snapshot_load_open_opties", None)
        if df_base is not None and not df_base.is_empty():
            source_name = "repository.load_open_opties_from_tx"
    else:
        source_name = "repository_snapshot_load_open_opties"

    if df_base is None or df_base.is_empty():
        return pl.DataFrame(), source_name

    df = df_base.clone()
    df_live = getattr(SNAPSHOT_STORE, "aggregator_snapshot_load_open_opties_from_tx_live", None)
    required_join_cols = {"broker", "asset_rollup", "optie_call_put", "optie_strike", "optie_exp_date", "Koers"}
    if df_live is not None and not df_live.is_empty() and required_join_cols.issubset(set(df_live.columns)):
        live_keys = ["broker", "asset_rollup", "optie_call_put", "optie_strike", "optie_exp_date"]
        df_live_join = (
            df_live.select(live_keys + ["Koers"])
            .with_columns([
                pl.col("broker").cast(pl.Utf8, strict=False),
                pl.col("asset_rollup").cast(pl.Utf8, strict=False),
                pl.col("optie_call_put").cast(pl.Utf8, strict=False),
                pl.col("optie_strike").cast(pl.Float64, strict=False),
                pl.col("optie_exp_date").cast(pl.Date, strict=False),
                pl.col("Koers").cast(pl.Float64, strict=False),
            ])
            .unique(subset=live_keys, keep="last")
        )
        df = (
            df.with_columns([
                pl.col("broker").cast(pl.Utf8, strict=False),
                pl.col("asset_rollup").cast(pl.Utf8, strict=False),
                pl.col("optie_call_put").cast(pl.Utf8, strict=False),
                pl.col("optie_strike").cast(pl.Float64, strict=False),
                pl.col("optie_exp_date").cast(pl.Date, strict=False),
            ])
            .join(df_live_join, on=live_keys, how="left")
        )
        source_name = "repository_snapshot_load_open_opties+live_koers"
    df_option_live = getattr(SNAPSHOT_STORE, "snapshot_optie_timevalue_live", None)
    option_join_cols = {"broker", "asset", "c_p", "strike", "exp", "last_px"}
    if df_option_live is not None and not df_option_live.is_empty() and option_join_cols.issubset(set(df_option_live.columns)):
        option_keys = ["broker", "asset_rollup", "optie_call_put", "optie_strike", "optie_exp_date"]
        df_option_join = (
            df_option_live.select(["broker", "asset", "c_p", "strike", "exp", "last_px"])
            .rename({
                "asset": "asset_rollup",
                "c_p": "optie_call_put",
                "strike": "optie_strike",
                "exp": "optie_exp_date",
                "last_px": "option_market_price",
            })
            .with_columns([
                pl.col("broker").cast(pl.Utf8, strict=False),
                pl.col("asset_rollup").cast(pl.Utf8, strict=False),
                pl.col("optie_call_put").cast(pl.Utf8, strict=False),
                pl.col("optie_strike").cast(pl.Float64, strict=False),
                pl.col("optie_exp_date").cast(pl.Date, strict=False),
                pl.col("option_market_price").cast(pl.Float64, strict=False),
            ])
            .filter(pl.col("option_market_price").is_not_null() & (pl.col("option_market_price") > 0))
            .unique(subset=option_keys, keep="last")
        )
        df = (
            df.with_columns([
                pl.col("broker").cast(pl.Utf8, strict=False),
                pl.col("asset_rollup").cast(pl.Utf8, strict=False),
                pl.col("optie_call_put").cast(pl.Utf8, strict=False),
                pl.col("optie_strike").cast(pl.Float64, strict=False),
                pl.col("optie_exp_date").cast(pl.Date, strict=False),
            ])
            .join(df_option_join, on=option_keys, how="left")
        )
        source_name = f"{source_name}+option_timevalue_last_px"
    return df, source_name


def _spot_lookup() -> dict[str, float]:
    out: dict[str, float] = {}
    df_live = getattr(SNAPSHOT_STORE, "aggregator_snapshot_load_open_opties_from_tx_live", None)
    if df_live is not None and not df_live.is_empty() and {"asset_rollup", "Koers"}.issubset(set(df_live.columns)):
        for row in df_live.select(["asset_rollup", "Koers"]).to_dicts():
            asset = str(row.get("asset_rollup") or "").strip()
            koers = _as_float(row.get("Koers"))
            if asset and koers is not None and asset not in out:
                out[asset] = koers
    for attr in (
        "repository_snapshot_active_asset_rollup_data",
        "repository_snapshot_asset_rollup_data",
        "repository_snapshot_portfolio_value_total_combined_put",
    ):
        df = getattr(SNAPSHOT_STORE, attr, None)
        if df is None or df.is_empty() or "asset_rollup" not in df.columns or "koers" not in df.columns:
            continue
        for row in df.select(["asset_rollup", "koers"]).to_dicts():
            asset = str(row.get("asset_rollup") or "").strip()
            koers = _as_float(row.get("koers"))
            if asset and koers is not None and asset not in out:
                out[asset] = koers
    hist_df = getattr(SNAPSHOT_STORE, "repository_snapshot_historical_close_latest", None)
    if hist_df is not None and not hist_df.is_empty() and {"asset_rollup", "close_price"}.issubset(set(hist_df.columns)):
        for row in hist_df.select(["asset_rollup", "close_price"]).to_dicts():
            asset = str(row.get("asset_rollup") or "").strip()
            koers = _as_float(row.get("close_price"))
            if asset and koers is not None and asset not in out:
                out[asset] = koers
    return out


def _cache_ready_row(row: dict) -> dict:
    out = dict(row)
    exp = out.get("optie_exp_date")
    if exp is not None and hasattr(exp, "strftime"):
        out["optie_exp_date"] = exp.strftime("%d-%m-%Y")
    elif exp is None:
        out["optie_exp_date"] = None
    else:
        out["optie_exp_date"] = str(exp)
    created = out.get("create_date")
    if created is not None and hasattr(created, "strftime"):
        out["create_date"] = created.strftime("%d-%m-%Y %H:%M:%S")
    elif created is None:
        out["create_date"] = None
    else:
        out["create_date"] = str(created)
    return out


def _existing_generated_rows() -> tuple[dict[str, dict], dict[str, dict]]:
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_orders_cache", {}) or {}
    bucket2: dict[str, dict] = {}
    bucket3: dict[str, dict] = {}
    for df in cache.values():
        if df is None or df.is_empty() or SOURCE_BUCKET_COL not in df.columns:
            continue
        for row in df.to_dicts():
            bucket = str(row.get(SOURCE_BUCKET_COL) or "").strip()
            if bucket == BUCKET_2:
                base_uid = str(row.get(BASE_POSITION_UNIEK_ID_COL) or "").strip()
                if base_uid:
                    bucket2[base_uid] = row
            elif bucket == BUCKET_3:
                parent_uid = str(row.get(PARENT_CHANGE_UID_COL) or "").strip()
                if parent_uid:
                    bucket3[parent_uid] = row
    return bucket2, bucket3


def _is_itm(option_cp: str, strike: float | None, spot: float | None) -> bool:
    if strike is None or spot is None:
        return False
    cp = str(option_cp or "").strip().lower()
    if cp == "call":
        return spot > strike
    if cp == "put":
        return spot < strike
    return False


def _bucket2_transactie_type(position_amount: float) -> str:
    return "koop" if position_amount < 0 else "verkoop"


def _bucket3_transactie_type(position_amount: float, option_cp: str) -> str:
    cp = str(option_cp or "").strip().lower()
    if cp == "call":
        return "koop" if position_amount > 0 else "verkoop"
    return "verkoop" if position_amount > 0 else "koop"


def _normalized_amount(base_amount: float, existing_row: dict | None = None) -> float:
    max_amount = abs(base_amount)
    if existing_row:
        existing_amount = _as_float(existing_row.get("transactie_aantal"))
        if existing_amount is not None and existing_amount > 0:
            return min(existing_amount, max_amount)
    return max_amount


def _bucket2_row_from_open_position(row: dict, existing_row: dict | None = None) -> dict:
    amount_signed = _as_float(row.get("SomVantransactie_aantal")) or 0.0
    price_now = _as_float(row.get("option_market_price"))
    if price_now is None or price_now <= 0:
        price_now = _as_float(existing_row.get("transactie_prijs")) if existing_row else None
    if price_now is None or price_now <= 0:
        price_now = 0.0
    change_kind = str(existing_row.get(CHANGE_KIND_COL) or "").strip() if existing_row else ""
    change_kind = change_kind or CHANGE_KIND_OPTION_EOM
    amount = _normalized_amount(amount_signed, existing_row)
    scenario_uid = str(existing_row.get(SCENARIO_ORDER_UID_COL) or "").strip() if existing_row else ""
    scenario_uid = scenario_uid or str(uuid.uuid4())
    return {
        SCENARIO_ORDER_UID_COL: scenario_uid,
        SOURCE_BUCKET_COL: BUCKET_2,
        SOURCE_TYPE_COL: SOURCE_TYPE_OPEN_POSITION,
        BASE_POSITION_UNIEK_ID_COL: str(row.get("uniek_id") or "").strip(),
        PARENT_CHANGE_UID_COL: None,
        CHANGE_KIND_COL: change_kind,
        "broker": row.get("broker"),
        "asset_rollup": row.get("asset_rollup"),
        "asset_type": "optie",
        "transactie_type": _bucket2_transactie_type(amount_signed),
        "transactie_aantal": amount,
        "transactie_prijs": 0.0 if change_kind == CHANGE_KIND_OPTION_EOM else price_now,
        "optie_call_put": row.get("optie_call_put"),
        "optie_strike": _as_float(row.get("optie_strike")),
        "optie_exp_date": row.get("optie_exp_date"),
        "create_date": datetime.now(),
        "include": 1,
    }


def _bucket3_row_from_bucket2(bucket2_row: dict, spot_lookup: dict[str, float], existing_row: dict | None = None) -> dict | None:
    if str(bucket2_row.get(CHANGE_KIND_COL) or "").strip() != CHANGE_KIND_OPTION_EOM:
        return None
    asset = str(bucket2_row.get("asset_rollup") or "").strip()
    strike = _as_float(bucket2_row.get("optie_strike"))
    spot = spot_lookup.get(asset)
    cp = str(bucket2_row.get("optie_call_put") or "").strip().lower()
    if not _is_itm(cp, strike, spot):
        return None
    amount = abs(_as_float(bucket2_row.get("transactie_aantal")) or 0.0)
    parent_uid = str(bucket2_row.get(SCENARIO_ORDER_UID_COL) or "").strip()
    bucket2_type = str(bucket2_row.get("transactie_type") or "").strip().lower()
    position_amount = -amount if bucket2_type == "koop" else amount
    scenario_uid = str(existing_row.get(SCENARIO_ORDER_UID_COL) or "").strip() if existing_row else ""
    scenario_uid = scenario_uid or str(uuid.uuid4())
    return {
        SCENARIO_ORDER_UID_COL: scenario_uid,
        SOURCE_BUCKET_COL: BUCKET_3,
        SOURCE_TYPE_COL: SOURCE_TYPE_OPTION_EOM_CHILD,
        BASE_POSITION_UNIEK_ID_COL: bucket2_row.get(BASE_POSITION_UNIEK_ID_COL),
        PARENT_CHANGE_UID_COL: parent_uid,
        CHANGE_KIND_COL: CHANGE_KIND_OPTION_EOM,
        "broker": bucket2_row.get("broker"),
        "asset_rollup": bucket2_row.get("asset_rollup"),
        "asset_type": "aandeel",
        "transactie_type": _bucket3_transactie_type(position_amount, cp),
        "transactie_aantal": amount,
        "transactie_prijs": strike,
        "optie_call_put": None,
        "optie_strike": None,
        "optie_exp_date": bucket2_row.get("optie_exp_date"),
        "create_date": datetime.now(),
        "include": 1,
    }


def sync_generated_option_orders() -> dict:
    cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_orders_cache", {}) or {}
    if not cache:
        load_test_orders_cache_from_db()
    df_open, source_name = _open_options_df()
    open_columns = list(df_open.columns) if df_open is not None and not df_open.is_empty() else []
    if df_open.is_empty():
        clear_bucket23_out_of_sync()
        return {
            "source": source_name,
            "open_option_rows": 0,
            "open_option_uid_rows": 0,
            "open_option_columns": open_columns,
            "bucket2_inserted": 0,
            "bucket2_updated": 0,
            "bucket2_deleted": 0,
            "bucket3_inserted": 0,
            "bucket3_updated": 0,
            "bucket3_deleted": 0,
        }

    bucket2_existing, bucket3_existing = _existing_generated_rows()
    base_rows = {
        str(row.get("uniek_id") or "").strip(): row
        for row in df_open.to_dicts()
        if str(row.get("uniek_id") or "").strip()
    }
    spot_lookup = _spot_lookup()
    stats = {
        "source": source_name,
        "open_option_rows": int(df_open.height),
        "open_option_uid_rows": len(base_rows),
        "open_option_columns": open_columns,
        "bucket2_inserted": 0,
        "bucket2_updated": 0,
        "bucket2_deleted": 0,
        "bucket3_inserted": 0,
        "bucket3_updated": 0,
        "bucket3_deleted": 0,
    }
    assets_touched: set[str] = set()
    generated_bucket2_by_asset: dict[str, list[dict]] = {}
    generated_bucket3_by_asset: dict[str, list[dict]] = {}

    for base_uid, open_row in base_rows.items():
        asset = str(open_row.get("asset_rollup") or "").strip()
        if not asset:
            continue
        existing_bucket2 = bucket2_existing.get(base_uid)
        bucket2_row = _bucket2_row_from_open_position(open_row, existing_bucket2)
        generated_bucket2_by_asset.setdefault(asset, []).append(bucket2_row)
        assets_touched.add(asset)
        if existing_bucket2:
            stats["bucket2_updated"] += 1
        else:
            stats["bucket2_inserted"] += 1

        parent_uid = str(bucket2_row.get(SCENARIO_ORDER_UID_COL) or "").strip()
        existing_bucket3 = bucket3_existing.get(parent_uid)
        bucket3_row = _bucket3_row_from_bucket2(bucket2_row, spot_lookup, existing_bucket3)
        if bucket3_row is not None:
            generated_bucket3_by_asset.setdefault(asset, []).append(bucket3_row)
            if existing_bucket3:
                stats["bucket3_updated"] += 1
            else:
                stats["bucket3_inserted"] += 1

    for base_uid, existing in list(bucket2_existing.items()):
        if base_uid in base_rows:
            continue
        asset = str(existing.get("asset_rollup") or "").strip()
        if asset:
            assets_touched.add(asset)
        stats["bucket2_deleted"] += 1
        parent_uid = str(existing.get(SCENARIO_ORDER_UID_COL) or "").strip()
        if parent_uid and parent_uid in bucket3_existing:
            stats["bucket3_deleted"] += 1

    for parent_uid, existing_child in list(bucket3_existing.items()):
        if parent_uid in bucket2_existing:
            parent_row = bucket2_existing.get(parent_uid)
            parent_base_uid = str(parent_row.get(BASE_POSITION_UNIEK_ID_COL) or "").strip() if parent_row else ""
            if parent_base_uid in base_rows:
                asset = str(existing_child.get("asset_rollup") or "").strip()
                desired_children = generated_bucket3_by_asset.get(asset, [])
                desired_parent_uids = {
                    str(row.get(PARENT_CHANGE_UID_COL) or "").strip()
                    for row in desired_children
                }
                if parent_uid not in desired_parent_uids:
                    stats["bucket3_deleted"] += 1

    for asset in assets_touched:
        existing_df = get_cached_orders(asset)
        manual_rows: list[dict] = []
        if existing_df is not None and not existing_df.is_empty():
            if SOURCE_BUCKET_COL in existing_df.columns:
                manual_rows = [
                    row for row in existing_df.to_dicts()
                    if str(row.get(SOURCE_BUCKET_COL) or "").strip() not in {BUCKET_2, BUCKET_3}
                ]
            else:
                manual_rows = existing_df.to_dicts()
        combined_rows = [
            _cache_ready_row(row)
            for row in (manual_rows + generated_bucket2_by_asset.get(asset, []) + generated_bucket3_by_asset.get(asset, []))
        ]
        if combined_rows:
            set_cached_orders_for_asset(asset, pl.from_dicts(combined_rows, strict=False))
        else:
            set_cached_orders_for_asset(asset, pl.DataFrame())

    flush_dirty_test_orders_to_db()
    load_test_orders_cache_from_db()
    clear_bucket23_out_of_sync()
    return stats

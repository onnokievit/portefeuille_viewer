import polars as pl

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.repository import estimate_delta
from portefeuille_viewer.services.scenario_order_resolver import resolve_active_scenario_orders_df


def _empty_df_like_base() -> pl.DataFrame:
    base_df = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_total_combined_put", None)
    if base_df is None:
        return pl.DataFrame({})
    return base_df.clear()


def _norm_asset(value) -> str:
    return str(value or "").strip().upper()


def _to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if "." in text and "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except Exception:
        return 0.0


def _signed_qty(transactie_type, amount) -> float:
    qty = abs(_to_float(amount))
    tt = str(transactie_type or "").strip().lower()
    if tt in {"verkoop", "sell", "short"}:
        return -qty
    return qty


def _price_lookup() -> dict[str, float]:
    prices: dict[str, float] = {}
    base_df = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_total_combined_put", None)
    if base_df is not None and not base_df.is_empty() and "asset_rollup" in base_df.columns and "koers" in base_df.columns:
        for row in base_df.select(["asset_rollup", "koers"]).to_dicts():
            asset = _norm_asset(row.get("asset_rollup"))
            if asset and asset not in prices:
                prices[asset] = _to_float(row.get("koers"))
    hist_df = getattr(SNAPSHOT_STORE, "repository_snapshot_historical_close_latest", None)
    if hist_df is not None and not hist_df.is_empty() and "asset_rollup" in hist_df.columns and "close_price" in hist_df.columns:
        for row in hist_df.select(["asset_rollup", "close_price"]).to_dicts():
            asset = _norm_asset(row.get("asset_rollup"))
            if asset and asset not in prices:
                prices[asset] = _to_float(row.get("close_price"))
    return prices


def _meta_lookup() -> dict[str, dict]:
    meta: dict[str, dict] = {}
    base_df = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_total_combined_put", None)
    if base_df is not None and not base_df.is_empty():
        keep = [c for c in ["asset_rollup", "regio", "sector", "value_grow", "koers"] if c in base_df.columns]
        for row in base_df.select(keep).to_dicts():
            asset = _norm_asset(row.get("asset_rollup"))
            if asset:
                meta[asset] = dict(row)
    assets_df = getattr(SNAPSHOT_STORE, "repository_snapshot_asset_rollup_data", None)
    if assets_df is not None and not assets_df.is_empty():
        keep = [c for c in ["asset_rollup", "regio", "sector", "value_grow"] if c in assets_df.columns]
        for row in assets_df.select(keep).to_dicts():
            asset = _norm_asset(row.get("asset_rollup"))
            if asset:
                meta.setdefault(asset, {}).update({k: v for k, v in row.items() if k != "asset_rollup"})
    return meta


def _base_row_template(asset: str, price_lookup: dict[str, float], meta_lookup: dict[str, dict]) -> dict:
    meta = dict(meta_lookup.get(asset, {}) or {})
    return {
        "asset_rollup": asset,
        "regio": meta.get("regio"),
        "sector": meta.get("sector"),
        "value_grow": meta.get("value_grow"),
        "koers": price_lookup.get(asset, _to_float(meta.get("koers"))),
        "aand_aantal_bezit": 0.0,
        "aand_waarde_bezit": 0.0,
        "opt_waarde_bezit": 0.0,
        "opt_waarde_ITM": 0.0,
        "opt_waarde_bezit_delta": 0.0,
        "opt_aantal_ITM_put": 0.0,
        "opt_aantal_OTM_put": 0.0,
        "opt_aantal_ITM_call": 0.0,
        "opt_aantal_OTM_call": 0.0,
        "aantal_sprinters": 0.0,
        "spr_waarde_bezit": 0.0,
        "total_aantal_lineair": 0.0,
        "total_waarde_lineair": 0.0,
        "total_waarde_delta": 0.0,
        "portfolio_total_waarde_lineair_pct": 0.0,
        "portfolio_total_waarde_delta_pct": 0.0,
    }


def _normalize_numeric_target(target: dict) -> dict:
    numeric_cols = [
        "koers",
        "aand_aantal_bezit",
        "aand_waarde_bezit",
        "opt_waarde_bezit",
        "opt_waarde_ITM",
        "opt_waarde_bezit_delta",
        "opt_aantal_ITM_put",
        "opt_aantal_OTM_put",
        "opt_aantal_ITM_call",
        "opt_aantal_OTM_call",
        "aantal_sprinters",
        "spr_waarde_bezit",
        "total_aantal_lineair",
        "total_waarde_lineair",
        "total_waarde_delta",
        "portfolio_total_waarde_lineair_pct",
        "portfolio_total_waarde_delta_pct",
    ]
    for col in numeric_cols:
        target[col] = _to_float(target.get(col))
    return target


def _apply_order_delta(target: dict, row: dict, spot_price: float) -> None:
    asset_type = str(row.get("asset_type") or "").strip().lower()
    qty = _signed_qty(row.get("transactie_type"), row.get("transactie_aantal"))
    if qty == 0:
        return

    if asset_type == "aandeel":
        target["aand_aantal_bezit"] += qty
        target["aand_waarde_bezit"] += qty * spot_price
        return

    if asset_type != "optie":
        return

    call_put = str(row.get("optie_call_put") or "").strip().lower()
    strike = _to_float(row.get("optie_strike"))
    if call_put not in {"call", "put"}:
        return

    if call_put == "put":
        target["opt_waarde_bezit"] += qty * strike * -1.0
        delta = estimate_delta("put", spot_price, strike) or 0.0
        target["opt_waarde_bezit_delta"] += qty * spot_price * delta
        if strike > spot_price:
            target["opt_aantal_ITM_put"] += qty
            target["opt_waarde_ITM"] += qty * strike * -1.0
        else:
            target["opt_aantal_OTM_put"] += qty
        return

    if strike < spot_price:
        target["opt_aantal_ITM_call"] += qty
    else:
        target["opt_aantal_OTM_call"] += qty


def _recompute_totals(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        return df
    df = df.with_columns([
        (pl.col("aand_aantal_bezit") + (-1 * pl.col("opt_aantal_ITM_put"))).alias("total_aantal_lineair"),
        (pl.col("aand_waarde_bezit") + pl.col("opt_waarde_bezit") + pl.col("spr_waarde_bezit")).alias("total_waarde_lineair"),
        (pl.col("aand_waarde_bezit") + pl.col("opt_waarde_bezit_delta") + pl.col("spr_waarde_bezit")).alias("total_waarde_delta"),
    ])
    total_lineair = float(df["total_waarde_lineair"].sum()) if "total_waarde_lineair" in df.columns else 0.0
    total_delta = float(df["total_waarde_delta"].sum()) if "total_waarde_delta" in df.columns else 0.0
    df = df.with_columns([
        pl.when(pl.lit(total_lineair != 0.0))
        .then(pl.col("total_waarde_lineair") / pl.lit(total_lineair))
        .otherwise(0.0)
        .alias("portfolio_total_waarde_lineair_pct"),
        pl.when(pl.lit(total_delta != 0.0))
        .then(pl.col("total_waarde_delta") / pl.lit(total_delta))
        .otherwise(0.0)
        .alias("portfolio_total_waarde_delta_pct"),
    ])
    return df


def build_portfolio_value_scenario_overlay_df(
    scenario_id: int | None = None,
    *,
    enabled: bool = True,
) -> pl.DataFrame | None:
    base_df = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_total_combined_put", None)
    if base_df is None:
        return None
    if not enabled:
        return None

    active_df = resolve_active_scenario_orders_df(scenario_id=scenario_id)
    if active_df is None or active_df.is_empty():
        return base_df.clone()

    base_rows = [dict(row) for row in base_df.to_dicts()]
    price_lookup = _price_lookup()
    meta_lookup = _meta_lookup()
    by_asset: dict[str, dict] = {}
    for row in base_rows:
        asset = _norm_asset(row.get("asset_rollup"))
        if asset:
            row["asset_rollup"] = asset
            by_asset[asset] = _normalize_numeric_target(row)

    for row in active_df.to_dicts():
        asset = _norm_asset(row.get("asset_rollup"))
        if not asset:
            continue
        if asset not in by_asset:
            by_asset[asset] = _base_row_template(asset, price_lookup, meta_lookup)
        target = by_asset[asset]
        spot_price = _to_float(target.get("koers")) or price_lookup.get(asset, 0.0)
        if spot_price == 0.0:
            continue
        _apply_order_delta(target, row, spot_price)

    out_df = pl.DataFrame(list(by_asset.values())) if by_asset else _empty_df_like_base()
    return _recompute_totals(out_df)


def refresh_portfolio_value_scenario_overlay_snapshot(
    scenario_id: int | None = None,
    *,
    enabled: bool = True,
) -> pl.DataFrame | None:
    SNAPSHOT_STORE.runtime_test_orders_enabled = bool(enabled)
    overlay_df = build_portfolio_value_scenario_overlay_df(scenario_id=scenario_id, enabled=enabled)
    SNAPSHOT_STORE.safe_write("repository_snapshot_portfolio_value_total_combined_scenario", overlay_df)
    return overlay_df

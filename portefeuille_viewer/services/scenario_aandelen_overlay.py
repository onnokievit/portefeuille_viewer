import polars as pl

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.services.aandelen_tab_summary import build_aandelen_tab_summary
from portefeuille_viewer.services.scenario_order_resolver import resolve_active_scenario_orders_df


def _norm_asset(value) -> str:
    return str(value or "").strip().upper()


def _to_float(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _empty_like_base() -> pl.DataFrame:
    base_df = getattr(SNAPSHOT_STORE, "snapshot_aandelen_projection_v2", None)
    if isinstance(base_df, pl.DataFrame):
        return base_df.clear()
    return pl.DataFrame({})


def _base_projection_df() -> pl.DataFrame:
    df = getattr(SNAPSHOT_STORE, "snapshot_aandelen_projection_v2", None)
    if isinstance(df, pl.DataFrame) and not df.is_empty():
        return df.clone()
    return build_aandelen_tab_summary()


def _base_combined_map() -> dict[str, dict]:
    df = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_total_combined_put", None)
    if df is None or df.is_empty() or "asset_rollup" not in df.columns:
        return {}
    out: dict[str, dict] = {}
    for row in df.to_dicts():
        asset = _norm_asset(row.get("asset_rollup"))
        if asset:
            out[asset] = dict(row)
    return out


def _scenario_combined_map() -> dict[str, dict]:
    df = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_total_combined_scenario", None)
    if df is None or df.is_empty() or "asset_rollup" not in df.columns:
        return {}
    out: dict[str, dict] = {}
    for row in df.to_dicts():
        asset = _norm_asset(row.get("asset_rollup"))
        if asset:
            out[asset] = dict(row)
    return out


def _asset_meta_map() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for attr in (
        "repository_snapshot_active_asset_rollup_data",
        "repository_snapshot_asset_rollup_data",
        "repository_snapshot_portfolio_value_total_combined_put",
    ):
        df = getattr(SNAPSHOT_STORE, attr, None)
        if df is None or df.is_empty() or "asset_rollup" not in df.columns:
            continue
        keep = [c for c in ("asset_rollup", "regio", "sector", "value_grow", "status", "koers") if c in df.columns]
        for row in df.select(keep).to_dicts():
            asset = _norm_asset(row.get("asset_rollup"))
            if asset:
                out.setdefault(asset, {}).update({k: v for k, v in row.items() if k != "asset_rollup"})
    return out


def _option_detail_delta_map() -> dict[str, float]:
    base_df = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_optie_call_put_detailed", None)
    scenario_df = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_optie_call_put_detailed_scenario", None)

    def _sum_by_asset(df: pl.DataFrame | None) -> dict[str, float]:
        if df is None or df.is_empty() or "asset_rollup" not in df.columns or "waarde_bezit_delta" not in df.columns:
            return {}
        out: dict[str, float] = {}
        for row in (
            df.select(
                [
                    pl.col("asset_rollup").cast(pl.Utf8, strict=False).alias("asset_rollup"),
                    pl.col("waarde_bezit_delta").cast(pl.Float64, strict=False).fill_null(0.0).alias("waarde_bezit_delta"),
                ]
            )
            .group_by("asset_rollup")
            .agg(pl.col("waarde_bezit_delta").sum().alias("waarde_bezit_delta"))
            .to_dicts()
        ):
            asset = _norm_asset(row.get("asset_rollup"))
            if asset:
                out[asset] = _to_float(row.get("waarde_bezit_delta"))
        return out

    base_map = _sum_by_asset(base_df)
    scenario_map = _sum_by_asset(scenario_df)
    assets = set(base_map) | set(scenario_map)
    return {asset: _to_float(scenario_map.get(asset)) - _to_float(base_map.get(asset)) for asset in assets}


def _row_template(base_columns: list[str], asset: str, meta: dict) -> dict:
    row: dict = {}
    numeric_defaults = {
        "koers_prev": 0.0,
        "koers": 0.0,
        "pct_change": 0.0,
        "eq_aantal_bezit": 0.0,
        "open_sp_aantal": 0.0,
        "eq_total_result": 0.0,
        "clos_opt_transactie_euro_totaal": 0.0,
        "clos_sp_transactie_euro_totaal": 0.0,
        "open_opt_total_result": 0.0,
        "open_sp_result": 0.0,
        "div_en_bel": 0.0,
        "totaal_ex_fee": 0.0,
        "totaal_inc_fee": 0.0,
        "net_change": 0.0,
        "totaal_fee": 0.0,
        "portfolio_total_waarde_lineair_pct": 0.0,
        "portfolio_total_waarde_delta_pct": 0.0,
        "optie_tijdswaarde_signed_eur": 0.0,
    }
    for col in base_columns:
        if col == "asset_rollup":
            row[col] = asset
        elif col in ("regio", "sector", "value_grow"):
            row[col] = meta.get(col, "")
        elif col == "status":
            row[col] = meta.get("status", "active")
        else:
            row[col] = numeric_defaults.get(col, "")
    if "asset_rollup" not in row:
        row["asset_rollup"] = asset
    return row


def build_aandelen_scenario_overlay_df(
    scenario_id: int | None = None,
    *,
    enabled: bool = True,
) -> pl.DataFrame | None:
    if not enabled:
        return None

    active_df = resolve_active_scenario_orders_df(scenario_id=scenario_id)
    base_df = _base_projection_df()
    if active_df is None or active_df.is_empty():
        return base_df.clone() if isinstance(base_df, pl.DataFrame) else None

    base_combined = _base_combined_map()
    scenario_combined = _scenario_combined_map()
    meta_map = _asset_meta_map()
    option_delta_map = _option_detail_delta_map()

    rows_by_asset: dict[str, dict] = {}
    base_columns = list(base_df.columns) if isinstance(base_df, pl.DataFrame) and not base_df.is_empty() else []
    if isinstance(base_df, pl.DataFrame) and not base_df.is_empty():
        for row in base_df.to_dicts():
            asset = _norm_asset(row.get("asset_rollup"))
            if asset:
                row["asset_rollup"] = asset
                rows_by_asset[asset] = row

    active_assets = {_norm_asset(v) for v in active_df.get_column("asset_rollup").to_list()} if "asset_rollup" in active_df.columns else set()
    active_assets.discard("")

    for asset in sorted(active_assets):
        row = rows_by_asset.get(asset)
        if row is None:
            row = _row_template(base_columns, asset, meta_map.get(asset, {}))
            rows_by_asset[asset] = row

        scenario_row = scenario_combined.get(asset, {})
        base_row = base_combined.get(asset, {})
        if "koers" in row and scenario_row:
            row["koers"] = _to_float(scenario_row.get("koers"))
        if "regio" in row:
            row["regio"] = meta_map.get(asset, {}).get("regio", row.get("regio"))
        if "sector" in row:
            row["sector"] = meta_map.get(asset, {}).get("sector", row.get("sector"))
        if "value_grow" in row:
            row["value_grow"] = meta_map.get(asset, {}).get("value_grow", row.get("value_grow"))
        if "status" in row:
            row["status"] = "active"
        if "eq_aantal_bezit" in row:
            row["eq_aantal_bezit"] = _to_float(scenario_row.get("aand_aantal_bezit", row.get("eq_aantal_bezit")))
        if "open_sp_aantal" in row:
            row["open_sp_aantal"] = _to_float(scenario_row.get("aantal_sprinters", row.get("open_sp_aantal")))
        if "portfolio_total_waarde_lineair_pct" in row:
            row["portfolio_total_waarde_lineair_pct"] = _to_float(
                scenario_row.get("portfolio_total_waarde_lineair_pct", row.get("portfolio_total_waarde_lineair_pct"))
            )
        if "portfolio_total_waarde_delta_pct" in row:
            row["portfolio_total_waarde_delta_pct"] = _to_float(
                scenario_row.get("portfolio_total_waarde_delta_pct", row.get("portfolio_total_waarde_delta_pct"))
            )
        if "net_change" in row and scenario_row:
            base_lineair = _to_float(base_row.get("total_waarde_lineair"))
            scenario_lineair = _to_float(scenario_row.get("total_waarde_lineair"))
            delta_lineair = scenario_lineair - base_lineair
            row["net_change"] = _to_float(row.get("net_change")) + delta_lineair
        if "totaal_inc_fee" in row and scenario_row:
            base_lineair = _to_float(base_row.get("total_waarde_lineair"))
            scenario_lineair = _to_float(scenario_row.get("total_waarde_lineair"))
            delta_lineair = scenario_lineair - base_lineair
            row["totaal_inc_fee"] = _to_float(row.get("totaal_inc_fee")) + delta_lineair
        if "totaal_ex_fee" in row and scenario_row:
            base_lineair = _to_float(base_row.get("total_waarde_lineair"))
            scenario_lineair = _to_float(scenario_row.get("total_waarde_lineair"))
            delta_lineair = scenario_lineair - base_lineair
            row["totaal_ex_fee"] = _to_float(row.get("totaal_ex_fee")) + delta_lineair
        option_delta = _to_float(option_delta_map.get(asset))
        if abs(option_delta) > 1e-9:
            base_lineair = _to_float(base_row.get("total_waarde_lineair"))
            scenario_lineair = _to_float(scenario_row.get("total_waarde_lineair"))
            delta_lineair = scenario_lineair - base_lineair
            if abs(delta_lineair) < 1e-9:
                if "open_opt_total_result" in row:
                    row["open_opt_total_result"] = _to_float(row.get("open_opt_total_result")) + option_delta
                if "totaal_ex_fee" in row:
                    row["totaal_ex_fee"] = _to_float(row.get("totaal_ex_fee")) + option_delta
                if "totaal_inc_fee" in row:
                    row["totaal_inc_fee"] = _to_float(row.get("totaal_inc_fee")) + option_delta
                if "net_change" in row:
                    row["net_change"] = _to_float(row.get("net_change")) + option_delta

    if not rows_by_asset:
        return _empty_like_base()

    out_df = pl.DataFrame(list(rows_by_asset.values()))
    if base_columns:
        for col in base_columns:
            if col not in out_df.columns:
                out_df = out_df.with_columns(pl.lit(None).alias(col))
        out_df = out_df.select(base_columns)
    return out_df


def refresh_aandelen_scenario_overlay_snapshot(
    scenario_id: int | None = None,
    *,
    enabled: bool = True,
) -> pl.DataFrame | None:
    overlay_df = build_aandelen_scenario_overlay_df(scenario_id=scenario_id, enabled=enabled)
    SNAPSHOT_STORE.safe_write("snapshot_aandelen_projection_v2_scenario", overlay_df)
    return overlay_df

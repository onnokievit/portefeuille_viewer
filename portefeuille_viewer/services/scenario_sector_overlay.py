import polars as pl

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.repository import estimate_delta
from portefeuille_viewer.services.scenario_order_resolver import resolve_active_scenario_orders_df
from portefeuille_viewer.services.scenario_portfolio_value_overlay import (
    _meta_lookup,
    _norm_asset,
    _price_lookup,
    _signed_qty,
    _to_float,
)

CHANGE_KIND_MARKET_CLOSE = "market_close"


def _empty_like(attr_name: str) -> pl.DataFrame:
    base_df = getattr(SNAPSHOT_STORE, attr_name, None)
    if base_df is None:
        return pl.DataFrame({})
    return base_df.clear()


def _synthetic_equity_rows(active_df: pl.DataFrame, price_lookup: dict[str, float], meta_lookup: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    if active_df is None or active_df.is_empty():
        return rows
    for row in active_df.to_dicts():
        if str(row.get("asset_type") or "").strip().lower() != "aandeel":
            continue
        asset = _norm_asset(row.get("asset_rollup"))
        if not asset:
            continue
        qty = _signed_qty(row.get("transactie_type"), row.get("transactie_aantal"))
        if qty == 0:
            continue
        spot = price_lookup.get(asset, 0.0)
        meta = dict(meta_lookup.get(asset, {}) or {})
        rows.append(
            {
                "broker": str(row.get("broker") or "").strip() or None,
                "asset_rollup": asset,
                "regio": meta.get("regio"),
                "sector": meta.get("sector"),
                "value_grow": meta.get("value_grow"),
                "koers": spot,
                "aantal_bezit": qty,
                "waarde_bezit": qty * spot,
            }
        )
    return rows


def _synthetic_option_rows(active_df: pl.DataFrame, price_lookup: dict[str, float], meta_lookup: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    if active_df is None or active_df.is_empty():
        return rows
    for row in active_df.to_dicts():
        if str(row.get("asset_type") or "").strip().lower() != "optie":
            continue
        asset = _norm_asset(row.get("asset_rollup"))
        if not asset:
            continue
        call_put = str(row.get("optie_call_put") or "").strip().lower()
        if call_put not in {"call", "put"}:
            continue
        qty = _signed_qty(row.get("transactie_type"), row.get("transactie_aantal"))
        if qty == 0:
            continue
        spot = price_lookup.get(asset, 0.0)
        strike = _to_float(row.get("optie_strike"))
        transactie_prijs = _to_float(row.get("transactie_prijs"))
        change_kind = str(row.get("change_kind") or "").strip().lower()
        if spot == 0.0 or strike == 0.0:
            continue
        is_itm = strike > spot if call_put == "put" else strike < spot
        if change_kind == CHANGE_KIND_MARKET_CLOSE:
            waarde_bezit = qty * transactie_prijs * -1.0
            waarde_bezit_delta = waarde_bezit
        else:
            waarde_bezit = qty * strike * (-1.0 if call_put == "put" else 1.0)
            delta = estimate_delta(call_put, spot, strike) or 0.0
            waarde_bezit_delta = qty * spot * delta
        meta = dict(meta_lookup.get(asset, {}) or {})
        rows.append(
            {
                "broker": str(row.get("broker") or "").strip() or None,
                "asset_rollup": asset,
                "regio": meta.get("regio"),
                "sector": meta.get("sector"),
                "value_grow": meta.get("value_grow"),
                "Koers": spot,
                "optie_strike": strike,
                "optie_call_put": call_put,
                "waarde_bezit": waarde_bezit,
                "waarde_ITM": waarde_bezit if is_itm else 0.0,
                "waarde_OTM": 0.0 if is_itm else waarde_bezit,
                "waarde_bezit_delta": waarde_bezit_delta,
            }
        )
    return rows


def _synthetic_sprinter_rows(active_df: pl.DataFrame, price_lookup: dict[str, float], meta_lookup: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    if active_df is None or active_df.is_empty():
        return rows
    for row in active_df.to_dicts():
        if str(row.get("asset_type") or "").strip().lower() != "sprinter":
            continue
        asset = _norm_asset(row.get("asset_rollup"))
        if not asset:
            continue
        qty = _signed_qty(row.get("transactie_type"), row.get("transactie_aantal"))
        if qty == 0:
            continue
        unit_value = _to_float(row.get("optie_strike")) or _to_float(row.get("transactie_prijs")) or price_lookup.get(asset, 0.0)
        meta = dict(meta_lookup.get(asset, {}) or {})
        rows.append(
            {
                "asset_rollup": asset,
                "regio": meta.get("regio"),
                "sector": meta.get("sector"),
                "value_grow": meta.get("value_grow"),
                "aantal_sprinters": qty,
                "spr_waarde_bezit": qty * unit_value,
            }
        )
    return rows


def build_sector_scenario_overlay_snapshots(
    scenario_id: int | None = None,
    *,
    enabled: bool = True,
) -> tuple[pl.DataFrame | None, pl.DataFrame | None, pl.DataFrame | None]:
    if not enabled:
        return None, None, None

    active_df = resolve_active_scenario_orders_df(scenario_id=scenario_id)
    if active_df is None or active_df.is_empty():
        return (
            getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_aandelen", None),
            getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_optie_call_put_detailed", None),
            getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_sprinters", None),
        )

    price_lookup = _price_lookup()
    meta_lookup = _meta_lookup()

    base_eq = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_aandelen", None)
    base_opt = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_optie_call_put_detailed", None)
    base_spr = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_sprinters", None)

    eq_rows = _synthetic_equity_rows(active_df, price_lookup, meta_lookup)
    opt_rows = _synthetic_option_rows(active_df, price_lookup, meta_lookup)
    spr_rows = _synthetic_sprinter_rows(active_df, price_lookup, meta_lookup)

    eq_df = base_eq.clone() if base_eq is not None else _empty_like("repository_snapshot_portfolio_value_aandelen")
    if eq_rows:
        eq_df = pl.concat([eq_df, pl.DataFrame(eq_rows)], how="diagonal_relaxed")

    opt_df = base_opt.clone() if base_opt is not None else _empty_like("repository_snapshot_portfolio_value_optie_call_put_detailed")
    if opt_rows:
        opt_df = pl.concat([opt_df, pl.DataFrame(opt_rows)], how="diagonal_relaxed")

    spr_df = base_spr.clone() if base_spr is not None else _empty_like("repository_snapshot_portfolio_value_sprinters")
    if spr_rows:
        spr_df = pl.concat([spr_df, pl.DataFrame(spr_rows)], how="diagonal_relaxed")

    return eq_df, opt_df, spr_df


def refresh_sector_scenario_overlay_snapshots(
    scenario_id: int | None = None,
    *,
    enabled: bool = True,
) -> tuple[pl.DataFrame | None, pl.DataFrame | None, pl.DataFrame | None]:
    eq_df, opt_df, spr_df = build_sector_scenario_overlay_snapshots(scenario_id=scenario_id, enabled=enabled)
    SNAPSHOT_STORE.safe_write("repository_snapshot_portfolio_value_aandelen_scenario", eq_df)
    SNAPSHOT_STORE.safe_write("repository_snapshot_portfolio_value_optie_call_put_detailed_scenario", opt_df)
    SNAPSHOT_STORE.safe_write("repository_snapshot_portfolio_value_sprinters_scenario", spr_df)
    return eq_df, opt_df, spr_df

"""Contract definitions for the asset indicator/advisor pipeline.

This module intentionally contains no runtime service logic. It defines the
stable snapshot columns and action/mode codes that producers and consumers must
share.
"""

from __future__ import annotations

from typing import Final

import polars as pl


SNAPSHOT_ASSET_INDICATOR_LIVE: Final = "snapshot_asset_indicator_live"
SNAPSHOT_ASSET_INDICATOR_SUMMARY: Final = "snapshot_asset_indicator_summary"
SNAPSHOT_ASSET_INDICATOR_META: Final = "snapshot_asset_indicator_meta"


ASSET_INDICATOR_ASSET_MODES: Final[tuple[str, ...]] = (
    "bullish_accumulation",
    "bullish_trend",
    "bullish_pullback",
    "range_theta_candidate",
    "range_theta",
    "bottoming",
    "overextended",
    "bearish_distribution",
    "high_risk_avoid",
    "insufficient_data",
)


ASSET_INDICATOR_PRIMARY_ACTIONS: Final[tuple[str, ...]] = (
    "long_houden",
    "long_uitbreiden_voorzichtig",
    "schrijf_puts",
    "covered_calls_ver_otm",
    "theta_harvest",
    "defensieve_covered_call",
    "alleen_spreads",
    "risico_verlagen",
    "niets_doen",
    "geen_advies_onvoldoende_data",
)


ASSET_INDICATOR_SECONDARY_ACTIONS: Final[tuple[str, ...]] = (
    "geen_call_dichtbij",
    "puts_alleen_bij_pullback",
    "geen_naked_puts",
    "geen_extra_leverage",
    "assignment_risico_controleren",
    "ex_dividend_controleren",
    "roll_candidate_zoeken",
    "wachten_op_stabilisatie",
    "volume_waarschuwt",
    "covered_calls_en_puts_toegestaan",
    "puts_dicht_bij_koers_toegestaan",
    "deeper_otm_put_reduced_position_sizing",
)


ASSET_INDICATOR_DATA_QUALITY_CODES: Final[tuple[str, ...]] = (
    "ok",
    "partial",
    "insufficient",
)


ASSET_INDICATOR_ROLES: Final[tuple[str, ...]] = (
    "dividend_low_beta_anchor",
    "dividend_value",
    "medium_value_theta",
    "high_beta_value",
    "high_beta_speculative",
    "early_investor",
    "volatility_products",
    "ignore",
)


ASSET_INDICATOR_LIVE_SCHEMA: Final[dict[str, pl.DataType]] = {
    "asset_rollup": pl.Utf8,
    "asset_name": pl.Utf8,
    "asset_type": pl.Utf8,
    "risk_class": pl.Utf8,
    "indicator_role": pl.Utf8,
    "as_of": pl.Datetime,
    "direction_score": pl.Float64,
    "long_term_direction_score": pl.Float64,
    "short_term_direction_score": pl.Float64,
    "range_position_pct": pl.Float64,
    "trend_phase": pl.Utf8,
    "realized_volatility_score": pl.Float64,
    "realized_volatility_20d_pct": pl.Float64,
    "realized_volatility_60d_pct": pl.Float64,
    "atr_pct": pl.Float64,
    "choppiness_score": pl.Float64,
    "ibkr_hv_proxy_pct": pl.Float64,
    "ibkr_iv_proxy_pct": pl.Float64,
    "implied_volatility_score": pl.Float64,
    "iv_vs_realized_volatility_score": pl.Float64,
    "theta_opportunity_proxy_score": pl.Float64,
    "theta_score": pl.Float64,
    "volume_score": pl.Float64,
    "vulnerability_score": pl.Float64,
    "liquidity_score": pl.Float64,
    "confidence_score": pl.Float64,
    "asset_mode": pl.Utf8,
    "primary_action": pl.Utf8,
    "secondary_action": pl.Utf8,
    "covered_call_delta_min": pl.Float64,
    "covered_call_delta_max": pl.Float64,
    "short_put_delta_min": pl.Float64,
    "short_put_delta_max": pl.Float64,
    "max_exposure_pct": pl.Float64,
    "current_exposure_pct": pl.Float64,
    "assignment_exposure_pct": pl.Float64,
    "reason_1": pl.Utf8,
    "reason_2": pl.Utf8,
    "reason_3": pl.Utf8,
    "data_quality": pl.Utf8,
}


ASSET_INDICATOR_SUMMARY_SCHEMA: Final[dict[str, pl.DataType]] = {
    "as_of": pl.Datetime,
    "group_type": pl.Utf8,
    "group_key": pl.Utf8,
    "asset_count": pl.Int64,
    "avg_direction_score": pl.Float64,
    "avg_theta_score": pl.Float64,
    "avg_volume_score": pl.Float64,
    "avg_vulnerability_score": pl.Float64,
    "top_assets": pl.Utf8,
}


ASSET_INDICATOR_META_SCHEMA: Final[dict[str, pl.DataType]] = {
    "last_run_id": pl.Utf8,
    "last_run_at": pl.Datetime,
    "last_success_at": pl.Datetime,
    "last_duration_ms": pl.Float64,
    "last_status": pl.Utf8,
    "last_error": pl.Utf8,
    "assets_total": pl.Int64,
    "assets_scored": pl.Int64,
    "assets_insufficient_data": pl.Int64,
    "service_version": pl.Utf8,
}


def empty_asset_indicator_live_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=ASSET_INDICATOR_LIVE_SCHEMA)


def empty_asset_indicator_summary_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=ASSET_INDICATOR_SUMMARY_SCHEMA)


def empty_asset_indicator_meta_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=ASSET_INDICATOR_META_SCHEMA)

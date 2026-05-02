"""Asset indicator snapshot builder.

V1 is intentionally manual and snapshot-only:
- read asset universe from asset_rollup_data snapshot;
- read historical OHLCV from the existing OHLCV snapshot;
- calculate Direction/Volume based rule output;
- publish live/summary/meta snapshots.

No timers, startup wiring, UI integration or database writes live here yet.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from datetime import date, datetime, time
from math import log10, sqrt
from time import perf_counter
from uuid import uuid4

import polars as pl

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.services.asset_indicator_contract import (
    ASSET_INDICATOR_LIVE_SCHEMA,
    ASSET_INDICATOR_META_SCHEMA,
    ASSET_INDICATOR_ROLES,
    ASSET_INDICATOR_SUMMARY_SCHEMA,
    SNAPSHOT_ASSET_INDICATOR_LIVE,
    SNAPSHOT_ASSET_INDICATOR_META,
    SNAPSHOT_ASSET_INDICATOR_SUMMARY,
    empty_asset_indicator_live_frame,
    empty_asset_indicator_meta_frame,
    empty_asset_indicator_summary_frame,
)
from portefeuille_viewer.services.asset_indicator_rules import (
    ActionInput,
    DirectionInput,
    VolumeInput,
    calculate_direction_score,
    calculate_long_term_direction_score,
    calculate_range_position_pct,
    calculate_short_term_direction_score,
    calculate_volume_score,
    classify_trend_phase,
    map_scores_to_action,
)


SERVICE_VERSION = "asset_indicator_v1_snapshot_only"
MIN_HISTORY_ROWS = 60


@dataclass(frozen=True)
class AssetIndicatorRunResult:
    run_id: str
    status: str
    assets_total: int
    assets_scored: int
    assets_insufficient_data: int
    duration_ms: float
    error: str = ""


def rebuild_asset_indicator_snapshots() -> AssetIndicatorRunResult:
    """Build and publish asset indicator snapshots once."""
    return AssetIndicatorService().rebuild()


class AssetIndicatorService:
    def rebuild(
        self,
        *,
        cutoff_date: date | None = None,
        publish_snapshots: bool = True,
        persist_history: bool = True,
        include_live_theta: bool = True,
    ) -> AssetIndicatorRunResult:
        run_id = uuid4().hex
        started_at = datetime.now() if cutoff_date is None else datetime.combine(cutoff_date, time(23, 59, 59))
        t0 = perf_counter()
        try:
            live_df = self._build_live_snapshot(
                started_at,
                cutoff_date=cutoff_date,
                include_live_theta=include_live_theta,
            )
            summary_df = self._build_summary_snapshot(live_df, started_at)
            duration_ms = (perf_counter() - t0) * 1000.0
            meta_df = self._build_meta_snapshot(
                run_id=run_id,
                started_at=started_at,
                duration_ms=duration_ms,
                status="ok",
                error="",
                live_df=live_df,
            )

            if publish_snapshots:
                SNAPSHOT_STORE.safe_write(SNAPSHOT_ASSET_INDICATOR_LIVE, live_df)
                SNAPSHOT_STORE.safe_write(SNAPSHOT_ASSET_INDICATOR_SUMMARY, summary_df)
                SNAPSHOT_STORE.safe_write(SNAPSHOT_ASSET_INDICATOR_META, meta_df)
            if persist_history:
                _persist_signal_history(
                    run_id=run_id,
                    started_at=started_at,
                    duration_ms=duration_ms,
                    status="ok",
                    error="",
                    live_df=live_df,
                )

            return AssetIndicatorRunResult(
                run_id=run_id,
                status="ok",
                assets_total=live_df.height,
                assets_scored=self._count_scored(live_df),
                assets_insufficient_data=self._count_insufficient(live_df),
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (perf_counter() - t0) * 1000.0
            error = f"{type(exc).__name__}: {exc}"
            meta_df = self._build_meta_snapshot(
                run_id=run_id,
                started_at=started_at,
                duration_ms=duration_ms,
                status="error",
                error=error,
                live_df=empty_asset_indicator_live_frame(),
            )
            if publish_snapshots:
                SNAPSHOT_STORE.safe_write(SNAPSHOT_ASSET_INDICATOR_LIVE, empty_asset_indicator_live_frame())
                SNAPSHOT_STORE.safe_write(SNAPSHOT_ASSET_INDICATOR_SUMMARY, empty_asset_indicator_summary_frame())
                SNAPSHOT_STORE.safe_write(SNAPSHOT_ASSET_INDICATOR_META, meta_df)
            print("[asset-indicator] rebuild failed")
            print(traceback.format_exc())
            return AssetIndicatorRunResult(
                run_id=run_id,
                status="error",
                assets_total=0,
                assets_scored=0,
                assets_insufficient_data=0,
                duration_ms=duration_ms,
                error=error,
            )

    def _build_live_snapshot(
        self,
        as_of: datetime,
        *,
        cutoff_date: date | None = None,
        include_live_theta: bool = True,
    ) -> pl.DataFrame:
        assets_df = _normalize_assets_df(getattr(SNAPSHOT_STORE, "repository_snapshot_asset_rollup_data", None))
        if assets_df.is_empty():
            return empty_asset_indicator_live_frame()

        history_df = _normalize_history_df(getattr(SNAPSHOT_STORE, "repository_snapshot_historical_ohlcv", None))
        if cutoff_date is not None and not history_df.is_empty() and "datum" in history_df.columns:
            history_df = history_df.filter(pl.col("datum") <= cutoff_date)
        history_by_asset = _history_by_asset(history_df)
        theta_by_asset = (
            _theta_by_asset(getattr(SNAPSHOT_STORE, "snapshot_optie_timevalue_live", None))
            if include_live_theta
            else {}
        )

        rows: list[dict] = []
        for asset in assets_df.to_dicts():
            asset_rollup = str(asset.get("asset_rollup") or "").strip().upper()
            if not asset_rollup:
                continue
            hist_rows = history_by_asset.get(asset_rollup, [])
            theta_metrics = theta_by_asset.get(asset_rollup, {})
            rows.append(self._build_asset_row(asset, hist_rows, as_of, theta_metrics))

        if not rows:
            return empty_asset_indicator_live_frame()
        return _cast_live_schema(pl.DataFrame(rows))

    def _build_asset_row(
        self,
        asset: dict,
        history_rows: list[dict],
        as_of: datetime,
        theta_metrics: dict,
    ) -> dict:
        asset_rollup = str(asset.get("asset_rollup") or "").strip().upper()
        base = {
            "asset_rollup": asset_rollup,
            "asset_name": _pick_text(asset, ("asset_name", "name", "naam", "ib_symbol"), fallback=asset_rollup),
            "asset_type": _pick_text(asset, ("asset_type", "type"), fallback=""),
            "risk_class": _pick_text(asset, ("risk_class", "value_grow"), fallback=""),
            "indicator_role": _normalize_indicator_role(
                _pick_text(asset, ("indicator_rol", "indicator_role", "indicatorl_rol"), fallback="")
            ),
            "as_of": as_of,
            "input_cutoff_date": _latest_history_date(history_rows),
            "direction_score": None,
            "long_term_direction_score": None,
            "short_term_direction_score": None,
            "range_position_pct": None,
            "trend_phase": "insufficient_data",
            "realized_volatility_score": None,
            "realized_volatility_20d_pct": None,
            "realized_volatility_60d_pct": None,
            "atr_pct": None,
            "choppiness_score": None,
            "ibkr_hv_proxy_pct": None,
            "ibkr_iv_proxy_pct": None,
            "implied_volatility_score": None,
            "iv_vs_realized_volatility_score": None,
            "theta_opportunity_proxy_score": None,
            "theta_score": None,
            "volume_score": None,
            "vulnerability_score": None,
            "liquidity_score": None,
            "confidence_score": 0.0,
            "asset_fase": "insufficient_data",
            "primary_action": "geen_advies_onvoldoende_data",
            "secondary_action": "wachten_op_stabilisatie",
            "covered_call_delta_min": None,
            "covered_call_delta_max": None,
            "short_put_delta_min": None,
            "short_put_delta_max": None,
            "max_exposure_pct": None,
            "current_exposure_pct": None,
            "assignment_exposure_pct": None,
            "reason_1": "Onvoldoende OHLCV-historie",
            "reason_2": "V1 gebruikt minimaal 60 historische datapunten",
            "reason_3": "Wacht op volledige brondata",
            "data_quality": "insufficient",
        }

        if len(history_rows) < MIN_HISTORY_ROWS:
            return base

        features = _calculate_history_features(history_rows)
        direction_input = features["direction_input"]
        long_term_direction_score = calculate_long_term_direction_score(direction_input)
        short_term_direction_score = calculate_short_term_direction_score(direction_input)
        range_position_pct = calculate_range_position_pct(direction_input)
        trend_phase = classify_trend_phase(
            long_term_direction_score=long_term_direction_score,
            short_term_direction_score=short_term_direction_score,
            range_position_pct=range_position_pct,
            data_quality="ok",
        )
        direction_score = calculate_direction_score(direction_input)
        volume_score = calculate_volume_score(features["volume_input"])
        volatility_metrics = features["volatility_metrics"]
        theta_score = _score_theta(theta_metrics)
        ibkr_hv_proxy_pct = _normalize_volatility_pct(
            _first_number(
                volatility_metrics.get("ibkr_hv_proxy_pct"),
            )
        )
        ibkr_iv_proxy_pct = _first_number(
            theta_metrics.get("avg_iv"),
            volatility_metrics.get("ibkr_iv_proxy_pct"),
        )
        ibkr_iv_proxy_pct = _normalize_volatility_pct(ibkr_iv_proxy_pct)
        implied_volatility_score = _score_implied_volatility(ibkr_iv_proxy_pct)
        iv_vs_realized_volatility_score = _score_iv_vs_realized(
            ibkr_iv_proxy_pct,
            volatility_metrics.get("realized_volatility_20d_pct"),
        )
        theta_opportunity_proxy_score = _score_theta_opportunity_proxy(
            implied_volatility_score=implied_volatility_score,
            iv_vs_realized_volatility_score=iv_vs_realized_volatility_score,
            choppiness_score=volatility_metrics.get("choppiness_score"),
            direction_score=direction_score,
        )
        data_quality = "ok" if direction_score is not None and volume_score is not None else "partial"
        if direction_score is None:
            data_quality = "insufficient"
            trend_phase = "insufficient_data"

        decision = map_scores_to_action(
            ActionInput(
                direction_score=direction_score,
                volume_score=volume_score,
                long_term_direction_score=long_term_direction_score,
                short_term_direction_score=short_term_direction_score,
                range_position_pct=range_position_pct,
                trend_phase=trend_phase,
                theta_score=theta_score,
                vulnerability_score=None,
                liquidity_score=None,
                data_quality=data_quality,
                indicator_role=base.get("indicator_role"),
                theta_opportunity_proxy_score=theta_opportunity_proxy_score,
                implied_volatility_score=implied_volatility_score,
                iv_vs_realized_volatility_score=iv_vs_realized_volatility_score,
                choppiness_score=volatility_metrics.get("choppiness_score"),
            )
        )

        base.update(
            {
                "direction_score": direction_score,
                "long_term_direction_score": long_term_direction_score,
                "short_term_direction_score": short_term_direction_score,
                "range_position_pct": range_position_pct,
                "trend_phase": trend_phase,
                "realized_volatility_score": volatility_metrics.get("realized_volatility_score"),
                "realized_volatility_20d_pct": volatility_metrics.get("realized_volatility_20d_pct"),
                "realized_volatility_60d_pct": volatility_metrics.get("realized_volatility_60d_pct"),
                "atr_pct": volatility_metrics.get("atr_pct"),
                "choppiness_score": volatility_metrics.get("choppiness_score"),
                "ibkr_hv_proxy_pct": ibkr_hv_proxy_pct,
                "ibkr_iv_proxy_pct": ibkr_iv_proxy_pct,
                "implied_volatility_score": implied_volatility_score,
                "iv_vs_realized_volatility_score": iv_vs_realized_volatility_score,
                "theta_opportunity_proxy_score": theta_opportunity_proxy_score,
                "theta_score": theta_score,
                "volume_score": volume_score,
                "confidence_score": decision.confidence_score,
                "asset_fase": decision.asset_fase,
                "primary_action": decision.primary_action,
                "secondary_action": decision.secondary_action,
                "covered_call_delta_min": decision.covered_call_delta_min,
                "covered_call_delta_max": decision.covered_call_delta_max,
                "short_put_delta_min": decision.short_put_delta_min,
                "short_put_delta_max": decision.short_put_delta_max,
                "reason_1": decision.reason_1,
                "reason_2": decision.reason_2,
                "reason_3": decision.reason_3,
                "data_quality": data_quality,
            }
        )
        return base

    def _build_summary_snapshot(self, live_df: pl.DataFrame, as_of: datetime) -> pl.DataFrame:
        if live_df is None or live_df.is_empty():
            return empty_asset_indicator_summary_frame()

        summary_rows: list[dict] = []
        for group_col, group_type in (("primary_action", "primary_action"), ("asset_fase", "asset_fase")):
            if group_col not in live_df.columns:
                continue
            grouped = (
                live_df.group_by(group_col)
                .agg(
                    [
                        pl.len().alias("asset_count"),
                        pl.col("direction_score").mean().alias("avg_direction_score"),
                        pl.col("theta_score").mean().alias("avg_theta_score"),
                        pl.col("volume_score").mean().alias("avg_volume_score"),
                        pl.col("vulnerability_score").mean().alias("avg_vulnerability_score"),
                        pl.col("asset_rollup").head(12).str.concat(", ").alias("top_assets"),
                    ]
                )
                .sort("asset_count", descending=True)
            )
            for row in grouped.to_dicts():
                summary_rows.append(
                    {
                        "as_of": as_of,
                        "group_type": group_type,
                        "group_key": row.get(group_col),
                        "asset_count": row.get("asset_count"),
                        "avg_direction_score": row.get("avg_direction_score"),
                        "avg_theta_score": row.get("avg_theta_score"),
                        "avg_volume_score": row.get("avg_volume_score"),
                        "avg_vulnerability_score": row.get("avg_vulnerability_score"),
                        "top_assets": row.get("top_assets"),
                    }
                )

        if not summary_rows:
            return empty_asset_indicator_summary_frame()
        return _cast_summary_schema(pl.DataFrame(summary_rows))

    def _build_meta_snapshot(
        self,
        *,
        run_id: str,
        started_at: datetime,
        duration_ms: float,
        status: str,
        error: str,
        live_df: pl.DataFrame,
    ) -> pl.DataFrame:
        assets_total = 0 if live_df is None else live_df.height
        assets_scored = self._count_scored(live_df)
        assets_insufficient = self._count_insufficient(live_df)
        return _cast_meta_schema(
            pl.DataFrame(
                [
                    {
                        "last_run_id": run_id,
                        "last_run_at": started_at,
                        "last_success_at": started_at if status == "ok" else None,
                        "last_duration_ms": duration_ms,
                        "last_status": status,
                        "last_error": error,
                        "assets_total": assets_total,
                        "assets_scored": assets_scored,
                        "assets_insufficient_data": assets_insufficient,
                        "service_version": SERVICE_VERSION,
                    }
                ]
            )
        )

    @staticmethod
    def _count_scored(df: pl.DataFrame | None) -> int:
        if df is None or df.is_empty() or "data_quality" not in df.columns:
            return 0
        return df.filter(pl.col("data_quality") != "insufficient").height

    @staticmethod
    def _count_insufficient(df: pl.DataFrame | None) -> int:
        if df is None or df.is_empty() or "data_quality" not in df.columns:
            return 0
        return df.filter(pl.col("data_quality") == "insufficient").height


def _normalize_assets_df(df: pl.DataFrame | None) -> pl.DataFrame:
    if df is None or df.is_empty() or "asset_rollup" not in df.columns:
        return pl.DataFrame(schema={"asset_rollup": pl.Utf8})
    out = (
        df.with_columns(
            pl.col("asset_rollup")
            .cast(pl.Utf8, strict=False)
            .str.strip_chars()
            .str.to_uppercase()
            .alias("asset_rollup")
        )
        .filter(pl.col("asset_rollup").is_not_null() & (pl.col("asset_rollup") != ""))
    )
    type_cols = [col for col in ("asset_type", "type") if col in out.columns]
    if type_cols:
        out = out.with_columns(
            pl.coalesce([pl.col(col).cast(pl.Utf8, strict=False) for col in type_cols])
            .str.strip_chars()
            .str.to_lowercase()
            .alias("_indicator_asset_type")
        ).filter(
            pl.col("_indicator_asset_type").is_not_null()
            & (~pl.col("_indicator_asset_type").is_in(["", "index", "future", "futures", "cash"]))
        )
    if "_indicator_asset_type" in out.columns:
        out = out.drop("_indicator_asset_type")
    role_cols = [col for col in ("indicator_rol", "indicator_role", "indicatorl_rol") if col in out.columns]
    if role_cols:
        out = out.with_columns(
            pl.coalesce([pl.col(col).cast(pl.Utf8, strict=False) for col in role_cols])
            .map_elements(_normalize_indicator_role, return_dtype=pl.Utf8)
            .alias("_indicator_role")
        ).filter(pl.col("_indicator_role") != "ignore")
    if "_indicator_role" in out.columns:
        out = out.drop("_indicator_role")
    return out.unique(subset=["asset_rollup"], keep="first").sort("asset_rollup")


def _normalize_history_df(df: pl.DataFrame | None) -> pl.DataFrame:
    if df is None or df.is_empty():
        return pl.DataFrame(
            schema={
                "datum": pl.Date,
                "asset_rollup": pl.Utf8,
                "open_price": pl.Float64,
                "high_price": pl.Float64,
                "low_price": pl.Float64,
                "close_price": pl.Float64,
                "volume_value": pl.Float64,
            }
        )
    required = {"datum", "asset_rollup", "close_price"}
    if not required.issubset(set(df.columns)):
        return pl.DataFrame(schema={"datum": pl.Date, "asset_rollup": pl.Utf8, "close_price": pl.Float64})

    exprs = [
        pl.col("datum").cast(pl.Date, strict=False).alias("datum"),
        pl.col("asset_rollup")
        .cast(pl.Utf8, strict=False)
        .str.strip_chars()
        .str.to_uppercase()
        .alias("asset_rollup"),
        pl.col("close_price").cast(pl.Float64, strict=False).alias("close_price"),
    ]
    for col in (
        "open_price",
        "high_price",
        "low_price",
        "volume_value",
        "historical_volatility",
        "implied_volatility",
        "ibkr_hv_last",
        "ibkr_iv_last",
    ):
        if col in df.columns:
            exprs.append(pl.col(col).cast(pl.Float64, strict=False).alias(col))
        else:
            exprs.append(pl.lit(None).cast(pl.Float64).alias(col))
    return (
        df.with_columns(exprs)
        .filter(
            pl.col("datum").is_not_null()
            & (pl.col("datum") < date.today())
            & pl.col("asset_rollup").is_not_null()
            & (pl.col("asset_rollup") != "")
            & pl.col("close_price").is_not_null()
        )
        .sort(["asset_rollup", "datum"])
    )


def _latest_history_date(history_rows: list[dict]) -> date | None:
    for row in reversed(history_rows or []):
        value = row.get("datum")
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return datetime.fromisoformat(str(value)).date()
        except Exception:
            continue
    return None


def _history_by_asset(df: pl.DataFrame) -> dict[str, list[dict]]:
    if df is None or df.is_empty() or "asset_rollup" not in df.columns:
        return {}
    grouped: dict[str, list[dict]] = {}
    for asset, sub_df in df.partition_by("asset_rollup", as_dict=True).items():
        key = asset[0] if isinstance(asset, tuple) else asset
        grouped[str(key).strip().upper()] = sub_df.sort("datum").to_dicts()
    return grouped


def _theta_by_asset(df: pl.DataFrame | None) -> dict[str, dict]:
    if df is None or df.is_empty() or "asset" not in df.columns:
        return {}
    required = {"asset", "time_total"}
    if not required.issubset(set(df.columns)):
        return {}
    work = df.with_columns(
        [
            pl.col("asset").cast(pl.Utf8, strict=False).str.strip_chars().str.to_uppercase().alias("asset"),
            pl.col("time_total").cast(pl.Float64, strict=False).alias("time_total"),
        ]
    )
    optional_exprs: list[pl.Expr] = []
    for col in ("time_per_unit", "qty_open", "last_px", "und_px", "iv", "delta", "theta"):
        if col in work.columns:
            optional_exprs.append(pl.col(col).cast(pl.Float64, strict=False).alias(col))
        else:
            optional_exprs.append(pl.lit(None).cast(pl.Float64).alias(col))
    work = work.with_columns(optional_exprs)
    grouped = work.group_by("asset").agg(
        [
            pl.col("time_total").abs().sum().alias("time_total_abs"),
            pl.col("time_per_unit").abs().mean().alias("avg_time_per_unit_abs"),
            pl.len().alias("option_rows"),
            pl.col("iv").mean().alias("avg_iv"),
            pl.col("theta").abs().mean().alias("avg_theta_abs"),
        ]
    )
    return {
        str(row.get("asset") or "").strip().upper(): row
        for row in grouped.to_dicts()
        if str(row.get("asset") or "").strip()
    }


def _score_theta(metrics: dict) -> float | None:
    if not metrics:
        return None
    score = 0.0
    time_total_abs = _to_float(metrics.get("time_total_abs")) or 0.0
    avg_time_per_unit_abs = _to_float(metrics.get("avg_time_per_unit_abs")) or 0.0
    avg_iv = _to_float(metrics.get("avg_iv"))
    avg_theta_abs = _to_float(metrics.get("avg_theta_abs")) or 0.0

    if time_total_abs >= 1000.0:
        score += 35.0
    elif time_total_abs >= 500.0:
        score += 25.0
    elif time_total_abs >= 150.0:
        score += 15.0
    elif time_total_abs > 0.0:
        score += 8.0

    if avg_time_per_unit_abs >= 5.0:
        score += 25.0
    elif avg_time_per_unit_abs >= 2.0:
        score += 18.0
    elif avg_time_per_unit_abs >= 0.75:
        score += 10.0
    elif avg_time_per_unit_abs > 0.0:
        score += 5.0

    if avg_iv is not None:
        if avg_iv >= 0.8:
            score += 25.0
        elif avg_iv >= 0.5:
            score += 18.0
        elif avg_iv >= 0.3:
            score += 10.0
        elif avg_iv > 0.0:
            score += 4.0

    if avg_theta_abs >= 1.0:
        score += 15.0
    elif avg_theta_abs >= 0.25:
        score += 10.0
    elif avg_theta_abs > 0.0:
        score += 5.0

    return round(min(score, 100.0), 2)


def _calculate_history_features(history_rows: list[dict]) -> dict:
    closes = [_to_float(row.get("close_price")) for row in history_rows]
    volumes = [_to_float(row.get("volume_value")) for row in history_rows]
    closes = [v for v in closes if v is not None]
    if not closes:
        return {
            "direction_input": DirectionInput(close=None),
            "volume_input": VolumeInput(),
            "volatility_metrics": {},
        }

    close = closes[-1]
    sma_20 = _mean_last(closes, 20)
    sma_50 = _mean_last(closes, 50)
    sma_200 = _mean_last(closes, 200)
    sma_50_prev = _mean_window(closes, end_exclusive=max(len(closes) - 1, 0), window=50)
    ema_9_series = _ema_series(closes, 9)
    ema_26_series = _ema_series(closes, 26)
    ema_50_series = _ema_series(closes, 50)
    ema_200_series = _ema_series(closes, 200)
    ema_9 = ema_9_series[-1] if ema_9_series else None
    ema_26 = ema_26_series[-1] if ema_26_series else None
    ema_50 = ema_50_series[-1] if ema_50_series else None
    ema_200 = ema_200_series[-1] if ema_200_series else None
    ema_9_prev = ema_9_series[-2] if len(ema_9_series) >= 2 else None
    ema_26_prev = ema_26_series[-2] if len(ema_26_series) >= 2 else None
    close_5d_ago = closes[-6] if len(closes) >= 6 else None
    close_20d_ago = closes[-21] if len(closes) >= 21 else None
    close_60d_ago = closes[-61] if len(closes) >= 61 else None
    high_90d = max(closes[-90:]) if closes else None
    low_90d = min(closes[-90:]) if closes else None
    high_52w = max(closes[-252:]) if closes else None
    low_52w = min(closes[-252:]) if closes else None

    price_changes: list[float | None] = []
    relative_volumes: list[float | None] = []
    for offset in (3, 2, 1):
        idx = len(history_rows) - offset
        prev_idx = idx - 1
        if idx <= 0 or idx >= len(history_rows) or prev_idx < 0:
            price_changes.append(None)
            relative_volumes.append(None)
            continue
        curr_close = _to_float(history_rows[idx].get("close_price"))
        prev_close = _to_float(history_rows[prev_idx].get("close_price"))
        curr_volume = _to_float(history_rows[idx].get("volume_value"))
        start = max(0, idx - 20)
        avg_volume_20 = _mean([_to_float(row.get("volume_value")) for row in history_rows[start:idx]])
        price_changes.append(_pct_change(curr_close, prev_close))
        relative_volumes.append(
            curr_volume / avg_volume_20 if curr_volume is not None and avg_volume_20 not in (None, 0.0) else None
        )

    latest_volume = volumes[-1] if volumes and volumes[-1] is not None else None
    avg_volume_20 = _mean([v for v in volumes[-21:-1] if v is not None])
    relative_volume_20d = (
        latest_volume / avg_volume_20 if latest_volume is not None and avg_volume_20 not in (None, 0.0) else None
    )
    latest_price_change = _pct_change(closes[-1], closes[-2] if len(closes) >= 2 else None)
    volume_weighted_price_change = (
        latest_price_change * relative_volume_20d
        if latest_price_change is not None and relative_volume_20d is not None
        else None
    )
    volatility_metrics = _calculate_volatility_metrics(history_rows)

    return {
        "direction_input": DirectionInput(
            close=close,
            sma_20=sma_20,
            sma_50=sma_50,
            sma_200=sma_200,
            sma_50_prev=sma_50_prev,
            ema_9=ema_9,
            ema_26=ema_26,
            ema_50=ema_50,
            ema_200=ema_200,
            ema_9_prev=ema_9_prev,
            ema_26_prev=ema_26_prev,
            close_5d_ago=close_5d_ago,
            close_20d_ago=close_20d_ago,
            close_60d_ago=close_60d_ago,
            high_90d=high_90d,
            low_90d=low_90d,
            high_52w=high_52w,
            low_52w=low_52w,
        ),
        "volume_input": VolumeInput(
            price_changes_3d=tuple(price_changes),  # type: ignore[arg-type]
            relative_volumes_3d=tuple(relative_volumes),  # type: ignore[arg-type]
            relative_volume_20d=relative_volume_20d,
            volume_weighted_price_change=volume_weighted_price_change,
        ),
        "volatility_metrics": volatility_metrics,
    }


def _calculate_volatility_metrics(history_rows: list[dict]) -> dict:
    closes = [_to_float(row.get("close_price")) for row in history_rows]
    highs = [_to_float(row.get("high_price")) for row in history_rows]
    lows = [_to_float(row.get("low_price")) for row in history_rows]

    realized_20 = _realized_volatility_pct(closes, 20)
    realized_60 = _realized_volatility_pct(closes, 60)
    atr_pct = _atr_pct(highs, lows, closes, 14)
    choppiness = _choppiness_score(highs, lows, closes, 14)
    realized_score = _score_realized_volatility(realized_20, realized_60, atr_pct)

    latest = history_rows[-1] if history_rows else {}
    ibkr_iv_proxy_pct = _normalize_volatility_pct(
        _first_number(
            latest.get("ibkr_iv_last"),
            latest.get("implied_volatility"),
        )
    )
    ibkr_hv_proxy_pct = _normalize_volatility_pct(
        _first_number(
            latest.get("ibkr_hv_last"),
            latest.get("historical_volatility"),
        )
    )

    return {
        "realized_volatility_score": realized_score,
        "realized_volatility_20d_pct": realized_20,
        "realized_volatility_60d_pct": realized_60,
        "atr_pct": atr_pct,
        "choppiness_score": choppiness,
        "ibkr_iv_proxy_pct": ibkr_iv_proxy_pct,
        "ibkr_hv_proxy_pct": ibkr_hv_proxy_pct,
    }


def _realized_volatility_pct(closes: list[float | None], window: int) -> float | None:
    clean = [float(v) for v in closes if v is not None and v > 0.0]
    if len(clean) < window + 1:
        return None
    returns: list[float] = []
    for prev, curr in zip(clean[-window - 1 : -1], clean[-window:]):
        if prev > 0.0 and curr > 0.0:
            returns.append(curr / prev - 1.0)
    if len(returns) < max(5, window // 2):
        return None
    stdev = _stddev(returns)
    if stdev is None:
        return None
    return round(stdev * sqrt(252.0) * 100.0, 2)


def _atr_pct(
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    window: int,
) -> float | None:
    rows = [
        (h, l, c)
        for h, l, c in zip(highs, lows, closes)
        if h is not None and l is not None and c is not None and h > 0.0 and l > 0.0 and c > 0.0
    ]
    if len(rows) < window + 1:
        return None
    true_ranges: list[float] = []
    for idx in range(1, len(rows)):
        high, low, _close = rows[idx]
        prev_close = rows[idx - 1][2]
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    recent_tr = true_ranges[-window:]
    latest_close = rows[-1][2]
    if not recent_tr or latest_close == 0.0:
        return None
    return round((sum(recent_tr) / len(recent_tr)) / latest_close * 100.0, 2)


def _choppiness_score(
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    window: int,
) -> float | None:
    rows = [
        (h, l, c)
        for h, l, c in zip(highs, lows, closes)
        if h is not None and l is not None and c is not None and h > 0.0 and l > 0.0 and c > 0.0
    ]
    if len(rows) < window + 1:
        return None
    recent_rows = rows[-window:]
    true_ranges: list[float] = []
    source_rows = rows[-window - 1 :]
    for idx in range(1, len(source_rows)):
        high, low, _close = source_rows[idx]
        prev_close = source_rows[idx - 1][2]
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    high_max = max(row[0] for row in recent_rows)
    low_min = min(row[1] for row in recent_rows)
    range_width = high_max - low_min
    tr_sum = sum(true_ranges[-window:])
    if range_width <= 0.0 or tr_sum <= 0.0 or window <= 1:
        return None
    value = 100.0 * log10(tr_sum / range_width) / log10(float(window))
    return round(_clamp(value, 0.0, 100.0), 2)


def _stddev(values: list[float]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    if len(clean) < 2:
        return None
    mean = sum(clean) / len(clean)
    variance = sum((v - mean) ** 2 for v in clean) / (len(clean) - 1)
    return sqrt(variance)


def _score_realized_volatility(
    realized_20: float | None,
    realized_60: float | None,
    atr_pct: float | None,
) -> float | None:
    values = [v for v in (realized_20, realized_60) if v is not None]
    if not values and atr_pct is None:
        return None
    base = values[0] if values else 0.0
    if realized_20 is not None and realized_60 is not None:
        base = (realized_20 * 0.65) + (realized_60 * 0.35)
    score = _linear_score(base, low=8.0, high=65.0)
    if atr_pct is not None:
        score = (score * 0.75) + (_linear_score(atr_pct, low=0.8, high=7.5) * 0.25)
    return round(_clamp(score, 0.0, 100.0), 2)


def _score_implied_volatility(iv_pct: float | None) -> float | None:
    if iv_pct is None:
        return None
    return round(_linear_score(iv_pct, low=10.0, high=85.0), 2)


def _score_iv_vs_realized(iv_pct: float | None, realized_pct: float | None) -> float | None:
    if iv_pct is None or realized_pct is None:
        return None
    spread = float(iv_pct) - float(realized_pct)
    return round(_linear_score(spread, low=-15.0, high=35.0), 2)


def _score_theta_opportunity_proxy(
    *,
    implied_volatility_score: float | None,
    iv_vs_realized_volatility_score: float | None,
    choppiness_score: float | None,
    direction_score: float | None,
) -> float | None:
    if implied_volatility_score is None and iv_vs_realized_volatility_score is None:
        return None
    score = 0.0
    weight = 0.0
    if implied_volatility_score is not None:
        score += implied_volatility_score * 0.45
        weight += 0.45
    if iv_vs_realized_volatility_score is not None:
        score += iv_vs_realized_volatility_score * 0.35
        weight += 0.35
    if choppiness_score is not None:
        score += choppiness_score * 0.20
        weight += 0.20
    if weight == 0.0:
        return None
    out = score / weight
    if direction_score is not None and float(direction_score) < -60.0:
        out *= 0.75
    return round(_clamp(out, 0.0, 100.0), 2)


def _persist_signal_history(
    *,
    run_id: str,
    started_at: datetime,
    duration_ms: float,
    status: str,
    error: str,
    live_df: pl.DataFrame,
) -> None:
    if live_df is None or live_df.is_empty():
        return
    try:
        from portefeuille_viewer.data import repository

        with repository.get_stockdata_connection() as conn:
            cur = conn.cursor()
            _ensure_signal_history_tables(cur)
            ended_at = datetime.now()
            cur.execute(
                """
                INSERT INTO asset_indicator_service_runs
                    (run_id, started_at, ended_at, status, duration_ms,
                     assets_total, assets_scored, assets_insufficient_data,
                     service_version, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    started_at,
                    ended_at,
                    status,
                    float(duration_ms),
                    int(live_df.height),
                    AssetIndicatorService._count_scored(live_df),
                    AssetIndicatorService._count_insufficient(live_df),
                    SERVICE_VERSION,
                    str(error or "")[:4000],
                ),
            )
            rows = [_history_row_tuple(run_id, row) for row in live_df.to_dicts()]
            if rows:
                _upsert_signal_history_rows(cur, rows)
            conn.commit()
    except Exception as exc:
        print(f"[asset-indicator] signal history persistence skipped: {exc}")


def _ensure_signal_history_tables(cur) -> None:
    try:
        cur.execute(
            """
            CREATE TABLE asset_indicator_service_runs (
                id COUNTER PRIMARY KEY,
                run_id TEXT(40),
                started_at DATETIME,
                ended_at DATETIME,
                status TEXT(32),
                duration_ms DOUBLE,
                assets_total LONG,
                assets_scored LONG,
                assets_insufficient_data LONG,
                service_version TEXT(120),
                error_message MEMO
            )
            """
        )
    except Exception:
        pass
    _ensure_table_column(cur, "asset_indicator_signal_history", "input_cutoff_date", "DATETIME")


def _ensure_table_column(cur, table_name: str, column_name: str, ddl_type: str) -> None:
    try:
        existing = {str(row.column_name).lower() for row in cur.columns(table=table_name)}
    except Exception:
        return
    if column_name.lower() in existing:
        return
    try:
        cur.execute(f"ALTER TABLE [{table_name}] ADD COLUMN [{column_name}] {ddl_type}")
    except Exception:
        pass


def _upsert_signal_history_rows(cur, rows: list[tuple]) -> None:
    insert_columns = [
        "run_id",
        "as_of",
        "input_cutoff_date",
        "asset_rollup",
        "asset_name",
        "indicator_role",
        "trend_phase",
        "asset_fase",
        "primary_action",
        "secondary_action",
        "data_quality",
        "direction_score",
        "long_term_direction_score",
        "short_term_direction_score",
        "range_position_pct",
        "realized_volatility_score",
        "atr_pct",
        "choppiness_score",
        "ibkr_hv_proxy_pct",
        "ibkr_iv_proxy_pct",
        "implied_volatility_score",
        "iv_vs_realized_volatility_score",
        "theta_opportunity_proxy_score",
        "theta_score",
        "volume_score",
        "confidence_score",
        "reason_1",
        "reason_2",
        "reason_3",
        "payload_json",
        "created_at",
    ]
    update_columns = [col for col in insert_columns if col not in {"asset_rollup", "input_cutoff_date"}]
    update_sql = (
        "UPDATE [asset_indicator_signal_history] SET "
        + ", ".join(f"[{col}] = ?" for col in update_columns)
        + " WHERE [asset_rollup] = ? AND [input_cutoff_date] = ?"
    )
    insert_sql = (
        "INSERT INTO [asset_indicator_signal_history] ("
        + ", ".join(f"[{col}]" for col in insert_columns)
        + ") VALUES ("
        + ", ".join("?" for _ in insert_columns)
        + ")"
    )
    for row in rows:
        (
            run_id,
            as_of,
            input_cutoff_date,
            asset_rollup,
            asset_name,
            indicator_role,
            trend_phase,
            asset_fase,
            primary_action,
            secondary_action,
            data_quality,
            direction_score,
            long_term_direction_score,
            short_term_direction_score,
            range_position_pct,
            realized_volatility_score,
            atr_pct,
            choppiness_score,
            ibkr_hv_proxy_pct,
            ibkr_iv_proxy_pct,
            implied_volatility_score,
            iv_vs_realized_volatility_score,
            theta_opportunity_proxy_score,
            theta_score,
            volume_score,
            confidence_score,
            reason_1,
            reason_2,
            reason_3,
            payload_json,
            created_at,
        ) = row
        if input_cutoff_date is None:
            cur.execute(insert_sql, row)
            continue
        cur.execute(
            update_sql,
            (
                run_id,
                as_of,
                asset_name,
                indicator_role,
                trend_phase,
                asset_fase,
                primary_action,
                secondary_action,
                data_quality,
                direction_score,
                long_term_direction_score,
                short_term_direction_score,
                range_position_pct,
                realized_volatility_score,
                atr_pct,
                choppiness_score,
                ibkr_hv_proxy_pct,
                ibkr_iv_proxy_pct,
                implied_volatility_score,
                iv_vs_realized_volatility_score,
                theta_opportunity_proxy_score,
                theta_score,
                volume_score,
                confidence_score,
                reason_1,
                reason_2,
                reason_3,
                payload_json,
                created_at,
                asset_rollup,
                input_cutoff_date,
            ),
        )
        if int(getattr(cur, "rowcount", 0) or 0) <= 0:
            cur.execute(insert_sql, row)
    try:
        cur.execute(
            """
            CREATE TABLE asset_indicator_signal_history (
                id COUNTER PRIMARY KEY,
                run_id TEXT(40),
                as_of DATETIME,
                input_cutoff_date DATETIME,
                asset_rollup TEXT(64),
                asset_name TEXT(255),
                indicator_role TEXT(80),
                trend_phase TEXT(80),
                asset_fase TEXT(80),
                primary_action TEXT(80),
                secondary_action TEXT(120),
                data_quality TEXT(32),
                direction_score DOUBLE,
                long_term_direction_score DOUBLE,
                short_term_direction_score DOUBLE,
                range_position_pct DOUBLE,
                realized_volatility_score DOUBLE,
                atr_pct DOUBLE,
                choppiness_score DOUBLE,
                ibkr_hv_proxy_pct DOUBLE,
                ibkr_iv_proxy_pct DOUBLE,
                implied_volatility_score DOUBLE,
                iv_vs_realized_volatility_score DOUBLE,
                theta_opportunity_proxy_score DOUBLE,
                theta_score DOUBLE,
                volume_score DOUBLE,
                confidence_score DOUBLE,
                reason_1 TEXT(255),
                reason_2 TEXT(255),
                reason_3 TEXT(255),
                payload_json MEMO,
                created_at DATETIME
            )
            """
        )
    except Exception:
        pass


def _history_row_tuple(run_id: str, row: dict) -> tuple:
    return (
        run_id,
        _dt_value(row.get("as_of")),
        _date_value(row.get("input_cutoff_date")),
        _text_value(row.get("asset_rollup"), 64),
        _text_value(row.get("asset_name"), 255),
        _text_value(row.get("indicator_role"), 80),
        _text_value(row.get("trend_phase"), 80),
        _text_value(row.get("asset_fase"), 80),
        _text_value(row.get("primary_action"), 80),
        _text_value(row.get("secondary_action"), 120),
        _text_value(row.get("data_quality"), 32),
        _float_value(row.get("direction_score")),
        _float_value(row.get("long_term_direction_score")),
        _float_value(row.get("short_term_direction_score")),
        _float_value(row.get("range_position_pct")),
        _float_value(row.get("realized_volatility_score")),
        _float_value(row.get("atr_pct")),
        _float_value(row.get("choppiness_score")),
        _float_value(row.get("ibkr_hv_proxy_pct")),
        _float_value(row.get("ibkr_iv_proxy_pct")),
        _float_value(row.get("implied_volatility_score")),
        _float_value(row.get("iv_vs_realized_volatility_score")),
        _float_value(row.get("theta_opportunity_proxy_score")),
        _float_value(row.get("theta_score")),
        _float_value(row.get("volume_score")),
        _float_value(row.get("confidence_score")),
        _text_value(row.get("reason_1"), 255),
        _text_value(row.get("reason_2"), 255),
        _text_value(row.get("reason_3"), 255),
        json.dumps(row, ensure_ascii=False, default=_json_default),
        datetime.now(),
    )


def _text_value(value: object, max_len: int) -> str:
    return str(value or "").strip()[:max_len]


def _float_value(value: object) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if out != out:
        return None
    return out


def _dt_value(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _date_value(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except Exception:
        return None


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _linear_score(value: float, *, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return _clamp(((float(value) - low) / (high - low)) * 100.0, 0.0, 100.0)


def _mean_last(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return _mean(values[-window:])


def _mean_window(values: list[float], *, end_exclusive: int, window: int) -> float | None:
    if end_exclusive < window:
        return None
    return _mean(values[end_exclusive - window : end_exclusive])


def _mean(values: list[float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _ema_series(values: list[float], period: int) -> list[float]:
    if period <= 0 or len(values) < period:
        return []
    alpha = 2.0 / (period + 1.0)
    ema_values: list[float] = []
    ema = sum(values[:period]) / period
    ema_values.extend([ema] * period)
    for value in values[period:]:
        ema = (float(value) * alpha) + (ema * (1.0 - alpha))
        ema_values.append(ema)
    return ema_values


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0.0):
        return None
    return current / previous - 1.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _first_number(*values) -> float | None:
    for value in values:
        out = _to_float(value)
        if out is not None:
            return out
    return None


def _normalize_volatility_pct(value) -> float | None:
    vol = _to_float(value)
    if vol is None:
        return None
    if vol <= 0.0:
        return None
    # IB option model ticks often use decimals (0.25), while TWS columns show percent (25.0).
    if vol <= 3.0:
        vol *= 100.0
    return round(vol, 2)


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        text = str(value).strip().replace(",", ".")
        try:
            return float(text)
        except Exception:
            return None


def _pick_text(row: dict, columns: tuple[str, ...], *, fallback: str) -> str:
    for col in columns:
        value = row.get(col)
        if value is not None and str(value).strip():
            return str(value).strip()
    return fallback


def _normalize_indicator_role(value) -> str:
    if value is None:
        return ""
    role = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    while "__" in role:
        role = role.replace("__", "_")
    aliases = {
        "income_anchor": "dividend_low_beta_anchor",
        "value_dividend": "dividend_value",
        "growth_theta": "medium_value_theta",
        "speculative_high_beta": "high_beta_speculative",
        "volatility_product": "volatility_products",
        "volatility_products": "volatility_products",
        "turnaround_theta": "medium_value_theta",
    }
    role = aliases.get(role, role)
    return role if role in ASSET_INDICATOR_ROLES else role


def _cast_live_schema(df: pl.DataFrame) -> pl.DataFrame:
    return _cast_schema(df, ASSET_INDICATOR_LIVE_SCHEMA)


def _cast_summary_schema(df: pl.DataFrame) -> pl.DataFrame:
    return _cast_schema(df, ASSET_INDICATOR_SUMMARY_SCHEMA)


def _cast_meta_schema(df: pl.DataFrame) -> pl.DataFrame:
    return _cast_schema(df, ASSET_INDICATOR_META_SCHEMA)


def _cast_schema(df: pl.DataFrame, schema: dict[str, pl.DataType]) -> pl.DataFrame:
    if df is None or df.is_empty():
        return pl.DataFrame(schema=schema)
    work = df
    for col, dtype in schema.items():
        if col not in work.columns:
            work = work.with_columns(pl.lit(None).cast(dtype).alias(col))
    return work.select([pl.col(col).cast(dtype, strict=False).alias(col) for col, dtype in schema.items()])

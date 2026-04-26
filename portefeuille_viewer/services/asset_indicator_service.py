"""Asset indicator snapshot builder.

V1 is intentionally manual and snapshot-only:
- read asset universe from asset_rollup_data snapshot;
- read historical OHLCV from the existing OHLCV snapshot;
- calculate Direction/Volume based rule output;
- publish live/summary/meta snapshots.

No timers, startup wiring, UI integration or database writes live here yet.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import datetime
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
    def rebuild(self) -> AssetIndicatorRunResult:
        run_id = uuid4().hex
        started_at = datetime.now()
        t0 = perf_counter()
        try:
            live_df = self._build_live_snapshot(started_at)
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

            SNAPSHOT_STORE.safe_write(SNAPSHOT_ASSET_INDICATOR_LIVE, live_df)
            SNAPSHOT_STORE.safe_write(SNAPSHOT_ASSET_INDICATOR_SUMMARY, summary_df)
            SNAPSHOT_STORE.safe_write(SNAPSHOT_ASSET_INDICATOR_META, meta_df)

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

    def _build_live_snapshot(self, as_of: datetime) -> pl.DataFrame:
        assets_df = _normalize_assets_df(getattr(SNAPSHOT_STORE, "repository_snapshot_asset_rollup_data", None))
        if assets_df.is_empty():
            return empty_asset_indicator_live_frame()

        history_df = _normalize_history_df(getattr(SNAPSHOT_STORE, "repository_snapshot_historical_ohlcv", None))
        history_by_asset = _history_by_asset(history_df)
        theta_by_asset = _theta_by_asset(getattr(SNAPSHOT_STORE, "snapshot_optie_timevalue_live", None))

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
            "direction_score": None,
            "long_term_direction_score": None,
            "short_term_direction_score": None,
            "range_position_pct": None,
            "trend_phase": "insufficient_data",
            "theta_score": None,
            "volume_score": None,
            "vulnerability_score": None,
            "liquidity_score": None,
            "confidence_score": 0.0,
            "asset_mode": "insufficient_data",
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
        theta_score = _score_theta(theta_metrics)
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
            )
        )

        base.update(
            {
                "direction_score": direction_score,
                "long_term_direction_score": long_term_direction_score,
                "short_term_direction_score": short_term_direction_score,
                "range_position_pct": range_position_pct,
                "trend_phase": trend_phase,
                "theta_score": theta_score,
                "volume_score": volume_score,
                "confidence_score": decision.confidence_score,
                "asset_mode": decision.asset_mode,
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
        for group_col, group_type in (("primary_action", "primary_action"), ("asset_mode", "asset_mode")):
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
    for col in ("open_price", "high_price", "low_price", "volume_value"):
        if col in df.columns:
            exprs.append(pl.col(col).cast(pl.Float64, strict=False).alias(col))
        else:
            exprs.append(pl.lit(None).cast(pl.Float64).alias(col))
    return (
        df.with_columns(exprs)
        .filter(
            pl.col("datum").is_not_null()
            & pl.col("asset_rollup").is_not_null()
            & (pl.col("asset_rollup") != "")
            & pl.col("close_price").is_not_null()
        )
        .sort(["asset_rollup", "datum"])
    )


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
    }


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

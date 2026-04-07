from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from typing import Any

import polars as pl

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.services.aandelen_tab_summary import build_aandelen_tab_summary
from portefeuille_viewer.services.asset_display_settings import load_price_decimals_map


class AandelenProjectionV2:
    """
    Versioned projection for Aandelen view.

    - Produces full snapshot DataFrame.
    - Produces cell-level patch based on previous snapshot.
    """

    name = "aandelen_v2"
    _DEBUG_RECOMPUTE = os.getenv("AANDELEN_V2_RECOMPUTE_DEBUG", "0").strip() == "1"
    depends_on = {
        # Live aggregators used in build_aandelen_tab_summary
        "aggregator_snapshot_aandelen_live",
        "aggregator_snapshot_load_open_opties_from_tx_live",
        "aggregator_snapshot_open_sprinters_live",
        # Repository snapshots used by static summary and fallbacks
        "repository_snapshot_gesloten_opties",
        "repository_snapshot_gesloten_sprinters_no_asset_detail",
        "repository_portfolio_dividend",
        "repository_snapshot_active_asset_rollup_data",
        "repository_snapshot_portfolio_value_total_combined_put",
        "repository_snapshot_per_dag_asset_result_v2",
        "repository_snapshot_per_dag_asset_result_v2_latest",
        "repository_snapshot_historical_close",
        "repository_snapshot_historical_close_latest",
        "repository_snapshot_asset_rollup_data",
        # Overlay source
        "snapshot_optie_timevalue_live",
    }

    def __init__(self):
        self._lock = threading.Lock()
        self._version = 0
        self._snapshot = pl.DataFrame()
        self._base_snapshot = pl.DataFrame()
        self._broker_cache: dict[str, pl.DataFrame] = {}
        self._last_patch: list[dict[str, Any]] = []
        self._updated_at: str | None = None
        self._selected_brokers: set[str] | None = None
        self._diag: dict[str, Any] = {}
        self._pending_broker_only_recompute = False

    def set_selected_brokers(self, brokers: set[str] | None) -> None:
        with self._lock:
            if brokers:
                self._selected_brokers = {str(b).strip().lower() for b in brokers if str(b).strip()}
            else:
                self._selected_brokers = None
            self._pending_broker_only_recompute = True

    def recompute(self, changed_keys: set[str]) -> None:
        recompute_started = time.perf_counter()
        with self._lock:
            selected_brokers = set(self._selected_brokers) if self._selected_brokers else None
            broker_only = bool(self._pending_broker_only_recompute)
            self._pending_broker_only_recompute = False
        changed_raw = {str(k).strip().upper() for k in (changed_keys or set()) if str(k).strip()}
        overlay_snapshot_keys = {"__TIMEVALUE_OVERLAY__", "SNAPSHOT_OPTIE_TIMEVALUE_LIVE"}
        overlay_only = bool(changed_raw) and changed_raw.issubset(overlay_snapshot_keys)
        technical_keys = self._has_technical_keys(changed_raw - {"SNAPSHOT_OPTIE_TIMEVALUE_LIVE"})
        changed_assets = self._normalize_changed_assets(changed_raw)
        incremental = bool(changed_assets)
        timings_ms: dict[str, float] = {}
        path = "full_rebuild"

        # Snapshot/topic-driven updates (AGGREGATOR_*/SNAPSHOT_*/REPOSITORY_*)
        # must refresh from source and rebuild broker cache, otherwise overlay-only
        # recomputes may keep stale open_sp_* values.
        if technical_keys:
            path = "technical_full_rebuild"
            t0 = time.perf_counter()
            df_new = build_aandelen_tab_summary(selected_brokers=selected_brokers)
            timings_ms["build_aandelen_tab_summary_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
            t0 = time.perf_counter()
            self._rebuild_broker_cache(df_new)
            timings_ms["rebuild_broker_cache_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        elif (broker_only or overlay_only) and self._broker_cache:
            path = "broker_cache_overlay"
            t0 = time.perf_counter()
            df_new = self._recompute_from_broker_cache(selected_brokers)
            timings_ms["recompute_from_broker_cache_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        elif incremental:
            path = "incremental"
            t0 = time.perf_counter()
            df_new, incremental_diag = self._recompute_incremental(changed_assets, selected_brokers)
            timings_ms["recompute_incremental_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        else:
            path = "fallback_full_rebuild"
            t0 = time.perf_counter()
            df_new = build_aandelen_tab_summary(selected_brokers=selected_brokers)
            timings_ms["build_aandelen_tab_summary_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
            t0 = time.perf_counter()
            self._rebuild_broker_cache(df_new)
            timings_ms["rebuild_broker_cache_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        incremental_diag = locals().get("incremental_diag", {})
        t0 = time.perf_counter()
        df_new, diag = self._with_price_quality_guard(
            df_new,
            selected_brokers,
            enable_repair=incremental and not broker_only and not overlay_only,
            repair_assets=changed_assets if incremental and not broker_only and not overlay_only else None,
        )
        timings_ms["price_quality_guard_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        t0 = time.perf_counter()
        patch = self._build_patch(self._snapshot, df_new)
        timings_ms["build_patch_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        timings_ms["total_recompute_ms"] = round((time.perf_counter() - recompute_started) * 1000.0, 3)
        changed_keys_sorted = sorted(changed_raw)
        patch_row_ids = sorted({str(item.get("row_id") or "").strip() for item in (patch or []) if str(item.get("row_id") or "").strip()})
        patch_fields = sorted({str(item.get("field") or "").strip() for item in (patch or []) if str(item.get("field") or "").strip() and str(item.get("field") or "").strip() != "__deleted__"})
        diag.update(incremental_diag)
        diag.update(
            {
                "patch_size": len(patch or []),
                "patch_row_ids": patch_row_ids[:20],
                "patch_fields_sample": patch_fields[:20],
                "path": path,
                "technical_keys": technical_keys,
                "broker_only": broker_only,
                "overlay_only": overlay_only,
                "incremental_candidate": incremental,
                "changed_assets_count": len(changed_assets),
                "changed_assets_sample": sorted(changed_assets)[:10],
                "changed_keys_count": len(changed_raw),
                "changed_keys_sample": changed_keys_sorted[:10],
                "changed_keys_full": changed_keys_sorted if len(changed_keys_sorted) <= 10 else [],
                "selected_brokers_count": len(selected_brokers or set()),
                "timings_ms": timings_ms,
            }
        )
        with self._lock:
            self._version += 1
            self._base_snapshot = (
                df_new if selected_brokers is None else self._base_snapshot
            )
            self._snapshot = df_new
            if selected_brokers is None:
                # Keep the unfiltered broker-cache root in sync with incremental
                # aandelen updates. Without this, a later overlay-only recompute
                # can overwrite the fresh incremental snapshot with stale cached
                # rows until a technical full rebuild happens.
                self._broker_cache["__ALL__"] = df_new
            self._last_patch = patch
            self._updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._diag = diag
        if self._DEBUG_RECOMPUTE:
            print(
                "[aandelen-v2-debug] "
                f"path={path} "
                f"technical={technical_keys} broker_only={broker_only} overlay_only={overlay_only} "
                f"incremental={incremental} changed_assets={sorted(changed_assets)[:10]} "
                f"changed_keys_count={len(changed_keys_sorted)} changed_keys_sample={changed_keys_sorted[:10]} "
                f"fallback_assets={diag.get('price_guard_fallback_asset_count', 0)} "
                f"repairs={diag.get('fallback_row_repairs', 0)} "
                f"repair_loop_ms={diag.get('price_guard_repair_loop_ms', 0.0)} "
                f"repair_merge_ms={diag.get('price_guard_repair_merge_ms', 0.0)} "
                f"incremental_keep_rows={diag.get('incremental_keep_rows', 0)} "
                f"incremental_rebuilt_rows={diag.get('incremental_rebuilt_rows', 0)} "
                f"incremental_asset_timings_ms={diag.get('incremental_asset_timings_ms', {})} "
                f"patch_size={diag.get('patch_size', 0)} patch_row_ids={diag.get('patch_row_ids', [])} "
                f"patch_fields_sample={diag.get('patch_fields_sample', [])} "
                f"timings={timings_ms}"
            )

    def _recompute_incremental(self, changed: set[str], selected_brokers: set[str] | None) -> tuple[pl.DataFrame, dict[str, Any]]:
        diag: dict[str, Any] = {
            "incremental_assets_count": len(changed or set()),
            "incremental_assets_sample": sorted(changed or set())[:10],
            "incremental_keep_rows": 0,
            "incremental_rebuilt_rows": 0,
            "incremental_asset_timings_ms": {},
            "incremental_fallback_reason": None,
        }
        if not changed:
            diag["incremental_fallback_reason"] = "no_changed_assets"
            return build_aandelen_tab_summary(selected_brokers=selected_brokers), diag

        with self._lock:
            current = self._snapshot
        if current is None or current.is_empty() or "asset_rollup" not in current.columns:
            diag["incremental_fallback_reason"] = "empty_current_snapshot"
            return build_aandelen_tab_summary(selected_brokers=selected_brokers), diag

        keep_df = current.filter(~pl.col("asset_rollup").cast(pl.Utf8).str.to_uppercase().is_in(list(changed)))
        diag["incremental_keep_rows"] = int(keep_df.height)
        frames: list[pl.DataFrame] = [keep_df]
        rebuilt_rows = 0
        asset_timings: dict[str, float] = {}
        for asset in sorted(changed):
            asset_t0 = time.perf_counter()
            try:
                one = build_aandelen_tab_summary(selected_brokers=selected_brokers, asset_rollup=asset)
                asset_timings[asset] = round((time.perf_counter() - asset_t0) * 1000.0, 3)
                if one is not None and not one.is_empty():
                    rebuilt_rows += int(one.height)
                    frames.append(one)
            except Exception:
                diag["incremental_fallback_reason"] = f"asset_failed:{asset}"
                diag["incremental_asset_timings_ms"] = asset_timings
                return build_aandelen_tab_summary(selected_brokers=selected_brokers), diag
        diag["incremental_rebuilt_rows"] = rebuilt_rows
        diag["incremental_asset_timings_ms"] = asset_timings
        if not frames:
            diag["incremental_fallback_reason"] = "no_frames"
            return build_aandelen_tab_summary(selected_brokers=selected_brokers), diag
        return pl.concat(frames, how="diagonal_relaxed").unique(subset=["asset_rollup"], keep="last"), diag

    @staticmethod
    def _normalize_changed_assets(changed_keys: set[str]) -> set[str]:
        if not changed_keys:
            return set()
        out: set[str] = set()
        for key in changed_keys:
            k = str(key or "").strip().upper()
            if not k:
                continue
            if k.startswith("__"):
                continue
            if (
                k.startswith("SNAPSHOT_")
                or k.startswith("AGGREGATOR_")
                or k.startswith("REPOSITORY_")
            ):
                continue
            # Row ids / composite keys are not valid asset_rollup values.
            if "|" in k or "/" in k:
                continue
            out.add(k)
        return out

    @staticmethod
    def _has_technical_keys(changed_keys: set[str]) -> bool:
        if not changed_keys:
            return False
        for key in changed_keys:
            k = str(key or "").strip().upper()
            if not k:
                continue
            if (
                k.startswith("SNAPSHOT_")
                or k.startswith("AGGREGATOR_")
                or k.startswith("REPOSITORY_")
            ):
                return True
        return False

    def snapshot(self) -> pl.DataFrame:
        with self._lock:
            return self._snapshot

    def version(self) -> int:
        with self._lock:
            return self._version

    def last_patch(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._last_patch)

    def meta(self) -> dict[str, Any]:
        with self._lock:
            asset_rollups: list[str] = []
            if self._snapshot is not None and not self._snapshot.is_empty() and "asset_rollup" in self._snapshot.columns:
                try:
                    asset_rollups = [
                        str(v).strip()
                        for v in self._snapshot["asset_rollup"].to_list()
                        if str(v).strip()
                    ]
                except Exception:
                    asset_rollups = []
            return {
                "view": "aandelen",
                "version": self._version,
                "updated_at": self._updated_at,
                "rows": self._snapshot.height if self._snapshot is not None else 0,
                "base_rows": self._base_snapshot.height if self._base_snapshot is not None else 0,
                "changes": len(self._last_patch),
                "selected_brokers": sorted(self._selected_brokers) if self._selected_brokers else [],
                "broker_cache_count": len(self._broker_cache),
                "asset_price_decimals": load_price_decimals_map(asset_rollups),
                "diag": dict(self._diag or {}),
            }

    def _recompute_from_broker_cache(self, selected_brokers: set[str] | None) -> pl.DataFrame:
        if selected_brokers is None:
            df_all = self._broker_cache.get("__ALL__")
            if isinstance(df_all, pl.DataFrame):
                return self._apply_timevalue_overlay(df_all, None)
            return build_aandelen_tab_summary(selected_brokers=None)

        frames: list[pl.DataFrame] = []
        for broker in sorted(selected_brokers):
            df_b = self._broker_cache.get(str(broker).strip().lower())
            if isinstance(df_b, pl.DataFrame) and not df_b.is_empty():
                frames.append(df_b)
        if not frames:
            return pl.DataFrame(schema={"asset_rollup": pl.Utf8})

        merged = pl.concat(frames, how="diagonal_relaxed")
        if merged.is_empty() or "asset_rollup" not in merged.columns:
            return merged

        dims_first = {
            "koers": "max",
            "koers_prev": "max",
            "pct_change": "max",
            "regio": "first",
            "sector": "first",
            "value_grow": "first",
            "status": "first",
            "portfolio_total_waarde_lineair_pct": "max",
            "portfolio_total_waarde_delta_pct": "max",
        }
        agg_exprs: list[pl.Expr] = []
        for col in merged.columns:
            if col == "asset_rollup":
                continue
            if col in dims_first:
                if dims_first[col] == "max":
                    agg_exprs.append(pl.col(col).max().alias(col))
                else:
                    agg_exprs.append(pl.col(col).drop_nulls().first().alias(col))
                continue
            if merged.schema.get(col) in {pl.Float64, pl.Float32, pl.Int64, pl.Int32, pl.Int16, pl.Int8, pl.UInt64, pl.UInt32, pl.UInt16, pl.UInt8}:
                agg_exprs.append(pl.col(col).sum().alias(col))
            else:
                agg_exprs.append(pl.col(col).drop_nulls().first().alias(col))
        grouped = merged.group_by("asset_rollup").agg(agg_exprs)
        return self._apply_timevalue_overlay(grouped, selected_brokers)

    def _rebuild_broker_cache(self, df_all: pl.DataFrame) -> None:
        brokers = self._all_brokers()
        cache: dict[str, pl.DataFrame] = {"__ALL__": self._apply_timevalue_overlay(df_all, None)}
        for broker in brokers:
            try:
                cache[broker] = self._apply_timevalue_overlay(
                    build_aandelen_tab_summary(selected_brokers={broker}),
                    {broker},
                )
            except Exception:
                continue
        with self._lock:
            self._broker_cache = cache

    @staticmethod
    def _apply_timevalue_overlay(df: pl.DataFrame, selected_brokers: set[str] | None) -> pl.DataFrame:
        if df is None or df.is_empty() or "asset_rollup" not in df.columns:
            return df

        tv = getattr(SNAPSHOT_STORE, "snapshot_optie_timevalue_live", None)
        if tv is None or tv.is_empty():
            if "optie_tijdswaarde_signed_eur" in df.columns:
                return df.with_columns(pl.col("optie_tijdswaarde_signed_eur").fill_null(0.0))
            return df.with_columns(pl.lit(0.0).alias("optie_tijdswaarde_signed_eur"))

        tv_df = tv
        if selected_brokers is not None and "broker" in tv_df.columns:
            allowed = [str(b).strip().lower() for b in selected_brokers if str(b).strip()]
            if allowed:
                tv_df = tv_df.filter(
                    pl.col("broker")
                    .cast(pl.Utf8, strict=False)
                    .str.strip_chars()
                    .str.to_lowercase()
                    .is_in(allowed)
                )

        if tv_df.is_empty() or "asset" not in tv_df.columns:
            if "optie_tijdswaarde_signed_eur" in df.columns:
                return df.with_columns(pl.col("optie_tijdswaarde_signed_eur").fill_null(0.0))
            return df.with_columns(pl.lit(0.0).alias("optie_tijdswaarde_signed_eur"))

        eurusd = float(get_settings().get_eurusd() or 1.0)
        if eurusd == 0:
            eurusd = 1.0

        tv_sum = (
            tv_df.select(
                [
                    pl.col("asset")
                    .cast(pl.Utf8, strict=False)
                    .str.strip_chars()
                    .str.to_uppercase()
                    .alias("__asset_key"),
                    pl.col("ccy").cast(pl.Utf8, strict=False).alias("ccy"),
                    pl.col("time_total").cast(pl.Float64, strict=False).alias("time_total"),
                ]
            )
            .filter(pl.col("__asset_key").is_not_null() & pl.col("time_total").is_not_null())
            .group_by(["__asset_key", "ccy"])
            .agg(pl.col("time_total").sum().alias("time_total_signed"))
            .with_columns(
                pl.when(pl.col("ccy") == "USD")
                .then(pl.col("time_total_signed") / eurusd)
                .otherwise(pl.col("time_total_signed"))
                .alias("optie_tijdswaarde_signed_eur")
            )
            .group_by("__asset_key")
            .agg(pl.col("optie_tijdswaarde_signed_eur").sum().alias("optie_tijdswaarde_signed_eur"))
        )

        out = (
            df.with_columns(
                pl.col("asset_rollup")
                .cast(pl.Utf8, strict=False)
                .str.strip_chars()
                .str.to_uppercase()
                .alias("__asset_key")
            )
            .drop("optie_tijdswaarde_signed_eur", strict=False)
            .join(tv_sum, on="__asset_key", how="left")
            .with_columns(pl.col("optie_tijdswaarde_signed_eur").fill_null(0.0))
            .drop("__asset_key")
        )
        return out

    @staticmethod
    def _all_brokers() -> set[str]:
        keys = [
            "aggregator_snapshot_aandelen_live",
            "aggregator_snapshot_load_open_opties_from_tx_live",
            "aggregator_snapshot_open_sprinters_live",
            "repository_snapshot_gesloten_opties",
            "repository_snapshot_gesloten_sprinters_no_asset_detail",
            "repository_portfolio_dividend",
            "snapshot_optie_timevalue_live",
        ]
        out: set[str] = set()
        for key in keys:
            df = getattr(SNAPSHOT_STORE, key, None)
            if df is None or df.is_empty() or "broker" not in df.columns:
                continue
            try:
                vals = (
                    df.select(pl.col("broker").cast(pl.Utf8).str.strip_chars().str.to_lowercase().alias("broker"))
                    .drop_nulls()
                    .unique()
                    .get_column("broker")
                    .to_list()
                )
                for b in vals:
                    s = str(b).strip().lower()
                    if s:
                        out.add(s)
            except Exception:
                continue
        return out

    def _with_price_quality_guard(
        self,
        df_new: pl.DataFrame,
        selected_brokers: set[str] | None,
        enable_repair: bool,
        repair_assets: set[str] | None = None,
    ) -> tuple[pl.DataFrame, dict[str, Any]]:
        if df_new is None or df_new.is_empty() or "asset_rollup" not in df_new.columns:
            return df_new, {
                "koers_null": 0,
                "koers_prev_null": 0,
                "koers_null_relevant": 0,
                "koers_null_expected": 0,
                "koers_prev_null_relevant": 0,
                "koers_prev_null_expected": 0,
                "fallback_row_repairs": 0,
                "fallback_assets": [],
            }

        diag = self._price_diag(df_new)
        fallback_assets = sorted(
            set(diag["koers_null_assets"]) | set(diag["koers_prev_null_assets"])
        )
        repair_target_assets = sorted(
            set(fallback_assets)
            if not repair_assets
            else (set(fallback_assets) & {str(a).strip().upper() for a in repair_assets if str(a).strip()})
        )
        repairs = 0
        repair_loop_ms = 0.0
        repair_merge_ms = 0.0
        repair_asset_timings: dict[str, float] = {}
        if enable_repair and repair_target_assets:
            repaired_rows: list[pl.DataFrame] = []
            repair_t0 = time.perf_counter()
            for asset in repair_target_assets:
                asset_t0 = time.perf_counter()
                try:
                    row = build_aandelen_tab_summary(
                        selected_brokers=selected_brokers,
                        asset_rollup=asset,
                    )
                    repair_asset_timings[asset] = round((time.perf_counter() - asset_t0) * 1000.0, 3)
                    if row is not None and not row.is_empty():
                        repaired_rows.append(row)
                except Exception:
                    repair_asset_timings[asset] = round((time.perf_counter() - asset_t0) * 1000.0, 3)
                    continue
            repair_loop_ms = round((time.perf_counter() - repair_t0) * 1000.0, 3)
            if repaired_rows:
                merge_t0 = time.perf_counter()
                repaired_df = pl.concat(repaired_rows, how="diagonal_relaxed").unique(
                    subset=["asset_rollup"], keep="last"
                )
                repaired_assets = set(
                    str(x).strip().upper() for x in repaired_df["asset_rollup"].to_list()
                )
                keep_df = df_new.filter(
                    ~pl.col("asset_rollup")
                    .cast(pl.Utf8)
                    .str.strip_chars()
                    .str.to_uppercase()
                    .is_in(list(repaired_assets))
                )
                df_new = pl.concat([keep_df, repaired_df], how="diagonal_relaxed").unique(
                    subset=["asset_rollup"], keep="last"
                )
                repair_merge_ms = round((time.perf_counter() - merge_t0) * 1000.0, 3)
                repairs = len(repaired_assets)
                diag = self._price_diag(df_new)

        return df_new, {
            "koers_null": diag["koers_null"],
            "koers_prev_null": diag["koers_prev_null"],
            "koers_null_relevant": diag["koers_null_relevant"],
            "koers_null_expected": diag["koers_null_expected"],
            "koers_prev_null_relevant": diag["koers_prev_null_relevant"],
            "koers_prev_null_expected": diag["koers_prev_null_expected"],
            "fallback_row_repairs": repairs,
            "fallback_assets": fallback_assets[:50],
            "price_guard_enable_repair": bool(enable_repair),
            "price_guard_fallback_asset_count": len(fallback_assets),
            "price_guard_repair_target_asset_count": len(repair_target_assets),
            "price_guard_repair_target_assets": repair_target_assets[:20],
            "price_guard_repair_loop_ms": repair_loop_ms,
            "price_guard_repair_merge_ms": repair_merge_ms,
            "price_guard_repair_asset_timings_ms": repair_asset_timings,
        }

    @staticmethod
    def _price_diag(df: pl.DataFrame) -> dict[str, Any]:
        if df is None or df.is_empty() or "asset_rollup" not in df.columns:
            return {
                "koers_null": 0,
                "koers_prev_null": 0,
                "koers_null_relevant": 0,
                "koers_null_expected": 0,
                "koers_prev_null_relevant": 0,
                "koers_prev_null_expected": 0,
                "koers_null_assets": [],
                "koers_prev_null_assets": [],
                "expected_no_price_assets": 0,
            }
        expected_no_price = AandelenProjectionV2._expected_no_price_assets()
        koers_null_assets: list[str] = []
        koers_prev_null_assets: list[str] = []
        koers_null_expected = 0
        koers_prev_null_expected = 0
        has_koers = "koers" in df.columns
        has_prev = "koers_prev" in df.columns
        for row in df.select(
            [
                "asset_rollup",
                pl.col("koers") if has_koers else pl.lit(None).alias("koers"),
                pl.col("koers_prev") if has_prev else pl.lit(None).alias("koers_prev"),
            ]
        ).to_dicts():
            asset = str(row.get("asset_rollup") or "").strip().upper()
            if not asset:
                continue
            koers_is_null = row.get("koers") is None
            koers_prev_is_null = row.get("koers_prev") is None
            if asset in expected_no_price:
                if koers_is_null:
                    koers_null_expected += 1
                if koers_prev_is_null:
                    koers_prev_null_expected += 1
                continue
            if koers_is_null:
                koers_null_assets.append(asset)
            if koers_prev_is_null:
                koers_prev_null_assets.append(asset)
        return {
            # Backward-compatible fields
            "koers_null": len(koers_null_assets),
            "koers_prev_null": len(koers_prev_null_assets),
            # Explicit relevant/expected split
            "koers_null_relevant": len(koers_null_assets),
            "koers_null_expected": koers_null_expected,
            "koers_prev_null_relevant": len(koers_prev_null_assets),
            "koers_prev_null_expected": koers_prev_null_expected,
            "koers_null_assets": koers_null_assets,
            "koers_prev_null_assets": koers_prev_null_assets,
            "expected_no_price_assets": len(expected_no_price),
        }

    @staticmethod
    def _expected_no_price_assets() -> set[str]:
        df_assets = getattr(SNAPSHOT_STORE, "repository_snapshot_asset_rollup_data", None)
        if df_assets is None or df_assets.is_empty() or "asset_rollup" not in df_assets.columns or "INCL_EXCL" not in df_assets.columns:
            return set()
        try:
            excluded = df_assets.filter(
                (pl.col("INCL_EXCL") == 0)
                | (pl.col("INCL_EXCL") == "0")
                | (pl.col("INCL_EXCL") == False)  # noqa: E712
            ).select(
                pl.col("asset_rollup").cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("asset_rollup")
            )
            return {
                str(x).strip().upper()
                for x in excluded["asset_rollup"].to_list()
                if str(x).strip()
            }
        except Exception:
            return set()

    def _build_patch(self, old_df: pl.DataFrame, new_df: pl.DataFrame) -> list[dict[str, Any]]:
        if new_df is None or new_df.is_empty() or "asset_rollup" not in new_df.columns:
            return []

        old_map = self._to_row_map(old_df)
        new_map = self._to_row_map(new_df)
        patch: list[dict[str, Any]] = []

        for row_id, new_row in new_map.items():
            old_row = old_map.get(row_id)
            if old_row is None:
                for field, value in new_row.items():
                    if field == "asset_rollup":
                        continue
                    patch.append({"row_id": row_id, "field": field, "value": value})
                continue
            for field, value in new_row.items():
                if field == "asset_rollup":
                    continue
                if not self._same_value(old_row.get(field), value):
                    patch.append({"row_id": row_id, "field": field, "value": value})

        for row_id in old_map.keys():
            if row_id not in new_map:
                patch.append({"row_id": row_id, "field": "__deleted__", "value": True})

        return patch

    @staticmethod
    def _to_row_map(df: pl.DataFrame) -> dict[str, dict[str, Any]]:
        if df is None or df.is_empty() or "asset_rollup" not in df.columns:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for row in df.to_dicts():
            row_id = str(row.get("asset_rollup") or "").strip()
            if not row_id:
                continue
            out[row_id] = row
        return out

    @staticmethod
    def _same_value(a: Any, b: Any) -> bool:
        if a is None and b is None:
            return True
        if isinstance(a, float) and isinstance(b, float):
            return abs(a - b) < 1e-12
        return a == b

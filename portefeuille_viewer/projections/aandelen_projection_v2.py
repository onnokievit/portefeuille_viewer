from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

import polars as pl

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.services.aandelen_tab_summary import build_aandelen_tab_summary


class AandelenProjectionV2:
    """
    Versioned projection for Aandelen view.

    - Produces full snapshot DataFrame.
    - Produces cell-level patch based on previous snapshot.
    """

    name = "aandelen_v2"
    depends_on = {
        "repository_snapshot_historical_close",
        "repository_snapshot_per_dag_asset_result_v2",
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
        with self._lock:
            selected_brokers = set(self._selected_brokers) if self._selected_brokers else None
            broker_only = bool(self._pending_broker_only_recompute)
            self._pending_broker_only_recompute = False
        incremental = bool(changed_keys)
        if broker_only and self._broker_cache:
            df_new = self._recompute_from_broker_cache(selected_brokers)
        elif incremental:
            df_new = self._recompute_incremental(changed_keys, selected_brokers)
        else:
            df_new = build_aandelen_tab_summary(selected_brokers=selected_brokers)
            self._rebuild_broker_cache(df_new)
        df_new, diag = self._with_price_quality_guard(
            df_new,
            selected_brokers,
            enable_repair=incremental and not broker_only,
        )
        patch = self._build_patch(self._snapshot, df_new)
        with self._lock:
            self._version += 1
            self._base_snapshot = (
                df_new if selected_brokers is None else self._base_snapshot
            )
            self._snapshot = df_new
            self._last_patch = patch
            self._updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._diag = diag

    def _recompute_incremental(self, changed_keys: set[str], selected_brokers: set[str] | None) -> pl.DataFrame:
        changed = {str(k).strip().upper() for k in (changed_keys or set()) if str(k).strip()}
        if not changed:
            return build_aandelen_tab_summary(selected_brokers=selected_brokers)

        with self._lock:
            current = self._snapshot
        if current is None or current.is_empty() or "asset_rollup" not in current.columns:
            return build_aandelen_tab_summary(selected_brokers=selected_brokers)

        keep_df = current.filter(~pl.col("asset_rollup").cast(pl.Utf8).str.to_uppercase().is_in(list(changed)))
        frames: list[pl.DataFrame] = [keep_df]
        for asset in sorted(changed):
            try:
                one = build_aandelen_tab_summary(selected_brokers=selected_brokers, asset_rollup=asset)
                if one is not None and not one.is_empty():
                    frames.append(one)
            except Exception:
                # Safe fallback: if one asset fails, do full recompute.
                return build_aandelen_tab_summary(selected_brokers=selected_brokers)
        if not frames:
            return build_aandelen_tab_summary(selected_brokers=selected_brokers)
        return pl.concat(frames, how="diagonal_relaxed").unique(subset=["asset_rollup"], keep="last")

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
            return {
                "view": "aandelen",
                "version": self._version,
                "updated_at": self._updated_at,
                "rows": self._snapshot.height if self._snapshot is not None else 0,
                "base_rows": self._base_snapshot.height if self._base_snapshot is not None else 0,
                "changes": len(self._last_patch),
                "selected_brokers": sorted(self._selected_brokers) if self._selected_brokers else [],
                "broker_cache_count": len(self._broker_cache),
                "diag": dict(self._diag or {}),
            }

    def _recompute_from_broker_cache(self, selected_brokers: set[str] | None) -> pl.DataFrame:
        if selected_brokers is None:
            df_all = self._broker_cache.get("__ALL__")
            if isinstance(df_all, pl.DataFrame):
                return df_all
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
        return merged.group_by("asset_rollup").agg(agg_exprs)

    def _rebuild_broker_cache(self, df_all: pl.DataFrame) -> None:
        brokers = self._all_brokers()
        cache: dict[str, pl.DataFrame] = {"__ALL__": df_all}
        for broker in brokers:
            try:
                cache[broker] = build_aandelen_tab_summary(selected_brokers={broker})
            except Exception:
                continue
        with self._lock:
            self._broker_cache = cache

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
        repairs = 0
        if enable_repair and fallback_assets:
            repaired_rows: list[pl.DataFrame] = []
            for asset in fallback_assets:
                try:
                    row = build_aandelen_tab_summary(
                        selected_brokers=selected_brokers,
                        asset_rollup=asset,
                    )
                    if row is not None and not row.is_empty():
                        repaired_rows.append(row)
                except Exception:
                    continue
            if repaired_rows:
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

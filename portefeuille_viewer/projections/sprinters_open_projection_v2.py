from __future__ import annotations

import threading
from datetime import datetime
from decimal import Decimal
from typing import Any

import polars as pl

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


class SprintersOpenProjectionV2:
    """Versioned projection for Sprinters Open."""

    name = "sprinters_open_v2"
    depends_on = {"aggregator_snapshot_open_sprinters_live"}

    def __init__(self):
        self._lock = threading.Lock()
        self._version = 0
        self._snapshot = pl.DataFrame()
        self._last_patch: list[dict[str, Any]] = []
        self._updated_at: str | None = None

    def recompute(self) -> None:
        df_src = getattr(SNAPSHOT_STORE, "aggregator_snapshot_open_sprinters_live", None)
        df_new = self._prepare_df(df_src if isinstance(df_src, pl.DataFrame) else pl.DataFrame())
        patch = self._build_patch(self._snapshot, df_new)
        with self._lock:
            self._version += 1
            self._snapshot = df_new
            self._last_patch = patch
            self._updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
                "view": "sprinters_open",
                "version": self._version,
                "updated_at": self._updated_at,
                "rows": self._snapshot.height if self._snapshot is not None else 0,
                "changes": len(self._last_patch),
            }

    @staticmethod
    def _row_id_of(row: dict[str, Any]) -> str:
        broker = str(row.get("broker") or "").strip().upper()
        asset = str(row.get("asset_rollup") or "").strip().upper()
        detail = str(row.get("asset_detail") or "").strip().upper()
        exp = row.get("optie_exp_date")
        cp = str(row.get("optie_call_put") or "").strip().upper()
        strike = row.get("optie_strike")
        if isinstance(strike, Decimal):
            strike = float(strike)
        s_strike = "" if strike is None else str(strike)
        s_exp = exp.isoformat() if hasattr(exp, "isoformat") else str(exp or "")
        return f"{broker}|{asset}|{detail}|{cp}|{s_strike}|{s_exp}"

    @staticmethod
    def _prepare_df(df: pl.DataFrame) -> pl.DataFrame:
        if df is None or df.is_empty():
            return pl.DataFrame(schema={"row_id": pl.Utf8})
        wanted = [
            "broker",
            "asset_rollup",
            "asset_detail",
            "Koers",
            "optie_exp_date",
            "optie_strike",
            "optie_call_put",
            "sprinter_funding",
            "sprinter_ratio",
            "SomVantransactie_fee",
            "SomVantransactie_aantal",
            "SomVantransactie_euro_totaal",
            "sp_result",
        ]
        keep = [c for c in wanted if c in df.columns]
        out = df.select(keep)
        rows = out.to_dicts()
        for r in rows:
            r["row_id"] = SprintersOpenProjectionV2._row_id_of(r)
        out = pl.DataFrame(rows)
        if "row_id" in out.columns:
            out = out.unique(subset=["row_id"], keep="last")
        order = ["row_id"] + [c for c in wanted if c in out.columns]
        return out.select([c for c in order if c in out.columns])

    def _build_patch(self, old_df: pl.DataFrame, new_df: pl.DataFrame) -> list[dict[str, Any]]:
        if new_df is None or new_df.is_empty() or "row_id" not in new_df.columns:
            return []
        old_map = self._to_row_map(old_df)
        new_map = self._to_row_map(new_df)
        patch: list[dict[str, Any]] = []
        for row_id, new_row in new_map.items():
            old_row = old_map.get(row_id)
            if old_row is None:
                for field, value in new_row.items():
                    if field == "row_id":
                        continue
                    patch.append({"row_id": row_id, "field": field, "value": value})
                continue
            for field, value in new_row.items():
                if field == "row_id":
                    continue
                if not self._same_value(old_row.get(field), value):
                    patch.append({"row_id": row_id, "field": field, "value": value})
        for row_id in old_map.keys():
            if row_id not in new_map:
                patch.append({"row_id": row_id, "field": "__deleted__", "value": True})
        return patch

    @staticmethod
    def _to_row_map(df: pl.DataFrame) -> dict[str, dict[str, Any]]:
        if df is None or df.is_empty() or "row_id" not in df.columns:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for row in df.to_dicts():
            rid = str(row.get("row_id") or "").strip()
            if rid:
                out[rid] = row
        return out

    @staticmethod
    def _same_value(a: Any, b: Any) -> bool:
        if a is None and b is None:
            return True
        if isinstance(a, float) and isinstance(b, float):
            return abs(a - b) < 1e-12
        return a == b


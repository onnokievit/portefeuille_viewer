from __future__ import annotations

import copy
import threading
from collections import defaultdict
from datetime import date, datetime

import polars as pl

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.repository import get_connection
from portefeuille_viewer.services.cash_management_result_chart_service import (
    build_cash_management_result_chart_payload,
)


PORTFOLIO_COLORS = {
    "total": "#111111",
    "degiro": "#22b7ff",
    "lynx": "#ff2f2f",
    "interactive": "#2cc96f",
}
INDEX_COLORS = ["#2f80ed", "#f5a623", "#9b51e0", "#27ae60", "#eb5757", "#56ccf2", "#7f8c8d"]
_CACHE_LOCK = threading.RLock()
_INDEX_OPTIONS_CACHE: list[str] | None = None
_PORTFOLIO_PAYLOAD_CACHE: dict | None = None
_INDEX_SERIES_CACHE: dict[str, dict] = {}


def _normalize_list(values) -> list[str]:
    out = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip().upper()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _to_iso_date(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if len(text) >= 10:
        return text[:10]
    return text


def clear_year_result_vs_indices_cache() -> None:
    global _INDEX_OPTIONS_CACHE, _PORTFOLIO_PAYLOAD_CACHE
    with _CACHE_LOCK:
        _INDEX_OPTIONS_CACHE = None
        _PORTFOLIO_PAYLOAD_CACHE = None
        _INDEX_SERIES_CACHE.clear()


def list_index_asset_rollups() -> list[str]:
    global _INDEX_OPTIONS_CACHE
    with _CACHE_LOCK:
        if _INDEX_OPTIONS_CACHE is not None:
            return list(_INDEX_OPTIONS_CACHE)
    snapshot = getattr(SNAPSHOT_STORE, "repository_snapshot_asset_rollup_data", None)
    if snapshot is not None and not snapshot.is_empty():
        try:
            if {"asset_rollup", "type"}.issubset(set(snapshot.columns)):
                options = _normalize_list(
                    snapshot
                    .filter(
                        pl.col("asset_rollup").is_not_null()
                        & (pl.col("type").cast(pl.Utf8).str.to_lowercase() == "index")
                    )
                    .select(pl.col("asset_rollup").cast(pl.Utf8))
                    .unique()
                    .sort("asset_rollup")
                    .get_column("asset_rollup")
                    .to_list()
                )
                with _CACHE_LOCK:
                    _INDEX_OPTIONS_CACHE = list(options)
                return options
        except Exception:
            pass
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            rows = cur.execute(
                """
                SELECT DISTINCT [asset_rollup]
                FROM asset_rollup_data
                WHERE LCase([type])='index'
                  AND [asset_rollup] IS NOT NULL
                ORDER BY [asset_rollup]
                """
            ).fetchall()
        except Exception:
            return []
    options = _normalize_list(row[0] for row in rows)
    with _CACHE_LOCK:
        _INDEX_OPTIONS_CACHE = list(options)
    return options


def _load_index_series_from_snapshot(missing: list[str]) -> dict[str, dict]:
    selected = _normalize_list(missing)
    if not selected:
        return {}
    df = getattr(SNAPSHOT_STORE, "repository_snapshot_historical_close", None)
    if df is None or df.is_empty():
        return {}
    required = {"datum", "asset_rollup", "close_price"}
    if not required.issubset(set(df.columns)):
        return {}
    try:
        raw = (
            df.filter(
                pl.col("asset_rollup").cast(pl.Utf8).str.to_uppercase().is_in(selected)
                & pl.col("datum").is_not_null()
                & pl.col("close_price").is_not_null()
            )
            .select(
                [
                    pl.col("datum"),
                    pl.col("asset_rollup").cast(pl.Utf8).str.to_uppercase().alias("asset_rollup"),
                    pl.col("close_price").cast(pl.Float64, strict=False).alias("close_price"),
                ]
            )
            .sort(["asset_rollup", "datum"])
            .to_dicts()
        )
    except Exception:
        return {}
    raw_by_asset = defaultdict(list)
    for row in raw:
        date_value = _to_iso_date(row.get("datum"))
        asset = str(row.get("asset_rollup") or "").strip().upper()
        close_price = row.get("close_price")
        if date_value and asset and close_price is not None:
            raw_by_asset[asset].append({"date": date_value, "value": float(close_price)})
    loaded = {}
    for asset in selected:
        asset_raw = raw_by_asset.get(asset) or []
        if not asset_raw:
            continue
        loaded[asset] = {
            "id": f"index:{asset}",
            "label": f"{asset} per jaar",
            "color": INDEX_COLORS[0],
            "width": 1.4,
            "points": _yearly_percent_from_value(asset_raw, "value"),
        }
    return loaded


def _load_portfolio_payload() -> dict:
    global _PORTFOLIO_PAYLOAD_CACHE
    with _CACHE_LOCK:
        if _PORTFOLIO_PAYLOAD_CACHE is not None:
            return copy.deepcopy(_PORTFOLIO_PAYLOAD_CACHE)
    payload = build_cash_management_result_chart_payload()
    with _CACHE_LOCK:
        _PORTFOLIO_PAYLOAD_CACHE = copy.deepcopy(payload)
    return payload


def _yearly_percent_from_value(raw_points: list[dict], value_key: str) -> list[dict]:
    bases = {}
    out = []
    for point in raw_points:
        date_value = str(point.get("date") or "")
        if len(date_value) < 4:
            continue
        value = point.get(value_key)
        if value is None:
            continue
        try:
            value = float(value)
        except Exception:
            continue
        year = date_value[:4]
        if year not in bases:
            bases[year] = value
        base = bases[year]
        if abs(base) < 1e-12:
            continue
        out.append({"date": date_value, "y": ((value / base) - 1.0) * 100.0})
    return out


def _portfolio_average_percent_series(raw_points: list[dict], profit_key: str, capital_key: str) -> list[dict]:
    states = {}
    out = []
    for point in raw_points:
        date_value = str(point.get("date") or "")
        if len(date_value) < 4:
            continue
        profit = point.get(profit_key)
        capital = point.get(capital_key)
        if profit is None or capital is None:
            continue
        try:
            profit = float(profit)
            capital = float(capital)
        except Exception:
            continue
        if abs(capital) < 1e-12:
            continue
        year = date_value[:4]
        if year not in states:
            states[year] = {"base_profit": profit, "capital_sum": 0.0, "capital_count": 0}
        state = states[year]
        state["capital_sum"] += capital
        state["capital_count"] += 1
        denominator = state["capital_sum"] / state["capital_count"]
        if abs(denominator) < 1e-12:
            continue
        out.append({"date": date_value, "y": ((profit - state["base_profit"]) / denominator) * 100.0})
    return out


def _build_portfolio_series(payload: dict, selected_portfolio: list[str]) -> list[dict]:
    points = payload.get("points") or []
    selected = {str(value).strip().lower() for value in (selected_portfolio or ["total"])}
    by_date = {}
    brokers_by_date = defaultdict(dict)
    for row in points:
        date_value = row.get("date")
        if not date_value:
            continue
        by_date.setdefault(
            date_value,
            {
                "date": date_value,
                "profit": row.get("total_profit"),
                "capital": row.get("total_value"),
            },
        )
        brokers_by_date[date_value][str(row.get("broker") or "").strip().lower()] = row

    series = []
    if "total" in selected:
        total_raw = [by_date[key] for key in sorted(by_date)]
        series.append(
            {
                "id": "portfolio:total",
                "label": "% pj totaal",
                "color": PORTFOLIO_COLORS["total"],
                "width": 2.1,
                "points": _portfolio_average_percent_series(total_raw, "profit", "capital"),
            }
        )
    for broker in ("degiro", "lynx", "interactive"):
        if broker not in selected:
            continue
        raw = []
        for date_value in sorted(brokers_by_date):
            row = brokers_by_date[date_value].get(broker)
            if not row:
                continue
            raw.append(
                {
                    "date": date_value,
                    "profit": row.get("profit"),
                    "capital": row.get("ending_balance"),
                }
            )
        series.append(
            {
                "id": f"portfolio:{broker}",
                "label": f"% pj {broker}",
                "color": PORTFOLIO_COLORS[broker],
                "width": 1.5,
                "points": _portfolio_average_percent_series(raw, "profit", "capital"),
            }
        )
    return series


def _load_index_series(selected_indices: list[str]) -> list[dict]:
    selected = _normalize_list(selected_indices)
    if not selected:
        return []
    with _CACHE_LOCK:
        missing = [asset for asset in selected if asset not in _INDEX_SERIES_CACHE]

    if missing:
        loaded_from_snapshot = _load_index_series_from_snapshot(missing)
        if loaded_from_snapshot:
            with _CACHE_LOCK:
                _INDEX_SERIES_CACHE.update(copy.deepcopy(loaded_from_snapshot))
            missing = [asset for asset in missing if asset not in loaded_from_snapshot]

    if missing:
        placeholders = ", ".join("?" for _ in missing)
        with get_connection() as conn:
            cur = conn.cursor()
            try:
                rows = cur.execute(
                    f"""
                    SELECT datum, asset_rollup, [close] AS close_price
                    FROM historical_data_correct
                    WHERE asset_rollup IN ({placeholders})
                      AND [close] IS NOT NULL
                    ORDER BY asset_rollup, datum
                    """,
                    missing,
                ).fetchall()
            except Exception:
                rows = cur.execute(
                    f"""
                    SELECT datum, asset_rollup, close_price
                    FROM historical_data_correct
                    WHERE asset_rollup IN ({placeholders})
                      AND close_price IS NOT NULL
                    ORDER BY asset_rollup, datum
                    """,
                    missing,
                ).fetchall()
        if rows:
            raw_by_asset = defaultdict(list)
            for row in rows:
                date_value = _to_iso_date(row[0])
                asset = str(row[1] or "").strip().upper()
                close_price = row[2]
                if not date_value or not asset or close_price is None:
                    continue
                try:
                    value = float(close_price)
                except Exception:
                    continue
                raw_by_asset[asset].append({"date": date_value, "value": value})

            loaded = {}
            for asset in missing:
                raw = sorted(raw_by_asset.get(asset, []), key=lambda point: point["date"])
                if not raw:
                    continue
                loaded[asset] = {
                    "id": f"index:{asset}",
                    "label": f"{asset} per jaar",
                    "color": INDEX_COLORS[0],
                    "width": 1.4,
                    "points": _yearly_percent_from_value(raw, "value"),
                }
            with _CACHE_LOCK:
                _INDEX_SERIES_CACHE.update(copy.deepcopy(loaded))

    out = []
    with _CACHE_LOCK:
        for idx, asset in enumerate(selected):
            item = _INDEX_SERIES_CACHE.get(asset)
            if not item:
                continue
            item = copy.deepcopy(item)
            item["color"] = INDEX_COLORS[idx % len(INDEX_COLORS)]
            out.append(item)
    return out


def build_year_result_vs_indices_payload(
    selected_indices: list[str] | None = None,
    selected_portfolio: list[str] | None = None,
    start_date: str | None = None,
    force_reload: bool = False,
) -> dict:
    if force_reload:
        clear_year_result_vs_indices_cache()
    index_options = list_index_asset_rollups()
    if selected_indices is None:
        selected_indices = index_options[:5]
    else:
        selected_indices = _normalize_list(selected_indices)
    selected_indices = [value for value in selected_indices if value in set(index_options)]
    selected_portfolio = selected_portfolio or ["total"]

    portfolio_payload = _load_portfolio_payload()
    series = _build_portfolio_series(portfolio_payload, selected_portfolio)
    series.extend(_load_index_series(selected_indices))
    start_date = str(start_date or "").strip()
    if start_date:
        for item in series:
            item["points"] = [
                point for point in item.get("points", [])
                if str(point.get("date") or "") >= start_date
            ]
        series = [item for item in series if item.get("points")]

    all_dates = [point["date"] for item in series for point in item.get("points", [])]
    return {
        "series": series,
        "index_options": index_options,
        "selected_indices": selected_indices,
        "selected_portfolio": selected_portfolio,
        "start_date_filter": start_date,
        "stats": {
            "start_date": min(all_dates) if all_dates else None,
            "end_date": max(all_dates) if all_dates else None,
            "series": len(series),
            "points": sum(len(item.get("points", [])) for item in series),
        },
    }

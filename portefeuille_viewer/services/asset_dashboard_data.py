"""Read-only presentation contract for Asset Dashboard; no producers or DB access."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import math

import polars as pl
from portefeuille_viewer.services.asset_dashboard_logic import DashboardAssetLogic


SOURCES = {
    "catalog": "repository_snapshot_active_asset_rollup_data",
    "summary": "snapshot_aandelen_projection_v2",
    "indicator": "snapshot_asset_indicator_live",
    "stocks": "aggregator_snapshot_aandelen_live",
    "options": "aggregator_snapshot_load_open_opties_from_tx_live",
    "sprinters": "aggregator_snapshot_open_sprinters_live",
    "dividend": "repository_snapshot_asset_dividend_calendar",
    "timevalue": "snapshot_optie_timevalue_live",
    "comments": "repository_snapshot_open_optie_comments",
}

# Exact visible column order of the corresponding Single Asset Analyse tables.
# Identifiers, fee helper columns and comment colours are not visible columns.
POSITION_COLUMNS = {
    "stocks": [("broker", "broker", "text"), ("asset_rollup", "asset_rollup", "text"),
               ("koers", "koers", "number"), ("aantal_bezit", "aantal_bezit", "number"),
               ("waarde_bezit", "waarde_bezit", "number")],
    "sprinters": [("broker", "broker", "text"), ("asset_rollup", "asset_rollup", "text"),
                 ("asset_detail", "asset_detail", "text"), ("optie_exp_date", "optie_exp_date", "date"),
                 ("optie_strike", "optie_strike", "number"), ("optie_call_put", "optie_call_put", "text"),
                 ("Koers", "Koers", "number"), ("SomVantransactie_aantal", "SomVantransactie_aantal", "number"),
                 ("sp_result", "sp_result", "number")],
    "options": [("itm", "itm", "text"), ("broker", "broker", "text"), ("asset", "asset_rollup", "text"),
                ("c/p", "optie_call_put", "text"), ("exp date", "optie_exp_date", "date"),
                ("strike", "optie_strike", "number"), ("Koers", "Koers", "number"),
                ("delta", "afwijking_pct", "percent"), ("aantal", "aantal_bezit", "number"),
                ("premie", "premie", "number"), ("result", "totaal_resultaat_optie", "number"),
                ("itm_otm", "itm_otm", "number"), ("tv/u", "time_per_unit", "number"),
                ("time value", "time_value", "number"), ("comment", "optie_comment", "text"),
                ("updated", "optie_comment_updated_at", "text")],
}


def _option_rows(store, asset):
    # Copy of the old UI-private transformation; shared ID generation is reused.
    if not isinstance(getattr(store, SOURCES["options"], None), pl.DataFrame):
        return []
    frame = DashboardAssetLogic(store, asset, 1., load_payoff=False).load_option_open_data()
    if frame.is_empty():
        return []
    frame = frame.filter((pl.col("asset_rollup") == asset) & (pl.col("aantal_bezit") != 0))
    comments = getattr(store, SOURCES["comments"], None)
    latest = {}
    if isinstance(comments, pl.DataFrame) and "uniek_id" in comments.columns:
        if "optie_comment_updated_at" in comments.columns:
            comments = comments.sort("optie_comment_updated_at", descending=True, nulls_last=True)
        for row in comments.to_dicts():
            latest.setdefault(row["uniek_id"], row)
    rows = frame.sort("optie_exp_date").to_dicts()
    for row in rows:
        comment = latest.get(row.get("uniek_id"), {})
        for field in ("optie_comment", "optie_comment_updated_at"):
            if field in comment:
                row[field] = comment[field]
    return rows


def _rows(store, key, asset=None):
    frame = getattr(store, SOURCES[key], None)
    if not isinstance(frame, pl.DataFrame) or frame.is_empty():
        return []
    if asset is not None:
        if "asset_rollup" not in frame.columns:
            return []
        frame = frame.filter(pl.col("asset_rollup") == asset)
    return frame.to_dicts()


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def event_date_display(raw, today=None):
    """One colour policy, evaluated independently for each event date."""
    today = today or date.today()
    day = raw.date() if isinstance(raw, datetime) else raw if isinstance(raw, date) else None
    if day is None and raw:
        for pattern in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
            try:
                day = datetime.strptime(str(raw)[:19] if "%H" in pattern else str(raw), pattern).date()
                break
            except ValueError:
                pass
    colour = None
    if day is None or day < today:
        colour = "#D9D9D9"
    elif (day - today).days <= 7:
        colour = "#FF0000"
    elif (day - today).days <= 30:
        colour = "#FFFF00"
    return {"date": day.strftime("%d-%m-%Y") if day else "—", "background": colour}


def dividend_display(row, today=None):
    """Preserve the legacy missing-amount rule for dividend badges."""
    result = event_date_display(row.get("next_dividend_date"), today)
    if row.get("next_dividend_amount") is None:
        result["background"] = "#D9D9D9"
    return dict(result, amount=row.get("next_dividend_amount"), currency=row.get("ib_currency") or "")


def build_dashboard_payload(store, asset="", status="all"):
    catalog = _rows(store, "catalog")
    if status in {"active", "inactive"}:
        catalog = [row for row in catalog if row.get("status") == status]
    assets = sorted({str(r["asset_rollup"]) for r in catalog if r.get("asset_rollup")
                     and r["asset_rollup"] != "CORRECTIE-BENCHMARK"})
    selected = asset if asset in assets else (assets[0] if assets else "")
    first = lambda key: next(iter(_rows(store, key, selected)), {})
    positions = {key: _rows(store, key, selected) for key in ("stocks", "sprinters")}
    # Match the existing stock table: closed/zero stock positions aren't open holdings.
    positions["stocks"] = [r for r in positions["stocks"] if r.get("aantal_bezit") not in (None, 0)]
    # Same presentation calculation as Single Asset Analyse, including short holdings.
    for row in positions["stocks"]:
        # Access quantities can be Decimal while live quotes are float. Normalize
        # both for this JSON presentation value before multiplying (not afterwards).
        price = json_safe(row.get("koers"))
        quantity = json_safe(row.get("aantal_bezit"))
        row["waarde_bezit"] = price * quantity if price is not None and quantity is not None else None
    positions["options"] = _option_rows(store, selected)
    for key in ("sprinters",):
        positions[key] = [r for r in positions[key]
                          if r.get("SomVantransactie_aantal") not in (None, 0)]
    positions = {key: [{field: row.get(field) for _, field, _ in POSITION_COLUMNS[key]}
                       for row in rows] for key, rows in positions.items()}
    dividend = first("dividend")
    return json_safe({
        "schema_version": 1, "assets": assets, "asset": selected,
        "asset_status": status,
        "reference": first("catalog"), "summary": first("summary"),
        "indicator": first("indicator"), "dividend": dividend,
        "dividend_display": dividend_display(dividend),
        "positions": positions,
        "position_columns": POSITION_COLUMNS,
    })

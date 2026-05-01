from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from portefeuille_viewer.config import get_stockdata_db_path
from portefeuille_viewer.data import repository


HISTORY_COLUMNS = [
    "id",
    "run_id",
    "as_of",
    "input_cutoff_date",
    "created_at",
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
    "theta_score",
    "theta_opportunity_proxy_score",
    "volume_score",
    "confidence_score",
    "reason_1",
    "reason_2",
    "reason_3",
]


PHASE_RANK = {
    "bear_continuation": 0,
    "bear_short_relief": 1,
    "bear_bottom_correction": 2,
    "chop": 3,
    "bull_short_pullback": 4,
    "bear_bottom_reversal": 5,
    "bull_overextended": 6,
    "bull_continuation": 7,
    "bull_top_reversal": 1,
    "high_risk_avoid": -1,
    "insufficient_data": -2,
}


@dataclass(frozen=True)
class AssetIndicatorChangesPayload:
    generated_at: str
    db_path: str
    days: int
    rows_loaded: int
    changes: list[dict[str, Any]]
    summary: dict[str, int]
    error: str = ""


def build_asset_indicator_changes(days: int = 7) -> AssetIndicatorChangesPayload:
    days = max(1, int(days))
    try:
        rows = load_history_rows(days=days)
        changes = build_changes(rows, days=days)
        return AssetIndicatorChangesPayload(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            db_path=str(get_stockdata_db_path() or ""),
            days=days,
            rows_loaded=len(rows),
            changes=changes,
            summary=_summary(changes),
        )
    except Exception as exc:
        return AssetIndicatorChangesPayload(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            db_path=str(get_stockdata_db_path() or ""),
            days=days,
            rows_loaded=0,
            changes=[],
            summary={},
            error=f"{type(exc).__name__}: {exc}",
        )


def load_history_rows(days: int = 7) -> list[dict[str, Any]]:
    # Load a wider window than the display window so every current row can be
    # compared against a prior row even when the previous run is older.
    cutoff = datetime.now() - timedelta(days=max(1, int(days)) + 45)
    with repository.get_stockdata_connection() as conn:
        cursor = conn.cursor()
        existing_cols = {str(row.column_name).lower() for row in cursor.columns(table="asset_indicator_signal_history")}
        columns_to_select = [col for col in HISTORY_COLUMNS if col.lower() in existing_cols]
        select_cols = ", ".join(f"[{col}]" for col in columns_to_select)
        sql = f"""
            SELECT {select_cols}
            FROM asset_indicator_signal_history
            WHERE created_at >= ?
            ORDER BY asset_rollup, created_at, id
        """
        cursor.execute(sql, cutoff)
        columns = [str(desc[0]) for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def build_changes(rows: list[dict[str, Any]], days: int = 7) -> list[dict[str, Any]]:
    cutoff = datetime.now() - timedelta(days=max(1, int(days)))
    by_asset: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        asset = str(row.get("asset_rollup") or "").strip().upper()
        if asset:
            by_asset.setdefault(asset, []).append(row)

    out: list[dict[str, Any]] = []
    for asset, asset_rows in by_asset.items():
        cutoff_rows = [row for row in asset_rows if row.get("input_cutoff_date") is not None]
        if cutoff_rows:
            asset_rows = cutoff_rows
        effective_rows = _latest_rows_per_input_day(asset_rows)
        effective_rows.sort(
            key=lambda r: (_dt_sort_value(r.get("created_at") or r.get("as_of")), int(r.get("id") or 0))
        )
        current = effective_rows[-1] if effective_rows else None
        previous = effective_rows[-2] if len(effective_rows) >= 2 else None
        if current is None:
            continue
        changed_at = _dt_value(current.get("created_at")) or _dt_value(current.get("as_of"))
        if changed_at is None or changed_at < cutoff:
            continue
        row = classify_change(asset, previous, current, changed_at)
        out.append(row)

    out.sort(key=lambda r: (int(r.get("priority") or 0), str(r.get("changed_at") or "")), reverse=True)
    return out


def _latest_rows_per_input_day(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_day: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _input_day_key(row)
        existing = latest_by_day.get(key)
        if existing is None or (
            _dt_sort_value(row.get("created_at") or row.get("as_of")),
            int(row.get("id") or 0),
        ) >= (
            _dt_sort_value(existing.get("created_at") or existing.get("as_of")),
            int(existing.get("id") or 0),
        ):
            latest_by_day[key] = row
    return list(latest_by_day.values())


def _input_day_key(row: dict[str, Any]) -> str:
    value = row.get("input_cutoff_date") or row.get("as_of") or row.get("created_at")
    dt = _dt_value(value)
    if dt is not None:
        return dt.date().isoformat()
    text = str(value or "").strip()
    return text or f"id:{row.get('id')}"


def classify_change(
    asset: str,
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    changed_at: datetime,
) -> dict[str, Any]:
    prev_phase = _text(previous, "asset_fase") if previous else ""
    cur_phase = _text(current, "asset_fase")
    prev_trend = _text(previous, "trend_phase") if previous else ""
    cur_trend = _text(current, "trend_phase")
    prev_action = _text(previous, "primary_action") if previous else ""
    cur_action = _text(current, "primary_action")
    prev_secondary = _text(previous, "secondary_action") if previous else ""
    cur_secondary = _text(current, "secondary_action")

    phase_delta = PHASE_RANK.get(cur_phase, 0) - PHASE_RANK.get(prev_phase, 0)
    direction_delta = _num(current.get("direction_score")) - _num(previous.get("direction_score") if previous else None)
    confidence_delta = _num(current.get("confidence_score")) - _num(previous.get("confidence_score") if previous else None)
    theta_delta = _num(current.get("theta_opportunity_proxy_score")) - _num(
        previous.get("theta_opportunity_proxy_score") if previous else None
    )

    label, impact, priority = _label_change(
        prev_phase=prev_phase,
        cur_phase=cur_phase,
        prev_action=prev_action,
        cur_action=cur_action,
        phase_delta=phase_delta,
        direction_delta=direction_delta,
        confidence_delta=confidence_delta,
        theta_delta=theta_delta,
        previous_exists=previous is not None,
    )

    reasons = _change_reasons(
        prev_phase,
        cur_phase,
        prev_trend,
        cur_trend,
        prev_action,
        cur_action,
        phase_delta,
        direction_delta,
        confidence_delta,
        theta_delta,
        current,
    )

    return {
        "asset_rollup": asset,
        "asset_name": current.get("asset_name") or (previous or {}).get("asset_name") or "",
        "indicator_role": current.get("indicator_role") or "",
        "changed_at": changed_at.isoformat(timespec="seconds"),
        "previous_at": _fmt_dt((previous or {}).get("created_at") or (previous or {}).get("as_of")),
        "current_input_cutoff_date": _fmt_date(current.get("input_cutoff_date") or current.get("as_of")),
        "previous_input_cutoff_date": _fmt_date(
            (previous or {}).get("input_cutoff_date") or (previous or {}).get("as_of")
        ),
        "previous_asset_fase": prev_phase,
        "current_asset_fase": cur_phase,
        "previous_trend_phase": prev_trend,
        "current_trend_phase": cur_trend,
        "previous_action": prev_action,
        "current_action": cur_action,
        "previous_secondary": prev_secondary,
        "current_secondary": cur_secondary,
        "change_label": label,
        "change_impact_score": round(float(impact), 1),
        "priority": int(priority),
        "direction_score": _round_or_blank(current.get("direction_score")),
        "direction_delta": _round_or_blank(direction_delta),
        "confidence_score": _round_or_blank(current.get("confidence_score")),
        "confidence_delta": _round_or_blank(confidence_delta),
        "theta_proxy": _round_or_blank(current.get("theta_opportunity_proxy_score")),
        "theta_delta": _round_or_blank(theta_delta),
        "volume_score": _round_or_blank(current.get("volume_score")),
        "range_position_pct": _round_or_blank(current.get("range_position_pct")),
        "data_quality": current.get("data_quality") or "",
        "change_reason_1": reasons[0],
        "change_reason_2": reasons[1],
        "change_reason_3": reasons[2],
        "current_reason_1": current.get("reason_1") or "",
        "current_reason_2": current.get("reason_2") or "",
        "current_reason_3": current.get("reason_3") or "",
    }


def _label_change(
    *,
    prev_phase: str,
    cur_phase: str,
    prev_action: str,
    cur_action: str,
    phase_delta: float,
    direction_delta: float,
    confidence_delta: float,
    theta_delta: float,
    previous_exists: bool,
) -> tuple[str, float, int]:
    if not previous_exists:
        return "nieuw", 0.0, 20
    if cur_phase == "high_risk_avoid":
        return "sterk_verslechterd", -80.0, 100
    if cur_phase == "bull_top_reversal" and prev_phase != "bull_top_reversal":
        return "sterk_verslechterd", -70.0, 98
    if prev_phase == "bull_overextended" and cur_phase == "bull_top_reversal":
        return "sterk_verslechterd", -85.0, 100
    if cur_phase == "bull_overextended" and prev_phase in {"bull_continuation", "bull_short_pullback"}:
        return "risico_omhoog", -35.0, 88
    if cur_phase == "bear_continuation" and prev_phase != "bear_continuation":
        return "verslechterd", -45.0, 82
    if prev_phase == "bear_short_relief" and cur_phase == "bear_continuation":
        return "verslechterd", -55.0, 86
    if prev_phase == "bear_bottom_correction" and cur_phase == "bear_bottom_reversal":
        return "verbeterd", 55.0, 80
    if prev_phase == "bull_short_pullback" and cur_phase == "bull_continuation":
        return "verbeterd", 45.0, 72
    if prev_phase == "chop" and cur_phase == "bull_continuation":
        return "verbeterd", 40.0, 70
    if cur_action == "theta_harvest" and prev_action != "theta_harvest":
        return "theta_kans_omhoog", max(25.0, theta_delta), 68

    impact = (phase_delta * 18.0) + (direction_delta * 0.35) + (confidence_delta * 0.15) + (theta_delta * 0.10)
    if impact >= 45.0:
        return "sterk_verbeterd", impact, 78
    if impact >= 15.0:
        return "verbeterd", impact, 62
    if impact <= -45.0:
        return "sterk_verslechterd", impact, 92
    if impact <= -15.0:
        return "verslechterd", impact, 74
    if prev_phase != cur_phase or prev_action != cur_action:
        return "gewijzigd", impact, 50
    return "stabiel", impact, 10


def _change_reasons(
    prev_phase: str,
    cur_phase: str,
    prev_trend: str,
    cur_trend: str,
    prev_action: str,
    cur_action: str,
    phase_delta: float,
    direction_delta: float,
    confidence_delta: float,
    theta_delta: float,
    current: dict[str, Any],
) -> tuple[str, str, str]:
    reason_1 = f"Fase: {prev_phase or '-'} -> {cur_phase or '-'}"
    reason_2 = f"Trend: {prev_trend or '-'} -> {cur_trend or '-'}"
    if prev_action != cur_action:
        reason_3 = f"Actie: {prev_action or '-'} -> {cur_action or '-'}"
    elif abs(theta_delta) >= 10.0:
        reason_3 = f"Asset theta proxy delta {theta_delta:+.1f}"
    elif abs(direction_delta) >= 10.0:
        reason_3 = f"Direction delta {direction_delta:+.1f}"
    elif abs(confidence_delta) >= 10.0:
        reason_3 = f"Confidence delta {confidence_delta:+.1f}"
    else:
        reason_3 = str(current.get("reason_1") or "Geen materiele wijziging")
    if phase_delta > 0 and "->" in reason_1:
        reason_1 += " (verbetering)"
    elif phase_delta < 0 and "->" in reason_1:
        reason_1 += " (verslechtering)"
    return reason_1, reason_2, reason_3


def _summary(changes: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {
        "totaal": len(changes),
        "sterk_verbeterd": 0,
        "verbeterd": 0,
        "stabiel": 0,
        "verslechterd": 0,
        "sterk_verslechterd": 0,
        "risico_omhoog": 0,
        "theta_kans_omhoog": 0,
        "gewijzigd": 0,
        "nieuw": 0,
    }
    for row in changes:
        label = str(row.get("change_label") or "")
        out[label] = out.get(label, 0) + 1
    return out


def _text(row: dict[str, Any] | None, key: str) -> str:
    if not row:
        return ""
    return str(row.get(key) or "").strip()


def _num(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _round_or_blank(value: Any) -> float | str:
    if value is None or value == "":
        return ""
    try:
        return round(float(value), 1)
    except Exception:
        return ""


def _dt_value(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _dt_sort_value(value: Any) -> datetime:
    return _dt_value(value) or datetime.min


def _fmt_dt(value: Any) -> str:
    dt = _dt_value(value)
    return "" if dt is None else dt.isoformat(timespec="seconds")


def _fmt_date(value: Any) -> str:
    dt = _dt_value(value)
    if dt is not None:
        return dt.date().isoformat()
    return str(value or "").strip()

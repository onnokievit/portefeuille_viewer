from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portefeuille_viewer.data import repository  # noqa: E402
from portefeuille_viewer.services.asset_indicator_rules import (  # noqa: E402
    ActionInput,
    classify_trend_phase,
    map_scores_to_action,
)


TABLE = "asset_indicator_signal_history"
READ_COLUMNS = [
    "id",
    "data_quality",
    "indicator_role",
    "direction_score",
    "long_term_direction_score",
    "short_term_direction_score",
    "range_position_pct",
    "theta_score",
    "volume_score",
    "asset_fase",
    "trend_phase",
    "primary_action",
    "secondary_action",
    "payload_json",
    "implied_volatility_score",
    "iv_vs_realized_volatility_score",
    "theta_opportunity_proxy_score",
    "choppiness_score",
]
WRITE_COLUMNS = [
    "trend_phase",
    "asset_fase",
    "primary_action",
    "secondary_action",
    "confidence_score",
    "reason_1",
    "reason_2",
    "reason_3",
    "payload_json",
]


def main() -> int:
    args = parse_args()
    rows = load_rows(limit=args.limit)
    updates: list[tuple[Any, ...]] = []
    old_fase = Counter()
    new_fase = Counter()
    old_trend = Counter()
    new_trend = Counter()
    changed_fase = 0
    changed_trend = 0
    changed_action = 0

    for row in rows:
        old_fase[str(row.get("asset_fase") or "")] += 1
        old_trend[str(row.get("trend_phase") or "")] += 1
        trend_phase = classify_trend_phase(
            row.get("long_term_direction_score"),
            row.get("short_term_direction_score"),
            row.get("range_position_pct"),
            data_quality=str(row.get("data_quality") or "ok"),
        )
        decision = map_scores_to_action(
            ActionInput(
                direction_score=row.get("direction_score"),
                volume_score=row.get("volume_score"),
                long_term_direction_score=row.get("long_term_direction_score"),
                short_term_direction_score=row.get("short_term_direction_score"),
                range_position_pct=row.get("range_position_pct"),
                trend_phase=trend_phase,
                theta_score=row.get("theta_score"),
                vulnerability_score=None,
                liquidity_score=None,
                data_quality=str(row.get("data_quality") or "ok"),
                indicator_role=str(row.get("indicator_role") or ""),
                theta_opportunity_proxy_score=row.get("theta_opportunity_proxy_score"),
                implied_volatility_score=row.get("implied_volatility_score"),
                iv_vs_realized_volatility_score=row.get("iv_vs_realized_volatility_score"),
                choppiness_score=row.get("choppiness_score"),
            )
        )
        new_fase[decision.asset_fase] += 1
        new_trend[trend_phase] += 1
        if str(row.get("asset_fase") or "") != decision.asset_fase:
            changed_fase += 1
        if str(row.get("trend_phase") or "") != trend_phase:
            changed_trend += 1
        if str(row.get("primary_action") or "") != decision.primary_action:
            changed_action += 1

        payload_json = update_payload_json(row.get("payload_json"), trend_phase, decision)
        updates.append(
            (
                trend_phase,
                decision.asset_fase,
                decision.primary_action,
                decision.secondary_action,
                decision.confidence_score,
                decision.reason_1,
                decision.reason_2,
                decision.reason_3,
                payload_json,
                row["id"],
            )
        )

    print(f"records_loaded={len(rows)}")
    print(f"changed_fase={changed_fase}")
    print(f"changed_trend={changed_trend}")
    print(f"changed_action={changed_action}")
    print_counter("old_fase", old_fase)
    print_counter("new_fase", new_fase)
    print_counter("old_trend", old_trend)
    print_counter("new_trend", new_trend)

    if not args.apply:
        print("dry_run=1")
        print("Gebruik --apply om de stock-db te updaten.")
        return 0

    updated = apply_updates(updates, batch_size=args.batch_size)
    print(f"dry_run=0")
    print(f"records_updated={updated}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Eenmalige reclassificatie van asset indicator history met 1.4 rules.")
    parser.add_argument("--apply", action="store_true", help="Schrijf de herclassificatie terug naar de stock-db.")
    parser.add_argument("--limit", type=int, default=0, help="Optionele testlimiet; 0 = alle records.")
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


def load_rows(limit: int = 0) -> list[dict[str, Any]]:
    cols = ", ".join(f"[{col}]" for col in READ_COLUMNS)
    top = f"TOP {int(limit)} " if int(limit or 0) > 0 else ""
    sql = f"SELECT {top}{cols} FROM {TABLE} ORDER BY [id]"
    with repository.get_stockdata_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        columns = [str(desc[0]) for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def apply_updates(updates: list[tuple[Any, ...]], batch_size: int) -> int:
    if not updates:
        return 0
    set_clause = ", ".join(f"[{col}] = ?" for col in WRITE_COLUMNS)
    sql = f"UPDATE {TABLE} SET {set_clause} WHERE [id] = ?"
    updated = 0
    with repository.get_stockdata_connection() as conn:
        conn.autocommit = False
        cur = conn.cursor()
        for idx in range(0, len(updates), max(1, int(batch_size))):
            batch = updates[idx : idx + max(1, int(batch_size))]
            cur.executemany(sql, batch)
            conn.commit()
            updated += len(batch)
            print(f"committed={updated}/{len(updates)}")
    return updated


def update_payload_json(payload_json: object, trend_phase: str, decision: object) -> str:
    try:
        payload = json.loads(str(payload_json or "{}"))
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}
    payload.update(
        {
            "trend_phase": trend_phase,
            "asset_fase": decision.asset_fase,
            "primary_action": decision.primary_action,
            "secondary_action": decision.secondary_action,
            "covered_call_delta_min": decision.covered_call_delta_min,
            "covered_call_delta_max": decision.covered_call_delta_max,
            "short_put_delta_min": decision.short_put_delta_min,
            "short_put_delta_max": decision.short_put_delta_max,
            "confidence_score": decision.confidence_score,
            "reason_1": decision.reason_1,
            "reason_2": decision.reason_2,
            "reason_3": decision.reason_3,
        }
    )
    return json.dumps(payload, ensure_ascii=False, default=str)


def print_counter(name: str, counter: Counter) -> None:
    print(f"[{name}]")
    for key, value in counter.most_common():
        print(f"  {key or '<blank>'}: {value}")


if __name__ == "__main__":
    raise SystemExit(main())

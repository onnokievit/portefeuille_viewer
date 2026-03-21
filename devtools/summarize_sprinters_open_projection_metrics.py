from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


LOG_PATH = Path("logs") / "sprinters_open_projection_v2_metrics.jsonl"
WINDOW = 200


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    vals = sorted(float(v) for v in values)
    idx = int(0.95 * (len(vals) - 1))
    return float(vals[idx])


def _summary(samples: list[dict]) -> dict:
    if not samples:
        return {
            "count": 0,
            "recompute_ms_avg": 0.0,
            "recompute_ms_p95": 0.0,
            "recompute_ms_max": 0.0,
            "publish_ms_avg": 0.0,
            "publish_ms_p95": 0.0,
            "publish_ms_max": 0.0,
            "total_ms_avg": 0.0,
            "total_ms_p95": 0.0,
            "total_ms_max": 0.0,
        }
    rec = [float(s.get("recompute_ms", 0.0)) for s in samples]
    pub = [float(s.get("publish_ms", 0.0)) for s in samples]
    tot = [float(s.get("total_ms", 0.0)) for s in samples]
    return {
        "count": len(samples),
        "recompute_ms_avg": round(sum(rec) / len(rec), 3),
        "recompute_ms_p95": round(_p95(rec), 3),
        "recompute_ms_max": round(max(rec), 3),
        "publish_ms_avg": round(sum(pub) / len(pub), 3),
        "publish_ms_p95": round(_p95(pub), 3),
        "publish_ms_max": round(max(pub), 3),
        "total_ms_avg": round(sum(tot) / len(tot), 3),
        "total_ms_p95": round(_p95(tot), 3),
        "total_ms_max": round(max(tot), 3),
    }


def _summary_by_reason(samples: list[dict]) -> dict[str, dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in samples:
        groups[str(s.get("reason") or "unknown")].append(s)
    return {reason: _summary(rows) for reason, rows in sorted(groups.items(), key=lambda x: x[0])}


def main() -> None:
    if not LOG_PATH.exists():
        print(f"metrics log ontbreekt: {LOG_PATH}")
        return
    lines = [ln for ln in LOG_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows = []
    for ln in lines[-WINDOW:]:
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    print(f"log={LOG_PATH} window={WINDOW} parsed={len(rows)}")
    print("overall=", _summary(rows))
    print("by_reason=", _summary_by_reason(rows))
    if rows:
        print("last=", rows[-1])


if __name__ == "__main__":
    main()


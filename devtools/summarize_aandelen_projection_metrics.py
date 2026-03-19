from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


LOG_PATH = Path("logs") / "aandelen_projection_v2_metrics.jsonl"
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
            "queue_wait_ms_avg": 0.0,
            "queue_wait_ms_p95": 0.0,
            "queue_wait_ms_max": 0.0,
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
    q = [float(s.get("queue_wait_ms", 0.0)) for s in samples]
    rec = [float(s.get("recompute_ms", 0.0)) for s in samples]
    pub = [float(s.get("publish_ms", 0.0)) for s in samples]
    tot = [float(s.get("total_ms", 0.0)) for s in samples]
    return {
        "count": len(samples),
        "queue_wait_ms_avg": round(sum(q) / len(q), 3),
        "queue_wait_ms_p95": round(_p95(q), 3),
        "queue_wait_ms_max": round(max(q), 3),
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


def _slowest(samples: list[dict], top_n: int = 10) -> list[dict]:
    rows = sorted(samples, key=lambda s: float(s.get("total_ms", 0.0)), reverse=True)
    return rows[:top_n]


def _bucket_patch_size(v: int) -> str:
    if v <= 0:
        return "0"
    if v <= 50:
        return "1-50"
    if v <= 200:
        return "51-200"
    if v <= 500:
        return "201-500"
    if v <= 1000:
        return "501-1000"
    return "1000+"


def _summary_by_patch_bucket(samples: list[dict]) -> dict[str, dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in samples:
        b = _bucket_patch_size(int(s.get("patch_size", 0) or 0))
        groups[b].append(s)
    order = ["0", "1-50", "51-200", "201-500", "501-1000", "1000+"]
    out = {}
    for b in order:
        rows = groups.get(b)
        if rows:
            out[b] = _summary(rows)
    return out


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
    print("by_patch_bucket=", _summary_by_patch_bucket(rows))
    slow = _slowest(rows, top_n=10)
    if slow:
        print("slowest_top10=")
        for i, s in enumerate(slow, start=1):
            print(
                f"{i:2d}. ts={s.get('ts')} reason={s.get('reason')} total_ms={s.get('total_ms')} "
                f"q_ms={s.get('queue_wait_ms', 0)} rec_ms={s.get('recompute_ms')} pub_ms={s.get('publish_ms')} "
                f"patch={s.get('patch_size')} rows={s.get('snapshot_rows')} version={s.get('version')}"
            )
    if rows:
        print("last=", rows[-1])


if __name__ == "__main__":
    main()

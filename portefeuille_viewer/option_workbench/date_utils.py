from __future__ import annotations

from datetime import date


def month_codes_from_today(horizon_months: int, today: date | None = None) -> list[str]:
    base = today or date.today()
    count = max(1, int(horizon_months or 1))
    out: list[str] = []
    year = base.year
    month = base.month
    for _ in range(count):
        out.append(f"{year:04d}{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return out


def parse_ib_expiry(raw: object) -> date | None:
    text = str(raw or "").strip()
    if len(text) < 8 or not text[:8].isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


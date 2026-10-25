"""Provider-neutral financial facts; UTC observations, explicit units and periods."""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
import json
import math


def utcnow():
    # Access DATETIME has no timezone: all new framework timestamps are UTC.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def clean(value):
    """Make provider responses JSON-safe without turning absent numbers into zero."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, 'item'):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def encode(value):
    return json.dumps(clean(value), sort_keys=True, ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def as_date(value):
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class FinancialFact:
    source: str
    subject: str
    category: str
    metric: str
    period_key: str
    value: object
    period_end: date | None = None
    period_kind: str = 'unknown'
    currency: str = ''
    unit: str = ''
    basis: str = 'unknown'
    source_at: datetime | None = None
    context: dict = field(default_factory=dict)
    subject_type: str = 'asset'

    @property
    def key(self):
        return digest([self.source, self.subject_type, self.subject, self.category,
                       self.metric, self.period_key, self.basis, self.currency, self.unit])

    @property
    def payload(self):
        return dict(value=clean(self.value), context=clean(self.context))


@dataclass
class FetchResult:
    facts: list[FinancialFact] = field(default_factory=list)
    raw: object = None
    status: str = 'ok'
    message: str = ''


def surprise(actual, consensus, *, unit='', tolerance=1e-8):
    """No percentage surprise for zero/negative denominators; margins use pp."""
    actual, consensus = number(actual), number(consensus)
    if actual is None or consensus is None:
        return dict(status='not_comparable', reason='missing_value')
    delta = actual-consensus
    verdict = 'meet' if abs(delta) <= tolerance else 'beat' if delta > 0 else 'miss'
    result = dict(status='comparable', verdict=verdict, actual=actual, consensus=consensus,
                  difference=delta)
    if unit == 'percent':
        result['difference_pp'] = delta
    elif consensus > 0:
        result['difference_pct'] = 100*delta/consensus
    return result

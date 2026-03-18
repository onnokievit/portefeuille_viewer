from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    PRICE_TICK = "price_tick"
    OPTION_TICK = "option_tick"
    TRANSACTION_COMMITTED = "transaction_committed"
    SNAPSHOT_REFRESH = "snapshot_refresh"
    DB_CHANGED = "db_changed"
    REBUILD_REQUESTED = "rebuild_requested"
    CUSTOM = "custom"


@dataclass(slots=True, frozen=True)
class Event:
    ts: datetime
    event_type: EventType
    key: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"


@dataclass(slots=True, frozen=True)
class CellChange:
    row_id: str
    field: str
    value: Any


@dataclass(slots=True, frozen=True)
class ViewPatch:
    view: str
    version: int
    changes: tuple[CellChange, ...]


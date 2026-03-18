from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class SnapshotInitPayload:
    view: str
    version: int
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class CellPatchPayload:
    row_id: str
    field: str
    value: Any


@dataclass(slots=True, frozen=True)
class ViewPatchPayload:
    view: str
    version: int
    changes: list[CellPatchPayload] = field(default_factory=list)


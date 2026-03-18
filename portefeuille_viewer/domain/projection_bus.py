from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol


class Projection(Protocol):
    name: str
    depends_on: set[str]

    def recompute(self, changed_keys: set[str]) -> None:
        ...


@dataclass(slots=True)
class ProjectionRunResult:
    projection_name: str
    changed_keys: int
    success: bool
    error: str | None = None


class ProjectionBus:
    """Simple in-process projection coordinator."""

    def __init__(self):
        self._lock = threading.Lock()
        self._projections: dict[str, Projection] = {}

    def register(self, projection: Projection) -> None:
        with self._lock:
            self._projections[projection.name] = projection

    def unregister(self, name: str) -> None:
        with self._lock:
            self._projections.pop(name, None)

    def run(self, changed_keys: set[str], topic: str | None = None) -> list[ProjectionRunResult]:
        with self._lock:
            projections = list(self._projections.values())
        results: list[ProjectionRunResult] = []
        for projection in projections:
            if topic and projection.depends_on and topic not in projection.depends_on:
                continue
            try:
                projection.recompute(changed_keys)
                results.append(
                    ProjectionRunResult(
                        projection_name=projection.name,
                        changed_keys=len(changed_keys),
                        success=True,
                    )
                )
            except Exception as exc:
                results.append(
                    ProjectionRunResult(
                        projection_name=projection.name,
                        changed_keys=len(changed_keys),
                        success=False,
                        error=str(exc),
                    )
                )
        return results

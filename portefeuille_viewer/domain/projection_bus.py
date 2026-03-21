from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol
import inspect
import time


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
    duration_ms: float = 0.0
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
            t0 = time.perf_counter()
            try:
                recompute_fn = getattr(projection, "recompute", None)
                if recompute_fn is None:
                    raise AttributeError(f"{projection.name} has no recompute()")
                try:
                    sig = inspect.signature(recompute_fn)
                    # Bound methods:
                    # - recompute() -> 0 params
                    # - recompute(changed_keys) -> 1 param
                    if len(sig.parameters) == 0:
                        recompute_fn()
                    else:
                        recompute_fn(changed_keys)
                except (TypeError, ValueError):
                    # Fallback: most projections in current codebase accept changed_keys.
                    recompute_fn(changed_keys)
                results.append(
                    ProjectionRunResult(
                        projection_name=projection.name,
                        changed_keys=len(changed_keys),
                        success=True,
                        duration_ms=(time.perf_counter() - t0) * 1000.0,
                    )
                )
            except Exception as exc:
                results.append(
                    ProjectionRunResult(
                        projection_name=projection.name,
                        changed_keys=len(changed_keys),
                        success=False,
                        duration_ms=(time.perf_counter() - t0) * 1000.0,
                        error=str(exc),
                    )
                )
        return results

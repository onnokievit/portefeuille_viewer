from __future__ import annotations

from datetime import datetime
from typing import Callable

from .events import Event, EventType
from .projection_bus import ProjectionBus, ProjectionRunResult
from .state_store import StateStore


class EngineCoreRuntime:
    """
    Minimal orchestration layer for Event + StateStore + ProjectionBus.

    This is intentionally lightweight and opt-in (feature-flagged wiring),
    so existing app flows remain unchanged unless explicitly enabled.
    """

    def __init__(
        self,
        enabled: bool = False,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.state_store = StateStore()
        self.projection_bus = ProjectionBus()
        self._log = logger or (lambda msg: print(msg))

    def register_projection(self, projection) -> None:
        self.projection_bus.register(projection)
        if self.enabled:
            self._log(f"[engine-core] registered projection: {projection.name}")

    def unregister_projection(self, name: str) -> None:
        self.projection_bus.unregister(name)
        if self.enabled:
            self._log(f"[engine-core] unregistered projection: {name}")

    def publish_event(self, event: Event, topic: str | None = None) -> list[ProjectionRunResult]:
        changed_keys = self.state_store.apply(event)
        if not self.enabled:
            return []
        return self.projection_bus.run(changed_keys, topic=topic)

    def publish_snapshot_update(self, snapshot_key: str, source: str = "snapshot_store") -> list[ProjectionRunResult]:
        event = Event(
            ts=datetime.now(),
            event_type=EventType.SNAPSHOT_REFRESH,
            key=str(snapshot_key),
            payload={"namespace": "snapshots", "value": True},
            source=source,
        )
        results = self.publish_event(event, topic=str(snapshot_key))
        if self.enabled and results:
            ok = sum(1 for r in results if r.success)
            fail = len(results) - ok
            self._log(
                f"[engine-core] topic={snapshot_key} projections={len(results)} ok={ok} failed={fail}"
            )
        return results

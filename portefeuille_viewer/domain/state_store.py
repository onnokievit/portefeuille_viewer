from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime
from typing import Any

from .events import Event


class StateStore:
    """
    Minimal event-driven state store.

    - Keeps a versioned bucket per namespace.
    - Returns changed entity keys so projections can recompute incrementally.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, Any]] = defaultdict(dict)
        self._versions: dict[str, int] = defaultdict(int)
        self._updated_at: dict[str, datetime] = {}

    def apply(self, event: Event) -> set[str]:
        """
        Apply one event and return changed keys.

        Convention:
        - event.payload may include:
          - namespace: str (default "default")
          - values: dict[str, Any] (bulk updates)
          - value: Any (single update)
        """
        namespace = str(event.payload.get("namespace") or "default")
        changed_keys: set[str] = set()
        with self._lock:
            bucket = self._state[namespace]
            values = event.payload.get("values")
            if isinstance(values, dict):
                for key, value in values.items():
                    skey = str(key)
                    if bucket.get(skey) != value:
                        bucket[skey] = value
                        changed_keys.add(skey)
            else:
                if event.key:
                    skey = str(event.key)
                    value = event.payload.get("value")
                    if bucket.get(skey) != value:
                        bucket[skey] = value
                        changed_keys.add(skey)
            if changed_keys:
                self._versions[namespace] += 1
                self._updated_at[namespace] = event.ts
        return changed_keys

    def snapshot(self, namespace: str = "default") -> dict[str, Any]:
        with self._lock:
            return dict(self._state.get(namespace, {}))

    def version(self, namespace: str = "default") -> int:
        with self._lock:
            return int(self._versions.get(namespace, 0))

    def updated_at(self, namespace: str = "default") -> datetime | None:
        with self._lock:
            return self._updated_at.get(namespace)


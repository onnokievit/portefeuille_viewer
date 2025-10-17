import time

import pytest


def test_safe_write_emits_and_sets_attr(monkeypatch):
    # Local import to ensure we use the real singleton
    from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
    import portefeuille_viewer.signals as signals_mod

    called = []

    def fake_queued_emit(key):
        called.append(key)

    # Patch the queued emit helper so we don't rely on Qt eventloop
    monkeypatch.setattr(signals_mod.signals, "queued_emit_snapshotUpdated", fake_queued_emit)

    # Ensure the attribute is not present initially (clean test runs)
    if hasattr(SNAPSHOT_STORE, "__test_snapshot_key"):
        delattr(SNAPSHOT_STORE, "__test_snapshot_key")

    # Call safe_write
    SNAPSHOT_STORE.safe_write("__test_snapshot_key", 42)

    # Attribute was written
    assert getattr(SNAPSHOT_STORE, "__test_snapshot_key") == 42

    # Timestamp recorded
    assert "__test_snapshot_key" in SNAPSHOT_STORE._last_update_ts
    ts = SNAPSHOT_STORE._last_update_ts["__test_snapshot_key"]
    assert isinstance(ts, float)
    assert time.time() - ts < 5.0

    # queued emit helper called with the correct key
    assert called == ["__test_snapshot_key"]

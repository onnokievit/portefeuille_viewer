import time
from PySide6.QtCore import QCoreApplication


def test_snapshot_updated_signal_received(qtbot):
    """Integration-style test: connect a real slot to signals.snapshotUpdated and
    ensure a safe_write triggers the slot via the queued emit helper.
    Requires pytest-qt (qtbot fixture) to process Qt events.
    """
    from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
    from portefeuille_viewer.signals import signals

    received = []

    def slot(key):
        received.append(key)

    # connect real slot
    signals.snapshotUpdated.connect(slot)

    # ensure Qt app exists
    app = QCoreApplication.instance() or QCoreApplication([])

    # perform safe write which uses queued_emit (QTimer.singleShot -> queued emit)
    SNAPSHOT_STORE.safe_write("__integration_test_key", 123)

    # Process events for a short while to let the queued emit fire
    deadline = time.time() + 2.0
    while time.time() < deadline and not received:
        app.processEvents()
        time.sleep(0.01)

    signals.snapshotUpdated.disconnect(slot)

    assert received == ["__integration_test_key"]

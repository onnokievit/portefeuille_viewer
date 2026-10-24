"""One shared maintenance pipeline at a time, including all its temp-table steps."""
from portefeuille_viewer.config import get_stockdata_db_path
from portefeuille_viewer.config.local_runtime import maintenance_lease


def release_task(owner, *args):
    lease = getattr(owner, '_pv_task_lease', None)
    if lease is not None:
        lease.release()
        owner._pv_task_lease = None


def claim_task(owner):
    if getattr(owner, '_pv_task_lease', None) is not None:
        return True
    lease = maintenance_lease(get_stockdata_db_path())
    if not lease.acquire():
        message = 'Gedeelde update draait al in een andere appinstantie; deze aanvraag wordt overgeslagen.'
        print('[shared-task] ' + message)
        for name in ('output', 'progress'):
            signal = getattr(owner, name, None)
            if signal is not None:
                signal.emit(message)
        return False
    owner._pv_task_lease = lease
    return True


def coordinate_runner(owner, *, global_price_signals=False):
    if global_price_signals:
        from portefeuille_viewer.signals import signals
        signals.priceUpdateFinished.connect(lambda *a: release_task(owner))
        signals.priceUpdateFailed.connect(lambda *a: release_task(owner))
    else:
        owner.finished.connect(lambda *a: release_task(owner))
        owner.failed.connect(lambda *a: release_task(owner))

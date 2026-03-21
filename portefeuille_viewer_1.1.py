import sys  
import os
import json
import threading
from collections import deque
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QTimer, qInstallMessageHandler
import inspect
from portefeuille_viewer.signals import signals

# Importeer hoofdvenster en benodigde modules
from portefeuille_viewer.ui_logica.main_window_logica import MainWindow
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data import repository
from portefeuille_viewer.services.price_feed import PriceFeedService
from portefeuille_viewer.services.historical_price_update_runner import HistoricalPriceUpdateRunner
from portefeuille_viewer.services.historical_price_update_runner import STOCKDATA_DB_PATH
from portefeuille_viewer.services.state_engine_runner import StateEngineRunner
from portefeuille_viewer.services.option_timevalue_service import OptionTimevalueService
from portefeuille_viewer.services.db_migration_service import DbMigrationService
from portefeuille_viewer.domain.portfolio_engine import PortfolioEngine
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.live_aggregator_aandelen import LiveAggregatorAandelen
from portefeuille_viewer.data.live_aggregator_opties import LiveAggregatorOpties
from portefeuille_viewer.data.live_aggregator_asset_prices import start_live_price_updater
from portefeuille_viewer.data.test_order_repository import flush_dirty_test_orders_to_db, load_test_orders_cache_from_db
from portefeuille_viewer.projections import (
    AandelenProjectionV2,
    OptiesOpenProjectionV2,
    OptieTijdswaardeProjectionV2,
    SprintersOpenProjectionV2,
)

# from portefeuille_viewer.data import live_aggregator_asset_rollup_data
import time

# Qt warning filter: onderdruk specifieke QSortFilterProxyModel warning
def qt_message_handler(mode, context, message):
    if "QSortFilterProxyModel: index from wrong model passed to mapToSource" in message:
        return
    print(message)

qInstallMessageHandler(qt_message_handler)

# Forceer Python om deze map als eerste te gebruiken
#sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(inspect.getfile(inspect.currentframe())))

print("✅ Repository geladen uit:", repository.__file__)


# Persistent aggregators for the whole app
live_aggregator_aandelen = LiveAggregatorAandelen()
live_aggregator_opties = LiveAggregatorOpties()
ENABLE_AANDELEN_PROJECTION_V2 = os.getenv("USE_AANDELEN_PROJECTION_V2", "0").strip() == "1"
aandelen_projection_v2 = AandelenProjectionV2() if ENABLE_AANDELEN_PROJECTION_V2 else None
ENABLE_OPTIES_OPEN_PROJECTION_V2 = os.getenv("USE_OPTIES_OPEN_PROJECTION_V2", "1").strip() == "1"
opties_open_projection_v2 = OptiesOpenProjectionV2() if ENABLE_OPTIES_OPEN_PROJECTION_V2 else None
ENABLE_OPTIE_TIJDSWAARDE_PROJECTION_V2 = os.getenv("USE_OPTIE_TIJDSWAARDE_PROJECTION_V2", "1").strip() == "1"
optie_tijdswaarde_projection_v2 = (
    OptieTijdswaardeProjectionV2() if ENABLE_OPTIE_TIJDSWAARDE_PROJECTION_V2 else None
)
_AANDELEN_PROJECTION_METRICS = deque(maxlen=200)
_AANDELEN_PROJECTION_METRICS_LOG = Path("logs") / "aandelen_projection_v2_metrics.jsonl"
_OPTIES_OPEN_PROJECTION_METRICS = deque(maxlen=200)
_OPTIES_OPEN_PROJECTION_METRICS_LOG = Path("logs") / "opties_open_projection_v2_metrics.jsonl"
_OPTIE_TIJDSWAARDE_PROJECTION_METRICS = deque(maxlen=200)
_OPTIE_TIJDSWAARDE_PROJECTION_METRICS_LOG = Path("logs") / "optie_tijdswaarde_projection_v2_metrics.jsonl"
ENABLE_SPRINTERS_OPEN_PROJECTION_V2 = os.getenv("USE_SPRINTERS_OPEN_PROJECTION_V2", "1").strip() == "1"
sprinters_open_projection_v2 = (
    SprintersOpenProjectionV2() if ENABLE_SPRINTERS_OPEN_PROJECTION_V2 else None
)
_SPRINTERS_OPEN_PROJECTION_METRICS = deque(maxlen=200)
_SPRINTERS_OPEN_PROJECTION_METRICS_LOG = Path("logs") / "sprinters_open_projection_v2_metrics.jsonl"
_AANDELEN_PROJECTION_ASYNC_ENABLED = False
_AANDELEN_PROJECTION_REQ_LOCK = threading.Lock()
_AANDELEN_PROJECTION_PENDING_LOCK = threading.Lock()
_AANDELEN_PROJECTION_INFLIGHT = False
_AANDELEN_PROJECTION_QUEUED_REQ: dict | None = None
_AANDELEN_PROJECTION_PENDING_RESULT: dict | None = None


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    vals = sorted(float(v) for v in values)
    idx = int(0.95 * (len(vals) - 1))
    return float(vals[idx])


def _metrics_summary(samples: list[dict]) -> dict:
    if not samples:
        return {
            "count": 0,
            "queue_wait_ms_avg": 0.0,
            "queue_wait_ms_p95": 0.0,
            "queue_wait_ms_max": 0.0,
            "recompute_ms_avg": 0.0,
            "recompute_ms_p95": 0.0,
            "recompute_ms_max": 0.0,
            "publish_ms_avg": 0.0,
            "publish_ms_p95": 0.0,
            "publish_ms_max": 0.0,
            "total_ms_avg": 0.0,
            "total_ms_p95": 0.0,
            "total_ms_max": 0.0,
        }
    queue_wait = [float(s.get("queue_wait_ms", 0.0)) for s in samples]
    recompute = [float(s.get("recompute_ms", 0.0)) for s in samples]
    publish = [float(s.get("publish_ms", 0.0)) for s in samples]
    total = [float(s.get("total_ms", 0.0)) for s in samples]
    return {
        "count": len(samples),
        "queue_wait_ms_avg": round(sum(queue_wait) / len(queue_wait), 3),
        "queue_wait_ms_p95": round(_p95(queue_wait), 3),
        "queue_wait_ms_max": round(max(queue_wait), 3),
        "recompute_ms_avg": round(sum(recompute) / len(recompute), 3),
        "recompute_ms_p95": round(_p95(recompute), 3),
        "recompute_ms_max": round(max(recompute), 3),
        "publish_ms_avg": round(sum(publish) / len(publish), 3),
        "publish_ms_p95": round(_p95(publish), 3),
        "publish_ms_max": round(max(publish), 3),
        "total_ms_avg": round(sum(total) / len(total), 3),
        "total_ms_p95": round(_p95(total), 3),
        "total_ms_max": round(max(total), 3),
    }


def _append_metrics_log(sample: dict) -> None:
    try:
        _AANDELEN_PROJECTION_METRICS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _AANDELEN_PROJECTION_METRICS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _append_opties_metrics_log(sample: dict) -> None:
    try:
        _OPTIES_OPEN_PROJECTION_METRICS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _OPTIES_OPEN_PROJECTION_METRICS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _append_optie_tijdswaarde_metrics_log(sample: dict) -> None:
    try:
        _OPTIE_TIJDSWAARDE_PROJECTION_METRICS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _OPTIE_TIJDSWAARDE_PROJECTION_METRICS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _append_sprinters_metrics_log(sample: dict) -> None:
    try:
        _SPRINTERS_OPEN_PROJECTION_METRICS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _SPRINTERS_OPEN_PROJECTION_METRICS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _publish_aandelen_projection_result(result: dict):
    if aandelen_projection_v2 is None:
        return
    t_pub0 = time.perf_counter()
    try:
        snapshot_df = result["snapshot_df"]
        patch_list = result["patch_list"]
        SNAPSHOT_STORE.safe_write("snapshot_aandelen_projection_v2", snapshot_df)
        SNAPSHOT_STORE.safe_write(
            "snapshot_aandelen_projection_v2_patch",
            patch_list,
        )
        t_pub1 = time.perf_counter()
        publish_ms = round((t_pub1 - t_pub0) * 1000.0, 3)
        enqueue_ts = float(result.get("enqueue_ts", t_pub0))
        total_ms = round((t_pub1 - enqueue_ts) * 1000.0, 3)
        sample = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": str(result.get("reason", "unknown")),
            "changed_keys_count": int(result.get("changed_keys_count", 0)),
            "queue_wait_ms": round(float(result.get("queue_wait_ms", 0.0)), 3),
            "inflight": bool(result.get("inflight", False)),
            "recompute_ms": round(float(result.get("recompute_ms", 0.0)), 3),
            "publish_ms": publish_ms,
            "total_ms": total_ms,
            "patch_size": len(patch_list),
            "snapshot_rows": snapshot_df.height if snapshot_df is not None else 0,
            "version": aandelen_projection_v2.version(),
        }
        _AANDELEN_PROJECTION_METRICS.append(sample)
        samples = list(_AANDELEN_PROJECTION_METRICS)
        metrics_payload = {
            "last": sample,
            "summary": _metrics_summary(samples),
            "samples": samples,
        }
        SNAPSHOT_STORE.safe_write("snapshot_aandelen_projection_v2_metrics", metrics_payload)
        _append_metrics_log(sample)
        meta = result.get("meta") or aandelen_projection_v2.meta()
        meta["reason"] = result.get("reason", "unknown")
        meta["metrics"] = {
            "last": sample,
            "summary": metrics_payload["summary"],
        }
        SNAPSHOT_STORE.safe_write("snapshot_aandelen_projection_v2_meta", meta)
        print(
            f"[projection-v2-metrics] reason={sample['reason']} queue_wait_ms={sample['queue_wait_ms']:.1f} "
            f"recompute_ms={sample['recompute_ms']:.1f} publish_ms={publish_ms:.1f} "
            f"total_ms={total_ms:.1f} patch={sample['patch_size']} rows={sample['snapshot_rows']} inflight={sample['inflight']}"
        )
    except Exception as exc:
        print(f"[projection-v2] aandelen refresh failed: {exc}")


def _run_aandelen_projection_compute(request: dict):
    global _AANDELEN_PROJECTION_PENDING_RESULT, _AANDELEN_PROJECTION_INFLIGHT, _AANDELEN_PROJECTION_QUEUED_REQ
    if aandelen_projection_v2 is None:
        return
    enqueue_ts = float(request.get("enqueue_ts", time.perf_counter()))
    queue_wait_ms = round((time.perf_counter() - enqueue_ts) * 1000.0, 3)
    try:
        t0 = time.perf_counter()
        aandelen_projection_v2.recompute(request.get("changed_keys") or set())
        t1 = time.perf_counter()
        result = {
            "reason": request.get("reason", "unknown"),
            "changed_keys_count": len(request.get("changed_keys") or set()),
            "enqueue_ts": enqueue_ts,
            "queue_wait_ms": queue_wait_ms,
            "recompute_ms": round((t1 - t0) * 1000.0, 3),
            "snapshot_df": aandelen_projection_v2.snapshot(),
            "patch_list": aandelen_projection_v2.last_patch() or [],
            "meta": aandelen_projection_v2.meta(),
            "inflight": True,
        }
        with _AANDELEN_PROJECTION_PENDING_LOCK:
            _AANDELEN_PROJECTION_PENDING_RESULT = result
        signals.queued_emit_projectionPublishTick("aandelen_v2")
    except Exception as exc:
        print(f"[projection-v2] aandelen compute failed: {exc}")
    finally:
        with _AANDELEN_PROJECTION_REQ_LOCK:
            next_req = _AANDELEN_PROJECTION_QUEUED_REQ
            _AANDELEN_PROJECTION_QUEUED_REQ = None
            if next_req is None:
                _AANDELEN_PROJECTION_INFLIGHT = False
            else:
                th = threading.Thread(target=_run_aandelen_projection_compute, args=(next_req,), daemon=True)
                th.start()


def _drain_aandelen_projection_pending():
    global _AANDELEN_PROJECTION_PENDING_RESULT
    if aandelen_projection_v2 is None:
        return
    with _AANDELEN_PROJECTION_PENDING_LOCK:
        result = _AANDELEN_PROJECTION_PENDING_RESULT
        _AANDELEN_PROJECTION_PENDING_RESULT = None
    if result is None:
        return
    _publish_aandelen_projection_result(result)


def refresh_aandelen_projection(reason: str, changed_keys: set[str] | None = None, force_sync: bool = False):
    global _AANDELEN_PROJECTION_INFLIGHT, _AANDELEN_PROJECTION_QUEUED_REQ
    if aandelen_projection_v2 is None:
        return
    req = {
        "reason": str(reason),
        "changed_keys": set(changed_keys or set()),
        "enqueue_ts": time.perf_counter(),
    }
    if force_sync or not _AANDELEN_PROJECTION_ASYNC_ENABLED:
        _run_aandelen_projection_compute(req)
        _drain_aandelen_projection_pending()
        return

    with _AANDELEN_PROJECTION_REQ_LOCK:
        if _AANDELEN_PROJECTION_INFLIGHT:
            _AANDELEN_PROJECTION_QUEUED_REQ = req
            return
        _AANDELEN_PROJECTION_INFLIGHT = True
        th = threading.Thread(target=_run_aandelen_projection_compute, args=(req,), daemon=True)
        th.start()


def refresh_opties_open_projection(reason: str):
    if opties_open_projection_v2 is None:
        return
    try:
        t0 = time.perf_counter()
        opties_open_projection_v2.recompute()
        snapshot_df = opties_open_projection_v2.snapshot()
        patch_list = opties_open_projection_v2.last_patch() or []
        t1 = time.perf_counter()
        SNAPSHOT_STORE.safe_write("snapshot_opties_open_projection_v2", snapshot_df)
        SNAPSHOT_STORE.safe_write("snapshot_opties_open_projection_v2_patch", patch_list)
        t2 = time.perf_counter()
        recompute_ms = round((t1 - t0) * 1000.0, 3)
        publish_ms = round((t2 - t1) * 1000.0, 3)
        total_ms = round((t2 - t0) * 1000.0, 3)
        sample = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": str(reason),
            "recompute_ms": recompute_ms,
            "publish_ms": publish_ms,
            "total_ms": total_ms,
            "patch_size": len(patch_list),
            "snapshot_rows": snapshot_df.height if snapshot_df is not None else 0,
            "version": opties_open_projection_v2.version(),
        }
        _OPTIES_OPEN_PROJECTION_METRICS.append(sample)
        samples = list(_OPTIES_OPEN_PROJECTION_METRICS)
        metrics_payload = {"last": sample, "summary": _metrics_summary(samples), "samples": samples}
        SNAPSHOT_STORE.safe_write("snapshot_opties_open_projection_v2_metrics", metrics_payload)
        _append_opties_metrics_log(sample)
        meta = opties_open_projection_v2.meta()
        meta["reason"] = reason
        meta["metrics"] = {"last": sample, "summary": metrics_payload["summary"]}
        SNAPSHOT_STORE.safe_write("snapshot_opties_open_projection_v2_meta", meta)
        print(
            f"[opties-projection-v2-metrics] reason={reason} recompute_ms={recompute_ms:.1f} "
            f"publish_ms={publish_ms:.1f} total_ms={total_ms:.1f} patch={sample['patch_size']} rows={sample['snapshot_rows']}"
        )
    except Exception as exc:
        print(f"[opties-projection-v2] refresh failed: {exc}")


def refresh_optie_tijdswaarde_projection(reason: str):
    if optie_tijdswaarde_projection_v2 is None:
        return
    try:
        t0 = time.perf_counter()
        optie_tijdswaarde_projection_v2.recompute()
        snapshot_df = optie_tijdswaarde_projection_v2.snapshot()
        patch_list = optie_tijdswaarde_projection_v2.last_patch() or []
        t1 = time.perf_counter()
        SNAPSHOT_STORE.safe_write("snapshot_optie_tijdswaarde_projection_v2", snapshot_df)
        SNAPSHOT_STORE.safe_write("snapshot_optie_tijdswaarde_projection_v2_patch", patch_list)
        t2 = time.perf_counter()
        recompute_ms = round((t1 - t0) * 1000.0, 3)
        publish_ms = round((t2 - t1) * 1000.0, 3)
        total_ms = round((t2 - t0) * 1000.0, 3)
        sample = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": str(reason),
            "recompute_ms": recompute_ms,
            "publish_ms": publish_ms,
            "total_ms": total_ms,
            "patch_size": len(patch_list),
            "snapshot_rows": snapshot_df.height if snapshot_df is not None else 0,
            "version": optie_tijdswaarde_projection_v2.version(),
        }
        _OPTIE_TIJDSWAARDE_PROJECTION_METRICS.append(sample)
        samples = list(_OPTIE_TIJDSWAARDE_PROJECTION_METRICS)
        metrics_payload = {"last": sample, "summary": _metrics_summary(samples), "samples": samples}
        SNAPSHOT_STORE.safe_write("snapshot_optie_tijdswaarde_projection_v2_metrics", metrics_payload)
        _append_optie_tijdswaarde_metrics_log(sample)
        meta = optie_tijdswaarde_projection_v2.meta()
        meta["reason"] = reason
        meta["metrics"] = {"last": sample, "summary": metrics_payload["summary"]}
        SNAPSHOT_STORE.safe_write("snapshot_optie_tijdswaarde_projection_v2_meta", meta)
        print(
            f"[optie-tijdswaarde-projection-v2-metrics] reason={reason} recompute_ms={recompute_ms:.1f} "
            f"publish_ms={publish_ms:.1f} total_ms={total_ms:.1f} patch={sample['patch_size']} rows={sample['snapshot_rows']}"
        )
    except Exception as exc:
        print(f"[optie-tijdswaarde-projection-v2] refresh failed: {exc}")


def refresh_sprinters_open_projection(reason: str):
    if sprinters_open_projection_v2 is None:
        return
    try:
        t0 = time.perf_counter()
        sprinters_open_projection_v2.recompute()
        snapshot_df = sprinters_open_projection_v2.snapshot()
        patch_list = sprinters_open_projection_v2.last_patch() or []
        t1 = time.perf_counter()
        SNAPSHOT_STORE.safe_write("snapshot_sprinters_open_projection_v2", snapshot_df)
        SNAPSHOT_STORE.safe_write("snapshot_sprinters_open_projection_v2_patch", patch_list)
        t2 = time.perf_counter()
        recompute_ms = round((t1 - t0) * 1000.0, 3)
        publish_ms = round((t2 - t1) * 1000.0, 3)
        total_ms = round((t2 - t0) * 1000.0, 3)
        sample = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": str(reason),
            "recompute_ms": recompute_ms,
            "publish_ms": publish_ms,
            "total_ms": total_ms,
            "patch_size": len(patch_list),
            "snapshot_rows": snapshot_df.height if snapshot_df is not None else 0,
            "version": sprinters_open_projection_v2.version(),
        }
        _SPRINTERS_OPEN_PROJECTION_METRICS.append(sample)
        samples = list(_SPRINTERS_OPEN_PROJECTION_METRICS)
        metrics_payload = {"last": sample, "summary": _metrics_summary(samples), "samples": samples}
        SNAPSHOT_STORE.safe_write("snapshot_sprinters_open_projection_v2_metrics", metrics_payload)
        _append_sprinters_metrics_log(sample)
        meta = sprinters_open_projection_v2.meta()
        meta["reason"] = reason
        meta["metrics"] = {"last": sample, "summary": metrics_payload["summary"]}
        SNAPSHOT_STORE.safe_write("snapshot_sprinters_open_projection_v2_meta", meta)
        print(
            f"[sprinters-projection-v2-metrics] reason={reason} recompute_ms={recompute_ms:.1f} "
            f"publish_ms={publish_ms:.1f} total_ms={total_ms:.1f} patch={sample['patch_size']} rows={sample['snapshot_rows']}"
        )
    except Exception as exc:
        print(f"[sprinters-projection-v2] refresh failed: {exc}")

def refresh_everything():
    start_time = time.time()
    flush_dirty_test_orders_to_db()
    load_test_orders_cache_from_db()
    repository.load_alle_transacties()
    repository.load_aandelen_from_tx()
    repository.load_open_opties_from_tx()
    repository.load_gesloten_opties_from_tx()
    repository.load_gesloten_opties_no_broker()
    repository.load_open_sprinters_from_tx()
    repository.load_gesloten_sprinters_from_tx()
    repository.load_asset_rollup_data()
    repository.load_sprinter_referentie_data()
    repository.load_dividend_data()
    repository.load_historical_close_snapshot()
    repository.load_per_dag_asset_result_v2_snapshot()
    repository.load_per_dag_asset_result()
    repository.load_optie_referentie_data()
    repository.build_repository_active_asset_rollup_data()
    live_aggregator_aandelen.process_live_update()
    live_aggregator_opties.process_live_update()
    repository.portfolio_value_asset_rollup_opties_put()
    repository.portfolio_value_asset_rollup_aandelen()
    repository.portfolio_value_asset_rollup_sprinters()
    repository.portfolio_value_asset_rollup_combined()  
    refresh_aandelen_projection("refresh_everything")
    refresh_opties_open_projection("refresh_everything")
    refresh_optie_tijdswaarde_projection("refresh_everything")
    refresh_sprinters_open_projection("refresh_everything")
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(SNAPSHOT_STORE.snapshot_store_summary())
    print(f"Datasets geladen in {elapsed_time:.2f} seconden.")


def refresh_transaction_derived_snapshots(payload: dict | None = None):
    start_time = time.time()
    try:
        # Zorg dat afgeleide snapshots altijd vanaf de gecommitte DB-waarheid worden opgebouwd.
        # Dit voorkomt race-gedrag waarbij ordersCommitted eerder komt dan lokale snapshot-sync in de UI.
        repository.load_alle_transacties()
        repository.load_aandelen_from_tx()
        repository.load_open_opties_from_tx()
        repository.load_gesloten_opties_from_tx()
        repository.load_gesloten_opties_no_broker()
        repository.load_open_sprinters_from_tx()
        repository.load_gesloten_sprinters_from_tx()
        repository.load_historical_close_snapshot()
        repository.load_per_dag_asset_result_v2_snapshot()
        repository.load_per_dag_asset_result()
        repository.build_repository_active_asset_rollup_data()
        live_aggregator_aandelen.process_live_update()
        live_aggregator_opties.process_live_update()
        repository.portfolio_value_asset_rollup_opties_put()
        repository.portfolio_value_asset_rollup_aandelen()
        repository.portfolio_value_asset_rollup_sprinters()
        repository.portfolio_value_asset_rollup_combined()
        ck: set[str] = set()
        asset_hint = (payload or {}).get("asset_rollup")
        if asset_hint:
            ck.add(str(asset_hint))
        refresh_aandelen_projection("transaction_derived", ck)
        refresh_opties_open_projection("transaction_derived")
        refresh_optie_tijdswaarde_projection("transaction_derived")
        refresh_sprinters_open_projection("transaction_derived")
    except Exception as exc:
        print(f"[snapshot-refresh] failed: {exc}")
        raise
    elapsed_time = time.time() - start_time
    reason = (payload or {}).get("reason", "unknown")
    print(f"[snapshot-refresh] transaction-derived snapshots refreshed in {elapsed_time:.2f}s ({reason})")


def run_startup_db_migrations():
    svc = DbMigrationService()
    results = svc.migrate_all_user_dbs()
    ok = sum(1 for r in results if r.success)
    fail = len(results) - ok
    print(f"[db-migrate] completed: ok={ok}, failed={fail}")
    for r in results:
        if r.success:
            print(
                f"[db-migrate] {r.database_name}: v{r.old_version} -> v{r.new_version}"
            )
        else:
            print(f"[db-migrate] {r.database_name}: FAILED ({r.error})")
    


def main():
    global _AANDELEN_PROJECTION_ASYNC_ENABLED
    run_startup_db_migrations()
    refresh_everything()
    state_engine_runner = StateEngineRunner(fallback_refresh=refresh_everything)
    SNAPSHOT_STORE.state_engine_runner = state_engine_runner
    historical_price_update_runner = HistoricalPriceUpdateRunner()
    
    # Koppel signalen aan orchestrator:
    # 1) request -> alleen state-engine starten
    # 2) finished(ok) -> daarna afgeleide snapshots verversen
    signals.stateRebuildRequested.connect(state_engine_runner.handle_rebuild_requested)
    signals.priceUpdateFinished.connect(state_engine_runner.handle_price_update_finished)
    signals.databaseChanged.connect(lambda db_name: refresh_everything())
    signals.databaseChanged.connect(state_engine_runner.handle_database_changed)
    # Debounce snapshot refreshes: bij een wave van price_catchup jobs
    # willen we niet na elke asset-run opnieuw alle snapshots/aggregators herladen.
    pending_refresh_payload: dict = {"reason": "unknown"}
    refresh_timer = QTimer()
    refresh_timer.setSingleShot(True)
    refresh_timer.setInterval(1200)
    opties_projection_refresh_timer = QTimer()
    opties_projection_refresh_timer.setSingleShot(True)
    opties_projection_refresh_timer.setInterval(300)
    optie_tijdswaarde_projection_refresh_timer = QTimer()
    optie_tijdswaarde_projection_refresh_timer.setSingleShot(True)
    optie_tijdswaarde_projection_refresh_timer.setInterval(300)
    sprinters_projection_refresh_timer = QTimer()
    sprinters_projection_refresh_timer.setSingleShot(True)
    sprinters_projection_refresh_timer.setInterval(300)
    orders_refresh_timer = QTimer()
    orders_refresh_timer.setSingleShot(True)
    orders_refresh_timer.setInterval(250)

    def _run_debounced_refresh():
        refresh_transaction_derived_snapshots(dict(pending_refresh_payload))

    def _run_orders_refresh():
        refresh_transaction_derived_snapshots({"reason": "orders_committed"})

    def _run_opties_projection_refresh():
        refresh_opties_open_projection("live_opties_snapshot")

    def _run_optie_tijdswaarde_projection_refresh():
        refresh_optie_tijdswaarde_projection("live_optie_tijdswaarde_snapshot")

    def _run_sprinters_projection_refresh():
        refresh_sprinters_open_projection("live_sprinters_snapshot")

    def _schedule_orders_refresh():
        # Herstel oud gedrag: na order-write direct transaction-derived snapshots verversen.
        # Debounced om korte bursts (bijv. gekoppelde writes) samen te nemen.
        orders_refresh_timer.start()

    def _schedule_snapshot_refresh(payload):
        if (payload or {}).get("status") != "ok":
            return
        # Refresh pas na aggregate-stap om dubbele UI-herlaadgolven te voorkomen.
        # Basis-engines (aandelen/opties/sprinters) worden direct gevolgd door
        # asset_result_v2; tussentijds refreshen is overbodig en kost UI-performance.
        engine_class = str((payload or {}).get("engine_class") or "").strip().lower()
        if engine_class != "asset_result_v2":
            return
        pending_refresh_payload.clear()
        pending_refresh_payload.update(payload or {})
        # Restart timer so bursts collapse into one refresh.
        refresh_timer.start()

    def _on_snapshot_updated_for_opties_projection(snapshot_key: str):
        if snapshot_key != "aggregator_snapshot_load_open_opties_from_tx_live":
            return
        opties_projection_refresh_timer.start()

    def _on_snapshot_updated_for_optie_tijdswaarde_projection(snapshot_key: str):
        if snapshot_key != "snapshot_optie_timevalue_live":
            return
        optie_tijdswaarde_projection_refresh_timer.start()

    def _on_snapshot_updated_for_sprinters_projection(snapshot_key: str):
        if snapshot_key != "aggregator_snapshot_open_sprinters_live":
            return
        sprinters_projection_refresh_timer.start()

    refresh_timer.timeout.connect(_run_debounced_refresh)
    opties_projection_refresh_timer.timeout.connect(_run_opties_projection_refresh)
    optie_tijdswaarde_projection_refresh_timer.timeout.connect(_run_optie_tijdswaarde_projection_refresh)
    sprinters_projection_refresh_timer.timeout.connect(_run_sprinters_projection_refresh)
    orders_refresh_timer.timeout.connect(_run_orders_refresh)
    signals.ordersCommitted.connect(_schedule_orders_refresh)
    signals.stateRebuildFinished.connect(_schedule_snapshot_refresh)
    signals.snapshotUpdated.connect(_on_snapshot_updated_for_opties_projection)
    signals.snapshotUpdated.connect(_on_snapshot_updated_for_optie_tijdswaarde_projection)
    signals.snapshotUpdated.connect(_on_snapshot_updated_for_sprinters_projection)
    def _on_aandelen_projection_filter_changed(payload: dict):
        if aandelen_projection_v2 is None:
            return
        brokers = payload.get("selected_brokers")
        if isinstance(brokers, (list, set, tuple)):
            selected = {str(x).strip() for x in brokers if str(x).strip()}
        else:
            selected = set()
        aandelen_projection_v2.set_selected_brokers(selected or None)
        print(f"[projection-v2] broker_filter_change selected={sorted(selected) if selected else ['ALL']}")
        refresh_aandelen_projection("broker_filter_change", force_sync=True)
    signals.aandelenProjectionFilterChanged.connect(_on_aandelen_projection_filter_changed)
    signals.stateRebuildFinished.connect(
        lambda payload: print(f"[state-engine] rebuild finished: {payload}")
    )
    signals.stateRebuildFailed.connect(
        lambda message: print(f"[state-engine] rebuild failed: {message}")
    )
    signals.priceUpdateStarted.connect(
        lambda payload: print(f"[price-update] started: {payload}")
    )
    signals.priceUpdateFinished.connect(
        lambda payload: print(f"[price-update] finished: {payload.get('status')} ({payload.get('fetch_start_date', 'n/a')} -> today)")
    )
    signals.priceUpdateFailed.connect(
        lambda message: print(f"[price-update] failed: {message}")
    )
    import faulthandler
    faulthandler.enable()
    app = QApplication(sys.argv)
    _AANDELEN_PROJECTION_ASYNC_ENABLED = True
    signals.projectionPublishTick.connect(
        lambda key: _drain_aandelen_projection_pending() if key == "aandelen_v2" else None
    )
    font = QFont()
    font.setPointSize(9)
    try:
        font.setWeight(QFont.Weight.DemiBold)
    except AttributeError:
        font.setWeight(QFont.DemiBold)
    app.setFont(font)
    settings = get_settings()
    price_feed = PriceFeedService(
        settings.get_ib_host(),
        settings.get_ib_port(),
        settings.get_ib_client_id()
    )
    stop_event, thread = start_live_price_updater(price_feed)
    portfolio_engine = PortfolioEngine(price_feed)
    option_timevalue_service = OptionTimevalueService(price_feed, STOCKDATA_DB_PATH)
    w = MainWindow(portfolio_engine, price_feed, live_price_updater_stop_event=stop_event)
    w.option_timevalue_service = option_timevalue_service
    w.show()
    # Start price-update pas nadat UI volledig staat en event-loop idle is.
    QTimer.singleShot(5000, historical_price_update_runner.request_startup_update)
    if price_feed.is_ready():
        portfolio_engine.start_subscriptions()
    else:
        price_feed._feed.ready.connect(lambda: portfolio_engine.start_subscriptions())
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

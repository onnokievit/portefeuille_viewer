import sys  
import os
import json
import threading
import builtins
import contextlib
import argparse
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast
from collections import Counter
from collections import deque
from pathlib import Path
import polars as pl
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
from portefeuille_viewer.services.app_task_scheduler import AppTaskScheduler
from portefeuille_viewer.services.db_migration_service import DbMigrationService
from portefeuille_viewer.services.scenario_aandelen_overlay import refresh_aandelen_scenario_overlay_snapshot
from portefeuille_viewer.services.scenario_portfolio_value_overlay import refresh_portfolio_value_scenario_overlay_snapshot
from portefeuille_viewer.services.scenario_sector_overlay import refresh_sector_scenario_overlay_snapshots
from portefeuille_viewer.domain.portfolio_engine import PortfolioEngine
from portefeuille_viewer.domain.engine_core_runtime import EngineCoreRuntime
from portefeuille_viewer.domain.projection_bus import ProjectionRunResult
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.live_aggregator_aandelen import LiveAggregatorAandelen
from portefeuille_viewer.data.live_aggregator_opties import LiveAggregatorOpties
from portefeuille_viewer.data.live_aggregator_sprinters import LiveAggregatorSprinters
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

def _log(*args, **kwargs) -> None:
    ts = time.strftime("%H:%M:%S")
    prefix = f"[{ts}]"
    if args:
        builtins.print(prefix, *args, **kwargs)
    else:
        builtins.print(prefix, **kwargs)

# Qt warning filter: onderdruk specifieke QSortFilterProxyModel warning
def qt_message_handler(mode, context, message):
    if "QSortFilterProxyModel: index from wrong model passed to mapToSource" in message:
        return
    _log(message)

qInstallMessageHandler(qt_message_handler)

# Forceer Python om deze map als eerste te gebruiken
# sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_log("✅ Repository geladen uit:", repository.__file__)


def _apply_env_defaults_from_settings() -> None:
    """Load env defaults from settings.ini; explicit shell env vars keep precedence."""
    try:
        settings = get_settings()
        cfg = getattr(settings, "config", None)
        if cfg is None or not cfg.has_section("env_defaults"):
            return
        for raw_key, raw_val in cfg.items("env_defaults"):
            env_key = str(raw_key or "").strip().upper()
            env_val = str(raw_val or "").strip()
            if not env_key or env_val == "":
                continue
            os.environ.setdefault(env_key, env_val)
    except Exception as exc:
        _log(f"[env-defaults] could not apply defaults: {exc}")


_apply_env_defaults_from_settings()


def _parse_startup_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--db",
        "--database",
        dest="database_alias",
        default="",
        help="Start direct met database alias/naam uit Settings > Databases.",
    )
    args, _unknown = parser.parse_known_args(argv[1:])
    return args


def _normalize_database_alias(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _resolve_database_alias(alias: str) -> str:
    settings = get_settings()
    databases = settings.get_databases()
    wanted = _normalize_database_alias(alias)
    if not wanted:
        return ""
    for name in databases:
        if _normalize_database_alias(name) == wanted:
            return name
    available = ", ".join(databases.keys()) or "(geen databases ingesteld)"
    raise ValueError(f"Onbekende database alias '{alias}'. Beschikbaar: {available}")


def _apply_startup_database_selection(alias: str) -> None:
    if not str(alias or "").strip():
        return
    db_name = _resolve_database_alias(alias)
    repository.switch_database(db_name)
    get_settings().set_last_database(db_name)
    _log(f"[startup-db] actieve database via --db: {db_name}")

# Persistent aggregators for the whole app
live_aggregator_aandelen = LiveAggregatorAandelen()
live_aggregator_opties = LiveAggregatorOpties()
live_aggregator_sprinters = LiveAggregatorSprinters()
ENABLE_AANDELEN_PROJECTION_V2 = os.getenv("USE_AANDELEN_PROJECTION_V2", "1").strip() == "1"
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
ENABLE_ENGINE_CORE_RUNTIME = os.getenv("USE_ENGINE_CORE_RUNTIME_V1", "0").strip() == "1"
ENABLE_ENGINE_CORE_RUNTIME_EXCLUSIVE = (
    ENABLE_ENGINE_CORE_RUNTIME
    and os.getenv("ENGINE_CORE_RUNTIME_EXCLUSIVE_V1", "0").strip() == "1"
)
ENABLE_ORDERS_COMMIT_FULL_REFRESH = (
    os.getenv("ORDERS_COMMIT_FULL_REFRESH_V1", "1").strip() == "1"
)
ENGINE_CORE_LOG_TOPICS = os.getenv("ENGINE_CORE_LOG_TOPICS", "0").strip() == "1"
PROJECTION_METRICS_LOG_CONSOLE = (
    os.getenv("PROJECTION_METRICS_LOG_CONSOLE", "0").strip() == "1"
)
PROJECTION_METRICS_LOG_FILE = (
    os.getenv("PROJECTION_METRICS_LOG_FILE", "0").strip() == "1"
)
PROJECTION_METRICS_LOG_TIMEVALUE_TOPIC = (
    os.getenv("PROJECTION_METRICS_LOG_TIMEVALUE_TOPIC", "0").strip() == "1"
)
APP_PERF_LOG = os.getenv("APP_PERF_LOG", "1").strip() == "1"
_EXCLUSIVE_LIVE_RECOMPUTE_INTERVAL_MS = {
    "aggregator_snapshot_load_open_opties_from_tx_live": max(
        0,
        int(os.getenv("EXCLUSIVE_LIVE_OPTIES_RECOMPUTE_MS", "30000")),
    ),
    "snapshot_optie_timevalue_live": max(
        0,
        int(os.getenv("EXCLUSIVE_LIVE_TIMEVALUE_RECOMPUTE_MS", "5000")),
    ),
    "aggregator_snapshot_open_sprinters_live": max(
        0,
        int(os.getenv("EXCLUSIVE_LIVE_SPRINTERS_RECOMPUTE_MS", "15000")),
    ),
}
_EXCLUSIVE_LIVE_RECOMPUTE_TIMERS: dict[str, QTimer] = {}
_EXCLUSIVE_LIVE_RECOMPUTE_PENDING: dict[str, set[str]] = {}


def _engine_core_logger(message: str) -> None:
    msg = str(message or "")
    if "[engine-core] topic=" in msg and not ENGINE_CORE_LOG_TOPICS:
        return
    _log(msg)


engine_core_runtime = EngineCoreRuntime(
    enabled=ENABLE_ENGINE_CORE_RUNTIME,
    logger=_engine_core_logger,
)
for _projection in (
    aandelen_projection_v2,
    opties_open_projection_v2,
    optie_tijdswaarde_projection_v2,
    sprinters_open_projection_v2,
):
    if _projection is not None:
        engine_core_runtime.register_projection(_projection)
_SPRINTERS_OPEN_PROJECTION_METRICS = deque(maxlen=200)
_SPRINTERS_OPEN_PROJECTION_METRICS_LOG = Path("logs") / "sprinters_open_projection_v2_metrics.jsonl"


class SupportsProjectionRefresh(Protocol):
    def recompute(self, *args: Any, **kwargs: Any) -> Any: ...
    def snapshot(self) -> pl.DataFrame: ...
    def last_patch(self) -> list[dict[str, Any]] | None: ...
    def version(self) -> Any: ...
    def meta(self) -> dict[str, Any]: ...


ProjectionPatch = list[dict[str, Any]]
ProjectionMetricsSample = dict[str, Any]
ProjectionDedupePolicy = Literal["always_publish", "skip_unchanged"]


@dataclass
class ProjectionRefreshConfig:
    projection_name: str
    projection: SupportsProjectionRefresh | None
    snapshot_key: str
    metrics_deque: deque[ProjectionMetricsSample]
    metrics_log_path: Path
    log_prefix: str
    error_prefix: str
    dedupe_policy: ProjectionDedupePolicy = "always_publish"
    last_published_snapshot: pl.DataFrame | None = field(default=None)
    last_published_patch: ProjectionPatch | None = field(default=None)


_CFG_OPTIES = ProjectionRefreshConfig(
    projection_name="opties_open_v2",
    projection=opties_open_projection_v2,
    snapshot_key="snapshot_opties_open_projection_v2",
    metrics_deque=_OPTIES_OPEN_PROJECTION_METRICS,
    metrics_log_path=_OPTIES_OPEN_PROJECTION_METRICS_LOG,
    log_prefix="[opties-projection-v2-metrics]",
    error_prefix="[opties-projection-v2]",
    dedupe_policy="skip_unchanged",
)
_CFG_TIJDSWAARDE = ProjectionRefreshConfig(
    projection_name="optie_tijdswaarde_v2",
    projection=optie_tijdswaarde_projection_v2,
    snapshot_key="snapshot_optie_tijdswaarde_projection_v2",
    metrics_deque=_OPTIE_TIJDSWAARDE_PROJECTION_METRICS,
    metrics_log_path=_OPTIE_TIJDSWAARDE_PROJECTION_METRICS_LOG,
    log_prefix="[optie-tijdswaarde-projection-v2-metrics]",
    error_prefix="[optie-tijdswaarde-projection-v2]",
)
_CFG_SPRINTERS = ProjectionRefreshConfig(
    projection_name="sprinters_open_v2",
    projection=sprinters_open_projection_v2,
    snapshot_key="snapshot_sprinters_open_projection_v2",
    metrics_deque=_SPRINTERS_OPEN_PROJECTION_METRICS,
    metrics_log_path=_SPRINTERS_OPEN_PROJECTION_METRICS_LOG,
    log_prefix="[sprinters-projection-v2-metrics]",
    error_prefix="[sprinters-projection-v2]",
)
_PROJECTION_REFRESH_CONFIGS: dict[str, ProjectionRefreshConfig] = {
    cfg.projection_name: cfg
    for cfg in (_CFG_OPTIES, _CFG_TIJDSWAARDE, _CFG_SPRINTERS)
}

_AANDELEN_PROJECTION_ASYNC_ENABLED = False
_AANDELEN_PROJECTION_REQ_LOCK = threading.Lock()
_AANDELEN_PROJECTION_PENDING_LOCK = threading.Lock()
_AANDELEN_PROJECTION_INFLIGHT = False
_AANDELEN_PROJECTION_QUEUED_REQ: dict | None = None
_AANDELEN_PROJECTION_PENDING_RESULT: dict | None = None
_AANDELEN_TV_STARTUP_SEEDED = False
_AANDELEN_TV_LAST_OVERLAY_TS = 0.0
_AANDELEN_TV_SEED_TS = 0.0
_AANDELEN_TV_OVERLAY_MIN_INTERVAL_SEC = 60.0
_AANDELEN_TV_WARMUP_WINDOW_SEC = 60.0
_AANDELEN_TV_WARMUP_INTERVAL_SEC = 5.0
_AANDELEN_TV_OVERLAY_LOCKED = False
_AANDELEN_TV_LOCK_TOL_EUR = 1.0
ENABLE_AANDELEN_TV_OVERLAY_FROM_LIVE = (
    os.getenv("ENABLE_AANDELEN_TV_OVERLAY_FROM_LIVE", "0").strip() == "1"
)


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


def _append_metrics_log_to(log_path: Path, sample: dict) -> None:
    if not PROJECTION_METRICS_LOG_FILE:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _df_equals(left, right) -> bool:
    if left is right:
        return True
    if left is None or right is None:
        return False
    try:
        return bool(left.equals(right))
    except Exception:
        return False


def _should_publish_projection(
    cfg: ProjectionRefreshConfig,
    snapshot_df: pl.DataFrame | None,
    patch_list: ProjectionPatch,
) -> bool:
    if cfg.dedupe_policy == "always_publish":
        return True
    if cfg.dedupe_policy == "skip_unchanged":
        return not (
            _df_equals(cfg.last_published_snapshot, snapshot_df)
            and cfg.last_published_patch == patch_list
        )
    return True


def _append_projection_metrics(
    cfg: ProjectionRefreshConfig,
    sample: ProjectionMetricsSample,
) -> dict[str, Any]:
    projection = cfg.projection
    if projection is None:
        return {"last": sample, "summary": _metrics_summary([]), "samples": [sample]}
    cfg.metrics_deque.append(sample)
    samples = list(cfg.metrics_deque)
    metrics_payload = {"last": sample, "summary": _metrics_summary(samples), "samples": samples}
    SNAPSHOT_STORE.safe_write(f"{cfg.snapshot_key}_metrics", metrics_payload)
    _append_metrics_log_to(cfg.metrics_log_path, sample)
    meta = projection.meta()
    meta["reason"] = sample["reason"]
    meta["metrics"] = {"last": sample, "summary": metrics_payload["summary"]}
    SNAPSHOT_STORE.safe_write(f"{cfg.snapshot_key}_meta", meta)
    return metrics_payload


def _empty_metrics_payload() -> dict[str, Any]:
    return {"last": None, "summary": _metrics_summary([]), "samples": []}


def _reset_projection_publish_caches() -> None:
    for cfg in _PROJECTION_REFRESH_CONFIGS.values():
        cfg.last_published_snapshot = None
        cfg.last_published_patch = None


def _invalidate_snapshots_for_database_change(
    option_timevalue_service: OptionTimevalueService | None = None,
) -> None:
    empty_df = pl.DataFrame()
    empty_metrics = _empty_metrics_payload()
    _reset_projection_publish_caches()
    SNAPSHOT_STORE.clear_live_prices()
    live_aggregator_aandelen.reset_for_database_change()
    live_aggregator_opties.reset_for_database_change()
    live_aggregator_sprinters.reset_for_database_change()

    empty_snapshot_writes: list[tuple[str, object]] = [
        ("repository_snapshot_alle_transacties", empty_df),
        ("repository_snapshot_aandelen", empty_df),
        ("aggregator_snapshot_aandelen_live", empty_df),
        ("repository_snapshot_load_open_opties", empty_df),
        ("aggregator_snapshot_load_open_opties_from_tx_live", empty_df),
        ("repository_snapshot_open_sprinters", empty_df),
        ("aggregator_snapshot_open_sprinters_live", empty_df),
        ("repository_snapshot_gesloten_opties", empty_df),
        ("repository_snapshot_gesloten_opties_no_broker", empty_df),
        ("repository_snapshot_gesloten_sprinters", empty_df),
        ("repository_snapshot_gesloten_sprinters_no_asset_detail", empty_df),
        ("repository_snapshot_asset_rollup_data", empty_df),
        ("repository_snapshot_active_asset_rollup_data", empty_df),
        ("repository_snapshot_sprinter_referentie_data", empty_df),
        ("repository_snapshot_optie_referentie_data", empty_df),
        ("repository_snapshot_portfolio_value_aandelen", empty_df),
        ("repository_snapshot_portfolio_value_aandelen_scenario", empty_df),
        ("repository_snapshot_portfolio_value_optie_call_put_detailed", empty_df),
        ("repository_snapshot_portfolio_value_optie_call_put_detailed_scenario", empty_df),
        ("repository_snapshot_portfolio_value_optie", empty_df),
        ("repository_snapshot_portfolio_value_sprinters", empty_df),
        ("repository_snapshot_portfolio_value_sprinters_scenario", empty_df),
        ("repository_snapshot_portfolio_value_total_combined_put", empty_df),
        ("repository_snapshot_portfolio_value_total_combined_scenario", empty_df),
        ("snapshot_aandelen_projection_v2", empty_df),
        ("snapshot_aandelen_projection_v2_patch", []),
        ("snapshot_aandelen_projection_v2_metrics", empty_metrics),
        ("snapshot_aandelen_projection_v2_meta", {}),
        ("snapshot_aandelen_projection_v2_scenario", empty_df),
        ("snapshot_opties_open_projection_v2", empty_df),
        ("snapshot_opties_open_projection_v2_patch", []),
        ("snapshot_opties_open_projection_v2_metrics", empty_metrics),
        ("snapshot_opties_open_projection_v2_meta", {}),
        ("snapshot_optie_tijdswaarde_projection_v2", empty_df),
        ("snapshot_optie_tijdswaarde_projection_v2_patch", []),
        ("snapshot_optie_tijdswaarde_projection_v2_metrics", empty_metrics),
        ("snapshot_optie_tijdswaarde_projection_v2_meta", {}),
        ("snapshot_sprinters_open_projection_v2", empty_df),
        ("snapshot_sprinters_open_projection_v2_patch", []),
        ("snapshot_sprinters_open_projection_v2_metrics", empty_metrics),
        ("snapshot_sprinters_open_projection_v2_meta", {}),
    ]
    for attr_name, value in empty_snapshot_writes:
        SNAPSHOT_STORE.safe_write(attr_name, value)
    if option_timevalue_service is not None:
        option_timevalue_service.reset_for_database_change()


def _publish_projection_from_runtime(
    cfg: ProjectionRefreshConfig,
    recompute_ms: float,
    reason: str,
) -> None:
    if cfg.projection is None:
        return
    snapshot_df = cfg.projection.snapshot()
    patch_list: ProjectionPatch = cfg.projection.last_patch() or []
    if not _should_publish_projection(cfg, snapshot_df, patch_list):
        return
    SNAPSHOT_STORE.safe_write(cfg.snapshot_key, snapshot_df)
    SNAPSHOT_STORE.safe_write(f"{cfg.snapshot_key}_patch", patch_list)
    cfg.last_published_snapshot = snapshot_df.clone() if snapshot_df is not None else None
    cfg.last_published_patch = list(patch_list)
    sample = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reason": str(reason),
        "recompute_ms": recompute_ms,
        "publish_ms": 0.0,
        "total_ms": recompute_ms,
        "patch_size": len(patch_list),
        "snapshot_rows": snapshot_df.height if snapshot_df is not None else 0,
        "version": cfg.projection.version(),
    }
    _append_projection_metrics(cfg, sample)


def _refresh_projection_sync(cfg: ProjectionRefreshConfig, reason: str) -> None:
    if cfg.projection is None:
        return
    try:
        t0 = time.perf_counter()
        cfg.projection.recompute()
        snapshot_df = cfg.projection.snapshot()
        patch_list: ProjectionPatch = cfg.projection.last_patch() or []
        t1 = time.perf_counter()
        SNAPSHOT_STORE.safe_write(cfg.snapshot_key, snapshot_df)
        SNAPSHOT_STORE.safe_write(f"{cfg.snapshot_key}_patch", patch_list)
        t2 = time.perf_counter()
        cfg.last_published_snapshot = snapshot_df.clone() if snapshot_df is not None else None
        cfg.last_published_patch = list(patch_list)
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
            "version": cfg.projection.version(),
        }
        _append_projection_metrics(cfg, sample)
        if PROJECTION_METRICS_LOG_CONSOLE:
            _log(
                f"{cfg.log_prefix} reason={reason} recompute_ms={recompute_ms:.1f} "
                f"publish_ms={publish_ms:.1f} total_ms={total_ms:.1f} "
                f"patch={sample['patch_size']} rows={sample['snapshot_rows']}"
            )
    except Exception as exc:
        _log(f"{cfg.error_prefix} refresh failed: {exc}")


def _reset_aandelen_tv_overlay_regime(reason: str) -> None:
    global _AANDELEN_TV_STARTUP_SEEDED
    global _AANDELEN_TV_LAST_OVERLAY_TS
    global _AANDELEN_TV_SEED_TS
    global _AANDELEN_TV_OVERLAY_LOCKED
    _AANDELEN_TV_STARTUP_SEEDED = False
    _AANDELEN_TV_LAST_OVERLAY_TS = 0.0
    _AANDELEN_TV_SEED_TS = 0.0
    _AANDELEN_TV_OVERLAY_LOCKED = False
    _log(f"[projection-v2] timevalue overlay regime reset ({reason})")


def _aandelen_tv_totals_in_sync() -> bool:
    df_aandelen = getattr(SNAPSHOT_STORE, "snapshot_aandelen_projection_v2", None)
    df_tv = getattr(SNAPSHOT_STORE, "snapshot_optie_timevalue_live", None)
    if (
        df_aandelen is None
        or df_tv is None
        or not hasattr(df_aandelen, "is_empty")
        or not hasattr(df_tv, "is_empty")
        or df_aandelen.is_empty()
        or df_tv.is_empty()
        or "optie_tijdswaarde_signed_eur" not in getattr(df_aandelen, "columns", [])
        or "time_total" not in getattr(df_tv, "columns", [])
    ):
        return False

    selected_brokers: set[str] | None = None
    meta = getattr(SNAPSHOT_STORE, "snapshot_aandelen_projection_v2_meta", None)
    if isinstance(meta, dict):
        selected = meta.get("selected_brokers")
        if isinstance(selected, list) and selected:
            selected_brokers = {
                str(x).strip().lower() for x in selected if str(x).strip()
            } or None

    try:
        aandelen_total = (
            df_aandelen.select(
                pl.col("optie_tijdswaarde_signed_eur")
                .cast(pl.Float64, strict=False)
                .fill_null(0.0)
                .sum()
                .alias("v")
            )
            .item(0, "v")
        )
        aandelen_total = float(aandelen_total or 0.0)
    except Exception:
        return False

    tv_calc = df_tv
    if selected_brokers is not None and "broker" in tv_calc.columns:
        allowed = [str(b).strip().lower() for b in selected_brokers if str(b).strip()]
        if allowed:
            tv_calc = tv_calc.filter(
                pl.col("broker")
                .cast(pl.Utf8, strict=False)
                .str.strip_chars()
                .str.to_lowercase()
                .is_in(allowed)
            )

    if tv_calc.is_empty():
        return abs(aandelen_total) <= _AANDELEN_TV_LOCK_TOL_EUR

    eurusd = float(get_settings().get_eurusd() or 1.0)
    if eurusd == 0:
        eurusd = 1.0

    try:
        tv_sum_df = (
            tv_calc.select(
                [
                    pl.col("ccy").cast(pl.Utf8, strict=False).alias("ccy"),
                    pl.col("time_total").cast(pl.Float64, strict=False).alias("time_total"),
                ]
            )
            .filter(pl.col("time_total").is_not_null())
            .group_by("ccy")
            .agg(pl.col("time_total").sum().alias("time_total_signed"))
            .with_columns(
                pl.when(pl.col("ccy") == "USD")
                .then(pl.col("time_total_signed") / eurusd)
                .otherwise(pl.col("time_total_signed"))
                .alias("time_total_eur")
            )
            .select(pl.col("time_total_eur").sum().alias("tv_total_eur"))
        )
        target_total = float(tv_sum_df.item(0, "tv_total_eur") or 0.0)
    except Exception:
        return False

    return abs(aandelen_total - target_total) <= _AANDELEN_TV_LOCK_TOL_EUR


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
        _append_metrics_log_to(_AANDELEN_PROJECTION_METRICS_LOG, sample)
        meta = result.get("meta") or aandelen_projection_v2.meta()
        meta["reason"] = result.get("reason", "unknown")
        meta["metrics"] = {
            "last": sample,
            "summary": metrics_payload["summary"],
        }
        SNAPSHOT_STORE.safe_write("snapshot_aandelen_projection_v2_meta", meta)
        reason_text = str(sample.get("reason", ""))
        is_timevalue_topic = reason_text == "snapshot:snapshot_optie_timevalue_live"
        if PROJECTION_METRICS_LOG_CONSOLE and (
            PROJECTION_METRICS_LOG_TIMEVALUE_TOPIC or not is_timevalue_topic
        ):
            _log(
                f"[projection-v2-metrics] reason={sample['reason']} queue_wait_ms={sample['queue_wait_ms']:.1f} "
                f"recompute_ms={sample['recompute_ms']:.1f} publish_ms={publish_ms:.1f} "
                f"total_ms={total_ms:.1f} patch={sample['patch_size']} rows={sample['snapshot_rows']} inflight={sample['inflight']}"
            )
    except Exception as exc:
        _log(f"[projection-v2] aandelen refresh failed: {exc}")


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
        _log(f"[projection-v2] aandelen compute failed: {exc}")
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
    _refresh_projection_sync(_CFG_OPTIES, reason)


def refresh_optie_tijdswaarde_projection(reason: str):
    _refresh_projection_sync(_CFG_TIJDSWAARDE, reason)


def refresh_sprinters_open_projection(reason: str):
    _refresh_projection_sync(_CFG_SPRINTERS, reason)


def _publish_runtime_projection_results(results, reason: str):
    for res in results or []:
        if not getattr(res, "success", False):
            _log(
                f"[engine-core] projection failed: {getattr(res, 'projection_name', 'unknown')} ({getattr(res, 'error', 'n/a')})"
            )
            continue
        pname = str(getattr(res, "projection_name", ""))
        recompute_ms = round(float(getattr(res, "duration_ms", 0.0)), 3)
        changed_keys = int(getattr(res, "changed_keys", 0))
        if pname == "aandelen_v2" and aandelen_projection_v2 is not None:
            _publish_aandelen_projection_result(
                {
                    "reason": reason,
                    "changed_keys_count": changed_keys,
                    "enqueue_ts": time.perf_counter(),
                    "queue_wait_ms": 0.0,
                    "recompute_ms": recompute_ms,
                    "snapshot_df": aandelen_projection_v2.snapshot(),
                    "patch_list": aandelen_projection_v2.last_patch() or [],
                    "meta": aandelen_projection_v2.meta(),
                    "inflight": False,
                }
            )
            continue
        cfg = _PROJECTION_REFRESH_CONFIGS.get(pname)
        if cfg is not None:
            _publish_projection_from_runtime(cfg, recompute_ms, reason)


def _runtime_recompute_all(reason: str):
    if not ENABLE_ENGINE_CORE_RUNTIME:
        return
    results = engine_core_runtime.projection_bus.run(set(), topic=None)
    _publish_runtime_projection_results(results, reason=reason)


def _runtime_recompute_selected(
    projection_names: set[str],
    reason: str,
    changed_keys: set[str] | None = None,
):
    if not ENABLE_ENGINE_CORE_RUNTIME:
        return
    selected = {str(name).strip() for name in (projection_names or set()) if str(name).strip()}
    if not selected:
        return
    projection_map = {
        "aandelen_v2": aandelen_projection_v2,
        "opties_open_v2": opties_open_projection_v2,
        "optie_tijdswaarde_v2": optie_tijdswaarde_projection_v2,
        "sprinters_open_v2": sprinters_open_projection_v2,
    }
    keys = set(changed_keys or set())
    results: list[ProjectionRunResult] = []
    for projection_name in selected:
        projection = projection_map.get(projection_name)
        if projection is None:
            continue
        t0 = time.perf_counter()
        try:
            recompute_fn = getattr(projection, "recompute", None)
            if recompute_fn is None:
                raise AttributeError(f"{projection_name} has no recompute()")
            try:
                sig = inspect.signature(recompute_fn)
                if len(sig.parameters) == 0:
                    recompute_fn()
                else:
                    recompute_fn(keys)
            except (TypeError, ValueError):
                recompute_fn(keys)
            results.append(
                ProjectionRunResult(
                    projection_name=projection_name,
                    changed_keys=len(keys),
                    success=True,
                    duration_ms=(time.perf_counter() - t0) * 1000.0,
                )
            )
        except Exception as exc:
            results.append(
                ProjectionRunResult(
                    projection_name=projection_name,
                    changed_keys=len(keys),
                    success=False,
                    duration_ms=(time.perf_counter() - t0) * 1000.0,
                    error=str(exc),
                )
            )
    _publish_runtime_projection_results(results, reason=reason)


def _run_exclusive_live_recompute(snapshot_key: str):
    pending = _EXCLUSIVE_LIVE_RECOMPUTE_PENDING.pop(snapshot_key, set())
    if not pending:
        return
    _runtime_recompute_selected(pending, reason=f"snapshot:{snapshot_key}:debounced")


def _queue_exclusive_live_recompute(snapshot_key: str, projection_names: set[str]):
    selected = {str(name).strip() for name in (projection_names or set()) if str(name).strip()}
    if not selected:
        return
    timer = _EXCLUSIVE_LIVE_RECOMPUTE_TIMERS.get(snapshot_key)
    if timer is None:
        _runtime_recompute_selected(selected, reason=f"snapshot:{snapshot_key}")
        return
    pending = _EXCLUSIVE_LIVE_RECOMPUTE_PENDING.setdefault(snapshot_key, set())
    pending.update(selected)
    timer.start()


def _on_snapshot_updated_engine_core(snapshot_key: str):
    global _AANDELEN_TV_STARTUP_SEEDED
    global _AANDELEN_TV_LAST_OVERLAY_TS
    global _AANDELEN_TV_SEED_TS
    global _AANDELEN_TV_OVERLAY_LOCKED
    if (
        ENABLE_AANDELEN_TV_OVERLAY_FROM_LIVE
        and
        snapshot_key == "snapshot_optie_timevalue_live"
        and aandelen_projection_v2 is not None
    ):
        tv_df = getattr(SNAPSHOT_STORE, "snapshot_optie_timevalue_live", None)
        tv_ready = False
        if tv_df is not None and hasattr(tv_df, "is_empty") and not tv_df.is_empty():
            try:
                if "time_total" in getattr(tv_df, "columns", []):
                    tv_ready = tv_df.filter(pl.col("time_total").is_not_null()).height > 0
                elif "last_px" in getattr(tv_df, "columns", []):
                    tv_ready = tv_df.filter(pl.col("last_px").is_not_null()).height > 0
            except Exception:
                tv_ready = False
        now_ts = time.time()
        if tv_ready and not _AANDELEN_TV_STARTUP_SEEDED:
            refresh_aandelen_projection(
                "startup_timevalue_seed",
                changed_keys={"__TIMEVALUE_OVERLAY__"},
                force_sync=True,
            )
            seeded_df = getattr(SNAPSHOT_STORE, "snapshot_aandelen_projection_v2", None)
            if (
                seeded_df is not None
                and hasattr(seeded_df, "is_empty")
                and not seeded_df.is_empty()
                and "optie_tijdswaarde_signed_eur" in getattr(seeded_df, "columns", [])
            ):
                _AANDELEN_TV_STARTUP_SEEDED = True
                _AANDELEN_TV_SEED_TS = now_ts
                _AANDELEN_TV_LAST_OVERLAY_TS = now_ts
                _log("[projection-v2] startup timevalue seed applied")
        elif tv_ready and _AANDELEN_TV_STARTUP_SEEDED:
            if not _AANDELEN_TV_OVERLAY_LOCKED and _aandelen_tv_totals_in_sync():
                _AANDELEN_TV_OVERLAY_LOCKED = True
                _log("[projection-v2] timevalue overlay locked (totals in sync)")
            if _AANDELEN_TV_OVERLAY_LOCKED:
                tv_ready = False
            interval = _AANDELEN_TV_OVERLAY_MIN_INTERVAL_SEC
            if (now_ts - _AANDELEN_TV_SEED_TS) <= _AANDELEN_TV_WARMUP_WINDOW_SEC:
                interval = _AANDELEN_TV_WARMUP_INTERVAL_SEC
            if (now_ts - _AANDELEN_TV_LAST_OVERLAY_TS) < interval:
                interval = None
            if interval is None:
                pass
            else:
                refresh_aandelen_projection(
                    "timevalue_overlay_tick",
                    changed_keys={"__TIMEVALUE_OVERLAY__"},
                    force_sync=True,
                )
                _AANDELEN_TV_LAST_OVERLAY_TS = now_ts
    if ENABLE_ENGINE_CORE_RUNTIME_EXCLUSIVE:
        live_topic_targets = {
            "aggregator_snapshot_aandelen_live": {"aandelen_v2"},
            "aggregator_snapshot_load_open_opties_from_tx_live": {"opties_open_v2"},
            "snapshot_optie_timevalue_live": {"optie_tijdswaarde_v2"},
            "aggregator_snapshot_open_sprinters_live": {"sprinters_open_v2"},
        }
        targets = live_topic_targets.get(snapshot_key)
        if targets is None:
            return
        _queue_exclusive_live_recompute(snapshot_key, targets)
        return
    results = engine_core_runtime.publish_snapshot_update(
        snapshot_key,
        source="signal.snapshotUpdated",
    )
    if ENABLE_ENGINE_CORE_RUNTIME_EXCLUSIVE:
        _publish_runtime_projection_results(results, reason=f"snapshot:{snapshot_key}")


def _refresh_phase_test_orders() -> None:
    flush_dirty_test_orders_to_db()
    load_test_orders_cache_from_db()


def _refresh_phase_repository_core() -> None:
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
    repository.load_asset_driver_beta_snapshot()
    repository.load_asset_dividend_calendar_snapshot()
    repository.load_per_dag_asset_result_v2_snapshot()
    repository.load_optie_referentie_data()
    repository.build_repository_active_asset_rollup_data()


def _refresh_phase_live_aggregators(*, force_publish: bool = False) -> None:
    live_aggregator_aandelen.process_live_update(force_publish=force_publish)
    live_aggregator_opties.process_live_update(force_publish=force_publish)
    live_aggregator_sprinters.process_live_update(force_publish=force_publish)


def _refresh_phase_portfolio_values() -> None:
    repository.portfolio_value_asset_rollup_opties_put()
    repository.portfolio_value_asset_rollup_aandelen()
    repository.portfolio_value_asset_rollup_sprinters()
    repository.portfolio_value_asset_rollup_combined()


def _refresh_phase_projections(reason: str) -> None:
    if ENABLE_ENGINE_CORE_RUNTIME_EXCLUSIVE:
        _runtime_recompute_all(reason)
    else:
        refresh_aandelen_projection(reason)
        refresh_opties_open_projection(reason)
        refresh_optie_tijdswaarde_projection(reason)
        refresh_sprinters_open_projection(reason)


def _refresh_active_scenario_overlays() -> None:
    scenario_id = getattr(SNAPSHOT_STORE, "runtime_active_test_order_scenario_id", None)
    enabled = bool(getattr(SNAPSHOT_STORE, "runtime_test_orders_enabled", False))
    if scenario_id is None:
        return
    refresh_portfolio_value_scenario_overlay_snapshot(int(scenario_id), enabled=enabled)
    refresh_sector_scenario_overlay_snapshots(int(scenario_id), enabled=enabled)
    refresh_aandelen_scenario_overlay_snapshot(int(scenario_id), enabled=enabled)


def refresh_everything(*, force_live_publish: bool = False):
    start_time = time.time()
    _refresh_phase_test_orders()
    _refresh_phase_repository_core()
    _refresh_phase_live_aggregators(force_publish=force_live_publish)
    _refresh_phase_portfolio_values()
    _refresh_phase_projections("refresh_everything")
    _refresh_active_scenario_overlays()
    end_time = time.time()
    elapsed_time = end_time - start_time
    _log(SNAPSHOT_STORE.snapshot_store_summary())
    _log(f"Datasets geladen in {elapsed_time:.2f} seconden.")


def refresh_transaction_derived_snapshots(payload: dict | None = None):
    start_time = time.perf_counter()
    timings: list[tuple[str, float]] = []
    df_tx: pl.DataFrame | None = None

    def _mark(stage: str, stage_start: float):
        timings.append((stage, time.perf_counter() - stage_start))

    try:
        stage_start = time.perf_counter()
        df_tx = repository.patch_transactions_snapshot_from_orders_payload(payload)
        if df_tx is not None:
            _mark("patch_transactions_snapshot", stage_start)
        else:
            # Fallback naar DB-waarheid als er geen veilige lokale patch mogelijk is.
            repository.load_alle_transacties()
            df_tx = SNAPSHOT_STORE.repository_snapshot_alle_transacties
            _mark("load_alle_transacties", stage_start)
        if df_tx is None:
            raise ValueError("repository_snapshot_alle_transacties is niet beschikbaar")
        raw_asset_types = {
            str(asset_type).strip().lower()
            for asset_type in ((payload or {}).get("changed_asset_types") or [])
            if str(asset_type).strip()
        }
        known_asset_types = {"aandeel", "optie", "sprinter"}
        unknown_asset_types = raw_asset_types - known_asset_types
        broad_refresh = not raw_asset_types or bool(unknown_asset_types)
        needs_aandelen = broad_refresh or "aandeel" in raw_asset_types
        needs_opties = broad_refresh or "optie" in raw_asset_types
        needs_sprinters = broad_refresh or "sprinter" in raw_asset_types

        if needs_aandelen:
            stage_start = time.perf_counter()
            repository.load_aandelen_from_tx(df_tx=df_tx)
            _mark("load_aandelen_from_tx", stage_start)
        if needs_opties:
            stage_start = time.perf_counter()
            repository.load_open_opties_from_tx(df_tx=df_tx)
            _mark("load_open_opties_from_tx", stage_start)
            stage_start = time.perf_counter()
            repository.load_gesloten_opties_from_tx(df_tx=df_tx)
            _mark("load_gesloten_opties_from_tx", stage_start)
            stage_start = time.perf_counter()
            repository.load_gesloten_opties_no_broker()
            _mark("load_gesloten_opties_no_broker", stage_start)
        if needs_sprinters:
            stage_start = time.perf_counter()
            repository.load_open_sprinters_from_tx(df_tx=df_tx)
            _mark("load_open_sprinters_from_tx", stage_start)
            stage_start = time.perf_counter()
            repository.load_gesloten_sprinters_from_tx(df_tx=df_tx)
            _mark("load_gesloten_sprinters_from_tx", stage_start)
        stage_start = time.perf_counter()
        repository.build_repository_active_asset_rollup_data()
        _mark("build_repository_active_asset_rollup_data", stage_start)
        if needs_aandelen:
            stage_start = time.perf_counter()
            live_aggregator_aandelen.process_live_update(force_publish=True)
            _mark("live_aggregator_aandelen.process_live_update", stage_start)
        if needs_opties:
            stage_start = time.perf_counter()
            live_aggregator_opties.process_live_update(force_publish=True)
            _mark("live_aggregator_opties.process_live_update", stage_start)
        if needs_sprinters:
            stage_start = time.perf_counter()
            live_aggregator_sprinters.process_live_update(force_publish=True)
            _mark("live_aggregator_sprinters.process_live_update", stage_start)
        if needs_opties:
            stage_start = time.perf_counter()
            repository.portfolio_value_asset_rollup_opties_put()
            _mark("portfolio_value_asset_rollup_opties_put", stage_start)
        if needs_aandelen:
            stage_start = time.perf_counter()
            repository.portfolio_value_asset_rollup_aandelen()
            _mark("portfolio_value_asset_rollup_aandelen", stage_start)
        if needs_sprinters:
            stage_start = time.perf_counter()
            repository.portfolio_value_asset_rollup_sprinters()
            _mark("portfolio_value_asset_rollup_sprinters", stage_start)
        stage_start = time.perf_counter()
        repository.portfolio_value_asset_rollup_combined()
        _mark("portfolio_value_asset_rollup_combined", stage_start)
        ck: set[str] = set()
        for asset_hint in ((payload or {}).get("changed_assets") or []):
            if asset_hint:
                ck.add(str(asset_hint))
        asset_hint = (payload or {}).get("asset_rollup")
        if asset_hint:
            ck.add(str(asset_hint))
        if ENABLE_ENGINE_CORE_RUNTIME_EXCLUSIVE:
            stage_start = time.perf_counter()
            runtime_targets: set[str] = set()
            if needs_aandelen:
                runtime_targets.add("aandelen_v2")
            if needs_opties:
                runtime_targets.update({"opties_open_v2", "optie_tijdswaarde_v2"})
            if needs_sprinters:
                runtime_targets.add("sprinters_open_v2")
            _runtime_recompute_selected(runtime_targets, "transaction_derived", ck)
            _mark("_runtime_recompute_selected", stage_start)
        else:
            if needs_aandelen:
                stage_start = time.perf_counter()
                refresh_aandelen_projection("transaction_derived", ck)
                _mark("refresh_aandelen_projection", stage_start)
            if needs_opties:
                stage_start = time.perf_counter()
                refresh_opties_open_projection("transaction_derived")
                _mark("refresh_opties_open_projection", stage_start)
                stage_start = time.perf_counter()
                refresh_optie_tijdswaarde_projection("transaction_derived")
                _mark("refresh_optie_tijdswaarde_projection", stage_start)
            if needs_sprinters:
                stage_start = time.perf_counter()
                refresh_sprinters_open_projection("transaction_derived")
                _mark("refresh_sprinters_open_projection", stage_start)
    except Exception as exc:
        _log(f"[snapshot-refresh] failed: {exc}")
        raise
    elapsed_time = time.perf_counter() - start_time
    reason = (payload or {}).get("reason", "unknown")
    timing_str = ", ".join(f"{name}={duration * 1000:.1f}ms" for name, duration in timings)
    _log(
        "[snapshot-refresh] transaction-derived snapshots refreshed "
        f"in {elapsed_time:.2f}s ({reason}) "
        f"types={sorted(raw_asset_types) if raw_asset_types else ['ALL']} "
        f"broad={broad_refresh} | {timing_str}"
    )
    if APP_PERF_LOG:
        _log(
            f"[perf] timer=refresh_transaction_derived_snapshots total_ms={elapsed_time * 1000.0:.1f} reason={reason}"
        )


def run_startup_db_migrations():
    svc = DbMigrationService()
    results = svc.migrate_all_user_dbs()
    ok = sum(1 for r in results if r.success)
    fail = len(results) - ok
    _log(f"[db-migrate] completed: ok={ok}, failed={fail}")
    for r in results:
        if r.success:
            _log(
                f"[db-migrate] {r.database_name}: v{r.old_version} -> v{r.new_version}"
            )
        else:
            _log(f"[db-migrate] {r.database_name}: FAILED ({r.error})")
    


def main():
    global _AANDELEN_PROJECTION_ASYNC_ENABLED
    global _AANDELEN_TV_STARTUP_SEEDED
    global _AANDELEN_TV_LAST_OVERLAY_TS
    global _AANDELEN_TV_SEED_TS
    import faulthandler
    faulthandler.enable()
    startup_args = _parse_startup_args(sys.argv)
    existing_app = QApplication.instance()
    app = cast(QApplication | None, existing_app)
    if app is None:
        app = QApplication(sys.argv)
    _AANDELEN_PROJECTION_ASYNC_ENABLED = True
    signals.projectionPublishTick.connect(
        lambda key: _drain_aandelen_projection_pending() if key == "aandelen_v2" else None
    )
    font = QFont()
    font.setPointSize(9)
    demi_bold = getattr(getattr(QFont, "Weight", None), "DemiBold", None)
    if demi_bold is not None:
        font.setWeight(demi_bold)
    app.setFont(font)
    run_startup_db_migrations()
    try:
        _apply_startup_database_selection(startup_args.database_alias)
    except Exception as exc:
        _log(f"[startup-db] {exc}")
        raise SystemExit(2) from exc
    if ENABLE_ENGINE_CORE_RUNTIME:
        _log("[engine-core] runtime enabled via USE_ENGINE_CORE_RUNTIME_V1=1")
        if ENABLE_ENGINE_CORE_RUNTIME_EXCLUSIVE:
            _log("[engine-core] exclusive mode enabled via ENGINE_CORE_RUNTIME_EXCLUSIVE_V1=1")
    refresh_everything()
    state_engine_runner = StateEngineRunner(fallback_refresh=refresh_everything)
    SNAPSHOT_STORE.state_engine_runner = state_engine_runner
    historical_price_update_runner = HistoricalPriceUpdateRunner()
    app_task_scheduler = AppTaskScheduler(app)
    app_task_scheduler.register_default_tasks()
    option_timevalue_service: OptionTimevalueService | None = None
    
    # Koppel signalen aan orchestrator:
    # 1) request -> alleen state-engine starten
    # 2) finished(ok) -> daarna afgeleide snapshots verversen
    signals.stateRebuildRequested.connect(state_engine_runner.handle_rebuild_requested)
    signals.priceUpdateFinished.connect(state_engine_runner.handle_price_update_finished)
    signals.priceUpdateFinished.connect(
        lambda payload: (
            repository.load_historical_close_snapshot(),
            repository.load_asset_driver_beta_snapshot()
        ) if (payload or {}).get("status") in {"ok", "skipped"} else None
    )
    signals.databaseChanged.connect(state_engine_runner.handle_database_changed)
    # Debounce snapshot refreshes: bij een wave van price_catchup jobs
    # willen we niet na elke asset-run opnieuw alle snapshots/aggregators herladen.
    pending_refresh_payload: dict = {"reason": "unknown"}
    snapshot_counter: Counter[str] = Counter()
    refresh_timer = QTimer()
    refresh_timer.setSingleShot(True)
    refresh_timer.setInterval(2500)
    db_change_refresh_timer = QTimer()
    db_change_refresh_timer.setSingleShot(True)
    db_change_refresh_timer.setInterval(0)
    opties_projection_refresh_timer = QTimer()
    opties_projection_refresh_timer.setSingleShot(True)
    opties_projection_refresh_timer.setInterval(5000)
    optie_tijdswaarde_projection_refresh_timer = QTimer()
    optie_tijdswaarde_projection_refresh_timer.setSingleShot(True)
    optie_tijdswaarde_projection_refresh_timer.setInterval(5000)
    sprinters_projection_refresh_timer = QTimer()
    sprinters_projection_refresh_timer.setSingleShot(True)
    sprinters_projection_refresh_timer.setInterval(5000)
    if ENABLE_ENGINE_CORE_RUNTIME_EXCLUSIVE:
        _EXCLUSIVE_LIVE_RECOMPUTE_TIMERS.clear()
        _EXCLUSIVE_LIVE_RECOMPUTE_PENDING.clear()
        for snapshot_key, interval_ms in _EXCLUSIVE_LIVE_RECOMPUTE_INTERVAL_MS.items():
            timer = QTimer()
            timer.setSingleShot(True)
            timer.setInterval(interval_ms)
            timer.timeout.connect(
                lambda sk=snapshot_key: _run_exclusive_live_recompute(sk)
            )
            _EXCLUSIVE_LIVE_RECOMPUTE_TIMERS[snapshot_key] = timer
    snapshot_counter_timer = QTimer()
    snapshot_counter_timer.setInterval(60_000)
    orders_refresh_timer: QTimer | None = None
    def _run_debounced_refresh():
        refresh_transaction_derived_snapshots(dict(pending_refresh_payload))

    def _run_opties_projection_refresh():
        refresh_opties_open_projection("live_opties_snapshot")

    def _run_optie_tijdswaarde_projection_refresh():
        refresh_optie_tijdswaarde_projection("live_optie_tijdswaarde_snapshot")

    def _run_sprinters_projection_refresh():
        refresh_sprinters_open_projection("live_sprinters_snapshot")

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

    def _refresh_asset_result_snapshots(payload: dict | None):
        if (payload or {}).get("status") != "ok":
            return
        engine_class = str((payload or {}).get("engine_class") or "").strip().lower()
        if engine_class != "asset_result_v2":
            return
        repository.load_per_dag_asset_result_v2_snapshot()
        changed_keys = {
            "repository_snapshot_per_dag_asset_result_v2",
            "repository_snapshot_per_dag_asset_result_v2_latest",
        }
        if ENABLE_ENGINE_CORE_RUNTIME_EXCLUSIVE:
            _runtime_recompute_selected(
                {"aandelen_v2"},
                reason="state_engine_asset_result_v2",
                changed_keys=changed_keys,
            )
        else:
            refresh_aandelen_projection(
                "state_engine_asset_result_v2",
                changed_keys=changed_keys,
                force_sync=True,
            )

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

    def _on_snapshot_updated_counter(snapshot_key: str):
        snapshot_counter[str(snapshot_key or "")] += 1

    def _flush_snapshot_counter():
        if not APP_PERF_LOG:
            snapshot_counter.clear()
            return
        if snapshot_counter:
            top = ", ".join(
                f"{key}={count}" for key, count in snapshot_counter.most_common(20)
            )
            _log(f"[snapshot-count/min] {top}")
        else:
            _log("[snapshot-count/min] no snapshotUpdated events")
        snapshot_counter.clear()

    def _run_db_change_refresh():
        refresh_everything(force_live_publish=True)
        with contextlib.suppress(Exception):
            portfolio_engine.start_subscriptions()
        if option_timevalue_service is not None:
            option_timevalue_service.schedule_rebuild({"reason": "database_changed"})

    def _on_database_changed_refresh(db_name: str):
        _reset_aandelen_tv_overlay_regime(f"database_changed:{db_name}")
        refresh_timer.stop()
        opties_projection_refresh_timer.stop()
        optie_tijdswaarde_projection_refresh_timer.stop()
        sprinters_projection_refresh_timer.stop()
        db_change_refresh_timer.stop()
        if orders_refresh_timer is not None:
            orders_refresh_timer.stop()
        _EXCLUSIVE_LIVE_RECOMPUTE_PENDING.clear()
        for timer in _EXCLUSIVE_LIVE_RECOMPUTE_TIMERS.values():
            with contextlib.suppress(Exception):
                timer.stop()
        _invalidate_snapshots_for_database_change(option_timevalue_service)
        db_change_refresh_timer.start()

    db_change_refresh_timer.timeout.connect(_run_db_change_refresh)
    refresh_timer.timeout.connect(_run_debounced_refresh)
    opties_projection_refresh_timer.timeout.connect(_run_opties_projection_refresh)
    optie_tijdswaarde_projection_refresh_timer.timeout.connect(_run_optie_tijdswaarde_projection_refresh)
    sprinters_projection_refresh_timer.timeout.connect(_run_sprinters_projection_refresh)
    snapshot_counter_timer.timeout.connect(_flush_snapshot_counter)
    snapshot_counter_timer.start()
    signals.ordersCommitted.connect(lambda payload=None: _reset_aandelen_tv_overlay_regime("orders_committed"))
    if ENABLE_ORDERS_COMMIT_FULL_REFRESH:
        pending_orders_refresh_payload: dict = {"reason": "orders_committed"}
        def _schedule_orders_refresh(payload: dict | None = None):
            pending_orders_refresh_payload.clear()
            pending_orders_refresh_payload.update({"reason": "orders_committed"})
            if isinstance(payload, dict):
                pending_orders_refresh_payload.update(payload)
            if orders_refresh_timer is not None:
                orders_refresh_timer.start()
        def _run_orders_refresh():
            refresh_transaction_derived_snapshots(dict(pending_orders_refresh_payload))
        orders_refresh_timer = QTimer()
        orders_refresh_timer.setSingleShot(True)
        orders_refresh_timer.setInterval(250)
        orders_refresh_timer.timeout.connect(_run_orders_refresh)
        signals.ordersCommitted.connect(_schedule_orders_refresh)
        _log("[orders-refresh] enabled via ORDERS_COMMIT_FULL_REFRESH_V1=1")
    else:
        _log("[orders-refresh] disabled (no full refresh on ordersCommitted)")
    signals.stateRebuildFinished.connect(_schedule_snapshot_refresh)
    signals.stateRebuildFinished.connect(_refresh_asset_result_snapshots)
    signals.snapshotUpdated.connect(_on_snapshot_updated_counter)
    if not ENABLE_ENGINE_CORE_RUNTIME_EXCLUSIVE:
        signals.snapshotUpdated.connect(_on_snapshot_updated_for_opties_projection)
        signals.snapshotUpdated.connect(_on_snapshot_updated_for_optie_tijdswaarde_projection)
        signals.snapshotUpdated.connect(_on_snapshot_updated_for_sprinters_projection)
    if ENABLE_ENGINE_CORE_RUNTIME:
        signals.snapshotUpdated.connect(_on_snapshot_updated_engine_core)
    def _on_aandelen_projection_filter_changed(payload: dict):
        if aandelen_projection_v2 is None:
            return
        brokers = payload.get("selected_brokers")
        if isinstance(brokers, (list, set, tuple)):
            selected = {str(x).strip() for x in brokers if str(x).strip()}
        else:
            selected = set()
        aandelen_projection_v2.set_selected_brokers(selected or None)
        _log(f"[projection-v2] broker_filter_change selected={sorted(selected) if selected else ['ALL']}")
        refresh_aandelen_projection("broker_filter_change", force_sync=True)
    signals.aandelenProjectionFilterChanged.connect(_on_aandelen_projection_filter_changed)
    signals.stateRebuildFinished.connect(
        lambda payload: _log(f"[state-engine] rebuild finished: {payload}")
    )
    signals.stateRebuildFailed.connect(
        lambda message: _log(f"[state-engine] rebuild failed: {message}")
    )
    signals.priceUpdateStarted.connect(
        lambda payload: _log(f"[price-update] started: {payload}")
    )
    signals.priceUpdateFinished.connect(
        lambda payload: _log(f"[price-update] finished: {payload.get('status')} ({payload.get('fetch_start_date', 'n/a')} -> today)")
    )
    signals.priceUpdateFailed.connect(
        lambda message: _log(f"[price-update] failed: {message}")
    )
    settings = get_settings()
    price_feed = PriceFeedService(
        settings.get_ib_host(),
        settings.get_ib_port(),
        settings.get_ib_client_id()
    )
    stop_event, thread = start_live_price_updater(price_feed)
    portfolio_engine = PortfolioEngine(
        price_feed,
        live_aggregator_aandelen=live_aggregator_aandelen,
        live_aggregator_opties=live_aggregator_opties,
        live_aggregator_sprinters=live_aggregator_sprinters,
    )
    option_timevalue_service = OptionTimevalueService(price_feed, STOCKDATA_DB_PATH)
    signals.databaseChanged.connect(_on_database_changed_refresh)
    w = MainWindow(portfolio_engine, price_feed, live_price_updater_stop_event=stop_event)
    setattr(w, "option_timevalue_service", option_timevalue_service)
    w.show()
    # Start price-update pas nadat UI volledig staat en event-loop idle is.
    QTimer.singleShot(5000, historical_price_update_runner.request_startup_update)
    app_task_scheduler.start()
    if price_feed.is_ready():
        portfolio_engine.start_subscriptions()
    else:
        price_feed._feed.ready.connect(lambda: portfolio_engine.start_subscriptions())
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

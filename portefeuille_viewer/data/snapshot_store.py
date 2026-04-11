import contextlib
import inspect
import os
import time
import threading
import polars as pl
from typing import Any


_SNAPSHOT_PERF_LOG = str(os.getenv("SNAPSHOT_PERF_LOG", "1")).strip() == "1"
_SNAPSHOT_PERF_LOG_CALLER = str(os.getenv("SNAPSHOT_PERF_LOG_CALLER", "0")).strip() == "1"
_SNAPSHOT_PERF_LOG_CALLER_SLOW_MS = max(
    0.0,
    float(os.getenv("SNAPSHOT_PERF_LOG_CALLER_SLOW_MS", "0")),
)


class SnapshotStore:
    """
    Houdt de actuele datasets in geheugen.
    Wordt gevuld door repository-functies of engines,
    maar bevat zelf geen laadlogica meer.
    """

    repository_snapshot_alle_transacties: pl.DataFrame | None
    repository_snapshot_aandelen: pl.DataFrame | None
    aggregator_snapshot_aandelen_live: pl.DataFrame | None
    repository_snapshot_load_open_opties: pl.DataFrame | None
    aggregator_snapshot_load_open_opties_from_tx_live: pl.DataFrame | None
    repository_snapshot_open_sprinters: pl.DataFrame | None
    aggregator_snapshot_open_sprinters_live: pl.DataFrame | None
    repository_snapshot_gesloten_opties: pl.DataFrame | None
    repository_snapshot_gesloten_opties_no_broker: pl.DataFrame | None
    repository_snapshot_gesloten_sprinters: pl.DataFrame | None
    repository_snapshot_gesloten_sprinters_no_asset_detail: pl.DataFrame | None
    repository_snapshot_asset_rollup_data: pl.DataFrame | None
    repository_snapshot_active_asset_rollup_data: pl.DataFrame | None
    repository_snapshot_sprinter_referentie_data: pl.DataFrame | None
    repository_snapshot_optie_referentie_data: pl.DataFrame | None
    repository_snapshot_portfolio_value_aandelen: pl.DataFrame | None
    repository_snapshot_portfolio_value_aandelen_scenario: pl.DataFrame | None
    repository_snapshot_portfolio_value_optie_call_put_detailed: pl.DataFrame | None
    repository_snapshot_portfolio_value_optie_call_put_detailed_scenario: pl.DataFrame | None
    repository_snapshot_portfolio_value_optie: pl.DataFrame | None
    repository_snapshot_portfolio_value_sprinters: pl.DataFrame | None
    repository_snapshot_portfolio_value_sprinters_scenario: pl.DataFrame | None
    repository_snapshot_portfolio_value_total_combined_put: pl.DataFrame | None
    repository_snapshot_portfolio_value_total_combined_scenario: pl.DataFrame | None
    snapshot_aandelen_projection_v2_scenario: pl.DataFrame | None
    repository_portfolio_dividend: pl.DataFrame | None
    repository_snapshot_historical_ohlcv: pl.DataFrame | None
    repository_snapshot_historical_close: pl.DataFrame | None
    repository_snapshot_historical_close_latest: pl.DataFrame | None
    repository_snapshot_asset_driver_beta: pl.DataFrame | None
    repository_snapshot_per_dag_asset_result_v2: pl.DataFrame | None
    repository_snapshot_per_dag_asset_result_v2_latest: pl.DataFrame | None
    live_prices: dict | None
    repository_snapshot_test_orders_cache: dict
    repository_dirty_test_orders_assets: set
    repository_snapshot_test_order_scenarios: pl.DataFrame | None
    repository_snapshot_test_order_scenario_content: dict
    repository_dirty_test_order_scenarios: bool
    repository_snapshot_active_scenario_orders_flat: pl.DataFrame | None
    repository_snapshot_active_scenario_orders_by_asset: dict[str, pl.DataFrame]
    repository_snapshot_beta_shift_scenarios: pl.DataFrame | None
    repository_snapshot_beta_shift_scenario_content: dict[int, dict[str, float]]
    runtime_bucket23_out_of_sync: bool
    runtime_bucket23_dirty_reason: str | None
    runtime_active_test_order_scenario_id: int | None
    runtime_active_beta_shift_scenario_id: int | None
    runtime_test_orders_enabled: bool
    runtime_beta_shift_enabled: bool
    runtime_price_shift_pct: float
    runtime_price_shift_driver: str | None
    runtime_price_shift_lookback: str
    runtime_price_shift_by_index: dict[str, float]
    repository_snapshot_open_optie_comments: pl.DataFrame | None
    repository_dirty_open_optie_comments: list
    snapshot_optie_timevalue_live: pl.DataFrame | None
    snapshot_optie_timevalue_summary: pl.DataFrame | None
    snapshot_optie_timevalue_meta: pl.DataFrame | None
    test_repository_load_input_test_dataframe: pl.DataFrame | None
    test_repository_load_output_test_dataframe: pl.DataFrame | None
    snapshot_aggregated_portfolio: pl.DataFrame | None
    active_database_name: str | None
    state_engine_runner: Any | None
    _last_update_ts: dict[str, float]
    _live_prices_lock: threading.Lock

    def __init__(self):
        self._live_prices_lock = threading.Lock()
        self._apply_defaults(bucket_reason="startup")

    @staticmethod
    def _build_default_state(bucket_reason: str | None) -> dict[str, Any]:
        return {
            "repository_snapshot_alle_transacties": None,
            "repository_snapshot_aandelen": None,
            "aggregator_snapshot_aandelen_live": None,
            "repository_snapshot_load_open_opties": None,
            "aggregator_snapshot_load_open_opties_from_tx_live": None,
            "repository_snapshot_open_sprinters": None,
            "aggregator_snapshot_open_sprinters_live": None,
            "repository_snapshot_gesloten_opties": None,
            "repository_snapshot_gesloten_opties_no_broker": None,
            "repository_snapshot_gesloten_sprinters": None,
            "repository_snapshot_gesloten_sprinters_no_asset_detail": None,
            "repository_snapshot_asset_rollup_data": None,
            "repository_snapshot_active_asset_rollup_data": None,
            "repository_snapshot_sprinter_referentie_data": None,
            "repository_snapshot_optie_referentie_data": None,
            "repository_snapshot_portfolio_value_aandelen": None,
            "repository_snapshot_portfolio_value_aandelen_scenario": None,
            "repository_snapshot_portfolio_value_optie_call_put_detailed": None,
            "repository_snapshot_portfolio_value_optie_call_put_detailed_scenario": None,
            "repository_snapshot_portfolio_value_optie": None,
            "repository_snapshot_portfolio_value_sprinters": None,
            "repository_snapshot_portfolio_value_sprinters_scenario": None,
            "repository_snapshot_portfolio_value_total_combined_put": None,
            "repository_snapshot_portfolio_value_total_combined_scenario": None,
            "snapshot_aandelen_projection_v2_scenario": None,
            "repository_portfolio_dividend": None,
            "repository_snapshot_historical_ohlcv": None,
            "repository_snapshot_historical_close": None,
            "repository_snapshot_historical_close_latest": None,
            "repository_snapshot_asset_driver_beta": None,
            "repository_snapshot_per_dag_asset_result_v2": None,
            "repository_snapshot_per_dag_asset_result_v2_latest": None,
            "live_prices": None,
            "repository_snapshot_test_orders_cache": {},
            "repository_dirty_test_orders_assets": set(),
            "repository_snapshot_test_order_scenarios": None,
            "repository_snapshot_test_order_scenario_content": {},
            "repository_dirty_test_order_scenarios": False,
            "repository_snapshot_active_scenario_orders_flat": None,
            "repository_snapshot_active_scenario_orders_by_asset": {},
            "repository_snapshot_beta_shift_scenarios": None,
            "repository_snapshot_beta_shift_scenario_content": {},
            "runtime_bucket23_out_of_sync": True,
            "runtime_bucket23_dirty_reason": bucket_reason,
            "runtime_active_test_order_scenario_id": None,
            "runtime_active_beta_shift_scenario_id": None,
            "runtime_test_orders_enabled": False,
            "runtime_beta_shift_enabled": False,
            "runtime_price_shift_pct": 0.0,
            "runtime_price_shift_driver": None,
            "runtime_price_shift_lookback": "12m",
            "runtime_price_shift_by_index": {},
            "repository_snapshot_open_optie_comments": None,
            "repository_dirty_open_optie_comments": [],
            "snapshot_optie_timevalue_live": None,
            "snapshot_optie_timevalue_summary": None,
            "snapshot_optie_timevalue_meta": None,
            "test_repository_load_input_test_dataframe": None,
            "test_repository_load_output_test_dataframe": None,
            "snapshot_aggregated_portfolio": None,
            "active_database_name": None,
            "state_engine_runner": None,
            "_last_update_ts": {},
        }

    def _apply_defaults(self, bucket_reason: str | None) -> None:
        for attr_name, value in self._build_default_state(bucket_reason).items():
            setattr(self, attr_name, value)

    def clear(self):
        """Reset alle snapshots naar leeg."""
        self._apply_defaults(bucket_reason="database_change")

    def set_live_prices(self, prices: dict | None) -> None:
        with self._live_prices_lock:
            self.live_prices = dict(prices or {})

    def update_live_prices(self, new_prices: dict) -> None:
        if not new_prices:
            return
        with self._live_prices_lock:
            if self.live_prices is None:
                self.live_prices = {}
            for k, v in new_prices.items():
                if isinstance(k, tuple) and len(k) == 2:
                    self.live_prices[k] = v
                else:
                    self.live_prices[(k, None)] = v

    def clear_live_prices(self) -> None:
        with self._live_prices_lock:
            self.live_prices = {}

    def get_live_prices_snapshot(self) -> dict:
        with self._live_prices_lock:
            return dict(self.live_prices or {})

    def is_loaded(self) -> bool:
        """Controleer of er al data is geladen."""
        return any(
            value
            for value in (
                self.repository_snapshot_alle_transacties is not None,
                self.repository_snapshot_aandelen is not None,
                self.aggregator_snapshot_aandelen_live is not None,
                self.repository_snapshot_load_open_opties is not None,
                self.aggregator_snapshot_load_open_opties_from_tx_live is not None,
                self.repository_snapshot_open_sprinters is not None,
                self.aggregator_snapshot_open_sprinters_live is not None,
                self.repository_snapshot_gesloten_opties is not None,
                self.repository_snapshot_gesloten_opties_no_broker is not None,
                self.repository_snapshot_gesloten_sprinters is not None,
                self.repository_snapshot_gesloten_sprinters_no_asset_detail is not None,
                self.repository_snapshot_asset_rollup_data is not None,
                self.repository_snapshot_active_asset_rollup_data is not None,
                self.repository_snapshot_sprinter_referentie_data is not None,
                self.repository_snapshot_optie_referentie_data is not None,
                self.repository_snapshot_portfolio_value_aandelen is not None,
                self.repository_snapshot_portfolio_value_aandelen_scenario is not None,
                self.repository_snapshot_portfolio_value_optie_call_put_detailed is not None,
                self.repository_snapshot_portfolio_value_optie_call_put_detailed_scenario is not None,
                self.repository_snapshot_portfolio_value_optie is not None,
                self.repository_snapshot_portfolio_value_sprinters is not None,
                self.repository_snapshot_portfolio_value_sprinters_scenario is not None,
                self.repository_snapshot_portfolio_value_total_combined_put is not None,
                self.repository_snapshot_portfolio_value_total_combined_scenario is not None,
                self.snapshot_aandelen_projection_v2_scenario is not None,
                self.repository_portfolio_dividend is not None,
                self.repository_snapshot_historical_ohlcv is not None,
                self.repository_snapshot_historical_close is not None,
                self.repository_snapshot_historical_close_latest is not None,
                self.repository_snapshot_per_dag_asset_result_v2 is not None,
                self.repository_snapshot_per_dag_asset_result_v2_latest is not None,
                self.live_prices is not None,
                self.repository_snapshot_test_orders_cache is not None,
                self.repository_dirty_test_orders_assets is not None,
                self.repository_snapshot_active_scenario_orders_flat is not None,
                self.snapshot_optie_timevalue_live is not None,
            )
        )

    def snapshot_store_summary(self) -> str:
        """Korte tekstuele samenvatting voor debug/log."""
        parts = []
        if self.repository_snapshot_alle_transacties is not None:
            parts.append(f"Repository Alle Transacties: {len(self.repository_snapshot_alle_transacties)} rijen")
        if self.repository_snapshot_aandelen is not None:
            parts.append(f"Repository Open Aandelen: {len(self.repository_snapshot_aandelen)} rijen")
        if self.aggregator_snapshot_aandelen_live is not None:
            parts.append(f"Aggregator Live Aandelen: {len(self.aggregator_snapshot_aandelen_live)} rijen")
        if self.repository_snapshot_load_open_opties is not None:
            parts.append(f"Repository Open Opties: {len(self.repository_snapshot_load_open_opties)} rijen")
        if self.aggregator_snapshot_load_open_opties_from_tx_live is not None:
            parts.append(f"Aggregator Live Opties: {len(self.aggregator_snapshot_load_open_opties_from_tx_live)} rijen")
        if self.repository_snapshot_open_sprinters is not None:
            parts.append(f"Repository Open Sprinters: {len(self.repository_snapshot_open_sprinters)} rijen")
        if self.aggregator_snapshot_open_sprinters_live is not None:
            parts.append(f"Aggregator Live Sprinters: {len(self.aggregator_snapshot_open_sprinters_live)} rijen")
        if self.repository_snapshot_gesloten_opties is not None:
            parts.append(f"Repository Gesloten Opties: {len(self.repository_snapshot_gesloten_opties)} rijen")
        if self.repository_snapshot_gesloten_opties_no_broker is not None:
            parts.append(f"Repository Gesloten Opties (zonder broker): {len(self.repository_snapshot_gesloten_opties_no_broker)} rijen")
        if self.repository_snapshot_gesloten_sprinters is not None:
            parts.append(f"Repository Gesloten Sprinters: {len(self.repository_snapshot_gesloten_sprinters)} rijen")
        if self.repository_snapshot_gesloten_sprinters_no_asset_detail is not None:
            parts.append(f"Repository Gesloten Sprinters (zonder asset_detail): {len(self.repository_snapshot_gesloten_sprinters_no_asset_detail)} rijen")
        if self.repository_snapshot_asset_rollup_data is not None:
            parts.append(f"Repository Asset Rollup data: {len(self.repository_snapshot_asset_rollup_data)} rijen")
        if self.repository_snapshot_active_asset_rollup_data is not None:
            parts.append(f"Live Aggregator Asset Rollup data: {len(self.repository_snapshot_active_asset_rollup_data)} rijen")
        if self.repository_snapshot_sprinter_referentie_data is not None:
            parts.append(f"Repository Sprinter Referentie data: {len(self.repository_snapshot_sprinter_referentie_data)} rijen")
        if self.repository_snapshot_optie_referentie_data is not None:
            parts.append(f"Repository Optie Referentie data: {len(self.repository_snapshot_optie_referentie_data)} rijen")
        if self.repository_snapshot_portfolio_value_aandelen is not None:
            parts.append(f"Repository Portfolio Value Aandelen data: {len(self.repository_snapshot_portfolio_value_aandelen)} rijen")
        if self.repository_snapshot_portfolio_value_aandelen_scenario is not None:
            parts.append(f"Scenario Portfolio Value Aandelen data: {len(self.repository_snapshot_portfolio_value_aandelen_scenario)} rijen")
        if self.repository_snapshot_portfolio_value_optie_call_put_detailed is not None:
            parts.append(f"Repository Portfolio Value Optie Call/Put Detailed data: {len(self.repository_snapshot_portfolio_value_optie_call_put_detailed)} rijen")
        if self.repository_snapshot_portfolio_value_optie_call_put_detailed_scenario is not None:
            parts.append(f"Scenario Portfolio Value Optie Call/Put Detailed data: {len(self.repository_snapshot_portfolio_value_optie_call_put_detailed_scenario)} rijen")
        if self.repository_snapshot_portfolio_value_optie is not None:
            parts.append(f"Repository Portfolio Value Optie Put data: {len(self.repository_snapshot_portfolio_value_optie)} rijen") 
        if self.repository_snapshot_portfolio_value_sprinters is not None:
            parts.append(f"Repository Portfolio Value Sprinters data: {len(self.repository_snapshot_portfolio_value_sprinters)} rijen")
        if self.repository_snapshot_portfolio_value_sprinters_scenario is not None:
            parts.append(f"Scenario Portfolio Value Sprinters data: {len(self.repository_snapshot_portfolio_value_sprinters_scenario)} rijen")
        if self.repository_snapshot_portfolio_value_total_combined_put is not None:
            parts.append(f"Repository Portfolio Value Total Combined data: {len(self.repository_snapshot_portfolio_value_total_combined_put)} rijen")   
        if self.repository_snapshot_portfolio_value_total_combined_scenario is not None:
            parts.append(
                "Scenario Portfolio Value Total Combined data: "
                f"{len(self.repository_snapshot_portfolio_value_total_combined_scenario)} rijen"
            )
        if self.snapshot_aandelen_projection_v2_scenario is not None:
            parts.append(
                "Scenario Aandelen Projection V2 data: "
                f"{len(self.snapshot_aandelen_projection_v2_scenario)} rijen"
            )
        if self.repository_portfolio_dividend is not None:
            parts.append(f"Repository Portfolio Dividend data: {len(self.repository_portfolio_dividend)} rijen")
        if self.repository_snapshot_historical_ohlcv is not None:
            parts.append(f"Repository Historical OHLCV data: {len(self.repository_snapshot_historical_ohlcv)} rijen")
        if self.repository_snapshot_historical_close is not None:
            parts.append(f"Repository Historical Close data: {len(self.repository_snapshot_historical_close)} rijen")
        if self.repository_snapshot_historical_close_latest is not None:
            parts.append(
                f"Repository Historical Close Latest data: {len(self.repository_snapshot_historical_close_latest)} rijen"
            )
        if self.repository_snapshot_per_dag_asset_result_v2 is not None:
            parts.append(
                f"Repository Per Dag Asset Result V2 data: {len(self.repository_snapshot_per_dag_asset_result_v2)} rijen"
            )
        if self.repository_snapshot_per_dag_asset_result_v2_latest is not None:
            parts.append(
                "Repository Per Dag Asset Result V2 Latest data: "
                f"{len(self.repository_snapshot_per_dag_asset_result_v2_latest)} rijen"
            )
        if self.snapshot_aggregated_portfolio is not None:
            parts.append(f"Aggregated Portfolio: {len(self.snapshot_aggregated_portfolio)} assets")
        if self.live_prices is not None:
            parts.append(f"Live Prices: {len(self.live_prices)} items") 
        if self.repository_dirty_test_orders_assets:
            parts.append(f"Dirty Test Orders Assets: {len(self.repository_dirty_test_orders_assets)} items")
        if self.repository_snapshot_test_orders_cache:
            parts.append(f"Test Orders Cache: {len(self.repository_snapshot_test_orders_cache)} items")
        if self.repository_snapshot_active_scenario_orders_flat is not None:
            parts.append(
                "Active Scenario Orders Flat: "
                f"{len(self.repository_snapshot_active_scenario_orders_flat)} rijen"
            )
        if self.runtime_bucket23_out_of_sync:
            parts.append(
                "Bucket2/3 Out Of Sync"
                + (f": {self.runtime_bucket23_dirty_reason}" if self.runtime_bucket23_dirty_reason else "")
            )
        if self.snapshot_optie_timevalue_live is not None:
            parts.append(f"Optie Timevalue Live: {len(self.snapshot_optie_timevalue_live)} rijen")


        return " \n ".join(parts) if parts else "(geen data geladen)"

    def safe_write(self, attr_name: str, value):
        """Schrijf een snapshot-attribuut op een veilige manier.

        - Voert de setattr uit
        - Houdt een timestamp bij in self._last_update_ts
        - Roept queued emit van central signals aan (zodat UI/main-thread reageert)

        We importeren `signals` lokaal om circulaire import-problemen bij module-load te vermijden.
        """
        t0 = time.perf_counter()
        setattr(self, attr_name, value)
        # record timestamp
        with contextlib.suppress(Exception):
            self._last_update_ts[attr_name] = time.time()
        # Notify subscribers that this snapshot key is updated. Import local to avoid cycles.
        with contextlib.suppress(Exception):
            from portefeuille_viewer.signals import signals

            # Use queued emit helper to ensure main-thread delivery
            signals.queued_emit_snapshotUpdated(attr_name)
        if _SNAPSHOT_PERF_LOG:
            with contextlib.suppress(Exception):
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                should_log_caller = _SNAPSHOT_PERF_LOG_CALLER or (
                    _SNAPSHOT_PERF_LOG_CALLER_SLOW_MS > 0.0
                    and elapsed_ms >= _SNAPSHOT_PERF_LOG_CALLER_SLOW_MS
                )
                if should_log_caller:
                    caller = "unknown"
                    with contextlib.suppress(Exception):
                        frame = inspect.currentframe()
                        if frame is not None and frame.f_back is not None:
                            caller_frame = frame.f_back
                            caller = (
                                f"{os.path.basename(caller_frame.f_code.co_filename)}:"
                                f"{caller_frame.f_lineno}:{caller_frame.f_code.co_name}"
                            )
                    print(
                        f"[snapshot-write] key={attr_name} ms={elapsed_ms:.1f} caller={caller}"
                    )
                else:
                    print(f"[snapshot-write] key={attr_name} ms={elapsed_ms:.1f}")



# Globale instantie — kan hergebruikt worden in UI of engines
SNAPSHOT_STORE = SnapshotStore()

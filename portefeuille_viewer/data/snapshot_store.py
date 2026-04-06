import contextlib
import polars as pl
from typing import Any


class SnapshotStore:
    """
    Houdt de actuele datasets in geheugen.
    Wordt gevuld door repository-functies of engines,
    maar bevat zelf geen laadlogica meer.
    """

    def __init__(self):
        # Polars DataFrames (standaard leeg)
        self.repository_snapshot_alle_transacties: pl.DataFrame | None = None
        self.repository_snapshot_aandelen: pl.DataFrame | None = None
        self.aggregator_snapshot_aandelen_live: pl.DataFrame | None = None  # NIEUW: live geaggregeerde aandelen data
        self.repository_snapshot_load_open_opties: pl.DataFrame | None = None
        self.aggregator_snapshot_load_open_opties_from_tx_live: pl.DataFrame | None = None  # NIEUW: live opties data met koersen
        self.repository_snapshot_open_sprinters: pl.DataFrame | None = None
        self.aggregator_snapshot_open_sprinters_live: pl.DataFrame | None = None  # NIEUW: live sprinters data met koersen met broker
        self.repository_snapshot_gesloten_opties: pl.DataFrame | None = None
        self.repository_snapshot_gesloten_opties_no_broker: pl.DataFrame | None = None
        self.repository_snapshot_gesloten_sprinters: pl.DataFrame | None = None
        self.repository_snapshot_gesloten_sprinters_no_asset_detail: pl.DataFrame | None = None
        self.repository_snapshot_asset_rollup_data: pl.DataFrame | None = None
        self.repository_snapshot_active_asset_rollup_data: pl.DataFrame | None = None  # NIEUW: live asset rollup data met koersen
        self.repository_snapshot_sprinter_referentie_data: pl.DataFrame | None = None  # NIEUW: referentie data voor sprinters
        self.repository_snapshot_optie_referentie_data: pl.DataFrame | None = None  # NIEUW: referentie data voor opties
        self.repository_snapshot_portfolio_value_aandelen: pl.DataFrame | None = None
        self.repository_snapshot_portfolio_value_aandelen_scenario: pl.DataFrame | None = None
        self.repository_snapshot_portfolio_value_optie_call_put_detailed: pl.DataFrame | None = None
        self.repository_snapshot_portfolio_value_optie_call_put_detailed_scenario: pl.DataFrame | None = None
        self.repository_snapshot_portfolio_value_optie: pl.DataFrame | None = None
        self.repository_snapshot_portfolio_value_sprinters: pl.DataFrame | None = None
        self.repository_snapshot_portfolio_value_sprinters_scenario: pl.DataFrame | None = None
        self.repository_snapshot_portfolio_value_total_combined_put: pl.DataFrame | None = None
        self.repository_snapshot_portfolio_value_total_combined_scenario: pl.DataFrame | None = None
        self.snapshot_aandelen_projection_v2_scenario: pl.DataFrame | None = None
        self.repository_portfolio_dividend: pl.DataFrame | None = None
        self.repository_snapshot_historical_ohlcv: pl.DataFrame | None = None
        self.repository_snapshot_historical_close: pl.DataFrame | None = None
        self.repository_snapshot_historical_close_latest: pl.DataFrame | None = None
        self.repository_snapshot_asset_driver_beta: pl.DataFrame | None = None
        self.repository_snapshot_per_dag_asset_result_v2: pl.DataFrame | None = None
        self.repository_snapshot_per_dag_asset_result_v2_latest: pl.DataFrame | None = None
        self.live_prices: dict | None = None
        self.repository_snapshot_test_orders_cache: dict = {}
        self.repository_dirty_test_orders_assets: set = set()
        self.repository_snapshot_active_scenario_orders_flat: pl.DataFrame | None = None
        self.repository_snapshot_active_scenario_orders_by_asset: dict[str, pl.DataFrame] = {}
        self.runtime_bucket23_out_of_sync: bool = True
        self.runtime_bucket23_dirty_reason: str | None = "startup"
        self.runtime_active_test_order_scenario_id: int | None = None
        self.runtime_test_orders_enabled: bool = False
        self.runtime_price_shift_pct: float = 0.0
        self.runtime_price_shift_driver: str | None = None
        self.runtime_price_shift_lookback: str = "12m"
        self.repository_snapshot_open_optie_comments: pl.DataFrame | None = None
        self.repository_dirty_open_optie_comments: list = []
        self.snapshot_optie_timevalue_live: pl.DataFrame | None = None
        self.snapshot_optie_timevalue_summary: pl.DataFrame | None = None
        self.snapshot_optie_timevalue_meta: pl.DataFrame | None = None
        self.test_repository_load_input_test_dataframe: pl.DataFrame | None = None
        self.test_repository_load_output_test_dataframe: pl.DataFrame | None = None  # DEBUG: tijdelijk voor UI debug
        self.snapshot_aggregated_portfolio: pl.DataFrame | None = None
        self.active_database_name: str | None = None
        self.state_engine_runner: Any | None = None
        self._last_update_ts = {}

    def clear(self):
        """Reset alle snapshots naar leeg."""
        self.repository_snapshot_alle_transacties = None
        self.repository_snapshot_aandelen = None
        self.aggregator_snapshot_aandelen_live = None
        self.repository_snapshot_load_open_opties = None
        self.aggregator_snapshot_load_open_opties_from_tx_live = None
        self.repository_snapshot_open_sprinters = None
        self.aggregator_snapshot_open_sprinters_live = None
        self.repository_snapshot_gesloten_opties = None
        self.repository_snapshot_gesloten_opties_no_broker = None
        self.repository_snapshot_gesloten_sprinters = None
        self.repository_snapshot_gesloten_sprinters_no_asset_detail = None
        self.snapshot_aggregated_portfolio = None
        self.repository_snapshot_asset_rollup_data = None
        self.repository_snapshot_active_asset_rollup_data = None
        self.repository_snapshot_sprinter_referentie_data = None
        self.repository_snapshot_portfolio_value_aandelen = None
        self.repository_snapshot_portfolio_value_aandelen_scenario = None
        self.repository_snapshot_portfolio_value_optie_call_put_detailed = None
        self.repository_snapshot_portfolio_value_optie_call_put_detailed_scenario = None
        self.repository_snapshot_portfolio_value_optie = None
        self.repository_snapshot_portfolio_value_sprinters = None
        self.repository_snapshot_portfolio_value_sprinters_scenario = None
        self.repository_snapshot_portfolio_value_total_combined_put = None
        self.repository_snapshot_portfolio_value_total_combined_scenario = None
        self.snapshot_aandelen_projection_v2_scenario = None
        self.repository_snapshot_optie_referentie_data = None
        self.repository_portfolio_dividend = None
        self.repository_snapshot_historical_ohlcv = None
        self.repository_snapshot_historical_close = None
        self.repository_snapshot_historical_close_latest = None
        self.repository_snapshot_asset_driver_beta = None
        self.repository_snapshot_per_dag_asset_result_v2 = None
        self.repository_snapshot_per_dag_asset_result_v2_latest = None
        self.active_database_name = None
        self.live_prices = None
        self.repository_snapshot_test_orders_cache = {}
        self.repository_dirty_test_orders_assets = set()
        self.repository_snapshot_active_scenario_orders_flat = None
        self.repository_snapshot_active_scenario_orders_by_asset = {}
        self.runtime_bucket23_out_of_sync = True
        self.runtime_bucket23_dirty_reason = "database_change"
        self.runtime_active_test_order_scenario_id = None
        self.runtime_test_orders_enabled = False
        self.runtime_price_shift_pct = 0.0
        self.runtime_price_shift_driver = None
        self.runtime_price_shift_lookback = "12m"
        self.repository_snapshot_open_optie_comments = None
        self.repository_dirty_open_optie_comments = []
        self.snapshot_optie_timevalue_live = None
        self.snapshot_optie_timevalue_summary = None
        self.snapshot_optie_timevalue_meta = None
        self.state_engine_runner = None

    def is_loaded(self) -> bool:
        """Controleer of er al data is geladen."""
        return any([
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
        ])

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
        setattr(self, attr_name, value)
        import time
        # record timestamp
        with contextlib.suppress(Exception):
            self._last_update_ts[attr_name] = time.time()
        # Notify subscribers that this snapshot key is updated. Import local to avoid cycles.
        with contextlib.suppress(Exception):
            from portefeuille_viewer.signals import signals

            # Use queued emit helper to ensure main-thread delivery
            signals.queued_emit_snapshotUpdated(attr_name)



# Globale instantie — kan hergebruikt worden in UI of engines
SNAPSHOT_STORE = SnapshotStore()

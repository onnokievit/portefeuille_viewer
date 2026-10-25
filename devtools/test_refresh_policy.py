"""Refresh regression tests without production databases or network access."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from portefeuille_viewer.services.refresh_policy import SnapshotCoverage, shared_refresh_plan


def main_callback(name, namespace):
    root = Path(__file__).parents[1]
    tree = ast.parse((root / (root.name + '.py')).read_text(encoding='utf-8-sig'))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<main callback>', 'exec'), namespace)
    return namespace[name]


class RefreshPolicyTests(unittest.TestCase):
    def test_delayed_timer_skips_covered_source_but_keeps_new_update(self):
        source = object()
        store = SimpleNamespace(aggregator_snapshot_load_open_opties_from_tx_live=source)
        coverage = SnapshotCoverage()
        refresh = Mock()
        callback = main_callback('_run_opties_projection_refresh', {
            '_PROJECTION_COVERAGE': coverage, 'SNAPSHOT_STORE': store,
            'refresh_opties_open_projection': refresh})
        coverage.mark({'opties_open_v2'}, store)
        callback()
        refresh.assert_not_called()
        store.aggregator_snapshot_load_open_opties_from_tx_live = object()
        callback()
        refresh.assert_called_once_with('live_opties_snapshot')
        coverage.clear()
        self.assertTrue(coverage.needs_refresh('opties_open_v2', store))

    def test_state_completion_refreshes_results_without_second_transaction_wave(self):
        tx = Mock(); results = Mock()
        namespace = dict(pending_refresh_payload={'status': 'ok', 'engine_class': 'asset_result_v2'},
                         ENABLE_ORDERS_COMMIT_FULL_REFRESH=True,
                         refresh_transaction_derived_snapshots=tx,
                         _refresh_asset_result_snapshots=results)
        callback = main_callback('_run_debounced_refresh', namespace)
        callback(); tx.assert_not_called(); results.assert_called_once()
        namespace['ENABLE_ORDERS_COMMIT_FULL_REFRESH'] = False
        callback(); tx.assert_called_once()

    def test_beta_and_dividend_do_not_restart_universe_or_aggregators(self):
        for domain in ('asset_driver_beta_snapshot', 'asset_dividend_calendar_current'):
            plan = shared_refresh_plan({domain})
            self.assertEqual(plan['aggregators'], set())
            self.assertFalse(plan['subscriptions'])
            self.assertFalse(plan['option_rebuild'])
            self.assertTrue(plan['projections'])

    def test_combined_domains_preserve_all_required_work(self):
        plan = shared_refresh_plan({'historical_data_correct', 'sprinters_referentie_data'})
        self.assertEqual(plan['aggregators'], {'sprinters'})
        self.assertTrue(plan['catchup']); self.assertTrue(plan['option_rebuild'])
        self.assertFalse(plan['subscriptions'])
        plan = shared_refresh_plan({'asset_rollup_data'})
        self.assertEqual(plan['aggregators'], {'aandelen', 'opties', 'sprinters'})
        self.assertTrue(plan['subscriptions']); self.assertTrue(plan['option_rebuild'])

    def test_real_shared_callback_keeps_beta_update_out_of_subscription_path(self):
        repository = Mock(); engine = Mock(); option_service = Mock()
        aggregators = [Mock(), Mock(), Mock()]
        projections = Mock(); portfolio = Mock()
        callback = main_callback('_shared_refresh', dict(
            shared_refresh_plan=shared_refresh_plan, repository=repository,
            live_aggregator_aandelen=aggregators[0], live_aggregator_opties=aggregators[1],
            live_aggregator_sprinters=aggregators[2], _refresh_phase_portfolio_values=portfolio,
            _refresh_phase_projections=projections, _refresh_active_scenario_overlays=Mock(),
            portfolio_engine=engine, option_timevalue_service=option_service,
            state_engine_runner=Mock(), _log=Mock(), w=Mock(), shared_data_watcher=Mock()))
        callback({'asset_driver_beta_snapshot'})
        engine.start_subscriptions.assert_not_called()
        option_service.schedule_rebuild.assert_not_called()
        portfolio.assert_not_called()
        for aggregator in aggregators:
            aggregator.process_live_update.assert_not_called()
        projections.assert_called_once_with('shared_stockdata_changed')

    def test_quote_updates_central_snapshot_without_polling_thread(self):
        from portefeuille_viewer.services.price_feed import PriceFeedService
        from portefeuille_viewer.data.asset_last_price_store import AssetLastPriceStore
        from portefeuille_viewer.data.snapshot_store import SnapshotStore
        store = SnapshotStore(); price_cache = AssetLastPriceStore()
        feed = SimpleNamespace(store=Mock(), _shared_proxy=True, _asset_processed_at={},
                               priceUpdated=Mock())
        with patch('portefeuille_viewer.services.price_feed.ASSET_LAST_PRICE_STORE', price_cache), \
             patch('portefeuille_viewer.data.asset_last_price_store.SNAPSHOT_STORE', store):
            PriceFeedService._on_price(feed, 'AAPL', 'USD', 123.)
        self.assertEqual(store.get_live_prices_snapshot()[('AAPL', 'USD')], 123.)
        self.assertFalse(price_cache._dirty_keys)
        feed.priceUpdated.emit.assert_called_once_with('AAPL', 'USD', 123.)


if __name__ == '__main__':
    unittest.main()

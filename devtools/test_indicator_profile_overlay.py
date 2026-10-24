import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

import polars as pl
from polars.testing import assert_frame_equal
from PySide6.QtWidgets import QApplication

from portefeuille_viewer.data.snapshot_store import SnapshotStore
from portefeuille_viewer.services import asset_indicator_service as service
from portefeuille_viewer.services import history_indicator_runner as runner_module
from portefeuille_viewer.services import projection_worker
from portefeuille_viewer.services.shared_asset_history import SharedAssetHistory


def inputs():
    store = SnapshotStore()
    store.repository_snapshot_asset_rollup_data = pl.DataFrame({
        'asset_rollup': ['A', 'B'], 'asset_type': ['aandeel', 'aandeel'],
        'asset_name': ['Asset A', 'Asset B'], 'indicator_rol': ['medium_value_theta'] * 2})
    store.repository_snapshot_historical_ohlcv = pl.DataFrame([
        dict(asset_rollup=asset, datum=date(2025, 1, 1) + timedelta(days=i),
             open_price=100.+i, high_price=102.+i, low_price=99.+i,
             close_price=101.+i, volume_value=10000.+i*5, implied_volatility=.25)
        for asset in ['A', 'B'] for i in range(90)])
    return store


def options(iv=.6, theta=-.2):
    return pl.DataFrame(dict(asset=['A'], time_total=[500.], time_per_unit=[5.],
        iv=[iv], theta=[theta], qty_open=[-100.]))


class ProfileOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cache_dir = self.tmp.name
        self.cache_patch = patch('portefeuille_viewer.services.shared_asset_history.SharedAssetHistory',
            side_effect=lambda path: SharedAssetHistory(path, cache_dir))
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def build(self, store):
        with patch.object(service, 'SNAPSHOT_STORE', store):
            result = service.AssetIndicatorService().rebuild(persist_history=False)
        self.assertEqual(result.status, 'ok', result.error)
        return result

    def test_shared_basis_contains_no_profile_data_and_is_computed_once(self):
        onno = inputs()
        onno.snapshot_optie_timevalue_live = options(.6)
        muriel = inputs()
        muriel.snapshot_optie_timevalue_live = options(.9)
        with patch.object(service, '_calculate_asset_history', wraps=service._calculate_asset_history) as calculate:
            one = self.build(onno)
            two = self.build(muriel)
        self.assertEqual(calculate.call_count, 2)  # Once per asset, not per profile.
        self.assertEqual(one.generation_key, two.generation_key)
        assert_frame_equal(one.historical_df.drop('as_of'), two.historical_df.drop('as_of'))
        self.assertTrue(one.historical_df['theta_score'].is_null().all())
        self.assertEqual(one.historical_df['ibkr_iv_proxy_pct'].to_list(), [25., 25.])
        self.assertNotEqual(onno.snapshot_asset_indicator_live['ibkr_iv_proxy_pct'][0],
                            muriel.snapshot_asset_indicator_live['ibkr_iv_proxy_pct'][0])
        # The asset without own options keeps the complete historical advice.
        self.assertEqual(onno.snapshot_asset_indicator_live['primary_action'][1],
                         one.historical_df['primary_action'][1])

    def test_incomplete_option_data_does_not_create_zero_theta_or_override_iv(self):
        store = inputs()
        store.aggregator_snapshot_load_open_opties_from_tx_live = pl.DataFrame({'asset_rollup': ['A']})
        store.snapshot_optie_timevalue_live = options(theta=None)
        result = self.build(store)
        row = store.snapshot_asset_indicator_live.row(0, named=True)
        self.assertIsNone(row['theta_score'])
        self.assertEqual(row['ibkr_iv_proxy_pct'], result.historical_df['ibkr_iv_proxy_pct'][0])
        self.assertEqual(row['profile_option_status'], 'optiegegevens ontbreken')
        store.snapshot_optie_timevalue_live = pl.concat([options(), options(theta=None)], how='vertical_relaxed')
        with patch.object(service, 'SNAPSHOT_STORE', store):
            updated = service.AssetIndicatorService().apply_profile_overlay(result.historical_df)
        self.assertEqual(updated['profile_option_status'][0], 'optiegegevens gedeeltelijk')
        self.assertIsNotNone(updated['theta_score'][0])

    def test_late_options_recompute_only_affected_row_and_closing_restores_basis(self):
        store = inputs()
        result = self.build(store)
        self.assertIn('laden', store.snapshot_asset_indicator_live['profile_option_status'][0])
        store.aggregator_snapshot_load_open_opties_from_tx_live = pl.DataFrame({'asset_rollup': ['A']})
        store.snapshot_optie_timevalue_live = options()
        builder = service.AssetIndicatorService()
        with patch.object(service, 'SNAPSHOT_STORE', store), \
             patch.object(builder, '_build_asset_row', wraps=builder._build_asset_row) as build:
            updated = builder.apply_profile_overlay(result.historical_df)
            self.assertEqual(build.call_count, 1)
            store.snapshot_asset_indicator_live = updated
            again = builder.apply_profile_overlay(result.historical_df)
            self.assertEqual(build.call_count, 1)
            assert_frame_equal(updated, again)
            # Closing the last position can precede the timevalue publication.
            store.aggregator_snapshot_load_open_opties_from_tx_live = pl.DataFrame(schema={'asset_rollup': pl.String})
            closed = builder.apply_profile_overlay(result.historical_df)
        self.assertIsNone(closed['theta_score'][0])
        self.assertEqual(closed['ibkr_iv_proxy_pct'][0], 25.)
        self.assertEqual(closed['profile_option_status'][0], 'geen open opties')

    def test_history_and_role_changes_create_a_new_shared_generation(self):
        store = inputs()
        first = self.build(store)
        store.repository_snapshot_historical_ohlcv = store.repository_snapshot_historical_ohlcv.with_columns(
            (pl.col('close_price') + 1).alias('close_price'))
        second = self.build(store)
        self.assertNotEqual(first.generation_key, second.generation_key)
        store.repository_snapshot_asset_rollup_data = store.repository_snapshot_asset_rollup_data.with_columns(
            pl.lit('high_beta_speculative').alias('indicator_rol'))
        third = self.build(store)
        self.assertNotEqual(second.generation_key, third.generation_key)

    def test_no_publication_when_disabled(self):
        store = inputs()
        with patch.object(service, 'SNAPSHOT_STORE', store):
            result = service.AssetIndicatorService().rebuild(publish_snapshots=False, persist_history=False)
        self.assertEqual(result.status, 'ok', result.error)
        self.assertIsNone(store.snapshot_asset_indicator_basis)
        self.assertIsNone(store.snapshot_asset_indicator_live)

    def test_previous_option_series_on_same_asset_is_not_reused(self):
        store = inputs()
        store.aggregator_snapshot_load_open_opties_from_tx_live = pl.DataFrame(dict(
            asset_rollup=['A'], broker=['ibkr'], optie_exp_date=[date(2026, 12, 18)],
            optie_call_put=['call'], optie_strike=[200.], SomVantransactie_aantal=[-100.]))
        store.snapshot_optie_timevalue_live = options().with_columns(
            pl.lit('ibkr').alias('broker'), pl.lit(date(2026, 12, 18)).alias('exp'),
            pl.lit('call').alias('c_p'), pl.lit(190.).alias('strike'))
        result = self.build(store)
        self.assertIsNone(store.snapshot_asset_indicator_live['theta_score'][0])
        store.snapshot_optie_timevalue_live = store.snapshot_optie_timevalue_live.with_columns(
            pl.lit(200.).alias('strike'))
        with patch.object(service, 'SNAPSHOT_STORE', store):
            updated = service.AssetIndicatorService().apply_profile_overlay(result.historical_df)
        self.assertIsNotNone(updated['theta_score'][0])

    def test_storage_rejects_profile_result_before_opening_database(self):
        store = inputs()
        store.snapshot_optie_timevalue_live = options()
        result = self.build(store)
        with patch.object(runner_module.repository, 'get_stockdata_connection') as connect:
            with self.assertRaises(ValueError):
                service._persist_signal_history(run_id='bad', started_at=datetime.now(),
                    duration_ms=0., status='ok', error='', live_df=store.snapshot_asset_indicator_live,
                    generation_key=result.generation_key, raise_errors=True)
            connect.assert_not_called()

    def test_timer_updates_late_options_without_database_save(self):
        store = inputs()
        self.build(store)
        published = []
        with patch.object(service, 'SNAPSHOT_STORE', store), \
             patch.object(projection_worker, 'SNAPSHOT_STORE', store), \
             patch.object(service, '_persist_signal_history') as save:
            runner = runner_module.HistoryIndicatorRunner()
            try:
                runner._option_timer.setInterval(20)
                runner.finished.connect(published.append)
                store.snapshot_optie_timevalue_live = options()
                # Repeated events cannot postpone the first timer deadline.
                for _ in range(20):
                    runner._on_snapshot_updated('snapshot_optie_timevalue_live')
                end = time.monotonic()+3
                while not published and time.monotonic()<end:
                    self.app.processEvents()
                    time.sleep(.002)
                self.assertEqual(len(published), 1)
                self.assertIsNotNone(store.snapshot_asset_indicator_live['theta_score'][0])
                save.assert_not_called()
            finally:
                runner.shutdown()

    def test_options_arriving_during_first_run_are_retained_and_only_basis_is_saved(self):
        store = inputs()
        entered = threading.Event()
        release = threading.Event()
        original = service._calculate_asset_history
        def slow_history(rows):
            entered.set()
            release.wait(3)
            return original(rows)
        published = []
        with patch.object(service, 'SNAPSHOT_STORE', store), \
             patch.object(projection_worker, 'SNAPSHOT_STORE', store), \
             patch.object(service, '_calculate_asset_history', side_effect=slow_history), \
             patch.object(service, '_persist_signal_history', return_value='saved') as save:
            runner = runner_module.HistoryIndicatorRunner()
            try:
                runner._option_timer.setInterval(10)
                runner.finished.connect(published.append)
                runner.request()
                self.assertTrue(entered.wait(1))
                store.snapshot_optie_timevalue_live = options()
                runner._on_snapshot_updated('snapshot_optie_timevalue_live')
                # Consume notification before a basis is published.
                runner._refresh_options()
                self.assertTrue(runner._options_dirty)
                release.set()
                end = time.monotonic()+3
                while (len(published)<2 or runner.writer.busy) and time.monotonic()<end:
                    self.app.processEvents()
                    time.sleep(.002)
                self.assertGreaterEqual(len(published), 2)
                self.assertIsNotNone(store.snapshot_asset_indicator_live['theta_score'][0])
                save.assert_called_once()
                self.assertTrue(save.call_args.kwargs['live_df']['theta_score'].is_null().all())
                self.assertEqual(save.call_args.kwargs['live_df']['ibkr_iv_proxy_pct'][0], 25.)
                self.assertTrue(save.call_args.kwargs['generation_key'])
            finally:
                release.set()
                runner.shutdown()


if __name__ == '__main__':
    unittest.main()

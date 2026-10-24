import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import polars as pl
from portefeuille_viewer.ui_logica import asset_indicator_web_tab as module


class IndicatorStartupTests(unittest.TestCase):
    def tab(self):
        tab=SimpleNamespace(_js_ready=False,_is_active=False,_initial_run_requested=False,
                            _runner=Mock(),btn_run=Mock(),status_label=Mock(),
                            _publish_snapshot=Mock(),_render_timer=Mock())
        tab.run_indicator=lambda:module.AssetIndicatorWebTab.run_indicator(tab)
        tab.set_active=lambda active:module.AssetIndicatorWebTab.set_active(tab,active)
        return tab

    def test_activate_before_web_ready_starts_once_without_switching_tabs(self):
        tab=self.tab();store=SimpleNamespace(snapshot_asset_indicator_live=None)
        with patch.object(module,'SNAPSHOT_STORE',store):
            tab.set_active(True)
            tab._runner.request.assert_called_once_with(reason='indicator_tab')
            module.AssetIndicatorWebTab._on_web_loaded(tab,True)
            tab.set_active(False);tab.set_active(True)
            tab._runner.request.assert_called_once()

    def test_web_ready_before_activation_does_not_start_inactive_tab(self):
        tab=self.tab();store=SimpleNamespace(snapshot_asset_indicator_live=None)
        with patch.object(module,'SNAPSHOT_STORE',store):
            module.AssetIndicatorWebTab._on_web_loaded(tab,True)
            tab._runner.request.assert_not_called()
            tab.set_active(True)
            tab._runner.request.assert_called_once()

    def test_result_ready_before_html_is_published_when_html_arrives(self):
        tab=self.tab();store=SimpleNamespace(snapshot_asset_indicator_live=None)
        with patch.object(module,'SNAPSHOT_STORE',store):
            tab.set_active(True)
            store.snapshot_asset_indicator_live=pl.DataFrame({'score':[7]})
            module.AssetIndicatorWebTab._on_web_loaded(tab,True)
            tab._publish_snapshot.assert_called_once()
            tab._runner.request.assert_called_once()

    def test_failed_initial_request_can_be_retried_on_next_activation(self):
        tab=self.tab();store=SimpleNamespace(snapshot_asset_indicator_live=None)
        with patch.object(module,'SNAPSHOT_STORE',store):
            tab.set_active(True)
            module.AssetIndicatorWebTab._on_run_failed(tab,'intentional')
            tab.set_active(False);tab.set_active(True)
            self.assertEqual(tab._runner.request.call_count,2)


if __name__=='__main__':unittest.main()

"""Reference snapshot events must not enter Access/COM on the GUI thread."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import polars as pl

from portefeuille_viewer.data import repository as repo


class ReferenceSnapshotTests(unittest.TestCase):
    def sources(self, **kwargs):
        data = dict(repository_snapshot_asset_rollup_data=pl.DataFrame({'asset_rollup':['XLV','XLV',None,'SPY']}),
            repository_snapshot_sprinter_referentie_data=pl.DataFrame({'asset_detail':['X','X',None]}),
            repository_snapshot_alle_transacties=pl.DataFrame({'broker':['IBKR','ibkr','other']}))
        data.update(kwargs)
        return SimpleNamespace(**data)

    def test_complete_snapshots_never_open_any_database(self):
        with patch.object(repo, 'SNAPSHOT_STORE', self.sources()), \
             patch.object(repo, 'get_settings', return_value=SimpleNamespace(get_brokers=lambda: [])), \
             patch.object(repo, 'get_stockdata_connection') as stock, \
             patch.object(repo, 'get_connection') as user:
            self.assertEqual(repo.load_reference_lists(), (['ibkr','other'], ['XLV','SPY'], ['X']))
            stock.assert_not_called()
            user.assert_not_called()

    def test_snapshot_callback_never_falls_back_to_database_when_data_missing(self):
        with patch.object(repo, 'SNAPSHOT_STORE', self.sources(
                    repository_snapshot_asset_rollup_data=None,
                    repository_snapshot_sprinter_referentie_data=None,
                    repository_snapshot_alle_transacties=None)), \
             patch.object(repo, 'get_settings', return_value=SimpleNamespace(get_brokers=lambda: [])), \
             patch.object(repo, 'get_stockdata_connection') as stock, \
             patch.object(repo, 'get_connection') as user:
            self.assertEqual(repo.load_reference_lists(snapshot_only=True), ([], [], []))
            stock.assert_not_called()
            user.assert_not_called()

    def test_empty_loaded_snapshot_is_valid_and_not_replaced_by_stale_database(self):
        with patch.object(repo, 'SNAPSHOT_STORE', self.sources(
                    repository_snapshot_asset_rollup_data=pl.DataFrame(schema={'asset_rollup':pl.String}))), \
             patch.object(repo, 'get_settings', return_value=SimpleNamespace(get_brokers=lambda: ['IBKR'])), \
             patch.object(repo, '_load_stock_reference_lists') as read:
            self.assertEqual(repo.load_reference_lists(), (['ibkr'], [], ['X']))
            read.assert_not_called()

    def test_missing_startup_snapshot_keeps_available_snapshot_and_fills_only_missing(self):
        with patch.object(repo, 'SNAPSHOT_STORE', self.sources(repository_snapshot_sprinter_referentie_data=None)), \
             patch.object(repo, 'get_settings', return_value=SimpleNamespace(get_brokers=lambda: ['IBKR'])), \
             patch.object(repo, '_load_stock_reference_lists', return_value=(['WRONG'],['DB_SPRINTER'])):
            self.assertEqual(repo.load_reference_lists(), (['ibkr'], ['XLV','SPY'], ['DB_SPRINTER']))

    def test_orders_snapshot_handler_requests_memory_only_lists(self):
        from portefeuille_viewer.ui_logica.orders_tab_widget import OrdersTabWidget
        class Combo:
            def __init__(self):
                self.text, self.items = 'typed value', []
            def currentText(self):
                return self.text
            def set_items(self, items):
                self.items, self.text = items, ''
            def setCurrentText(self, text):
                self.text = text
        parts = [{key: Combo() for key in ['broker','asset_rollup','detail']} for _ in range(2)]
        host = SimpleNamespace(order1=parts[0], order2=parts[1])
        host._reload_reference_lists = lambda: OrdersTabWidget._reload_reference_lists(host)
        with patch.object(repo, 'SNAPSHOT_STORE', self.sources(repository_snapshot_sprinter_referentie_data=None)), \
             patch.object(repo, 'get_settings', return_value=SimpleNamespace(get_brokers=lambda: ['IBKR'])), \
             patch.object(repo, '_load_stock_reference_lists') as db:
            OrdersTabWidget._on_snapshot_updated(host, 'repository_snapshot_asset_rollup_data')
            db.assert_not_called()
        self.assertEqual(parts[0]['asset_rollup'].items, ['XLV','SPY'])
        self.assertTrue(all(widget.text == 'typed value' for part in parts for widget in part.values()))


if __name__ == '__main__':
    unittest.main()

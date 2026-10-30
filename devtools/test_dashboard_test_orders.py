"""Scenario payoff and native-editor reuse checks; no database writes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import polars as pl
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget, QTableWidget, QTableWidgetItem, QCheckBox, QComboBox, QPushButton, QVBoxLayout
from devtools.test_asset_dashboard_analytics import fixture
from portefeuille_viewer.services.asset_dashboard_analytics import calculate_analytics
from portefeuille_viewer.services.asset_dashboard_test_orders import DashboardTestOrders

class ScenarioPayoffTests(unittest.TestCase):
    def test_selected_orders_only_and_original_snapshots_unchanged(self):
        store,payload,settings=fixture()
        baseline=calculate_analytics(store,payload,settings)['payoff']['values'][9][8]
        original=store.repository_snapshot_load_open_opties.clone()
        store.dashboard_test_orders=pl.DataFrame([
            dict(asset_rollup='AAPL',broker='test',asset_type='optie',transactie_type='verkoop',transactie_aantal=100.,transactie_prijs=2.,optie_call_put='call',optie_exp_date='2026-12-18',optie_strike=120.,include=1),
            dict(asset_rollup='AAPL',broker='test',asset_type='aandeel',transactie_type='koop',transactie_aantal=5.,transactie_prijs=90.,optie_call_put=None,optie_exp_date=None,optie_strike=None,include=1),
            dict(asset_rollup='AAPL',broker='test',asset_type='aandeel',transactie_type='koop',transactie_aantal=10000.,transactie_prijs=1.,optie_call_put=None,optie_exp_date=None,optie_strike=None,include=0),
        ])
        self.assertEqual(calculate_analytics(store,payload,settings)['payoff']['values'][9][8],baseline)
        settings['test_orders_enabled']=True
        payoff=calculate_analytics(store,payload,settings)['payoff']
        self.assertTrue(payoff['test_orders'])
        self.assertAlmostEqual(payoff['values'][9][8]-baseline,250/1.2)
        self.assertTrue(store.repository_snapshot_load_open_opties.equals(original))

class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_editor_restores_same_widgets_and_geometry(self):
        for use_layout in (False,True):
            parent=QWidget();dashboard=QWidget();dashboard._timer=SimpleNamespace(isActive=lambda:False,start=Mock())
            target=SimpleNamespace(_refresh_test_orders_view_for_active_asset=Mock())
            layout=QVBoxLayout(parent) if use_layout else None
            for name,kind in [('checkBoxEnableTestOrders',QCheckBox),('checkBoxAssetOrdersOnly',QCheckBox),('comboboxScenarioSelector',QComboBox),('buttonEditScenarios',QPushButton),('buttonAddTestOrder',QPushButton),('buttonDeleteTestOrder',QPushButton),('testOrdersTable',QTableWidget)]:
                widget=kind(parent);widget.setGeometry(5,7,150,40)
                if layout:layout.addWidget(widget)
                setattr(target,name,widget)
            service=DashboardTestOrders(target,dashboard)
            original=target.testOrdersTable
            geometry=original.geometry()
            QTimer.singleShot(20,lambda: service.dialog.reject())
            service.open_editor()
            self.assertIs(target.testOrdersTable,original)
            self.assertIs(original.parentWidget(),parent)
            if not use_layout:self.assertEqual(original.geometry(),geometry)
            if layout:self.assertGreaterEqual(layout.indexOf(original),0)
            parent.deleteLater();dashboard.deleteLater()

    def test_test_comment_uses_shared_series_identity_and_latest_cache(self):
        from portefeuille_viewer.data.repository import build_uniek_id
        values=dict(broker='lynx',asset_rollup='AAPL',asset_type='optie',optie_exp_date='20-11-2026',optie_call_put='call',optie_strike='110.00',scenario_order_uid='test-uid')
        table=QTableWidget(1,2);table.setHorizontalHeaderLabels(['Broker','Comment'])
        table.setItem(0,0,QTableWidgetItem('lynx'));table.setItem(0,1,QTableWidgetItem('verouderd'))
        selector=QComboBox();selector.addItem('AAPL')
        target=SimpleNamespace(testOrdersTable=table,test_order_columns=['broker','optie_comment'],
            row_to_dict_db=lambda row:values,asset_selector=selector,checkBoxEnableTestOrders=QCheckBox(),
            checkBoxAssetOrdersOnly=QCheckBox(),comboboxScenarioSelector=QComboBox())
        dashboard=SimpleNamespace(_timer=SimpleNamespace(isActive=lambda:False,start=Mock()))
        service=DashboardTestOrders(target,dashboard);service.asset='AAPL'
        identity=build_uniek_id(values)
        frame=pl.DataFrame([dict(uniek_id=identity,optie_comment='nieuw',optie_comment_color='#f8d7da',optie_comment_textcolor='#000000')])
        with patch('portefeuille_viewer.services.asset_dashboard_test_orders.fetch_open_optie_comments',return_value=frame):
            state=service.state('AAPL')
        cell=state['rows'][0][1]
        self.assertEqual(cell['text'],'nieuw');self.assertEqual(cell['comment']['id'],identity)
        self.assertEqual(cell['comment']['background'],'#f8d7da');self.assertEqual(state['row_keys'],['test-uid'])
        values['optie_strike']=''
        with patch('portefeuille_viewer.services.asset_dashboard_test_orders.fetch_open_optie_comments') as fetch:
            invalid=service.state('AAPL')
        self.assertNotIn('comment',invalid['rows'][0][1]);fetch.assert_not_called()

    def test_actions_use_existing_controls(self):
        target=SimpleNamespace(checkBoxEnableTestOrders=QCheckBox(),checkBoxAssetOrdersOnly=QCheckBox(),comboboxScenarioSelector=QComboBox(),testOrdersTable=QTableWidget(),_refresh_test_orders_view_for_active_asset=Mock())
        target.comboboxScenarioSelector.addItem('A',11);target.comboboxScenarioSelector.addItem('B',12)
        dashboard=SimpleNamespace(_timer=SimpleNamespace(isActive=lambda:False,start=Mock()))
        service=DashboardTestOrders(target,dashboard)
        service.action('enabled',True);service.action('scenario',12)
        self.assertTrue(target.checkBoxEnableTestOrders.isChecked())
        self.assertEqual(target.comboboxScenarioSelector.currentData(),12)
        with self.assertRaises(ValueError):service.action('scenario',999)

if __name__=='__main__':unittest.main()


class InlineEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_native_delegates_include_and_delete(self):
        from PySide6.QtCore import Qt
        from portefeuille_viewer.ui_logica.single_asset_analyse_tab_logica import NumberDelegate, ComboDelegate
        fields=['scenario_order_uid','transactie_prijs','include','broker']
        table=QTableWidget(1,len(fields))
        for col,value in enumerate(['uid','1,00','','lynx']):table.setItem(0,col,QTableWidgetItem(value))
        table.setItemDelegateForColumn(1,NumberDelegate(table));table.setItemDelegateForColumn(3,ComboDelegate(['lynx','degiro'],table))
        table.item(0,2).setFlags(Qt.ItemIsEnabled|Qt.ItemIsUserCheckable)
        target=SimpleNamespace(testOrdersTable=table,test_order_columns=fields,test_order_columns_db=fields,
            row_to_dict_db=lambda row:{'scenario_order_uid':table.item(row,0).text()},
            checkBoxEnableTestOrders=QCheckBox(),checkBoxAssetOrdersOnly=QCheckBox(),comboboxScenarioSelector=QComboBox(),
            _handle_delete_test_order_clicked=Mock())
        service=DashboardTestOrders(target,SimpleNamespace(_timer=SimpleNamespace(isActive=lambda:False,start=Mock())))
        changed=Mock();table.cellChanged.connect(changed)
        self.assertEqual(service.edit('uid','transactie_prijs','2.345')['value'],'2,35')
        self.assertTrue(service.edit('uid','include',True)['value'])
        self.assertEqual(service.edit('uid','broker','degiro')['value'],'degiro')
        self.assertGreaterEqual(changed.call_count,3)
        with self.assertRaises(ValueError):service.edit('uid','transactie_prijs','abc')
        with self.assertRaises(ValueError):service.edit('uid','scenario_order_uid','other')
        service.action('sort',{'field':'broker','descending':True})
        self.assertEqual(table.horizontalHeader().sortIndicatorSection(),3)
        service.action('delete','uid');target._handle_delete_test_order_clicked.assert_called_once()
        table.deleteLater()


class FilterRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_filter_refreshes_once_without_native_toggle_side_effects(self):
        checkbox=QCheckBox();native=Mock();checkbox.toggled.connect(native)
        refresh=Mock()
        target=SimpleNamespace(testOrdersTable=QTableWidget(),checkBoxEnableTestOrders=QCheckBox(),
            checkBoxAssetOrdersOnly=checkbox,comboboxScenarioSelector=QComboBox(),
            _refresh_test_orders_view_for_active_asset=refresh)
        service=DashboardTestOrders(target,SimpleNamespace(_timer=SimpleNamespace(isActive=lambda:False,start=Mock())))
        service.asset='AAPL'
        for value in (True,False):
            service.action('asset_only',value)
            self.assertEqual(target.show_all_test_orders,not value)
            self.assertEqual(checkbox.isChecked(),value)
        self.assertEqual(refresh.call_count,2)
        native.assert_not_called()

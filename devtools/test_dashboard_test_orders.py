"""Scenario payoff and native-editor reuse checks; no database writes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import polars as pl
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget, QTableWidget, QCheckBox, QComboBox, QPushButton, QVBoxLayout
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
            target=SimpleNamespace()
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

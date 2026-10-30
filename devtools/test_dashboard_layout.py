import argparse
import ast
import configparser
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory

from portefeuille_viewer.config.settings_manager import SettingsManager
from portefeuille_viewer.config.profile_storage import ProfileStorage
from portefeuille_viewer.services.asset_dashboard_layout import BLOCK_IDS, validate_layout


def fixture():
    return dict(version=4, blocks=[dict(id=key,x=0,y=i*50,w=120,h=50) for i,key in enumerate(BLOCK_IDS)])

class LayoutTests(unittest.TestCase):
    def settings(self):
        settings=SettingsManager.__new__(SettingsManager)
        settings.config=configparser.ConfigParser();settings.save=Mock()
        return settings

    def test_modes_independent_and_roundtrip(self):
        settings=self.settings();self.assertIsNone(settings.get_asset_dashboard_layout('desktop'))
        settings.set_asset_dashboard_layout('desktop',fixture())
        self.assertEqual(settings.get_asset_dashboard_layout('desktop'),fixture())
        self.assertIsNone(settings.get_asset_dashboard_layout('laptop'))
        laptop=fixture();laptop['blocks'][0]['w']=200
        settings.set_asset_dashboard_layout('laptop',laptop)
        self.assertEqual(settings.get_asset_dashboard_layout('desktop'),fixture())
        self.assertEqual(settings.get_asset_dashboard_layout('laptop'),laptop)

    def test_old_layout_is_migrated_without_changing_proportions(self):
        old=fixture();old['version']=1
        for block in old['blocks']:
            block['x'] //= 10;block['w'] //= 10;block['y'] //= 10;block['h'] //= 10
        new=validate_layout(old)
        self.assertEqual(new,fixture())
        self.assertEqual(old['blocks'][0]['w'],12)

    def test_version_two_height_migration_preserves_pixels(self):
        old=fixture();old['version']=2
        for block in old['blocks']:
            block['y'] //= 10;block['h'] //= 10
        self.assertEqual(validate_layout(old),fixture())
        self.assertEqual(old['blocks'][0]['h']*27-7,fixture()['blocks'][0]['h']*2.7-7)

    def test_old_saved_layout_adds_movable_asset_info_between_table_and_chart(self):
        value=fixture();value['version']=3
        value['blocks']=[b for b in value['blocks'] if b['id']!='asset_info']
        table=next(b for b in value['blocks'] if b['id']=='payoff_table')
        result=validate_layout(value)
        info=next(b for b in result['blocks'] if b['id']=='asset_info')
        chart=next(b for b in result['blocks'] if b['id']=='payoff')
        self.assertEqual((info['x'],info['w'],info['y']),(table['x'],table['w'],table['y']+table['h']))
        self.assertGreaterEqual(chart['y'],info['y']+info['h'])
        self.assertEqual(result['version'],4)

    def test_invalid_and_corrupt_layout(self):
        settings=self.settings()
        for change in ('duplicate','overlap','bounds','float','version'):
            value=fixture()
            if change=='duplicate':value['blocks'][1]['id']=value['blocks'][0]['id']
            if change=='overlap':value['blocks'][1]['y']=0
            if change=='bounds':value['blocks'][0]['w']=241
            if change=='float':value['blocks'][0]['x']=1.5
            if change=='version':value['version']=999
            with self.assertRaises(ValueError):settings.set_asset_dashboard_layout('desktop',value)
        settings.save.assert_not_called()
        settings.config.read_dict({'ui':{'asset_dashboard_layout_desktop':'broken'}})
        self.assertIsNone(settings.get_asset_dashboard_layout('desktop'))

    def test_profile_storage_and_validation_copy(self):
        with TemporaryDirectory() as root:
            store=ProfileStorage('onno','unused','unused',root=root,machine_id='test')
            for mode in ('desktop','laptop'):
                self.assertEqual(store.target('ui','asset_dashboard_layout_'+mode),store.preferences)
        value=fixture();result=validate_layout(value);result['blocks'][0]['x']=1
        self.assertEqual(value['blocks'][0]['x'],0)

    def test_startup_options(self):
        source=Path(__file__).resolve().parents[1]/'portefeuille_viewer_1.8.py'
        tree=ast.parse(source.read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_parse_startup_args')
        namespace={'argparse':argparse};exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
        parse=namespace['_parse_startup_args']
        self.assertEqual(parse(['app']).dashboard_mode,'desktop')
        self.assertEqual(parse(['app','-desktop']).dashboard_mode,'desktop')
        args=parse(['app','-laptop','--profile','muriel'])
        self.assertEqual((args.dashboard_mode,args.database_alias),('laptop','muriel'))

    def main_method(self, name):
        path=Path(__file__).resolve().parents[1]/'portefeuille_viewer/ui_logica/main_window_logica.py'
        tree=ast.parse(path.read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MainWindow')
        node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
        namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),namespace)
        return namespace[name]

    def test_retired_dashboard_tab_is_removed_from_saved_order(self):
        path=Path(__file__).resolve().parents[1]/'portefeuille_viewer/ui_logica/main_window_logica.py'
        tree=ast.parse(path.read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MainWindow')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_apply_saved_tab_order')
        orders,dashboard,single=object(),object(),object()
        for saved,expected in [(['orders','asset_dashboard','single','asset_dashboard_layout'],[orders,single,dashboard]),
                               (['orders','asset_dashboard','single'],[orders,dashboard,single])]:
            items=[orders,dashboard,single]
            def move(old,new):items.insert(new,items.pop(old))
            tabs=SimpleNamespace(indexOf=lambda widget:items.index(widget),tabBar=lambda:SimpleNamespace(moveTab=move))
            window=SimpleNamespace(_tab_specs=[('orders','Orders',orders),('asset_dashboard_layout','Asset Dashboard',dashboard),('single','Single',single)],
                tabWidget=tabs,_persist_tab_order=Mock())
            namespace={'get_settings':lambda:SimpleNamespace(get_tab_order=lambda:saved)}
            exec(compile(ast.Module(body=[method],type_ignores=[]),str(path),'exec'),namespace)
            namespace['_apply_saved_tab_order'](window)
            self.assertEqual(items,expected)
            window._persist_tab_order.assert_called_once()

    def test_switch_stops_previous_before_activating_next(self):
        order=[]
        first=SimpleNamespace(set_active=lambda active:order.append(('first',active)))
        second=SimpleNamespace(set_active=lambda active:order.append(('second',active)))
        selected=second
        window=SimpleNamespace(_dashboard_tabs=(first,second),tabWidget=SimpleNamespace(widget=lambda i:selected),
            subscriptions_tab=SimpleNamespace(set_active=Mock()),_update_price_focus=Mock())
        self.main_method('_on_tab_changed')(window,0)
        self.assertEqual(order,[('first',False),('second',True)])
        order.clear();selected=object()
        self.main_method('_on_tab_changed')(window,0)
        self.assertEqual(order,[('first',False),('second',False)])

    def test_close_flushes_both_dashboards_in_sequence(self):
        class StopAfterFlush(Exception):pass
        callbacks=[]
        first=Mock();second=Mock()
        first.flush_comments_before_close.side_effect=lambda callback:callbacks.append(callback) or True
        second.flush_comments_before_close.side_effect=lambda callback:callbacks.append(callback) or True
        window=SimpleNamespace(_dashboard_tabs=(first,second),close=Mock(),
            _close_standalone_dialogs=Mock(side_effect=StopAfterFlush))
        event=SimpleNamespace(ignore=Mock())
        close=self.main_method('closeEvent')
        close(window,event);self.assertEqual(len(callbacks),1);callbacks.pop()()
        close(window,event);self.assertEqual(len(callbacks),1);callbacks.pop()()
        with self.assertRaises(StopAfterFlush):close(window,event)
        self.assertEqual(window._dashboard_close_done,{first,second})

    def test_cancelled_queued_job_does_not_calculate(self):
        from portefeuille_viewer.ui_logica import asset_dashboard_tab as module
        job=module._AnalyticsJob(1,(),{});job.cancelled.set()
        with patch.object(module,'calculate_analytics') as calculate:
            job.run()
        calculate.assert_not_called()

    def test_one_shared_calculation_lane(self):
        from portefeuille_viewer.ui_logica import asset_dashboard_tab as module
        state=dict(active=0,peak=0,calls=0);lock=threading.Lock()
        def calculate(*args,**kwargs):
            with lock:
                state['active']+=1;state['peak']=max(state['peak'],state['active']);state['calls']+=1
            threading.Event().wait(.025)
            with lock:state['active']-=1
            return {}
        jobs=[module._AnalyticsJob(i,(),{}) for i in range(2)]
        with patch.object(module,'calculate_analytics',side_effect=calculate):
            for job in jobs:module.DASHBOARD_ANALYTICS_POOL.start(job)
            self.assertTrue(module.DASHBOARD_ANALYTICS_POOL.waitForDone(5000))
        self.assertEqual(state['peak'],1);self.assertEqual(state['calls'],2)

if __name__=='__main__':unittest.main()

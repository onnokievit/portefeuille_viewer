"""Profile isolation and real Windows process-lock tests; no Access connections."""
import configparser
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from portefeuille_viewer.config import settings_manager as sm
from portefeuille_viewer.config.profile_storage import ProfileStorage, read_config, atomic_write
from portefeuille_viewer.config.profile_session import resolve_database

REPO = Path(__file__).resolve().parents[1]

CHILD = r'''
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from portefeuille_viewer.config import settings_manager as sm
from portefeuille_viewer.config.profile_session import prepare_profile_session,ProfileAlreadyOpen
root=Path(sys.argv[2]); name=sys.argv[3]; mode=sys.argv[4]
sm.SHARED_CONFIG_PATH=root/'legacy-shared.ini'
sm.LOCAL_CONFIG_PATH=root/'legacy-local.ini'
try:
    session=prepare_profile_session(['app','--db',name],data_root=root/'data',machine_id='testpc')
    print(json.dumps({'ready':True,'profile':session.profile,'db':session.database_name,
                      'repository_imported':'portefeuille_viewer.data.repository' in sys.modules}),flush=True)
    if mode=='hold':sys.stdin.readline()
    if mode=='merge':
        sys.stdin.readline()
        settings=sm.get_settings()
        if not settings.config.has_section('brokers'):settings.config.add_section('brokers')
        for i in range(20):
            settings.config.set('brokers',name+'_'+str(i),str(i))
            settings.save()
    session.close()
except ProfileAlreadyOpen:
    print(json.dumps({'duplicate':True}),flush=True)
    sys.exit(3)
'''


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.shared=self.root/'legacy-shared.ini'
        self.local=self.root/'legacy-local.ini'
        self.db={n:self.root/(n+'.accdb') for n in ('onno','muriel','quinten')}
        for p in self.db.values():p.touch()  # inert placeholders: never opened by Access
        cfg=configparser.ConfigParser()
        cfg['databases']={('onno-productie' if n=='onno' else n):f'{p} | black | white | {str(n=="onno").lower()}' for n,p in self.db.items()}
        cfg['stockdata']={'db_path':str(self.root/'stock.accdb')}
        cfg['comment_colors']={'4':'Rood,#f8d7da,#000000'}
        cfg['ui']={'tab_order':'["orders", "aandelen"]'}
        atomic_write(cfg,self.shared)
        self.local.write_text('[ui]\ntheme = light\nmain_window_geometry = {"x":1,"y":2,"w":800,"h":600}\n[market_data]\ncapacity = 100\nbatch_size = 50\nrotation_seconds = 30\nstale_seconds = 180\n',encoding='utf-8')
        self.legacy=(self.shared.read_bytes(),self.local.read_bytes())
        self.patches=[patch.object(sm,'SHARED_CONFIG_PATH',self.shared),patch.object(sm,'LOCAL_CONFIG_PATH',self.local)]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    def manager(self,name='onno',pc='desktop'):
        return sm.SettingsManager(profile=name,database_name='onno-productie' if name=='onno' else name,
                                  data_root=self.root/'data',machine_id=pc)

    def child(self,name='onno',mode='hold',root=None):
        child=subprocess.Popen([sys.executable,'-u','-c',CHILD,str(REPO),str(root or self.root),name,mode],
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.addCleanup(self.stop_child,child)
        lines=queue.Queue()
        threading.Thread(target=lambda:lines.put(child.stdout.readline()),daemon=True).start()
        line=lines.get(timeout=15)
        if not line: self.fail('Child failed: '+child.stderr.read())
        return child,json.loads(line)

    @staticmethod
    def stop_child(child):
        if child.poll() is None:child.kill()
        child.wait(timeout=10)
        for pipe in (child.stdin,child.stdout,child.stderr):
            if pipe:pipe.close()

    def test_legacy_preferences_preserved_without_rewriting_sources(self):
        onno=self.manager();muriel=self.manager('muriel')
        self.assertEqual(onno.get_market_data_settings()['batch_size'],50)
        self.assertEqual(muriel.get_theme(),'light')
        self.assertEqual(self.legacy,(self.shared.read_bytes(),self.local.read_bytes()))
        self.assertEqual(onno.get_comment_colors()[0][1],'Rood')

    def test_profiles_have_independent_preferences(self):
        onno=self.manager();muriel=self.manager('muriel')
        onno.set_theme('dark')
        onno.set_market_data_settings({'capacity':80,'batch_size':20,'rotation_seconds':60,'stale_seconds':180})
        self.assertEqual(self.manager().get_theme(),'dark')
        self.assertEqual(self.manager('muriel').get_theme(),'light')
        self.assertEqual(muriel.get_market_data_settings()['capacity'],100)
        profile=read_config([onno._profile_storage.preferences])
        self.assertFalse(profile.has_option('ui','main_window_geometry'))
        self.assertFalse(profile.has_section('databases'))

    def test_geometry_is_per_computer_and_profile(self):
        desktop=self.manager();laptop=self.manager(pc='laptop');muriel=self.manager('muriel')
        original=laptop.get_main_window_geometry()
        desktop.set_main_window_geometry(100,200,1200,800)
        self.assertEqual(self.manager(pc='laptop').get_main_window_geometry(),original)
        self.assertEqual(muriel.get_main_window_geometry(),original)
        self.assertEqual(self.manager().get_main_window_geometry()['x'],100)

    def test_profile_save_does_not_rewrite_shared_settings(self):
        onno=self.manager();shared=onno._profile_storage.shared
        before=shared.read_bytes();mtime=shared.stat().st_mtime_ns
        onno.set_theme('dark')
        self.assertEqual(shared.read_bytes(),before)
        self.assertEqual(shared.stat().st_mtime_ns,mtime)

    def test_stale_profile_save_preserves_another_instances_shared_edit(self):
        onno=self.manager();muriel=self.manager('muriel')
        muriel.set_comment_colors([(4,'Rood','#ff0000','#000000')])
        onno.set_theme('dark')
        self.assertEqual(self.manager().get_comment_colors()[0][2],'#ff0000')

    def test_shared_saves_merge_changed_keys_only(self):
        onno=self.manager();muriel=self.manager('muriel')
        onno.config.set('stockdata','db_path','new-stock.accdb');onno.save()
        muriel.set_comment_colors([(4,'Rood','#ff0000','#000000')])
        current=self.manager()
        self.assertEqual(current.get_stockdata_db_path(),'new-stock.accdb')
        self.assertEqual(current.get_comment_colors()[0][2],'#ff0000')

    def test_external_profile_keys_survive_saves(self):
        onno=self.manager();path=onno._profile_storage.preferences
        disk=read_config([path]);disk['extension']={'custom':'keep'};atomic_write(disk,path)
        onno.set_theme('dark')
        self.assertEqual(read_config([path])['extension']['custom'],'keep')

    def test_noop_save_changes_no_files(self):
        onno=self.manager()
        before={p:p.stat().st_mtime_ns for p in onno._profile_storage.paths}
        onno.save()
        self.assertEqual(before,{p:p.stat().st_mtime_ns for p in before})

    def test_cannot_remove_or_repoint_active_database(self):
        onno=self.manager()
        with self.assertRaises(ValueError):onno.remove_database('onno-productie')
        with self.assertRaises(ValueError):onno.update_database('onno-productie',path='other.accdb')
        with self.assertRaises(ValueError):onno.set_last_database('muriel')

    def test_aliases_resolve_and_unknown_alias_rejected(self):
        catalog={'onno-productie':{},'muriel':{},'quinten':{}}
        self.assertEqual(resolve_database('ONNO',catalog),'onno-productie')
        self.assertEqual(resolve_database('muriel',catalog),'muriel')
        with self.assertRaises(ValueError):resolve_database('nobody',catalog)

    def test_second_instance_of_same_database_rejected_before_repository_import(self):
        owner,first=self.child()
        self.assertFalse(first['repository_imported'])
        second,result=self.child(mode='probe')
        self.assertTrue(result['duplicate']);self.assertEqual(second.wait(timeout=10),3)

    def test_different_users_can_run_concurrently(self):
        first,a=self.child()
        second,b=self.child('muriel')
        self.assertTrue(a['ready'] and b['ready'])
        self.assertNotEqual(a['profile'],b['profile'])

    def test_two_processes_merge_shared_settings_without_losing_keys(self):
        first,_=self.child('onno',mode='merge');second,_=self.child('muriel',mode='merge')
        for process in (first,second):process.stdin.write('\n');process.stdin.flush()
        for process in (first,second):self.assertEqual(process.wait(timeout=15),0)
        shared=read_config([self.root/'data/gedeeld/settings_shared.ini'])
        for name in ('onno','muriel'):
            for i in range(20):self.assertEqual(shared['brokers'][name+'_'+str(i)],str(i))

    def test_crash_releases_database_lock(self):
        owner,_=self.child();owner.kill();owner.wait(timeout=10)
        replacement,result=self.child(mode='probe')
        self.assertTrue(result['ready']);self.assertEqual(replacement.wait(timeout=10),0)

    def test_normal_exit_releases_database_lock(self):
        owner,_=self.child();owner.stdin.write('\n');owner.stdin.flush();owner.wait(timeout=10)
        replacement,result=self.child(mode='probe')
        self.assertTrue(result['ready'])

    def test_different_version_directories_cannot_bypass_database_lock(self):
        owner,_=self.child()
        other=self.root/'other-version';other.mkdir()
        (other/'legacy-shared.ini').write_bytes(self.shared.read_bytes())
        (other/'legacy-local.ini').write_bytes(self.local.read_bytes())
        second,result=self.child(root=other,mode='probe')
        self.assertTrue(result['duplicate']);self.assertEqual(second.wait(timeout=10),3)
        self.assertFalse((other/'data').exists())

    def test_most_recent_profile_is_computer_local(self):
        owner,result=self.child('muriel',mode='probe');owner.wait(timeout=10)
        recent=read_config([self.root/'data/computers/testpc/startup.ini'])
        self.assertEqual(recent['app']['last_database'],'muriel')
        shared=read_config([self.root/'data/gedeeld/settings_shared.ini'])
        self.assertNotIn('last_database',shared['app'] if shared.has_section('app') else {})

    def test_real_entry_imports_bind_selected_profile_before_any_database_connection(self):
        script=r'''
import ast,json,sys
from pathlib import Path
from unittest.mock import patch
repo=Path(sys.argv[1]);root=Path(sys.argv[2]);sys.path.insert(0,str(repo))
from portefeuille_viewer.config import settings_manager as sm
from portefeuille_viewer.config import profile_session as ps
sm.SHARED_CONFIG_PATH=root/'legacy-shared.ini';sm.LOCAL_CONFIG_PATH=root/'legacy-local.ini'
ps.USER_DATA_ROOT=root/'data'
sys.argv=['app','--db','muriel']
path=repo/'portefeuille_viewer_1.5.py';tree=ast.parse(path.read_text(encoding='utf-8'))
prefix=[]
for node in tree.body:
    if isinstance(node,ast.FunctionDef):break
    prefix.append(node)
with patch('pyodbc.connect',side_effect=AssertionError('Database opened during imports')) as connect:
    exec(compile(ast.Module(body=prefix,type_ignores=[]),str(path),'exec'),{'__name__':'__main__','__file__':str(path)})
    from portefeuille_viewer.data import repository
    assert repository.DEFAULT_DB_NAME=='muriel'
    assert Path(repository.db_path).resolve()==(root/'muriel.accdb').resolve()
    try:repository.switch_database('onno-productie')
    except ValueError:pass
    else:raise AssertionError('Profile switch accepted')
    connect.assert_not_called()
print('ENTRY_OK')
'''
        result=subprocess.run([sys.executable,'-c',script,str(REPO),str(self.root)],
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('ENTRY_OK',result.stdout)


if __name__=='__main__':unittest.main()

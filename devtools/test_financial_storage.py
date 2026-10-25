"""Real isolated Access storage, retries and interprocess concurrency tests."""
import base64
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from devtools.setup_financial_data_stockdata import migrate
from portefeuille_viewer.data import financial_data_repository as repo
from portefeuille_viewer.data.shared_database import connect_stockdata
from portefeuille_viewer.services.financial_data_contract import FinancialFact, FetchResult
from portefeuille_viewer.services.financial_data_service import FinancialDataService
from portefeuille_viewer.services.financial_comparisons import build_comparisons


NOW = datetime(2026,10,25,9)


def fact(subject='A', value=1.2, **kwargs):
    values = dict(source='Yahoo', subject=subject, category='estimate', metric='eps_estimate.avg',
        period_key='quarterly:2026-09-30', value=value, period_end=date(2026,9,30), period_kind='quarterly',
        currency='USD', unit='currency_per_share', basis='provider_eps')
    values.update(kwargs)
    return FinancialFact(**values)


class Provider:
    name = 'Yahoo'
    groups = ('eps_estimate',)
    def __init__(self):
        self.calls = []
        self.fail = set()
    def prepare(self):
        pass
    def fetch(self, asset, group):
        self.calls.append(asset['asset_rollup'])
        if asset['asset_rollup'] in self.fail:
            raise TimeoutError('fixture timeout')
        if not asset.get('yfinance_symbol'):
            return FetchResult(status='missing_mapping')
        return FetchResult([fact(asset['asset_rollup'])])


class FinancialStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='pv-financial-')
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.base = Path(cls.tmp.name)/'base.accdb'
        ddl = [
            'CREATE TABLE asset_rollup_data (Id COUNTER PRIMARY KEY, asset_rollup TEXT(64), '
            'yfinance_symbol TEXT(50), [type] TEXT(32), ib_currency TEXT(16), INCL_EXCL LONG)',
            'CREATE TABLE historical_data_correct (Id COUNTER PRIMARY KEY, asset_rollup TEXT(64))']
        script = "$ErrorActionPreference='Stop';$e=New-Object -ComObject DAO.DBEngine.120;" \
            + "$d=$e.CreateDatabase('"+str(cls.base).replace("'","''")+"',';LANGID=0x0409;CP=1252;COUNTRY=0',128);" \
            + ''.join("$d.Execute('"+sql+"');" for sql in ddl)+"$d.Close()"
        subprocess.run(['powershell','-NoProfile','-NonInteractive','-EncodedCommand',
            base64.b64encode(script.encode('utf-16-le')).decode()],capture_output=True,check=True,timeout=30)
        assert migrate(cls.base)['missing_tables']
        cls.migration = migrate(cls.base, apply=True)

    def setUp(self):
        self.path = self.base.with_name(uuid4().hex+'.accdb')
        shutil.copy2(self.base,self.path)

    def store(self, facts, now=NOW, status='ok'):
        return repo.store_result(self.path,'Yahoo','A','eps_estimate','A|aandeel|EUR',
            FetchResult(facts,status=status), now+timedelta(days=1), now)

    def assets(self):
        with connect_stockdata(self.path) as conn:
            for asset, symbol, included in [('A','A.AS',1),('B','B.AS',0),('C',None,0)]:
                conn.execute('INSERT INTO asset_rollup_data (asset_rollup,yfinance_symbol,[type],ib_currency,INCL_EXCL) '
                    'VALUES (?,?,?,?,?)',asset,symbol,'aandeel','EUR',included)

    def test_schema_explicit_idempotent_and_backup_exists(self):
        self.assertTrue(repo.schema_ready(self.path))
        self.assertTrue(Path(self.migration['backup']).is_file())
        self.assertEqual(migrate(self.path)['missing_tables'],[])
        self.assertTrue(migrate(self.path,apply=True)['verified'])

    def test_changed_history_and_identical_polling_is_idempotent(self):
        self.assertEqual(self.store([fact()]),1)
        self.assertEqual(self.store([fact()],now=NOW+timedelta(hours=1)),0)
        self.assertEqual(self.store([fact(value=1.3)],now=NOW+timedelta(hours=2)),1)
        history=repo.facts_for(self.path,'A',history=True)
        self.assertEqual([r['revision'] for r in history],[1,2])
        self.assertEqual([r['value_num'] for r in history],[1.2,1.3])
        self.assertEqual(repo.facts_for(self.path,'A')[0]['value_num'],1.3)

    def test_missing_response_and_error_preserve_values_and_success_checkpoint(self):
        self.store([fact()])
        self.store([fact(value=None)], now=NOW+timedelta(hours=1),status='no_data')
        self.store([],now=NOW+timedelta(hours=2),status='error')
        self.assertEqual(repo.facts_for(self.path,'A')[0]['value_num'],1.2)
        state=next(iter(repo.fetch_states(self.path).values()))
        self.assertEqual(state['last_success'],NOW+timedelta(hours=1))
        self.assertEqual(state['failures'],1)

    def test_sparse_payload_merge_preserves_existing_fields_and_zero(self):
        self.store([fact(value=dict(low=1.,avg=1.2,high=1.4))])
        self.store([fact(value=dict(avg=0.,high=None))])
        value=json.loads(repo.facts_for(self.path,'A')[0]['payload_json'])['value']
        self.assertEqual(value,dict(low=1.,avg=0.,high=1.4))

    def test_history_failure_rolls_back_current_facts_and_checkpoint(self):
        original=repo._insert_many
        def broken(cur,table,columns,rows):
            if table=='financial_facts_history':
                raise RuntimeError('injected history failure')
            return original(cur,table,columns,rows)
        with patch.object(repo,'_insert_many',side_effect=broken):
            with self.assertRaises(RuntimeError):self.store([fact()])
        self.assertEqual(repo.facts_for(self.path,'A'),[])
        self.assertEqual(repo.fetch_states(self.path),{})
        self.assertEqual(self.store([fact()]),1)

    def test_two_processes_write_identical_fact_once(self):
        code = "from pathlib import Path; from datetime import datetime,timedelta; " \
            "from portefeuille_viewer.data.financial_data_repository import store_result; " \
            "from portefeuille_viewer.services.financial_data_contract import FinancialFact,FetchResult; " \
            "import sys; print(store_result(Path(sys.argv[1]),'Yahoo','A','calendar','A'," \
            "FetchResult([FinancialFact('Yahoo','A','event','earnings_schedule','quarterly:2026-09-30'," \
            "{'date_start':'2026-10-28'})]),datetime(2026,10,26),datetime(2026,10,25)))"
        children=[subprocess.Popen([sys.executable,'-c',code,str(self.path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                  for _ in range(2)]
        results=[]
        for child in children:
            out,err=child.communicate(timeout=30)
            self.assertEqual(child.returncode,0,err)
            results.append(int(out.strip().splitlines()[-1]))
        self.assertEqual(sorted(results),[0,1])
        self.assertEqual(len(repo.facts_for(self.path,'A',history=True)),1)

    def test_service_includes_unheld_assets_and_reuses_shared_checkpoints(self):
        self.assets()
        provider=Provider()
        service=FinancialDataService(self.path,[provider],clock=lambda:NOW,pause=lambda _:None)
        result=service.refresh()
        self.assertEqual(result.rows_processed,3)
        self.assertEqual(set(provider.calls),{'A','B','C'})
        self.assertEqual(len(repo.facts_for(self.path,'B')),1)
        self.assertEqual(len(repo.fetch_states(self.path)),3)
        self.assertEqual(service.refresh().rows_processed,0)

    def test_failed_group_retries_without_repeating_successful_assets(self):
        self.assets()
        provider=Provider();provider.fail={'A'}
        with self.assertLogs(level='WARNING'):
            first=FinancialDataService(self.path,[provider],clock=lambda:NOW,pause=lambda _:None).refresh()
        self.assertEqual(first.status,'partial')
        provider.calls=[];provider.fail=set()
        second=FinancialDataService(self.path,[provider],clock=lambda:NOW+timedelta(minutes=20),pause=lambda _:None).refresh()
        self.assertEqual(provider.calls,['A'])
        self.assertEqual(second.rows_error,0)

    def test_mapping_change_invalidates_not_due_checkpoint(self):
        self.assets();provider=Provider()
        FinancialDataService(self.path,[provider],clock=lambda:NOW,pause=lambda _:None).refresh()
        with connect_stockdata(self.path) as conn:
            conn.execute("UPDATE asset_rollup_data SET yfinance_symbol='C.AS' WHERE asset_rollup='C'")
        provider.calls=[]
        FinancialDataService(self.path,[provider],clock=lambda:NOW,pause=lambda _:None).refresh()
        self.assertEqual(provider.calls,['C'])

    def test_crash_safe_lease_skips_second_collector_and_budget_resumes(self):
        from portefeuille_viewer.config.local_runtime import FileLease
        from portefeuille_viewer.config.process_lock import canonical_path
        self.assets();provider=Provider()
        lease=FileLease('financial-collection:'+canonical_path(self.path))
        self.assertTrue(lease.acquire())
        try:
            result=FinancialDataService(self.path,[provider],clock=lambda:NOW,pause=lambda _:None).refresh()
            self.assertEqual(result.status,'skipped')
            self.assertEqual(provider.calls,[])
        finally:lease.release()
        first=FinancialDataService(self.path,[provider],clock=lambda:NOW,pause=lambda _:None,max_jobs=1).refresh()
        self.assertEqual(first.rows_processed,1)
        provider.calls=[]
        second=FinancialDataService(self.path,[provider],clock=lambda:NOW,pause=lambda _:None).refresh()
        self.assertEqual(second.rows_processed,2)
        self.assertNotIn('A',provider.calls)

    def test_rate_limit_sets_shared_provider_cooldown(self):
        self.assets();provider=Provider()
        provider.fetch=lambda *args:(_ for _ in ()).throw(RuntimeError('HTTP 429'))
        with self.assertLogs(level='WARNING'):
            first=FinancialDataService(self.path,[provider],clock=lambda:NOW,pause=lambda _:None).refresh()
        self.assertEqual(first.rows_processed,1)
        second=FinancialDataService(self.path,[provider],clock=lambda:NOW+timedelta(minutes=5),pause=lambda _:None).refresh()
        self.assertEqual(second.rows_processed,0)

    def test_macro_subject_extension_uses_same_storage_without_asset_ownership(self):
        provider=Provider()
        provider.name='MacroFixture'
        provider.subjects=lambda path:[dict(subject_key='US',type='economy')]
        provider.fetch=lambda asset, group:FetchResult([FinancialFact('MacroFixture','US','actual','cpi','2026-09',
            2.5,subject_type='economy',unit='percent')])
        result=FinancialDataService(self.path,[provider],clock=lambda:NOW,pause=lambda _:None).refresh()
        self.assertEqual(result.rows_changed,1)
        self.assertEqual(repo.facts_for(self.path,'US')[0]['subject_type'],'economy')

    def test_missing_schema_is_not_bootstrapped_by_app(self):
        with connect_stockdata(self.path) as conn:
            conn.execute('DROP TABLE financial_data_schema')
        provider=Provider()
        result=FinancialDataService(self.path,[provider],clock=lambda:NOW,pause=lambda _:None).refresh()
        self.assertEqual(result.status,'skipped')
        self.assertFalse(repo.schema_ready(self.path))
        self.assertFalse(provider.calls)

    def test_comparison_uses_prepublication_consensus_and_ignores_later_update(self):
        self.store([fact(value=1.2)],now=datetime(2026,10,20))
        self.store([fact(value=1.4)],now=datetime(2026,10,29))
        self.store([fact(category='event',metric='earnings_schedule',value={'date_start':'2026-10-28',
            'date_end':'2026-10-28'})],now=datetime(2026,10,20))
        self.store([fact(category='actual',metric='eps',value=1.3)],now=datetime(2026,10,29))
        result=build_comparisons(self.path,'Yahoo','A')
        self.assertEqual(result[0].value['consensus'],1.2)
        self.assertEqual(result[0].value['verdict'],'beat')
        self.assertEqual(result[0].context['consensus_revision'],1)

    def test_currency_or_period_mismatch_never_becomes_a_beat(self):
        self.store([fact(value=1.2,currency='EUR')],now=datetime(2026,10,20))
        self.store([fact(category='actual',metric='eps',value=1.3)])
        result=build_comparisons(self.path,'Yahoo','A')
        self.assertEqual(result[0].value['status'],'not_comparable')

    def test_ibkr_legacy_patch_keeps_yahoo_and_only_appends_changes(self):
        from portefeuille_viewer.data import dividend_calendar_repository as div
        from portefeuille_viewer.data.dividend_calendar_repository import DividendCalendarRow
        row=DividendCalendarRow('A','A','EUR',date(2026,11,1),1.2,4.,4.5,date(2026,10,28),
            'IBKR','Yahoo','ok','','raw',NOW,NOW)
        with patch.object(div,'_connect',side_effect=lambda:connect_stockdata(self.path)):
            div.replace_current_and_append_history([row])
            row.next_earnings_date=None;row.source_earnings='';row.next_dividend_amount=None
            row.updated_at=NOW+timedelta(hours=1);row.fetched_at=row.updated_at
            div.replace_current_and_append_history([row])
        with connect_stockdata(self.path) as conn:
            actual=conn.execute('SELECT next_dividend_amount,next_earnings_date,source_earnings '
                'FROM asset_dividend_calendar_current WHERE asset_rollup=?','A').fetchone()
            self.assertEqual(actual[0],1.2)
            self.assertEqual(actual[2],'Yahoo')
            self.assertEqual(conn.execute('SELECT Count(*) FROM asset_dividend_calendar_history').fetchone()[0],1)


if __name__=='__main__':unittest.main()

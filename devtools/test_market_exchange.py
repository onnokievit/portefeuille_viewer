import json
from pathlib import Path
import sys
import tempfile
import shutil
import base64
import subprocess
from datetime import date, datetime, timedelta
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portefeuille_viewer.services.market_exchange import synchronize, validate_url, NoRedirect, ExchangeHTTP
from portefeuille_viewer.data.market_exchange_repository import StockdataInbox
from portefeuille_viewer.data import market_exchange_repository as exchange_repo
from portefeuille_viewer.data.shared_database import connect_stockdata
from portefeuille_viewer.data.stockdata_worker import enable_stockdata_workers, shutdown_stockdata_workers
from devtools.setup_financial_data_stockdata import migrate
from portefeuille_viewer.data import financial_data_repository as financial_repo
from portefeuille_viewer.services.financial_data_contract import FinancialFact, FetchResult, digest


def record(seq=1, revision=1, **extra):
    return dict(sequence=seq, operation='upsert', id='cftc-es', revision=revision,
        source='CFTC', dataset='positioning', schema_version=9,
        subject=dict(type='market', id='ES'), payload=dict(value=seq, new_field=['preserve']), **extra)


def page(after=0, items=None, high=None):
    items = [record()] if items is None else items
    cursor = items[-1]['sequence'] if items else after
    high = cursor if high is None else high
    return dict(api_version=1, stream_id='test-stream', after=after, next_cursor=cursor,
                high_watermark=high, has_more=cursor < high, items=items)


MANIFEST = dict(api_version=1, stream_id='test-stream', datasets=[])


class InboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.base_tmp.cleanup)
        cls.base = Path(cls.base_tmp.name)/'base.accdb'
        ddl = [
            'CREATE TABLE asset_rollup_data (Id COUNTER PRIMARY KEY, asset_rollup TEXT(64))',
            'CREATE TABLE historical_data_correct (Id COUNTER PRIMARY KEY, asset_rollup TEXT(64))']
        script = "$ErrorActionPreference='Stop';$e=New-Object -ComObject DAO.DBEngine.120;" \
            + "$d=$e.CreateDatabase('"+str(cls.base).replace("'","''")+"',';LANGID=0x0409;CP=1252;COUNTRY=0',128);" \
            + ''.join("$d.Execute('"+sql+"');" for sql in ddl)+"$d.Close()"
        subprocess.run(['powershell','-NoProfile','-NonInteractive','-EncodedCommand',
            base64.b64encode(script.encode('utf-16-le')).decode()],capture_output=True,check=True,timeout=30)
        migrate(cls.base,apply=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/'stockdata.accdb'
        shutil.copy2(self.base,self.path)
        enable_stockdata_workers()
        self.inbox=StockdataInbox(self.path)

    def tearDown(self):
        self.inbox.close(); shutdown_stockdata_workers(); self.tmp.cleanup()

    def test_unknown_dataset_schema_and_subject_survive(self):
        self.inbox.apply(page(), MANIFEST)
        stored=self.inbox.records('positioning','market','ES')[0]
        self.assertEqual(stored['schema_version'],9)
        self.assertEqual(stored['payload']['new_field'],['preserve'])

    def test_bad_second_record_rolls_back_whole_page(self):
        broken=record(2,2);broken.pop('subject')
        with self.assertRaises(ValueError):self.inbox.apply(page(items=[record(),broken]),MANIFEST)
        self.assertEqual(self.inbox.state()['cursor'],0)
        self.assertEqual(self.inbox.records(),[])

    def test_restart_resume_and_network_failure(self):
        self.inbox.apply(page(high=2),MANIFEST)
        self.inbox.close(); self.inbox=StockdataInbox(self.path)
        class Broken:
            def get(self,path,**query):
                if path=='manifest':return MANIFEST
                raise TimeoutError()
        with self.assertRaises(TimeoutError):synchronize(Broken(),self.inbox)
        self.assertEqual(self.inbox.state()['cursor'],1)
        test=self
        class Working:
            def get(self,path,**query):
                if path=='manifest':return MANIFEST
                test.assertEqual(query['after'],1)
                return page(1,[record(2,2)])
        result=synchronize(Working(),self.inbox)
        self.assertEqual(result['cursor'],2)
        self.assertEqual(len(self.inbox.records()),1)
        self.assertEqual(self.inbox.records()[0]['revision'],2)
        with connect_stockdata(self.path) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM financial_facts_history').fetchone()[0],2)

    def test_replay_wrong_stream_cursor_and_regression_rejected(self):
        self.inbox.apply(page(),MANIFEST)
        for invalid in [page(),page(1,[record(2,1)])]:
            with self.assertRaises(ValueError):self.inbox.apply(invalid,MANIFEST)
        changed=page(1,[]);changed['stream_id']='restored-db'
        with self.assertRaises(ValueError):self.inbox.apply(changed,MANIFEST)
        self.assertEqual(self.inbox.state()['cursor'],1)

    def test_empty_page_and_delete(self):
        self.inbox.apply(page(),MANIFEST)
        self.inbox.apply(page(1,[]),MANIFEST)
        deleted=record(2,2);deleted['operation']='delete'
        self.inbox.apply(page(1,[deleted]),MANIFEST)
        self.assertEqual(self.inbox.records(),[])

    def test_history_write_failure_rolls_back_facts_and_cursor(self):
        original = exchange_repo._insert_many
        def broken(cur,table,columns,rows):
            if table == 'financial_facts_history':raise RuntimeError('injected disk failure')
            return original(cur,table,columns,rows)
        with patch.object(exchange_repo,'_insert_many',side_effect=broken):
            with self.assertRaises(RuntimeError):self.inbox.apply(page(),MANIFEST)
        self.assertEqual(self.inbox.records(),[])
        self.assertEqual(self.inbox.state()['cursor'],0)
        self.inbox.apply(page(),MANIFEST)
        self.assertEqual(self.inbox.state()['cursor'],1)

    def test_laptop_database_copy_carries_cursor_and_records(self):
        self.inbox.apply(page(),MANIFEST)
        shutdown_stockdata_workers()
        laptop=self.path.with_name('laptop.accdb')
        shutil.copy2(self.path,laptop)
        enable_stockdata_workers()
        other=StockdataInbox(laptop)
        self.assertEqual(other.state()['cursor'],1)
        self.assertEqual(other.records(),self.inbox.records())
        other.apply(page(1,[record(2,2)]),MANIFEST)
        self.assertEqual(other.state()['cursor'],2)
        self.assertEqual(self.inbox.state()['cursor'],1)

    def test_existing_local_facts_keep_history_and_server_metadata(self):
        fact=FinancialFact('Yahoo','A','estimate','eps','q:2026-09-30',1.5,
            period_end=date(2026,9,30),period_kind='quarterly',currency='USD')
        financial_repo.store_result(self.path,'Yahoo','A','eps','A',FetchResult([fact]),datetime(2026,10,30))
        item=record();item.update(id=fact.key,source='Yahoo',dataset='estimate',schema_version=1,
            subject=dict(type='asset',id='A'),observed_at='2026-10-27T10:00:00Z',
            published_at=None,content_hash=digest(fact.payload),
            payload=dict(metric='eps',period=dict(key=fact.period_key,end='2026-09-30',kind='quarterly'),
                currency='USD',unit='',basis='unknown',**fact.payload))
        self.inbox.apply(page(items=[item]),MANIFEST)
        self.assertEqual(len(financial_repo.facts_for(self.path,'A',history=True)),1)
        self.assertEqual(self.inbox.records()[0]['revision'],1)
        updated=json.loads(json.dumps(item));updated['sequence']=2;updated['revision']=2
        updated['payload']['value']=1.7;updated['content_hash']=digest(dict(value=1.7,context={}))
        self.inbox.apply(page(1,[updated]),MANIFEST)
        self.assertEqual(len(financial_repo.facts_for(self.path,'A',history=True)),2)
        self.assertEqual(financial_repo.facts_for(self.path,'A')[0]['value_num'],1.7)
        self.assertEqual(self.inbox.records()[0]['revision'],2)

    def test_simultaneous_profile_pages_commit_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        def apply_once(_):
            try:return self.inbox.apply(page(),MANIFEST)
            except ValueError:return 'already advanced'
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(apply_once,range(2)))
        self.assertEqual(results.count(1),1)
        self.assertEqual(results.count('already advanced'),1)
        self.assertEqual(self.inbox.state()['cursor'],1)

    def test_local_yahoo_is_skipped_when_wyse_is_configured(self):
        from portefeuille_viewer.services.financial_data_service import FinancialDataService
        with patch('portefeuille_viewer.services.market_exchange.remote_collection_enabled',return_value=True):
            result=FinancialDataService(self.path).refresh()
        self.assertEqual(result.status,'skipped')
        self.assertIn('Wyse',result.message)

    def test_https_and_local_http_no_redirect(self):
        self.assertEqual(validate_url('https://data.example.com/'),'https://data.example.com')
        self.assertEqual(validate_url('http://192.168.2.160:18180'),'http://192.168.2.160:18180')
        for bad in ['http://example.com','https://user:pw@example.com','https://example.com/api','file:///tmp/a']:
            with self.assertRaises(ValueError):validate_url(bad)
        with self.assertRaises(ValueError):NoRedirect().redirect_request(None,None,None,None,None,None)

    def test_cloudflare_headers_require_tls_and_complete_credentials(self):
        with self.assertRaises(ValueError):
            ExchangeHTTP('http://192.168.2.160:18180','a'*40,
                cloudflare_client_id='device.access',cloudflare_client_secret='secret')
        with self.assertRaises(ValueError):
            ExchangeHTTP('https://markt-data.kiteco.nl','a'*40,cloudflare_client_id='device.access')
        with self.assertRaises(ValueError) as error:
            ExchangeHTTP('https://markt-data.kiteco.nl','a'*40,
                cloudflare_client_id='device.access',cloudflare_client_secret='private-secret\n')
        self.assertNotIn('private-secret',str(error.exception))
        client=ExchangeHTTP('https://markt-data.kiteco.nl','a'*40,
            cloudflare_client_id='device.access',cloudflare_client_secret='secret')
        from io import BytesIO
        from email.message import Message
        from unittest.mock import MagicMock
        response=MagicMock();headers=Message();headers['Content-Type']='application/json'
        response.__enter__.return_value=response;response.headers=headers;response.read.return_value=b'{}'
        with patch.object(client.opener,'open',return_value=response) as opened:
            client.get('manifest')
        sent=dict((k.lower(),v) for k,v in opened.call_args.args[0].header_items())
        self.assertEqual(sent['cf-access-client-id'],'device.access')
        self.assertEqual(sent['cf-access-client-secret'],'secret')
        self.assertEqual(sent['authorization'],'Bearer '+'a'*40)


if __name__=='__main__':unittest.main()

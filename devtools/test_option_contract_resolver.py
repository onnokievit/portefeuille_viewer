from datetime import date
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import threading
import os
from unittest.mock import MagicMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from portefeuille_viewer.services.option_contract_resolver import (
    ResolveSpec, reference_map, references_for, request_contracts, resolve,
)


def spec():
    return ResolveSpec('EURUSD-FUT','6E','USD',date(2026,11,20),1.125,'P',asset_type='future',
        references=[dict(opt_exchange='CME',opt_tradingclass=tc,opt_multiplier=125000) for tc in ('5EU','3EU')])


def detail(cid=936030866, **changes):
    values=dict(conId=cid,symbol='EUR',secType='FOP',exchange='CME',currency='USD',
        lastTradeDateOrContractMonth='20261120',strike=1.125,right='P',multiplier='125000',
        tradingClass='3EU',localSymbol='3EUX6 P1125')
    values.update(changes)
    return SimpleNamespace(contract=SimpleNamespace(**values))


class Feed:
    def __init__(self,rows):self.rows=rows;self.requests=[]
    def request_contract_details(self,contract,on_detail,on_end,on_error=None):
        self.requests.append(contract)
        for row in self.rows:on_detail(row)
        on_end()


class ResolverTests(unittest.TestCase):
    def test_duplicate_week_mappings_preserved_and_candidates_deduplicated(self):
        rows=[dict(asset_rollup='EURUSD-FUT',opt_week=0,opt_tradingclass=tc,opt_exchange='CME',opt_multiplier=125000)
              for tc in ('2EU','3EU','WE4','5EU','3EU')]
        mapping=reference_map(rows)
        self.assertEqual(len(mapping[('EURUSD-FUT',0)]),5)
        self.assertEqual(len(references_for(mapping,'EURUSD-FUT',3)),4)
        self.assertIn('3EU',[r['opt_tradingclass'] for r in references_for(mapping,'EURUSD-FUT',3)])

    def test_eurusd_uses_options_only_override_and_real_exchange(self):
        requested=spec();contracts=list(request_contracts(requested))
        self.assertTrue(contracts)
        self.assertTrue(all((c.symbol,c.secType,c.exchange,c.multiplier)==('EUR','FOP','CME','125000') for c in contracts))
        self.assertEqual(requested.symbol,'6E')
        self.assertEqual({c.tradingClass for c in contracts},{'','3EU','5EU'})

    def test_correct_contract_resolves_without_wrong_class(self):
        feed=Feed([detail()]);result=resolve(feed,spec(),.01)
        self.assertEqual(result.reason,'resolved')
        self.assertEqual(result.candidates[0]['conid'],936030866)
        self.assertEqual(len(feed.requests),1)

    def test_multiple_exact_contracts_are_not_automatically_chosen(self):
        result=resolve(Feed([detail(),detail(123,tradingClass='EUU',localSymbol='other')]),spec(),.01)
        self.assertEqual(result.reason,'ambiguous')
        self.assertEqual(len(result.candidates),2)

    def test_mismatched_fields_never_accepted(self):
        for changes in (dict(strike=1.13),dict(currency='EUR'),dict(symbol='6E'),dict(secType='OPT'),
                        dict(exchange='SMART'),dict(right='C'),dict(multiplier='100'),
                        dict(lastTradeDateOrContractMonth='20261030'),dict(localSymbol='')):
            with self.subTest(changes=changes):
                self.assertEqual(resolve(Feed([detail(**changes)]),spec(),.01).candidates,[])

    def test_timeout_never_accepts_incomplete_contract_list(self):
        class Partial:
            def request_contract_details(self,c,on_detail,on_end,on_error=None):on_detail(detail())
        result=resolve(Partial(),spec(),.001)
        self.assertEqual(result.reason,'timeout');self.assertEqual(result.candidates,[])

    def test_late_callback_and_error_do_not_contaminate_next_attempt(self):
        callbacks=[]
        class Retry:
            def request_contract_details(self,c,on_detail,on_end,on_error=None):
                if not callbacks:
                    callbacks.append(on_detail);on_error(200,'No security definition');return
                callbacks[0](detail(777))
                on_detail(detail(888));on_end()
        result=resolve(Retry(),spec(),.01)
        self.assertEqual(result.reason,'resolved')
        self.assertEqual([c['conid'] for c in result.candidates],[888])

    def test_ibkr_errors_are_visible_in_diagnostics(self):
        class Error:
            def request_contract_details(self,c,on_detail,on_end,on_error=None):on_error(200,'No security definition')
        result=resolve(Error(),spec(),.01)
        self.assertEqual(result.reason,'no_contract_details')
        self.assertIn('IBKR 200',result.message)

    def test_offline_does_not_queue_contract_requests(self):
        feed=Feed([]);feed.is_ready=lambda:False
        self.assertEqual(resolve(feed,spec(),.01).reason,'not_connected')
        self.assertEqual(feed.requests,[])

    def test_shared_client_forwards_contract_error_and_clears_callback(self):
        from portefeuille_viewer.services.shared_quote_client import RemotePriceFeedIB
        from unittest.mock import Mock
        error,end=Mock(),Mock()
        client=SimpleNamespace(lock=threading.RLock(),callbacks={'token':(Mock(),end,999999,error)})
        RemotePriceFeedIB._dispatch(client,'detail_error',('token',200,'No security definition'))
        error.assert_called_once_with(200,'No security definition')
        end.assert_called_once();self.assertEqual(client.callbacks,{})

    def test_stock_option_route_still_works(self):
        stock=ResolveSpec('AAPL','AAPL','USD',date(2026,11,20),200.,'C',asset_type='aandeel',
            references=[dict(opt_exchange='SMART',opt_tradingclass='AAPL',opt_multiplier=100)])
        feed=Feed([detail(symbol='AAPL',secType='OPT',exchange='SMART',strike=200.,right='C',
            multiplier='100',tradingClass='AAPL',localSymbol='AAPL test')])
        self.assertEqual(resolve(feed,stock,.01).reason,'resolved')

    def test_automatic_and_manual_use_same_validated_candidates(self):
        from portefeuille_viewer.services.option_timevalue_service import OptionTimevalueService,OpenSeriesRow
        feed=Feed([detail()]);connection=MagicMock();connection.__enter__.return_value=connection
        service=SimpleNamespace(price_feed=SimpleNamespace(_feed=feed),_resolve_wait_sec=.01,
            _option_resolve_spec=lambda *a:spec(),_connect_stockdb=lambda:connection,
            _series_key=OptionTimevalueService._series_key)
        row=OpenSeriesRow('broker','EURUSD-FUT','6E','USD','put',1.125,date(2026,11,20),1,'CME','5EU',125000,series_id=1)
        self.assertEqual(OptionTimevalueService._resolve_contracts(service,[row]),{})
        self.assertEqual(connection.execute.call_args.args[1][0],936030866)
        manual=OptionTimevalueService.get_manual_resolve_candidates(service,dict(asset='EURUSD-FUT',c_p='put',
            ccy='USD',strike=1.125,exp='2026-11-20'))
        self.assertEqual(manual[0]['conid'],936030866)
        self.assertEqual(row.underlying_symbol,'6E')
        feed.rows.append(detail(123,localSymbol='second'))
        connection.reset_mock()
        failed=OptionTimevalueService._resolve_contracts(service,[row])
        self.assertEqual(list(failed.values()),['ambiguous'])
        connection.execute.assert_not_called()


class ResolverStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile,subprocess,base64
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        cls.path=Path(cls.tmp.name)/'resolver.accdb'
        sql=('CREATE TABLE option_series_master (series_id COUNTER PRIMARY KEY, conid LONG, '
             'local_symbol TEXT(100), underlying_symbol TEXT(50), trading_class TEXT(50), '
             'exchange_code TEXT(50), multiplier DOUBLE, resolver_locked YESNO, '
             'last_verified_ts DATETIME, updated_at DATETIME)')
        script=("$ErrorActionPreference='Stop';$e=New-Object -ComObject DAO.DBEngine.120;"
            +"$d=$e.CreateDatabase('"+str(cls.path)+"',';LANGID=0x0409;CP=1252;COUNTRY=0',128);"
            +"$d.Execute('"+sql+"');$d.Close()")
        subprocess.run(['powershell','-NoProfile','-NonInteractive','-EncodedCommand',
            base64.b64encode(script.encode('utf-16-le')).decode()],capture_output=True,check=True,timeout=30)

    def check_case(self,details,locked=False,existing=None):
        from portefeuille_viewer.data.shared_database import connect_stockdata
        from portefeuille_viewer.services.option_timevalue_service import OptionTimevalueService,OpenSeriesRow
        with connect_stockdata(self.path) as conn:
            conn.execute('INSERT INTO option_series_master (conid,resolver_locked) VALUES (?,?)',existing,locked)
            sid=conn.execute('SELECT @@IDENTITY').fetchone()[0]
        feed=Feed(details)
        service=SimpleNamespace(price_feed=SimpleNamespace(_feed=feed),_resolve_wait_sec=.01,
            _option_resolve_spec=lambda *a:spec(),_connect_stockdb=lambda:connect_stockdata(self.path),
            _series_key=OptionTimevalueService._series_key)
        row=OpenSeriesRow('broker','EURUSD-FUT','6E','USD','put',1.125,date(2026,11,20),1,'CME','5EU',125000,series_id=int(sid))
        failed=OptionTimevalueService._resolve_contracts(service,[row])
        with connect_stockdata(self.path) as conn:
            saved=conn.execute('SELECT conid,underlying_symbol,trading_class,multiplier FROM option_series_master WHERE series_id=?',int(sid)).fetchone()
        return saved,failed

    def test_exact_contract_stored_in_access(self):
        row,failed=self.check_case([detail()])
        self.assertFalse(failed);self.assertEqual(tuple(row),(936030866,'EUR','3EU',125000.))

    def test_ambiguous_contract_does_not_write_master(self):
        row,failed=self.check_case([detail(),detail(123,localSymbol='other')])
        self.assertEqual(list(failed.values()),['ambiguous']);self.assertIsNone(row[0])

    def test_manual_lock_and_existing_conid_are_preserved(self):
        locked,_=self.check_case([detail()],locked=True)
        self.assertIsNone(locked[0])
        existing,_=self.check_case([detail()],existing=444)
        self.assertEqual(existing[0],444)


class ManualDialogTests(unittest.TestCase):
    def test_waiting_for_ibkr_does_not_block_ui(self):
        import time
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        from portefeuille_viewer.ui_logica.option_manual_resolver_dialog import OptionManualResolverDialog
        from portefeuille_viewer.services.option_contract_resolver import normalize
        app=QApplication.instance() or QApplication([])
        gate=threading.Event()
        service=SimpleNamespace(get_manual_resolve_candidates=lambda item:
            ([normalize(detail())] if gate.wait(2) else []))
        dialog=OptionManualResolverDialog(service,[dict(asset='EURUSD-FUT',exp='2026-11-20',
            c_p='put',strike=1.125,ccy='USD')])
        ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(5)
        try:
            dialog._load_candidates_for_selected()
            until=time.monotonic()+.06
            while time.monotonic()<until:app.processEvents();time.sleep(.002)
            self.assertGreater(len(ticks),1)
            self.assertFalse(dialog.btn_apply.isEnabled())
            gate.set();until=time.monotonic()+2
            while not dialog.tbl_candidates.rowCount() and time.monotonic()<until:
                app.processEvents();time.sleep(.002)
            self.assertEqual(dialog.tbl_candidates.rowCount(),1)
            self.assertTrue(dialog.btn_apply.isEnabled())
        finally:
            gate.set();timer.stop();dialog.close();dialog.deleteLater();app.processEvents()


if __name__=='__main__':unittest.main()

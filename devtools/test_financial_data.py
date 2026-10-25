"""Provider fixtures, fiscal-period safety, cadence and incremental dividend merge."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import threading

import pandas as pd

from portefeuille_viewer.services.financial_data_contract import FinancialFact, digest, surprise
from portefeuille_viewer.services.yahoo_financial_provider import YahooFinancialProvider, GROUPS
from portefeuille_viewer.services.financial_data_service import next_due
from portefeuille_viewer.data.dividend_calendar_repository import DividendCalendarRow, merge_dividend_row


ASSET = dict(asset_rollup='A', type='aandeel', yfinance_symbol='A.AS', ib_currency='EUR', INCL_EXCL=0)


class Ticker:
    def __init__(self, symbol):
        self.calendar = {'Earnings Date':[date(2026,10,28), date(2026,10,30)],
            'Earnings Average':1.2, 'Revenue Average':1000, 'Dividend Date':date(2026,11,1)}
        self._analysis = SimpleNamespace(_earnings_trend=[dict(period='0q', endDate='2026-09-30')])
    def get_earnings_estimate(self):
        return pd.DataFrame(dict(avg=[1.2],low=[1.0],high=[1.4],numberOfAnalysts=[10],currency=['USD']), index=['0q'])
    def get_revenue_estimate(self):
        return pd.DataFrame(dict(avg=[1000.],low=[950.],high=[1050.],currency=['USD']), index=['0q'])
    def get_eps_trend(self):
        return pd.DataFrame(dict(current=[1.2], **{'7daysAgo':[1.1]}), index=['0q'])
    def get_eps_revisions(self):
        return pd.DataFrame(dict(upLast7days=[2], downLast7days=[0]), index=['0q'])
    def get_earnings_history(self):
        return pd.DataFrame(dict(epsActual=[1.3],epsEstimate=[1.2],surprisePercent=[.08333]),
                            index=pd.to_datetime(['2026-09-30']))
    def get_earnings_dates(self, limit):
        return pd.DataFrame({'EPS Estimate':[1.2], 'Reported EPS':[1.3]},
                            index=pd.to_datetime(['2026-10-28 21:00:00+00:00']))
    def get_analyst_price_targets(self):
        return dict(current=100., low=90., mean=120., high=150.)
    def get_recommendations(self):
        return pd.DataFrame(dict(period=['0m'],strongBuy=[2],buy=[3],hold=[4],sell=[1],strongSell=[0]))
    def get_upgrades_downgrades(self):
        return pd.DataFrame(dict(Firm=['Firm A'],FromGrade=['Hold'],ToGrade=['Buy'],Action=['up']),
                            index=pd.to_datetime(['2026-10-20 10:00:00+00:00']))
    def get_income_stmt(self, freq):
        return pd.DataFrame({'2026-09-30':dict(TotalRevenue=1100.,GrossProfit=440.,OperatingIncome=220.,
                                             NetIncome=110.,DilutedEPS=1.1)})
    def get_cashflow(self, freq):
        return pd.DataFrame({'2026-09-30':dict(OperatingCashFlow=200.,FreeCashFlow=150.,CapitalExpenditure=-50.)})
    def get_info(self):
        return dict(financialCurrency='USD',currency='EUR')


class FinancialProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = YahooFinancialProvider(Ticker)
        self.provider.prepare()

    def test_every_group_normalizes_without_profile_or_database(self):
        for group in GROUPS:
            with self.subTest(group=group):
                result = self.provider.fetch(ASSET, group)
                self.assertEqual(result.status, 'ok')
                self.assertTrue(result.facts)
                self.assertTrue(all(f.source == 'Yahoo' and f.subject == 'A' for f in result.facts))

    def test_event_date_change_keeps_identity_and_range_is_not_confirmation(self):
        one = self.provider.fetch(ASSET, 'calendar').facts[0]
        self.provider._tickers['A.AS'].calendar['Earnings Date'] = [date(2026,10,31)]
        two = self.provider.fetch(ASSET, 'calendar').facts[0]
        self.assertEqual(one.key, two.key)
        self.assertNotEqual(one.payload, two.payload)
        self.assertEqual(one.value['certainty'], 'source_unconfirmed')
        self.assertEqual(one.value['date_end'], '2026-10-30')
        self.assertEqual(one.period_end, date(2026,9,30))

    def test_periods_are_from_source_not_inferred_from_current_calendar_quarter(self):
        result = self.provider.fetch(ASSET,'eps_estimate')
        self.assertEqual(result.facts[0].period_key, 'quarterly:2026-09-30')
        self.provider._tickers['A.AS']._analysis._earnings_trend = []
        result = self.provider.fetch(ASSET,'eps_estimate')
        self.assertTrue(all(f.period_end is None for f in result.facts))
        self.assertEqual(result.facts[0].context['period_resolution'], 'unknown')

    def test_financial_currency_is_separate_from_listing_and_margins_are_percent(self):
        facts = self.provider.fetch(ASSET,'income_quarterly').facts
        revenue = next(f for f in facts if f.metric == 'revenue')
        margin = next(f for f in facts if f.metric == 'gross_margin')
        self.assertEqual(revenue.currency, 'USD')
        self.assertEqual(margin.value, 40.)
        self.assertEqual(margin.unit, 'percent')
        self.assertFalse(any(f.category == 'estimate' for f in facts))

    def test_analyst_targets_do_not_create_revisions_for_current_quote(self):
        facts = self.provider.fetch(ASSET,'analyst_targets').facts
        self.assertFalse(any(f.metric == 'price_target.current' for f in facts))
        self.assertTrue(all(f.currency == 'EUR' for f in facts))

    def test_provider_eps_and_reported_diluted_eps_have_different_basis(self):
        source = self.provider.fetch(ASSET,'earnings_history').facts
        diluted = self.provider.fetch(ASSET,'income_quarterly').facts
        self.assertEqual(next(f for f in source if f.metric == 'eps').basis, 'provider_eps')
        self.assertEqual(next(f for f in diluted if f.metric == 'eps_diluted').basis, 'reported')
        self.assertEqual(next(f for f in source if f.metric == 'eps_beat_miss').value['verdict'], 'beat')

    def test_zero_values_are_not_missing(self):
        revisions = self.provider.fetch(ASSET,'eps_revisions').facts
        self.assertEqual(next(f for f in revisions if f.metric.endswith('downLast7days')).value, 0)

    def test_missing_mapping_and_ineligible_instruments_do_not_hit_network(self):
        provider = YahooFinancialProvider(Mock(side_effect=AssertionError('Network forbidden')))
        provider.prepare()
        self.assertEqual(provider.fetch(dict(ASSET, yfinance_symbol=''),'calendar').status,'missing_mapping')
        self.assertEqual(provider.fetch(dict(ASSET,type='future'),'eps_estimate').status,'not_applicable')
        self.assertEqual(provider.fetch(dict(ASSET,type='etf'),'eps_estimate').status,'not_applicable')

    def test_new_round_discards_in_memory_ticker_cache(self):
        self.provider.fetch(ASSET,'calendar')
        self.assertTrue(self.provider._tickers)
        self.provider.prepare()
        self.assertFalse(self.provider._tickers)

    def test_round_invalidates_process_wide_http_cache_without_network(self):
        from yfinance.data import YfData
        self.provider._uses_yfinance = True
        with patch.object(YfData.cache_get, 'cache_clear') as clear:
            self.provider.prepare()
            self.provider.prepare()
        self.assertEqual(clear.call_count,2)

    def test_scheduler_runs_collection_off_caller_thread_and_records_partial(self):
        from portefeuille_viewer.services import app_task_scheduler as scheduler
        lease=Mock();lease.acquire.return_value=True
        finished=threading.Event();ids=[];logs=[]
        result=SimpleNamespace(status='partial', rows_processed=2,rows_ok=1,rows_error=1,message='partial fixture')
        task=scheduler.ScheduledTask('financial_data_refresh','fixture',0,300000,
            lambda: ids.append(threading.get_ident()) or result,daily=False,shared_maintenance=False)
        owner=SimpleNamespace(_running=set())
        owner._run_task_thread=lambda task, run: (scheduler.AppTaskScheduler._run_task_thread(owner,task,run),finished.set())
        with patch('portefeuille_viewer.config.get_stockdata_db_path',return_value='fixture.accdb'), \
             patch('portefeuille_viewer.config.local_runtime.FileLease',return_value=lease), \
             patch.object(scheduler,'has_successful_run_today',side_effect=AssertionError('daily skip forbidden')), \
             patch.object(scheduler,'start_update_run',side_effect=lambda **kw:ids.append(threading.get_ident()) or 1), \
             patch.object(scheduler,'finish_update_run',side_effect=lambda run,**kw:logs.append(kw)):
            gui=threading.get_ident()
            scheduler.AppTaskScheduler._maybe_start_task(owner,task)
            self.assertTrue(finished.wait(3))
        self.assertTrue(all(tid!=gui for tid in ids))
        self.assertEqual(logs[-1]['status'],'partial')
        self.assertFalse(owner._running)

    def test_source_exception_propagates_for_retry_instead_of_no_data(self):
        ticker = Ticker('A')
        ticker.get_earnings_history = Mock(side_effect=TimeoutError('timeout'))
        self.provider._tickers['A.AS'] = ticker
        with self.assertRaises(TimeoutError):
            self.provider.fetch(ASSET, 'earnings_history')

    def test_cadence_daily_near_earnings_analysts_and_error_backoff(self):
        now = datetime(2026,10,25,9)
        self.assertEqual(next_due('income_yearly','ok',now), datetime(2026,10,26))
        self.assertEqual(next_due('analyst_targets','ok',now), now+timedelta(hours=1))
        self.assertEqual(next_due('calendar','ok',now,[{'date_end':'2026-10-29'}]), now+timedelta(hours=4))
        self.assertEqual(next_due('income_quarterly','ok',now,[{'date_end':'2026-10-25'}]),now+timedelta(hours=1))
        self.assertEqual(next_due('calendar','error',now,failures=2), now+timedelta(hours=1))

    def test_surprise_negative_zero_missing_and_margin_pp(self):
        self.assertEqual(surprise(-.1,-.2)['verdict'],'beat')
        self.assertNotIn('difference_pct',surprise(-.1,-.2))
        self.assertNotIn('difference_pct',surprise(1,0))
        self.assertEqual(surprise(None,1)['status'],'not_comparable')
        self.assertAlmostEqual(surprise(25,24,unit='percent')['difference_pp'],1.)

    def test_dividend_patch_preserves_earnings_values_and_zero(self):
        before = dict(next_earnings_date=date(2026,10,28), source_earnings='Yahoo',
                      next_dividend_date=date(2026,11,1), next_dividend_amount=1.2)
        row = DividendCalendarRow('A','A','EUR',None,None,0.,None,None,'IBKR','',
            'no_data','missing','',datetime.now(),datetime.now())
        merged = merge_dividend_row(before,row)
        self.assertEqual(merged['source_earnings'],'Yahoo')
        self.assertEqual(merged['next_dividend_amount'],1.2)
        self.assertEqual(merged['trailing_12m_dividend'],0.)
        row.next_dividend_date = date(2026,12,1)
        merged = merge_dividend_row(before,row)
        self.assertEqual(merged['next_dividend_date'],before['next_dividend_date'])


if __name__ == '__main__':
    unittest.main()

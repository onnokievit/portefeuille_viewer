"""Shared, resumable provider collection. Network never holds a database writer lock."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import logging
import time

from portefeuille_viewer.config.local_runtime import FileLease
from portefeuille_viewer.config.process_lock import canonical_path
from portefeuille_viewer.data import financial_data_repository as repo
from portefeuille_viewer.services.financial_data_contract import FetchResult, FinancialFact, as_date, utcnow


@dataclass
class CollectionResult:
    rows_processed: int = 0
    rows_ok: int = 0
    rows_error: int = 0
    rows_no_data: int = 0
    rows_skipped: int = 0
    rows_changed: int = 0
    message: str = ''
    status: str = 'ok'


class FinancialDataService:
    def __init__(self, path=None, providers=None, *, max_seconds=180, max_jobs=200,
                 clock=utcnow, pause=time.sleep):
        if path is None:
            from portefeuille_viewer.config import get_stockdata_db_path
            path = get_stockdata_db_path()
        if providers is None:
            from portefeuille_viewer.services.yahoo_financial_provider import YahooFinancialProvider
            providers = [YahooFinancialProvider()]
        self.path = path
        self.providers = providers
        self.max_seconds = max_seconds
        self.max_jobs = max_jobs
        self.clock = clock
        self.pause = pause

    def refresh(self):
        result = CollectionResult()
        lease = FileLease('financial-collection:' + canonical_path(self.path))
        if not lease.acquire():
            result.status, result.message = 'skipped', 'Andere instantie haalt financiële gegevens op'
            return result
        try:
            if not repo.schema_ready(self.path):
                result.status = 'skipped'
                result.message = 'Financiële opslag nog niet geïnstalleerd; voer setup_financial_data_stockdata.py uit'
                return result
            states = repo.fetch_states(self.path)
            assets = repo.load_assets(self.path)
            now = self.clock()
            started = time.monotonic()
            for provider in self.providers:
                cooldown = states.get(repo.state_key(provider.name, '__provider__', 'cooldown'))
                if cooldown and cooldown['next_due'] and cooldown['next_due'] > now:
                    continue
                try:
                    provider.prepare()
                except Exception as exc:
                    result.rows_error += 1
                    repo.store_result(self.path, provider.name, '__provider__', 'cooldown', '',
                        FetchResult(status='error', message=f'{type(exc).__name__}: {exc}'),
                        now+timedelta(hours=1), now)
                    logging.exception('Financial provider initialisation failed: %s', provider.name)
                    continue
                jobs = []
                subjects = provider.subjects(self.path) if hasattr(provider, 'subjects') else assets
                for asset in subjects:
                    subject = str(asset.get('asset_rollup') or asset.get('subject_key') or '').strip()
                    if not subject:
                        continue
                    selector = selector_for(asset)
                    for order, group in enumerate(provider.groups):
                        state = states.get(repo.state_key(provider.name, subject, group))
                        due = (state.get('next_due') if state else None) or datetime.min
                        if state is None or state.get('symbol') != selector or due <= now:
                            jobs.append((due, order, subject, asset, group, state))
                # Oldest checkpoints first: interrupted initial imports progress
                # through the universe instead of restarting at the first asset.
                jobs.sort(key=lambda job: job[:3])
                event_dates = {}
                for _, _, subject, asset, group, state in jobs:
                    if result.rows_processed >= self.max_jobs or time.monotonic()-started >= self.max_seconds:
                        break
                    if subject not in event_dates:
                        event_dates[subject] = repo.earnings_window(self.path, subject)
                    try:
                        fetched = provider.fetch(asset, group)
                    except Exception as exc:
                        fetched = FetchResult(status='error', message=f'{type(exc).__name__}: {exc}')
                    observed = self.clock()
                    due = next_due(group, fetched.status, observed, event_dates[subject],
                                   int(state.get('failures') or 0) if state else 0)
                    result.rows_changed += repo.store_result(self.path, provider.name, subject, group,
                        selector_for(asset), fetched, due, observed)
                    if group.startswith('income_') or group == 'earnings_history':
                        from portefeuille_viewer.services.financial_comparisons import build_comparisons
                        comparisons = build_comparisons(self.path, provider.name, subject)
                        if comparisons:
                            result.rows_changed += repo.store_result(self.path, provider.name, subject,
                                'comparisons', selector_for(asset), FetchResult(comparisons), due, observed)
                    result.rows_processed += 1
                    if fetched.status == 'error':
                        result.rows_error += 1
                        logging.warning('Financial data %s %s %s: %s', provider.name, subject, group, fetched.message)
                    elif fetched.status == 'ok':
                        result.rows_ok += 1
                    elif fetched.status == 'no_data':
                        result.rows_no_data += 1
                    else:
                        result.rows_skipped += 1
                    for fact in fetched.facts:
                        if fact.category == 'event' and fact.metric == 'earnings_schedule':
                            event_dates[subject] = [fact.value]
                    if '429' in fetched.message or 'ratelimit' in fetched.message.replace(' ', '').lower():
                        repo.store_result(self.path, provider.name, '__provider__', 'cooldown', '',
                            FetchResult(status='error', message=fetched.message), observed+timedelta(hours=1), observed)
                        break
                    self.pause(.25)
            result.status = 'partial' if result.rows_error else 'ok'
            result.message = (f'Financiële gegevens: gecontroleerd={result.rows_processed}, '
                f'goed={result.rows_ok}, ontbreekt={result.rows_no_data}, overgeslagen={result.rows_skipped}, '
                f'fouten={result.rows_error}, wijzigingen={result.rows_changed}')
            return result
        finally:
            lease.release()


def selector_for(asset):
    # Mapping/type/currency edits invalidate even a not_applicable checkpoint.
    return '|'.join(str(asset.get(k) or '').strip() for k in ('yfinance_symbol', 'type', 'ib_currency'))[:128]


def next_due(group, status, now, events=(), failures=0):
    if status == 'error':
        return now + timedelta(minutes=min(360, 15*2**min(failures, 5)))
    if status in {'missing_mapping', 'not_applicable'}:
        return now + timedelta(days=1)
    if status == 'no_data':
        return now + timedelta(hours=6)
    if group in {'analyst_targets', 'recommendations', 'analyst_changes'}:
        return now + timedelta(hours=1)
    for event in events:
        day = as_date(event.get('date_end'))
        if day:
            days = (day-now.date()).days
            if -2 <= days <= 0:
                return now + timedelta(hours=1)
            if 0 < days <= 7:
                return now + timedelta(hours=4)
    # Calendar day checkpoint: start next morning, rather than drifting later
    # every day when one session started at 15:00 and another at 09:00.
    return datetime.combine(now.date()+timedelta(days=1), datetime.min.time())


def record_ibkr_dividends(rows, path=None):
    """Mirror IBKR observations into the shared fact history, after legacy commit."""
    if path is None:
        from portefeuille_viewer.config import get_stockdata_db_path
        path = get_stockdata_db_path()
    if not repo.schema_ready(path):
        return
    now = utcnow()
    for row in rows:
        facts = []
        if row.status == 'ok':
            for field, unit in [('next_dividend_date','date'), ('next_dividend_amount','currency_per_share'),
                                ('trailing_12m_dividend','currency_per_share'), ('forward_12m_dividend','currency_per_share')]:
                value = getattr(row, field)
                if value is not None:
                    facts.append(FinancialFact('IBKR', row.asset_rollup, 'dividend_projection', field,
                        'rolling_next' if field.startswith('next') else 'rolling_12m',
                        value, currency=row.ib_currency, unit=unit, basis='ibkr_tick_59',
                        context={'date_semantics': 'next_dividend_date_unspecified'}))
        status = 'error' if row.status == 'error' else 'no_data' if not facts else 'ok'
        repo.store_result(path, 'IBKR', row.asset_rollup, 'dividends', row.ib_symbol,
            FetchResult(facts, raw=row.raw_dividend_value, status=status, message=row.message),
            now+timedelta(days=1), now)

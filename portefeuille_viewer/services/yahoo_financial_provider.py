"""Yahoo-specific parsing is isolated here; no DB, profiles or Qt dependencies."""
from datetime import datetime, timezone

from portefeuille_viewer.services.financial_data_contract import (
    FinancialFact, FetchResult, as_date, clean, number, surprise, digest)


GROUPS = ('calendar', 'earnings_history', 'eps_estimate', 'revenue_estimate', 'analyst_targets',
          'recommendations', 'analyst_changes', 'earnings_dates', 'eps_trend', 'eps_revisions',
          'income_quarterly', 'income_yearly', 'cashflow_quarterly', 'cashflow_yearly')
STOCK_TYPES = {'aandeel', 'stock', 'equity', ''}
FUND_TYPES = {'etf', 'fonds', 'fund'}


class YahooFinancialProvider:
    name = 'Yahoo'
    groups = GROUPS

    def __init__(self, ticker_factory=None):
        self._uses_yfinance = ticker_factory is None
        self._factory = ticker_factory
        self._tickers = {}

    def prepare(self):
        if self._factory is None:
            import yfinance as yf
            from yfinance.config import YfConfig
            from portefeuille_viewer.config.local_runtime import runtime_root
            # Local computer cache, independent of source directory/profile.
            yf.set_tz_cache_location(str(runtime_root() / 'yfinance'))
            # Do not silently classify connection errors as "no data".
            YfConfig.debug.hide_exceptions = False
            YfConfig.network.retries = 0
            self._factory = yf.Ticker
        # A new task round must NOT reuse yesterday's in-memory Ticker caches.
        self._tickers.clear()
        if self._uses_yfinance:
            # get_earnings_dates uses a process-wide unbounded-age HTTP LRU,
            # separate from Ticker. Explicitly invalidate it for each new round.
            from yfinance.data import YfData
            YfData().cache_get.cache_clear()

    def applicable(self, asset, group):
        kind = str(asset.get('type') or '').strip().lower()
        return kind in STOCK_TYPES or (kind in FUND_TYPES and group == 'calendar')

    def fetch(self, asset, group):
        symbol = str(asset.get('yfinance_symbol') or '').strip()
        if not symbol:
            return FetchResult(status='missing_mapping', message='Geen yfinance_symbol')
        if not self.applicable(asset, group):
            return FetchResult(status='not_applicable', message='Geen bedrijfsrapportage voor dit instrumenttype')
        ticker = self._tickers.setdefault(symbol, None)
        if ticker is None:
            ticker = self._factory(symbol)
            self._tickers[symbol] = ticker
        subject = str(asset['asset_rollup'])
        facts = []
        def add(category, metric, period, value, *, end=None, kind='unknown', currency='',
                unit='', basis='unknown', context=None, source_at=None):
            value = clean(value)
            if value is not None and value != '':
                facts.append(FinancialFact(self.name, subject, category, metric, str(period), value,
                    end, kind, currency or '', unit, basis, source_at, context or {}))

        if group == 'calendar':
            raw = ticker.calendar or {}
            dates = sorted({str(as_date(d)) for d in raw.get('Earnings Date', []) if as_date(d)})
            if dates:
                # Use the provider's current reporting period if supplied. Never
                # infer a fiscal quarter from the month of the announcement.
                try:
                    ticker.get_earnings_estimate()
                    trend = getattr(getattr(ticker, '_analysis', None), '_earnings_trend', None) or []
                    end = next((as_date(i.get('endDate')) for i in trend if i.get('period') == '0q'), None)
                    if end and end > as_date(dates[0]):
                        end = None  # Inconsistent source period; do not link by guess.
                except Exception:
                    end = None
                add('event', 'earnings_schedule', f'quarterly:{end}' if end else 'rolling_next',
                    dict(date_start=dates[0], date_end=dates[-1], dates=dates,
                         certainty='source_unconfirmed', time_precision='date'),
                    end=end, kind='quarterly' if end else 'unknown',
                    context={'period_resolution': 'source' if end else 'unknown', 'symbol': symbol})
            for field, metric in [('Ex-Dividend Date', 'ex_dividend_date'), ('Dividend Date', 'dividend_payment_date')]:
                day = as_date(raw.get(field))
                if day:
                    add('event', metric, str(day), str(day), basis='source_date', context={'symbol': symbol})
            for field, metric in [('Earnings Average', 'eps_consensus'), ('Earnings Low', 'eps_low'),
                                  ('Earnings High', 'eps_high'), ('Revenue Average', 'revenue_consensus'),
                                  ('Revenue Low', 'revenue_low'), ('Revenue High', 'revenue_high')]:
                value = number(raw.get(field))
                if value is not None:
                    add('calendar_estimate', metric, 'rolling_next', value,
                        basis='source_unspecified', context={'earnings_dates': dates,
                        'period_resolution': 'unknown', 'comparable': False})
        elif group in {'eps_estimate', 'revenue_estimate', 'eps_trend', 'eps_revisions'}:
            getter = {'eps_estimate':'get_earnings_estimate', 'revenue_estimate':'get_revenue_estimate',
                      'eps_trend':'get_eps_trend', 'eps_revisions':'get_eps_revisions'}[group]
            frame = getattr(ticker, getter)()
            raw = frame_rows(frame)
            # Public yfinance frames omit endDate. Read ONLY optional metadata,
            # isolated to this version-tested adapter. Never infer fiscal dates.
            trend = getattr(getattr(ticker, '_analysis', None), '_earnings_trend', None) or []
            ends = {item.get('period'): as_date(item.get('endDate')) for item in trend if isinstance(item, dict)}
            for item in raw:
                label, row = item['index'], item['values']
                end = ends.get(label)
                kind = 'quarterly' if str(label).endswith('q') else 'yearly' if str(label).endswith('y') else 'unknown'
                period = f'{kind}:{end}' if end else f'unresolved:{label}'
                currency = str(row.get('currency') or '')
                for field, value in row.items():
                    value = number(value)
                    if value is not None:
                        add('estimate' if group.endswith('estimate') else 'estimate_trend', f'{group}.{field}',
                            period, value, end=end, kind=kind, currency=currency,
                            unit=('analysts' if field == 'numberOfAnalysts' else
                                  'fraction' if field == 'growth' else
                                  'currency_per_share' if group.startswith('eps') else 'currency'),
                            basis='provider_eps' if group.startswith('eps') else 'total_revenue',
                            context={'source_period_label': label,
                                     'period_resolution': 'source' if end else 'unknown'})
        elif group == 'earnings_history':
            raw = frame_rows(ticker.get_earnings_history())
            try:
                currency = str((ticker.get_info() or {}).get('financialCurrency') or '')
            except Exception:
                currency = ''
            for item in raw:
                end, row = as_date(item['index']), item['values']
                if not end:
                    continue
                period = f'quarterly:{end}'
                for field, metric in [('epsActual','eps'), ('epsEstimate','eps_consensus_at_report'),
                                      ('epsDifference','eps_difference'), ('surprisePercent','eps_surprise_source')]:
                    value = number(row.get(field))
                    if value is not None:
                        add('actual' if field == 'epsActual' else 'report_comparison', metric, period, value,
                            end=end, kind='quarterly', currency=currency,
                            unit='currency_per_share' if field in {'epsActual','epsEstimate','epsDifference'} else 'source_surprise',
                            basis='provider_eps', context={'source_row': row})
                comparison = surprise(row.get('epsActual'), row.get('epsEstimate'))
                if comparison['status'] == 'comparable':
                    add('report_comparison', 'eps_beat_miss', period, comparison, end=end,
                        kind='quarterly', basis='provider_eps', context={'comparison_origin': 'provider_paired_values',
                        'prepublication_observation_guaranteed': False})
        elif group == 'earnings_dates':
            raw = frame_rows(ticker.get_earnings_dates(limit=24))
            for item in raw:
                day = as_date(item['index'])
                if day:
                    # Preserve source publication rows; no guessed quarter linkage.
                    add('publication', 'earnings_source_row', 'publication:'+item['index'], item['values'],
                        context={'date': str(day), 'timestamp_source': item['index'], 'period_resolution': 'unknown'})
        elif group == 'analyst_targets':
            raw = clean(ticker.get_analyst_price_targets() or {})
            try:
                currency = str((ticker.get_info() or {}).get('currency') or '')
            except Exception:
                currency = ''
            for field, value in raw.items():
                if field == 'current':
                    continue  # A changing quote is not an analyst target revision.
                if number(value) is not None:
                    add('analyst', 'price_target.'+field, 'current', number(value),
                        currency=currency, unit='listing_price',
                        basis='source_listing_unit', context={'symbol': symbol, 'currency_verified': bool(currency)})
        elif group == 'recommendations':
            raw = frame_rows(ticker.get_recommendations())
            for item in raw:
                row = item['values']
                period = str(row.get('period') or item['index'])
                for field in ('strongBuy','buy','hold','sell','strongSell'):
                    if number(row.get(field)) is not None:
                        add('analyst', 'recommendation.'+field, period, number(row[field]), unit='analysts',
                            context={'source_period_label': period})
        elif group == 'analyst_changes':
            raw = frame_rows(ticker.get_upgrades_downgrades())
            for item in raw:
                row = item['values']
                firm = str(row.get('Firm') or row.get('firm') or '')
                add('analyst_event', 'rating_or_target_change', digest([item['index'], firm]), row,
                    source_at=source_datetime(item['index']),
                    context={'firm': firm, 'source_timestamp': item['index'], 'symbol': symbol})
        elif group.startswith(('income_', 'cashflow_')):
            kind = 'quarterly' if group.endswith('quarterly') else 'yearly'
            getter = ticker.get_income_stmt if group.startswith('income_') else ticker.get_cashflow
            frame = getter(freq=kind)
            raw = statement_rows(frame)
            # Financial currency differs from listing currency. Preserve unknowns.
            try:
                currency = str((ticker.get_info() or {}).get('financialCurrency') or '')
            except Exception:
                currency = ''
            mapping = {'TotalRevenue':'revenue', 'GrossProfit':'gross_profit', 'OperatingIncome':'operating_income',
                       'NetIncome':'net_income', 'BasicEPS':'eps_basic', 'DilutedEPS':'eps_diluted',
                       'EBITDA':'ebitda', 'EBIT':'ebit', 'OperatingCashFlow':'operating_cashflow',
                       'FreeCashFlow':'free_cashflow', 'CapitalExpenditure':'capital_expenditure'}
            for item in raw:
                end, row = as_date(item['period']), item['values']
                if not end:
                    continue
                period = f'{kind}:{end}'
                for field, metric in mapping.items():
                    value = number(row.get(field))
                    if value is not None:
                        add('actual', metric, period, value, end=end, kind=kind, currency=currency,
                            unit='currency_per_share' if metric.startswith('eps') else 'currency',
                            basis='total_revenue' if metric == 'revenue' else 'reported',
                            context={'source_field': field, 'currency_known': bool(currency)})
                revenue = number(row.get('TotalRevenue'))
                if revenue is not None and revenue != 0:
                    for field, metric in [('GrossProfit','gross_margin'), ('OperatingIncome','operating_margin'),
                                          ('NetIncome','net_margin')]:
                        value = number(row.get(field))
                        if value is not None:
                            add('actual', metric, period, 100*value/revenue, end=end, kind=kind,
                                unit='percent', basis='reported', context={'formula': f'{field}/TotalRevenue*100',
                                'formula_version': 1})
        else:
            raise ValueError('Unknown Yahoo data group: '+group)
        return FetchResult(facts=facts, raw=raw, status='ok' if facts else 'no_data')


def frame_rows(frame):
    if frame is None or frame.empty:
        return []
    return [{'index': str(index), 'values': clean(row.to_dict())} for index, row in frame.iterrows()]


def statement_rows(frame):
    if frame is None or frame.empty:
        return []
    return [{'period': str(column), 'values': clean(frame[column].to_dict())} for column in frame.columns]


def source_datetime(value):
    try:
        result = datetime.fromisoformat(str(value))
        return result.astimezone(timezone.utc).replace(tzinfo=None) if result.tzinfo else None
    except (ValueError, TypeError):
        return None

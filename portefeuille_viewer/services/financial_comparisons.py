"""Conservative observed-consensus comparisons. No period/date/basis guessing."""
from datetime import datetime, time
import json

from portefeuille_viewer.data import financial_data_repository as repo
from portefeuille_viewer.services.financial_data_contract import FinancialFact, as_date, surprise


def build_comparisons(path, source, subject):
    current = repo.facts_for(path, subject, source)
    historical = repo.facts_for(path, subject, source, history=True)
    events = {row['period_key']: row for row in current if row['category'] == 'event'
              and row['metric'] == 'earnings_schedule' and row['period_end']}
    mapping = {'eps':'eps_estimate.avg', 'revenue':'revenue_estimate.avg',
               'gross_margin':'gross_margin_estimate.avg', 'operating_margin':'operating_margin_estimate.avg',
               'net_margin':'net_margin_estimate.avg'}
    result = []
    for actual in current:
        if actual['category'] != 'actual' or actual['metric'] not in mapping:
            continue
        event = events.get(actual['period_key'])
        reason = ''
        cutoff = None
        if event:
            schedule = json.loads(event['payload_json'])['value']
            days = [as_date(json.loads(row['payload_json'])['value'].get('date_start')) for row in historical
                    if row['category'] == 'event' and row['metric'] == 'earnings_schedule'
                    and row['period_key'] == actual['period_key']]
            day = min((day for day in days if day), default=as_date(schedule.get('date_start')))
            if day:
                # Date-only and even estimated ranges: use START of earliest
                # possible day, never estimates observed after publication.
                cutoff = datetime.combine(day, time())
        if cutoff is None:
            reason = 'publication_date_or_period_unknown'
        candidates = [row for row in historical if cutoff and row['category'] == 'estimate'
            and row['metric'] == mapping[actual['metric']] and row['period_key'] == actual['period_key']
            and row['changed_at'] < cutoff and row['currency_code'] == actual['currency_code']
            and row['unit_code'] == actual['unit_code'] and row['basis'] == actual['basis']]
        if not actual['currency_code'] and actual['unit_code'] != 'percent':
            candidates = []
            reason = reason or 'currency_unknown'
        estimate = max(candidates, key=lambda r: (r['changed_at'], r['revision'])) if candidates else None
        context = dict(actual_fact_key=actual['fact_key'], actual_revision=actual['revision'])
        if estimate:
            value = surprise(actual['value_num'], estimate['value_num'], unit=actual['unit_code'])
            context.update(consensus_fact_key=estimate['fact_key'], consensus_revision=estimate['revision'],
                consensus_observed_at=estimate['changed_at'].isoformat(),
                comparison_origin='observed_before_earliest_scheduled_date', event_fact_key=event['fact_key'],
                comparison_cutoff_utc=cutoff.isoformat(),
                date_certainty='source_unconfirmed')
        else:
            value = dict(status='not_comparable', reason=reason or 'no_matching_prepublication_consensus')
        result.append(FinancialFact(source, subject, 'observed_comparison', actual['metric']+'_beat_miss',
            actual['period_key'], value, period_end=as_date(actual['period_end']), period_kind=actual['period_kind'],
            currency=actual['currency_code'] or '', unit=actual['unit_code'] or '', basis=actual['basis'] or 'unknown',
            context=context))
    return result

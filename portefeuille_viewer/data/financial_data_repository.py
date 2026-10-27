"""Versioned STOCKDATA facts. No automatic schema changes or network calls."""
from datetime import datetime, time, timedelta

from portefeuille_viewer.data.shared_database import connect_stockdata
from portefeuille_viewer.data.stockdata_worker import stockdata_job
from portefeuille_viewer.services.financial_data_contract import digest, encode, utcnow, clean
import json

SCHEMA_VERSION = 1
TABLES = ('financial_data_schema', 'financial_facts_current', 'financial_facts_history', 'financial_fetch_state')
FACT_COLUMNS = ('fact_key', 'source', 'subject_type', 'subject_key', 'category', 'metric',
    'period_key', 'period_end', 'period_kind', 'currency_code', 'unit_code', 'basis',
    'value_num', 'payload_json', 'content_hash', 'source_at', 'first_seen', 'last_seen', 'changed_at', 'revision')


@stockdata_job
def schema_ready(path):
    with connect_stockdata(path) as conn:
        cur = conn.cursor()
        names = {str(r.table_name).lower() for r in cur.tables(tableType='TABLE')}
        if not set(TABLES).issubset(names):
            return False
        row = cur.execute('SELECT schema_version FROM financial_data_schema WHERE schema_id=1').fetchone()
        return bool(row and int(row[0]) == SCHEMA_VERSION)


@stockdata_job
def load_assets(path):
    """All catalog records, including unheld/INCL_EXCL=0 records and missing mappings."""
    with connect_stockdata(path) as conn:
        cur = conn.execute('SELECT * FROM asset_rollup_data ORDER BY asset_rollup')
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def _dicts(cur):
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


@stockdata_job
def facts_for(path, subject, source=None, history=False):
    table = 'financial_facts_history' if history else 'financial_facts_current'
    with connect_stockdata(path) as conn:
        sql = f'SELECT * FROM {table} WHERE subject_key=?'
        params = [subject]
        if source:
            sql += ' AND source=?'
            params.append(source)
        records = _dicts(conn.execute(sql, *params))
        if not history:
            records = [row for row in records if json.loads(row['payload_json']).get(
                '__wyse_envelope__', {}).get('operation') != 'delete']
        return records


@stockdata_job
def fetch_states(path):
    with connect_stockdata(path) as conn:
        return {r['state_key']: r for r in _dicts(conn.execute('SELECT * FROM financial_fetch_state'))}


def state_key(source, subject, group):
    return digest([source, subject, group])


def _insert_many(cur, table, columns, rows):
    if rows:
        cur.executemany(f'INSERT INTO [{table}] (' + ','.join(f'[{c}]' for c in columns)
            + ') VALUES (' + ','.join('?' for _ in columns) + ')', rows)


@stockdata_job
def store_result(path, source, subject, group, symbol, result, next_due, observed_at=None):
    """Merge nonmissing fields; changed facts and fetch checkpoint commit together."""
    now = observed_at or utcnow()
    with connect_stockdata(path) as conn:
        conn.begin_write()
        cur = conn.cursor()
        existing = {r['fact_key']: r for r in _dicts(cur.execute(
            'SELECT * FROM financial_facts_current WHERE source=? AND subject_key=?', source, subject))}
        inserts, updates, history, seen = [], [], [], []
        for fact in result.facts:
            if fact.source != source or fact.subject != subject:
                raise ValueError('Financial provider returned a different subject/source')
            value = clean(fact.value)
            if value is None or value == '':
                continue
            previous = existing.get(fact.key)
            # Sparse responses patch existing values, rather than replacing with nulls.
            payload = fact.payload
            if previous:
                old_payload = json.loads(previous['payload_json'])
                payload = merge_available(old_payload, payload)
            content_hash = digest(payload)
            if previous and previous['content_hash'] == content_hash:
                seen.append((now, fact.key))
                continue
            revision = int(previous['revision'])+1 if previous else 1
            numeric = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            row = (fact.key, source, fact.subject_type, subject, fact.category, fact.metric,
                fact.period_key, datetime.combine(fact.period_end, time()) if fact.period_end else None,
                fact.period_kind, fact.currency, fact.unit, fact.basis, numeric, encode(payload), content_hash,
                fact.source_at, previous['first_seen'] if previous else now, now, now, revision)
            history.append(row)
            if previous:
                updates.append(row[1:] + (fact.key,))
            else:
                inserts.append(row)
            existing[fact.key] = dict(zip(FACT_COLUMNS, row))
        _insert_many(cur, 'financial_facts_current', FACT_COLUMNS, inserts)
        if seen:
            cur.executemany('UPDATE financial_facts_current SET last_seen=? WHERE fact_key=?', seen)
        if updates:
            cur.executemany('UPDATE financial_facts_current SET '
                + ','.join(f'[{c}]=?' for c in FACT_COLUMNS[1:]) + ' WHERE fact_key=?', updates)
        _insert_many(cur, 'financial_facts_history', FACT_COLUMNS, history)
        key = state_key(source, subject, group)
        old = cur.execute('SELECT failures,last_success,raw_json FROM financial_fetch_state WHERE state_key=?', key).fetchone()
        failures = (int(old[0] or 0)+1) if old and result.status == 'error' else int(result.status == 'error')
        success = now if result.status in {'ok', 'no_data', 'not_applicable'} else old[1] if old else None
        raw_json = (old[2] if old and result.raw is None else
                    encode(dict(received_at_utc=now, data=result.raw)))
        values = (source, subject, group, symbol, result.status, now, success, next_due,
                  failures, result.message[:4000], raw_json)
        if old:
            cur.execute('UPDATE financial_fetch_state SET source=?,subject_key=?,group_name=?,symbol=?,status=?, '
                'last_attempt=?,last_success=?,next_due=?,failures=?,message=?,raw_json=? WHERE state_key=?',
                *(values+(key,)))
        else:
            _insert_many(cur, 'financial_fetch_state', ('state_key','source','subject_key','group_name','symbol',
                'status','last_attempt','last_success','next_due','failures','message','raw_json'), [(key,)+values])
        return len(history)


def merge_available(old, new):
    result = dict(old)
    for key, value in new.items():
        if value is None or value == '':
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            value = merge_available(result[key], value)
        result[key] = value
    return result


def earnings_window(path, subject):
    """Latest known schedule, retaining historical dates without presenting them as future."""
    records = facts_for(path, subject)
    events = []
    for row in records:
        if row['category'] == 'event' and row['metric'] == 'earnings_schedule':
            value = json.loads(row['payload_json'])['value']
            if value.get('date_end'):
                events.append(value)
    return events

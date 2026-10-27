"""Wyse facts, history AND replication cursor in the existing STOCKDATA tables.

Remote revisions are carried in payload metadata. Local revision numbers remain
monotonic, preserving facts previously collected by the app without collisions.
No schema creation, HTTP, or file cache is performed here.
"""
from datetime import datetime, timedelta, timezone
import json

from .shared_database import connect_stockdata
from .stockdata_worker import stockdata_job
from .financial_data_repository import FACT_COLUMNS, _insert_many, schema_ready
from portefeuille_viewer.services.financial_data_contract import digest, encode, utcnow

STATE_KEY = digest(['market_exchange', 'api_v1', 'default'])
META = '__wyse_envelope__'


def _datetime(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def _state(conn):
    row = conn.execute('SELECT raw_json,last_success FROM financial_fetch_state WHERE state_key=?', STATE_KEY).fetchone()
    if row is None:
        return dict(stream_id='', cursor=0, last_sync=None, manifest_json=None)
    stored = json.loads(row[0])
    return dict(stream_id=stored['stream_id'], cursor=stored['cursor'],
                last_sync=row[1].isoformat()+'Z' if row[1] else None,
                manifest_json=encode(stored['manifest']))


@stockdata_job
def state(path):
    with connect_stockdata(path) as conn:
        return _state(conn)


@stockdata_job
def apply_page(path, page, manifest):
    from portefeuille_viewer.services.market_exchange import validate_page
    with connect_stockdata(path) as conn:
        conn.begin_write()
        old = _state(conn)
        items = validate_page(page, manifest, old)
        cur = conn.cursor()
        now = utcnow()
        for item in items:
            key = item['id']
            # Access key/field limits must fail explicitly, never silently truncate.
            payload = item['payload']
            period = payload.get('period') or {}
            if not isinstance(period, dict):
                raise ValueError('Ongeldige rapportageperiode')
            metric = payload.get('metric', '__record__')
            period_key = period.get('key', key)
            for value, limit in ((key,64),(item['source'],32),(item['subject']['type'],24),
                    (item['subject']['id'],128),(item['dataset'],40),(metric,80),(period_key,160),
                    (period.get('kind','unknown'),24),(payload.get('currency',''),16),
                    (payload.get('unit',''),24),(payload.get('basis','unknown'),40)):
                if not isinstance(value, str) or len(value) > limit:
                    raise ValueError('API-veld past niet in STOCKDATA; geen data opgeslagen')
            previous_cur = cur.execute('SELECT '+','.join('['+c+']' for c in FACT_COLUMNS)
                +' FROM financial_facts_current WHERE fact_key=?', key)
            previous_row = previous_cur.fetchone()
            previous = dict(zip(FACT_COLUMNS, previous_row)) if previous_row else None
            old_payload = json.loads(previous['payload_json']) if previous else {}
            remote_old = old_payload.get(META, {})
            if remote_old.get('stream_id') == page['stream_id'] and item['revision'] <= remote_old['revision']:
                raise ValueError('Serverrevisie gaat terug; pagina niet verwerkt')
            if META in payload:
                raise ValueError('Gereserveerd metadataveld in bronpayload')
            # Preserve arbitrary future dataset payloads, not just value/context.
            body = {k:v for k,v in payload.items() if k not in ('metric','period','currency','unit','basis')}
            content_hash = digest(body)
            if item.get('content_hash') and item.get('schema_version') == 1 and content_hash != item['content_hash']:
                raise ValueError('Inhoudshash klopt niet; pagina niet verwerkt')
            metadata = {k:v for k,v in item.items() if k != 'payload'}
            metadata['stream_id'] = page['stream_id']
            metadata['payload_headers'] = {k:payload[k] for k in
                ('metric','period','currency','unit','basis') if k in payload}
            body[META] = metadata
            revision = int(previous['revision'])+1 if previous else 1
            numeric = body.get('value')
            numeric = float(numeric) if isinstance(numeric,(int,float)) and not isinstance(numeric,bool) else None
            observed = _datetime(item.get('observed_at')) or now
            row = (key, item['source'], item['subject']['type'], item['subject']['id'], item['dataset'],
                metric, period_key, _datetime(period.get('end') or item.get('effective_at')),
                period.get('kind','unknown'), payload.get('currency',''), payload.get('unit',''),
                payload.get('basis','unknown'), numeric, encode(body), content_hash,
                _datetime(item.get('published_at')), previous['first_seen'] if previous else observed,
                observed, observed, revision)
            # Identical content already collected locally does not create a duplicate
            # history revision. Still attach provenance to the existing current row.
            changed = (not previous or previous['content_hash'] != content_hash or
                remote_old.get('operation', 'upsert') != item['operation'])
            if not changed:
                cur.execute('UPDATE financial_facts_current SET payload_json=?,last_seen=? WHERE fact_key=?',
                            row[13], observed, key)
            else:
                if previous:
                    cur.execute('UPDATE financial_facts_current SET '+','.join('['+c+']=?' for c in FACT_COLUMNS[1:])
                                +' WHERE fact_key=?', *(row[1:]+(key,)))
                else:
                    _insert_many(cur,'financial_facts_current',FACT_COLUMNS,[row])
                _insert_many(cur,'financial_facts_history',FACT_COLUMNS,[row])
        raw = encode(dict(stream_id=page['stream_id'],cursor=page['next_cursor'],manifest=manifest))
        fields = ('source','subject_key','group_name','symbol','status','last_attempt','last_success',
                  'next_due','failures','message','raw_json')
        values = ('Wyse','__market_exchange__','api_v1','','ok',now,now,now+timedelta(minutes=1),0,
                  'Marktgegevens en voortgang atomair opgeslagen in STOCKDATA',raw)
        if old['manifest_json'] is None:
            _insert_many(cur,'financial_fetch_state',('state_key',)+fields,[(STATE_KEY,)+values])
        else:
            cur.execute('UPDATE financial_fetch_state SET '+','.join('['+c+']=?' for c in fields)
                        +' WHERE state_key=?', *(values+(STATE_KEY,)))
    return len(items)


@stockdata_job
def records(path, dataset=None, subject_type=None, subject_id=None):
    with connect_stockdata(path) as conn:
        sql, args = 'SELECT * FROM financial_facts_current WHERE 1=1', []
        for column,value in (('category',dataset),('subject_type',subject_type),('subject_key',subject_id)):
            if value is not None:
                sql += ' AND ['+column+']=?'
                args.append(value)
        cur = conn.execute(sql, *args)
        columns = [c[0] for c in cur.description]
        result = []
        for values in cur.fetchall():
            row = dict(zip(columns,values)); body=json.loads(row['payload_json'])
            meta = body.pop(META, None)
            if not meta or meta.get('operation') == 'delete':
                continue
            item = dict(meta); item.pop('stream_id',None)
            headers = item.pop('payload_headers')
            item['payload'] = dict(headers, **body)
            result.append(item)
        return result


class StockdataInbox:
    """Connection-free facade; each DB-only job runs on the existing owner worker."""
    def __init__(self, path):
        self.path = path
        if not schema_ready(path):
            raise RuntimeError('Financiële tabellen ontbreken in STOCKDATA; geen automatische schemawijziging')

    def state(self):return state(self.path)
    def apply(self, page, manifest):return apply_page(self.path,page,manifest)
    def records(self, dataset=None, subject_type=None, subject_id=None):
        return records(self.path,dataset,subject_type,subject_id)
    def close(self):pass  # The shared STOCKDATA worker owns the physical connection.

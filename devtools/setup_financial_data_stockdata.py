"""Explicit STOCKDATA migration; never called by application startup."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portefeuille_viewer.data.shared_database import connect_stockdata
from portefeuille_viewer.data.financial_data_repository import SCHEMA_VERSION, schema_ready

FACT_DDL = '''fact_key TEXT(64) NOT NULL, source TEXT(32), subject_type TEXT(24),
subject_key TEXT(128), category TEXT(40), metric TEXT(80), period_key TEXT(160),
period_end DATETIME, period_kind TEXT(24), currency_code TEXT(16), unit_code TEXT(24),
basis TEXT(40), value_num DOUBLE, payload_json LONGTEXT, content_hash TEXT(64),
source_at DATETIME, first_seen DATETIME, last_seen DATETIME, changed_at DATETIME, revision LONG'''
DDL = {
    'financial_data_schema': 'schema_id LONG PRIMARY KEY, schema_version LONG, installed_at DATETIME',
    'financial_facts_current': FACT_DDL + ', CONSTRAINT pk_fin_facts PRIMARY KEY (fact_key)',
    'financial_facts_history': 'Id COUNTER PRIMARY KEY, ' + FACT_DDL,
    'financial_fetch_state': '''state_key TEXT(64) PRIMARY KEY, source TEXT(32), subject_key TEXT(128),
group_name TEXT(40), symbol TEXT(128), status TEXT(32), last_attempt DATETIME, last_success DATETIME,
next_due DATETIME, failures LONG, message LONGTEXT, raw_json LONGTEXT''',
}
INDEXES = {
    'financial_facts_current': [('idx_fin_subject', 'subject_key, category', False)],
    'financial_facts_history': [('uq_fin_revision', 'fact_key, revision', True),
                              ('idx_fin_hist_subject', 'subject_key, category, changed_at', False)],
    'financial_fetch_state': [('idx_fin_due', 'next_due', False)],
}


def migrate(path, apply=False):
    path = Path(path).resolve()
    if not path.is_file() or path.suffix.lower() != '.accdb':
        raise ValueError('Geef een bestaand STOCKDATA .accdb-bestand op')
    with connect_stockdata(path) as conn:
        cur = conn.cursor()
        tables = {str(r.table_name).lower() for r in cur.tables(tableType='TABLE')}
        if not {'asset_rollup_data', 'historical_data_correct'}.issubset(tables):
            raise ValueError('Dit bestand is geen STOCKDATA-database')
    report = dict(database=str(path), schema_version=SCHEMA_VERSION,
                  missing_tables=[name for name in DDL if name not in tables], apply=apply)
    if not apply:
        return report
    backup = path.with_name(path.stem + '.before-financial-data-' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + path.suffix)
    shutil.copy2(path, backup)
    report['backup'] = str(backup)
    with connect_stockdata(path) as conn:
        conn.begin_write()
        cur = conn.cursor()
        if 'financial_data_schema' in tables:
            version = cur.execute('SELECT schema_version FROM financial_data_schema WHERE schema_id=1').fetchone()
            if version and int(version[0]) != SCHEMA_VERSION:
                raise ValueError('Onbekende schema-versie; geen automatische downgrade/upgrade')
        for name, definition in DDL.items():
            if name not in tables:
                cur.execute(f'CREATE TABLE [{name}] ({definition})')
        for table, definitions in INDEXES.items():
            names = {str(r.index_name).lower() for r in cur.statistics(table=table) if r.index_name}
            for name, columns, unique in definitions:
                if name.lower() not in names:
                    cur.execute(f'CREATE {"UNIQUE " if unique else ""}INDEX {name} ON [{table}] ({columns})')
        # Validate every expected column before enabling the application collector.
        from portefeuille_viewer.data.financial_data_repository import FACT_COLUMNS
        for table in ('financial_facts_current', 'financial_facts_history'):
            columns = {str(r.column_name).lower() for r in cur.columns(table=table)}
            if not set(FACT_COLUMNS).issubset(columns):
                raise ValueError(f'Onvolledig/bestaand afwijkend schema: {table}')
        row = cur.execute('SELECT schema_version FROM financial_data_schema WHERE schema_id=1').fetchone()
        if not row:
            cur.execute('INSERT INTO financial_data_schema (schema_id,schema_version,installed_at) VALUES (1,?,?)',
                        SCHEMA_VERSION, datetime.utcnow())
    if not schema_ready(path):
        raise RuntimeError('Schema verificatie mislukt')
    report['verified'] = True
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Sluit alle viewers en Access voor --apply. Maakt eerst een backup.')
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='Zonder deze vlag alleen het plan tonen')
    args = parser.parse_args()
    print(json.dumps(migrate(args.db, args.apply), indent=2))

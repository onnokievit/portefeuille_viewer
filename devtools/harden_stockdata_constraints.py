"""Explicit offline STOCKDATA audit/migration. Default is read-only; never run by the app."""
import argparse
from collections import defaultdict
from datetime import datetime
import json
import hashlib
import os
from uuid import uuid4
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pyodbc
pyodbc.pooling = False  # CLI must release stage-file handles before promotion
from portefeuille_viewer.config.process_lock import ProcessLock, canonical_path

POLICIES = {
    'historical_data_correct': ('symbol', 'datum'),
    'asset_last_prices': ('ib_symbol', 'ib_currency'),
    'option_last_prices': ('series_id',),
    'option_series_master': ('asset_rollup', 'optie_call_put', 'strike', 'expiry', 'ib_currency'),
    'asset_rollup_data': ('asset_rollup',),
    'asset_dividend_calendar_current': ('asset_rollup',),
    'asset_dividend_calendar_history': ('asset_rollup', 'fetched_at'),
    'asset_driver_beta_snapshot': ('asset_rollup', 'driver_index', 'lookback_code', 'return_interval'),
    'single_asset_stepsize_settings': ('asset_rollup',),
}


def bracket(name):
    return '[' + name.replace(']', ']]') + ']'


def checksum(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def audit(connection):
    report = {}
    tables = {str(row.table_name).lower() for row in connection.cursor().tables(tableType='TABLE')}
    for table, keys in POLICIES.items():
        if table not in tables:
            report[table] = {'present': False}
            continue
        columns = [row.column_name for row in connection.cursor().columns(table=table)]
        missing = set(keys) - {str(col).lower() for col in columns}
        if missing:
            report[table] = {'present': True, 'error': 'Missing columns: ' + ', '.join(sorted(missing))}
            continue
        indexes = defaultdict(list)
        for row in connection.cursor().statistics(table=table, unique=True):
            if row.index_name and not row.non_unique and row.column_name:
                indexes[str(row.index_name)].append((int(row.ordinal_position), str(row.column_name).lower()))
        unique = {name: [col for _, col in sorted(items)] for name, items in indexes.items()}
        has_unique = any(set(cols) == set(keys) and len(cols) == len(keys) for cols in unique.values())
        fields = ','.join(map(bracket, keys))
        null_sql = ' OR '.join(bracket(key) + ' IS NULL' for key in keys)
        null_count = connection.cursor().execute(f'SELECT Count(*) FROM [{table}] WHERE {null_sql}').fetchone()[0]
        groups = connection.cursor().execute(f'SELECT {fields},Count(*) FROM [{table}] GROUP BY {fields} HAVING Count(*)>1').fetchall()
        duplicate_rows = []
        for group in groups:
            where = ' AND '.join(bracket(key) + (' IS NULL' if value is None else '=?') for key, value in zip(keys, group))
            parameters = tuple(value for value in group[:-1] if value is not None)
            cur = connection.cursor().execute(f'SELECT * FROM [{table}] WHERE {where}', parameters)
            names = [d[0] for d in cur.description]
            rows = [dict(zip(names, row)) for row in cur.fetchall()]
            compared = [tuple(row[name] for name in names if name.lower() not in {'id', 'series_id'}) for row in rows]
            identical = all(row == compared[0] for row in compared[1:])
            ids = [row[name] for row in rows for name in names if name.lower() == 'id']
            duplicate_rows.append({'key': list(group[:-1]), 'count': len(rows), 'identical': identical, 'ids': ids})
        if table == 'historical_data_correct' and groups:
            duplicate_ids = connection.cursor().execute('SELECT [Id],Count(*) FROM [historical_data_correct] GROUP BY [Id] HAVING Count(*)>1').fetchall()
            if duplicate_ids:
                report[table] = {'present': True, 'error': 'Technical Id is not unique; automatic cleanup refused'}
                continue
        report[table] = {'present': True, 'keys': keys, 'unique_indexes': unique,
            'protected': has_unique, 'null_key_rows': null_count, 'duplicates': duplicate_rows}
    return report


def apply_constraints(connection, report, deduplicate_identical=False):
    # Validate the entire plan before the first write. No arbitrary winner selection.
    for table, result in report.items():
        if not result['present']:
            continue
        if result.get('error') or result['null_key_rows']:
            raise RuntimeError(f'{table}: missing columns or NULL keys; resolve manually')
        for group in result['duplicates']:
            if not (table == 'historical_data_correct' and deduplicate_identical and group['identical'] and len(group['ids']) == group['count']):
                raise RuntimeError(f'{table}: duplicate key requires manual review')
    deleted = 0
    created = []
    for table, result in report.items():
        if not result['present']:
            continue
        for group in result['duplicates']:
            # Lowest technical Id survives; all actual fields were compared above.
            for row_id in sorted(group['ids'])[1:]:
                connection.cursor().execute(f'DELETE FROM [{table}] WHERE [Id]=?', row_id)
                deleted += 1
    connection.commit()  # Release Access DML locks before creating indexes.
    for table, result in report.items():
        if not result['present']:
            continue
        if not result['protected']:
            name = 'pv_uq_' + table
            fields = ','.join(map(bracket, result['keys']))
            connection.cursor().execute(f'CREATE UNIQUE INDEX [{name}] ON [{table}] ({fields}) WITH DISALLOW NULL')
            created.append(name)
    connection.commit()
    return {'deleted_identical_rows': deleted, 'created_indexes': created}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='Requires all app/Access connections closed')
    parser.add_argument('--deduplicate-identical', action='store_true')
    args = parser.parse_args()
    path = args.db.resolve(strict=True)
    if args.apply and any(part.lower() == 'portf_db_analyse' for part in path.parts):
        parser.error('The supplied analysis databases are strictly read-only')
    connection = None
    with ProcessLock('stock-writer:' + canonical_path(path)):
        backup = None
        stage = None
        if args.apply:
            # The app is closed during migration, enabling a byte-for-byte backup.
            if path.with_suffix('.laccdb').exists():
                raise RuntimeError('Sluit alle app- en Access-verbindingen; lockbestand aanwezig')
            backup = path.with_name(path.stem + '.backup-' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + path.suffix)
            original_hash = checksum(path)
            shutil.copy2(path, backup)
            if checksum(backup) != original_hash or checksum(path) != original_hash:
                raise RuntimeError('Database changed during backup; migration stopped')
            stage = path.with_name(path.stem + ".work-" + uuid4().hex + path.suffix)
            shutil.copy2(path, stage)
        try:
            mode = 'Exclusive=1;' if args.apply else ''
            connection = pyodbc.connect('DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=' + str(stage or path) + ';' + mode, readonly=not args.apply)
            before = audit(connection)
            connection.commit()  # Release audit read locks before stage DDL.
            output = {'database': str(path), 'backup': str(backup) if backup else None, 'audit': before}
            if args.apply:
                output['applied'] = apply_constraints(connection, before, args.deduplicate_identical)
                output['after'] = audit(connection)
                if any(row.get('present') and (not row.get('protected') or row.get('duplicates') or row.get('null_key_rows')) for row in output['after'].values()):
                    raise RuntimeError('Post-migration verification failed; original is unchanged')
                connection.close()
                connection = None
                if path.with_suffix('.laccdb').exists():
                    raise RuntimeError('Original database was opened during migration; original is unchanged')
                if checksum(path) != original_hash:
                    raise RuntimeError('Original database changed during migration; original is unchanged by this script')
                os.replace(stage, path)
                stage = None
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(output, indent=2, default=str), encoding='utf-8')
        except BaseException:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()
            if stage is not None:
                stage.unlink(missing_ok=True)
    print(args.report)


if __name__ == '__main__':
    main()

"""Read-only status, or an explicitly requested collection against --db."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portefeuille_viewer.data import financial_data_repository as repo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--max-seconds', type=int, default=180)
    parser.add_argument('--max-jobs', type=int, default=200)
    parser.add_argument('--asset', help='Toon huidige feiten voor deze asset')
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error('Database bestaat niet')
    if not repo.schema_ready(args.db):
        parser.error('Financiële opslag niet geïnstalleerd; gebruik het afzonderlijke setup-script')
    report = {}
    if args.collect:
        from dataclasses import asdict
        from portefeuille_viewer.services.financial_data_service import FinancialDataService
        report['collection'] = asdict(FinancialDataService(args.db,
            max_seconds=args.max_seconds, max_jobs=args.max_jobs).refresh())
    states = list(repo.fetch_states(args.db).values())
    report['coverage'] = dict(Counter(row['status'] for row in states))
    report['problems'] = [dict(asset=row['subject_key'], group=row['group_name'], status=row['status'],
        message=row['message'], last_attempt=row['last_attempt'], next_due=row['next_due'])
        for row in states if row['status'] not in {'ok', 'not_applicable'}]
    if args.asset:
        report['facts'] = repo.facts_for(args.db, args.asset)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()

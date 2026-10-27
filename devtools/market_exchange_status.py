"""Read STOCKDATA replication status; --sync stores facts and cursor in Access."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portefeuille_viewer.config.local_runtime import runtime_root, FileLease
from portefeuille_viewer.services.market_exchange import ExchangeHTTP, synchronize
from portefeuille_viewer.data.market_exchange_repository import StockdataInbox
from portefeuille_viewer.config import get_stockdata_db_path
from portefeuille_viewer.config.process_lock import canonical_path
from portefeuille_viewer.data.stockdata_worker import enable_stockdata_workers, shutdown_stockdata_workers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sync', action='store_true')
    parser.add_argument('--db', type=Path, help='Standaard: de ingestelde STOCKDATA')
    parser.add_argument('--pages', type=int, default=20, choices=range(1, 501), metavar='1..500')
    args = parser.parse_args()
    root = runtime_root() / 'market-exchange-v1'
    config = json.loads((root / 'connection.json').read_text(encoding='utf-8-sig'))
    client = ExchangeHTTP(config['server_url'], config['api_token'])
    path = args.db or get_stockdata_db_path()
    enable_stockdata_workers()
    try:
        with FileLease('market-exchange-stockdata-v1:' + canonical_path(path)):
            inbox = StockdataInbox(path)
            try:
                if args.sync:
                    print(json.dumps(synchronize(client, inbox, max_pages=args.pages)))
                state = inbox.state()
                manifest = json.loads(state.pop('manifest_json') or '{}')
                state['datasets'] = len(manifest.get('datasets', []))
                state['database'] = str(path)
                print(json.dumps(state, indent=2))
            finally:
                inbox.close()
    finally:
        shutdown_stockdata_workers()


if __name__ == '__main__':
    main()

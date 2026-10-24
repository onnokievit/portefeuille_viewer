"""Shared, reproducible historical indicator results; never contains user options."""
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import polars as pl

from portefeuille_viewer.config.local_runtime import runtime_root, resource_id
from portefeuille_viewer.config.process_lock import ProcessLock, canonical_path

SCHEMA_VERSION = 1


def rules_fingerprint():
    digest = hashlib.sha256(pl.__version__.encode())
    for name in ('shared_asset_history.py', 'asset_indicator_service.py',
                 'asset_indicator_rules.py', 'asset_indicator_contract.py'):
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()


def history_fingerprint(history, assets, rules):
    digest = hashlib.sha256(json.dumps(dict(assets=sorted(assets), rules=rules,
        schema=[(name, str(dtype)) for name, dtype in history.schema.items()]), sort_keys=True).encode())
    digest.update(history.hash_rows(seed=1729).to_numpy().tobytes())
    return digest.hexdigest()


class SharedAssetHistory:
    def __init__(self, stock_path, directory=None):
        identity = resource_id(canonical_path(stock_path))
        self.directory = Path(directory) if directory is not None else runtime_root() / 'asset_indicator_history' / identity
        self.path = self.directory / 'current.json'
        self.lock = ProcessLock('historical-asset-indicators:' + canonical_path(self.path))

    def get(self, history, assets, build, *, rules=None):
        """Only the lock owner computes a missing generation; other viewers read it."""
        key = history_fingerprint(history, assets, rules or rules_fingerprint())
        self.generation_key = key
        if not self.lock.acquire(120000):
            raise TimeoutError('Gedeelde asset-indicatorberekening duurt te lang; probeer opnieuw')
        try:
            try:
                cached = json.loads(self.path.read_text(encoding='utf-8'))
                rows = cached['rows']
                checksum = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
                if (cached['schema'] == SCHEMA_VERSION and cached['key'] == key
                        and cached['checksum'] == checksum and set(rows) == set(assets)):
                    print('[asset-indicator-history] cache hit')
                    return rows
            except (OSError, ValueError, KeyError, TypeError):
                pass
            rows = build()
            if set(rows) != set(assets):
                raise ValueError('Incomplete historical indicator result')
            # Round-trip through the exact JSON representation used by readers.
            # Dates are encoded by the calculation helper as ISO dates.
            rows = json.loads(json.dumps(rows))
            payload = dict(schema=SCHEMA_VERSION, key=key, rows=rows,
                checksum=hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest())
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp-' + uuid4().hex)
            try:
                with temporary.open('w', encoding='utf-8') as stream:
                    json.dump(payload, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            print('[asset-indicator-history] cache rebuilt')
            return rows
        finally:
            self.lock.release()

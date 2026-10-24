"""Choose and lock a portfolio before importing repositories or starting workers."""
import argparse
import atexit
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from . import settings_manager as sm
from .process_lock import ProcessLock, canonical_path
from .profile_storage import USER_DATA_ROOT, computer_id, patch_config, profile_slug, read_config

_session = None


class ProfileAlreadyOpen(RuntimeError):
    pass


@dataclass
class ProfileSession:
    database_name: str
    database_path: str
    profile: str
    lock: ProcessLock
    runtime_dir: Path

    def close(self):
        self.lock.release()


def get_profile_session():
    return _session


def resolve_database(alias, databases):
    normalize = lambda s: ''.join(c for c in str(s).lower() if c.isalnum())
    exact = [n for n in databases if normalize(n) == normalize(alias)]
    matches = exact or [n for n in databases if normalize(profile_slug(n)) == normalize(alias)]
    if len(matches) != 1:
        raise ValueError(f"Onbekend of niet-uniek profiel '{alias}'. Beschikbaar: {', '.join(databases)}")
    return matches[0]


def prepare_profile_session(argv, *, data_root=None, machine_id=None):
    global _session
    if _session is not None:
        return _session
    parser = argparse.ArgumentParser(description='Portefeuille Viewer')
    parser.add_argument('--db', '--database', '--profile', dest='database_alias', default='',
                        help='Profiel/database uit de catalogus, bijvoorbeeld onno, muriel of quinten')
    args, _ = parser.parse_known_args(argv[1:])
    root = Path(data_root or USER_DATA_ROOT)
    machine = machine_id or computer_id()
    shared = root / 'gedeeld/settings_shared.ini'
    cfg = read_config([shared if shared.exists() else sm.SHARED_CONFIG_PATH])
    catalog = sm.SettingsManager.__new__(sm.SettingsManager)
    catalog.config = cfg
    databases = catalog.get_databases()
    if not databases:
        raise ValueError('Geen userdatabases ingesteld')
    recent_path = root / 'computers' / machine / 'startup.ini'
    recent = read_config([recent_path]).get('app', 'last_database', fallback='')
    alias = args.database_alias or (recent if recent in databases else catalog.get_default_database())
    name = resolve_database(alias, databases)
    profile = profile_slug(name)
    if any(n != name and profile_slug(n) == profile for n in databases):
        raise ValueError('Meerdere database-aliassen leiden tot dezelfde profielmap: ' + profile)
    path = canonical_path(databases[name]['path'])
    if not Path(path).is_file():
        raise ValueError('Userdatabase niet gevonden: ' + path)
    lock = ProcessLock('database:' + path)
    if not lock.acquire():
        raise ProfileAlreadyOpen(f"Profiel '{name}' is al geopend op deze computer. Gebruik het bestaande venster.")
    old_settings = sm._settings_manager
    try:
        settings = sm.SettingsManager(profile=profile, database_name=name, data_root=root, machine_id=machine)
        sm._settings_manager = settings
        settings.set_last_database(name)
        patch_config(recent_path, {('app', 'last_database'): name})
        runtime = root / 'runtime' / machine / (profile + '-' + str(os.getpid()) + '-' + uuid4().hex[:8])
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / 'session.json').write_text(json.dumps({'profile':profile,'database':path,'pid':os.getpid()},indent=2),encoding='utf-8')
        os.environ["PV_CONFIG_FILES"] = json.dumps([str(p) for p in settings._profile_storage.paths])
        os.environ["PV_PROFILE_DATABASE"] = name
        os.environ["PV_STOCKDATA_DATABASE"] = settings.get_stockdata_db_path()
        os.environ["PV_INSTANCE_RUNTIME"] = str(runtime)
        _session = ProfileSession(name, path, profile, lock, runtime)
        atexit.register(_session.close)
        return _session
    except BaseException:
        sm._settings_manager = old_settings
        lock.release()
        raise


def start_profile_session(argv):
    try:
        return prepare_profile_session(argv)
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'Portefeuille Viewer — profiel', 0x10)
        raise SystemExit(2) from exc

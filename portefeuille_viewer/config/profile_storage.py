"""Version-bound shared, portfolio and computer-specific INI storage."""
import configparser
import hashlib
import os
from pathlib import Path
import re
import socket
import tempfile

from .process_lock import ProcessLock, canonical_path

USER_DATA_ROOT = Path(__file__).resolve().parents[2] / 'gebruikersdata'
SHARED_SECTIONS = {'databases', 'stockdata', 'brokers', 'comment_colors', 'env_defaults', 'market_data'}


def profile_slug(name):
    name = re.sub(r'[-_ ]+(productie|production)$', '', str(name).lower())
    slug = re.sub(r'[^a-z0-9_-]+', '-', name).strip('-_')
    if not slug:
        raise ValueError('Profielnaam bevat geen geldige tekens')
    return slug


def computer_id():
    machine = socket.gethostname()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            machine += str(winreg.QueryValueEx(key, 'MachineGuid')[0])
    except OSError:
        pass
    return profile_slug(socket.gethostname()) + '-' + hashlib.sha256(machine.encode()).hexdigest()[:8]


def read_config(paths):
    cfg = configparser.ConfigParser()
    if isinstance(paths, (str, Path)):
        paths = [paths]
    for path in paths:
        # Avoid a Windows reader keeping an INI open during another process's replace.
        with ProcessLock('settings:' + canonical_path(path)):
            cfg.read([path], encoding='utf-8')
    return cfg


def config_values(cfg):
    return {(s, k): v for s in cfg.sections() for k, v in cfg.items(s)}


def put(cfg, section, key, value):
    if value is None:
        cfg.remove_option(section, key)
    else:
        if not cfg.has_section(section):
            cfg.add_section(section)
        cfg.set(section, key, value)


def atomic_write(cfg, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.ini.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            cfg.write(f)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def patch_config(path, changes):
    """Merge only changed keys under a cross-process lock; preserve others' edits."""
    with ProcessLock('settings:' + canonical_path(path)):
        cfg = read_config([path])
        for (section, key), value in changes.items():
            put(cfg, section, key, value)
        atomic_write(cfg, path)


class ProfileStorage:
    def __init__(self, profile, legacy_shared, legacy_local, root=None, machine_id=None):
        self.root = Path(root or USER_DATA_ROOT)
        self.profile = profile_slug(profile)
        self.machine_id = machine_id or computer_id()
        self.shared = self.root / 'gedeeld/settings_shared.ini'
        self.preferences = self.root / 'profielen' / self.profile / 'settings.ini'
        self.computer = self.root / 'computers' / self.machine_id / self.profile / 'settings_local.ini'
        self.paths = [self.shared, self.preferences, self.computer]
        self.legacy_paths = [legacy_shared, legacy_local]

    def target(self, section, key):
        if section in SHARED_SECTIONS:
            return self.shared
        if (section == 'interactive_brokers' or
            (section == 'app' and key == 'last_database') or
            (section == 'ui' and (key.endswith('_geometry') or key.endswith('_col_widths') or
                                  key in {'font_size', 'cash_dashboard_chart_height_px'})) or
            (section == 'option_chain_scanner' and key in {
                'parquet_dir', 'host', 'port', 'tws_host', 'tws_port',
                'client_id_base', 'client_id_min', 'client_id_max'})):
            return self.computer
        return self.preferences

    def load(self):
        # One-time copy only: never rewrite the old INIs, or seed files that exist.
        with ProcessLock('profile-setup:' + canonical_path(self.root)):
            missing = [p for p in self.paths if not p.exists()]
            if missing:
                legacy = read_config(self.legacy_paths)
                parts = {p: configparser.ConfigParser() for p in missing}
                for (s, k), value in config_values(legacy).items():
                    target = self.target(s, k)
                    if target in parts:
                        put(parts[target], s, k, value)
                for path, cfg in parts.items():
                    atomic_write(cfg, path)
        # Earlier profile files may still contain this formerly private section.
        # Shared scheduler settings always win, without deleting personal files.
        cfg = read_config(self.paths)
        shared = read_config(self.shared)
        if shared.has_section('market_data'):
            cfg.remove_section('market_data')
            cfg.add_section('market_data')
            for key, value in shared.items('market_data'):
                cfg.set('market_data', key, value)
        return cfg

    def save_changes(self, cfg, baseline):
        current = config_values(cfg)
        changes = {}
        for pair in current.keys() | baseline.keys():
            if current.get(pair) != baseline.get(pair):
                changes.setdefault(self.target(*pair), {})[pair] = current.get(pair)
        for path, patch in changes.items():
            patch_config(path, patch)

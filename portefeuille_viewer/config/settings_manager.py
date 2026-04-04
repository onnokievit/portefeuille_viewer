# portefeuille_viewer/config/settings_manager.py
"""
Centraal beheer voor applicatie settings via een gedeelde en lokale ini.
"""
import configparser
import json
from pathlib import Path
from typing import Dict, Optional

# Nieuwe configuratiebestanden
SHARED_CONFIG_PATH = Path(__file__).parent / "settings_shared.ini"
LOCAL_CONFIG_DIR = Path(__file__).parent / ".user_settings"
LOCAL_CONFIG_PATH = LOCAL_CONFIG_DIR / "settings_local.ini"

# Legacy paden voor eenmalige migratie
LEGACY_SHARED_CONFIG_PATH = Path(__file__).parent / "settings.ini"
LEGACY_LOCAL_CONFIG_PATH = LOCAL_CONFIG_DIR / "settings.ini"

DEFAULT_COMMENT_COLORS = [
    (4, "Rood", "#f8d7da", "#000000"),
    (3, "Oranje", "#ffeeba", "#000000"),
    (2, "Groen", "#d4edda", "#000000"),
    (1, "Grijs", "#bfbfbf", "#ffffff"),
    (0, "Geen", "", ""),
]

LOCAL_ONLY_KEYS = {
    "interactive_brokers": None,
    "ui": {
        "theme",
        "font_size",
        "table_header_bg",
        "table_total_bg",
        "tab_inactive_bg",
        "tab_active_bg",
        "tab_hover_bg",
        "aandelen_web_col_widths",
    },
    "app": {"last_database"},
}


class SettingsManager:
    # === EURUSD Setting ===
    def get_eurusd(self) -> float:
        return self.config.getfloat('app', 'eurusd', fallback=1.0)

    def set_eurusd(self, value: float):
        if not self.config.has_section('app'):
            self.config.add_section('app')
        self.config.set('app', 'eurusd', str(value))
        self.save()
    """Centraal beheer voor alle applicatie settings."""
    
    def __init__(self):
        self.config = configparser.ConfigParser()
        self._load_config()
    
    def _load_config(self):
        """Laad config uit settings_shared.ini en settings_local.ini."""
        LOCAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_configs_if_needed()
        self._reload_from_disk()
        print(f"Config geladen: shared={SHARED_CONFIG_PATH}, local={LOCAL_CONFIG_PATH}")

    def _reload_from_disk(self):
        self.config = configparser.ConfigParser()
        if SHARED_CONFIG_PATH.exists():
            self.config.read(SHARED_CONFIG_PATH, encoding='utf-8')
        if LOCAL_CONFIG_PATH.exists():
            self.config.read(LOCAL_CONFIG_PATH, encoding='utf-8')

    def _migrate_legacy_configs_if_needed(self):
        if SHARED_CONFIG_PATH.exists() and LOCAL_CONFIG_PATH.exists():
            return

        merged = configparser.ConfigParser()
        legacy_present = False
        if SHARED_CONFIG_PATH.exists():
            merged.read(SHARED_CONFIG_PATH, encoding='utf-8')
        elif LEGACY_SHARED_CONFIG_PATH.exists():
            merged.read(LEGACY_SHARED_CONFIG_PATH, encoding='utf-8')
            legacy_present = True

        if LOCAL_CONFIG_PATH.exists():
            merged.read(LOCAL_CONFIG_PATH, encoding='utf-8')
        elif LEGACY_LOCAL_CONFIG_PATH.exists():
            merged.read(LEGACY_LOCAL_CONFIG_PATH, encoding='utf-8')
            legacy_present = True

        shared_cfg, local_cfg = self._split_config(merged)
        if legacy_present or not SHARED_CONFIG_PATH.exists():
            self._write_config(shared_cfg, SHARED_CONFIG_PATH)
        if legacy_present or not LOCAL_CONFIG_PATH.exists():
            self._write_config(local_cfg, LOCAL_CONFIG_PATH)

    def _is_local_key(self, section: str, key: str) -> bool:
        rule = LOCAL_ONLY_KEYS.get(section)
        if rule is None and section in LOCAL_ONLY_KEYS:
            return True
        if isinstance(rule, set):
            return key in rule
        return False

    def _split_config(self, source: configparser.ConfigParser) -> tuple[configparser.ConfigParser, configparser.ConfigParser]:
        shared_cfg = configparser.ConfigParser()
        local_cfg = configparser.ConfigParser()
        for section in source.sections():
            for key, value in source.items(section):
                target = local_cfg if self._is_local_key(section, key) else shared_cfg
                if not target.has_section(section):
                    target.add_section(section)
                target.set(section, key, value)
        return shared_cfg, local_cfg

    def _write_config(self, cfg: configparser.ConfigParser, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            cfg.write(f)
    
    def save(self):
        """Sla huidige config gesplitst op naar shared en local."""
        shared_cfg, local_cfg = self._split_config(self.config)
        self._write_config(shared_cfg, SHARED_CONFIG_PATH)
        self._write_config(local_cfg, LOCAL_CONFIG_PATH)
        print(f"Config opgeslagen: shared={SHARED_CONFIG_PATH}, local={LOCAL_CONFIG_PATH}")
    
    # === Interactive Brokers ===
    def get_ib_host(self) -> str:
        return self.config.get('interactive_brokers', 'host', fallback='127.0.0.1')
    
    def get_ib_port(self) -> int:
        return self.config.getint('interactive_brokers', 'port', fallback=7496)
    
    def get_ib_client_id(self) -> int:
        return self.config.getint('interactive_brokers', 'client_id', fallback=299)
    
    def set_ib_settings(self, host: str, port: int, client_id: int):
        if not self.config.has_section('interactive_brokers'):
            self.config.add_section('interactive_brokers')
        self.config.set('interactive_brokers', 'host', host)
        self.config.set('interactive_brokers', 'port', str(port))
        self.config.set('interactive_brokers', 'client_id', str(client_id))
        self.save()
    
    # === Databases ===
    def get_databases(self) -> Dict[str, Dict[str, str]]:
        """Haal alle databases op als dictionary."""
        databases = {}
        if not self.config.has_section('databases'):
            return databases
        
        for name, value in self.config.items('databases'):
            # Parse: path | fg_color | bg_color | is_default
            parts = [p.strip() for p in value.split('|')]
            if len(parts) >= 3:
                databases[name] = {
                    'path': parts[0],
                    'fg_color': parts[1],
                    'bg_color': parts[2],
                    'is_default': parts[3].lower() == 'true' if len(parts) > 3 else False
                }
        return databases
    
    def get_default_database(self) -> Optional[str]:
        """Haal naam van default database op."""
        databases = self.get_databases()
        # Zoek database met is_default=true
        for name, config in databases.items():
            if config.get('is_default', False):
                return name
        # Fallback: eerste database
        return next(iter(databases.keys()), None)
    
    def add_database(self, name: str, path: str, fg_color: str = 'black', 
        bg_color: str = 'white', is_default: bool = False):
        """Voeg nieuwe database toe."""
        if not self.config.has_section('databases'):
            self.config.add_section('databases')
        
        # Als dit de default wordt, zet alle anderen op false
        if is_default:
            self._clear_default_flags()
        
        value = f"{path} | {fg_color} | {bg_color} | {str(is_default).lower()}"
        self.config.set('databases', name, value)
        self.save()
    
    def remove_database(self, name: str):
        """Verwijder database."""
        if self.config.has_section('databases') and self.config.has_option('databases', name):
            self.config.remove_option('databases', name)
            self.save()
    
    def update_database(self, name: str, path: str = None, fg_color: str = None, 
        bg_color: str = None, is_default: bool = None):
        """Update database configuratie."""
        databases = self.get_databases()
        if name not in databases:
            return
        
        current = databases[name]
        new_path = path if path is not None else current['path']
        new_fg = fg_color if fg_color is not None else current['fg_color']
        new_bg = bg_color if bg_color is not None else current['bg_color']
        new_default = is_default if is_default is not None else current.get('is_default', False)
        
        # Als dit de nieuwe default wordt, clear andere flags
        if new_default and not current.get('is_default', False):
            self._clear_default_flags()
        
        value = f"{new_path} | {new_fg} | {new_bg} | {str(new_default).lower()}"
        self.config.set('databases', name, value)
        self.save()
    
    def set_default_database(self, name: str):
        """Stel database in als default."""
        databases = self.get_databases()
        if name not in databases:
            return
        
        self._clear_default_flags()
        current = databases[name]
        value = f"{current['path']} | {current['fg_color']} | {current['bg_color']} | true"
        self.config.set('databases', name, value)
        self.save()
    
    def _clear_default_flags(self):
        """Zet alle is_default flags naar false."""
        databases = self.get_databases()
        for name, db in databases.items():
            if db.get('is_default', False):
                value = f"{db['path']} | {db['fg_color']} | {db['bg_color']} | false"
                self.config.set('databases', name, value)
    
    # === UI Settings ===
    def get_theme(self) -> str:
        return self.config.get('ui', 'theme', fallback='light')
    
    def set_theme(self, theme: str):
        if not self.config.has_section('ui'):
            self.config.add_section('ui')
        self.config.set('ui', 'theme', theme)
        self.save()

    def get_table_header_bg(self) -> str:
        return self.config.get('ui', 'table_header_bg', fallback='#c6c6c6')

    def set_table_header_bg(self, color: str):
        if not self.config.has_section('ui'):
            self.config.add_section('ui')
        self.config.set('ui', 'table_header_bg', color)
        self.save()

    def get_table_total_bg(self) -> str:
        return self.config.get('ui', 'table_total_bg', fallback='#c6c6c6')

    def set_table_total_bg(self, color: str):
        if not self.config.has_section('ui'):
            self.config.add_section('ui')
        self.config.set('ui', 'table_total_bg', color)
        self.save()

    def get_tab_inactive_bg(self) -> str:
        return self.config.get('ui', 'tab_inactive_bg', fallback='#d9d9d9')

    def set_tab_inactive_bg(self, color: str):
        if not self.config.has_section('ui'):
            self.config.add_section('ui')
        self.config.set('ui', 'tab_inactive_bg', color)
        self.save()

    def get_tab_active_bg(self) -> str:
        return self.config.get('ui', 'tab_active_bg', fallback='#7a7a7a')

    def set_tab_active_bg(self, color: str):
        if not self.config.has_section('ui'):
            self.config.add_section('ui')
        self.config.set('ui', 'tab_active_bg', color)
        self.save()

    def get_tab_hover_bg(self) -> str:
        return self.config.get('ui', 'tab_hover_bg', fallback='#f3eed7')

    def set_tab_hover_bg(self, color: str):
        if not self.config.has_section('ui'):
            self.config.add_section('ui')
        self.config.set('ui', 'tab_hover_bg', color)
        self.save()

    def get_aandelen_web_col_widths(self) -> Dict[str, int]:
        raw = self.config.get('ui', 'aandelen_web_col_widths', fallback='{}')
        try:
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                return {}
            out: Dict[str, int] = {}
            for k, v in obj.items():
                key = str(k).strip()
                if not key:
                    continue
                try:
                    iv = int(v)
                except Exception:
                    continue
                if iv > 0:
                    out[key] = iv
            return out
        except Exception:
            return {}

    def set_aandelen_web_col_widths(self, widths: Dict[str, int]):
        if not self.config.has_section('ui'):
            self.config.add_section('ui')
        clean: Dict[str, int] = {}
        for k, v in (widths or {}).items():
            key = str(k).strip()
            if not key:
                continue
            try:
                iv = int(v)
            except Exception:
                continue
            if iv > 0:
                clean[key] = iv
        self.config.set('ui', 'aandelen_web_col_widths', json.dumps(clean, ensure_ascii=False))
        self.save()

    def get_tab_order(self) -> list[str]:
        raw = self.config.get('ui', 'tab_order', fallback='[]')
        try:
            items = json.loads(raw)
        except Exception:
            return []
        if not isinstance(items, list):
            return []
        out: list[str] = []
        for item in items:
            text = str(item).strip()
            if text:
                out.append(text)
        return out

    def set_tab_order(self, tab_ids: list[str]):
        if not self.config.has_section('ui'):
            self.config.add_section('ui')
        clean: list[str] = []
        seen: set[str] = set()
        for item in (tab_ids or []):
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            clean.append(text)
        self.config.set('ui', 'tab_order', json.dumps(clean, ensure_ascii=False))
        self.save()

    
    # === App Settings ===
    def get_last_database(self) -> Optional[str]:
        return self.config.get('app', 'last_database', fallback=None)
    
    def set_last_database(self, name: str):
        if not self.config.has_section('app'):
            self.config.add_section('app')
        self.config.set('app', 'last_database', name)
        self.save()

    # === Brokers ===
    def get_brokers(self):
        """Haal brokerlijst op uit settings.ini (comma-separated)."""
        raw = self.config.get('brokers', 'list', fallback='')
        return [b.strip() for b in raw.split(',') if b.strip()]

    # === Comment colors ===
    def get_comment_colors(self):
        """
        Retourneer lijst van (priority, label, bg_hex, fg_hex) voor comment-kleuren.
        Priority bepaalt ook sorteer-volgorde; hoogste eerst.
        """
        colors = []
        if self.config.has_section("comment_colors"):
            for key, value in self.config.items("comment_colors"):
                try:
                    prio = int(key.strip())
                except Exception:
                    prio = 0
                parts = [p.strip() for p in value.split(",")]
                label = parts[0] if parts else ""
                bg_hex = parts[1] if len(parts) > 1 else ""
                fg_hex = parts[2] if len(parts) > 2 else ""
                if bg_hex and not fg_hex:
                    fg_hex = "#000000"
                colors.append((prio, label, bg_hex, fg_hex))
        if not colors:
            colors = list(DEFAULT_COMMENT_COLORS)
        # Sorteer op priority, hoog naar laag
        return sorted(colors, key=lambda x: x[0], reverse=True)

    def get_comment_color_priority_map(self):
        """Map hex -> priority (int)."""
        return {bg_hex: prio for prio, _label, bg_hex, _fg_hex in self.get_comment_colors()}

    def get_comment_color_text_map(self):
        """Map achtergrondkleur hex -> tekstkleur hex."""
        return {bg_hex: fg_hex for _prio, _label, bg_hex, fg_hex in self.get_comment_colors() if bg_hex}

    def set_comment_colors(self, colors):
        """
        Sla comment-kleuren op naar user settings.

        `colors` mag zijn:
        - list[(label, hex)]
        - list[(label, bg_hex, fg_hex)]
        - list[(priority, label, bg_hex, fg_hex)]

        Keys in ini zijn numeric priority's.
        """
        if not self.config.has_section("comment_colors"):
            self.config.add_section("comment_colors")
        else:
            # wis bestaande opties
            for k, _v in list(self.config.items("comment_colors")):
                self.config.remove_option("comment_colors", k)

        normalized = []
        for item in (colors or []):
            if not item:
                continue
            if len(item) == 2:
                label, bg_hex = item
                fg_hex = "#000000" if bg_hex else ""
                normalized.append((None, str(label), str(bg_hex), str(fg_hex)))
            elif len(item) == 3:
                # Ambigue: (prio,label,bg) of (label,bg,fg)
                prio = None
                try:
                    prio = int(item[0])
                except Exception:
                    prio = None
                if prio is not None:
                    label, bg_hex = item[1], item[2]
                    fg_hex = "#000000" if bg_hex else ""
                    normalized.append((prio, str(label), str(bg_hex), str(fg_hex)))
                else:
                    label, bg_hex, fg_hex = item
                    fg_hex = fg_hex or ("#000000" if bg_hex else "")
                    normalized.append((None, str(label), str(bg_hex), str(fg_hex)))
            elif len(item) >= 4:
                prio, label, bg_hex, fg_hex = item[0], item[1], item[2], item[3]
                try:
                    prio = int(prio)
                except Exception:
                    prio = None
                fg_hex = fg_hex or ("#000000" if bg_hex else "")
                normalized.append((prio, str(label), str(bg_hex), str(fg_hex)))

        # Als prio ontbreekt: toekennen op basis van volgorde (hoog->laag)
        if any(p is None for p, _l, _b, _f in normalized):
            n = len(normalized)
            normalized = [(n - 1 - i, l, b, f) for i, (_p, l, b, f) in enumerate(normalized)]

        # schrijf weg (hoog->laag)
        for prio, label, bg_hex, fg_hex in sorted(normalized, key=lambda x: x[0], reverse=True):
            self.config.set("comment_colors", str(prio), f"{label},{bg_hex},{fg_hex}")

        self.save()


# Singleton instance
_settings_manager = None


def get_settings() -> SettingsManager:
    """Haal singleton settings manager op."""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager


# Convenience functies voor backward compatibility
def get_databases() -> Dict[str, Dict[str, str]]:
    return get_settings().get_databases()


def get_default_database() -> Optional[str]:
    return get_settings().get_default_database()


def add_database(name: str, path: str, fg_color: str = 'black', bg_color: str = 'white'):
    get_settings().add_database(name, path, fg_color, bg_color)


def remove_database(name: str):
    get_settings().remove_database(name)


def update_database(name: str, path: str = None, fg_color: str = None, bg_color: str = None):
    get_settings().update_database(name, path, fg_color, bg_color)


def set_default_database(name: str):
    get_settings().set_default_database(name)

# portefeuille_viewer/config/settings_manager.py
"""
Centraal beheer voor alle applicatie settings via settings.ini.
"""
import configparser
from pathlib import Path
from typing import Dict, Optional

# Pad naar default config (in package)
DEFAULT_CONFIG_PATH = Path(__file__).parent / "settings.ini"

# Pad naar user config (in home directory)
USER_CONFIG_DIR = Path(__file__).parent / ".user_settings"
USER_CONFIG_PATH = USER_CONFIG_DIR / "settings.ini"

DEFAULT_COMMENT_COLORS = [
    (4, "Rood", "#f8d7da"),
    (3, "Oranje", "#ffeeba"),
    (2, "Groen", "#d4edda"),
    (1, "Grijs", "#bfbfbf"),
    (0, "Geen", ""),
]


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
        """Laad config: eerst default, dan user overwrites."""
        # Laad default config uit package
        if DEFAULT_CONFIG_PATH.exists():
            self.config.read(DEFAULT_CONFIG_PATH, encoding='utf-8')
            print(f"Default config geladen: {DEFAULT_CONFIG_PATH}")
        
        # User config overschrijft defaults (als deze bestaat)
        if USER_CONFIG_PATH.exists():
            self.config.read(USER_CONFIG_PATH, encoding='utf-8')
            print(f"User config geladen: {USER_CONFIG_PATH}")
    
    def save(self):
        """Sla huidige config op naar user directory."""
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(USER_CONFIG_PATH, 'w', encoding='utf-8') as f:
            self.config.write(f)
        print(f"Config opgeslagen: {USER_CONFIG_PATH}")
    
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
    
    # === App Settings ===
    def get_last_database(self) -> Optional[str]:
        return self.config.get('app', 'last_database', fallback=None)
    
    def set_last_database(self, name: str):
        if not self.config.has_section('app'):
            self.config.add_section('app')
        self.config.set('app', 'last_database', name)
        self.save()

    # === Comment colors ===
    def get_comment_colors(self):
        """
        Retourneer lijst van (priority, label, hex) voor comment-kleuren.
        Priority bepaalt ook sorteer-volgorde; hoogste eerst.
        """
        colors = []
        if self.config.has_section("comment_colors"):
            for key, value in self.config.items("comment_colors"):
                try:
                    prio = int(key.strip())
                except Exception:
                    prio = 0
                parts = [p.strip() for p in value.split(",", 1)]
                label = parts[0] if parts else ""
                hexval = parts[1] if len(parts) > 1 else ""
                colors.append((prio, label, hexval))
        if not colors:
            colors = list(DEFAULT_COMMENT_COLORS)
        # Sorteer op priority, hoog naar laag
        return sorted(colors, key=lambda x: x[0], reverse=True)

    def get_comment_color_priority_map(self):
        """Map hex -> priority (int)."""
        return {hexval: prio for prio, _label, hexval in self.get_comment_colors()}

    def set_comment_colors(self, colors):
        """
        Sla comment-kleuren op naar user settings.

        `colors` mag zijn:
        - list[(label, hex)]
        - list[(priority, label, hex)]

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
                label, hexval = item
                normalized.append((None, str(label), str(hexval)))
            elif len(item) >= 3:
                prio, label, hexval = item[0], item[1], item[2]
                try:
                    prio = int(prio)
                except Exception:
                    prio = None
                normalized.append((prio, str(label), str(hexval)))

        # Als prio ontbreekt: toekennen op basis van volgorde (hoog->laag)
        if any(p is None for p, _l, _h in normalized):
            n = len(normalized)
            normalized = [(n - 1 - i, l, h) for i, (_p, l, h) in enumerate(normalized)]

        # schrijf weg (hoog->laag)
        for prio, label, hexval in sorted(normalized, key=lambda x: x[0], reverse=True):
            self.config.set("comment_colors", str(prio), f"{label},{hexval}")

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

# portefeuille_viewer/config/__init__.py
"""
Configuration module voor Portefeuille Viewer.
Centraliseert alle applicatie settings in settings.ini
"""

from .settings_manager import (
    get_settings,
    get_databases,
    get_default_database,
    get_stockdata_db_path,
    add_database,
    remove_database,
    update_database,
    set_default_database,
    SettingsManager
)

__all__ = [
    'get_settings',
    'get_databases',
    'get_default_database',
    'get_stockdata_db_path',
    'add_database',
    'remove_database',
    'update_database',
    'set_default_database',
    'SettingsManager'
]

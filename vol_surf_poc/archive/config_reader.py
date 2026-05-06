"""Reads DB paths and IB settings from the main app's settings INI files."""
import configparser
from pathlib import Path

_BASE = Path(__file__).parent.parent / "portefeuille_viewer" / "config"
_SHARED = _BASE / "settings_shared.ini"
_LOCAL  = _BASE / ".user_settings" / "settings_local.ini"

_FALLBACK_STOCK_DB = (
    r"C:\Users\onno\OneDrive\Beleggen"
    r"\2025 - portefeuille database 02.03 - STOCKDATA.accdb"
)


def _cfg() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read([str(_SHARED), str(_LOCAL)], encoding="utf-8")
    return cfg


def get_stock_db_path() -> str:
    return _cfg().get("stockdata", "db_path", fallback=_FALLBACK_STOCK_DB)


def get_ib_port() -> int:
    """IB Gateway port. Override in settings_local.ini: [volsurf] ib_port = 7498"""
    return int(_cfg().get("volsurf", "ib_port", fallback="7496"))

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


DEFAULT_STOCKDATA_DB = (
    r"C:\Users\onno\OneDrive\Beleggen"
    r"\2025 - portefeuille database 02.03 - STOCKDATA.accdb"
)


@dataclass(frozen=True)
class AppSettings:
    stockdata_db_path: str
    ib_host: str
    ib_port: int
    ib_client_id: int
    shared_settings_path: Path
    local_settings_path: Path


def find_pv14_config_dir(start: Path | None = None) -> Path:
    """Find portefeuille viewer 1.4 config from either repo-root or in-project PoC location."""
    anchor = (start or Path(__file__).resolve()).resolve()
    candidates: list[Path] = []
    for parent in [anchor.parent, *anchor.parents]:
        candidates.extend(
            [
                parent / "portefeuille_viewer" / "config",
                parent / "portefeuille_viewer_1.4" / "portefeuille_viewer" / "config",
                parent / "portefeuille_viewer" / "portefeuille_viewer_1.4" / "portefeuille_viewer" / "config",
            ]
        )
    for candidate in candidates:
        if (candidate / "settings_shared.ini").exists():
            return candidate
    return (
        anchor.parents[2]
        / "portefeuille_viewer"
        / "portefeuille_viewer_1.4"
        / "portefeuille_viewer"
        / "config"
    )


def load_settings() -> AppSettings:
    config_dir = find_pv14_config_dir()
    shared_settings = config_dir / "settings_shared.ini"
    local_settings = config_dir / ".user_settings" / "settings_local.ini"
    cfg = configparser.ConfigParser()
    cfg.read([str(shared_settings), str(local_settings)], encoding="utf-8")

    return AppSettings(
        stockdata_db_path=cfg.get("stockdata", "db_path", fallback=DEFAULT_STOCKDATA_DB).strip(),
        ib_host=cfg.get("interactive_brokers", "host", fallback="127.0.0.1").strip(),
        ib_port=cfg.getint("interactive_brokers", "port", fallback=7496),
        ib_client_id=cfg.getint("interactive_brokers", "client_id", fallback=299),
        shared_settings_path=shared_settings,
        local_settings_path=local_settings,
    )

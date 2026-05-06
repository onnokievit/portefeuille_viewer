from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IvRequestSettings:
    tws_host: str
    tws_port: int
    client_id_min: int
    client_id_max: int
    market_data_type: int = 1
    batch_size: int = 25
    batch_wait_sec: float = 3.0
    request_pause_sec: float = 0.05


@dataclass(frozen=True)
class SurfaceSelectionSettings:
    dte_min: int = 1
    dte_max: int = 60
    moneyness_min: float = 0.75
    moneyness_max: float = 1.25
    max_strikes_per_expiry: int = 20
    right_mode: str = "B"


@dataclass(frozen=True)
class SnapshotPaths:
    root_dir: Path
    latest_path: Path
    snapshot_path: Path

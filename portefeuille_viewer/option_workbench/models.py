from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScannerSettings:
    parquet_dir: Path
    horizon_months: int
    parallel_workers: int
    tws_host: str
    tws_port: int
    client_id_base: int
    client_id_min: int = 1000
    client_id_max: int = 10000
    include_calls: bool = True
    include_puts: bool = True
    right_request_mode: str = "separate"
    request_pause_sec: float = 1.0
    asset_pause_sec: float = 2.0
    timeout_sec: float = 20.0


@dataclass(frozen=True)
class OptionScanAsset:
    asset_rollup: str
    ib_symbol: str
    ib_currency: str
    ib_asset_type: str
    option_exchange: str
    opt_tradingclass: str = ""


@dataclass
class AssetScanResult:
    asset_rollup: str
    ib_symbol: str
    ib_currency: str
    option_exchange: str
    status: str
    parquet_path: str = ""
    months_requested: int = 0
    requests_sent: int = 0
    contracts_returned: int = 0
    contracts_inserted: int = 0
    contracts_updated: int = 0
    contracts_rejected: int = 0
    client_id: int = 0
    error_message: str = ""

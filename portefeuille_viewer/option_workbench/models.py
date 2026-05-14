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
    option_sec_type: str = ""
    option_variant: str = ""

    def __post_init__(self) -> None:
        asset_type = str(self.ib_asset_type or "").upper()
        option_type = str(self.option_sec_type or "").upper()
        if not option_type:
            option_type = "FOP" if asset_type == "FUT" else "OPT"
        object.__setattr__(self, "ib_asset_type", asset_type or "STK")
        object.__setattr__(self, "option_sec_type", option_type)
        if not self.option_variant:
            parts = [option_type, str(self.option_exchange or "").upper(), str(self.opt_tradingclass or "").upper()]
            object.__setattr__(self, "option_variant", "/".join(part for part in parts if part))

    def scan_key(self) -> str:
        return f"{self.asset_rollup}|{self.option_variant}"


@dataclass
class AssetScanResult:
    asset_rollup: str
    ib_symbol: str
    ib_currency: str
    option_exchange: str
    status: str
    option_sec_type: str = ""
    opt_tradingclass: str = ""
    option_variant: str = ""
    parquet_path: str = ""
    months_requested: int = 0
    requests_sent: int = 0
    contracts_returned: int = 0
    contracts_inserted: int = 0
    contracts_updated: int = 0
    contracts_rejected: int = 0
    client_id: int = 0
    error_message: str = ""

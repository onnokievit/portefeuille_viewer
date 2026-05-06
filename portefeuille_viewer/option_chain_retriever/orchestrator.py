from __future__ import annotations

import uuid
from datetime import datetime
from typing import Callable

from .chain_run_repository import ChainRunRepository
from .chain_scanner import BatchOptionChainScanner, OptionChainScanner
from .chain_store import merge_and_write_chain
from .models import AssetScanResult, OptionScanAsset, ScannerSettings

LogFn = Callable[[str], None]
ResultFn = Callable[[AssetScanResult], None]


class OptionChainRetrievalJob:
    def __init__(
        self,
        settings: ScannerSettings,
        stock_db_path: str,
        assets: list[OptionScanAsset],
        log: LogFn | None = None,
        on_asset_result: ResultFn | None = None,
    ) -> None:
        self.settings = settings
        self.stock_db_path = stock_db_path
        self.assets = assets
        self.log = log or (lambda _msg: None)
        self.on_asset_result = on_asset_result or (lambda _result: None)
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        self._scanner = OptionChainScanner(settings, self.log)
        self._batch: BatchOptionChainScanner | None = None

    def stop(self) -> None:
        self._scanner.stop()
        if self._batch is not None:
            self._batch.stop()

    def run(self) -> list[AssetScanResult]:
        repo = ChainRunRepository(self.stock_db_path)
        repo.start_run(self.run_id, self.settings, len(self.assets))
        self.log(f"[run] gestart run_id={self.run_id} assets={len(self.assets)}")
        results: list[AssetScanResult] = []

        def scan_one(asset: OptionScanAsset, run_id: str, client_id: int) -> AssetScanResult:
            started = datetime.now()
            rows, result = self._scanner.scan_asset(asset, run_id, client_id)
            if rows:
                path, inserted, updated, _total = merge_and_write_chain(
                    self.settings.parquet_dir,
                    asset.asset_rollup,
                    rows,
                )
                result.parquet_path = str(path)
                result.contracts_inserted = inserted
                result.contracts_updated = updated
            finished = datetime.now()
            repo.log_asset(run_id, result, started, finished)
            self.on_asset_result(result)
            self.log(
                f"[asset] {result.asset_rollup} clientId={result.client_id} "
                f"status={result.status} returned={result.contracts_returned} "
                f"inserted={result.contracts_inserted} updated={result.contracts_updated}"
            )
            return result

        try:
            self._batch = BatchOptionChainScanner(self.settings, scan_one, self.log)
            results = self._batch.run(self.assets, self.run_id)
            status = "success" if all(r.status in {"success", "skipped"} for r in results) else "partial"
            repo.finish_run(self.run_id, status, results)
            self.log(f"[run] klaar status={status}")
            return results
        except Exception as exc:
            repo.finish_run(self.run_id, "error", results, str(exc))
            self.log(f"[run] fout: {exc}")
            raise

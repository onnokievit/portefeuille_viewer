from __future__ import annotations

import json
import queue
import random
import threading
import time
from datetime import datetime
from typing import Callable

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper

from .date_utils import month_codes_from_today, parse_ib_expiry
from .models import AssetScanResult, OptionScanAsset, ScannerSettings

LogFn = Callable[[str], None]


def _sleep_interruptible(seconds: float, stop_event: threading.Event) -> None:
    remaining = max(0.0, float(seconds or 0.0))
    while remaining > 0 and not stop_event.is_set():
        step = min(0.25, remaining)
        time.sleep(step)
        remaining -= step


def _random_client_ids(count: int, low: int, high: int) -> list[int]:
    lower = max(1, int(low or 1000))
    upper = max(lower, int(high or 10000))
    span = upper - lower + 1
    if count <= span:
        return random.sample(range(lower, upper + 1), count)
    return [random.randint(lower, upper) for _ in range(count)]


class ContractDetailsApp(EWrapper, EClient):
    def __init__(self, log: LogFn | None = None) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.log = log or (lambda _msg: None)
        self.ready = threading.Event()
        self.done = threading.Event()
        self.rows: list[dict] = []
        self.errors: list[tuple[int, int, str]] = []

    def nextValidId(self, orderId: int) -> None:
        self.log(f"[IB] connected; nextValidId={orderId}")
        self.ready.set()

    def error(self, reqId, errorCode, errorString, advancedOrderReject="") -> None:
        if errorCode in {2103, 2104, 2105, 2106, 2107, 2108, 2158, 2119}:
            return
        msg = str(errorString or "")
        self.errors.append((int(reqId or -1), int(errorCode or 0), msg))
        self.log(f"[IB error] reqId={reqId} code={errorCode} msg={msg}")
        if errorCode in {200, 321}:
            self.done.set()

    def contractDetails(self, reqId, contractDetails) -> None:
        c = contractDetails.contract
        row = {
            "conid": int(getattr(c, "conId", 0) or 0),
            "ib_symbol": str(getattr(c, "symbol", "") or ""),
            "sec_type": str(getattr(c, "secType", "") or ""),
            "local_symbol": str(getattr(c, "localSymbol", "") or ""),
            "trading_class": str(getattr(c, "tradingClass", "") or ""),
            "exchange": str(getattr(c, "exchange", "") or ""),
            "primary_exchange": str(getattr(c, "primaryExchange", "") or ""),
            "ib_currency": str(getattr(c, "currency", "") or ""),
            "last_trade_date_raw": str(getattr(c, "lastTradeDateOrContractMonth", "") or ""),
            "strike": float(getattr(c, "strike", 0.0) or 0.0),
            "right": str(getattr(c, "right", "") or ""),
            "multiplier": _to_float(getattr(c, "multiplier", None)),
            "request_id": int(reqId or 0),
        }
        row["raw_contract_json"] = json.dumps(row, ensure_ascii=False, default=str)
        self.rows.append(row)

    def contractDetailsEnd(self, reqId) -> None:
        self.log(f"[IB] contractDetailsEnd reqId={reqId}; rows={len(self.rows)}")
        self.done.set()


def _to_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def build_option_contract(asset: OptionScanAsset, month: str, right: str) -> Contract:
    contract = Contract()
    contract.symbol = asset.ib_symbol
    contract.secType = "OPT"
    contract.exchange = asset.option_exchange or "SMART"
    contract.currency = asset.ib_currency
    if right:
        contract.right = right
    contract.lastTradeDateOrContractMonth = month
    # Deliberately do not set strike or multiplier.
    return contract


def normalize_rows(
    rows: list[dict],
    asset: OptionScanAsset,
    run_id: str,
    request_month: str,
    request_right: str,
    seen_at: datetime,
) -> tuple[list[dict], int]:
    out: list[dict] = []
    rejected = 0
    for row in rows:
        conid = int(row.get("conid") or 0)
        if conid <= 0:
            rejected += 1
            continue
        raw_expiry = row.get("last_trade_date_raw")
        expiry = parse_ib_expiry(raw_expiry)
        contract_month = str(raw_expiry or "")[:6] if str(raw_expiry or "")[:6].isdigit() else request_month
        clean = {
            "conid": conid,
            "asset_rollup": asset.asset_rollup,
            "ib_symbol": row.get("ib_symbol") or asset.ib_symbol,
            "ib_currency": row.get("ib_currency") or asset.ib_currency,
            "sec_type": row.get("sec_type") or "OPT",
            "exchange": row.get("exchange") or asset.option_exchange,
            "primary_exchange": row.get("primary_exchange") or "",
            "local_symbol": row.get("local_symbol") or "",
            "trading_class": row.get("trading_class") or "",
            "expiry": expiry,
            "last_trade_date_raw": str(raw_expiry or ""),
            "right": row.get("right") or request_right,
            "strike": float(row.get("strike") or 0.0),
            "multiplier": _to_float(row.get("multiplier")) if row.get("multiplier") is not None else None,
            "contract_month": contract_month,
            "source": "tws_contract_details",
            "first_seen_at": seen_at,
            "last_seen_at": seen_at,
            "last_refresh_run_id": run_id,
            "last_request_month": request_month,
            "last_request_right": request_right,
            "raw_contract_json": row.get("raw_contract_json") or json.dumps(row, ensure_ascii=False, default=str),
        }
        out.append(clean)
    return out, rejected


class OptionChainScanner:
    def __init__(self, settings: ScannerSettings, log: LogFn | None = None) -> None:
        self.settings = settings
        self.log = log or (lambda _msg: None)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def scan_asset(self, asset: OptionScanAsset, run_id: str, client_id: int) -> tuple[list[dict], AssetScanResult]:
        result = AssetScanResult(
            asset_rollup=asset.asset_rollup,
            ib_symbol=asset.ib_symbol,
            ib_currency=asset.ib_currency,
            option_exchange=asset.option_exchange,
            status="running",
            client_id=client_id,
        )
        if asset.ib_asset_type.upper() != "STK":
            result.status = "skipped"
            result.error_message = f"unsupported_ib_asset_type={asset.ib_asset_type}"
            self.log(f"[skip] {asset.asset_rollup}: {result.error_message}")
            return [], result

        separate_rights = []
        if self.settings.include_calls:
            separate_rights.append("C")
        if self.settings.include_puts:
            separate_rights.append("P")
        if not separate_rights:
            result.status = "skipped"
            result.error_message = "no_rights_selected"
            return [], result
        mode = (self.settings.right_request_mode or "separate").strip().lower()
        rights = [""] if mode == "combined" and len(separate_rights) == 2 else separate_rights
        months = month_codes_from_today(self.settings.horizon_months)
        result.months_requested = len(months)
        all_rows: list[dict] = []
        rejected = 0

        app = ContractDetailsApp(self.log)
        thread: threading.Thread | None = None
        try:
            self.log(f"[IB] connect asset={asset.asset_rollup} port={self.settings.tws_port} clientId={client_id}")
            app.connect(self.settings.tws_host, self.settings.tws_port, client_id)
            thread = threading.Thread(target=app.run, daemon=True)
            thread.start()
            if not app.ready.wait(timeout=self.settings.timeout_sec):
                raise RuntimeError(f"connection timeout on port {self.settings.tws_port}")

            req_id = 1000
            for month in months:
                for right in rights:
                    if self._stop_event.is_set():
                        raise RuntimeError("scan cancelled")
                    before = len(app.rows)
                    app.done.clear()
                    app.errors.clear()
                    contract = build_option_contract(asset, month, right)
                    self.log(
                        f"[scan] {asset.asset_rollup} {asset.ib_symbol} {asset.option_exchange} "
                        f"month={month} right={right or 'BOTH'}"
                    )
                    started = time.perf_counter()
                    app.reqContractDetails(req_id, contract)
                    app.done.wait(timeout=self.settings.timeout_sec)
                    duration_ms = (time.perf_counter() - started) * 1000.0
                    batch_raw = app.rows[before:]
                    batch, batch_rejected = normalize_rows(
                        batch_raw,
                        asset,
                        run_id,
                        month,
                        right or "BOTH",
                        datetime.now(),
                    )
                    all_rows.extend(batch)
                    rejected += batch_rejected
                    result.requests_sent += 1
                    self.log(
                        f"[scan] {asset.asset_rollup} month={month} right={right or 'BOTH'} "
                        f"rows={len(batch)} rejected={batch_rejected} ms={duration_ms:.0f}"
                    )
                    req_id += 1
                    _sleep_interruptible(self.settings.request_pause_sec, self._stop_event)
            result.contracts_returned = len(all_rows)
            result.contracts_rejected = rejected
            result.status = "success"
            return all_rows, result
        except Exception as exc:
            result.status = "error"
            result.error_message = str(exc)
            result.contracts_returned = len(all_rows)
            result.contracts_rejected = rejected
            self.log(f"[error] {asset.asset_rollup}: {exc}")
            return all_rows, result
        finally:
            try:
                app.disconnect()
            except Exception:
                pass
            if thread is not None:
                thread.join(timeout=1.0)


class BatchOptionChainScanner:
    def __init__(
        self,
        settings: ScannerSettings,
        scan_one: Callable[[OptionScanAsset, str, int], AssetScanResult],
        log: LogFn | None = None,
    ) -> None:
        self.settings = settings
        self.scan_one = scan_one
        self.log = log or (lambda _msg: None)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self, assets: list[OptionScanAsset], run_id: str) -> list[AssetScanResult]:
        workers = max(1, int(self.settings.parallel_workers or 1))
        client_ids = _random_client_ids(
            len(assets),
            self.settings.client_id_min,
            self.settings.client_id_max,
        )
        if workers == 1:
            out = []
            for asset, client_id in zip(assets, client_ids):
                if self._stop_event.is_set():
                    break
                out.append(self.scan_one(asset, run_id, client_id))
                _sleep_interruptible(self.settings.asset_pause_sec, self._stop_event)
            return out

        asset_queue: queue.Queue[tuple[OptionScanAsset, int]] = queue.Queue()
        for asset, client_id in zip(assets, client_ids):
            asset_queue.put((asset, client_id))
        results: list[AssetScanResult] = []
        lock = threading.Lock()

        def worker(worker_idx: int) -> None:
            while not self._stop_event.is_set():
                try:
                    asset, client_id = asset_queue.get_nowait()
                except queue.Empty:
                    return
                try:
                    result = self.scan_one(asset, run_id, client_id)
                    with lock:
                        results.append(result)
                    _sleep_interruptible(self.settings.asset_pause_sec, self._stop_event)
                finally:
                    asset_queue.task_done()

        threads = [threading.Thread(target=worker, args=(idx,), daemon=True) for idx in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return results

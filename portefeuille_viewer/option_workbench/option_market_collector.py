from __future__ import annotations

import random
import threading
import time
from datetime import datetime
from typing import Callable

import polars as pl
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper

from .iv_models import IvRequestSettings

LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int, str], None]

UNSET_DOUBLE = 1e100

PRICE_FIELDS = {
    1: "bid",
    2: "ask",
    4: "last",
    9: "close",
}
SIZE_FIELDS = {
    0: "bid_size",
    3: "ask_size",
    5: "last_size",
    8: "volume",
    27: "call_open_interest",
    28: "put_open_interest",
    29: "call_volume",
    30: "put_volume",
}
GENERIC_FIELDS = {
    23: "underlying_hist_vol_30d",
    24: "underlying_iv_30d",
}
OPTION_FIELDS = {
    10: "bid",
    11: "ask",
    12: "last",
    13: "model",
}


class OptionMarketApp(EWrapper, EClient):
    def __init__(self, log: LogFn | None = None) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.log = log or (lambda _msg: None)
        self.ready = threading.Event()
        self.rows_by_req: dict[int, dict] = {}
        self.errors_by_req: dict[int, list[tuple[int, str]]] = {}
        self.market_data_type_by_req: dict[int, int] = {}

    def nextValidId(self, orderId: int) -> None:
        self.log(f"[IB] connected; nextValidId={orderId}")
        self.ready.set()

    def error(self, reqId, errorCode, errorString, advancedOrderReject="") -> None:
        code = int(errorCode or 0)
        if code in {2103, 2104, 2105, 2106, 2107, 2108, 2119, 2158}:
            return
        rid = int(reqId or -1)
        msg = str(errorString or "")
        self.errors_by_req.setdefault(rid, []).append((code, msg))
        self.log(f"[IB error] reqId={rid} code={code} msg={msg}")

    def marketDataType(self, reqId, marketDataType: int) -> None:
        self.market_data_type_by_req[int(reqId or 0)] = int(marketDataType or 0)

    def tickPrice(self, reqId, tickType, price, attrib) -> None:
        name = PRICE_FIELDS.get(int(tickType or -1))
        if name:
            self._row(reqId)[name] = _clean_float(price)

    def tickSize(self, reqId, tickType, size) -> None:
        name = SIZE_FIELDS.get(int(tickType or -1))
        if name:
            self._row(reqId)[name] = int(size or 0)

    def tickGeneric(self, reqId, tickType, value) -> None:
        name = GENERIC_FIELDS.get(int(tickType or -1))
        if name:
            self._row(reqId)[name] = _clean_float(value)

    def tickOptionComputation(
        self,
        reqId,
        tickType,
        tickAttrib,
        impliedVol,
        delta,
        optPrice,
        pvDividend,
        gamma,
        vega,
        theta,
        undPrice,
    ) -> None:
        prefix = OPTION_FIELDS.get(int(tickType or -1))
        if not prefix:
            return
        row = self._row(reqId)
        row[f"{prefix}_iv"] = _clean_float(impliedVol)
        row[f"{prefix}_delta"] = _clean_float(delta)
        row[f"{prefix}_opt_price"] = _clean_float(optPrice)
        row[f"{prefix}_pv_dividend"] = _clean_float(pvDividend)
        row[f"{prefix}_gamma"] = _clean_float(gamma)
        row[f"{prefix}_vega"] = _clean_float(vega)
        row[f"{prefix}_theta"] = _clean_float(theta)
        row[f"{prefix}_und_price"] = _clean_float(undPrice)

    def _row(self, reqId) -> dict:
        return self.rows_by_req.setdefault(int(reqId or 0), {})


def collect_option_snapshot(
    selected: pl.DataFrame,
    settings: IvRequestSettings,
    log: LogFn | None = None,
    progress: ProgressFn | None = None,
) -> pl.DataFrame:
    log = log or (lambda _msg: None)
    progress = progress or (lambda _done, _total, _msg: None)
    if selected.is_empty():
        return pl.DataFrame()

    total = selected.height
    client_id = random.randint(int(settings.client_id_min), int(settings.client_id_max))
    app = OptionMarketApp(log)
    thread: threading.Thread | None = None
    started_at = datetime.now()
    log(
        f"[IV] connect port={settings.tws_port} clientId={client_id} "
        f"marketDataType={settings.market_data_type}"
    )
    try:
        app.connect(settings.tws_host, settings.tws_port, client_id)
        thread = threading.Thread(target=app.run, daemon=True)
        thread.start()
        if not app.ready.wait(timeout=20.0):
            raise RuntimeError(f"connection timeout on port {settings.tws_port}")
        app.reqMarketDataType(int(settings.market_data_type))

        contracts = selected.to_dicts()
        base_req_id = 5000
        all_rows: list[dict] = []
        for batch_start in range(0, total, int(settings.batch_size)):
            batch = contracts[batch_start : batch_start + int(settings.batch_size)]
            active: list[tuple[int, dict]] = []
            for offset, source_row in enumerate(batch):
                req_id = base_req_id + batch_start + offset
                contract = _contract_from_chain_row(source_row)
                app.rows_by_req[req_id] = {}
                active.append((req_id, source_row))
                app.reqMktData(req_id, contract, "100,101,104,106", False, False, [])
                if settings.request_pause_sec > 0:
                    time.sleep(float(settings.request_pause_sec))

            msg = f"batch {batch_start + len(batch)}/{total}"
            log(f"[IV] requested {msg}; wait={settings.batch_wait_sec:.1f}s")
            progress(batch_start, total, msg)
            time.sleep(float(settings.batch_wait_sec))

            for req_id, source_row in active:
                try:
                    app.cancelMktData(req_id)
                except Exception:
                    pass
                out = _base_output_row(source_row, started_at, client_id)
                out.update(app.rows_by_req.get(req_id, {}))
                out["market_data_type_returned"] = app.market_data_type_by_req.get(req_id, int(settings.market_data_type))
                errors = app.errors_by_req.get(req_id, [])
                out["request_status"] = "error" if errors else "ok"
                out["error_code"] = errors[-1][0] if errors else None
                out["error_message"] = errors[-1][1] if errors else ""
                _derive_fields(out)
                all_rows.append(out)
            progress(min(batch_start + len(batch), total), total, msg)
        log(f"[IV] snapshot rows={len(all_rows)}")
        return pl.DataFrame(all_rows)
    finally:
        try:
            app.disconnect()
        except Exception:
            pass
        if thread is not None:
            thread.join(timeout=1.0)


def _contract_from_chain_row(row: dict) -> Contract:
    contract = Contract()
    contract.conId = int(row.get("conid") or 0)
    contract.secType = str(row.get("sec_type") or "OPT")
    contract.exchange = str(row.get("exchange") or "SMART")
    contract.currency = str(row.get("ib_currency") or "")
    return contract


def _base_output_row(row: dict, snapshot_ts: datetime, client_id: int) -> dict:
    return {
        "snapshot_ts": snapshot_ts,
        "asset_rollup": row.get("asset_rollup"),
        "conid": int(row.get("conid") or 0),
        "ib_symbol": row.get("ib_symbol"),
        "ib_currency": row.get("ib_currency"),
        "sec_type": row.get("sec_type"),
        "exchange": row.get("exchange"),
        "local_symbol": row.get("local_symbol"),
        "trading_class": row.get("trading_class"),
        "expiry": row.get("expiry"),
        "right": row.get("right"),
        "strike": _clean_float(row.get("strike")),
        "multiplier": _clean_float(row.get("multiplier")),
        "dte": int(row.get("dte") or 0),
        "moneyness": _clean_float(row.get("moneyness")),
        "client_id": int(client_id),
        "source": "tws_req_mkt_data",
    }


def _derive_fields(row: dict) -> None:
    bid = row.get("bid")
    ask = row.get("ask")
    if bid is not None and ask is not None and bid >= 0 and ask >= 0:
        row["mid"] = (float(bid) + float(ask)) / 2.0
    else:
        row["mid"] = None
    model_iv = row.get("model_iv")
    row["iv"] = float(model_iv) * 100.0 if model_iv is not None and model_iv < 10 else model_iv
    row["delta"] = row.get("model_delta")
    row["gamma"] = row.get("model_gamma")
    row["vega"] = row.get("model_vega")
    row["theta"] = row.get("model_theta")
    if row.get("model_und_price") and row.get("strike"):
        try:
            row["model_moneyness"] = float(row["strike"]) / float(row["model_und_price"])
        except Exception:
            row["model_moneyness"] = None


def _clean_float(value) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if abs(out) >= UNSET_DOUBLE or out != out:
        return None
    return out

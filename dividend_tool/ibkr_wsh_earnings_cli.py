from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyodbc
from ibapi.client import EClient
from ibapi.common import WshEventData
from ibapi.wrapper import EWrapper


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from portefeuille_viewer.config import get_settings  # noqa: E402


ONNO_DB_PATH = Path(r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - ONNO.accdb")
INFO_ERROR_CODES = {2103, 2104, 2106, 2158}


@dataclass(frozen=True)
class AssetLookup:
    asset_rollup: str
    ib_symbol: str
    ib_currency: str
    exchange: str
    prim_exchange: str
    contractid: int


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def connect_access(db_path: Path) -> pyodbc.Connection:
    conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};"
    log(f"DB connect: {db_path}")
    return pyodbc.connect(conn_str)


def lookup_asset(db_path: Path, asset: str | None, conid: int | None) -> AssetLookup:
    if conid is not None:
        where = "contractid=?"
        params: tuple[Any, ...] = (conid,)
    elif asset:
        where = "UCASE(asset_rollup)=?"
        params = (asset.strip().upper(),)
    else:
        raise ValueError("Geef --asset of --conid mee.")

    sql = f"""
        SELECT TOP 1
            asset_rollup,
            ib_symbol,
            ib_currency,
            exchange,
            prim_exchange,
            contractid
        FROM asset_rollup_data
        WHERE {where}
          AND contractid IS NOT NULL
        ORDER BY asset_rollup
    """
    with connect_access(db_path) as conn:
        row = conn.cursor().execute(sql, params).fetchone()
    if row is None:
        raise RuntimeError(f"Geen asset met contractid gevonden voor asset={asset!r} conid={conid!r}")
    contractid = int(row.contractid)
    return AssetLookup(
        asset_rollup=str(row.asset_rollup or "").strip(),
        ib_symbol=str(row.ib_symbol or "").strip(),
        ib_currency=str(row.ib_currency or "").strip(),
        exchange=str(row.exchange or "").strip(),
        prim_exchange=str(row.prim_exchange or "").strip(),
        contractid=contractid,
    )


class WshTestApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.connected_event = threading.Event()
        self.meta_event = threading.Event()
        self.event_data_event = threading.Event()
        self.errors: list[dict[str, Any]] = []
        self.meta_json = ""
        self.event_json = ""

    def nextValidId(self, orderId):  # noqa: N802
        log(f"IB nextValidId ontvangen: {orderId}")
        self.connected_event.set()

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):  # noqa: N802
        try:
            code = int(errorCode)
        except Exception:
            code = -1
        row = {
            "reqId": reqId,
            "code": code,
            "message": str(errorString),
            "advanced": str(advancedOrderRejectJson or ""),
        }
        self.errors.append(row)
        level = "INFO" if code in INFO_ERROR_CODES else "ERROR"
        log(f"IB {level} reqId={reqId} code={code}: {errorString}")
        if code not in INFO_ERROR_CODES:
            self.meta_event.set()
            self.event_data_event.set()

    def wshMetaData(self, reqId: int, dataJson: str):  # noqa: N802
        self.meta_json = str(dataJson or "")
        log(f"wshMetaData ontvangen reqId={reqId} chars={len(self.meta_json)}")
        print_json_or_raw("WSH META RAW", self.meta_json)
        self.meta_event.set()

    def wshEventData(self, reqId: int, dataJson: str):  # noqa: N802
        self.event_json = str(dataJson or "")
        log(f"wshEventData ontvangen reqId={reqId} chars={len(self.event_json)}")
        print_json_or_raw("WSH EVENT RAW", self.event_json)
        self.event_data_event.set()


def print_json_or_raw(title: str, text: str) -> None:
    print(f"\n--- {title} ---", flush=True)
    if not text:
        print("(leeg)", flush=True)
        return
    try:
        parsed = json.loads(text)
        print(json.dumps(parsed, indent=2, ensure_ascii=False)[:12000], flush=True)
    except Exception:
        print(text[:12000], flush=True)
    print(f"--- END {title} ---\n", flush=True)


def build_wsh_request(conid: int, start_date: date, days: int, total_limit: int, filter_json: str) -> WshEventData:
    req = WshEventData()
    req.conId = int(conid)
    req.startDate = start_date.strftime("%Y%m%d")
    req.endDate = (start_date + timedelta(days=max(0, int(days)))).strftime("%Y%m%d")
    req.totalLimit = int(total_limit)
    req.filter = filter_json
    req.fillWatchlist = False
    req.fillPortfolio = False
    req.fillCompetitors = False
    return req


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test IBKR Wall Street Horizon earnings events via TWS API.")
    parser.add_argument("--db", default=str(ONNO_DB_PATH), help="Pad naar ONNO Access database.")
    parser.add_argument("--asset", default="MICROSOFT", help="asset_rollup uit ONNO asset_rollup_data.")
    parser.add_argument("--conid", type=int, default=None, help="IBKR conId; overschrijft --asset lookup.")
    parser.add_argument("--days", type=int, default=180, help="Aantal dagen vooruit vanaf vandaag.")
    parser.add_argument("--total-limit", type=int, default=20, help="Max aantal WSH events.")
    parser.add_argument(
        "--filter",
        default='{"watchlist":["wshe_ed","wshe_eps"]}',
        help="Raw WSH filter JSON. Gebruik '' om leeg te testen.",
    )
    parser.add_argument("--timeout", type=float, default=20.0, help="Timeout per IBKR stap in seconden.")
    parser.add_argument("--client-offset", type=int, default=80, help="Offset bovenop app IB client_id.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    host = settings.get_ib_host()
    port = settings.get_ib_port()
    client_id = settings.get_ib_client_id() + int(args.client_offset)
    start_date = date.today()

    try:
        lookup = lookup_asset(Path(args.db), args.asset, args.conid)
    except Exception as exc:
        log(f"FATAL asset lookup mislukt: {type(exc).__name__}: {exc}")
        return 1

    log("START IBKR WSH earnings test")
    log(
        "Asset: "
        f"{lookup.asset_rollup} ib_symbol={lookup.ib_symbol} conId={lookup.contractid} "
        f"currency={lookup.ib_currency} exchange={lookup.exchange} prim={lookup.prim_exchange or '-'}"
    )
    log(f"IB connect: host={host} port={port} client_id={client_id}")
    log("Communicatie-overzicht:")
    log("  1. Connect naar TWS/Gateway via ibapi.")
    log("  2. reqWshMetaData: verplicht per sessie; laat event types/filters zien.")
    log("  3. reqWshEventData: vraagt WSH events voor conId op.")
    log("  4. Raw JSON wordt geprint; script schrijft niets naar database.")

    app = WshTestApp()
    app.connect(host, port, clientId=client_id)
    thread = threading.Thread(target=app.run, daemon=True, name="ibkr-wsh-test")
    thread.start()

    if not app.connected_event.wait(timeout=float(args.timeout)):
        log("FATAL: timeout op nextValidId; TWS/Gateway niet klaar of client_id conflict")
        app.disconnect()
        return 2

    meta_req_id = 9100
    event_req_id = 9101
    log(f"send reqWshMetaData reqId={meta_req_id}")
    app.reqWshMetaData(meta_req_id)
    if not app.meta_event.wait(timeout=float(args.timeout)):
        log("WARN: timeout op wshMetaData callback")

    wsh_req = build_wsh_request(
        lookup.contractid,
        start_date=start_date,
        days=int(args.days),
        total_limit=int(args.total_limit),
        filter_json=str(args.filter or ""),
    )
    log(
        "send reqWshEventData "
        f"reqId={event_req_id} conId={wsh_req.conId} startDate={wsh_req.startDate} "
        f"endDate={wsh_req.endDate} totalLimit={wsh_req.totalLimit} filter={wsh_req.filter!r}"
    )
    app.reqWshEventData(event_req_id, wsh_req)
    if not app.event_data_event.wait(timeout=float(args.timeout)):
        log("WARN: timeout op wshEventData callback")

    time.sleep(0.5)
    app.disconnect()
    log(
        "KLAAR "
        f"meta_chars={len(app.meta_json)} event_chars={len(app.event_json)} "
        f"errors={len([e for e in app.errors if e['code'] not in INFO_ERROR_CODES])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

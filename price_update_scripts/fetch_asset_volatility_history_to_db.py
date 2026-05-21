from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyodbc
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from portefeuille_viewer.config import get_stockdata_db_path  # noqa: E402
from portefeuille_viewer.data.repository import get_stockdata_connection  # noqa: E402

STOCKDATA_DB_PATH = get_stockdata_db_path()
INFO_CODES = {1100, 1101, 1102, 2103, 2104, 2105, 2106, 2107, 2108, 2158, 2159}
TEMP_VOL_TABLE = "temp_asset_volatility_history"


@dataclass(frozen=True)
class AssetMeta:
    asset_rollup: str
    ib_symbol: str
    ib_currency: str
    asset_type: str
    exchange: str
    prim_exchange: str
    contractid: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch IBKR HV/IV daily series and update historical_data_correct."
    )
    parser.add_argument("--db", default=STOCKDATA_DB_PATH)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7496)
    parser.add_argument("--client-id", type=int, default=108)
    parser.add_argument("--timeout-sec", type=int, default=40)
    parser.add_argument("--duration", default="1 Y", help='IBKR durationStr, bijv. "1 M", "6 M", "1 Y", "2 Y"')
    parser.add_argument("--use-rth", type=int, choices=[0, 1], default=1)
    parser.add_argument("--use-conid", action="store_true")
    parser.add_argument("--asset", default="", help="Optioneel: een enkele asset_rollup")
    parser.add_argument("--limit", type=int, default=0, help="0 = alle gevonden assets")
    parser.add_argument("--active-only", action="store_true", help="Filter op INCL_EXCL=1")
    parser.add_argument("--include-non-equity", action="store_true")
    parser.add_argument("--include-ignore", action="store_true")
    parser.add_argument("--what", choices=["both", "hv", "iv"], default="both")
    parser.add_argument("--max-in-flight", type=int, default=3, help="Aantal gelijktijdige IBKR historical requests")
    parser.add_argument("--dry-run", action="store_true", help="Haal data op, maar schrijf niet naar DB")
    parser.add_argument("--log", action="store_true")
    return parser.parse_args()


class HistVolSeriesApp(EWrapper, EClient):
    def __init__(self, *, log_enabled: bool = False) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self._lock = threading.Lock()
        self._requests: dict[int, dict[str, Any]] = {}
        self._log_enabled = log_enabled

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def fetch_series(
        self,
        req_id: int,
        contract: Contract,
        *,
        what_to_show: str,
        duration: str,
        use_rth: int,
        timeout_sec: int,
    ) -> tuple[list[dict[str, Any]], str]:
        event = threading.Event()
        with self._lock:
            self._requests[req_id] = {"event": event, "rows": [], "error": ""}
        self.reqHistoricalData(req_id, contract, "", duration, "1 day", what_to_show, int(use_rth), 1, False, [])
        if not event.wait(timeout=max(5, int(timeout_sec))):
            with self._safe_cancel(req_id):
                pass
            with self._lock:
                self._requests.pop(req_id, None)
            return [], f"{what_to_show}: timeout"
        with self._safe_cancel(req_id):
            pass
        with self._lock:
            state = self._requests.pop(req_id, {})
        return list(state.get("rows") or []), str(state.get("error") or "")

    def _safe_cancel(self, req_id: int):
        class _CancelContext:
            def __enter__(inner_self):
                try:
                    self.cancelHistoricalData(req_id)
                except Exception:
                    pass

            def __exit__(inner_self, exc_type, exc, tb):
                return False

        return _CancelContext()

    def historicalData(self, reqId, bar):  # noqa: N802
        row_date = parse_ib_date(getattr(bar, "date", None))
        value = to_float(getattr(bar, "close", None))
        if row_date is None or value is None:
            return
        with self._lock:
            state = self._requests.get(int(reqId))
            if state is not None:
                state["rows"].append({"datum": row_date, "value": value})

    def historicalDataEnd(self, reqId, start, end):  # noqa: N802
        with self._lock:
            state = self._requests.get(int(reqId))
            if state is not None:
                state["event"].set()

    def error(self, reqId, *args):  # noqa: N802
        code = None
        msg = ""
        if len(args) == 2:
            code, msg = args
        elif len(args) == 3:
            code, msg, _ = args
        elif len(args) >= 4:
            _, code, msg, _ = args[:4]
        try:
            code = int(code)
        except Exception:
            pass
        if code in INFO_CODES:
            return
        if isinstance(msg, str) and "connection is OK" in msg:
            return
        if self._log_enabled:
            print(f"[vol-history] IB ERROR reqId={reqId} code={code}: {msg}")
        try:
            req_id = int(reqId)
        except Exception:
            return
        if req_id < 0:
            return
        with self._lock:
            state = self._requests.get(req_id)
            if state is not None:
                state["error"] = f"IB ERROR {code}: {msg}"
                if code in {200, 162, 321}:
                    state["event"].set()


def main() -> int:
    args = parse_args()
    t0 = time.perf_counter()
    assets = load_assets(args)
    if not assets:
        print(json.dumps({"status": "skipped", "reason": "no_assets"}))
        return 0
    log_progress(
        f"loaded assets={len(assets)} duration={args.duration} "
        f"what={args.what} max_in_flight={args.max_in_flight}"
    )

    app = HistVolSeriesApp(log_enabled=bool(args.log))
    app.connect(args.host, int(args.port), clientId=int(args.client_id))
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    if not app.ready.wait(timeout=8):
        app.disconnect()
        print(json.dumps({"status": "failed", "error": "IBKR connection not ready"}))
        return 1
    log_progress(f"connected host={args.host} port={args.port} client_id={args.client_id}")

    total_hv_rows = 0
    total_iv_rows = 0
    total_updated = 0
    total_hv_updated = 0
    total_iv_updated = 0
    assets_ok = 0
    assets_error = 0
    errors: list[str] = []
    try:
        result_by_asset = fetch_volatility_series_windowed(app, assets, args)
        if args.dry_run:
            for asset in assets:
                result = result_by_asset.get(asset.asset_rollup, {})
                hv_rows = list(result.get("hv_rows") or [])
                iv_rows = list(result.get("iv_rows") or [])
                error = "; ".join(x for x in (result.get("hv_error"), result.get("iv_error")) if x)
                if error and not hv_rows and not iv_rows:
                    assets_error += 1
                    errors.append(f"{asset.asset_rollup}: {error}")
                else:
                    assets_ok += 1
                total_hv_rows += len(hv_rows)
                total_iv_rows += len(iv_rows)
                log_missing_series(asset.asset_rollup, hv_rows, iv_rows)
                log_progress(
                    f"{asset.asset_rollup}: hv_rows={len(hv_rows)} iv_rows={len(iv_rows)} "
                    f"updated=0 db_ms=0 error={error}"
                )
        else:
            temp_rows: list[tuple[str, date, float | None, float | None]] = []
            with connect_access(args.db) as update_conn:
                for asset in assets:
                    result = result_by_asset.get(asset.asset_rollup, {})
                    hv_rows = list(result.get("hv_rows") or [])
                    iv_rows = list(result.get("iv_rows") or [])
                    error = "; ".join(x for x in (result.get("hv_error"), result.get("iv_error")) if x)
                    if error and not hv_rows and not iv_rows:
                        assets_error += 1
                        errors.append(f"{asset.asset_rollup}: {error}")
                    else:
                        assets_ok += 1
                    total_hv_rows += len(hv_rows)
                    total_iv_rows += len(iv_rows)
                    log_missing_series(asset.asset_rollup, hv_rows, iv_rows)
                    asset_temp_rows = build_temp_rows(asset.asset_rollup, hv_rows, iv_rows)
                    temp_rows.extend(asset_temp_rows)
                    log_progress(
                        f"{asset.asset_rollup}: hv_rows={len(hv_rows)} iv_rows={len(iv_rows)} "
                        f"queued={len(asset_temp_rows)} error={error}"
                    )
                update_t0 = time.perf_counter()
                temp_inserted = write_temp_volatility_rows(update_conn, temp_rows)
                total_hv_updated, total_iv_updated = merge_temp_volatility(update_conn)
                update_conn.commit()
                total_updated = max(total_hv_updated, total_iv_updated)
                update_ms = int((time.perf_counter() - update_t0) * 1000)
                log_progress(
                    f"bulk db update temp_rows={temp_inserted} hv_updated={total_hv_updated} "
                    f"iv_updated={total_iv_updated} db_ms={update_ms}"
                )
    finally:
        app.disconnect()

    payload = {
        "status": "ok" if assets_error == 0 else "partial",
        "assets_total": len(assets),
        "assets_ok": assets_ok,
        "assets_error": assets_error,
        "hv_rows": total_hv_rows,
        "iv_rows": total_iv_rows,
        "db_rows_updated": total_updated,
        "db_hv_updated": total_hv_updated,
        "db_iv_updated": total_iv_updated,
        "dry_run": bool(args.dry_run),
        "duration_ms": int((time.perf_counter() - t0) * 1000),
        "errors_preview": errors[:10],
    }
    print(json.dumps(payload))
    return 0 if assets_ok > 0 else 1


def fetch_volatility_series_windowed(
    app: HistVolSeriesApp,
    assets: list[AssetMeta],
    args: argparse.Namespace,
) -> dict[str, dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    req_id = 9700
    for asset in assets:
        contract = build_contract(asset, use_conid=bool(args.use_conid))
        if args.what in {"both", "hv"}:
            req_id += 1
            tasks.append(
                {
                    "asset": asset,
                    "req_id": req_id,
                    "contract": contract,
                    "what_to_show": "HISTORICAL_VOLATILITY",
                    "kind": "hv",
                }
            )
        if args.what in {"both", "iv"}:
            req_id += 1
            tasks.append(
                {
                    "asset": asset,
                    "req_id": req_id,
                    "contract": contract,
                    "what_to_show": "OPTION_IMPLIED_VOLATILITY",
                    "kind": "iv",
                }
            )

    result_by_asset: dict[str, dict[str, Any]] = {
        asset.asset_rollup: {"hv_rows": [], "iv_rows": [], "hv_error": "", "iv_error": ""}
        for asset in assets
    }
    max_workers = max(1, int(args.max_in_flight))

    def run_task(task: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], str]:
        rows, error = app.fetch_series(
            int(task["req_id"]),
            task["contract"],
            what_to_show=str(task["what_to_show"]),
            duration=str(args.duration),
            use_rth=int(args.use_rth),
            timeout_sec=int(args.timeout_sec),
        )
        return task["asset"].asset_rollup, str(task["kind"]), rows, error

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(run_task, task) for task in tasks]
        for future in as_completed(futures):
            asset_rollup, kind, rows, error = future.result()
            result = result_by_asset.setdefault(
                asset_rollup,
                {"hv_rows": [], "iv_rows": [], "hv_error": "", "iv_error": ""},
            )
            if kind == "hv":
                result["hv_rows"] = rows
                result["hv_error"] = error
            else:
                result["iv_rows"] = rows
                result["iv_error"] = error
            log_progress(
                f"fetched {asset_rollup} {kind.upper()} rows={len(rows)}"
                + (f" error={error}" if error else "")
            )
    return result_by_asset


def load_assets(args: argparse.Namespace) -> list[AssetMeta]:
    where = [
        "asset_rollup IS NOT NULL",
        "ib_symbol IS NOT NULL",
        "ib_currency IS NOT NULL",
    ]
    params: list[Any] = []
    if args.asset:
        where.append("UCASE(asset_rollup) = UCASE(?)")
        params.append(args.asset.strip())
    if args.active_only:
        where.append("INCL_EXCL = 1")
    sql = f"""
        SELECT asset_rollup, ib_symbol, ib_currency, [type], exchange, prim_exchange,
               contractid, indicator_rol
        FROM asset_rollup_data
        WHERE {" AND ".join(where)}
        ORDER BY asset_rollup
    """
    out: list[AssetMeta] = []
    with connect_access(args.db) as conn:
        cur = conn.cursor()
        for row in cur.execute(sql, *params).fetchall():
            asset_type = clean(getattr(row, "type", "")).lower()
            indicator_role = clean(getattr(row, "indicator_rol", "")).lower()
            if not args.include_non_equity and asset_type in {"", "index", "future", "fut", "cash"}:
                continue
            if not args.include_ignore and indicator_role == "ignore":
                continue
            out.append(
                AssetMeta(
                    asset_rollup=clean(row.asset_rollup).upper(),
                    ib_symbol=clean(row.ib_symbol),
                    ib_currency=clean(row.ib_currency),
                    asset_type=asset_type,
                    exchange=clean(row.exchange),
                    prim_exchange=clean(row.prim_exchange),
                    contractid=to_int(row.contractid),
                )
            )
            if args.limit and len(out) >= int(args.limit):
                break
    return out


def update_historical_data_correct(
    db_path: str,
    asset_rollup: str,
    hv_rows: list[dict[str, Any]],
    iv_rows: list[dict[str, Any]],
) -> int:
    with connect_access(db_path) as conn:
        updated = update_historical_data_correct_conn(conn, asset_rollup, hv_rows, iv_rows)
        conn.commit()
        return updated


def build_temp_rows(
    asset_rollup: str,
    hv_rows: list[dict[str, Any]],
    iv_rows: list[dict[str, Any]],
) -> list[tuple[str, date, float | None, float | None]]:
    by_date: dict[date, dict[str, float]] = {}
    for row in hv_rows:
        by_date.setdefault(row["datum"], {})["historical_volatility"] = float(row["value"])
    for row in iv_rows:
        by_date.setdefault(row["datum"], {})["implied_volatility"] = float(row["value"])
    return [
        (
            asset_rollup,
            datum,
            values.get("historical_volatility"),
            values.get("implied_volatility"),
        )
        for datum, values in sorted(by_date.items())
    ]


def write_temp_volatility_rows(
    conn,
    rows: list[tuple[str, date, float | None, float | None]],
) -> int:
    cur = conn.cursor()
    ensure_temp_volatility_table(cur)
    cur.execute(f"DELETE FROM {TEMP_VOL_TABLE}")
    if not rows:
        return 0
    cur.executemany(
        f"""
        INSERT INTO {TEMP_VOL_TABLE}
            ([asset_rollup], [datum], [historical_volatility], [implied_volatility])
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def ensure_temp_volatility_table(cur) -> None:
    try:
        cur.execute(
            f"""
            CREATE TABLE {TEMP_VOL_TABLE}
                (
                    [asset_rollup] TEXT(255),
                    [datum] DATETIME,
                    [historical_volatility] DOUBLE,
                    [implied_volatility] DOUBLE
                )
            """
        )
    except pyodbc.Error:
        pass
    for idx_name, idx_cols in (
        (f"idx_{TEMP_VOL_TABLE}_asset_datum", "[asset_rollup], [datum]"),
        ("idx_historical_data_correct_asset_datum", "[asset_rollup], [datum]"),
    ):
        table_name = TEMP_VOL_TABLE if idx_name.startswith(f"idx_{TEMP_VOL_TABLE}") else "historical_data_correct"
        try:
            cur.execute(f"CREATE INDEX {idx_name} ON {table_name} ({idx_cols})")
        except pyodbc.Error:
            pass


def merge_temp_volatility(conn) -> tuple[int, int]:
    cur = conn.cursor()
    hv_updated = execute_update_count(
        cur,
        f"""
        UPDATE historical_data_correct AS main
        INNER JOIN {TEMP_VOL_TABLE} AS temp
            ON main.[asset_rollup] = temp.[asset_rollup]
           AND DateValue(main.[datum]) = DateValue(temp.[datum])
        SET main.[historical_volatility] = temp.[historical_volatility]
        WHERE temp.[historical_volatility] IS NOT NULL
          AND (
                main.[historical_volatility] <> temp.[historical_volatility]
             OR main.[historical_volatility] IS NULL
          )
        """,
    )
    iv_updated = execute_update_count(
        cur,
        f"""
        UPDATE historical_data_correct AS main
        INNER JOIN {TEMP_VOL_TABLE} AS temp
            ON main.[asset_rollup] = temp.[asset_rollup]
           AND DateValue(main.[datum]) = DateValue(temp.[datum])
        SET main.[implied_volatility] = temp.[implied_volatility]
        WHERE temp.[implied_volatility] IS NOT NULL
          AND (
                main.[implied_volatility] <> temp.[implied_volatility]
             OR main.[implied_volatility] IS NULL
          )
        """,
    )
    return hv_updated, iv_updated


def execute_update_count(cur, sql: str) -> int:
    cur.execute(sql)
    try:
        return int(cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0)
    except Exception:
        return 0


def update_historical_data_correct_conn(
    conn,
    asset_rollup: str,
    hv_rows: list[dict[str, Any]],
    iv_rows: list[dict[str, Any]],
) -> int:
    by_date: dict[date, dict[str, float]] = {}
    for row in hv_rows:
        by_date.setdefault(row["datum"], {})["historical_volatility"] = float(row["value"])
    for row in iv_rows:
        by_date.setdefault(row["datum"], {})["implied_volatility"] = float(row["value"])
    if not by_date:
        return 0

    updated = 0
    cur = conn.cursor()
    for datum, values in sorted(by_date.items()):
        if "historical_volatility" in values and "implied_volatility" in values:
            cur.execute(
                """
                UPDATE historical_data_correct
                SET historical_volatility = ?, implied_volatility = ?
                WHERE asset_rollup = ? AND DateValue(datum) = ?
                """,
                values["historical_volatility"],
                values["implied_volatility"],
                asset_rollup,
                datum,
            )
        elif "historical_volatility" in values:
            cur.execute(
                """
                UPDATE historical_data_correct
                SET historical_volatility = ?
                WHERE asset_rollup = ? AND DateValue(datum) = ?
                """,
                values["historical_volatility"],
                asset_rollup,
                datum,
            )
        else:
            cur.execute(
                """
                UPDATE historical_data_correct
                SET implied_volatility = ?
                WHERE asset_rollup = ? AND DateValue(datum) = ?
                """,
                values["implied_volatility"],
                asset_rollup,
                datum,
            )
        updated += int(cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0)
    return updated


def build_contract(meta: AssetMeta, *, use_conid: bool) -> Contract:
    sec_type = resolve_sec_type(meta.asset_type)
    c = Contract()
    c.symbol = meta.ib_symbol
    c.secType = sec_type
    c.currency = meta.ib_currency
    c.exchange = resolve_exchange(sec_type, meta.exchange, meta.prim_exchange)
    if meta.prim_exchange:
        c.primaryExchange = meta.prim_exchange
    if use_conid and meta.contractid > 0:
        c.conId = int(meta.contractid)
    return c


def resolve_sec_type(asset_type: str) -> str:
    t = clean(asset_type).lower()
    if t == "index":
        return "IND"
    if t in {"future", "fut"}:
        return "FUT"
    return "STK"


def resolve_exchange(sec_type: str, exchange: str, prim_exchange: str) -> str:
    if sec_type == "STK":
        return "SMART"
    return clean(exchange).upper() or clean(prim_exchange).upper() or "SMART"


def connect_access(db_path: str):
    if db_path == get_stockdata_db_path():
        return get_stockdata_connection()
    return pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")


def log_progress(message: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [vol-history] {message}", flush=True)


def log_missing_series(asset_rollup: str, hv_rows: list[dict[str, Any]], iv_rows: list[dict[str, Any]]) -> None:
    asset = clean(asset_rollup).upper()
    if not hv_rows:
        log_progress(f"{asset}: melding: geen HISTORICAL_VOLATILITY data ontvangen/opgeslagen")
    if not iv_rows:
        log_progress(f"{asset}: melding: geen OPTION_IMPLIED_VOLATILITY data ontvangen/opgeslagen")


def parse_ib_date(value: Any) -> date | None:
    text = clean(value)
    if not text:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except Exception:
            pass
    return None


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        text = clean(value).replace(",", ".")
        try:
            return float(text)
        except Exception:
            return None


def to_int(value: Any) -> int:
    try:
        if value is None or clean(value) == "":
            return 0
        return int(float(value))
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

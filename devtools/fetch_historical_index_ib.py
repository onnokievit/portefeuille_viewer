import argparse
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


@dataclass
class HistoricalBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class IBHistoricalIndexApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self._next_valid_id_event = threading.Event()
        self._done_event = threading.Event()
        self._error_event = threading.Event()
        self._bars: list[HistoricalBar] = []
        self._error_msg: str | None = None
        self._cd_event = threading.Event()
        self._cd_rows: list[Contract] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802 (IB API naming)
        self._next_valid_id_event.set()

    def error(self, reqId, *args):  # noqa: N802
        # IB API argument variants:
        # - (errorCode, errorString)
        # - (errorCode, errorString, advancedOrderRejectJson)
        # - (errorTime, errorCode, errorString, advancedOrderRejectJson)
        if len(args) == 2:
            errorCode, errorString = args
        elif len(args) == 3:
            errorCode, errorString, _ = args
        elif len(args) >= 4:
            _, errorCode, errorString, _ = args[:4]
        else:
            return
        # Ignore common info/warning codes that are not fatal.
        if errorCode in (2103, 2104, 2106, 2158):
            return
        self._error_msg = f"IB error {errorCode} (reqId={reqId}): {errorString}"
        self._error_event.set()
        self._done_event.set()

    def historicalData(self, reqId, bar):  # noqa: N802
        self._bars.append(
            HistoricalBar(
                date=str(bar.date),
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume),
            )
        )

    def historicalDataEnd(self, reqId, start, end):  # noqa: N802
        self._done_event.set()

    def contractDetails(self, reqId, contractDetails):  # noqa: N802
        self._cd_rows.append(contractDetails.contract)

    def contractDetailsEnd(self, reqId):  # noqa: N802
        self._cd_event.set()


def make_index_contract(symbol: str, exchange: str, currency: str, conid: int = 0) -> Contract:
    c = Contract()
    if conid:
        c.conId = int(conid)
    c.symbol = symbol
    c.secType = "IND"
    c.exchange = exchange
    c.currency = currency
    return c


def resolve_index_contract(app: IBHistoricalIndexApp, contract: Contract, timeout_sec: float) -> Contract:
    app._cd_rows = []
    app._cd_event.clear()
    req_id = 9101
    app.reqContractDetails(req_id, contract)
    app._cd_event.wait(timeout=timeout_sec)
    if app._cd_rows:
        return app._cd_rows[0]
    return contract


def contract_debug_string(c: Contract) -> str:
    return (
        f"conId={getattr(c, 'conId', 0)} "
        f"symbol={getattr(c, 'symbol', '')} "
        f"secType={getattr(c, 'secType', '')} "
        f"exchange={getattr(c, 'exchange', '')} "
        f"primaryExch={getattr(c, 'primaryExchange', '')} "
        f"currency={getattr(c, 'currency', '')} "
        f"localSymbol={getattr(c, 'localSymbol', '')}"
    )


def write_csv_with_fallback(df: pd.DataFrame, path: str) -> str:
    try:
        df.to_csv(path, index=False)
        return path
    except PermissionError:
        p = Path(path)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback = str(p.with_name(f"{p.stem}_{stamp}{p.suffix}"))
        df.to_csv(fallback, index=False)
        print(f"WARN: file locked, wrote fallback CSV: {fallback}")
        return fallback


def fetch_historical_index(
    host: str,
    port: int,
    client_id: int,
    symbol: str,
    exchange: str,
    currency: str,
    conid: int,
    duration_str: str,
    bar_size: str,
    what_to_show: str,
    use_rth: int,
    timeout_sec: float,
    debug_contract: bool = False,
    resolve_contract: bool = False,
) -> pd.DataFrame:
    app = IBHistoricalIndexApp()
    app.connect(host, port, clientId=client_id)

    t = threading.Thread(target=app.run, daemon=True)
    t.start()

    if not app._next_valid_id_event.wait(timeout=min(timeout_sec, 5.0)):
        # Keep going, like the simple test scripts; some setups are slow/quirky
        # with nextValidId but still serve historical data.
        print("WARN: nextValidId not received yet; continuing request anyway.")

    try:
        app.reqMarketDataType(3)  # delayed data when no realtime subscription
    except Exception:
        pass

    base_contract = make_index_contract(symbol=symbol, exchange=exchange, currency=currency, conid=conid)
    contract = (
        resolve_index_contract(app, base_contract, timeout_sec=timeout_sec)
        if resolve_contract
        else base_contract
    )
    if debug_contract:
        print(f"[DEBUG] Requested contract: {contract_debug_string(base_contract)}")
        print(f"[DEBUG] Resolved contract:  {contract_debug_string(contract)}")
    app._bars = []
    app._error_event.clear()
    app._done_event.clear()
    req_id = 9001
    app.reqHistoricalData(
        reqId=req_id,
        contract=contract,
        endDateTime="",
        durationStr=duration_str,
        barSizeSetting=bar_size,
        whatToShow=what_to_show,
        useRTH=use_rth,
        formatDate=1,
        keepUpToDate=False,
        chartOptions=[],
    )

    done = app._done_event.wait(timeout=timeout_sec)
    app.disconnect()
    time.sleep(0.2)

    if not done:
        raise TimeoutError("Historical data request timed out.")
    if app._error_event.is_set():
        raise RuntimeError(app._error_msg or "Unknown IB error.")

    df = pd.DataFrame([b.__dict__ for b in app._bars])
    if not df.empty:
        df = df.sort_values("date").reset_index(drop=True)
    return df


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Standalone IB historical index fetcher (default: AEX).")
    p.add_argument("--host", default="127.0.0.1", help="IB Gateway/TWS host")
    p.add_argument("--port", type=int, default=7496, help="IB Gateway/TWS port")
    p.add_argument("--client-id", type=int, default=4, help="IB client id")
    p.add_argument("--symbol", default="EOE", help="Index symbol")
    p.add_argument("--exchange", default="FTA", help="Index exchange (AEX often: AEB)")
    p.add_argument("--currency", default="EUR", help="Currency")
    p.add_argument("--conid", type=int, default=0, help="Optional IB contract id (conId)")
    p.add_argument("--duration", default="2 Y", help="IB duration string, e.g. '1 M', '1 Y', '2 Y'")
    p.add_argument("--bar-size", default="1 day", help="IB bar size, e.g. '1 day', '1 hour'")
    p.add_argument(
        "--what-to-show",
        default="AUTO",
        help="IB whatToShow, e.g. TRADES, MIDPOINT, BID, ASK, HISTORICAL_VOLATILITY",
    )
    p.add_argument("--use-rth", type=int, default=0, choices=[0, 1], help="Use regular trading hours only")
    p.add_argument("--timeout-sec", type=float, default=20.0, help="Timeout in seconds")
    p.add_argument("--csv", default="", help="Optional output CSV path")
    p.add_argument(
        "--preset",
        choices=["single", "major"],
        default="single",
        help="single=one index from --symbol/--exchange, major=EOE+DAX+NDX",
    )
    p.add_argument(
        "--csv-dir",
        default="",
        help="Optional output dir for preset mode (writes one CSV per index).",
    )
    p.add_argument("--debug-contract", action="store_true", help="Print resolved IB contract fields")
    p.add_argument(
        "--combined-csv",
        default="",
        help="Optional combined CSV output path with rows for all requested indices.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    if args.preset == "single":
        targets = [
            {
                "index_name": args.symbol,
                "candidates": [(args.symbol, args.exchange, args.currency, args.conid)],
            }
        ]
    else:
        # Robust candidates per index (direct contract first, no hard dependency on a single conId).
        targets = [
            {
                "index_name": "AEX",
                "candidates": [
                    ("EOE", "FTA", "EUR", 0),
                    ("EOE", "AEB", "EUR", 0),
                ],
            },
            {
                "index_name": "DAX",
                "candidates": [
                    ("DAX", "EUREX", "EUR", 0),
                    ("DAX", "DTB", "EUR", 0),
                    ("DAX", "EUREX", "EUR", 825711),
                ],
            },
        ]

    failures = 0
    all_frames: list[pd.DataFrame] = []
    for i, target in enumerate(targets):
        index_name = target["index_name"]
        df = None
        err = None
        sym = ""
        exch = ""
        cur = ""
        for candidate_idx, (cand_sym, cand_exch, cand_cur, cand_conid) in enumerate(target["candidates"]):
            what_candidates = [args.what_to_show] if args.what_to_show.upper() != "AUTO" else ["TRADES", "MIDPOINT"]
            # First try direct contract request, then contractDetails-resolved fallback.
            for resolve_contract in (False, True):
                for wts in what_candidates:
                    try:
                        attempt_client_id = args.client_id + (i * 10) + candidate_idx
                        temp_df = fetch_historical_index(
                            host=args.host,
                            port=args.port,
                            client_id=attempt_client_id,
                            symbol=cand_sym,
                            exchange=cand_exch,
                            currency=cand_cur,
                            conid=cand_conid,
                            duration_str=args.duration,
                            bar_size=args.bar_size,
                            what_to_show=wts,
                            use_rth=args.use_rth,
                            timeout_sec=args.timeout_sec,
                            debug_contract=args.debug_contract,
                            resolve_contract=resolve_contract,
                        )
                        if temp_df is not None and not temp_df.empty:
                            df = temp_df
                            sym, exch, cur = cand_sym, cand_exch, cand_cur
                            break
                    except Exception as exc:
                        err = exc
                        df = None
                if df is not None and not df.empty:
                    break
            if df is not None and not df.empty:
                break
        if df is None:
            failures += 1
            print(f"[{index_name}] FAILED: {err}")
            continue

        df["index_name"] = index_name
        df["symbol"] = sym
        df["exchange"] = exch
        df["currency"] = cur
        all_frames.append(df)

        print(f"\n=== {sym} @ {exch} ({cur}) ===")
        if df.empty:
            print("No bars returned.")
        else:
            print(df.tail(10).to_string(index=False))
            print(f"Rows: {len(df)}")
            print(f"Range: {df['date'].iloc[0]} -> {df['date'].iloc[-1]}")

        if args.csv and args.preset == "single":
            written = write_csv_with_fallback(df, args.csv)
            print(f"Saved CSV: {written}")
        should_write_default_dir = (not args.csv) and (not args.csv_dir)
        out_dir = args.csv_dir or (str(script_dir) if should_write_default_dir else "")
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            out = os.path.join(out_dir, f"{sym}_{exch}_hist.csv")
            written = write_csv_with_fallback(df, out)
            print(f"Saved CSV: {written}")

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        combined = combined.sort_values(["index_name", "date"]).reset_index(drop=True)
        combined_out = args.combined_csv or str(script_dir / "indices_hist_combined.csv")
        Path(combined_out).parent.mkdir(parents=True, exist_ok=True)
        written = write_csv_with_fallback(combined, combined_out)
        print(f"Saved combined CSV: {written}")

    return 1 if failures == len(targets) else 0


if __name__ == "__main__":
    raise SystemExit(main())

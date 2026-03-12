import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


@dataclass
class IndexTarget:
    index_name: str
    symbol: str
    exchange: str
    currency: str


class IBHistSimpleApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.done = threading.Event()
        self.error_text: str | None = None
        self.rows: list[dict] = []

    def error(self, reqId, *args):  # noqa: N802
        # IB API variants:
        # - (errorCode, errorString)
        # - (errorCode, errorString, advancedOrderRejectJson)
        # - (errorTime, errorCode, errorString, advancedOrderRejectJson)
        code = None
        msg = ""
        if len(args) == 2:
            code, msg = args
        elif len(args) == 3:
            code, msg, _ = args
        elif len(args) >= 4:
            _, code, msg, _ = args[:4]
        else:
            return

        try:
            code_int = int(code)
        except Exception:
            code_int = None

        if code_int in (2103, 2104, 2106, 2158):
            return
        if isinstance(msg, str) and "connection is OK" in msg:
            return

        self.error_text = f"IB error {code} (reqId={reqId}): {msg}"
        self.done.set()

    def historicalData(self, reqId, bar):  # noqa: N802
        self.rows.append(
            {
                "date": str(bar.date),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
        )

    def historicalDataEnd(self, reqId, start, end):  # noqa: N802
        self.done.set()


def fetch_one_index(
    target: IndexTarget,
    host: str,
    port: int,
    client_id: int,
    duration_str: str = "5 Y",
    bar_size: str = "1 day",
    timeout_sec: float = 45.0,
) -> pd.DataFrame:
    app = IBHistSimpleApp()
    app.connect(host, port, clientId=client_id)
    api_thread = threading.Thread(target=app.run, daemon=True)
    api_thread.start()

    time.sleep(1.0)
    try:
        app.reqMarketDataType(3)
    except Exception:
        pass

    c = Contract()
    c.symbol = target.symbol
    c.secType = "IND"
    c.exchange = target.exchange
    c.currency = target.currency

    app.reqHistoricalData(
        reqId=1,
        contract=c,
        endDateTime="",
        durationStr=duration_str,
        barSizeSetting=bar_size,
        whatToShow="TRADES",
        useRTH=0,
        formatDate=2,
        keepUpToDate=False,
        chartOptions=[],
    )

    app.done.wait(timeout=timeout_sec)
    app.disconnect()
    api_thread.join(timeout=2.0)
    time.sleep(0.2)

    if app.error_text:
        raise RuntimeError(app.error_text)

    df = pd.DataFrame(app.rows)
    if df.empty:
        return df
    df = df.sort_values("date").reset_index(drop=True)
    df["index_name"] = target.index_name
    df["symbol"] = target.symbol
    df["exchange"] = target.exchange
    df["currency"] = target.currency
    return df


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    target_groups = [
        {
            "index_name": "AEX",
            "candidates": [
                IndexTarget(index_name="AEX", symbol="EOE", exchange="FTA", currency="EUR"),
                IndexTarget(index_name="AEX", symbol="EOE", exchange="AEB", currency="EUR"),
            ],
        },
        {
            "index_name": "DAX",
            "candidates": [
                IndexTarget(index_name="DAX", symbol="DAX", exchange="EUREX", currency="EUR"),
                IndexTarget(index_name="DAX", symbol="DAX", exchange="DTB", currency="EUR"),
            ],
        },
        {
            "index_name": "NDX",
            "candidates": [
                IndexTarget(index_name="NDX", symbol="NDX", exchange="NASDAQ", currency="USD"),
                IndexTarget(index_name="NDX", symbol="NDX", exchange="CBOE", currency="USD"),
            ],
        },
        {
            "index_name": "TSX",
            "candidates": [
                IndexTarget(index_name="TSX", symbol="TSX", exchange="TSE", currency="CAD"),
                IndexTarget(index_name="TSX", symbol="TXCX", exchange="TSE", currency="CAD"),
            ],
        },
    ]

    all_frames: list[pd.DataFrame] = []
    failures = 0

    for i, group in enumerate(target_groups):
        df = None
        used_target = None
        last_err: Exception | None = None
        for j, target in enumerate(group["candidates"]):
            for attempt in (1, 2):
                try:
                    # Retry with different client ids to avoid stale-session conflicts.
                    cid = 40 + (i * 20) + j + ((attempt - 1) * 100)
                    df = fetch_one_index(
                        target=target,
                        host="127.0.0.1",
                        port=7496,
                        client_id=cid,
                        duration_str="5 Y",
                        bar_size="1 day",
                        timeout_sec=60.0,
                    )
                    if df is not None and not df.empty:
                        used_target = target
                        break
                except Exception as exc:
                    last_err = exc
                    time.sleep(1.0)
                    continue
            if df is not None and not df.empty:
                break

        if df is None or df.empty:
            failures += 1
            print(f"[{group['index_name']}] FAILED: {last_err or 'No data'}")
            continue

        out = base_dir / f"{used_target.symbol}_{used_target.exchange}_hist.csv"
        df.to_csv(out, index=False)
        print(
            f"[{group['index_name']}] rows={len(df)} "
            f"range={df['date'].iloc[0]} -> {df['date'].iloc[-1]} "
            f"({used_target.symbol}@{used_target.exchange})"
        )
        print(f"Saved CSV: {out}")
        all_frames.append(df)

        # Small cooldown to reduce IB pacing/queue issues between indices.
        time.sleep(1.5)

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        combined = combined.sort_values(["index_name", "date"]).reset_index(drop=True)
        combined_out = base_dir / "indices_hist_combined.csv"
        combined.to_csv(combined_out, index=False)
        print(f"Saved combined CSV: {combined_out}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

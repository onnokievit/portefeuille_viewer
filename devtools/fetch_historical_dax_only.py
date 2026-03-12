import threading
import time
from pathlib import Path

import pandas as pd
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper


class DaxHistoricalApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.rows: list[dict] = []
        self.done = threading.Event()

    def error(self, reqId, *args):  # noqa: N802
        if len(args) >= 2:
            code = args[0] if len(args) == 2 else args[1]
            msg = args[1] if len(args) == 2 else args[2]
            if code not in (2103, 2104, 2106, 2158):
                print(f"IB error {code} (reqId={reqId}): {msg}")

    def historicalData(self, reqId, bar):  # noqa: N802
        self.rows.append(
            {
                "symbol": "DAX",
                "exchange": "EUREX",
                "currency": "EUR",
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


def main() -> int:
    app = DaxHistoricalApp()
    app.connect("127.0.0.1", 7496, clientId=44)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    time.sleep(1.0)

    try:
        app.reqMarketDataType(3)
    except Exception:
        pass

    contract = Contract()
    contract.symbol = "DAX"
    contract.secType = "IND"
    contract.exchange = "EUREX"
    contract.currency = "EUR"

    app.reqHistoricalData(
        reqId=1,
        contract=contract,
        endDateTime="",
        durationStr="5 Y",
        barSizeSetting="1 day",
        whatToShow="TRADES",
        useRTH=0,
        formatDate=2,
        keepUpToDate=False,
        chartOptions=[],
    )

    app.done.wait(timeout=30)
    app.disconnect()
    time.sleep(0.2)

    df = pd.DataFrame(app.rows)
    if df.empty:
        print("Geen DAX rows ontvangen.")
        return 1

    df = df.sort_values("date").reset_index(drop=True)
    out_path = Path(__file__).resolve().parent / "DAX_EUREX_hist_only.csv"
    df.to_csv(out_path, index=False)

    print(df.tail(10).to_string(index=False))
    print(f"Rows: {len(df)}")
    print(f"Range: {df['date'].iloc[0]} -> {df['date'].iloc[-1]}")
    print(f"Saved CSV: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import argparse
import datetime as dt
import threading
import time
from typing import Any, Dict, List


def fetch_executions_last_days(
    host: str = "127.0.0.1",
    port: int = 7498,
    client_id: int = 78,
    timeout: float = 10.0,
    days: int = 5,
) -> List[Dict[str, Any]]:
    """
    Standalone E2E helper to fetch executions from the last N days.
    Returns a list of dicts with execution info.
    """
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    from ibapi.execution import ExecutionFilter

    results: List[Dict[str, Any]] = []
    ready = threading.Event()
    done = threading.Event()

    class App(EWrapper, EClient):
        def __init__(self):
            EClient.__init__(self, self)

        def nextValidId(self, orderId: int):
            ready.set()

        def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
            # Keep output minimal but visible for E2E runs.
            print(f"[IB ERROR] {errorCode} {errorString} (reqId={reqId})")

        def execDetails(self, reqId, contract, execution):
            results.append(
                {
                    "execId": getattr(execution, "execId", None),
                    "orderId": getattr(execution, "orderId", None),
                    "symbol": getattr(contract, "symbol", None),
                    "secType": getattr(contract, "secType", None),
                    "exchange": getattr(contract, "exchange", None),
                    "currency": getattr(contract, "currency", None),
                    "action": getattr(execution, "side", None),
                    "shares": getattr(execution, "shares", None),
                    "price": getattr(execution, "price", None),
                    "time": getattr(execution, "time", None),
                    # Optie-specifieke velden
                    "expiry": getattr(contract, "lastTradeDateOrContractMonth", None),
                    "strike": getattr(contract, "strike", None),
                    "right": getattr(contract, "right", None),
                    "multiplier": getattr(contract, "multiplier", None),
                    "tradingClass": getattr(contract, "tradingClass", None),
                    "localSymbol": getattr(contract, "localSymbol", None),
                }
            )

        def execDetailsEnd(self, reqId):
            done.set()

    app = App()
    app.connect(host, port, clientId=client_id)
    t = threading.Thread(target=app.run, daemon=True)
    t.start()

    if not ready.wait(timeout=timeout):
        app.disconnect()
        raise RuntimeError("IBAPI not ready (nextValidId timeout).")

    start_time = dt.datetime.now() - dt.timedelta(days=days)
    filt = ExecutionFilter()
    filt.time = start_time.strftime("%Y%m%d %H:%M:%S")
    app.reqExecutions(1, filt)
    done.wait(timeout=timeout)
    time.sleep(0.2)
    app.disconnect()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="E2E: fetch executions from the last N days.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--ports", default="7498,7496")
    parser.add_argument("--client-id", type=int, default=77)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--days", type=int, default=5)
    args = parser.parse_args()

    ports = [int(p.strip()) for p in args.ports.split(",") if p.strip()]
    for idx, port in enumerate(ports):
        client_id = args.client_id + idx
        orders = fetch_executions_last_days(
            host=args.host,
            port=port,
            client_id=client_id,
            timeout=args.timeout,
            days=args.days,
        )

        print(f"Port {port} (clientId {client_id}) executions (last {args.days} days): {len(orders)}")
        for row in orders:
            print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Diagnose-script: test option chain ophalen voor een asset via IB Gateway.

Probeer achtereenvolgens:
  1. reqContractDetails voor het onderliggende (stock) → conId
     - met exchanges: SMART, ISLAND, NASDAQ, AEB, EURONEXT
  2. reqSecDefOptParams met de gevonden conId
  3. Als dat niets oplevert: reqContractDetails op een open optie-contract
     (strike=0 = wildcard → geeft alle opties terug)

Gebruik:
  python test_chain.py MSFT USD SMART
  python test_chain.py ASML EUR AEB
"""
import sys
import threading
import time
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract


CLIENT_ID = 9876     # vaste ID voor dit test-script


class TestApp(EWrapper, EClient):
    def __init__(self):
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.ready          = threading.Event()
        self.cd_results     = []
        self.cd_done        = threading.Event()
        self.op_results     = []
        self.op_done        = threading.Event()

    def nextValidId(self, orderId):
        print(f"[IB] verbonden — nextValidId={orderId}")
        self.ready.set()

    def error(self, reqId, errorCode, errorString, advancedOrderReject=""):
        if errorCode in {2103,2104,2105,2106,2107,2108,2158,2119,10182,10197}:
            return
        print(f"  [err reqId={reqId}] {errorCode}: {errorString}")
        if errorCode in {200, 162, 321, 354}:
            self.cd_done.set()
            self.op_done.set()

    def contractDetails(self, reqId, contractDetails):
        c = contractDetails.contract
        print(f"  → contractDetails: conId={c.conId}  symbol={c.symbol}  "
              f"secType={c.secType}  exchange={c.exchange}  "
              f"currency={c.currency}  localSymbol={c.localSymbol}  "
              f"tradingClass={c.tradingClass}  multiplier={c.multiplier}")
        self.cd_results.append(contractDetails)

    def contractDetailsEnd(self, reqId):
        print(f"  [contractDetailsEnd reqId={reqId}]  {len(self.cd_results)} resultaten")
        self.cd_done.set()

    def securityDefinitionOptionalParameter(self, reqId, exchange, underlyingConId,
                                             tradingClass, multiplier, expirations, strikes):
        print(f"  → optParams: exchange={exchange}  tradingClass={tradingClass}  "
              f"multiplier={multiplier}  "
              f"expiries={len(expirations)}  strikes={len(strikes)}")
        if expirations:
            exp_sorted = sorted(expirations)
            print(f"    eerste expiries: {exp_sorted[:5]}")
        if strikes:
            s_sorted = sorted(float(s) for s in strikes)
            print(f"    strikes (eerste 10): {s_sorted[:10]}")
        self.op_results.append({
            "exchange": exchange, "tradingClass": tradingClass,
            "multiplier": multiplier,
            "expiries": sorted(expirations),
            "strikes": sorted(float(s) for s in strikes),
        })

    def securityDefinitionOptionalParameterEnd(self, reqId):
        print(f"  [secDefOptParamsEnd reqId={reqId}]  {len(self.op_results)} exchange(s)")
        self.op_done.set()


def run(symbol: str, currency: str, exchange_hint: str, port: int = 7496) -> None:
    app = TestApp()
    app.connect("127.0.0.1", port, CLIENT_ID)
    t = threading.Thread(target=app.run, daemon=True)
    t.start()

    if not app.ready.wait(timeout=10):
        print("[FOUT] Verbinding mislukt")
        return

    # ── Stap 1: conId opzoeken voor het onderliggende aandeel ─────────────────
    exchanges_to_try = [exchange_hint, "SMART", "ISLAND", "NASDAQ", "AEB", "EURONEXT"]
    # verwijder duplicaten maar bewaar volgorde
    seen = set()
    exchanges_to_try = [e for e in exchanges_to_try if e not in seen and not seen.add(e)]

    con_id   = 0
    best_exch = ""

    for exch in exchanges_to_try:
        print(f"\n{'─'*60}")
        print(f"[STAP 1] reqContractDetails  {symbol}/{currency}  exchange={exch}")
        app.cd_results.clear()
        app.cd_done.clear()

        c = Contract()
        c.symbol   = symbol
        c.secType  = "STK"
        c.currency = currency
        c.exchange = exch

        app.reqContractDetails(1, c)
        app.cd_done.wait(timeout=8)

        if app.cd_results:
            con_id    = app.cd_results[0].contract.conId
            best_exch = exch
            print(f"  ✓ conId gevonden: {con_id}  via exchange={exch}")
            break
        else:
            print(f"  ✗ geen resultaat voor exchange={exch}")

    if not con_id:
        print("\n[FOUT] Kon geen conId vinden. Controleer symbol/currency.")
        app.disconnect()
        return

    # ── Stap 2: reqSecDefOptParams ────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"[STAP 2] reqSecDefOptParams  symbol={symbol}  conId={con_id}")
    app.op_results.clear()
    app.op_done.clear()

    app.reqSecDefOptParams(2, symbol, "", "STK", con_id)
    app.op_done.wait(timeout=20)

    if app.op_results:
        best = max(app.op_results, key=lambda r: len(r["strikes"]))
        print(f"\n  ✓ Beste exchange: {best['exchange']}  "
              f"tradingClass={best['tradingClass']}  "
              f"strikes={len(best['strikes'])}  expiries={len(best['expiries'])}")
    else:
        print("\n  ✗ reqSecDefOptParams leverde niets op.")
        print("  → Probeer Stap 3: wildcard reqContractDetails op optie")

        # ── Stap 3: wildcard optie-lookup ─────────────────────────────────────
        print(f"\n{'─'*60}")
        print(f"[STAP 3] reqContractDetails (OPT wildcard)  {symbol}/{currency}")
        app.cd_results.clear()
        app.cd_done.clear()

        c = Contract()
        c.symbol   = symbol
        c.secType  = "OPT"
        c.currency = currency
        c.exchange = "SMART"

        app.reqContractDetails(3, c)
        # wildcard kan lang duren — laat 15 sec lopen
        time.sleep(1)   # geef IB even tijd om te beginnen
        app.cd_done.wait(timeout=15)

        if app.cd_results:
            print(f"\n  ✓ {len(app.cd_results)} optie-contracten gevonden via wildcard")
            # Toon unieke expiries en strikes
            expiries = sorted({r.contract.lastTradeDateOrContractMonth for r in app.cd_results})
            strikes  = sorted({r.contract.strike for r in app.cd_results})
            tcs      = {r.contract.tradingClass for r in app.cd_results}
            print(f"  tradingClasses: {tcs}")
            print(f"  expiries ({len(expiries)}): {expiries[:8]}")
            print(f"  strikes  ({len(strikes)}): {strikes[:10]}")
        else:
            print("  ✗ ook wildcard leverde niets op.")

    print(f"\n{'═'*60}")
    print("Test klaar.")
    app.disconnect()


if __name__ == "__main__":
    args    = sys.argv[1:]
    symbol  = args[0] if len(args) > 0 else "MSFT"
    ccy     = args[1] if len(args) > 1 else "USD"
    exch    = args[2] if len(args) > 2 else "SMART"
    port    = int(args[3]) if len(args) > 3 else 7496
    print(f"Test ophalen optieketen: {symbol} / {ccy} / {exch}  (poort {port})")
    run(symbol, ccy, exch, port)

"""
IB Gateway connector for vol surface data collection.

Flow:
  1. connect()
  2. fetch_spot_price()         — get underlying close/last
  3. fetch_option_params()      — reqSecDefOptParams → strikes + expiries
  4. fetch_option_ivs()         — batch reqMktData snapshots → IV per contract
  5. save_to_parquet() / load_latest_parquet()
"""
import math
import random
import threading
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CHAIN_PREFIX = "CHAIN"

MAX_DTE = 60
MAX_STRIKES_PER_EXPIRY = 14
MONEYNESS_MIN = 0.0
MONEYNESS_MAX = 1.10

# IB uses these sentinels for "not available"
_SENTINELS = {-1.0, -2.0, 1.7976931348623157e308}


def _valid(v, positive: bool = True) -> bool:
    """Return True when v is a finite, non-sentinel, optionally positive number."""
    if v is None:
        return False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(f):
        return False
    if f in _SENTINELS:
        return False
    return f > 0 if positive else True


# ── Low-level IB app ──────────────────────────────────────────────────────────

class _App(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self._lock = threading.Lock()
        self._req_id = 100
        self._connected = threading.Event()

        # contract details
        self._cd_results: dict[int, list] = {}
        self._cd_events:  dict[int, threading.Event] = {}

        # reqSecDefOptParams
        self._op_req_id: int | None = None
        self._op_result: dict | None = None
        self._op_event = threading.Event()

        # spot price
        self._spot:        dict[int, dict]             = {}
        self._spot_events: dict[int, threading.Event] = {}

        # option IV
        self._opt:        dict[int, dict]             = {}
        self._opt_events: dict[int, threading.Event] = {}
        self._opt_errors: dict[int, tuple[int, str]]  = {}
        self._cancelled_market_data: set[int] = set()
        self._market_data_types_seen: set[tuple[int, int]] = set()

    def _next(self) -> int:
        with self._lock:
            rid = self._req_id
            self._req_id += 1
            return rid

    # ── EWrapper callbacks ────────────────────────────────────────────────────

    def nextValidId(self, orderId: int) -> None:
        with self._lock:
            self._req_id = max(self._req_id, orderId)
        self._connected.set()

    def error(self, reqId, errorCode, errorString, advancedOrderReject="") -> None:
        # Purely informational codes — ignore
        if errorCode in {2103, 2104, 2105, 2106, 2107, 2108, 2158, 2119, 10182, 10197}:
            return
        # Happens when a snapshot was cancelled or had already ended. It is noisy
        # after timeout batches and does not explain missing IV.
        if errorCode == 300 and reqId in self._cancelled_market_data:
            return
        # Signal waiting events so they don't block forever
        for store in (self._opt_events, self._spot_events, self._cd_events):
            ev = store.get(reqId)
            if ev:
                ev.set()
        if reqId in self._opt_events:
            self._opt_errors[reqId] = (int(errorCode), str(errorString))
        if errorCode in {354, 10168}:
            print(f"  [IB {reqId}] {errorCode}: {errorString}  (market-data/subscription)")
        else:
            print(f"  [IB {reqId}] {errorCode}: {errorString}")

    def marketDataType(self, reqId, marketDataType) -> None:
        names = {1: "live", 2: "frozen", 3: "delayed", 4: "delayed-frozen"}
        key = (int(reqId), int(marketDataType))
        if key in self._market_data_types_seen:
            return
        self._market_data_types_seen.add(key)
        if reqId == 100 or len(self._market_data_types_seen) <= 5:
            print(f"  [IB {reqId}] marketDataType={marketDataType} ({names.get(marketDataType, 'unknown')})")
        elif len(self._market_data_types_seen) == 6:
            print("  [IB] marketDataType logging suppressed for remaining option requests")

    def contractDetails(self, reqId, contractDetails) -> None:
        self._cd_results.setdefault(reqId, []).append(contractDetails)

    def contractDetailsEnd(self, reqId) -> None:
        if ev := self._cd_events.get(reqId):
            ev.set()

    def securityDefinitionOptionalParameter(
        self, reqId, exchange, underlyingConId,
        tradingClass, multiplier, expirations, strikes
    ) -> None:
        if reqId != self._op_req_id:
            return
        # Keep the exchange result with the most strikes (= primary exchange)
        if self._op_result is None or len(strikes) > len(self._op_result["strikes"]):
            self._op_result = {
                "strikes":       sorted(float(s) for s in strikes),
                "expiries":      sorted(expirations),
                "multiplier":    multiplier or "100",
                "exchange":      exchange,
                "trading_class": tradingClass,
            }

    def securityDefinitionOptionalParameterEnd(self, reqId) -> None:
        if reqId == self._op_req_id:
            self._op_event.set()

    def tickPrice(self, reqId, tickType, price, attrib) -> None:
        if reqId not in self._spot or not _valid(price):
            return
        with self._lock:
            d = self._spot[reqId]
            if tickType == 4:                       # LAST  — preferred
                d["price"] = float(price)
                self._spot_events[reqId].set()
            elif tickType == 9 and "price" not in d:  # CLOSE — fallback
                d["price"] = float(price)
                self._spot_events[reqId].set()

    def tickOptionComputation(
        self, reqId, tickType, tickAttrib,
        impliedVol, delta, optPrice, pvDividend,
        gamma, vega, theta, undPrice
    ) -> None:
        if reqId not in self._opt:
            return
        # Priority: MODEL(13) > LAST(12) > ASK(11) > BID(10)
        prio = {13: 0, 12: 1, 11: 2, 10: 3}
        if tickType not in prio:
            return

        iv = float(impliedVol) if _valid(impliedVol) and float(impliedVol) < 5.0 else None
        if iv is None:
            return

        with self._lock:
            d = self._opt[reqId]
            if prio[tickType] <= prio.get(d.get("tick_type", 99), 99):
                d.update({
                    "iv":        iv,
                    "delta":     float(delta)   if _valid(delta,    False) and abs(float(delta))   <= 1.05 else None,
                    "gamma":     float(gamma)   if _valid(gamma)                                           else None,
                    "theta":     float(theta)   if _valid(theta,    False)                                 else None,
                    "und_price": float(undPrice) if _valid(undPrice)                                       else None,
                    "tick_type": tickType,
                })

        if tickType == 13:          # MODEL always marks the contract as done
            self._opt_events[reqId].set()


# ── Public collector ──────────────────────────────────────────────────────────

class IbCollector:
    """Fetch option-chain IV data from IB Gateway for vol-surface construction."""

    def __init__(self, port: int = 7496, client_id: int | None = None) -> None:
        self._port      = port
        self._client_id = client_id or random.randint(3000, 8999)
        self._app       = _App()
        self._thread: threading.Thread | None = None
        self.last_series: pd.DataFrame = pd.DataFrame()
        self.last_contracts: pd.DataFrame = pd.DataFrame()
        self.last_attempts: pd.DataFrame = pd.DataFrame()

    # ── connection ────────────────────────────────────────────────────────────

    def connect(self, timeout: float = 12.0) -> bool:
        self._app.connect("127.0.0.1", self._port, self._client_id)
        self._thread = threading.Thread(
            target=self._app.run, daemon=True, name="ib-vol-surf"
        )
        self._thread.start()
        ok = self._app._connected.wait(timeout=timeout)
        if ok:
            print(f"[IB] Connected — port={self._port} clientId={self._client_id}")
            print("[IB] Requesting delayed/frozen market data when live data is unavailable")
            self._app.reqMarketDataType(4)
        else:
            print(f"[IB] Connection timeout on port {self._port}")
        return ok

    def disconnect(self) -> None:
        try:
            self._app.disconnect()
        except Exception:
            pass

    # ── helpers ───────────────────────────────────────────────────────────────

    def _resolve_con_id(
        self, symbol: str, currency: str, exchange: str, sec_type: str = "STK"
    ) -> int:
        # For USD assets prefer SMART/US-exchanges first so we don't accidentally
        # pick up a European cross-listing (e.g. MSFT on AEB has no option chain).
        if currency == "USD":
            order = [exchange, "SMART", "ISLAND", "NASDAQ", "AEB", "EURONEXT"]
        else:
            order = [exchange, "SMART", "AEB", "EURONEXT", "ISLAND", "NASDAQ"]

        seen: set[str] = set()
        candidates: list[str] = []
        for e in order:
            if e not in seen:
                seen.add(e)
                candidates.append(e)

        for exch in candidates:
            c = Contract()
            c.symbol   = symbol
            c.secType  = sec_type
            c.currency = currency
            c.exchange = exch

            rid = self._app._next()
            ev  = threading.Event()
            self._app._cd_events[rid]  = ev
            self._app._cd_results[rid] = []
            self._app.reqContractDetails(rid, c)
            ev.wait(timeout=10)

            results = self._app._cd_results.get(rid, [])
            if results:
                con_id = results[0].contract.conId
                print(f"  [collector] conId={con_id} via exchange={exch}")
                return con_id

        return 0

    # ── public fetch methods ──────────────────────────────────────────────────

    def fetch_spot_price(
        self, symbol: str, currency: str, exchange: str, sec_type: str = "STK"
    ) -> float | None:
        c = Contract()
        c.symbol   = symbol
        c.secType  = sec_type
        c.currency = currency
        c.exchange = exchange

        rid = self._app._next()
        ev  = threading.Event()
        self._app._spot[rid]        = {}
        self._app._spot_events[rid] = ev
        self._app.reqMktData(rid, c, "", True, False, [])
        ev.wait(timeout=8)
        self._app.cancelMktData(rid)
        return self._app._spot.get(rid, {}).get("price")

    def fetch_option_params(
        self, symbol: str, currency: str, exchange: str
    ) -> dict | None:
        """Return chain params, preferring reqSecDefOptParams over wildcard OPT."""
        con_id = self._resolve_con_id(symbol, currency, exchange)
        if not con_id:
            print(f"  [collector] Could not resolve conId for {symbol}/{exchange}")
            return None

        params = self._fetch_params_via_secdef(symbol, con_id)
        if params:
            return params
        print("  [collector] reqSecDefOptParams returned no usable chain; falling back to wildcard OPT")
        return self._fetch_params_via_wildcard(symbol, currency)

    def _fetch_params_via_secdef(self, symbol: str, con_id: int) -> dict | None:
        rid = self._app._next()
        self._app._op_req_id = rid
        self._app._op_result = None
        self._app._op_event.clear()
        self._app.reqSecDefOptParams(rid, symbol, "", "STK", con_id)
        self._app._op_event.wait(timeout=20)

        result = self._app._op_result
        if not result:
            return None

        print(
            f"  [collector] Chain (secDef): {len(result['strikes'])} strikes, "
            f"{len(result['expiries'])} expiries  tradingClass={result['trading_class']}  "
            f"exchange={result['exchange']}"
        )
        return {
            "strikes": result["strikes"],
            "expiries": result["expiries"],
            "multiplier": result["multiplier"],
            "exchange": result["exchange"],
            "trading_class": result["trading_class"],
            "valid_pairs": None,
            "source": "secdef",
        }

    def _fetch_params_via_wildcard(self, symbol: str, currency: str) -> dict | None:
        """Build chain params from a wildcard OPT reqContractDetails call."""
        c = Contract()
        c.symbol   = symbol
        c.secType  = "OPT"
        c.currency = currency
        c.exchange = "SMART"

        rid = self._app._next()
        ev  = threading.Event()
        self._app._cd_events[rid]  = ev
        self._app._cd_results[rid] = []
        self._app.reqContractDetails(rid, c)
        time.sleep(1)           # give IB time to begin streaming results
        ev.wait(timeout=20)

        results = self._app._cd_results.get(rid, [])
        if not results:
            print("  [collector] Wildcard OPT lookup returned no results")
            return None

        # Keep exact (strike, expiry) pairs — avoids Cartesian blowup
        valid_pairs = {
            (float(r.contract.strike), r.contract.lastTradeDateOrContractMonth)
            for r in results
        }
        strikes    = sorted({p[0] for p in valid_pairs})
        expiries   = sorted({p[1] for p in valid_pairs})
        multiplier = results[0].contract.multiplier or "100"
        tc         = results[0].contract.tradingClass or symbol
        exch       = results[0].contract.exchange or "SMART"

        print(
            f"  [collector] Chain (wildcard OPT): {len(valid_pairs)} valid pairs, "
            f"{len(strikes)} strikes, {len(expiries)} expiries  "
            f"tradingClass={tc}  exchange={exch}"
        )
        return {
            "strikes":      strikes,
            "expiries":     expiries,
            "multiplier":   multiplier,
            "exchange":     exch,
            "trading_class": tc,
            "valid_pairs":  valid_pairs,   # set of (float_strike, str_expiry)
            "source":       "wildcard",
        }

    @staticmethod
    def params_to_chain_df(
        params: dict, symbol: str, currency: str, port: int | None = None
    ) -> pd.DataFrame:
        valid_pairs = params.get("valid_pairs") or {
            (float(s), e) for e in params.get("expiries", []) for s in params.get("strikes", [])
        }
        chain_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        source = params.get("source") or "unknown"
        rows: list[dict] = []
        for strike, expiry in sorted(valid_pairs, key=lambda p: (p[1], p[0])):
            try:
                exp_date = datetime.strptime(expiry, "%Y%m%d").date()
                weekday = exp_date.strftime("%A")
            except ValueError:
                weekday = ""
            rows.append({
                "symbol": symbol,
                "currency": currency,
                "expiry": expiry,
                "strike": float(strike),
                "weekday": weekday,
                "exchange": params.get("exchange") or "SMART",
                "trading_class": params.get("trading_class") or symbol,
                "multiplier": str(params.get("multiplier") or "100"),
                "chain_date": date.today().isoformat(),
                "chain_id": chain_id,
                "source": source,
                "port": port,
            })
        return pd.DataFrame(rows)

    @staticmethod
    def chain_df_to_params(df: pd.DataFrame) -> dict:
        if df.empty:
            return {}
        valid_pairs = {
            (float(row.strike), str(row.expiry))
            for row in df[["strike", "expiry"]].itertuples(index=False)
        }
        return {
            "strikes": sorted({p[0] for p in valid_pairs}),
            "expiries": sorted({p[1] for p in valid_pairs}),
            "multiplier": str(df["multiplier"].dropna().iloc[0]) if "multiplier" in df and not df["multiplier"].dropna().empty else "100",
            "exchange": str(df["exchange"].dropna().iloc[0]) if "exchange" in df and not df["exchange"].dropna().empty else "SMART",
            "trading_class": str(df["trading_class"].dropna().iloc[0]) if "trading_class" in df and not df["trading_class"].dropna().empty else "",
            "valid_pairs": valid_pairs,
        }

    @staticmethod
    def _is_friday(expiry_str: str) -> bool:
        try:
            return datetime.strptime(expiry_str, "%Y%m%d").date().weekday() == 4
        except ValueError:
            return False

    @staticmethod
    def _nearest_to_atm(strikes: list[float], spot: float, limit: int) -> list[float]:
        if len(strikes) <= limit:
            return sorted(strikes)
        return sorted(strikes, key=lambda s: (abs(s - spot), s))[:limit]

    def build_contract_list(
        self,
        symbol:          str,
        currency:        str,
        spot:            float,
        params:          dict,
        opt_ref:         dict | None = None,
        dte_min:         int   = 3,
        dte_max:         int   = 60,
        moneyness_range: float = MONEYNESS_MAX,
        max_strikes_per_expiry: int = MAX_STRIKES_PER_EXPIRY,
    ) -> list[tuple]:
        """
        Return list of (Contract, expiry_str, dte, strike, right) tuples
        filtered hard for the POC:
        - Friday expiries only
        - max 60 DTE
        - 0.0 < strike / spot <= 1.10
        - cap strikes per expiry closest to ATM
        """
        today  = date.today()
        floor  = today + timedelta(days=dte_min)
        cutoff = today + timedelta(days=min(dte_max, MAX_DTE))
        max_moneyness = min(float(moneyness_range), MONEYNESS_MAX)
        lo     = spot * MONEYNESS_MIN
        hi     = spot * max_moneyness

        exch  = (opt_ref or {}).get("opt_exchange")    or params.get("exchange")       or "SMART"
        tc    = (opt_ref or {}).get("opt_tradingclass") or params.get("trading_class") or ""
        mult  = str(int((opt_ref or {}).get("opt_multiplier") or 100))

        valid_pairs = params.get("valid_pairs")
        raw_pair_count = len(valid_pairs) if valid_pairs else len(params["strikes"]) * len(params["expiries"])
        print(
            "  [collector] Selection rule: Fridays only, "
            f"DTE {dte_min}-{min(dte_max, MAX_DTE)}, "
            f"0.0 < moneyness <= {max_moneyness:.2f}, "
            f"max {max_strikes_per_expiry} strikes/expiry"
        )
        print(
            f"  [collector] Chain raw: {raw_pair_count} pairs, "
            f"{len(params['expiries'])} expiries, {len(params['strikes'])} strikes"
        )

        selected_by_expiry: dict[str, tuple[int, list[float]]] = {}
        reject = Counter()
        pairs = (
            sorted(valid_pairs, key=lambda p: (p[1], p[0]))
            if valid_pairs
            else [(float(s), e) for e in sorted(params["expiries"]) for s in sorted(params["strikes"])]
        )

        for strike, expiry_str in pairs:
            try:
                exp_date = datetime.strptime(expiry_str, "%Y%m%d").date()
            except ValueError:
                reject["bad_expiry"] += 1
                continue
            if exp_date.weekday() != 4:
                reject["not_friday"] += 1
                continue
            if not (floor <= exp_date <= cutoff):
                reject["outside_dte"] += 1
                continue
            moneyness = float(strike) / spot
            if not (MONEYNESS_MIN < moneyness <= max_moneyness):
                reject["outside_moneyness"] += 1
                continue
            dte = (exp_date - today).days
            selected_by_expiry.setdefault(expiry_str, (dte, []))[1].append(float(strike))

        capped_by_expiry: dict[str, tuple[int, list[float]]] = {}
        capped_out = 0
        for expiry_str, (dte, strikes) in sorted(selected_by_expiry.items()):
            uniq = sorted(set(strikes))
            chosen = self._nearest_to_atm(uniq, spot, max_strikes_per_expiry)
            capped_out += max(0, len(uniq) - len(chosen))
            capped_by_expiry[expiry_str] = (dte, sorted(chosen))

        print(
            f"  [collector] Filtered: {sum(len(v[1]) for v in selected_by_expiry.values())} pairs "
            f"over {len(selected_by_expiry)} Friday expiries"
        )
        if reject:
            print(f"  [collector] Rejected: {dict(reject)}")
        if capped_out:
            print(f"  [collector] Strike cap removed {capped_out} pairs")

        contracts: list[tuple] = []
        requested_rows: list[dict] = []
        series_rows: list[dict] = []
        for expiry_str, (dte, strikes) in capped_by_expiry.items():
            available = sorted(set(selected_by_expiry.get(expiry_str, (dte, []))[1]))
            series_rows.append({
                "expiry": expiry_str,
                "dte": dte,
                "weekday": "Friday",
                "available_strikes": len(available),
                "selected_strikes": len(strikes),
                "min_moneyness": round(min(strikes) / spot, 4) if strikes else None,
                "max_moneyness": round(max(strikes) / spot, 4) if strikes else None,
                "contracts_requested": len(strikes) * 2,
                "contracts_with_iv": 0,
            })
            for strike in strikes:
                for right in ("C", "P"):
                    c = Contract()
                    c.symbol                       = symbol
                    c.secType                      = "OPT"
                    c.currency                     = currency
                    c.exchange                     = exch
                    c.lastTradeDateOrContractMonth = expiry_str
                    c.strike                       = float(strike)
                    c.right                        = right
                    c.multiplier                   = mult
                    if tc:
                        c.tradingClass = tc
                    contracts.append((c, expiry_str, dte, float(strike), right))
                    requested_rows.append({
                        "symbol": symbol,
                        "expiry": expiry_str,
                        "dte": dte,
                        "strike": float(strike),
                        "right": right,
                        "moneyness": round(float(strike) / spot, 6),
                        "requested": True,
                    })
        self.last_series = pd.DataFrame(series_rows)
        self.last_contracts = pd.DataFrame(requested_rows)
        print(
            f"  [collector] Requested: {len(contracts)} contracts "
            f"({len(capped_by_expiry)} expiries x <= {max_strikes_per_expiry} strikes x 2 rights)"
        )
        return contracts

    def fetch_iv_for_contracts(
        self,
        contracts:     list[tuple],
        spot:          float,
        symbol:        str,
        currency:      str,
        batch_size:    int   = 20,
        batch_timeout: float = 14.0,
        on_progress=None,
    ) -> pd.DataFrame:
        """
        Fetch IV for a pre-built list of (Contract, expiry_str, dte, strike, right).
        Uses reqMktData snapshot; relies on tickOptionComputation field=13 (MODEL).
        """
        total = len(contracts)
        print(f"  [collector] {total} contracts — batches of {batch_size}")

        rows: list[dict] = []
        attempt_rows: list[dict] = []
        batches_done = 0
        for batch_start in range(0, total, batch_size):
            batch   = contracts[batch_start: batch_start + batch_size]
            req_map: dict[int, tuple] = {}

            for c, expiry_str, dte, strike, right in batch:
                rid = self._app._next()
                ev  = threading.Event()
                self._app._opt[rid]        = {}
                self._app._opt_events[rid] = ev
                self._app.reqMktData(rid, c, "", True, False, [])
                req_map[rid] = (expiry_str, dte, strike, right)
                time.sleep(0.05)

            deadline = time.time() + batch_timeout
            for rid in req_map:
                remaining = max(0.05, deadline - time.time())
                self._app._opt_events[rid].wait(timeout=remaining)

            for rid, (expiry_str, dte, strike, right) in req_map.items():
                self._app._cancelled_market_data.add(rid)
                self._app.cancelMktData(rid)
                d  = self._app._opt.get(rid, {})
                iv = d.get("iv")
                error_code, error_text = self._app._opt_errors.get(rid, (None, ""))
                got_iv = bool(iv and 0.001 < iv < 5.0)
                attempt_rows.append({
                    "symbol": symbol,
                    "expiry": expiry_str,
                    "dte": dte,
                    "strike": strike,
                    "right": right,
                    "moneyness": round(strike / spot, 6),
                    "got_iv": got_iv,
                    "iv": round(iv * 100, 4) if got_iv else None,
                    "tick_type": d.get("tick_type"),
                    "error_code": error_code,
                    "error": error_text,
                })
                if got_iv:
                    rows.append({
                        "symbol":    symbol,
                        "expiry":    expiry_str,
                        "dte":       dte,
                        "strike":    strike,
                        "right":     right,
                        "iv":        round(iv * 100, 4),
                        "delta":     d.get("delta"),
                        "gamma":     d.get("gamma"),
                        "theta":     d.get("theta"),
                        "und_price": d.get("und_price") or spot,
                        "spot":      spot,
                        "moneyness": round(strike / spot, 6),
                    })

            batches_done += 1
            done = min(batch_start + batch_size, total)
            batch_got = sum(1 for r in attempt_rows[-len(batch):] if r["got_iv"])
            batch_errors = Counter(r["error_code"] for r in attempt_rows[-len(batch):] if r["error_code"])
            msg  = (
                f"Batch {done}/{total} ({done/total*100:.0f}%) — "
                f"{len(rows)} IV punten totaal, {batch_got}/{len(batch)} in batch"
            )
            print(f"  [collector] {msg}")
            if batch_errors:
                print(f"  [collector] Batch errors: {dict(batch_errors)}")
            if on_progress:
                on_progress(done, total, msg)

            if batches_done >= 3 and len(rows) == 0:
                print(
                    "  [collector] Geen IV data na 3 batches — afgebroken. "
                    "De chain/selectie is gelukt; IB gaf geen option-computation IV terug "
                    "(weekend, market-data permissies, of geen modeldata)."
                )
                break

        self.last_attempts = pd.DataFrame(attempt_rows)
        if attempt_rows:
            ok = sum(1 for r in attempt_rows if r["got_iv"])
            errors = Counter(r["error_code"] for r in attempt_rows if r["error_code"])
            print(f"  [collector] Result: {ok}/{len(attempt_rows)} contracts returned IV")
            if errors:
                print(f"  [collector] Result errors: {dict(errors)}")
            if not self.last_series.empty:
                by_expiry = self.last_attempts.groupby("expiry")["got_iv"].sum().to_dict()
                self.last_series["contracts_with_iv"] = (
                    self.last_series["expiry"].map(by_expiry).fillna(0).astype(int)
                )
        return pd.DataFrame(rows)

    def fetch_option_ivs(
        self,
        symbol:          str,
        currency:        str,
        spot:            float,
        params:          dict,
        opt_ref:         dict | None = None,
        dte_min:         int   = 3,
        dte_max:         int   = 60,
        moneyness_range: float = MONEYNESS_MAX,
        batch_size:      int   = 20,
        batch_timeout:   float = 14.0,
        max_strikes_per_expiry: int = MAX_STRIKES_PER_EXPIRY,
        on_progress=None,
    ) -> pd.DataFrame:
        contracts = self.build_contract_list(
            symbol, currency, spot, params, opt_ref,
            dte_min, dte_max, moneyness_range, max_strikes_per_expiry,
        )
        return self.fetch_iv_for_contracts(
            contracts, spot, symbol, currency,
            batch_size, batch_timeout, on_progress,
        )

    # ── parquet persistence ───────────────────────────────────────────────────

    @staticmethod
    def save_to_parquet(df: pd.DataFrame, symbol: str) -> Path:
        path = DATA_DIR / f"{symbol}_{date.today().isoformat()}.parquet"
        df.to_parquet(path, index=False)
        print(f"  [collector] Saved {len(df)} rows → {path.name}")
        return path

    @staticmethod
    def save_chain_to_parquet(params: dict, symbol: str, currency: str, port: int | None = None) -> Path:
        df = IbCollector.params_to_chain_df(params, symbol, currency, port=port)
        old_best = IbCollector.best_chain_path(symbol)
        if old_best:
            try:
                old_df = pd.read_parquet(old_best, columns=["expiry", "strike"])
                old_score = (int(old_df["expiry"].nunique()), int(len(old_df)))
                new_score = (int(df["expiry"].nunique()), int(len(df)))
                if new_score < old_score:
                    print(
                        "  [collector] WARNING: new chain is smaller than existing best "
                        f"({new_score[0]} expiries/{new_score[1]} pairs vs "
                        f"{old_score[0]} expiries/{old_score[1]} pairs in {Path(old_best).name})"
                    )
            except Exception as exc:
                print(f"  [collector] Could not compare existing chain quality: {exc}")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        source = str(params.get("source") or "unknown")
        path = DATA_DIR / f"{CHAIN_PREFIX}_{symbol}_{date.today().isoformat()}_{source}_p{port or 0}_{stamp}.parquet"
        df.to_parquet(path, index=False)
        print(f"  [collector] Saved chain {len(df)} pairs → {path.name}")
        return path

    @staticmethod
    def load_latest_chain(symbol: str) -> pd.DataFrame | None:
        path = IbCollector.best_chain_path(symbol)
        if not path:
            return None
        df = pd.read_parquet(path)
        print(f"  [collector] Loaded best chain {len(df)} pairs ← {Path(path).name}")
        return df

    @staticmethod
    def load_latest_parquet(symbol: str) -> pd.DataFrame | None:
        path = IbCollector.latest_parquet_path(symbol)
        if not path:
            return None
        df = pd.read_parquet(path)
        print(f"  [collector] Loaded {len(df)} rows ← {Path(path).name}")
        return df

    @staticmethod
    def latest_parquet_path(symbol: str) -> str | None:
        files = [
            p for p in sorted(DATA_DIR.glob(f"{symbol}_*.parquet"), reverse=True)
            if not p.name.startswith(f"{CHAIN_PREFIX}_")
        ]
        return str(files[0]) if files else None

    @staticmethod
    def latest_chain_path(symbol: str) -> str | None:
        files = sorted(DATA_DIR.glob(f"{CHAIN_PREFIX}_{symbol}_*.parquet"), reverse=True)
        return str(files[0]) if files else None

    @staticmethod
    def best_chain_path(symbol: str) -> str | None:
        files = sorted(DATA_DIR.glob(f"{CHAIN_PREFIX}_{symbol}_*.parquet"), reverse=True)
        best_path: Path | None = None
        best_score: tuple[int, int, float] = (-1, -1, -1.0)
        for path in files:
            try:
                df = pd.read_parquet(path, columns=["expiry", "strike"])
            except Exception:
                continue
            score = (int(df["expiry"].nunique()), int(len(df)), path.stat().st_mtime)
            if score > best_score:
                best_score = score
                best_path = path
        return str(best_path) if best_path else None

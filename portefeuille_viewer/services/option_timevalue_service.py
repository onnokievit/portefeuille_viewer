from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import polars as pl
import pyodbc
from PySide6.QtCore import QObject, QTimer, QMetaObject, Qt, Slot
from ibapi.contract import Contract

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals


_OPTION_TIMEVALUE_PERF_LOG = str(os.getenv("OPTION_TIMEVALUE_PERF_LOG", "1")).strip() == "1"


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        txt = _clean(v).replace(",", ".")
        try:
            return float(txt)
        except Exception:
            return None


def _pick_option_price(ticks: dict[str, float]) -> tuple[float | None, str | None]:
    b = _to_float(ticks.get("bid"))
    a = _to_float(ticks.get("ask"))
    if b is not None and a is not None and b > 0 and a > 0:
        return (b + a) / 2.0, "mid"
    for k in ("last", "delayed_last", "model_price", "close", "delayed_close"):
        v = _to_float(ticks.get(k))
        if v is not None and v > 0:
            return v, k
    return None, None


def _intrinsic(cp: str, strike: float, und: float) -> float:
    if cp == "call":
        return max(0.0, und - strike)
    return max(0.0, strike - und)


def _option_week(expiry: date) -> int:
    if expiry.weekday() != 4:  # Friday
        return 0
    fridays_before = 0
    for d in range(1, expiry.day):
        if date(expiry.year, expiry.month, d).weekday() == 4:
            fridays_before += 1
    return fridays_before + 1


@dataclass
class OpenSeriesRow:
    broker: str
    asset_rollup: str
    underlying_symbol: str
    ib_currency: str
    optie_call_put: str
    strike: float
    expiry: date
    qty_open: float
    exchange_code: str
    trading_class: str
    multiplier: float
    series_id: int | None = None
    conid: int | None = None
    resolver_locked: bool = False
    ref_mapping_found: bool = True
    ref_week: int = 0


class OptionTimevalueService(QObject):
    """Build live option time-value snapshot from open options + option_series_master."""

    _snapshot_rebuild_keys = {
        "aggregator_snapshot_load_open_opties_from_tx_live",
        "repository_snapshot_historical_close_latest",
        "repository_snapshot_asset_rollup_data",
        "repository_snapshot_optie_referentie_data",
    }
    _snapshot_publish_keys = {
        "aggregator_snapshot_aandelen_live",
    }
    _snapshot_clear_unresolved_keys = {
        "aggregator_snapshot_load_open_opties_from_tx_live",
        "repository_snapshot_optie_referentie_data",
    }

    def __init__(self, price_feed, stock_db_path: str, parent: QObject | None = None):
        super().__init__(parent)
        self.price_feed = price_feed
        self.stock_db_path = stock_db_path
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._rows: list[OpenSeriesRow] = []
        self._underlying_close: dict[str, float] = {}
        self._ticks: dict[int, dict[str, float]] = {}
        self._unresolved_series: dict[tuple[str, str, float, str, str], dict[str, Any]] = {}
        self._rebuild_inflight = False
        self._rebuild_queued = False
        self._pending_rebuild_result: dict[str, Any] | None = None
        self._resolve_wait_sec = max(
            0.1, float(os.getenv("OPTION_TIMEVALUE_RESOLVE_WAIT_SEC", "1.0"))
        )
        self._log_enabled = _clean(os.getenv("OPTION_TIMEVALUE_LOG", "0")) == "1"
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(350)
        self._rebuild_timer.timeout.connect(self._on_rebuild_timer_fired)
        self._publish_timer = QTimer(self)
        self._publish_timer.setSingleShot(True)
        self._publish_timer.setInterval(
            max(250, int(os.getenv("OPTION_TIMEVALUE_PUBLISH_DEBOUNCE_MS", "5000")))
        )
        self._publish_timer.timeout.connect(self._on_publish_timer_fired)
        self._full_publish_timer = QTimer(self)
        self._full_publish_timer.setInterval(
            max(1000, int(os.getenv("OPTION_TIMEVALUE_FULL_PUBLISH_MS", "60000")))
        )
        self._full_publish_timer.timeout.connect(self._on_full_publish_timer_fired)
        self._full_publish_timer.start()

        with contextlib.suppress(Exception):
            self.price_feed.optionTickUpdated.connect(self._on_option_tick)
        signals.ordersCommitted.connect(self.schedule_rebuild)
        signals.snapshotUpdated.connect(self._on_snapshot_updated)

        QTimer.singleShot(1500, self.schedule_rebuild)

    def _log(self, msg: str):
        if self._log_enabled:
            print(msg)

    def _on_rebuild_timer_fired(self):
        if _OPTION_TIMEVALUE_PERF_LOG:
            print("[option-timevalue] timer=rebuild fired")
        self._rebuild_universe()

    def _on_publish_timer_fired(self):
        if _OPTION_TIMEVALUE_PERF_LOG:
            print("[option-timevalue] timer=publish fired")
        self._publish_snapshot(trigger="publish_timer")

    def _on_full_publish_timer_fired(self):
        if _OPTION_TIMEVALUE_PERF_LOG:
            print("[option-timevalue] timer=full_publish fired")
        self._publish_snapshot(trigger="full_publish_timer")

    def schedule_rebuild(self, payload: dict | None = None):
        with self._state_lock:
            if self._rebuild_inflight:
                self._rebuild_queued = True
                return
        self._rebuild_timer.start()

    def shutdown(self):
        if self._rebuild_timer.isActive():
            self._rebuild_timer.stop()
        if self._publish_timer.isActive():
            self._publish_timer.stop()
        if self._full_publish_timer.isActive():
            self._full_publish_timer.stop()

    def reset_for_database_change(self) -> None:
        if self._rebuild_timer.isActive():
            self._rebuild_timer.stop()
        if self._publish_timer.isActive():
            self._publish_timer.stop()
        if self._full_publish_timer.isActive():
            self._full_publish_timer.stop()
        with self._lock:
            self._rows = []
            self._underlying_close = {}
            self._ticks = {}
        with self._state_lock:
            self._rebuild_inflight = False
            self._rebuild_queued = False
            self._pending_rebuild_result = None
        self._clear_unresolved("database_change")
        SNAPSHOT_STORE.safe_write(
            "snapshot_optie_timevalue_live",
            pl.DataFrame(
                schema={
                    "broker": pl.Utf8,
                    "asset": pl.Utf8,
                    "exp": pl.Date,
                    "c_p": pl.Utf8,
                    "strike": pl.Float64,
                    "qty_open": pl.Float64,
                    "mult": pl.Float64,
                    "ccy": pl.Utf8,
                    "last_px": pl.Float64,
                    "px_source": pl.Utf8,
                    "bid": pl.Float64,
                    "ask": pl.Float64,
                    "und_px": pl.Float64,
                    "intrinsic": pl.Float64,
                    "time_per_unit": pl.Float64,
                    "time_total": pl.Float64,
                    "iv": pl.Float64,
                    "delta": pl.Float64,
                    "gamma": pl.Float64,
                    "theta": pl.Float64,
                    "series_id": pl.Int64,
                    "conid": pl.Int64,
                }
            ),
        )
        SNAPSHOT_STORE.safe_write(
            "snapshot_optie_timevalue_summary",
            pl.DataFrame(schema={"ccy": pl.Utf8, "time_value_abs": pl.Float64}),
        )
        SNAPSHOT_STORE.safe_write(
            "snapshot_optie_timevalue_meta",
            pl.DataFrame(
                schema={
                    "ts": pl.Utf8,
                    "priced": pl.Int64,
                    "total": pl.Int64,
                    "unresolved_count": pl.Int64,
                    "unresolved_series": pl.Utf8,
                }
            ),
        )
        self._full_publish_timer.start()

    def _on_snapshot_updated(self, snapshot_key: str):
        if snapshot_key in self._snapshot_rebuild_keys:
            if snapshot_key in self._snapshot_clear_unresolved_keys:
                self._clear_unresolved("snapshot_update")
            self.schedule_rebuild()
            return
        if snapshot_key in self._snapshot_publish_keys:
            self._publish_timer.start()

    def _clear_unresolved(self, reason: str):
        if self._unresolved_series:
            self._unresolved_series.clear()
            self._log(f"[option-timevalue] unresolved cache cleared ({reason})")

    @staticmethod
    def _series_key(r: OpenSeriesRow) -> tuple[str, str, float, str, str]:
        return (
            _clean(r.asset_rollup).upper(),
            r.expiry.isoformat() if isinstance(r.expiry, date) else _clean(r.expiry),
            round(float(r.strike), 6),
            _clean(r.optie_call_put).lower(),
            _clean(r.ib_currency).upper(),
        )

    def _set_unresolved(self, r: OpenSeriesRow, reason: str, hint: str = ""):
        key = self._series_key(r)
        self._unresolved_series[key] = {
            "asset": key[0],
            "exp": key[1],
            "strike": key[2],
            "c_p": key[3],
            "ccy": key[4],
            "reason": reason,
            "hint": hint,
            "updated_at": _now_ts(),
        }

    def _clear_unresolved_for_resolved_rows(self, rows: list[OpenSeriesRow]):
        for r in rows:
            if r.conid and int(r.conid) > 0:
                self._unresolved_series.pop(self._series_key(r), None)

    def _on_option_tick(self, payload: dict):
        try:
            sid = int(payload.get("series_id"))
        except Exception:
            return
        field = _clean(payload.get("field"))
        with self._lock:
            d = self._ticks.setdefault(sid, {})
            if field:
                val = _to_float(payload.get("value"))
                if val is not None:
                    d[field] = val
            for gk in ("iv", "delta", "gamma", "theta", "vega", "model_price", "underlying_price"):
                gv = _to_float(payload.get(gk))
                if gv is not None:
                    d[gk] = gv
        self._publish_timer.start()

    def _connect_stockdb(self):
        return pyodbc.connect(
            rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={self.stock_db_path}"
        )

    def _ensure_option_series_master_columns(self, cur) -> None:
        # Additive-only schema hardening for manual resolver workflow.
        try:
            cur.execute("ALTER TABLE option_series_master ADD COLUMN resolver_locked YESNO")
        except Exception:
            pass
        try:
            cur.execute("UPDATE option_series_master SET resolver_locked=False WHERE resolver_locked IS NULL")
        except Exception:
            pass

    def list_unresolved_series(self) -> list[dict[str, Any]]:
        try:
            return list(self._unresolved_series.values())
        except Exception:
            return []

    def _asset_symbol_from_snapshot(self, asset_rollup: str) -> str:
        try:
            df = SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
            if df is None or df.is_empty():
                return asset_rollup
            m = (
                df.filter(pl.col("asset_rollup").cast(pl.Utf8) == asset_rollup)
                .select(["ib_symbol"])
                .to_dicts()
            )
            if m:
                return _clean(m[0].get("ib_symbol")) or asset_rollup
        except Exception:
            pass
        return asset_rollup

    def get_manual_resolve_candidates(self, unresolved_item: dict[str, Any]) -> list[dict[str, Any]]:
        if not hasattr(self.price_feed, "_feed") or self.price_feed._feed is None:
            return []
        try:
            asset = _clean(unresolved_item.get("asset")).upper()
            cp = _clean(unresolved_item.get("c_p")).lower()
            ccy = _clean(unresolved_item.get("ccy")).upper()
            strike = float(unresolved_item.get("strike"))
            exp = date.fromisoformat(_clean(unresolved_item.get("exp")))
            right = "C" if cp == "call" else "P"
        except Exception:
            return []
        symbol = self._asset_symbol_from_snapshot(asset) or asset
        details_holder = []
        done = threading.Event()
        ib = self.price_feed._feed

        def on_detail(cd):
            details_holder.append(cd)

        def on_end():
            done.set()

        for sec_type, exch in [
            ("OPT", "SMART"),
            ("OPT", "FTA"),
            ("FOP", "SMART"),
            ("FOP", "FTA"),
        ]:
            c = Contract()
            c.secType = sec_type
            c.symbol = symbol
            c.currency = ccy
            c.exchange = exch
            c.lastTradeDateOrContractMonth = exp.strftime("%Y%m%d")
            c.strike = float(strike)
            c.right = right
            details_holder.clear()
            done.clear()
            with contextlib.suppress(Exception):
                ib.request_contract_details(c, on_detail, on_end)
            done.wait(timeout=max(self._resolve_wait_sec, 1.2))
            if details_holder:
                break

        out: list[dict[str, Any]] = []
        seen: set[int] = set()
        for det in details_holder:
            con = getattr(det, "contract", None)
            if con is None:
                continue
            try:
                conid = int(getattr(con, "conId", 0) or 0)
            except Exception:
                conid = 0
            if conid <= 0 or conid in seen:
                continue
            seen.add(conid)
            out.append(
                {
                    "conid": conid,
                    "local_symbol": _clean(getattr(con, "localSymbol", "")),
                    "trading_class": _clean(getattr(con, "tradingClass", "")),
                    "exchange_code": _clean(getattr(con, "exchange", "")) or "SMART",
                    "multiplier": _to_float(getattr(con, "multiplier", None)) or 100.0,
                    "underlying_symbol": _clean(getattr(con, "symbol", "")) or symbol,
                    "sec_type": _clean(getattr(con, "secType", "")),
                    "last_trade_date": _clean(getattr(con, "lastTradeDateOrContractMonth", "")),
                    "currency": _clean(getattr(con, "currency", "")) or ccy,
                }
            )
        return out

    def apply_manual_resolution(self, unresolved_item: dict[str, Any], candidate: dict[str, Any], lock_row: bool = True) -> tuple[bool, str]:
        try:
            asset = _clean(unresolved_item.get("asset")).upper()
            cp = _clean(unresolved_item.get("c_p")).lower()
            ccy = _clean(unresolved_item.get("ccy")).upper()
            strike = float(unresolved_item.get("strike"))
            exp = date.fromisoformat(_clean(unresolved_item.get("exp")))
            conid = int(candidate.get("conid") or 0)
            if conid <= 0:
                return False, "Geen geldige conid geselecteerd."
            local_symbol = _clean(candidate.get("local_symbol"))
            trading_class = _clean(candidate.get("trading_class")).upper()
            exchange_code = _clean(candidate.get("exchange_code")).upper() or "SMART"
            multiplier = _to_float(candidate.get("multiplier")) or 100.0
            underlying_symbol = _clean(candidate.get("underlying_symbol")) or self._asset_symbol_from_snapshot(asset)
        except Exception as exc:
            return False, f"Ongeldige selectie: {exc}"

        try:
            now = datetime.now()
            with self._connect_stockdb() as conn:
                cur = conn.cursor()
                self._ensure_option_series_master_columns(cur)
                rec = cur.execute(
                    """
                    SELECT TOP 1 series_id
                    FROM option_series_master
                    WHERE asset_rollup=? AND optie_call_put=? AND strike=? AND expiry=? AND ib_currency=?
                    """,
                    (asset, cp, strike, exp, ccy),
                ).fetchone()
                if not rec:
                    return False, "Serie niet gevonden in option_series_master."
                cur.execute(
                    """
                    UPDATE option_series_master
                    SET conid=?, local_symbol=?, trading_class=?, exchange_code=?, multiplier=?,
                        underlying_symbol=?, source_tag=?, resolver_locked=?, active=?, last_verified_ts=?, updated_at=?
                    WHERE series_id=?
                    """,
                    (
                        conid,
                        local_symbol or None,
                        trading_class or None,
                        exchange_code or None,
                        multiplier,
                        underlying_symbol or None,
                        "resolver_manual",
                        bool(lock_row),
                        True,
                        now,
                        now,
                        int(rec[0]),
                    ),
                )
                conn.commit()

            key = (asset, exp.isoformat(), round(float(strike), 6), cp, ccy)
            with contextlib.suppress(Exception):
                self._unresolved_series.pop(key, None)
            self.schedule_rebuild()
            return True, "Handmatige resolve opgeslagen."
        except Exception as exc:
            return False, f"Opslaan mislukt: {exc}"

    def _extract_open_series(self) -> list[OpenSeriesRow]:
        df = SNAPSHOT_STORE.aggregator_snapshot_load_open_opties_from_tx_live
        if df is None or df.is_empty():
            df = SNAPSHOT_STORE.repository_snapshot_load_open_opties
        if df is None or df.is_empty():
            return []

        required = {"broker", "asset_rollup", "optie_call_put", "optie_strike", "optie_exp_date", "SomVantransactie_aantal"}
        if not required.issubset(set(df.columns)):
            return []

        asset_map = SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
        if asset_map is None or asset_map.is_empty():
            return []
        m = asset_map.select(["asset_rollup", "ib_symbol", "ib_currency"]).rename({"ib_symbol": "underlying_symbol"})
        merged = (
            df.select([
                "broker",
                "asset_rollup",
                "optie_call_put",
                "optie_strike",
                "optie_exp_date",
                "SomVantransactie_aantal",
            ])
            .with_columns([
                pl.col("broker").cast(pl.Utf8).str.to_lowercase().alias("broker"),
                pl.col("asset_rollup").cast(pl.Utf8).alias("asset_rollup"),
                pl.col("optie_call_put").cast(pl.Utf8).str.to_lowercase().alias("optie_call_put"),
                pl.col("optie_strike").cast(pl.Float64).alias("strike"),
                pl.col("SomVantransactie_aantal").cast(pl.Float64).alias("qty_open"),
                pl.col("optie_exp_date").cast(pl.Date).alias("expiry"),
            ])
            .drop(["optie_strike", "SomVantransactie_aantal", "optie_exp_date"])
            .join(m, on="asset_rollup", how="left")
            .drop_nulls(["asset_rollup", "optie_call_put", "strike", "expiry", "ib_currency"])
            .filter(pl.col("qty_open") != 0)
            .unique(subset=["broker", "asset_rollup", "optie_call_put", "strike", "expiry"], keep="last")
        )

        ref_map = self._build_opt_ref_map()
        out: list[OpenSeriesRow] = []
        for r in merged.to_dicts():
            expiry = r.get("expiry")
            if not isinstance(expiry, date):
                continue
            asset_rollup = _clean(r.get("asset_rollup"))
            week = _option_week(expiry)
            exact = ref_map.get((asset_rollup, week))
            fallback = ref_map.get((asset_rollup, 0))
            ref = exact or fallback or {}
            ref_found = bool(exact or fallback)
            mult = _to_float(ref.get("opt_multiplier"))
            out.append(
                OpenSeriesRow(
                    broker=_clean(r.get("broker")).lower(),
                    asset_rollup=asset_rollup,
                    underlying_symbol=_clean(r.get("underlying_symbol")) or asset_rollup,
                    ib_currency=_clean(r.get("ib_currency")).upper(),
                    optie_call_put=_clean(r.get("optie_call_put")).lower(),
                    strike=float(r.get("strike")),
                    expiry=expiry,
                    qty_open=float(r.get("qty_open")),
                    exchange_code=_clean(ref.get("opt_exchange")).upper() or "SMART",
                    trading_class=_clean(ref.get("opt_tradingclass")).upper(),
                    multiplier=float(mult) if mult is not None else 100.0,
                    ref_mapping_found=ref_found,
                    ref_week=int(week),
                )
            )
        return out

    def _build_opt_ref_map(self) -> dict[tuple[str, int], dict]:
        ref = SNAPSHOT_STORE.repository_snapshot_optie_referentie_data
        if ref is None or ref.is_empty():
            return {}
        cols = set(ref.columns)
        if not {"asset_rollup", "opt_week"}.issubset(cols):
            return {}
        out = {}
        for r in ref.to_dicts():
            asset = _clean(r.get("asset_rollup"))
            try:
                week = int(r.get("opt_week"))
            except Exception:
                week = 0
            out[(asset, week)] = r
        return out

    def _upsert_master_and_resolve(self, rows: list[OpenSeriesRow]) -> list[OpenSeriesRow]:
        if not rows:
            return []
        now = datetime.now()
        with self._connect_stockdb() as conn:
            cur = conn.cursor()
            self._ensure_option_series_master_columns(cur)
            for r in rows:
                ex = cur.execute(
                    """
                    SELECT TOP 1 series_id, conid, local_symbol, multiplier, underlying_symbol, exchange_code, trading_class, resolver_locked
                    FROM option_series_master
                    WHERE asset_rollup=?
                      AND optie_call_put=?
                      AND strike=?
                      AND expiry=?
                      AND ib_currency=?
                    """,
                    (r.asset_rollup, r.optie_call_put, r.strike, r.expiry, r.ib_currency),
                ).fetchone()
                if ex is None:
                    cur.execute(
                        """
                        INSERT INTO option_series_master (
                            asset_rollup, underlying_symbol, strike, expiry,
                            exchange_code, trading_class, multiplier, ib_currency,
                            optie_call_put, source_tag, resolver_locked, active, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            r.asset_rollup,
                            r.underlying_symbol or None,
                            r.strike,
                            r.expiry,
                            r.exchange_code or None,
                            r.trading_class or None,
                            r.multiplier,
                            r.ib_currency,
                            r.optie_call_put,
                            "resolver_auto",
                            False,
                            True,
                            now,
                            now,
                        ),
                    )
                else:
                    is_locked = bool(ex[7]) if ex[7] is not None else False
                    if is_locked:
                        # Respect manual lock: do not overwrite mapping fields.
                        continue
                    merged_underlying = r.underlying_symbol or _clean(ex[4]) or None
                    merged_exchange = r.exchange_code or _clean(ex[5]) or None
                    merged_trading_class = r.trading_class or _clean(ex[6]) or None
                    merged_multiplier = r.multiplier if r.multiplier is not None else (_to_float(ex[3]) or 100.0)
                    cur.execute(
                        """
                        UPDATE option_series_master
                        SET underlying_symbol=?, exchange_code=?, trading_class=?,
                            multiplier=?, source_tag=?, active=?, updated_at=?
                        WHERE series_id=?
                        """,
                        (
                            merged_underlying,
                            merged_exchange,
                            merged_trading_class,
                            merged_multiplier,
                            "resolver_auto",
                            True,
                            now,
                            int(ex[0]),
                        ),
                    )
            conn.commit()

            db_rows = []
            for r in rows:
                rec = cur.execute(
                    """
                    SELECT TOP 1 series_id, conid, local_symbol, multiplier, exchange_code, trading_class, resolver_locked
                    FROM option_series_master
                    WHERE asset_rollup=?
                      AND optie_call_put=?
                      AND strike=?
                      AND expiry=?
                      AND ib_currency=?
                    """,
                    (r.asset_rollup, r.optie_call_put, r.strike, r.expiry, r.ib_currency),
                ).fetchone()
                if not rec:
                    continue
                r.series_id = int(rec[0])
                r.conid = int(rec[1]) if rec[1] is not None else None
                rec_mult = _to_float(rec[3])
                if rec_mult is not None:
                    r.multiplier = float(rec_mult)
                if _clean(rec[4]):
                    r.exchange_code = _clean(rec[4]).upper()
                if _clean(rec[5]):
                    r.trading_class = _clean(rec[5]).upper()
                r.resolver_locked = bool(rec[6]) if rec[6] is not None else False
                db_rows.append(r)

            resolve_candidates: list[OpenSeriesRow] = []
            for r in db_rows:
                if r.conid and int(r.conid) > 0:
                    continue
                if r.resolver_locked:
                    # Manual lock means resolver should not mutate this row.
                    continue
                key = self._series_key(r)
                if not r.ref_mapping_found:
                    self._set_unresolved(
                        r,
                        "missing_reference_mapping",
                        f"Voeg optie_referentie_data mapping toe voor asset={r.asset_rollup}, opt_week={r.ref_week}",
                    )
                    continue
                # Stop met opnieuw proberen totdat relevante referentie/universe snapshot wijzigt.
                if key in self._unresolved_series:
                    continue
                resolve_candidates.append(r)
            if resolve_candidates:
                failed = self._resolve_contracts(resolve_candidates)
                for r in resolve_candidates:
                    reason = failed.get(self._series_key(r))
                    if reason:
                        self._set_unresolved(
                            r,
                            reason,
                            "Controleer optie_referentie_data (trading class/exchange) of IB contractdetails",
                        )
                conn.commit()

            # Reload after resolve
            final_rows = []
            for r in db_rows:
                rec = cur.execute(
                    """
                    SELECT TOP 1 series_id, conid, multiplier, exchange_code
                    FROM option_series_master
                    WHERE series_id=?
                    """,
                    (int(r.series_id),),
                ).fetchone()
                if not rec:
                    continue
                r.conid = int(rec[1]) if rec[1] is not None else None
                mult = _to_float(rec[2])
                if mult is not None:
                    r.multiplier = mult
                if _clean(rec[3]):
                    r.exchange_code = _clean(rec[3]).upper()
                final_rows.append(r)
            self._clear_unresolved_for_resolved_rows(final_rows)
        return final_rows

    def _resolve_contracts(self, rows: list[OpenSeriesRow]) -> dict[tuple[str, str, float, str, str], str]:
        failed: dict[tuple[str, str, float, str, str], str] = {}
        if not rows:
            return failed
        if not hasattr(self.price_feed, "_feed") or self.price_feed._feed is None:
            for r in rows:
                failed[self._series_key(r)] = "no_contract_details"
            return failed
        ib = self.price_feed._feed
        with self._connect_stockdb() as conn:
            cur = conn.cursor()
            now = datetime.now()
            for r in rows:
                details_holder = []
                done = threading.Event()

                def on_detail(cd):
                    details_holder.append(cd)

                def on_end():
                    done.set()

                for sec_type, use_tc, exch in [
                    ("OPT", True, r.exchange_code),
                    ("OPT", False, r.exchange_code),
                    ("OPT", True, "SMART"),
                    ("OPT", False, "SMART"),
                    ("FOP", True, r.exchange_code),
                    ("FOP", False, r.exchange_code),
                    ("FOP", True, "SMART"),
                    ("FOP", False, "SMART"),
                ]:
                    c = Contract()
                    c.secType = sec_type
                    c.symbol = r.underlying_symbol
                    c.currency = r.ib_currency
                    c.exchange = exch or "SMART"
                    c.lastTradeDateOrContractMonth = r.expiry.strftime("%Y%m%d")
                    c.strike = float(r.strike)
                    c.right = "C" if r.optie_call_put == "call" else "P"
                    if use_tc and r.trading_class:
                        c.tradingClass = r.trading_class
                    details_holder.clear()
                    done.clear()
                    with contextlib.suppress(Exception):
                        ib.request_contract_details(c, on_detail, on_end)
                    done.wait(timeout=self._resolve_wait_sec)
                    if details_holder:
                        break

                if not details_holder:
                    failed[self._series_key(r)] = "timeout" if not done.is_set() else "no_contract_details"
                    continue
                det = details_holder[0]
                con = det.contract
                conid = int(getattr(con, "conId", 0) or 0)
                if conid <= 0:
                    failed[self._series_key(r)] = "no_contract_details"
                    continue
                local_symbol = _clean(getattr(con, "localSymbol", ""))
                tc = _clean(getattr(con, "tradingClass", ""))
                exch = _clean(getattr(con, "exchange", ""))
                mult = _to_float(getattr(con, "multiplier", None))
                cur.execute(
                    """
                    UPDATE option_series_master
                    SET conid=?, local_symbol=?, trading_class=?, exchange_code=?,
                        multiplier=?, last_verified_ts=?, updated_at=?
                    WHERE series_id=?
                    """,
                    (
                        conid,
                        local_symbol or None,
                        tc or None,
                        exch or None,
                        mult,
                        now,
                        now,
                        int(r.series_id),
                    ),
                )
            conn.commit()
        return failed

    def _load_underlying_close_map(self) -> dict[str, float]:
        h = getattr(SNAPSHOT_STORE, "repository_snapshot_historical_close_latest", None)
        if h is None or h.is_empty():
            return {}
        try:
            return {
                _clean(r.get("asset_rollup")): float(r.get("close_price"))
                for r in h.select([
                    pl.col("asset_rollup").cast(pl.Utf8),
                    pl.col("close_price").cast(pl.Float64),
                ]).to_dicts()
                if r.get("asset_rollup") is not None and r.get("close_price") is not None
            }
        except Exception:
            return {}

    def _rebuild_universe(self):
        with self._state_lock:
            if self._rebuild_inflight:
                self._rebuild_queued = True
                return
            self._rebuild_inflight = True
        th = threading.Thread(target=self._rebuild_universe_worker, daemon=True)
        th.start()

    def _rebuild_universe_worker(self):
        try:
            rows = self._extract_open_series()
            rows = self._upsert_master_and_resolve(rows)
            subs = [
                (int(r.series_id), int(r.conid), r.exchange_code, r.ib_currency)
                for r in rows
                if r.series_id and r.conid and int(r.conid) > 0
            ]
            close_map = self._load_underlying_close_map()
            with self._state_lock:
                self._pending_rebuild_result = {
                    "rows": rows,
                    "subs": subs,
                    "close_map": close_map,
                    "error": None,
                }
        except Exception as exc:
            with self._state_lock:
                self._pending_rebuild_result = {
                    "rows": [],
                    "subs": [],
                    "close_map": {},
                    "error": str(exc),
                }
        with contextlib.suppress(Exception):
            QMetaObject.invokeMethod(self, "_apply_rebuild_result", Qt.QueuedConnection)

    @Slot()
    def _apply_rebuild_result(self):
        with self._state_lock:
            result = self._pending_rebuild_result
            self._pending_rebuild_result = None
        if not result:
            with self._state_lock:
                self._rebuild_inflight = False
            return

        err = result.get("error")
        if err:
            print(f"[option-timevalue] rebuild failed: {err}")
        else:
            self._underlying_close = result.get("close_map") or {}
            self._rows = result.get("rows") or []
            subs = result.get("subs") or []
            if subs:
                with contextlib.suppress(Exception):
                    self.price_feed.ensure_option_subscriptions(subs)
            self._publish_snapshot(trigger="rebuild_apply")
            self._log(
                f"[option-timevalue] universe refreshed: open_series={len(self._rows)} "
                f"subscribed={len(subs)} @ {_now_ts()}"
            )

        queued = False
        with self._state_lock:
            self._rebuild_inflight = False
            queued = self._rebuild_queued
            self._rebuild_queued = False
        if queued:
            self._rebuild_timer.start()

    def _publish_snapshot(self, trigger: str = "direct"):
        t0 = time.perf_counter()
        rows = self._rows or []
        if not rows:
            SNAPSHOT_STORE.safe_write("snapshot_optie_timevalue_live", pl.DataFrame())
            SNAPSHOT_STORE.safe_write("snapshot_optie_timevalue_summary", pl.DataFrame())
            SNAPSHOT_STORE.safe_write(
                "snapshot_optie_timevalue_meta",
                pl.DataFrame(
                    [
                        {
                            "ts": _now_ts(),
                            "priced": 0,
                            "total": 0,
                            "unresolved_count": len(self._unresolved_series),
                            "unresolved_series": json.dumps(list(self._unresolved_series.values()), ensure_ascii=False),
                        }
                    ]
                ),
            )
            if _OPTION_TIMEVALUE_PERF_LOG:
                print(
                    f"[option-timevalue] publish trigger={trigger} total_ms={(time.perf_counter() - t0) * 1000.0:.1f} rows=0 priced=0"
                )
            return

        output = []
        by_ccy = defaultdict(float)
        priced = 0
        with self._lock:
            live_prices = SNAPSHOT_STORE.get_live_prices_snapshot()

        def _live_underlying_px(symbol: str, ccy: str) -> float | None:
            sym = _clean(symbol).upper()
            cur = _clean(ccy).upper()
            if not sym:
                return None
            keys = [
                (sym, cur),
                (sym, None),
                sym,
            ]
            for k in keys:
                v = _to_float(live_prices.get(k))
                if v is not None and v > 0:
                    return v
            return None

        for r in rows:
            sid = int(r.series_id or 0)
            with self._lock:
                tick = dict(self._ticks.get(sid, {}))
            # Fallback op laatst bekende optieprijs uit DB-cache wanneer live tick ontbreekt
            # of wanneer specifieke velden nog niet gevuld zijn (bijv. buiten markttijd).
            fallback = None
            with contextlib.suppress(Exception):
                fallback = self.price_feed.get_option_last(sid)
            if fallback:
                for src_key, dst_key in (
                    ("bid", "bid"),
                    ("ask", "ask"),
                    ("last_px", "last"),
                    ("px_source", "px_source"),
                    ("underlying_price", "underlying_price"),
                    ("iv", "iv"),
                    ("delta", "delta"),
                    ("gamma", "gamma"),
                    ("theta", "theta"),
                ):
                    if tick.get(dst_key) is None and fallback.get(src_key) is not None:
                        tick[dst_key] = fallback.get(src_key)
            px, px_source = _pick_option_price(tick)
            if px is not None:
                priced += 1
            # Onderliggende koers prioriteit:
            # 1) centrale live_prices (zelfde methodiek als Aandelen-tab)
            # 2) option tick underlying_price
            # 3) close-map fallback
            und = _live_underlying_px(r.underlying_symbol or r.asset_rollup, r.ib_currency)
            if und is None:
                und = _to_float(tick.get("underlying_price"))
            if und is None:
                und = self._underlying_close.get(r.asset_rollup)
            intrinsic = None
            time_per = None
            time_total = None
            if px is not None and und is not None:
                intrinsic = _intrinsic(r.optie_call_put, float(r.strike), float(und))
                time_per = max(0.0, float(px) - float(intrinsic))
                # Signed richting:
                # - short (qty_open < 0) => positieve "te oogsten" tijdswaarde
                # - long  (qty_open > 0) => negatieve tijdswaarde-exposure
                # qty_open is already in onderliggende eenheden; waarde-exposure is daarom:
                # time_per_unit * qty_open (multiplier valt algebraisch weg).
                # Dit werkt ook voor niet-100 multipliers.
                time_total = -time_per * float(r.qty_open)
                by_ccy[r.ib_currency] += float(time_total)

            output.append(
                {
                    "broker": r.broker,
                    "asset": r.asset_rollup,
                    "exp": r.expiry,
                    "c_p": r.optie_call_put,
                    "strike": float(r.strike),
                    "qty_open": float(r.qty_open),
                    "mult": float(r.multiplier),
                    "ccy": r.ib_currency,
                    "last_px": px,
                    "px_source": px_source,
                    "bid": _to_float(tick.get("bid")),
                    "ask": _to_float(tick.get("ask")),
                    "und_px": und,
                    "intrinsic": intrinsic,
                    "time_per_unit": time_per,
                    "time_total": time_total,
                    "iv": _to_float(tick.get("iv")),
                    "delta": _to_float(tick.get("delta")),
                    "gamma": _to_float(tick.get("gamma")),
                    "theta": _to_float(tick.get("theta")),
                    "series_id": sid,
                    "conid": int(r.conid or 0),
                }
            )

        live_schema = {
            "broker": pl.Utf8,
            "asset": pl.Utf8,
            "exp": pl.Date,
            "c_p": pl.Utf8,
            "strike": pl.Float64,
            "qty_open": pl.Float64,
            "mult": pl.Float64,
            "ccy": pl.Utf8,
            "last_px": pl.Float64,
            "px_source": pl.Utf8,
            "bid": pl.Float64,
            "ask": pl.Float64,
            "und_px": pl.Float64,
            "intrinsic": pl.Float64,
            "time_per_unit": pl.Float64,
            "time_total": pl.Float64,
            "iv": pl.Float64,
            "delta": pl.Float64,
            "gamma": pl.Float64,
            "theta": pl.Float64,
            "series_id": pl.Int64,
            "conid": pl.Int64,
        }
        live_df = pl.from_dicts(
            output,
            schema=live_schema,
            infer_schema_length=None,
        ).sort(["asset", "exp", "c_p", "strike"])
        summary_df = pl.from_dicts(
            [{"ccy": ccy, "time_value_abs": val} for ccy, val in sorted(by_ccy.items())],
            schema={"ccy": pl.Utf8, "time_value_abs": pl.Float64},
            infer_schema_length=None,
        )
        SNAPSHOT_STORE.safe_write("snapshot_optie_timevalue_live", live_df)
        SNAPSHOT_STORE.safe_write("snapshot_optie_timevalue_summary", summary_df)
        SNAPSHOT_STORE.safe_write(
            "snapshot_optie_timevalue_meta",
            pl.DataFrame(
                [
                    {
                        "ts": _now_ts(),
                        "priced": priced,
                        "total": len(output),
                        "unresolved_count": len(self._unresolved_series),
                        "unresolved_series": json.dumps(list(self._unresolved_series.values()), ensure_ascii=False),
                    }
                ]
            ),
        )
        if _OPTION_TIMEVALUE_PERF_LOG:
            print(
                f"[option-timevalue] publish trigger={trigger} total_ms={(time.perf_counter() - t0) * 1000.0:.1f} rows={len(output)} priced={priced} unresolved={len(self._unresolved_series)}"
            )

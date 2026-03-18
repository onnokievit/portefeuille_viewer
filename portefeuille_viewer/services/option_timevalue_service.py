from __future__ import annotations

import contextlib
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import polars as pl
import pyodbc
from PySide6.QtCore import QObject, QTimer
from ibapi.contract import Contract

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals


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


def _pick_option_price(ticks: dict[str, float]) -> float | None:
    for k in ("last", "delayed_last", "close", "delayed_close"):
        v = _to_float(ticks.get(k))
        if v is not None and v > 0:
            return v
    b = _to_float(ticks.get("bid"))
    a = _to_float(ticks.get("ask"))
    if b is not None and a is not None and b > 0 and a > 0:
        return (b + a) / 2.0
    return None


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


class OptionTimevalueService(QObject):
    """Build live option time-value snapshot from open options + option_series_master."""

    def __init__(self, price_feed, stock_db_path: str, parent: QObject | None = None):
        super().__init__(parent)
        self.price_feed = price_feed
        self.stock_db_path = stock_db_path
        self._lock = threading.Lock()
        self._rows: list[OpenSeriesRow] = []
        self._underlying_close: dict[str, float] = {}
        self._ticks: dict[int, dict[str, float]] = {}
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(350)
        self._rebuild_timer.timeout.connect(self._rebuild_universe)
        self._publish_timer = QTimer(self)
        self._publish_timer.setSingleShot(True)
        self._publish_timer.setInterval(300)
        self._publish_timer.timeout.connect(self._publish_snapshot)
        self._full_publish_timer = QTimer(self)
        self._full_publish_timer.setInterval(1500)
        self._full_publish_timer.timeout.connect(self._publish_snapshot)
        self._full_publish_timer.start()

        with contextlib.suppress(Exception):
            self.price_feed.optionTickUpdated.connect(self._on_option_tick)
        signals.ordersCommitted.connect(self.schedule_rebuild)
        signals.databaseChanged.connect(lambda _db: self.schedule_rebuild())
        signals.snapshotUpdated.connect(self._on_snapshot_updated)

        QTimer.singleShot(1500, self.schedule_rebuild)

    def schedule_rebuild(self):
        self._rebuild_timer.start()

    def shutdown(self):
        if self._rebuild_timer.isActive():
            self._rebuild_timer.stop()
        if self._publish_timer.isActive():
            self._publish_timer.stop()
        if self._full_publish_timer.isActive():
            self._full_publish_timer.stop()

    def _on_snapshot_updated(self, snapshot_key: str):
        if snapshot_key in {
            "aggregator_snapshot_load_open_opties_from_tx_live",
            "repository_snapshot_load_open_opties",
            "repository_snapshot_historical_close",
            "repository_snapshot_asset_rollup_data",
            "repository_snapshot_optie_referentie_data",
        }:
            self.schedule_rebuild()

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
            ref = ref_map.get((asset_rollup, week)) or ref_map.get((asset_rollup, 0)) or {}
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
            for r in rows:
                ex = cur.execute(
                    """
                    SELECT TOP 1 series_id, conid, local_symbol, multiplier
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
                            optie_call_put, source_tag, active, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                            "position",
                            True,
                            now,
                            now,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE option_series_master
                        SET underlying_symbol=?, exchange_code=?, trading_class=?,
                            multiplier=?, source_tag=?, active=?, updated_at=?
                        WHERE series_id=?
                        """,
                        (
                            r.underlying_symbol or None,
                            r.exchange_code or None,
                            r.trading_class or None,
                            r.multiplier,
                            "position",
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
                    SELECT TOP 1 series_id, conid, local_symbol, multiplier, exchange_code, trading_class
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
                db_rows.append(r)

            unresolved = [r for r in db_rows if not r.conid]
            if unresolved:
                self._resolve_contracts(unresolved)
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
        return final_rows

    def _resolve_contracts(self, rows: list[OpenSeriesRow]):
        if not rows:
            return
        if not hasattr(self.price_feed, "_feed") or self.price_feed._feed is None:
            return
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
                    done.wait(timeout=5.0)
                    if details_holder:
                        break

                if not details_holder:
                    continue
                det = details_holder[0]
                con = det.contract
                conid = int(getattr(con, "conId", 0) or 0)
                if conid <= 0:
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

    def _load_underlying_close_map(self) -> dict[str, float]:
        h = SNAPSHOT_STORE.repository_snapshot_historical_close
        if h is None or h.is_empty():
            return {}
        try:
            latest = (
                h.select([
                    pl.col("asset_rollup").cast(pl.Utf8),
                    pl.col("datum").cast(pl.Date),
                    pl.col("close_price").cast(pl.Float64),
                ])
                .sort(["asset_rollup", "datum"])
                .group_by("asset_rollup")
                .agg(pl.col("close_price").last().alias("close_price"))
            )
            return {
                _clean(r.get("asset_rollup")): float(r.get("close_price"))
                for r in latest.to_dicts()
                if r.get("asset_rollup") is not None and r.get("close_price") is not None
            }
        except Exception:
            return {}

    def _rebuild_universe(self):
        try:
            rows = self._extract_open_series()
            rows = self._upsert_master_and_resolve(rows)
            self._underlying_close = self._load_underlying_close_map()
            self._rows = rows
            subs = [
                (int(r.series_id), int(r.conid), r.exchange_code, r.ib_currency)
                for r in rows
                if r.series_id and r.conid and int(r.conid) > 0
            ]
            if subs:
                self.price_feed.ensure_option_subscriptions(subs)
            self._publish_snapshot()
            print(
                f"[option-timevalue] universe refreshed: open_series={len(rows)} "
                f"subscribed={len(subs)} @ {_now_ts()}"
            )
        except Exception as exc:
            print(f"[option-timevalue] rebuild failed: {exc}")

    def _publish_snapshot(self):
        rows = self._rows or []
        if not rows:
            SNAPSHOT_STORE.safe_write("snapshot_optie_timevalue_live", pl.DataFrame())
            SNAPSHOT_STORE.safe_write("snapshot_optie_timevalue_summary", pl.DataFrame())
            return

        output = []
        by_ccy = defaultdict(float)
        priced = 0
        for r in rows:
            sid = int(r.series_id or 0)
            with self._lock:
                tick = dict(self._ticks.get(sid, {}))
            px = _pick_option_price(tick)
            if px is not None:
                priced += 1
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
                qty_contracts = float(r.qty_open) / 100.0
                time_total = -time_per * qty_contracts * float(r.multiplier)
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

        live_df = pl.DataFrame(output).sort(["asset", "exp", "c_p", "strike"])
        summary_df = pl.DataFrame(
            [{"ccy": ccy, "time_value_abs": val} for ccy, val in sorted(by_ccy.items())]
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
                    }
                ]
            ),
        )

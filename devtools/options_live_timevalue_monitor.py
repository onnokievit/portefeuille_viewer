from __future__ import annotations

import argparse
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
import pyodbc
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


DEFAULT_STOCK_DB = r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - STOCKDATA.accdb"
DEFAULT_TABLE = "option_subscription_universe_onno"
INFO_CODES = {1100, 1101, 1102, 2103, 2104, 2105, 2106, 2107, 2108, 2158, 2159}
TICK_NAME = {
    1: "bid",
    2: "ask",
    4: "last",
    9: "close",
    66: "delayed_bid",
    67: "delayed_ask",
    68: "delayed_last",
    75: "delayed_close",
}


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except Exception:
        return None
    if abs(x) > 1e100:
        return None
    return x


def _pos_or_none(v: float | None) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except Exception:
        return None
    return x if x > 0 else None


def _fmt_nl(v: float | None, decimals: int = 4) -> str:
    if v is None:
        return ""
    s = f"{float(v):,.{decimals}f}"
    # EN -> NL: 1,234.56 -> 1.234,56
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _cell_decimals(col_idx: int) -> int:
    # 1 dec: strike, qty_open, mult
    if col_idx in (4, 5, 6):
        return 1
    # 2 dec: prijsvelden + time value velden
    if col_idx in (8, 9, 10, 11, 12, 13, 14):
        return 2
    # Greeks op 3 dec
    if col_idx in (15, 16, 17, 18):
        return 3
    # default
    return 4


def _pick_option_price(p: dict[str, float]) -> float | None:
    for k in ("last", "delayed_last", "close", "delayed_close"):
        v = p.get(k)
        if v is not None and v > 0:
            return v
    b = p.get("bid")
    a = p.get("ask")
    if b is not None and a is not None and b > 0 and a > 0:
        return (b + a) / 2.0
    return None


def _intrinsic(cp: str, strike: float, und: float) -> float:
    if cp == "call":
        return max(0.0, und - strike)
    return max(0.0, strike - und)


def connect_access(db_path: str) -> pyodbc.Connection:
    return pyodbc.connect(rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}")


@dataclass
class UniverseRow:
    series_id: int
    broker: str
    asset_rollup: str
    underlying_symbol: str
    optie_call_put: str
    strike: float
    expiry: datetime
    ib_currency: str
    exchange_code: str
    conid: int
    qty_open: float
    multiplier: float


class OptionLiveApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.req_to_series: dict[int, UniverseRow] = {}
        self.prices: dict[int, dict[str, float]] = {}
        self.greeks: dict[int, dict[str, float]] = {}
        self.lock = threading.Lock()

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()
        print(f"[{_ts()}] Connected. nextValidId={orderId}")

    def error(self, reqId, *args):  # noqa: N802
        code = None
        msg = ""
        if len(args) == 2:
            code, msg = args
        elif len(args) == 3:
            code, msg, _ = args
        elif len(args) >= 4:
            _, code, msg, _ = args[:4]
        if code is None:
            return
        try:
            code_i = int(code)
        except Exception:
            code_i = None
        if code_i in INFO_CODES:
            return
        if isinstance(msg, str) and "connection is OK" in msg:
            return
        print(f"[{_ts()}] IB ERROR reqId={reqId} code={code}: {msg}")

    def tickPrice(self, reqId, tickType, price, attrib):  # noqa: N802
        p = _to_num(price)
        if p is None:
            return
        name = TICK_NAME.get(int(tickType))
        if not name:
            return
        with self.lock:
            self.prices.setdefault(int(reqId), {})[name] = p

    def tickOptionComputation(  # noqa: N802
        self,
        reqId,
        tickType,
        tickAttrib,
        impliedVol,
        delta,
        optPrice,
        pvDividend,
        gamma,
        vega,
        theta,
        undPrice,
    ):
        values = {
            "iv": _to_num(impliedVol),
            "delta": _to_num(delta),
            "gamma": _to_num(gamma),
            "theta": _to_num(theta),
            "vega": _to_num(vega),
            "model_price": _to_num(optPrice),
            "underlying_price": _to_num(undPrice),
        }
        with self.lock:
            g = self.greeks.setdefault(int(reqId), {})
            for k, v in values.items():
                if v is not None:
                    g[k] = v


def load_universe(conn: pyodbc.Connection, table_name: str, user_name: str) -> list[UniverseRow]:
    sql = f"""
        SELECT
            user_name,
            broker,
            series_id,
            qty_open,
            asset_rollup,
            underlying_symbol,
            optie_call_put,
            strike,
            expiry,
            ib_currency,
            exchange_code,
            multiplier,
            conid
        FROM {table_name}
        WHERE user_name=?
          AND conid IS NOT NULL
          AND conid > 0
        ORDER BY asset_rollup, expiry, optie_call_put, strike, broker
    """
    df = pd.read_sql(sql, conn, params=[user_name])
    if df.empty:
        return []
    df["broker"] = df["broker"].astype(str).str.strip().str.lower()
    df["asset_rollup"] = df["asset_rollup"].astype(str).str.strip()
    df["underlying_symbol"] = df["underlying_symbol"].astype(str).str.strip()
    df["optie_call_put"] = df["optie_call_put"].astype(str).str.strip().str.lower()
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df["qty_open"] = pd.to_numeric(df["qty_open"], errors="coerce")
    df["multiplier"] = pd.to_numeric(df["multiplier"], errors="coerce").fillna(100.0)
    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce")
    df["conid"] = pd.to_numeric(df["conid"], errors="coerce")
    df = df.dropna(subset=["series_id", "strike", "qty_open", "expiry", "conid"])
    out: list[UniverseRow] = []
    for _, r in df.iterrows():
        out.append(
            UniverseRow(
                series_id=int(r["series_id"]),
                broker=str(r["broker"]),
                asset_rollup=str(r["asset_rollup"]),
                underlying_symbol=str(r["underlying_symbol"]),
                optie_call_put=str(r["optie_call_put"]),
                strike=float(r["strike"]),
                expiry=r["expiry"].to_pydatetime(),
                ib_currency=str(r["ib_currency"] or "").upper(),
                exchange_code=str(r["exchange_code"] or "SMART").upper(),
                conid=int(r["conid"]),
                qty_open=float(r["qty_open"]),
                multiplier=float(r["multiplier"]),
            )
        )
    return out


def load_latest_underlying_close(conn: pyodbc.Connection) -> dict[str, float]:
    sql = """
        SELECT h.asset_rollup, h.[close] AS underlying_close
        FROM historical_data_correct AS h
        INNER JOIN (
            SELECT asset_rollup, MAX(datum) AS max_datum
            FROM historical_data_correct
            GROUP BY asset_rollup
        ) AS x
          ON h.asset_rollup=x.asset_rollup AND h.datum=x.max_datum
    """
    df = pd.read_sql(sql, conn)
    out: dict[str, float] = {}
    if df.empty:
        return out
    df["asset_rollup"] = df["asset_rollup"].astype(str).str.strip()
    df["underlying_close"] = pd.to_numeric(df["underlying_close"], errors="coerce")
    df = df.dropna(subset=["asset_rollup", "underlying_close"])
    for _, r in df.iterrows():
        out[str(r["asset_rollup"])] = float(r["underlying_close"])
    return out


def build_contract(u: UniverseRow) -> Contract:
    c = Contract()
    c.conId = int(u.conid)
    c.exchange = u.exchange_code or "SMART"
    if u.ib_currency:
        c.currency = u.ib_currency
    return c


class MonitorWindow(QWidget):
    def __init__(
        self,
        app_ib: OptionLiveApp,
        universe: list[UniverseRow],
        underlying_close: dict[str, float],
        fx_usd_eur: float = 0.0,
    ):
        super().__init__()
        self.setWindowTitle("Options Live Timevalue Monitor")
        self.resize(1600, 900)
        self.app_ib = app_ib
        self.universe = universe
        self.underlying_close = underlying_close
        self.fx_usd_eur = float(fx_usd_eur or 0.0)
        self.series_by_req: dict[int, UniverseRow] = {}

        self.label_ticker = QLabel("starting...")
        self.label_summary = QLabel("")
        self.btn_refresh = QPushButton("Refresh Table")
        self.btn_refresh.clicked.connect(self.refresh_table)

        self.table = QTableWidget(0, 19)
        self.table.setHorizontalHeaderLabels(
            [
                "broker",
                "asset",
                "exp",
                "c/p",
                "strike",
                "qty_open",
                "mult",
                "ccy",
                "last_px",
                "bid",
                "ask",
                "und_px",
                "intrinsic",
                "time_per_unit",
                "time_total",
                "iv",
                "delta",
                "gamma",
                "theta",
            ]
        )
        self.table.setSortingEnabled(True)

        top = QHBoxLayout()
        top.addWidget(self.label_ticker, 1)
        top.addWidget(self.label_summary, 2)
        top.addWidget(self.btn_refresh, 0)

        lay = QVBoxLayout()
        lay.addLayout(top)
        lay.addWidget(self.table)
        self.setLayout(lay)

        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(1000)
        self.ui_timer.timeout.connect(self.refresh_table)
        self.ui_timer.start()

        self._setup_subscriptions()
        self.refresh_table()

    def _setup_subscriptions(self) -> None:
        req_start = 30000
        subscribed = 0
        for i, u in enumerate(self.universe):
            req_id = req_start + i
            self.series_by_req[req_id] = u
            self.app_ib.req_to_series[req_id] = u
            self.app_ib.reqMktData(req_id, build_contract(u), "", False, False, [])
            subscribed += 1
        self.label_ticker.setText(f"[{_ts()}] subscribed={subscribed}")

    def closeEvent(self, event):  # noqa: N802
        for req_id in list(self.series_by_req.keys()):
            try:
                self.app_ib.cancelMktData(req_id)
            except Exception:
                pass
        try:
            self.app_ib.disconnect()
        except Exception:
            pass
        super().closeEvent(event)

    def refresh_table(self) -> None:
        rows = []
        with self.app_ib.lock:
            prices = dict(self.app_ib.prices)
            greeks = dict(self.app_ib.greeks)

        prices_seen = 0
        by_ccy: dict[str, float] = {}
        for req_id, u in self.series_by_req.items():
            p = prices.get(req_id, {})
            g = greeks.get(req_id, {})
            option_px = _pick_option_price(p)
            if option_px is not None:
                prices_seen += 1

            und_px = _to_num(g.get("underlying_price"))
            if und_px is None:
                und_px = self.underlying_close.get(u.asset_rollup)
            und_px = float(und_px) if und_px is not None else None

            intrinsic = None
            time_per_unit = None
            time_total = None
            if option_px is not None and und_px is not None:
                intrinsic = _intrinsic(u.optie_call_put, float(u.strike), float(und_px))
                time_per_unit = max(0.0, float(option_px) - float(intrinsic))
                qty_contracts = abs(float(u.qty_open)) / 100.0
                time_total = time_per_unit * qty_contracts * float(u.multiplier)
                by_ccy[u.ib_currency or ""] = by_ccy.get(u.ib_currency or "", 0.0) + float(time_total)

            rows.append(
                (
                    u.broker,
                    u.asset_rollup,
                    u.expiry.strftime("%Y-%m-%d"),
                    u.optie_call_put,
                    u.strike,
                    u.qty_open,
                    u.multiplier,
                    u.ib_currency,
                    option_px,
                    _pos_or_none(_to_num(p.get("bid"))),
                    _pos_or_none(_to_num(p.get("ask"))),
                    und_px,
                    intrinsic,
                    time_per_unit,
                    time_total,
                    _to_num(g.get("iv")),
                    _to_num(g.get("delta")),
                    _to_num(g.get("gamma")),
                    _to_num(g.get("theta")),
                )
            )

        self.table.setSortingEnabled(False)
        footer_rows = len([k for k in by_ccy.keys() if k]) + (1 if self.fx_usd_eur > 0 else 0)
        self.table.setRowCount(len(rows) + footer_rows)
        for r, vals in enumerate(rows):
            for c, v in enumerate(vals):
                if isinstance(v, float):
                    text = _fmt_nl(v, _cell_decimals(c))
                elif v is None:
                    text = ""
                else:
                    text = str(v)
                item = QTableWidgetItem(text)
                if c >= 4:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)

        # Footer totals per currency
        row_idx = len(rows)
        for ccy, total in sorted(by_ccy.items()):
            if not ccy:
                continue
            vals = ["TOTAL", "", "", "", "", "", "", ccy, "", "", "", "", "", "", _fmt_nl(total, 2), "", "", "", ""]
            for c, text in enumerate(vals):
                it = QTableWidgetItem(text)
                it.setBackground(Qt.lightGray)
                if c in (0, 7):
                    it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                else:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row_idx, c, it)
            row_idx += 1

        # Optional converted EUR estimate row
        if self.fx_usd_eur > 0:
            eur_total = by_ccy.get("EUR", 0.0) + by_ccy.get("USD", 0.0) * self.fx_usd_eur
            vals = ["TOTAL_EUR_EST", "", "", "", "", "", "", "EUR", "", "", "", "", "", "", _fmt_nl(eur_total, 2), "", "", "", ""]
            for c, text in enumerate(vals):
                it = QTableWidgetItem(text)
                it.setBackground(Qt.gray)
                if c in (0, 7):
                    it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                else:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row_idx, c, it)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()

        ccy_parts = [f"{k}:{_fmt_nl(v, 2)}" for k, v in sorted(by_ccy.items()) if k]
        ccy_txt = " | ".join(ccy_parts) if ccy_parts else "-"
        self.label_ticker.setText(f"[{_ts()}] ticks with price={prices_seen}/{len(rows)}")
        self.label_summary.setText(f"time_value_abs_by_ccy: {ccy_txt}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Standalone live options monitor from option subscription universe.")
    p.add_argument("--stock-db", default=DEFAULT_STOCK_DB)
    p.add_argument("--table", default=DEFAULT_TABLE)
    p.add_argument("--user", default="onno")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7496)
    p.add_argument("--client-id", type=int, default=121)
    p.add_argument("--market-data-type", type=int, default=3, choices=[1, 2, 3, 4])
    p.add_argument("--fx-usd-eur", type=float, default=0.0, help="Optional USD->EUR factor for extra total row.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = connect_access(args.stock_db)
    try:
        universe = load_universe(conn, args.table, args.user)
        und_close = load_latest_underlying_close(conn)
    finally:
        conn.close()
    if not universe:
        print("No universe rows found with conid > 0.")
        return 1

    app_ib = OptionLiveApp()
    app_ib.connect(args.host, args.port, clientId=args.client_id)
    th = threading.Thread(target=app_ib.run, daemon=True)
    th.start()
    if not app_ib.ready.wait(timeout=8):
        print("IB connection failed (no nextValidId).")
        try:
            app_ib.disconnect()
        except Exception:
            pass
        return 1
    app_ib.reqMarketDataType(args.market_data_type)

    qapp = QApplication([])
    win = MonitorWindow(
        app_ib=app_ib,
        universe=universe,
        underlying_close=und_close,
        fx_usd_eur=args.fx_usd_eur,
    )
    win.show()
    return qapp.exec()


if __name__ == "__main__":
    raise SystemExit(main())

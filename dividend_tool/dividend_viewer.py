"""
Dividend Viewer — standalone tool.
Laadt assets uit de portefeuille-database (asset_rollup_data).
Haalt dividend op via IBKR reqMktData generic tick 456.
Worker draait als subprocess (QProcess) en communiceert via JSON stdout.
"""
from __future__ import annotations

import json
import random
import sys
import threading
import time
from pathlib import Path

import pyodbc
from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ── project root op sys.path ─────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from portefeuille_viewer.config import get_settings, get_databases, get_default_database  # noqa: E402


# ── kolom-indices ────────────────────────────────────────────────────────────
C_ASSET    = 0
C_SYMBOL   = 1
C_EXCHANGE = 2
C_CURRENCY = 3
C_TRAILING = 4
C_FORWARD  = 5
C_EXDATE   = 6
C_AMOUNT   = 7
C_STATUS   = 8
C_MESSAGE  = 9
C_RAW      = 10

COL_HEADERS = [
    "Asset", "IB Symbol", "Exchange", "Valuta",
    "Trailing 12m", "Forward 12m", "Ex-datum", "Volgend bedrag",
    "Status", "Melding", "Raw",
]

_STOCK_TYPES = {"aandeel", "stock", "etf", "fonds", "fund", ""}

DIVIDEND_TICK_TYPE = 59
WORKER_TIMEOUT     = 10.0


# ── helpers ──────────────────────────────────────────────────────────────────

def _ib_settings() -> tuple[str, int, int]:
    s = get_settings()
    return s.get_ib_host(), s.get_ib_port(), s.get_ib_client_id() + 50


def _db_connection_string() -> str:
    databases = get_databases()
    default   = get_default_database()
    db_path   = ""
    if default and default in databases:
        db_path = databases[default]["path"]
    elif databases:
        db_path = next(iter(databases.values()))["path"]
    if not db_path:
        raise RuntimeError("Geen database geconfigureerd in de portefeuille-app.")
    return rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};"


def _load_assets() -> list[dict]:
    conn_str = _db_connection_string()
    with pyodbc.connect(conn_str) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM asset_rollup_data")
        columns = [c[0].lower() for c in cursor.description]
        rows    = cursor.fetchall()

    assets = []
    for row in rows:
        r = dict(zip(columns, row))

        sym = str(r.get("ib_symbol") or "").strip()
        if not sym:
            continue

        incl = str(r.get("incl_excl") or "").strip().upper()
        if incl == "X":
            continue

        asset_type = str(r.get("type") or "").strip().lower()

        exchange      = str(r.get("exchange") or "SMART").strip() or "SMART"
        prim_exchange = str(r.get("prim_exchange") or "").strip()
        currency      = str(r.get("ib_currency") or "USD").strip() or "USD"
        asset         = str(r.get("asset_rollup") or sym).strip()

        contractid = None
        try:
            raw_cid = r.get("contractid")
            if raw_cid is not None:
                contractid = int(raw_cid)
        except Exception:
            pass

        assets.append({
            "asset":        asset,
            "asset_type":   asset_type,
            "symbol":       sym,
            "exchange":     exchange,
            "prim_exchange": prim_exchange,
            "currency":     currency,
            "contractid":   contractid,
        })

    assets.sort(key=lambda a: a["asset"].lower())
    return assets


def _parse_dividend(raw: str) -> tuple[str, str, str, str]:
    """Parseert IBKR dividend string: trailing12m,forward12m,nextDate,nextAmount"""
    parts = [p.strip() for p in raw.split(",")]
    while len(parts) < 4:
        parts.append("")

    def fmt(v: str) -> str:
        if not v:
            return "—"
        try:
            return f"{float(v):.4f}".rstrip("0").rstrip(".")
        except ValueError:
            return v

    trailing = fmt(parts[0])
    forward  = fmt(parts[1])
    ex_date  = parts[2] if parts[2] else "—"
    amount   = fmt(parts[3])
    return trailing, forward, ex_date, amount


# ── IBKR worker (draait als subprocess) ──────────────────────────────────────

def _run_worker_process() -> None:
    """
    Wordt aangeroepen wanneer het script met --worker wordt gestart.
    Verbindt met IBKR, haalt dividend op per asset, print JSON-regels naar stdout.
    """
    from ibapi.client import EClient
    from ibapi.contract import Contract
    from ibapi.wrapper import EWrapper

    try:
        host, port, client_id = _ib_settings()
        assets = _load_assets()
    except Exception as exc:
        print(json.dumps({"event": "error", "message": str(exc)}), flush=True)
        return

    connected_event = threading.Event()
    pending_lock    = threading.Lock()
    pending: dict[int, dict] = {}

    class App(EWrapper, EClient):
        def __init__(self):
            EClient.__init__(self, self)

        def nextValidId(self, orderId):
            connected_event.set()

        def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
            if errorCode in (2103, 2104, 2106, 2158, 300):
                return
            with pending_lock:
                state = pending.get(reqId)
                if state is not None:
                    state["error"] = f"IB {errorCode}: {errorString}"
                    state["event"].set()

        def tickString(self, reqId, tickType, value):
            if tickType != DIVIDEND_TICK_TYPE:
                return
            with pending_lock:
                state = pending.get(reqId)
                if state is not None:
                    state["value"] = value
                    state["event"].set()

    seed = client_id + random.randint(1, 4999)
    app  = App()
    app.connect(host, port, clientId=seed)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()

    if not connected_event.wait(timeout=8.0):
        print(json.dumps({"event": "error", "message": "Timeout: geen verbinding met IBKR gateway"}), flush=True)
        return

    print(json.dumps({"event": "started", "count": len(assets)}), flush=True)

    for index, asset in enumerate(assets, 1):
        asset_type = asset["asset_type"]
        if asset_type and asset_type not in _STOCK_TYPES:
            print(json.dumps({
                "event": "asset_result", "index": index, "count": len(assets),
                "asset": asset["asset"], "status": "skipped",
                "message": f"type '{asset_type}' overgeslagen",
                "trailing": "", "forward": "", "ex_date": "", "amount": "",
            }), flush=True)
            continue

        req_id = int(time.time() * 1000) % 1_000_000 + random.randint(1, 999)
        event  = threading.Event()
        state  = {"event": event, "value": "", "error": ""}
        with pending_lock:
            pending[req_id] = state

        contract          = Contract()
        contract.secType  = "STK"
        contract.symbol   = asset["symbol"]
        contract.currency = asset["currency"]
        contract.exchange = asset["exchange"]
        if asset["prim_exchange"]:
            contract.primaryExch = asset["prim_exchange"]  # type: ignore[attr-defined]
        if asset["contractid"]:
            contract.conId = asset["contractid"]

        try:
            app.reqMktData(req_id, contract, "456", False, False, [])
            event.wait(timeout=WORKER_TIMEOUT)
        finally:
            try:
                app.cancelMktData(req_id)
            except Exception:
                pass
            with pending_lock:
                pending.pop(req_id, None)

        value = str(state.get("value") or "").strip()
        error = str(state.get("error") or "").strip()

        if error:
            result = {"status": "error", "message": error,
                      "trailing": "", "forward": "", "ex_date": "", "amount": "", "raw": ""}
        elif value:
            trailing, forward, ex_date, amount = _parse_dividend(value)
            result = {"status": "ok", "message": "",
                      "trailing": trailing, "forward": forward,
                      "ex_date": ex_date, "amount": amount, "raw": value}
        else:
            result = {"status": "geen data", "message": "Geen data binnen timeout",
                      "trailing": "", "forward": "", "ex_date": "", "amount": "", "raw": ""}

        print(json.dumps({
            "event": "asset_result", "index": index, "count": len(assets),
            "asset": asset["asset"], **result,
        }), flush=True)

        time.sleep(0.05)

    try:
        app.disconnect()
    except Exception:
        pass
    print(json.dumps({"event": "finished", "count": len(assets)}), flush=True)


# ── Hoofdvenster ──────────────────────────────────────────────────────────────

class DividendWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dividend Viewer")
        self.resize(1200, 700)

        self._process: QProcess | None = None
        self._stdout_buf = ""
        self._assets: list[dict] = []
        self._asset_row_map: dict[str, int] = {}

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(6)
        root.setContentsMargins(10, 10, 10, 10)

        # ── knoppen ──────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()

        self.btn_load = QPushButton("Assets laden")
        self.btn_load.setFixedHeight(30)
        self.btn_load.clicked.connect(self._load_assets)
        btn_row.addWidget(self.btn_load)

        self.btn_fetch = QPushButton("Dividend ophalen")
        self.btn_fetch.setFixedHeight(30)
        self.btn_fetch.setEnabled(False)
        self.btn_fetch.clicked.connect(self._on_fetch)
        btn_row.addWidget(self.btn_fetch)

        btn_row.addStretch(1)

        self.lbl_ib = QLabel()
        self._update_ib_label()
        btn_row.addWidget(self.lbl_ib)

        root.addLayout(btn_row)

        # ── tabel ─────────────────────────────────────────────────────────────
        self.table = QTableWidget(0, len(COL_HEADERS))
        self.table.setHorizontalHeaderLabels(COL_HEADERS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        root.addWidget(self.table, 1)

        # ── statusbalk ────────────────────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Klik 'Assets laden' om te beginnen.")

        self._load_assets()

    def _update_ib_label(self):
        try:
            host, port, client_id = _ib_settings()
            self.lbl_ib.setText(f"IBKR: {host}:{port}  client {client_id}")
            self.lbl_ib.setStyleSheet("color: #555;")
        except Exception:
            self.lbl_ib.setText("IBKR: niet geconfigureerd")

    def _load_assets(self):
        self.status_bar.showMessage("Assets laden uit database…")
        try:
            self._assets = _load_assets()
        except Exception as exc:
            self.status_bar.showMessage(f"Database fout: {exc}")
            return

        self._asset_row_map = {}
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for asset in self._assets:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._asset_row_map[asset["asset"]] = row

            for col, val in [
                (C_ASSET,    asset["asset"]),
                (C_SYMBOL,   asset["symbol"]),
                (C_EXCHANGE, asset["exchange"]),
                (C_CURRENCY, asset["currency"]),
                (C_TRAILING, ""),
                (C_FORWARD,  ""),
                (C_EXDATE,   ""),
                (C_AMOUNT,   ""),
                (C_STATUS,   "idle"),
                (C_MESSAGE,  ""),
                (C_RAW,      ""),
            ]:
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == C_STATUS:
                    item.setBackground(QColor("#efe6d2"))
                self.table.setItem(row, col, item)

        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self.btn_fetch.setEnabled(len(self._assets) > 0)
        self.status_bar.showMessage(f"{len(self._assets)} assets geladen.")

    def _on_fetch(self):
        if self._process is not None:
            return

        self.btn_fetch.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.btn_fetch.setText("Bezig…")
        self._stdout_buf = ""

        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(["-u", str(Path(__file__).resolve()), "--worker"])
        process.readyReadStandardOutput.connect(self._on_stdout)
        process.readyReadStandardError.connect(self._on_stderr)
        process.finished.connect(self._on_finished)
        process.start()
        self._process = process

    def _on_stdout(self):
        if self._process is None:
            return
        self._stdout_buf += self._process.readAllStandardOutput().toStdString()
        while "\n" in self._stdout_buf:
            line, self._stdout_buf = self._stdout_buf.split("\n", 1)
            line = line.strip()
            if line:
                self._handle_line(line)

    def _on_stderr(self):
        if self._process is None:
            return
        text = self._process.readAllStandardError().toStdString().strip()
        if text:
            self.status_bar.showMessage(text.splitlines()[-1])

    def _handle_line(self, line: str):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            self.status_bar.showMessage(line)
            return

        event = payload.get("event")
        if event == "started":
            self.status_bar.showMessage(f"Verbonden. {payload.get('count', 0)} assets ophalen…")
        elif event == "asset_result":
            self._update_row(payload)
            self.status_bar.showMessage(
                f"[{payload.get('index', 0)}/{payload.get('count', 0)}] {payload.get('asset', '')}"
            )
        elif event == "error":
            self.status_bar.showMessage(str(payload.get("message", "Onbekende fout")))
        elif event == "finished":
            self.status_bar.showMessage(f"Klaar. {payload.get('count', 0)} assets verwerkt.")

    def _update_row(self, payload: dict):
        asset  = str(payload.get("asset") or "")
        row    = self._asset_row_map.get(asset)
        if row is None:
            return

        status = str(payload.get("status") or "")
        updates = [
            (C_TRAILING, payload.get("trailing", "")),
            (C_FORWARD,  payload.get("forward",  "")),
            (C_EXDATE,   payload.get("ex_date",  "")),
            (C_AMOUNT,   payload.get("amount",   "")),
            (C_STATUS,   status),
            (C_MESSAGE,  payload.get("message",  "")),
            (C_RAW,      payload.get("raw",      "")),
        ]
        color_map = {
            "ok":       QColor("#d8ead3"),
            "error":    QColor("#f4cccc"),
            "geen data": QColor("#fce5cd"),
            "skipped":  QColor("#d9d9d9"),
            "idle":     QColor("#efe6d2"),
        }
        for col, val in updates:
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            item.setText(str(val) if val else "")
            if col == C_STATUS:
                item.setBackground(color_map.get(status, QColor("#efe6d2")))

    def _on_finished(self, exit_code: int, _):
        if self._stdout_buf.strip():
            self._handle_line(self._stdout_buf.strip())
        self._stdout_buf = ""
        self._process = None
        self.btn_fetch.setEnabled(True)
        self.btn_load.setEnabled(True)
        self.btn_fetch.setText("Dividend ophalen")
        if exit_code != 0:
            QMessageBox.warning(self, "Dividend Viewer", f"Worker gestopt met exit code {exit_code}.")

    def closeEvent(self, event):
        if self._process is not None:
            self._process.kill()
        event.accept()


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--worker" in sys.argv:
        _run_worker_process()
    else:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        window = DividendWindow()
        window.show()
        sys.exit(app.exec())

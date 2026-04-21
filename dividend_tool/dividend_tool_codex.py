from __future__ import annotations

import configparser
import json
import random
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pyodbc
import yfinance as yf
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper
from PySide6.QtCore import QObject, QProcess, Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_CONFIG_DIR = REPO_ROOT / "portefeuille_viewer" / "config"
SETTINGS_SHARED_PATH = APP_CONFIG_DIR / "settings_shared.ini"
SETTINGS_LOCAL_PATH = APP_CONFIG_DIR / ".user_settings" / "settings_local.ini"
DEFAULT_DB_PATH = Path(
    r"C:\Users\onno\OneDrive\Beleggen\2025 - portefeuille database 02.03 - ONNO.accdb"
)
DEFAULT_IB_HOST = "127.0.0.1"
DEFAULT_IB_PORT = 7496
DEFAULT_IB_CLIENT_ID = 299
DIVIDEND_TICK_TYPE = 59
WORKER_TIMEOUT_SECONDS = 8.0
EARNINGS_FEE_TYPE = "earnings_next"


@dataclass
class AssetRecord:
    asset_rollup: str
    asset_type: str
    ib_symbol: str
    ib_currency: str
    exchange: str
    prim_exchange: str
    contractid: int | None


@dataclass
class DividendResult:
    asset_rollup: str
    status: str
    message: str
    trailing_12m: float | None = None
    forward_12m: float | None = None
    next_date: str = ""
    next_amount: float | None = None
    raw_value: str = ""
    earnings_status: str = ""
    next_earnings_date: str = ""
    earnings_symbol: str = ""


def load_ib_settings() -> tuple[str, int, int]:
    cfg = configparser.ConfigParser()
    if SETTINGS_SHARED_PATH.exists():
        cfg.read(SETTINGS_SHARED_PATH, encoding="utf-8")
    if SETTINGS_LOCAL_PATH.exists():
        cfg.read(SETTINGS_LOCAL_PATH, encoding="utf-8")
    host = cfg.get("interactive_brokers", "host", fallback=DEFAULT_IB_HOST)
    port = cfg.getint("interactive_brokers", "port", fallback=DEFAULT_IB_PORT)
    client_id = cfg.getint("interactive_brokers", "client_id", fallback=DEFAULT_IB_CLIENT_ID)
    return host, port, client_id


def get_connection(db_path: Path) -> pyodbc.Connection:
    conn_str = rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path}"
    return pyodbc.connect(conn_str)


def load_assets(db_path: Path) -> list[AssetRecord]:
    sql = """
        SELECT
            asset_rollup,
            [type] AS asset_type,
            ib_symbol,
            ib_currency,
            exchange,
            prim_exchange,
            contractid
        FROM asset_rollup_data
        WHERE IIF(INCL_EXCL IS NULL, 0, INCL_EXCL) <> 0
          AND IIF(ib_symbol IS NULL, '', ib_symbol) <> ''
        ORDER BY asset_rollup
    """
    with get_connection(db_path) as conn:
        rows = conn.cursor().execute(sql).fetchall()
    assets: list[AssetRecord] = []
    for row in rows:
        contractid = None
        try:
            contractid = int(row.contractid) if row.contractid is not None else None
        except Exception:
            contractid = None
        assets.append(
            AssetRecord(
                asset_rollup=str(row.asset_rollup or "").strip(),
                asset_type=str(row.asset_type or "").strip().lower(),
                ib_symbol=str(row.ib_symbol or "").strip(),
                ib_currency=str(row.ib_currency or "USD").strip() or "USD",
                exchange=str(row.exchange or "SMART").strip() or "SMART",
                prim_exchange=str(row.prim_exchange or "").strip(),
                contractid=contractid,
            )
        )
    return assets


def build_contract(asset: AssetRecord) -> Contract | None:
    if asset.asset_type not in {"aandeel", "stock", "etf", "fonds", "fund"}:
        return None
    contract = Contract()
    contract.secType = "STK"
    contract.symbol = asset.ib_symbol
    contract.currency = asset.ib_currency or "USD"
    contract.exchange = asset.exchange or "SMART"
    if asset.prim_exchange:
        contract.primaryExchange = asset.prim_exchange
    if asset.contractid:
        contract.conId = asset.contractid
    return contract


def build_yfinance_candidates(asset: AssetRecord) -> list[str]:
    base = asset.ib_symbol.strip()
    if not base:
        return []

    exchange = (asset.prim_exchange or asset.exchange or "").upper().strip()
    candidates: list[str] = [base]
    suffix_map = {
        "AEB": ".AS",
        "ENEXT.AS": ".AS",
        "SBF": ".PA",
        "BVME": ".MI",
        "IBIS": ".DE",
        "XETRA": ".DE",
        "FWB": ".F",
        "LSE": ".L",
        "LON": ".L",
        "EBS": ".SW",
        "SWX": ".SW",
        "TSEJ": ".T",
        "TSE": ".T",
        "HKG": ".HK",
        "HKSE": ".HK",
    }
    suffix = suffix_map.get(exchange, "")
    if suffix:
        candidates.insert(0, f"{base}{suffix}")
    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def normalize_to_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", ""))
        return parsed.date()
    except Exception:
        return None


def fetch_next_earnings_date(asset: AssetRecord) -> tuple[str, str, str]:
    today = date.today()
    candidates = build_yfinance_candidates(asset)
    for symbol in candidates:
        try:
            df = yf.Ticker(symbol).get_earnings_dates(limit=12)
        except Exception as exc:
            last_error = f"yfinance fout voor {symbol}: {exc}"
            continue
        if df is None or getattr(df, "empty", True):
            last_error = f"Geen earnings-data voor {symbol}"
            continue
        try:
            idx_values = list(df.index)
        except Exception:
            idx_values = []
        next_dates = [d for d in (normalize_to_date(v) for v in idx_values) if d and d >= today]
        if next_dates:
            return "ok", min(next_dates).isoformat(), symbol
        last_error = f"Geen toekomstige earnings-datum voor {symbol}"
    return "no_data", "", last_error if 'last_error' in locals() else "Geen yfinance candidates"


def reset_earnings_rows(db_path: Path) -> None:
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM fees_dividend WHERE fee_type = ?", EARNINGS_FEE_TYPE)
        conn.commit()


def upsert_earnings_row(db_path: Path, asset: AssetRecord, next_earnings_date: str, source_symbol: str) -> None:
    if not next_earnings_date:
        return
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO fees_dividend (datum, broker, fee_type, asset, amount, currency, notitie)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            next_earnings_date,
            "yfinance",
            EARNINGS_FEE_TYPE,
            asset.asset_rollup,
            None,
            asset.ib_currency or None,
            f"next earnings via yfinance ({source_symbol})",
        )
        conn.commit()


def parse_dividend_value(raw_value: str) -> tuple[float | None, float | None, str, float | None]:
    parts = [part.strip() for part in raw_value.split(",")]
    while len(parts) < 4:
        parts.append("")

    def parse_float(value: str) -> float | None:
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    trailing_12m = parse_float(parts[0])
    forward_12m = parse_float(parts[1])
    next_date = parts[2]
    next_amount = parse_float(parts[3])
    return trailing_12m, forward_12m, next_date, next_amount


class DividendIbWorker(EWrapper, EClient):
    def __init__(self, host: str, port: int, client_id: int, assets: list[AssetRecord], db_path: Path) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.host = host
        self.port = port
        self.client_id = client_id
        self.assets = assets
        self.db_path = db_path
        self._connected_event = threading.Event()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, dict] = {}
        self._global_errors: list[str] = []
        self._client_id_seed = client_id + random.randint(1, 5000)

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self._connected_event.set()

    def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = "") -> None:  # noqa: N802
        ignored_codes = {2104, 2106, 2158}
        if errorCode in ignored_codes:
            return
        message = f"IBKR {errorCode}: {errorString}"
        if reqId in self._pending:
            with self._pending_lock:
                state = self._pending.get(reqId)
                if state is not None:
                    state["error"] = message
                    state["event"].set()
            return
        self._global_errors.append(message)

    def tickString(self, reqId: int, tickType: int, value: str) -> None:  # noqa: N802
        if tickType != DIVIDEND_TICK_TYPE:
            return
        with self._pending_lock:
            state = self._pending.get(reqId)
            if state is None:
                return
            state["value"] = value
            state["event"].set()

    def connect_and_start(self) -> None:
        self.connect(self.host, self.port, clientId=self._client_id_seed)
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        if not self._connected_event.wait(timeout=5.0):
            raise RuntimeError("Geen verbinding met IBKR gateway/TWS")

    def disconnect_cleanly(self) -> None:
        with self._pending_lock:
            pending_ids = list(self._pending.keys())
        for req_id in pending_ids:
            with ExceptionSuppressor():
                self.cancelMktData(req_id)
        with ExceptionSuppressor():
            self.disconnect()

    def fetch_all(self) -> None:
        self.connect_and_start()
        reset_earnings_rows(self.db_path)
        print(json.dumps({"event": "started", "count": len(self.assets)}), flush=True)
        for index, asset in enumerate(self.assets, start=1):
            result = self.fetch_one(asset)
            print(
                json.dumps(
                    {
                        "event": "asset_result",
                        "index": index,
                        "count": len(self.assets),
                        "asset_rollup": result.asset_rollup,
                        "status": result.status,
                        "message": result.message,
                        "trailing_12m": result.trailing_12m,
                        "forward_12m": result.forward_12m,
                        "next_date": result.next_date,
                        "next_amount": result.next_amount,
                        "raw_value": result.raw_value,
                        "earnings_status": result.earnings_status,
                        "next_earnings_date": result.next_earnings_date,
                        "earnings_symbol": result.earnings_symbol,
                    }
                ),
                flush=True,
            )
        self.disconnect_cleanly()
        print(json.dumps({"event": "finished", "count": len(self.assets)}), flush=True)

    def fetch_one(self, asset: AssetRecord) -> DividendResult:
        contract = build_contract(asset)
        earnings_status, next_earnings_date, earnings_symbol = fetch_next_earnings_date(asset)
        if next_earnings_date:
            with ExceptionSuppressor():
                upsert_earnings_row(self.db_path, asset, next_earnings_date, earnings_symbol)
        if contract is None:
            return DividendResult(
                asset_rollup=asset.asset_rollup,
                status="skipped",
                message=f"Asset type '{asset.asset_type}' niet ondersteund voor dividendrequest",
                earnings_status=earnings_status,
                next_earnings_date=next_earnings_date,
                earnings_symbol=earnings_symbol,
            )

        req_id = int(time.time() * 1000) % 1_000_000 + random.randint(1, 999)
        event = threading.Event()
        state = {"event": event, "value": "", "error": ""}
        with self._pending_lock:
            self._pending[req_id] = state
        try:
            self.reqMktData(req_id, contract, "456", False, False, [])
            event.wait(timeout=WORKER_TIMEOUT_SECONDS)
            value = str(state.get("value") or "").strip()
            error = str(state.get("error") or "").strip()
            if error:
                return DividendResult(
                    asset_rollup=asset.asset_rollup,
                    status="error",
                    message=error,
                    earnings_status=earnings_status,
                    next_earnings_date=next_earnings_date,
                    earnings_symbol=earnings_symbol,
                )
            if not value:
                return DividendResult(
                    asset_rollup=asset.asset_rollup,
                    status="no_data",
                    message="Geen dividenddata van IBKR ontvangen binnen timeout",
                    earnings_status=earnings_status,
                    next_earnings_date=next_earnings_date,
                    earnings_symbol=earnings_symbol,
                )
            trailing_12m, forward_12m, next_date, next_amount = parse_dividend_value(value)
            return DividendResult(
                asset_rollup=asset.asset_rollup,
                status="ok",
                message="Dividend ontvangen",
                trailing_12m=trailing_12m,
                forward_12m=forward_12m,
                next_date=next_date,
                next_amount=next_amount,
                raw_value=value,
                earnings_status=earnings_status,
                next_earnings_date=next_earnings_date,
                earnings_symbol=earnings_symbol,
            )
        finally:
            with ExceptionSuppressor():
                self.cancelMktData(req_id)
            with self._pending_lock:
                self._pending.pop(req_id, None)


class ExceptionSuppressor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return True


class DividendToolWindow(QMainWindow):
    COLUMN_KEYS = [
        "asset_rollup",
        "asset_type",
        "ib_symbol",
        "ib_currency",
        "status",
        "trailing_12m",
        "forward_12m",
        "next_date",
        "next_amount",
        "next_earnings_date",
        "earnings_symbol",
        "message",
        "raw_value",
    ]
    COLUMN_HEADERS = [
        "Asset",
        "Type",
        "IB Symbol",
        "Valuta",
        "Status",
        "Trailing 12m",
        "Forward 12m",
        "Next Date",
        "Next Amount",
        "Next Earnings",
        "YF Symbol",
        "Melding",
        "Raw",
    ]

    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self.db_path = db_path
        self.assets = load_assets(db_path)
        self.asset_row_map = {asset.asset_rollup: idx for idx, asset in enumerate(self.assets)}
        self._stdout_buffer = ""
        self._process: QProcess | None = None
        self.setWindowTitle("Dividend Tool Codex")
        self.resize(1500, 900)
        self._build_ui()
        self._populate_table()

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.start_button = QPushButton("Start Dividend Ophalen")
        self.start_button.clicked.connect(self.start_worker)
        self.status_label = QLabel(f"{len(self.assets)} assets geladen uit asset_rollup_data")
        self.status_label.setWordWrap(True)
        top.addWidget(self.start_button)
        top.addWidget(self.status_label, 1)
        root.addLayout(top)

        self.table = QTableWidget(0, len(self.COLUMN_HEADERS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMN_HEADERS)
        self.table.setSortingEnabled(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.table, 1)

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self.assets))
        for row, asset in enumerate(self.assets):
            base_values = {
                "asset_rollup": asset.asset_rollup,
                "asset_type": asset.asset_type,
                "ib_symbol": asset.ib_symbol,
                "ib_currency": asset.ib_currency,
                "status": "idle",
                "trailing_12m": "",
                "forward_12m": "",
                "next_date": "",
                "next_amount": "",
                "next_earnings_date": "",
                "earnings_symbol": "",
                "message": "",
                "raw_value": "",
            }
            for column, key in enumerate(self.COLUMN_KEYS):
                item = QTableWidgetItem(str(base_values[key]))
                if key == "status":
                    item.setBackground(QColor("#efe6d2"))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()

    @Slot()
    def start_worker(self) -> None:
        if self._process is not None:
            return
        self.start_button.setEnabled(False)
        self.status_label.setText("Dividend ophalen gestart...")
        self._stdout_buffer = ""
        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(["-u", str(Path(__file__).resolve()), "--worker", "--db", str(self.db_path)])
        process.readyReadStandardOutput.connect(self._on_ready_stdout)
        process.readyReadStandardError.connect(self._on_ready_stderr)
        process.finished.connect(self._on_finished)
        process.start()
        self._process = process

    def _on_ready_stdout(self) -> None:
        if self._process is None:
            return
        self._stdout_buffer += bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            self._handle_worker_line(line)

    def _on_ready_stderr(self) -> None:
        if self._process is None:
            return
        stderr = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if stderr:
            self.status_label.setText(stderr.splitlines()[-1])

    def _handle_worker_line(self, line: str) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            self.status_label.setText(line)
            return
        event = payload.get("event")
        if event == "started":
            self.status_label.setText(f"Dividend worker gestart voor {payload.get('count', 0)} assets")
            return
        if event == "asset_result":
            self._update_asset_row(payload)
            self.status_label.setText(
                f"Verwerkt {payload.get('index', 0)}/{payload.get('count', 0)}: {payload.get('asset_rollup', '')}"
            )
            return
        if event == "error":
            self.status_label.setText(str(payload.get("message") or "Onbekende workerfout"))
            return
        if event == "finished":
            self.status_label.setText(f"Klaar. {payload.get('count', 0)} assets verwerkt.")

    def _update_asset_row(self, payload: dict) -> None:
        asset_rollup = str(payload.get("asset_rollup") or "")
        row = self.asset_row_map.get(asset_rollup)
        if row is None:
            return
        updates = {
            "status": str(payload.get("status") or ""),
            "trailing_12m": self._format_number(payload.get("trailing_12m")),
            "forward_12m": self._format_number(payload.get("forward_12m")),
            "next_date": str(payload.get("next_date") or ""),
            "next_amount": self._format_number(payload.get("next_amount")),
            "next_earnings_date": str(payload.get("next_earnings_date") or ""),
            "earnings_symbol": str(payload.get("earnings_symbol") or ""),
            "message": str(payload.get("message") or ""),
            "raw_value": str(payload.get("raw_value") or ""),
        }
        for key, value in updates.items():
            column = self.COLUMN_KEYS.index(key)
            item = self.table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, column, item)
            item.setText(value)
            if key == "status":
                item.setBackground(self._status_color(updates["status"]))

    def _on_finished(self, exit_code: int, exit_status) -> None:
        _ = exit_status
        if self._stdout_buffer.strip():
            self._handle_worker_line(self._stdout_buffer.strip())
        self._stdout_buffer = ""
        self._process = None
        self.start_button.setEnabled(True)
        if exit_code != 0:
            QMessageBox.warning(self, "Dividend Tool", f"Worker beëindigd met exit code {exit_code}.")

    @staticmethod
    def _format_number(value) -> str:
        if value in (None, ""):
            return ""
        try:
            return f"{float(value):.4f}".rstrip("0").rstrip(".")
        except Exception:
            return str(value)

    @staticmethod
    def _status_color(status: str) -> QColor:
        mapping = {
            "idle": QColor("#efe6d2"),
            "ok": QColor("#d8ead3"),
            "no_data": QColor("#fce5cd"),
            "skipped": QColor("#d9d9d9"),
            "error": QColor("#f4cccc"),
        }
        return mapping.get(status, QColor("#efe6d2"))


def parse_cli_args(argv: list[str]) -> tuple[bool, Path]:
    worker = "--worker" in argv
    db_path = DEFAULT_DB_PATH
    if "--db" in argv:
        idx = argv.index("--db")
        if idx + 1 < len(argv):
            db_path = Path(argv[idx + 1])
    return worker, db_path


def run_worker(db_path: Path) -> int:
    host, port, client_id = load_ib_settings()
    assets = load_assets(db_path)
    worker = DividendIbWorker(host=host, port=port, client_id=client_id, assets=assets, db_path=db_path)
    try:
        worker.fetch_all()
    except Exception as exc:
        print(json.dumps({"event": "error", "message": str(exc)}), flush=True)
        return 1
    return 0


def run_gui(db_path: Path) -> int:
    app = QApplication(sys.argv)
    window = DividendToolWindow(db_path=db_path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    is_worker, db_path = parse_cli_args(sys.argv[1:])
    if is_worker:
        raise SystemExit(run_worker(db_path))
    raise SystemExit(run_gui(db_path))

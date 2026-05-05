"""
PySide6 main window for the Vol Surface POC.

Layout:
  ┌─ top bar ──────────────────────────────────────────────────────────────┐
  │  [Asset combo]  [Ophalen]  [Laad cache]   status …   [▓▓░░ progress]  │
  ├─ controls ─────────────────────────────────────────────────────────────┤
  │  X-as: ○ Strike  ● Moneyness  ○ Delta     Type: ● Calls ○ Puts ○ Beide │
  ├─ tabs ─────────────────────────────────────────────────────────────────┤
  │  [3D Surface]  [Smile Lines]  [Heatmap]                                │
  │              QWebEngineView  (plotly HTML)                             │
  ├─ console (toggle) ─────────────────────────────────────────────────────┤
  │  raw stdout output from IB collector                                   │
  └────────────────────────────────────────────────────────────────────────┘
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from types import SimpleNamespace
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QTextCursor, QFont
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QSizePolicy, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

import surface_builder as sb
import cp_chain_reader as cp
from config_reader import get_stock_db_path, get_ib_port
from db_reader import load_assets, load_optie_referentie
from ib_collector import IbCollector

LOG_DIR = Path(__file__).parent / "logs"


# ── stdout redirector ─────────────────────────────────────────────────────────

class _StdoutRedirect(QObject):
    """Captures sys.stdout writes and emits them as a Qt signal (thread-safe)."""
    text_written = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._original = sys.stdout
        LOG_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = LOG_DIR / f"vol_surf_{stamp}.log"
        self._log = self.path.open("a", encoding="utf-8")

    def install(self) -> None:
        sys.stdout = self

    def uninstall(self) -> None:
        sys.stdout = self._original
        self._log.close()

    def write(self, text: str) -> None:
        if text:
            self._original.write(text)          # keep terminal output too
            self._log.write(text)
            self._log.flush()
            self.text_written.emit(text)

    def flush(self) -> None:
        self._original.flush()
        self._log.flush()


# ── background fetch worker ───────────────────────────────────────────────────

class _FetchWorker(QObject):
    progress = Signal(int, int, str)   # done, total, message
    diagnostics = Signal(object)       # dict[str, pd.DataFrame]
    finished = Signal(object)          # pd.DataFrame
    error    = Signal(str)

    def __init__(self, asset_row: dict, stock_db_path: str, ib_port: int = 7496,
                 dte_min: int = 3, dte_max: int = 60, moneyness_pct: int = 10,
                 mode: str = "full") -> None:
        super().__init__()
        self._row          = asset_row
        self._db           = stock_db_path
        self._port         = ib_port
        self._dte_min      = dte_min
        self._dte_max      = dte_max
        self._moneyness    = moneyness_pct / 100.0
        self._mode         = mode

    def run(self) -> None:
        try:
            self._do_run()
        except Exception as exc:
            self.error.emit(str(exc))

    def _do_run(self) -> None:
        row        = self._row
        symbol     = (row.get("ib_symbol") or row.get("asset_rollup") or "").strip()
        currency   = (row.get("ib_currency") or "EUR").strip()
        exchange   = (row.get("prim_exchange") or row.get("exchange") or "SMART").strip()
        asset_roll = row.get("asset_rollup", symbol)

        if self._mode == "cp_chain":
            self._do_cp_chain(symbol, currency, asset_roll)
            return

        self.progress.emit(0, 100, f"Verbinden met IB Gateway (poort {self._port})…")
        col = IbCollector(port=self._port)
        if not col.connect():
            self.error.emit(f"Kan niet verbinden met IB Gateway op poort {self._port}.\n"
                            "Controleer of Gateway/TWS actief is.")
            return

        try:
            params = None
            spot = None

            if self._mode in ("full", "iv"):
                self.progress.emit(5, 100, f"Spotprijs ophalen voor {symbol}…")
                spot = col.fetch_spot_price(symbol, currency, exchange)
                if not spot:
                    self.error.emit(
                        f"Kon spotprijs niet ophalen voor {symbol} / {currency} / {exchange}.\n"
                        "Controleer symbol, currency en exchange in asset_rollup_data."
                    )
                    return
                self.progress.emit(12, 100, f"Spot: {spot:.4f} {currency}")

            if self._mode == "iv":
                self.progress.emit(15, 100, "Nieuwste chain-cache laden…")
                chain_df = IbCollector.load_latest_chain(symbol)
                if chain_df is None or chain_df.empty:
                    self.error.emit(
                        f"Geen chain-cache gevonden voor {symbol}.\n"
                        "Gebruik eerst 'Haal CP chain'."
                    )
                    return
                params = IbCollector.chain_df_to_params(chain_df)
                self.diagnostics.emit({
                    "series": self._chain_summary(chain_df),
                    "attempts": pd.DataFrame(),
                    "chain": chain_df,
                })
                expiries = chain_df["expiry"].nunique() if "expiry" in chain_df else 0
                chain_path = IbCollector.best_chain_path(symbol) or ""
                self.progress.emit(
                    25, 100,
                    f"Beste chain-cache: {len(chain_df)} paren, {expiries} expiries"
                    + (f" ({Path(chain_path).name})" if chain_path else "")
                )

            if self._mode in ("full", "chain"):
                self.progress.emit(15, 100, "Optieketen ophalen via IB secDef/wildcard…")
                params = col.fetch_option_params(symbol, currency, exchange)
                if not params:
                    self.error.emit(
                        f"Kon optieketen niet ophalen voor {symbol}.\n"
                        "Mogelijk heeft dit asset geen optie-serie bij IB."
                    )
                    return
                n_str = len(params["strikes"])
                n_exp = len(params["expiries"])
                self.progress.emit(25, 100, f"Keten: {n_str} strikes × {n_exp} expiries")
                IbCollector.save_chain_to_parquet(params, symbol, currency, port=self._port)

            if self._mode == "chain":
                chain_df = IbCollector.params_to_chain_df(params, symbol, currency, port=self._port)
                self.diagnostics.emit({
                    "series": self._chain_summary(chain_df),
                    "attempts": pd.DataFrame(),
                    "chain": chain_df,
                })
                path = IbCollector.best_chain_path(symbol) or IbCollector.latest_chain_path(symbol) or ""
                name = Path(path).name if path else "chain parquet"
                self.progress.emit(100, 100, f"Chain opgeslagen: {name}")
                self.finished.emit(pd.DataFrame())
                return

            opt_ref = load_optie_referentie(self._db, asset_roll)
            if opt_ref:
                self.progress.emit(27, 100,
                    f"Optie-ref: exchange={opt_ref['opt_exchange']}  "
                    f"tc={opt_ref['opt_tradingclass']}")
            else:
                self.progress.emit(27, 100, "Geen optie-referentie gevonden — IB chain params gebruikt")

            def on_progress(done: int, total: int, msg: str) -> None:
                pct = 30 + int(done / total * 65)
                self.progress.emit(pct, 100, msg)

            self.progress.emit(30, 100, "IV ophalen per contract (snapshot mode)…")
            df = col.fetch_option_ivs(
                symbol=symbol,
                currency=currency,
                spot=spot,
                params=params,
                opt_ref=opt_ref,
                dte_min=self._dte_min,
                dte_max=self._dte_max,
                moneyness_range=self._moneyness,
                on_progress=on_progress,
            )
            self.diagnostics.emit({
                "series": col.last_series.copy(),
                "attempts": col.last_attempts.copy(),
                "chain": pd.DataFrame(),
            })

            if df.empty:
                self.error.emit(
                    "Geen IV data ontvangen.\n\n"
                    "Buiten trading hours levert IB MODEL_OPTION (field 13) data.\n"
                    "Dit werkt het best voor liquide aandelen met actieve optiemarkten.\n"
                    "Probeer een andere asset of wacht tot market hours."
                )
                return

            IbCollector.save_to_parquet(df, symbol)
            self.progress.emit(100, 100, f"Gereed — {len(df)} IV punten opgeslagen")
            self.finished.emit(df)

        finally:
            col.disconnect()

    def _do_cp_chain(self, symbol: str, currency: str, asset_roll: str) -> None:
        self.progress.emit(0, 100, "Client Portal chain ophalen...")
        opt_ref = load_optie_referentie(self._db, asset_roll)
        cp_exchange = (opt_ref or {}).get("opt_exchange") or "AUTO"
        if cp_exchange:
            print(f"[diagnostics] CP chain exchange preference: {cp_exchange}")
        args = SimpleNamespace(
            symbol=symbol,
            base_url=cp.DEFAULT_BASE_URL,
            currency=currency,
            exchange=cp_exchange,
            spot=None,
            spot_from_db=True,
            require_spot=True,
            moneyness_min=0.90,
            moneyness_max=self._moneyness,
            max_months=3,
            max_strikes_per_side=20,
            no_validate=False,
            sleep=0.0,
            timeout=20.0,
            output="",
        )
        df = cp.build_chain(args)
        if df.empty:
            self.error.emit(f"Client Portal gaf geen chain-rijen terug voor {symbol}.")
            return
        path = cp.save(df, symbol, None)
        self.diagnostics.emit({
            "series": self._chain_summary(df),
            "attempts": pd.DataFrame(),
            "chain": df,
        })
        expiries = df["expiry"].nunique() if "expiry" in df else 0
        self.progress.emit(100, 100, f"CP chain opgeslagen: {len(df)} rijen, {expiries} expiries")
        print(f"[diagnostics] CP chain saved: {path}")
        self.finished.emit(pd.DataFrame())

    @staticmethod
    def _chain_summary(chain_df: pd.DataFrame) -> pd.DataFrame:
        if chain_df.empty:
            return pd.DataFrame()
        df = chain_df.copy()
        try:
            today = pd.Timestamp.today().normalize()
            exp = pd.to_datetime(df["expiry"], format="%Y%m%d", errors="coerce")
            df["dte"] = (exp - today).dt.days
        except Exception:
            df["dte"] = None
        return (
            df.groupby(["expiry", "weekday"], dropna=False)
            .agg(
                dte=("dte", "first"),
                available_strikes=("strike", "nunique"),
                min_strike=("strike", "min"),
                max_strike=("strike", "max"),
            )
            .reset_index()
            .sort_values("expiry")
        )


# ── main window ───────────────────────────────────────────────────────────────

class VolSurfWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.resize(1440, 920)

        self._df:           pd.DataFrame | None = None
        self._series_df:    pd.DataFrame | None = None
        self._attempts_df:  pd.DataFrame | None = None
        self._chain_df:     pd.DataFrame | None = None
        self._parquet_path: str                 = ""
        self._stock_db:     str                 = get_stock_db_path()
        self._ib_port:      int                 = get_ib_port()
        self._update_title()
        self._assets:       list[dict]          = []
        self._fetch_thread: QThread | None      = None
        self._fetch_worker: _FetchWorker | None = None

        self._stdout = _StdoutRedirect(self)
        self._stdout.text_written.connect(self._append_console)
        self._stdout.install()

        self._setup_ui()
        self._load_assets()

    def _update_title(self) -> None:
        broker = "LYNX" if self._ib_port == 7496 else f"IB direct"
        self.setWindowTitle(f"Vol Surface POC — {broker} (poort {self._ib_port})")

    def _on_port_changed(self, port: int) -> None:
        self._ib_port = int(port)
        self._update_title()

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(4)

        # top bar
        top = QHBoxLayout()
        root.addLayout(top)

        top.addWidget(QLabel("Asset:"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(240)
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.setMaximumWidth(400)
        top.addWidget(self.combo)

        top.addWidget(QLabel("Poort:"))
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(self._ib_port)
        self.spin_port.setFixedWidth(78)
        self.spin_port.setToolTip("IB Gateway/TWS API poort, bv. LYNX 7496 of IBKR TWS 7498")
        self.spin_port.valueChanged.connect(self._on_port_changed)
        top.addWidget(self.spin_port)

        self.btn_fetch = QPushButton("Ophalen ▶")
        self.btn_fetch.setFixedWidth(95)
        self.btn_fetch.clicked.connect(self._on_fetch)
        top.addWidget(self.btn_fetch)

        self.btn_cp_chain = QPushButton("Haal CP chain")
        self.btn_cp_chain.setFixedWidth(115)
        self.btn_cp_chain.setToolTip("Haal een Client Portal chain op met DB-spot filtering")
        self.btn_cp_chain.clicked.connect(self._on_fetch_cp_chain)
        top.addWidget(self.btn_cp_chain)

        self.btn_chain = QPushButton("TWS chain")
        self.btn_chain.setFixedWidth(85)
        self.btn_chain.setToolTip("Fallback/test: haal option chain via TWS/IB Gateway")
        self.btn_chain.clicked.connect(self._on_fetch_chain)
        top.addWidget(self.btn_chain)

        self.btn_iv = QPushButton("IV uit chain")
        self.btn_iv.setFixedWidth(100)
        self.btn_iv.setToolTip("Gebruik de nieuwste chain-cache en haal alleen IV snapshots op")
        self.btn_iv.clicked.connect(self._on_fetch_iv_from_chain)
        top.addWidget(self.btn_iv)

        self.btn_cache = QPushButton("Laad cache")
        self.btn_cache.setFixedWidth(100)
        self.btn_cache.clicked.connect(self._on_load_cache)
        top.addWidget(self.btn_cache)

        self.btn_clear = QPushButton("Wis cache")
        self.btn_clear.setFixedWidth(90)
        self.btn_clear.setToolTip("Verwijder het parquet-bestand voor dit asset; volgende run haalt verse data op")
        self.btn_clear.clicked.connect(self._on_clear_cache)
        top.addWidget(self.btn_clear)

        self.status = QLabel("Selecteer een asset. Gebruik 'Haal CP chain' voor chain-cache, daarna 'IV uit chain'.")
        self.status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedWidth(160)
        self.progress.setVisible(False)
        top.addWidget(self.progress)

        # control bar
        ctrl = QHBoxLayout()
        root.addLayout(ctrl)

        # X-axis toggle
        x_box = QGroupBox("X-as")
        x_lay = QHBoxLayout(x_box)
        x_lay.setContentsMargins(6, 2, 6, 2)
        self._x_grp = QButtonGroup(self)
        for label, val in [("Strike", "strike"), ("Moneyness", "moneyness"), ("Delta", "delta")]:
            rb = QRadioButton(label)
            rb.setProperty("v", val)
            if val == "moneyness":
                rb.setChecked(True)
            self._x_grp.addButton(rb)
            x_lay.addWidget(rb)
        self._x_grp.buttonClicked.connect(self._on_controls_changed)
        ctrl.addWidget(x_box)

        # Right toggle
        r_box = QGroupBox("Type")
        r_lay = QHBoxLayout(r_box)
        r_lay.setContentsMargins(6, 2, 6, 2)
        self._r_grp = QButtonGroup(self)
        for label, val in [("Calls", "C"), ("Puts", "P"), ("Beide", "B")]:
            rb = QRadioButton(label)
            rb.setProperty("v", val)
            if val == "C":
                rb.setChecked(True)
            self._r_grp.addButton(rb)
            r_lay.addWidget(rb)
        self._r_grp.buttonClicked.connect(self._on_controls_changed)
        ctrl.addWidget(r_box)

        # DTE filter
        dte_box = QGroupBox("DTE")
        dte_lay = QHBoxLayout(dte_box)
        dte_lay.setContentsMargins(6, 2, 6, 2)
        dte_lay.addWidget(QLabel("min:"))
        self.spin_dte_min = QSpinBox()
        self.spin_dte_min.setRange(0, 365)
        self.spin_dte_min.setValue(3)
        self.spin_dte_min.setSuffix("d")
        self.spin_dte_min.setFixedWidth(62)
        dte_lay.addWidget(self.spin_dte_min)
        dte_lay.addWidget(QLabel("max:"))
        self.spin_dte_max = QSpinBox()
        self.spin_dte_max.setRange(1, 60)
        self.spin_dte_max.setValue(60)
        self.spin_dte_max.setSuffix("d")
        self.spin_dte_max.setFixedWidth(66)
        dte_lay.addWidget(self.spin_dte_max)
        ctrl.addWidget(dte_box)

        # Moneyness filter
        mn_box = QGroupBox("K/S max")
        mn_lay = QHBoxLayout(mn_box)
        mn_lay.setContentsMargins(6, 2, 6, 2)
        mn_lay.addWidget(QLabel("max:"))
        self.spin_moneyness = QSpinBox()
        self.spin_moneyness.setRange(1, 110)
        self.spin_moneyness.setValue(110)
        self.spin_moneyness.setSuffix("%")
        self.spin_moneyness.setFixedWidth(62)
        mn_lay.addWidget(self.spin_moneyness)
        ctrl.addWidget(mn_box)

        ctrl.addStretch()

        # info label
        self.info = QLabel("")
        self.info.setStyleSheet("color: #666; font-size: 11px;")
        ctrl.addWidget(self.info)

        # chart tabs
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self._view_3d      = QWebEngineView()
        self._view_smile   = QWebEngineView()
        self._view_heatmap = QWebEngineView()
        self._series_table = QTableWidget()
        self._attempts_table = QTableWidget()
        self._parquet_table = QTableWidget()
        self._chain_table = QTableWidget()

        self.tabs.addTab(self._view_3d,      "3D Surface")
        self.tabs.addTab(self._view_smile,   "Smile Lines")
        self.tabs.addTab(self._view_heatmap, "Heatmap")
        self.tabs.addTab(self._series_table,    "Series")
        self.tabs.addTab(self._attempts_table,  "IB Resultaat")
        self.tabs.addTab(self._parquet_table,   "Parquet")
        self.tabs.addTab(self._chain_table,      "Chain cache")

        for table in (self._series_table, self._attempts_table, self._parquet_table, self._chain_table):
            table.setAlternatingRowColors(True)
            table.setSortingEnabled(True)
            table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.tabs.currentChanged.connect(self._on_tab_changed)

        # console panel
        console_bar = QHBoxLayout()
        root.addLayout(console_bar)

        self.btn_console = QPushButton("▼ Console")
        self.btn_console.setFixedWidth(100)
        self.btn_console.setCheckable(True)
        self.btn_console.setChecked(False)
        self.btn_console.clicked.connect(self._on_toggle_console)
        console_bar.addWidget(self.btn_console)

        self.btn_clear_console = QPushButton("Wis")
        self.btn_clear_console.setFixedWidth(50)
        self.btn_clear_console.clicked.connect(self._on_clear_console)
        console_bar.addWidget(self.btn_clear_console)
        console_bar.addStretch()

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setVisible(False)
        self.console.setFixedHeight(180)
        font = QFont("Consolas", 9)
        font.setStyleHint(QFont.Monospace)
        self.console.setFont(font)
        self.console.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #d4d4d4; border: none; }"
        )
        root.addWidget(self.console)

    # ── asset loading ─────────────────────────────────────────────────────────

    def _load_assets(self) -> None:
        try:
            self._assets = load_assets(self._stock_db)
        except Exception as exc:
            self.status.setText(f"Fout bij laden assets: {exc}")
            return

        self.combo.clear()
        for a in self._assets:
            sym = a.get("ib_symbol") or ""
            ccy = a.get("ib_currency") or ""
            label = f"{a['asset_rollup']}   ({sym} / {ccy})"
            self.combo.addItem(label, userData=a)

        self.status.setText(f"{len(self._assets)} assets geladen uit DB.")

    # ── property helpers ──────────────────────────────────────────────────────

    def _current_asset(self) -> dict | None:
        return self.combo.currentData()

    def _x_mode(self) -> str:
        btn = self._x_grp.checkedButton()
        return btn.property("v") if btn else "moneyness"

    def _right(self) -> str:
        btn = self._r_grp.checkedButton()
        return btn.property("v") if btn else "C"

    def _current_symbol(self) -> str:
        a = self._current_asset()
        if not a:
            return ""
        return (a.get("ib_symbol") or a.get("asset_rollup") or "").strip()

    # ── button handlers ───────────────────────────────────────────────────────

    def _on_fetch(self) -> None:
        asset = self._current_asset()
        if asset:
            self._start_fetch(asset, "full")

    def _on_fetch_chain(self) -> None:
        asset = self._current_asset()
        if asset:
            self._start_fetch(asset, "chain")

    def _on_fetch_cp_chain(self) -> None:
        asset = self._current_asset()
        if asset:
            self._start_fetch(asset, "cp_chain")

    def _on_fetch_iv_from_chain(self) -> None:
        asset = self._current_asset()
        if asset:
            self._start_fetch(asset, "iv")

    def _on_load_cache(self) -> None:
        symbol = self._current_symbol()
        if not symbol:
            return
        df = IbCollector.load_latest_parquet(symbol)
        if df is None or df.empty:
            self.status.setText(f"Geen cache gevonden voor {symbol}.")
        else:
            self._df = df
            self._series_df = None
            self._attempts_df = None
            self._chain_df = IbCollector.load_latest_chain(symbol)
            self._parquet_path = IbCollector.latest_parquet_path(symbol) or ""
            self._update_info()
            self._update_diagnostic_tables()
            self.status.setText(f"Cache geladen: {len(df)} IV punten voor {symbol}.")
            self._render_charts()

    def _on_clear_cache(self) -> None:
        from ib_collector import DATA_DIR
        symbol = self._current_symbol()
        if not symbol:
            return
        files = sorted(DATA_DIR.glob(f"{symbol}_*.parquet"), reverse=True)
        files = [f for f in files if not f.name.startswith("CHAIN_")]
        if not files:
            self.status.setText(f"Geen cache om te verwijderen voor {symbol}.")
            return
        for f in files:
            f.unlink(missing_ok=True)
        self._df = None
        self._series_df = None
        self._attempts_df = None
        self._chain_df = None
        self._parquet_path = ""
        self._update_diagnostic_tables()
        self.status.setText(f"Cache gewist voor {symbol} ({len(files)} bestand(en)).")

    def _on_controls_changed(self) -> None:
        if self._df is not None:
            self._render_charts()

    def _on_tab_changed(self, _index: int) -> None:
        pass    # charts are pre-rendered; nothing needed here

    # ── console ───────────────────────────────────────────────────────────────

    def _on_toggle_console(self, checked: bool) -> None:
        self.console.setVisible(checked)
        self.btn_console.setText("▲ Console" if checked else "▼ Console")

    def _on_clear_console(self) -> None:
        self.console.clear()

    def _append_console(self, text: str) -> None:
        # Auto-open console on first output during a fetch
        if not self.console.isVisible() and self.btn_console.isChecked() is False:
            if text.strip().startswith("[IB]") or text.strip().startswith("[collector]"):
                self.btn_console.setChecked(True)
                self.console.setVisible(True)
                self.btn_console.setText("▲ Console")

        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.console.setTextCursor(cursor)
        self.console.insertPlainText(text)
        self.console.ensureCursorVisible()

    def closeEvent(self, event) -> None:
        self._stdout.uninstall()
        super().closeEvent(event)

    # ── fetch pipeline ────────────────────────────────────────────────────────

    def _on_thread_finished(self) -> None:
        self._fetch_thread = None
        self._fetch_worker = None

    def _start_fetch(self, asset: dict, mode: str = "full") -> None:
        try:
            running = self._fetch_thread is not None and self._fetch_thread.isRunning()
        except RuntimeError:
            running = False
            self._fetch_thread = None

        if running:
            self.status.setText("Bezig met ophalen — even geduld…")
            return

        self._set_buttons_enabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)

        worker = _FetchWorker(
            asset, self._stock_db, self._ib_port,
            dte_min=self.spin_dte_min.value(),
            dte_max=self.spin_dte_max.value(),
            moneyness_pct=self.spin_moneyness.value(),
            mode=mode,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.diagnostics.connect(self._on_diagnostics)
        worker.finished.connect(self._on_fetch_done)
        worker.error.connect(self._on_fetch_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)

        self._fetch_thread = thread
        self._fetch_worker = worker
        thread.start()

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self.btn_fetch.setEnabled(enabled)
        self.btn_chain.setEnabled(enabled)
        self.btn_cp_chain.setEnabled(enabled)
        self.btn_iv.setEnabled(enabled)
        self.btn_cache.setEnabled(enabled)
        self.btn_clear.setEnabled(enabled)

    def _on_progress(self, done: int, total: int, msg: str) -> None:
        pct = int(done / total * 100) if total else 0
        self.progress.setValue(pct)
        self.status.setText(msg)

    def _on_diagnostics(self, diagnostics: dict) -> None:
        self._series_df = diagnostics.get("series")
        self._attempts_df = diagnostics.get("attempts")
        chain = diagnostics.get("chain")
        if chain is not None and not chain.empty:
            self._chain_df = chain
        self._update_diagnostic_tables()

    def _on_fetch_done(self, df: pd.DataFrame) -> None:
        if df is not None and not df.empty:
            self._df = df
            symbol = self._current_symbol()
            self._parquet_path = IbCollector.latest_parquet_path(symbol) or ""
        self._set_buttons_enabled(True)
        self.progress.setVisible(False)
        self._update_info()
        self._update_diagnostic_tables()
        if df is None or df.empty:
            self.status.setText("Gereed — chain-cache bijgewerkt.")
            self.tabs.setCurrentWidget(self._chain_table)
            return
        self.status.setText(f"Gereed — {len(df)} IV punten. Grafieken worden gebouwd…")
        self._render_charts()

    def _on_fetch_error(self, msg: str) -> None:
        self._set_buttons_enabled(True)
        self.progress.setVisible(False)
        self.status.setText(f"Fout: {msg[:80]}")
        if msg.startswith("Geen IV data ontvangen"):
            self.tabs.setCurrentWidget(self._attempts_table)
            self.status.setText(
                "Geen IV data ontvangen. Bekijk 'IB Resultaat' en de console voor market-data/weekend diagnose."
            )
            return
        QMessageBox.warning(self, "Fout bij ophalen", msg)

    # ── chart rendering ───────────────────────────────────────────────────────

    def _update_info(self) -> None:
        if self._df is None or self._df.empty:
            self.info.setText("")
            return
        df   = self._df
        syms = df["symbol"].iloc[0] if "symbol" in df.columns else ""
        spot = df["spot"].iloc[0]   if "spot"   in df.columns else 0
        nc   = len(df[df["right"] == "C"])
        np_  = len(df[df["right"] == "P"])
        dte_range = f"{df['dte'].min()}–{df['dte'].max()}d"
        self.info.setText(
            f"{syms}  spot={spot:.2f}  "
            f"calls={nc}  puts={np_}  DTE={dte_range}"
        )

    def _set_table_df(self, table: QTableWidget, df: pd.DataFrame | None, max_rows: int = 500) -> None:
        table.setSortingEnabled(False)
        table.clear()
        if df is None or df.empty:
            table.setRowCount(0)
            table.setColumnCount(1)
            table.setHorizontalHeaderLabels(["Geen data"])
            table.setSortingEnabled(True)
            return

        show = df.head(max_rows).copy()
        table.setRowCount(len(show))
        table.setColumnCount(len(show.columns))
        table.setHorizontalHeaderLabels([str(c) for c in show.columns])
        for r_idx, row in enumerate(show.itertuples(index=False)):
            for c_idx, value in enumerate(row):
                text = "" if pd.isna(value) else str(value)
                table.setItem(r_idx, c_idx, QTableWidgetItem(text))
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)

    def _update_diagnostic_tables(self) -> None:
        self._set_table_df(self._series_table, self._series_df)
        self._set_table_df(self._attempts_table, self._attempts_df)
        self._set_table_df(self._parquet_table, self._df)
        self._set_table_df(self._chain_table, self._chain_df)

        series = 0 if self._series_df is None else len(self._series_df)
        attempts = 0 if self._attempts_df is None else len(self._attempts_df)
        got_iv = 0
        if self._attempts_df is not None and "got_iv" in self._attempts_df.columns:
            got_iv = int(self._attempts_df["got_iv"].fillna(False).sum())
        if attempts:
            print(f"[diagnostics] Series={series}, attempted={attempts}, got IV={got_iv}")
        if self._parquet_path:
            print(f"[diagnostics] Latest parquet: {self._parquet_path}")

    def _render_charts(self) -> None:
        if self._df is None or self._df.empty:
            return

        df     = self._df.copy()
        x_mode = self._x_mode()
        right  = self._right()

        if x_mode == "delta":
            df = df.dropna(subset=["delta"])
            if df.empty:
                self.status.setText(
                    "Geen delta data beschikbaar. "
                    "Kies Strike of Moneyness als X-as."
                )
                return

        self.status.setText("Grafieken bouwen…")
        try:
            html_3d      = sb.build_3d_surface(df, x_mode, right)
            html_smile   = sb.build_smile_lines(df, x_mode, right)
            html_heatmap = sb.build_heatmap(df, x_mode, right)
        except Exception as exc:
            self.status.setText(f"Fout bij bouwen grafieken: {exc}")
            return

        self._view_3d.setHtml(html_3d)
        self._view_smile.setHtml(html_smile)
        self._view_heatmap.setHtml(html_heatmap)

        n_pts = len(df)
        self.status.setText(
            f"{n_pts} IV punten weergegeven — "
            f"X={x_mode}  type={'Calls' if right=='C' else 'Puts' if right=='P' else 'Beide'}"
        )

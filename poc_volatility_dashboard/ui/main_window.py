from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from traceback import format_exc

import numpy as np

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from poc_volatility_dashboard.analysis.volatility_analysis import (
    VolatilityAnalysis,
    analyze_volatility,
    prepare_volatility_data,
)
from poc_volatility_dashboard.data.db_volatility_source import (
    AssetRow,
    filter_duration,
    load_assets,
    load_volatility_history,
)
from poc_volatility_dashboard.data.ibkr_volatility_source import (
    IbkrRequest,
    fetch_ibkr_implied_volatility,
)
from poc_volatility_dashboard.data.settings_reader import AppSettings, load_settings


@dataclass(frozen=True)
class LoadRequest:
    source: str
    db_path: str
    asset_rollup: str
    symbol: str
    currency: str
    duration: str
    scale_mode: str
    ib_host: str
    ib_port: int
    ib_client_id: int


@dataclass(frozen=True)
class LoadResult:
    source: str
    symbol: str
    rows: int
    analysis: VolatilityAnalysis


class AnalysisWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, request: LoadRequest) -> None:
        super().__init__()
        self.request = request

    def run(self) -> None:
        try:
            if self.request.source == "IBKR":
                raw_df = fetch_ibkr_implied_volatility(
                    IbkrRequest(
                        symbol=self.request.symbol,
                        host=self.request.ib_host,
                        port=self.request.ib_port,
                        client_id=self.request.ib_client_id,
                        duration=self.request.duration,
                        currency=self.request.currency,
                    )
                )
            else:
                raw_df = load_volatility_history(self.request.db_path, self.request.asset_rollup)
                raw_df = filter_duration(raw_df, self.request.duration)

            if raw_df.empty:
                raise RuntimeError("No implied-volatility rows found")

            volatility_data = prepare_volatility_data(raw_df, scale_mode=self.request.scale_mode)
            analysis = analyze_volatility(volatility_data)
            self.finished.emit(
                LoadResult(
                    source=self.request.source,
                    symbol=self.request.symbol,
                    rows=len(raw_df),
                    analysis=analysis,
                )
            )
        except Exception as exc:
            self.failed.emit(f"{exc}\n\n{format_exc()}")


class MplCanvas(FigureCanvas):
    def __init__(self) -> None:
        self.figure = Figure(figsize=(18, 6), tight_layout=True)
        self.axes = self.figure.subplots(1, 3)
        super().__init__(self.figure)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings: AppSettings = load_settings()
        self.assets: list[AssetRow] = []
        self.current_result: LoadResult | None = None
        self.worker_thread: QThread | None = None
        self.worker: AnalysisWorker | None = None
        self._loading_assets = False
        self._pending_auto_analyze = False

        self.setWindowTitle("PoC Volatility Dashboard")
        self.resize(1600, 950)
        self.auto_analyze_timer = QTimer(self)
        self.auto_analyze_timer.setSingleShot(True)
        self.auto_analyze_timer.timeout.connect(self._auto_analyze)
        self._build_ui()
        self._load_initial_settings()
        self._load_assets()

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)

        settings_box = QGroupBox("Settings")
        settings_layout = QGridLayout(settings_box)

        self.db_path_edit = QLineEdit()
        self.db_path_edit.setReadOnly(True)
        settings_layout.addWidget(QLabel("Stockdata DB"), 0, 0)
        settings_layout.addWidget(self.db_path_edit, 0, 1, 1, 5)

        self.source_combo = QComboBox()
        self.source_combo.addItems(["DB", "IBKR"])
        self.source_combo.currentTextChanged.connect(self._on_source_changed)
        self.host_edit = QLineEdit()
        self.port_edit = QLineEdit()
        self.client_id_edit = QLineEdit()
        settings_layout.addWidget(QLabel("Source"), 1, 0)
        settings_layout.addWidget(self.source_combo, 1, 1)
        settings_layout.addWidget(QLabel("Host"), 1, 2)
        settings_layout.addWidget(self.host_edit, 1, 3)
        settings_layout.addWidget(QLabel("Port"), 1, 4)
        settings_layout.addWidget(self.port_edit, 1, 5)
        settings_layout.addWidget(QLabel("Client ID"), 1, 6)
        settings_layout.addWidget(self.client_id_edit, 1, 7)
        layout.addWidget(settings_box)

        query_box = QGroupBox("Data Query")
        query_layout = QHBoxLayout(query_box)
        self.asset_combo = QComboBox()
        self.asset_combo.setEditable(True)
        self.symbol_edit = QLineEdit("SPY")
        self.currency_edit = QLineEdit("USD")
        self.duration_edit = QLineEdit("2 Y")
        self.annualize_check = QCheckBox("Apply sqrt(252)")
        self.annualize_check.setToolTip("Only enable this if the source values are daily vol, not already annualized.")
        self.auto_analyze_check = QCheckBox("Auto analyze")
        self.auto_analyze_check.setChecked(True)
        self.auto_analyze_check.setToolTip("Run analysis automatically when a different asset is selected.")
        self.analyze_button = QPushButton("Analyze")
        self.analyze_button.clicked.connect(self._start_analysis)
        self.reload_assets_button = QPushButton("Reload assets")
        self.reload_assets_button.clicked.connect(self._load_assets)

        query_layout.addWidget(QLabel("Asset"))
        query_layout.addWidget(self.asset_combo, 3)
        query_layout.addWidget(QLabel("Symbol"))
        query_layout.addWidget(self.symbol_edit)
        query_layout.addWidget(QLabel("Currency"))
        query_layout.addWidget(self.currency_edit)
        query_layout.addWidget(QLabel("Duration"))
        query_layout.addWidget(self.duration_edit)
        query_layout.addWidget(self.annualize_check)
        query_layout.addWidget(self.auto_analyze_check)
        query_layout.addWidget(self.analyze_button)
        query_layout.addWidget(self.reload_assets_button)
        layout.addWidget(query_box)

        self.asset_combo.currentIndexChanged.connect(self._asset_changed)

        summary_box = QGroupBox("Current Implied Volatility")
        summary_layout = QFormLayout(summary_box)
        self.current_iv_label = QLabel("N/A")
        self.range_label = QLabel("N/A")
        self.regime_label = QLabel("N/A")
        self.percentile_label = QLabel("N/A")
        self.signal_label = QLabel("N/A")
        summary_layout.addRow("Current IV", self.current_iv_label)
        summary_layout.addRow("IV Range", self.range_label)
        summary_layout.addRow("Current Regime", self.regime_label)
        summary_layout.addRow("Percentile", self.percentile_label)
        summary_layout.addRow("Mean Reversion Signal", self.signal_label)
        layout.addWidget(summary_box)

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(180)
        layout.addWidget(self.log_text)

        self.canvas = MplCanvas()
        layout.addWidget(self.canvas, 1)

        self.setCentralWidget(root)

    def _load_initial_settings(self) -> None:
        self.db_path_edit.setText(self.settings.stockdata_db_path)
        self.host_edit.setText(self.settings.ib_host)
        self.port_edit.setText(str(self.settings.ib_port))
        self.client_id_edit.setText(str(self.settings.ib_client_id))
        self._on_source_changed(self.source_combo.currentText())
        self._log(f"Settings loaded from {self.settings.shared_settings_path}")
        self._log(f"Local settings overlay: {self.settings.local_settings_path}")

    def _load_assets(self) -> None:
        self._loading_assets = True
        try:
            self.assets = load_assets(self.settings.stockdata_db_path)
        except Exception as exc:
            self._log(f"Could not load asset list: {exc}")
            self.assets = []

        self.asset_combo.blockSignals(True)
        self.asset_combo.clear()
        for asset in self.assets:
            self.asset_combo.addItem(asset.label, asset)
        self.asset_combo.blockSignals(False)
        self._log(f"Loaded {len(self.assets)} assets from DB")

        preferred = self._find_asset_index("SPY")
        if preferred >= 0:
            self.asset_combo.setCurrentIndex(preferred)
        elif self.assets:
            self.asset_combo.setCurrentIndex(0)
        self._loading_assets = False
        self._asset_changed()

    def _find_asset_index(self, text: str) -> int:
        needle = text.strip().upper()
        for idx, asset in enumerate(self.assets):
            if asset.asset_rollup.upper() == needle or asset.ib_symbol.upper() == needle:
                return idx
        return -1

    def _asset_changed(self) -> None:
        asset = self._selected_asset()
        if asset is None:
            typed = self.asset_combo.currentText().strip().upper()
            self.symbol_edit.setText(typed)
        else:
            self.symbol_edit.setText(asset.ib_symbol or asset.asset_rollup)
            self.currency_edit.setText(asset.ib_currency or "USD")
        self._schedule_auto_analyze()

    def _schedule_auto_analyze(self) -> None:
        if self._loading_assets or not self.auto_analyze_check.isChecked():
            return
        if self.worker_thread is not None and self.worker_thread.isRunning():
            self._pending_auto_analyze = True
            return
        self.auto_analyze_timer.start(250)

    def _auto_analyze(self) -> None:
        if not self.auto_analyze_check.isChecked():
            return
        if self.source_combo.currentText() == "IBKR":
            return
        self._start_analysis(auto=True)

    def _selected_asset(self) -> AssetRow | None:
        data = self.asset_combo.currentData()
        return data if isinstance(data, AssetRow) else None

    def _on_source_changed(self, source: str) -> None:
        use_ib = source == "IBKR"
        self.host_edit.setEnabled(use_ib)
        self.port_edit.setEnabled(use_ib)
        self.client_id_edit.setEnabled(use_ib)

    def _start_analysis(self, auto: bool = False) -> None:
        if self.worker_thread is not None and self.worker_thread.isRunning():
            if auto:
                self._pending_auto_analyze = True
            return
        asset = self._selected_asset()
        asset_rollup = asset.asset_rollup if asset else self.asset_combo.currentText().strip().upper()
        symbol = self.symbol_edit.text().strip().upper() or asset_rollup
        currency = self.currency_edit.text().strip().upper() or "USD"
        request = LoadRequest(
            source=self.source_combo.currentText(),
            db_path=self.settings.stockdata_db_path,
            asset_rollup=asset_rollup,
            symbol=symbol,
            currency=currency,
            duration=self.duration_edit.text().strip() or "2 Y",
            scale_mode="sqrt_annualize" if self.annualize_check.isChecked() else "db_raw",
            ib_host=self.host_edit.text().strip() or "127.0.0.1",
            ib_port=int(self.port_edit.text().strip() or "7496"),
            ib_client_id=int(self.client_id_edit.text().strip() or "299"),
        )
        self.analyze_button.setEnabled(False)
        prefix = "Auto analyzing" if auto else "Analyzing"
        self._log(f"{prefix} {request.asset_rollup or request.symbol} from {request.source}")

        self.worker_thread = QThread(self)
        self.worker = AnalysisWorker(request)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._analysis_finished)
        self.worker.failed.connect(self._analysis_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(lambda: self.analyze_button.setEnabled(True))
        self.worker_thread.finished.connect(self._maybe_run_pending_auto_analyze)
        self.worker_thread.start()

    def _maybe_run_pending_auto_analyze(self) -> None:
        self.worker_thread = None
        self.worker = None
        if self._pending_auto_analyze:
            self._pending_auto_analyze = False
            self._schedule_auto_analyze()

    def _analysis_finished(self, result: LoadResult) -> None:
        self.current_result = result
        self._update_summary(result.analysis)
        self._plot(result.analysis)
        self._log(f"Loaded {result.rows} rows for {result.symbol} from {result.source}")
        for line in result.analysis.notes:
            self._log(line)

    def _analysis_failed(self, message: str) -> None:
        self._log(message)
        QMessageBox.warning(self, "Analysis failed", message.splitlines()[0])

    def _update_summary(self, analysis: VolatilityAnalysis) -> None:
        vol = analysis.volatility_data["implied_vol"]
        self.current_iv_label.setText(f"{analysis.current_iv:.4f} ({analysis.current_iv * 100:.2f}%)")
        self.range_label.setText(f"Min: {vol.min():.3f} | Mean: {vol.mean():.3f} | Max: {vol.max():.3f}")
        self.regime_label.setText(analysis.regime)
        self.percentile_label.setText(f"{analysis.current_percentile:.1%}")
        self.signal_label.setText(analysis.mean_reversion_signal)

    def _plot(self, analysis: VolatilityAnalysis) -> None:
        ax1, ax2, ax3 = self.canvas.axes
        for ax in self.canvas.axes:
            ax.clear()

        df = analysis.analysis_df
        vol_data = analysis.volatility_data
        forward_reg = analysis.forward_regression

        ax1.scatter(df["current_vol"], df["forward_vol"], alpha=0.6, s=20)
        x_range = np.linspace(df["current_vol"].min(), df["current_vol"].max(), 100)
        ax1.plot(
            x_range,
            forward_reg.slope * x_range + forward_reg.intercept,
            "r-",
            linewidth=2,
            label=f"Regression R^2 = {forward_reg.r_squared:.3f}",
        )
        min_val = min(df["current_vol"].min(), df["forward_vol"].min())
        max_val = max(df["current_vol"].max(), df["forward_vol"].max())
        ax1.plot([min_val, max_val], [min_val, max_val], "k--", linewidth=1, alpha=0.7, label="y=x")
        ax1.set_xlabel("Current Implied Volatility")
        ax1.set_ylabel("30-Day Forward Average IV")
        ax1.set_title(
            f"Forward IV vs Current IV\n"
            f"y={forward_reg.slope:.3f}x+{forward_reg.intercept:.3f}, R^2={forward_reg.r_squared:.3f}"
        )
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        high = df["current_vol"] > analysis.intersection_x
        low = ~high
        ax2.scatter(df.loc[high, "current_vol"], df.loc[high, "vol_diff"], alpha=0.6, s=20, color="red", label="High Vol Regime")
        ax2.scatter(df.loc[low, "current_vol"], df.loc[low, "vol_diff"], alpha=0.6, s=20, color="blue", label="Low Vol Regime")
        if analysis.high_regression is not None and high.any():
            x_high = np.linspace(df.loc[high, "current_vol"].min(), df.loc[high, "current_vol"].max(), 100)
            ax2.plot(
                x_high,
                analysis.high_regression.slope * x_high + analysis.high_regression.intercept,
                "r-",
                linewidth=2,
                label=f"High Vol R^2 = {analysis.high_regression.r_squared:.3f}",
            )
        if analysis.low_regression is not None and low.any():
            x_low = np.linspace(df.loc[low, "current_vol"].min(), df.loc[low, "current_vol"].max(), 100)
            ax2.plot(
                x_low,
                analysis.low_regression.slope * x_low + analysis.low_regression.intercept,
                "b-",
                linewidth=2,
                label=f"Low Vol R^2 = {analysis.low_regression.r_squared:.3f}",
            )
        ax2.axhline(y=0, color="black", linestyle="--", linewidth=1, alpha=0.7, label="No Change")
        ax2.axvline(
            x=analysis.intersection_x,
            color="green",
            linestyle=":",
            linewidth=1,
            alpha=0.7,
            label=f"Regime Split (IV={analysis.intersection_x:.3f})",
        )
        ax2.set_xlabel("Current Implied Volatility")
        ax2.set_ylabel("IV Difference (Forward - Current)")
        ax2.set_title("IV Difference vs Current IV")
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        ax3.plot(vol_data.index, vol_data["implied_vol"], label="Implied Volatility", linewidth=1)
        vol_75 = vol_data["implied_vol"].quantile(0.75)
        vol_25 = vol_data["implied_vol"].quantile(0.25)
        ax3.axhline(y=vol_75, color="red", linestyle="--", alpha=0.7, label="75th Percentile")
        ax3.axhline(y=vol_25, color="green", linestyle="--", alpha=0.7, label="25th Percentile")
        ax3.axhline(y=vol_data["implied_vol"].mean(), color="black", linestyle="-", alpha=0.7, label="Mean")
        ax3.scatter(vol_data.index[-1], analysis.current_iv, color="red", s=100, zorder=5, label="Current")
        ax3.set_xlabel("Date")
        ax3.set_ylabel("Implied Volatility")
        ax3.set_title("Implied Volatility Time Series")
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        ax3.tick_params(axis="x", rotation=45)

        self.canvas.figure.tight_layout()
        self.canvas.draw()

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.appendPlainText(f"[{timestamp}] {message}")

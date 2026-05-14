from __future__ import annotations

import time
from pathlib import Path

import polars as pl
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover
    QWebEngineView = None

from portefeuille_viewer.config import get_settings
from .asset_source import load_scan_assets
from .models import AssetScanResult, OptionScanAsset, ScannerSettings
from .orchestrator import OptionChainRetrievalJob

from . import surface_builder as surface
from .chain_registry_reader import chain_summary, load_chain
from .db_access import load_assets, load_latest_spot
from .gex_scanner import aggregate_gex_by_strike, build_gex_scan, estimate_gamma_flip
from .iv_models import IvRequestSettings, SurfaceSelectionSettings
from .iv_snapshot_store import load_latest, write_snapshot
from .option_market_collector import collect_option_snapshot
from .option_selector import select_option_universe
from .spot_resolver import load_asset_last_price, resolve_spot
from .theta_scanner import build_theta_scan, filter_theta_candidates


class IvFetchWorker(QObject):
    log = Signal(str)
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, selected: pl.DataFrame, settings: IvRequestSettings) -> None:
        super().__init__()
        self.selected = selected
        self.settings = settings

    @Slot()
    def run(self) -> None:
        try:
            df = collect_option_snapshot(
                self.selected,
                self.settings,
                log=self.log.emit,
                progress=self.progress.emit,
            )
            self.finished.emit(df)
        except Exception as exc:
            self.failed.emit(str(exc))


class ChainScanWorker(QObject):
    log = Signal(str)
    result = Signal(object)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, settings: ScannerSettings, stock_db_path: str, assets: list[OptionScanAsset]) -> None:
        super().__init__()
        self.settings = settings
        self.stock_db_path = stock_db_path
        self.assets = assets
        self._job: OptionChainRetrievalJob | None = None

    @Slot()
    def run(self) -> None:
        try:
            self._job = OptionChainRetrievalJob(
                self.settings,
                self.stock_db_path,
                self.assets,
                log=self.log.emit,
                on_asset_result=self.result.emit,
            )
            self._job.run()
            self.finished.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
            self.finished.emit()

    def stop(self) -> None:
        if self._job is not None:
            self._job.stop()


class SortableTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other) -> bool:
        left = self.data(Qt.UserRole)
        right = other.data(Qt.UserRole) if other is not None else None
        if left is not None and right is not None:
            try:
                return float(left) < float(right)
            except Exception:
                return str(left) < str(right)
        return super().__lt__(other)


class IvSurfaceWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("IV Surface POC - chain parquet")
        self.resize(1420, 900)
        self.settings_manager = get_settings()
        self.stock_db_path = self.settings_manager.get_stockdata_db_path()
        scanner_cfg = self.settings_manager.get_option_chain_scanner_settings()
        self.parquet_dir = scanner_cfg["parquet_dir"]
        self.assets: list[dict] = []
        self.chain_df = pl.DataFrame()
        self.selected_df = pl.DataFrame()
        self.snapshot_df = pl.DataFrame()
        self.theta_df = pl.DataFrame()
        self.theta_display_df = pl.DataFrame()
        self.gex_df = pl.DataFrame()
        self.gex_strike_df = pl.DataFrame()
        self.gamma_flip = None
        self.spot_source = ""
        self._thread: QThread | None = None
        self._worker: IvFetchWorker | None = None
        self._scan_thread: QThread | None = None
        self._scan_worker: ChainScanWorker | None = None

        self._build_ui(scanner_cfg)
        self._load_assets()

    def _build_ui(self, scanner_cfg: dict) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        settings_box = QGroupBox("Bronnen en IBKR")
        settings_layout = QVBoxLayout(settings_box)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Stock DB"))
        self.stock_db_edit = QLineEdit(self.stock_db_path)
        self.stock_db_edit.setReadOnly(True)
        row1.addWidget(self.stock_db_edit, 2)
        row1.addWidget(QLabel("Parquet map"))
        self.parquet_dir_edit = QLineEdit(self.parquet_dir)
        row1.addWidget(self.parquet_dir_edit, 2)
        browse = QPushButton("Kies...")
        browse.clicked.connect(self._choose_parquet_dir)
        row1.addWidget(browse)
        settings_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.asset_combo = QComboBox()
        self.asset_combo.setMinimumWidth(260)
        self.asset_combo.currentIndexChanged.connect(self._asset_changed)
        self.host_edit = QLineEdit(str(scanner_cfg.get("tws_host") or "127.0.0.1"))
        self.host_edit.setFixedWidth(130)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(int(scanner_cfg.get("tws_port") or 7496))
        self.client_min_spin = QSpinBox()
        self.client_min_spin.setRange(1000, 10000)
        self.client_min_spin.setValue(int(scanner_cfg.get("client_id_min") or 1000))
        self.client_max_spin = QSpinBox()
        self.client_max_spin.setRange(1000, 10000)
        self.client_max_spin.setValue(int(scanner_cfg.get("client_id_max") or 10000))
        self.market_type_combo = QComboBox()
        self.market_type_combo.addItem("Live", 1)
        self.market_type_combo.addItem("Frozen", 2)
        self.market_type_combo.addItem("Delayed", 3)
        self.market_type_combo.addItem("Delayed frozen", 4)
        for label, widget in [
            ("Asset", self.asset_combo),
            ("Host", self.host_edit),
            ("Poort", self.port_spin),
            ("Client min", self.client_min_spin),
            ("Client max", self.client_max_spin),
            ("Data", self.market_type_combo),
        ]:
            row2.addWidget(QLabel(label))
            row2.addWidget(widget)
        row2.addStretch(1)
        load_chain_btn = QPushButton("Laad chain")
        load_chain_btn.clicked.connect(self._load_chain_for_asset)
        row2.addWidget(load_chain_btn)
        load_latest_btn = QPushButton("Laad latest IV")
        load_latest_btn.clicked.connect(self._load_latest_snapshot)
        row2.addWidget(load_latest_btn)
        settings_layout.addLayout(row2)
        root.addWidget(settings_box)

        select_box = QGroupBox("Selectie")
        select_layout = QHBoxLayout(select_box)
        self.spot_edit = QLineEdit()
        self.spot_edit.setFixedWidth(100)
        self.spot_label = QLabel("")
        self.dte_min_spin = QSpinBox()
        self.dte_min_spin.setRange(0, 5000)
        self.dte_min_spin.setValue(1)
        self.dte_max_spin = QSpinBox()
        self.dte_max_spin.setRange(1, 5000)
        self.dte_max_spin.setValue(60)
        self.mny_min_spin = QDoubleSpinBox()
        self.mny_min_spin.setRange(0.01, 10.0)
        self.mny_min_spin.setDecimals(3)
        self.mny_min_spin.setSingleStep(0.025)
        self.mny_min_spin.setValue(0.75)
        self.mny_max_spin = QDoubleSpinBox()
        self.mny_max_spin.setRange(0.01, 10.0)
        self.mny_max_spin.setDecimals(3)
        self.mny_max_spin.setSingleStep(0.025)
        self.mny_max_spin.setValue(1.25)
        self.max_strikes_spin = QSpinBox()
        self.max_strikes_spin.setRange(1, 1000)
        self.max_strikes_spin.setValue(20)
        self.right_combo = QComboBox()
        self.right_combo.addItem("Beide", "B")
        self.right_combo.addItem("Calls", "C")
        self.right_combo.addItem("Puts", "P")
        self.batch_size_spin = QSpinBox()
        self.batch_size_spin.setRange(1, 200)
        self.batch_size_spin.setValue(25)
        self.batch_wait_spin = QDoubleSpinBox()
        self.batch_wait_spin.setRange(0.5, 60.0)
        self.batch_wait_spin.setDecimals(1)
        self.batch_wait_spin.setValue(3.0)
        self.max_spread_spin = QDoubleSpinBox()
        self.max_spread_spin.setRange(0.1, 500.0)
        self.max_spread_spin.setDecimals(1)
        self.max_spread_spin.setValue(20.0)
        self.delta_min_spin = QDoubleSpinBox()
        self.delta_min_spin.setRange(0.0, 1.0)
        self.delta_min_spin.setDecimals(2)
        self.delta_min_spin.setSingleStep(0.05)
        self.delta_min_spin.setValue(0.05)
        self.delta_max_spin = QDoubleSpinBox()
        self.delta_max_spin.setRange(0.0, 1.0)
        self.delta_max_spin.setDecimals(2)
        self.delta_max_spin.setSingleStep(0.05)
        self.delta_max_spin.setValue(0.50)
        for label, widget in [
            ("Spot", self.spot_edit),
            ("DTE min", self.dte_min_spin),
            ("DTE max", self.dte_max_spin),
            ("K/S min", self.mny_min_spin),
            ("K/S max", self.mny_max_spin),
            ("Max strikes/expiry/right", self.max_strikes_spin),
            ("Right", self.right_combo),
            ("Batch", self.batch_size_spin),
            ("Wacht/batch", self.batch_wait_spin),
            ("Max spread %", self.max_spread_spin),
            ("Delta min", self.delta_min_spin),
            ("Delta max", self.delta_max_spin),
        ]:
            select_layout.addWidget(QLabel(label))
            select_layout.addWidget(widget)
        self.apply_select_btn = QPushButton("Maak selectie")
        self.apply_select_btn.clicked.connect(self._apply_selection)
        select_layout.addWidget(self.apply_select_btn)
        self.fetch_btn = QPushButton("Haal IV snapshot")
        self.fetch_btn.clicked.connect(self._fetch_iv)
        self.fetch_btn.setEnabled(False)
        select_layout.addWidget(self.fetch_btn)
        select_layout.addWidget(self.spot_label)
        root.addWidget(select_box)

        self.progress = QProgressBar()
        root.addWidget(self.progress)

        splitter = QSplitter(Qt.Vertical)
        self.tabs = QTabWidget()
        self.chain_table = QTableWidget()
        self.selection_table = QTableWidget()
        self.snapshot_table = QTableWidget()
        self.theta_table = QTableWidget()
        self.gex_table = QTableWidget()
        self.gex_strike_table = QTableWidget()
        self.theta_filter_col = QComboBox()
        self.theta_filter_text = QLineEdit()
        self.theta_filter_text.setPlaceholderText("tekst bevat")
        self.theta_filter_min = QLineEdit()
        self.theta_filter_min.setPlaceholderText("min")
        self.theta_filter_max = QLineEdit()
        self.theta_filter_max.setPlaceholderText("max")
        self.tabs.addTab(self.chain_table, "Chain parquet")
        self.tabs.addTab(self._chain_scanner_tab(scanner_cfg), "Chain scanner")
        self.tabs.addTab(self.selection_table, "Selectie")
        self.tabs.addTab(self.snapshot_table, "IV snapshot")
        self.tabs.addTab(self._theta_tab(), "Theta scanner")
        self.tabs.addTab(self.gex_table, "Gamma Exposure")
        self.tabs.addTab(self.gex_strike_table, "GEX per strike")
        self.tabs.addTab(self._web_widget("surface3d"), "3D Surface")
        self.tabs.addTab(self._web_widget("smile"), "Smile")
        self.tabs.addTab(self._web_widget("heatmap"), "Heatmap")
        self.tabs.addTab(self._web_widget("thetaheatmap"), "Theta heatmap")
        self.tabs.addTab(self._web_widget("gexstrike"), "GEX chart")
        self.tabs.addTab(self._web_widget("gexheatmap"), "GEX heatmap")
        splitter.addWidget(self.tabs)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        splitter.addWidget(self.log_edit)
        splitter.setSizes([620, 180])
        root.addWidget(splitter)
        self.setCentralWidget(central)

    def _chain_scanner_tab(self, scanner_cfg: dict) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        controls = QHBoxLayout()
        self.scan_horizon_spin = QSpinBox()
        self.scan_horizon_spin.setRange(1, 120)
        self.scan_horizon_spin.setValue(int(scanner_cfg.get("horizon_months") or 3))
        self.scan_request_pause_spin = QDoubleSpinBox()
        self.scan_request_pause_spin.setRange(0.0, 60.0)
        self.scan_request_pause_spin.setDecimals(2)
        self.scan_request_pause_spin.setSingleStep(0.25)
        self.scan_request_pause_spin.setValue(float(scanner_cfg.get("request_pause_sec") or 1.0))
        self.scan_asset_pause_spin = QDoubleSpinBox()
        self.scan_asset_pause_spin.setRange(0.0, 300.0)
        self.scan_asset_pause_spin.setDecimals(2)
        self.scan_asset_pause_spin.setSingleStep(0.5)
        self.scan_asset_pause_spin.setValue(float(scanner_cfg.get("asset_pause_sec") or 2.0))
        self.scan_right_mode_combo = QComboBox()
        self.scan_right_mode_combo.addItem("C/P gescheiden", "separate")
        self.scan_right_mode_combo.addItem("C+P in 1 request", "combined")
        mode_idx = self.scan_right_mode_combo.findData(str(scanner_cfg.get("right_request_mode") or "separate"))
        self.scan_right_mode_combo.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)
        self.scan_current_btn = QPushButton("Scan huidige asset")
        self.scan_current_btn.clicked.connect(self._start_chain_scan_current)
        self.scan_stop_btn = QPushButton("Stop scan")
        self.scan_stop_btn.setEnabled(False)
        self.scan_stop_btn.clicked.connect(self._stop_chain_scan)
        for label, control in [
            ("Maanden", self.scan_horizon_spin),
            ("Req pauze", self.scan_request_pause_spin),
            ("Asset pauze", self.scan_asset_pause_spin),
            ("Rights", self.scan_right_mode_combo),
        ]:
            controls.addWidget(QLabel(label))
            controls.addWidget(control)
        controls.addStretch(1)
        controls.addWidget(self.scan_current_btn)
        controls.addWidget(self.scan_stop_btn)
        layout.addLayout(controls)
        self.scan_result_table = QTableWidget(0, 9)
        self.scan_result_table.setHorizontalHeaderLabels(
            ["asset", "clientId", "status", "returned", "inserted", "updated", "rejected", "exchange", "parquet/error"]
        )
        self.scan_result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.scan_result_table.horizontalHeader().setDefaultSectionSize(120)
        self.scan_result_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.scan_result_table)
        return widget

    def _theta_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        filter_row = QHBoxLayout()
        self.theta_filter_col.addItem("Alle kolommen", "")
        for control in (self.theta_filter_col, self.theta_filter_text, self.theta_filter_min, self.theta_filter_max):
            filter_row.addWidget(control)
        apply_btn = QPushButton("Filter")
        apply_btn.clicked.connect(self._refresh_theta_table)
        clear_btn = QPushButton("Wis filter")
        clear_btn.clicked.connect(self._clear_theta_filter)
        filter_row.addWidget(apply_btn)
        filter_row.addWidget(clear_btn)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)
        layout.addWidget(self.theta_table)
        self.theta_filter_text.returnPressed.connect(self._refresh_theta_table)
        self.theta_filter_min.returnPressed.connect(self._refresh_theta_table)
        self.theta_filter_max.returnPressed.connect(self._refresh_theta_table)
        return widget

    def _web_widget(self, name: str):
        if QWebEngineView is None:
            widget = QTextEdit()
            widget.setReadOnly(True)
        else:
            widget = QWebEngineView()
        setattr(self, f"{name}_view", widget)
        return widget

    def _load_assets(self) -> None:
        try:
            self.assets = load_assets(self.stock_db_path, include_disabled=True)
        except Exception as exc:
            QMessageBox.critical(self, "Assets laden mislukt", str(exc))
            self.assets = []
        self.asset_combo.clear()
        for asset in self.assets:
            self.asset_combo.addItem(
                f"{asset['asset_rollup']} ({asset['ib_symbol']} / {asset['ib_currency']})",
                asset,
            )
        self._append_log(f"[assets] geladen: {len(self.assets)}")
        if self.assets:
            self._asset_changed(0)

    @Slot()
    def _asset_changed(self, _idx: int) -> None:
        asset = self._current_asset()
        if not asset:
            return
        quote = load_asset_last_price(self.stock_db_path, asset)
        if quote.price is None:
            spot, info = load_latest_spot(self.stock_db_path, asset["asset_rollup"])
            quote_price = spot
            source = "historical_data_correct"
            detail = str(info)
        else:
            quote_price = quote.price
            source = quote.source
            detail = quote.detail
        if quote_price:
            self.spot_edit.setText(f"{quote_price:.4f}")
            self.spot_source = source
            self.spot_label.setText(f"spot uit {source}: {detail}")
        else:
            self.spot_source = ""
            self.spot_label.setText(detail)

    def _load_chain_for_asset(self) -> None:
        asset = self._current_asset()
        if not asset:
            return
        try:
            self.chain_df = load_chain(self.parquet_dir_edit.text().strip(), asset["asset_rollup"])
        except Exception as exc:
            QMessageBox.critical(self, "Chain laden mislukt", str(exc))
            return
        self._append_log(f"[chain] {asset['asset_rollup']} {chain_summary(self.chain_df)}")
        self._fill_table(self.chain_table, self.chain_df.head(1000))
        self._apply_selection()

    def _apply_selection(self) -> None:
        if self.chain_df.is_empty():
            self._log_cli("[selectie] overgeslagen: chain is leeg")
            return
        started = time.perf_counter()
        self._refresh_spot_from_ibkr()
        spot = self._spot_value()
        settings = SurfaceSelectionSettings(
            dte_min=self.dte_min_spin.value(),
            dte_max=self.dte_max_spin.value(),
            moneyness_min=self.mny_min_spin.value(),
            moneyness_max=self.mny_max_spin.value(),
            max_strikes_per_expiry=self.max_strikes_spin.value(),
            right_mode=str(self.right_combo.currentData() or "B"),
        )
        self._log_cli(
            "[selectie] start "
            f"chain_rows={self.chain_df.height} spot={spot} "
            f"dte={settings.dte_min}-{settings.dte_max} "
            f"k_s={settings.moneyness_min:.3f}-{settings.moneyness_max:.3f} "
            f"max_strikes={settings.max_strikes_per_expiry} right={settings.right_mode}"
        )
        self.selected_df = select_option_universe(self.chain_df, spot, settings)
        selected_ms = (time.perf_counter() - started) * 1000.0
        self._append_log(f"[selectie] rows={self.selected_df.height}")
        self._log_cli(f"[selectie] selected_rows={self.selected_df.height} select_ms={selected_ms:.1f}")
        table_started = time.perf_counter()
        self._fill_table(self.selection_table, self.selected_df.head(1000))
        table_ms = (time.perf_counter() - table_started) * 1000.0
        total_ms = (time.perf_counter() - started) * 1000.0
        self._log_cli(f"[selectie] table_rows={min(self.selected_df.height, 1000)} table_ms={table_ms:.1f}")
        self._log_cli(f"[selectie] klaar total_ms={total_ms:.1f}")
        self.fetch_btn.setEnabled(not self.selected_df.is_empty())

    def _fetch_iv(self) -> None:
        if self.selected_df.is_empty():
            return
        settings = IvRequestSettings(
            tws_host=self.host_edit.text().strip() or "127.0.0.1",
            tws_port=self.port_spin.value(),
            client_id_min=min(self.client_min_spin.value(), self.client_max_spin.value()),
            client_id_max=max(self.client_min_spin.value(), self.client_max_spin.value()),
            market_data_type=int(self.market_type_combo.currentData() or 1),
            batch_size=self.batch_size_spin.value(),
            batch_wait_sec=self.batch_wait_spin.value(),
        )
        self.progress.setRange(0, self.selected_df.height)
        self.progress.setValue(0)
        self.fetch_btn.setEnabled(False)
        self._thread = QThread(self)
        self._worker = IvFetchWorker(self.selected_df, settings)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append_log)
        self._worker.progress.connect(self._progress)
        self._worker.failed.connect(self._fetch_failed)
        self._worker.finished.connect(self._fetch_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _start_chain_scan_current(self) -> None:
        asset = self._current_asset()
        if not asset:
            return
        try:
            scan_assets = load_scan_assets(self.stock_db_path, include_disabled=True)
        except Exception as exc:
            QMessageBox.critical(self, "Scanner assets laden mislukt", str(exc))
            return
        current_variants = [item for item in scan_assets if item.asset_rollup == asset["asset_rollup"]]
        if not current_variants:
            QMessageBox.information(self, "Asset ontbreekt", f"Geen scanner-config gevonden voor {asset['asset_rollup']}.")
            return
        settings = self._chain_scanner_settings()
        self.scan_result_table.setRowCount(0)
        self.scan_current_btn.setEnabled(False)
        self.scan_stop_btn.setEnabled(True)
        self._scan_thread = QThread(self)
        self._scan_worker = ChainScanWorker(settings, self.stock_db_path, current_variants)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.log.connect(self._append_log)
        self._scan_worker.log.connect(self._log_cli)
        self._scan_worker.result.connect(self._append_chain_scan_result)
        self._scan_worker.failed.connect(self._chain_scan_failed)
        self._scan_worker.finished.connect(self._chain_scan_finished)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._append_log(
            f"[chain-scan] start {asset['asset_rollup']} variants={len(current_variants)} months={settings.horizon_months} "
            f"rights={settings.right_request_mode} clientId={settings.client_id_min}-{settings.client_id_max}"
        )
        self._scan_thread.start()

    def _chain_scanner_settings(self) -> ScannerSettings:
        return ScannerSettings(
            parquet_dir=Path(self.parquet_dir_edit.text().strip()),
            horizon_months=self.scan_horizon_spin.value(),
            parallel_workers=1,
            right_request_mode=str(self.scan_right_mode_combo.currentData() or "separate"),
            tws_host=self.host_edit.text().strip() or "127.0.0.1",
            tws_port=self.port_spin.value(),
            client_id_base=min(self.client_min_spin.value(), self.client_max_spin.value()),
            client_id_min=min(self.client_min_spin.value(), self.client_max_spin.value()),
            client_id_max=max(self.client_min_spin.value(), self.client_max_spin.value()),
            request_pause_sec=self.scan_request_pause_spin.value(),
            asset_pause_sec=self.scan_asset_pause_spin.value(),
        )

    def _stop_chain_scan(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.stop()
            self._append_log("[chain-scan] stop gevraagd")

    @Slot(str)
    def _chain_scan_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Chain scan mislukt", message)
        self._append_log(f"[chain-scan error] {message}")

    @Slot()
    def _chain_scan_finished(self) -> None:
        self.scan_current_btn.setEnabled(True)
        self.scan_stop_btn.setEnabled(False)
        self._scan_worker = None
        self._scan_thread = None
        self._append_log("[chain-scan] klaar")

    @Slot(object)
    def _append_chain_scan_result(self, result: AssetScanResult) -> None:
        row = self.scan_result_table.rowCount()
        self.scan_result_table.insertRow(row)
        values = [
            result.asset_rollup,
            result.client_id,
            result.status,
            result.contracts_returned,
            result.contracts_inserted,
            result.contracts_updated,
            result.contracts_rejected,
            result.option_variant or result.option_exchange,
            result.parquet_path or result.error_message,
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.scan_result_table.setItem(row, col, item)
        current = self._current_asset()
        if current and result.asset_rollup == current["asset_rollup"] and result.status == "success":
            self._append_log(f"[chain-scan] {result.asset_rollup} gereed; klik 'Laad chain' om de nieuwe chain te laden")

    @Slot(object)
    def _fetch_finished(self, df: pl.DataFrame) -> None:
        self.snapshot_df = df
        self.fetch_btn.setEnabled(True)
        self._worker = None
        self._thread = None
        self._fill_table(self.snapshot_table, df.head(1000))
        asset = self._current_asset()
        if asset and not df.is_empty():
            paths = write_snapshot(df, self.parquet_dir_edit.text().strip(), asset["asset_rollup"])
            self._append_log(f"[snapshot] geschreven: {paths.snapshot_path}")
            self._append_log(f"[snapshot] latest: {paths.latest_path}")
        self._build_theta_scan()
        self._build_gex_scan()
        self._render_charts()

    @Slot(str)
    def _fetch_failed(self, message: str) -> None:
        self.fetch_btn.setEnabled(True)
        QMessageBox.critical(self, "IV ophalen mislukt", message)
        self._append_log(f"[error] {message}")

    @Slot(int, int, str)
    def _progress(self, done: int, total: int, msg: str) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        if msg:
            self.progress.setFormat(f"{done}/{total} {msg}")

    def _load_latest_snapshot(self) -> None:
        asset = self._current_asset()
        if not asset:
            return
        df = load_latest(self.parquet_dir_edit.text().strip(), asset["asset_rollup"])
        if df.is_empty():
            QMessageBox.information(self, "Geen latest", "Geen latest IV snapshot gevonden.")
            return
        self.snapshot_df = df
        self._fill_table(self.snapshot_table, df.head(1000))
        self._append_log(f"[snapshot] latest geladen rows={df.height}")
        self._build_theta_scan()
        self._build_gex_scan()
        self._render_charts()

    def _render_charts(self) -> None:
        if self.snapshot_df.is_empty():
            return
        pdf = self.snapshot_df.to_pandas()
        right = str(self.right_combo.currentData() or "B")
        html_3d = surface.build_3d_surface(pdf, "moneyness", right)
        html_smile = surface.build_smile_lines(pdf, "moneyness", right)
        html_heatmap = surface.build_heatmap(pdf, "moneyness", right)
        self._set_html(self.surface3d_view, html_3d)
        self._set_html(self.smile_view, html_smile)
        self._set_html(self.heatmap_view, html_heatmap)
        if not self.theta_df.is_empty():
            theta_pdf = self.theta_df.to_pandas()
            html_theta = surface.build_metric_heatmap(
                theta_pdf,
                "extrinsic_yield_ann_pct",
                "Annualized Extrinsic Yield",
                "moneyness",
                right,
            )
            self._set_html(self.thetaheatmap_view, html_theta)
        self._set_html(
            self.gexstrike_view,
            surface.build_gex_by_strike(self.gex_strike_df.to_pandas(), self.gamma_flip, self._spot_value()),
        )
        self._set_html(self.gexheatmap_view, surface.build_gex_heatmap(self.gex_df.to_pandas()))

    def _build_theta_scan(self) -> None:
        spot = self._spot_value()
        raw = build_theta_scan(self.snapshot_df, fallback_spot=spot)
        self.theta_df = filter_theta_candidates(
            raw,
            max_spread_pct=self.max_spread_spin.value(),
            min_dte=max(1, self.dte_min_spin.value()),
            max_dte=self.dte_max_spin.value(),
            min_abs_delta=min(self.delta_min_spin.value(), self.delta_max_spin.value()),
            max_abs_delta=max(self.delta_min_spin.value(), self.delta_max_spin.value()),
        )
        self._append_log(f"[theta] candidates={self.theta_df.height} raw={raw.height}")
        self._populate_theta_filter_columns()
        self._refresh_theta_table()

    def _build_gex_scan(self) -> None:
        spot = self._spot_value()
        self.gex_df = build_gex_scan(
            self.snapshot_df,
            fallback_spot=spot,
            prefer_fallback_spot=self.spot_source.startswith("ibkr"),
        )
        if self.gex_df.is_empty():
            self.gex_strike_df = pl.DataFrame()
            self.gamma_flip = None
            self._fill_table(self.gex_table, self.gex_df)
            self._fill_table(self.gex_strike_table, self.gex_strike_df)
            self._append_log("[gex] geen bruikbare gamma/open-interest data")
            return
        self.gex_strike_df = aggregate_gex_by_strike(self.gex_df)
        self.gamma_flip = estimate_gamma_flip(self.gex_strike_df, reference_spot=spot)
        self._fill_table(self.gex_table, self.gex_df.head(1000))
        self._fill_table(self.gex_strike_table, self.gex_strike_df.head(1000))
        flip_text = f"{self.gamma_flip:.3f}" if self.gamma_flip is not None else "n.v.t."
        self._append_log(
            f"[gex] contracts={self.gex_df.height} strikes={self.gex_strike_df.height} "
            f"gamma_flip={flip_text} spot={spot} spot_source={self.spot_source or 'manual'}"
        )

    def _populate_theta_filter_columns(self) -> None:
        current = self.theta_filter_col.currentData()
        self.theta_filter_col.blockSignals(True)
        self.theta_filter_col.clear()
        self.theta_filter_col.addItem("Alle kolommen", "")
        preferred = [
            "theta_score",
            "right",
            "expiry",
            "dte",
            "strike",
            "moneyness",
            "delta",
            "extrinsic_value",
            "extrinsic_yield_ann_pct",
            "seller_theta_per_day",
            "theta_yield_ann_pct",
            "spread_pct",
            "trading_class",
            "local_symbol",
        ]
        columns = [col for col in preferred if col in self.theta_df.columns]
        columns += [col for col in self.theta_df.columns if col not in columns]
        for col in columns:
            self.theta_filter_col.addItem(col, col)
        idx = self.theta_filter_col.findData(current)
        self.theta_filter_col.setCurrentIndex(idx if idx >= 0 else 0)
        self.theta_filter_col.blockSignals(False)

    def _refresh_theta_table(self) -> None:
        df = self.theta_df
        if df.is_empty():
            self.theta_display_df = df
            self._fill_table(self.theta_table, df)
            return
        col = str(self.theta_filter_col.currentData() or "")
        text = self.theta_filter_text.text().strip()
        min_val = self._parse_optional_float(self.theta_filter_min.text())
        max_val = self._parse_optional_float(self.theta_filter_max.text())
        if text:
            pattern = text.lower()
            if col:
                df = df.filter(pl.col(col).cast(pl.Utf8).str.to_lowercase().str.contains(pattern, literal=True))
            else:
                expr = None
                for name in df.columns:
                    part = pl.col(name).cast(pl.Utf8).str.to_lowercase().str.contains(pattern, literal=True)
                    expr = part if expr is None else (expr | part)
                if expr is not None:
                    df = df.filter(expr)
        if col and min_val is not None:
            df = df.filter(pl.col(col).cast(pl.Float64, strict=False) >= min_val)
        if col and max_val is not None:
            df = df.filter(pl.col(col).cast(pl.Float64, strict=False) <= max_val)
        self.theta_display_df = df
        self._fill_table(self.theta_table, df.head(1000))
        self._append_log(f"[theta] filter rows={df.height}")

    def _clear_theta_filter(self) -> None:
        self.theta_filter_col.setCurrentIndex(0)
        self.theta_filter_text.clear()
        self.theta_filter_min.clear()
        self.theta_filter_max.clear()
        self._refresh_theta_table()

    def _parse_optional_float(self, text: str) -> float | None:
        clean = str(text or "").strip().replace(",", ".")
        if not clean:
            return None
        try:
            return float(clean)
        except Exception:
            return None

    def _set_html(self, widget, html: str) -> None:
        if hasattr(widget, "setHtml"):
            widget.setHtml(html)
        else:
            widget.setPlainText(html)

    def _fill_table(self, table: QTableWidget, df: pl.DataFrame) -> None:
        table.setUpdatesEnabled(False)
        table.setSortingEnabled(False)
        try:
            cols = df.columns
            table.clearContents()
            table.setColumnCount(len(cols))
            table.setHorizontalHeaderLabels(cols)
            table.setRowCount(df.height)
            for r_idx, row in enumerate(df.to_dicts()):
                for c_idx, col in enumerate(cols):
                    value = row.get(col, "")
                    item = SortableTableWidgetItem(self._display_value(col, value))
                    sort_value = self._sort_value(value)
                    if sort_value is not None:
                        item.setData(Qt.UserRole, sort_value)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    table.setItem(r_idx, c_idx, item)
            header = table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.Interactive)
            header.setDefaultSectionSize(115)
            header.setStretchLastSection(False)
        finally:
            table.setSortingEnabled(True)
            table.setUpdatesEnabled(True)

    def _sort_value(self, value):
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return str(value)

    def _display_value(self, col: str, value) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.3f}"
        try:
            numeric = float(value)
        except Exception:
            return str(value)
        numeric_cols = {
            "strike",
            "moneyness",
            "delta",
            "abs_delta",
            "iv",
            "bid",
            "ask",
            "last",
            "mid",
            "close",
            "spread",
            "spread_pct",
            "option_price_used",
            "intrinsic_value",
            "extrinsic_value",
            "extrinsic_pct_strike",
            "extrinsic_yield_ann_pct",
            "seller_theta_per_day",
            "theta",
            "theta_yield_ann_pct",
            "theta_score",
            "vega",
            "gamma",
            "model_opt_price",
            "model_und_price",
            "model_iv",
            "model_delta",
            "model_gamma",
            "model_vega",
            "model_theta",
            "model_moneyness",
            "multiplier",
            "spot_used",
            "gamma_used",
            "open_interest_used",
            "call_open_interest",
            "put_open_interest",
            "multiplier_used",
            "gex_1pct",
            "dealer_gex_1pct",
            "abs_dealer_gex_1pct",
            "net_dealer_gex_1pct",
            "call_gex_1pct",
            "put_gex_1pct",
            "gross_gex_1pct",
            "open_interest",
            "cumulative_dealer_gex_1pct",
            "abs_net_dealer_gex_1pct",
        }
        if col in numeric_cols:
            return f"{numeric:.3f}"
        return str(value)

    def _choose_parquet_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Kies parquet map", self.parquet_dir_edit.text())
        if path:
            self.parquet_dir_edit.setText(path)

    def _current_asset(self) -> dict | None:
        return self.asset_combo.currentData()

    def _refresh_spot_from_ibkr(self) -> None:
        asset = self._current_asset()
        if not asset:
            return
        current = self._spot_value()
        self._log_cli(f"[spot] refresh start asset={asset.get('asset_rollup')} current={current}")
        quote = resolve_spot(
            asset=asset,
            stock_db_path=self.stock_db_path,
            host=self.host_edit.text().strip() or "127.0.0.1",
            port=self.port_spin.value(),
            client_id_min=min(self.client_min_spin.value(), self.client_max_spin.value()),
            client_id_max=max(self.client_min_spin.value(), self.client_max_spin.value()),
            market_data_type=int(self.market_type_combo.currentData() or 1),
            log=self._log_cli,
            timeout_sec=4.0,
        )
        if quote.price is None:
            self._log_cli(f"[spot] refresh failed source={quote.source} detail={quote.detail}")
            return
        self.spot_edit.setText(f"{quote.price:.4f}")
        self.spot_source = quote.source
        self.spot_label.setText(f"spot uit {quote.source}: {quote.detail}")
        self._log_cli(f"[spot] refresh ok price={quote.price:.4f} source={quote.source} detail={quote.detail}")

    def _spot_value(self) -> float | None:
        try:
            return float(self.spot_edit.text().strip().replace(",", "."))
        except Exception:
            return None

    @Slot(str)
    def _append_log(self, msg: str) -> None:
        self.log_edit.append(str(msg))

    def _log_cli(self, msg: str) -> None:
        print(str(msg), flush=True)

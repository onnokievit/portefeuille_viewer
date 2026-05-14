from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from portefeuille_viewer.config import get_settings

from .asset_source import load_scan_assets
from .models import AssetScanResult, OptionScanAsset, ScannerSettings
from .orchestrator import OptionChainRetrievalJob
from .parquet_viewer import load_preview

ASSET_KEY_ROLE = Qt.UserRole
SORT_VALUE_ROLE = Qt.UserRole + 1


class SortableTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other) -> bool:
        if other is None:
            return super().__lt__(other)
        if self.column() == 0 and other.column() == 0:
            left = 1 if self.checkState() == Qt.Checked else 0
            right = 1 if other.checkState() == Qt.Checked else 0
            return left < right
        left = self.data(SORT_VALUE_ROLE)
        right = other.data(SORT_VALUE_ROLE)
        if left is not None and right is not None:
            return str(left).casefold() < str(right).casefold()
        return self.text().casefold() < other.text().casefold()


class ScanWorker(QObject):
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


class OptionChainRetrieverWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Optie Scanner")
        self.resize(1280, 820)
        self.settings_manager = get_settings()
        self.stock_db_path = self.settings_manager.get_stockdata_db_path()
        self.assets: list[OptionScanAsset] = []
        self._worker_thread: QThread | None = None
        self._worker: ScanWorker | None = None

        self._build_ui()
        self._load_settings()
        self._load_assets()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        controls = QGroupBox("Scanner instellingen")
        controls_layout = QVBoxLayout(controls)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Stock DB:"))
        self.stock_db_edit = QLineEdit()
        self.stock_db_edit.setReadOnly(True)
        row1.addWidget(self.stock_db_edit, 2)
        row1.addWidget(QLabel("Parquet map:"))
        self.parquet_dir_edit = QLineEdit()
        row1.addWidget(self.parquet_dir_edit, 2)
        browse = QPushButton("Kies...")
        browse.clicked.connect(self._choose_parquet_dir)
        row1.addWidget(browse)
        controls_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.host_edit = QLineEdit()
        self.host_edit.setFixedWidth(130)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.client_min_spin = QSpinBox()
        self.client_min_spin.setRange(1000, 10000)
        self.client_max_spin = QSpinBox()
        self.client_max_spin.setRange(1000, 10000)
        self.horizon_spin = QSpinBox()
        self.horizon_spin.setRange(1, 120)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 16)
        self.max_assets_spin = QSpinBox()
        self.max_assets_spin.setRange(1, 10000)
        self.right_mode_combo = QComboBox()
        self.right_mode_combo.addItem("C/P gescheiden", "separate")
        self.right_mode_combo.addItem("C+P in 1 request", "combined")
        for label, widget in [
            ("Host", self.host_edit),
            ("Poort", self.port_spin),
            ("Client min", self.client_min_spin),
            ("Client max", self.client_max_spin),
            ("Maanden", self.horizon_spin),
            ("Workers", self.workers_spin),
            ("Max assets/start", self.max_assets_spin),
            ("Rights", self.right_mode_combo),
        ]:
            row2.addWidget(QLabel(label))
            row2.addWidget(widget)
        row2.addStretch(1)
        save_btn = QPushButton("Sla instellingen op")
        save_btn.clicked.connect(self._save_settings)
        row2.addWidget(save_btn)
        reload_btn = QPushButton("Herlaad assets")
        reload_btn.clicked.connect(self._load_assets)
        row2.addWidget(reload_btn)
        self.start_btn = QPushButton("Start scan")
        self.start_btn.clicked.connect(self._start_scan)
        row2.addWidget(self.start_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_scan)
        row2.addWidget(self.stop_btn)
        controls_layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.request_pause_spin = QDoubleSpinBox()
        self.request_pause_spin.setRange(0.0, 60.0)
        self.request_pause_spin.setDecimals(2)
        self.request_pause_spin.setSingleStep(0.25)
        self.request_pause_spin.setSuffix(" s")
        self.asset_pause_spin = QDoubleSpinBox()
        self.asset_pause_spin.setRange(0.0, 300.0)
        self.asset_pause_spin.setDecimals(2)
        self.asset_pause_spin.setSingleStep(0.5)
        self.asset_pause_spin.setSuffix(" s")
        row3.addWidget(QLabel("Pauze tussen requests"))
        row3.addWidget(self.request_pause_spin)
        row3.addWidget(QLabel("Pauze tussen assets"))
        row3.addWidget(self.asset_pause_spin)
        row3.addStretch(1)
        controls_layout.addLayout(row3)
        root.addWidget(controls)

        self.tabs = QTabWidget()
        self.scan_tab = QWidget()
        scan_layout = QVBoxLayout(self.scan_tab)
        splitter = QSplitter(Qt.Vertical)
        top = QWidget()
        top_layout = QHBoxLayout(top)
        left_box = QGroupBox("Assets")
        left_layout = QVBoxLayout(left_box)
        asset_buttons = QHBoxLayout()
        select_all = QPushButton("Alles")
        select_all.clicked.connect(lambda: self._set_asset_checks(True))
        select_none = QPushButton("Geen")
        select_none.clicked.connect(lambda: self._set_asset_checks(False))
        asset_buttons.addWidget(select_all)
        asset_buttons.addWidget(select_none)
        asset_buttons.addStretch(1)
        left_layout.addLayout(asset_buttons)
        self.asset_table = QTableWidget(0, 5)
        self.asset_table.setHorizontalHeaderLabels(["Scan", "asset", "symbol", "ccy", "type/exchange"])
        self.asset_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.asset_table.horizontalHeader().setStretchLastSection(True)
        self.asset_table.setSortingEnabled(True)
        left_layout.addWidget(self.asset_table)
        top_layout.addWidget(left_box, 2)

        result_box = QGroupBox("Resultaten")
        result_layout = QVBoxLayout(result_box)
        self.result_table = QTableWidget(0, 9)
        self.result_table.setHorizontalHeaderLabels(
            ["asset", "clientId", "status", "returned", "inserted", "updated", "rejected", "exchange", "parquet/error"]
        )
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        result_layout.addWidget(self.result_table)
        top_layout.addWidget(result_box, 3)
        splitter.addWidget(top)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        splitter.addWidget(self.log_edit)
        splitter.setSizes([540, 220])
        scan_layout.addWidget(splitter)
        self.tabs.addTab(self.scan_tab, "Scanner")

        self.parquet_tab = QWidget()
        parquet_layout = QVBoxLayout(self.parquet_tab)
        p_row = QHBoxLayout()
        self.parquet_file_edit = QLineEdit()
        p_row.addWidget(self.parquet_file_edit)
        p_browse = QPushButton("Open parquet")
        p_browse.clicked.connect(self._choose_parquet_file)
        p_row.addWidget(p_browse)
        p_load = QPushButton("Laad preview")
        p_load.clicked.connect(self._load_parquet_preview)
        p_row.addWidget(p_load)
        parquet_layout.addLayout(p_row)
        self.parquet_summary = QLabel("")
        parquet_layout.addWidget(self.parquet_summary)
        self.parquet_table = QTableWidget()
        parquet_layout.addWidget(self.parquet_table)
        self.tabs.addTab(self.parquet_tab, "Parquet viewer")

        root.addWidget(self.tabs)
        self.setCentralWidget(central)

    def _load_settings(self) -> None:
        cfg = self.settings_manager.get_option_chain_scanner_settings()
        self.stock_db_edit.setText(self.stock_db_path)
        self.parquet_dir_edit.setText(cfg["parquet_dir"])
        self.host_edit.setText(cfg["tws_host"])
        self.port_spin.setValue(int(cfg["tws_port"]))
        self.client_min_spin.setValue(int(cfg["client_id_min"]))
        self.client_max_spin.setValue(int(cfg["client_id_max"]))
        self.horizon_spin.setValue(int(cfg["horizon_months"]))
        self.workers_spin.setValue(int(cfg["parallel_workers"]))
        self.max_assets_spin.setValue(int(cfg["max_assets_per_start"]))
        self.request_pause_spin.setValue(float(cfg["request_pause_sec"]))
        self.asset_pause_spin.setValue(float(cfg["asset_pause_sec"]))
        mode_idx = self.right_mode_combo.findData(str(cfg.get("right_request_mode") or "separate"))
        self.right_mode_combo.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)

    def _save_settings(self) -> None:
        self.settings_manager.set_option_chain_scanner_settings(
            parquet_dir=self.parquet_dir_edit.text().strip(),
            horizon_months=self.horizon_spin.value(),
            parallel_workers=self.workers_spin.value(),
            max_assets_per_start=self.max_assets_spin.value(),
            right_request_mode=str(self.right_mode_combo.currentData() or "separate"),
            tws_host=self.host_edit.text().strip() or "127.0.0.1",
            tws_port=self.port_spin.value(),
            client_id_base=min(self.client_min_spin.value(), self.client_max_spin.value()),
            client_id_min=min(self.client_min_spin.value(), self.client_max_spin.value()),
            client_id_max=max(self.client_min_spin.value(), self.client_max_spin.value()),
            request_pause_sec=self.request_pause_spin.value(),
            asset_pause_sec=self.asset_pause_spin.value(),
        )
        self._append_log("[settings] opgeslagen")

    def _load_assets(self) -> None:
        try:
            self.assets = load_scan_assets(self.stock_db_path)
        except Exception as exc:
            QMessageBox.critical(self, "Assets laden mislukt", str(exc))
            self.assets = []
        self.asset_table.setSortingEnabled(False)
        self.asset_table.clearContents()
        self.asset_table.setRowCount(len(self.assets))
        for row, asset in enumerate(self.assets):
            check = SortableTableWidgetItem("")
            check.setFlags(check.flags() | Qt.ItemIsUserCheckable)
            check.setCheckState(Qt.Checked)
            check.setData(ASSET_KEY_ROLE, asset.scan_key())
            self.asset_table.setItem(row, 0, check)
            values = [
                asset.asset_rollup,
                asset.ib_symbol,
                asset.ib_currency,
                f"{asset.ib_asset_type} / {asset.option_variant}",
            ]
            for col, value in enumerate(values, start=1):
                item = SortableTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setData(ASSET_KEY_ROLE, asset.scan_key())
                item.setData(SORT_VALUE_ROLE, str(value))
                self.asset_table.setItem(row, col, item)
        self.asset_table.setSortingEnabled(True)
        self._append_log(f"[assets] geladen: {len(self.assets)}")

    def _selected_assets(self) -> list[OptionScanAsset]:
        by_asset = {asset.scan_key(): asset for asset in self.assets}
        out = []
        for row in range(self.asset_table.rowCount()):
            item = self.asset_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                asset = by_asset.get(str(item.data(ASSET_KEY_ROLE) or ""))
                if asset is not None:
                    out.append(asset)
        return out

    def _set_asset_checks(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.asset_table.rowCount()):
            item = self.asset_table.item(row, 0)
            if item:
                item.setCheckState(state)

    def _scanner_settings(self) -> ScannerSettings:
        return ScannerSettings(
            parquet_dir=Path(self.parquet_dir_edit.text().strip()),
            horizon_months=self.horizon_spin.value(),
            parallel_workers=self.workers_spin.value(),
            right_request_mode=str(self.right_mode_combo.currentData() or "separate"),
            tws_host=self.host_edit.text().strip() or "127.0.0.1",
            tws_port=self.port_spin.value(),
            client_id_base=min(self.client_min_spin.value(), self.client_max_spin.value()),
            client_id_min=min(self.client_min_spin.value(), self.client_max_spin.value()),
            client_id_max=max(self.client_min_spin.value(), self.client_max_spin.value()),
            request_pause_sec=self.request_pause_spin.value(),
            asset_pause_sec=self.asset_pause_spin.value(),
        )

    def _start_scan(self) -> None:
        assets = self._selected_assets()
        if not assets:
            QMessageBox.information(self, "Geen assets", "Selecteer minimaal 1 asset.")
            return
        max_assets = self.max_assets_spin.value()
        if len(assets) > max_assets:
            self._append_log(f"[batch] {len(assets)} aangevinkt; deze start verwerkt de eerste {max_assets}")
            assets = assets[:max_assets]
        self._save_settings()
        self.result_table.setRowCount(0)
        settings = self._scanner_settings()
        self._worker_thread = QThread(self)
        self._worker = ScanWorker(settings, self.stock_db_path, assets)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append_log)
        self._worker.result.connect(self._append_result)
        self._worker.failed.connect(lambda msg: QMessageBox.critical(self, "Scan fout", msg))
        self._worker.finished.connect(self._scan_finished)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._append_log(
            f"[run] start assets={len(assets)} workers={settings.parallel_workers} "
            f"clientId=random {settings.client_id_min}-{settings.client_id_max} "
            f"pause_req={settings.request_pause_sec:.2f}s pause_asset={settings.asset_pause_sec:.2f}s"
        )
        self._worker_thread.start()

    def _stop_scan(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._append_log("[run] stop gevraagd")

    @Slot()
    def _scan_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._append_log("[run] worker klaar")
        self._worker = None
        self._worker_thread = None

    @Slot(str)
    def _append_log(self, msg: str) -> None:
        self.log_edit.append(str(msg))

    @Slot(object)
    def _append_result(self, result: AssetScanResult) -> None:
        row = self.result_table.rowCount()
        self.result_table.insertRow(row)
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
            self.result_table.setItem(row, col, item)
        if result.status == "success":
            asset_row = self._asset_current_row(f"{result.asset_rollup}|{result.option_variant}")
            if asset_row is not None:
                check = self.asset_table.item(asset_row, 0)
                if check is not None:
                    check.setCheckState(Qt.Unchecked)
            self._append_log(f"[batch] {result.asset_rollup} succesvol; uitgevinkt")

    def _asset_current_row(self, asset_key: str) -> int | None:
        for row in range(self.asset_table.rowCount()):
            item = self.asset_table.item(row, 0)
            if item and item.data(ASSET_KEY_ROLE) == asset_key:
                return row
        return None

    def _choose_parquet_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Kies parquet map", self.parquet_dir_edit.text())
        if path:
            self.parquet_dir_edit.setText(path)

    def _choose_parquet_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open parquet", self.parquet_dir_edit.text(), "Parquet (*.parquet)")
        if path:
            self.parquet_file_edit.setText(path)
            self._load_parquet_preview()

    def _load_parquet_preview(self) -> None:
        path = self.parquet_file_edit.text().strip()
        if not path:
            return
        try:
            df, summary = load_preview(path)
        except Exception as exc:
            QMessageBox.critical(self, "Parquet laden mislukt", str(exc))
            return
        self.parquet_summary.setText(" | ".join(f"{k}={v}" for k, v in summary.items()))
        self.parquet_table.setColumnCount(len(df.columns))
        self.parquet_table.setHorizontalHeaderLabels(df.columns)
        self.parquet_table.setRowCount(df.height)
        rows = df.to_dicts()
        for r_idx, row in enumerate(rows):
            for c_idx, col in enumerate(df.columns):
                item = QTableWidgetItem(str(row.get(col, "")))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.parquet_table.setItem(r_idx, c_idx, item)
        self.parquet_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = OptionChainRetrieverWindow()
    window.show()
    return app.exec()

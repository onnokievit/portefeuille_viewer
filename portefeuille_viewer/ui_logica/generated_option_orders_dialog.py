from __future__ import annotations

import polars as pl

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals
from portefeuille_viewer.data.test_order_repository import (
    BUCKET_1,
    CHANGE_KIND_COL,
    DEFAULT_TEST_ORDER_SCENARIO_NAME,
    PARENT_CHANGE_UID_COL,
    SCENARIO_ORDER_UID_COL,
    SOURCE_BUCKET_COL,
    SOURCE_TYPE_COL,
    create_test_order_scenario_in_cache,
    delete_test_order_scenario_in_cache,
    ensure_default_test_order_scenario,
    flush_dirty_test_order_scenarios_to_db,
    get_cached_test_order_scenario_content_map,
    get_cached_test_order_scenarios,
    get_cached_orders,
    get_test_orders,
    flush_dirty_test_orders_to_db,
    load_test_order_scenarios_cache_from_db,
    rename_test_order_scenario_in_cache,
    save_scenario_content_for_visible_rows,
    set_cached_orders_for_asset,
)
from portefeuille_viewer.services.scenario_aandelen_overlay import (
    refresh_aandelen_scenario_overlay_snapshot,
)
from portefeuille_viewer.services.scenario_generated_option_sync import (
    BUCKET_2,
    BUCKET_3,
    CHANGE_KIND_MARKET_CLOSE,
    CHANGE_KIND_OPTION_EOM,
    SOURCE_TYPE_OPTION_EOM_CHILD,
    sync_generated_option_orders,
)
from portefeuille_viewer.services.scenario_order_resolver import (
    refresh_active_scenario_orders_snapshot,
)
from portefeuille_viewer.services.scenario_portfolio_value_overlay import (
    refresh_portfolio_value_scenario_overlay_snapshot,
)
from portefeuille_viewer.services.scenario_sector_overlay import (
    refresh_sector_scenario_overlay_snapshots,
)


class CheckableSortItem(QTableWidgetItem):
    def __lt__(self, other):  # type: ignore[override]
        if isinstance(other, QTableWidgetItem):
            return int(self.checkState() == Qt.Checked) < int(other.checkState() == Qt.Checked)
        return super().__lt__(other)


class MultiSelectFilterDialog(QDialog):
    def __init__(self, title: str, placeholder: str, options: list[str], selected: set[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(340, 420)
        self._options = list(options)
        self._draft = set(selected)

        layout = QVBoxLayout(self)
        self.searchEdit = QLineEdit(self)
        self.searchEdit.setPlaceholderText(placeholder)
        layout.addWidget(self.searchEdit)

        self.checkAll = QCheckBox("(Alles selecteren)", self)
        layout.addWidget(self.checkAll)

        self.listWidget = QListWidget(self)
        layout.addWidget(self.listWidget, 1)

        buttons = QHBoxLayout()
        self.btnOk = QPushButton("OK", self)
        self.btnClear = QPushButton("Wissen", self)
        self.btnCancel = QPushButton("Cancel", self)
        buttons.addWidget(self.btnOk)
        buttons.addWidget(self.btnClear)
        buttons.addWidget(self.btnCancel)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.searchEdit.textChanged.connect(self._render_list)
        self.checkAll.toggled.connect(self._toggle_all_visible)
        self.btnOk.clicked.connect(self.accept)
        self.btnClear.clicked.connect(self._clear_all)
        self.btnCancel.clicked.connect(self.reject)
        self.listWidget.itemChanged.connect(self._on_item_changed)

        self._render_list()

    def selected_values(self) -> set[str]:
        return set(self._draft)

    def _visible_options(self) -> list[str]:
        q = (self.searchEdit.text() or "").strip().lower()
        if not q:
            return list(self._options)
        return [v for v in self._options if q in v.lower()]

    def _sync_all_checkbox(self) -> None:
        visible = self._visible_options()
        if not visible:
            checked = False
            indeterminate = False
        else:
            selected_count = sum(1 for v in visible if v in self._draft)
            checked = selected_count == len(visible)
            indeterminate = 0 < selected_count < len(visible)
        self.checkAll.blockSignals(True)
        try:
            self.checkAll.setChecked(checked)
            self.checkAll.setTristate(False)
            self.checkAll.setCheckState(Qt.PartiallyChecked if indeterminate else (Qt.Checked if checked else Qt.Unchecked))
        finally:
            self.checkAll.blockSignals(False)

    def _render_list(self) -> None:
        visible = self._visible_options()
        self.listWidget.blockSignals(True)
        try:
            self.listWidget.clear()
            for value in visible:
                item = QListWidgetItem(value, self.listWidget)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Checked if value in self._draft else Qt.Unchecked)
        finally:
            self.listWidget.blockSignals(False)
        self._sync_all_checkbox()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        value = item.text()
        if item.checkState() == Qt.Checked:
            self._draft.add(value)
        else:
            self._draft.discard(value)
        self._sync_all_checkbox()

    def _toggle_all_visible(self, checked: bool) -> None:
        visible = self._visible_options()
        if checked:
            self._draft.update(visible)
        else:
            for value in visible:
                self._draft.discard(value)
        self._render_list()

    def _clear_all(self) -> None:
        self._draft.clear()
        self._render_list()


class ScenarioManagerDialog(QDialog):
    def __init__(self, scenarios_df: pl.DataFrame, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Scenario beheer")
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(self)
        self.table.setColumnCount(1)
        self.table.setHorizontalHeaderLabels(["Scenario naam"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.table)

        button_row = QHBoxLayout()
        self.button_add = QPushButton("Add", self)
        self.button_delete = QPushButton("Delete", self)
        self.button_save = QPushButton("Opslaan", self)
        self.button_cancel = QPushButton("Sluiten", self)
        button_row.addWidget(self.button_add)
        button_row.addWidget(self.button_delete)
        button_row.addStretch(1)
        button_row.addWidget(self.button_save)
        button_row.addWidget(self.button_cancel)
        layout.addLayout(button_row)

        self.button_add.clicked.connect(self.add_empty_row)
        self.button_delete.clicked.connect(self.delete_selected_row)
        self.button_save.clicked.connect(self.accept)
        self.button_cancel.clicked.connect(self.reject)

        rows = sorted(
            scenarios_df.to_dicts(),
            key=lambda row: str(row.get("scenario_name") or "").strip().lower(),
        ) if scenarios_df is not None and not scenarios_df.is_empty() else []
        self.table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            item = QTableWidgetItem(str(row.get("scenario_name") or ""))
            item.setData(Qt.UserRole, int(row.get("scenario_id")))
            if str(row.get("scenario_name") or "").strip() == DEFAULT_TEST_ORDER_SCENARIO_NAME:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_idx, 0, item)

    def add_empty_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem("")
        item.setData(Qt.UserRole, None)
        self.table.setItem(row, 0, item)
        self.table.setCurrentCell(row, 0)
        self.table.editItem(item)

    def delete_selected_row(self):
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is not None and str(item.text() or "").strip() == DEFAULT_TEST_ORDER_SCENARIO_NAME:
            return
        self.table.removeRow(row)
        remaining = self.table.rowCount()
        if remaining <= 0:
            return
        next_row = min(row, remaining - 1)
        self.table.setCurrentCell(next_row, 0)

    def get_rows(self) -> list[dict]:
        rows = []
        for row_idx in range(self.table.rowCount()):
            item = self.table.item(row_idx, 0)
            if item is None:
                continue
            name = str(item.text() or "").strip()
            if not name:
                continue
            rows.append({
                "scenario_id": item.data(Qt.UserRole),
                "scenario_name": name,
            })
        return rows


class GeneratedOptionOrdersDialog(QDialog):
    _BUCKET2_COLS = [
        ("Incl", "include"),
        ("Asset", "asset_rollup"),
        ("Broker", "broker"),
        ("ITM/OTM", "itm_otm"),
        ("Type", "asset_type"),
        ("Transactie", "transactie_type"),
        ("Afhandeling", CHANGE_KIND_COL),
        ("Aantal", "transactie_aantal"),
        ("Prijs", "transactie_prijs"),
        ("c/p", "optie_call_put"),
        ("Exp datum", "optie_exp_date"),
        ("Strike", "optie_strike"),
    ]
    _BUCKET3_COLS = [
        ("Incl", "include"),
        ("Asset", "asset_rollup"),
        ("Broker", "broker"),
        ("ITM/OTM", "itm_otm"),
        ("Type", "asset_type"),
        ("Transactie", "transactie_type"),
        ("Aantal", "transactie_aantal"),
        ("Prijs", "transactie_prijs"),
        ("c/p", "optie_call_put"),
        ("Exp datum", "optie_exp_date"),
        ("Strike", "optie_strike"),
    ]

    @staticmethod
    def _scenario_content_safe_df(rows: list[dict]) -> pl.DataFrame:
        safe_rows: list[dict] = []
        for row in rows:
            out = dict(row)
            exp = out.get("optie_exp_date")
            if exp is not None and hasattr(exp, "strftime"):
                out["optie_exp_date"] = exp.strftime("%d-%m-%Y")
            elif exp is not None:
                out["optie_exp_date"] = str(exp)
            else:
                out["optie_exp_date"] = None
            created = out.get("create_date")
            if created is not None and hasattr(created, "strftime"):
                out["create_date"] = created.strftime("%d-%m-%Y %H:%M:%S")
            elif created is not None:
                out["create_date"] = str(created)
            else:
                out["create_date"] = None
            safe_rows.append(out)
        return pl.from_dicts(safe_rows, strict=False) if safe_rows else pl.DataFrame()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Optie Scenario")
        self.setWindowFlag(Qt.Window, True)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.setSizeGripEnabled(True)
        self._restore_geometry()
        self._scenario_id: int | None = None
        self._bucket1_df = pl.DataFrame()
        self._bucket2_df = pl.DataFrame()
        self._bucket3_df = pl.DataFrame()
        self._bucket2_filter_items: list[dict] = []
        self._broker_filter_options: list[str] = []
        self._broker_filter_selected: set[str] = set()
        self._asset_filter_options: list[str] = []
        self._asset_filter_selected: set[str] = set()
        self._itm_filter_options: list[str] = []
        self._itm_filter_selected: set[str] = set()
        self._exp_filter_options: list[str] = []
        self._exp_filter_selected: set[str] = set()
        self._suppress_bucket2_item_changed = False
        self._bucket3_collapsed = True

        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.btnSync = QPushButton("Sync", self)
        controls.addWidget(self.btnSync)
        self.btnManageScenarios = QPushButton("Scenario beheer", self)
        controls.addWidget(self.btnManageScenarios)
        controls.addWidget(QLabel("Scenario"))
        self.comboScenario = QComboBox(self)
        controls.addWidget(self.comboScenario)
        self.btnClose = QPushButton("Close", self)
        controls.addWidget(self.btnClose)
        controls.addStretch(1)
        layout.addLayout(controls)

        filters = QHBoxLayout()
        self.searchAll = QLineEdit(self)
        self.searchAll.setPlaceholderText("Zoek alle kolommen...")
        filters.addWidget(self.searchAll)
        self.btnBrokerFilter = QPushButton("Broker", self)
        filters.addWidget(self.btnBrokerFilter)
        self.btnAssetFilter = QPushButton("Asset", self)
        filters.addWidget(self.btnAssetFilter)
        self.btnItmFilter = QPushButton("ITM/OTM", self)
        filters.addWidget(self.btnItmFilter)
        self.filterCp = QComboBox(self)
        filters.addWidget(self.filterCp)
        self.btnExpFilter = QPushButton("Expiratie", self)
        filters.addWidget(self.btnExpFilter)
        self.btnFilteredOn = QPushButton("Selection on", self)
        filters.addWidget(self.btnFilteredOn)
        self.btnFilteredOff = QPushButton("Selection off", self)
        filters.addWidget(self.btnFilteredOff)
        self.btnSave = QPushButton("Save", self)
        filters.addWidget(self.btnSave)
        self.checkEnableTestOrders = QCheckBox("Test Orders", self)
        self.checkEnableTestOrders.setChecked(bool(getattr(SNAPSHOT_STORE, "runtime_test_orders_enabled", False)))
        filters.addWidget(self.checkEnableTestOrders)
        self.btnClearFilters = QPushButton("Clear filters", self)
        filters.addWidget(self.btnClearFilters)
        filters.addStretch(1)
        layout.addLayout(filters)

        self.labelStatus = QLabel("", self)
        layout.addWidget(self.labelStatus)

        layout.addWidget(QLabel("Bucket 1 - Manual Test Orders", self))
        self.tableBucket1 = self._create_table(self)
        layout.addWidget(self.tableBucket1, 1)

        bucket2_header = QHBoxLayout()
        bucket2_header.addWidget(QLabel("Bucket 2 - Open Position", self))
        bucket2_header.addStretch(1)
        self.btnBucket2AllEom = QPushButton("Visible -> EOM", self)
        bucket2_header.addWidget(self.btnBucket2AllEom)
        self.btnBucket2AllMarketClose = QPushButton("Visible -> Market Close", self)
        bucket2_header.addWidget(self.btnBucket2AllMarketClose)
        layout.addLayout(bucket2_header)
        self.tableBucket2 = self._create_table(self)
        layout.addWidget(self.tableBucket2, 1)

        bucket3_header = QHBoxLayout()
        self.btnToggleBucket3 = QToolButton(self)
        self.btnToggleBucket3.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btnToggleBucket3.setArrowType(Qt.RightArrow)
        self.btnToggleBucket3.setText("Bucket 3 - Derived Option EOM")
        bucket3_header.addWidget(self.btnToggleBucket3)
        bucket3_header.addStretch(1)
        layout.addLayout(bucket3_header)
        self.tableBucket3 = self._create_table(self)
        layout.addWidget(self.tableBucket3, 1)

        self.comboScenario.currentIndexChanged.connect(self._on_scenario_changed)
        self.btnManageScenarios.clicked.connect(self._open_scenario_manager)
        self.checkEnableTestOrders.toggled.connect(self._on_toggle_enable_test_orders)
        self.btnSync.clicked.connect(self._on_sync_clicked)
        self.btnFilteredOn.clicked.connect(lambda: self._set_filtered_bucket2_checks(True))
        self.btnFilteredOff.clicked.connect(lambda: self._set_filtered_bucket2_checks(False))
        self.btnClearFilters.clicked.connect(self._clear_filters)
        self.btnSave.clicked.connect(self._on_save_clicked)
        self.btnClose.clicked.connect(self.reject)
        self.searchAll.textChanged.connect(self._apply_bucket2_filters)
        self.btnBrokerFilter.clicked.connect(self._open_broker_filter_dialog)
        self.btnAssetFilter.clicked.connect(self._open_asset_filter_dialog)
        self.btnItmFilter.clicked.connect(self._open_itm_filter_dialog)
        self.filterCp.currentIndexChanged.connect(self._apply_bucket2_filters)
        self.btnExpFilter.clicked.connect(self._open_expiry_filter_dialog)
        self.tableBucket2.itemChanged.connect(self._on_bucket2_item_changed)
        self.btnBucket2AllEom.clicked.connect(lambda: self._set_bucket2_change_kind_for_visible(CHANGE_KIND_OPTION_EOM))
        self.btnBucket2AllMarketClose.clicked.connect(
            lambda: self._set_bucket2_change_kind_for_visible(CHANGE_KIND_MARKET_CLOSE)
        )
        self.btnToggleBucket3.clicked.connect(self._toggle_bucket3_collapsed)
        signals.testOrderScenariosChanged.connect(self._on_test_order_scenarios_changed)
        signals.testOrdersEnabledChanged.connect(self._on_test_orders_enabled_changed)

        self._reload_scenarios()
        self._reload_tables()
        self._apply_bucket3_collapsed_state()

    @staticmethod
    def _create_table(parent: QWidget) -> QTableWidget:
        table = QTableWidget(parent)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSortingEnabled(True)
        return table

    @staticmethod
    def _fill_filter_combo(combo: QComboBox, values: list[str]) -> None:
        current = combo.currentText()
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("C/P")
            for value in values:
                combo.addItem(value)
            idx = combo.findText(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            combo.blockSignals(False)

    @staticmethod
    def _table_cols(bucket3: bool) -> list[tuple[str, str]]:
        return list(GeneratedOptionOrdersDialog._BUCKET3_COLS if bucket3 else GeneratedOptionOrdersDialog._BUCKET2_COLS)

    def _reload_scenarios(self, selected_id: int | None = None) -> None:
        load_test_order_scenarios_cache_from_db()
        if selected_id is None:
            selected_id = getattr(SNAPSHOT_STORE, "runtime_active_test_order_scenario_id", None)
        if selected_id is None:
            selected_id = ensure_default_test_order_scenario()
        df = get_cached_test_order_scenarios()
        rows = sorted(
            df.to_dicts(),
            key=lambda row: str(row.get("scenario_name") or "").strip().lower(),
        ) if df is not None and not df.is_empty() else []
        self.comboScenario.blockSignals(True)
        try:
            self.comboScenario.clear()
            target_index = -1
            for idx, row in enumerate(rows):
                scenario_id = int(row.get("scenario_id"))
                scenario_name = str(row.get("scenario_name") or "")
                self.comboScenario.addItem(scenario_name, scenario_id)
                if scenario_id == selected_id:
                    target_index = idx
            if target_index < 0:
                selected_id = ensure_default_test_order_scenario()
                self.comboScenario.addItem("Default", selected_id)
                target_index = self.comboScenario.count() - 1
            self.comboScenario.setCurrentIndex(target_index)
            self._scenario_id = int(self.comboScenario.currentData())
        finally:
            self.comboScenario.blockSignals(False)

    def _generated_df_for_selected_scenario(self) -> pl.DataFrame:
        scenario_id = self._scenario_id or ensure_default_test_order_scenario()
        df = get_test_orders(asset_rollup=None, scenario_id=None)
        if df is None or df.is_empty():
            return pl.DataFrame()
        content_map = get_cached_test_order_scenario_content_map(int(scenario_id))
        enabled_map = {
            str(uid).strip(): int(row.get("enabled") or 0)
            for uid, row in content_map.items()
            if str(uid).strip()
        }
        if SCENARIO_ORDER_UID_COL not in df.columns:
            return df.with_columns(pl.lit(0).alias("include"))
        return df.with_columns(
            pl.col(SCENARIO_ORDER_UID_COL)
            .cast(pl.Utf8, strict=False)
            .map_elements(lambda uid: int(enabled_map.get(str(uid or "").strip(), 0)), return_dtype=pl.Int64)
            .alias("include")
        )

    def _reload_tables(self) -> None:
        df = self._generated_df_for_selected_scenario()
        if df.is_empty():
            self._bucket1_df = pl.DataFrame()
            self._bucket2_df = pl.DataFrame()
            self._bucket3_df = pl.DataFrame()
        else:
            if SOURCE_BUCKET_COL in df.columns:
                self._bucket1_df = df.filter(pl.col(SOURCE_BUCKET_COL).fill_null(BUCKET_1).cast(pl.Utf8, strict=False) == BUCKET_1)
                self._bucket2_df = df.filter(pl.col(SOURCE_BUCKET_COL) == BUCKET_2)
                self._bucket3_df = df.filter(pl.col(SOURCE_BUCKET_COL) == BUCKET_3)
            else:
                self._bucket1_df = df
                self._bucket2_df = pl.DataFrame()
                self._bucket3_df = pl.DataFrame()
        self.tableBucket1.blockSignals(True)
        try:
            self._fill_bucket_table(self.tableBucket1, self._bucket1_df, bucket3=False)
        finally:
            self.tableBucket1.blockSignals(False)
        self._render_tables_from_frames()
        self.labelStatus.setText(
            f"Scenario {self.comboScenario.currentText()} | bucket1={self._bucket1_df.height if not self._bucket1_df.is_empty() else 0} | "
            f"bucket2={self._bucket2_df.height if not self._bucket2_df.is_empty() else 0} | "
            f"bucket3={self._bucket3_df.height if not self._bucket3_df.is_empty() else 0}"
        )

    def _render_tables_from_frames(self) -> None:
        self._bucket2_df = self._with_itm_otm(self._bucket2_df)
        self._bucket3_df = self._with_itm_otm(self._bucket3_df)
        self._fill_bucket_table(self.tableBucket2, self._bucket2_df, bucket3=False)
        self._fill_bucket_table(self.tableBucket3, self._bucket3_df, bucket3=True)
        self._reload_bucket2_filters()
        self._sync_bucket3_checkstates_from_bucket2()
        self._apply_bucket2_filters()

    def _toggle_bucket3_collapsed(self) -> None:
        self._bucket3_collapsed = not self._bucket3_collapsed
        self._apply_bucket3_collapsed_state()

    def _apply_bucket3_collapsed_state(self) -> None:
        self.tableBucket3.setVisible(not self._bucket3_collapsed)
        self.btnToggleBucket3.setArrowType(Qt.RightArrow if self._bucket3_collapsed else Qt.DownArrow)

    def _fill_bucket_table(self, table: QTableWidget, df: pl.DataFrame, *, bucket3: bool) -> None:
        cols = self._table_cols(bucket3 or table is self.tableBucket1)

        table.blockSignals(True)
        try:
            sorting = table.isSortingEnabled()
            table.setSortingEnabled(False)
            table.clear()
            table.setColumnCount(len(cols))
            table.setHorizontalHeaderLabels([label for label, _ in cols])
            rows = df.to_dicts() if df is not None and not df.is_empty() else []
            table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, (_label, key) in enumerate(cols):
                    if key == "include":
                        item = CheckableSortItem()
                        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
                        if not bucket3:
                            flags |= Qt.ItemIsUserCheckable
                        item.setFlags(flags)
                        item.setCheckState(Qt.Checked if int(row.get("include") or 0) == 1 else Qt.Unchecked)
                        item.setData(Qt.UserRole, str(row.get(SCENARIO_ORDER_UID_COL) or ""))
                        if bucket3:
                            item.setData(Qt.UserRole + 1, str(row.get(PARENT_CHANGE_UID_COL) or ""))
                        table.setItem(r, c, item)
                        continue
                    if key == CHANGE_KIND_COL and table is self.tableBucket2:
                        current_value = str(row.get(key) or "").strip() or CHANGE_KIND_OPTION_EOM
                        item = QTableWidgetItem(current_value)
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        table.setItem(r, c, item)
                        table.setCellWidget(
                            r,
                            c,
                            self._build_change_kind_toggle(
                                str(row.get(SCENARIO_ORDER_UID_COL) or "").strip(),
                                current_value,
                                table,
                            ),
                        )
                        continue
                    value = row.get(key)
                    text = "" if value is None else str(value)
                    item = QTableWidgetItem(text)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    table.setItem(r, c, item)
            table.setSortingEnabled(sorting)
        finally:
            table.blockSignals(False)

    def _reload_bucket2_filters(self) -> None:
        rows = self._bucket2_df.to_dicts() if self._bucket2_df is not None and not self._bucket2_df.is_empty() else []
        self._bucket2_filter_items = rows
        self._broker_filter_options = sorted({str(r.get("broker") or "").strip() for r in rows if str(r.get("broker") or "").strip()})
        self._broker_filter_selected = {v for v in self._broker_filter_selected if v in self._broker_filter_options}
        self._asset_filter_options = sorted({str(r.get("asset_rollup") or "").strip() for r in rows if str(r.get("asset_rollup") or "").strip()})
        self._asset_filter_selected = {v for v in self._asset_filter_selected if v in self._asset_filter_options}
        self._itm_filter_options = sorted({str(r.get("itm_otm") or "").strip() for r in rows if str(r.get("itm_otm") or "").strip()})
        self._itm_filter_selected = {v for v in self._itm_filter_selected if v in self._itm_filter_options}
        self._fill_filter_combo(self.filterCp, sorted({str(r.get("optie_call_put") or "").strip() for r in rows if str(r.get("optie_call_put") or "").strip()}))
        def _exp_sort_key(s: str):
            try:
                d, m, y = s.split("-")
                return (int(y), int(m), int(d))
            except Exception:
                return (9999, 99, 99)
        self._exp_filter_options = sorted(
            {str(r.get("optie_exp_date") or "").strip() for r in rows if str(r.get("optie_exp_date") or "").strip()},
            key=_exp_sort_key,
        )
        self._exp_filter_selected = {v for v in self._exp_filter_selected if v in self._exp_filter_options}
        self._sync_broker_button()
        self._sync_asset_button()
        self._sync_itm_button()
        self._sync_exp_button()

    def _build_change_kind_toggle(self, scenario_uid: str, value: str, parent: QWidget) -> QWidget:
        wrapper = QWidget(parent)
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)
        btn_eom = QToolButton(wrapper)
        btn_eom.setText("EOM")
        btn_eom.setCheckable(True)
        btn_eom.setAutoExclusive(True)
        btn_mkt = QToolButton(wrapper)
        btn_mkt.setText("Mkt Close")
        btn_mkt.setCheckable(True)
        btn_mkt.setAutoExclusive(True)
        current = str(value or "").strip() or CHANGE_KIND_OPTION_EOM
        btn_eom.setChecked(current == CHANGE_KIND_OPTION_EOM)
        btn_mkt.setChecked(current == CHANGE_KIND_MARKET_CLOSE)
        btn_eom.clicked.connect(
            lambda checked, uid=scenario_uid: self._on_bucket2_change_kind_changed(uid, CHANGE_KIND_OPTION_EOM)
            if checked else None
        )
        btn_mkt.clicked.connect(
            lambda checked, uid=scenario_uid: self._on_bucket2_change_kind_changed(uid, CHANGE_KIND_MARKET_CLOSE)
            if checked else None
        )
        layout.addWidget(btn_eom)
        layout.addWidget(btn_mkt)
        layout.addStretch(1)
        return wrapper

    def _clear_filters(self) -> None:
        self.searchAll.blockSignals(True)
        try:
            self.searchAll.clear()
        finally:
            self.searchAll.blockSignals(False)
        for combo in (self.filterCp,):
            combo.blockSignals(True)
            try:
                combo.setCurrentIndex(0)
            finally:
                combo.blockSignals(False)
        self._broker_filter_selected = set()
        self._asset_filter_selected = set()
        self._itm_filter_selected = set()
        self._exp_filter_selected = set()
        self._sync_broker_button()
        self._sync_asset_button()
        self._sync_itm_button()
        self._sync_exp_button()
        self._apply_bucket2_filters()

    def _row_matches_bucket2_filters(self, row: int) -> bool:
        q = (self.searchAll.text() or "").strip().lower()
        if q:
            haystack = " | ".join(
                (self.tableBucket2.item(row, col).text() if self.tableBucket2.item(row, col) else "").strip().lower()
                for col in range(1, self.tableBucket2.columnCount())
            )
            terms = [part.strip().lower() for part in q.split(",") if part.strip()]
            if any(term not in haystack for term in terms):
                return False
        checks = [
            (self.filterCp, "optie_call_put"),
        ]
        for combo, key in checks:
            selected = (combo.currentText() or "C/P").strip()
            if selected in {"ALL", "C/P", ""}:
                continue
            if key == "broker":
                col = 2
            elif key == "asset_rollup":
                col = 1
            elif key == "optie_call_put":
                col = self._bucket2_column_index("optie_call_put")
            item = self.tableBucket2.item(row, col)
            value = (item.text() if item else "").strip()
            if value != selected:
                return False
        if self._broker_filter_selected:
            item = self.tableBucket2.item(row, 2)
            value = (item.text() if item else "").strip()
            if value not in self._broker_filter_selected:
                return False
        if self._asset_filter_selected:
            item = self.tableBucket2.item(row, self._bucket2_column_index("asset_rollup"))
            value = (item.text() if item else "").strip()
            if value not in self._asset_filter_selected:
                return False
        if self._itm_filter_selected:
            item = self.tableBucket2.item(row, self._bucket2_column_index("itm_otm"))
            value = (item.text() if item else "").strip()
            if value not in self._itm_filter_selected:
                return False
        if self._exp_filter_selected:
            item = self.tableBucket2.item(row, self._bucket2_column_index("optie_exp_date"))
            value = (item.text() if item else "").strip()
            if value not in self._exp_filter_selected:
                return False
        return True

    def _bucket2_column_index(self, key: str) -> int:
        for idx, (_label, col_key) in enumerate(self._BUCKET2_COLS):
            if col_key == key:
                return idx
        return -1

    def _sync_broker_button(self) -> None:
        count = len(self._broker_filter_selected)
        self.btnBrokerFilter.setText(f"Broker ({count})" if count > 0 else "Broker")

    def _sync_asset_button(self) -> None:
        count = len(self._asset_filter_selected)
        self.btnAssetFilter.setText(f"Asset ({count})" if count > 0 else "Asset")

    def _sync_itm_button(self) -> None:
        count = len(self._itm_filter_selected)
        self.btnItmFilter.setText(f"ITM/OTM ({count})" if count > 0 else "ITM/OTM")

    def _sync_exp_button(self) -> None:
        count = len(self._exp_filter_selected)
        self.btnExpFilter.setText(f"Expiratie ({count})" if count > 0 else "Expiratie")

    def _open_broker_filter_dialog(self) -> None:
        dlg = MultiSelectFilterDialog("Filter: broker", "Zoek broker...", self._broker_filter_options, self._broker_filter_selected, self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._broker_filter_selected = dlg.selected_values()
        self._sync_broker_button()
        self._apply_bucket2_filters()

    def _open_asset_filter_dialog(self) -> None:
        dlg = MultiSelectFilterDialog("Filter: asset_rollup", "Zoek asset...", self._asset_filter_options, self._asset_filter_selected, self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._asset_filter_selected = dlg.selected_values()
        self._sync_asset_button()
        self._apply_bucket2_filters()

    def _open_itm_filter_dialog(self) -> None:
        dlg = MultiSelectFilterDialog("Filter: itm_otm", "Zoek ITM/OTM...", self._itm_filter_options, self._itm_filter_selected, self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._itm_filter_selected = dlg.selected_values()
        self._sync_itm_button()
        self._apply_bucket2_filters()

    def _open_expiry_filter_dialog(self) -> None:
        dlg = MultiSelectFilterDialog("Filter: optie_exp_date", "Zoek datum...", self._exp_filter_options, self._exp_filter_selected, self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._exp_filter_selected = dlg.selected_values()
        self._sync_exp_button()
        self._apply_bucket2_filters()

    @staticmethod
    def _spot_lookup() -> dict[str, float]:
        out: dict[str, float] = {}
        df_live = getattr(SNAPSHOT_STORE, "aggregator_snapshot_load_open_opties_from_tx_live", None)
        if df_live is not None and not df_live.is_empty() and {"asset_rollup", "Koers"}.issubset(set(df_live.columns)):
            for row in df_live.select(["asset_rollup", "Koers"]).to_dicts():
                asset = str(row.get("asset_rollup") or "").strip()
                if not asset:
                    continue
                try:
                    price = float(row.get("Koers"))
                except Exception:
                    continue
                if asset not in out:
                    out[asset] = price
        for attr, price_col in (
            ("repository_snapshot_active_asset_rollup_data", "koers"),
            ("repository_snapshot_asset_rollup_data", "koers"),
            ("repository_snapshot_portfolio_value_total_combined_put", "koers"),
            ("repository_snapshot_historical_close_latest", "close_price"),
        ):
            df = getattr(SNAPSHOT_STORE, attr, None)
            if df is None or df.is_empty() or "asset_rollup" not in df.columns or price_col not in df.columns:
                continue
            for row in df.select(["asset_rollup", price_col]).to_dicts():
                asset = str(row.get("asset_rollup") or "").strip()
                if not asset:
                    continue
                try:
                    price = float(row.get(price_col))
                except Exception:
                    continue
                if asset not in out:
                    out[asset] = price
        return out

    @staticmethod
    def _norm_option_exp(value) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if hasattr(value, "strftime"):
            try:
                return value.strftime("%d-%m-%Y")
            except Exception:
                return text
        for sep in ("-", "/", "."):
            parts = text.replace("/", sep).replace(".", sep).split(sep)
            if len(parts) != 3:
                continue
            try:
                a, b, c = [int(p) for p in parts]
            except Exception:
                continue
            if len(parts[0]) == 4:
                year, month, day = a, b, c
                return f"{day:02d}-{month:02d}-{year:04d}"
            year = c + 2000 if c < 100 else c
            return f"{a:02d}-{b:02d}-{year:04d}"
        return text

    def _option_price_lookup(self) -> dict[tuple[str, str, str, str, str], float]:
        out: dict[tuple[str, str, str, str, str], float] = {}
        df = getattr(SNAPSHOT_STORE, "snapshot_optie_timevalue_live", None)
        if (
            df is not None
            and not df.is_empty()
            and {"broker", "asset", "c_p", "strike", "exp", "last_px"}.issubset(set(df.columns))
        ):
            for row in df.to_dicts():
                try:
                    price = float(row.get("last_px"))
                    strike_key = f"{float(row.get('strike')):.8f}"
                except Exception:
                    continue
                if price <= 0:
                    continue
                key = (
                    str(row.get("broker") or "").strip().lower(),
                    str(row.get("asset") or "").strip().upper(),
                    str(row.get("c_p") or "").strip().lower(),
                    strike_key,
                    self._norm_option_exp(row.get("exp")),
                )
                if all(key) and key not in out:
                    out[key] = price
        return out

    def _market_close_price_for_row(self, row: dict, lookup: dict[tuple[str, str, str, str, str], float]) -> float:
        try:
            strike_key = f"{float(row.get('optie_strike')):.8f}"
        except Exception:
            strike_key = ""
        key = (
            str(row.get("broker") or "").strip().lower(),
            str(row.get("asset_rollup") or "").strip().upper(),
            str(row.get("optie_call_put") or "").strip().lower(),
            strike_key,
            self._norm_option_exp(row.get("optie_exp_date")),
        )
        if key in lookup:
            return float(lookup[key])
        try:
            return float(row.get("transactie_prijs") or 0.0)
        except Exception:
            return 0.0

    def _rebuild_bucket3_preview_from_bucket2(self) -> None:
        rows = self._bucket2_df.to_dicts() if self._bucket2_df is not None and not self._bucket2_df.is_empty() else []
        existing_by_parent: dict[str, dict] = {}
        if self._bucket3_df is not None and not self._bucket3_df.is_empty():
            for row in self._bucket3_df.to_dicts():
                parent_uid = str(row.get(PARENT_CHANGE_UID_COL) or "").strip()
                if parent_uid:
                    existing_by_parent[parent_uid] = row
        spot_lookup = self._spot_lookup()
        out_rows: list[dict] = []
        for row in rows:
            if str(row.get(CHANGE_KIND_COL) or "").strip() != CHANGE_KIND_OPTION_EOM:
                continue
            asset = str(row.get("asset_rollup") or "").strip()
            cp = str(row.get("optie_call_put") or "").strip().lower()
            try:
                strike = float(row.get("optie_strike"))
                amount = abs(float(row.get("transactie_aantal") or 0.0))
            except Exception:
                continue
            spot = spot_lookup.get(asset)
            if spot is None:
                continue
            is_itm = (cp == "call" and spot > strike) or (cp == "put" and spot < strike)
            if not is_itm:
                continue
            parent_uid = str(row.get(SCENARIO_ORDER_UID_COL) or "").strip()
            existing = existing_by_parent.get(parent_uid, {})
            bucket2_type = str(row.get("transactie_type") or "").strip().lower()
            position_amount = -amount if bucket2_type == "koop" else amount
            transactie_type = (
                ("koop" if position_amount > 0 else "verkoop")
                if cp == "call"
                else ("verkoop" if position_amount > 0 else "koop")
            )
            out_rows.append(
                {
                    SCENARIO_ORDER_UID_COL: str(existing.get(SCENARIO_ORDER_UID_COL) or "").strip() or parent_uid,
                    SOURCE_BUCKET_COL: BUCKET_3,
                    SOURCE_TYPE_COL: SOURCE_TYPE_OPTION_EOM_CHILD,
                    PARENT_CHANGE_UID_COL: parent_uid,
                    CHANGE_KIND_COL: CHANGE_KIND_OPTION_EOM,
                    "broker": row.get("broker"),
                    "asset_rollup": row.get("asset_rollup"),
                    "asset_type": "aandeel",
                    "transactie_type": transactie_type,
                    "transactie_aantal": amount,
                    "transactie_prijs": strike,
                    "optie_call_put": None,
                    "optie_strike": None,
                    "optie_exp_date": row.get("optie_exp_date"),
                    "create_date": row.get("create_date"),
                    "include": int(row.get("include") or 0),
                }
            )
        self._bucket3_df = pl.from_dicts(out_rows, strict=False) if out_rows else pl.DataFrame()

    def _on_bucket2_change_kind_changed(self, scenario_uid: str, change_kind: str) -> None:
        uid = str(scenario_uid or "").strip()
        if not uid:
            return
        lookup = self._option_price_lookup()
        rows = self._bucket2_df.to_dicts() if self._bucket2_df is not None and not self._bucket2_df.is_empty() else []
        changed = False
        for row in rows:
            if str(row.get(SCENARIO_ORDER_UID_COL) or "").strip() != uid:
                continue
            row[CHANGE_KIND_COL] = change_kind
            row["transactie_prijs"] = (
                0.0 if change_kind == CHANGE_KIND_OPTION_EOM else self._market_close_price_for_row(row, lookup)
            )
            changed = True
            break
        if not changed:
            return
        self._bucket2_df = pl.from_dicts(rows, strict=False) if rows else pl.DataFrame()
        self._rebuild_bucket3_preview_from_bucket2()
        self._render_tables_from_frames()

    def _set_bucket2_change_kind_for_visible(self, change_kind: str) -> None:
        visible_uids: set[str] = set()
        for row in range(self.tableBucket2.rowCount()):
            if self.tableBucket2.isRowHidden(row):
                continue
            item = self.tableBucket2.item(row, 0)
            if item is None:
                continue
            uid = str(item.data(Qt.UserRole) or "").strip()
            if uid:
                visible_uids.add(uid)
        if not visible_uids:
            return
        lookup = self._option_price_lookup()
        rows = self._bucket2_df.to_dicts() if self._bucket2_df is not None and not self._bucket2_df.is_empty() else []
        changed = False
        for row in rows:
            if str(row.get(SCENARIO_ORDER_UID_COL) or "").strip() not in visible_uids:
                continue
            row[CHANGE_KIND_COL] = change_kind
            row["transactie_prijs"] = (
                0.0 if change_kind == CHANGE_KIND_OPTION_EOM else self._market_close_price_for_row(row, lookup)
            )
            changed = True
        if not changed:
            return
        self._bucket2_df = pl.from_dicts(rows, strict=False) if rows else pl.DataFrame()
        self._rebuild_bucket3_preview_from_bucket2()
        self._render_tables_from_frames()

    def _with_itm_otm(self, df: pl.DataFrame) -> pl.DataFrame:
        if df is None or df.is_empty():
            return pl.DataFrame() if df is None else df
        required = {"asset_rollup", "optie_call_put", "optie_strike"}
        if not required.issubset(set(df.columns)):
            return df
        spot_lookup = self._spot_lookup()
        rows = []
        for row in df.to_dicts():
            out = dict(row)
            asset = str(out.get("asset_rollup") or "").strip()
            cp = str(out.get("optie_call_put") or "").strip().lower()
            try:
                strike = float(out.get("optie_strike"))
            except Exception:
                strike = None
            spot = spot_lookup.get(asset)
            verdict = ""
            if cp in {"call", "put"} and strike is not None and spot is not None:
                verdict = "ITM" if ((cp == "call" and spot > strike) or (cp == "put" and spot < strike)) else "OTM"
            out["itm_otm"] = verdict
            rows.append(out)
        return pl.from_dicts(rows, strict=False) if rows else df

    def _apply_bucket2_filters(self) -> None:
        for row in range(self.tableBucket2.rowCount()):
            self.tableBucket2.setRowHidden(row, not self._row_matches_bucket2_filters(row))

    def _table_rows_for_save(self, table: QTableWidget, df: pl.DataFrame) -> list[dict]:
        rows: list[dict] = []
        source_rows = df.to_dicts() if df is not None and not df.is_empty() else []
        source_map = {
            str(row.get(SCENARIO_ORDER_UID_COL) or "").strip(): dict(row)
            for row in source_rows
            if str(row.get(SCENARIO_ORDER_UID_COL) or "").strip()
        }
        for r in range(table.rowCount()):
            uid_item = table.item(r, 0)
            uid = str(uid_item.data(Qt.UserRole) or "").strip() if uid_item is not None else ""
            if not uid:
                continue
            source_row = source_map.get(uid)
            if source_row is None:
                continue
            row = dict(source_row)
            row[SCENARIO_ORDER_UID_COL] = uid
            if table is self.tableBucket3:
                parent_uid = str(uid_item.data(Qt.UserRole + 1) or "").strip()
                row["include"] = 1 if self._bucket2_checkstate_by_uid(parent_uid) == Qt.Checked else 0
            else:
                row["include"] = 1 if (uid_item and uid_item.checkState() == Qt.Checked) else 0
            rows.append(row)
        return rows

    def _current_generated_include_maps(self) -> tuple[dict[str, int], dict[str, int]]:
        bucket2_map: dict[str, int] = {}
        bucket3_map: dict[str, int] = {}
        for row in self._table_rows_for_save(self.tableBucket2, self._bucket2_df):
            uid = str(row.get(SCENARIO_ORDER_UID_COL) or "").strip()
            if uid:
                bucket2_map[uid] = int(row.get("include") or 0)
        for row in self._table_rows_for_save(self.tableBucket3, self._bucket3_df):
            uid = str(row.get(SCENARIO_ORDER_UID_COL) or "").strip()
            if uid:
                bucket3_map[uid] = int(row.get("include") or 0)
        return bucket2_map, bucket3_map

    def _bucket2_checkstate_by_uid(self, scenario_uid: str) -> Qt.CheckState:
        suid = str(scenario_uid or "").strip()
        for row in range(self.tableBucket2.rowCount()):
            item = self.tableBucket2.item(row, 0)
            if item is None:
                continue
            if str(item.data(Qt.UserRole) or "").strip() == suid:
                return item.checkState()
        return Qt.Unchecked

    def _sync_bucket3_checkstates_from_bucket2(self) -> None:
        self.tableBucket3.blockSignals(True)
        try:
            for row in range(self.tableBucket3.rowCount()):
                item = self.tableBucket3.item(row, 0)
                if item is None:
                    continue
                parent_uid = str(item.data(Qt.UserRole + 1) or "").strip()
                item.setCheckState(self._bucket2_checkstate_by_uid(parent_uid))
        finally:
            self.tableBucket3.blockSignals(False)

    def _on_bucket2_item_changed(self, item: QTableWidgetItem) -> None:
        if self._suppress_bucket2_item_changed:
            return
        if item.column() != 0:
            return
        self._sync_bucket3_checkstates_from_bucket2()

    def _set_all_checks(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        self._suppress_bucket2_item_changed = True
        self.tableBucket2.blockSignals(True)
        try:
            for row in range(self.tableBucket2.rowCount()):
                item = self.tableBucket2.item(row, 0)
                if item is not None:
                    item.setCheckState(state)
        finally:
            self.tableBucket2.blockSignals(False)
            self._suppress_bucket2_item_changed = False
        self._sync_bucket3_checkstates_from_bucket2()

    def _set_filtered_bucket2_checks(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        self._suppress_bucket2_item_changed = True
        self.tableBucket2.blockSignals(True)
        try:
            for row in range(self.tableBucket2.rowCount()):
                if self.tableBucket2.isRowHidden(row):
                    continue
                item = self.tableBucket2.item(row, 0)
                if item is not None:
                    item.setCheckState(state)
        finally:
            self.tableBucket2.blockSignals(False)
            self._suppress_bucket2_item_changed = False
        self._sync_bucket3_checkstates_from_bucket2()

    def _apply_test_orders_enabled_state(self, checked: bool) -> None:
        SNAPSHOT_STORE.runtime_test_orders_enabled = bool(checked)
        scenario_id = self._scenario_id or ensure_default_test_order_scenario()
        refresh_portfolio_value_scenario_overlay_snapshot(int(scenario_id), enabled=bool(checked))
        refresh_sector_scenario_overlay_snapshots(int(scenario_id), enabled=bool(checked))
        refresh_aandelen_scenario_overlay_snapshot(int(scenario_id), enabled=bool(checked))
        signals.queued_emit_testOrdersEnabledChanged(bool(checked))

    def _on_toggle_enable_test_orders(self, checked: bool) -> None:
        self._apply_test_orders_enabled_state(bool(checked))

    def _on_test_orders_enabled_changed(self, enabled: bool) -> None:
        self.checkEnableTestOrders.blockSignals(True)
        try:
            self.checkEnableTestOrders.setChecked(bool(enabled))
        finally:
            self.checkEnableTestOrders.blockSignals(False)

    def _persist_current_scenario(self) -> None:
        scenario_id = self._scenario_id or ensure_default_test_order_scenario()
        self._sync_bucket3_checkstates_from_bucket2()
        rows = self._table_rows_for_save(self.tableBucket1, self._bucket1_df)
        rows.extend(self._table_rows_for_save(self.tableBucket2, self._bucket2_df))
        rows.extend(self._table_rows_for_save(self.tableBucket3, self._bucket3_df))
        if not rows:
            return
        save_scenario_content_for_visible_rows(int(scenario_id), self._scenario_content_safe_df(rows))
        flush_dirty_test_order_scenarios_to_db()
        refresh_active_scenario_orders_snapshot(int(scenario_id))
        if int(getattr(SNAPSHOT_STORE, "runtime_active_test_order_scenario_id", -1) or -1) == int(scenario_id):
            enabled = bool(getattr(SNAPSHOT_STORE, "runtime_test_orders_enabled", False))
            refresh_portfolio_value_scenario_overlay_snapshot(int(scenario_id), enabled=enabled)
            refresh_sector_scenario_overlay_snapshots(int(scenario_id), enabled=enabled)
            refresh_aandelen_scenario_overlay_snapshot(int(scenario_id), enabled=enabled)

    def _persist_generated_bucket2_rows(self) -> None:
        if self._bucket2_df is None or self._bucket2_df.is_empty():
            return
        by_asset: dict[str, list[dict]] = {}
        for row in self._bucket2_df.to_dicts():
            asset = str(row.get("asset_rollup") or "").strip()
            if asset:
                by_asset.setdefault(asset, []).append(dict(row))
        for asset, bucket2_rows in by_asset.items():
            existing_df = get_cached_orders(asset)
            manual_rows: list[dict] = []
            if existing_df is not None and not existing_df.is_empty():
                manual_rows = [
                    row for row in existing_df.to_dicts()
                    if str(row.get(SOURCE_BUCKET_COL) or "").strip() not in {BUCKET_2, BUCKET_3}
                ]
            combined_rows = manual_rows + bucket2_rows
            set_cached_orders_for_asset(
                asset,
                pl.from_dicts(combined_rows, strict=False) if combined_rows else pl.DataFrame(),
            )
        flush_dirty_test_orders_to_db()

    def _on_scenario_changed(self, _index: int) -> None:
        data = self.comboScenario.currentData()
        if data is None:
            return
        self._scenario_id = int(data)
        self._reload_tables()

    def _on_test_order_scenarios_changed(self) -> None:
        load_test_order_scenarios_cache_from_db()
        self._reload_scenarios(selected_id=self._scenario_id)
        self._reload_tables()

    def _open_scenario_manager(self) -> None:
        df = get_cached_test_order_scenarios()
        dialog = ScenarioManagerDialog(df, self)
        if dialog.exec() != QDialog.Accepted:
            return

        rows = dialog.get_rows()
        current_rows = get_cached_test_order_scenarios().to_dicts()
        current_by_id = {int(row["scenario_id"]): row for row in current_rows}
        remaining_ids = set(current_by_id.keys())
        selected_scenario_id = self._scenario_id

        for row in rows:
            scenario_id = row.get("scenario_id")
            if scenario_id is None:
                continue
            remaining_ids.discard(int(scenario_id))

        seen_names = set()
        for row in rows:
            scenario_name = str(row.get("scenario_name") or "").strip()
            if not scenario_name:
                continue
            key = scenario_name.lower()
            scenario_id = row.get("scenario_id")

            if scenario_id is None:
                if key in seen_names:
                    continue
                seen_names.add(key)
                new_id = create_test_order_scenario_in_cache(scenario_name)
                if selected_scenario_id is None:
                    selected_scenario_id = new_id
                continue

            scenario_id = int(scenario_id)
            existing_name = str(current_by_id.get(scenario_id, {}).get("scenario_name") or "").strip()
            if key in seen_names and existing_name.lower() != key:
                continue
            seen_names.add(key)
            if existing_name != scenario_name:
                try:
                    rename_test_order_scenario_in_cache(scenario_id, scenario_name)
                except ValueError:
                    continue

        for scenario_id in sorted(remaining_ids):
            try:
                delete_test_order_scenario_in_cache(scenario_id)
            except ValueError:
                continue
            if selected_scenario_id == scenario_id:
                selected_scenario_id = None

        flush_dirty_test_order_scenarios_to_db()
        load_test_order_scenarios_cache_from_db()
        signals.queued_emit_testOrderScenariosChanged()
        if selected_scenario_id is None:
            selected_scenario_id = ensure_default_test_order_scenario()
        self._reload_scenarios(selected_id=int(selected_scenario_id))
        self._reload_tables()

    def _on_sync_clicked(self) -> None:
        scenario_id = self._scenario_id or ensure_default_test_order_scenario()
        try:
            bucket2_include_map, bucket3_include_map = self._current_generated_include_maps()
            self._persist_generated_bucket2_rows()
            stats = sync_generated_option_orders()
            generated_df = get_test_orders(asset_rollup=None, scenario_id=None)
            if generated_df is not None and not generated_df.is_empty() and SOURCE_BUCKET_COL in generated_df.columns:
                content_map = get_cached_test_order_scenario_content_map(int(scenario_id))
                enabled_uids = {
                    uid for uid, row in content_map.items()
                    if int(row.get("enabled") or 0) == 1
                }
                generated_rows: list[dict] = []
                for row in generated_df.filter(
                    pl.col(SOURCE_BUCKET_COL).cast(pl.Utf8, strict=False).is_in([BUCKET_2, BUCKET_3])
                ).to_dicts():
                    uid = str(row.get(SCENARIO_ORDER_UID_COL) or "").strip()
                    parent_uid = str(row.get(PARENT_CHANGE_UID_COL) or "").strip()
                    bucket = str(row.get(SOURCE_BUCKET_COL) or "").strip()
                    if bucket == BUCKET_2 and uid in bucket2_include_map:
                        include = int(bucket2_include_map[uid])
                    elif bucket == BUCKET_3 and uid in bucket3_include_map:
                        include = int(bucket3_include_map[uid])
                    elif bucket == BUCKET_3 and parent_uid in bucket2_include_map:
                        include = int(bucket2_include_map[parent_uid])
                    else:
                        include = 1 if uid in enabled_uids else 0
                    out = dict(row)
                    out["include"] = include
                    generated_rows.append(out)
                generated_df = pl.from_dicts(generated_rows, strict=False) if generated_rows else pl.DataFrame()
                if not generated_df.is_empty():
                    save_scenario_content_for_visible_rows(int(scenario_id), generated_df)
                    flush_dirty_test_order_scenarios_to_db()
                    refresh_active_scenario_orders_snapshot(int(scenario_id))
                    if int(getattr(SNAPSHOT_STORE, "runtime_active_test_order_scenario_id", -1) or -1) == int(scenario_id):
                        enabled = bool(getattr(SNAPSHOT_STORE, "runtime_test_orders_enabled", False))
                        refresh_portfolio_value_scenario_overlay_snapshot(int(scenario_id), enabled=enabled)
                        refresh_sector_scenario_overlay_snapshots(int(scenario_id), enabled=enabled)
                        refresh_aandelen_scenario_overlay_snapshot(int(scenario_id), enabled=enabled)
        except Exception as exc:
            QMessageBox.warning(self, "Sync mislukt", str(exc))
            return
        self._reload_tables()
        self.labelStatus.setText(
            "Sync voltooid | "
            f"source={stats.get('source')} | open={stats.get('open_option_rows')} | uid={stats.get('open_option_uid_rows')} | "
            f"b2 +{stats['bucket2_inserted']} / ~{stats['bucket2_updated']} / -{stats['bucket2_deleted']} | "
            f"b3 +{stats['bucket3_inserted']} / ~{stats['bucket3_updated']} / -{stats['bucket3_deleted']}"
        )

    def _on_save_clicked(self) -> None:
        try:
            self._persist_generated_bucket2_rows()
            self._on_sync_clicked()
            self._persist_current_scenario()
        except Exception as exc:
            QMessageBox.warning(self, "Save mislukt", str(exc))
            return
        self._reload_tables()
        self.labelStatus.setText(f"Scenario {self.comboScenario.currentText()} opgeslagen.")

    def _restore_geometry(self):
        from portefeuille_viewer.config import get_settings
        geo = get_settings().get_scenario_editor_window_geometry()
        if geo:
            screens = QGuiApplication.screens()
            on_screen = any(
                s.geometry().contains(geo['x'] + 50, geo['y'] + 50)
                for s in screens
            )
            if on_screen:
                self.setGeometry(geo['x'], geo['y'], geo['w'], geo['h'])
                return
        self.resize(1180, 760)

    def closeEvent(self, event):
        from portefeuille_viewer.config import get_settings
        g = self.geometry()
        get_settings().set_scenario_editor_window_geometry(g.x(), g.y(), g.width(), g.height())
        if getattr(self, '_force_close', False):
            global _SCENARIO_DIALOG_INSTANCE
            _SCENARIO_DIALOG_INSTANCE = None
            event.accept()
        else:
            event.ignore()
            self.hide()


# --- Singleton toegangspunt ---

_SCENARIO_DIALOG_INSTANCE: "GeneratedOptionOrdersDialog | None" = None


def open_scenario_dialog() -> None:
    global _SCENARIO_DIALOG_INSTANCE
    if _SCENARIO_DIALOG_INSTANCE is not None:
        try:
            _SCENARIO_DIALOG_INSTANCE.isVisible()
        except RuntimeError:
            _SCENARIO_DIALOG_INSTANCE = None
    if _SCENARIO_DIALOG_INSTANCE is None:
        _SCENARIO_DIALOG_INSTANCE = GeneratedOptionOrdersDialog(None)
    dlg = _SCENARIO_DIALOG_INSTANCE
    if dlg.windowState() & Qt.WindowMinimized:
        dlg.setWindowState(dlg.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        dlg.showNormal()
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()


def close_scenario_dialog() -> None:
    global _SCENARIO_DIALOG_INSTANCE
    if _SCENARIO_DIALOG_INSTANCE is not None:
        try:
            _SCENARIO_DIALOG_INSTANCE._force_close = True
            _SCENARIO_DIALOG_INSTANCE.close()
        except RuntimeError:
            pass
        _SCENARIO_DIALOG_INSTANCE = None

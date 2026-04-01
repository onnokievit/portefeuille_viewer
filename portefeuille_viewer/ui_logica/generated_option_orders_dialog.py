from __future__ import annotations

import polars as pl

from PySide6.QtCore import Qt
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
    QVBoxLayout,
    QWidget,
)

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.data.test_order_repository import (
    BUCKET_1,
    CHANGE_KIND_COL,
    PARENT_CHANGE_UID_COL,
    SCENARIO_ORDER_UID_COL,
    SOURCE_BUCKET_COL,
    ensure_default_test_order_scenario,
    flush_dirty_test_order_scenarios_to_db,
    get_cached_test_order_scenario_content_map,
    get_cached_test_order_scenarios,
    get_test_orders,
    load_test_order_scenarios_cache_from_db,
    save_scenario_content_for_visible_rows,
)
from portefeuille_viewer.services.scenario_aandelen_overlay import (
    refresh_aandelen_scenario_overlay_snapshot,
)
from portefeuille_viewer.services.scenario_generated_option_sync import (
    BUCKET_2,
    BUCKET_3,
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


class GeneratedOptionOrdersDialog(QDialog):
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
        self.setWindowTitle("Generated Option Orders")
        self.resize(1180, 760)
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

        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Scenario"))
        self.comboScenario = QComboBox(self)
        controls.addWidget(self.comboScenario)
        self.checkEnableTestOrders = QCheckBox("Test Orders", self)
        self.checkEnableTestOrders.setChecked(bool(getattr(SNAPSHOT_STORE, "runtime_test_orders_enabled", False)))
        controls.addWidget(self.checkEnableTestOrders)
        self.btnSync = QPushButton("Sync", self)
        controls.addWidget(self.btnSync)
        self.btnSelectAll = QPushButton("Select all", self)
        controls.addWidget(self.btnSelectAll)
        self.btnSelectNone = QPushButton("Select none", self)
        controls.addWidget(self.btnSelectNone)
        self.btnSave = QPushButton("Save", self)
        controls.addWidget(self.btnSave)
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
        filters.addWidget(QLabel("c/p"))
        self.filterCp = QComboBox(self)
        filters.addWidget(self.filterCp)
        self.btnExpFilter = QPushButton("Expiratie", self)
        filters.addWidget(self.btnExpFilter)
        self.btnFilteredOn = QPushButton("Selection on", self)
        filters.addWidget(self.btnFilteredOn)
        self.btnFilteredOff = QPushButton("Selection off", self)
        filters.addWidget(self.btnFilteredOff)
        self.btnClearFilters = QPushButton("Clear filters", self)
        filters.addWidget(self.btnClearFilters)
        filters.addStretch(1)
        layout.addLayout(filters)

        self.labelStatus = QLabel("", self)
        layout.addWidget(self.labelStatus)

        layout.addWidget(QLabel("Bucket 1 - Manual Test Orders", self))
        self.tableBucket1 = self._create_table(self)
        layout.addWidget(self.tableBucket1, 1)

        layout.addWidget(QLabel("Bucket 2 - Open Position", self))
        self.tableBucket2 = self._create_table(self)
        layout.addWidget(self.tableBucket2, 1)

        layout.addWidget(QLabel("Bucket 3 - Derived Option EOM", self))
        self.tableBucket3 = self._create_table(self)
        layout.addWidget(self.tableBucket3, 1)

        self.comboScenario.currentIndexChanged.connect(self._on_scenario_changed)
        self.checkEnableTestOrders.toggled.connect(self._on_toggle_enable_test_orders)
        self.btnSync.clicked.connect(self._on_sync_clicked)
        self.btnSelectAll.clicked.connect(lambda: self._set_all_checks(True))
        self.btnSelectNone.clicked.connect(lambda: self._set_all_checks(False))
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

        self._reload_scenarios()
        self._reload_tables()

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
            combo.addItem("ALL")
            for value in values:
                combo.addItem(value)
            idx = combo.findText(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            combo.blockSignals(False)

    def _reload_scenarios(self) -> None:
        load_test_order_scenarios_cache_from_db()
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
        df = get_test_orders(asset_rollup=None, scenario_id=scenario_id)
        if df is None or df.is_empty():
            return pl.DataFrame()
        return df

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
        self._bucket2_df = self._with_itm_otm(self._bucket2_df)
        self._bucket3_df = self._with_itm_otm(self._bucket3_df)
        self._fill_bucket_table(self.tableBucket2, self._bucket2_df, bucket3=False)
        self._fill_bucket_table(self.tableBucket3, self._bucket3_df, bucket3=True)
        self._reload_bucket2_filters()
        self._sync_bucket3_checkstates_from_bucket2()
        self._apply_bucket2_filters()
        self.labelStatus.setText(
            f"Scenario {self.comboScenario.currentText()} | bucket1={self._bucket1_df.height if not self._bucket1_df.is_empty() else 0} | "
            f"bucket2={self._bucket2_df.height if not self._bucket2_df.is_empty() else 0} | "
            f"bucket3={self._bucket3_df.height if not self._bucket3_df.is_empty() else 0}"
        )

    def _fill_bucket_table(self, table: QTableWidget, df: pl.DataFrame, *, bucket3: bool) -> None:
        cols = [
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
        if bucket3:
            cols.append(("Parent", PARENT_CHANGE_UID_COL))

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
        self._exp_filter_options = sorted({str(r.get("optie_exp_date") or "").strip() for r in rows if str(r.get("optie_exp_date") or "").strip()})
        self._exp_filter_selected = {v for v in self._exp_filter_selected if v in self._exp_filter_options}
        self._sync_broker_button()
        self._sync_asset_button()
        self._sync_itm_button()
        self._sync_exp_button()

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
                for col in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
            )
            terms = [part.strip().lower() for part in q.split(",") if part.strip()]
            if any(term not in haystack for term in terms):
                return False
        checks = [
            (self.filterCp, "optie_call_put"),
        ]
        for combo, key in checks:
            selected = (combo.currentText() or "ALL").strip()
            if selected == "ALL":
                continue
            if key == "broker":
                col = 2
            elif key == "asset_rollup":
                col = 1
            elif key == "optie_call_put":
                col = 7
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
            item = self.tableBucket2.item(row, 1)
            value = (item.text() if item else "").strip()
            if value not in self._asset_filter_selected:
                return False
        if self._itm_filter_selected:
            item = self.tableBucket2.item(row, 3)
            value = (item.text() if item else "").strip()
            if value not in self._itm_filter_selected:
                return False
        if self._exp_filter_selected:
            item = self.tableBucket2.item(row, 9)
            value = (item.text() if item else "").strip()
            if value not in self._exp_filter_selected:
                return False
        return True

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
        app = QApplication.instance()
        if app is None:
            return
        for widget in app.allWidgets():
            if getattr(widget, "objectName", lambda: "")() == "checkBoxEnableTestOrders":
                widget.blockSignals(True)
                try:
                    if isinstance(widget, QCheckBox):
                        widget.setChecked(bool(checked))
                finally:
                    widget.blockSignals(False)

    def _on_toggle_enable_test_orders(self, checked: bool) -> None:
        self._apply_test_orders_enabled_state(bool(checked))

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

    def _on_scenario_changed(self, _index: int) -> None:
        data = self.comboScenario.currentData()
        if data is None:
            return
        self._scenario_id = int(data)
        self._reload_tables()

    def _on_sync_clicked(self) -> None:
        scenario_id = self._scenario_id or ensure_default_test_order_scenario()
        try:
            stats = sync_generated_option_orders()
            generated_df = get_test_orders(asset_rollup=None, scenario_id=None)
            if generated_df is not None and not generated_df.is_empty() and SOURCE_BUCKET_COL in generated_df.columns:
                content_map = get_cached_test_order_scenario_content_map(int(scenario_id))
                enabled_uids = {
                    uid for uid, row in content_map.items()
                    if int(row.get("enabled") or 0) == 1
                }
                generated_df = generated_df.filter(
                    pl.col(SOURCE_BUCKET_COL).cast(pl.Utf8, strict=False).is_in([BUCKET_2, BUCKET_3])
                ).with_columns(
                    pl.col(SCENARIO_ORDER_UID_COL)
                    .cast(pl.Utf8, strict=False)
                    .map_elements(lambda uid: 1 if str(uid or "").strip() in enabled_uids else 0, return_dtype=pl.Int64)
                    .alias("include")
                )
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
            self._persist_current_scenario()
        except Exception as exc:
            QMessageBox.warning(self, "Save mislukt", str(exc))
            return
        self._reload_tables()
        self.labelStatus.setText(f"Scenario {self.comboScenario.currentText()} opgeslagen.")

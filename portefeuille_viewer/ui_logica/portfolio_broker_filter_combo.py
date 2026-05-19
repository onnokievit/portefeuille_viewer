from __future__ import annotations

import polars as pl
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import QComboBox, QLabel, QWidget

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.services.portfolio_broker_filter_state import (
    PORTFOLIO_BROKER_FILTER_STATE,
    normalize_broker,
)


class PortfolioBrokerFilterController:
    def __init__(self, owner: QWidget, combo: QComboBox, label: QLabel | None = None) -> None:
        self.owner = owner
        self.combo = combo
        self.label = label
        self._syncing = False
        self._commit_pending = False
        self.combo.setObjectName("comboBoxBrokerFilter")
        self.combo.setEditable(True)
        if self.combo.lineEdit() is not None:
            self.combo.lineEdit().setReadOnly(True)
        if self.label is not None:
            self.label.setText("Broker:")
        self.combo.view().pressed.connect(self._on_item_pressed)
        self.combo.model().itemChanged.connect(self._on_item_changed)
        PORTFOLIO_BROKER_FILTER_STATE.changed.connect(self._on_shared_state_changed)
        self.refresh_options()
        self._apply_shared_selection()

    def refresh_options(self) -> None:
        brokers = self._available_brokers()
        current = PORTFOLIO_BROKER_FILTER_STATE.selected_set() or set()
        self._syncing = True
        try:
            self.combo.clear()
            all_item = QStandardItem("Alle brokers")
            all_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            all_item.setCheckState(Qt.Checked if not current else Qt.Unchecked)
            self.combo.model().appendRow(all_item)
            for broker in brokers:
                item = QStandardItem(broker)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if normalize_broker(broker) in current else Qt.Unchecked)
                self.combo.model().appendRow(item)
        finally:
            self._syncing = False
        self._ensure_state()
        self._update_text()

    def selected(self) -> list[str]:
        selected: list[str] = []
        model = self.combo.model()
        for row in range(1, model.rowCount()):
            item = model.item(row)
            if item is not None and item.checkState() == Qt.Checked:
                broker = normalize_broker(item.text())
                if broker:
                    selected.append(broker)
        return selected or []

    def _available_brokers(self) -> list[str]:
        configured = [str(v).strip() for v in get_settings().get_brokers() if str(v).strip()]
        found: dict[str, str] = {normalize_broker(v): v for v in configured if normalize_broker(v)}
        for attr in (
            "repository_snapshot_portfolio_value_aandelen",
            "repository_snapshot_portfolio_value_optie",
            "repository_snapshot_portfolio_value_optie_call_put_detailed",
            "repository_snapshot_portfolio_value_sprinters",
            "repository_snapshot_portfolio_value_aandelen_scenario",
            "repository_snapshot_portfolio_value_optie_call_put_detailed_scenario",
            "repository_snapshot_portfolio_value_sprinters_scenario",
        ):
            df = getattr(SNAPSHOT_STORE, attr, None)
            if not isinstance(df, pl.DataFrame) or df.is_empty() or "broker" not in df.columns:
                continue
            for value in df["broker"].to_list():
                text = str(value or "").strip()
                key = normalize_broker(text)
                if key and key not in found:
                    found[key] = text
        return [found[k] for k in sorted(found)]

    def _ensure_state(self) -> None:
        model = self.combo.model()
        if model.rowCount() <= 0:
            return
        checked = [
            row
            for row in range(1, model.rowCount())
            if model.item(row) is not None and model.item(row).checkState() == Qt.Checked
        ]
        all_item = model.item(0)
        if all_item is not None:
            all_item.setCheckState(Qt.Checked if not checked else Qt.Unchecked)

    def _update_text(self) -> None:
        selected = self.selected()
        if not selected:
            text = "Alle brokers"
        elif len(selected) == 1:
            text = selected[0]
        else:
            text = f"{len(selected)} brokers"
        self.combo.setCurrentText(text)

    def _on_item_pressed(self, index) -> None:
        if self._syncing:
            return
        item = self.combo.model().itemFromIndex(index)
        if item is None:
            return
        row = index.row()
        if row == 0:
            new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
            for i in range(self.combo.model().rowCount()):
                child = self.combo.model().item(i)
                if child is not None:
                    child.setCheckState(new_state if i == 0 else Qt.Unchecked)
        else:
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        self._schedule_commit()

    def _on_item_changed(self, _item: QStandardItem) -> None:
        if self._syncing:
            return
        self._schedule_commit()

    def _schedule_commit(self) -> None:
        if self._commit_pending:
            return
        self._commit_pending = True
        QTimer.singleShot(0, self._commit_selection)

    def _commit_selection(self) -> None:
        self._commit_pending = False
        if self._syncing:
            return
        self._syncing = True
        try:
            self._ensure_state()
            self._update_text()
            selected = self.selected()
        finally:
            self._syncing = False
        PORTFOLIO_BROKER_FILTER_STATE.set_selected(selected)

    def _on_shared_state_changed(self, _selected: list[str]) -> None:
        self._apply_shared_selection()
        if hasattr(self.owner, "reload_snapshot"):
            self.owner.reload_snapshot()
        elif hasattr(self.owner, "reload_data"):
            self.owner.reload_data()

    def _apply_shared_selection(self) -> None:
        selected = PORTFOLIO_BROKER_FILTER_STATE.selected_set() or set()
        self._syncing = True
        try:
            model = self.combo.model()
            for row in range(model.rowCount()):
                item = model.item(row)
                if item is None:
                    continue
                if row == 0:
                    item.setCheckState(Qt.Checked if not selected else Qt.Unchecked)
                else:
                    item.setCheckState(Qt.Checked if normalize_broker(item.text()) in selected else Qt.Unchecked)
        finally:
            self._syncing = False
        self._ensure_state()
        self._update_text()

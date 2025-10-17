from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QLabel, QHeaderView, QComboBox, QHBoxLayout
from PySide6.QtCore import Slot, QSortFilterProxyModel, Qt
from portefeuille_viewer.ui.models import PolarsTableModel
import polars as pl
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


class RepositoryAggregatorTesterTab(QWidget):
    """Generic snapshot tester tab.

    Dropdown lists snapshot-like attributes on `SNAPSHOT_STORE`. Selecting one
    displays the Polars DataFrame (read-only) without modification.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        # Top bar: snapshot selector
        topbar = QHBoxLayout()
        self.selector = QComboBox()
        self.selector.addItem("-- Kies snapshot --")
        topbar.addWidget(QLabel("Snapshot:"))
        topbar.addWidget(self.selector)
        layout.addLayout(topbar)

        self.label = QLabel("")
        layout.addWidget(self.label)

        # Table view
        self.table = QTableView()
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setDefaultSectionSize(20)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setStretchLastSection(True)
        layout.addWidget(self.table)

        # Populate selector with snapshot-like attributes
        self._populate_selector()
        self.selector.currentIndexChanged.connect(self._on_selection_changed)

        # Initial blank state
        self._show_placeholder()

    def _populate_selector(self):
        keys = []
        for k, v in vars(SNAPSHOT_STORE).items():
            if k.startswith('_'):
                continue
            if v is None or isinstance(v, pl.DataFrame):
                keys.append(k)
        keys.sort()
        for k in keys:
            self.selector.addItem(k)

    @Slot(int)
    def _on_selection_changed(self, index: int):
        if index <= 0:
            self._show_placeholder()
            return
        key = self.selector.itemText(index)
        self._display_snapshot_key(key)

    def _show_placeholder(self):
        self.label.setText("Kies een snapshot uit de dropdown om de data te tonen.")
        df = pl.DataFrame({})
        self._set_table_model(df)

    def _display_snapshot_key(self, key: str):
        df = getattr(SNAPSHOT_STORE, key, None)
        if df is None:
            self.label.setText(f"Snapshot '{key}' is leeg of niet geladen.")
            df = pl.DataFrame({})
        else:
            try:
                nr = len(df)
            except Exception:
                nr = None
            self.label.setText(f"Snapshot '{key}': {nr if nr is not None else '?'} regels")

        self._set_table_model(df)

    def _set_table_model(self, df: pl.DataFrame):
        if df is None:
            df = pl.DataFrame({})
        self.model = PolarsTableModel(df, self)
        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setSortRole(Qt.UserRole)
        self.table.setModel(self.proxy_model)


from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Slot, QSortFilterProxyModel, Qt
from portefeuille_viewer.ui.repository_tester_ui import Ui_Form
from portefeuille_viewer.ui.models import PolarsTableModel
import polars as pl
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE

class RepositoryTesterTab(QWidget):
    """
    Snapshot tester tab gekoppeld aan repository_tester_ui.py
    Dropdown toont snapshots uit SNAPSHOT_STORE, selectie toont DataFrame in tableview.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_Form()
        self.ui.setupUi(self)

        # Populate combobox
        self._populate_selector()
        self.ui.comboBox.currentIndexChanged.connect(self._on_selection_changed)
        self._show_placeholder()

    def _populate_selector(self):
        self.ui.comboBox.clear()
        self.ui.comboBox.addItem("-- Kies snapshot --")
        keys = []
        for k, v in vars(SNAPSHOT_STORE).items():
            if k.startswith('_'):
                continue
            if v is None or isinstance(v, pl.DataFrame):
                keys.append(k)
        keys.sort()
        for k in keys:
            self.ui.comboBox.addItem(k)

    @Slot(int)
    def _on_selection_changed(self, index):
        if index <= 0:
            self._show_placeholder()
            return
        key = self.ui.comboBox.itemText(index)
        self._display_snapshot_key(key)

    def _show_placeholder(self):
        # Optioneel: label toevoegen in UI voor status
        df = pl.DataFrame({})
        self._set_table_model(df)

    def _display_snapshot_key(self, key):
        df = getattr(SNAPSHOT_STORE, key, None)
        if df is not None and isinstance(df, dict) and df:
            first_key = next(iter(df.keys()))
            if isinstance(first_key, tuple):
                colnames = [f"key_{i+1}" for i in range(len(first_key))]
                rows = [dict(zip(colnames, k), value=v) for k, v in df.items()]
                df = pl.DataFrame(rows)
            else:
                df = pl.DataFrame([{"key": k, "value": v} for k, v in df.items()])
        elif df is not None and isinstance(df, dict) or df is None:
            df = pl.DataFrame({})
        self._set_table_model(df)

    def _set_table_model(self, df):
        if df is None:
            df = pl.DataFrame({})
        self.model = PolarsTableModel(df, self)
        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setSortRole(Qt.UserRole)
        self.ui.tableView.setModel(self.proxy_model)

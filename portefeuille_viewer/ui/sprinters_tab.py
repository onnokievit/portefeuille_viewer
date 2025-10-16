from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableView, QHeaderView
from PySide6.QtCore import QAbstractTableModel, Qt, Slot
import polars as pl
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE

class SprintersTableModel(QAbstractTableModel):
    def __init__(self, df: pl.DataFrame = None):
        super().__init__()
        self.set_dataframe(df)

    def set_dataframe(self, df: pl.DataFrame):
        self._df = df if df is not None else pl.DataFrame()
        self._columns = self._df.columns if not self._df.is_empty() else []
        self.layoutChanged.emit()

    def rowCount(self, parent=None):
        return 0 if self._df is None else self._df.height

    def columnCount(self, parent=None):
        return 0 if self._df is None else len(self._columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole or self._df is None:
            return None
        value = self._df.item(index.row(), index.column())
        return str(value)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and self._columns:
            return self._columns[section]
        return str(section)

class SprintersTab(QWidget):
    def __init__(self, portfolio_engine=None, parent=None):
        super().__init__(parent)
        self.portfolio_engine = portfolio_engine
        self.setWindowTitle("Sprinters (Live)")
        self.layout = QVBoxLayout(self)
        self.label = QLabel("Live Sprinters Data")
        self.layout.addWidget(self.label)
        self.table = QTableView()
        self.layout.addWidget(self.table)
        self.model = SprintersTableModel()
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._connect_signals()
        self._refresh_table()

    def _connect_signals(self):
        # Verbind met de sprintersUpdated signal van de aggregator uit de portfolio_engine
        if self.portfolio_engine and hasattr(self.portfolio_engine, 'live_aggregator_sprinters'):
            self.portfolio_engine.live_aggregator_sprinters.sprintersUpdated.connect(self._refresh_table)

    @Slot()
    def _refresh_table(self):
        df = SNAPSHOT_STORE.aggregator_snapshot_open_sprinters_live
        self.model.set_dataframe(df)

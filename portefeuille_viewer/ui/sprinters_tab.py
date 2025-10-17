from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QLabel, QHeaderView
from PySide6.QtCore import Slot, QSortFilterProxyModel, Qt
from portefeuille_viewer.ui.models import PolarsTableModel
import polars as pl
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE

class SprintersTab(QWidget):
    def __init__(self, portfolio_engine=None, parent=None):
        super().__init__(parent)
        self.portfolio_engine = portfolio_engine
        self.current_sort_column = -1
        self.current_sort_order = 0

        layout = QVBoxLayout(self)
        self.label = QLabel("Loading...")
        layout.addWidget(self.label)

        self.table = QTableView()
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setDefaultSectionSize(20)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setStretchLastSection(True)
        layout.addWidget(self.table)

        if self.portfolio_engine and hasattr(self.portfolio_engine, 'live_aggregator_sprinters'):
            self.portfolio_engine.live_aggregator_sprinters.sprintersUpdated.connect(self.on_sprinters_update)

        self.reload_data()

    @Slot()
    def on_sprinters_update(self):
        if hasattr(self, 'table') and self.table.model() is not None:
            header = self.table.horizontalHeader()
            self.current_sort_column = header.sortIndicatorSection()
            self.current_sort_order = header.sortIndicatorOrder()
        self.reload_data()

    def reload_data(self):
        df = SNAPSHOT_STORE.aggregator_snapshot_open_sprinters_live
        # Bepaal database-naam indien mogelijk
        try:
            import importlib
            repository = importlib.import_module('portefeuille_viewer.data.repository')
            # Haal de actuele database-naam uit repository.db_path (pad), zoek de key in DB_MAP
            db_path = getattr(repository, 'db_path', None)
            db_map = getattr(repository, 'DB_MAP', {})
            db_name = None
            for name, path in db_map.items():
                if path == db_path:
                    db_name = name
                    break
            if not db_name:
                db_name = "(onbekend)"
        except Exception:
            db_name = "(onbekend)"

        # Bepaal kolommen voor lege tabel (indien geen data)
        default_columns = [
            "broker", "asset_rollup", "asset_detail", "Koers", "sprinter_funding", "sprinter_ratio", "SomVantransactie_aantal", "SomVantransactie_euro_totaal", "winst"
        ]

        if df is None or df.is_empty():
            # Toon altijd een lege tabel met kolommen
            df = pl.DataFrame({col: [] for col in default_columns})
            self.label.setText(f"DATABASE {db_name} heeft geen sprinter transacties.")
        else:
            self.label.setText(f"{len(df)} open sprinters geladen uit database {db_name}")

        self.model = PolarsTableModel(df, self)
        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setSortRole(Qt.UserRole)
        self.table.setModel(self.proxy_model)

        if self.current_sort_column >= 0:
            self.table.sortByColumn(self.current_sort_column, self.current_sort_order)

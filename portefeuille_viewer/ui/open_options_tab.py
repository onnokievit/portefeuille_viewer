# ----------------------------------------------------
# portefeuille_viewer/ui/open_opties_polars_tab.py
# -----------------------------------------------------
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QLabel, QHeaderView
from PySide6.QtCore import Slot
from portefeuille_viewer.data import repository
from portefeuille_viewer.ui.models import PolarsTableModel
import polars as pl
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE 

class OpenOptiesPolarsTab(QWidget):
    """
    Tabblad dat open opties toont met live prijzen.
    Leest uit snapshot_load_open_opties_from_tx_live (gevuld door LiveAggregatorOpties).
    """
    def __init__(self, portfolio_engine=None, parent=None):
        super().__init__(parent)
        self.portfolio_engine = portfolio_engine
        
        layout = QVBoxLayout(self)

        # Label voor aantal rijen
        self.label = QLabel("Loading...")
        layout.addWidget(self.label)

        # Tabel bouwen
        self.table = QTableView()
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        
        # Row height instellen op 20px
        self.table.verticalHeader().setDefaultSectionSize(20)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setStretchLastSection(True)

        layout.addWidget(self.table)
        
        # Connect to portfolio engine signals if available
        if self.portfolio_engine and hasattr(self.portfolio_engine, 'live_aggregator_opties'):
            self.portfolio_engine.live_aggregator_opties.optiesUpdated.connect(self.on_opties_update)
        
        # Initial data load
        self.reload_data()
    
    @Slot()
    def on_opties_update(self):
        """Handle opties update signal from LiveAggregatorOpties."""
        self.reload_data()
    
    def reload_data(self):
        """Reload data from SnapshotStore."""
        # Haal data uit de live snapshot (gevuld door LiveAggregatorOpties)
        df = SNAPSHOT_STORE.snapshot_load_open_opties_from_tx_live
        
        if df is None or df.is_empty():
            df = pl.DataFrame()
            self.label.setText("Geen opties data beschikbaar (wacht op live prices)")
        else:
            self.label.setText(f"{len(df)} open opties geladen")
        
        # Update model
        self.model = PolarsTableModel(df, self)
        self.table.setModel(self.model)


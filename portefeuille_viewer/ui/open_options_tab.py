# ----------------------------------------------------
# portefeuille_viewer/ui/open_opties_polars_tab.py
# -----------------------------------------------------
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QLabel, QHeaderView
from portefeuille_viewer.data import repository
from portefeuille_viewer.ui.models import PolarsTableModel
import polars as pl
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE 

class OpenOptiesPolarsTab(QWidget):
    """
    Tabblad dat de eerste 50 regels van load_open_opties_from_tx toont (Polars versie).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        # Data laden
        df = SNAPSHOT_STORE.snapshot_load_open_opties_from_tx
        #df = df.head(50) if not df.is_empty() else pl.DataFrame()

        # Model aanmaken
        self.model = PolarsTableModel(df, self)

        # Tabel bouwen
        table = QTableView()
        table.setModel(self.model)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)

        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setStretchLastSection(True)

        layout.addWidget(QLabel(f"{len(df)} regels geladen (eerste 50 getoond)"))
        layout.addWidget(table)

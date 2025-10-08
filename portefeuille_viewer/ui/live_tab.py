import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableView, QHeaderView

from portefeuille_viewer.ui.models import WidePerAssetModel, MultiColFilterProxy

class LiveViewTab(QWidget):
    """
    Tabblad dat een blanco tabel toont.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        # UI setup
        v = QVBoxLayout(self)

        # Leeg model initialiseren
        empty_df = pd.DataFrame(columns=WidePerAssetModel.COLS)
        self.model = WidePerAssetModel(empty_df, self)
        self.proxy = MultiColFilterProxy(self.model.COLS, self)
        self.proxy.setSourceModel(self.model)

        # Tabel instellen
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setStyleSheet("""
        QTableView::item:hover { background-color: #E6F2FF; }
        QTableView::item:selected { background-color: #FFF2CC; color: #000; }
        QTableView::item:selected:hover { background-color: #FFE08A; }
        QTableView::item:selected:!active { background-color: #FFF8D6; }
        """)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setStretchLastSection(False)

        v.addWidget(self.table)

        # Label met totaal (optioneel, kan verwijderd worden)
        self.lbl_total = QLabel("Totale waarde: 0,00")
        f = self.lbl_total.font()
        f.setPointSize(12)
        f.setBold(True)
        self.lbl_total.setFont(f)
        v.addWidget(self.lbl_total)
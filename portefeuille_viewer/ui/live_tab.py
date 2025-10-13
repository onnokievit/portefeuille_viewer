from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QHeaderView, QLabel

from portefeuille_viewer.ui.models import PolarsTableModel, MultiColFilterProxy
import polars as pl


class LiveViewTab(QWidget):
    """
    Minimalistische LiveViewTab — klaar voor Polars dataset.
    Toont een lege tabel, met filtering en sortering via MultiColFilterProxy.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        # Layout
        layout = QVBoxLayout(self)

        # Initieel leeg Polars DataFrame
        empty_df = pl.DataFrame(schema={
            "Asset": pl.Utf8,
            "Koers": pl.Float32,
            "Waarde_eq": pl.Float32,
            "Totaal_portefeuille": pl.Float32
        })

        # Model en proxy
        self.model = PolarsTableModel(empty_df, self)
        self.proxy = MultiColFilterProxy(self.model._cols, self)
        self.proxy.setSourceModel(self.model)

        # Tabel
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)

        # Header-instellingen
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setStretchLastSection(True)

        # Stijl
        self.table.setStyleSheet("""
        QTableView::item:hover { background-color: #E6F2FF; }
        QTableView::item:selected { background-color: #FFF2CC; color: #000; }
        """)

        layout.addWidget(self.table)

        # Optioneel label onderaan voor totalen
        self.lbl_total = QLabel("Totale waarde: 0,00")
        f = self.lbl_total.font()
        f.setPointSize(12)
        f.setBold(True)
        self.lbl_total.setFont(f)
        layout.addWidget(self.lbl_total)

    # --------------------------------------------------------
    # Data update (wordt later door engine aangeroepen)
    # --------------------------------------------------------
    def set_data(self, df: pl.DataFrame):
        """Krijgt een Polars DataFrame van portfolio_engine en toont dit."""
        self.model.set_df(df)
        try:
            total = df["Totaal_portefeuille"].sum()
            self.lbl_total.setText(f"Totale waarde: {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        except Exception:
            self.lbl_total.setText("Totale waarde: -")

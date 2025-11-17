from PySide6.QtWidgets import QWidget
from portefeuille_viewer.ui.opties_open_ui import Ui_Form
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.ui.models import PolarsTableModel
from PySide6.QtCore import QSortFilterProxyModel, Qt, Slot

import polars as pl
from PySide6.QtGui import QColor

from PySide6.QtGui import QColor
from portefeuille_viewer.ui.models import PolarsTableModel
from PySide6.QtCore import Qt

class OptiesOpenTableModel(PolarsTableModel):
    def data(self, index, role=Qt.DisplayRole):
        # Gebruik originele formattering voor DisplayRole
        if role == Qt.DisplayRole:
            return super().data(index, role)

        row = self._df.row(index.row())
        columns = self._df.columns
        colname = columns[index.column()]

        kleur_kolommen = ["broker", "asset_rollup", "optie_call_put", "optie_strike", "optie_exp_date"]

        if role == Qt.BackgroundRole:
            try:
                optie_call_put = row[columns.index("optie_call_put")]
                itm_otm = row[columns.index("itm_otm")]
                if colname in kleur_kolommen and itm_otm != 0:
                    if optie_call_put == "put":
                        return QColor(255, 200, 200)  # lichtrood
                    elif optie_call_put == "call":
                        return QColor(200, 255, 200)  # lichtgroen
            except Exception:
                pass
        return super().data(index, role)
    
class OptiesOpenTab(QWidget, Ui_Form):
    """
    Tabblad dat open opties toont met live prijzen.
    Leest uit aggregator_snapshot_load_open_opties_from_tx_live (gevuld door LiveAggregatorOpties).
    """
    def __init__(self, portfolio_engine=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.tableView.verticalHeader().setDefaultSectionSize(18) 
        self.portfolio_engine = portfolio_engine
        self.current_sort_column = -1
        self.current_sort_order = 0
        # Gebruik de juiste TableView uit de UI
        self.table = self.tableView
        # self.label = self.labelOpties  # Alleen als je een label toevoegt aan de UI
        if self.portfolio_engine and hasattr(self.portfolio_engine, 'live_aggregator_opties'):
            self.portfolio_engine.live_aggregator_opties.optiesUpdated.connect(self.on_opties_update)
        self.reload_data()

    @Slot()
    def on_opties_update(self):
        if hasattr(self, 'table') and self.table.model() is not None:
            header = self.table.horizontalHeader()
            self.current_sort_column = header.sortIndicatorSection()
            self.current_sort_order = header.sortIndicatorOrder()
        self.reload_data()

    def reload_data(self):
        df = SNAPSHOT_STORE.aggregator_snapshot_load_open_opties_from_tx_live
        df = df.select([
            "broker",
            "asset_rollup",
            "Koers",
            pl.col("optie_call_put").alias("optie_call_put"),
            pl.col("optie_strike").alias("optie_strike"),
            pl.col("optie_exp_date").alias("optie_exp_date"),
            pl.col("SomVantransactie_aantal").alias("aantal_bezit"),
            pl.col("SomVantransactie_euro_totaal").alias("premie"),
            pl.col("ITM_OTM").alias("itm_otm"),
            pl.col("opt_total_result").alias("totaal_resultaat_optie"),
            pl.col("SomVantransactie_fee").alias("totaal_fees"),
        ])
        if df is None or df.is_empty():
            df = pl.DataFrame()
            # self.label.setText("Geen opties data beschikbaar (wacht op live prices)")
        #self.model = PolarsTableModel(df, self)
        self.model = OptiesOpenTableModel(df, self)
        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setSortRole(Qt.UserRole)
        self.table.setModel(self.proxy_model)
        if self.current_sort_column >= 0:
            self.table.sortByColumn(self.current_sort_column, self.current_sort_order)

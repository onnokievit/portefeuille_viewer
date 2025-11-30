
import polars as pl

from PySide6.QtCore import QSortFilterProxyModel, Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget


from portefeuille_viewer.ui.models import PolarsTableModel
from portefeuille_viewer.ui.opties_open_ui import Ui_Form
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.ui.filter_popup import HeaderFilterMenuMixin


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
    
class OptiesOpenTab(QWidget, Ui_Form, HeaderFilterMenuMixin):
    """
    Tabblad dat open opties toont met live prijzen.
    Leest uit aggregator_snapshot_load_open_opties_from_tx_live (gevuld door LiveAggregatorOpties).
    """
    def __init__(self, portfolio_engine=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        # self.tableView = self.table  # of self.tableView als dat je QTableView is
        self._table_model = None  # na reload_data()
        self._col_filters = {}
        self.tableView.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableView.horizontalHeader().customContextMenuRequested.connect(self.on_header_menu)
        self.tableView.verticalHeader().setDefaultSectionSize(18) 
        self.portfolio_engine = portfolio_engine
        self.current_sort_column = -1
        self.current_sort_order = 0
        # Gebruik de juiste TableView uit de UI
        self.table = self.tableView
        self.buttonClearFilters.clicked.connect(self._on_clear_filters)
        self.lineEditFilter.returnPressed.connect(self.apply_filters)
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

    def apply_filters(self):
        # print("apply_filters aangeroepen, tekst:", self.lineEditFilter.text())
        q = self.lineEditFilter.text().strip()
        filters = {"q": q} if q else {}

        # kolomfilters omzetten naar generieke repo keys
        for col, spec in (self._col_filters or {}).items():
            if "in" in spec:
                filters[f"__in__{col}"] = list(spec["in"])
            if "contains" in spec:
                filters[f"__contains__{col}"] = spec["contains"]
            if "eq" in spec:
                filters[f"__eq__{col}"] = spec["eq"]
            if "date_on" in spec and spec["date_on"]:
                filters[f"__date_on__{col}"] = spec["date_on"]

        self.active_filters = filters
        # print("Filters dict:", filters)
        self._reset_seek()
        self._load_initial_records()

    def _load_initial_records(self):
        self.reload_data()

    def _reset_seek(self):
        pass

    def reload_data(self):
        df = SNAPSHOT_STORE.aggregator_snapshot_load_open_opties_from_tx_live
        if "ITM_OTM" in df.columns:
            df = df.with_columns(
                pl.when(pl.col("ITM_OTM") != 0)
                    .then(pl.lit("ITM"))
                    .otherwise(pl.lit("OTM"))
                    .alias("itm")
            )
        df = df.select([
            "broker",
            "asset_rollup",
            
            pl.col("optie_call_put").alias("optie_call_put"),
            pl.col("optie_strike").alias("optie_strike"),
            pl.col("optie_exp_date").alias("optie_exp_date"),
            pl.col("SomVantransactie_aantal").alias("aantal_bezit"),
            pl.col("SomVantransactie_euro_totaal").alias("premie"),
            "Koers",
            pl.col("ITM_OTM").alias("itm_otm"),
            pl.col("opt_total_result").alias("totaal_resultaat_optie"),
            pl.col("SomVantransactie_fee").alias("totaal_fees"),
            pl.col("itm").alias("itm")
        ])
        # Voeg berekende kolom toe: % afwijking koers t.o.v. strike (absoluut)
        if "Koers" in df.columns and "optie_strike" in df.columns:
            df = df.with_columns(
                ( (pl.col("Koers") - pl.col("optie_strike")).abs() / pl.col("optie_strike") * 100 ).alias("afwijking_pct")
            )

        filters = getattr(self, "active_filters", {})
        if filters:
            for key, value in filters.items():
                if key.startswith("__in__"):
                    col = key.replace("__in__", "")
                    df = df.filter(pl.col(col).is_in(value))
                elif key.startswith("__contains__"):
                    col = key.replace("__contains__", "")
                    df = df.filter(pl.col(col).cast(str).str.contains(value))
                elif key.startswith("__eq__"):
                    col = key.replace("__eq__", "")
                    df = df.filter(pl.col(col) == value)
                elif key.startswith("__date_on__"):
                    col = key.replace("__date_on__", "")
                    df = df.filter(pl.col(col) == value)

                elif key == "q":
                    # Meerdere zoektermen (AND), gescheiden door komma
                    terms = [t.strip() for t in value.split(",") if t.strip()]
                    for term in terms:
                        mask = None
                        # Maak varianten van de zoekterm met en zonder voorloopnullen
                        import re
                        def pad_zero(s):
                            parts = re.split(r'[-/]', s)
                            return [
                                s,
                                '-'.join(f"{int(p):02d}" if p.isdigit() else p for p in parts),
                                '/'.join(f"{int(p):02d}" if p.isdigit() else p for p in parts)
                            ]
                        term_variants = set()
                        for t in pad_zero(term):
                            term_variants.add(t)
                        for c in df.columns:
                            dtype = df[c].dtype
                            if isinstance(dtype, pl.Date) or isinstance(dtype, pl.Datetime):
                                m = None
                                for v in term_variants:
                                    m1 = df[c].dt.strftime("%d-%m-%Y").str.contains(v.replace("/", "-"))
                                    m2 = df[c].dt.strftime("%d/%m/%Y").str.contains(v.replace("-", "/"))
                                    m3 = df[c].dt.strftime("%d-%m").str.contains(v.replace("/", "-"))
                                    m4 = df[c].dt.strftime("%d/%m").str.contains(v.replace("-", "/"))
                                    m = m1 | m2 | m3 | m4 if m is None else (m | m1 | m2 | m3 | m4)
                                # combineer alle varianten
                            else:
                                m = pl.col(c).cast(str).str.to_lowercase().str.contains(term.lower())
                            mask = m if mask is None else (mask | m)
                        df = df.filter(mask)

        if df is None or df.is_empty():
            df = pl.DataFrame()
            
        
        self.model = OptiesOpenTableModel(df, self)
        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setSortRole(Qt.UserRole)
        self.tableView.setModel(self.proxy_model)
        self._table_model = self.model  # update voor de mixin
        self.table.setModel(self.proxy_model)
        if self.current_sort_column >= 0:
            self.tableView.sortByColumn(self.current_sort_column, self.current_sort_order)

    def _apply_in_filter(self, colname, selected):
        if not selected:
            self._col_filters.pop(colname, None)
        else:
            self._col_filters[colname] = {"in": selected}
        self.apply_filters()  # ipv self._load_initial_records()

    def _on_clear_filters(self):
        self._col_filters.clear()
        self._text_filter = ""
        self.lineEditFilter.clear()
        self.apply_filters()
        self._reset_seek()
        self._load_initial_records()


import contextlib
import polars as pl
import pyqtgraph as pg
from streamlit import header

from PySide6.QtWidgets import QWidget, QTableWidgetItem,QHeaderView
from PySide6.QtGui import QFont, QColor
from PySide6.QtCore import QLocale, QDate, Slot, QSortFilterProxyModel, Qt

from portefeuille_viewer.ui.models import ColoredPolarsTableModel  
from portefeuille_viewer.ui.single_asset_analyse_tab_ui import Ui_SingleAssetAnalyseTab
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.services.single_asset_scenario_analyse import (
    bereken_open_opties_payoff,
    bereken_open_sprinters_payoff,
    bereken_gesloten_aandelen_payoff,
    bereken_open_aandelen_payoff,
)

# Widget-class die UI en logica koppelt
class SingleAssetAnalyseTab(QWidget, Ui_SingleAssetAnalyseTab):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        settings = get_settings()
        start_date_str = settings.config.get('app', 'single_asset_analyse_start_date', fallback=None)
        if start_date_str:
            self.startDate.setDate(QDate.fromString(start_date_str, 'yyyy-MM-dd'))
        self.endDate.setDate(QDate.currentDate())

        # self.gridLayout_2.setColumnStretch(0, 10)
        # self.gridLayout_2.setColumnStretch(1, 6)
        self.active_filters_opties_open = {}
        self.payoff_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        
        self.stepSizeBox.setLocale(QLocale(QLocale.C))

        
        font = QFont("Arial", 8)  # Kies je gewenste lettertype en grootte
        self.payoff_table.setFont(font)        
                
        self.logic = SingleAssetAnalyseLogic()
        self.update_opties_open_table()
        
        self.asset_selector.addItems(self.logic.load_assets())
        
        self.asset_selector.currentTextChanged.connect(self.on_asset_selected)
        self.endDate.setDate(QDate.currentDate())

        self.startDate.dateChanged.connect(self.update_history_charts)
        self.startDate.dateChanged.connect(self.save_start_date_to_settings)
        self.endDate.dateChanged.connect(self.update_history_charts)

        # Initialiseer pyqtgraph plot_widget
        self.plot_widget = pg.PlotWidget()
        self.layoutChart.addWidget(self.plot_widget)
        # PYQTGRAPH: alle margins uit
        self.plot_widget.setContentsMargins(0, 0, 0, 0)
        self.plot_widget.plotItem.setContentsMargins(0, 0, 0, 0)
        self.plot_widget.plotItem.layout.setContentsMargins(0, 0, 0, 0)

        # Geen assen nodig voor Excel-uiting
        
        self.plot_widget.showAxis('right', False)
        self.plot_widget.showAxis('top', False)
        self.plot_widget.showAxis('bottom', True)

        # Synchroniseer grafiek als kolom 0 resized wordt
        self.payoff_table.horizontalHeader().sectionResized.connect(self.sync_plot_with_table)
        # Tooltip/annotatie voor mouseover
        self._mpl_annotation = None
        # self._mpl_hover_cid = self.canvas.mpl_connect('motion_notify_event', self._on_mpl_hover)
        self._mpl_last_lines = []
        self._mpl_x_mapping = []  # mapping van x_scaled naar koerswaarde



        # Initialiseer payoff_table
        self.payoff_table.setColumnCount(17)
        self.payoff_table.setRowCount(10)
        self.stepSizeBox.valueChanged.connect(self.update_payoff_table)
                # Maak de rijhoogte compacter
        assets = self.logic.load_assets()
        self.asset_selector.addItems(assets)
        if assets:
            self.asset_selector.setCurrentIndex(0)
            self.on_asset_selected(assets[0])
        for row in range(10):
            self.payoff_table.setRowHeight(row, 11)  # pas 22 aan voor nog compacter/ruimer
        # Je kunt hier headers en andere init doen zoals in je oude code
        self.lineEditFilterOptiesOpen.returnPressed.connect(self.apply_filters_opties_open)
        self.tableViewOptiesOpen.clicked.connect(self._on_table_cell_clicked)

    @Slot()
    def save_start_date_to_settings(self):
        settings = get_settings()
        date_str = self.startDate.date().toString('yyyy-MM-dd')
        if not settings.config.has_section('app'):
            settings.config.add_section('app')
        settings.config.set('app', 'single_asset_analyse_start_date', date_str)
        settings.save()


    def _filter_dataframe(self, df, filters):
        import re
        import polars as pl
        for key, value in filters.items():
            if key.startswith("__in__"):
                col = key.replace("__in__", "")
                df = df.filter(pl.col(col).is_in(value))
            elif key.startswith("__contains__"):
                col = key.replace("__contains__","")
                df = df.filter(pl.col(col).cast(str).str.contains(value))
            elif key.startswith("__eq__"):
                col = key.replace("__eq__","")
                df = df.filter(pl.col(col) == value)
            elif key.startswith("__date_on__"):
                col = key.replace("__date_on__","")
                df = df.filter(pl.col(col) == value)
            elif key == "q":
                terms = [t.strip() for t in value.split(",") if t.strip()]
                for term in terms:
                    mask = None
                    def pad_zero(s):
                        parts = re.split(r'[-/]', s)
                        return [
                            s,
                            '-'.join(f"{int(p):02d}" if p.isdigit() else p for p in parts),
                            '/'.join(f"{int(p):02d}" if p.isdigit() else p for p in parts)
                        ]
                    term_variants = set(pad_zero(term))
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
                        else:
                            m = pl.col(c).cast(str).str.to_lowercase().str.contains(term.lower())
                        mask = m if mask is None else (mask | m)
                    df = df.filter(mask)
        return df
    
    def _on_table_cell_clicked(self, index):
        #print("Clicked index:", index, "Model:", index.model(), "Current model:", self.tableViewOptiesOpen.model())
        try:
            model = self.tableViewOptiesOpen.model()
            if not index.isValid():
                return
            # Check of index.model() gelijk is aan het huidige model
            if index.model() is not model:
                return
            if isinstance(model, QSortFilterProxyModel):
                source_index = model.mapToSource(index)
                if not source_index.isValid():
                    return
                source_model = model.sourceModel()
                colname = source_model.headerData(source_index.column(), Qt.Horizontal)
                value = source_model.data(source_index, Qt.DisplayRole)
            else:
                colname = model.headerData(index.column(), Qt.Horizontal)
                value = model.data(index, Qt.DisplayRole)
            if colname == "asset_rollup":
                idx = self.asset_selector.findText(value)
                if idx >= 0:
                    self.asset_selector.setCurrentIndex(idx)
        except Exception:
            # Onderdruk Qt warning
            pass

    def update_opties_open_table(self):
        df = self.logic.load_option_open_data()
        asset = self.asset_selector.currentText()
        # Voor de eerste tabel géén asset-filtering, volledige tabel tonen
        df_all = df.drop("totaal_fees")
        df_all = df_all.sort(["optie_exp_date", "asset_rollup"])
        if hasattr(self, "active_filters_opties_open") and self.active_filters_opties_open:
            df_all = self._filter_dataframe(df_all, self.active_filters_opties_open)
        # Voor put/call tabellen wél filteren
        df_put = df.filter(pl.col("asset_rollup") == asset).filter(pl.col("optie_call_put") == "put").drop("totaal_fees")
        df_put = df_put.sort("optie_exp_date")
        df_call = df.filter(pl.col("asset_rollup") == asset).filter(pl.col("optie_call_put") == "call").drop("totaal_fees")
        df_call = df_call.sort("optie_exp_date")

        kleur_kolommen = ["broker", "asset_rollup", "optie_call_put", "optie_strike", "optie_exp_date"]
        columns = df.columns
        def kleur_func(row, colname, kleur_kolommen):
            return self.opties_kleur_func(row, colname, kleur_kolommen, columns)

        font = QFont("Arial", 8)
        kolombreedtes = {
            "broker": 65,
            "asset_rollup": 75,
            "Koers": 50,
            "optie_call_put": 40,
            "optie_strike": 50,
            "optie_exp_date": 80,
            "aantal_bezit": 60,
            "premie": 60,
            "itm_otm": 60,
            "totaal_resultaat_optie": 60,
            "itm": 35,
            "afwijking_pct": 45,
        }

        # Alle opties (volledige tabel, geen asset-filter)
        model_all = ColoredPolarsTableModel(df_all, kleur_kolommen, kleur_func, self)

        proxy_model = QSortFilterProxyModel(self)
        proxy_model.setSourceModel(model_all)
        proxy_model.setSortRole(Qt.UserRole)
        #print("Disconnecting click handler, replacing model")
        self.tableViewOptiesOpen.clicked.disconnect(self._on_table_cell_clicked)
        self.tableViewOptiesOpen.setModel(proxy_model)
        self.tableViewOptiesOpen.setSortingEnabled(True)
        self.tableViewOptiesOpen.clicked.connect(self._on_table_cell_clicked)
        # print("Model replaced, click handler reconnected")

        self.tableViewOptiesOpen.setFont(font)
        self.tableViewOptiesOpen.setStyleSheet("""
        QScrollBar:vertical {
            width: 25px;
        }
        QScrollBar::handle:vertical {
            background: #e0e0e0;
            min-height: 20px;
        }
        QScrollBar::handle:vertical:hover {
            background: #b0b0b0;
        }
        QScrollBar:vertical {
            width: 18px;
        }
        QScrollBar::groove:vertical {
            background: #f0f0f0;
            width: 18px;
            border-radius: 18px;
        }
        """)
        #self.tableViewOptiesOpen.setStyleSheet("QScrollBar:vertical { width: 18px; }")
        header_all = self.tableViewOptiesOpen.horizontalHeader()
        header_all.setSectionResizeMode(QHeaderView.Interactive)
        def apply_widths_all():
            for i, col in enumerate(df_all.columns):
                if col in kolombreedtes:
                    header_all.resizeSection(i, kolombreedtes[col])
        model_all.modelReset.connect(apply_widths_all)
        model_all.layoutChanged.connect(apply_widths_all)
        apply_widths_all()
        self.tableViewOptiesOpen.verticalHeader().setDefaultSectionSize(10)

        # Put opties (wel asset-filter)
        model_put = ColoredPolarsTableModel(df_put, kleur_kolommen, kleur_func, self)
        self.tableViewOptiesOpenPut.setModel(model_put)
        self.tableViewOptiesOpenPut.setFont(font)
        self.tableViewOptiesOpenPut.setStyleSheet("QScrollBar:vertical { width: 14px; }")
        header_put = self.tableViewOptiesOpenPut.horizontalHeader()
        header_put.setSectionResizeMode(QHeaderView.Interactive)
        def apply_widths_put():
            for i, col in enumerate(df_put.columns):
                if col in kolombreedtes:
                    header_put.resizeSection(i, kolombreedtes[col])
        model_put.modelReset.connect(apply_widths_put)
        model_put.layoutChanged.connect(apply_widths_put)
        apply_widths_put()
        self.tableViewOptiesOpenPut.verticalHeader().setDefaultSectionSize(10)

        # Call opties (wel asset-filter)
        model_call = ColoredPolarsTableModel(df_call, kleur_kolommen, kleur_func, self)
        self.tableViewOptiesOpenCall.setModel(model_call)
        self.tableViewOptiesOpenCall.setFont(font)
        self.tableViewOptiesOpenCall.setStyleSheet("QScrollBar:vertical { width: 18px; }")
        header_call = self.tableViewOptiesOpenCall.horizontalHeader()
        header_call.setSectionResizeMode(QHeaderView.Interactive)
        def apply_widths_call():
            for i, col in enumerate(df_call.columns):
                if col in kolombreedtes:
                    header_call.resizeSection(i, kolombreedtes[col])
        model_call.modelReset.connect(apply_widths_call)
        model_call.layoutChanged.connect(apply_widths_call)
        apply_widths_call()
        self.tableViewOptiesOpenCall.verticalHeader().setDefaultSectionSize(10)
        

    def on_asset_selected(self, asset_rollup):
        self.logic.set_asset(asset_rollup)
        self.update_payoff_table()
        self.update_history_charts()
        self.update_opties_open_table()

    def update_history_charts(self):
        df = self.logic.load_asset_history(
            self.asset_selector.currentText(),
            self.startDate.date(),
            self.endDate.date()
        )
        if df.height == 0:
            self.priceAantalChart.clear()
            self.resultaatChart.clear()
            return
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        # # from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE # sourcery skip
        # SNAPSHOT_STORE.test_repository_load_output_test_dataframe = df  # sourcery skip # of df_sum als je de gesumde versie wilt zien
        # # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        import numpy as np
        x = np.arange(len(df))
        datums = df["datum"].to_list()
        close_price = [float(v) if v is not None and v != '' else 0.0 for v in df["close_price"].to_list()]
        aantal = [float(v) if v is not None and v != '' else 0.0 for v in df["totaal_aantal_bezit"].to_list()]
        totaal = [float(v) if v is not None and v != '' else 0.0 for v in df["totaal"].to_list()]

        # --- Chart 1: priceAantalChart (zoals eerder) ---
        pw = self.priceAantalChart
        pw.clear()
        pw.plotItem.clear()
        pw.plot(x, close_price, pen='b', name="Koers")
        if not hasattr(self, '_rightView'):
            self._rightView = pg.ViewBox()
            pw.plotItem.showAxis('right')
            pw.plotItem.scene().addItem(self._rightView)
            pw.plotItem.getAxis('right').linkToView(self._rightView)
            self._rightView.setXLink(pw.plotItem)
        self._rightView.setGeometry(pw.plotItem.vb.sceneBoundingRect())
        pw.plotItem.vb.sigResized.connect(lambda: self._rightView.setGeometry(pw.plotItem.vb.sceneBoundingRect()))
        if hasattr(self, '_rightView'):
            self._rightView.clear()
        aantal_curve = pg.PlotCurveItem(x, aantal, pen=pg.mkPen('g', width=2), name="Aantal bezit")
        self._rightView.addItem(aantal_curve)
        pw.plotItem.getAxis('right').setLabel('Aantal bezit', color='g')
        ticks = [(i, str(datums[i])) for i in range(0, len(datums), max(1, len(datums)//10))]
        ax = pw.getPlotItem().getAxis('bottom')
        ax.setTicks([ticks])
        pw.plotItem.setLabel('left', '')
        pw.plotItem.setLabel('bottom', '')

        # --- Chart 2: resultaatChart ---
        rw = self.resultaatChart
        rw.clear()
        rw.plotItem.clear()
        rw.plot(x, totaal, pen=pg.mkPen('orange', width=2), name="Totaal")
        rw.plotItem.setLabel('left', '')
        rw.plotItem.setLabel('bottom', '')
        font = QFont("Arial", 7)
        pw.getAxis('bottom').setStyle(tickFont=font)
        pw.getAxis('left').setStyle(tickFont=font)
        rw.getAxis('bottom').setStyle(tickFont=font)
        rw.getAxis('left').setStyle(tickFont=font)
        ticks2 = [(i, str(datums[i])) for i in range(0, len(datums), max(1, len(datums)//10))]
        ax2 = rw.getPlotItem().getAxis('bottom')
        ax2.setTicks([ticks2])                    
        import datetime
        n = len(datums)
        step = max(1, n // 10)
        ticks = []
        for i in range(0, n, step):
            d = datums[i]
            if isinstance(d, str):
                d = datetime.datetime.strptime(d, "%Y-%m-%d")  # pas aan aan je formaat
            ticks.append((i, d.strftime("%m/%y")))
        if (n-1) % step != 0:
            d = datums[-1]
            ticks.append((n-1, d.strftime("%m/%y")))
        pw.getPlotItem().getAxis('bottom').setTicks([ticks])
        rw.getPlotItem().getAxis('bottom').setTicks([ticks])

        # Filter functionaliteit voor tableViewOptiesOpen
        self._col_filters_opties_open = {}
        #self.active_filters_opties_open = {}
        self.lineEditFilterOptiesOpen.returnPressed.connect(self.apply_filters_opties_open)
        self.buttonClearFiltersOptiesOpen.clicked.connect(self._on_clear_filters_opties_open)
        # ...vervolgens: plot df in je pyqtgraph-widgets
    @staticmethod
    def opties_kleur_func(row, colname, kleur_kolommen, columns):
        try:
            optie_call_put = row[columns.index("optie_call_put")]
            itm_otm = row[columns.index("itm_otm")]
            # print(f"DEBUG: {colname=}, {optie_call_put=}, {itm_otm=}")
            if colname in kleur_kolommen and itm_otm != 0:
                if optie_call_put == "put":
                    return QColor(255, 200, 200)
                elif optie_call_put == "call":
                    return QColor(200, 255, 200)
        except Exception as e:
            print(f"DEBUG Exception: {e}")
        return None





    def update_payoff_table(self):
        # Gebaseerd op oude code, maar nu via self.logic
        asset_rollup = self.asset_selector.currentText()
        live_price = 100

        ib_symbol = ib_currency = None
        df_rollup = getattr(SNAPSHOT_STORE, "snapshot_asset_rollup_data", None)
        if df_rollup is not None and hasattr(df_rollup, "filter"):
            with contextlib.suppress(Exception):
                row = df_rollup.filter(pl.col("asset_rollup") == asset_rollup)
                if row.height > 0:
                    ib_symbol = row["ib_symbol"][0] if "ib_symbol" in row.columns else None
                    ib_currency = row["ib_currency"][0] if "ib_currency" in row.columns else None
        if hasattr(SNAPSHOT_STORE, "live_prices") and SNAPSHOT_STORE.live_prices:
            price = None
            if ib_symbol and ib_currency:
                # print("Zoek prijs voor:", (ib_symbol, ib_currency)) # DEBUG chosen asset
                price = SNAPSHOT_STORE.live_prices.get((ib_symbol, ib_currency))
            if price is None and ib_symbol:
                price = SNAPSHOT_STORE.live_prices.get(ib_symbol)
            if price is None:
                price = SNAPSHOT_STORE.live_prices.get(asset_rollup)
            if isinstance(price, dict) and "last" in price:
                live_price = price["last"]
            elif isinstance(price, (int, float)):
                live_price = price
        
        center = float(live_price)

        step_size = self.stepSizeBox.value()
        steps = [round(center * (i - 8) * step_size + center, 2) for i in range(17)]

        headers = [str(s) for s in steps]

        self.payoff_table.setHorizontalHeaderLabels(headers)

        row_labels = [
            "Open opties",
            "Gesloten opties",
            "Open sprinters",
            "Gesloten sprinters",
            "Open aandelen",
            "Gesloten aandelen",
            "Dividend",
            "Totaal zonder fees",
            "Fees",
            "Totaal",
        ]
        for row, label in enumerate(row_labels):
            self.payoff_table.setVerticalHeaderItem(row, QTableWidgetItem(label))

        # Bereken payoff-matrix via self.logic
        payoff_matrix = [[self.logic.payoff_open_opties(s) for s in steps]]
        payoff_matrix.append([self.logic.payoff_gesloten_opties(s) for s in steps])
        payoff_matrix.append([self.logic.payoff_open_sprinters(s) for s in steps])
        payoff_matrix.append([self.logic.payoff_gesloten_sprinters(s) for s in steps])
        payoff_matrix.append([self.logic.payoff_open_aandelen(s) for s in steps])
        payoff_matrix.append([self.logic.payoff_gesloten_aandelen() for _ in steps])

        dividend_val = self.logic.get_dividend(asset_rollup)
        payoff_matrix.append([dividend_val for _ in steps])

        payoff_totaal_zonder_fees = [sum(payoff_matrix[row][i] for row in range(7)) for i in range(17)]
        payoff_matrix.append(payoff_totaal_zonder_fees)

        payoff_fees = self.logic.get_fees(steps)
        payoff_matrix.append(payoff_fees)

        payoff_totaal = [payoff_matrix[7][i] + payoff_matrix[8][i] for i in range(17)]
        payoff_matrix.append(payoff_totaal)

        factor = getattr(self.logic, "currency_factor", 1.0)

        middle_col = 8
        total_row = 9
        from PySide6.QtGui import QColor, QBrush, QFont
        from PySide6.QtCore import Qt
        lightgrey = QBrush(QColor(220, 220, 220))
        lightblue = QBrush(QColor(200, 220, 255))
        boldfont = QFont()
        boldfont.setBold(True)

        for col in range(17):
            if header_item := self.payoff_table.horizontalHeaderItem(col):
                header_item.setFont(boldfont)
                header_item.setBackground(lightgrey)

        for row in range(10):
            for col in range(17):
                val = payoff_matrix[row][col] / factor
                item = QTableWidgetItem(str(int(round(val, 0))))
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if val < 0:
                    item.setForeground(QColor(220, 0, 0))
                if col == middle_col:
                    item.setBackground(lightgrey)
                if row == total_row:
                    item.setFont(boldfont)
                    item.setBackground(lightblue)
                self.payoff_table.setItem(row, col, item)

        self.payoff_table.viewport().update()
        self.update_chart()
        for row in range(10):
            self.payoff_table.setRowHeight(row, 11)  # pas 22 aan voor nog compacter/ruimer

    @Slot()
    def apply_filters_opties_open(self):
        q = self.lineEditFilterOptiesOpen.text().strip()
        filters = {"q": q} if q else {}

        # ...en kolomfilters toevoegen...
        for col, spec in (self._col_filters_opties_open or {}).items():
            if "in" in spec:
                filters[f"__in__{col}"] = list(spec["in"])
            if "contains" in spec:
                filters[f"__contains__{col}"] = spec["contains"]
            if "eq" in spec:
                filters[f"__eq__{col}"] = spec["eq"]
            if "date_on" in spec and spec["date_on"]:
                filters[f"__date_on__{col}"] = spec["date_on"]

        # print(f"Applying filters opties open: {filters}")
        self.active_filters_opties_open = filters
        self.update_opties_open_table()

    def _on_clear_filters_opties_open(self):
        self._col_filters_opties_open.clear()
        self.lineEditFilterOptiesOpen.clear()
        self.apply_filters_opties_open()




    def update_chart(self):
        self.plot_widget.clear()
        # x-as: koerswaarden uit de header
        x_values = []
        for i in range(self.payoff_table.columnCount()):
            header_item = self.payoff_table.horizontalHeaderItem(i)
            try:
                x_values.append(float(header_item.text()))
            except Exception:
                x_values.append(i)

        # y-waarden uit de tabel
        y_totaal = []
        y_open_opties = []
        for i in range(self.payoff_table.columnCount()):
            item_totaal = self.payoff_table.item(9, i)
            item_open_opties = self.payoff_table.item(0, i)
            totaal_val = float(item_totaal.text()) if item_totaal and item_totaal.text() else 0
            open_opties_val = float(item_open_opties.text()) if item_open_opties and item_open_opties.text() else 0
            y_totaal.append(totaal_val)
            y_open_opties.append(open_opties_val)
        y_verschil = [t - o for t, o in zip(y_totaal, y_open_opties)]

        # Y-as limieten bepalen (zoals in je oude code)
        all_y = y_totaal + y_open_opties + y_verschil
        if all_y:
            min_y = min(all_y)
            max_y = max(all_y)
            if max_y == min_y:
                max_y = min_y + 1
            lower = min_y * 1.25 if min_y < 0 else min_y / 1.25
            upper = max_y * 1.25 if max_y > 0 else max_y / 1.25
            if lower == upper:
                upper = lower + 1
            self.plot_widget.setYRange(lower, upper)

        # Plotten met pyqtgraph
        self.plot_widget.plot(x_values, y_totaal, pen=pg.mkPen(color="#C6EFCE", width=2), name="Totaal")
        self.plot_widget.plot(x_values, y_verschil, pen=pg.mkPen(color="#BFBFBF", width=2), name="Totaal - Open opties")
        self.plot_widget.plot(x_values, y_open_opties, pen=pg.mkPen(color="#FF0000", width=2), name="Open opties")

        label_col_width = self.payoff_table.verticalHeader().width()
        vb = self.plot_widget.getViewBox()
        vb.setContentsMargins(label_col_width, 0, 0, 0)

        label_col_width = self.payoff_table.verticalHeader().width()
        axis = self.plot_widget.getAxis('left')
        axis.setWidth(label_col_width)
  
        self.plot_widget.setLabel('left', 'Waarde')
        self.plot_widget.setLabel('bottom', 'Koers')
        self.plot_widget.setTitle('Payoff per koersstap')
        self.plot_widget.addLegend()

    def sync_plot_with_table(self, *args):
        # Breedte linker label-kolom ophalen
        label_col_width = self.payoff_table.verticalHeader().width()

        # Offset toepassen op de ViewBox
        vb = self.plot_widget.getViewBox()
        vb.setContentsMargins(label_col_width, 0, 0, 0)

    # TODO Rename this here and in `update_chart`
    def _get_from_chart_all_y_values_for_define_min_max(self, all_y, ax):
        y_min = all_y[0]
        y_max = all_y[0]
        for y in all_y[1:]:
            if y < y_min:
                y_min = y
            if y > y_max:
                y_max = y
            # Ondergrens
        lower = y_min * 1.25 if y_min < 0 else y_min / 1.25
            # Bovengrens
        upper = y_max * 1.25 if y_max > 0 else y_max / 1.25
        if lower == upper:
            upper = lower + 1  # voorkom platte lijn
        ax.set_ylim(lower, upper)

# Logica uit single_asset_analyse_tab.py overgenomen



class SingleAssetAnalyseLogic:
    def __init__(self):
        self.df_open_opties = None
        self.df_gesloten_opties = None
        self.df_open_sprinters = None
        self.df_gesloten_sprinters = None
        self.df_aandelen = None
        self.df_gesloten_aandelen = None
        self.currency_factor = 1.0
        self.snapshot_df = None  # for clarity, but always use repository_per_dag_asset_result

    def load_assets(self):
        df = SNAPSHOT_STORE.snapshot_asset_rollup_data
        if df is not None and df.height > 0:
            return sorted(
                [str(a) for a in df["asset_rollup"].unique().to_list() if a is not None]
            )
        return []

    def set_asset(self, asset_rollup):
        store = SNAPSHOT_STORE
        self.df_open_opties = (
            store.repository_snapshot_load_open_opties.filter(pl.col("asset_rollup") == asset_rollup)
            if store.repository_snapshot_load_open_opties is not None
            else None
        )
        self.df_gesloten_opties = (
            store.repository_snapshot_gesloten_opties.filter(pl.col("asset_rollup") == asset_rollup)
            if store.repository_snapshot_gesloten_opties is not None
            else None
        )
        self.df_open_sprinters = (
            store.repository_snapshot_open_sprinters.filter(pl.col("asset_rollup") == asset_rollup)
            if store.repository_snapshot_open_sprinters is not None
            else None
        )
        self.df_gesloten_sprinters = (
            store.repository_snapshot_gesloten_sprinters.filter(pl.col("asset_rollup") == asset_rollup)
            if store.repository_snapshot_gesloten_sprinters is not None
            else None
        )
        self.df_aandelen = (
            store.repository_snapshot_aandelen.filter(pl.col("asset_rollup") == asset_rollup)
            if store.repository_snapshot_aandelen is not None
            else None
        )
        self.df_gesloten_aandelen = self.df_aandelen

        df = SNAPSHOT_STORE.snapshot_asset_rollup_data
        factor = 1.0
        if df is not None and df.height > 0:
            row = df.filter(pl.col("asset_rollup") == asset_rollup)
            if row.height > 0 and "ib_currency" in row.columns:
                if row["ib_currency"][0] == "USD":
                    
                    factor = get_settings().get_eurusd()
        self.currency_factor = factor

    def payoff_open_opties(self, koers):
        return bereken_open_opties_payoff(self.df_open_opties, koers)

    def payoff_gesloten_opties(self, koers):
        if self.df_gesloten_opties is not None and self.df_gesloten_opties.height > 0:
            if "clos_opt_transactie_euro_totaal" in self.df_gesloten_opties.columns:
                return float(self.df_gesloten_opties["clos_opt_transactie_euro_totaal"].sum())
        return 0.0

    def payoff_open_sprinters(self, koers):
        return bereken_open_sprinters_payoff(self.df_open_sprinters, koers)

    def payoff_gesloten_sprinters(self, koers):
        if self.df_gesloten_sprinters is not None and self.df_gesloten_sprinters.height > 0:
            if "clos_sp_transactie_euro_totaal" in self.df_gesloten_sprinters.columns:
                return float(self.df_gesloten_sprinters["clos_sp_transactie_euro_totaal"].sum())
        return 0.0
    
    def payoff_open_aandelen(self, koers):
        return bereken_open_aandelen_payoff(self.df_aandelen, koers)

    def payoff_gesloten_aandelen(self):
        if self.df_gesloten_aandelen is not None:
            return bereken_gesloten_aandelen_payoff(self.df_gesloten_aandelen)
        return 0.0

    def get_dividend(self, asset_rollup):
        df_div = getattr(SNAPSHOT_STORE, "repository_portfolio_dividend", None)
        dividend_val = 0.0
        if df_div is not None and hasattr(df_div, "filter"):
            with contextlib.suppress(Exception):
                rows = df_div.filter(pl.col("asset_rollup") == asset_rollup)
                if rows.height > 0 and "div_en_bel" in rows.columns:
                    dividend_val = float(rows["div_en_bel"].sum())
        return dividend_val

    def get_fees(self, steps):
        fee_aandelen = 0.0
        if self.df_aandelen is not None and self.df_aandelen.height > 0:
            if "fee_koop" in self.df_aandelen.columns:
                fee_aandelen += float(self.df_aandelen["fee_koop"].sum())
            if "fee_verkoop" in self.df_aandelen.columns:
                fee_aandelen += float(self.df_aandelen["fee_verkoop"].sum())

        fee_open_opties = [0.0 for _ in steps]
        if self.df_open_opties is not None and self.df_open_opties.height > 0 and "SomVantransactie_fee" in self.df_open_opties.columns:
            fee_val = float(self.df_open_opties["SomVantransactie_fee"].sum())
            fee_open_opties = [fee_val for _ in steps]

        fee_gesloten_opties = 0.0
        if self.df_gesloten_opties is not None and self.df_gesloten_opties.height > 0 and "clos_opt_transactie_fee" in self.df_gesloten_opties.columns:
            fee_gesloten_opties = float(self.df_gesloten_opties["clos_opt_transactie_fee"].sum())

        fee_open_sprinters = [0.0 for _ in steps]
        if self.df_open_sprinters is not None and self.df_open_sprinters.height > 0 and "SomVantransactie_fee" in self.df_open_sprinters.columns:
            fee_val = float(self.df_open_sprinters["SomVantransactie_fee"].sum())
            fee_open_sprinters = [fee_val for _ in steps]

        fee_gesloten_sprinters = 0.0
        if self.df_gesloten_sprinters is not None and self.df_gesloten_sprinters.height > 0 and "clos_sp_transactie_fee" in self.df_gesloten_sprinters.columns:
            fee_gesloten_sprinters = float(self.df_gesloten_sprinters["clos_sp_transactie_fee"].sum())

        return [
            fee_open_opties[i]
            + fee_gesloten_opties
            + fee_open_sprinters[i]
            + fee_gesloten_sprinters
            + fee_aandelen
            for i in range(len(steps))
        ]

    import polars as pl

    def load_asset_history(self, asset, start_date, end_date):
        # Use the in-memory Polars DataFrame from the repository snapshot
        df = getattr(SNAPSHOT_STORE, "repository_per_dag_asset_result", None)
        if df is None or df.height == 0:
            return pl.DataFrame({})
        # Convert QDate to Python datetime.date if needed
        if hasattr(start_date, 'toPython'):  # QDate
            start_date = start_date.toPython()
        elif hasattr(start_date, 'toPyDate'):
            start_date = start_date.toPyDate()
        if hasattr(end_date, 'toPython'):
            end_date = end_date.toPython()
        elif hasattr(end_date, 'toPyDate'):
            end_date = end_date.toPyDate()
        # Convert to Polars datetime
        start_date = pl.datetime(start_date.year, start_date.month, start_date.day)
        end_date = pl.datetime(end_date.year, end_date.month, end_date.day)
        # Ensure 'datum' is a datetime column
        if df["datum"].dtype != pl.Datetime:
            df = df.with_columns([
                pl.col("datum").str.strptime(pl.Datetime, "%d/%m/%Y", strict=False).alias("datum")
            ])
        mask = (
            (df["asset_rollup"] == asset) &
            (df["datum"] >= start_date) &
            (df["datum"] <= end_date)
        )
        return df.filter(mask).sort("datum")

    def load_option_open_data(self):
        # print("Load open opties data for single asset analyse aangeroepen")
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
            "Koers",
            pl.col("optie_call_put").alias("optie_call_put"),
            pl.col("optie_strike").alias("optie_strike"),
            pl.col("optie_exp_date").alias("optie_exp_date"),
            pl.col("SomVantransactie_aantal").alias("aantal_bezit"),
            pl.col("SomVantransactie_euro_totaal").alias("premie"),
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
        
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        SNAPSHOT_STORE.test_repository_load_input_test_dataframe = df  # sourcery skip # of df_sum als je de gesumde versie wilt zien
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken

        if df is None or df.is_empty():
            df = pl.DataFrame()

        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        SNAPSHOT_STORE.test_repository_load_output_test_dataframe = df  # sourcery skip # of df_sum als je de gesumde versie wilt zien
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken

        return df
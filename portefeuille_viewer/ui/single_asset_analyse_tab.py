from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.services.single_asset_scenario_analyse import bereken_open_opties_payoff
from portefeuille_viewer.services.single_asset_scenario_analyse import bereken_open_sprinters_payoff
from portefeuille_viewer.services.single_asset_scenario_analyse import bereken_gesloten_aandelen_payoff
from portefeuille_viewer.services.single_asset_scenario_analyse import bereken_open_aandelen_payoff
import polars as pl
from PySide6.QtWidgets import QWidget, QComboBox, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QTableWidget, QTableWidgetItem, QHeaderView
from PySide6.QtCore import QTimer, Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure




class SingleAssetAnalyseTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        # Layouts
        main_layout = QVBoxLayout()
        selector_layout = QHBoxLayout()

        # Asset selector
        self.asset_selector = QComboBox()
        self.asset_selector.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.asset_selector.setMinimumWidth(120)
        selector_label = QLabel("Asset:")
        selector_layout.addWidget(selector_label)
        selector_layout.addWidget(self.asset_selector)
        selector_layout.addStretch()

        main_layout.addLayout(selector_layout)

        self.figure = Figure(figsize=(6, 4))
        self.canvas = FigureCanvas(self.figure)
        main_layout.addWidget(self.canvas)


        # Payoff tabel (placeholder)
        
        self.payoff_table = QTableWidget()
        self.payoff_table.setColumnCount(21)  # 10 stappen links, 1 center, 10 rechts
        self.payoff_table.setRowCount(10)  # open opties, gesloten opties, open sprinters, gesloten sprinters, open aandelen, gesloten aandelen, dividend, totaal zonder fees, fees, totaal
        self.payoff_table.setMinimumHeight(400)
        self.payoff_table.setFixedWidth(1400)
        self.payoff_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Kolombreedte meeschalend met de widget
        self.payoff_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.payoff_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        main_layout.addWidget(self.payoff_table)

        self.setLayout(main_layout)

        # Data-attributen voor de gekozen asset
        self.df_open_opties = None
        self.df_gesloten_opties = None
        self.df_open_sprinters = None
        self.df_gesloten_sprinters = None
        self.df_aandelen = None

        # Vul de asset selector met alle assets uit snapshot_asset_rollup_data
        self.load_assets()

        # Koppel event aan asset selector (pas NA alles is aangemaakt)
        self.asset_selector.currentTextChanged.connect(self.on_asset_selected)

        # Timer voor refresh van payoff tabel (eerst initialiseren, dan pas eerste update)
        self._refresh_timer = QTimer(self)
        self._refresh_phase = 0
        self._refresh_count = 0
        self._refresh_timer.timeout.connect(self.update_payoff_table)
        self._refresh_timer.start(250)  # start met 250ms interval

        # Initiele payoff tabel/dataframes forceren voor eerste asset
        if self.asset_selector.count() > 0:
            self.on_asset_selected(self.asset_selector.currentText())
            # self.update_chart()

    def _advance_refresh_timer(self):
        # Na 2s (8 ticks van 250ms), ga naar 1s interval
        self._refresh_count += 1
        if self._refresh_phase == 0 and self._refresh_count >= 8:
            self._refresh_timer.setInterval(1000)
            self._refresh_phase = 1


    def update_payoff_table(self):
        self._advance_refresh_timer()
        # Robuust: alleen uitvoeren als payoff_table bestaat
        if not hasattr(self, 'payoff_table') or self.payoff_table is None:
            return
        # Koersstappen -20% tot +20% (21 kolommen)
        # Gebruik live prijs indien beschikbaar, anders 100 als center
        asset_rollup = self.asset_selector.currentText()
        live_price = 100
        # Zoek ib_symbol en ib_currency op uit snapshot_asset_rollup_data
        ib_symbol = None
        ib_currency = None
        df_rollup = getattr(SNAPSHOT_STORE, 'snapshot_asset_rollup_data', None)
        if df_rollup is not None and hasattr(df_rollup, 'filter'):
            try:
                row = df_rollup.filter(pl.col('asset_rollup') == asset_rollup)
                if row.height > 0:
                    if 'ib_symbol' in row.columns:
                        ib_symbol = row['ib_symbol'][0]
                    if 'ib_currency' in row.columns:
                        ib_currency = row['ib_currency'][0]
            except Exception:
                pass
        # Probeer live prijs te pakken uit snapshot store met (ib_symbol, ib_currency)
        if hasattr(SNAPSHOT_STORE, 'live_prices') and SNAPSHOT_STORE.live_prices:
            price = None
            if ib_symbol is not None and ib_currency is not None:
                price = SNAPSHOT_STORE.live_prices.get((ib_symbol, ib_currency))
            if price is None and ib_symbol is not None:
                # fallback: probeer alleen ib_symbol (oude keys)
                price = SNAPSHOT_STORE.live_prices.get(ib_symbol)
            if price is None:
                # fallback: probeer asset_rollup (legacy)
                price = SNAPSHOT_STORE.live_prices.get(asset_rollup)
            if isinstance(price, dict) and 'last' in price:
                live_price = price['last']
            elif isinstance(price, (int, float)):
                live_price = price
        center = float(live_price)
        steps = [round(center * (1 + (i - 10) * 0.02), 2) for i in range(21)]
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
            "Totaal"
        ]
        for row, label in enumerate(row_labels):
            self.payoff_table.setVerticalHeaderItem(row, QTableWidgetItem(label))

        # Bereken payoff per bucket per koersstap
        payoff_matrix = []
        # 1. Open opties
        payoff_open_opties = [self._payoff_open_opties(s) for s in steps]
        payoff_matrix.append(payoff_open_opties)
        # 2. Gesloten opties
        payoff_gesloten_opties = [self._payoff_gesloten_opties(s) for s in steps]
        payoff_matrix.append(payoff_gesloten_opties)
        # 3. Open sprinters
        payoff_open_sprinters = [self._payoff_open_sprinters(s) for s in steps]
        payoff_matrix.append(payoff_open_sprinters)
        # 4. Gesloten sprinters
        payoff_gesloten_sprinters = [self._payoff_gesloten_sprinters(s) for s in steps]
        payoff_matrix.append(payoff_gesloten_sprinters)
        # 5. Open aandelen
        payoff_open_aandelen = [self._payoff_open_aandelen(s) for s in steps]
        payoff_matrix.append(payoff_open_aandelen)
        # 6. Gesloten aandelen (gerealiseerd resultaat, koers-onafhankelijk)
        payoff_gesloten_aandelen = [self._payoff_gesloten_aandelen() for _ in steps]
        payoff_matrix.append(payoff_gesloten_aandelen)
        # 7. Dividend (zelfde waarde voor alle kolommen)
        asset_rollup = self.asset_selector.currentText()
        dividend_val = 0.0
        df_div = getattr(SNAPSHOT_STORE, 'repository_portfolio_dividend', None)
        if df_div is not None and hasattr(df_div, 'filter'):
            try:
                rows = df_div.filter(pl.col('asset_rollup') == asset_rollup)
                if rows.height > 0 and 'div_en_bel' in rows.columns:
                    dividend_val = float(rows['div_en_bel'].sum())
            except Exception:
                pass
        payoff_dividend = [dividend_val for _ in steps]
        payoff_matrix.append(payoff_dividend)

        # 8. Totaal zonder fees (som van alle rijen behalve fees)
        payoff_totaal_zonder_fees = [sum(payoff_matrix[row][i] for row in range(7)) for i in range(21)]
        payoff_matrix.append(payoff_totaal_zonder_fees)

        # 9. Fees-rij: sommeer relevante fee-velden per asset
        # Aandelen: fee_koop en fee_verkoop (koers-onafhankelijk)
        fee_aandelen = 0.0
        if self.df_aandelen is not None and self.df_aandelen.height > 0:
            if "fee_koop" in self.df_aandelen.columns:
                fee_aandelen += float(self.df_aandelen["fee_koop"].sum())
            if "fee_verkoop" in self.df_aandelen.columns:
                fee_aandelen += float(self.df_aandelen["fee_verkoop"].sum())

        # Open opties: SomVantransactie_fee (per koers, dus per stap berekenen)
        fee_open_opties = [0.0 for _ in steps]
        if self.df_open_opties is not None and self.df_open_opties.height > 0 and "SomVantransactie_fee" in self.df_open_opties.columns:
            fee_val = float(self.df_open_opties["SomVantransactie_fee"].sum())
            fee_open_opties = [fee_val for _ in steps]

        # Gesloten opties: clos_opt_transactie_fee (koers-onafhankelijk)
        fee_gesloten_opties = 0.0
        if self.df_gesloten_opties is not None and self.df_gesloten_opties.height > 0 and "clos_opt_transactie_fee" in self.df_gesloten_opties.columns:
            fee_gesloten_opties = float(self.df_gesloten_opties["clos_opt_transactie_fee"].sum())

        # Open sprinters: SomVantransactie_fee (per koers, dus per stap berekenen)
        fee_open_sprinters = [0.0 for _ in steps]
        if self.df_open_sprinters is not None and self.df_open_sprinters.height > 0 and "SomVantransactie_fee" in self.df_open_sprinters.columns:
            fee_val = float(self.df_open_sprinters["SomVantransactie_fee"].sum())
            fee_open_sprinters = [fee_val for _ in steps]

        # Gesloten sprinters: clos_sp_transactie_fee (koers-onafhankelijk)
        fee_gesloten_sprinters = 0.0
        if self.df_gesloten_sprinters is not None and self.df_gesloten_sprinters.height > 0 and "clos_sp_transactie_fee" in self.df_gesloten_sprinters.columns:
            fee_gesloten_sprinters = float(self.df_gesloten_sprinters["clos_sp_transactie_fee"].sum())

        # Fees per kolom: som van alle fees per assettype (open opties/sprinters per stap, rest koers-onafhankelijk)
        payoff_fees = [
            fee_open_opties[i] + fee_gesloten_opties + fee_open_sprinters[i] + fee_gesloten_sprinters + fee_aandelen
            for i in range(len(steps))
        ]
        payoff_matrix.append(payoff_fees)

        # 10. Totaal: som van 'Totaal zonder fees' en 'Fees' (rij 7 en 8)
        payoff_totaal = [payoff_matrix[7][i] + payoff_matrix[8][i] for i in range(21)]
        payoff_matrix.append(payoff_totaal)

        # Zet waarden in de tabel, pas omrekenfactor toe
        factor = getattr(self, 'currency_factor', 1.0)

        from PySide6.QtGui import QColor, QBrush, QFont

        middle_col = 10  # 0-based index, center
        total_row = 9    # 0-based index, laatste rij

        # Kleuren
        lightgrey = QBrush(QColor(220, 220, 220))
        lightblue = QBrush(QColor(200, 220, 255))
        boldfont = QFont()
        boldfont.setBold(True)

        # Kolomkoppen (x-as): bold en lichtgrijs
        for col in range(21):
            header_item = self.payoff_table.horizontalHeaderItem(col)
            if header_item:
                header_item.setFont(boldfont)
                header_item.setBackground(lightgrey)

        for row in range(10):
            for col in range(21):
                val = payoff_matrix[row][col]
                val = val / factor if factor != 1.0 else val
                item = QTableWidgetItem(str(int(round(val, 0))))
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

                from PySide6.QtGui import QColor

                if val < 0:
                    item.setForeground(QColor(220, 0, 0))  # Rood

                # Middelste kolom lichtgrijs
                if col == middle_col:
                    item.setBackground(lightgrey)
                # Total-rij bold en lichtblauw
                if row == total_row:
                    item.setFont(boldfont)
                    item.setBackground(lightblue)

                self.payoff_table.setItem(row, col, item)

        # Forceer update/repaint
        self.payoff_table.viewport().update()
        self.update_chart()

    def closeEvent(self, event):
        # Stop de timer als de widget wordt gesloten
        if hasattr(self, '_refresh_timer'):
            self._refresh_timer.stop()
        super().closeEvent(event)
    def closeEvent(self, event):
        # Stop de timer als de widget wordt gesloten
        if hasattr(self, '_refresh_timer'):
            self._refresh_timer.stop()
        super().closeEvent(event)

    def closeEvent(self, event):
        # Stop de timer als de widget wordt gesloten
        if hasattr(self, '_refresh_timer'):
            self._refresh_timer.stop()
        super().closeEvent(event)

    # Placeholder payoff-functies per bucket
    def _payoff_open_opties(self, koers):
        # Verplaats logica naar services.single_asset_scenario_analyse
        return bereken_open_opties_payoff(self.df_open_opties, koers)

    def _payoff_gesloten_opties(self, koers):
        # Toon het totaal van clos_opt_transactie_euro_totaal voor deze asset (gesloten opties)
        if self.df_gesloten_opties is not None and self.df_gesloten_opties.height > 0:
            if "clos_opt_transactie_euro_totaal" in self.df_gesloten_opties.columns:
                return float(self.df_gesloten_opties["clos_opt_transactie_euro_totaal"].sum())
        return 0.0

    def _payoff_open_sprinters(self, koers):
        return bereken_open_sprinters_payoff(self.df_open_sprinters, koers)

    def _payoff_gesloten_sprinters(self, koers):
        # Toon het totaal van clos_sp_transactie_euro_totaal voor deze asset (gesloten sprinters)
        if self.df_gesloten_sprinters is not None and self.df_gesloten_sprinters.height > 0:
            if "clos_sp_transactie_euro_totaal" in self.df_gesloten_sprinters.columns:
                return float(self.df_gesloten_sprinters["clos_sp_transactie_euro_totaal"].sum())
        return 0.0

    def _payoff_open_aandelen(self, koers):
        return bereken_open_aandelen_payoff(self.df_aandelen, koers)

    def _payoff_gesloten_aandelen(self):
        
        # Gesloten aandelen: gerealiseerd resultaat
        if hasattr(self, 'df_gesloten_aandelen'):
            return bereken_gesloten_aandelen_payoff(self.df_gesloten_aandelen)
        return 0.0
    # (verwijderd: dubbele __init__-definitie en alles erbuiten)

    def load_assets(self):
        df = SNAPSHOT_STORE.snapshot_asset_rollup_data
        if df is not None and df.height > 0:
            assets = df["asset_rollup"].unique().to_list()
            assets = sorted([str(a) for a in assets if a is not None])
            self.asset_selector.clear()
            self.asset_selector.addItems(assets)
        else:
            self.asset_selector.clear()

    def on_asset_selected(self, asset_rollup):
        # Haal relevante dataframes op voor het gekozen asset_rollup
        store = SNAPSHOT_STORE
        # Open opties
        if store.repository_snapshot_load_open_opties is not None:
            self.df_open_opties = store.repository_snapshot_load_open_opties.filter(pl.col("asset_rollup") == asset_rollup)
        else:
            self.df_open_opties = None
        # Gesloten opties
        if store.repository_snapshot_gesloten_opties is not None:
            self.df_gesloten_opties = store.repository_snapshot_gesloten_opties.filter(pl.col("asset_rollup") == asset_rollup)
        else:
            self.df_gesloten_opties = None
        # Open sprinters
        if store.repository_snapshot_open_sprinters is not None:
            self.df_open_sprinters = store.repository_snapshot_open_sprinters.filter(pl.col("asset_rollup") == asset_rollup)
        else:
            self.df_open_sprinters = None
        # Gesloten sprinters
        if store.repository_snapshot_gesloten_sprinters is not None:
            self.df_gesloten_sprinters = store.repository_snapshot_gesloten_sprinters.filter(pl.col("asset_rollup") == asset_rollup)
        else:
            self.df_gesloten_sprinters = None
        # Open aandelen
        if store.repository_snapshot_aandelen is not None:
            self.df_aandelen = store.repository_snapshot_aandelen.filter(pl.col("asset_rollup") == asset_rollup)
        else:
            self.df_aandelen = None
        # Gesloten aandelen: gebruik hetzelfde snapshot als open aandelen
        if store.repository_snapshot_aandelen is not None:
            self.df_gesloten_aandelen = store.repository_snapshot_aandelen.filter(pl.col("asset_rollup") == asset_rollup)
        else:
            self.df_gesloten_aandelen = None
        # Update payoff tabel na selectie
        
        df = SNAPSHOT_STORE.snapshot_asset_rollup_data
        factor = 1.0
        if df is not None and df.height > 0:
            row = df.filter(pl.col('asset_rollup') == asset_rollup)
            if row.height > 0 and 'ib_currency' in row.columns:
                currency = row['ib_currency'][0]
                if currency == 'USD':
                    factor = 1.16
        self.currency_factor = factor
        
        self.update_payoff_table()


    def update_chart(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        # x-as: koers (kolomheaders)
        x = []
        for i in range(self.payoff_table.columnCount()):
            header_item = self.payoff_table.horizontalHeaderItem(i)
            if header_item:
                try:
                    x.append(float(header_item.text()))
                except ValueError:
                    x.append(header_item.text())
            else:
                x.append(i)
        # y-as: totaalrij (laatste rij, index 9)
        y_totaal = []
        y_open_opties = []
        for i in range(self.payoff_table.columnCount()):
            item_totaal = self.payoff_table.item(9, i)
            item_open_opties = self.payoff_table.item(0, i)
            try:
                totaal_val = float(item_totaal.text()) if item_totaal and item_totaal.text() else 0
            except ValueError:
                totaal_val = 0
            try:
                open_opties_val = float(item_open_opties.text()) if item_open_opties and item_open_opties.text() else 0
            except ValueError:
                open_opties_val = 0
            y_totaal.append(totaal_val)
            y_open_opties.append(open_opties_val)
        # Verschil: totaal - open opties
        y_verschil = [t - o for t, o in zip(y_totaal, y_open_opties)]
        ax.axhline(0, color='black', linewidth=0.5)
        # Plot beide lijnen
        ax.plot(x, y_totaal, color='#C8F5D6', label='Totaal')
        ax.plot(x, y_verschil, color='blue', label='Totaal - Open opties')
        ax.plot(x, y_open_opties, color='red', label='Open opties')
        ax.set_xlabel("Koers")
        ax.set_ylabel("Waarde")
        ax.set_title("Payoff per koersstap")
        ax.legend()
        self.canvas.draw()
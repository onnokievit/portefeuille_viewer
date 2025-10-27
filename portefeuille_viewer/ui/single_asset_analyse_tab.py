from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.services.single_asset_scenario_analyse import (
    bereken_open_opties_payoff,
    bereken_open_sprinters_payoff,
    bereken_gesloten_aandelen_payoff,
    bereken_open_aandelen_payoff,
)
import polars as pl
from PySide6.QtWidgets import (
    QWidget,
    QComboBox,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
)
from PySide6.QtCore import QTimer, Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtGui import QColor, QBrush, QFont
import numpy as np


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

        # Chart
        self.figure = Figure(figsize=(6, 4))
        self.canvas = FigureCanvas(self.figure)

        # Payoff tabel
        self.payoff_table = QTableWidget()
        self.payoff_table.setColumnCount(21)
        self.payoff_table.setRowCount(10)
        self.payoff_table.setMinimumHeight(400)
        self.payoff_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.payoff_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.payoff_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        # Zet chart en tabel in een QSplitter
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.canvas)
        splitter.addWidget(self.payoff_table)
        splitter.setSizes([400, 500])  # eerste waarde = hoogte chart, tweede = tabel

        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

        # Data-attributen
        self.df_open_opties = None
        self.df_gesloten_opties = None
        self.df_open_sprinters = None
        self.df_gesloten_sprinters = None
        self.df_aandelen = None

        # Laad assets
        self.load_assets()

        # Connectie selector
        self.asset_selector.currentTextChanged.connect(self.on_asset_selected)

        # Timer voor refresh
        self._refresh_timer = QTimer(self)
        self._refresh_phase = 0
        self._refresh_count = 0
        self._refresh_timer.timeout.connect(self.update_payoff_table)
        self._refresh_timer.start(250)

        if self.asset_selector.count() > 0:
            self.on_asset_selected(self.asset_selector.currentText())

    def _advance_refresh_timer(self):
        self._refresh_count += 1
        if self._refresh_phase == 0 and self._refresh_count >= 8:
            self._refresh_timer.setInterval(1000)
            self._refresh_phase = 1

    def update_payoff_table(self):
        self._advance_refresh_timer()
        if not hasattr(self, "payoff_table") or self.payoff_table is None:
            return

        asset_rollup = self.asset_selector.currentText()
        live_price = 100

        ib_symbol = ib_currency = None
        df_rollup = getattr(SNAPSHOT_STORE, "snapshot_asset_rollup_data", None)
        if df_rollup is not None and hasattr(df_rollup, "filter"):
            try:
                row = df_rollup.filter(pl.col("asset_rollup") == asset_rollup)
                if row.height > 0:
                    ib_symbol = row["ib_symbol"][0] if "ib_symbol" in row.columns else None
                    ib_currency = row["ib_currency"][0] if "ib_currency" in row.columns else None
            except Exception:
                pass

        if hasattr(SNAPSHOT_STORE, "live_prices") and SNAPSHOT_STORE.live_prices:
            price = None
            if ib_symbol and ib_currency:
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
            "Totaal",
        ]
        for row, label in enumerate(row_labels):
            self.payoff_table.setVerticalHeaderItem(row, QTableWidgetItem(label))

        # Bereken payoff-matrix
        payoff_matrix = []
        payoff_matrix.append([self._payoff_open_opties(s) for s in steps])
        payoff_matrix.append([self._payoff_gesloten_opties(s) for s in steps])
        payoff_matrix.append([self._payoff_open_sprinters(s) for s in steps])
        payoff_matrix.append([self._payoff_gesloten_sprinters(s) for s in steps])
        payoff_matrix.append([self._payoff_open_aandelen(s) for s in steps])
        payoff_matrix.append([self._payoff_gesloten_aandelen() for _ in steps])

        # Dividend
        df_div = getattr(SNAPSHOT_STORE, "repository_portfolio_dividend", None)
        dividend_val = 0.0
        if df_div is not None and hasattr(df_div, "filter"):
            try:
                rows = df_div.filter(pl.col("asset_rollup") == asset_rollup)
                if rows.height > 0 and "div_en_bel" in rows.columns:
                    dividend_val = float(rows["div_en_bel"].sum())
            except Exception:
                pass
        payoff_matrix.append([dividend_val for _ in steps])

        # Totaal zonder fees
        payoff_totaal_zonder_fees = [sum(payoff_matrix[row][i] for row in range(7)) for i in range(21)]
        payoff_matrix.append(payoff_totaal_zonder_fees)

        # Fees
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

        payoff_fees = [
            fee_open_opties[i] + fee_gesloten_opties + fee_open_sprinters[i] + fee_gesloten_sprinters + fee_aandelen
            for i in range(len(steps))
        ]
        payoff_matrix.append(payoff_fees)

        # Totaal (inclusief fees)
        payoff_totaal = [payoff_matrix[7][i] + payoff_matrix[8][i] for i in range(21)]
        payoff_matrix.append(payoff_totaal)

        factor = getattr(self, "currency_factor", 1.0)

        middle_col = 10
        total_row = 9
        lightgrey = QBrush(QColor(220, 220, 220))
        lightblue = QBrush(QColor(200, 220, 255))
        boldfont = QFont()
        boldfont.setBold(True)

        for col in range(21):
            header_item = self.payoff_table.horizontalHeaderItem(col)
            if header_item:
                header_item.setFont(boldfont)
                header_item.setBackground(lightgrey)

        for row in range(10):
            for col in range(21):
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

    def closeEvent(self, event):
        if hasattr(self, "_refresh_timer"):
            self._refresh_timer.stop()
        super().closeEvent(event)

    # Payoff-functies
    def _payoff_open_opties(self, koers):
        return bereken_open_opties_payoff(self.df_open_opties, koers)

    def _payoff_gesloten_opties(self, koers):
        if self.df_gesloten_opties is not None and self.df_gesloten_opties.height > 0:
            if "clos_opt_transactie_euro_totaal" in self.df_gesloten_opties.columns:
                return float(self.df_gesloten_opties["clos_opt_transactie_euro_totaal"].sum())
        return 0.0

    def _payoff_open_sprinters(self, koers):
        return bereken_open_sprinters_payoff(self.df_open_sprinters, koers)

    def _payoff_gesloten_sprinters(self, koers):
        if self.df_gesloten_sprinters is not None and self.df_gesloten_sprinters.height > 0:
            if "clos_sp_transactie_euro_totaal" in self.df_gesloten_sprinters.columns:
                return float(self.df_gesloten_sprinters["clos_sp_transactie_euro_totaal"].sum())
        return 0.0

    def _payoff_open_aandelen(self, koers):
        return bereken_open_aandelen_payoff(self.df_aandelen, koers)

    def _payoff_gesloten_aandelen(self):
        if hasattr(self, "df_gesloten_aandelen"):
            return bereken_gesloten_aandelen_payoff(self.df_gesloten_aandelen)
        return 0.0

    def load_assets(self):
        df = SNAPSHOT_STORE.snapshot_asset_rollup_data
        if df is not None and df.height > 0:
            assets = sorted([str(a) for a in df["asset_rollup"].unique().to_list() if a is not None])
            self.asset_selector.clear()
            self.asset_selector.addItems(assets)
        else:
            self.asset_selector.clear()

    def on_asset_selected(self, asset_rollup):
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
                    factor = 1.16
        self.currency_factor = factor
        self.update_payoff_table()

    def update_chart(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)

        # === Koersen ophalen ===
        x_values = []
        for i in range(self.payoff_table.columnCount()):
            header_item = self.payoff_table.horizontalHeaderItem(i)
            if header_item:
                try:
                    x_values.append(float(header_item.text()))
                except ValueError:
                    x_values.append(i)
            else:
                x_values.append(i)

        # === Y-waarden ophalen ===
        y_totaal, y_open_opties = [], []
        for i in range(self.payoff_table.columnCount()):
            item_totaal = self.payoff_table.item(9, i)
            item_open_opties = self.payoff_table.item(0, i)
            totaal_val = float(item_totaal.text()) if item_totaal and item_totaal.text() else 0
            open_opties_val = float(item_open_opties.text()) if item_open_opties and item_open_opties.text() else 0
            y_totaal.append(totaal_val)
            y_open_opties.append(open_opties_val)
        y_verschil = [t - o for t, o in zip(y_totaal, y_open_opties)]

        # === Bereken exacte kolomposities (pixels) ===
        col_widths = [self.payoff_table.columnWidth(i) for i in range(self.payoff_table.columnCount())]
        cumulative = np.cumsum([0] + col_widths)
        col_centers = [cumulative[i] + col_widths[i] / 2 for i in range(len(col_widths))]
        x_scaled = np.array(col_centers)
        ax.set_xlim(x_scaled[0] - col_widths[0] / 2, x_scaled[-1] + col_widths[-1] / 2)

        # === Plot ===
        ax.axhline(0, color="black", linewidth=0.5)
        ax.plot(x_scaled, y_totaal, color="#4CD276", label="Totaal")
        ax.plot(x_scaled, y_verschil, color="blue", label="Totaal - Open opties")
        ax.plot(x_scaled, y_open_opties, color="red", label="Open opties")

        # === X-ticks exact boven kolommen ===
        ax.set_xticks(x_scaled)
        ax.set_xticklabels([str(v) for v in x_values], fontsize=8, rotation=0)

        # === Dynamische linker marge ===
        canvas_width = max(self.canvas.width(), 1)  # voorkom deling door nul
        first_col_width = self.payoff_table.columnWidth(0)
        # Zet de marge in figuurcoördinaten (0–1)
        left_margin = first_col_width / canvas_width

        self.figure.subplots_adjust(
            left=left_margin,   # uitlijnen met eerste kolom
            right=0.995,        # bijna tot de rand
            bottom=0.22,
            top=0.9
        )

        ax.set_xlabel("Koers")
        ax.set_ylabel("Waarde")
        ax.set_title("Payoff per koersstap")
        ax.legend(loc="upper left")

        ax.margins(x=0)
        self.canvas.draw()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Herteken de grafiek met nieuwe marges
        self.update_chart()



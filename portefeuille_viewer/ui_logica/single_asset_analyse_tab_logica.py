
import contextlib
import polars as pl
from PySide6.QtWidgets import QWidget, QTableWidgetItem,QHeaderView
from PySide6.QtGui import QFont
from PySide6.QtCore import QLocale
import pyqtgraph as pg
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

		self.gridLayout_2.setColumnStretch(0, 10)
		self.gridLayout_2.setColumnStretch(1, 7)
		
		self.payoff_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
		
		self.stepSizeBox.setLocale(QLocale(QLocale.C))
		# Maak de rijhoogte compacter
		for row in range(10):
			self.payoff_table.setRowHeight(row, 16)  # pas 22 aan voor nog compacter/ruimer
		
		font = QFont("Arial", 8)  # Kies je gewenste lettertype en grootte
		self.payoff_table.setFont(font)        
                
		self.logic = SingleAssetAnalyseLogic()
        
		self.asset_selector.addItems(self.logic.load_assets())
		self.asset_selector.currentTextChanged.connect(self.on_asset_selected)

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
		self.payoff_table.setColumnCount(21)
		self.payoff_table.setRowCount(10)
		self.stepSizeBox.valueChanged.connect(self.update_payoff_table)
		# Je kunt hier headers en andere init doen zoals in je oude code

	def on_asset_selected(self, asset_rollup):
		self.logic.set_asset(asset_rollup)
		self.update_payoff_table()

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
		steps = [round(center * (i - 10) * step_size + center, 2) for i in range(21)]

		# steps = [round(center * (i - 10) * 0.02 + center, 2) for i in range(21)]
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

		payoff_totaal_zonder_fees = [sum(payoff_matrix[row][i] for row in range(7)) for i in range(21)]
		payoff_matrix.append(payoff_totaal_zonder_fees)

		payoff_fees = self.logic.get_fees(steps)
		payoff_matrix.append(payoff_fees)

		payoff_totaal = [payoff_matrix[7][i] + payoff_matrix[8][i] for i in range(21)]
		payoff_matrix.append(payoff_totaal)

		factor = getattr(self.logic, "currency_factor", 1.0)

		middle_col = 10
		total_row = 9
		from PySide6.QtGui import QColor, QBrush, QFont
		from PySide6.QtCore import Qt
		lightgrey = QBrush(QColor(220, 220, 220))
		lightblue = QBrush(QColor(200, 220, 255))
		boldfont = QFont()
		boldfont.setBold(True)

		for col in range(21):
			if header_item := self.payoff_table.horizontalHeaderItem(col):
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


import contextlib
from PySide6.QtWidgets import QWidget, QTableWidgetItem
from portefeuille_viewer.ui.single_asset_analyse_tab_ui import Ui_SingleAssetAnalyseTab
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.services.single_asset_scenario_analyse import (
	bereken_open_opties_payoff,
	bereken_open_sprinters_payoff,
	bereken_gesloten_aandelen_payoff,
	bereken_open_aandelen_payoff,
)
import polars as pl
from portefeuille_viewer.config import get_settings
import numpy as np

# Widget-class die UI en logica koppelt
class SingleAssetAnalyseTab(QWidget, Ui_SingleAssetAnalyseTab):
	

	def __init__(self, parent=None):
		super().__init__(parent)
		self.setupUi(self)
		from PySide6.QtWidgets import QHeaderView
		self.payoff_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

		# Maak de rijhoogte compacter
		for row in range(10):
			self.payoff_table.setRowHeight(row, 16)  # pas 22 aan voor nog compacter/ruimer
                
		self.logic = SingleAssetAnalyseLogic()
        
		self.asset_selector.addItems(self.logic.load_assets())
		self.asset_selector.currentTextChanged.connect(self.on_asset_selected)

		# Voeg matplotlib-canvas toe aan chartWidget
		from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
		from matplotlib.figure import Figure
		self.figure = Figure(figsize=(6, 4))
		self.canvas = FigureCanvas(self.figure)
		self.layoutChart.addWidget(self.canvas)

		# Tooltip/annotatie voor mouseover
		self._mpl_annotation = None
		self._mpl_hover_cid = self.canvas.mpl_connect('motion_notify_event', self._on_mpl_hover)
		self._mpl_last_lines = []
		self._mpl_x_mapping = []  # mapping van x_scaled naar koerswaarde



		# Initialiseer payoff_table
		self.payoff_table.setColumnCount(21)
		self.payoff_table.setRowCount(10)
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
		steps = [round(center * (i - 10) * 0.02 + center, 2) for i in range(21)]
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
		self.figure.clear()
		# Reset annotatie bij nieuw tekenen
		if self._mpl_annotation:
			self._mpl_annotation.set_visible(False)
			self._mpl_annotation = None
		ax = self.figure.add_subplot(111)

		# Check of er kolommen zijn, anders geen grafiek tekenen
		if self.payoff_table.columnCount() == 0:
			self.canvas.draw()
			return

		# === Koersen ophalen ===
		x_values = []
		for i in range(self.payoff_table.columnCount()):
			if header_item := self.payoff_table.horizontalHeaderItem(i):
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

		# === Y-as limiet bepalen door alle y-waarden van alle lijnen te loopen ===
		all_y = y_totaal + y_open_opties + y_verschil
		if all_y:
			self._get_from_chart_all_y_values_for_define_min_max(all_y, ax)
		# === Y-as limiet instellen op basis van alle lijnen ===
		all_y = y_totaal + y_verschil + y_open_opties
		if all_y:
			min_y = min(all_y)
			max_y = max(all_y)
			if max_y == min_y:
				max_y = min_y + 1  # voorkom platte lijn
			if min_y < 0:
				lower = min_y * 1.25
			else:
				lower = min_y / 1.25
			if max_y > 0:
				upper = max_y * 1.25
			else:
				upper = max_y / 1.25
			ax.set_ylim(lower, upper)

		for spine in ax.spines.values():
			spine.set_linewidth(0.5)
			spine.set_color("#CCCCCC")

		# lichte as- en achtergrondstijl
		ax.tick_params(colors="#666666", labelsize=9)
		ax.set_facecolor("#FAFAFA")

		# === Bereken exacte kolomposities (pixels) ===
		col_widths = [self.payoff_table.columnWidth(i) for i in range(self.payoff_table.columnCount())]
		cumulative = np.cumsum([0] + col_widths)
		col_centers = [cumulative[i] + col_widths[i] / 2 for i in range(len(col_widths))]
		x_scaled = np.array(col_centers)
		ax.set_xlim(x_scaled[0] - col_widths[0] / 2, x_scaled[-1] + col_widths[-1] / 2)
		# Mapping van x_scaled naar koerswaarde
		self._mpl_x_mapping = list(zip(x_scaled, x_values))

		# === Plot ===
		line_totaal, = ax.plot(x_scaled, y_totaal, color="#C6EFCE", label="Totaal", picker=5)
		line_verschil, = ax.plot(x_scaled, y_verschil, color="#BFBFBF", label="Totaal - Open opties", picker=5)
		line_open_opties, = ax.plot(x_scaled, y_open_opties, color="#FF0000", label="Open opties", picker=5)
		# Sla ook koerswaarden op per lijn
		self._mpl_last_lines = [
			(line_totaal, x_scaled, y_totaal, x_values, "Totaal"),
			(line_verschil, x_scaled, y_verschil, x_values, "Totaal - Open opties"),
			(line_open_opties, x_scaled, y_open_opties, x_values, "Open opties"),
		]
		ax.axhline(0, color="black", linewidth=0.5)

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

	def _on_mpl_hover(self, event):
		# Toon een tooltip met de dichtstbijzijnde waarde bij de muis
		if not event.inaxes or not self._mpl_last_lines:
			if self._mpl_annotation:
				self._mpl_annotation.set_visible(False)
				self.canvas.draw_idle()
			return
		ax = event.inaxes
		min_dist = float('inf')
		closest_info = None
		for line, xdata, ydata, xvals, label in self._mpl_last_lines:
			for idx, (xi, yi) in enumerate(zip(xdata, ydata)):
				dist = (event.xdata - xi) ** 2 + (event.ydata - yi) ** 2
				if dist < min_dist:
					min_dist = dist
					# Toon koerswaarde uit xvals
					koers_val = xvals[idx] if idx < len(xvals) else xi
					closest_info = (xi, yi, koers_val, label)
		if closest_info and min_dist < 1000:  # pixelafstand, evt. aanpassen
			xi, yi, koers_val, label = closest_info
			if self._mpl_annotation is None:
				self._mpl_annotation = ax.annotate(
					f"{label}\nKoers: {koers_val:.2f}\nWaarde: {yi:.0f}",
					xy=(xi, yi), xycoords='data',
					xytext=(10, 30), textcoords='offset points',
					bbox=dict(boxstyle="round,pad=0.3", fc="yellow", alpha=0.7),
					arrowprops=dict(arrowstyle="->", color='gray'),
				)
			else:
				self._mpl_annotation.xy = (xi, yi)
				self._mpl_annotation.set_text(f"{label}\nKoers: {koers_val:.2f}\nWaarde: {yi:.0f}")
				self._mpl_annotation.set_visible(True)
			self.canvas.draw_idle()
		elif self._mpl_annotation:
			self._mpl_annotation.set_visible(False)
			self.canvas.draw_idle()

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

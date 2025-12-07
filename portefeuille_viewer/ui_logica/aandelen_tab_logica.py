# Logica voor de AandelenTab, gekoppeld aan de Designer UI (Ui_AandelenTab)
from PySide6.QtWidgets import QWidget, QTableWidgetItem,QFileDialog, QMessageBox
from PySide6.QtCore import Slot, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import QTableWidget
from portefeuille_viewer.ui.aandelen_tab_ui import Ui_AandelenTab
from portefeuille_viewer.domain.portfolio_engine import PortfolioEngine
from portefeuille_viewer.ui.models import PolarsTableModel
from portefeuille_viewer.ui.filter_popup import ColumnFilterPopup
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
import polars as pl

class AandelenTab(QWidget, Ui_AandelenTab):
	@Slot()
	def on_btnExportExcel_clicked(self):
		"""Exporteer de huidige zichtbare tabel (df_sum) naar Excel."""
		try:
			# self.model._df is de huidige zichtbare Polars DataFrame (df_sum)
			df = self.model._df
			if df is None or df.is_empty():
				QMessageBox.warning(self, "Exporteren mislukt", "Geen data om te exporteren.")
				return
			# Converteer naar pandas DataFrame
			pdf = df.to_pandas()
			fname, _ = QFileDialog.getSaveFileName(self, "Opslaan als Excel", "aandelen_snapshot.xlsx", "Excel Files (*.xlsx)")
			if fname:
				pdf.to_excel(fname, index=False)
				QMessageBox.information(self, "Export geslaagd", f"Snapshot succesvol opgeslagen als:\n{fname}")
		except Exception as e:
			QMessageBox.critical(self, "Exporteren mislukt", f"Fout bij exporteren:\n{e}")
	"""
	Tab voor het tonen van de geaggregeerde aandelen-posities uit PortfolioEngine.
	Kolommen: asset_rollup, koers, aantal_bezit, result_realized, result_non_realized
	"""
	def __init__(self, portfolio_engine=None, pricefeed=None, parent=None):
		"""
		This Python function initializes a GUI component for managing stock portfolio data, including
		setting up UI elements, connecting to a portfolio engine and price feed, handling button actions,
		setting up tables, and loading initial data.
		
		:param portfolio_engine: The `portfolio_engine` parameter in the `__init__` method is used to pass
		an instance of a `PortfolioEngine` class to the `AandelenTab` class. If `portfolio_engine` is
		provided, it is stored in the `self.engine` attribute of the `Aandelen
		:param pricefeed: The `pricefeed` parameter in the `__init__` method is used to provide a source of
		price data for the portfolio engine. If `pricefeed` is not provided explicitly, the code will
		attempt to use the `pricefeed` attribute of the `portfolio_engine` object. If neither
		:param parent: In the provided code snippet, the `parent` parameter is used in the `__init__`
		method of a class. In this context, `parent` typically refers to the parent widget or object to
		which the current widget or object being initialized belongs
		"""
		super().__init__(parent)
		self.setupUi(self)

		self.current_sort_column = -1
		self.current_sort_order = 0
		self.col_filters = {}
		self.selected_brokers = None

		# Engine en pricefeed
		if portfolio_engine is not None:
			self.engine = portfolio_engine
			if hasattr(self.engine, 'pricefeed'):
				pricefeed = self.engine.pricefeed
		else:
			if pricefeed is None:
				raise ValueError("Either portfolio_engine or pricefeed must be provided")
			self.engine = PortfolioEngine(pricefeed)

		self.pricefeed = pricefeed or (self.engine.pricefeed if hasattr(self.engine, 'pricefeed') else None)
		# Alleen ticker/label updaten op priceUpdated, niet de tabel
		if self.pricefeed and hasattr(self.pricefeed, 'priceUpdated'):
			self.pricefeed.priceUpdated.connect(self.on_ticker_display)

		# Koppel knoppen aan logica
		self.btnSelecteerBrokers.clicked.connect(self.open_broker_popup)
		self.btnWisFilters.clicked.connect(self.clear_all_filters)
		
		# Table setup
		self.tblAandelen.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
		self.tblAandelen.horizontalHeader().customContextMenuRequested.connect(self.on_header_menu)
		self.tblAandelen.verticalHeader().setVisible(False)
		self.tblAandelen.setAlternatingRowColors(True)
		self.tblAandelen.setSortingEnabled(True)
		self.tblAandelen.verticalHeader().setDefaultSectionSize(20)

		self.tblTotalen.setFixedHeight(32)
		self.tblTotalen.verticalHeader().setVisible(False)
		self.tblTotalen.horizontalHeader().setVisible(False)
		
		self.tblTotalen.setEditTriggers(QTableWidget.NoEditTriggers)
		self.tblTotalen.setFocusPolicy(Qt.NoFocus)
		self.tblTotalen.setSelectionMode(QTableWidget.NoSelection)

		# Initieel laden
		self.reload_data()

		# Koppel live update: alleen via PortfolioEngine
		if hasattr(self.engine, 'dataUpdated'):
			self.engine.dataUpdated.connect(self.on_engine_data_update)
		# print("[DEBUG] self.pricefeed in tab bij connect:", self.pricefeed, id(self.pricefeed) if self.pricefeed else None)

	def clear_all_filters(self):
		self.col_filters.clear()
		self.selected_brokers = None
		self.reload_data()

	def on_sort_changed(self, column, order):
		self.current_sort_column = column
		self.current_sort_order = order

	def reload_data(self):
		########### import data ##################################
		df = SNAPSHOT_STORE.aggregator_snapshot_aandelen_live
		if self.selected_brokers is not None and "broker" in df.columns:
			df = df.filter(pl.col("broker").is_in(list(self.selected_brokers)))
		if not df.is_empty():
			df_aandelen_sum = df.group_by("asset_rollup","koers","regio", "sector","value_grow").agg([
				pl.col("aantal_bezit").sum().alias("eq_aantal_bezit"),
				pl.col("aantal_koop").sum().alias("eq_aantal_koop"),
				pl.col("euro_koop").sum().alias("eq_euro_koop"),
				pl.col("aantal_verkoop").sum().alias("eq_aantal_verkoop"),
				pl.col("euro_verkoop").sum().alias("eq_euro_verkoop"),
				pl.col("total_result").sum().alias("eq_total_result"),
				pl.col("eq_total_fee").sum().alias("eq_total_fee"),
			])
		else:
			df_aandelen_sum = df
		
		df_gesloten_opties = SNAPSHOT_STORE.repository_snapshot_gesloten_opties
		if self.selected_brokers is not None and "broker" in df.columns:
			df_gesloten_opties = df_gesloten_opties.filter(pl.col("broker").is_in(list(self.selected_brokers)))
		if not df_gesloten_opties.is_empty():
			df_clos_opt_sum = df_gesloten_opties.group_by("asset_rollup").agg([
				pl.col("clos_opt_transactie_euro_totaal").sum(),
				pl.col("clos_opt_transactie_fee").sum(),
			])
		else:
			df_clos_opt_sum = df_gesloten_opties

		df_gesloten_sprinters = SNAPSHOT_STORE.repository_snapshot_gesloten_sprinters_no_asset_detail
		if self.selected_brokers is not None and "broker" in df.columns:
			df_gesloten_sprinters = df_gesloten_sprinters.filter(pl.col("broker").is_in(list(self.selected_brokers)))
		if not df_gesloten_sprinters.is_empty():
			df_clos_sp_sum = df_gesloten_sprinters.group_by("asset_rollup").agg([
				pl.col("clos_sp_transactie_euro_totaal").sum(),
				pl.col("clos_sp_transactie_fee").sum(),
			])
		else:
			df_clos_sp_sum = df_gesloten_opties

		df_open_opties = SNAPSHOT_STORE.aggregator_snapshot_load_open_opties_from_tx_live
		if self.selected_brokers is not None and "broker" in df.columns:
			df_open_opties = df_open_opties.filter(pl.col("broker").is_in(list(self.selected_brokers)))
		if not df_open_opties.is_empty():
			df_open_opt_sum = df_open_opties.group_by("asset_rollup").agg([
				pl.col("opt_total_result").sum().alias("open_opt_total_result"),
				pl.col("SomVantransactie_fee").sum().alias("open_opt_transactie_fee"),
			])
		else:
			df_open_opt_sum = df_open_opties

		df_open_sprinters = SNAPSHOT_STORE.aggregator_snapshot_open_sprinters_live
		if self.selected_brokers is not None and "broker" in df.columns:
			df_open_sprinters = df_open_sprinters.filter(pl.col("broker").is_in(list(self.selected_brokers)))
		if df_open_sprinters is not None and not df_open_sprinters.is_empty():
			df_open_sp_sum = df_open_sprinters.group_by("asset_rollup").agg([
				pl.col("sp_result").sum().alias("open_sp_result"),
				pl.col("SomVantransactie_fee").sum().alias("open_sp_transactie_fee"),
				pl.col("SomVantransactie_aantal").sum().alias("open_sp_aantal"),
			])
		else:
			df_open_sp_sum = df_open_sprinters if df_open_sprinters is not None else pl.DataFrame()

		df_dividend = SNAPSHOT_STORE.repository_portfolio_dividend
		if self.selected_brokers is not None and "broker" in df.columns:
			df_dividend = df_dividend.filter(pl.col("broker").is_in(list(self.selected_brokers)))
		if not df_dividend.is_empty():
			df_div_bel = df_dividend.group_by("asset_rollup").agg([
				pl.col("div_en_bel").sum().alias("div_en_bel"),
			])
		else:
			df_div_bel = df_dividend
		
		df_active_rollup = SNAPSHOT_STORE.repository_snapshot_active_asset_rollup_data

		df_portfolio_value_combined = SNAPSHOT_STORE.repository_snapshot_portfolio_value_total_combined

		df_asset_result = SNAPSHOT_STORE.repository_per_dag_asset_result
		if df_asset_result["datum"].dtype == pl.String:
			df_asset_result = df_asset_result.with_columns(
				pl.col("datum").str.strptime(pl.Date, "%d/%m/%Y")
			)
		df_aset_result_latest = (
			df_asset_result
			.sort(["asset_rollup", "datum"])
			.group_by("asset_rollup")
			.agg([pl.all().last()])
		)


		########### einde import data ##################################
		
		########### Joins ##################################
		df_aand_opt = df_aandelen_sum.join(df_clos_opt_sum, on=["asset_rollup"], how="full", suffix="_opt_gesloten")
		if "asset_rollup_opt_gesloten" in df_aand_opt.columns:
			df_aand_opt = df_aand_opt.with_columns([
				pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_opt_gesloten")]).alias("asset_rollup")
		])
		df_aand_opt_sp = df_aand_opt.join(df_clos_sp_sum, on=["asset_rollup"], how="full", suffix="_sp_gesloten")
		if "asset_rollup_sp_gesloten" in df_aand_opt_sp.columns:
			df_aand_opt_sp = df_aand_opt_sp.with_columns([
				pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_sp_gesloten")]).alias("asset_rollup")
		])
		df_aand_opt_sp_open_opt = df_aand_opt_sp.join(df_open_opt_sum, on=["asset_rollup"], how="full", suffix="_opt_o_open")
		if "asset_rollup_opt_o_open" in df_aand_opt_sp_open_opt.columns:
			df_aand_opt_sp_open_opt = df_aand_opt_sp_open_opt.with_columns([
				pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_opt_o_open")]).alias("asset_rollup")
		])
		df_open_sp_sum_join = df_aand_opt_sp_open_opt.join(df_open_sp_sum, on=["asset_rollup"], how="full", suffix="_sp_open")
		if "asset_rollup_opt_o_open" in df_aand_opt_sp_open_opt.columns:
			df_open_sp_sum_join = df_open_sp_sum_join.with_columns([
				pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_sp_open")]).alias("asset_rollup")
		])
		df_final = df_open_sp_sum_join.join(df_div_bel, on=["asset_rollup"], how="full", suffix="_div_bel")
		if "asset_rollup_div_bel" in df_open_sp_sum_join.columns:
			df_final = df_final.with_columns([
				pl.coalesce([pl.col("asset_rollup"), pl.col("asset_rollup_div_bel")]).alias("asset_rollup")
		])
		df_final = df_final.join(df_active_rollup.select(["asset_rollup","status"]), on=["asset_rollup"], how="left")

		df_final = df_final.join(df_portfolio_value_combined.select(["asset_rollup","portfolio_total_waarde_lineair_pct","portfolio_total_waarde_delta_pct"]), on=["asset_rollup"], how="left")

		df_final = df_final.join(df_aset_result_latest.select(["asset_rollup","close_price","totaal"]), on=["asset_rollup"], how="left")

		# # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
		# from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE # sourcery skip
		SNAPSHOT_STORE.test_repository_load_input_test_dataframe = df_aset_result_latest  # sourcery skip # of df_sum als je de gesumde versie wilt zien
		# # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken


		# # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
		# from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE # sourcery skip
		#SNAPSHOT_STORE.test_repository_load_output_test_dataframe = df_final1  # sourcery skip # of df_sum als je de gesumde versie wilt zien
		# # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken



		required_columns = {
			"open_sp_aantal": 0,
			"open_sp_result": 0,
			"open_sp_transactie_fee": 0,
			"clos_sp_transactie_euro_totaal": 0,
			"clos_sp_transactie_fee": 0,
			"eq_aantal_bezit": 0,
			"eq_total_result": 0,
			"clos_opt_transactie_euro_totaal": 0,
			"clos_opt_transactie_fee": 0,
			"open_opt_total_result": 0,
			"open_opt_transactie_fee": 0,
			"div_en_bel": 0,
			"totaal_resultaat": 0,
			"totaal_fee": 0,
			"koers": 0,
			"status": "",
			"asset_rollup": "",
		}
		for col, default in required_columns.items():
			if col not in df_final.columns:
				df_final = df_final.with_columns(pl.lit(default).alias(col))
		########### Einde Joins ##################################
		
		EURUSD = get_settings().get_eurusd()
		df_final = df_final.with_columns(
			(pl.col("eq_total_result") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("eq_total_result"),
			(pl.col("clos_opt_transactie_euro_totaal") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("clos_opt_transactie_euro_totaal"),
			(pl.col("clos_sp_transactie_euro_totaal") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("clos_sp_transactie_euro_totaal"),
			(pl.col("open_opt_total_result") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("open_opt_total_result"),
			(pl.col("open_sp_result") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("open_sp_result"),
			(pl.col("eq_total_fee") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("eq_total_fee"),
			(pl.col("clos_opt_transactie_fee") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("clos_opt_transactie_fee"),
			(pl.col("clos_sp_transactie_fee") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("clos_sp_transactie_fee"),
			(pl.col("open_opt_transactie_fee") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("open_opt_transactie_fee"),
			(pl.col("open_sp_transactie_fee") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("open_sp_transactie_fee"),
			(pl.col("div_en_bel") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("div_en_bel"),
			(pl.col("totaal") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("totaal"),
				pl.when(
				(pl.col("close_price").is_not_null()) & (pl.col("close_price") != 0)
			).then(
				(pl.col("koers") / pl.col("close_price")) - 1
			).otherwise(0).alias("pct_change")
		)
		########### Sum en berekende kolommen ###############
		if not df_final.is_empty():
			df_sum = df_final.group_by("asset_rollup", "koers","regio", "sector","value_grow","status","portfolio_total_waarde_lineair_pct","portfolio_total_waarde_delta_pct","close_price","pct_change").agg([
				pl.col("eq_aantal_bezit").sum().alias("eq_aantal_bezit"),
				pl.col("open_sp_aantal").sum().alias("open_sp_aantal"),
				pl.col("eq_total_result").sum().alias("eq_total_result"),
				pl.col("clos_opt_transactie_euro_totaal").sum().alias("clos_opt_transactie_euro_totaal"),
				pl.col("clos_sp_transactie_euro_totaal").sum().alias("clos_sp_transactie_euro_totaal"),
				pl.col("open_opt_total_result").sum().alias("open_opt_total_result"),
				pl.col("open_sp_result").sum().alias("open_sp_result"),
				pl.col("eq_total_fee").sum().alias("eq_total_fee"),
				pl.col("clos_opt_transactie_fee").sum().alias("clos_opt_transactie_fee"),
				pl.col("clos_sp_transactie_fee").sum().alias("clos_sp_transactie_fee"),
				pl.col("open_opt_transactie_fee").sum().alias("open_opt_transactie_fee"),
				pl.col("open_sp_transactie_fee").sum().alias("open_sp_transactie_fee"),
				pl.col("div_en_bel").sum().alias("div_en_bel"),
				pl.col("totaal").sum().alias("totaal"),
			]).with_columns([
				(
					pl.col("eq_total_result")
					+ pl.col("clos_opt_transactie_euro_totaal")
					+ pl.col("clos_sp_transactie_euro_totaal")
					+ pl.col("open_opt_total_result")
					+ pl.col("open_sp_result")
					+ pl.col("div_en_bel")
				).alias("totaal_ex_fee"),
				(
					pl.col("eq_total_result")
					+ pl.col("clos_opt_transactie_euro_totaal")
					+ pl.col("clos_sp_transactie_euro_totaal")
					+ pl.col("open_opt_total_result")
					+ pl.col("open_sp_result")
					+ pl.col("div_en_bel")
					+ pl.col("eq_total_fee")
					+ pl.col("clos_opt_transactie_fee")
					+ pl.col("clos_sp_transactie_fee")
					+ pl.col("open_opt_transactie_fee")
					+ pl.col("open_sp_transactie_fee")
				).alias("totaal_inc_fee"),
				(
					pl.col("eq_total_fee")
					+ pl.col("clos_opt_transactie_fee")
					+ pl.col("clos_sp_transactie_fee")
					+ pl.col("open_opt_transactie_fee")
					+ pl.col("open_sp_transactie_fee")
				).alias("totaal_fee"),
				# (
				# 	pl.col("totaal_inc_fee") 
				# 	- pl.col("totaal")
				# ).alias("net_change")
			])
		else:
			df_sum = df
		
		df_sum = df_sum.with_columns((pl.col("totaal_inc_fee")-pl.col("totaal")).alias("net_change"))


		########### einde Sum en berekende kolommen ##################################
		
		########### Kolom indeling ##################################
		df_sum = df_sum.select([
			"asset_rollup",
			pl.col("close_price").alias("koers_prev"),
			"koers",
			"pct_change",
			"eq_aantal_bezit",
			"open_sp_aantal",
			"eq_total_result",
			"clos_opt_transactie_euro_totaal",
			"clos_sp_transactie_euro_totaal",
			"open_opt_total_result",
			"open_sp_result",
			"div_en_bel",
			"totaal_ex_fee",
			"totaal_inc_fee",
			"net_change",
			"totaal_fee",
			"regio", "sector","value_grow","status","portfolio_total_waarde_lineair_pct","portfolio_total_waarde_delta_pct",
		])
		for col, filt_dict in (self.col_filters or {}).items():
			if col not in df_sum.columns:
				continue
			if "in" in filt_dict and filt_dict["in"]:
				df_sum = df_sum.filter(pl.col(col).is_in(list(filt_dict["in"])))

		kolommen = [
			"asset_rollup",
			"koers_prev",
			"koers",
			"pct_change",
			"eq_aantal_bezit",
			"open_sp_aantal",
			"eq_total_result",
			"clos_opt_transactie_euro_totaal",
			"clos_sp_transactie_euro_totaal",
			"open_opt_total_result",
			"open_sp_result",
			"div_en_bel",
			"totaal_ex_fee",
			"totaal_inc_fee",
			"net_change",
			"totaal_fee",
			"regio",
			"sector",
			"value_grow",
			"status",
			"portfolio_total_waarde_lineair_pct",
			"portfolio_total_waarde_delta_pct"
		]
		totalen = {}
		if not df_sum.is_empty():
			for col in kolommen:
				if col in ["asset_rollup", "regio", "sector", "value_grow", "status","koers_prev", "koers","pct_change","eq_aantal_bezit","open_sp_aantal"]:
					totalen[col] = "TOTAAL" if col == "asset_rollup" else ""
				elif col in df_sum.columns:
					totalen[col] = df_sum[col].sum()
				else:
					totalen[col] = ""
		else:
			for col in kolommen:
				totalen[col] = "TOTAAL" if col == "asset_rollup" else ""
		self.tblTotalen.setColumnCount(len(kolommen))
		for i, col in enumerate(kolommen):
			val = totalen[col]
			if col in ["portfolio_total_waarde_lineair_pct", "portfolio_total_waarde_delta_pct", "pct_change"]:
				# Format as percentage with 2 decimals, right aligned
				try:
					val_str = f"{float(val) * 100:.2f}%"
				except Exception:
					val_str = str(val)
			elif isinstance(val, float):
				if "fee" in col or "totaal" in col or "result" in col or "euro" in col:
					val_str = f"{val:,.2f}"
				else:
					val_str = f"{int(val)}"
			else:
				val_str = str(val)
			item = QTableWidgetItem(val_str)
			item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
			self.tblTotalen.setItem(0, i, item)

		# Format percentage columns in the main table as well
		self.model = PolarsTableModel(df_sum, self)
		# Patch the data method to format percentage columns
		orig_data_method = self.model.data
		def patched_data(index, role):
			colname = self.model._df.columns[index.column()]
			if role == Qt.DisplayRole:
				if colname in ["portfolio_total_waarde_lineair_pct", "portfolio_total_waarde_delta_pct", "pct_change"]:
					val = self.model._df[colname][index.row()]
					try:
						return f"{float(val) * 100:.2f}%"
					except Exception:
						return str(val)
				if colname == "koers_prev":
					val = self.model._df[colname][index.row()]
					try:
						return f"{float(val):.2f}"
					except Exception:
						return str(val)
			if role == Qt.TextAlignmentRole and colname == "koers_prev":
				return Qt.AlignRight | Qt.AlignVCenter
			return orig_data_method(index, role)
		self.model.data = patched_data

		self.proxy_model = QSortFilterProxyModel(self)
		self.proxy_model.setSourceModel(self.model)
		self.proxy_model.setSortRole(Qt.UserRole)
		self.tblAandelen.setModel(self.proxy_model)
		if self.current_sort_column >= 0:
			self.tblAandelen.sortByColumn(self.current_sort_column, self.current_sort_order)

	def open_broker_popup(self):
		from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
		df = SNAPSHOT_STORE.aggregator_snapshot_aandelen_live
		if df is None or df.is_empty() or "broker" not in df.columns:
			return
		brokers = sorted(b for b in set(df["broker"].to_list()) if b is not None)
		pre_selected = set(self.selected_brokers) if self.selected_brokers else set(brokers)
		popup = ColumnFilterPopup("Selecteer brokers", brokers, pre_selected, self)
		popup.acceptedSelection.connect(self.set_broker_selection)
		popup.exec()

	def on_broker_selection_changed(self, idx):
		self.reload_data()

	def set_broker_selection(self, selected: set):
		self.selected_brokers = selected
		self.reload_data()

	def on_engine_data_update(self):
		if hasattr(self, 'tblAandelen') and self.tblAandelen.model() is not None:
			header = self.tblAandelen.horizontalHeader()
			self.current_sort_column = header.sortIndicatorSection()
			self.current_sort_order = header.sortIndicatorOrder()
		self.reload_data()

	@Slot(str, str, float)
	def on_ticker_display(self, sym: str, cur: str, px: float):
		# print(f"[DEBUG] on_ticker_display: {sym} {cur} {px}")
		# Live ticker label updaten (vereist lblLiveTicker in UI)
		if hasattr(self, 'lblLiveTicker'):
			self.lblLiveTicker.setText(f"📈 Koersupdate voor {sym} ({cur}): {px:.2f}")


	def on_price_update(self, *args):
		# Deze functie wordt niet meer direct gebruikt voor tabel updates
		pass

	def on_header_menu(self, pos):
		header = self.tblAandelen.horizontalHeader()
		section = header.logicalIndexAt(pos)
		try:
			colname = self.model._df.columns[section]
		except Exception:
			return
		from PySide6.QtWidgets import QMenu
		menu = QMenu(self)
		a_pick = menu.addAction("Waarden kiezen…")
		act = menu.exec(header.mapToGlobal(pos))
		if act == a_pick:
			self._open_value_popup_for_column(colname, header.mapToGlobal(pos))



	def _open_value_popup_for_column(self, colname: str, global_pos=None):
		df = self.model._df
		if df is None or df.is_empty() or colname not in df.columns:
			return
		values = sorted(x for x in set(df[colname].to_list()) if x is not None)
		pre = set(self.col_filters[colname]["in"]) if colname in self.col_filters and "in" in self.col_filters[colname] else set(values)
		pop = ColumnFilterPopup(f"Filter: {colname}", values, pre_selected=pre, parent=self)
		if global_pos:
			pop.move(global_pos)
		pop.acceptedSelection.connect(lambda selected: self._apply_in_filter(colname, selected))
		pop.cleared.connect(lambda: self._clear_col_filter(colname))
		pop.show()

	def _apply_in_filter(self, colname: str, selected: set):
		if not selected:
			self.col_filters.pop(colname, None)
		else:
			self.col_filters[colname] = {"in": selected}
		self.reload_data()

	def _clear_col_filter(self, colname: str):
		self.col_filters.pop(colname, None)
		self.reload_data()

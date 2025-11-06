# Logica voor de AandelenTab, gekoppeld aan de Designer UI (Ui_AandelenTab)
from PySide6.QtWidgets import QWidget, QTableWidgetItem
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
		
		from PySide6.QtWidgets import QFileDialog, QMessageBox
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
	Kolommen: asset_rollup, koers, aantal_bezit, result_realised, result_non_realised
	"""
	def __init__(self, portfolio_engine=None, pricefeed=None, parent=None):
		print("[DEBUG] AandelenTab __init__ aangeroepen")
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
		print("[DEBUG] self.pricefeed in tab bij connect:", self.pricefeed, id(self.pricefeed) if self.pricefeed else None)


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
		SNAPSHOT_STORE.test_repository_load_output_test_dataframe = df_aandelen_sum

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
		if not df_open_sprinters.is_empty():
			df_open_sp_sum = df_open_sprinters.group_by("asset_rollup").agg([
				pl.col("sp_result").sum().alias("open_sp_result"),
				pl.col("SomVantransactie_fee").sum().alias("open_sp_transactie_fee"),
				pl.col("SomVantransactie_aantal").sum().alias("open_sp_aantal"),
			])
		else:
			df_open_sp_sum = df_open_sprinters
		

		df_dividend = SNAPSHOT_STORE.repository_portfolio_dividend
		if self.selected_brokers is not None and "broker" in df.columns:
			df_dividend = df_dividend.filter(pl.col("broker").is_in(list(self.selected_brokers)))
		if not df_dividend.is_empty():
			df_div_bel = df_dividend.group_by("asset_rollup").agg([
				pl.col("div_en_bel").sum().alias("div_en_bel"),
			])
		else:
			df_div_bel = df_dividend
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
			(pl.col("div_en_bel") / pl.when(pl.col("regio") == "US").then(EURUSD).otherwise(1)).alias("div_en_bel")
		)
        ########### Sum en berekende kolommen ###############
		if not df_final.is_empty():
			df_sum = df_final.group_by("asset_rollup", "koers","regio", "sector","value_grow").agg([
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
				).alias("totaal_fee")
			])
		else:
			df_sum = df
        ########### einde Sum en berekende kolommen ##################################
        
        ########### Kolom indeling ##################################
		df_sum = df_sum.select([
			"asset_rollup",
			"koers",
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
			"totaal_fee",
			"regio", "sector","value_grow"
		])
		for col, filt_dict in (self.col_filters or {}).items():
			if col not in df_sum.columns:
				continue
			if "in" in filt_dict and filt_dict["in"]:
				df_sum = df_sum.filter(pl.col(col).is_in(list(filt_dict["in"])))

		kolommen = [
			"asset_rollup",
			"koers",
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
			"totaal_fee",
			"regio",
			"sector",
			"value_grow"
		]
		totalen = {}
		if not df_sum.is_empty():
			for col in kolommen:
				if col in ["asset_rollup", "regio", "sector", "value_grow"]:
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
			if isinstance(val, float):
				if "fee" in col or "totaal" in col or "result" in col or "euro" in col:
					val_str = f"{val:,.2f}"
				else:
					val_str = f"{int(val)}"
			else:
				val_str = str(val)
			item = QTableWidgetItem(val_str)
			item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
			self.tblTotalen.setItem(0, i, item)

		self.model = PolarsTableModel(df_sum, self)
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
		values = sorted(set(df[colname].to_list()))
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

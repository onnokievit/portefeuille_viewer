# Logica voor de AandelenTab, gekoppeld aan de Designer UI (Ui_AandelenTab)
from PySide6.QtWidgets import QWidget, QTableWidgetItem, QFileDialog, QMessageBox, QStyledItemDelegate, QStyle, QHeaderView, QHBoxLayout, QSizePolicy
from PySide6.QtCore import Slot, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtWidgets import QTableWidget
from PySide6.QtGui import QColor

from portefeuille_viewer.ui.aandelen_tab_ui import Ui_AandelenTab
from portefeuille_viewer.domain.portfolio_engine import PortfolioEngine
from portefeuille_viewer.ui.models import PolarsTableModel
from portefeuille_viewer.ui.filter_popup import ColumnFilterPopup
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals
from portefeuille_viewer.services.aandelen_tab_summary import build_aandelen_tab_summary
import polars as pl

class CustomSelectionDelegate(QStyledItemDelegate):
	def paint(self, painter, option, index):
		if option.state & QStyle.State_Selected:
			painter.save()
			painter.fillRect(option.rect, QColor("#FFF2CC"))  # selectie-kleur
			painter.setPen(QColor(0, 0, 0))
			text = index.data(Qt.DisplayRole)
			if index.data(Qt.TextAlignmentRole) is not None:
				alignment = index.data(Qt.TextAlignmentRole)
			else:
				alignment = option.displayAlignment if hasattr(option, 'displayAlignment') else Qt.AlignVCenter | Qt.AlignLeft
			painter.drawText(option.rect, alignment, str(text))
			painter.restore()
		elif option.state & QStyle.State_MouseOver:
			painter.save()
			painter.fillRect(option.rect, QColor("#E6F2FF"))  # hover-kleur
			painter.setPen(QColor(0, 0, 0))
			text = index.data(Qt.DisplayRole)
			if index.data(Qt.TextAlignmentRole) is not None:
				alignment = index.data(Qt.TextAlignmentRole)
			else:
				alignment = option.displayAlignment if hasattr(option, 'displayAlignment') else Qt.AlignVCenter | Qt.AlignLeft
			painter.drawText(option.rect, alignment, str(text))
			painter.restore()
		else:
			super().paint(painter, option, index)



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
		self._active = False
		self._dirty = False
		self._reload_timer = QTimer(self)
		self._reload_timer.setInterval(500)
		self._reload_timer.setSingleShot(True)
		self._reload_timer.timeout.connect(self._reload_if_needed)
		# Losse throttle voor optie-timevalue updates zodat deze tab niet continu herlaadt.
		self._option_tv_reload_timer = QTimer(self)
		self._option_tv_reload_timer.setInterval(5000)  # vaste update-cadans
		self._option_tv_reload_timer.setSingleShot(True)
		self._option_tv_reload_timer.timeout.connect(self._reload_if_needed)

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
		self.tblAandelen.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
		self.tblAandelen.verticalHeader().setDefaultSectionSize(20)
		self.tblAandelen.horizontalHeader().setStretchLastSection(False)

		self.tblTotalen.setFixedHeight(32)
		self.tblTotalen.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
		self.tblTotalen.verticalHeader().setVisible(False)
		self.tblTotalen.horizontalHeader().setVisible(False)
		self.tblTotalen.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		self.tblTotalen.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		self.tblTotalen.horizontalHeader().setStretchLastSection(False)
		
		self.tblTotalen.setEditTriggers(QTableWidget.NoEditTriggers)
		self.tblTotalen.setFocusPolicy(Qt.NoFocus)
		self.tblTotalen.setSelectionMode(QTableWidget.NoSelection)
		self._wrap_footer_in_container()
		self._init_footer_sync()
		self._header_bg_color = get_settings().get_table_header_bg()
		self._total_bg_color = get_settings().get_table_total_bg()
		self._apply_header_style()
		signals.uiStyleChanged.connect(self._on_ui_style_changed)

		self._display_cache = {}
		self._pct_change_bg_cache = []
		self.model = PolarsTableModel(pl.DataFrame(), self)
		orig_data_method = self.model.data
		def patched_data(index, role):
			if not index.isValid():
				return orig_data_method(index, role)
			if self.model._df.is_empty():
				return orig_data_method(index, role)
			colname = self.model._df.columns[index.column()]
			if role == Qt.DisplayRole and colname in self._display_cache:
				return self._display_cache[colname][index.row()]
			if role == Qt.TextAlignmentRole and colname == "koers_prev":
				return Qt.AlignRight | Qt.AlignVCenter
			if role == Qt.BackgroundRole and colname == "pct_change":
				if 0 <= index.row() < len(self._pct_change_bg_cache):
					return self._pct_change_bg_cache[index.row()]
				return None
			return orig_data_method(index, role)
		self.model.data = patched_data

		self.proxy_model = QSortFilterProxyModel(self)
		self.proxy_model.setSourceModel(self.model)
		self.proxy_model.setSortRole(Qt.UserRole)
		self.tblAandelen.setModel(self.proxy_model)
		# Custom selectie-kleur voor geselecteerde rijen
		self.tblAandelen.setItemDelegate(CustomSelectionDelegate(self.tblAandelen))

		# Initieel laden
		self.reload_data()

		# Koppel live update: alleen via PortfolioEngine
		if hasattr(self.engine, 'dataUpdated'):
			self.engine.dataUpdated.connect(self.on_engine_data_update)
		signals.snapshotUpdated.connect(self._on_snapshot_updated)
		# print("[DEBUG] self.pricefeed in tab bij connect:", self.pricefeed, id(self.pricefeed) if self.pricefeed else None)

	def clear_all_filters(self):
		self.col_filters.clear()
		self.selected_brokers = None
		self.reload_data()

	def on_sort_changed(self, column, order):
		self.current_sort_column = column
		self.current_sort_order = order

	def reload_data(self):
		df_sum = build_aandelen_tab_summary(self.selected_brokers)
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
			#"totaal_prev",
			"totaal_fee",
			"regio",
			"sector",
			"value_grow",
			"status",
			"portfolio_total_waarde_lineair_pct",
			"portfolio_total_waarde_delta_pct",
			"optie_tijdswaarde_signed_eur",
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
			if col == "asset_rollup":
				item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
			else:
				item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
			item.setBackground(QColor(self._total_bg_color))
			self.tblTotalen.setItem(0, i, item)

		# Cache voor display-strings en kleuren op basis van pct_change
		self._display_cache = {}
		self._pct_change_bg_cache = []
		display_cols = ["portfolio_total_waarde_lineair_pct", "portfolio_total_waarde_delta_pct", "pct_change", "koers_prev"]
		for colname in display_cols:
			if colname in df_sum.columns:
				values = df_sum[colname].to_list()
				if colname in ["portfolio_total_waarde_lineair_pct", "portfolio_total_waarde_delta_pct", "pct_change"]:
					self._display_cache[colname] = [
						(f"{float(v) * 100:.2f}%") if v is not None else "" for v in values
					]
				elif colname == "koers_prev":
					self._display_cache[colname] = [
						(f"{float(v):.2f}") if v is not None else "" for v in values
					]
		def interpolate_color(val, min_val, mid_val, max_val, color_min, color_mid, color_max):
			if val <= min_val:
				return QColor(*color_min)
			elif val >= max_val:
				return QColor(*color_max)
			elif val < mid_val:
				ratio = (val - min_val) / (mid_val - min_val)
				r = color_min[0] + ratio * (color_mid[0] - color_min[0])
				g = color_min[1] + ratio * (color_mid[1] - color_min[1])
				b = color_min[2] + ratio * (color_mid[2] - color_min[2])
				return QColor(int(r), int(g), int(b))
			else:
				ratio = (val - mid_val) / (max_val - mid_val)
				r = color_mid[0] + ratio * (color_max[0] - color_mid[0])
				g = color_mid[1] + ratio * (color_max[1] - color_mid[1])
				b = color_mid[2] + ratio * (color_max[2] - color_mid[2])
				return QColor(int(r), int(g), int(b))

		if "pct_change" in df_sum.columns and not df_sum.is_empty():
			for v in df_sum["pct_change"].to_list():
				try:
					val = float(v)
				except Exception:
					self._pct_change_bg_cache.append(None)
					continue
				self._pct_change_bg_cache.append(
					interpolate_color(
						val, -0.02, 0, 0.02,
						(255, 102, 102),  # rood
						(255, 255, 255),  # wit
						(153, 255, 153)   # groen
					)
				)

		self.model.set_df(df_sum)
		if self.current_sort_column < 0:
			try:
				self.current_sort_column = df_sum.columns.index("asset_rollup")
				self.current_sort_order = Qt.AscendingOrder
			except Exception:
				self.current_sort_column = 0
				self.current_sort_order = Qt.AscendingOrder
		self.tblAandelen.sortByColumn(self.current_sort_column, self.current_sort_order)
		self._sync_footer_section_sizes()
		self._sync_footer_scrollbar_gap()

	def set_active(self, active: bool):
		self._active = active
		if active and self._dirty:
			self._schedule_reload()

	def _schedule_reload(self):
		self._dirty = True
		if not self._reload_timer.isActive():
			self._reload_timer.start()

	def _reload_if_needed(self):
		if not self._active:
			return
		if self._dirty:
			self._dirty = False
			self.reload_data()

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
		if not self._active:
			self._dirty = True
			return
		self._schedule_reload()

	def _on_snapshot_updated(self, snapshot_key: str):
		# Optie tijdswaarde heeft eigen feed/service; refresh Aandelen-tab bij update.
		if snapshot_key == "snapshot_optie_timevalue_live":
			if not self._active:
				self._dirty = True
				return
			self._dirty = True
			if not self._option_tv_reload_timer.isActive():
				self._option_tv_reload_timer.start()

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

	def _init_footer_sync(self):
		"""Houd de totalen-rij visueel in sync met de hoofd-tabel."""
		main_header = self.tblAandelen.horizontalHeader()
		footer_header = self.tblTotalen.horizontalHeader()

		# Houd kolombreedtes gelijk
		main_header.sectionResized.connect(
			lambda idx, _old, new: self.tblTotalen.setColumnWidth(idx, new)
		)
		# Houd kolomvolgorde gelijk (als de gebruiker kolommen versleept)
		main_header.sectionMoved.connect(
			lambda logical, _old, new: footer_header.moveSection(footer_header.visualIndex(logical), new)
		)

		# Synchroniseer horizontale scroll
		main_scroll = self.tblAandelen.horizontalScrollBar()
		footer_scroll = self.tblTotalen.horizontalScrollBar()
		main_scroll.valueChanged.connect(footer_scroll.setValue)
		main_scroll.rangeChanged.connect(lambda _min, _max: self._sync_footer_scrollbar_gap())
		self.tblAandelen.verticalScrollBar().rangeChanged.connect(
			lambda _min, _max: self._sync_footer_scrollbar_gap()
		)

	def _sync_footer_section_sizes(self):
		"""Initiele sync van kolombreedtes en scrollpositie."""
		main_header = self.tblAandelen.horizontalHeader()
		for i in range(main_header.count()):
			self.tblTotalen.setColumnWidth(i, main_header.sectionSize(i))
		self.tblTotalen.horizontalScrollBar().setValue(
			self.tblAandelen.horizontalScrollBar().value()
		)

	def _sync_footer_scrollbar_gap(self):
		"""Reserveer dezelfde scrollbar-ruimte als de hoofd-tabel om verspringen te voorkomen."""
		v_scroll = self.tblAandelen.verticalScrollBar()
		scroll_width = v_scroll.sizeHint().width() if v_scroll.maximum() > 0 else 0
		if hasattr(self, "_footer_spacer") and self._footer_spacer is not None:
			self._footer_spacer.setFixedWidth(scroll_width)

	def _apply_header_style(self):
		style = f"QHeaderView::section {{ background-color: {self._header_bg_color}; }}"
		self.tblAandelen.horizontalHeader().setStyleSheet(style)
		self.tblTotalen.horizontalHeader().setStyleSheet(style)

	def _apply_total_row_bg(self):
		for col_idx in range(self.tblTotalen.columnCount()):
			item = self.tblTotalen.item(0, col_idx)
			if item is not None:
				item.setBackground(QColor(self._total_bg_color))

	def _on_ui_style_changed(self, key: str):
		if key == "table_header_bg":
			self._header_bg_color = get_settings().get_table_header_bg()
			self._apply_header_style()
		elif key == "table_total_bg":
			self._total_bg_color = get_settings().get_table_total_bg()
			self._apply_total_row_bg()

	def _wrap_footer_in_container(self):
		"""Plaats de totalen-tabel in een container met spacer voor scrollbar-ruimte."""
		if hasattr(self, "_footer_container") and self._footer_container is not None:
			return
		self._footer_container = QWidget(self)
		self._footer_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
		footer_layout = QHBoxLayout(self._footer_container)
		footer_layout.setContentsMargins(0, 0, 0, 0)
		footer_layout.setSpacing(0)
		self._footer_spacer = QWidget(self._footer_container)
		self._footer_spacer.setFixedWidth(0)

		main_layout = self.verticalLayout_main
		main_layout.removeWidget(self.tblTotalen)
		self.tblTotalen.setParent(self._footer_container)
		footer_layout.addWidget(self.tblTotalen)
		footer_layout.addWidget(self._footer_spacer)
		main_layout.addWidget(self._footer_container)
		main_layout.setStretchFactor(self.tblAandelen, 1)
		main_layout.setStretchFactor(self._footer_container, 0)

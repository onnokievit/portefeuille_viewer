from PySide6.QtWidgets import QWidget, QHeaderView, QTableWidget, QTableWidgetItem, QHBoxLayout, QSizePolicy
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QTimer
from PySide6.QtGui import QColor, QBrush
import polars as pl
import contextlib

from portefeuille_viewer.ui.portfolio_value_ui import Ui_Form
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals
from portefeuille_viewer.ui.filter_popup import HeaderFilterMenuMixin
from portefeuille_viewer.config import get_settings

class PercentColoredPolarsModel(QAbstractTableModel):
    """
    Minimal Polars-backed table model that color-codes two percent columns:
    - portfolio_total_waarde_lineair_pct
    - portfolio_total_waarde_delta_pct

    Background gradient: red (low) → yellow (mid) → green (high).
    """
    def __init__(self, df: pl.DataFrame | None = None, parent=None):
        super().__init__(parent)
        self._df = df if isinstance(df, pl.DataFrame) else pl.DataFrame({})
        self._cols = list(self._df.columns)
        self._pct_cols = {
            "portfolio_total_waarde_lineair_pct",
            "portfolio_total_waarde_delta_pct",
        }
        # Store min/max per pct col for color mapping
        self._col_minmax = {col: (0.0, 1.0) for col in self._pct_cols}

    def set_df(self, df: pl.DataFrame | None):
        self.beginResetModel()
        self._df = df if isinstance(df, pl.DataFrame) else pl.DataFrame({})
        self._cols = list(self._df.columns)
        # Calculate min/max for each percent column for color mapping
        self._col_minmax = {}
        for col in self._pct_cols:
            if col in self._df.columns and not self._df.is_empty():
                try:
                    vals = self._df[col].to_numpy()
                    vals = [float(v) for v in vals if v is not None]
                    if vals:
                        minv, maxv = min(vals), max(vals)
                        # If min==max, avoid div by zero
                        if minv == maxv:
                            minv, maxv = 0.0, maxv
                        self._col_minmax[col] = (minv, maxv)
                    else:
                        self._col_minmax[col] = (0.0, 1.0)
                except Exception:
                    self._col_minmax[col] = (0.0, 1.0)
            else:
                self._col_minmax[col] = (0.0, 1.0)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if self._df.is_empty() else self._df.height

    def columnCount(self, parent=QModelIndex()):
        return 0 if self._df.is_empty() else self._df.width

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._cols[section]
        return str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self._df.is_empty():
            return None
        row = index.row()
        col = index.column()
        colname = self._cols[col]
        val = self._df[row, col]

        if role == Qt.DisplayRole:
            if val is None:
                return ""
            # Show as percentage with one decimal for the target cols
            if colname in self._pct_cols:
                try:
                    f = float(val)
                    return f"{f*100:.1f}%"
                except Exception:
                    return str(val)
            # Custom formatting for total_waarde_lineair and total_waarde_delta
            if colname in ("total_waarde_lineair", "total_waarde_delta"):
                try:
                    f = float(val)
                    # Format: 0 decimals, thousands separator (.), right aligned
                    s = f"{int(round(f)):,}".replace(",", ".")
                    return s
                except Exception:
                    return str(val)
            if colname in (
                "aand_aantal_bezit",
                "aantal_sprinters",
                "opt_aantal_ITM_put",
                "opt_aantal_OTM_put",
                "opt_aantal_ITM_call",
                "opt_aantal_OTM_call",
            ):
                try:
                    s = f"{int(round(abs(float(val)))):,}".replace(",", ".")
                    return s
                except Exception:
                    return str(val)
            # Custom formatting for koers column
            if colname == "koers":
                try:
                    f = float(val)
                    return f"{f:,.2f}".replace(",", ".")
                except Exception:
                    return str(val)
            # default string
            return str(val)

        if role == Qt.UserRole:
            # Sorteerbare waarde voor alle kolommen
            if colname in self._pct_cols:
                # percentages als float (0–1)
                try:
                    return float(val)
                except Exception:
                    return 0.0
            else:
                # voor andere kolommen: eerst proberen numeriek, anders string
                try:
                    return float(val)
                except Exception:
                    return "" if val is None else str(val)

        if role == Qt.TextAlignmentRole:
            if colname in self._pct_cols or colname in (
                "total_waarde_lineair",
                "total_waarde_delta",
                "koers",
                "aand_aantal_bezit",
                "aantal_sprinters",
                "opt_aantal_ITM_put",
                "opt_aantal_OTM_put",
                "opt_aantal_ITM_call",
                "opt_aantal_OTM_call",
            ):
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        # Red background for negative values in total_waarde_lineair and total_waarde_delta
        if role == Qt.BackgroundRole:
            if colname in self._pct_cols:
                # ...existing code for gradient...
                try:
                    f = float(val)
                except Exception:
                    f = 0.0
                minv, maxv = self._col_minmax.get(colname, (0.0, 1.0))
                # Avoid div by zero
                if maxv - minv == 0:
                    t = 0.0
                else:
                    t = (f - minv) / (maxv - minv)
                    t = max(0.0, min(1.0, t))
                # Groen (0,180,90) → Geel (255,255,160) → Rood (255,90,90)
                # t=0: groen, t=0.5: geel, t=1: rood
                if t < 0.5:
                    # Groen naar geel
                    t2 = t / 0.5
                    r = int(0 + (255 - 0) * t2)
                    g = int(180 + (255 - 180) * t2)
                    b = int(90 + (160 - 90) * t2)
                else:
                    # Geel naar rood
                    t2 = (t - 0.5) / 0.5
                    r = int(255)
                    g = int(255 - (255 - 90) * t2)
                    b = int(160 - (160 - 90) * t2)
                color = QColor(r, g, b)
                return QBrush(color)
            if colname in ("total_waarde_lineair", "total_waarde_delta"):
                try:
                    f = float(val)
                    if f < 0:
                        return QBrush(QColor(255, 90, 90))  # Red for negative
                except Exception:
                    pass
        return None
        

class PortfolioValueTab(QWidget, Ui_Form, HeaderFilterMenuMixin):
    """Logic for the portfolio value tab: load snapshot and display colored table."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_Form()
        self.ui.setupUi(self)
        # Alias voor HeaderFilterMenuMixin-verwachting
        self.tableView = self.ui.tableView
        self._table_model = None
        self._col_filters = {}
        self.current_sort_column = -1
        self.current_sort_order = 0

        # Model setup (met proxy voor sorteren/filteren)
        self.model = PercentColoredPolarsModel(pl.DataFrame({}), self)
        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        # Sorteer op numerieke UserRole (bv. percentages als float)
        self.proxy_model.setSortRole(Qt.UserRole)
        self.ui.tableView.setModel(self.proxy_model)
        self._table_model = self.model

        self._header_bg_color = get_settings().get_table_header_bg()
        self._total_bg_color = get_settings().get_table_total_bg()
        self._init_totals_footer()
        self._apply_header_style()

        # Filter comboboxes (supports older UI names as fallback)
        self._sector_combo_label = "Alle sectoren"
        self._value_grow_combo_label = "Waarde & groei"
        self._region_combo_label = "Alle regions"
        self.comboBoxSector = getattr(self.ui, "comboBoxSector", None) or getattr(self.ui, "comboBox", None)
        if self.comboBoxSector is not None:
            self.comboBoxSector.currentTextChanged.connect(self._on_sector_changed)
        self.comboBoxValueGrow = getattr(self.ui, "comboBoxValueGrow", None) or getattr(self.ui, "comboBox_2", None)
        if self.comboBoxValueGrow is not None:
            self.comboBoxValueGrow.currentTextChanged.connect(self._on_value_grow_changed)
        self.comboBoxRegion = getattr(self.ui, "comboBoxRegion", None) or getattr(self.ui, "comboBox_3", None)
        if self.comboBoxRegion is not None:
            self.comboBoxRegion.currentTextChanged.connect(self._on_region_changed)
        self.btnClearFilter = getattr(self.ui, "btnClearFilter", None) or getattr(self.ui, "pushButton_2", None)
        if self.btnClearFilter is not None:
            self.btnClearFilter.clicked.connect(self._on_clear_filters_clicked)

        # Header contextmenu voor filters/sorteren
        header = self.ui.tableView.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self.on_header_menu)
        header.sectionClicked.connect(self._on_header_clicked)

        # Table UX tweaks
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        # Gebruik standaardfont uit de UI en zelfde rijhoogte als OptiesOpen
        self.ui.tableView.verticalHeader().setVisible(False)
        self.ui.tableView.verticalHeader().setDefaultSectionSize(18)

        # Initial load
        self.reload_snapshot()

        # Debounced reload on relevant snapshot updates, so we refresh after
        # transaction-derived rebuild has actually written the new snapshots.
        self._snapshot_reload_timer = QTimer(self)
        self._snapshot_reload_timer.setSingleShot(True)
        self._snapshot_reload_timer.setInterval(150)
        self._snapshot_reload_timer.timeout.connect(self.reload_snapshot)
        self._watched_snapshot_keys = {
            "repository_snapshot_portfolio_value_total_combined_put",
            "repository_snapshot_portfolio_value_total_combined_scenario",
            "repository_snapshot_portfolio_value_aandelen",
            "repository_snapshot_portfolio_value_optie",
            "repository_snapshot_portfolio_value_optie_call_put_detailed",
            "repository_snapshot_portfolio_value_sprinters",
        }

        # React to central signals: reload when relevant snapshots are rewritten.
        def _on_snapshot_updated(snapshot_key: str):
            with contextlib.suppress(Exception):
                if snapshot_key in self._watched_snapshot_keys:
                    # Collapse bursts of writes into one UI reload.
                    self._snapshot_reload_timer.start()
        def _on_state_rebuild_finished(payload: dict | None):
            with contextlib.suppress(Exception):
                if (payload or {}).get("status") == "ok":
                    self.reload_snapshot()
        signals.snapshotUpdated.connect(_on_snapshot_updated)
        signals.stateRebuildFinished.connect(_on_state_rebuild_finished)
        signals.uiStyleChanged.connect(self._on_ui_style_changed)

    def _on_header_clicked(self, section: int):
        """Klik op kolomheader toggelt sorteerorde via proxy model."""
        current_section = self.current_sort_column
        current_order = self.current_sort_order
        if section == current_section:
            # Toggle tussen ascending/descending
            order = Qt.DescendingOrder if current_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            order = Qt.AscendingOrder
        self.current_sort_column = section
        self.current_sort_order = order
        self.tableView.sortByColumn(section, order)

    def apply_filters(self):
        """Bouw intern filters-dict op basis van _col_filters en herlaad de snapshot."""
        filters = {}
        for col, spec in (self._col_filters or {}).items():
            if "in" in spec:
                filters[f"__in__{col}"] = list(spec["in"])
            if "contains" in spec:
                filters[f"__contains__{col}"] = spec["contains"]
            if "eq" in spec:
                filters[f"__eq__{col}"] = spec["eq"]
        self.active_filters = filters
        self.reload_snapshot()

    def _load_initial_records(self):
        """Compat-methode voor HeaderFilterMenuMixin; herlaadt de snapshot."""
        self.reload_snapshot()

    def _apply_in_filter(self, colname, selected):
        if not selected:
            self._col_filters.pop(colname, None)
        else:
            self._col_filters[colname] = {"in": selected}
        self.apply_filters()

    def _on_sector_changed(self, text: str):
        if not text or text == self._sector_combo_label:
            self._col_filters.pop("sector", None)
        else:
            self._col_filters["sector"] = {"eq": text}
        self.apply_filters()

    def _on_clear_filters_clicked(self):
        if self.comboBoxSector is not None:
            self.comboBoxSector.blockSignals(True)
            self.comboBoxSector.setCurrentIndex(0)
            self.comboBoxSector.blockSignals(False)
        if self.comboBoxValueGrow is not None:
            self.comboBoxValueGrow.blockSignals(True)
            self.comboBoxValueGrow.setCurrentIndex(0)
            self.comboBoxValueGrow.blockSignals(False)
        if self.comboBoxRegion is not None:
            self.comboBoxRegion.blockSignals(True)
            self.comboBoxRegion.setCurrentIndex(0)
            self.comboBoxRegion.blockSignals(False)
        self._col_filters.clear()
        self.apply_filters()

    def _refresh_sector_combo(self, df: pl.DataFrame):
        if self.comboBoxSector is None:
            return
        sectors = []
        if df is not None and not df.is_empty() and "sector" in df.columns:
            sectors = [
                str(v) for v in df["sector"].unique().to_list()
                if v is not None and str(v).strip() != ""
            ]
        sectors = sorted(set(sectors), key=str.lower)
        current = self.comboBoxSector.currentText()
        self.comboBoxSector.blockSignals(True)
        self.comboBoxSector.clear()
        self.comboBoxSector.addItem(self._sector_combo_label)
        for sector in sectors:
            self.comboBoxSector.addItem(sector)
        if current and current in sectors:
            self.comboBoxSector.setCurrentText(current)
        else:
            self.comboBoxSector.setCurrentIndex(0)
        self.comboBoxSector.blockSignals(False)

    def _on_value_grow_changed(self, text: str):
        if not text or text == self._value_grow_combo_label:
            self._col_filters.pop("value_grow", None)
        else:
            self._col_filters["value_grow"] = {"eq": text}
        self.apply_filters()

    def _refresh_value_grow_combo(self, df: pl.DataFrame):
        if self.comboBoxValueGrow is None:
            return
        values = []
        if df is not None and not df.is_empty() and "value_grow" in df.columns:
            values = [
                str(v) for v in df["value_grow"].unique().to_list()
                if v is not None and str(v).strip() != ""
            ]
        values = sorted(set(values), key=str.lower)
        current = self.comboBoxValueGrow.currentText()
        self.comboBoxValueGrow.blockSignals(True)
        self.comboBoxValueGrow.clear()
        self.comboBoxValueGrow.addItem(self._value_grow_combo_label)
        for val in values:
            self.comboBoxValueGrow.addItem(val)
        if current and current in values:
            self.comboBoxValueGrow.setCurrentText(current)
        else:
            self.comboBoxValueGrow.setCurrentIndex(0)
        self.comboBoxValueGrow.blockSignals(False)

    def _on_region_changed(self, text: str):
        col = getattr(self, "_region_col", "regio")
        if not text or text == self._region_combo_label:
            self._col_filters.pop(col, None)
        else:
            self._col_filters[col] = {"eq": text}
        self.apply_filters()

    def _refresh_region_combo(self, df: pl.DataFrame):
        if self.comboBoxRegion is None:
            return
        col = "regio"
        if df is not None and "regio" not in df.columns and "region" in df.columns:
            col = "region"
        self._region_col = col
        values = []
        if df is not None and not df.is_empty() and col in df.columns:
            values = [
                str(v) for v in df[col].unique().to_list()
                if v is not None and str(v).strip() != ""
            ]
        values = sorted(set(values), key=str.lower)
        current = self.comboBoxRegion.currentText()
        self.comboBoxRegion.blockSignals(True)
        self.comboBoxRegion.clear()
        self.comboBoxRegion.addItem(self._region_combo_label)
        for val in values:
            self.comboBoxRegion.addItem(val)
        if current and current in values:
            self.comboBoxRegion.setCurrentText(current)
        else:
            self.comboBoxRegion.setCurrentIndex(0)
        self.comboBoxRegion.blockSignals(False)

    def reload_snapshot(self):
        # Expected snapshot key: repository_snapshot_portfolio_value_total_combined
        # print("🔄 PortfolioValueTab: snapshot herladen...")
        df = None
        if bool(getattr(SNAPSHOT_STORE, "runtime_test_orders_enabled", False)):
            df = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_total_combined_scenario", None)
        if df is None:
            df = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_total_combined_put", None)
        if df is None or (hasattr(df, "is_empty") and df.is_empty()):
            self.model.set_df(pl.DataFrame({}))
            self._clear_totals()
            return
        # Ensure percent cols exist; if missing, derive safely
        # df = df.drop("aand_aantal_bezit")



        cols_to_keep = [
            "asset_rollup",
            "regio",
            "sector",
            "value_grow",
            "koers",
            "aand_aantal_bezit",
            "aantal_sprinters",
            "opt_aantal_ITM_put",
            "opt_aantal_OTM_put",
            "opt_aantal_ITM_call",
            "opt_aantal_OTM_call",
            "total_waarde_lineair",
            "total_waarde_delta",
            "portfolio_total_waarde_lineair_pct",
            "portfolio_total_waarde_delta_pct",
            # enzovoort: alleen wat je in deze tab wilt tonen/filteren
        ]
        df = df.select([c for c in cols_to_keep if c in df.columns])
        self._refresh_sector_combo(df)
        self._refresh_value_grow_combo(df)
        self._refresh_region_combo(df)

        df = self._ensure_percent_columns(df)

        filters = getattr(self, "active_filters", {})
        if filters:
            for key, value in filters.items():
                if key.startswith("__in__"):
                    col = key.replace("__in__", "")
                    if col in df.columns:
                        df = df.filter(pl.col(col).is_in(value))
                elif key.startswith("__contains__"):
                    col = key.replace("__contains__", "")
                    if col in df.columns:
                        df = df.filter(pl.col(col).cast(str).str.contains(value))
                elif key.startswith("__eq__"):
                    col = key.replace("__eq__", "")
                    if col in df.columns:
                        df = df.filter(pl.col(col) == value)

        self.model.set_df(df)
        self._apply_column_widths(df)
        self._update_totals(df)
        self._sync_footer_section_sizes()
        self._sync_footer_scrollbar_gap()


    def _ensure_percent_columns(self, df: pl.DataFrame) -> pl.DataFrame:
        cols = set(df.columns)
        need_lineair = "portfolio_total_waarde_lineair_pct" not in cols
        need_delta = "portfolio_total_waarde_delta_pct" not in cols
        if not (need_lineair or need_delta):
            return df
        # Try to compute if totals exist
        total_lineair = None
        total_delta = None
        try:
            if "total_waarde_lineair" in cols:
                total_lineair = float(df["total_waarde_lineair"].sum())
            if "total_waarde_delta" in cols:
                total_delta = float(df["total_waarde_delta"].sum())
        except Exception:
            pass
        exprs = []
        if need_lineair and total_lineair and total_lineair != 0:
            exprs.append((pl.col("total_waarde_lineair") / total_lineair).alias("portfolio_total_waarde_lineair_pct"))
        if need_delta and total_delta and total_delta != 0:
            exprs.append((pl.col("total_waarde_delta") / total_delta).alias("portfolio_total_waarde_delta_pct"))
        return df.with_columns(exprs) if exprs else df

    def _apply_column_widths(self, df: pl.DataFrame):
        widths = {
            "asset_rollup": 140,
            "aand_aantal_bezit": 100,
            "aantal_sprinters": 100,
            "opt_aantal_ITM_put": 110,
            "opt_aantal_OTM_put": 110,
            "opt_aantal_ITM_call": 120,
            "opt_aantal_OTM_call": 120,
            #"aand_waarde_bezit": 110,
            #"opt_waarde_bezit": 110,
            #"opt_waarde_bezit_delta": 130,
            "koers": 80,
            "total_waarde_lineair": 130,
            "total_waarde_delta": 130,
            "portfolio_total_waarde_lineair_pct": 160,
            "portfolio_total_waarde_delta_pct": 160,
        }
        header = self.ui.tableView.horizontalHeader()
        for i, col in enumerate(df.columns):
            if col in widths:
                header.resizeSection(i, widths[col])

    def _init_totals_footer(self):
        self.tblTotalen = QTableWidget(self)
        self.tblTotalen.setRowCount(1)
        self.tblTotalen.setColumnCount(0)
        self.tblTotalen.setFixedHeight(32)
        self.tblTotalen.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.tblTotalen.verticalHeader().setVisible(False)
        self.tblTotalen.horizontalHeader().setVisible(False)
        self.tblTotalen.horizontalHeader().setStretchLastSection(False)
        self.tblTotalen.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tblTotalen.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tblTotalen.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tblTotalen.setFocusPolicy(Qt.NoFocus)
        self.tblTotalen.setSelectionMode(QTableWidget.NoSelection)

        self._footer_container = QWidget(self)
        self._footer_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        footer_layout = QHBoxLayout(self._footer_container)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(0)
        self._footer_spacer = QWidget(self._footer_container)
        self._footer_spacer.setFixedWidth(0)

        footer_layout.addWidget(self.tblTotalen)
        footer_layout.addWidget(self._footer_spacer)

        main_layout = self.ui.verticalLayout
        main_layout.addWidget(self._footer_container)
        main_layout.setStretchFactor(self.ui.tableView, 1)
        main_layout.setStretchFactor(self._footer_container, 0)

        self._init_footer_sync()

    def _init_footer_sync(self):
        main_header = self.ui.tableView.horizontalHeader()
        footer_header = self.tblTotalen.horizontalHeader()
        main_header.sectionResized.connect(
            lambda idx, _old, new: self.tblTotalen.setColumnWidth(idx, new)
        )
        main_header.sectionMoved.connect(
            lambda logical, _old, new: footer_header.moveSection(footer_header.visualIndex(logical), new)
        )
        main_scroll = self.ui.tableView.horizontalScrollBar()
        footer_scroll = self.tblTotalen.horizontalScrollBar()
        main_scroll.valueChanged.connect(footer_scroll.setValue)
        main_scroll.rangeChanged.connect(lambda _min, _max: self._sync_footer_scrollbar_gap())
        self.ui.tableView.verticalScrollBar().rangeChanged.connect(
            lambda _min, _max: self._sync_footer_scrollbar_gap()
        )

    def _sync_footer_section_sizes(self):
        main_header = self.ui.tableView.horizontalHeader()
        for i in range(main_header.count()):
            self.tblTotalen.setColumnWidth(i, main_header.sectionSize(i))
        self.tblTotalen.horizontalScrollBar().setValue(
            self.ui.tableView.horizontalScrollBar().value()
        )

    def _sync_footer_scrollbar_gap(self):
        v_scroll = self.ui.tableView.verticalScrollBar()
        scroll_width = v_scroll.sizeHint().width() if v_scroll.maximum() > 0 else 0
        if hasattr(self, "_footer_spacer") and self._footer_spacer is not None:
            self._footer_spacer.setFixedWidth(scroll_width)

    def _apply_header_style(self):
        style = f"QHeaderView::section {{ background-color: {self._header_bg_color}; }}"
        self.ui.tableView.horizontalHeader().setStyleSheet(style)
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

    def _clear_totals(self):
        if hasattr(self, "tblTotalen"):
            self.tblTotalen.setColumnCount(0)

    def _format_total_value(self, col: str, val):
        if val is None:
            return ""
        if col in ("portfolio_total_waarde_lineair_pct", "portfolio_total_waarde_delta_pct"):
            try:
                return f"{float(val) * 100:.1f}%"
            except Exception:
                return str(val)
        if col in ("total_waarde_lineair", "total_waarde_delta"):
            try:
                s = f"{int(round(float(val))):,}".replace(",", ".")
                return s
            except Exception:
                return str(val)
        if col in (
            "aand_aantal_bezit",
            "aantal_sprinters",
            "opt_aantal_ITM_put",
            "opt_aantal_OTM_put",
            "opt_aantal_ITM_call",
            "opt_aantal_OTM_call",
        ):
            try:
                s = f"{int(round(abs(float(val)))):,}".replace(",", ".")
                return s
            except Exception:
                return str(val)
        if col == "koers":
            try:
                return f"{float(val):,.2f}".replace(",", ".")
            except Exception:
                return str(val)
        return str(val)

    def _update_totals(self, df: pl.DataFrame):
        if df is None or df.is_empty():
            self._clear_totals()
            return
        cols = list(df.columns)
        self.tblTotalen.setColumnCount(len(cols))
        totalen = {}
        for col in cols:
            if col == "asset_rollup":
                totalen[col] = "TOTAAL"
            elif col in ("regio", "sector", "value_grow"):
                totalen[col] = ""
            elif col in ("portfolio_total_waarde_lineair_pct", "portfolio_total_waarde_delta_pct"):
                totalen[col] = 1.0
            elif col in (
                "aantal_sprinters",
                "opt_aantal_ITM_put",
                "opt_aantal_OTM_put",
                "opt_aantal_ITM_call",
                "opt_aantal_OTM_call",
            ):
                try:
                    totalen[col] = df[col].abs().sum()
                except Exception:
                    totalen[col] = ""
            elif col in df.columns:
                try:
                    totalen[col] = df[col].sum()
                except Exception:
                    totalen[col] = ""
            else:
                totalen[col] = ""
        for i, col in enumerate(cols):
            val_str = self._format_total_value(col, totalen.get(col))
            item = QTableWidgetItem(val_str)
            if col == "asset_rollup":
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item.setBackground(QColor(self._total_bg_color))
            self.tblTotalen.setItem(0, i, item)


from PySide6.QtWidgets import QWidget, QHeaderView
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QColor, QBrush
import polars as pl
import contextlib

from portefeuille_viewer.ui.portfolio_value_ui import Ui_Form
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals
from portefeuille_viewer.ui.filter_popup import HeaderFilterMenuMixin

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
            if colname in self._pct_cols:
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        if role == Qt.BackgroundRole and colname in self._pct_cols:
            # Gradient: min = groen, max = rood, ertussen geel
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

        # Header contextmenu voor filters/sorteren
        header = self.ui.tableView.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self.on_header_menu)
        header.sectionClicked.connect(self._on_header_clicked)

        # Table UX tweaks
        header.setSectionResizeMode(QHeaderView.Interactive)
        # Gebruik standaardfont uit de UI en zelfde rijhoogte als OptiesOpen
        self.ui.tableView.verticalHeader().setVisible(False)
        self.ui.tableView.verticalHeader().setDefaultSectionSize(18)

        # Initial load
        self.reload_snapshot()

        # React to central signals: reload when DB changes or orders commit
        def _on_db_changed(_name: str):
            with contextlib.suppress(Exception):
                print("🔄 PortfolioValueTab: databaseChanged signal ontvangen, herladen snapshot...")
                self.reload_snapshot()
        def _on_orders_committed():
            with contextlib.suppress(Exception):
                self.reload_snapshot()
        signals.databaseChanged.connect(_on_db_changed)
        signals.ordersCommitted.connect(_on_orders_committed)

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

    def reload_snapshot(self):
        # Expected snapshot key: repository_snapshot_portfolio_value_total_combined
        print("🔄 PortfolioValueTab: snapshot herladen...")
        df = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_total_combined", None)
        if df is None or (hasattr(df, "is_empty") and df.is_empty()):
            self.model.set_df(pl.DataFrame({}))
            return
        # Ensure percent cols exist; if missing, derive safely
        # df = df.drop("aand_aantal_bezit")

        cols_to_keep = [
            "asset_rollup",
            "regio",
            "sector",
            "value_grow",
            "total_waarde_lineair",
            "total_waarde_delta",
            "portfolio_total_waarde_lineair_pct",
            "portfolio_total_waarde_delta_pct",
            # enzovoort: alleen wat je in deze tab wilt tonen/filteren
        ]
        df = df.select([c for c in cols_to_keep if c in df.columns])

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
            #"aand_aantal_bezit": 100,
            #"aand_waarde_bezit": 110,
            #"opt_waarde_bezit": 110,
            #"opt_waarde_bezit_delta": 130,
            "total_waarde_lineair": 130,
            "total_waarde_delta": 130,
            "portfolio_total_waarde_lineair_pct": 160,
            "portfolio_total_waarde_delta_pct": 160,
        }
        header = self.ui.tableView.horizontalHeader()
        for i, col in enumerate(df.columns):
            if col in widths:
                header.resizeSection(i, widths[col])


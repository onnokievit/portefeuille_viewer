import contextlib
import re
from datetime import datetime
import polars as pl
import pyqtgraph as pg

from PySide6.QtWidgets import QWidget, QTableWidgetItem, QHeaderView, QComboBox, QLineEdit, QStyledItemDelegate, QMenu, QColorDialog, QInputDialog, QScrollArea, QAbstractItemView, QStyleOptionViewItem, QStyle
from PySide6.QtGui import QFont, QColor, QDoubleValidator, QAction, QPalette, QPen
from PySide6.QtCore import QLocale, QDate, Slot, QSortFilterProxyModel, Qt, QTimer

# from streamlit import columns

from portefeuille_viewer.signals import signals
from portefeuille_viewer.ui.models import ColoredPolarsTableModel  
from portefeuille_viewer.ui.single_asset_analyse_tab_ui import Ui_SingleAssetAnalyseTab
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.config import get_settings
from portefeuille_viewer.ui.filter_popup import HeaderFilterMenuMixin, ColumnFilterPopup
from portefeuille_viewer.data.repository import (
    build_uniek_id,
    fetch_open_optie_comments,
    upsert_open_optie_comment,
    load_open_optie_comments_cache,
    flush_dirty_open_optie_comments_to_db,
    update_open_optie_comment_color,
)
from portefeuille_viewer.services.single_asset_scenario_analyse import (
    bereken_open_opties_payoff,
    bereken_open_sprinters_payoff,
    bereken_gesloten_aandelen_payoff,
    bereken_open_aandelen_payoff,
)
from portefeuille_viewer.services.aandelen_tab_summary import build_aandelen_tab_summary
from portefeuille_viewer.data.test_order_repository import delete_test_order
from portefeuille_viewer.data.test_order_repository import (
    get_cached_orders,
    set_cached_orders_for_asset,
    flush_dirty_test_orders_to_db,  # voor later timer/exit
    load_test_orders_cache_from_db,
)

class CommentSortProxy(QSortFilterProxyModel):
    """Proxy die op UserRole sorteert en tuples (priority, text) netjes vergelijkt."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDynamicSortFilter(True)

    def lessThan(self, left, right):
        role = self.sortRole()
        links = left.data(role)
        rechts = right.data(role)
        try:
            return links < rechts
        except Exception:
            # fallback op displayrole als tuple/None niet vergelijkbaar zijn
            links = left.data(Qt.DisplayRole)
            rechts = right.data(Qt.DisplayRole)
            try:
                return links < rechts
            except Exception:
                return False



...
def auto_fill_year(line_edit: QLineEdit):
    #print("auto_fill_year called")
    s = (line_edit.text() or "").strip()
    if not s:
        return
    s_norm = s.replace("\\", "/").replace("-", "/")
    m = re.match(r'^\s*(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?\s*$', s_norm)
    if not m:
        return
    d, mth = int(m.group(1)), int(m.group(2))
    y = m.group(3)
    y2 = (datetime.now().year % 100) if y is None else (int(y) if len(y) == 2 else int(y) % 100)
    #print(f"Auto-filling date: d={d}, mth={mth}, y2={y2}")
    line_edit.setText(f"{d}-{mth:02d}-{y2:02d}")


class ComboDelegate(QStyledItemDelegate):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.options = options
    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.addItems(self.options)
        cb.setEditable(True)
        cb.setInsertPolicy(QComboBox.NoInsert)
        return cb
    def setEditorData(self, editor, index):
        val = index.data(Qt.EditRole) or ""
        i = editor.findText(val)
        if i >= 0: 
            editor.setCurrentIndex(i)
        else: 
            editor.setCurrentText(val)
    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.EditRole)

class DoubleDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        le = QLineEdit(parent)
        le.setValidator(QDoubleValidator(0, 1e12, 2, le))
        return le

class DateDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        le = QLineEdit(parent)
        le.editingFinished.connect(lambda le=le: auto_fill_year(le))
        return le

    def setModelData(self, editor, model, index):
        auto_fill_year(editor)  # d-mm-yy → dd-mm-yy
        model.setData(index, editor.text(), Qt.EditRole)

class NumberDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        le = QLineEdit(parent)
        v = QDoubleValidator(0, 1e12, 2, le)
        v.setLocale(QLocale(QLocale.C))  # punt als decimaal
        le.setValidator(v)
        return le

    def setModelData(self, editor, model, index):
        txt = editor.text().replace(",", ".").strip()
        try:
            val = float(txt)
            model.setData(index, f"{val:.2f}", Qt.EditRole)
        except Exception:
            model.setData(index, txt, Qt.EditRole)

class CommentNoSelectDelegate(QStyledItemDelegate):
    """
    Delegate die selectie-overlay negeert zodat de comment-kleur zichtbaar blijft.
    """
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        opt.state &= ~QStyle.State_Selected
        super().paint(painter, opt, index)
        if option.state & QStyle.State_Selected:
            painter.save()
            painter.setPen(QPen(option.palette.color(QPalette.Text), 1))
            rect = option.rect.adjusted(1, 1, -1, -1)
            painter.drawRoundedRect(rect, 3, 3)
            painter.restore()


class CommentablePolarsTableModel(ColoredPolarsTableModel):
    """Voegt bewerkbare kolom(men) toe voor opmerkingen op open opties."""

    def __init__(self, df, kleur_kolommen=None, kleur_func=None, parent=None, editable_cols=None, commit_callback=None, *args, **kwargs):
        super().__init__(df, kleur_kolommen, kleur_func, parent, *args, **kwargs)
        self._editable_cols = set(editable_cols or [])
        self._commit_callback = commit_callback
        self._color_priority_map = {}
        self._comment_color_fg_map = {}

    def set_color_priority_map(self, prio_map: dict):
        self._color_priority_map = prio_map or {}

    def set_comment_color_text_map(self, fg_map: dict):
        self._comment_color_fg_map = fg_map or {}

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if not index.isValid() or self._df.is_empty():
                return None
            colname = self._df.columns[index.column()]
            if colname == "aantal_bezit":
                val = self._df[index.row(), index.column()]
                if val is None:
                    return ""
                try:
                    return f"{float(val):,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
                except Exception:
                    return str(val)
            if colname in {"optie_strike", "premie"}:
                val = self._df[index.row(), index.column()]
                if val is None:
                    return ""
                try:
                    return f"{float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                except Exception:
                    return str(val)
        if role == Qt.EditRole:
            if not index.isValid() or self._df.is_empty():
                return ""
            val = self._df[index.row(), index.column()]
            return "" if val is None else str(val)
        if role == Qt.BackgroundRole:
            try:
                colname = self._df.columns[index.column()]
                if colname == "optie_comment":
                    color_col = self._df.columns.index("optie_comment_color") if "optie_comment_color" in self._df.columns else None
                    if color_col is not None:
                        cval = self._df[index.row(), color_col]
                        if cval:
                            return QColor(cval)
            except Exception:
                pass
        if role == Qt.ForegroundRole:
            try:
                colname = self._df.columns[index.column()]
                if colname == "optie_comment":
                    if "optie_comment_textcolor" in self._df.columns:
                        text_col = self._df.columns.index("optie_comment_textcolor")
                        text_val = self._df[index.row(), text_col]
                        if text_val:
                            return QColor(text_val)
                    color_col = self._df.columns.index("optie_comment_color") if "optie_comment_color" in self._df.columns else None
                    if color_col is not None:
                        cval = self._df[index.row(), color_col]
                        fg = self._comment_color_fg_map.get(cval or "")
                        if fg:
                            return QColor(fg)
            except Exception:
                pass
        if role == Qt.UserRole:
            # custom sort: for comment/color columns sort on color priority then text
            try:
                colname = self._df.columns[index.column()]
                if colname == "optie_comment" and "optie_comment_color" in self._df.columns:
                    cval = self._df[index.row(), self._df.columns.index("optie_comment_color")] or ""
                    priority = self._color_priority_map.get(cval, 0)
                    return (priority, str(self._df[index.row(), index.column()] or ""))
            except Exception:
                pass
        return super().data(index, role)

    def flags(self, index):
        base = super().flags(index)
        if not index.isValid():
            return base
        col_name = self._df.columns[index.column()]
        if col_name in self._editable_cols:
            base |= Qt.ItemIsEditable
        return base

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        col_name = self._df.columns[index.column()]
        if col_name not in self._editable_cols:
            return False

        row_idx = index.row()
        new_val = "" if value is None else str(value)

        try:
            # Update comment kolom
            col_values = self._df[col_name].to_list()
            col_values[row_idx] = new_val
            self._df = self._df.with_columns(pl.Series(col_name, col_values))

            # Timestamp bijwerken als kolom aanwezig is
            ts_col = "optie_comment_updated_at"
            if ts_col in self._df.columns:
                ts_values = self._df[ts_col].to_list()
                ts_values[row_idx] = datetime.now()
                self._df = self._df.with_columns(pl.Series(ts_col, ts_values))

            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])

            if self._commit_callback:
                row_data = self._df.row(row_idx, named=True)
                # Defer commit zodat Qt's editor/commitData flow niet botst met model resets
                QTimer.singleShot(0, lambda rd=row_data: self._commit_callback(rd))
            return True
        except Exception:
            return False







class AandelenTableModel(ColoredPolarsTableModel):
    """Custom model to format aantal_bezit with 2 decimals in open aandelen table."""
    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if not index.isValid() or self._df.is_empty():
                return None
            colname = self._df.columns[index.column()]
            if colname == "aantal_bezit":
                val = self._df[index.row(), index.column()]
                if val is None:
                    return ""
                try:
                    return f"{float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                except Exception:
                    return str(val)
        return super().data(index, role)

# Widget-class die UI en logica koppelt
class SingleAssetAnalyseTab(QWidget, Ui_SingleAssetAnalyseTab, HeaderFilterMenuMixin):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self._wrap_in_scroll_area()
        self._active = False
        self._summary_dirty = False
        self._summary_reload_timer = QTimer(self)
        self._summary_reload_timer.setInterval(300)
        self._summary_reload_timer.setSingleShot(True)
        self._summary_reload_timer.timeout.connect(self._reload_summary_if_needed)

        # init logic
        self.logic = SingleAssetAnalyseLogic()

        # init flags op basis van de checkboxen
        self.show_all_test_orders = not self.checkBoxAssetOrdersOnly.isChecked()
        self.enable_test_orders = self.checkBoxEnableTestOrders.isChecked()
        self.logic.enable_test_orders = self.enable_test_orders

        # pas hier de connecties
        self.checkBoxAssetOrdersOnly.toggled.connect(self.on_toggle_show_all_test_orders)
        self.checkBoxEnableTestOrders.toggled.connect(self.on_toggle_enable_test_orders)

        self.tableView = self.tableViewOptiesOpen
        self._fill_filter_comboboxes()
        self._table_model = None  # voor de mixin
        self._col_filters = {}    # voor de mixin
        self.payoff_matrix = None
        asset_rollups = []
        df_rollups = getattr(SNAPSHOT_STORE, "repository_snapshot_active_asset_rollup_data", None)
        if df_rollups is not None and df_rollups.height > 0:
            asset_rollups = [str(x) for x in df_rollups["asset_rollup"].unique().to_list() if x]

        self.test_order_columns_db = [
            "Id", "broker", "asset_rollup", "asset_type","transactie_type","transactie_aantal","transactie_prijs","optie_call_put","optie_exp_date",
            "optie_strike",  "include"
            ]
        self.test_order_columns = self.test_order_columns_db + ["optie_comment"]
        display_labels = [
            "Id", "Broker", "Asset", "Asset Type", "Transactie",
            "Aantal", "Prijs", "c/p", "Exp datum",
            "Strike",  "Incl", "Comment",
            ]
        
        
        self.testOrdersTable.setColumnCount(len(self.test_order_columns))
        self.testOrdersTable.setHorizontalHeaderLabels(display_labels)
        self.testOrdersTable.setColumnHidden(0, True)
        header_test_orders = self.testOrdersTable.horizontalHeader()
        header_test_orders.setSectionResizeMode(QHeaderView.Interactive)
        header_test_orders.setStretchLastSection(False)
        self._apply_test_orders_column_widths()
        self._apply_test_orders_styling()
        self.testOrdersTable.setSortingEnabled(True)
        # try:
        #     asset_col = self.test_order_columns.index("asset_rollup")
        #     self.testOrdersTable.sortItems(asset_col, Qt.AscendingOrder)
        # except ValueError:
        #     pass
        
        
        self.df_test_orders = {}
        self.testOrdersTable.cellChanged.connect(self.on_test_orders_changed)
        self.buttonAddTestOrder.clicked.connect(self.add_empty_row)  # als je een knop hebt
        self.buttonDeleteTestOrder.clicked.connect(self.on_delete_test_order_clicked)

        # Delegates koppelen op kolomnaam (niet op index), zodat kolomvolgorde vrij kan wijzigen.
        def _set_delegate(colname: str, delegate) -> None:
            if colname not in self.test_order_columns:
                return
            self.testOrdersTable.setItemDelegateForColumn(self.test_order_columns.index(colname), delegate)

        _set_delegate("broker", ComboDelegate(["degiro", "lynx", "interactive"], self))
        _set_delegate("asset_rollup", ComboDelegate(asset_rollups, self))
        _set_delegate("asset_type", ComboDelegate(["aandeel", "optie"], self))
        _set_delegate("transactie_type", ComboDelegate(["koop", "verkoop"], self))
        _set_delegate("optie_call_put", ComboDelegate(["call", "put"], self))
        _set_delegate("optie_exp_date", DateDelegate(self))

        num_delegate = NumberDelegate(self)
        _set_delegate("transactie_aantal", num_delegate)
        _set_delegate("transactie_prijs", num_delegate)
        _set_delegate("optie_strike", num_delegate)
        _set_delegate("optie_comment", CommentNoSelectDelegate(self.testOrdersTable))
        # Klik op asset -> selecteer in asset_selector
        self.testOrdersTable.cellClicked.connect(self._on_test_order_cell_clicked)
        self.testOrdersTable.setContextMenuPolicy(Qt.CustomContextMenu)
        self.testOrdersTable.customContextMenuRequested.connect(self._on_test_orders_context_menu)
        



        self.priceAantalChart.setFocusPolicy(Qt.NoFocus)
        self.resultaatChart.setFocusPolicy(Qt.NoFocus)
        signals.databaseChanged.connect(self.on_database_changed)
        signals.ordersCommitted.connect(self.on_orders_committed)
        self.comboBoxStatus.setCurrentText("active")
        self.comboBoxRegio.currentTextChanged.connect(self._on_filter_changed)
        self.comboBoxStatus.currentTextChanged.connect(self._on_filter_changed)
        self.comboBoxValueGrow.currentTextChanged.connect(self._on_filter_changed)
        self.comboBoxSector.currentTextChanged.connect(self._on_filter_changed)
        self._init_sort_comboboxes()
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
        self.stepSizeBox.setDecimals(1)
        self.stepSizeBox.setSingleStep(0.5)
        self.stepSizeBox.setValue(2)

        
        font = QFont("Arial", 8)  # Kies je gewenste lettertype en grootte
        self.payoff_table.setFont(font)        
                
        self.logic = SingleAssetAnalyseLogic()
        #self.update_opties_open_table()
        
        self.asset_selector.addItems(self.logic.load_assets())
        asset_font = self.asset_selector.font()
        asset_font.setPointSize(10)
        asset_font.setBold(True)
        self.asset_selector.setFont(asset_font)
        self._align_summary_labels()
        
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

        self._history_charts_right_axis_ready = False
        self._opties_open_filter_connections_ready = False
        self.payoff_table.setRowCount(10)
        self.stepSizeBox.valueChanged.connect(self.update_payoff_table)
                # Maak de rijhoogte compacter
        self._on_filter_changed()
        self.payoff_table.verticalHeader().setMinimumSectionSize(22)
        self.payoff_table.verticalHeader().setDefaultSectionSize(22)
        for row in range(10):
            self.payoff_table.setRowHeight(row, 22)  # pas 22 aan voor nog compacter/ruimer
            # Zet rowHeight ook voor de andere tabellen
            for table in [self.tableViewOptiesOpen, self.tableViewOptiesOpenPut, self.tableViewOptiesOpenCall, self.tableViewAandelen, self.tableViewSprinters]:
                table.verticalHeader().setMinimumSectionSize(22)
                table.verticalHeader().setDefaultSectionSize(22)
                # rowCount kan per tabel verschillen, dus dynamisch ophalen
                for row in range(table.model().rowCount() if table.model() else 0):
                    table.setRowHeight(row, 22)
        # Je kunt hier headers en andere init doen zoals in je oude code
        self.lineEditFilterOptiesOpen.returnPressed.connect(self.apply_filters_opties_open)
        self.buttonClearFiltersOptiesOpen.clicked.connect(self._on_clear_filters_opties_open)
        self._opties_open_filter_connections_ready = True
        load_open_optie_comments_cache()
        self.update_opties_open_table()
        self.testOrderFlushTimer = QTimer(self)
        self.testOrderFlushTimer.setInterval(60_000)  # 60s
        self.testOrderFlushTimer.timeout.connect(self._flush_test_orders_if_dirty)
        # Comments cache vooraf laden
        load_open_optie_comments_cache()
        self.commentFlushTimer = QTimer(self)
        self.commentFlushTimer.setInterval(60_000)  # 60s
        self.commentFlushTimer.timeout.connect(self._flush_comments_if_dirty)

        self.tableViewOptiesOpen.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableViewOptiesOpen.horizontalHeader().customContextMenuRequested.connect(lambda pos: self._on_header_menu_for_view(self.tableViewOptiesOpen, pos))
        self.tableViewOptiesOpen.clicked.connect(self._on_table_cell_clicked)
        self.tableViewOptiesOpen.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableViewOptiesOpen.customContextMenuRequested.connect(lambda pos: self._on_comment_context_menu_for_view(self.tableViewOptiesOpen, pos))
        # Ook contextmenu voor de put/call tabellen
        self.tableViewOptiesOpenPut.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableViewOptiesOpenPut.customContextMenuRequested.connect(lambda pos: self._on_comment_context_menu_for_view(self.tableViewOptiesOpenPut, pos))
        self.tableViewOptiesOpenCall.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableViewOptiesOpenCall.customContextMenuRequested.connect(lambda pos: self._on_comment_context_menu_for_view(self.tableViewOptiesOpenCall, pos))

    def set_active(self, active: bool):
        self._active = active
        if active:
            self._schedule_summary_reload()

    def _schedule_summary_reload(self):
        self._summary_dirty = True
        if not self._summary_reload_timer.isActive():
            self._summary_reload_timer.start()

    def _reload_summary_if_needed(self):
        if not self._active:
            return
        if self._summary_dirty:
            self._summary_dirty = False
            self.update_aandelen_table()

    def _apply_test_orders_column_widths(self) -> None:
        """
        Handmatige kolombreedtes voor `testOrdersTable`.
        Pas de dict hieronder aan naar smaak.
        """
        col_widths = {
            "broker": 60,
            "asset_rollup": 75,
            "asset_type": 70,
            "transactie_type": 75,
            "transactie_aantal": 80,
            "transactie_prijs": 80,
            "optie_exp_date": 75,
            "optie_strike": 50,
            "optie_call_put": 35,
            "include": 50,
            "optie_comment": 305,
        }

        header = self.testOrdersTable.horizontalHeader()
        for name, width in col_widths.items():
            if name not in self.test_order_columns:
                continue
            idx = self.test_order_columns.index(name)
            header.resizeSection(idx, width)

    def _apply_test_orders_styling(self) -> None:
        # match "opties open" look: Arial 8, non-bold, compact rows
        font = QFont("Arial", 8)
        font.setBold(False)
        self.testOrdersTable.setFont(font)
        self.testOrdersTable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.testOrdersTable.setStyleSheet("""
        QTableWidget::item:selected { background: rgba(255,242,204,80); color: black; }
        QTableWidget::item:selected:active { background: rgba(255,242,204,80); color: black; }
        QTableWidget::item:selected:active:focus { background: rgba(255,242,204,80); color: black; }
        """)
        self.testOrdersTable.verticalHeader().setMinimumSectionSize(22)
        self.testOrdersTable.verticalHeader().setDefaultSectionSize(22)
        self.testOrdersTable.verticalHeader().setVisible(False)
        for r in range(self.testOrdersTable.rowCount()):
            self.testOrdersTable.setRowHeight(r, 22)

    def _wrap_in_scroll_area(self) -> None:
        """
        Maak alleen deze tab scrollbaar (handig op laptop-schermen).

        De UI van deze tab gebruikt absolute positioning op `self.widget`.
        Door `self.widget` in een QScrollArea te plaatsen wordt de hele tab scrollbaar.
        """
        try:
            layout = getattr(self, "verticalLayout_2", None)
            content = getattr(self, "widget", None)
            if layout is None or content is None:
                return

            if getattr(self, "_single_asset_scroll_area", None) is not None:
                return

            # Bepaal content size op basis van grootste child geometry (absolute UI)
            max_w = 0
            max_h = 0
            for child in content.findChildren(QWidget):
                g = child.geometry()
                max_w = max(max_w, g.x() + g.width())
                max_h = max(max_h, g.y() + g.height())
            if max_w > 0 and max_h > 0:
                content.setMinimumSize(max_w + 10, max_h + 10)

            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

            layout.removeWidget(content)
            scroll.setWidget(content)
            layout.addWidget(scroll)

            self._single_asset_scroll_area = scroll
        except Exception as exc:
            print(f"[ui] kon SingleAssetAnalyseTab niet scrollbaar maken: {exc}")

    def _ensure_history_charts_right_axis(self):
        pw = self.priceAantalChart
        if self._history_charts_right_axis_ready:
            return

        self._rightView = pg.ViewBox()
        pw.plotItem.showAxis('right')
        pw.plotItem.scene().addItem(self._rightView)
        pw.plotItem.getAxis('right').linkToView(self._rightView)
        self._rightView.setXLink(pw.plotItem)

        def _sync_right_view_geometry():
            self._rightView.setGeometry(pw.plotItem.vb.sceneBoundingRect())

        _sync_right_view_geometry()
        pw.plotItem.vb.sigResized.connect(_sync_right_view_geometry)
        self._history_charts_right_axis_ready = True

    @staticmethod
    def _set_plot_ranges(widget: pg.PlotWidget, x_values, y_values, *, padding=0.02):
        if x_values is None or y_values is None or len(x_values) == 0 or len(y_values) == 0:
            return

        x_min, x_max = float(min(x_values)), float(max(x_values))
        y_min, y_max = float(min(y_values)), float(max(y_values))
        if x_min == x_max:
            x_max = x_min + 1.0
        if y_min == y_max:
            y_max = y_min + 1.0

        widget.setXRange(x_min, x_max, padding=padding)
        widget.setYRange(y_min, y_max, padding=padding)

    @Slot(bool)
    def on_toggle_show_all_test_orders(self, checked):
        self.show_all_test_orders = not checked  # checked = alleen huidig asset
        asset = self.asset_selector.currentText()
        if self.show_all_test_orders:
            cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_orders_cache", {}) or {}
            df = pl.concat(cache.values(), how="diagonal_relaxed") if cache else None
        else:
            df = get_cached_orders(asset)
        self.fill_test_orders_table(df)

    @Slot(bool)
    def on_toggle_enable_test_orders(self, checked):
        self.enable_test_orders = checked
        self.logic.enable_test_orders = checked
        asset = self.asset_selector.currentText()
        self.logic.set_asset(asset)
        self.update_payoff_table()
        self.update_chart()
    
    def _flush_test_orders_if_dirty(self):
        flush_dirty_test_orders_to_db()
        # stop timer als er niets meer dirty is
        dirty = getattr(SNAPSHOT_STORE, "repository_dirty_test_orders_assets", set()) or set()
        if not dirty and self.testOrderFlushTimer.isActive():
            self.testOrderFlushTimer.stop()

    def _flush_comments_if_dirty(self):
        flush_dirty_open_optie_comments_to_db()
        dirty = getattr(SNAPSHOT_STORE, "repository_dirty_open_optie_comments", []) or []
        if not dirty and self.commentFlushTimer.isActive():
            self.commentFlushTimer.stop()
    
    
    def apply_filters(self):
        self.apply_filters_opties_open()

    def _load_initial_records(self):
        self.apply_filters_opties_open()
    
    @Slot()
    def on_test_orders_changed(self, row, col):
        if self.testOrdersTable.signalsBlocked():
            return

        # Comment hoort niet bij test-order DB; schrijf naar optie-comments via uniek_id.
        try:
            idx_comment = self.test_order_columns.index("optie_comment")
        except ValueError:
            idx_comment = -1
        if idx_comment >= 0 and col == idx_comment:
            self._on_test_order_comment_changed(row)
            return

        # Forceer asset_rollup alleen in per-asset modus
        if "asset_rollup" in self.test_order_columns_db and not getattr(self, "show_all_test_orders", False):
            try:
                idx = self.test_order_columns.index("asset_rollup")
                asset_val = self.asset_selector.currentText()
                self.testOrdersTable.blockSignals(True)
                item = self.testOrdersTable.item(row, idx)
                if item is None:
                    item = QTableWidgetItem("")
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    self.testOrdersTable.setItem(row, idx, item)
                item.setText(asset_val)
            finally:
                self.testOrdersTable.blockSignals(False)

        # lees tabel en schrijf naar cache
        df_asset = self.read_test_orders()
        if getattr(self, "show_all_test_orders", False):
            for asset_val in df_asset["asset_rollup"].unique().to_list():
                df_sub = df_asset.filter(pl.col("asset_rollup") == asset_val)
                set_cached_orders_for_asset(asset_val, df_sub)
        else:
            asset_rollup = self.asset_selector.currentText()
            set_cached_orders_for_asset(asset_rollup, df_asset)

        # herbereken payoff/chart op huidige asset
        current_asset = self.asset_selector.currentText()
        self.logic.enable_test_orders = getattr(self, "enable_test_orders", True)
        self.logic.set_asset(current_asset)
        self.update_payoff_table()
        self.update_chart()

        if not self.testOrderFlushTimer.isActive():
            self.testOrderFlushTimer.start()

    def _on_test_order_comment_changed(self, row: int) -> None:
        try:
            item = self.testOrdersTable.item(row, self.test_order_columns.index("optie_comment"))
            comment = item.text() if item else ""
            current_color = item.data(Qt.UserRole) if item is not None else ""
            current_color = current_color or ""
        except Exception:
            return

        values = self.row_to_dict_db(row)
        if (values.get("asset_type") or "").strip().lower() not in {"optie", "aandeel"}:
            return
        uniek_id = build_uniek_id(values)
        if not uniek_id:
            return

        try:
            fg_by_bg = get_settings().get_comment_color_text_map()
            current_textcolor = fg_by_bg.get(current_color, "")
            upsert_open_optie_comment(uniek_id, comment, current_color, current_textcolor)
            latest = fetch_open_optie_comments([uniek_id])
            if latest is not None and not latest.is_empty():
                row_latest = latest.row(0, named=True)
                self._patch_comment_in_models(
                    uniek_id,
                    row_latest.get("optie_comment") or "",
                    row_latest.get("optie_comment_color") or "",
                    row_latest.get("optie_comment_textcolor") or "",
                    row_latest.get("optie_comment_updated_at"),
                )
                self._apply_comment_style_to_test_order_row(
                    row,
                    row_latest.get("optie_comment_color") or "",
                    row_latest.get("optie_comment_textcolor") or "",
                )
        except Exception as exc:
            print(f"[comments] kon test-order comment niet opslaan: {exc}")
            return

        if not self.commentFlushTimer.isActive():
            self.commentFlushTimer.start()

    def _apply_comment_style_to_test_order_row(self, row: int, color_hex: str, textcolor_hex: str = "") -> None:
        try:
            idx_comment = self.test_order_columns.index("optie_comment")
        except ValueError:
            return
        item = self.testOrdersTable.item(row, idx_comment)
        if item is None:
            return
        self.testOrdersTable.blockSignals(True)
        try:
            item.setData(Qt.UserRole, color_hex or "")
            if color_hex:
                item.setBackground(QColor(color_hex))
                fg = textcolor_hex or get_settings().get_comment_color_text_map().get(color_hex)
                if fg:
                    item.setForeground(QColor(fg))
            else:
                item.setBackground(QColor())
                item.setForeground(QColor())
        finally:
            self.testOrdersTable.blockSignals(False)

    def _on_test_orders_context_menu(self, pos) -> None:
        row = self.testOrdersTable.rowAt(pos.y())
        col = self.testOrdersTable.columnAt(pos.x())
        if row < 0 or col < 0:
            return

        try:
            idx_comment = self.test_order_columns.index("optie_comment")
        except ValueError:
            return
        if col != idx_comment:
            return

        values = self.row_to_dict_db(row)
        if (values.get("asset_type") or "").strip().lower() not in {"optie", "aandeel"}:
            return
        uniek_id = build_uniek_id(values)
        if not uniek_id:
            return

        item = self.testOrdersTable.item(row, col)
        current_comment = item.text() if item else ""
        current_color = item.data(Qt.UserRole) if item is not None else ""
        current_color = current_color or ""

        menu = QMenu(self)

        act_clear = QAction("Geen kleur", menu)
        menu.addAction(act_clear)
        menu.addSeparator()

        color_defs = get_settings().get_comment_colors()
        for _prio, label, bg_hex, _fg_hex in color_defs:
            act = QAction(label, menu)
            act.setData(bg_hex)
            menu.addAction(act)

        menu.addSeparator()
        act_custom = QAction("Kies kleur...", menu)
        menu.addAction(act_custom)

        chosen = menu.exec(self.testOrdersTable.viewport().mapToGlobal(pos))
        if not chosen:
            return

        if chosen == act_clear:
            hexval = ""
        elif chosen == act_custom:
            color = QColorDialog.getColor(QColor(current_color) if current_color else QColor("#ffffff"), self, "Kies kleur")
            if not color.isValid():
                return
            hexval = color.name()
        else:
            hexval = chosen.data() or ""

        try:
            fg_by_bg = get_settings().get_comment_color_text_map()
            textcolor = fg_by_bg.get(hexval, "")
            upsert_open_optie_comment(uniek_id, current_comment, hexval, textcolor)
            latest = fetch_open_optie_comments([uniek_id])
            if latest is not None and not latest.is_empty():
                row_latest = latest.row(0, named=True)
                self._patch_comment_in_models(
                    uniek_id,
                    row_latest.get("optie_comment") or "",
                    row_latest.get("optie_comment_color") or "",
                    row_latest.get("optie_comment_textcolor") or "",
                    row_latest.get("optie_comment_updated_at"),
                )
                self._apply_comment_style_to_test_order_row(
                    row,
                    row_latest.get("optie_comment_color") or "",
                    row_latest.get("optie_comment_textcolor") or "",
                )
            else:
                self._apply_comment_style_to_test_order_row(row, hexval, textcolor)
        except Exception as exc:
            print(f"[comments] kon test-order kleur niet opslaan: {exc}")
            return

        if not self.commentFlushTimer.isActive():
            self.commentFlushTimer.start()





    def fill_test_orders_table(self, df=None):
        def fmt_date(val):
            if val in ("", None):
                return ""
            import datetime as dt
            if isinstance(val, dt.datetime):
                return val.strftime("%d-%m-%Y")
            if isinstance(val, dt.date):
                return val.strftime("%d-%m-%Y")
            s = str(val).strip()
            # probeer verschillende scheidingen en volgordes
            for sep in ("-", "/", "."):
                parts = s.replace("/", sep).replace(".", sep).split(sep)
                if len(parts) == 3:
                    try:
                        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                        if y < 100:
                            y = 2000 + y
                        return f"{d:02d}-{m:02d}-{y:04d}"
                    except Exception:
                        continue
            return s
        num_cols = {...}

        sorting = self.testOrdersTable.isSortingEnabled()
        self.testOrdersTable.setSortingEnabled(False)
        self.testOrdersTable.blockSignals(True)
        self.testOrdersTable.setRowCount(0)

        if df is None or getattr(df, "is_empty", lambda: True)():
            self.add_empty_row()
        else:
            cols = self.test_order_columns
            rows = df.to_dicts()
            # comments ophalen op basis van uniek_id (alleen voor optie-rijen)
            comment_by_id = {}
            color_by_id = {}
            textcolor_by_id = {}
            fg_by_bg = get_settings().get_comment_color_text_map()
            try:
                uniek_ids = []
                for rd in rows:
                    if (rd.get("asset_type") or "").strip().lower() not in {"optie", "aandeel"}:
                        continue
                    uid = build_uniek_id(rd)
                    if uid:
                        rd["_uniek_id"] = uid
                        uniek_ids.append(uid)
                if uniek_ids:
                    df_comments = fetch_open_optie_comments(uniek_ids)
                    if df_comments is not None and not df_comments.is_empty():
                        comment_by_id = {r["uniek_id"]: (r.get("optie_comment") or "") for r in df_comments.to_dicts()}
                        color_by_id = {r["uniek_id"]: (r.get("optie_comment_color") or "") for r in df_comments.to_dicts()}
                        textcolor_by_id = {r["uniek_id"]: (r.get("optie_comment_textcolor") or "") for r in df_comments.to_dicts()}
            except Exception as exc:
                print(f"[comments] ophalen comments voor test-orders faalde: {exc}")

            for row_data in rows:
                row = self.testOrdersTable.rowCount()
                self.testOrdersTable.insertRow(row)
                asset_type = (row_data.get("asset_type") or "").strip().lower()
                for c, name in enumerate(cols):
                    if name == "optie_comment":
                        val = comment_by_id.get(row_data.get("_uniek_id", ""), "")
                    else:
                        val = row_data.get(name, "")
                    if asset_type != "optie" and name in ("optie_exp_date", "optie_strike", "optie_call_put"):
                        val = ""
                    if val is None:
                        val = ""
                    if name == "optie_exp_date":
                        val = fmt_date(val)
                    if name in num_cols and val not in ("", None):
                        try:
                            val = f"{float(val):.2f}"
                        except Exception:
                            pass
                    if name == "include":
                        item = QTableWidgetItem()
                        item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                        item.setCheckState(Qt.Checked if val in (None, "", 1, "1", "True", "true") else Qt.Unchecked)
                    else:
                        item = QTableWidgetItem(str(val))
                        item.setFlags(item.flags() | Qt.ItemIsEditable)
                        if name == "optie_comment":
                            color_hex = color_by_id.get(row_data.get("_uniek_id", ""), "")
                            text_hex = textcolor_by_id.get(row_data.get("_uniek_id", ""), "")
                            if color_hex:
                                item.setData(Qt.UserRole, color_hex)
                                item.setBackground(QColor(color_hex))
                                fg = text_hex or fg_by_bg.get(color_hex)
                                if fg:
                                    item.setForeground(QColor(fg))
                    self.testOrdersTable.setItem(row, c, item)

        self.testOrdersTable.blockSignals(False)
        self._apply_test_orders_styling()
        if sorting:
            try:
                asset_col = self.test_order_columns.index("asset_rollup")
                self.testOrdersTable.setSortingEnabled(True)
                self.testOrdersTable.sortItems(asset_col, Qt.AscendingOrder)
            except ValueError:
                self.testOrdersTable.setSortingEnabled(True)




    def add_empty_row(self):
        sorting = self.testOrdersTable.isSortingEnabled()
        if sorting:
            self.testOrdersTable.setSortingEnabled(False)
        self.testOrdersTable.blockSignals(True)

        row = self.testOrdersTable.rowCount()
        self.testOrdersTable.insertRow(row)
        cols = self.test_order_columns
        for c, name in enumerate(cols):
            if name == "include":
                item = QTableWidgetItem()
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Checked)
            else:
                item = QTableWidgetItem("")
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                if name == "asset_rollup" and not getattr(self, "show_all_test_orders", False):
                    item.setText(self.asset_selector.currentText())
            self.testOrdersTable.setItem(row, c, item)

        self.testOrdersTable.blockSignals(False)
        self._apply_test_orders_styling()
        if sorting:
            self.testOrdersTable.setSortingEnabled(True)
            try:
                asset_col = self.test_order_columns.index("asset_rollup")
                self.testOrdersTable.sortItems(asset_col, Qt.AscendingOrder)
            except ValueError:
                pass


    @Slot()
    def on_delete_test_order_clicked(self):
        idx = self.testOrdersTable.currentRow()
        if idx < 0:
            return
        row_data = self.row_to_dict(idx)
        order_id = row_data.get("Id")
        deleted_asset = (row_data.get("asset_rollup") or "").strip() or self.asset_selector.currentText()
        self._debug_print_test_orders_cache(f"delete clicked id={order_id} asset={deleted_asset}")
        # Verwijder uit DB als er een Id is, anders alleen uit UI
        if order_id:
            delete_test_order(int(order_id))
        self.testOrdersTable.blockSignals(True)
        self.testOrdersTable.removeRow(idx)
        self.testOrdersTable.blockSignals(False)
        df_remaining = self.read_test_orders()  # leest de huidige tabel (single-asset of all-assets)
        if getattr(self, "show_all_test_orders", False):
            # In all-assets mode toont de tabel meerdere assets; update alleen het asset van de verwijderde rij.
            if df_remaining is not None and not df_remaining.is_empty() and "asset_rollup" in df_remaining.columns:
                df_asset_remaining = df_remaining.filter(pl.col("asset_rollup") == deleted_asset)
            else:
                df_asset_remaining = pl.DataFrame({c: [] for c in self.test_order_columns})
            set_cached_orders_for_asset(deleted_asset, df_asset_remaining)
        else:
            # single-asset mode: tabel bevat alleen dit asset
            set_cached_orders_for_asset(deleted_asset, df_remaining)

        self._debug_print_test_orders_cache(f"after delete id={order_id} asset={deleted_asset}")
        if not self.testOrderFlushTimer.isActive():
            self.testOrderFlushTimer.start()
        self.logic.set_asset(self.asset_selector.currentText())
        self.update_payoff_table()
        self.update_chart()

    def _debug_print_test_orders_cache(self, msg: str):
        """Debug helper om cache/dirty status te loggen naar CLI."""
        try:
            cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_orders_cache", {}) or {}
            dirty = getattr(SNAPSHOT_STORE, "repository_dirty_test_orders_assets", set()) or set()
            current_asset = self.asset_selector.currentText()
            mode = "all" if getattr(self, "show_all_test_orders", False) else "single"
            n_assets = len(cache)
            total_rows = 0
            current_rows = 0
            with_ids = 0
            for a, df in cache.items():
                if df is None or getattr(df, "is_empty", lambda: True)():
                    continue
                total_rows += df.height
                if a == current_asset:
                    current_rows = df.height
                if "Id" in df.columns:
                    try:
                        with_ids += int((df["Id"].cast(pl.Utf8).str.lengths() > 0).sum())
                    except Exception:
                        pass
            print(f"[test_orders] {msg} mode={mode} current_asset={current_asset} cache_assets={n_assets} cache_rows={total_rows} current_rows={current_rows} dirty={sorted(dirty)}")
        except Exception as exc:
            print(f"[test_orders] debug failed: {exc}")

    def _is_valid_test_order(self, data: dict) -> bool:
        # alles leeg? overslaan
        if all(not data.get(k) for k in data if k not in ("Id",)):
            return False

        # verplichte basis
        if not all(data.get(k) for k in ("asset_rollup", "asset_type", "transactie_type")):
            return False

        if data["asset_type"] == "aandeel":
            return all(data.get(k) for k in ("transactie_aantal", "transactie_prijs"))
        if data["asset_type"] == "optie":
            return all(data.get(k) for k in (
                "transactie_aantal", "transactie_prijs",
                "optie_call_put", "optie_strike", "optie_exp_date"
            ))
        return False  # onbekend type
    
    
    def read_test_orders(self):
        cols = self.test_order_columns_db
        rows = []
        for r in range(self.testOrdersTable.rowCount()):
            row_data = {}
            for c, name in enumerate(cols):
                item = self.testOrdersTable.item(r, c)
                if name == "include":
                    row_data[name] = 1 if (item and item.checkState() == Qt.Checked) else 0
                else:
                    row_data[name] = item.text() if item else ""
            if not self._is_valid_test_order(row_data):
                continue
            rows.append(row_data)
        if rows:
            return pl.DataFrame(rows)
        # retourneer lege DF met alle kolomnamen zodat downstream geen ColumnNotFound krijgt
        return pl.DataFrame({c: [] for c in cols})

    
    def row_to_dict(self, row: int) -> dict:
        cols = self.test_order_columns
        data = {}
        for c, name in enumerate(cols):
            item = self.testOrdersTable.item(row, c)
            if name == "include":
                data[name] = 1 if (item and item.checkState() == Qt.Checked) else 0
            else:
                data[name] = item.text() if item else ""
        return data

    def row_to_dict_db(self, row: int) -> dict:
        cols = self.test_order_columns_db
        data = {}
        for c, name in enumerate(cols):
            item = self.testOrdersTable.item(row, c)
            if name == "include":
                data[name] = 1 if (item and item.checkState() == Qt.Checked) else 0
            else:
                data[name] = item.text() if item else ""
        return data
    



    
    def on_database_changed(self, db_name):
        # Hier vul je asset_selector, regio, value_grow etc opnieuw
        #print("Database changed:", db_name)
        self._fill_filter_comboboxes()
        self._on_filter_changed()
        self.comboBoxStatus.setCurrentText("active")
        # comment-cache opnieuw laden uit nieuwe DB en tabel verversen
        load_open_optie_comments_cache()
        self.update_opties_open_table()
        # test orders cache opnieuw laden en tabel verversen
        load_test_orders_cache_from_db()
        self.fill_test_orders_table(get_cached_orders(self.asset_selector.currentText()))
        
    def on_orders_committed(self):
        self.update_opties_open_table()
        

    @Slot()
    def save_start_date_to_settings(self):
        settings = get_settings()
        date_str = self.startDate.date().toString('yyyy-MM-dd')
        if not settings.config.has_section('app'):
            settings.config.add_section('app')
        settings.config.set('app', 'single_asset_analyse_start_date', date_str)
        settings.save()

    def _on_filter_changed(self):
        current_asset = self.asset_selector.currentText()
        regio = self.comboBoxRegio.currentText()
        status = self.comboBoxStatus.currentText()
        value_grow = self.comboBoxValueGrow.currentText()
        sector = self.comboBoxSector.currentText()
        # Lege string betekent 'geen filter'
        regio = regio if regio else None
        status = status if status else None
        value_grow = value_grow if value_grow else None
        sector = sector if sector else None
        assets = self.logic.load_assets(regio=regio, status=status, value_grow=value_grow, sector=sector)
        assets = self._apply_asset_sorting(assets)
        self.asset_selector.clear()
        self.asset_selector.addItems(assets)
        if current_asset and current_asset in assets:
            self.asset_selector.setCurrentText(current_asset)
        elif assets:
            self.asset_selector.setCurrentIndex(0)
            self.on_asset_selected(assets[0])

    def _init_sort_comboboxes(self):
        self.comboBoxSortering.clear()
        self.comboBoxSortering.addItem("alfabetisch")
        self.comboBoxSortering.addItem("pct_change")
        self.comboBoxSortering.addItem("totaal_inc_fee")
        self.comboBoxSortering.addItem("net_change")
        self.comboBoxSortering.addItem("portfolio_total_waarde_lineair_pct")
        self.comboBoxSortering.addItem("portfolio_total_waarde_delta_pct")

        self.comboBoxSortDirection.clear()
        self.comboBoxSortDirection.addItem("ASC")
        self.comboBoxSortDirection.addItem("DESC")

        self.comboBoxSortering.currentTextChanged.connect(self._on_filter_changed)
        self.comboBoxSortDirection.currentTextChanged.connect(self._on_filter_changed)

    def _apply_asset_sorting(self, assets: list[str]) -> list[str]:
        sort_key = (self.comboBoxSortering.currentText() or "").strip()
        direction = (self.comboBoxSortDirection.currentText() or "ASC").strip().upper()
        desc = direction == "DESC"

        if not sort_key or sort_key.lower() in {"alfabetisch", "alphabetisch"}:
            return sorted(assets, reverse=desc)

        df_sum = build_aandelen_tab_summary()
        if df_sum is None or df_sum.is_empty() or sort_key not in df_sum.columns:
            return sorted(assets, reverse=desc)

        df_sort = df_sum.select(["asset_rollup", sort_key])
        value_map: dict[str, float | None] = {}
        for row in df_sort.to_dicts():
            asset = row.get("asset_rollup")
            if asset is None:
                continue
            val = row.get(sort_key)
            try:
                value_map[str(asset)] = float(val) if val is not None else None
            except Exception:
                value_map[str(asset)] = None

        def _key(a: str):
            v = value_map.get(a)
            if v is None:
                return (1, 0.0)
            return (0, -v if desc else v)

        return sorted(assets, key=_key)

    def _fill_filter_comboboxes(self):
        df = getattr(SNAPSHOT_STORE, "repository_snapshot_active_asset_rollup_data", None)
        if df is None or df.height == 0:
            return
        df = df.filter(
            (pl.col("asset_rollup") != "CORRECTIE-BENCHMARK") &
            (pl.col("asset_rollup").is_not_null()) &
            (pl.col("asset_rollup").cast(str) != ""))
        self.comboBoxRegio.clear()
        self.comboBoxStatus.clear()
        self.comboBoxValueGrow.clear()
        self.comboBoxSector.clear()
        self.comboBoxRegio.addItem("")  # empty for 'all'
        self.comboBoxStatus.addItem("")
        self.comboBoxValueGrow.addItem("")
        self.comboBoxSector.addItem("")
        for val in sorted(set(df["regio"].to_list())):
            if val is not None:
                self.comboBoxRegio.addItem(str(val))
        for val in sorted(set(df["status"].to_list())):
            if val is not None:
                self.comboBoxStatus.addItem(str(val))
        for val in sorted(set(df["value_grow"].to_list())):
            if val is not None:
                self.comboBoxValueGrow.addItem(str(val))
        for val in sorted(set(df["sector"].to_list())):
            if val is not None:
                self.comboBoxSector.addItem(str(val))


    def _filter_dataframe(self, df, filters):
        # print(f"DEBUG: _filter_dataframe filters = {filters}")
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
                cols = getattr(source_model, "_df", None).columns if getattr(source_model, "_df", None) is not None else []
                colname = cols[source_index.column()] if cols else source_model.headerData(source_index.column(), Qt.Horizontal)
                value = source_model.data(source_index, Qt.DisplayRole)
            else:
                cols = getattr(model, "_df", None).columns if getattr(model, "_df", None) is not None else []
                colname = cols[index.column()] if cols else model.headerData(index.column(), Qt.Horizontal)
                value = model.data(index, Qt.DisplayRole)
            if colname == "asset_rollup":
                idx = self.asset_selector.findText(value)
                if idx >= 0:
                    self.asset_selector.setCurrentIndex(idx)
        except Exception:
            # Onderdruk Qt warning
            pass

    def _on_test_order_cell_clicked(self, row, col):
        """Klik op asset in test-orders tabel: stel asset_selector in en reload."""
        try:
            asset_col = self.test_order_columns.index("asset_rollup")
        except ValueError:
            return
        if col != asset_col:
            return
        item = self.testOrdersTable.item(row, col)
        if not item:
            return
        value = (item.text() or "").strip()
        if not value:
            return
        idx = self.asset_selector.findText(value)
        if idx >= 0:
            self.asset_selector.setCurrentIndex(idx)

    def update_sprinters_table(self):
        import polars as pl

        df = getattr(SNAPSHOT_STORE, "aggregator_snapshot_open_sprinters_live", None)
        if df is None or df.is_empty() or "asset_rollup" not in df.columns:
            self.tableViewSprinters.setModel(None)  # Tabel leegmaken!
            return
        else:
            asset = self.asset_selector.currentText()
            df = df.filter(pl.col("asset_rollup") == asset)
        
        # Filter op asset_rollup
        
        # Selecteer relevante kolommen (pas aan indien gewenst)
        df = df.select([
            "broker",
            "asset_rollup",
            "asset_detail",
            "optie_exp_date",
            "optie_strike", 
            "optie_call_put",
            "Koers",
            "SomVantransactie_aantal",
            "sp_result"
        ])
        kleur_kolommen = ["broker", "asset_rollup", "SomVantransctie_aantal"]
        def kleur_func(row, colname, kleur_kolommen):
            return None
        model = AandelenTableModel(df, kleur_kolommen, kleur_func, self)
        self.tableViewSprinters.setModel(model)
        # Kolombreedtes instellen per kolom
        kolombreedtes = {
            "broker": 60,
            "asset_rollup": 75,
            "asset_detail": 90,
            "optie_exp_date": 60,
            "optie_strike": 40,
            "optie_call_put": 40,
            "Koers": 40,
            "SomVantransactie_aantal": 60,
            "sp_result": 60,
        }
        header = self.tableViewSprinters.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for i, col in enumerate(df.columns):
            if col in kolombreedtes:
                header.resizeSection(i, kolombreedtes[col])
        font = QFont("Arial", 8)
        font.setBold(False)
        self.tableViewSprinters.setFont(font)
        self.tableViewSprinters.verticalHeader().setVisible(False)



    def update_aandelen_table(self):
        import polars as pl
        df = getattr(SNAPSHOT_STORE, "aggregator_snapshot_aandelen_live", None)
        if df is None or df.is_empty():
            df = pl.DataFrame()
        asset = self.asset_selector.currentText()
        # Filter op asset_rollup en aantal_bezit
        df = df.filter(pl.col("asset_rollup") == asset)
        df = df.filter(pl.col("aantal_bezit") != 0)
        # Voeg berekende kolom toe: waarde_bezit = koers * aantal_bezit
        if "koers" in df.columns and "aantal_bezit" in df.columns:
            df = df.with_columns([
                pl.col("aantal_bezit").cast(pl.Float64),
                (pl.col("koers") * pl.col("aantal_bezit")).alias("waarde_bezit")
            ])
        # Selecteer de gewenste kolommen
        df = df.select([
            "broker",
            "asset_rollup",
            "koers",
            "aantal_bezit",
            "waarde_bezit"
        ])
        kleur_kolommen = ["broker", "asset_rollup", "aantal_bezit"]
        columns = df.columns #noqa
        def kleur_func(row, colname, kleur_kolommen):
            # Optioneel: eigen kleurfunctie
            return None
        model = AandelenTableModel(df, kleur_kolommen, kleur_func, self)
        self.tableViewAandelen.setModel(model)
        # Kolombreedtes instellen per kolom
        kolombreedtes = {
            "broker": 60,
            "asset_rollup": 90,
            "koers": 60,
            "aantal_bezit": 90,
            "waarde_bezit": 90,
        }
        header = self.tableViewAandelen.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for i, col in enumerate(df.columns):
            if col in kolombreedtes:
                header.resizeSection(i, kolombreedtes[col])
        # Optioneel: font instellen
        font = QFont("Arial", 8)
        font.setBold(False)
        self.tableViewAandelen.setFont(font)
        self.tableViewAandelen.verticalHeader().setVisible(False)
        self._update_summary_labels()

    def _align_summary_labels(self):
        labels = [
            "lbKoersPrev",
            "lblKoers",
            "lblPctChange",
            "lblNetChange",
            "lblPctLineair",
            "lblPctDelta",
        ]
        for name in labels:
            label = getattr(self, name, None)
            if label is not None:
                label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def _format_number(self, val, decimals=2):
        if val is None:
            return "-"
        try:
            return f"{float(val):.{decimals}f}"
        except Exception:
            return str(val)

    def _format_pct(self, val, decimals=2):
        if val is None:
            return "-"
        try:
            return f"{float(val) * 100:.{decimals}f}%"
        except Exception:
            return str(val)

    def _set_label_bg(self, label, color: QColor | None):
        if label is None:
            return
        if color is None:
            label.setStyleSheet("")
            return
        label.setStyleSheet(f"background-color: {color.name()};")

    def _color_green_red(self, val):
        try:
            f = float(val)
        except Exception:
            return None
        if f > 0:
            return QColor(198, 239, 206)
        if f < 0:
            return QColor(255, 199, 206)
        return None

    def _pct_gradient_color(self, val, minv, maxv):
        try:
            f = float(val)
        except Exception:
            f = 0.0
        if maxv - minv == 0:
            t = 0.0
        else:
            t = (f - minv) / (maxv - minv)
            t = max(0.0, min(1.0, t))
        if t < 0.5:
            t2 = t / 0.5
            r = int(0 + (255 - 0) * t2)
            g = int(180 + (255 - 180) * t2)
            b = int(90 + (160 - 90) * t2)
        else:
            t2 = (t - 0.5) / 0.5
            r = int(255)
            g = int(255 - (255 - 90) * t2)
            b = int(160 - (160 - 90) * t2)
        return QColor(r, g, b)

    def _get_portfolio_value_pct_color(self, asset_rollup: str, colname: str):
        df = getattr(SNAPSHOT_STORE, "repository_snapshot_portfolio_value_total_combined_put", None)
        if df is None or df.is_empty():
            return None
        if colname not in df.columns:
            if colname == "portfolio_total_waarde_lineair_pct" and "total_waarde_lineair" in df.columns:
                try:
                    total = float(df["total_waarde_lineair"].sum())
                    if total != 0:
                        df = df.with_columns((pl.col("total_waarde_lineair") / total).alias(colname))
                except Exception:
                    return None
            elif colname == "portfolio_total_waarde_delta_pct" and "total_waarde_delta" in df.columns:
                try:
                    total = float(df["total_waarde_delta"].sum())
                    if total != 0:
                        df = df.with_columns((pl.col("total_waarde_delta") / total).alias(colname))
                except Exception:
                    return None
        if colname not in df.columns:
            return None
        try:
            vals = [float(v) for v in df[colname].to_list() if v is not None]
            if not vals:
                return None
            minv, maxv = min(vals), max(vals)
            if minv == maxv:
                minv, maxv = 0.0, maxv
            row = df.filter(pl.col("asset_rollup") == asset_rollup)
            if row.height == 0:
                return None
            val = row[colname][0]
            return self._pct_gradient_color(val, minv, maxv)
        except Exception:
            return None

    def _update_summary_labels(self):
        asset = self.asset_selector.currentText()
        df_sum = build_aandelen_tab_summary(asset_rollup=asset)
        row = df_sum.row(0, named=True) if df_sum is not None and not df_sum.is_empty() else None

        koers_prev_val = row.get("koers_prev") if row else None
        koers_val = row.get("koers") if row else None

        if hasattr(self, "lbKoersPrev"):
            self.lbKoersPrev.setText(self._format_number(koers_prev_val))
            self._set_label_bg(self.lbKoersPrev, QColor(221, 235, 247))
        if hasattr(self, "lblKoers"):
            self.lblKoers.setText(self._format_number(koers_val))
            koers_color = None
            try:
                if koers_val is not None and koers_prev_val is not None:
                    if float(koers_val) > float(koers_prev_val):
                        koers_color = QColor(198, 239, 206)
                    elif float(koers_val) < float(koers_prev_val):
                        koers_color = QColor(255, 199, 206)
            except Exception:
                koers_color = None
            self._set_label_bg(self.lblKoers, koers_color)
        if hasattr(self, "lblPctChange"):
            pct_val = row.get("pct_change") if row else None
            self.lblPctChange.setText(self._format_pct(pct_val))
            self._set_label_bg(self.lblPctChange, self._color_green_red(pct_val))
        if hasattr(self, "lblNetChange"):
            net_val = row.get("net_change") if row else None
            self.lblNetChange.setText(self._format_number(net_val))
            self._set_label_bg(self.lblNetChange, self._color_green_red(net_val))

        if hasattr(self, "lblPctLineair"):
            val = row.get("portfolio_total_waarde_lineair_pct") if row else None
            self.lblPctLineair.setText(self._format_pct(val, decimals=1))
            self._set_label_bg(
                self.lblPctLineair,
                self._get_portfolio_value_pct_color(asset, "portfolio_total_waarde_lineair_pct"),
            )
        if hasattr(self, "lblPctDelta"):
            val = row.get("portfolio_total_waarde_delta_pct") if row else None
            self.lblPctDelta.setText(self._format_pct(val, decimals=1))
            self._set_label_bg(
                self.lblPctDelta,
                self._get_portfolio_value_pct_color(asset, "portfolio_total_waarde_delta_pct"),
            )



    def update_opties_open_table(self):
        df = self.logic.load_option_open_data()
        asset = self.asset_selector.currentText()
        # Voor de eerste tabel géén asset-filtering, volledige tabel tonen
        df_all = df.drop("totaal_fees")
        df_all = df_all.sort(["optie_exp_date", "asset_rollup"])
        if "uniek_id" in df_all.columns:
            uniek_ids = df_all["uniek_id"].to_list()
            # print(f"[comments] update_opties_open_table: {len(uniek_ids)} uniek_ids in df_all")
            df_comments = fetch_open_optie_comments(uniek_ids)
            # Zorg dat join-keys dezelfde dtype hebben, ook bij lege resultaten
            if df_comments is None or df_comments.is_empty():
                df_comments = pl.DataFrame(
                    {
                        "uniek_id": pl.Series([], dtype=pl.Utf8),
                        "optie_comment": pl.Series([], dtype=pl.Utf8),
                        "optie_comment_textcolor": pl.Series([], dtype=pl.Utf8),
                        "optie_comment_updated_at": pl.Series([], dtype=pl.Datetime),
                    }
                )
            else:
                df_comments = df_comments.with_columns([
                    pl.col("uniek_id").cast(pl.Utf8),
                    pl.col("optie_comment").cast(pl.Utf8),
                ])
            df_all = df_all.with_columns(pl.col("uniek_id").cast(pl.Utf8))
            # join met suffix en daarna coalesce zodat we geen _right kolommen houden
            df_all = df_all.join(df_comments, on="uniek_id", how="left", suffix="_comment_db")
            # print(f"[comments] join result rows={df_all.height}, cols={df_all.columns}")
            # coalesce met checks zodat ontbrekende suffix kolommen geen fout geven
            exprs = []
            if "optie_comment_comment_db" in df_all.columns:
                exprs.append(pl.coalesce([pl.col("optie_comment_comment_db"), pl.col("optie_comment")]).fill_null("").alias("optie_comment"))
            else:
                exprs.append(pl.col("optie_comment").fill_null("").alias("optie_comment"))
            if "optie_comment_updated_at_comment_db" in df_all.columns:
                exprs.append(pl.coalesce([pl.col("optie_comment_updated_at_comment_db"), pl.col("optie_comment_updated_at")]).alias("optie_comment_updated_at"))
            else:
                exprs.append(pl.col("optie_comment_updated_at"))
            if "optie_comment_color_comment_db" in df_all.columns:
                exprs.append(pl.coalesce([pl.col("optie_comment_color_comment_db"), pl.col("optie_comment_color")]).fill_null("").alias("optie_comment_color"))
            else:
                exprs.append(pl.col("optie_comment_color").fill_null("").alias("optie_comment_color"))
            if "optie_comment_textcolor_comment_db" in df_all.columns:
                exprs.append(pl.coalesce([pl.col("optie_comment_textcolor_comment_db"), pl.col("optie_comment_textcolor")]).fill_null("").alias("optie_comment_textcolor"))
            else:
                exprs.append(pl.col("optie_comment_textcolor").fill_null("").alias("optie_comment_textcolor"))
            df_all = df_all.with_columns(exprs)
            # opruimen helperkolommen indien aanwezig
            for col in ("optie_comment_comment_db", "optie_comment_updated_at_comment_db", "optie_comment_color_comment_db", "optie_comment_textcolor_comment_db"):
                if col in df_all.columns:
                    df_all = df_all.drop(col)
        # Put/Call tabellen moeten NIET meefilteren met de hoofdtable filters.
        df_all_for_putcall = df_all
        df_all_filtered = df_all
        if hasattr(self, "active_filters_opties_open") and self.active_filters_opties_open:
            df_all_filtered = self._filter_dataframe(df_all_filtered, self.active_filters_opties_open)
        # Voor put/call tabellen wél filteren
        df_put = (
            df_all_for_putcall
            .filter(pl.col("asset_rollup") == asset)
            .filter(pl.col("optie_call_put") == "put")
        )
        df_put = df_put.sort("optie_exp_date")
        df_call = (
            df_all_for_putcall
            .filter(pl.col("asset_rollup") == asset)
            .filter(pl.col("optie_call_put") == "call")
        )
        df_call = df_call.sort("optie_exp_date")

        kleur_kolommen = ["broker", "asset_rollup", "optie_call_put", "optie_strike", "optie_exp_date","afwijking_pct"]
        df_columns = df_all_filtered.columns
        def kleur_func(row, colname, kleur_kolommen):
            return self.opties_kleur_func(row, colname, kleur_kolommen, df_columns)

        font = QFont("Arial", 8)
        font.setBold(False)
        kolombreedtes = {
            "itm": 35,
            "broker": 60,
            "asset_rollup": 75,
            "optie_call_put": 35,
            "optie_exp_date": 75,
            "optie_strike": 50,
            "Koers": 50,
            "afwijking_pct": 60,
            "aantal_bezit": 60,
            "premie": 60,
            
            "itm_otm": 60,
            "totaal_resultaat_optie": 60,
            
            
            "optie_comment": 305,
            "optie_comment_updated_at": 75,
            "optie_comment_color": 60,
        }

        # Alle opties (volledige tabel, geen asset-filter)
        model_all = CommentablePolarsTableModel(
            df_all_filtered,
            kleur_kolommen,
            kleur_func,
            self,
            editable_cols={"optie_comment"},
            commit_callback=self._on_comment_commit,
        )
        color_priority_map = get_settings().get_comment_color_priority_map()
        model_all.set_color_priority_map(color_priority_map)
        model_all.set_comment_color_text_map(get_settings().get_comment_color_text_map())
        display_headers = {
            "asset_rollup": "asset",
            "optie_call_put": "c/p",
            "optie_exp_date": "exp date",
            "optie_strike": "strike",
            "aantal_bezit": "aantal",
            "totaal_resultaat_optie": "result",
            "afwijking_pct": "delta",
            "optie_comment": "comment",
            "optie_comment_updated_at": "updated",
        }
        model_all.set_display_headers(display_headers)
        self._table_model = model_all  # model_all is je hoofdmodel voor de tabel
        self._model_opties_all = model_all
        proxy_model = CommentSortProxy(self)
        proxy_model.setSourceModel(model_all)
        proxy_model.setSortRole(Qt.UserRole)
        #print("Disconnecting click handler, replacing model")
        # self.tableViewOptiesOpen.clicked.disconnect(self._on_table_cell_clicked)
        self.tableViewOptiesOpen.setModel(proxy_model)
        self.tableViewOptiesOpen.setSortingEnabled(True)
        # self.tableViewOptiesOpen.clicked.connect(self._on_table_cell_clicked)
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
        self.tableViewOptiesOpen.verticalHeader().setVisible(False)
        if "uniek_id" in df_all.columns:
            idx_all_uniek = df_all.columns.index("uniek_id")
            self.tableViewOptiesOpen.setColumnHidden(idx_all_uniek, True)
        if "optie_comment_color" in df_all.columns:
            idx_color = df_all.columns.index("optie_comment_color")
            self.tableViewOptiesOpen.setColumnHidden(idx_color, True)
        if "optie_comment_textcolor" in df_all.columns:
            idx_text = df_all.columns.index("optie_comment_textcolor")
            self.tableViewOptiesOpen.setColumnHidden(idx_text, True)

        # Put opties (wel asset-filter)
        model_put = CommentablePolarsTableModel(
            df_put,
            kleur_kolommen,
            kleur_func,
            self,
            editable_cols={"optie_comment"},
            commit_callback=self._on_comment_commit,
        )
        model_put.set_color_priority_map(color_priority_map)
        model_put.set_comment_color_text_map(get_settings().get_comment_color_text_map())
        model_put.set_display_headers(display_headers)
        proxy_put = CommentSortProxy(self)
        proxy_put.setSourceModel(model_put)
        proxy_put.setSortRole(Qt.UserRole)
        self.tableViewOptiesOpenPut.setModel(proxy_put)
        self.tableViewOptiesOpenPut.setSortingEnabled(True)
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
        self.tableViewOptiesOpenPut.verticalHeader().setVisible(False)
        if "uniek_id" in df_put.columns:
            idx_put_uniek = df_put.columns.index("uniek_id")
            self.tableViewOptiesOpenPut.setColumnHidden(idx_put_uniek, True)
        if "optie_comment_color" in df_put.columns:
            idx_color = df_put.columns.index("optie_comment_color")
            self.tableViewOptiesOpenPut.setColumnHidden(idx_color, True)
        if "optie_comment_textcolor" in df_put.columns:
            idx_text = df_put.columns.index("optie_comment_textcolor")
            self.tableViewOptiesOpenPut.setColumnHidden(idx_text, True)
        self._model_opties_put = model_put

        # Call opties (wel asset-filter)
        model_call = CommentablePolarsTableModel(
            df_call,
            kleur_kolommen,
            kleur_func,
            self,
            editable_cols={"optie_comment"},
            commit_callback=self._on_comment_commit,
        )
        model_call.set_color_priority_map(color_priority_map)
        model_call.set_comment_color_text_map(get_settings().get_comment_color_text_map())
        model_call.set_display_headers(display_headers)
        proxy_call = CommentSortProxy(self)
        proxy_call.setSourceModel(model_call)
        proxy_call.setSortRole(Qt.UserRole)
        self.tableViewOptiesOpenCall.setModel(proxy_call)
        self.tableViewOptiesOpenCall.setSortingEnabled(True)
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
        self.tableViewOptiesOpenCall.verticalHeader().setVisible(False)
        if "uniek_id" in df_call.columns:
            idx_call_uniek = df_call.columns.index("uniek_id")
            self.tableViewOptiesOpenCall.setColumnHidden(idx_call_uniek, True)
        if "optie_comment_color" in df_call.columns:
            idx_color = df_call.columns.index("optie_comment_color")
            self.tableViewOptiesOpenCall.setColumnHidden(idx_color, True)
        if "optie_comment_textcolor" in df_call.columns:
            idx_text = df_call.columns.index("optie_comment_textcolor")
            self.tableViewOptiesOpenCall.setColumnHidden(idx_text, True)
        self._model_opties_call = model_call
        

    def _on_comment_commit(self, row_data: dict):
        """Sla bewerkte comment op en herlaad de tabellen zodat alle views synchroon blijven."""
        try:
            uniek_id = row_data.get("uniek_id")
            comment = row_data.get("optie_comment") or ""
            ts = row_data.get("optie_comment_updated_at")
            color = row_data.get("optie_comment_color") or ""
            textcolor = row_data.get("optie_comment_textcolor") or ""
            # print(f"[comments] commit uniek_id={uniek_id}, comment='{comment}', color='{color}', ts={ts}")
            upsert_open_optie_comment(uniek_id, comment, color, textcolor, ts)
        except Exception as e:
            print(f"Kon optie-comment niet opslaan: {e}")
            return
        # Na opslaan laatste comment ophalen en in bestaande modellen patchen (geen volledige reload)
        latest = fetch_open_optie_comments([uniek_id])
        if latest is not None and not latest.is_empty():
            latest_row = latest.row(0, named=True)
            comment_new = latest_row.get("optie_comment") or ""
            color_new = latest_row.get("optie_comment_color") or ""
            textcolor_new = latest_row.get("optie_comment_textcolor") or ""
            ts_new = latest_row.get("optie_comment_updated_at")
        else:
            comment_new = comment
            color_new = color
            textcolor_new = textcolor
            ts_new = ts
        self._patch_comment_in_models(uniek_id, comment_new, color_new, textcolor_new, ts_new)
        if not self.commentFlushTimer.isActive():
            self.commentFlushTimer.start()

    def _patch_comment_in_models(self, uniek_id: str, comment: str, color: str, textcolor: str, ts):
        """Werk comment/timestamp bij in alle optie modellen zonder volledige reload."""
        if not uniek_id:
            return
        # print(f"[comments] patch models voor {uniek_id} -> '{comment}' color='{color}' @ {ts}")
        def _update_model(model: CommentablePolarsTableModel | None):
            if model is None or getattr(model, "_df", None) is None:
                return
            df = model._df
            if "uniek_id" not in df.columns:
                return
            df = df.with_columns([
                pl.when(pl.col("uniek_id") == uniek_id).then(pl.lit(comment)).otherwise(pl.col("optie_comment")).alias("optie_comment"),
                pl.when(pl.col("uniek_id") == uniek_id).then(pl.lit(color)).otherwise(pl.col("optie_comment_color")).alias("optie_comment_color"),
                pl.when(pl.col("uniek_id") == uniek_id).then(pl.lit(textcolor)).otherwise(pl.col("optie_comment_textcolor")).alias("optie_comment_textcolor"),
                pl.when(pl.col("uniek_id") == uniek_id).then(pl.lit(ts)).otherwise(pl.col("optie_comment_updated_at")).alias("optie_comment_updated_at"),
            ])
            model.set_df(df)

        _update_model(getattr(self, "_model_opties_all", None))
        _update_model(getattr(self, "_model_opties_put", None))
        _update_model(getattr(self, "_model_opties_call", None))

    def _on_comment_context_menu_for_view(self, view, pos):
        index = view.indexAt(pos)
        if not index.isValid():
            return
        model = view.model()
        src_index = model.mapToSource(index) if hasattr(model, "mapToSource") else index
        source_model = model.sourceModel() if hasattr(model, "sourceModel") else model
        cols = getattr(source_model, "_df", None).columns if getattr(source_model, "_df", None) is not None else []
        if not cols:
            return
        col_name = cols[src_index.column()]
        if col_name != "optie_comment":
            return
        try:
            uniek_id_idx = cols.index("uniek_id")
        except ValueError:
            return
        color_idx = cols.index("optie_comment_color") if "optie_comment_color" in cols else None
        current_uniek_id = source_model._df[src_index.row(), uniek_id_idx]
        current_comment = source_model._df[src_index.row(), src_index.column()] or ""
        current_color = source_model._df[src_index.row(), color_idx] if color_idx is not None else ""

        menu = QMenu(self)
        color_defs = get_settings().get_comment_colors()
        for _prio, label, bg_hex, _fg_hex in color_defs:
            act = QAction(label, menu)
            act.setData(bg_hex)
            menu.addAction(act)

        menu.addSeparator()
        act_custom = QAction("Kies kleur...", menu)
        menu.addAction(act_custom)

        chosen = menu.exec(view.mapToGlobal(pos))
        if not chosen:
            return
        if chosen == act_custom:
            color = QColorDialog.getColor(QColor(current_color) if current_color else QColor("#ffffff"), self, "Kies kleur")
            if not color.isValid():
                return
            hexval = color.name()
        else:
            hexval = chosen.data()

        try:
            fg_by_bg = get_settings().get_comment_color_text_map()
            textcolor = fg_by_bg.get(hexval, "")
            latest = fetch_open_optie_comments([current_uniek_id])
            if latest is None or latest.is_empty():
                upsert_open_optie_comment(current_uniek_id, current_comment or "", hexval, textcolor)
                latest = fetch_open_optie_comments([current_uniek_id])
            else:
                update_open_optie_comment_color(current_uniek_id, hexval, textcolor)
                latest = fetch_open_optie_comments([current_uniek_id])
            if latest is not None and not latest.is_empty():
                row = latest.row(0, named=True)
                self._patch_comment_in_models(
                    current_uniek_id,
                    row.get("optie_comment") or "",
                    row.get("optie_comment_color") or "",
                    row.get("optie_comment_textcolor") or "",
                    row.get("optie_comment_updated_at"),
                )
            if not self.commentFlushTimer.isActive():
                self.commentFlushTimer.start()
        except Exception as exc:
            print(f"[comments] kon kleur niet opslaan: {exc}")

    def _on_header_menu_for_view(self, view, pos):
        """
        Header-menu met extra sorteeropties op kleur voor de commentkolom.
        """
        header = view.horizontalHeader()
        section = header.logicalIndexAt(pos)
        model = view.model()
        source_model = model.sourceModel() if hasattr(model, "sourceModel") else model
        try:
            colname = source_model._df.columns[section]
        except Exception:
            return

        menu = QMenu(self)
        a_color_desc = a_color_asc = None
        if colname == "optie_comment":
            a_color_desc = menu.addAction("Sorteren op kleur (rood→groen)")
            a_color_asc = menu.addAction("Sorteren op kleur (groen→rood)")
            menu.addSeparator()

        a_asc  = menu.addAction("Sorteren A → Z")
        a_desc = menu.addAction("Sorteren Z → A")
        menu.addSeparator()
        a_clear = menu.addAction(f"Filter van {colname} wissen")
        menu.addSeparator()
        a_contains = menu.addAction("Tekst bevat...")
        a_equals   = menu.addAction("Is precies...")
        menu.addSeparator()
        a_color_filter = None
        if colname == "optie_comment":
            a_color_filter = menu.addAction("Filter op kleur...")
            menu.addSeparator()
        a_pick = menu.addAction("Waarden kiezen...")

        act = menu.exec(header.mapToGlobal(pos))
        if not act:
            return
        if act == a_color_desc:
            view.sortByColumn(section, Qt.DescendingOrder)
            return
        if act == a_color_asc:
            view.sortByColumn(section, Qt.AscendingOrder)
            return
        if act in (a_asc, a_desc):
            order = Qt.AscendingOrder if act == a_asc else Qt.DescendingOrder
            view.sortByColumn(section, order)
            return

        if act == a_clear:
            self._col_filters.pop(colname, None)
            self.apply_filters()
            return
        if act == a_contains:
            text, ok = QInputDialog.getText(self, f"{colname} bevat", "Tekst:")
            if ok and text.strip():
                self._col_filters[colname] = {"contains": text.strip()}
                self.apply_filters()
            return

        if act == a_equals:
            text, ok = QInputDialog.getText(self, f"{colname} is precies", "Waarde:")
            if ok and text.strip():
                self._col_filters[colname] = {"eq": text.strip()}
                self.apply_filters()
            return

        if act == a_color_filter:
            self._open_comment_color_popup(header.mapToGlobal(pos))
            return

        if act == a_pick:
            self._open_value_popup_for_column(colname, header.mapToGlobal(pos))
            return

    def _open_comment_color_popup(self, global_pos):
        color_defs = get_settings().get_comment_colors() or []
        values = [bg_hex for _prio, _label, bg_hex, _fg_hex in color_defs if bg_hex]
        if "" not in values:
            values.insert(0, "")
        label_map = {"": "Geen kleur"}
        for _prio, label, bg_hex, _fg_hex in color_defs:
            if bg_hex:
                label_map[bg_hex] = label

        pre = set()
        if "optie_comment_color" in (self._col_filters or {}) and "in" in self._col_filters["optie_comment_color"]:
            pre = set(self._col_filters["optie_comment_color"]["in"])

        pop = ColumnFilterPopup("Filter: comment kleur", values, pre_selected=pre, parent=self, label_map=label_map)
        pop.move(global_pos)
        pop.acceptedSelection.connect(lambda selected: self._apply_in_filter("optie_comment_color", selected))
        pop.cleared.connect(lambda: self._clear_col_filter("optie_comment_color"))
        pop.show()


    def on_asset_selected(self, asset_rollup):
        self.logic.enable_test_orders = getattr(self, "enable_test_orders", True)
        self.logic.set_asset(asset_rollup)
        # Laad testorders uit DB voor dit asset en vul de tabel
        try:
            if getattr(self, "show_all_test_orders", False):
                cache = getattr(SNAPSHOT_STORE, "repository_snapshot_test_orders_cache", {}) or {}
                if cache:
                    df_orders = pl.concat(cache.values(), how="diagonal_relaxed")
                else:
                    df_orders = None
            else:
                df_orders = get_cached_orders(asset_rollup)
        except Exception as e:
            print(f"Kon testorders niet laden: {e}")
            df_orders = None
        self.fill_test_orders_table(df_orders)

        self.update_payoff_table()
        self.update_history_charts()
        self.update_opties_open_table()
        self.update_aandelen_table()
        self.update_sprinters_table()

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

        import numpy as np
        x = np.arange(len(df))
        datums = df["datum"].to_list()
        close_price = [float(v) if v is not None and v != '' else 0.0 for v in df["close_price"].to_list()]
        aantal = [float(v) if v is not None and v != '' else 0.0 for v in df["totaal_aantal_bezit"].to_list()]
        factor = getattr(self.logic, "currency_factor", 1.0)
        totaal = [float(v) / factor if v is not None and v != '' else 0.0 for v in df["totaal"].to_list()]

        # --- Chart 1: priceAantalChart (zoals eerder) ---
        pw = self.priceAantalChart
        self._ensure_history_charts_right_axis()
        pw.clear()
        pw.plotItem.clear()
        pw.plot(x, close_price, pen='b', name="Koers")
        self._rightView.clear()
        aantal_curve = pg.PlotCurveItem(x, aantal, pen=pg.mkPen('g', width=2), name="Aantal bezit")
        self._rightView.addItem(aantal_curve)
        pw.plotItem.getAxis('right').setLabel('Aantal bezit', color='g')
        ticks = [(i, str(datums[i])) for i in range(0, len(datums), max(1, len(datums)//10))]
        ax = pw.getPlotItem().getAxis('bottom')
        ax.setTicks([ticks])
        pw.plotItem.setLabel('left', '')
        pw.plotItem.setLabel('bottom', '')
        self._set_plot_ranges(pw, x, close_price)
        if aantal:
            y_min, y_max = float(min(aantal)), float(max(aantal))
            if y_min == y_max:
                y_max = y_min + 1.0
            self._rightView.setYRange(y_min, y_max, padding=0.02)

        # --- Chart 2: resultaatChart ---
        rw = self.resultaatChart
        rw.clear()
        rw.plotItem.clear()
        rw.plot(x, totaal, pen=pg.mkPen('orange', width=2), name="Totaal")
        rw.plotItem.setLabel('left', '')
        rw.plotItem.setLabel('bottom', '')
        self._set_plot_ranges(rw, x, totaal)
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
        self._col_filters = {}
        # ...vervolgens: plot df in je pyqtgraph-widgets
    
    @staticmethod
    def opties_kleur_func(row, colname, kleur_kolommen, columns):
        try:
            # map kolomnamen -> waarden zodat volgorde geen rol speelt
            if isinstance(row, dict):
                val_map = row
            else:
                val_map = {columns[i]: row[i] for i in range(min(len(columns), len(row)))}
            optie_call_put = val_map.get("optie_call_put")
            itm_otm = val_map.get("itm_otm")
            # print(f"DEBUG opties_kleur_func: colname={colname}, optie_call_put={optie_call_put}, itm_otm={itm_otm}")
            if colname in kleur_kolommen and itm_otm is not None and itm_otm != 0:
                if optie_call_put == "put":
                    return QColor(255, 200, 200)
                elif optie_call_put == "call":
                    return QColor(200, 255, 200)
        except Exception as e:
            print(f"DEBUG Exception: {e}")
        return None

    def update_payoff_table(self):
        #print("Updating payoff table...")
        # Gebaseerd op oude code, maar nu via self.logic
        asset_rollup = self.asset_selector.currentText()
        live_price = 100

        ib_symbol = ib_currency = None
        df_rollup = getattr(SNAPSHOT_STORE, "repository_snapshot_asset_rollup_data", None)
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

        step_pct = self.stepSizeBox.value()
        step_size = step_pct / 100.0
        steps = [round(center * (i - 8) * step_size + center, 2) for i in range(17)]
        self._payoff_steps = steps

        def _format_step(val: float) -> str:
            try:
                if abs(val) >= 1000:
                    text = f"{val:,.0f}"
                else:
                    text = f"{val:,.2f}"
                return text.replace(",", "X").replace(".", ",").replace("X", ".")
            except Exception:
                return str(val)

        headers = [_format_step(s) for s in steps]

        self.payoff_table.setHorizontalHeaderLabels(headers)

        row_labels = [
            "Open aandelen",
            "Open sprinters",
            "Open opties",
            "Gesloten aandelen",
            "Gesloten sprinters",
            "Gesloten opties",
                        
            "Dividend",
            "Totaal zonder fees",
            "Fees",
            "Totaal",
        ]
        for row, label in enumerate(row_labels):
            self.payoff_table.setVerticalHeaderItem(row, QTableWidgetItem(label))

        # Bereken payoff-matrix via self.logic
        
        self.payoff_matrix = [[self.logic.payoff_open_aandelen(s) for s in steps]]
        self.payoff_matrix.append([self.logic.payoff_open_sprinters(s) for s in steps])
        self.payoff_matrix.append([self.logic.payoff_open_opties(s) for s in steps])
        self.payoff_matrix.append([self.logic.payoff_gesloten_aandelen() for _ in steps])
        self.payoff_matrix.append([self.logic.payoff_gesloten_sprinters(s) for s in steps])
        self.payoff_matrix.append([self.logic.payoff_gesloten_opties(s) for s in steps])
        
        dividend_val = self.logic.get_dividend(asset_rollup)
        self.payoff_matrix.append([dividend_val for _ in steps])

        payoff_totaal_zonder_fees = [sum(self.payoff_matrix[row][i] for row in range(7)) for i in range(17)]
        self.payoff_matrix.append(payoff_totaal_zonder_fees)

        payoff_fees = self.logic.get_fees(steps)
        self.payoff_matrix.append(payoff_fees)

        payoff_totaal = [self.payoff_matrix[7][i] + self.payoff_matrix[8][i] for i in range(17)]
        self.payoff_matrix.append(payoff_totaal)

        factor = getattr(self.logic, "currency_factor", 1.0)

        middle_col = 8
        sub_total_row = 7
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
                val = self.payoff_matrix[row][col] / factor
                display_val = abs(int(round(val, 0))) if val < 0 else int(round(val, 0))
                item = QTableWidgetItem(str(display_val))
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                #item = QTableWidgetItem(str(int(round(val, 0))))
                
                # Alleen de laatste rij (total_row) bold maken
                if row == sub_total_row:
                #     #item.setFont(boldfont) 
                    item.setBackground(lightgrey)
                if row == total_row:
                    item.setFont(boldfont)
                    item.setBackground(lightblue)

                else:
                    # Normale font voor alle andere cellen
                    normalfont = QFont()
                    normalfont.setBold(False)
                    item.setFont(normalfont)
                if val < 0:
                    item.setForeground(QColor(220, 0, 0))
                if col == middle_col:
                    item.setBackground(lightgrey)
                self.payoff_table.setItem(row, col, item)

        self.payoff_table.viewport().update()
        self.update_chart()
        for row in range(10):
            self.payoff_table.setRowHeight(row, 22)  # pas 22 aan voor nog compacter/ruimer
            #print(f"DEBUG: payoff_table row {row} height =", self.payoff_table.rowHeight(row))

    @Slot()
    def apply_filters_opties_open(self):
        q = self.lineEditFilterOptiesOpen.text().strip()
        filters = {"q": q} if q else {}

        # ...en kolomfilters toevoegen...
        for col, spec in (self._col_filters or {}).items():
            if "in" in spec:
                filters[f"__in__{col}"] = list(spec["in"])
            if "contains" in spec:
                filters[f"__contains__{col}"] = spec["contains"]
            if "eq" in spec:
                filters[f"__eq__{col}"] = spec["eq"]
            if "date_on" in spec and spec["date_on"]:
                filters[f"__date_on__{col}"] = spec["date_on"]
        # self.active_filters = filters
        # print(f"Applying filters opties open: {filters}")
        self.active_filters_opties_open = filters
        self.update_opties_open_table()


    def _on_clear_filters_opties_open(self):
        self._col_filters.clear()
        self.lineEditFilterOptiesOpen.clear()
        self.apply_filters_opties_open()




    def update_chart(self):
        #print("Updating payoff chart...")
        factor = getattr(self.logic, "currency_factor", 1.0)
        self.plot_widget.clear()
        # x-as: koerswaarden uit de berekende stappen (niet uit de geformatteerde header)
        x_values = []
        steps = getattr(self, "_payoff_steps", None)
        if steps and len(steps) == self.payoff_table.columnCount():
            x_values = list(steps)
        else:
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
            #item_totaal = self.payoff_table.item(9, i)
            #totaal_val = float(item_totaal.text()) if item_totaal and item_totaal.text() else 0
            # item_open_opties = self.payoff_table.item(0, i)
            # open_opties_val = float(item_open_opties.text()) if item_open_opties and item_open_opties.text() else 0
            
            totaal_val = self.payoff_matrix[9][i] / factor
            open_opties_val = self.payoff_matrix[2][i] / factor
            
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
        if x_values:
            x_min, x_max = min(x_values), max(x_values)
            if x_min == x_max:
                x_max = x_min + 1.0
            self.plot_widget.setXRange(x_min, x_max, padding=0.02)

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

        self.plot_widget.setLabel('left', '')
        self.plot_widget.setLabel('bottom', '')
        # self.plot_widget.setTitle('Payoff per koersstap')
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
        self.enable_test_orders = True
        self.df_open_opties = None
        self.df_gesloten_opties = None
        self.df_open_sprinters = None
        self.df_gesloten_sprinters = None
        self.df_aandelen = None
        self.df_gesloten_aandelen = None
        self.currency_factor = 1.0
        self.snapshot_df = None  # for clarity, but always use repository_per_dag_asset_result

    def load_assets(self, regio=None, status=None, value_grow=None, sector=None):
        df = getattr(SNAPSHOT_STORE, "repository_snapshot_active_asset_rollup_data", None)
        if df is None or df.height == 0:
            return []

        df = df.filter(
            (pl.col("asset_rollup") != "CORRECTIE-BENCHMARK") &
            (pl.col("asset_rollup").is_not_null()) &
            (pl.col("asset_rollup").cast(str) != "")
        )

        mask = pl.Series([True] * df.height)
        if regio:
            mask &= df["regio"] == regio
        if status and status != "all":
            mask &= df["status"] == status
        if value_grow:
            mask &= df["value_grow"] == value_grow
        if sector:
            mask &= df["sector"] == sector

        filtered = df.filter(mask)
        return sorted([
            str(a) for a in filtered["asset_rollup"].unique().to_list()
            if a is not None and str(a) != "" and a != "CORRECTIE-BENCHMARK"])

    from portefeuille_viewer.data.test_order_repository import get_cached_orders

    def _augment_with_test_orders(self, asset_rollup: str):
        from portefeuille_viewer.data.test_order_repository import get_cached_orders
        
        df_test = get_cached_orders(asset_rollup)
        if df_test is None or df_test.is_empty():
            return
        if "include" in df_test.columns:
            df_test = df_test.filter(pl.col("include") == 1)

        # Opties
        df_test_opties = df_test.filter(pl.col("asset_type") == "optie")
        if df_test_opties.height > 0:
            df_opt = (
                df_test_opties
                .with_columns([
                    pl.when(pl.col("transactie_type") == "verkoop")
                    .then(-pl.col("transactie_aantal").cast(pl.Float64))
                    .otherwise(pl.col("transactie_aantal").cast(pl.Float64))
                    .alias("SomVantransactie_aantal"),
                ])
                
                .with_columns([
                    (-1* pl.col("SomVantransactie_aantal") * pl.col("transactie_prijs").cast(pl.Float64) )
                        .alias("SomVantransactie_euro_totaal"),
                    pl.lit(0.0).alias("SomVantransactie_fee"),
                    (pl.col("optie_strike").cast(pl.Float64) * pl.col("SomVantransactie_aantal")).alias("optie_waarde"),
                    pl.lit(None).alias("uniek_id"),
                ])
                .select([
                    "uniek_id",
                    "broker",
                    "asset_rollup",
                    "asset_type",
                    "optie_exp_date",
                    "optie_strike",
                    "optie_call_put",
                    "SomVantransactie_fee",
                    "SomVantransactie_euro_totaal",
                    "SomVantransactie_aantal",
                    "optie_waarde",
                ])
            )
            base_opt = self.df_open_opties if self.df_open_opties is not None else pl.DataFrame()
            self.df_open_opties = pl.concat([base_opt, df_opt], how="diagonal_relaxed")

        # Aandelen
        # Aandelen – zelfde structuur als df_aandelen, geen koers/waarde_bezit
        df_test_eq = df_test.filter(pl.col("asset_type") == "aandeel")
        if df_test_eq.height > 0:
            df_eq = (
                df_test_eq
                .with_columns([
                    pl.lit("aandeel").alias("asset_type"),
                    pl.when(pl.col("transactie_type") == "koop")
                    .then(pl.col("transactie_aantal").cast(pl.Float64))
                    .otherwise(0.0)
                    .alias("aantal_koop"),
                    pl.when(pl.col("transactie_type") == "koop")
                      .then(-pl.col("transactie_aantal").cast(pl.Float64) * pl.col("transactie_prijs").cast(pl.Float64))
                    .otherwise(0.0)
                    .alias("euro_koop"),
                    pl.lit(0.0).alias("fee_koop"),
                    pl.when(pl.col("transactie_type") == "verkoop")
                    .then(-pl.col("transactie_aantal").cast(pl.Float64))
                    .otherwise(0.0)
                    .alias("aantal_verkoop"),
                    pl.when(pl.col("transactie_type") == "verkoop")
                      .then(pl.col("transactie_aantal").cast(pl.Float64) * pl.col("transactie_prijs").cast(pl.Float64))
                    .otherwise(0.0)
                    .alias("euro_verkoop"),
                    pl.lit(0.0).alias("fee_verkoop"),
                ])
                .group_by(["broker", "asset_rollup", "asset_type"])
                .agg([
                    pl.sum("aantal_koop"),
                    pl.sum("euro_koop"),
                    pl.sum("fee_koop"),
                    pl.sum("aantal_verkoop"),
                    pl.sum("euro_verkoop"),
                    pl.sum("fee_verkoop"),
                ])
                .with_columns([
                    (pl.col("aantal_koop") + pl.col("aantal_verkoop")).alias("aantal_bezit"),
                    (pl.col("fee_koop") + pl.col("fee_verkoop")).alias("eq_total_fee"),
                ])
                .select([
                    "broker", "asset_rollup", "asset_type",
                    "aantal_koop", "euro_koop", "fee_koop",
                    "aantal_verkoop", "euro_verkoop", "fee_verkoop",
                    "aantal_bezit", "eq_total_fee",
                ])
            )
            base_eq = self.df_aandelen if self.df_aandelen is not None else pl.DataFrame()
            self.df_aandelen = pl.concat([base_eq, df_eq], how="diagonal_relaxed")






        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        # from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE # sourcery skip
        #SNAPSHOT_STORE.test_repository_load_output_test_dataframe = df_final1  # sourcery skip # of df_sum als je de gesumde versie wilt zien
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken



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

  
        
        if getattr(self, "enable_test_orders", True):
            self._augment_with_test_orders(asset_rollup)
        # self._augment_with_test_orders(asset_rollup)
        self.df_gesloten_aandelen = self.df_aandelen

        
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        # from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE # sourcery skip
        # SNAPSHOT_STORE.test_repository_load_output_test_dataframe = self.df_aandelen  # sourcery skip # of df_sum als je de gesumde versie wilt zien
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken

        
        
        df = SNAPSHOT_STORE.repository_snapshot_asset_rollup_data
        factor = 1.0
        if df is not None and df.height > 0:
            row = df.filter(pl.col("asset_rollup") == asset_rollup)
            if row.height > 0 and "ib_currency" in row.columns:
                if row["ib_currency"][0] == "USD":
                    
                    factor = get_settings().get_eurusd()
        self.currency_factor = factor

    def payoff_open_opties(self, koers):
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
        # from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE # sourcery skip
        # SNAPSHOT_STORE.test_repository_load_input_test_dataframe = self.df_open_opties  # sourcery skip # of df_sum als je de gesumde versie wilt zien
        # # ############# DEBUG TEST< tijdelijk dataframe copieeren zodat deze repository viewer kan worden bekeken
      
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
        if df is None:
            return pl.DataFrame()
        if "ITM_OTM" in df.columns:
            df = df.with_columns(
                pl.when(pl.col("ITM_OTM") != 0)
                    .then(pl.lit("ITM"))
                    .otherwise(pl.lit("OTM"))
                    .alias("itm")
            )
        # Voeg berekende kolom toe: % afwijking koers t.o.v. strike (absoluut)
        if "Koers" in df.columns and "optie_strike" in df.columns:
            df = df.with_columns(
            ( (pl.col("Koers") - pl.col("optie_strike")) / pl.col("optie_strike") * 100 ).alias("afwijking_pct")
            )

        df = df.select([
            pl.col("itm").alias("itm"),
            
            "broker",
            "asset_rollup",
            pl.col("optie_call_put").alias("optie_call_put"),
            pl.col("optie_exp_date").alias("optie_exp_date"),
            pl.col("optie_strike").alias("optie_strike"),
            "Koers",
            "afwijking_pct",
            pl.col("SomVantransactie_aantal").alias("aantal_bezit"),
            pl.col("SomVantransactie_euro_totaal").alias("premie"),
            pl.col("opt_total_result").alias("totaal_resultaat_optie"),
            pl.col("SomVantransactie_fee").alias("totaal_fees"),
            pl.col("ITM_OTM").alias("itm_otm"),


        ])


        if df is None or df.is_empty():
            df = pl.DataFrame()

        if not df.is_empty():
            # Voeg uniek_id toe op basis van optiekenmerken (hidden kolom in de tabel)
            df = df.with_columns([
                pl.struct([
                    "broker",
                    "asset_rollup",
                    "optie_exp_date",
                    "optie_call_put",
                    "optie_strike",
                ]).map_elements(
                    lambda s: build_uniek_id({**s, "asset_type": "optie"}),
                    return_dtype=pl.Utf8,
                ).alias("uniek_id"),
            ])
            # Standaard lege comment kolommen, worden gevuld vanuit DB in update_opties_open_table
            df = df.with_columns([
                pl.lit("").alias("optie_comment"),
                pl.lit("").alias("optie_comment_color"),
                pl.lit("").alias("optie_comment_textcolor"),
                pl.lit(None).alias("optie_comment_updated_at"),
            ])

        return df

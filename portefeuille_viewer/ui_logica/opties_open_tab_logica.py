
import contextlib
import polars as pl
from datetime import datetime, date

from PySide6.QtCore import QSortFilterProxyModel, Qt, Slot, QTimer
from PySide6.QtGui import QColor, QAction, QPen, QPalette
from PySide6.QtWidgets import QWidget, QMenu, QColorDialog, QAbstractItemView, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QInputDialog, QHeaderView


from portefeuille_viewer.ui.models import PolarsTableModel
from portefeuille_viewer.ui.opties_open_ui import Ui_Form
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.ui.filter_popup import HeaderFilterMenuMixin, ColumnFilterPopup
from portefeuille_viewer.data.repository import (
    build_uniek_id,
    fetch_open_optie_comments,
    upsert_open_optie_comment,
    load_open_optie_comments_cache,
    flush_dirty_open_optie_comments_to_db,
    update_open_optie_comment_color,
)
from portefeuille_viewer.signals import signals
from portefeuille_viewer.config.settings_manager import get_settings


class OptiesOpenTableModel(PolarsTableModel):
    def __init__(self, df, parent=None, commit_callback=None):
        super().__init__(df, parent)
        self._editable_cols = {"optie_comment"}
        self._commit_callback = commit_callback
        self._color_priority_map = {}
        self._display_cache = {}
        self._bg_cache = {}
        self._fg_cache = {}
        self._itm_flags = []
        self._call_put = []
        self._comment_colors = []
        self._comment_textcolors = []
        self._comment_color_fg_map = {}

    def set_color_priority_map(self, prio_map: dict):
        self._color_priority_map = prio_map or {}

    def set_comment_color_text_map(self, fg_map: dict):
        self._comment_color_fg_map = fg_map or {}

    def set_format_caches(self, display_cache=None, bg_cache=None, fg_cache=None, itm_flags=None, call_put=None, comment_colors=None, comment_textcolors=None):
        self._display_cache = display_cache or {}
        self._bg_cache = bg_cache or {}
        self._fg_cache = fg_cache or {}
        self._itm_flags = itm_flags or []
        self._call_put = call_put or []
        self._comment_colors = comment_colors or []
        self._comment_textcolors = comment_textcolors or []

    def update_comment_color_cache(self, row_idx: int, color_val: str):
        if 0 <= row_idx < len(self._comment_colors):
            self._comment_colors[row_idx] = color_val or ""

    def update_comment_textcolor_cache(self, row_idx: int, text_val: str):
        if 0 <= row_idx < len(self._comment_textcolors):
            self._comment_textcolors[row_idx] = text_val or ""

    def flags(self, index):
        f = super().flags(index)
        if index.isValid():
            col_name = self._df.columns[index.column()]
            if col_name in self._editable_cols:
                f |= Qt.ItemIsEditable
        return f

    def data(self, index, role=Qt.DisplayRole):
        # Gebruik originele formattering voor DisplayRole, behalve voor percentage kolom
        if role == Qt.DisplayRole:
            if not index.isValid() or self._df.is_empty():
                return None
            col_name = self._df.columns[index.column()]
            if col_name in self._display_cache:
                return self._display_cache[col_name][index.row()]
            return super().data(index, role)
        if role == Qt.EditRole:
            if not index.isValid() or self._df.is_empty():
                return ""
            val = self._df[index.row(), index.column()]
            return "" if val is None else str(val)

        columns = self._df.columns
        colname = columns[index.column()]
        row_idx = index.row()

        # Kolommen die rood/groen moeten krijgen voor ITM posities
        kleur_kolommen = ["itm", "broker", "asset_rollup", "optie_call_put", "optie_strike", "optie_exp_date"]

        if role == Qt.BackgroundRole:
            try:
                if colname in self._bg_cache:
                    cache = self._bg_cache.get(colname, [])
                    if 0 <= row_idx < len(cache):
                        return cache[row_idx]

                if colname == "optie_comment" and "optie_comment_color" in columns:
                    if 0 <= row_idx < len(self._comment_colors):
                        color_val = self._comment_colors[row_idx]
                        if color_val:
                            return QColor(color_val)

                if colname in kleur_kolommen and 0 <= row_idx < len(self._itm_flags):
                    if self._itm_flags[row_idx]:
                        if 0 <= row_idx < len(self._call_put):
                            if self._call_put[row_idx] == "put":
                                return QColor(255, 200, 200)  # lichtrood
                            if self._call_put[row_idx] == "call":
                                return QColor(200, 255, 200)  # lichtgroen
            except Exception:
                pass
        if role == Qt.ForegroundRole:
            try:
                if colname == "optie_comment":
                    if 0 <= row_idx < len(self._comment_textcolors):
                        text_val = self._comment_textcolors[row_idx] or ""
                        if text_val:
                            return QColor(text_val)
                    if 0 <= row_idx < len(self._comment_colors):
                        color_val = self._comment_colors[row_idx] or ""
                        fg = self._comment_color_fg_map.get(color_val)
                        if fg:
                            return QColor(fg)
                if colname in self._fg_cache:
                    cache = self._fg_cache.get(colname, [])
                    if 0 <= row_idx < len(cache):
                        return cache[row_idx]
            except Exception:
                pass
        if role == Qt.TextAlignmentRole and colname == "koers_prev":
            return Qt.AlignRight | Qt.AlignVCenter
        if role == Qt.UserRole:
            try:
                if colname == "optie_comment" and "optie_comment_color" in columns:
                    color_idx = columns.index("optie_comment_color")
                    cval = self._df[row_idx, color_idx] or ""
                    priority = self._color_priority_map.get(cval, 0)
                    return (priority, str(self._df[row_idx, index.column()] or ""))
            except Exception:
                pass
        return super().data(index, role)

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        col_name = self._df.columns[index.column()]
        if col_name not in self._editable_cols:
            return False
        row_idx = index.row()
        new_val = "" if value is None else str(value)
        try:
            col_values = self._df[col_name].to_list()
            col_values[row_idx] = new_val
            self._df = self._df.with_columns(pl.Series(col_name, col_values))

            ts_col = "optie_comment_updated_at"
            if ts_col in self._df.columns:
                ts_values = self._df[ts_col].to_list()
                ts_values[row_idx] = datetime.now()
                self._df = self._df.with_columns(pl.Series(ts_col, ts_values))

            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
            if self._commit_callback:
                row_data = self._df.row(row_idx, named=True)
                self._commit_callback(row_data)
            return True
        except Exception:
            return False


class CommentSortProxy(QSortFilterProxyModel):
    """Proxy die kleur/tekst sorting ondersteunt via UserRole tuples."""
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
            links = left.data(Qt.DisplayRole)
            rechts = right.data(Qt.DisplayRole)
            try:
                return links < rechts
            except Exception:
                return False


class CommentNoSelectDelegate(QStyledItemDelegate):
    """
    Delegate die selectie-overlay negeert zodat de celkleur (comment) zichtbaar blijft.
    """
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        opt.state &= ~QStyle.State_Selected
        bg = index.data(Qt.BackgroundRole)
        if isinstance(bg, QColor):
            painter.save()
            painter.fillRect(option.rect, bg)
            painter.restore()
        super().paint(painter, opt, index)
        if option.state & QStyle.State_Selected:
            painter.save()
            painter.setPen(QPen(option.palette.color(QPalette.Text), 1))
            rect = option.rect.adjusted(1, 1, -1, -1)
            painter.drawRoundedRect(rect, 3, 3)
            painter.restore()
    
class OptiesOpenTab(QWidget, Ui_Form, HeaderFilterMenuMixin):
    """
    Tabblad dat open opties toont met live prijzen.
    Leest uit aggregator_snapshot_load_open_opties_from_tx_live (gevuld door LiveAggregatorOpties).
    """
    def __init__(self, portfolio_engine=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        # self.tableView = self.table  # of self.tableView als dat je QTableView is
        self._table_model = None  # na reload_data()
        self._col_filters = {}
        self._active = False
        self._dirty = False
        self._reload_timer = QTimer(self)
        self._reload_timer.setInterval(500)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.timeout.connect(self._reload_if_needed)
        self.tableView.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableView.horizontalHeader().customContextMenuRequested.connect(self.on_header_menu)
        self.tableView.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tableView.verticalHeader().setDefaultSectionSize(18) 
        self._header_bg_color = get_settings().get_table_header_bg()
        self._apply_header_style()
        self.portfolio_engine = portfolio_engine
        self.current_sort_column = -1
        self.current_sort_order = 0
        # Gebruik de juiste TableView uit de UI
        self.table = self.tableView
        self.buttonClearFilters.clicked.connect(self._on_clear_filters)
        self.lineEditFilter.returnPressed.connect(self.apply_filters)
        # self.label = self.labelOpties  # Alleen als je een label toevoegt aan de UI
        if self.portfolio_engine and hasattr(self.portfolio_engine, 'live_aggregator_opties'):
            self.portfolio_engine.live_aggregator_opties.optiesUpdated.connect(self.on_opties_update)
        load_open_optie_comments_cache()
        self.commentFlushTimer = QTimer(self)
        self.commentFlushTimer.setInterval(60_000)  # 60s
        self.commentFlushTimer.timeout.connect(self._flush_comments_if_dirty)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_comment_context_menu)
        # selectie/kleuren
        self.tableView.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tableView.setStyleSheet("""
        QTableView::item:selected { background: rgba(255,242,204,80); color: black; }
        QTableView::item:selected:active { background: rgba(255,242,204,80); color: black; }
        QTableView::item:selected:active:focus { background: transparent; color: black; }
        QTableView::item:focus { background: transparent; color: black; }
        """)
        self._columns_signature = None
        self.model = OptiesOpenTableModel(pl.DataFrame(), self, commit_callback=self._on_comment_commit)
        self.model.set_color_priority_map(get_settings().get_comment_color_priority_map())
        self.model.set_comment_color_text_map(get_settings().get_comment_color_text_map())
        self.proxy_model = CommentSortProxy(self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setSortRole(Qt.UserRole)
        self.tableView.setModel(self.proxy_model)
        self.tableView.setSortingEnabled(True)
        self.table.setModel(self.proxy_model)
        self._table_model = self.model
        signals.databaseChanged.connect(self._on_db_changed)
        signals.uiStyleChanged.connect(self._on_ui_style_changed)
        self.reload_data()

    def _apply_column_widths(self, df: pl.DataFrame) -> None:
        """
        Handmatige kolombreedtes voor de opties-open tabel.
        Pas de dict hieronder aan naar smaak.
        """
        if df is None or df.is_empty():
            return
        header = self.tableView.horizontalHeader()
        col_widths = {
            "itm": 80,
            "broker": 100,
            "asset_rollup": 110,
            "optie_call_put": 45,
            "optie_exp_date": 100,
            "optie_strike": 80,
            "Koers": 80,
            "koers_prev": 80,
            "pct_change_prev": 90,
            "afwijking_pct": 80,
            "aantal_bezit": 80,
            "premie": 100,
            "totaal_resultaat_optie": 100,
            "optie_comment": 600,
            "optie_comment_updated_at": 100,
        }
        for col, width in col_widths.items():
            if col not in df.columns:
                continue
            header.resizeSection(df.columns.index(col), width)

    def _apply_header_style(self):
        style = f"QHeaderView::section {{ background-color: {self._header_bg_color}; }}"
        self.tableView.horizontalHeader().setStyleSheet(style)

    def _on_ui_style_changed(self, key: str):
        if key != "table_header_bg":
            return
        self._header_bg_color = get_settings().get_table_header_bg()
        self._apply_header_style()

    def _reorder_opties_open_columns(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Pas hier de gewenste kolomvolgorde aan.
        Onbekende kolommen worden genegeerd; overige kolommen blijven achteraan staan.
        """
        if df is None or df.is_empty():
            return df

        desired_order = [
            "itm",
            "broker",
            "asset_rollup",
            "optie_call_put",
            "optie_exp_date",
            "optie_strike",
            "Koers",
            "afwijking_pct",
            "koers_prev",
            "pct_change_prev",
            
            "aantal_bezit",
            "premie",
            
            "totaal_resultaat_optie",
            "itm_otm",
            "totaal_fees",
            "optie_comment",
            "optie_comment_updated_at",
            # helper/hidden columns last
            "optie_comment_color",
            "uniek_id",
            
        ]

        cols = df.columns
        ordered = [c for c in desired_order if c in cols]
        rest = [c for c in cols if c not in ordered]
        return df.select(ordered + rest)

    @Slot()
    def on_opties_update(self):
        # niet herladen tijdens edit, dat breekt de bewerking
        if self.tableView.state() == QAbstractItemView.EditingState:
            return
        if hasattr(self, 'table') and self.table.model() is not None:
            header = self.table.horizontalHeader()
            self.current_sort_column = header.sortIndicatorSection()
            self.current_sort_order = header.sortIndicatorOrder()
        if not self._active:
            self._dirty = True
            return
        self._schedule_reload()

    def _on_db_changed(self, db_name: str):
        load_open_optie_comments_cache()
        if not self._active:
            self._dirty = True
            return
        self._schedule_reload()

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

    def on_header_menu(self, pos):
        """
        Eigen header-menu met kleur-sort opties voor de comment-kolom.
        """
        header = self.tableView.horizontalHeader()
        section = header.logicalIndexAt(pos)
        try:
            colname = self._table_model._df.columns[section]
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
            self.tableView.sortByColumn(section, Qt.DescendingOrder)
            return
        if act == a_color_asc:
            self.tableView.sortByColumn(section, Qt.AscendingOrder)
            return
        if act in (a_asc, a_desc):
            order = Qt.AscendingOrder if act == a_asc else Qt.DescendingOrder
            self.tableView.sortByColumn(section, order)
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

    def apply_filters(self):
        # print("apply_filters aangeroepen, tekst:", self.lineEditFilter.text())
        q = self.lineEditFilter.text().strip()
        filters = {"q": q} if q else {}

        # kolomfilters omzetten naar generieke repo keys
        for col, spec in (self._col_filters or {}).items():
            if "in" in spec:
                filters[f"__in__{col}"] = list(spec["in"])
            if "contains" in spec:
                filters[f"__contains__{col}"] = spec["contains"]
            if "eq" in spec:
                filters[f"__eq__{col}"] = spec["eq"]
            if "date_on" in spec and spec["date_on"]:
                filters[f"__date_on__{col}"] = spec["date_on"]

        self.active_filters = filters
        # print("Filters dict:", filters)
        self._reset_seek()
        self._load_initial_records()

    def _load_initial_records(self):
        self.reload_data()

    def _reset_seek(self):
        pass

    def _flush_comments_if_dirty(self):
        flush_dirty_open_optie_comments_to_db()
        dirty = getattr(SNAPSHOT_STORE, "repository_dirty_open_optie_comments", []) or []
        if not dirty and self.commentFlushTimer.isActive():
            self.commentFlushTimer.stop()
        # na flush de cache opnieuw laden zodat nieuwe records ook bij filteren beschikbaar zijn
        if not dirty:
            load_open_optie_comments_cache()

    def _on_comment_context_menu(self, pos):
        index = self.tableView.indexAt(pos)
        if not index.isValid():
            return
        model = self.tableView.model()
        src_index = model.mapToSource(index) if hasattr(model, "mapToSource") else index
        col_name = self._table_model._df.columns[src_index.column()]
        if col_name != "optie_comment":
            return
        cols = self._table_model._df.columns
        try:
            uniek_id_idx = cols.index("uniek_id")
        except ValueError:
            return
        color_idx = cols.index("optie_comment_color") if "optie_comment_color" in cols else None
        current_uniek_id = self._table_model._df[src_index.row(), uniek_id_idx]
        current_comment = self._table_model._df[src_index.row(), src_index.column()] or ""
        current_color = self._table_model._df[src_index.row(), color_idx] if color_idx is not None else ""

        menu = QMenu(self)
        color_defs = get_settings().get_comment_colors()
        for _prio, label, bg_hex, _fg_hex in color_defs:
            act = QAction(label, menu)
            act.setData(bg_hex)
            menu.addAction(act)
        menu.addSeparator()
        act_custom = QAction("Kies kleur...", menu)
        menu.addAction(act_custom)

        chosen = menu.exec(self.tableView.mapToGlobal(pos))
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
                self._patch_comment_in_model(
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

    def _patch_comment_in_model(self, uniek_id: str, comment: str, color: str, textcolor: str, ts):
        if not uniek_id:
            return
        self._restore_selection_uniek = uniek_id
        self._restore_selection_col = "optie_comment"
        try:
            df = self._table_model._df
            if df is None or df.is_empty():
                return
            df = df.with_columns([
                pl.when(pl.col("uniek_id") == uniek_id).then(pl.lit(comment)).otherwise(pl.col("optie_comment")).alias("optie_comment"),
                pl.when(pl.col("uniek_id") == uniek_id).then(pl.lit(color)).otherwise(pl.col("optie_comment_color")).alias("optie_comment_color"),
                pl.when(pl.col("uniek_id") == uniek_id).then(pl.lit(textcolor)).otherwise(pl.col("optie_comment_textcolor")).alias("optie_comment_textcolor"),
                pl.when(pl.col("uniek_id") == uniek_id).then(pl.lit(ts)).otherwise(pl.col("optie_comment_updated_at")).alias("optie_comment_updated_at"),
            ])
            # vind de rij-index om dataChanged te emitten zonder reset
            try:
                mask = (self._table_model._df["uniek_id"] == uniek_id).to_list()
                row_idx = mask.index(True) if True in mask else None
            except Exception:
                row_idx = None
            self._table_model._df = df
            if row_idx is not None:
                if hasattr(self._table_model, "update_comment_color_cache"):
                    self._table_model.update_comment_color_cache(row_idx, color)
                if hasattr(self._table_model, "update_comment_textcolor_cache"):
                    self._table_model.update_comment_textcolor_cache(row_idx, textcolor)
                tl = self._table_model.index(row_idx, 0)
                br = self._table_model.index(row_idx, df.width - 1)
                self._table_model.dataChanged.emit(tl, br, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole, Qt.ForegroundRole])
            self._restore_selection()
        except Exception as exc:
            print(f"[comments] patch failed: {exc}")

    def _on_comment_commit(self, row_data: dict):
        try:
            uniek_id = row_data.get("uniek_id")
            comment = row_data.get("optie_comment") or ""
            color = row_data.get("optie_comment_color") or ""
            textcolor = row_data.get("optie_comment_textcolor") or ""
            ts = row_data.get("optie_comment_updated_at")
            upsert_open_optie_comment(uniek_id, comment, color, textcolor, ts)
            latest = fetch_open_optie_comments([uniek_id])
            if latest is not None and not latest.is_empty():
                row = latest.row(0, named=True)
                self._patch_comment_in_model(
                    uniek_id,
                    row.get("optie_comment") or "",
                    row.get("optie_comment_color") or "",
                    row.get("optie_comment_textcolor") or "",
                    row.get("optie_comment_updated_at"),
                )
            if not self.commentFlushTimer.isActive():
                self.commentFlushTimer.start()
            self._restore_selection_uniek = uniek_id
            self._restore_selection_col = "optie_comment"
            self._restore_selection()
        except Exception as exc:
            print(f"[comments] commit failed: {exc}")

    def reload_data(self):
        # huidige selectie onthouden voor herstel
        current_uniek = None
        current_col_name = None
        if getattr(self, "_table_model", None) is not None and self._table_model._df is not None and not self._table_model._df.is_empty():
            idx = self.tableView.currentIndex()
            if idx.isValid():
                try:
                    src_idx = self.proxy_model.mapToSource(idx) if hasattr(self, "proxy_model") else idx
                    cols = self._table_model._df.columns
                    if "uniek_id" in cols:
                        current_uniek = self._table_model._df[src_idx.row(), cols.index("uniek_id")]
                        current_col_name = cols[src_idx.column()] if src_idx.column() < len(cols) else None
                except Exception:
                    pass
        self._restore_selection_uniek = current_uniek
        self._restore_selection_col = current_col_name

        df = SNAPSHOT_STORE.aggregator_snapshot_load_open_opties_from_tx_live
        if "ITM_OTM" in df.columns:
            df = df.with_columns(
                pl.when(pl.col("ITM_OTM") != 0)
                    .then(pl.lit("ITM"))
                    .otherwise(pl.lit("OTM"))
                    .alias("itm")
            )
        df = df.select([
            "broker",
            "asset_rollup",
            
            pl.col("optie_call_put").alias("optie_call_put"),
            pl.col("optie_strike").alias("optie_strike"),
            pl.col("optie_exp_date").alias("optie_exp_date"),
            pl.col("SomVantransactie_aantal").alias("aantal_bezit"),
            pl.col("SomVantransactie_euro_totaal").alias("premie"),
            "Koers",
            pl.col("ITM_OTM").alias("itm_otm"),
            pl.col("opt_total_result").alias("totaal_resultaat_optie"),
            pl.col("SomVantransactie_fee").alias("totaal_fees"),
            pl.col("itm").alias("itm"),
        ])
        # Voeg berekende kolom toe: % afwijking koers t.o.v. strike (absoluut)
        if "Koers" in df.columns and "optie_strike" in df.columns:
            df = df.with_columns(
                ( (pl.col("Koers") - pl.col("optie_strike")) / pl.col("optie_strike") * 100 ).alias("afwijking_pct")
            )
        if df is None or df.is_empty():
            df = pl.DataFrame()
        else:
            df = df.with_columns([
                pl.struct([
                    "broker",
                    "asset_rollup",
                    "optie_exp_date",
                    "optie_call_put",
                    "optie_strike",
                ]).map_elements(lambda s: build_uniek_id({**s, "asset_type": "optie"}), return_dtype=pl.Utf8).alias("uniek_id"),
                pl.lit("").alias("optie_comment"),
                pl.lit("").alias("optie_comment_color"),
                pl.lit("").alias("optie_comment_textcolor"),
                pl.lit(None).alias("optie_comment_updated_at"),
            ])
            # comments uit cache
            ids = df["uniek_id"].to_list()
            df_comments = fetch_open_optie_comments(ids)
            if df_comments is not None and not df_comments.is_empty():
                df = df.join(df_comments, on="uniek_id", how="left", suffix="_comment_db")
                exprs = []
                if "optie_comment_comment_db" in df.columns:
                    exprs.append(pl.coalesce([pl.col("optie_comment_comment_db"), pl.col("optie_comment")]).fill_null("").alias("optie_comment"))
                else:
                    exprs.append(pl.col("optie_comment").fill_null("").alias("optie_comment"))
                if "optie_comment_color_comment_db" in df.columns:
                    exprs.append(pl.coalesce([pl.col("optie_comment_color_comment_db"), pl.col("optie_comment_color")]).fill_null("").alias("optie_comment_color"))
                else:
                    exprs.append(pl.col("optie_comment_color").fill_null("").alias("optie_comment_color"))
                if "optie_comment_textcolor_comment_db" in df.columns:
                    exprs.append(pl.coalesce([pl.col("optie_comment_textcolor_comment_db"), pl.col("optie_comment_textcolor")]).fill_null("").alias("optie_comment_textcolor"))
                else:
                    exprs.append(pl.col("optie_comment_textcolor").fill_null("").alias("optie_comment_textcolor"))
                if "optie_comment_updated_at_comment_db" in df.columns:
                    exprs.append(pl.coalesce([pl.col("optie_comment_updated_at_comment_db"), pl.col("optie_comment_updated_at")]).alias("optie_comment_updated_at"))
                else:
                    exprs.append(pl.col("optie_comment_updated_at"))
                df = df.with_columns(exprs)
                for col in ("optie_comment_comment_db", "optie_comment_color_comment_db", "optie_comment_textcolor_comment_db", "optie_comment_updated_at_comment_db"):
                    if col in df.columns:
                        df = df.drop(col)

            # Voeg koers_prev toe vanuit per_dag_asset_result + pct_change_prev (Koers vs koers_prev)
            try:
                df_asset_result = getattr(SNAPSHOT_STORE, "repository_per_dag_asset_result", None)
                if df_asset_result is not None and not df_asset_result.is_empty():
                    today = date.today()
                    df_asset_result = df_asset_result.filter(pl.col("datum") < today)
                    if "datum" in df_asset_result.columns and df_asset_result["datum"].dtype == pl.String:
                        df_asset_result = df_asset_result.with_columns(
                            pl.col("datum").str.strptime(pl.Date, "%d/%m/%Y", strict=False)
                        )
                    df_latest = (
                        df_asset_result
                        .sort(["asset_rollup", "datum"])
                        .group_by("asset_rollup")
                        .agg([pl.col("close_price").last().alias("koers_prev")])
                    )
                    df = df.join(df_latest, on="asset_rollup", how="left")
                else:
                    df = df.with_columns(pl.lit(None).alias("koers_prev"))
            except Exception:
                if "koers_prev" not in df.columns:
                    df = df.with_columns(pl.lit(None).alias("koers_prev"))

            # Zorg dat koers_prev numeriek is (voor consistente formatting/alignment)
            if "koers_prev" in df.columns:
                with contextlib.suppress(Exception):
                    df = df.with_columns(pl.col("koers_prev").cast(pl.Float64, strict=False).alias("koers_prev"))

            if "Koers" in df.columns and "koers_prev" in df.columns:
                df = df.with_columns(
                    pl.when((pl.col("koers_prev").is_not_null()) & (pl.col("koers_prev") != 0))
                    .then((pl.col("Koers") / pl.col("koers_prev")) - 1)
                    .otherwise(None)
                    .alias("pct_change_prev")
                )
            elif "pct_change_prev" not in df.columns:
                df = df.with_columns(pl.lit(None).alias("pct_change_prev"))

        filters = getattr(self, "active_filters", {})
        if filters:
            for key, value in filters.items():
                if key.startswith("__in__"):
                    col = key.replace("__in__", "")
                    df = df.filter(pl.col(col).is_in(value))
                elif key.startswith("__contains__"):
                    col = key.replace("__contains__", "")
                    df = df.filter(pl.col(col).cast(str).str.contains(value))
                elif key.startswith("__eq__"):
                    col = key.replace("__eq__", "")
                    df = df.filter(pl.col(col) == value)
                elif key.startswith("__date_on__"):
                    col = key.replace("__date_on__", "")
                    df = df.filter(pl.col(col) == value)

                elif key == "q":
                    # Meerdere zoektermen (AND), gescheiden door komma
                    terms = [t.strip() for t in value.split(",") if t.strip()]
                    for term in terms:
                        mask = None
                        # Maak varianten van de zoekterm met en zonder voorloopnullen
                        import re
                        def pad_zero(s):
                            parts = re.split(r'[-/]', s)
                            return [
                                s,
                                '-'.join(f"{int(p):02d}" if p.isdigit() else p for p in parts),
                                '/'.join(f"{int(p):02d}" if p.isdigit() else p for p in parts)
                            ]
                        term_variants = set()
                        for t in pad_zero(term):
                            term_variants.add(t)
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
                                # combineer alle varianten
                            else:
                                m = pl.col(c).cast(str).str.to_lowercase().str.contains(term.lower())
                            mask = m if mask is None else (mask | m)
                        df = df.filter(mask)

        df = self._reorder_opties_open_columns(df)

        if df is None or df.is_empty():
            df = pl.DataFrame()
        
        # DEBUG: print kolommen (1x per unieke set) om te zien of itm/itm_otm nog aanwezig is
        try:
            cols_now = tuple(df.columns) if df is not None else ()
            if getattr(self, "_debug_last_df_columns", None) != cols_now:
                self._debug_last_df_columns = cols_now
                # print(f"[opties_open] df.columns={list(cols_now)} rows={0 if df is None else df.height}")
        except Exception:
            pass
        
        
        display_cache = {}
        if "pct_change_prev" in df.columns:
            values = df["pct_change_prev"].to_list()
            display_cache["pct_change_prev"] = [
                (f"{float(v) * 100:.2f}%") if v is not None else "" for v in values
            ]
        if "koers_prev" in df.columns:
            values = df["koers_prev"].to_list()
            display_cache["koers_prev"] = [
                (f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")) if v is not None else ""
                for v in values
            ]

        bg_cache = {}
        fg_cache = {}
        for col in ("pct_change_prev", "afwijking_pct"):
            if col in df.columns:
                vals = df[col].to_list()
                bg_cache[col] = [
                    QColor("#c6f7c6") if v is not None and v > 0 else QColor("#f7c6c6") if v is not None and v < 0 else None
                    for v in vals
                ]
                fg_cache[col] = [
                    QColor(0, 120, 0) if v is not None and v > 0 else QColor(220, 0, 0) if v is not None and v < 0 else None
                    for v in vals
                ]

        itm_flags = []
        if "itm" in df.columns:
            itm_flags = [str(v or "").upper() == "ITM" for v in df["itm"].to_list()]
        elif "itm_otm" in df.columns:
            vals = df["itm_otm"].to_list()
            flags = []
            for v in vals:
                try:
                    flags.append(int(v) != 0)
                except Exception:
                    flags.append(False)
            itm_flags = flags

        call_put = []
        if "optie_call_put" in df.columns:
            call_put = [(v or "").lower() for v in df["optie_call_put"].to_list()]

        comment_colors = df["optie_comment_color"].to_list() if "optie_comment_color" in df.columns else []
        comment_textcolors = df["optie_comment_textcolor"].to_list() if "optie_comment_textcolor" in df.columns else []

        self.model.set_format_caches(
            display_cache=display_cache,
            bg_cache=bg_cache,
            fg_cache=fg_cache,
            itm_flags=itm_flags,
            call_put=call_put,
            comment_colors=comment_colors,
            comment_textcolors=comment_textcolors,
        )
        self.model.set_df(df)

        cols_now = tuple(df.columns) if df is not None else ()
        if self._columns_signature != cols_now:
            self._columns_signature = cols_now
            # commentkolom: delegate die selectie overlay negeert
            try:
                comment_col = df.columns.index("optie_comment")
                self.tableView.setItemDelegateForColumn(comment_col, CommentNoSelectDelegate(self.tableView))
            except ValueError:
                pass
            # verberg helperkolommen
            for hide_col in ("uniek_id", "optie_comment_color", "optie_comment_textcolor", "totaal_fees"):
                if hide_col in df.columns:
                    idx = df.columns.index(hide_col)
                    self.tableView.setColumnHidden(idx, True)
            self._apply_column_widths(df)
        if self.current_sort_column >= 0:
            self.tableView.sortByColumn(self.current_sort_column, self.current_sort_order)
        else:
            try:
                col_idx = df.columns.index("optie_exp_date")
            except Exception:
                col_idx = -1
            if col_idx >= 0:
                self.tableView.sortByColumn(col_idx, Qt.AscendingOrder)
        # selectie herstellen
        self._restore_selection()

    def _restore_selection(self):
        try:
            uniek_id = getattr(self, "_restore_selection_uniek", None)
            col_name = getattr(self, "_restore_selection_col", None)
            if not uniek_id or self._table_model is None or self._table_model._df is None:
                return
            df = self._table_model._df
            if "uniek_id" not in df.columns:
                return
            target_col = df.columns.index(col_name) if col_name in df.columns else 0
            for r in range(df.height):
                if df[r, df.columns.index("uniek_id")] == uniek_id:
                    src_idx = self._table_model.index(r, target_col)
                    view_idx = self.proxy_model.mapFromSource(src_idx) if hasattr(self, "proxy_model") else src_idx
                    self.tableView.setCurrentIndex(view_idx)
                    self.tableView.scrollTo(view_idx)
                    break
        except Exception:
            pass

    def _apply_in_filter(self, colname, selected):
        if not selected:
            self._col_filters.pop(colname, None)
        else:
            self._col_filters[colname] = {"in": selected}
        self.apply_filters()  # ipv self._load_initial_records()

    def _on_clear_filters(self):
        self._col_filters.clear()
        self._text_filter = ""
        self.lineEditFilter.clear()
        self.apply_filters()
        self._reset_seek()
        self._load_initial_records()

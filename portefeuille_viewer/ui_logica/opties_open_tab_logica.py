
import polars as pl
from datetime import datetime

from PySide6.QtCore import QSortFilterProxyModel, Qt, Slot, QTimer
from PySide6.QtGui import QColor, QAction
from PySide6.QtWidgets import QWidget, QMenu, QColorDialog, QAbstractItemView, QStyledItemDelegate, QStyleOptionViewItem, QStyle


from portefeuille_viewer.ui.models import PolarsTableModel
from portefeuille_viewer.ui.opties_open_ui import Ui_Form
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.ui.filter_popup import HeaderFilterMenuMixin
from portefeuille_viewer.data.repository import (
    build_uniek_id,
    fetch_open_optie_comments,
    upsert_open_optie_comment,
    load_open_optie_comments_cache,
    flush_dirty_open_optie_comments_to_db,
)


class OptiesOpenTableModel(PolarsTableModel):
    def __init__(self, df, parent=None, commit_callback=None):
        super().__init__(df, parent)
        self._editable_cols = {"optie_comment"}
        self._commit_callback = commit_callback

    def flags(self, index):
        f = super().flags(index)
        if index.isValid():
            col_name = self._df.columns[index.column()]
            if col_name in self._editable_cols:
                f |= Qt.ItemIsEditable
        return f

    def data(self, index, role=Qt.DisplayRole):
        # Gebruik originele formattering voor DisplayRole
        if role == Qt.DisplayRole:
            return super().data(index, role)
        if role == Qt.EditRole:
            if not index.isValid() or self._df.is_empty():
                return ""
            val = self._df[index.row(), index.column()]
            return "" if val is None else str(val)

        row = self._df.row(index.row())
        columns = self._df.columns
        colname = columns[index.column()]

        kleur_kolommen = ["broker", "asset_rollup", "optie_call_put", "optie_strike", "optie_exp_date"]

        if role == Qt.BackgroundRole:
            try:
                if colname == "optie_comment" and "optie_comment_color" in columns:
                    color_val = row[columns.index("optie_comment_color")]
                    if color_val:
                        return QColor(color_val)
                optie_call_put = row[columns.index("optie_call_put")]
                itm_otm = row[columns.index("itm_otm")]
                if colname in kleur_kolommen and itm_otm != 0:
                    if optie_call_put == "put":
                        return QColor(255, 200, 200)  # lichtrood
                    elif optie_call_put == "call":
                        return QColor(200, 255, 200)  # lichtgroen
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


class CommentNoSelectDelegate(QStyledItemDelegate):
    """
    Delegate die selectie-overlay negeert zodat de celkleur (comment) zichtbaar blijft.
    """
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        opt.state &= ~QStyle.State_Selected
        super().paint(painter, opt, index)
    
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
        self.tableView.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tableView.horizontalHeader().customContextMenuRequested.connect(self.on_header_menu)
        self.tableView.verticalHeader().setDefaultSectionSize(18) 
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
        self.reload_data()

    @Slot()
    def on_opties_update(self):
        # niet herladen tijdens edit, dat breekt de bewerking
        if self.tableView.state() == QAbstractItemView.EditingState:
            return
        if hasattr(self, 'table') and self.table.model() is not None:
            header = self.table.horizontalHeader()
            self.current_sort_column = header.sortIndicatorSection()
            self.current_sort_order = header.sortIndicatorOrder()
        self.reload_data()

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
        color_actions = {
            "Geen": "",
            "Rood": "#f8d7da",
            "Oranje": "#ffeeba",
            "Groen": "#d4edda",
        }
        for label, hexval in color_actions.items():
            act = QAction(label, menu)
            act.setData(hexval)
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
            upsert_open_optie_comment(current_uniek_id, current_comment, hexval)
            latest = fetch_open_optie_comments([current_uniek_id])
            if latest is not None and not latest.is_empty():
                row = latest.row(0, named=True)
                self._patch_comment_in_model(current_uniek_id, row.get("optie_comment") or "", row.get("optie_comment_color") or "", row.get("optie_comment_updated_at"))
            if not self.commentFlushTimer.isActive():
                self.commentFlushTimer.start()
        except Exception as exc:
            print(f"[comments] kon kleur niet opslaan: {exc}")

    def _patch_comment_in_model(self, uniek_id: str, comment: str, color: str, ts):
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
                tl = self._table_model.index(row_idx, 0)
                br = self._table_model.index(row_idx, df.width - 1)
                self._table_model.dataChanged.emit(tl, br, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole])
            self._restore_selection()
        except Exception as exc:
            print(f"[comments] patch failed: {exc}")

    def _on_comment_commit(self, row_data: dict):
        try:
            uniek_id = row_data.get("uniek_id")
            comment = row_data.get("optie_comment") or ""
            color = row_data.get("optie_comment_color") or ""
            ts = row_data.get("optie_comment_updated_at")
            upsert_open_optie_comment(uniek_id, comment, color, ts)
            latest = fetch_open_optie_comments([uniek_id])
            if latest is not None and not latest.is_empty():
                row = latest.row(0, named=True)
                self._patch_comment_in_model(uniek_id, row.get("optie_comment") or "", row.get("optie_comment_color") or "", row.get("optie_comment_updated_at"))
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
                ( (pl.col("Koers") - pl.col("optie_strike")).abs() / pl.col("optie_strike") * 100 ).alias("afwijking_pct")
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
                if "optie_comment_updated_at_comment_db" in df.columns:
                    exprs.append(pl.coalesce([pl.col("optie_comment_updated_at_comment_db"), pl.col("optie_comment_updated_at")]).alias("optie_comment_updated_at"))
                else:
                    exprs.append(pl.col("optie_comment_updated_at"))
                df = df.with_columns(exprs)
                for col in ("optie_comment_comment_db", "optie_comment_color_comment_db", "optie_comment_updated_at_comment_db"):
                    if col in df.columns:
                        df = df.drop(col)

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

        if df is None or df.is_empty():
            df = pl.DataFrame()
            
        
        self.model = OptiesOpenTableModel(df, self, commit_callback=self._on_comment_commit)
        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setSortRole(Qt.UserRole)
        self.tableView.setModel(self.proxy_model)
        # commentkolom: delegate die selectie overlay negeert
        try:
            comment_col = df.columns.index("optie_comment")
            self.tableView.setItemDelegateForColumn(comment_col, CommentNoSelectDelegate(self.tableView))
        except ValueError:
            pass
        self._table_model = self.model  # update voor de mixin
        self.table.setModel(self.proxy_model)
        # verberg helperkolommen
        for hide_col in ("uniek_id", "optie_comment_color"):
            if hide_col in df.columns:
                idx = df.columns.index(hide_col)
                self.tableView.setColumnHidden(idx, True)
        if self.current_sort_column >= 0:
            self.tableView.sortByColumn(self.current_sort_column, self.current_sort_order)
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

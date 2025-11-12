import re 
import contextlib
import pyodbc
import pandas as pd
import polars as pl
import traceback
from datetime import datetime
from portefeuille_viewer.signals import signals

from PySide6.QtWidgets import QWidget, QMenu, QInputDialog, QMessageBox,QAbstractItemView, QLineEdit
from PySide6.QtCore import Qt, Signal

from portefeuille_viewer.ui.filter_popup import ColumnFilterPopup  # ← nieuw
from portefeuille_viewer.ui.orders_tab_ui import Ui_OrdersTabUI
# from portefeuille_viewer.ui_logica.orders_tab_logica import OrdersTabLogica
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.ui.models import PandasTableModel

from portefeuille_viewer.data.repository import (
    get_connection,DB_MAP, DB_STYLES, DEFAULT_DB_NAME,
    load_reference_lists, update_transactions_atomic, insert_transaction,
    get_next_order_id, get_next_order_item_no, delete_transactions_by_ids, parse_int_field, # build_uniek_id,is_pairable,
    )



class OrdersTabWidget(QWidget, Ui_OrdersTabUI):
    ordersCommitted = Signal()     # Na succesvol opslaan of update
    dbChanged = Signal()           # DB-switch event
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.tableViewOrders.setStyleSheet(
            """
            QTableView::item:hover { background-color: #E6F2FF; }
            QTableView::item:selected { background-color: #FFF2CC; color: #000000; }
            QTableView::item:selected:hover { background-color: #FFE08A; }
            QTableView::item:selected:!active { background-color: #FFF8D6; }
            """)
        self.EDIT_ID = None
        self.EDIT_ID2 = None
        # Importeer hier om circular import te voorkomen
        
        self.order1 = {
            "cb_oorsprong": self.comboOorsprong1,
            "broker": self.comboBroker1,
            "asset_rollup": self.comboAssetRollup1,
            "asset_type": self.comboAssetType1,
            "trans_type": self.comboTransType1,
            "detail": self.comboDetail1,
            "aantal": self.lineEditAantal1,
            "prijs": self.lineEditPrijs1,
            "fee": self.lineEditFee1,
            "exp": self.lineEditOptieExp1,
            "strike": self.lineEditOptieStrike1,
            "cp": self.comboOptieCP1,
        }
        self.order2 = {
            "cb_oorsprong": None,
            "broker": self.comboBroker2,
            "asset_rollup": self.comboAssetRollup2,
            "asset_type": self.comboAssetType2,
            "trans_type": self.comboTransType2,
            "detail": self.comboDetail2,
            "aantal": self.lineEditAantal2,
            "prijs": self.lineEditPrijs2,
            "fee": self.lineEditFee2,
            "exp": self.lineEditOptieExp2,
            "strike": self.lineEditOptieStrike2,
            "cp": self.comboOptieCP2,
        }
        
        self.lineEditFilter.returnPressed.connect(self.apply_filters)
        self.buttonClearFilters.clicked.connect(self._on_clear_filters)
                
        self._col_filters = {}  # dict om actieve filters per kolom op te slaan
        self.active_filters = {}
        self.seek_value = None
        self.seek_id = None
        self._snapshot_store = SNAPSHOT_STORE
        self._pandas = pd
        self._PandasTableModel = PandasTableModel

        # Laad referentielijsten
        self._brokers, self._asset_rollups, self._sprinter_details = load_reference_lists()
        
        # Vul comboboxen (regel 1)
        self.comboOorsprong1.set_items(["HEDGE","OPEN", "CLOSE", "ASSIGN", "EXPIRE", "DOORROL", "STOCKSPLIT", "EXERCISE"])
        self.comboBroker1.set_items(self._brokers)
        self.comboAssetRollup1.set_items(self._asset_rollups)
        self.comboAssetType1.set_items(["aandeel", "optie", "sprinter"])
        self.comboDetail1.set_items(self._sprinter_details)
        self.comboDetail1.setVisible(False)
        self.comboTransType1.set_items(["koop", "verkoop"])

        # Vul comboboxen (regel 2)
        self.comboBroker2.set_items(self._brokers)
        self.comboAssetRollup2.set_items(self._asset_rollups)
        self.comboAssetType2.set_items(["aandeel", "optie", "sprinter"])
        self.comboDetail2.set_items(self._sprinter_details)
        self.comboDetail2.setVisible(False)
        # Verberg alle widgets van regel 2 bij opstarten
        
        self.lineEditOptieExp1.editingFinished.connect(lambda e=self.lineEditOptieExp1: self.auto_fill_year(e))
        self.lineEditOptieExp2.editingFinished.connect(lambda e=self.lineEditOptieExp2: self.auto_fill_year(e))

        for widget in [
            self.comboDetail1,
            self.lineEditOptieExp1, self.lineEditOptieStrike1, self.comboOptieCP1,
            self.comboBroker2, self.comboAssetRollup2, self.comboAssetType2, self.comboDetail2,
            self.comboTransType2, self.lineEditAantal2, self.lineEditPrijs2, self.lineEditFee2,
            self.lineEditOptieExp2, self.lineEditOptieStrike2, self.comboOptieCP2, self.labelDetail, 
            self.labelOptieExp, self.labelOptieStrike, self.labelOptieCP
        ]:
            widget.setVisible(False)
        for lbl in [
            getattr(self, n, None) for n in [
                'labelBroker2', 'labelAssetRollup2', 'labelAssetType2', 'labelDetail2',
                'labelTransType2', 'labelAantal2', 'labelPrijs2', 'labelFee2',
                'labelOptieExp2', 'labelOptieStrike2', 'labelOptieCP2']
        ]:
            if lbl is not None:
                lbl.setVisible(False)
        self.comboTransType2.set_items(["koop", "verkoop"])

        # Optie CP (Call/Put) comboboxen
        self.comboOptieCP1.set_items(["call", "put"])
        self.comboOptieCP2.set_items(["call", "put"])

        # Koppel knoppen en comboboxen aan handlers
        self.buttonSave.clicked.connect(self.on_save_clicked)
        self.buttonReset.clicked.connect(self.on_reset_clicked)
        self.buttonDelete.clicked.connect(self.on_delete_clicked)
        self.comboAssetType1.currentTextChanged.connect(self.on_asset_type1_changed)
        self.comboAssetType2.currentTextChanged.connect(self.on_asset_type2_changed)
        self.comboOorsprong1.currentTextChanged.connect(self.on_oorsprong1_changed)
        
        self.comboDatabase.addItems(list(DB_MAP.keys()))
        self.comboDatabase.setCurrentText(DEFAULT_DB_NAME)
        self.comboDatabase.currentTextChanged.connect(self.apply_database_by_name)
        self._apply_db_color(DEFAULT_DB_NAME)
        
        
        self._current_offset = 0
        self._page_size = 200
        self._no_more_records = False
        self._loading_more = False
        self._sort_col = "Id"
        self._sort_dir = "DESC"
        self._init_table()
        self.tableViewOrders.selectionModel().selectionChanged.connect(self.on_table_select)
        self.comboOorsprong1.setFocus()
        # ...koppel overige events indien nodig
        # self.load_table_data()

    def auto_fill_year(self, line_edit: QLineEdit):
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
        line_edit.setText(f"{d}-{mth:02d}-{y2:02d}")


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
    
    def _reset_seek(self):
        """Reset seek/paging state wanneer filters/sortering wijzigt of bij initial load."""
        self.seek_value = None
        self.seek_id = None
        self._no_more_records = False
        self._current_offset = 0  # NEW: track offset for snapshot paging
    
    def _apply_snapshot_filters(self, df_pl):
        if q := self.active_filters.get("q", "").strip().lower():
            df_pl = df_pl.filter(
                pl.col("broker").cast(pl.Utf8).str.to_lowercase().str.contains(q) |
                pl.col("asset_rollup").cast(pl.Utf8).str.to_lowercase().str.contains(q) |
                pl.col("asset_detail").cast(pl.Utf8).str.to_lowercase().str.contains(q, literal=True) |
                pl.col("uniek_id").cast(pl.Utf8).str.to_lowercase().str.contains(q)
            )

        # Kolomfilters toepassen (uit self._col_filters)
        for col, filt_dict in (self._col_filters or {}).items():
            if col not in df_pl.columns:
                continue
            if "in" in filt_dict and filt_dict["in"]:
                df_pl = df_pl.filter(pl.col(col).is_in(list(filt_dict["in"])))
            elif "eq" in filt_dict:
                df_pl = df_pl.filter(pl.col(col) == filt_dict["eq"])
            elif "contains" in filt_dict:
                df_pl = df_pl.filter(
                    pl.col(col).cast(pl.Utf8).str.to_lowercase()
                    .str.contains(filt_dict["contains"].lower())
                )
        return df_pl

    def _apply_snapshot_sorting(self, df_pl):
        # Sorteer op de gekozen kolom en richting
        sort_col = getattr(self, '_sort_col', 'Id')
        sort_dir = getattr(self, '_sort_dir', 'DESC')
        if sort_col in df_pl.columns:
            descending = (sort_dir == 'DESC')
            df_pl = df_pl.sort(sort_col, descending=descending)
        return df_pl

    def _init_table(self):
        header = self.tableViewOrders.horizontalHeader()
        header.customContextMenuRequested.connect(self.on_header_menu)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        self._sort_col = "Id"
        self._sort_dir = "DESC"
        header.setSortIndicator(0, Qt.DescendingOrder)
        header.sortIndicatorChanged.connect(self._on_header_sort_changed)
        self.tableViewOrders.verticalScrollBar().valueChanged.connect(self._on_table_scroll)

        self.tableViewOrders.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tableViewOrders.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tableViewOrders.setAlternatingRowColors(True)
        self.tableViewOrders.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tableViewOrders.verticalHeader().setVisible(False)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        # Laad direct records met juiste sortering
        self._load_initial_records()

    def _on_clear_filters(self):
        self._col_filters.clear()
        self._text_filter = ""
        self.lineEditFilter.clear()
        self.apply_filters()
        self._reset_seek()
        self._load_initial_records()
    
        
    def _on_header_right_click(self, pos):
        logical_index = self.tableViewOrders.horizontalHeader().logicalIndexAt(pos)
        colname = self._orders_model._df.columns[logical_index]
        unique_values = list(self._orders_model._df[colname].unique())
        global_pos = self.tableViewOrders.horizontalHeader().mapToGlobal(pos)
        self._open_value_popup_for_column(colname, unique_values, global_pos)
    
    # def _open_value_popup_for_column(self, colname, unique_values, global_pos):
    #     # Maak een nieuwe popup per kolom
    #     pop = ColumnFilterPopup(f"Filter: {colname}", unique_values, pre_selected=set(self._col_filters.get(colname, {}).get("in", [])), parent=self)
    #     pop.move(global_pos)
    #     pop.acceptedSelection.connect(lambda selected: self._apply_in_filter(colname, selected))
    #     pop.cleared.connect(lambda: self._apply_in_filter(colname, set()))
    #     pop.show()

    def _apply_in_filter(self, colname, selected):
        if not selected:
            self._col_filters.pop(colname, None)
        else:
            self._col_filters[colname] = {"in": selected}
        self._load_initial_records()

    def _load_initial_records(self):
        self._current_offset = 0
        self._no_more_records = False
        self._loading_more = False
        # Gebruik Polars snapshot, filter en sorteer vóór lazy loading
        df_pl = getattr(self._snapshot_store, 'repository_snapshot_alle_transacties', None)
        if df_pl is None or df_pl.is_empty():
            df = self._pandas.DataFrame()
        else:
            df_pl = self._apply_snapshot_filters(df_pl)
            df_pl = self._apply_snapshot_sorting(df_pl)
            df = df_pl.head(self._page_size).to_pandas()
        df_view = self._format_df_for_table(df)
        self._orders_model = self._PandasTableModel(df_view, self)
        self.tableViewOrders.setModel(self._orders_model)
        self.tableViewOrders.selectionModel().selectionChanged.connect(self.on_table_select)
        self._current_offset = len(df)
        self._no_more_records = (len(df) < self._page_size)

    def _load_more_records(self, initial=False):
        if self._loading_more or self._no_more_records:
            return
        self._loading_more = True
        try:
            df_pl = getattr(self._snapshot_store, 'repository_snapshot_alle_transacties', None)
            if df_pl is None or df_pl.is_empty():
                df = self._pandas.DataFrame()
                df_view = self._format_df_for_table(df)
                if initial or not hasattr(self, '_orders_model') or self._orders_model is None:
                    self._orders_model = self._PandasTableModel(df_view, self)
                    self.tableViewOrders.setModel(self._orders_model)
                    self.tableViewOrders.selectionModel().selectionChanged.connect(self.on_table_select)
                else:
                    self._orders_model.append_df(df_view.reset_index(drop=True))
                self._no_more_records = True
                return
            # Filtering en sortering op Polars vóór slicing
            df_pl = self._apply_snapshot_filters(df_pl)
            df_pl = self._apply_snapshot_sorting(df_pl)
            df_pl_page = df_pl.slice(self._current_offset, self._page_size)
            if df_pl_page.is_empty():
                self._no_more_records = True
                return
            df = df_pl_page.to_pandas()
            df_view = self._format_df_for_table(df)
            if initial or not hasattr(self, '_orders_model') or self._orders_model is None:
                self._orders_model = self._PandasTableModel(df_view, self)
                self.tableViewOrders.setModel(self._orders_model)
                self.tableViewOrders.selectionModel().selectionChanged.connect(self.on_table_select)
            else:
                self._orders_model.append_df(df_view.reset_index(drop=True))
            self._current_offset += len(df)
            if len(df) < self._page_size:
                self._no_more_records = True
        finally:
            self._loading_more = False

    def _on_table_scroll(self, value):
        sb = self.tableViewOrders.verticalScrollBar()
        if sb.value() >= sb.maximum() - 50:
            self._load_more_records()

    def _on_header_sort_changed(self, section, order):
        try:
            colname = self._orders_model._df.columns[section]
        except Exception:
            colname = "Id"
        self._sort_col = colname
        
        self._sort_dir = "ASC" if order == Qt.AscendingOrder else "DESC"
        self._load_initial_records()



    def on_oorsprong1_changed(self, value):
        # Toon/verberg regel 2 afhankelijk van oorsprong
        zichtbaar = self.bepaal_order2_visibility(value)
        for widget in [
            self.comboBroker2, self.comboAssetRollup2, self.comboAssetType2, 
            self.comboTransType2, self.lineEditAantal2, self.lineEditPrijs2, self.lineEditFee2,
            #self.comboDetail2, self.lineEditOptieExp2, self.lineEditOptieStrike2, self.comboOptieCP2
        ]:
            widget.setVisible(zichtbaar)
        # Eventueel ook labels tonen/verbergen als die bestaan
        for lbl in [
            getattr(self, n, None) for n in [
                'labelBroker2', 'labelAssetRollup2', 'labelAssetType2', 'labelDetail2',
                'labelTransType2', 'labelAantal2', 'labelPrijs2', 'labelFee2',
                'labelOptieExp2', 'labelOptieStrike2', 'labelOptieCP2']
        ]:
            if lbl is not None:
                lbl.setVisible(zichtbaar)

    def load_table_data(self):
        """Laad transactiedata uit snapshot en vul de tabel."""
        # Haal snapshot op
        df_pl = getattr(self._snapshot_store, 'repository_snapshot_alle_transacties', None)
        self._sort_col = "Id"
        self._sort_dir = "DESC"
        if df_pl is None or df_pl.is_empty():
            df = self._pandas.DataFrame()
        else:
            # Sorteer Polars DataFrame op Id DESC
            df_pl = df_pl.sort("Id", descending=True)
            # Converteer naar pandas
            df = df_pl.to_pandas()
            df = self._format_df_for_table(df)
        # Zet model op de tableView
        self._orders_model = self._PandasTableModel(df, self)
        self.tableViewOrders.setModel(self._orders_model)
        self.tableViewOrders.selectionModel().selectionChanged.connect(self.on_table_select)
        # print(f"✅ Orders tabel geladen met na updaten van een record (een save) {len(df)} records.")

    def _format_df_for_table(self, df):
        # Gekopieerd uit oude orders_tab.py, vereenvoudigd
        TABLE_COLS = [
            "Id","datum","transactie_oorsprong","broker","asset_rollup","asset_type",
            "transactie_type","asset_detail","optie_exp_date","optie_strike","optie_call_put",
            "aantal","transactie_prijs","transactie_fee","uniek_id","transactie_oorsprong_detail"
        ]
        if df is None or df.empty:
            return self._pandas.DataFrame(columns=TABLE_COLS)
        out = df.copy()
        for c in TABLE_COLS:
            if c not in out.columns:
                out[c] = self._pandas.NA
        # Datums naar string
        out["datum"] = self._pandas.to_datetime(out["datum"], errors="coerce").dt.strftime("%d/%m/%Y")
        out["optie_exp_date"] = self._pandas.to_datetime(out["optie_exp_date"], errors="coerce").dt.strftime("%d/%m/%Y")
        def fmt2(val):
            v = self._pandas.to_numeric(val, errors="coerce")
            if self._pandas.isna(v):
                return ""
            return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        def fmt_int(val):
            v = self._pandas.to_numeric(val, errors="coerce")
            if self._pandas.isna(v):
                return ""
            return f"{int(v):,}".replace(",", ".")
        out["aantal"] = out["aantal"].apply(fmt_int)
        for c in ["optie_strike", "transactie_prijs", "transactie_fee"]:
            if c in out.columns:
                out[c] = out[c].apply(fmt2)
        for c in [
            "transactie_oorsprong","broker","asset_rollup","asset_type","transactie_type",
            "asset_detail","optie_call_put","uniek_id","transactie_oorsprong_detail"
        ]:
            if c in out.columns:
                out[c] = out[c].fillna("")
        out["datum"] = out["datum"].fillna("")
        out["optie_exp_date"] = out["optie_exp_date"].fillna("")
        out = out.fillna("")
        return out[TABLE_COLS]

    def on_save_clicked(self):
        # --- Strikte lijst-validatie: alleen waarden uit de combobox-lijsten toegestaan
        def validate_combo(combo, veldnaam, allow_empty=True):
            text = (combo.currentText() or "").strip()
            if text == "" and not allow_empty:
                QMessageBox.critical(self, "Fout", f"{veldnaam}: waarde is verplicht. orders tab widget.")
                if combo.isVisible():
                    combo.setFocus()
                    combo.lineEdit().selectAll()
                return False
            canonical = None
            for i in range(combo.count()):
                it = combo.itemText(i)
                if it.lower() == text.lower():
                    canonical = it
                    break
            if canonical is None and text != "":
                QMessageBox.critical(self, "Fout", f"{veldnaam}: ‘{text}’ staat niet in de lijst. Kies een bestaande waarde. orders tab widget.")
                if combo.isVisible():
                    combo.setFocus()
                    combo.lineEdit().selectAll()
                return False
            if canonical:
                combo.setCurrentText(canonical)
            return True

        # Order 1 validatie
        if not validate_combo(self.comboBroker1, "Broker", allow_empty=False):
            return
        if not validate_combo(self.comboAssetType1, "Type", allow_empty=False):
            return
        if not validate_combo(self.comboTransType1, "Koop/Verkoop", allow_empty=False):
            return
        at1 = self.comboAssetType1.currentText()
        if at1 == "sprinter":
            if not validate_combo(self.comboDetail1, "Asset Detail", allow_empty=False):
                return
        elif not validate_combo(self.comboAssetRollup1, "Asset Rollup", allow_empty=False):
            return
        if at1 == "optie" and not validate_combo(self.comboOptieCP1, "Call/Put", allow_empty=False):
            return

        # Order 2 validatie indien nodig
        oorspr = self.comboOorsprong1.currentText() if self.comboOorsprong1 else ""
        tweede_nodig = oorspr in ["DOORROL","ASSIGN","EXERCISE"]
        if tweede_nodig and self.comboBroker2.isVisible():
            if not validate_combo(self.comboBroker2, "Broker (regel 2)", allow_empty=False):
                return
            if not validate_combo(self.comboAssetType2, "Type (regel 2)", allow_empty=False):
                return
            if not validate_combo(self.comboTransType2, "Koop/Verkoop (regel 2)", allow_empty=False):
                return
            at2 = self.comboAssetType2.currentText()
            if at2 == "sprinter":
                if not validate_combo(self.comboDetail2, "Asset Detail (regel 2)", allow_empty=False):
                    return
            elif not validate_combo(self.comboAssetRollup2, "Asset Rollup (regel 2)", allow_empty=False):
                return
            if at2 == "optie" and not validate_combo(self.comboOptieCP2, "Call/Put (regel 2)", allow_empty=False):
                return

        # 1) Form → dict
        def parse_float(text):
            try:
                return float(text.replace(",", ".")) if text else None
            except Exception:
                return None


        eerste_order = dict(
            transactie_oorsprong=self.comboOorsprong1.currentText() or None,
            broker=self.comboBroker1.currentText() or None,
            asset_rollup=self.comboAssetRollup1.currentText() or None,
            asset_type=at1 or None,
            asset_detail=self.comboDetail1.currentText() if at1 == "sprinter" else None,
            transactie_type=self.comboTransType1.currentText() or None,
            aantal=parse_int_field(self.lineEditAantal1.text()),
            transactie_prijs=parse_float(self.lineEditPrijs1.text()),
            transactie_fee=-abs(parse_float(self.lineEditFee1.text())) if self.lineEditFee1.text() else None,
            optie_strike=parse_float(self.lineEditOptieStrike1.text()) if (at1 in ["optie", "sprinter"] and self.lineEditOptieStrike1.text()) else None,
            optie_exp_date=self.lineEditOptieExp1.text() if (at1 in ["optie", "sprinter"] and self.lineEditOptieExp1.text()) else None,
            optie_call_put=self.comboOptieCP1.currentText() if at1 in ["optie", "sprinter"] else None,
        )

        tweede_order = None
        if tweede_nodig:
            at2 = self.comboAssetType2.currentText()
            tweede_order = dict(
                transactie_oorsprong=self.comboOorsprong1.currentText(),
                broker=self.comboBroker2.currentText() or None,
                asset_rollup=self.comboAssetRollup2.currentText() or None,
                asset_type=at2 or None,
                asset_detail=self.comboDetail2.currentText() if at2 == "sprinter" else None,
                transactie_type=self.comboTransType2.currentText() or None,
                aantal=parse_int_field(self.lineEditAantal2.text()),
                transactie_prijs=parse_float(self.lineEditPrijs2.text()),
                transactie_fee=-abs(parse_float(self.lineEditFee2.text())) if self.lineEditFee2.text() else None,
                optie_strike=parse_float(self.lineEditOptieStrike2.text()) if (at2 in ["optie", "sprinter"] and self.lineEditOptieStrike2.text()) else None,
                optie_exp_date=self.lineEditOptieExp2.text() if (at2 in ["optie", "sprinter"] and self.lineEditOptieExp2.text()) else None,
                optie_call_put=self.comboOptieCP2.currentText() if at2 in ["optie", "sprinter"] else None,
            )

        # 2) Linking (oorsprong detail)
        uniek1 = self.build_uniek_id(eerste_order)
        if tweede_order:
            uniek2 = self.build_uniek_id(tweede_order)
            if self.is_pairable(eerste_order) and self.is_pairable(tweede_order):
                eerste_order["transactie_oorsprong_detail"] = uniek2
                tweede_order["transactie_oorsprong_detail"] = uniek1
            else:
                eerste_order["transactie_oorsprong_detail"] = None
                tweede_order["transactie_oorsprong_detail"] = None
        else:
            eerste_order["transactie_oorsprong_detail"] = None

        # 3) UPDATE-pad (→ geen duplicaten)
        print("start van de ceck of EDIT_ID bestaat:", getattr(self, "EDIT_ID", None))
        if self.EDIT_ID is not None:
            return self._update_existing_orders(eerste_order, tweede_order)

        try:
            new_order_id = get_next_order_id()
            eerste_order["order_id"] = new_order_id
            eerste_order["order_id_number"] = get_next_order_item_no(new_order_id)
            eerste_id = insert_transaction(eerste_order)
            tweede_id = None
            if tweede_order:
                tweede_order["order_id"] = new_order_id
                tweede_order["order_id_number"] = get_next_order_item_no(new_order_id)
                tweede_id = insert_transaction(tweede_order)
        #     # TODO: snapshot sync indien nodig
        except pyodbc.Error as e:
            QMessageBox.critical(self, "Databasefout", f"Kon niet opslaan:\n{e}")
            return
        msg = f"✅ Order opgeslagen met Id {eerste_id}"
        if tweede_id:
            msg += f" (en gekoppeld aan {tweede_id})"
        QMessageBox.information(self, "Succes", msg)
        self.load_table_data()
        self.reset_form()  # Optioneel: reset velden na insert
        self.comboOorsprong1.setFocus()
        return

    def _update_existing_orders(self, eerste_order, tweede_order):
        try:

            data_update_1 = dict(eerste_order)
            data_update_2 = dict(tweede_order) if (self.EDIT_ID2 is not None and tweede_order is not None) else None
            update_transactions_atomic(
                record_id1=int(self.EDIT_ID), data1=data_update_1,
                record_id2=(int(self.EDIT_ID2) if self.EDIT_ID2 is not None else None), data2=data_update_2
            )
            # Sync met snapshot: update eerste record
            self._update_transaction_in_snapshot(int(self.EDIT_ID), data_update_1)
            # Sync met snapshot: update tweede record (indien gekoppeld)
            if self.EDIT_ID2 is not None and data_update_2 is not None:
                self._update_transaction_in_snapshot(int(self.EDIT_ID2), data_update_2)
            # Refresh afgeleide snapshots na UPDATE
            # self._refresh_derived_snapshots()  # VERWIJDERD: centrale signalen regelen nu updates
        except pyodbc.Error as e:
            QMessageBox.critical(self, "Databasefout", f"Kon niet updaten:\n{e}")
            return
        msg = f"✅ Record {self.EDIT_ID} bijgewerkt"
        if self.EDIT_ID2 is not None and data_update_2 is not None:
            msg = f"✅ Records {self.EDIT_ID} en {self.EDIT_ID2} bijgewerkt"
        QMessageBox.information(self, "Succes", msg)
        # reset + refresh
        self.EDIT_ID = None
        self.EDIT_ID2 = None
        self._load_initial_records()
        self.reset_form()
        # self.ordersCommitted.emit()    # Live-tab verversen
        # from portefeuille_viewer.signals import signals
        # signals.ordersCommitted.emit()
        
        #self.ordersCommitted.emit()
        #self.ordersCommitted.emit()
        #from portefeuille_viewer.signals import signals
        #signals.ordersCommitted.emit()
        return

    def _update_transaction_in_snapshot(self, record_id: int, data_dict: dict):
        """
        Update een bestaand record in repository_snapshot_alle_transacties.
        Zorgt ervoor dat de snapshot gesynchroniseerd blijft met de database na een UPDATE.
        
        We herladen het record vanuit de database om schema-compatibiliteit te garanderen.
        """
        if SNAPSHOT_STORE.repository_snapshot_alle_transacties is None:
            print("⚠️ Snapshot niet geladen - kan record niet updaten")
            return  # Geen snapshot geladen, niets te doen

        try:
            # Haal het bijgewerkte record op uit de database

            with get_connection() as conn:
                sql = "SELECT * FROM transacties_bron_data_org WHERE Id = ?"
                updated_df = pl.read_database(sql, conn, execute_options={"parameters": [record_id]})

            if updated_df.is_empty():
                print(f"⚠️ Record {record_id} niet gevonden in database na UPDATE")
                return

            # Verwijder het oude record en voeg het nieuwe toe
            # Dit is eenvoudiger dan veld-voor-veld updaten en garandeert consistentie
            mask = SNAPSHOT_STORE.repository_snapshot_alle_transacties["Id"] != record_id
            SNAPSHOT_STORE.repository_snapshot_alle_transacties = pl.concat([
                SNAPSHOT_STORE.repository_snapshot_alle_transacties.filter(mask),
                updated_df
            ])
            # print(f"✅ Record {record_id} geüpdatet in snapshot")
        except Exception as e:
            self._extracted_from__update_transaction_in_snapshot_37(
                '❌ Fout bij updaten record ', record_id, ' in snapshot: ', e
            )


    def on_reset_clicked(self):
        # Reset formulier naar lege staat
        self.EDIT_ID = None
        self.EDIT_ID2 = None
        self.comboOorsprong1.setFocus()
        self.reset_form()


    def on_delete_clicked(self):
        # Verwijder geselecteerde order(s)
        """Verwijder geselecteerde order(s) op basis van Id(s)."""
        if self.EDIT_ID is None:
            QMessageBox.warning(self, "Geen selectie", "Selecteer eerst een order om te verwijderen.")
            return
        
        try:
            # Verzamel alle Ids om te verwijderen (EDIT_ID en eventueel EDIT_ID2)
            ids_to_delete = [self.EDIT_ID]
            if self.EDIT_ID2 is not None:
                ids_to_delete.append(self.EDIT_ID2)
            
            # print(f"🔍 Te verwijderen Id(s): {ids_to_delete}")
            
            # Confirmation dialog
            if len(ids_to_delete) > 1:
                msg = f"Deze order bestaat uit {len(ids_to_delete)} gekoppelde transacties.\n\nWeet je zeker dat je deze orders wilt verwijderen?"
            else:
                msg = "Weet je zeker dat je deze order wilt verwijderen?"
            
            reply = QMessageBox.question(
                self, "Bevestigen", msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply != QMessageBox.Yes:
                # print("❌ Verwijderen geannuleerd door gebruiker")
                return
            
            # Delete from database
            deleted_count = delete_transactions_by_ids(ids_to_delete)
            # print(f"🗑️ {deleted_count} record(s) verwijderd uit database")
            
            # Delete from snapshot
            self._delete_transactions_from_snapshot_by_ids(ids_to_delete)
            
            # Refresh afgeleide snapshots
            # self._refresh_derived_snapshots()  # VERWIJDERD: centrale signalen regelen nu updates
            
            # Success message
            id_list_str = ", ".join(map(str, ids_to_delete))
            QMessageBox.information(
                self, "Succes",
                f"✅ Order verwijderd: {deleted_count} record(s) (Id: {id_list_str})"
            )
            
            # Reset form en refresh
            self.EDIT_ID = None
            self.EDIT_ID2 = None
            self.reset_form()
            self.comboOorsprong1.setFocus()
            self._load_initial_records()
            # self.ordersCommitted.emit()  # Trigger refresh van andere tabs

        except Exception as e:
            QMessageBox.critical(self, "Fout", f"Kon order niet verwijderen:\n{e}")
            import traceback
            traceback.print_exc()

    def _delete_transactions_from_snapshot_by_ids(self, ids_to_delete: list):
        """Verwijder transacties met specifieke Id's uit snapshot."""
        if SNAPSHOT_STORE.repository_snapshot_alle_transacties is None:
            # print("⚠️ Snapshot niet geladen - kan records niet verwijderen")
            return
        try:
            self._extracted_from__delete_transactions_from_snapshot_by_ids_9(ids_to_delete)
        except Exception as e:
            # print(f"❌ Fout bij verwijderen uit snapshot: {e}")
            import traceback
            traceback.print_exc()
            
    # TODO Rename this here and in `_delete_transactions_from_snapshot_by_ids`
    def _extracted_from__delete_transactions_from_snapshot_by_ids_9(self, ids_to_delete):
        # Filter out records with these Id's
        before_count = len(SNAPSHOT_STORE.repository_snapshot_alle_transacties)
        SNAPSHOT_STORE.repository_snapshot_alle_transacties = SNAPSHOT_STORE.repository_snapshot_alle_transacties.filter(
            ~pl.col("Id").is_in(ids_to_delete)
        )
        after_count = len(SNAPSHOT_STORE.repository_snapshot_alle_transacties)
        deleted = before_count - after_count
        id_list_str = ", ".join(map(str, ids_to_delete))
        # print(f"✅ {deleted} record(s) met Id [{id_list_str}] verwijderd uit snapshot (totaal: {after_count} rijen)")

    def on_asset_type1_changed(self, value):
        # Gebruik OrdersTabLogica om te bepalen welke velden zichtbaar moeten zijn
        zichtbaarheid = self.bepaal_zichtbaarheid_order_fields(value)
        self.comboDetail1.setVisible(zichtbaarheid['detail'])
        self.lineEditOptieExp1.setVisible(zichtbaarheid['exp'])
        self.lineEditOptieStrike1.setVisible(zichtbaarheid['strike'])
        self.comboOptieCP1.setVisible(zichtbaarheid['cp'])
        self.labelOptieExp.setVisible(zichtbaarheid['labelOptieExp'])
        self.labelOptieStrike.setVisible(zichtbaarheid['labelOptieStrike'])
        self.labelOptieCP.setVisible(zichtbaarheid['labelOptieCP'])
        self.labelDetail.setVisible(zichtbaarheid['labelDetail'])        
        # ...herhaal voor labels indien nodig

    def on_asset_type2_changed(self, value):
        zichtbaarheid = self.bepaal_zichtbaarheid_order_fields(value)
        self.comboDetail2.setVisible(zichtbaarheid['detail'])
        self.lineEditOptieExp2.setVisible(zichtbaarheid['exp'])
        self.lineEditOptieStrike2.setVisible(zichtbaarheid['strike'])
        self.comboOptieCP2.setVisible(zichtbaarheid['cp'])
        self.labelOptieExp.setVisible(zichtbaarheid['labelOptieExp'])
        self.labelOptieStrike.setVisible(zichtbaarheid['labelOptieStrike'])
        self.labelOptieCP.setVisible(zichtbaarheid['labelOptieCP'])
        self.labelDetail.setVisible(zichtbaarheid['labelDetail'])        

        # ...herhaal voor labels indien nodig

# Je kunt de naam wijzigen naar orders_tab_methoden.py als je wilt, maar conventioneel is Widget of View gebruikelijk voor UI-klassen.
    def on_header_menu(self, pos):
        # print("Header menu op aangeroepen, positie:", pos)
        header = self.tableViewOrders.horizontalHeader()
        section = header.logicalIndexAt(pos)
        try:
            colname = self._orders_model._df.columns[section]
        except Exception:
            return

        menu = QMenu(self)
        a_asc  = menu.addAction("Sorteren A → Z")
        a_desc = menu.addAction("Sorteren Z → A")
        menu.addSeparator()
        a_clear = menu.addAction(f"Filter van {colname} wissen")
        menu.addSeparator()
        a_contains = menu.addAction("Tekst bevat…")
        a_equals   = menu.addAction("Is precies…")
        menu.addSeparator()
        a_pick = menu.addAction("Waarden kiezen…")

        act = menu.exec(header.mapToGlobal(pos))
        if not act: 
            return
        if act in (a_asc, a_desc):
            order = Qt.AscendingOrder if act == a_asc else Qt.DescendingOrder
            header.setSortIndicator(section, order)
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

        if act == a_pick:
            self._open_value_popup_for_column(colname, header.mapToGlobal(pos))
            return

    def _open_value_popup_for_column(self, colname: str, global_pos):
        import portefeuille_viewer.data.repository as repo
        # Base filters = alle actieve filters BEHALVE dit kolomfilter zelf
        base = dict(getattr(self, "active_filters", {}) or {})
        for k in list(base.keys()):
            if k.startswith("__"):
                try:
                    _, kcol = k.strip("_").split("__", 1)   # b.v. "__in__broker" -> ("in","broker")
                except ValueError:
                    continue
                if kcol == colname:
                    base.pop(k, None)

        try:
            values = repo.get_distinct_values(colname, base_filters=base)
        except Exception as e:
            QMessageBox.critical(self, "Filter", f"Kon waarden voor '{colname}' niet laden:\n{e}")
            return

        pre = set()
        if colname in (self._col_filters or {}) and "in" in self._col_filters[colname]:
            pre = set(self.col_filters[colname]["in"])

        pop = ColumnFilterPopup(f"Filter: {colname}", values, pre_selected=pre, parent=self)
        pop.move(global_pos)
        pop.acceptedSelection.connect(lambda selected: self._apply_in_filter(colname, selected))
        pop.cleared.connect(lambda: self._clear_col_filter(colname))
        pop.show()
        
    def _clear_col_filter(self, colname: str):
        self._col_filters.pop(colname, None)
        self.apply_filters()


    def on_table_select(self, selected, deselected):
        sel = self.tableViewOrders.selectionModel()
        if sel is None:
            return
        rows = sel.selectedRows()
        if not rows:
            return

        r = rows[0].row()
        rec = self._orders_model.get_row(r) if hasattr(self._orders_model, "get_row") else {}
        if not rec:
            return

        try:
            with get_connection() as conn:
                df_sel = pd.read_sql(
                    "SELECT * FROM transacties_bron_data_org WHERE Id = ?",
                    conn, params=[int(rec.get("Id"))]
                )
            if df_sel.empty:
                return

            r1 = df_sel.iloc[0].to_dict()
            self.EDIT_ID = int(r1["Id"])
            # print(f"EDIT1 opgehaald. Loading record Id {self.EDIT_ID} into form")
            self.fill_form_from_row(self.order1, r1, side=1)

            # probeer bijbehorende tweede
            self.EDIT_ID2 = None
            oid = r1.get("order_id")
            if pd.notna(oid):
                with get_connection() as conn:
                    df_grp = pd.read_sql(
                        "SELECT * FROM transacties_bron_data_org WHERE order_id = ? ORDER BY order_id_number, Id",
                        conn, params=[int(oid)]
                    )
                others = df_grp[df_grp["Id"] != self.EDIT_ID]
                if not others.empty:
                    r2 = others.iloc[0].to_dict()
                    self.EDIT_ID2 = int(r2["Id"])
                    # print(f"EDIT2 opgehaald. Loading linked record Id {self.EDIT_ID2} into form")
                    self.fill_form_from_row(self.order2, r2, side=2)
                    self._show_order2(True)
                    return

            # geen tweede record → forceer weg
            self.EDIT_ID2 = None
            # leegmaken (optioneel maar netjes)
            for k in ["broker","asset_rollup","asset_type","trans_type","aantal","prijs","fee","exp","strike","cp","detail"]:
                w = self.order2.get(k)
                if w is None:
                    continue
                # Prefer SmartCombo.reset when available
                if hasattr(w, "reset"):
                    with contextlib.suppress(Exception):
                        w.reset()
                        continue
                if hasattr(w, "setCurrentIndex"): 
                    w.setCurrentIndex(-1)
                if hasattr(w, "setEditText"): 
                    w.setEditText("")
                if hasattr(w, "clear"): 
                    w.clear()
            self._show_order2(False)

        except Exception as e:
            QMessageBox.critical(self, "Selectie", f"Kon record niet laden:\n{e}")
            
    def fill_form_from_row(self, part, row: dict, side: int):
        """
        Vul alle velden van 'part' (order1 of order2) uit een DB-rij.
        Zorgt er ook voor dat de juiste extra velden zichtbaar zijn.
        """
        # Oorsprong (alleen op regel 1 aanwezig)
        if side == 1 and part.get("cb_oorsprong"):
            part["cb_oorsprong"].setCurrentText(str(row.get("transactie_oorsprong") or ""))

        # Standaardvelden
        part["broker"].setCurrentText(str(row.get("broker") or ""))
        part["asset_rollup"].setCurrentText(str(row.get("asset_rollup") or ""))
        part["asset_type"].setCurrentText(str(row.get("asset_type") or ""))
        part["trans_type"].setCurrentText(str(row.get("transactie_type") or ""))

        # Numerieke/tekstvelden
        def to_str_or_empty(v): return "" if v in (None, "") else str(v)

        part["aantal"].setText(to_str_or_empty(row.get("aantal")))
        part["prijs"].setText(to_str_or_empty(row.get("transactie_prijs")))
        part["fee"].setText(to_str_or_empty(row.get("transactie_fee")))

        # Sprinter detail
        part["detail"].setCurrentText(str(row.get("asset_detail") or ""))

        # Optievelden
        part["strike"].setText(to_str_or_empty(row.get("optie_strike")))
        # datum netjes weergeven
        try:
            d = row.get("optie_exp_date")
            if pd.notna(d):
                dstr = pd.to_datetime(d, errors="coerce").strftime("%d-%m-%y")
            else:
                dstr = ""
        except Exception:
            dstr = to_str_or_empty(row.get("optie_exp_date"))
        part["exp"].setText(dstr)
        part["cp"].setCurrentText(str(row.get("optie_call_put") or ""))

        # Toon/verberg de juiste velden na het zetten van 'asset_type'
        if side == 1:
            self.toggle_order1_fields()
        else:
            # Zorg dat regel 2 zichtbaar wordt als er een tweede order is
            for w in [part["broker"], part["asset_rollup"], part["asset_type"], part["trans_type"],
                    part["aantal"], part["prijs"], part["fee"]]:
                w.setVisible(True)
            self.toggle_order2_fields()
            
    def _show_order2(self, visible: bool):
        widgets = [
            "broker","asset_rollup","asset_type","detail","trans_type","aantal","prijs","fee",
            #"lbl_exp","exp","lbl_strike","strike","lbl_cp","cp"
        ]
        for key in widgets:
            if self.order2[key] is not None:  # Skip None values
                self.order2[key].setVisible(visible)
        if visible:
            self.toggle_order2_fields()
    def reset_form(self):
        for part in [self.order1, self.order2]:
            for k in ["cb_oorsprong", "broker", "asset_rollup", "asset_type",
                    "trans_type", "detail", "cp"]:
                w = part.get(k)
                if w is not None:
                    # Prefer a dedicated reset() when available (SmartCombo)
                    if hasattr(w, "reset"):
                        try:
                            w.reset()
                        except Exception:
                            # fallback to safer clears
                            if hasattr(w, "setCurrentIndex"): 
                                w.setCurrentIndex(-1)
                            if hasattr(w, "setEditText"): 
                                w.setEditText("")
                    else:
                        if hasattr(w, "setCurrentIndex"): 
                            w.setCurrentIndex(-1)
                        if hasattr(w, "setEditText"): 
                            w.setEditText("")
            for k in ["aantal", "prijs", "fee", "exp", "strike"]:
                if part.get(k) is not None:
                    part[k].clear()
        self.toggle_order1_fields()
        # Ensure order2 reference lists are reattached before toggling visibility
        # so that when the row is shown again its combos have fresh models.
        with contextlib.suppress(Exception):
            # reapply lists from current references
            if hasattr(self, "brokers"):
                self.order2["broker"].set_items(self.brokers)
            if hasattr(self, "asset_rollups"):
                self.order2["asset_rollup"].set_items(self.asset_rollups)
            if hasattr(self, "sprinter_details"):
                self.order2["detail"].set_items(self.sprinter_details)
        self.toggle_order2_visibility()
        
    def toggle_order2_visibility(self):
        oorspr = self.order1["cb_oorsprong"].currentText() if self.order1["cb_oorsprong"] else ""
        visible = oorspr in ["DOORROL", "ASSIGN", "EXERCISE"]

        widgets = [
            "broker","asset_rollup","asset_type","trans_type","aantal","prijs","fee",
            #"lbl_exp","exp","lbl_strike","strike","lbl_cp","cp","detail",
        ]
        for key in widgets:
            if self.order2[key] is not None:  # Skip None values (like lbl_detail)
                self.order2[key].setVisible(visible)

        if visible:
            self.toggle_order2_fields()

    def toggle_order1_fields(self):
        at = self.order1["asset_type"].currentText()
        try:
            for w in [ self.order1["detail"],
                    self.order1["exp"],
                    self.order1["strike"],
                    self.order1["cp"]]:
                if w is not None:
                    w.setVisible(False)

            # Sprinter: toon detail + exp/strike/cp velden
            if at == "sprinter":
                # lbl_detail zit nu in header, alleen detail widget toggen
                for w in [self.order1["detail"],self.order1["exp"],self.order1["strike"],self.order1["cp"],
                        #self.order1["lbl_exp"], self.order1["lbl_strike"], self.order1["lbl_cp"], 
                        ]:
                    if w is not None:
                        w.setVisible(True)


            # Optie: toon alleen optievelden
            elif at == "optie":
                for w in [self.order1["exp"],self.order1["strike"],self.order1["cp"],
                        #self.order1["lbl_exp"], self.order1["lbl_strike"], self.order1["lbl_cp"]
                        ]:
                    if w is not None:
                        w.setVisible(True)
        except Exception as e:
            QMessageBox.critical(self, "Selectie", f"Kon record niet laden:\n{e}")
            traceback.print_exc()  # ← print de volledige stacktrace naar de terminal
        # Eerst alles verbergen
        

    def toggle_order2_fields(self):
        at = self.order2["asset_type"].currentText()
        try:
            
        # Eerst alles verbergen
            for w in [
                    self.order2["detail"], self.order2["exp"],self.order2["strike"],self.order2["cp"],
                    #self.order2["lbl_strike"], self.order2["lbl_exp"],self.order2["lbl_cp"]
                    ]:
                if w is not None:
                    w.setVisible(False)

            # Sprinter: toon detail + exp/strike/cp velden
            if at == "sprinter":
                for w in [self.order2["detail"], self.order2["exp"],self.order2["strike"], self.order2["cp"],
                        #self.order1["lbl_exp"], self.order1["lbl_strike"], self.order1["lbl_cp"]
                        ]:
                    if w is not None:
                        w.setVisible(True)

            # Optie: toon alleen optievelden
            elif at == "optie":
                for w in [ self.order2["exp"], self.order2["strike"], self.order2["cp"],
                        #self.order1["lbl_exp"],self.order1["lbl_strike"],self.order1["lbl_cp"],
                        ]:
                    if w is not None:
                        w.setVisible(True)
        except Exception as e:
            QMessageBox.critical(self, "Selectie", f"Kon record niet laden:\n{e}")
            traceback.print_exc()  # ← print de volledige stacktrace naar de terminal
            
    
    def bepaal_order2_visibility(self, oorsprong: str):
        """
        Bepaalt of order2 zichtbaar moet zijn op basis van oorsprong.
        """
        return oorsprong in {"DOORROL", "ASSIGN", "EXERCISE"}


    def bepaal_zichtbaarheid_order_fields(self, asset_type: str):
        """
        Bepaalt welke velden zichtbaar moeten zijn voor een orderrij op basis van asset_type.
        Geeft een dict terug met veldnamen als key en True/False als waarde.
        """
        # Basis: alles uit behalve standaardvelden
        zichtbaarheid = {
            'detail': False,
            'exp': False,
            'strike': False,
            'cp': False,
            # 'lbl_exp': False, 'lbl_strike': False, 'lbl_cp': False, 
            'labelOptieExp': False, 'optie_exp': False,
            'labelOptieStrike': False, 'optie_strike': False,
            'labelOptieCP': False, 'optie_call_put': False,
            'labelDetail': False
        }
        if asset_type == 'sprinter':
            for k in ['detail','exp','strike','cp','labelDetail','labelOptieExp','labelOptieStrike','labelOptieCP']:
                zichtbaarheid[k] = True
        elif asset_type == 'optie':
            for k in ['exp','strike','cp','labelOptieExp','labelOptieStrike','labelOptieCP']: #,'lbl_exp','lbl_strike','lbl_cp'
                zichtbaarheid[k] = True
        return zichtbaarheid
    
    def build_uniek_id(self, values: dict) -> str:
        broker = self._clean(values.get("broker"))
        at = self._clean(values.get("asset_type")).lower()
        if at == "optie":
            rollup = self._clean(values.get("asset_rollup"))
            exp    = self._date_for_id(values.get("optie_exp_date"))
            cp     = self._clean(values.get("optie_call_put")).lower()
            strike = self._norm_dec_for_id(values.get("optie_strike"))
            return f"{broker}-{rollup}-{at}-{exp}-{cp}-{strike}"
        if at == "sprinter":
            detail = self._clean(values.get("asset_detail"))
            return f"{broker}-{detail}-{at}"
        if at == "aandeel":
            rollup = self._clean(values.get("asset_rollup"))
            return f"{broker}-{rollup}-{at}"
        rollup = self._clean(values.get("asset_rollup"))
        return f"{broker}-{rollup}-{at}"

    
    def is_pairable(self, order: dict) -> bool:
        oorspr = (order.get("transactie_oorsprong") or "").upper()
        return oorspr in {"DOORROL", "ASSIGN",  "EXERCISE"}
    
    def _clean(self, x):
        return "" if x is None else str(x).strip()
    
    
    def _date_for_id(self, x):
        d = self._parse_date(x)
        return f"{d.day}-{d.month}-{d.year}" if d else ""
    
    def _norm_dec_for_id(self, x):
        if x in (None, ""):
            return ""
        s = str(x).strip().replace(",", ".")
        try:
            f = float(s)
            return str(int(f)) if f.is_integer() else f"{f}".rstrip("0").rstrip(".")
        except ValueError:
            return s
        
    def _parse_date(self, x):
        from datetime import date, datetime
        if x in (None, ""):
            return None
        if isinstance(x, datetime):
            return x.date()
        if isinstance(x, date):
            return x
        s = str(x).strip().replace("\\", "/").replace("-", "/")
        p = s.split("/")
        try:
            if len(p) == 3:
                if len(p[0]) <= 2 and len(p[1]) <= 2:
                    d, m, y = int(p[0]), int(p[1]), int(p[2])
                    y = (2000+y) if y < 100 else y
                    return date(y, m, d)
                if len(p[0]) == 4:
                    y, m, d = int(p[0]), int(p[1]), int(p[2])
                    return date(y, m, d)
        except Exception:
            return None
        return None
    
    def apply_database_by_name(self, name):
        import portefeuille_viewer.data.repository as repo
        try:
            repo.switch_database(name)  # ✅ correcte manier
        except Exception as e:
            QMessageBox.critical(self, "Database", f"Kan niet verbinden:\n{e}")
            return

        # print(f"🔄 Database gewisseld naar: {name}")
        
        # Herlaad repository_snapshot_alle_transacties uit de nieuwe database
        try:
            # print("📥 Laden van repository_snapshot_alle_transacties uit nieuwe database...")
            repo.load_alle_transacties()
            print(f"✅ repository_snapshot_alle_transacties geladen: {len(SNAPSHOT_STORE.repository_snapshot_alle_transacties)} rijen")
        except Exception as e:
            QMessageBox.critical(self, "Database", f"Kon transacties niet laden:\n{e}")
            # print(f"❌ Fout bij laden transacties: {e}")
            import traceback
            traceback.print_exc()
            return
        
        # Refresh alle afgeleide snapshots ###################################### DATABASE WISSEL #############
        # self._refresh_derived_snapshots()  # VERWIJDERD: centrale signalen regelen nu updates

        # ververs alle referentielijsten
        self.brokers, self.asset_rollups, self.sprinter_details = repo.load_reference_lists()
        # self.brokers, self.asset_rollups, self.sprinter_details = load_reference_lists()
        # zet in beide order-rijen
        self.order1["broker"].set_items(self.brokers)
        self.order1["asset_rollup"].set_items(self.asset_rollups)
        self.order1["detail"].set_items(self.sprinter_details)

        self.order2["broker"].set_items(self.brokers)
        self.order2["asset_rollup"].set_items(self.asset_rollups)
        self.order2["detail"].set_items(self.sprinter_details)

        for part in [self.order1, self.order2]:
            part["broker"].set_items(self.brokers)
            part["asset_rollup"].set_items(self.asset_rollups)
            part["detail"].set_items(self.sprinter_details)

        
        
        self._apply_db_color(name)  # wisselt de kleurstijl van de DB-keuze
        
        self.reset_form()           # wist velden + toggles
        
        self._load_initial_records()
        self.dbChanged.emit()
        # Zend centraal signaal uit voor app-brede database-wissel
        if hasattr(self, 'active_db_name'):
            signals.databaseChanged.emit(self.active_db_name)
            
    def _apply_db_color(self, name: str):
        style = DB_STYLES.get(name, {"fg": "black", "bg": "white"})
        fg = style.get("fg", "black")
        bg = style.get("bg", "white")
        css = f"""
        QComboBox {{
            color: {fg}; background-color: {bg}; font-weight: bold;
            padding: 2px 24px 2px 6px; border: 1px solid rgba(0,0,0,0.25); border-radius: 6px;
        }}
        QComboBox::drop-down {{ width: 22px; border: none; }}
        QComboBox QAbstractItemView {{
            color: black; background-color: white;
            selection-background-color: {bg}; selection-color: white;
        }}
        """
        
        self.comboDatabase.setStyleSheet(css)
        
    def set_items(self, items):
        items_sorted = sorted([str(x) for x in items], key=str.lower)
        self.blockSignals(True)
        self.clear()
        self.addItems(items_sorted)
        self.completer.setModel(self.model())
        self.setCurrentIndex(-1)
        if self.isEditable():
            self.setEditText("")
        self.blockSignals(False)
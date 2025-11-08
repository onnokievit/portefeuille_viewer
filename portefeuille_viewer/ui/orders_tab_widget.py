import contextlib
from PySide6.QtWidgets import QWidget, QMenu, QInputDialog, QMessageBox
from PySide6.QtCore import Qt

from portefeuille_viewer.ui.filter_popup import ColumnFilterPopup  # ← nieuw
from portefeuille_viewer.ui.orders_tab_ui import Ui_OrdersTabUI
from portefeuille_viewer.ui_logica.orders_tab_logica import OrdersTabLogica

from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.ui.models import PandasTableModel

import pandas as pd
import polars as pl

from portefeuille_viewer.data.repository import (
    DB_MAP, DB_STYLES, DEFAULT_DB_NAME,
    get_connection,
    load_reference_lists, insert_transaction, update_transactions_atomic,
    build_uniek_id, is_pairable,
    get_next_order_id, get_next_order_item_no,
)

class OrdersTabWidget(QWidget, Ui_OrdersTabUI):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        # Importeer hier om circular import te voorkomen
        
        self.lineEditFilter.returnPressed.connect(self.apply_filters)
        self.buttonClearFilters.clicked.connect(self._on_clear_filters)
        # self.tableViewOrders.selectionModel().selectionChanged.connect(self.on_table_select)
        
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
        for widget in [
            self.comboBroker2, self.comboAssetRollup2, self.comboAssetType2, self.comboDetail2,
            self.comboTransType2, self.lineEditAantal2, self.lineEditPrijs2, self.lineEditFee2,
            self.lineEditOptieExp2, self.lineEditOptieStrike2, self.comboOptieCP2
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
        self._current_offset = 0
        self._page_size = 200
        self._no_more_records = False
        self._loading_more = False
        self._sort_col = "Id"
        self._sort_dir = "DESC"
        self._init_table()
        # ...koppel overige events indien nodig
        # self.load_table_data()

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
        # Pas tekstfilter toe (uit self.active_filters["q"])
        q = self.active_filters.get("q", "").strip().lower()
        if q:
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
    
    
    
    
    # def _apply_snapshot_filters(self, df_pl):
    #     for col, filt_dict in self._col_filters.items():
    #         if col not in df_pl.columns:
    #             continue
    #         # voorbeeld: 'in' filter
    #         if "in" in filt_dict and filt_dict["in"]:
    #             df_pl = df_pl.filter(pl.col(col).is_in(list(filt_dict["in"])))
    #         # andere filtertypes kun je uitbreiden zoals in je oude tab
    #     return df_pl

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
        from PySide6.QtCore import Qt
        # Forceer sortering op Id DESC bij opstarten
        self._sort_col = "Id"
        self._sort_dir = "DESC"
        header.setSortIndicator(0, Qt.DescendingOrder)


        header.sortIndicatorChanged.connect(self._on_header_sort_changed)
        self.tableViewOrders.verticalScrollBar().valueChanged.connect(self._on_table_scroll)
        from PySide6.QtWidgets import QAbstractItemView
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
        from PySide6.QtCore import Qt
        self._sort_dir = "ASC" if order == Qt.AscendingOrder else "DESC"
        self._load_initial_records()



    def on_oorsprong1_changed(self, value):
        # Toon/verberg regel 2 afhankelijk van oorsprong
        zichtbaar = OrdersTabLogica.bepaal_order2_visibility(value)
        for widget in [
            self.comboBroker2, self.comboAssetRollup2, self.comboAssetType2, self.comboDetail2,
            self.comboTransType2, self.lineEditAantal2, self.lineEditPrijs2, self.lineEditFee2,
            self.lineEditOptieExp2, self.lineEditOptieStrike2, self.comboOptieCP2
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
        if df_pl is None or df_pl.is_empty():
            df = self._pandas.DataFrame()
        else:
            # Converteer naar pandas
            df = df_pl.to_pandas()
            df = self._format_df_for_table(df)
        # Zet model op de tableView
        self._orders_model = self._PandasTableModel(df, self)
        self.tableViewOrders.setModel(self._orders_model)

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
        from portefeuille_viewer.data.repository import (
            insert_transaction, update_transactions_atomic, build_uniek_id, is_pairable, get_next_order_id, get_next_order_item_no
        )
        from PySide6.QtWidgets import QMessageBox
        import pyodbc

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
        tweede_nodig = oorspr in ["DOORROL","ASSIGN","EXPIRE","EXERCISE"]
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
        def parse_int(text):
            try:
                return int(text)
            except Exception:
                return None

        eerste_order = dict(
            transactie_oorsprong=self.comboOorsprong1.currentText() or None,
            broker=self.comboBroker1.currentText() or None,
            asset_rollup=self.comboAssetRollup1.currentText() or None,
            asset_type=at1 or None,
            asset_detail=self.comboDetail1.currentText() if at1 == "sprinter" else None,
            transactie_type=self.comboTransType1.currentText() or None,
            aantal=parse_int(self.lineEditAantal1.text()),
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
                aantal=parse_int(self.lineEditAantal2.text()),
                transactie_prijs=parse_float(self.lineEditPrijs2.text()),
                transactie_fee=-abs(parse_float(self.lineEditFee2.text())) if self.lineEditFee2.text() else None,
                optie_strike=parse_float(self.lineEditOptieStrike2.text()) if (at2 in ["optie", "sprinter"] and self.lineEditOptieStrike2.text()) else None,
                optie_exp_date=self.lineEditOptieExp2.text() if (at2 in ["optie", "sprinter"] and self.lineEditOptieExp2.text()) else None,
                optie_call_put=self.comboOptieCP2.currentText() if at2 in ["optie", "sprinter"] else None,
            )

        # 2) Linking (oorsprong detail)
        uniek1 = build_uniek_id(eerste_order)
        if tweede_order:
            uniek2 = build_uniek_id(tweede_order)
            if is_pairable(eerste_order) and is_pairable(tweede_order):
                eerste_order["transactie_oorsprong_detail"] = uniek2
                tweede_order["transactie_oorsprong_detail"] = uniek1
            else:
                eerste_order["transactie_oorsprong_detail"] = None
                tweede_order["transactie_oorsprong_detail"] = None
        else:
            eerste_order["transactie_oorsprong_detail"] = None

        # 3) UPDATE-pad (→ geen duplicaten)
        if hasattr(self, "EDIT_ID") and self.EDIT_ID is not None:
            try:
                data_update_1 = dict(eerste_order)
                data_update_2 = dict(tweede_order) if (hasattr(self, "EDIT_ID2") and self.EDIT_ID2 is not None and tweede_order is not None) else None
                update_transactions_atomic(
                    record_id1=int(self.EDIT_ID), data1=data_update_1,
                    record_id2=(int(self.EDIT_ID2) if hasattr(self, "EDIT_ID2") and self.EDIT_ID2 is not None else None), data2=data_update_2
                )
                # TODO: snapshot sync indien nodig
            except pyodbc.Error as e:
                QMessageBox.critical(self, "Databasefout", f"Kon niet updaten:\n{e}")
                return
            msg = f"✅ Record {self.EDIT_ID} bijgewerkt"
            if hasattr(self, "EDIT_ID2") and self.EDIT_ID2 is not None and data_update_2 is not None:
                msg = f"✅ Records {self.EDIT_ID} en {self.EDIT_ID2} bijgewerkt"
            QMessageBox.information(self, "Succes", msg)
            self.EDIT_ID = None
            self.EDIT_ID2 = None
            self.load_table_data()
            # self.reset_form()  # Optioneel: reset velden na update
            return

        # 4) INSERT-pad
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
            # TODO: snapshot sync indien nodig
        except pyodbc.Error as e:
            QMessageBox.critical(self, "Databasefout", f"Kon niet opslaan:\n{e}")
            return
        msg = f"✅ Order opgeslagen met Id {eerste_id}"
        if tweede_id:
            msg += f" (en gekoppeld aan {tweede_id})"
        QMessageBox.information(self, "Succes", msg)
        self.load_table_data()
        # self.reset_form()  # Optioneel: reset velden na insert
        return

    def on_reset_clicked(self):
        # Reset alle velden naar default/empty
        pass

    def on_delete_clicked(self):
        # Verwijder geselecteerde order(s)
        pass

    def on_asset_type1_changed(self, value):
        # Gebruik OrdersTabLogica om te bepalen welke velden zichtbaar moeten zijn
        zichtbaarheid = OrdersTabLogica.bepaal_zichtbaarheid_order_fields(value)
        self.comboDetail1.setVisible(zichtbaarheid['detail'])
        self.lineEditOptieExp1.setVisible(zichtbaarheid['exp'])
        self.lineEditOptieStrike1.setVisible(zichtbaarheid['strike'])
        self.comboOptieCP1.setVisible(zichtbaarheid['cp'])
        # ...herhaal voor labels indien nodig

    def on_asset_type2_changed(self, value):
        zichtbaarheid = OrdersTabLogica.bepaal_zichtbaarheid_order_fields(value)
        self.comboDetail2.setVisible(zichtbaarheid['detail'])
        self.lineEditOptieExp2.setVisible(zichtbaarheid['exp'])
        self.lineEditOptieStrike2.setVisible(zichtbaarheid['strike'])
        self.comboOptieCP2.setVisible(zichtbaarheid['cp'])
        # ...herhaal voor labels indien nodig

# Je kunt de naam wijzigen naar orders_tab_methoden.py als je wilt, maar conventioneel is Widget of View gebruikelijk voor UI-klassen.
    def on_header_menu(self, pos):
        print("Header menu op aangeroepen, positie:", pos)
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


    # def on_table_select(self, selected, deselected):
    #     sel = self.table.selectionModel()
    #     if sel is None:
    #         return
    #     rows = sel.selectedRows()
    #     if not rows:
    #         return

    #     r = rows[0].row()
    #     rec = self.model.get_row(r) if hasattr(self.model, "get_row") else {}
    #     if not rec:
    #         return

    #     try:
    #         with get_connection() as conn:
    #             df_sel = pd.read_sql(
    #                 "SELECT * FROM transacties_bron_data_org WHERE Id = ?",
    #                 conn, params=[int(rec.get("Id"))]
    #             )
    #         if df_sel.empty:
    #             return

    #         r1 = df_sel.iloc[0].to_dict()
    #         self.EDIT_ID = int(r1["Id"])
    #         self.fill_form_from_row(self.order1, r1, side=1)

    #         # probeer bijbehorende tweede
    #         self.EDIT_ID2 = None
    #         oid = r1.get("order_id")
    #         if pd.notna(oid):
    #             with get_connection() as conn:
    #                 df_grp = pd.read_sql(
    #                     "SELECT * FROM transacties_bron_data_org WHERE order_id = ? ORDER BY order_id_number, Id",
    #                     conn, params=[int(oid)]
    #                 )
    #             others = df_grp[df_grp["Id"] != self.EDIT_ID]
    #             if not others.empty:
    #                 r2 = others.iloc[0].to_dict()
    #                 self.EDIT_ID2 = int(r2["Id"])
    #                 self.fill_form_from_row(self.order2, r2, side=2)
    #                 self._show_order2(True)
    #                 return

    #         # geen tweede record → forceer weg
    #         self.EDIT_ID2 = None
    #         # leegmaken (optioneel maar netjes)
    #         for k in ["broker","asset_rollup","asset_type","trans_type","aantal","prijs","fee","exp","strike","cp","detail"]:
    #             w = self.order2.get(k)
    #             if w is None:
    #                 continue
    #             # Prefer SmartCombo.reset when available
    #             if hasattr(w, "reset"):
    #                 with contextlib.suppress(Exception):
    #                     w.reset()
    #                     continue
    #             if hasattr(w, "setCurrentIndex"): 
    #                 w.setCurrentIndex(-1)
    #             if hasattr(w, "setEditText"): 
    #                 w.setEditText("")
    #             if hasattr(w, "clear"): 
    #                 w.clear()
    #         self._show_order2(False)

    #     except Exception as e:
    #         QMessageBox.critical(self, "Selectie", f"Kon record niet laden:\n{e}")



from PySide6.QtWidgets import QWidget
from portefeuille_viewer.ui.orders_tab_ui import Ui_OrdersTabUI
from portefeuille_viewer.ui_logica.orders_tab_logica import OrdersTabLogica

class OrdersTabWidget(QWidget, Ui_OrdersTabUI):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        # Importeer hier om circular import te voorkomen
        from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
        from portefeuille_viewer.ui.models import PandasTableModel
        from portefeuille_viewer.data.repository import load_reference_lists
        import pandas as pd

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

    def _apply_snapshot_filters(self, df_pl):
        # Placeholder: voeg hier je eigen filterlogica toe, evt. met self._active_filters
        # Voor nu geen filters, maar structuur is klaar voor uitbreiding
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
        # Laad direct records met juiste sortering
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
                QMessageBox.critical(self, "Fout", f"{veldnaam}: waarde is verplicht.")
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
                QMessageBox.critical(self, "Fout", f"{veldnaam}: ‘{text}’ staat niet in de lijst. Kies een bestaande waarde.")
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

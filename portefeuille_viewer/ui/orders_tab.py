import re
from datetime import date, datetime
from typing import Optional

import pandas as pd
import pyodbc
from PySide6.QtCore import Qt, QModelIndex, QEvent, Signal
from PySide6.QtWidgets import QMenu, QInputDialog  # ← toevoegen
from portefeuille_viewer.ui.filter_popup import ColumnFilterPopup  # ← nieuw
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QGridLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QTableView, QHeaderView,
    QAbstractItemView, QCompleter, QMessageBox, QSpacerItem, QSizePolicy
)

from portefeuille_viewer.data.repository import (
    DB_MAP, DB_STYLES, DEFAULT_DB_NAME,
    conn_str, get_connection,
    load_reference_lists, insert_transaction, update_transactions_atomic,
    fetch_records_page, build_uniek_id, is_pairable,
    get_next_order_id, get_next_order_item_no,
)

from portefeuille_viewer.ui.models import PandasTableModel
# test
# ------------------------------------------------------------
# SmartCombo helper
# ------------------------------------------------------------
class SmartCombo(QComboBox):
    def __init__(self, parent=None, match_contains=False, auto_accept_on_tab=True):
        super().__init__(parent)
        self.setEditable(True)
        self._match_contains = match_contains
        self._auto_accept_on_tab = auto_accept_on_tab
        self.setInsertPolicy(QComboBox.NoInsert)  # voorkom "toevoegen" van vrije tekst
        self.lineEdit().editingFinished.connect(self._validate_in_list_now)
        self.completer = QCompleter(self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains if match_contains else Qt.MatchStartsWith)
        self.completer.setCompletionMode(
            QCompleter.PopupCompletion if match_contains else QCompleter.InlineCompletion
        )
        self.setCompleter(self.completer)
        self.lineEdit().editingFinished.connect(self._force_inline_completion)
        if auto_accept_on_tab:
            self.lineEdit().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.lineEdit() and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter):
                self._force_inline_completion()
                self._validate_in_list_now()
        return super().eventFilter(obj, event)


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

    def _force_inline_completion(self):
        if self._match_contains:
            return
        text = self.currentText() or ""
        if not text:
            return
        m = self.model()
        best = None
        for i in range(m.rowCount()):
            it = self.itemText(i)
            if it.lower().startswith(text.lower()):
                best = it
                break
        if best:
            self.setCurrentText(best)

    def _validate_in_list_now(self) -> bool:
        """
        Live validatie: als er tekst staat die niet overeenkomt met een item (case-insensitive),
        toon popup en focus terug. Bij match zet 'm naar de canonieke schrijfwijze.
        """
        text = (self.currentText() or "").strip()
        if not text:
            return True  # leeg laten we aan 'opslaan'-validatie (verplicht/niet-verplicht)

        canonical = None
        for i in range(self.count()):
            it = self.itemText(i)
            if it.lower() == text.lower():
                canonical = it
                break

        if canonical is None:
            veld = self.objectName() or "Veld"
            QMessageBox.critical(self, "Fout", f"{veld}: ‘{text}’ staat niet in de lijst. Kies een bestaande waarde.")
            self.setFocus()
            self.lineEdit().selectAll()
            return False

        self.setCurrentText(canonical)
        return True



# ------------------------------------------------------------
# OrdersTab
# ------------------------------------------------------------
class OrdersTab(QWidget):
    ordersCommitted = Signal()     # Na succesvol opslaan of update
    dbChanged = Signal()           # DB-switch event

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.EDIT_ID = None
        self.EDIT_ID2 = None
        self._loading_more = False
        self._no_more_records = False

        self.sort_col = "Id"
        self.sort_dir = "DESC"
        self.active_filters = {}
        self.seek_value = None
        self.seek_id = None

        self.brokers, self.asset_rollups, self.sprinter_details = load_reference_lists()

        v = QVBoxLayout(self)
        v.addWidget(self._build_orders_grid())
        v.addLayout(self._build_topbar())
        self._apply_db_color(DEFAULT_DB_NAME)
        v.addWidget(self._build_table())
        self.col_filters = {}   # {"kolomnaam": {"in": set([...])}, ...}

        self._wire_dynamic()
        self.reset_form()
        self.load_initial_records()



    def _validate_combo_in_list(self, combo, veldnaam: str, allow_empty: bool = True) -> bool:
        """
        Staat alleen waarden toe die precies in de lijst voorkomen (case-insensitive).
        - allow_empty=False => lege invoer is niet toegestaan.
        - Bij match zet hij het 'canonieke' item (zoals in de lijst) terug.
        """
        if combo is None:
            return True

        text = (combo.currentText() or "").strip()
        if text == "":
            if allow_empty:
                return True
            QMessageBox.critical(self, "Fout", f"{veldnaam}: waarde is verplicht.")
            if combo.isVisible():
                combo.setFocus(); combo.lineEdit().selectAll()
            return False

        # zoek exact item (case-insensitive)
        canonical = None
        for i in range(combo.count()):
            it = combo.itemText(i)
            if it.lower() == text.lower():
                canonical = it
                break

        if canonical is None:
            QMessageBox.critical(self, "Fout", f"{veldnaam}: ‘{text}’ staat niet in de lijst. Kies een bestaande waarde.")
            if combo.isVisible():
                combo.setFocus(); combo.lineEdit().selectAll()
            return False

        # zet het canonieke item (zorgt voor consistente hoofdletters/tekens)
        combo.setCurrentText(canonical)
        return True






    # --------------------------------------------------------
    # UI Builders
    # --------------------------------------------------------
    def _build_orders_grid(self):
        box = QGroupBox("Orders")
        grid = QGridLayout(box)

        headers = ["Oorsprong", "Broker", "Asset Rollup", "Type", "Koop/Verkoop", "Aantal", "Prijs", "Fee"]
        for c, txt in enumerate(headers):
            grid.addWidget(QLabel(txt), 0, c, alignment=Qt.AlignLeft)

        # --- eerste order ---
        self.order1 = self._build_order_row(grid, row=1, side=1)

        # --- tweede order ---
        self.order2 = self._build_order_row(grid, row=3, side=2)

        for c in range(12):
            grid.setColumnMinimumWidth(c, 120)
            grid.setColumnStretch(c, 0)
        return box

    def _build_order_row(self, grid, row, side):
        cb_oorspr = SmartCombo() if side == 1 else None
        if cb_oorspr:
            cb_oorspr.set_items(["OPEN", "CLOSE", "ASSIGN", "EXPIRE", "DOORROL", "STOCKSPLIT", "EXERCISE"])

        broker = SmartCombo(); broker.set_items(self.brokers)
        rollup = SmartCombo(); rollup.set_items(self.asset_rollups)
        at = SmartCombo(); at.set_items(["aandeel", "optie", "sprinter"])
        ttype = SmartCombo(); ttype.set_items(["koop", "verkoop"])
        aantal = QLineEdit()
        prijs = QLineEdit()
        fee = QLineEdit()

        widgets = [cb_oorspr or QLabel(""), broker, rollup, at, ttype, aantal, prijs, fee]
        for c, w in enumerate(widgets):
            grid.addWidget(w, row, c)

        # --- Sprinter detail ---
        lbl_det, det = QLabel("asset_detail"), SmartCombo()
        det.set_items(self.sprinter_details)
        grid.addWidget(lbl_det, row - 1, 11)
        grid.addWidget(det, row, 11)
        lbl_det.setVisible(False); det.setVisible(False)

        # --- Optie velden ---
        lbl_exp, exp = QLabel("optie_exp_date"), QLineEdit()
        lbl_strk, strike = QLabel("optie_strike"), QLineEdit()
        lbl_cp, cp = QLabel("optie_call_put"), SmartCombo()
        exp.editingFinished.connect(lambda e=exp: self.auto_fill_year(e))
        cp.set_items(["call", "put"])

        grid.addWidget(lbl_exp, row - 1, 8);   grid.addWidget(exp, row, 8)
        grid.addWidget(lbl_strk, row - 1, 9);  grid.addWidget(strike, row, 9)
        grid.addWidget(lbl_cp, row - 1, 10);   grid.addWidget(cp, row, 10)

        for w in (lbl_exp, exp, lbl_strk, strike, lbl_cp, cp):
            w.setVisible(False)

        return dict(
            cb_oorsprong=cb_oorspr, broker=broker, asset_rollup=rollup,
            asset_type=at, trans_type=ttype, aantal=aantal,
            prijs=prijs, fee=fee,
            # sprinter
            lbl_detail=lbl_det, detail=det,
            # optie
            lbl_exp=lbl_exp, exp=exp,
            lbl_strike=lbl_strk, strike=strike,
            lbl_cp=lbl_cp, cp=cp
        )


    def _build_topbar(self):
        h = QHBoxLayout()
        btn_save = QPushButton("Opslaan")
        btn_save.clicked.connect(self.opslaan_orders)
        h.addWidget(btn_save)
        btn_reset = QPushButton("Reset")
        btn_reset.clicked.connect(self.reset_action)
        h.addWidget(btn_reset)
        h.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        h.addWidget(QLabel("Database:"))
        self.db_choice = QComboBox()
        self.db_choice.addItems(list(DB_MAP.keys()))
        self.db_choice.setCurrentText(DEFAULT_DB_NAME)
        self.db_choice.currentTextChanged.connect(self.apply_database_by_name)
        h.addWidget(self.db_choice)

        h.addSpacing(16)
        h.addWidget(QLabel("Filter:"))
        self.filter_q = QLineEdit()
        self.filter_q.setPlaceholderText("Zoek (broker/rollup/detail/uniek_id)")
        self.filter_q.returnPressed.connect(self.apply_filters)
        h.addWidget(self.filter_q)

        btn_clear = QPushButton("Filters wissen")
        btn_clear.clicked.connect(self.clear_filters)
        h.addWidget(btn_clear)
        return h

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
        self.db_choice.setStyleSheet(css)

    def _build_table(self):
        self.table = QTableView()
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)

        self.df = pd.DataFrame()
        self.model = PandasTableModel(self.df, self)

        # Sorting aanzetten
        self.table.setSortingEnabled(True)

        # Onthoud sorteerstate (default zoals in single-file)
        self.sort_col = "Id"
        self.sort_dir = "DESC"

        # Paging/lazy state
        self._loading_more = False
        self._no_more_records = False
        self._reset_seek()  # komt als methode verderop

        # Header-sort event koppelen
        header = self.table.horizontalHeader()
        header.sortIndicatorChanged.connect(self.on_header_sort_changed)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self.on_header_menu)

        # Scroll-event koppelen (voor lazy load)
        self.table.verticalScrollBar().valueChanged.connect(self.on_scroll)



        self.table.setModel(self.model)
        # koppel selectie → velden vullen
        self.table.selectionModel().selectionChanged.connect(self.on_table_select)

        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setMouseTracking(True)
        self.table.viewport().setAttribute(Qt.WA_Hover, True)
        self.table.setStyleSheet("""
        QTableView::item:hover { background-color: #E6F2FF; }
        QTableView::item:selected { background-color: #FFF2CC; color: #000000; }
        QTableView::item:selected:hover { background-color: #FFE08A; }
        QTableView::item:selected:!active { background-color: #FFF8D6; }
        """)
        return self.table

    # --------------------------------------------------------
    # Behavior
    # --------------------------------------------------------
    def _wire_dynamic(self):
        self.order1["asset_type"].currentTextChanged.connect(self.toggle_order1_fields)
        if self.order1["cb_oorsprong"]:
            self.order1["cb_oorsprong"].currentTextChanged.connect(self.toggle_order2_visibility)
        self.order2["asset_type"].currentTextChanged.connect(self.toggle_order2_fields)

# --- PLAATS DIT BINNEN class OrdersTab ---

    def _reset_seek(self):
        """Reset seek/paging state wanneer filters/sortering wijzigt of bij initial load."""
        self.seek_value = None
        self.seek_id = None
        self._no_more_records = False


    def _update_seek_from_df(self, df_raw):
        """Werk seek-value en -id bij aan de hand van de laatste rij uit de batch."""
        if df_raw is None or df_raw.empty:
            self.seek_value = None
            self.seek_id = None
            self._no_more_records = True
            return
        last = df_raw.iloc[-1]
        col = self.sort_col if self.sort_col in df_raw.columns else "Id"
        val = last[col]
        # numpy scalar → python scalar, voorkomt type-mismatch in parametrized queries
        try:
            import numpy as np
            if isinstance(val, np.generic):
                val = val.item()
        except Exception:
            pass
        self.seek_value = val
        self.seek_id = int(last["Id"])


    
    
    def toggle_order1_fields(self):
        at = self.order1["asset_type"].currentText()

        # Eerst alles verbergen
        for w in [self.order1["lbl_detail"], self.order1["detail"],
                self.order1["lbl_exp"], self.order1["exp"],
                self.order1["lbl_strike"], self.order1["strike"],
                self.order1["lbl_cp"], self.order1["cp"]]:
            w.setVisible(False)

        # Sprinter: toon detailvelden
        if at == "sprinter":
            for w in [self.order1["lbl_detail"], self.order1["detail"],
                    self.order1["lbl_exp"], self.order1["exp"],
                    self.order1["lbl_strike"], self.order1["strike"],
                    self.order1["lbl_cp"], self.order1["cp"]]:
                w.setVisible(True)

        # Optie: toon optievelden
        elif at == "optie":
            for w in [self.order1["lbl_exp"], self.order1["exp"],
                    self.order1["lbl_strike"], self.order1["strike"],
                    self.order1["lbl_cp"], self.order1["cp"]]:
                w.setVisible(True)


    def toggle_order2_fields(self):
        at = self.order2["asset_type"].currentText()

        # Eerst alles verbergen
        for w in [self.order2["lbl_detail"], self.order2["detail"],
                self.order2["lbl_exp"], self.order2["exp"],
                self.order2["lbl_strike"], self.order2["strike"],
                self.order2["lbl_cp"], self.order2["cp"]]:
            w.setVisible(False)

        # Sprinter: toon alleen sprintervelden
        if at == "sprinter":
            for w in [self.order2["lbl_detail"], self.order2["detail"],
                    self.order2["lbl_exp"], self.order2["exp"],
                    self.order2["lbl_strike"], self.order2["strike"],
                    self.order2["lbl_cp"], self.order2["cp"]]:
                w.setVisible(True)

        # Optie: toon optievelden
        elif at == "optie":
            for w in [self.order2["lbl_exp"], self.order2["exp"],
                    self.order2["lbl_strike"], self.order2["strike"],
                    self.order2["lbl_cp"], self.order2["cp"]]:
                w.setVisible(True)

    def toggle_order2_visibility(self):
        oorspr = self.order1["cb_oorsprong"].currentText() if self.order1["cb_oorsprong"] else ""
        visible = oorspr in ["DOORROL", "ASSIGN", "EXPIRE", "EXERCISE"]

        widgets = [
            "broker","asset_rollup","asset_type","trans_type","aantal","prijs","fee",
            "lbl_detail","detail","lbl_exp","exp","lbl_strike","strike","lbl_cp","cp"
        ]
        for key in widgets:
            self.order2[key].setVisible(visible)

        if visible:
            self.toggle_order2_fields()

    def on_header_menu(self, pos):
        header = self.table.horizontalHeader()
        section = header.logicalIndexAt(pos)
        try:
            colname = self.model._df.columns[section]
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
        if not act: return

        if act in (a_asc, a_desc):
            order = Qt.AscendingOrder if act == a_asc else Qt.DescendingOrder
            header.setSortIndicator(section, order)
            return

        if act == a_clear:
            self.col_filters.pop(colname, None)
            self.apply_filters()
            return

        if act == a_contains:
            text, ok = QInputDialog.getText(self, f"{colname} bevat", "Tekst:")
            if ok and text.strip():
                self.col_filters[colname] = {"contains": text.strip()}
                self.apply_filters()
            return

        if act == a_equals:
            text, ok = QInputDialog.getText(self, f"{colname} is precies", "Waarde:")
            if ok and text.strip():
                self.col_filters[colname] = {"eq": text.strip()}
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
        if colname in (self.col_filters or {}) and "in" in self.col_filters[colname]:
            pre = set(self.col_filters[colname]["in"])

        pop = ColumnFilterPopup(f"Filter: {colname}", values, pre_selected=pre, parent=self)
        pop.move(global_pos)
        pop.acceptedSelection.connect(lambda selected: self._apply_in_filter(colname, selected))
        pop.cleared.connect(lambda: self._clear_col_filter(colname))
        pop.show()

    def _apply_in_filter(self, colname: str, selected: set):
        if not selected:
            self.col_filters.pop(colname, None)
        else:
            self.col_filters[colname] = {"in": selected}
        self.apply_filters()

    def _clear_col_filter(self, colname: str):
        self.col_filters.pop(colname, None)
        self.apply_filters()


    def _show_order2(self, visible: bool):
        widgets = [
            "broker","asset_rollup","asset_type","trans_type","aantal","prijs","fee",
            "lbl_detail","detail","lbl_exp","exp","lbl_strike","strike","lbl_cp","cp"
        ]
        for key in widgets:
            self.order2[key].setVisible(visible)
        if visible:
            self.toggle_order2_fields()


    # --------------------------------------------------------
    # Logic: opslaan, filters, db switch
    # --------------------------------------------------------
    def opslaan_orders(self):
        from portefeuille_viewer.data.repository import parse_int_field, _parse_date
        
        # --- Strikte lijst-validatie: alleen waarden uit de combobox-lijsten toegestaan
        # Order 1
        if not self._validate_combo_in_list(self.order1["broker"], "Broker", allow_empty=False):
            return
        if not self._validate_combo_in_list(self.order1["asset_type"], "Type", allow_empty=False):
            return
        if not self._validate_combo_in_list(self.order1["trans_type"], "Koop/Verkoop", allow_empty=False):
            return

        at1 = self.order1["asset_type"].currentText()
        if at1 == "sprinter":
            # bij sprinter is asset_rollup optioneel in jouw validatie; detail verplicht als jij dat wilt
            if not self._validate_combo_in_list(self.order1["detail"], "Asset Detail", allow_empty=False):
                return
        else:
            # aandeel of optie → asset_rollup moet in lijst
            if not self._validate_combo_in_list(self.order1["asset_rollup"], "Asset Rollup", allow_empty=False):
                return

        if at1 == "optie":
            # call/put moet in lijst (je combo is al beperkt tot ["call","put"], maar we checken hard)
            if not self._validate_combo_in_list(self.order1["cp"], "Call/Put", allow_empty=False):
                return

        # Order 2 (alleen als zichtbaar/nodig)
        oorspr = self.order1["cb_oorsprong"].currentText() if self.order1["cb_oorsprong"] else ""
        tweede_nodig = oorspr in ["DOORROL","ASSIGN","EXPIRE","EXERCISE"]
        if tweede_nodig and self.order2["broker"].isVisible():
            if not self._validate_combo_in_list(self.order2["broker"], "Broker (regel 2)", allow_empty=False):
                return
            if not self._validate_combo_in_list(self.order2["asset_type"], "Type (regel 2)", allow_empty=False):
                return
            if not self._validate_combo_in_list(self.order2["trans_type"], "Koop/Verkoop (regel 2)", allow_empty=False):
                return

            at2 = self.order2["asset_type"].currentText()
            if at2 == "sprinter":
                if not self._validate_combo_in_list(self.order2["detail"], "Asset Detail (regel 2)", allow_empty=False):
                    return
            else:
                if not self._validate_combo_in_list(self.order2["asset_rollup"], "Asset Rollup (regel 2)", allow_empty=False):
                    return

            if at2 == "optie":
                if not self._validate_combo_in_list(self.order2["cp"], "Call/Put (regel 2)", allow_empty=False):
                    return

        
        # Validatie minimaal gelijk aan single-file
        if not self.order1["broker"].currentText():
            QMessageBox.critical(self, "Fout", "Broker (Order 1) verplicht"); return
        if not self.order1["asset_rollup"].currentText() and self.order1["asset_type"].currentText() != "sprinter":
            QMessageBox.critical(self, "Fout", "Asset Rollup (Order 1) verplicht"); return
        if not self.order1["trans_type"].currentText():
            QMessageBox.critical(self, "Fout", "Transactie Type (Order 1) verplicht"); return

        # 1) Form → dict
        at1 = self.order1["asset_type"].currentText()
        eerste_order = dict(
            transactie_oorsprong=self.order1["cb_oorsprong"].currentText() if self.order1["cb_oorsprong"] else None,
            broker=self.order1["broker"].currentText() or None,
            asset_rollup=self.order1["asset_rollup"].currentText() or None,
            asset_type=at1 or None,
            asset_detail=self.order1["detail"].currentText() if at1 == "sprinter" else None,
            transactie_type=self.order1["trans_type"].currentText() or None,
            aantal=parse_int_field(self.order1["aantal"].text()),
            transactie_prijs=float(self.order1["prijs"].text()) if self.order1["prijs"].text() else None,
            transactie_fee=-abs(float(self.order1["fee"].text())) if self.order1["fee"].text() else None,
            optie_strike=float(self.order1["strike"].text()) if (at1 == "optie" and self.order1["strike"].text()) else None,
            optie_exp_date=_parse_date(self.order1["exp"].text()) if (at1 == "optie" and self.order1["exp"].text()) else None,
            optie_call_put=self.order1["cp"].currentText() if at1 == "optie" else None,
        )

        tweede_order = None
        tweede_nodig = (self.order1["cb_oorsprong"].currentText() in ["DOORROL", "ASSIGN", "EXPIRE", "EXERCISE"]) \
            if self.order1["cb_oorsprong"] else False
        if tweede_nodig:
            at2 = self.order2["asset_type"].currentText()
            tweede_order = dict(
                transactie_oorsprong=self.order1["cb_oorsprong"].currentText(),
                broker=self.order2["broker"].currentText() or None,
                asset_rollup=self.order2["asset_rollup"].currentText() or None,
                asset_type=at2 or None,
                asset_detail=self.order2["detail"].currentText() if at2 == "sprinter" else None,
                transactie_type=self.order2["trans_type"].currentText() or None,
                aantal=parse_int_field(self.order2["aantal"].text()),
                transactie_prijs=float(self.order2["prijs"].text()) if self.order2["prijs"].text() else None,
                transactie_fee=-abs(float(self.order2["fee"].text())) if self.order2["fee"].text() else None,
                optie_strike=float(self.order2["strike"].text()) if (at2 == "optie" and self.order2["strike"].text()) else None,
                optie_exp_date=_parse_date(self.order2["exp"].text()) if (at2 == "optie" and self.order2["exp"].text()) else None,
                optie_call_put=self.order2["cp"].currentText() if at2 == "optie" else None,
            )

        # 2) Linking (oorsprong detail), idem als single-file
        from portefeuille_viewer.data.repository import build_uniek_id, is_pairable
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
        if self.EDIT_ID is not None:
            try:
                from portefeuille_viewer.data.repository import update_transactions_atomic
                data_update_1 = dict(eerste_order)
                data_update_2 = dict(tweede_order) if (self.EDIT_ID2 is not None and tweede_order is not None) else None
                update_transactions_atomic(
                    record_id1=int(self.EDIT_ID), data1=data_update_1,
                    record_id2=(int(self.EDIT_ID2) if self.EDIT_ID2 is not None else None), data2=data_update_2
                )
            except pyodbc.Error as e:
                QMessageBox.critical(self, "Databasefout", f"Kon niet updaten:\n{e}"); return

            msg = f"✅ Record {self.EDIT_ID} bijgewerkt"
            if self.EDIT_ID2 is not None and data_update_2 is not None:
                msg = f"✅ Records {self.EDIT_ID} en {self.EDIT_ID2} bijgewerkt"
            QMessageBox.information(self, "Succes", msg)

            # reset + refresh
            self.EDIT_ID = None; self.EDIT_ID2 = None
            self.load_initial_records()
            self.reset_form()
            self.ordersCommitted.emit()    # Live-tab verversen
            return

        # 4) INSERT-pad (ongewijzigd)
        try:
            from portefeuille_viewer.data.repository import get_next_order_id, get_next_order_item_no, insert_transaction
            new_order_id = get_next_order_id()
            eerste_order["order_id"] = new_order_id
            eerste_order["order_id_number"] = get_next_order_item_no(new_order_id)
            eerste_id = insert_transaction(eerste_order)

            tweede_id = None
            if tweede_order:
                tweede_order["order_id"] = new_order_id
                tweede_order["order_id_number"] = get_next_order_item_no(new_order_id)
                tweede_id = insert_transaction(tweede_order)

        except pyodbc.Error as e:
            QMessageBox.critical(self, "Databasefout", f"Kon niet opslaan:\n{e}"); return

        msg = f"✅ Order opgeslagen met Id {eerste_id}"
        if tweede_id:
            msg += f" (en gekoppeld aan {tweede_id})"
        QMessageBox.information(self, "Succes", msg)

        self.load_initial_records()
        self.reset_form()
        self.ordersCommitted.emit()


    def apply_database_by_name(self, name):
        import portefeuille_viewer.data.repository as repo
        try:
            repo.switch_database(name)  # ✅ correcte manier
        except Exception as e:
            QMessageBox.critical(self, "Database", f"Kan niet verbinden:\n{e}")
            return

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
        
        self.load_initial_records()
        self.dbChanged.emit()

    def apply_filters(self):
        q = self.filter_q.text().strip() if hasattr(self, "filter_q") else ""
        filters = {"q": q} if q else {}

        # kolomfilters omzetten naar generieke repo keys
        for col, spec in (self.col_filters or {}).items():
            if "in" in spec:
                filters[f"__in__{col}"] = list(spec["in"])
            if "contains" in spec:
                filters[f"__contains__{col}"] = spec["contains"]
            if "eq" in spec:
                filters[f"__eq__{col}"] = spec["eq"]
            if "date_on" in spec and spec["date_on"]:
                filters[f"__date_on__{col}"] = spec["date_on"]

        self.active_filters = filters
        self._reset_seek()
        self.load_initial_records()


    def clear_filters(self):
        if hasattr(self, "filter_q"):
            self.filter_q.clear()
        self.col_filters = {}
        self.active_filters = {}
        self._reset_seek()
        self.load_initial_records()



    def on_header_sort_changed(self, section, order):
        """Wanneer gebruiker op een kolom klikt: sorteerstate bijwerken + opnieuw laden."""
        try:
            colname = self.model._df.columns[section]
        except Exception:
            colname = "Id"
        self.sort_col = str(colname)
        from PySide6.QtCore import Qt
        self.sort_dir = "ASC" if order == Qt.AscendingOrder else "DESC"
        self._reset_seek()
        self.load_initial_records()


    def _format_df_for_table(self, df: pd.DataFrame) -> pd.DataFrame:
        TABLE_COLS = [
            "Id","datum","transactie_oorsprong","broker","asset_rollup","asset_type",
            "transactie_type","asset_detail","optie_exp_date","optie_strike","optie_call_put",
            "aantal","transactie_prijs","transactie_fee","uniek_id","transactie_oorsprong_detail"
        ]
        if df is None or df.empty:
            return pd.DataFrame(columns=TABLE_COLS)

        out = df.copy()

        # Zorg dat alle kolommen bestaan
        for c in TABLE_COLS:
            if c not in out.columns:
                out[c] = pd.NA

        # --- Datums naar string (leeg i.p.v. NaT)
        out["datum"] = pd.to_datetime(out["datum"], errors="coerce").dt.strftime("%d/%m/%Y")
        out["optie_exp_date"] = pd.to_datetime(out["optie_exp_date"], errors="coerce").dt.strftime("%d/%m/%Y")

        # --- Helpers voor EU-opmaak ---
        def fmt2(val):
            """2 decimalen, EU notatie (komma decimaal, punt duizendtallen)."""
            v = pd.to_numeric(val, errors="coerce")
            if pd.isna(v):
                return ""
            return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        def fmt_int(val):
            """Gehele aantallen met punt als duizendtal; leeg voor NaN/None."""
            v = pd.to_numeric(val, errors="coerce")
            if pd.isna(v):
                return ""
            # Wil je ook duizendtallen bij aantallen:
            return f"{int(v):,}".replace(",", ".")

        # --- Numerieke kolommen formatteren ---
        # Aantallen als integer
        out["aantal"] = out["aantal"].apply(fmt_int)

        # Prijs/fee/strike met 2 dec in EU notatie
        for c in ["optie_strike", "transactie_prijs", "transactie_fee"]:
            if c in out.columns:
                out[c] = out[c].apply(fmt2)

        # --- Tekstkolommen: leeg i.p.v. None/NaN ---
        for c in [
            "transactie_oorsprong","broker","asset_rollup","asset_type","transactie_type",
            "asset_detail","optie_call_put","uniek_id","transactie_oorsprong_detail"
        ]:
            if c in out.columns:
                out[c] = out[c].fillna("")

        # Dates na strftime kunnen 'NaT' → leeg
        out["datum"] = out["datum"].fillna("")
        out["optie_exp_date"] = out["optie_exp_date"].fillna("")

        # Laatste vangnet
        out = out.fillna("")

        return out[TABLE_COLS]





    def reset_form(self):
        for part in [self.order1, self.order2]:
            for k in ["cb_oorsprong", "broker", "asset_rollup", "asset_type",
                    "trans_type", "detail", "cp"]:
                if part.get(k) is not None:
                    part[k].setCurrentIndex(-1)
                    part[k].setEditText("") if hasattr(part[k], "setEditText") else None
            for k in ["aantal", "prijs", "fee", "exp", "strike"]:
                if part.get(k) is not None:
                    part[k].clear()
        self.toggle_order1_fields()
        self.toggle_order2_visibility()

    def on_table_select(self, selected, deselected):
        sel = self.table.selectionModel()
        if sel is None:
            return
        rows = sel.selectedRows()
        if not rows:
            return

        r = rows[0].row()
        rec = self.model.get_row(r) if hasattr(self.model, "get_row") else {}
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
                    self.fill_form_from_row(self.order2, r2, side=2)
                    self._show_order2(True)
                    return

            # geen tweede record → forceer weg
            self.EDIT_ID2 = None
            # leegmaken (optioneel maar netjes)
            for k in ["broker","asset_rollup","asset_type","trans_type","aantal","prijs","fee","exp","strike","cp","detail"]:
                w = self.order2.get(k)
                if hasattr(w, "setCurrentIndex"): w.setCurrentIndex(-1)
                if hasattr(w, "setEditText"): w.setEditText("")
                if hasattr(w, "clear"): w.clear()
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



    def reset_action(self):
        self.EDIT_ID = None
        self.EDIT_ID2 = None
        self.reset_form()

    # --------------------------------------------------------
    # Data loading
    # --------------------------------------------------------
    def load_initial_records(self):
        import portefeuille_viewer.data.repository as repo
        self._reset_seek()
        df_raw = repo.fetch_records_page(
            limit=200,  # of jouw PAGE_SIZE
            sort_col=self.sort_col,
            sort_dir=self.sort_dir,
            filters=getattr(self, "active_filters", None)
        )

        # Let op: jij had al een formatter; laat die intact
        df_view = self._format_df_for_table(df_raw)
        self.model.set_df(df_view)

        self._update_seek_from_df(df_raw)
        
    def load_more_records(self):
        if self._loading_more or self._no_more_records:
            return
        self._loading_more = True
        try:
            import portefeuille_viewer.data.repository as repo
            df_raw = repo.fetch_records_page(
                limit=200,  # zelfde PAGE_SIZE
                sort_col=self.sort_col,
                sort_dir=self.sort_dir,
                filters=getattr(self, "active_filters", None),
                seek_value=self.seek_value,
                seek_id=self.seek_id
            )
            if df_raw is None or df_raw.empty:
                self._no_more_records = True
                return

            df_view = self._format_df_for_table(df_raw)
            # Vereist dat je in stap B `append_df` aan je model hebt toegevoegd
            self.model.append_df(df_view)

            self._update_seek_from_df(df_raw)
        finally:
            self._loading_more = False


    def on_scroll(self, _value):
        sb = self.table.verticalScrollBar()
        # marge van ~50 pixels voor ‘bijna onderaan’
        if sb.value() >= sb.maximum() - 50:
            self.load_more_records()

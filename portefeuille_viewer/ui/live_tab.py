import time
import pandas as pd
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableView, QHeaderView, QMessageBox,
    QMenu, QInputDialog
)

from portefeuille_viewer.data.repository import (
    load_assetrollup_to_ib,
    load_equity_flows,
    load_sprinter_flows,
    load_sprinter_reference,
    coalesce_cols,
    load_closed_options_summary,   # ← NIEUW
    load_sprinter_fees
)
from portefeuille_viewer.ui.models import WidePerAssetModel, MultiColFilterProxy
from portefeuille_viewer.ui.filter_popup import ColumnFilterPopup

# ------------------------------------------------------------
# LiveViewTab
# ------------------------------------------------------------
class LiveViewTab(QWidget):
    """
    Tabblad dat de actuele portefeuille toont, inclusief koersen van IB.
    """
    def __init__(self, pricefeed, parent=None):
        super().__init__(parent)
        self.col_filters = {}  # {"KolomNaam": {"in": set([...])} | {"eq": v} | {"contains": "txt"}}



        self.feed_service = pricefeed

        # UI setup
        v = QVBoxLayout(self)
        # model alvast leeg initialiseren
        internal_cols = [
            "_ib_symbol","_ib_currency","_prim_exch",
            "_qty_eq","_avg_entry_eq","_hist_init_eq",
            "_qty_spr","_avg_entry_spr","_hist_realized_spr","_fund_w",
            "_premie_opties","_fees_opties"
        ]

        empty_df = pd.DataFrame(columns=WidePerAssetModel.COLS + internal_cols)
        self.model = WidePerAssetModel(empty_df, self)
        self.model._sprinters_df = pd.DataFrame()

        self.proxy = MultiColFilterProxy(self.model.COLS, self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)





        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setStyleSheet("""
        QTableView::item:hover { background-color: #E6F2FF; }
        QTableView::item:selected { background-color: #FFF2CC; color: #000; }
        QTableView::item:selected:hover { background-color: #FFE08A; }
        QTableView::item:selected:!active { background-color: #FFF8D6; }
        """)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setStretchLastSection(False)

        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self.on_header_menu)

        widths = {
            "Asset": 200, "Valuta": 70, "Koers": 110,
            "Aantal_eq": 110, "avg_buy_eq": 120, "Waarde_eq": 140,
            "Hist_eq": 150, "Open_eq": 150, "Totaal_eq": 150, "Fees_eq": 110,
            "Aantal_spr": 110, "avg_buy_spr": 120, "Waarde_spr": 140,
            "Hist_spr": 150, "Open_spr": 150, "Totaal_spr": 150, "Fees_spr": 110,"Premie_opties": 150,
            "Fees_opties": 110,
            "Totaal_portefeuille": 170
        }
        for i, name in enumerate(self.model.COLS):
            self.table.setColumnWidth(i, widths.get(name, 120))

        v.addWidget(self.table)

        # Label met totaal
        self.lbl_total = QLabel("Totale waarde (aandelen + sprinters): 0,00")
        f = self.lbl_total.font()
        f.setPointSize(12)
        f.setBold(True)
        self.lbl_total.setFont(f)
        v.addWidget(self.lbl_total)

        # Data uit database
        self.reload_from_snapshots()


        # IB feed connectie
        self.feed_service.priceUpdated.connect(self.on_ul_price)

        # # Eerste subscriptions
        # if not self.base_df.empty:
        #     subs = self.base_df[["_ib_symbol", "_ib_currency", "_prim_exch"]].dropna().drop_duplicates()
        #     tuples = list(subs.itertuples(index=False, name=None))
        #     if tuples:
        #         self.feed_service.ensure_subscriptions(tuples)

        # Timer voor totaal
        self._kpi_timer = QTimer(self)
        self._kpi_timer.timeout.connect(self._refresh_total)
        self._kpi_timer.start(700)

        # Sortering
        self.table.sortByColumn(self.model.COLS.index("Totaal_portefeuille"), Qt.DescendingOrder)


    def set_df(self, df: pd.DataFrame):
        self.beginResetModel()
        self._df = df.copy() if df is not None else pd.DataFrame(columns=self.COLS)
        self.endResetModel()




    def on_header_menu(self, pos):
        header = self.table.horizontalHeader()
        section = header.logicalIndexAt(pos)
        colname = self.model.COLS[section]

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
            self.col_filters.pop(colname, None)
            self._apply_proxy_filters()
            return

        if act == a_contains:
            text, ok = QInputDialog.getText(self, f"{colname} bevat", "Tekst:")
            if ok and text.strip():
                self.col_filters[colname] = {"contains": text.strip()}
                self._apply_proxy_filters()
            return

        if act == a_equals:
            text, ok = QInputDialog.getText(self, f"{colname} is precies", "Waarde:")
            if ok and text.strip():
                self.col_filters[colname] = {"eq": text.strip()}
                self._apply_proxy_filters()
            return

        if act == a_pick:
            # distincts komen hier uit het huidige dataframe (client-side)
            series = self.model._df[colname] if colname in self.model._df.columns else pd.Series(dtype=object)
            values = []
            blanks = False
            for x in series.drop_duplicates().tolist():
                if pd.isna(x) or str(x).strip() == "":
                    blanks = True
                else:
                    values.append(str(x))
            if blanks:
                values.insert(0, None)

            pre = set()
            if colname in self.col_filters and "in" in self.col_filters[colname]:
                pre = set(self.col_filters[colname]["in"])

            pop = ColumnFilterPopup(f"Filter: {colname}", values, pre_selected=pre, parent=self)
            pop.move(header.mapToGlobal(pos))
            pop.acceptedSelection.connect(lambda selected: self._apply_in_filter(colname, selected))
            pop.cleared.connect(lambda: self._clear_in_filter(colname))
            pop.show()

    def _apply_in_filter(self, colname: str, selected: set):
        if not selected:
            self.col_filters.pop(colname, None)
        else:
            self.col_filters[colname] = {"in": selected}
        self._apply_proxy_filters()

    def _clear_in_filter(self, colname: str):
        self.col_filters.pop(colname, None)
        self._apply_proxy_filters()

    def _apply_proxy_filters(self):
        # Zet alle UI-filters over op de proxy
        self.proxy.clearAll()
        for col, spec in (self.col_filters or {}).items():
            if "in" in spec:
                self.proxy.setIn(col, set(spec["in"]))
            if "eq" in spec:
                self.proxy.setEq(col, spec["eq"])
            if "contains" in spec:
                self.proxy.setContains(col, spec["contains"])


    # --------------------------------------------------------
    # Data
    # --------------------------------------------------------
    def _build_base_dataframe(self):
        import pandas as pd

        # ---------- 1) Load basis-datasets ----------
        try:    amap   = load_assetrollup_to_ib()
        except: amap   = pd.DataFrame()
        try:    eq     = load_equity_flows()
        except: eq     = pd.DataFrame()
        
        # --- NIEUW: sprinter flows + fees apart ophalen ---
        try:
            spr_fl = load_sprinter_flows()   # bevat hist_spr + avg_entry_spr + qty_spr + fund_w  
        except Exception:
            spr_fl = pd.DataFrame()

        self._sprinters_df = spr_fl.copy()
        if hasattr(self, "model"):
            self.model._sprinters_df = spr_fl.copy()
        

        # --- Fees voor sprinters ophalen (lichte query) ---
        try:
            spr_fees = load_sprinter_fees()
        except Exception:
            spr_fees = pd.DataFrame(columns=["_ar_key", "fee_spr"])

        # merge fees bij spr_fl
        if not spr_fees.empty:
            spr_fl = spr_fl.merge(spr_fees[["_ar_key", "fee_spr"]], on="_ar_key", how="left")
        else:
            spr_fl["fee_spr"] = 0.0

        print("DEBUG MERGE spr_fl:")
        print(spr_fl[["asset_rollup", "fee_spr"]].head(100))


        # --- overige tabellen ---
        try:    spr_rf = load_sprinter_reference()
        except: spr_rf = pd.DataFrame()
        try:    opt_closed = load_closed_options_summary()
        except: opt_closed = pd.DataFrame()

        
        try:    opt_closed = load_closed_options_summary()   # direct uit table
        except: opt_closed = pd.DataFrame()

        # ---------- 2) Normaliseer keys ----------
        def _prep(df: pd.DataFrame) -> pd.DataFrame:
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.copy()
            if "asset_rollup" in df.columns:
                df["asset_rollup"] = df["asset_rollup"].astype(str).str.strip()
                df["_ar_key"] = df["asset_rollup"].str.casefold()
            elif "_ar_key" not in df.columns:
                return pd.DataFrame()
            return df

        amap       = _prep(amap)
        eq         = _prep(eq)
        spr_fl     = _prep(spr_fl)
        spr_rf     = _prep(spr_rf)
        opt_closed = _prep(opt_closed)

        # ---------- 2b) Dedupliceren/aggregaties per _ar_key ----------
        # eq is in principe al per asset_rollup geaggregeerd, maar doe defensief:
        if not eq.empty:
            eq = eq.groupby("_ar_key", as_index=False).agg({
                "qty_eq": "sum",
                "avg_entry_eq": "mean",   # of gewogen, maar meestal 1 regel per _ar_key
                "hist_eq": "sum",
                "fee_eq": "sum"
            })

        # spr_fl kan meerdere regels per asset (meerdere sprinters) bevatten → aggregeren naar 1 regel
        if not spr_fl.empty:
            spr_tmp = spr_fl[["_ar_key","qty_spr","avg_entry_spr","hist_spr","fee_spr"]].copy()
            # gewicht voor gemiddelde = absolute hoeveelheid
            spr_tmp["w"] = spr_tmp["qty_spr"].abs()

            spr_agg = (
                spr_tmp
                .groupby("_ar_key", as_index=False)
                .apply(lambda g: pd.Series({
                    "qty_spr": g["qty_spr"].sum(),
                    "hist_spr": g["hist_spr"].sum(),
                    
                    "avg_entry_spr": 0.0 if g["w"].sum() == 0.0
                        else (g["avg_entry_spr"].mul(g["w"]).sum() / g["w"].sum())
                }))
                .reset_index(drop=True)
            )
            spr_fl = spr_agg
            # --- Fees per asset_rollup toevoegen na aggregatie ---
            try:
                spr_fees = load_sprinter_fees()
            except Exception:
                spr_fees = pd.DataFrame(columns=["_ar_key", "fee_spr"])

            if not spr_fees.empty:
                spr_fl = spr_fl.merge(spr_fees[["_ar_key", "fee_spr"]], on="_ar_key", how="left")
            else:
                spr_fl["fee_spr"] = 0.0

            print("✅ Sprinter fees na merge op rollup-niveau:")
            print(spr_fl.loc[spr_fl["_ar_key"] == "danone", ["_ar_key", "fee_spr"]])



        # opt_closed zou al per asset_rollup gegroepeerd zijn, maar haal zekerheidshalve duplicates weg
        if not opt_closed.empty:
            opt_closed = opt_closed.drop_duplicates(subset=["_ar_key"])




        if amap.empty and eq.empty and spr_fl.empty:
            QMessageBox.information(self, "Overzicht", "Geen data of mapping gevonden.")
            self.base_df = pd.DataFrame(columns=WidePerAssetModel.COLS + [
                "_ib_symbol","_ib_currency","_prim_exch",
                "_qty_eq","_avg_entry_eq","_hist_init_eq",
                "_qty_spr","_avg_entry_spr","_hist_realized_spr","_fund_w",
                "_premie_opties","_fees_opties"
            ])
            self.model.set_df(self.base_df)
            self._refresh_total()
            return

        # ---------- 3) Bouw assets-skelet ----------
        keys = []
        for d in (amap, eq, spr_fl):
            if not d.empty and "_ar_key" in d.columns:
                keys.append(d[["_ar_key"]])
        assets = pd.concat(keys, ignore_index=True).drop_duplicates() if keys else pd.DataFrame(columns=["_ar_key"])

        # Mapping-info (naam/symbool/valuta/beurs)
        if not amap.empty:
            cols = [c for c in ["_ar_key","asset_rollup","ib_symbol","ib_currency","prim_exchange"] if c in amap.columns]
            assets = assets.merge(amap[cols].drop_duplicates("_ar_key"), on="_ar_key", how="left")

        # Equity-aggregaten
        if not eq.empty:
            cols = [c for c in ["_ar_key","qty_eq","avg_entry_eq","hist_eq","fee_eq"] if c in eq.columns]
            assets = assets.merge(eq[cols], on="_ar_key", how="left")

        # Sprinter-aggregaten
        if not spr_fl.empty:
            cols = [c for c in ["_ar_key","qty_spr","avg_entry_spr","hist_spr","fee_spr"] if c in spr_fl.columns]
            assets = assets.merge(spr_fl[cols], on="_ar_key", how="left")

        # Sprinter reference (funding weight)
        if not spr_rf.empty and "fund_w" in spr_rf.columns:
            assets = assets.merge(spr_rf[["_ar_key","fund_w"]].drop_duplicates("_ar_key"), on="_ar_key", how="left")

        # ---------- 4) Gesloten/verlopen opties toevoegen ----------
        # voorkom _x/_y suffixen als er nog oude kolommen bestonden
        assets = assets.drop(columns=["premie_opties","fees_opties"], errors="ignore")

        if not opt_closed.empty:
            # kolomnamen defensief naar lowercase, dan alleen op _ar_key mergen
            opt_closed = opt_closed.rename(columns={c: str(c).lower() for c in opt_closed.columns})
            need = {"_ar_key","premie_opties","fees_opties"}
            if need.issubset(set(opt_closed.columns)):
                assets = assets.merge(
                    opt_closed[["_ar_key","premie_opties","fees_opties"]],
                    on="_ar_key", how="left"
                )

        # Zorg dat deze kolommen bestaan vóór casting
        for c in ("premie_opties","fees_opties"):
            if c not in assets.columns:
                assets[c] = 0.0

        # ---------- 5) Fill/typen afdwingen ----------
        # basis stringvelden
        for c in ["asset_rollup","ib_symbol","ib_currency","prim_exchange"]:
            if c not in assets.columns:
                assets[c] = None

        # numerieke velden
        num_cols = [
            "qty_eq","avg_entry_eq","hist_eq","fee_eq",
            "qty_spr","avg_entry_spr","hist_spr","fee_spr",
            "fund_w","premie_opties","fees_opties"
        ]
        for c in num_cols:
            if c not in assets.columns:
                assets[c] = 0.0
            assets[c] = pd.to_numeric(assets[c], errors="coerce").fillna(0.0)

        # fallback naam
        assets["asset_rollup"] = assets["asset_rollup"].fillna(assets["_ar_key"])

        # ---------- 6) Rijen bouwen ----------
        rows = []
        for r in assets.itertuples(index=False):
            asset_name = getattr(r, "asset_rollup")
            qty_eq     = float(getattr(r, "qty_eq", 0.0) or 0.0)
            avg_eq     = float(getattr(r, "avg_entry_eq", 0.0) or 0.0)
            hist_eq    = float(getattr(r, "hist_eq", 0.0) or 0.0)
            fee_eq     = float(getattr(r, "fee_eq", 0.0) or 0.0)

            qty_spr    = float(getattr(r, "qty_spr", 0.0) or 0.0)
            avg_spr    = float(getattr(r, "avg_entry_spr", 0.0) or 0.0)
            hist_spr   = float(getattr(r, "hist_spr", 0.0) or 0.0)
            fee_spr    = float(getattr(r, "fee_spr", 0.0) or 0.0)
            fund_w     = float(getattr(r, "fund_w", 0.0) or 0.0)

            premie_opt = float(getattr(r, "premie_opties", 0.0) or 0.0)
            fees_opt   = float(getattr(r, "fees_opties", 0.0) or 0.0)

            rows.append([
                # --- zichtbare kolommen (exact als WidePerAssetModel.COLS = 20) ---
                asset_name, getattr(r,"ib_currency", None), None,            # Asset, Valuta, Koers
                qty_eq,  avg_eq, 0.0,  hist_eq, 0.0,  hist_eq,  fee_eq,     # Aandelen-blok
                qty_spr, avg_spr, 0.0,  hist_spr, 0.0,  hist_spr, fee_spr,  # Sprinters-blok
                premie_opt, fees_opt,                                       # Opties historisch
                hist_eq + hist_spr + premie_opt,                                         # Totaal_portefeuille (excl. opties)

                # --- interne kolommen (12) ---
                getattr(r,"ib_symbol",None), getattr(r,"ib_currency",None), getattr(r,"prim_exchange",None),
                qty_eq, avg_eq, hist_eq,         # _qty/_avg/_hist_eq
                qty_spr, avg_spr, hist_spr,      # _qty/_avg/_hist_spr
                fund_w,                           # _fund_w
                premie_opt, fees_opt              # _premie_opties/_fees_opties
            ])

        internal_cols = [
            "_ib_symbol","_ib_currency","_prim_exch",
            "_qty_eq","_avg_entry_eq","_hist_init_eq",
            "_qty_spr","_avg_entry_spr","_hist_realized_spr","_fund_w",
            "_premie_opties","_fees_opties"
        ]

        if not rows:
            self.base_df = pd.DataFrame(columns=WidePerAssetModel.COLS + internal_cols)
        else:
            self.base_df = pd.DataFrame(rows, columns=WidePerAssetModel.COLS + internal_cols)

        # ---------- 7) Model & UI ----------
        if hasattr(self, "model"):
            self.model.set_df(self.base_df)
            self._refresh_total()




    # --------------------------------------------------------
    # Events
    # --------------------------------------------------------
    @Slot(str, str, float)
    def on_ul_price(self, ib_symbol: str, currency: str, price: float):
        """Realtime prijsupdate vanuit IB."""
        self.model.update_price(ib_symbol, currency, price)

    @Slot()
    def reload_from_db(self):
        """Wordt aangeroepen na opslaan of DB-switch."""
        self._build_base_dataframe()
        self.model.beginResetModel()
        self.model._df = self.base_df.copy()
        self.model.endResetModel()

        # Voeg cacheprijzen toe
        df_prices = self.feed_service.store.snapshot_df()
        if not df_prices.empty:
            merged = pd.merge(self.model._df, df_prices, on=["_ib_symbol", "_ib_currency"], how="left")
            self.model._df["Koers"] = merged["Koers_y"].combine_first(merged["Koers_x"])

        # Update op basis van cache
        snap = self.feed_service.store.snapshot()
        for (sym, cur), px in snap.items():
            self.model.update_price(sym, cur, px)

        # Nieuwe subscriptions
        if not self.base_df.empty:
            subs = self.base_df[["_ib_symbol", "_ib_currency", "_prim_exch"]].dropna().drop_duplicates()
            tuples = list(subs.itertuples(index=False, name=None))
            if tuples:
                self.feed_service.ensure_subscriptions(tuples)

    def _refresh_total(self):
        # Als lbl_total (nog) niet bestaat, gewoon terug
        if not hasattr(self, "lbl_total") or self.lbl_total is None:
            return

        total = self.model.total_value()
        self.lbl_total.setText(
            f"Totale waarde (aandelen + sprinters): {total:,.2f}"
            .replace(",", "X").replace(".", ",").replace("X", ".")
    )
        
    def reload_from_snapshots(self):
        """Herladen van model op basis van data in snapshot_store."""
        from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE

        df_eq = SNAPSHOT_STORE.open_aandelen
        df_spr = SNAPSHOT_STORE.open_sprinters
        df_opt = SNAPSHOT_STORE.open_opties

        if df_eq.empty:
            print("[LiveTab] Waarschuwing: geen equity data geladen")
            return

        # Normaliseer keys
        df_eq = df_eq.copy()
        df_eq["_ar_key"] = df_eq["asset_rollup"].str.casefold()
        df_spr["_ar_key"] = df_spr["asset_rollup"].str.casefold()
        df_opt["_ar_key"] = df_opt["asset_rollup"].str.casefold()

        # Merge dataframes op _ar_key
        df = df_eq.merge(df_spr, on="_ar_key", how="left", suffixes=("_eq", "_spr"))
        df = df.merge(df_opt, on="_ar_key", how="left")

        df["Asset"] = df["asset_rollup_eq"]
        df["Valuta"] = df["ib_currency"] if "ib_currency" in df.columns else ""
        df["Koers"] = df.get("current_price", 0.0)

        df["Aantal_eq"] = df.get("qty_eq", 0.0)
        df["avg_buy_eq"] = df.get("avg_entry_eq", 0.0)
        df["Hist_eq"] = df.get("hist_eq", 0.0)
        df["Fees_eq"] = df.get("fee_eq", 0.0)

        df["Aantal_spr"] = df.get("qty_spr", 0.0)
        df["avg_buy_spr"] = df.get("avg_entry_spr", 0.0)
        df["Hist_spr"] = df.get("hist_spr", 0.0)
        df["Fees_spr"] = df.get("fee_spr", 0.0)

        df["Premie_opties"] = df.get("premie_opties", 0.0)
        df["Fees_opties"] = df.get("fees_opties", 0.0)

        df = df.fillna(0.0)

        df["Totaal_portefeuille"] = df["Hist_eq"] + df["Hist_spr"] + df["Premie_opties"]

        df = df[[
            "Asset", "Valuta", "Koers",
            "Aantal_eq", "avg_buy_eq", "Hist_eq", "Fees_eq",
            "Aantal_spr", "avg_buy_spr", "Hist_spr", "Fees_spr",
            "Premie_opties", "Fees_opties", "Totaal_portefeuille"
        ]]

        self.model.set_df(df)
        self._refresh_total()
        print("✅ LiveViewTab succesvol herladen uit SNAPSHOT_STORE")





import pandas as pd
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor, QBrush


# ------------------------------------------------------------
# PandasTableModel — generiek voor Orders-tab
# ------------------------------------------------------------
class PandasTableModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self._df = df.copy() if df is not None else pd.DataFrame()

    def rowCount(self, parent=QModelIndex()):
        return 0 if self._df is None else len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return 0 if self._df is None else len(self._df.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self._df is None:
            return None
        val = self._df.iat[index.row(), index.column()]

        if role == Qt.DisplayRole:
            # Belangrijk: None/NaN/NaT moeten leeg tonen
            return "" if pd.isna(val) else str(val)

        if role == Qt.TextAlignmentRole:
            return (Qt.AlignRight | Qt.AlignVCenter) if isinstance(val, (float, int)) else (Qt.AlignLeft | Qt.AlignVCenter)

        return None



    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or self._df is None:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)

    def set_df(self, df: pd.DataFrame):
        self.beginResetModel()
        self._df = df.copy() if df is not None else pd.DataFrame()
        self.endResetModel()

    def get_row(self, row_idx: int) -> dict:
        """Geef de geselecteerde rij als dict terug, of {} als out-of-range."""
        if self._df is None or row_idx < 0 or row_idx >= len(self._df):
            return {}
        return self._df.iloc[row_idx].to_dict()
    def append_df(self, df_more: pd.DataFrame):
        if df_more is None or df_more.empty:
            return
        start = len(self._df)
        self.beginInsertRows(QModelIndex(), start, start + len(df_more) - 1)
        self._df = pd.concat([self._df, df_more], ignore_index=True)
        self.endInsertRows()



# ------------------------------------------------------------
# WidePerAssetModel — speciaal voor portefeuille-overzicht
# ------------------------------------------------------------
class WidePerAssetModel(QAbstractTableModel):
    """
    Toon gecombineerde posities (aandelen + sprinters) per asset.
    Bevat kolommen met actuele prijzen, P/L, fees, etc.
    """

    COLS = [
        "Asset","Valuta","Koers",
        "Aantal_eq","avg_buy_eq","Waarde_eq","Hist_eq","Open_eq","Totaal_eq","Fees_eq",
        "Aantal_spr","avg_buy_spr","Waarde_spr","Hist_spr","Open_spr","Totaal_spr","Fees_spr",
        "Premie_opties","Fees_opties",              # ← toegevoegd
        "Totaal_portefeuille"
    ]


    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self._df = df.copy() if df is not None else pd.DataFrame(columns=self.COLS)

    # ---------------------------------------------
    # Qt model API
    # ---------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.COLS[section]
        return str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self._df is None:
            return None
        col = self.COLS[index.column()]
        row = self._df.iloc[index.row()]
        val = row.get(col, None)
        # val = self._df.iloc[index.row()][col]

        if role == Qt.DisplayRole:
            # leeg tonen bij None/NaN/NaT
            if pd.isna(val):
                return ""
            # eenvoudige EU-opmaak: getallen met 2 dec., aantallen als int
            if col in ("Aantal_eq", "Aantal_spr"):
                try:
                    n = int(round(float(val)))
                    return f"{n:,}".replace(",", ".")
                except Exception:
                    return str(val)
            if isinstance(val, (int, float)):
                try:
                    s = f"{float(val):,.2f}"
                    return s.replace(",", "X").replace(".", ",").replace("X", ".")
                except Exception:
                    return str(val)
            return str(val)

        if role == Qt.TextAlignmentRole:
            return (Qt.AlignRight | Qt.AlignVCenter) if isinstance(val, (float, int)) else (Qt.AlignLeft | Qt.AlignVCenter)

        if role == Qt.ForegroundRole and col == "Totaal_portefeuille":
            v = self._df.iloc[index.row()]["Totaal_portefeuille"]
            if isinstance(v, (float, int)):
                return QBrush(QColor("darkgreen") if v >= 0 else QColor("red"))

        return None

    def set_df(self, df: pd.DataFrame):
        """Vervang de onderliggende dataframe en reset het model netjes."""
        self.beginResetModel()
        self._df = df.copy() if df is not None else pd.DataFrame(columns=self.COLS)
        self.endResetModel()




    # ---------------------------------------------
    # Business logic
    # ---------------------------------------------
    def update_price(self, ib_symbol: str, currency: str, px: float):
        """Wordt aangeroepen bij prijsupdate vanuit IB feed."""
        if self._df.empty:
            return
        mask = (self._df["_ib_symbol"] == ib_symbol) & (self._df["_ib_currency"] == currency)
        idx = self._df.index[mask]
        if len(idx) == 0:
            return
        i = idx[0]
        self._df.at[i, "Koers"] = px
        self._recalc_row(i)
        top_left = self.index(i, 0)
        bottom_right = self.index(i, len(self.COLS) - 1)
        self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole])

    def _recalc_row(self, i: int):
        """Herberekent alle velden voor één asset."""
        r = self._df.iloc[i]
        
        # if not hasattr(self, "_sprinters_df"):
        #     print("⚠️  _sprinters_df ontbreekt in model")
        # elif self._sprinters_df.empty:
        #     print("⚠️  _sprinters_df is leeg")
        # else:
        #     print("✅ _sprinters_df geladen met", len(self._sprinters_df), "regels")
        #     print(self._sprinters_df.head(5))



        px = float(r["Koers"] or 0.0)

        # === Aandelen ===
        qty_eq   = float(r["_qty_eq"] or 0.0)
        avg_eq   = float(r["_avg_entry_eq"] or 0.0)
        hist_eq  = float(r["_hist_init_eq"] or 0.0)
        waarde_eq = qty_eq * px
        open_eq   = (px - avg_eq) * qty_eq
        total_eq  = hist_eq + open_eq

        # === Sprinters ===
        # Zoek alle sprinters (asset_detail) die bij deze asset_rollup horen
        asset_name = str(r["Asset"]).strip().lower()
        waarde_spr = open_spr = total_spr = hist_spr = 0.0

        if hasattr(self, "_sprinters_df") and not self._sprinters_df.empty:
            subset = self._sprinters_df[
                self._sprinters_df["asset_rollup"].str.lower() == asset_name
            ]
            if not subset.empty:
                # Bereken per sprinter met eigen funding
                subset = subset.copy()
                subset["waarde_i"] = subset["qty_spr"] * (px - subset["fund_w"])
                subset["open_i"]   = ((px - subset["fund_w"]) - subset["avg_entry_spr"]) * subset["qty_spr"]
                subset["total_i"]  = subset["hist_spr"] + subset["open_i"]

                waarde_spr = subset["waarde_i"].sum()
                open_spr   = subset["open_i"].sum()
                total_spr  = subset["total_i"].sum()
                hist_spr   = subset["hist_spr"].sum()

        premie_opt = float(r.get("_premie_opties", 0.0))
        fees_opt   = float(r.get("_fees_opties", 0.0))

        # === Totaal portefeuille ===
        totaal_port = total_eq + total_spr + premie_opt

        # === Waarden terugschrijven ===
        self._df.at[i, "Waarde_eq"] = waarde_eq
        self._df.at[i, "Open_eq"]   = open_eq
        self._df.at[i, "Totaal_eq"] = total_eq

        self._df.at[i, "Waarde_spr"] = waarde_spr
        self._df.at[i, "Open_spr"]   = open_spr
        self._df.at[i, "Totaal_spr"] = total_spr
        self._df.at[i, "Hist_spr"]   = hist_spr

        self._df.at[i, "Premie_opties"] = premie_opt
        self._df.at[i, "Fees_opties"]   = fees_opt
        self._df.at[i, "Totaal_portefeuille"] = totaal_port

        


    def total_value(self) -> float:
        """Som van Totaal_portefeuille."""
        if self._df.empty or "Totaal_portefeuille" not in self._df.columns:
            return 0.0
        return float(self._df["Totaal_portefeuille"].sum())

from PySide6.QtCore import QSortFilterProxyModel, Qt

class MultiColFilterProxy(QSortFilterProxyModel):
    """
    Houdt per kolom een set 'in'-waardes, 'eq' of 'contains' filter bij.
    Werkt bovenop WidePerAssetModel (client-side filtering).
    """
    def __init__(self, col_names: list[str], parent=None):
        super().__init__(parent)
        self._cols = list(col_names)
        self._in = {}         # {colname: set([...])}
        self._eq = {}         # {colname: value}
        self._contains = {}   # {colname: "substr"}

        self.setDynamicSortFilter(True)

    def clearAll(self):
        self._in.clear(); self._eq.clear(); self._contains.clear()
        self.invalidateFilter()

    def clearFor(self, col: str):
        self._in.pop(col, None); self._eq.pop(col, None); self._contains.pop(col, None)
        self.invalidateFilter()

    def setIn(self, col: str, values: set):
        self._in[col] = set(values or [])
        self.invalidateFilter()

    def setEq(self, col: str, value):
        self._eq[col] = value
        self.invalidateFilter()

    def setContains(self, col: str, substr: str):
        self._contains[col] = (substr or "").strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        sm = self.sourceModel()
        if sm is None:
            return True
        # lees rechtstreeks uit model._df voor performance en betrouwbaarheid
        try:
            df = sm._df
        except Exception:
            return True

        for col, want in self._in.items():
            if want:
                cidx = self._cols.index(col)
                val = df.iloc[source_row][col]
                # None/"" worden in set gerepresenteerd als None
                if pd.isna(val) or str(val).strip() == "":
                    v = None
                else:
                    v = str(val)
                if v not in want:
                    return False

        for col, v in self._eq.items():
            val = df.iloc[source_row][col]
            if pd.isna(val) or str(val) != str(v):
                return False

        for col, substr in self._contains.items():
            if substr:
                val = str(df.iloc[source_row][col])
                if substr.lower() not in val.lower():
                    return False

        return True


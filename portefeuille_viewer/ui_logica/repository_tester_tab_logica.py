import json
from PySide6.QtWidgets import QWidget, QHeaderView, QMessageBox, QFileDialog
from PySide6.QtCore import Slot, QSortFilterProxyModel, Qt
from portefeuille_viewer.ui.repository_tester_ui import Ui_Form
from portefeuille_viewer.ui.models import PolarsTableModel
import polars as pl
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE

class RepositoryTesterTab(QWidget):
    """
    Snapshot tester tab gekoppeld aan repository_tester_ui.py
    Dropdown toont snapshots uit SNAPSHOT_STORE, selectie toont DataFrame in tableview.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_Form()
        self.ui.setupUi(self)
        # self.ui.btnExportExcel.clicked.connect(self.on_btnExportExcel_clicked)
        self.ui.tableView.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.ui.tableView.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # Populate combobox
        self._populate_selector()
        self.ui.comboBox.currentIndexChanged.connect(self._on_selection_changed)
        self._show_placeholder()

    @Slot()
    def on_btnExportExcel_clicked(self):
        """Exporteer de huidige zichtbare tabel naar Excel, met snapshotnaam in bestandsnaam."""
        try:
            df = self.model._df
            if df is None or df.is_empty():
                QMessageBox.warning(self, "Exporteren mislukt", "Geen data om te exporteren.")
                return
            pdf = df.to_pandas()
            # Gebruik de huidige snapshotnaam voor het bestand
            snapshot_name = getattr(self, "current_snapshot_key", "snapshot")
            fname, _ = QFileDialog.getSaveFileName(
                self,
                "Opslaan als Excel",
                f"{snapshot_name}.xlsx",
                "Excel Files (*.xlsx)"
            )
            if fname:
                pdf.to_excel(fname, index=False)
                QMessageBox.information(self, "Export geslaagd", f"Snapshot succesvol opgeslagen als:\n{fname}")
        except Exception as e:
            QMessageBox.critical(self, "Exporteren mislukt", f"Fout bij exporteren:\n{e}")




    def _populate_selector(self):
        self.ui.comboBox.clear()
        self.ui.comboBox.addItem("-- Kies snapshot --")
        keys = []
        for k, v in vars(SNAPSHOT_STORE).items():
            if k.startswith('_'):
                continue
            if v is None or isinstance(v, (pl.DataFrame,dict)):
                keys.append(k)
        keys.sort()
        for k in keys:
            self.ui.comboBox.addItem(k)

    @Slot(int)
    def _on_selection_changed(self, index):
        if index <= 0:
            self._show_placeholder()
            return
        key = self.ui.comboBox.itemText(index)
        self._display_snapshot_key(key)

    def _show_placeholder(self):
        # Optioneel: label toevoegen in UI voor status
        df = pl.DataFrame({})
        self._set_table_model(df)

    def _display_snapshot_key(self, key):
        def _to_cell(v):
            if v is None or isinstance(v, (str, int, float, bool)):
                return v
            try:
                return json.dumps(v, ensure_ascii=False, default=str)
            except Exception:
                return str(v)

        data = getattr(SNAPSHOT_STORE, key, None)
        self.current_snapshot_key = key
        # Lege DataFrame als data None is
        if data is None:
            df = pl.DataFrame({})
            self._set_table_model(df)
            return

        # Dict met tuple keys
        if isinstance(data, dict) and data:
            
            # Converteer keys die lijsten zijn naar tuples
            keys = [tuple(k) if isinstance(k, (list, tuple)) else (k,) for k in data.keys()]
            # Bepaal kolomnamen
            max_len = max(len(k) for k in keys)
            colnames = [f"key_{i+1}" for i in range(max_len)]
            rows = []
            for k, v in zip(keys, data.values()):
                # Vul aan met None als de tuple korter is
                k_full = k + (None,) * (max_len - len(k))
                row = dict(zip(colnames, [_to_cell(x) for x in k_full]))
                row["value"] = _to_cell(v)
                rows.append(row)
            df = pl.DataFrame(rows)
        # Dict met niet-tuple keys
        elif isinstance(data, dict):
            df = pl.DataFrame([{"key": _to_cell(k), "value": _to_cell(v)} for k, v in data.items()])
        # Al een DataFrame
        elif isinstance(data, pl.DataFrame):
            df = data
        else:
            df = pl.DataFrame({})

        self._set_table_model(df)

    def _set_table_model(self, df):
        if df is None:
            df = pl.DataFrame({})
        self.model = PolarsTableModel(df, self)
        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setSortRole(Qt.UserRole)
        self.ui.tableView.setModel(self.proxy_model)

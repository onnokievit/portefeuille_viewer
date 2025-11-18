from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QCheckBox, QListWidget,
    QListWidgetItem, QDialogButtonBox, QWidget, QMenu, QInputDialog, QMessageBox
)
# test random comment voor github online test
class ColumnFilterPopup(QDialog):
    acceptedSelection = Signal(set)  # set met gekozen waarden (kan None bevatten)
    cleared = Signal()

    def __init__(self, title: str, values: list, pre_selected: set | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() | Qt.Popup)
        self.resize(260, 340)

        self._all_values = values[:] if values else []
        self._pre = set(pre_selected or set())

        lay = QVBoxLayout(self)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Zoek...")
        lay.addWidget(self.search)

        self.chk_all = QCheckBox("(Alles selecteren)")
        lay.addWidget(self.chk_all)
        self.chk_all.setTristate(True)   # optioneel: laat 'gedeeltelijk geselecteerd' zien

        self.list = QListWidget(self)
        self.list.setSelectionMode(QListWidget.NoSelection)
        self.list.setStyleSheet("QListWidget::item{padding:2px 6px;}")

        lay.addWidget(self.list, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_clear = btns.addButton("Wissen", QDialogButtonBox.ActionRole)
        lay.addWidget(btns)

        self._rebuild_items()

        self.list.itemClicked.connect(self._toggle_clicked_item)     # ← nieuw
        self.list.itemActivated.connect(self._toggle_clicked_item)   # ← nieuw (enter/dubbelklik)


        self.search.textChanged.connect(self._apply_filter_text)
        self.chk_all.toggled.connect(self._toggle_all)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        self.btn_clear.clicked.connect(self._on_clear)

    def _label_for(self, v): return "(Lege regels)" if v in (None, "") else str(v)

    def _rebuild_items(self):
        self.list.clear()
        # (Lege regels) eerst
        items = []
        if any(v in (None, "") for v in self._all_values):
            items.append(None)
        items.extend(sorted([v for v in self._all_values if v not in (None, "")], key=lambda x: str(x).lower()))

        for v in items:
            it = QListWidgetItem(self._label_for(v))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            checked = (v in self._pre) if self._pre else True
            it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            it.setData(Qt.UserRole, v)
            self.list.addItem(it)

        # Update de status van de "Alles selecteren"-checkbox
        self._update_all_checkbox()

    def _toggle_all(self, _state):
        check = Qt.Checked if self.chk_all.isChecked() else Qt.Unchecked
        self.list.blockSignals(True)  # Blokkeer signalen om conflicten te voorkomen
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(check)
        self.list.blockSignals(False)  # Heractiveer signalen

    def _apply_filter_text(self, text: str):
        t = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(t not in it.text().lower() if t else False)

    def _toggle_clicked_item(self, item):
        """Klik op de hele rij (niet alleen het checkboxvakje) toggelt de checkstate."""
        if not (item.flags() & Qt.ItemIsUserCheckable):
            return
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

        self._extracted_from__update_all_checkbox_8()

    def _on_accept(self):
        selected = set()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.isHidden(): 
                continue
            if it.checkState() == Qt.Checked:
                selected.add(it.data(Qt.UserRole))
        self.acceptedSelection.emit(selected)
        self.accept()

    def _on_clear(self):
        self.cleared.emit()
        self.accept()

    def _update_all_checkbox(self):
        self._extracted_from__update_all_checkbox_8()

    # TODO Rename this here and in `_toggle_clicked_item` and `_update_all_checkbox`
    def _extracted_from__update_all_checkbox_8(self):
        total = self.list.count()
        checked = sum(
            self.list.item(i).checkState() == Qt.Checked for i in range(total)
        )
        self._extracted_from__update_all_checkbox_11(checked, total)

    # TODO Rename this here and in `_toggle_clicked_item` and `_update_all_checkbox`
    def _extracted_from__update_all_checkbox_11(self, checked, total):
        self.chk_all.blockSignals(True)
        if checked == 0:
            self.chk_all.setCheckState(Qt.Unchecked)
        elif checked == total:
            self.chk_all.setCheckState(Qt.Checked)
        else:
            self.chk_all.setCheckState(Qt.PartiallyChecked)
        self.chk_all.blockSignals(False)


class HeaderFilterMenuMixin:
    """
    Vereist in de host-widget:
    - self.tableView: QTableView
    - self._table_model: het model met een ._df attribuut (pandas DataFrame)
    - self._col_filters: dict met actieve kolomfilters
    - self.apply_filters(): methode die filters toepast en de tabel herlaadt
    - self._load_initial_records(): (optioneel) methode om data opnieuw te laden
    """    # Je kunt de naam wijzigen naar orders_tab_methoden.py als je wilt, maar conventioneel is Widget of View gebruikelijk voor UI-klassen.
    def on_header_menu(self, pos):
        # print("Header menu op aangeroepen, positie:", pos)
        header = self.tableView.horizontalHeader()
        section = header.logicalIndexAt(pos)
        try:
            colname = self._table_model._df.columns[section]
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
    
    def _apply_in_filter(self, colname, selected):
        if not selected:
            self._col_filters.pop(colname, None)
        else:
            self._col_filters[colname] = {"in": selected}
        self._load_initial_records()
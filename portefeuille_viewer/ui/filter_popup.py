from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QCheckBox, QListWidget,
    QListWidgetItem, QDialogButtonBox, QWidget
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

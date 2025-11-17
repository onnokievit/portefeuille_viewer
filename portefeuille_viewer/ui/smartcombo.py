import contextlib
from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QComboBox, QCompleter, QMessageBox

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
        if obj is self.lineEdit() and event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter):
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

    def reset(self):
        """Reset combo to empty/editable state and ensure completer is attached to the current model."""
        try:
            self.blockSignals(True)
            self.completer.setModel(self.model())
            self.setCurrentIndex(-1)
            if self.isEditable():
                self.setEditText("")
            with contextlib.suppress(Exception):
                self.lineEdit().deselect()
        finally:
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
        text = (self.currentText() or "").strip()
        if not text:
            return True
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

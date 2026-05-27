from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import QComboBox, QLabel, QWidget


def _normalize_text(value) -> str:
    return str(value or "").strip()


class CheckableFilterComboController:
    """Small reusable controller for an include-list combobox.

    All options are checked by default. Unchecking one or more options excludes
    those values from the result set.
    """

    def __init__(
        self,
        owner: QWidget,
        combo: QComboBox,
        *,
        all_label: str,
        item_label: str,
        label: QLabel | None = None,
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        self.owner = owner
        self.combo = combo
        self.label = label
        self.all_label = all_label
        self.item_label = item_label
        self.on_changed = on_changed
        self._syncing = False
        self._commit_pending = False
        self._known_values: list[str] = []
        self._selected_values: set[str] | None = None
        self._selection_initialized = False

        self.combo.setEditable(True)
        if self.combo.lineEdit() is not None:
            self.combo.lineEdit().setReadOnly(True)
            self.combo.lineEdit().setFocusPolicy(Qt.NoFocus)
        if self.label is not None:
            self.label.setText(f"{self.item_label}:")
        self.combo.view().pressed.connect(self._on_item_pressed)
        self.combo.model().itemChanged.connect(self._on_item_changed)

    def set_options(self, values: Iterable[str]) -> None:
        clean_values = sorted(
            {_normalize_text(value) for value in values if _normalize_text(value)},
            key=str.lower,
        )
        previous = self._selected_values
        previous_was_all = (
            not self._selection_initialized
            or previous is None
            or (bool(self._known_values) and set(previous) == set(self._known_values))
        )
        if previous_was_all:
            selected = set(clean_values)
        else:
            selected = {value for value in previous if value in clean_values}

        self._known_values = clean_values
        self._selected_values = selected
        self._selection_initialized = True
        self._syncing = True
        try:
            self.combo.clear()
            all_item = QStandardItem(self.all_label)
            all_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            all_item.setCheckState(Qt.Checked if self._is_all_selected(selected) else Qt.Unchecked)
            self.combo.model().appendRow(all_item)
            for value in clean_values:
                item = QStandardItem(value)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if value in selected else Qt.Unchecked)
                self.combo.model().appendRow(item)
        finally:
            self._syncing = False
        self._update_text()

    def selected_values(self) -> list[str] | None:
        if self._is_all_selected(self._selected_values):
            return None
        return sorted(self._selected_values or set(), key=str.lower)

    def set_selected_values(self, values: Iterable[str] | None) -> None:
        if values is None:
            self._selected_values = set(self._known_values)
        else:
            wanted = {_normalize_text(value) for value in values if _normalize_text(value)}
            self._selected_values = {value for value in wanted if value in self._known_values} if self._known_values else wanted
        self._selection_initialized = True
        self._apply_selection_to_model()

    def set_all_selected(self) -> None:
        self._selected_values = set(self._known_values)
        self._selection_initialized = True
        self._apply_selection_to_model()
        self._update_text()

    def _is_all_selected(self, selected: set[str] | None) -> bool:
        return set(self._known_values) == set(selected or set())

    def _on_item_pressed(self, index) -> None:
        if self._syncing:
            return
        item = self.combo.model().itemFromIndex(index)
        if item is None:
            return
        if index.row() == 0:
            check_all = item.checkState() != Qt.Checked
            self._selected_values = set(self._known_values) if check_all else set()
        else:
            selected = set(self._selected_values or set())
            value = _normalize_text(item.text())
            if value in selected:
                selected.remove(value)
            elif value:
                selected.add(value)
            self._selected_values = selected
        self._apply_selection_to_model()
        self._schedule_commit()

    def _on_item_changed(self, _item: QStandardItem) -> None:
        if self._syncing:
            return
        self._schedule_commit()

    def _apply_selection_to_model(self) -> None:
        selected = set(self._selected_values or set())
        self._syncing = True
        try:
            model = self.combo.model()
            for row in range(model.rowCount()):
                item = model.item(row)
                if item is None:
                    continue
                if row == 0:
                    item.setCheckState(Qt.Checked if self._is_all_selected(selected) else Qt.Unchecked)
                else:
                    item.setCheckState(Qt.Checked if _normalize_text(item.text()) in selected else Qt.Unchecked)
        finally:
            self._syncing = False
        self._update_text()

    def _schedule_commit(self) -> None:
        if self._commit_pending:
            return
        self._commit_pending = True
        QTimer.singleShot(0, self._commit_selection)

    def _commit_selection(self) -> None:
        self._commit_pending = False
        self._update_text()
        if self.on_changed is not None:
            self.on_changed()

    def _update_text(self) -> None:
        selected = set(self._selected_values or set())
        total = len(self._known_values)
        count = len(selected)
        if total == 0 or count == total:
            text = self.all_label
        elif count == 0:
            text = f"Geen {self.item_label.lower()}"
        elif total - count <= 2:
            excluded = total - count
            text = f"excl. {excluded} {self.item_label.lower()}"
        elif count <= 2:
            text = ", ".join(sorted(selected, key=str.lower))
        else:
            text = f"{count} {self.item_label.lower()}"
        self.combo.setCurrentText(text)

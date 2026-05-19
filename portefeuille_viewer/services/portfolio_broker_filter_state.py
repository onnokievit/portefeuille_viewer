from __future__ import annotations

from PySide6.QtCore import QObject, Signal


def normalize_broker(value) -> str:
    return str(value or "").strip().lower()


class PortfolioBrokerFilterState(QObject):
    changed = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self._selected: list[str] = []

    def selected(self) -> list[str]:
        return list(self._selected)

    def selected_set(self) -> set[str] | None:
        selected = {normalize_broker(v) for v in self._selected if normalize_broker(v)}
        return selected or None

    def set_selected(self, brokers: list[str] | set[str] | tuple[str, ...] | None) -> None:
        cleaned = sorted({normalize_broker(v) for v in (brokers or []) if normalize_broker(v)})
        if cleaned == self._selected:
            return
        self._selected = cleaned
        self.changed.emit(list(self._selected))

    def clear(self) -> None:
        self.set_selected([])


PORTFOLIO_BROKER_FILTER_STATE = PortfolioBrokerFilterState()

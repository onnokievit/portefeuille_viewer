"""Live diagnostics for requested streams, receipts and selected prices."""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
)


STATUSES = {"waiting": "Wacht op beurt", "requested": "Aangevraagd",
            "receiving": "Ontvangt data", "quiet": "Geen recente data",
            "rejected": "Geweigerd", "retry": "Herstel gepland", "closed": "Markt gesloten"}


def stamp(value):
    return time.strftime("%d-%m %H:%M:%S", time.localtime(value)) if value else "—"


class SubscriptionsTab(QWidget):
    HEADERS = ["Instrument", "Type", "Valuta", "Beurs", "Contract-ID", "Request-ID",
               "Status", "Data", "Handelssessie", "Laatste ontvangst", "Last", "Last ontvangen",
               "Bid", "Bid ontvangen", "Ask", "Ask ontvangen", "Gekozen koers", "Prijsbron",
               "Verwerkt in app", "Volgende beurt (schatting)", "Laatste melding"]

    def __init__(self, price_feed, parent=None, settings=None):
        super().__init__(parent)
        self.feed = price_feed
        self.settings = settings
        self._active = False
        layout = QVBoxLayout(self)
        intro = QLabel("Koersabonnementen — gezamenlijke capaciteit voor aandelen, opties, futures, indices en valuta.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        controls = QHBoxLayout()
        self.inputs = {}
        snapshot = self.feed.subscription_snapshot()
        for key, title, low, high in [
            ("capacity", "Max. abonnementen", 1, 1000),
            ("batch_size", "Wisselgroep", 1, 1000),
            ("rotation_seconds", "Wisselen elke (sec)", 5, 3600),
            ("stale_seconds", "Stil na (sec)", 30, 7200),
        ]:
            controls.addWidget(QLabel(title))
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setValue(int(snapshot[key]))
            self.inputs[key] = spin
            controls.addWidget(spin)
        apply = QPushButton("Toepassen en bewaren")
        apply.clicked.connect(self._apply)
        controls.addWidget(apply)
        controls.addStretch()
        layout.addLayout(controls)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Zoek instrument, contract, status of foutmelding…")
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)
        footnote = QLabel(
            "Live/delayed is onafhankelijk van koersouderdom. Ontvangsttijd is de tijd in deze app, "
            "niet het tijdstip van de transactie. 'Geen recente data' bewijst geen storing. "
            "Onbekende handelsuren worden niet als gesloten behandeld. "
            "De aandelenkoers blijft Last, met slotkoers als fallback; bied/laat vervangen Last niet.")
        footnote.setWordWrap(True)
        layout.addWidget(footnote)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.refresh()
        for col in range(len(self.HEADERS)):
            self.table.setColumnWidth(col, 145 if col not in (0, 19, 20) else 210)

    def set_active(self, active):
        self._active = bool(active)
        if active:
            self.timer.start()
            self.refresh()
        else:
            self.timer.stop()

    def _apply(self):
        values = {key: spin.value() for key, spin in self.inputs.items()}
        if self.settings is None:
            from portefeuille_viewer.config import get_settings
            self.settings = get_settings()
        try:
            self.settings.set_market_data_settings(values)
        except (OSError, ValueError) as exc:
            self.summary.setText(f"Instellingen niet opgeslagen: {exc}")
            return
        self.feed.configure_subscriptions(**values)
        self.refresh()

    @staticmethod
    def _field(fields, name):
        candidates = [fields[key] for key in (name, "delayed_" + name) if key in fields]
        field = max(candidates, key=lambda f: f.get("received_at", 0)) if candidates else {}
        value = field.get("value")
        return (f"{value:.6g}" if isinstance(value, (float, int)) else "—", stamp(field.get("received_at")))

    def refresh(self, *_args):
        snapshot = self.feed.subscription_snapshot()
        self.summary.setText(
            f"{'Verbonden' if snapshot['connected'] else 'Niet verbonden / herstel'} | "
            f"{len(snapshot['rows'])} gewenst | {snapshot['occupied']} plaatsen bezet | "
            f"{snapshot['receiving']} hebben data ontvangen in deze beurt | "
            f"effectief budget {snapshot['effective_capacity']} / ingesteld {snapshot['capacity']}")
        query = self.search.text().casefold()
        rendered = []
        for row in snapshot["rows"]:
            fields = row["fields"]
            last, last_at = self._field(fields, "last")
            bid, bid_at = self._field(fields, "bid")
            ask, ask_at = self._field(fields, "ask")
            display = fields.get("display", {})
            value = display.get("value")
            values = [row.get("display_name") or row.get("description") or row["symbol"], row["asset_type"], row["currency"],
                      row["exchange"], str(row.get("resolved_conid") or row["contractid"] or "—"),
                      str(row["req_id"] or "—"), STATUSES.get(row["status"], row["status"]), row["data_type"],
                      {"open": "Open", "closed": "Gesloten", "unknown": "Onbekend"}[row["session"]],
                      stamp(row["last_tick"]), last, last_at, bid, bid_at, ask, ask_at,
                      f"{value:.6g}" if isinstance(value, (float, int)) else "—",
                      display.get("source", "—"), stamp(row.get("processed_at")),
                      stamp(row.get("next_turn")), row["error"]]
            if not query or query in " ".join(values).casefold():
                rendered.append(values)
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rendered))
        for r, values in enumerate(rendered):
            for c, value in enumerate(values):
                item = self.table.item(r, c)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(r, c, item)
                if item.text() != value:
                    item.setText(value)
                    item.setToolTip(value)
        self.table.setUpdatesEnabled(True)
        self.table.setSortingEnabled(True)

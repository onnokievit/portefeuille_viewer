"""Small, in-memory audit trail from processed quote to acknowledged DOM value.

An acknowledgement confirms a table cell, not physical screen painting. Tokens
and quote versions prevent late JavaScript results from confirming newer prices.
"""
import math
import threading
import time
from collections import OrderedDict


def same_price(left, right):
    try:
        return math.isfinite(float(left)) and math.isfinite(float(right)) and math.isclose(
            float(left), float(right), rel_tol=1e-10, abs_tol=1e-10)
    except (ValueError, TypeError):
        return False


class QuoteDeliveryTrace:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.entries = {}
        self.pending = OrderedDict()
        self.sequence = 0
        self.active = False
        self.ready = False

    @staticmethod
    def key(symbol, currency):
        return str(symbol).strip().upper(), str(currency).strip().upper()

    def reset(self):
        with self.lock:
            self.entries.clear()
            self.pending.clear()
            # Never reuse tokens: a callback from the previous DB can still run.

    def set_view(self, active, ready):
        with self.lock:
            self.active, self.ready = bool(active), bool(ready)
            if not ready:
                self.pending.clear()

    def processed(self, symbol, currency, price, receipt):
        with self.lock:
            entry = self.entries.setdefault(self.key(symbol, currency), {})
            entry["processed"] = {"value": price, "at": self.clock(),
                                  "version": receipt.get("version"),
                                  "received_at": receipt.get("received_at")}

    def submit(self, cells, *, scenario=False):
        """Freeze the quote version when the actual Koers payload is sent."""
        with self.lock:
            self.sequence += 1
            token = self.sequence
            plans = []
            for cell in cells:
                key = self.key(cell["symbol"], cell["currency"])
                entry = self.entries.setdefault(key, {})
                processed = entry.get("processed", {})
                plan = {**cell, "key": key, "at": self.clock(), "token": token,
                        "scenario": bool(scenario), "version": processed.get("version")
                        if same_price(processed.get("value"), cell.get("value")) else None}
                entry["sent"] = plan
                plans.append(plan)
            self.pending[token] = plans
            while len(self.pending) > 8:
                self.pending.popitem(last=False)
            return token

    def acknowledge(self, token, result):
        with self.lock:
            plans = self.pending.pop(token, None)
            if plans is None:
                return
            observed = {str(r.get("asset", "")): r for r in result.get("rows", []) if isinstance(r, dict)}
            for plan in plans:
                entry = self.entries.get(plan["key"])
                if not entry or entry.get("sent", {}).get("token") != token:
                    continue
                row = observed.get(str(plan["asset"]), {})
                if not result.get("ok"):
                    reason = "web_error"
                elif row.get("state") in {"filtered", "missing"}:
                    reason = row["state"]
                elif not row.get("dom_matches") or not same_price(row.get("value"), plan["value"]):
                    reason = "dom_mismatch"
                else:
                    reason = "confirmed"
                entry["observation"] = {"reason": reason, "at": self.clock(),
                    "error": str(result.get("error", "")), "value": row.get("value"),
                    "text": row.get("text", ""), "token": token}
                if reason == "confirmed":
                    entry["rendered"] = {"at": self.clock(), "value": row["value"],
                        "text": row.get("text", ""), "version": plan["version"],
                        "scenario": plan["scenario"], "token": token}

    def snapshot(self, symbol, currency, latest_receipt=None):
        with self.lock:
            entry = self.entries.get(self.key(symbol, currency), {})
            processed = entry.get("processed", {})
            sent = entry.get("sent", {})
            rendered = entry.get("rendered", {})
            observed = entry.get("observation", {})
            issue_labels = {"filtered": "Rij uitgefilterd", "missing": "Rij ontbreekt in webtabel",
                            "dom_mismatch": "Koers wijkt af in webcel", "web_error": "Fout in aandelenpagina"}
            last_issue = issue_labels.get(observed.get("reason")) if observed.get("token") == sent.get("token") else None
            receipt_version = (latest_receipt or {}).get("version")
            if not self.ready:
                status = "Aandelenpagina niet gereed"
            elif not self.active:
                status = "Aandelen-tab inactief" + (f"; laatste controle: {last_issue}" if last_issue else "")
            elif receipt_version and receipt_version != processed.get("version"):
                status = "Wacht op interne verwerking"
            elif not processed:
                status = "Nog geen koers intern verwerkt"
            elif sent and self.clock() - sent["at"] > 10 and sent.get("token") != observed.get("token"):
                status = "Geen webbevestiging (>10 sec)"
            elif observed.get("token") == sent.get("token") and observed.get("reason") in {
                "filtered", "missing", "dom_mismatch", "web_error"
            }:
                status = issue_labels[observed["reason"]]
            elif rendered and rendered.get("scenario"):
                status = "Webcel bevestigd; scenario/koerscorrectie actief"
            elif rendered and same_price(rendered.get("value"), processed.get("value")):
                status = "Koers bevestigd in webcel"
            elif sent and same_price(sent.get("value"), processed.get("value")):
                status = "Verzonden; wacht op webbevestiging"
            else:
                status = "Intern bijgewerkt; wacht op aandelenoverzicht"
            return {"received_at": processed.get("received_at"), "processed_at": processed.get("at"),
                    "processed_value": processed.get("value"), "sent_at": sent.get("at"),
                    "sent_value": sent.get("value"), "rendered_at": rendered.get("at"),
                    "rendered_value": rendered.get("value"), "rendered_text": rendered.get("text", ""),
                    "status": status, "error": observed.get("error", ""),
                    "active": self.active, "ready": self.ready}

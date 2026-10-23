"""Real, offline QtWebEngine render/patch regression with a synthetic share."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

import json
import time
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch

import polars as pl
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView

from portefeuille_viewer.services.quote_delivery_trace import QuoteDeliveryTrace
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE


class WebDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, condition, timeout=15):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents(QEventLoop.AllEvents, 50)
            time.sleep(.005)
        self.assertTrue(condition(), "Qt/JavaScript callback did not arrive")

    def js(self, script):
        result = []
        self.web.page().runJavaScript(script, lambda value: result.append(value))
        self.wait_until(lambda: bool(result))
        return result[0]

    def test_real_dom_full_patch_missing_updates_filters_and_errors(self):
        with patch("portefeuille_viewer.config.get_databases", return_value={}), \
             patch("portefeuille_viewer.config.get_default_database", return_value=None), \
             patch("pyodbc.connect", side_effect=AssertionError("Database access forbidden")):
            from portefeuille_viewer.ui_logica.aandelen_web_pilot_tab import AandelenWebPilotTab
        trace = QuoteDeliveryTrace()
        trace.set_view(True, True)
        trace.processed("SPCX", "USD", 100., {"version": 1, "received_at": time.time()})
        # Use the real page/methods without its constructor's scenario/DB loaders.
        host = QWidget()
        self.web = QWebEngineView(host)
        host.web = self.web
        host._price_feed = SimpleNamespace(quote_delivery=trace)
        for name in ("_quote_delivery_cells", "_run_quote_delivery_js", "_run_js"):
            setattr(host, name, MethodType(getattr(AandelenWebPilotTab, name), host))
        host._json_default = AandelenWebPilotTab._json_default
        loaded = []
        self.web.loadFinished.connect(lambda ok: loaded.append(ok))
        self.web.setHtml(AandelenWebPilotTab._html_template(host))
        self.wait_until(lambda: bool(loaded))
        self.assertTrue(loaded[-1])
        mapping = pl.DataFrame([{"asset_rollup": "SPCX", "ib_symbol": "SPCX",
                                 "ib_currency": "USD", "type": "aandeel"}])
        with patch.object(SNAPSHOT_STORE, "repository_snapshot_asset_rollup_data", mapping), \
             patch.object(SNAPSHOT_STORE, "runtime_test_orders_enabled", False), \
             patch.object(SNAPSHOT_STORE, "runtime_beta_shift_enabled", False), \
             patch.object(SNAPSHOT_STORE, "runtime_price_shift_pct", 0):
            def send(function, payload):
                host._run_js(function, payload)
                self.wait_until(lambda: not trace.pending)
                return trace.snapshot("SPCX", "USD")

            initial = send("renderSnapshot", {"rows": [{"asset_rollup": "SPCX", "koers": 100.}]})
            self.assertEqual(initial["rendered_value"], 100.)
            self.assertEqual(self.js('document.getElementById("c_SPCX_koers").textContent'), "100,00")
            trace.processed("SPCX", "USD", 90., {"version": 2, "received_at": time.time()})
            fallen = send("applyPatch", {"changes": [{"row_id": "SPCX", "field": "koers", "value": 90.}]})
            self.assertEqual(fallen["rendered_value"], 90.)
            self.assertEqual(self.js('document.getElementById("c_SPCX_koers").textContent'), "90,00")

            # Simulate a broken patch handler: no send-only false confirmation.
            self.js("window.originalApplyPatch = window.applyPatch; window.applyPatch = function() {};")
            trace.processed("SPCX", "USD", 85., {"version": 3, "received_at": time.time()})
            stuck = send("applyPatch", {"changes": [{"row_id": "SPCX", "field": "koers", "value": 85.}]})
            self.assertEqual(stuck["rendered_value"], 90.)
            self.assertEqual(stuck["status"], "Koers wijkt af in webcel")
            self.js("window.applyPatch = window.originalApplyPatch;")

            self.js('document.getElementById("f_asset").value="OTHER"; document.getElementById("f_asset").dispatchEvent(new Event("input"));')
            filtered = send("applyPatch", {"changes": [{"row_id": "SPCX", "field": "koers", "value": 85.}]})
            self.assertEqual(filtered["status"], "Rij uitgefilterd")

            self.js('window.applyPatch = function() { throw new Error("synthetic render failure"); };')
            failed = send("applyPatch", {"changes": [{"row_id": "SPCX", "field": "koers", "value": 84.}]})
            self.assertEqual(failed["status"], "Fout in aandelenpagina")
            self.assertIn("synthetic render failure", failed["error"])
        host.close()
        host.deleteLater()
        # WebEngine must release its page before QApplication/interpreter exits.
        cleanup = QEventLoop()
        QTimer.singleShot(50, cleanup.quit)
        cleanup.exec()
        self.web = None


if __name__ == "__main__":
    unittest.main()

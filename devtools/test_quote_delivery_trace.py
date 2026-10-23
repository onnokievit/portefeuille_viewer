"""Offline evidence tests: no synthetic send is treated as a render ACK."""
import unittest

from portefeuille_viewer.services.quote_delivery_trace import QuoteDeliveryTrace


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.
        self.trace = QuoteDeliveryTrace(clock=lambda: self.now)
        self.trace.set_view(True, True)
        self.process(100., 1)

    def process(self, price, version):
        self.trace.processed("SPCX", "USD", price, {"version": version, "received_at": self.now - .01})

    def send(self, value=100., **kwargs):
        return self.trace.submit([{"asset": "SPCX", "symbol": "SPCX", "currency": "USD", "value": value}], **kwargs)

    def ack(self, token, value=100., **kwargs):
        self.trace.acknowledge(token, {"ok": True, "rows": [{"asset": "SPCX", "value": value,
            "text": str(value), "dom_matches": True, **kwargs}]})

    def snapshot(self, **receipt):
        return self.trace.snapshot("SPCX", "USD", receipt)

    def test_send_does_not_confirm_render_and_timeout_is_visible(self):
        self.send()
        self.assertIsNone(self.snapshot()["rendered_at"])
        self.assertIn("wacht op webbevestiging", self.snapshot()["status"])
        self.now += 11
        self.assertIn("Geen webbevestiging", self.snapshot()["status"])

    def test_ack_confirms_exact_submitted_price(self):
        token = self.send()
        self.now += .5
        self.ack(token)
        self.assertEqual(self.snapshot()["rendered_at"], self.now)
        self.assertEqual(self.snapshot()["rendered_value"], 100.)
        self.assertEqual(self.snapshot()["status"], "Koers bevestigd in webcel")

    def test_new_quote_does_not_inherit_old_render_confirmation(self):
        token = self.send()
        self.ack(token)
        self.process(90., 2)
        result = self.snapshot(version=2)
        self.assertEqual(result["rendered_value"], 100.)
        self.assertIn("wacht op aandelenoverzicht", result["status"])
        new = self.send(90.)
        self.ack(new, 90.)
        self.assertEqual(self.snapshot()["rendered_value"], 90.)

    def test_latest_received_but_not_processed_is_identified(self):
        self.assertEqual(self.snapshot(version=2)["status"], "Wacht op interne verwerking")

    def test_old_callback_cannot_confirm_newer_submission(self):
        old = self.send()
        self.process(90., 2)
        new = self.send(90.)
        self.ack(new, 90.)
        self.ack(old)
        self.assertEqual(self.snapshot()["rendered_value"], 90.)

    def test_dom_mismatch_is_not_confirmation(self):
        self.ack(self.send(), dom_matches=False)
        self.assertIsNone(self.snapshot()["rendered_at"])
        self.assertIn("wijkt af", self.snapshot()["status"])

    def test_stale_dom_price_is_not_confirmation(self):
        self.ack(self.send(), 90.)
        self.assertIsNone(self.snapshot()["rendered_at"])

    def test_filtered_and_missing_are_different_from_feed_failure(self):
        self.ack(self.send(), state="filtered")
        self.assertEqual(self.snapshot()["status"], "Rij uitgefilterd")
        self.ack(self.send(), state="missing")
        self.assertEqual(self.snapshot()["status"], "Rij ontbreekt in webtabel")

    def test_inactive_tab_not_reported_as_stall(self):
        self.send()
        self.now += 20
        self.trace.set_view(False, True)
        self.assertEqual(self.snapshot()["status"], "Aandelen-tab inactief")

    def test_database_reset_invalidates_old_callbacks(self):
        token = self.send()
        self.trace.reset()
        self.process(90., 2)
        self.send(90.)
        self.ack(token)
        self.assertIsNone(self.snapshot()["rendered_at"])

    def test_page_reload_invalidates_old_callbacks(self):
        token = self.send()
        self.trace.set_view(True, False)
        self.trace.set_view(True, True)
        self.ack(token)
        self.assertIsNone(self.snapshot()["rendered_at"])

    def test_identical_quote_does_not_require_fake_dom_update(self):
        self.ack(self.send())
        first_render = self.snapshot()["rendered_at"]
        self.now += 30
        self.process(100., 2)
        self.assertEqual(self.snapshot()["rendered_at"], first_render)
        self.assertEqual(self.snapshot(version=2)["status"], "Koers bevestigd in webcel")

    def test_scenario_price_not_mislabelled_as_stale_market_data(self):
        self.ack(self.send(110., scenario=True), 110.)
        self.assertIn("scenario/koerscorrectie", self.snapshot()["status"])

    def test_javascript_error_does_not_confirm_any_price(self):
        token = self.send()
        self.trace.acknowledge(token, {"ok": False, "error": "render failed"})
        self.assertIsNone(self.snapshot()["rendered_at"])
        self.assertEqual(self.snapshot()["error"], "render failed")

    def test_pending_callback_memory_is_bounded(self):
        for _ in range(100):
            self.send()
        self.assertEqual(len(self.trace.pending), 8)

    def test_last_render_failure_remains_visible_in_diagnostic_tab(self):
        self.ack(self.send(), dom_matches=False)
        self.trace.set_view(False, True)
        self.assertIn("inactief", self.snapshot()["status"])
        self.assertIn("wijkt af", self.snapshot()["status"])


if __name__ == "__main__":
    unittest.main()

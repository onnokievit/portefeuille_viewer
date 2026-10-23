"""Offline concurrency/state regressions: never connect to IBKR or Access."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from portefeuille_viewer.services.subscription_manager import MarketSchedule, SubscriptionManager


class Clock:
    def __init__(self):
        self.now = 1700000000.0

    def __call__(self):
        return self.now


class Transport:
    def __init__(self):
        self.counter = 0
        self.live = {}
        self.history = []
        self.detail_requests = []
        self.events = []

    def next_id(self):
        self.counter += 1
        return self.counter

    def start(self, req_id, spec, fallback):
        self.live[req_id] = spec["key"]
        self.history.append(spec["key"])

    def cancel(self, req_id):
        self.live.pop(req_id, None)

    def details(self, req_id, spec, fallback):
        self.detail_requests.append((req_id, spec))

    def forget_details(self, req_id):
        pass

    def event(self, message):
        self.events.append(message)


def spec(number, kind="asset"):
    return {"key": (kind, number), "symbol": f"S{number}", "kind": kind,
            "currency": "USD", "exchange": "SMART", "contractid": number,
            "asset_type": "optie" if kind == "option" else "aandeel", "meta": {"cid": number}}


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.transport = Transport()
        self.manager = SubscriptionManager(self.transport, capacity=3, batch_size=1,
                                           rotation_seconds=30, clock=self.clock)
        self.manager.reset(True)

    def advance(self, seconds, receive=True):
        for _ in range(int(seconds * 5)):
            self.clock.now += .2
            self.manager.step()
            if receive:
                for req_id in list(self.manager.by_request):
                    self.manager.tick(req_id, "last", 10)
            self.assertLessEqual(len(self.transport.live), self.manager.capacity)

    def test_250_instruments_are_served_without_exceeding_100(self):
        self.manager.configure(100, 10, 30, 180)
        self.manager.set_source("assets", [spec(i) for i in range(150)])
        self.manager.set_source("options", [spec(i, "option") for i in range(100)])
        self.advance(520)
        self.assertEqual(len(set(self.transport.history)), 250)
        self.assertLessEqual(len(self.transport.live), 100)

    def test_requested_is_not_confirmed_and_delayed_is_recorded(self):
        self.manager.set_source("assets", [spec(1)])
        self.advance(1, receive=False)
        snapshot = self.manager.snapshot()
        self.assertEqual(snapshot["receiving"], 0)
        row = snapshot["rows"][0]
        self.assertEqual(row["status"], "requested")
        self.manager.market_type(row["req_id"], 3)
        self.manager.tick(row["req_id"], "delayed_last", 90, delayed=True)
        row = self.manager.snapshot()["rows"][0]
        self.assertEqual(row["status"], "receiving")
        self.assertEqual(row["data_type"], "Delayed")
        self.assertEqual(row["fields"]["delayed_last"]["value"], 90)

    def test_rejection_reduces_capacity_and_requeues(self):
        self.manager.set_source("assets", [spec(i) for i in range(5)])
        self.advance(1)
        req_id = next(iter(self.manager.by_request))
        key = self.manager.by_request[req_id]
        self.manager.error(req_id, 101, "Max tickers")
        self.assertEqual(self.manager.effective_capacity, 2)
        self.assertEqual(self.manager.records[key].status, "rejected")
        self.advance(100)
        self.assertIn(key, self.transport.history[3:])
        self.assertLessEqual(len(self.transport.live), 2)

    def test_rejection_counters_survive_recovery_and_configure(self):
        self.manager.set_source("assets", [spec(1)])
        self.advance(1)
        req_id = next(iter(self.manager.by_request))
        self.manager.error(req_id, 101, "limit")
        self.assertEqual(self.manager.snapshot()["rejected_now"], 1)
        self.advance(35)
        self.manager.configure(3, 1, 30, 180)
        snapshot = self.manager.snapshot()
        self.assertEqual(snapshot["rejected_now"], 0)
        self.assertEqual(snapshot["rejections_total"], 1)
        self.assertEqual(snapshot["limit_rejections_total"], 1)
        # Ignore late duplicate errors for an already released request.
        self.manager.error(req_id, 101, "duplicate late callback")
        self.assertEqual(self.manager.snapshot()["limit_rejections_total"], 1)

    def test_counter_reset_does_not_change_subscriptions_or_errors(self):
        self.manager.set_source("assets", [spec(1)])
        self.advance(1)
        req_id = next(iter(self.manager.by_request))
        self.manager.error(req_id, 354, "No permissions")
        before = self.manager.snapshot()
        self.assertEqual(before["rejections_total"], 1)
        self.assertEqual(before["limit_rejections_total"], 0)
        self.manager.reset_rejection_counters()
        after = self.manager.snapshot()
        self.assertEqual(after["rejections_total"], 0)
        self.assertEqual(after["rows"], before["rows"])
        self.assertEqual(after["rejected_now"], 1)

    def test_source_replacement_cancels_old_instruments(self):
        self.manager.set_source("assets", [spec(i) for i in range(3)])
        self.advance(1)
        self.manager.set_source("assets", [spec(8)])
        self.advance(2)
        self.assertEqual(list(self.transport.live.values()), [("asset", 8)])
        self.assertEqual(len(self.manager.records), 1)

    def test_late_cancelled_ticks_cannot_resurrect_stream(self):
        self.manager.set_source("assets", [spec(1)])
        self.advance(1)
        req_id = next(iter(self.manager.by_request))
        self.manager.set_source("assets", [])
        self.assertFalse(self.manager.tick(req_id, "last", 42))

    def test_focus_preempts_and_then_rejoins_normal_rotation(self):
        self.manager.set_source("assets", [spec(i) for i in range(6)])
        self.advance(1)
        self.manager.set_focus([("asset", 5)])
        self.advance(2)
        self.assertIn(("asset", 5), self.transport.live.values())
        self.manager.set_focus([])
        self.advance(100)
        self.assertEqual(len(set(self.transport.history)), 6)

    def test_closed_skipped_but_unknown_kept(self):
        self.manager.set_source("assets", [spec(i) for i in range(3)])
        day = datetime.fromtimestamp(self.clock.now, timezone.utc).strftime("%Y%m%d")
        self.manager.records[("asset", 0)].schedule = MarketSchedule.parse(day + ":CLOSED", "UTC")
        self.advance(2)
        self.assertNotIn(("asset", 0), self.transport.live.values())
        self.assertIn(("asset", 1), self.transport.live.values())

    def test_silence_marked_then_bounded_retry_not_permanent_stop(self):
        self.manager.set_source("assets", [spec(1)])
        self.advance(185, receive=False)
        self.assertEqual(self.manager.records[("asset", 1)].status, "quiet")
        self.advance(220, receive=False)
        self.assertGreater(len(self.transport.history), 1)

    def test_reconnect_ignores_old_ids(self):
        self.manager.set_source("assets", [spec(1)])
        self.advance(1)
        old = next(iter(self.manager.by_request))
        self.transport.live.clear()  # connection loss removes server-side streams
        self.manager.reset(False)
        self.advance(5)
        self.assertFalse(self.manager.tick(old, "last", 9))
        self.manager.reset(True)
        self.advance(1)
        self.assertEqual(len(self.transport.live), 1)
        self.assertNotEqual(next(iter(self.transport.live)), old)

    def test_schedule_requests_bounded_and_refresh_after_timeout(self):
        self.manager.set_source("assets", [spec(i) for i in range(10)])
        self.advance(10)
        self.assertEqual(len(self.transport.detail_requests), 4)
        self.advance(25)
        self.assertGreater(len(self.transport.detail_requests), 4)

    def test_no_data_with_valid_market_type_still_not_confirmed(self):
        self.manager.set_source("assets", [spec(1)])
        self.advance(1, receive=False)
        req_id = next(iter(self.manager.by_request))
        self.manager.market_type(req_id, 1)
        self.assertEqual(self.manager.snapshot()["receiving"], 0)


class ScheduleTests(unittest.TestCase):
    def test_us_extended_hours_and_dst(self):
        schedule = MarketSchedule.parse("20261023:0400-20261023:2000;20261024:CLOSED", "US/Eastern")
        # 08 UTC = 04 EDT, premarket must be included.
        now = datetime(2026, 10, 23, 8, tzinfo=timezone.utc).timestamp()
        self.assertEqual(schedule.state(now)[0], "open")
        self.assertEqual(schedule.state(now - 1)[0], "closed")
        winter = MarketSchedule.parse("20261106:0400-20261106:2000", "US/Eastern")
        self.assertEqual(winter.state(datetime(2026, 11, 6, 8, tzinfo=timezone.utc).timestamp())[0], "closed")
        self.assertEqual(winter.state(datetime(2026, 11, 6, 9, tzinfo=timezone.utc).timestamp())[0], "open")

    def test_overnight_break_and_expired_coverage(self):
        schedule = MarketSchedule.parse("20261023:1800-20261024:0500,20261024:0600-20261024:1000", "UTC")
        self.assertEqual(schedule.state(datetime(2026, 10, 24, 2, tzinfo=timezone.utc).timestamp())[0], "open")
        self.assertEqual(schedule.state(datetime(2026, 10, 25, 2, tzinfo=timezone.utc).timestamp())[0], "unknown")

    def test_invalid_timezone_is_unknown(self):
        self.assertEqual(MarketSchedule.parse("20261023:CLOSED", "Not/AZone").state(1700000000)[0], "unknown")


if __name__ == "__main__":
    unittest.main()

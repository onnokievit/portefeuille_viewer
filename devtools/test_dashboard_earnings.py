from datetime import date, timedelta
import json
import unittest

from portefeuille_viewer.services.asset_dashboard_data import dividend_display, event_date_display
from portefeuille_viewer.services.asset_dashboard_earnings import next_earnings


class EarningsTests(unittest.TestCase):
    today = date(2026,10,27)

    def schedule(self, day, seen="2026-10-27", **extra):
        return dict(subject_key="AAPL",source="Yahoo",metric="earnings_schedule",last_seen=seen,
                    payload_json=json.dumps(dict(value={"date_start":day,"date_end":day},**extra)))

    def test_colour_dates_are_independent(self):
        dividend = dividend_display({"next_dividend_date":self.today+timedelta(days=20),
                                     "next_dividend_amount":.25},self.today)
        earnings = event_date_display(self.today+timedelta(days=3),self.today)
        self.assertEqual(dividend["background"],"#FFFF00")
        self.assertEqual(earnings["background"],"#FF0000")
        self.assertEqual(event_date_display(None,self.today)["background"],"#D9D9D9")

    def test_new_schedule_supersedes_old_date(self):
        rows=[self.schedule("2026-10-28","2026-10-25"),self.schedule("2026-11-05")]
        self.assertEqual(next_earnings(rows,self.today)["AAPL"]["date"],"2026-11-05")

    def test_past_and_deleted_schedules_are_not_future_events(self):
        self.assertEqual(next_earnings([self.schedule("2026-10-26")],self.today),{})
        deleted=self.schedule("2026-11-05",__wyse_envelope__={"operation":"delete"})
        self.assertEqual(next_earnings([deleted],self.today),{})

    def test_source_publication_fallback_does_not_use_reported_rows(self):
        rows=[dict(subject_key="AAPL",source="Yahoo",metric="earnings_source_row",last_seen="2026-10-27",
                   payload_json=json.dumps({"value":{"Reported EPS":actual},"context":{"date":"2026-11-05"}}))
              for actual in [1.2,None]]
        self.assertEqual(next_earnings(rows[:1],self.today),{})
        self.assertEqual(next_earnings(rows[1:],self.today)["AAPL"]["date"],"2026-11-05")

    def test_no_schedule_does_not_invent_a_date(self):
        self.assertEqual(next_earnings([],self.today),{})


if __name__=="__main__":unittest.main()

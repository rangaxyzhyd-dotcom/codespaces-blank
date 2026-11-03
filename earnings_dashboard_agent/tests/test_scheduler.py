import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scheduler.runner import _is_recent, start_scheduler

IST = ZoneInfo("Asia/Kolkata")


class SchedulerTests(unittest.TestCase):
    def test_result_detection_includes_today_and_previous_two_calendar_days(self):
        now = datetime(2026, 11, 3, 10, 0, tzinfo=IST)

        for published in ("2026-11-03T00:05:00+05:30", "2026-11-02T00:05:00+05:30", "2026-11-01T23:55:00+05:30"):
            with self.subTest(published=published):
                self.assertTrue(_is_recent({"published": published}, now))

        self.assertFalse(_is_recent({"published": "2026-10-31T23:55:00+05:30"}, now))
        self.assertFalse(_is_recent({"published": "2026-11-04T00:00:00+05:30"}, now))

    @patch("scheduler.runner.BackgroundScheduler")
    def test_market_poll_defaults_to_every_five_minutes(self, scheduler_class):
        start_scheduler([])

        market_job = scheduler_class.return_value.add_job.call_args_list[0]
        self.assertEqual(market_job.args[1], "cron")
        self.assertEqual(market_job.kwargs["minute"], "*/5")


if __name__ == "__main__":
    unittest.main()
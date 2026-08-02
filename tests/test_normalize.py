import unittest

from ff_calendar_toolkit.normalize import convert_time_zone, normalize_rows


class NormalizeTests(unittest.TestCase):
    def test_normalize_rows_carries_dates_and_times(self):
        rows = [
            {"date": "Tue Sep 2", "time": "3:00am"},
            {
                "currency": "USD",
                "impact": "red",
                "event": "Test Event",
                "actual": "1",
                "forecast": "2",
                "previous": "3",
                "detail": "url",
            },
            {"time": "empty", "currency": "EUR", "impact": "orange", "event": "Second Event"},
        ]

        normalized = normalize_rows(
            rows,
            "2025",
            "UTC",
            "Asia/Karachi",
            ["USD", "EUR"],
            ["red", "orange"],
        )

        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["date"], "02/09/2025")
        self.assertEqual(normalized[0]["day"], "Tue")
        self.assertEqual(normalized[0]["time"], "08:00")
        self.assertEqual(normalized[1]["time"], "08:00")

    def test_convert_time_zone_handles_special_values(self):
        self.assertEqual(
            convert_time_zone("02/09/2025", "all day", "UTC", "Asia/Karachi"),
            ("all day", "02/09/2025", ""),
        )

    def test_convert_time_zone_shifts_date_back_over_midnight(self):
        self.assertEqual(
            convert_time_zone("26/06/2026", "4:30am", "Asia/Karachi", "UTC"),
            ("23:30", "25/06/2026", "Thu"),
        )

    def test_convert_time_zone_shifts_date_forward_over_midnight(self):
        self.assertEqual(
            convert_time_zone("25/06/2026", "8:30pm", "America/New_York", "Asia/Karachi"),
            ("05:30", "26/06/2026", "Fri"),
        )

    def test_normalize_rows_shifts_day_and_date_over_midnight(self):
        rows = [
            {"date": "Fri Jun 26", "time": "4:30am"},
            {
                "currency": "JPY",
                "impact": "orange",
                "event": "Tokyo Core CPI y/y",
                "actual": "1.6%",
                "forecast": "1.6%",
                "previous": "1.3%",
                "detail": "url",
            },
        ]

        normalized = normalize_rows(rows, "2026", "Asia/Karachi", "UTC", ["JPY"], ["orange"])

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["time"], "23:30")
        self.assertEqual(normalized[0]["date"], "25/06/2026")
        self.assertEqual(normalized[0]["day"], "Thu")


if __name__ == "__main__":
    unittest.main()

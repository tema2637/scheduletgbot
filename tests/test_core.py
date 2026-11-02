import asyncio
import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

import config
from data_manager import DataManager
from retry import retry_request
from schedule_parser import TIME_SLOTS, parse_file, parse_weeks
from storage import validate
from ui_templates import safe

ROOT = Path(__file__).resolve().parents[1]


class CoreTests(unittest.TestCase):
    def test_active_schedule_is_valid(self):
        data = json.loads((ROOT / "data" / "schedule.json").read_text(encoding="utf-8"))
        self.assertEqual(len(validate(data)), len(data))
        self.assertEqual(len({row["Group"]["Name"] for row in data}), 49)

    def test_active_schedule_uses_new_monday_times(self):
        data = json.loads((ROOT / "data" / "schedule.json").read_text(encoding="utf-8"))
        actual = {
            (
                row["TimeSlot"]["NumberSlot"],
                row["TimeSlot"]["StartTime"],
                row["TimeSlot"]["EndTime"],
            )
            for row in data
            if row["TimeSlot"]["DayOfWeek"] == 1
        }
        expected = {
            (1, "09:25", "10:55"),
            (2, "11:25", "12:55"),
            (3, "13:05", "14:35"),
            (4, "14:45", "16:15"),
            (5, "16:25", "17:55"),
            (6, "18:05", "19:35"),
        }
        self.assertEqual(actual, expected)

    def test_parser_uses_new_monday_times(self):
        self.assertEqual(TIME_SLOTS[1][1], ("09:25", "10:55"))
        self.assertEqual(TIME_SLOTS[1][2], ("11:25", "12:55"))
        self.assertEqual(TIME_SLOTS[1][6], ("18:05", "19:35"))

    def test_week_ranges(self):
        self.assertEqual(parse_weeks("1–5, 7, 9 11"), [1, 2, 3, 4, 5, 7, 9, 11])
        for value in ("5-1", "0", "61", "1-100000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_weeks(value)

    def test_current_xlsx_import(self):
        records, report = parse_file(ROOT / "imports" / "Расписание-2.xlsx")
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["source_cells"], 1029)
        self.assertEqual(len(records), 1504)

    def test_academic_week_changes_on_monday(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = DataManager(
                schedule_path=ROOT / "data" / "schedule.json",
                db_path=Path(directory) / "users.db",
            )
            self.assertEqual(manager.get_academic_week(date(2026, 9, 7)), 2)
            self.assertEqual(manager.get_academic_week(date(2026, 9, 8)), 2)

    def test_html_escape(self):
        self.assertEqual(safe("A&B <b>"), "A&amp;B &lt;b&gt;")


class RetryAfter(Exception):
    def __init__(self, retry_after):
        self.retry_after = retry_after


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_the_same_method(self):
        method = object()
        send = AsyncMock(side_effect=[RetryAfter(0), "ok"])
        sleep = AsyncMock()
        result = await retry_request(send, object(), method, RetryAfter, sleep=sleep)
        self.assertEqual(result, "ok")
        self.assertIs(send.call_args_list[0].args[1], method)
        self.assertIs(send.call_args_list[1].args[1], method)
        sleep.assert_awaited_once_with(0.0)

    async def test_does_not_retry_other_errors(self):
        send = AsyncMock(side_effect=ValueError("broken"))
        with self.assertRaises(ValueError):
            await retry_request(send, object(), object(), RetryAfter)
        self.assertEqual(send.await_count, 1)


if __name__ == "__main__":
    unittest.main()

import asyncio
import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import config
import subscription
from data_manager import DataManager
from retry import retry_request
from schedule_parser import (
    TIME_SLOTS,
    collect_cells,
    extract_from_segment,
    parse_cell,
    parse_file,
    parse_weeks,
)
from storage import validate
from ui_templates import safe

ROOT = Path(__file__).resolve().parents[1]


class CoreTests(unittest.TestCase):
    def test_active_schedule_is_valid(self):
        data = json.loads((ROOT / "data" / "schedule.json").read_text(encoding="utf-8"))
        self.assertEqual(len(validate(data)), len(data))
        self.assertEqual(len(data), 1521)
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
        self.assertEqual(len(records), 1521)
        self.assertEqual(len(report["source_sha256"]), 64)

    def test_validate_rejects_slot_time_drift(self):
        data = json.loads((ROOT / "data" / "schedule.json").read_text(encoding="utf-8"))
        bad = json.loads(json.dumps(data[0]))
        bad["TimeSlot"]["StartTime"] = "00:00"
        with self.assertRaises(ValueError):
            validate([bad])

    def test_validate_rejects_unsupported_day(self):
        data = json.loads((ROOT / "data" / "schedule.json").read_text(encoding="utf-8"))
        bad = json.loads(json.dumps(data[0]))
        bad["TimeSlot"]["DayOfWeek"] = 6
        with self.assertRaises(ValueError):
            validate([bad])

    def test_room_after_last_teacher_is_kept(self):
        lessons = parse_cell(
            "Математика (1-5) Иванов И.И. 410",
            "ИКС 243", 1, 1, {"Иванов И.И."}, {"Иванов"},
        )
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0]["Cabinet"], "410")

    def test_multiple_lessons_in_one_cell_are_split(self):
        lessons = parse_cell(
            "311 ПКП в ПД (1-8,12,15,17) 311 Общ.энерг.(14,16) "
            "Шаталов Н.А. Физ.кул.(9-11,13) Кобзев",
            "РЗ 252", 5, 2, {"Шаталов Н.А."}, {"Шаталов", "Кобзев"},
        )
        self.assertEqual(
            [(x["LessonTitle"], x["TeacherName"], x["Cabinet"], x["Weeks"])
             for x in lessons],
            [
                ("ПКП в ПД", "Шаталов Н.А.", "311",
                 [1, 2, 3, 4, 5, 6, 7, 8, 12, 15, 17]),
                ("Общ.энерг.", "Шаталов Н.А.", "311", [14, 16]),
                ("Физ.кул.", "Кобзев", "", [9, 10, 11, 13]),
            ],
        )

    def test_multiple_subjects_before_one_teacher_are_split(self):
        lessons = parse_cell(
            "207 МДК.01.03. (1,3,5) 207 МДК.01.02. (2,4,6-12,14) Буслова Н.И.",
            "ИКС 251", 1, 4, {"Буслова Н.И."}, {"Буслова"},
        )
        self.assertEqual(
            [(x["LessonTitle"], x["TeacherName"], x["Cabinet"], x["Weeks"])
             for x in lessons],
            [
                ("МДК.01.03.", "Буслова Н.И.", "207", [1, 3, 5]),
                ("МДК.01.02.", "Буслова Н.И.", "207",
                 [2, 4, 6, 7, 8, 9, 10, 11, 12, 14]),
            ],
        )

    def test_invalid_paren_does_not_become_weeks(self):
        subject, weeks, room = extract_from_segment("Математика (305) (1-5)")
        self.assertEqual(weeks, [1, 2, 3, 4, 5])
        self.assertEqual(room, "305")

    def test_saturday_is_rejected_instead_of_misattributed(self):
        rows = [[""] for _ in range(5)]
        rows.append(["СУББОТА", "1"])
        rows.append(["", "", "Математика (1-5) Иванов И.И."])
        with self.assertRaises(ValueError):
            collect_cells(rows, 1)

    def test_date_beyond_loaded_weeks_is_unknown_not_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = DataManager(
                schedule_path=ROOT / "data" / "schedule.json",
                db_path=Path(directory) / "users.db",
            )
            self.assertIsNone(manager.get_schedule_for_day("ИКС 243", date(2027, 1, 15)))

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

    def test_teacher_search_and_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = DataManager(
                schedule_path=ROOT / "data" / "schedule.json",
                db_path=Path(directory) / "users.db",
            )
            teachers = manager.get_teachers()
            self.assertGreater(len(teachers), 50)
            self.assertIn("Шаталов Н.А.", teachers)

            # Search by substring
            shatalov = manager.find_teachers("шатал")
            self.assertEqual(shatalov, ["Шаталов Н.А."])

            # Teacher schedule on Monday week 10 (2026-11-02)
            lessons = manager.get_teacher_schedule_for_day("Шаталов Н.А.", date(2026, 11, 2))
            self.assertEqual(len(lessons), 3)
            self.assertEqual(lessons[0]["LessonTitle"], "ПКП в ПД")
            self.assertEqual(lessons[0]["Group"]["Name"], "РЗ 252")

            # Save and load teacher target
            manager.save_user_target(999, "teacher:Шаталов Н.А.")
            self.assertEqual(manager.get_user_target(999), "teacher:Шаталов Н.А.")
            self.assertTrue(manager.is_teacher_target("teacher:Шаталов Н.А."))
            self.assertEqual(manager.target_name("teacher:Шаталов Н.А."), "Шаталов Н.А.")

            # Teacher week text
            week_text = manager.get_teacher_week_text("Шаталов Н.А.", date(2026, 11, 2))
            self.assertIn("ПРЕПОДАВАТЕЛЬ: Шаталов Н.А.", week_text)
            self.assertIn("РЗ 252", week_text)

    def test_notify_settings_and_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = DataManager(
                schedule_path=ROOT / "data" / "schedule.json",
                db_path=Path(directory) / "users.db",
            )
            # Default is False / None
            self.assertFalse(manager.get_user_notify(123))
            self.assertIsNone(manager.get_user_notify_time(123))

            # Enable notify with specific time
            manager.save_user_target(123, "РЗ 252")
            manager.set_user_notify_time(123, "19:00")
            self.assertTrue(manager.get_user_notify(123))
            self.assertEqual(manager.get_user_notify_time(123), "19:00")

            # Users for time
            users_19 = manager.get_users_for_time("19:00")
            self.assertEqual(users_19, [(123, "РЗ 252")])
            self.assertEqual(manager.get_users_for_time("20:00"), [])

            # Disable notify
            manager.set_user_notify_time(123, None)
            self.assertFalse(manager.get_user_notify(123))
            self.assertIsNone(manager.get_user_notify_time(123))

            # Users by target
            users = manager.get_users_by_target("РЗ 252")
            self.assertEqual(users, [123])

            # check_and_reload when unchanged
            has_changed, changed = manager.check_and_reload()
            self.assertFalse(has_changed)
            self.assertEqual(changed, set())

    def test_render_week_image(self):
        from image_generator import render_week_image
        png = render_week_image("РЗ 252", date(2026, 11, 2))
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(png), 5000)

        # Teacher image
        t_png = render_week_image("Шаталов Н.А.", date(2026, 11, 2), is_teacher=True)
        self.assertTrue(t_png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(t_png), 5000)


class SubscriptionCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_member_check_is_cached(self):
        old = (subscription._BOT, subscription._CHANNEL_ID, subscription._ENABLED,
               subscription._CACHE_TTL, subscription._NEGATIVE_TTL)
        bot = SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member"))
        )
        try:
            subscription._BOT = bot
            subscription._CHANNEL_ID = "@test"
            subscription._ENABLED = True
            subscription._CACHE.clear()
            subscription._CACHE_TTL = 60
            subscription._NEGATIVE_TTL = 30
            self.assertTrue(await subscription.is_subscribed(1))
            self.assertTrue(await subscription.is_subscribed(1))
            self.assertEqual(bot.get_chat_member.await_count, 1)
        finally:
            (subscription._BOT, subscription._CHANNEL_ID, subscription._ENABLED,
             subscription._CACHE_TTL, subscription._NEGATIVE_TTL) = old
            subscription._CACHE.clear()


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

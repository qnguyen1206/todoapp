import ast
import re
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_APP = ROOT / "services" / "web_ui" / "app.py"


def load_daily_helpers():
    tree = ast.parse(WEB_APP.read_text(encoding="utf-8"))
    names = {
        "DAILY_RAW_RE", "DAILY_DAY_ORDER", "_parse_daily_raw", "_normalize_daily_schedules",
        "_daily_details", "_daily_schedule_for_day",
    }
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in names for target in node.targets
        ):
            selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            selected.append(node)
    namespace = {"re": re, "datetime": datetime}
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), str(WEB_APP), "exec"), namespace)
    return namespace


class DailyPerDayScheduleTests(unittest.TestCase):
    def test_different_weekdays_resolve_to_different_times(self):
        helpers = load_daily_helpers()
        details = helpers["_daily_details"]({"schedules": [
            {"days": ["Mon"], "start_time": "09:00", "end_time": "10:00"},
            {"days": ["Wed"], "start_time": "14:00", "end_time": "15:30"},
        ]}, "Mon,Wed 09:00-10:00 - Project meeting")

        self.assertEqual(helpers["_daily_schedule_for_day"](details, "Mon")["start_time"], "09:00")
        self.assertEqual(helpers["_daily_schedule_for_day"](details, "Wed")["start_time"], "14:00")
        self.assertIsNone(helpers["_daily_schedule_for_day"](details, "Fri"))

    def test_legacy_shared_time_tasks_remain_compatible(self):
        helpers = load_daily_helpers()
        details = helpers["_daily_details"]({}, "Mon,Wed 09:00-10:00 - Existing task")
        self.assertEqual(len(details["schedules"]), 1)
        self.assertEqual(details["schedules"][0]["days"], ["Mon", "Wed"])
        self.assertEqual(helpers["_daily_schedule_for_day"](details, "Wed")["end_time"], "10:00")

    def test_duplicate_day_time_groups_are_rejected(self):
        helpers = load_daily_helpers()
        with self.assertRaisesRegex(ValueError, "only have one time range|only have one|only have"):
            helpers["_normalize_daily_schedules"]([
                {"days": ["Mon"], "start_time": "09:00"},
                {"days": ["Mon"], "start_time": "14:00"},
            ])

    def test_ui_and_reminder_pipeline_include_per_day_schedules(self):
        template = (ROOT / "services" / "web_ui" / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")
        backend = (ROOT / "services" / "backend" / "app.py").read_text(encoding="utf-8")
        scheduler = (ROOT / "services" / "scheduler" / "app.py").read_text(encoding="utf-8")

        self.assertIn('id="daily-custom-times"', template)
        self.assertIn("{title, days, start_time, end_time, schedules, notes, reminder}", javascript)
        self.assertIn("recurring_schedule JSONB", backend)
        self.assertIn('reminder.get("recurring_schedule")', scheduler)

    def test_ai_is_told_to_keep_different_day_times_in_one_task(self):
        source = WEB_APP.read_text(encoding="utf-8")
        self.assertIn("one add_daily_task or update_daily_task call", source)
        self.assertIn("never create one task per day", source)
        self.assertIn('"schedules": parsed["schedules"]', source)
        self.assertIn('"recurring_schedule": daily_schedules', source)


if __name__ == "__main__":
    unittest.main()

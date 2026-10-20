import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

from calendar_view import CalendarView
from todo_list_manager import ToDoListManager


ROOT = Path(__file__).resolve().parents[1]


class DesktopCalendarContractTests(unittest.TestCase):
    def test_desktop_calendar_matches_unified_web_views(self):
        calendar_source = (ROOT / "calendar_view.py").read_text(encoding="utf-8")
        app_source = (ROOT / "todo.py").read_text(encoding="utf-8")

        self.assertIn('for mode in ("year", "month", "week", "day")', calendar_source)
        self.assertIn("def set_view_mode(self, mode):", calendar_source)
        self.assertIn("def _render_year_view(self):", calendar_source)
        self.assertIn("def _render_schedule_view(self, single_day=False):", calendar_source)
        self.assertIn("def go_to_date(self):", calendar_source)
        self.assertIn('text="Visible hours:"', calendar_source)
        self.assertIn('"start_hour": self.start_hour', calendar_source)
        self.assertIn("def _daily_task_definitions(self):", calendar_source)
        self.assertIn("def add_daily_task_indicator(self, container, tasks, cell_date, bg_color):", calendar_source)
        self.assertNotIn('text="📅 Schedule View"', app_source)

    def test_year_and_schedule_views_load_task_files_once_per_render(self):
        calendar_source = (ROOT / "calendar_view.py").read_text(encoding="utf-8")

        self.assertIn("todo_tasks = self.get_tasks()", calendar_source)
        self.assertIn("daily_definitions = self._daily_task_definitions()", calendar_source)
        self.assertIn("events_by_date = {", calendar_source)
        self.assertIn("self._tasks_for_date(target, todo_tasks, daily_definitions)", calendar_source)

    def test_desktop_regular_task_time_range_round_trips(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ToDoListManager.__new__(ToDoListManager)
            manager.TODO_FILE = str(Path(temp_dir) / "todo.txt")
            manager.parent_app = SimpleNamespace()
            task = ("Focused work", "10-15-2026", "09:00", "2", "Deep work", "11:30")

            manager.save_tasks([task], skip_mysql=True)

            self.assertEqual(manager.load_tasks(), [task])

    def test_regular_task_times_are_independently_optional(self):
        ToDoListManager._validate_task_time_range("", "17:00")
        ToDoListManager._validate_task_time_range("09:00", "")
        with self.assertRaisesRegex(ValueError, "after the start time"):
            ToDoListManager._validate_task_time_range("17:00", "09:00")

        calendar = CalendarView.__new__(CalendarView)
        calendar.parent_app = SimpleNamespace(use_24_hour=SimpleNamespace(get=lambda: True))
        self.assertEqual(calendar.format_task_time_range("", "17:00"), "Ends 17:00")


if __name__ == "__main__":
    unittest.main()

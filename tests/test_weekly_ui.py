import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WeeklyUIContractTests(unittest.TestCase):
    def test_date_only_tasks_use_a_separate_compact_note_area(self):
        template = (ROOT / "services" / "web_ui" / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "services" / "web_ui" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn('id="weekly-unscheduled"', template)
        self.assertIn("filter(task => !normalizeDueTime(task.due_time))", javascript)
        self.assertIn("No start time", javascript)
        self.assertIn("max-height: 76px", css)
        self.assertIn("grid.style.gridTemplateRows = `54px repeat(${visibleSlotCount}, 24px)`", javascript)

    def test_calendar_and_weekly_hover_text_use_the_task_title(self):
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertGreaterEqual(javascript.count('title="${escHtml(task.title)}"'), 2)
        self.assertIn('title="${escHtml(t.title)}"', javascript)
        self.assertNotIn("title=\"${task.type === 'daily' ? 'Recurring daily task' : 'Todo task'}\"", javascript)

    def test_end_of_day_events_reach_the_final_calendar_boundary(self):
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function weeklyEndSlot(value, startSlot)", javascript)
        self.assertIn("if (totalMinutes === 0 && startSlot > 0) return 96", javascript)
        self.assertIn("Math.ceil(totalMinutes / 15)", javascript)
        self.assertIn("Math.min(96, start + 1)", javascript)
        self.assertNotIn("Math.min(95, hour * 4 + Math.floor(minute / 15))", javascript)

    def test_regular_tasks_support_optional_start_and_end_times(self):
        template = (ROOT / "services" / "web_ui" / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")
        web_app = (ROOT / "services" / "web_ui" / "app.py").read_text(encoding="utf-8")
        backend = (ROOT / "services" / "backend" / "app.py").read_text(encoding="utf-8")

        self.assertIn('id="f-end-time"', template)
        self.assertIn("fmtTaskTimeRange(t)", javascript)
        self.assertIn("End time must be after start time", javascript)
        self.assertNotIn("Enter a start time before adding an end time", javascript)
        self.assertIn("if (due_time && end_time && end_time <= due_time)", javascript)
        self.assertIn("if start and end and end <= start", web_app)
        self.assertNotIn("needs a start time before its end time", backend)
        self.assertIn('"end_time": end_time', web_app)
        self.assertIn("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS end_time TEXT", backend)
        self.assertIn("t.due_time, t.end_time", backend)
        self.assertIn('if "end_time" in task', backend)
        self.assertIn('else "end_time = tasks.end_time"', backend)
        self.assertIn('end_time_supplied = "end_time" in data', web_app)
        self.assertIn("app.js?v=20261019-independent-task-times-v1", template)

    def test_calendar_combines_year_month_week_and_day_views(self):
        template = (ROOT / "services" / "web_ui" / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn('data-tab="weekly"', template)
        self.assertNotIn('id="tab-weekly"', template)
        for view in ("year", "month", "week", "day"):
            self.assertIn(f'data-calendar-view="{view}"', template)
        self.assertIn('id="calendar-start-hour"', template)
        self.assertIn('id="calendar-end-hour"', template)
        self.assertIn('id="calendar-date-picker"', template)
        self.assertIn("function setCalendarView(view)", javascript)
        self.assertIn("function jumpToCalendarDate(value)", javascript)
        self.assertIn("async function renderYearCalendar", javascript)
        self.assertIn("async function loadCalendarSchedule", javascript)
        self.assertIn("localStorage.setItem('calendarStartHour'", javascript)
        self.assertIn("Math.max(task._start, startSlot)", javascript)
        self.assertIn("Math.min(task._end, endSlot)", javascript)


if __name__ == "__main__":
    unittest.main()

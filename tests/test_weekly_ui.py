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
        self.assertIn("No due time", javascript)
        self.assertIn("max-height: 76px", css)
        self.assertIn("grid-template-rows: 54px", css)

    def test_calendar_and_weekly_hover_text_use_the_task_title(self):
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertGreaterEqual(javascript.count('title="${escHtml(task.title)}"'), 2)
        self.assertIn('title="${escHtml(t.title)}"', javascript)
        self.assertNotIn("title=\"${task.type === 'daily' ? 'Recurring daily task' : 'Todo task'}\"", javascript)


if __name__ == "__main__":
    unittest.main()

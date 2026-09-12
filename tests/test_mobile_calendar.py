import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MobileCalendarContractTests(unittest.TestCase):
    def test_mobile_calendar_uses_a_full_width_touch_grid_and_day_details(self):
        template = (ROOT / "services" / "web_ui" / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "services" / "web_ui" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn('id="calendar-mobile-grid"', template)
        self.assertIn('id="calendar-day-details"', template)
        self.assertIn("function selectCalendarDay(day)", javascript)
        self.assertIn("function renderCalendarDayDetails()", javascript)
        self.assertIn('data-calendar-day="${day}"', javascript)
        self.assertIn("calendarTasksByDay", javascript)
        self.assertIn(".calendar-mobile-grid", css)
        self.assertIn("grid-template-columns: repeat(7, minmax(0, 1fr))", css)
        self.assertIn("touch-action: manipulation", css)

    def test_mobile_calendar_does_not_force_a_wide_scroll_area(self):
        css = (ROOT / "services" / "web_ui" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertNotIn(".calendar-grid { min-width: 630px; }", css)
        self.assertNotIn(".calendar-grid { min-width: 560px; }", css)
        self.assertIn(".calendar-grid { display: none; }", css)


if __name__ == "__main__":
    unittest.main()

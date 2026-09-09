import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HealthDashboardContractTests(unittest.TestCase):
    def test_backend_health_executes_a_real_database_query(self):
        source = (ROOT / "services" / "backend" / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "health"
        )
        function_source = ast.get_source_segment(source, function)

        self.assertIn('cur.execute("SELECT 1")', function_source)
        self.assertIn('"database": {"status": "ok", "type": "postgresql"}', function_source)
        self.assertIn('"database": {"status": "error", "type": "postgresql"}', function_source)

    def test_system_health_checks_every_cvm_application_service_concurrently(self):
        source = (ROOT / "services" / "web_ui" / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "health_all"
        )
        function_source = ast.get_source_segment(source, function)

        for service in ("backend", "ai_inference", "task_sync", "scheduler", "openclaw", "postgres"):
            self.assertIn(f'"{service}"', function_source)
        self.assertIn("ThreadPoolExecutor", function_source)
        self.assertIn('"latency_ms"', function_source)

    def test_settings_renders_all_health_cards_and_feedback(self):
        template = (ROOT / "services" / "web_ui" / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "services" / "web_ui" / "static" / "style.css").read_text(encoding="utf-8")

        self.assertIn("System Health", template)
        self.assertIn('id="health-last-checked"', template)
        self.assertIn("PostgreSQL Database", javascript)
        self.assertIn("OpenClaw", javascript)
        self.assertIn("Checking all services", javascript)
        self.assertIn("Last check failed", javascript)
        self.assertIn("if (btn.dataset.tab === 'settings') {", javascript)
        self.assertIn("checkHealth();", javascript)
        self.assertIn(".health-grid", css)


if __name__ == "__main__":
    unittest.main()

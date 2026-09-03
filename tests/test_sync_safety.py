import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def function_source(relative_path, function_name):
    path = ROOT / relative_path
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        item for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == function_name
    )
    return ast.get_source_segment(source, node)


class SyncSafetyContractTests(unittest.TestCase):
    def test_normal_push_never_calls_force_replace(self):
        source = function_source("cvm_manager.py", "push_tasks_to_cvm")
        self.assertIn("backend_client.store_tasks", source)
        self.assertNotIn("force_replace_tasks", source)
        self.assertNotIn("replace_tasks", source)

    def test_force_push_is_the_only_menu_action_using_force_replace(self):
        source = function_source("cvm_manager.py", "force_push_tasks_to_cvm")
        self.assertIn("backend_client.force_replace_tasks", source)

    def test_legacy_generic_replace_method_is_blocked(self):
        source = function_source("cvm_client.py", "replace_tasks")
        self.assertNotIn("requests.post", source)
        self.assertIn("Unsafe replace blocked", source)

    def test_force_replace_requires_two_independent_confirmations(self):
        source = function_source("services/backend/app.py", "replace_tasks")
        self.assertIn("X-Confirm-Replace", source)
        self.assertIn("FORCE REPLACE ALL TASKS", source)

    def test_two_way_sync_preserves_existing_remote_collision(self):
        source = function_source("services/backend/app.py", "sync_tasks")
        self.assertIn("ON CONFLICT (user_id, task_id) DO NOTHING", source)

    def test_web_clear_does_not_use_full_replace(self):
        for name in ("clear_tasks_only", "clear_daily_only"):
            source = function_source("services/web_ui/app.py", name)
            self.assertNotIn("/tasks/replace", source)
            self.assertIn('"DELETE"', source)


if __name__ == "__main__":
    unittest.main()

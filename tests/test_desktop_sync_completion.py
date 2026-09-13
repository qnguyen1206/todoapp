import ast
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from cvm_manager import CVMManager


ROOT = Path(__file__).resolve().parents[1]


def function_source(relative_path, function_name):
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        item for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == function_name
    )
    return ast.get_source_segment(source, node)


class _ImmediateRoot:
    def after(self, _delay, callback):
        callback()


class _TodoStore:
    def __init__(self):
        self.saved = None
        self.refreshed = False

    def save_tasks(self, tasks, skip_mysql=False):
        self.saved = (tasks, skip_mysql)

    def refresh_task_list(self):
        self.refreshed = True


class DesktopSyncCompletionTests(unittest.TestCase):
    def test_completed_remote_todos_are_not_restored_as_active(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _TodoStore()
            manager = CVMManager.__new__(CVMManager)
            manager.parent_app = SimpleNamespace(
                root=_ImmediateRoot(), todo_list_manager=store
            )
            manager._daily_file_path = lambda: str(Path(temp_dir) / "daily.txt")
            manager._task_id_map_path = lambda: Path(temp_dir) / "task_ids.json"

            applied = manager._apply_remote_tasks([
                {
                    "id": "todo:active", "title": "Keep me", "due_date": "09-14-2026",
                    "due_time": "10:00", "priority": 2, "notes": "active",
                    "completed": False,
                },
                {
                    "id": "todo:done", "title": "Already done", "due_date": "09-13-2026",
                    "due_time": "09:00", "priority": 1, "notes": "finished",
                    "completed": True,
                },
            ])

            self.assertEqual(applied, 1)
            self.assertEqual(store.saved, ([
                ("Keep me", "09-14-2026", "10:00", "2", "active")
            ], True))
            self.assertTrue(store.refreshed)

    def test_pending_completion_is_durable_until_acknowledged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "mutations.json"
            manager = CVMManager.__new__(CVMManager)
            manager._pending_mutations_lock = threading.RLock()
            manager._pending_mutations_path = lambda: state_path
            manager._task_id_map_path = lambda: Path(temp_dir) / "task_ids.json"
            task = ("Finish report", "09-14-2026", "17:00", "1", "notes")

            manager.record_local_task_completion(task)
            snapshot = manager._pending_mutations_snapshot()
            expected_id = manager._todo_task_id(task)
            self.assertEqual(snapshot["completed"], {expected_id})
            self.assertTrue(state_path.exists())

            manager._acknowledge_pending_mutations(snapshot)
            self.assertEqual(manager._pending_mutations_snapshot()["completed"], set())

    def test_web_task_keeps_its_server_id_when_completed_on_desktop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _TodoStore()
            manager = CVMManager.__new__(CVMManager)
            manager._pending_mutations_lock = threading.RLock()
            manager.parent_app = SimpleNamespace(
                root=_ImmediateRoot(), todo_list_manager=store
            )
            manager._daily_file_path = lambda: str(Path(temp_dir) / "daily.txt")
            manager._task_id_map_path = lambda: Path(temp_dir) / "task_ids.json"
            manager._pending_mutations_path = lambda: Path(temp_dir) / "mutations.json"
            remote = {
                "id": "web-generated-uuid", "title": "Web meeting",
                "due_date": "09-15-2026", "due_time": "14:00",
                "priority": 2, "notes": "", "completed": False,
            }

            manager._apply_remote_tasks([remote])
            manager.record_local_task_completion(
                ("Web meeting", "09-15-2026", "14:00", "2", "")
            )

            self.assertEqual(
                manager._pending_mutations_snapshot()["completed"],
                {"web-generated-uuid"},
            )

    def test_desktop_finish_and_sync_are_wired_to_completion_mutations(self):
        finish_source = function_source("todo_list_manager.py", "remove_task")
        sync_source = function_source("cvm_manager.py", "sync_tasks_with_cvm")
        backend_source = function_source("services/backend/app.py", "sync_tasks")

        self.assertIn("record_local_task_completion", finish_source)
        self.assertIn("completed_task_ids", sync_source)
        self.assertIn("completed_task_ids", backend_source)
        self.assertIn("SET completed = TRUE", backend_source)


if __name__ == "__main__":
    unittest.main()

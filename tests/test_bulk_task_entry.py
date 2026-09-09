import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_APP = ROOT / "services" / "web_ui" / "app.py"


class BulkTaskEntryTests(unittest.TestCase):
    def test_web_ui_exposes_a_non_ai_bulk_entry_and_preview(self):
        template = (ROOT / "services" / "web_ui" / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('onclick="openBulkTaskModal()"', template)
        self.assertIn('id="bulk-task-input"', template)
        self.assertIn("works without AI", template)
        self.assertIn("function parseBulkTaskLine", javascript)
        self.assertIn("function renderBulkTaskPreview", javascript)
        self.assertIn("today|tomorrow", javascript)
        self.assertIn("Task | date | time | priority | notes", template)

    def test_bulk_save_uses_one_atomic_backend_store(self):
        source = WEB_APP.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "add_tasks_bulk"
        )
        function_source = ast.get_source_segment(source, function)

        self.assertIn('data.get("tasks")', function_source)
        self.assertIn("uuid.uuid4()", function_source)
        self.assertIn("_encrypt_tasks(tasks, user_id)", function_source)
        self.assertEqual(function_source.count('"/tasks/store"'), 1)
        self.assertNotIn("range(12)", function_source)

    def test_invalid_lines_block_the_entire_client_batch(self):
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("tasks.some(task => !task.valid)", javascript)
        self.assertIn("Nothing will be saved until every line is valid", javascript)
        self.assertIn("'/api/tasks/bulk'", javascript)
        self.assertIn("await loadTasks()", javascript)


class BulkTaskActionTests(unittest.TestCase):
    def test_task_table_has_row_and_select_all_controls(self):
        template = (ROOT / "services" / "web_ui" / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="select-all-tasks"', template)
        self.assertIn('id="task-bulk-actions"', template)
        self.assertIn('id="task-bulk-actions" class="task-bulk-actions" hidden', template)
        self.assertIn("document.getElementById('task-bulk-actions').hidden = count === 0", javascript)
        self.assertNotIn("button.disabled = count === 0", javascript)
        self.assertIn("Select at least one task first.", javascript)
        self.assertIn("function checkedTaskIds()", javascript)
        self.assertIn("syncTaskSelectionFromDOM()", javascript)
        self.assertIn("}).join('');\n  updateTaskSelectionUI(tasks);", javascript)
        self.assertIn("toggleTaskSelection", javascript)
        self.assertIn("toggleAllVisibleTasks", javascript)
        self.assertIn("selectedTaskIds", javascript)

    def test_finish_and_delete_are_atomic_backend_batches(self):
        backend = (ROOT / "services" / "backend" / "app.py").read_text(encoding="utf-8")
        web_app = WEB_APP.read_text(encoding="utf-8")

        self.assertIn('@app.route("/tasks/batch/complete"', backend)
        self.assertIn('@app.route("/tasks/batch/delete"', backend)
        self.assertIn("task_id = ANY(%s)", backend)
        self.assertIn('DELETE FROM task_reminders WHERE user_id = %s AND task_id = ANY(%s)', backend)
        self.assertIn('"/tasks/batch/complete"', web_app)
        self.assertIn('"/tasks/batch/delete"', web_app)
        self.assertIn("Never report", web_app)

    def test_bulk_edit_changes_only_selected_fields_in_one_store(self):
        source = WEB_APP.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "edit_tasks_bulk"
        )
        function_source = ast.get_source_segment(source, function)

        self.assertIn('{"due_date", "due_time", "priority", "notes"}', function_source)
        self.assertIn("Some selected tasks no longer exist", function_source)
        self.assertEqual(function_source.count('"/tasks/store"'), 1)
        self.assertIn("_encrypt_tasks(edited, user_id)", function_source)

    def test_bulk_edit_ui_uses_opt_in_fields(self):
        template = (ROOT / "services" / "web_ui" / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")

        for field in ("date", "time", "priority", "notes"):
            self.assertIn(f'id="bulk-edit-{field}-enabled"', template)
        self.assertIn("Check at least one field to change", javascript)
        self.assertIn("'/api/tasks/bulk/edit'", javascript)


if __name__ == "__main__":
    unittest.main()

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_APP = ROOT / "services" / "web_ui" / "app.py"


def function_source(function_name):
    source = WEB_APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        item for item in ast.walk(tree)
        if isinstance(item, ast.FunctionDef) and item.name == function_name
    )
    return ast.get_source_segment(source, node)


class AIToolOrchestrationContractTests(unittest.TestCase):
    def test_round_limit_is_50_and_is_not_a_tool_call_limit(self):
        source = WEB_APP.read_text(encoding="utf-8")
        self.assertIn("MAX_AI_TOOL_ROUNDS = 50", source)
        self.assertNotIn("12-round", source)
        self.assertIn("A tool round may contain any ", source)
        self.assertIn("number of tool calls", source)

    def test_successful_mutations_return_recorded_tool_results_immediately(self):
        source = function_source("ai_chat_tools")
        self.assertIn("successful_actions.append(result_payload.get(\"message\")", source)
        self.assertIn("if successful_actions:\n                return action_summary()", source)
        self.assertIn('"actions": successful_actions', source)

    def test_successful_mutations_are_not_executed_twice(self):
        source = function_source("ai_chat_tools")
        self.assertIn("seen_successful_mutations", source)
        self.assertIn('"duplicate": True', source)

    def test_many_adds_are_requested_in_one_model_response(self):
        source = function_source("ai_chat_tools")
        self.assertIn("issue every add tool call together in the same response", source)
        self.assertIn("adding a new task does not require a get call", source)

    def test_web_and_worker_timeouts_allow_multi_step_tool_requests(self):
        javascript = (ROOT / "services" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")
        dockerfile = (ROOT / "services" / "web_ui" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("}, 300000);", javascript)
        self.assertIn('"--timeout", "300"', dockerfile)


if __name__ == "__main__":
    unittest.main()

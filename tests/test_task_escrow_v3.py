import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TaskEscrowV3Tests(unittest.TestCase):
    def read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_contract_has_fixed_recipient_release_and_deadline_refund(self):
        contract = self.read("contracts/TaskRewardEscrow.sol")
        self.assertIn("function createEscrow(bytes32 key, address recipient, uint64 deadline) external payable", contract)
        self.assertIn("if (msg.sender != escrow.sponsor) revert Unauthorized()", contract)
        self.assertIn("block.timestamp < escrow.deadline", contract)
        self.assertIn("escrow.state = State.Released", contract)
        self.assertIn("escrow.state = State.Refunded", contract)
        self.assertIn("msg.value > type(uint96).max", contract)
        self.assertNotIn("delegatecall", contract)

    def test_wallet_only_exposes_policy_bound_escrow_actions(self):
        wallet = self.read("services/wallet/app.py")
        self.assertIn('"create":', wallet)
        self.assertIn('"release": "release(bytes32)"', wallet)
        self.assertIn('"refund": "refund(bytes32)"', wallet)
        self.assertIn("Task escrow is restricted to Base Sepolia", wallet)
        self.assertIn('if str(data.get("data", "")).lower() != calldata.lower()', wallet)
        self.assertIn('/v1/escrows/authorize', wallet)
        self.assertNotIn('/v1/escrows/arbitrary', wallet)

    def test_backend_enforces_task_and_confirmation_lifecycle(self):
        backend = self.read("services/backend/app.py")
        self.assertIn("CREATE TABLE IF NOT EXISTS task_escrows", backend)
        self.assertIn("Complete the task before releasing its reward", backend)
        self.assertIn("Refund is available only after the escrow deadline", backend)
        self.assertIn("Settle or refund this task's escrow before deleting it", backend)
        self.assertIn("Settle or refund all task escrows before replacing the task list", backend)
        self.assertIn('authorization_path = "/v1/escrows/authorize"', backend)
        self.assertIn("failure_status = \"failed\" if action == \"create\" else \"funded\"", backend)

    def test_ui_and_compose_keep_escrow_disabled_by_default(self):
        template = self.read("services/web_ui/templates/index.html")
        script = self.read("services/web_ui/static/app.js")
        compose = self.read("docker-compose.yml")
        self.assertIn('id="task-escrow-form"', template)
        self.assertIn("async function prepareTaskEscrow()", script)
        self.assertIn("async function prepareTaskEscrowAction", script)
        self.assertIn("task?.completed === true", script)
        self.assertIn("TASK_ESCROW_ENABLED: ${TASK_ESCROW_ENABLED:-false}", compose)
        self.assertIn("TASK_ESCROW_CONTRACT_ADDRESS", compose)


if __name__ == "__main__":
    unittest.main()

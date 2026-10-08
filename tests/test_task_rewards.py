import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class TaskRewardContractTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_xp_is_backend_authoritative_and_idempotent_per_task(self):
        backend = self.read("services/backend/app.py")
        self.assertIn("import hashlib", backend)
        self.assertIn("CREATE TABLE IF NOT EXISTS task_reward_events", backend)
        self.assertIn("PRIMARY KEY (user_id, task_id)", backend)
        self.assertIn("ON CONFLICT (user_id, task_id) DO NOTHING RETURNING xp_awarded", backend)
        self.assertIn("_record_task_completion_rewards", backend)
        self.assertIn("SAVEPOINT task_reward_award", backend)
        self.assertIn("Task completed, but rewards are temporarily unavailable", backend)
        self.assertIn('"rewards": rewards', backend)
        self.assertIn("def _reconcile_completed_task_rewards", backend)
        self.assertIn("_reconcile_completed_task_rewards(cur, g.user_id)", backend)
        self.assertIn("cur, user_id, [task_id]", backend)
        self.assertIn("pg_advisory_xact_lock(hashtext('todoapp-reward-schema'))", backend)

    def test_badge_issuer_is_narrow_and_base_sepolia_only(self):
        wallet = self.read("services/wallet/app.py")
        self.assertIn("mintAchievement(address,uint256,bytes32)", wallet)
        self.assertIn("REWARD_ALLOWED_ACHIEVEMENT_IDS = {1, 10, 50, 100}", wallet)
        self.assertIn("Achievement badges are restricted to Base Sepolia", wallet)
        self.assertIn("/v1/rewards/authorize-achievement", wallet)
        self.assertNotIn("/v1/rewards/arbitrary-call", wallet)

    def test_solidity_badges_are_single_use_and_non_transferable(self):
        contract = self.read("contracts/TodoAchievements.sol")
        self.assertIn('require(msg.sender == issuer, "issuer only")', contract)
        self.assertIn('require(!usedClaims[claimId], "claim already used")', contract)
        self.assertIn('require(!earned[recipient][achievementId]', contract)
        self.assertGreaterEqual(contract.count('revert("badges are non-transferable")'), 3)

    def test_rewards_ui_and_safe_disabled_default_exist(self):
        template = self.read("services/web_ui/templates/index.html")
        script = self.read("services/web_ui/static/app.js")
        compose = self.read("docker-compose.yml")
        self.assertIn('id="reward-achievements"', template)
        self.assertIn("async function loadRewards()", script)
        self.assertIn("async function mintAchievement", script)
        self.assertIn('id="claim-all-badges"', template)
        self.assertIn("async function claimEarnedBadges", script)
        self.assertIn("Badges are free to claim", script)
        reward_loader = script[script.index("async function loadRewards()") : script.index("async function mintAchievement")]
        self.assertIn("renderCharacterStats(stats)", reward_loader)
        self.assertNotIn("loadCharacter();", reward_loader)
        self.assertIn("renderCharacterStats(result.rewards)", script)
        self.assertIn("xpBadge.textContent = `XP ${totalXp}`", script)
        self.assertIn("REWARD_BADGES_ENABLED: ${REWARD_BADGES_ENABLED:-false}", compose)

    def test_add_task_resets_stale_native_date_picker(self):
        script = self.read("services/web_ui/static/app.js")
        open_add_task = script[script.index("function openAddTask()") : script.index("function openEditTask")]
        self.assertIn("nativeTaskDatePicker.value = '';", open_add_task)
        self.assertIn("setCustomValidity('')", open_add_task)
        self.assertIn("choosing the same date for a new task", script)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ClawdiConnectorContractTests(unittest.TestCase):
    def test_openclaw_image_pins_clawdi_cli(self):
        dockerfile = (ROOT / "services" / "openclaw" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ARG CLAWDI_VERSION=", dockerfile)
        self.assertIn('"clawdi@${CLAWDI_VERSION}"', dockerfile)
        self.assertNotIn("clawdi@latest", dockerfile)

    def test_connector_is_optional_private_and_persistent(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        connector = compose.split("  clawdi_connector:", 1)[1].split("\n  # ---", 1)[0]
        self.assertIn("CLAWDI_ENABLED: ${CLAWDI_ENABLED:-false}", connector)
        self.assertIn('CLAWDI_NO_AUTO_UPDATE: "1"', connector)
        self.assertIn("clawdi daemon run", connector)
        self.assertIn("clawdi_data:/home/node/.clawdi", connector)
        self.assertIn("OPENCLAW_STATE_DIR: /home/node/.openclaw", connector)
        self.assertIn("OPENCLAW_CONFIG_PATH: /home/node/.openclaw/openclaw.json", connector)
        self.assertIn("OPENCLAW_WORKSPACE_DIR: /home/node/.openclaw/workspace", connector)
        self.assertIn("OPENCLAW_AGENT_ID: main", connector)
        self.assertIn("OPENCLAW_GATEWAY_URL: ws://openclaw:18789", connector)
        self.assertIn("OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN}", connector)
        self.assertIn('test: ["CMD", "clawdi", "--version"]', connector)
        self.assertNotIn("disable: true", connector)
        self.assertNotIn("ports:", connector)
        self.assertNotIn("docker.sock", connector)

    def test_connector_shares_only_agent_state_not_database_storage(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        connector = compose.split("  clawdi_connector:", 1)[1].split("\n  # ---", 1)[0]
        self.assertIn("openclaw_data:/home/node/.openclaw", connector)
        self.assertIn("openclaw_auth:/home/node/.config/openclaw", connector)
        self.assertNotIn("postgres_data", connector)
        self.assertNotIn("backend_data", connector)


if __name__ == "__main__":
    unittest.main()

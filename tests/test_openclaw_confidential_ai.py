import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIGURATOR = ROOT / "services" / "openclaw" / "configure-openclaw.mjs"


@unittest.skipUnless(shutil.which("node"), "Node.js is required for the OpenClaw config test")
class OpenClawConfidentialAIConfigTests(unittest.TestCase):
    def run_configurator(self, initial_config=None, **environment):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "openclaw.json"
            if initial_config is not None:
                config_path.write_text(json.dumps(initial_config), encoding="utf-8")
            env = os.environ.copy()
            env.update({
                "OPENCLAW_CONFIG_PATH": str(config_path),
                "OPENCLAW_ALLOWED_ORIGINS": "https://cloud.phala.com",
                **environment,
            })
            result = subprocess.run(
                [shutil.which("node"), str(CONFIGURATOR)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else None
            return result, config

    def test_enabled_mode_registers_phala_without_persisting_the_secret(self):
        secret = "phala-test-secret-that-must-not-be-written"
        result, config = self.run_configurator(
            {"unrelated": {"preserved": True}},
            OPENCLAW_CONFIDENTIAL_AI_ENABLED="true",
            PHALA_AI_API_KEY=secret,
            OPENCLAW_CONFIDENTIAL_AI_MODEL="deepseek/deepseek-v4-flash",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        provider = config["models"]["providers"]["phala"]
        model_ref = "phala/deepseek/deepseek-v4-flash"
        self.assertEqual(provider["baseUrl"], "https://inference.phala.com/v1")
        self.assertEqual(provider["api"], "openai-completions")
        self.assertEqual(provider["apiKey"], "${PHALA_AI_API_KEY}")
        self.assertNotIn(secret, json.dumps(config))
        self.assertEqual(config["agents"]["defaults"]["model"]["primary"], model_ref)
        self.assertTrue(
            config["agents"]["defaults"]["models"][model_ref]
            ["params"]["extra_body"]["provider"]["aci_verified"]
        )
        self.assertTrue(config["unrelated"]["preserved"])

    def test_enabled_mode_fails_closed_without_an_api_key(self):
        result, _ = self.run_configurator(
            {},
            OPENCLAW_CONFIDENTIAL_AI_ENABLED="true",
            PHALA_AI_API_KEY="",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PHALA_AI_API_KEY is empty", result.stderr)

    def test_disabled_mode_preserves_existing_model_configuration(self):
        initial = {"agents": {"defaults": {"model": {"primary": "openai/example"}}}}
        result, config = self.run_configurator(
            initial,
            OPENCLAW_CONFIDENTIAL_AI_ENABLED="false",
            PHALA_AI_API_KEY="",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(config["agents"]["defaults"]["model"]["primary"], "openai/example")
        self.assertNotIn("models", config)


class OpenClawComposeContractTests(unittest.TestCase):
    def test_compose_uses_the_configured_openclaw_image_and_secure_environment(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("image: kairu1206/cvm-openclaw:latest", compose)
        self.assertIn("PHALA_AI_API_KEY: ${PHALA_AI_API_KEY}", compose)
        self.assertIn("OPENCLAW_CONFIDENTIAL_AI_ENABLED:", compose)
        self.assertIn("node /opt/todoapp/configure-openclaw.mjs", compose)


if __name__ == "__main__":
    unittest.main()

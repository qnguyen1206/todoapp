import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class WalletIntegrationContractTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_compose_keeps_wallet_internal_and_mounts_dstack_socket(self):
        compose = self.read("docker-compose.yml")
        wallet_block = compose.split("\n  wallet:\n", 1)[1].split("\n  backend:\n", 1)[0]
        self.assertIn('expose:\n      - "5004"', wallet_block)
        self.assertNotIn("ports:", wallet_block)
        self.assertIn("/var/run/dstack.sock:/var/run/dstack.sock:ro", wallet_block)

    def test_web_has_wallet_tab_and_controlled_send_controls(self):
        template = self.read("services/web_ui/templates/index.html")
        script = self.read("services/web_ui/static/app.js")
        self.assertIn('data-tab="wallet"', template)
        self.assertIn('id="wallet-qr"', template)
        self.assertIn("Send testnet ETH", template)
        self.assertIn("password and email confirmation", template)
        self.assertIn("async function loadWallet()", script)

    def test_wallet_service_has_only_policy_bound_testnet_transfer_endpoints(self):
        source = self.read("services/wallet/app.py")
        route_lines = [line for line in source.splitlines() if "@app.route" in line]
        self.assertTrue(any("quote-transfer" in line for line in route_lines))
        self.assertTrue(any("authorize-transfer" in line for line in route_lines))
        self.assertFalse(any('"/sign"' in line or "sign-message" in line for line in route_lines))
        self.assertIn("to_account_secure", source)
        self.assertIn("SEND_ENABLED_CHAIN_IDS = {84532}", source)
        self.assertIn("Wallet v2 cannot send to smart contracts", source)

    def test_wallet_helper_does_not_interrupt_verification_email_function(self):
        backend = self.read("services/backend/app.py")
        verification_body = backend.split("def _send_verification_code", 1)[1].split(
            "def _wallet_headers", 1
        )[0]
        self.assertIn("smtplib.SMTP", verification_body)
        self.assertIn("return True", verification_body)
        self.assertIn("Wallet derivation identity changed", backend)

    def test_send_flow_requires_reauthentication_otp_idempotency_and_nonce_lock(self):
        backend = self.read("services/backend/app.py")
        self.assertIn("verify_password(password", backend)
        self.assertIn('hash_token(f"wallet:{parsed_id}:{code}")', backend)
        self.assertIn("pg_advisory_xact_lock", backend)
        self.assertIn("idempotency_key", backend)
        self.assertIn("password_attempts", backend)
        self.assertIn("Another transfer already uses this nonce", backend)
        self.assertGreaterEqual(backend.count("Daily transfer limit is"), 2)
        self.assertIn("raw_transaction=NULL", backend)


if __name__ == "__main__":
    unittest.main()

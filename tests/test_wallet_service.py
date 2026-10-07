import importlib.util
import pathlib
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
if importlib.util.find_spec("flask") is None:
    raise unittest.SkipTest("wallet service dependencies are not installed in the desktop test environment")
SPEC = importlib.util.spec_from_file_location(
    "todo_wallet_service", ROOT / "services" / "wallet" / "app.py"
)
wallet_service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wallet_service)


class WalletServiceTests(unittest.TestCase):
    def setUp(self):
        self.original_api_key = wallet_service.API_KEY
        self.original_environment = wallet_service.ENVIRONMENT
        wallet_service.API_KEY = "test-internal-key"
        wallet_service.ENVIRONMENT = "production"
        self.client = wallet_service.app.test_client()

    def tearDown(self):
        wallet_service.API_KEY = self.original_api_key
        wallet_service.ENVIRONMENT = self.original_environment

    def headers(self):
        return {"X-API-Key": "test-internal-key"}

    def test_derivation_path_is_deterministic_and_hides_user_id(self):
        path_a = wallet_service._derivation_path("1234567890abcdef")
        path_b = wallet_service._derivation_path("1234567890abcdef")
        self.assertEqual(path_a, path_b)
        self.assertNotIn("1234567890abcdef", path_a)
        self.assertIn("/eip155/", path_a)

    def test_internal_routes_require_api_key(self):
        response = self.client.post("/v1/wallets/derive", json={"user_id": "1234567890abcdef"})
        self.assertEqual(response.status_code, 401)

    def test_derive_returns_public_receive_metadata_only(self):
        with patch.object(wallet_service, "_derive_address", return_value="0x" + "a" * 40):
            response = self.client.post(
                "/v1/wallets/derive",
                headers=self.headers(),
                json={"user_id": "1234567890abcdef"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["address"], "0x" + "a" * 40)
        self.assertEqual(payload["mode"], "receive-only")
        self.assertNotIn("private_key", payload)
        self.assertNotIn("mnemonic", payload)

    def test_portfolio_combines_balance_and_history(self):
        address = "0x" + "b" * 40
        balance = {"wei": "1", "formatted": "0.000000000000000001", "symbol": "ETH"}
        with (
            patch.object(wallet_service, "_native_balance", return_value=balance),
            patch.object(wallet_service, "_transaction_history", return_value=([], True, "")),
        ):
            response = self.client.post(
                "/v1/wallets/portfolio", headers=self.headers(), json={"address": address}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["balance"], balance)

    def test_only_narrow_transfer_routes_exist(self):
        rules = {rule.rule for rule in wallet_service.app.url_map.iter_rules()}
        self.assertIn("/v1/wallets/quote-transfer", rules)
        self.assertIn("/v1/wallets/authorize-transfer", rules)
        self.assertIn("/v1/wallets/broadcast", rules)
        self.assertFalse(any(rule.endswith("/sign") or "message" in rule for rule in rules))
        self.assertEqual(wallet_service.SEND_ENABLED_CHAIN_IDS, {84532})


if __name__ == "__main__":
    unittest.main()

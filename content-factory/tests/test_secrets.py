import os
import tempfile
import unittest
from pathlib import Path

from yula_factory.secrets import config_value, delete_config_value, save_config_value


class SecretVaultTests(unittest.TestCase):
    def test_plain_and_dpapi_values_round_trip(self):
        original = os.environ.get("YULA_CREDENTIAL_VAULT")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "providers.local.json"
            os.environ["YULA_CREDENTIAL_VAULT"] = str(path)
            try:
                save_config_value("PUBLIC_ID", "123", secret=False)
                save_config_value("PRIVATE_TOKEN", "secret-value", secret=True)
                self.assertEqual(config_value("PUBLIC_ID"), "123")
                self.assertEqual(config_value("PRIVATE_TOKEN"), "secret-value")
                self.assertNotIn("secret-value", path.read_text(encoding="utf-8"))
                self.assertTrue(delete_config_value("PRIVATE_TOKEN"))
                self.assertEqual(config_value("PRIVATE_TOKEN"), "")
                self.assertFalse(delete_config_value("PRIVATE_TOKEN"))
            finally:
                if original is None:
                    os.environ.pop("YULA_CREDENTIAL_VAULT", None)
                else:
                    os.environ["YULA_CREDENTIAL_VAULT"] = original


if __name__ == "__main__":
    unittest.main()

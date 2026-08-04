from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from yula_factory.pexels import _api_key


class PexelsCredentialTests(unittest.TestCase):
    def test_api_key_uses_shared_secure_configuration(self):
        with patch.dict(os.environ, {"PEXELS_API_KEY": "test-key"}, clear=False):
            self.assertEqual(_api_key(), "test-key")


if __name__ == "__main__":
    unittest.main()

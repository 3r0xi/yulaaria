from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ContentRootOverrideTests(unittest.TestCase):
    def test_environment_override_is_used(self):
        with tempfile.TemporaryDirectory() as temp:
            expected = Path(temp).resolve()
            environment = dict(os.environ)
            environment["YULA_CONTENT_ROOT"] = str(expected)
            result = subprocess.run(
                [sys.executable, "-c", "from yula_factory.paths import CONTENT_ROOT; print(CONTENT_ROOT.resolve())"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(Path(result.stdout.strip()), expected)


if __name__ == "__main__":
    unittest.main()

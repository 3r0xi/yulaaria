import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import yula_factory.paths as paths
from yula_factory.storage import object_key, stage_media


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.original_root = paths.CONTENT_ROOT
        self.original_bucket = os.environ.get("R2_BUCKET_NAME")

    def tearDown(self):
        paths.CONTENT_ROOT = self.original_root
        if self.original_bucket is None:
            os.environ.pop("R2_BUCKET_NAME", None)
        else:
            os.environ["R2_BUCKET_NAME"] = self.original_bucket

    def test_object_key_is_content_addressed_and_stage_returns_signed_url(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths.CONTENT_ROOT = root
            media = root / "clip.mp4"
            media.write_bytes(b"same-media")
            os.environ["R2_BUCKET_NAME"] = "media"
            client = Mock()
            client.generate_presigned_url.return_value = "https://example.invalid/signed"

            result = stage_media(media, "2026-08-10", 24, client=client, db_path=root / "state.sqlite3")

            self.assertEqual(result["status"], "staged")
            self.assertTrue(result["object_key"].startswith("yula-aria/2026-08-10/"))
            self.assertEqual(result["object_key"], object_key(media, "2026-08-10"))
            self.assertEqual(result["expires_in_seconds"], 86400)
            client.upload_file.assert_called_once()

    def test_expiration_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths.CONTENT_ROOT = root
            media = root / "clip.mp4"
            media.write_bytes(b"data")
            os.environ["R2_BUCKET_NAME"] = "media"
            with self.assertRaises(ValueError):
                stage_media(media, "2026-08-10", 169, client=Mock(), db_path=root / "state.sqlite3")


if __name__ == "__main__":
    unittest.main()

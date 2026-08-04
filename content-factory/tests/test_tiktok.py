import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from yula_factory import tiktok


class TikTokTests(unittest.TestCase):
    def test_chunk_plan_is_single_below_limit_and_multiple_above(self):
        self.assertEqual(tiktok.chunk_plan(4_000_000), (4_000_000, 1))
        chunk_size, count = tiktok.chunk_plan(70 * 1024 * 1024)
        self.assertGreaterEqual(chunk_size, tiktok.MIN_CHUNK)
        self.assertGreaterEqual(count, 2)

    def test_unaudited_client_is_forced_private(self):
        creator = {"privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]}
        with patch.dict(os.environ, {"TIKTOK_APP_AUDITED": "0"}, clear=False):
            with self.assertRaises(PermissionError):
                tiktok._privacy({"privacy_level": "PUBLIC_TO_EVERYONE"}, creator)
            self.assertEqual(tiktok._privacy({"privacy_level": "SELF_ONLY"}, creator), "SELF_ONLY")

    def test_video_publish_builds_direct_post_and_uploads_local_file(self):
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "clip.mp4"
            video.write_bytes(b"0" * 1024)
            creator = {
                "privacy_level_options": ["SELF_ONLY"],
                "max_video_post_duration_sec": 180,
                "comment_disabled": False,
                "duet_disabled": False,
                "stitch_disabled": False,
            }
            response = {"publish_id": "pub-123", "upload_url": "https://upload.example/video"}
            with patch("yula_factory.tiktok._json_request", return_value=response) as request, patch("yula_factory.tiktok._upload_video") as upload:
                result = tiktok._video_post({
                    "media_path": str(video),
                    "media_type": "video",
                    "text": "A quiet reset",
                    "duration_seconds": 12,
                }, creator, "token-not-logged")
            self.assertEqual(result["external_id"], "pub-123")
            self.assertEqual(request.call_args.args[0], "/v2/post/publish/video/init/")
            self.assertEqual(request.call_args.args[2]["source_info"]["source"], "FILE_UPLOAD")
            upload.assert_called_once()

    def test_status_request_uses_publish_id(self):
        with patch("yula_factory.tiktok._access_token", return_value="token"), patch("yula_factory.tiktok._json_request", return_value={"status": "PUBLISH_COMPLETE"}) as request:
            result = tiktok.fetch_status("pub-123")
        self.assertEqual(result["status"], "PUBLISH_COMPLETE")
        self.assertEqual(request.call_args.args[2], {"publish_id": "pub-123"})


if __name__ == "__main__":
    unittest.main()

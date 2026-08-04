import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yula_factory.paths as paths
from yula_factory.media_host import create_signed_media_url, resolve_signed_media_url


class MediaHostTests(unittest.TestCase):
    def setUp(self):
        self.original_root = paths.CONTENT_ROOT

    def tearDown(self):
        paths.CONTENT_ROOT = self.original_root

    def test_signed_url_round_trip_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            paths.CONTENT_ROOT = Path(temp)
            media = Path(temp) / "clip.mp4"
            media.write_bytes(b"media")
            with patch("yula_factory.media_host.required_value", return_value="test-key"):
                url = create_signed_media_url(media, "https://example.trycloudflare.com", 1, now=1000)
                self.assertEqual(resolve_signed_media_url(url, now=1001), media.resolve())
                with self.assertRaises(PermissionError):
                    resolve_signed_media_url(url.replace("sig=", "sig=bad"), now=1001)

    def test_expired_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            paths.CONTENT_ROOT = Path(temp)
            media = Path(temp) / "image.jpg"
            media.write_bytes(b"image")
            with patch("yula_factory.media_host.required_value", return_value="test-key"):
                url = create_signed_media_url(media, "https://example.trycloudflare.com", 1, now=1000)
                with self.assertRaises(PermissionError):
                    resolve_signed_media_url(url, now=4601)


if __name__ == "__main__":
    unittest.main()

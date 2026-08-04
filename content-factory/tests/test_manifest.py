import json
import tempfile
import unittest
from pathlib import Path

from yula_factory.manifest import validate_manifest


def valid_planned_manifest() -> dict:
    platform = {"caption": "x", "hashtags": [], "music_search": "none", "music_reuse_policy": "original only"}
    return {
        "schema_version": "1.0",
        "production_status": "planned",
        "day": 1,
        "publish_date": "2026-08-01",
        "theme": "Notice more",
        "cover_text": "NOTICE MORE",
        "folder": "2026-08-01_D01_NOTICE_MORE",
        "sources": [],
        "render": {"width": 1080, "height": 1920, "video_codec": "h264", "music_policy": "no_music_platform_added", "duration_seconds": 12},
        "platforms": {name: dict(platform) for name in ("instagram", "facebook", "tiktok", "youtube_shorts", "threads", "x")},
    }


class ManifestTests(unittest.TestCase):
    def test_valid_planned_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            path.write_text(json.dumps(valid_planned_manifest()), encoding="utf-8")
            self.assertEqual(validate_manifest(path), [])

    def test_rejects_wrong_date_and_platform_set(self):
        data = valid_planned_manifest()
        data["publish_date"] = "2026-08-02"
        del data["platforms"]["x"]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            errors = validate_manifest(path)
        self.assertTrue(any("publish_date" in error for error in errors))
        self.assertTrue(any("platforms" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

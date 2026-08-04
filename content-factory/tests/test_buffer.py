import json
import tempfile
import unittest
from pathlib import Path

from yula_factory.buffer import load_schedule_plan, submit_schedule_plan, validate_schedule_plan


class BufferTests(unittest.TestCase):
    def test_valid_plan_and_approval_gate(self):
        plan = {
            "posts": [{
                "service": "twitter",
                "channel_id": "channel-1",
                "text": "Approved text",
                "mode": "customScheduled",
                "due_at": "2026-08-11T18:00:00+02:00",
                "assets": [{"image": "https://example.com/image.jpg"}],
            }]
        }
        self.assertEqual(validate_schedule_plan(plan), [])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "plan.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            self.assertEqual(len(load_schedule_plan(path)["posts"]), 1)
            with self.assertRaises(PermissionError):
                submit_schedule_plan(path, approve=False)

    def test_tiktok_is_rejected_by_current_create_post_api(self):
        errors = validate_schedule_plan({"posts": [{"service": "tiktok", "channel_id": "x", "text": "x", "mode": "addToQueue"}]})
        self.assertTrue(any("not supported" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

from yula_factory.schedule import approve_plan, dispatch_due, plan_status, record_external_schedule, store_plan, submit_approved_now, validate_plan


def sample_plan():
    return {
        "version": 1,
        "timezone": "Europe/Warsaw",
        "posts": [{
            "day": 10,
            "slot": "text-01",
            "platform": "x",
            "provider": "buffer",
            "channel_id": "channel-1",
            "due_at": "2026-08-10T12:30:00+02:00",
            "text": "Approved copy",
        }],
    }


class ScheduleTests(unittest.TestCase):
    def test_validate_rejects_secrets_and_provider_mismatch(self):
        plan = sample_plan()
        plan["posts"][0]["api_key"] = "do-not-store"
        plan["posts"][0]["provider"] = "meta"
        errors = validate_plan(plan, verify_files=False)
        self.assertTrue(any("forbidden secret" in error for error in errors))
        self.assertTrue(any("invalid for platform" in error for error in errors))

    def test_validate_skip_files_skips_media_root_and_existence_checks(self):
        plan = sample_plan()
        plan["posts"][0]["media_path"] = r"G:\external\approved-video.mp4"
        plan["posts"][0]["public_media_url"] = "https://media.example/approved-video.mp4"
        self.assertEqual(validate_plan(plan, verify_files=False), [])
        self.assertTrue(any("media_path" in error for error in validate_plan(plan, verify_files=True)))

    def test_store_approve_digest_and_dry_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan_path = root / "plan.json"
            db_path = root / "ledger.sqlite3"
            plan_path.write_text(json.dumps(sample_plan()), encoding="utf-8")
            stored = store_plan(plan_path, db_path=db_path, verify_files=False)
            self.assertEqual(stored["status"], "planned")
            with self.assertRaises(PermissionError):
                approve_plan(stored["plan_id"], "0" * 64, db_path=db_path)
            approved = approve_plan(stored["plan_id"], stored["digest"], db_path=db_path)
            self.assertEqual(approved["status"], "approved")
            preview = dispatch_due(
                now=datetime(2026, 8, 4, tzinfo=timezone.utc),
                db_path=db_path,
                live=False,
            )
            self.assertEqual(preview["status"], "dry_run")
            self.assertEqual(len(preview["eligible"]), 1)

    def test_live_dispatch_requires_environment_gate(self):
        original = os.environ.pop("YULA_SCHEDULER_LIVE", None)
        try:
            with self.assertRaises(PermissionError):
                dispatch_due(live=True)
        finally:
            if original is not None:
                os.environ["YULA_SCHEDULER_LIVE"] = original

    def test_stale_post_is_not_published_and_requires_manual_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "ledger.sqlite3"
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(sample_plan()), encoding="utf-8")
            stored = store_plan(plan_path, db_path=db_path, verify_files=False)
            approve_plan(stored["plan_id"], stored["digest"], db_path=db_path)
            preview = dispatch_due(
                now=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
                db_path=db_path,
                live=False,
                catch_up_minutes=120,
            )
            self.assertEqual(preview["eligible"], [])
            self.assertEqual(len(preview["missed"]), 1)
            with patch.dict(os.environ, {"YULA_SCHEDULER_LIVE": "1"}), patch("yula_factory.schedule._publish") as publish:
                result = dispatch_due(
                    now=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
                    db_path=db_path,
                    live=True,
                    catch_up_minutes=120,
                )
            publish.assert_not_called()
            self.assertEqual(result["processed"], 0)
            self.assertEqual(plan_status(stored["plan_id"], db_path=db_path)["posts"][0]["status"], "manual_required")

    def test_submit_now_uses_native_future_scheduling_and_defers_meta(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "ledger.sqlite3"
            plan = sample_plan()
            plan["posts"] = [
                {
                    "day": 7,
                    "slot": "short",
                    "platform": "youtube",
                    "provider": "youtube",
                    "due_at": "2026-08-07T12:30:00+02:00",
                    "media_path": r"G:\external\video.mp4",
                    "title": "A quiet reset",
                    "tags": ["slow living"],
                },
                {
                    "day": 7,
                    "slot": "photo",
                    "platform": "instagram",
                    "provider": "meta",
                    "due_at": "2026-08-07T13:00:00+02:00",
                    "media_path": r"G:\external\photo.jpg",
                    "text": "A small story.",
                },
            ]
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            stored = store_plan(plan_path, db_path=db_path, verify_files=False)
            approve_plan(stored["plan_id"], stored["digest"], db_path=db_path)
            preview = submit_approved_now(stored["plan_id"], db_path=db_path, live=False)
            self.assertEqual([item["platform"] for item in preview["eligible"]], ["youtube"])
            self.assertEqual(preview["deferred"][0]["reason"], "platform_ui_required")

    def test_tiktok_direct_post_is_dispatched_locally_at_due_time(self):
        plan = sample_plan()
        plan["posts"][0] = {
            "day": 7,
            "slot": "short",
            "platform": "tiktok",
            "provider": "tiktok",
            "due_at": "2026-08-07T12:30:00+02:00",
            "media_path": r"G:\external\video.mp4",
            "media_type": "video",
            "text": "A quiet reset",
            "privacy_level": "SELF_ONLY",
        }
        self.assertEqual(validate_plan(plan, verify_files=False), [])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "ledger.sqlite3"
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            stored = store_plan(plan_path, db_path=db_path, verify_files=False)
            approve_plan(stored["plan_id"], stored["digest"], db_path=db_path)
            preview = submit_approved_now(stored["plan_id"], db_path=db_path, live=False)
            self.assertEqual(preview["eligible"], [])
            self.assertEqual(preview["deferred"][0]["reason"], "local_due_dispatch_required")

    def test_submit_now_live_records_provider_external_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "ledger.sqlite3"
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(sample_plan()), encoding="utf-8")
            stored = store_plan(plan_path, db_path=db_path, verify_files=False)
            approve_plan(stored["plan_id"], stored["digest"], db_path=db_path)
            with patch.dict(os.environ, {"YULA_SCHEDULER_LIVE": "1"}), patch("yula_factory.schedule._publish", return_value={"id": "buffer-123"}):
                result = submit_approved_now(stored["plan_id"], db_path=db_path, live=True)
            self.assertEqual(result["results"][0]["external_id"], "buffer-123")
            self.assertEqual(plan_status(stored["plan_id"], db_path=db_path)["posts"][0]["status"], "scheduled")

    def test_record_external_schedule_is_idempotent_and_conflict_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "ledger.sqlite3"
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(sample_plan()), encoding="utf-8")
            stored = store_plan(plan_path, db_path=db_path, verify_files=False)
            approve_plan(stored["plan_id"], stored["digest"], db_path=db_path)
            post_id = plan_status(stored["plan_id"], db_path=db_path)["posts"][0]["id"]
            self.assertEqual(record_external_schedule(post_id, "ui-123", db_path=db_path)["status"], "scheduled")
            self.assertEqual(record_external_schedule(post_id, "ui-123", db_path=db_path)["status"], "cached")
            with self.assertRaises(FileExistsError):
                record_external_schedule(post_id, "ui-456", db_path=db_path)


if __name__ == "__main__":
    unittest.main()

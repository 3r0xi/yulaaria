import json
import unittest
from pathlib import Path

from yula_factory.job import _metadata, validate_job
from yula_factory.pexels import _best_video_file


class JobTests(unittest.TestCase):
    def setUp(self):
        self.job_path = Path(__file__).resolve().parents[1] / "jobs" / "day02.json"
        self.job = json.loads(self.job_path.read_text(encoding="utf-8"))

    def test_day02_job_is_valid(self):
        self.assertEqual(validate_job(self.job), [])

    def test_day03_to_day10_jobs_are_valid(self):
        jobs = Path(__file__).resolve().parents[1] / "jobs"
        for day in range(3, 11):
            job = json.loads((jobs / f"day{day:02d}.json").read_text(encoding="utf-8"))
            self.assertEqual(validate_job(job), [], f"Day {day}")

    def test_transition_overlap_is_subtracted_from_duration(self):
        job = json.loads(json.dumps(self.job))
        job["render"]["transition_seconds"] = 0.5
        job["render"]["duration_seconds"] -= 0.5 * (len(job["sources"]) - 1)
        self.assertEqual(validate_job(job), [])

    def test_youtube_companion_slot_is_supported(self):
        job = json.loads(json.dumps(self.job))
        job["content_slot"] = "youtube_companion"
        job["output_stem"] = "YA_D02_youtube_companion_v01"
        self.assertEqual(validate_job(job), [])

    def test_kie_music_job_configuration_is_supported(self):
        job = json.loads(json.dumps(self.job))
        job["music"] = {
            "provider": "kie_suno",
            "associated_content_id": job["output_stem"],
            "version": 1,
            "generate": False,
            "rhythm_seed": 2002,
            "brief": {
                "model": "auto",
                "title": "Two Versions 01",
                "genre": "cinematic electronic",
                "mood": "reflective tension",
                "style": "deep restrained pulse and original glassy motif",
                "tempo_bpm": 76,
                "target_duration_seconds": 9,
                "exact_duration_required": True,
                "instrumental": True,
                "prompt": "Original short-form score with an immediate hook and loop-friendly tail.",
            },
        }
        self.assertEqual(validate_job(job), [])

    def test_metadata_has_all_platforms_and_checklist(self):
        text = _metadata(self.job)
        for heading in ("INSTAGRAM", "FACEBOOK", "TIKTOK", "YOUTUBE SHORTS", "THREADS", "X"):
            self.assertIn(heading, text)
        self.assertIn("PRE-SCHEDULING CHECKLIST", text)
        self.assertIn("ACTUAL MUSIC USED AFTER SCHEDULING", text)
        self.assertNotIn("Music reuse:", text)

    def test_video_file_selector_prefers_portrait(self):
        files = [
            {"file_type": "video/mp4", "width": 3840, "height": 2160, "link": "landscape"},
            {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "portrait"},
        ]
        self.assertEqual(_best_video_file(files, prefer_portrait=True)["link"], "portrait")

    def test_video_file_selector_prefers_smallest_adequate_portrait(self):
        files = [
            {"file_type": "video/mp4", "width": 2160, "height": 3840, "link": "4k"},
            {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "1080p"},
            {"file_type": "video/mp4", "width": 720, "height": 1280, "link": "720p"},
        ]
        self.assertEqual(_best_video_file(files, prefer_portrait=True)["link"], "1080p")

    def test_metadata_formats_tags_and_text_posts(self):
        job = json.loads(json.dumps(self.job))
        job["platforms"]["instagram"]["hashtags"] = ["one", "two"]
        job["text_posts"] = {
            "posts": ["First.", "Second.", "Third."],
            "instructions": "Publish separately or as a connected sequence.",
        }
        self.assertEqual(validate_job(job), [])
        text = _metadata(job)
        self.assertIn("Hashtags: one, two", text)
        self.assertIn("TEXT-ONLY POSTS - THREADS + X", text)
        self.assertIn("Post 3: Third.", text)


if __name__ == "__main__":
    unittest.main()

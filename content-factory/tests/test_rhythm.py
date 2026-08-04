import json
import unittest
from pathlib import Path

from yula_factory.render import _pattern_interrupt_filter
from yula_factory.rhythm import build_rhythm_cues, synchronise_job_to_audio


class RhythmTests(unittest.TestCase):
    def test_cues_are_deterministic_and_preserve_duration(self):
        first = build_rhythm_cues(30, 82, 42, 5, 0.35)
        second = build_rhythm_cues(30, 82, 42, 5, 0.35)
        self.assertEqual(first, second)
        rendered = sum(first["source_clip_durations"]) - 0.35 * 4
        self.assertAlmostEqual(rendered, 30, places=2)
        self.assertTrue(first["pattern_interrupt_seconds"])

    def test_job_sources_are_aligned_when_enabled(self):
        path = Path(__file__).resolve().parents[1] / "jobs" / "day10.json"
        job = json.loads(path.read_text(encoding="utf-8"))
        before = [item["clip_duration_seconds"] for item in job["sources"]]
        job["render"]["audio_sync"] = {"enabled": True}
        synced, cues = synchronise_job_to_audio(job)
        after = [item["clip_duration_seconds"] for item in synced["sources"]]
        self.assertIsNotNone(cues)
        self.assertNotEqual(before, after)
        self.assertEqual(after, cues["source_clip_durations"])

    def test_day_eleven_enables_sync_by_default(self):
        path = Path(__file__).resolve().parents[1] / "jobs" / "day10.json"
        job = json.loads(path.read_text(encoding="utf-8"))
        job["day"] = 11
        _, cues = synchronise_job_to_audio(job)
        self.assertIsNotNone(cues)

    def test_visual_interrupt_filter_uses_audio_cues(self):
        value = _pattern_interrupt_filter([4.5, 9.0])
        self.assertIn("between(t,4.500,4.640)", value)
        self.assertIn("between(t,9.000,9.140)", value)


if __name__ == "__main__":
    unittest.main()

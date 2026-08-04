import json
import unittest
from pathlib import Path

from yula_factory.gallery import VARIANTS, validate_gallery_job


class GalleryTests(unittest.TestCase):
    def test_day01_to_day10_gallery_jobs_are_valid(self):
        jobs = Path(__file__).resolve().parents[1] / "photo_galleries"
        for day in range(1, 11):
            job = json.loads((jobs / f"day{day:02d}.json").read_text(encoding="utf-8"))
            self.assertEqual(validate_gallery_job(job), [], f"Day {day}")

    def test_two_social_export_variants_are_defined(self):
        self.assertEqual(VARIANTS["instagram_facebook_4x5"], (1080, 1350))
        self.assertEqual(VARIANTS["tiktok_9x16"], (1080, 1920))


if __name__ == "__main__":
    unittest.main()

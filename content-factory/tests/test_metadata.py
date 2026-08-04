import json
import tempfile
import unittest
from pathlib import Path

from yula_factory.metadata import UNIFIED_MARKER, add_youtube_companion_metadata, extend_caption, unify_day_metadata


class MetadataTests(unittest.TestCase):
    def test_caption_is_extended_without_exceeding_limit(self):
        value = extend_caption("A quiet room changes with the light.", "photo")
        self.assertGreaterEqual(len(value), 190)
        self.assertLessEqual(len(value), 250)

    def test_unification_is_backed_up_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "metadata.txt").write_text(
                "YULA ARIA - DAY 01\nPublish date: 2026-08-01\nTheme: Stillness\nCover text: Pause\nNotion: \n\n"
                "MASTER PRODUCTION NOTES\n\nINSTAGRAM\nCaption: A quiet room.\nMusic reuse: remove me\n",
                encoding="utf-8",
            )
            (folder / "photo_gallery_metadata.txt").write_text(
                "PHOTO\nPURPOSE\nOld purpose.\n\nINSTAGRAM\nCaption: Light across the table.\n",
                encoding="utf-8",
            )
            (folder / "photo_gallery_manifest.json").write_text(json.dumps({"metadata_file": "photo_gallery_metadata.txt"}), encoding="utf-8")
            (folder / "photo_gallery_qa.json").write_text(json.dumps({"checks": {"metadata_exists": True}}), encoding="utf-8")
            result = unify_day_metadata(folder)
            text = (folder / "metadata.txt").read_text(encoding="utf-8")
            self.assertEqual(result["status"], "unified")
            self.assertIn(UNIFIED_MARKER, text)
            self.assertIn("VIDEO / REEL", text)
            self.assertIn("PHOTO / CAROUSEL", text)
            self.assertNotIn("PURPOSE", text)
            self.assertNotIn("Music reuse:", text)
            self.assertFalse((folder / "photo_gallery_metadata.txt").exists())
            self.assertEqual(unify_day_metadata(folder)["status"], "cached")

    def test_companion_short_is_added_before_photo_section(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "metadata.txt").write_text("VIDEO / REEL\nmain\n\nPHOTO / CAROUSEL\nphotos\n", encoding="utf-8")
            job = {
                "output_stem": "YA_D11_youtube_companion_v01",
                "platforms": {"youtube_shorts": {
                    "title": "A second angle",
                    "caption": "The same theme from another point of view.",
                    "cta": "Which version held you longer?",
                    "hashtags": ["#Shorts"],
                    "music_search": "Original ASMR score",
                    "schedule_notes": "Schedule at least six hours after the main Short.",
                }},
            }
            self.assertEqual(add_youtube_companion_metadata(folder, job)["status"], "added")
            text = (folder / "metadata.txt").read_text(encoding="utf-8")
            self.assertLess(text.index("YOUTUBE SHORTS - COMPANION"), text.index("PHOTO / CAROUSEL"))
            self.assertEqual(add_youtube_companion_metadata(folder, job)["status"], "cached")

    def test_companion_short_can_be_revised_without_duplication(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "metadata.txt").write_text("VIDEO / REEL\nmain\n\nPHOTO / CAROUSEL\nphotos\n", encoding="utf-8")
            job = {
                "output_stem": "YA_D11_youtube_companion_v01",
                "platforms": {"youtube_shorts": {"title": "First", "caption": "First caption.", "hashtags": ["one"]}},
            }
            add_youtube_companion_metadata(folder, job)
            job["output_stem"] = "YA_D11_youtube_companion_v02"
            job["platforms"]["youtube_shorts"]["title"] = "Second"
            result = add_youtube_companion_metadata(folder, job)
            text = (folder / "metadata.txt").read_text(encoding="utf-8")
            self.assertEqual(result["status"], "revised")
            self.assertEqual(text.count("YOUTUBE SHORTS - COMPANION"), 1)
            self.assertIn("YA_D11_youtube_companion_v02", text)
            self.assertNotIn("YA_D11_youtube_companion_v01", text)
            self.assertIn("PHOTO / CAROUSEL", text)


if __name__ == "__main__":
    unittest.main()

import unittest

from yula_factory.editing import load_style_library, resolve_style, select_style


class EditingTests(unittest.TestCase):
    def test_library_contains_requested_style_families(self):
        library = load_style_library()
        ids = {item["id"] for item in library["styles"]}
        self.assertIn("fast_hook_montage", ids)
        self.assertIn("editorial_photo_motion", ids)
        self.assertIn("suspense_reveal_structure", ids)

    def test_recent_style_is_penalized(self):
        selected = select_style("luxury hotel detail", ["video", "photo"], ["minimal_luxury_composition"])
        self.assertNotEqual(selected["id"], "minimal_luxury_composition")

    def test_explicit_style_resolves_full_profile(self):
        selected = select_style("anything", ["video"], explicit_style="cinematic_slow_build")
        self.assertEqual(selected["id"], "cinematic_slow_build")
        self.assertIn("music_sync", selected)
        self.assertEqual(resolve_style(selected["id"])["profile"], "cinematic")


if __name__ == "__main__":
    unittest.main()

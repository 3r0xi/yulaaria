import unittest

from yula_factory.audio_analysis import snap_to_onsets


class AudioAnalysisTests(unittest.TestCase):
    def test_cues_snap_only_to_nearby_onsets(self):
        result = snap_to_onsets([2.0, 5.0, 8.0], [2.16, 5.6, 7.83], max_shift_seconds=0.25)
        self.assertEqual(result, [2.16, 5.0, 7.83])


if __name__ == "__main__":
    unittest.main()

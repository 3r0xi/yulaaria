import tempfile
import unittest
import wave
from pathlib import Path

from yula_factory.audio import AudioScore, asmr_profile_for_theme, generate_original_audio


class AudioTests(unittest.TestCase):
    def test_deterministic_output(self):
        score = AudioScore(duration_seconds=1, seed=7, sample_rate=44100)
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "first.wav"
            second = Path(temp) / "second.wav"
            generate_original_audio(score, first)
            generate_original_audio(score, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with wave.open(str(first), "rb") as wav:
                self.assertEqual(wav.getnchannels(), 2)
                self.assertEqual(wav.getframerate(), 44100)
                self.assertEqual(wav.getnframes(), 44100)

    def test_rejects_imitation_fields(self):
        with self.assertRaises(ValueError):
            AudioScore.from_dict({"duration_seconds": 10, "seed": 1, "artist": "named artist"})

    def test_refuses_overwrite(self):
        score = AudioScore(duration_seconds=1, seed=8, sample_rate=44100)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "existing.wav"
            output.write_bytes(b"keep")
            with self.assertRaises(FileExistsError):
                generate_original_audio(score, output)
            self.assertEqual(output.read_bytes(), b"keep")

    def test_theme_profile_and_validation(self):
        self.assertEqual(asmr_profile_for_theme("Rain on a hotel window"), "rain_glass")
        self.assertEqual(asmr_profile_for_theme("Mediterranean morning"), "coastal_air")
        self.assertEqual(asmr_profile_for_theme("Fashion style details"), "fabric_jewelry_detail")
        self.assertEqual(
            AudioScore.from_dict({"duration_seconds": 10, "seed": 1, "asmr_profile": "watch_shoes_jewelry"}).asmr_profile,
            "watch_shoes_jewelry",
        )
        with self.assertRaises(ValueError):
            AudioScore.from_dict({"duration_seconds": 10, "seed": 1, "asmr_profile": "copy_a_song"})


if __name__ == "__main__":
    unittest.main()

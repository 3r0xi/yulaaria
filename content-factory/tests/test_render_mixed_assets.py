import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from yula_factory.audio import AudioScore, generate_original_audio
from yula_factory.qa import sha256_file
from yula_factory.render import render_manifest


ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Arial,54,&H00FFFFFF,&H000000FF,&H70000000,&H60000000,-1,0,0,0,100,100,1,0,3,2,0,2,100,100,260,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:02.00,Main,,0,0,0,,Mixed asset test
"""


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools are required")
class MixedAssetRenderTests(unittest.TestCase):
    def test_landscape_video_and_photo_render_without_forced_crop(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = root / "sources"
            overlays = root / "overlays"
            audio = root / "audio"
            sources.mkdir()
            overlays.mkdir()
            audio.mkdir()
            video = sources / "landscape.mp4"
            photo = sources / "portrait.jpg"
            subprocess.run([
                shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=0x345678:s=1280x720:d=1.2:r=30",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
            ], check=True)
            subprocess.run([
                shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=0x765432:s=900x1200", "-frames:v", "1", str(photo),
            ], check=True)
            for name in ("video-license.txt", "photo-license.txt"):
                (sources / name).write_text("test evidence", encoding="utf-8")
            (overlays / "text.ass").write_text(ASS, encoding="utf-8")
            (overlays / "cover.ass").write_text(ASS, encoding="utf-8")
            score = audio / "score.wav"
            generate_original_audio(AudioScore(duration_seconds=2, seed=5), score)
            platform = {"caption": "test", "hashtags": [], "music_search": "original"}
            manifest = {
                "schema_version": "1.0",
                "production_status": "assets_selected",
                "day": 1,
                "publish_date": "2026-08-01",
                "theme": "Mixed Assets",
                "cover_text": "Mixed Assets",
                "folder": "2026-08-01_D01_MIXED_ASSETS",
                "sources": [
                    {
                        "asset_type": "video", "provider": "Pexels", "url": "https://example.test/video",
                        "local_path": "sources/landscape.mp4", "sha256": sha256_file(video), "license_name": "test",
                        "license_checked_on": date.today().isoformat(), "license_evidence_path": "sources/video-license.txt",
                        "selected": True, "offset_seconds": 0, "clip_duration_seconds": 1.1, "fit_mode": "contain_blur",
                    },
                    {
                        "asset_type": "photo", "provider": "Pexels", "url": "https://example.test/photo",
                        "local_path": "sources/portrait.jpg", "sha256": sha256_file(photo), "license_name": "test",
                        "license_checked_on": date.today().isoformat(), "license_evidence_path": "sources/photo-license.txt",
                        "selected": True, "offset_seconds": 0, "clip_duration_seconds": 1.1, "fit_mode": "pan_zoom",
                    },
                ],
                "render": {
                    "width": 1080, "height": 1920, "fps": 30, "video_codec": "h264", "duration_seconds": 2.0,
                    "music_policy": "clean_silent_master_preserved", "template_version": "mixed-v1",
                    "output_stem": "mixed_test", "overlay_file": "overlays/text.ass",
                    "cover_overlay_file": "overlays/cover.ass", "cover_source_index": 0, "cover_offset_seconds": 0,
                    "transition_seconds": 0.2, "transition_type": "dissolve", "pattern_interrupt_seconds": [0.7],
                    "audio": {"audio_file": "audio/score.wav"},
                },
                "platforms": {name: dict(platform) for name in ("instagram", "facebook", "tiktok", "youtube_shorts", "threads", "x")},
            }
            path = root / "manifest.draft.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            result = render_manifest(path)
            self.assertTrue(Path(result["outputs"]["silent_master"]["path"]).is_file())
            self.assertTrue(Path(result["outputs"]["original_audio_master"]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()

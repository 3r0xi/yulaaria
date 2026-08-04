import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yula_factory.kie_suno import KieSunoClient, build_generate_payload, select_model, validate_generate_payload
from yula_factory.music_pipeline import prepare_or_generate_music


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return json.dumps(self.payload).encode("utf-8")


def sample_brief():
    return {
        "model": "auto",
        "title": "Yula Night Window 01",
        "genre": "cinematic electronic",
        "mood": "atmospheric tension resolving into calm confidence",
        "style": "deep rhythmic beat, organic percussion, memorable original motif",
        "tempo_bpm": 96,
        "energy": "medium rising",
        "instrumentation": ["warm synth bass", "frame drum", "airy plucks"],
        "structure": "0-2 second hook, build, reveal, loop-friendly tail",
        "hook_timing": "within 0.8 seconds",
        "target_duration_seconds": 20,
        "exact_duration_required": True,
        "instrumental": True,
        "prompt": "Original short-form score with an immediate musical hook and no imitation of existing works.",
        "negative_instructions": "recognizable melodies, generic corporate music, harsh clipping",
        "style_weight": 0.75,
        "weirdness": 0.35,
        "audio_weight": 0.65,
    }


class KieSunoTests(unittest.TestCase):
    def test_duration_critical_brief_selects_v55_and_valid_payload(self):
        payload, decision = build_generate_payload(sample_brief())
        self.assertEqual(decision.model, "V5_5")
        self.assertEqual(payload["duration"], 20.0)
        self.assertNotIn("KIE_API_KEY", json.dumps(payload))
        validate_generate_payload(payload)

    def test_explicit_incompatible_model_is_rejected(self):
        brief = sample_brief()
        brief["model"] = "V5"
        with self.assertRaises(ValueError):
            select_model(brief)

    def test_imitation_instruction_is_rejected(self):
        brief = sample_brief()
        brief["prompt"] = "Make it in the style of a famous producer"
        with self.assertRaises(ValueError):
            build_generate_payload(brief)

    def test_client_uses_bearer_header_without_returning_secret(self):
        captured = {}

        def opener(request, timeout=0):
            captured["authorization"] = request.headers["Authorization"]
            return FakeResponse({"code": 200, "msg": "success", "data": {"taskId": "task-1"}})

        client = KieSunoClient(api_key="test-secret", opener=opener, sleep=lambda _: None)
        task = client.submit_generation(build_generate_payload(sample_brief())[0])
        self.assertEqual(task, "task-1")
        self.assertEqual(captured["authorization"], "Bearer test-secret")

    def test_planning_writes_request_and_sqlite_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = {
                "provider": "kie_suno",
                "associated_content_id": "YA_D12_primary_v01",
                "version": 1,
                "generate": False,
                "brief": sample_brief(),
                "creative_notes": "First motif experiment.",
            }
            with patch.dict(os.environ, {"KIE_CALLBACK_URL": "https://callback.example.invalid/v1/kie/callback"}):
                result = prepare_or_generate_music(config, root, db_path=root / "state.sqlite3")
            self.assertEqual(result["status"], "planned")
            request = json.loads(Path(result["request_file"]).read_text(encoding="utf-8"))
            self.assertEqual(request["model"], "V5_5")
            self.assertNotIn("api_key", request)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .secrets import required_value


API_BASE_URL = "https://api.kie.ai"
GENERATE_PATH = "/api/v1/generate"
DETAILS_PATH = "/api/v1/generate/record-info"
SUPPORTED_MODELS = ("V3_5", "V4", "V4_5", "V4_5PLUS", "V4_5ALL", "V5", "V5_5")
TERMINAL_SUCCESS = {"SUCCESS"}
TERMINAL_FAILURE = {
    "CREATE_TASK_FAILED",
    "GENERATE_AUDIO_FAILED",
    "CALLBACK_EXCEPTION",
    "SENSITIVE_WORD_ERROR",
}
RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}
RETRYABLE_API_CODES = {408, 429, 500, 501, 531}
FORBIDDEN_PAYLOAD_FIELDS = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "secret",
    "password",
}


class KieSunoError(RuntimeError):
    pass


class KieSunoRetryableError(KieSunoError):
    pass


@dataclass(frozen=True)
class ModelDecision:
    model: str
    reason: str


def select_model(brief: dict) -> ModelDecision:
    requested = str(brief.get("model", "auto")).upper()
    if requested != "AUTO":
        if requested not in SUPPORTED_MODELS:
            raise ValueError(f"Unsupported Kie/Suno model: {requested}")
        if brief.get("exact_duration_required") and requested != "V5_5":
            raise ValueError("Exact duration control currently requires V5_5")
        return ModelDecision(requested, "explicit operator selection")

    if brief.get("exact_duration_required") or brief.get("target_duration_seconds"):
        return ModelDecision("V5_5", "duration-critical short-form generation")
    priority = str(brief.get("priority", "balanced")).lower()
    if priority == "speed":
        return ModelDecision("V4_5ALL", "speed-priority generation")
    if priority in {"richness", "sound_design"}:
        return ModelDecision("V4_5PLUS", "richer sound and creative control")
    if priority == "vocals":
        return ModelDecision("V4", "vocal-focused compatibility choice")
    return ModelDecision("V5", "balanced quality, musicality, and speed")


def _style_from_brief(brief: dict) -> str:
    values: list[str] = []
    for key in ("genre", "mood", "style", "energy", "instrumentation", "structure"):
        value = brief.get(key)
        if isinstance(value, list):
            value = ", ".join(str(item).strip() for item in value if str(item).strip())
        if value:
            values.append(str(value).strip())
    bpm = brief.get("tempo_bpm")
    if bpm:
        values.append(f"{int(bpm)} BPM")
    hook = brief.get("hook_timing")
    if hook:
        values.append(f"hook {hook}")
    return ", ".join(values)


def build_generate_payload(brief: dict) -> tuple[dict, ModelDecision]:
    """Build an API-only payload. Creative/archive fields never leak into it."""
    forbidden_fields = {"artist", "imitate", "reference_track", "reference_song"}.intersection(brief)
    if forbidden_fields:
        raise ValueError(f"Artist/song imitation fields are forbidden: {sorted(forbidden_fields)}")
    decision = select_model(brief)
    instrumental = bool(brief.get("instrumental", True))
    title = str(brief.get("title", "")).strip()
    style = str(brief.get("api_style") or _style_from_brief(brief)).strip()
    prompt = str(brief.get("lyrics") or brief.get("prompt") or "").strip()
    combined_instruction = f"{style} {prompt}".lower()
    if any(phrase in combined_instruction for phrase in ("in the style of", "sound exactly like", "imitate ")):
        raise ValueError("Imitation instructions are forbidden; describe original musical qualities instead")
    if not title:
        raise ValueError("music brief title is required")
    if not style:
        raise ValueError("music brief style is required")

    payload: dict = {
        "customMode": True,
        "instrumental": instrumental,
        "model": decision.model,
        "title": title,
        "style": style,
    }
    if prompt:
        payload["prompt"] = prompt
    if not instrumental and not prompt:
        raise ValueError("lyrics/prompt is required when instrumental is false")

    mappings = {
        "negative_instructions": "negativeTags",
        "vocal_gender": "vocalGender",
        "style_weight": "styleWeight",
        "weirdness": "weirdnessConstraint",
        "audio_weight": "audioWeight",
        "persona_id": "personaId",
        "persona_model": "personaModel",
        "callback_url": "callBackUrl",
    }
    for source, target in mappings.items():
        value = brief.get(source)
        if value not in (None, ""):
            payload[target] = value
    duration = brief.get("target_duration_seconds")
    if duration is not None:
        if decision.model != "V5_5":
            raise ValueError("duration is only sent when model is V5_5")
        payload["duration"] = float(duration)
    validate_generate_payload(payload)
    return payload, decision


def validate_generate_payload(payload: dict) -> None:
    lowered = {str(key).lower() for key in payload}
    forbidden = lowered.intersection(FORBIDDEN_PAYLOAD_FIELDS)
    if forbidden:
        raise ValueError(f"Secret fields are forbidden in Kie request payloads: {sorted(forbidden)}")
    model = str(payload.get("model", ""))
    if model not in SUPPORTED_MODELS:
        raise ValueError("model must be a currently supported Kie/Suno model")
    if payload.get("customMode") is not True:
        raise ValueError("The Yula production pipeline requires customMode=true")
    if not isinstance(payload.get("instrumental"), bool):
        raise ValueError("instrumental must be boolean")
    title = str(payload.get("title", ""))
    style = str(payload.get("style", ""))
    prompt = str(payload.get("prompt", ""))
    if not title or len(title) > 80:
        raise ValueError("title must contain 1 to 80 characters")
    if not style:
        raise ValueError("style is required in custom mode")
    prompt_limit = 3000 if model in {"V3_5", "V4"} else 5000
    style_limit = 200 if model in {"V3_5", "V4"} else 1000
    if len(prompt) > prompt_limit:
        raise ValueError(f"prompt exceeds the {prompt_limit}-character limit for {model}")
    if len(style) > style_limit:
        raise ValueError(f"style exceeds the {style_limit}-character limit for {model}")
    if not payload["instrumental"] and not prompt:
        raise ValueError("prompt is required for vocal music")
    if "duration" in payload and model != "V5_5":
        raise ValueError("duration is only effective for V5_5")
    for key in ("styleWeight", "weirdnessConstraint", "audioWeight"):
        if key in payload:
            value = float(payload[key])
            if not 0 <= value <= 1 or round(value, 2) != value:
                raise ValueError(f"{key} must be between 0 and 1 with at most two decimals")


class KieSunoClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = API_BASE_URL,
        opener: Callable = urlopen,
        sleep: Callable[[float], None] = time.sleep,
        attempts: int = 4,
    ) -> None:
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.opener = opener
        self.sleep = sleep
        self.attempts = max(1, int(attempts))

    @property
    def api_key(self) -> str:
        return self._api_key or required_value("KIE_API_KEY")

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                with self.opener(request, timeout=60) as response:
                    result = json.loads(response.read().decode("utf-8"))
                code = int(result.get("code", 0))
                if code != 200:
                    error = KieSunoRetryableError if code in RETRYABLE_API_CODES else KieSunoError
                    raise error(f"Kie API returned code {code}: {str(result.get('msg', 'request failed'))[:500]}")
                return result
            except HTTPError as exc:
                last_error = exc
                if exc.code not in RETRYABLE_HTTP or attempt == self.attempts - 1:
                    raise KieSunoError(f"Kie API HTTP error {exc.code}") from exc
            except (URLError, TimeoutError, KieSunoRetryableError) as exc:
                last_error = exc
                if attempt == self.attempts - 1:
                    raise KieSunoError("Kie API remained unavailable after bounded retries") from exc
            self.sleep(min(2**attempt, 8))
        raise KieSunoError("Kie API request failed") from last_error

    def submit_generation(self, payload: dict) -> str:
        validate_generate_payload(payload)
        response = self._request("POST", GENERATE_PATH, payload)
        task_id = str((response.get("data") or {}).get("taskId", "")).strip()
        if not task_id:
            raise KieSunoError("Kie generation response did not contain taskId")
        return task_id

    def task_details(self, task_id: str) -> dict:
        task = str(task_id).strip()
        if not task:
            raise ValueError("task_id is required")
        return self._request("GET", f"{DETAILS_PATH}?{urlencode({'taskId': task})}")

    def wait_for_completion(self, task_id: str, timeout_seconds: int = 900, poll_seconds: int = 30) -> dict:
        deadline = time.monotonic() + max(1, int(timeout_seconds))
        while True:
            response = self.task_details(task_id)
            data = response.get("data") or {}
            status = str(data.get("status", "")).upper()
            if status in TERMINAL_SUCCESS:
                return response
            if status in TERMINAL_FAILURE:
                raise KieSunoError(
                    f"Kie generation failed with {status}: {str(data.get('errorMessage') or '')[:500]}"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Kie generation {task_id} did not finish within {timeout_seconds} seconds")
            self.sleep(max(5, int(poll_seconds)))

    def download_audio(self, url: str, output: Path, attempts: int = 3) -> Path:
        parsed = urlparse(str(url))
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Kie audio URL must be HTTPS")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        partial = output.with_suffix(output.suffix + ".part")
        for attempt in range(max(1, int(attempts))):
            try:
                request = Request(url, headers={"User-Agent": "YulaAriaContentFactory/0.4"})
                with self.opener(request, timeout=120) as response, partial.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                if partial.stat().st_size < 1024:
                    raise OSError("downloaded audio is unexpectedly small")
                os.replace(partial, output)
                return output
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                partial.unlink(missing_ok=True)
                if attempt == max(1, int(attempts)) - 1:
                    raise KieSunoError("Could not download generated Kie audio") from exc
                self.sleep(min(2**attempt, 8))
        raise KieSunoError("Could not download generated Kie audio")


def extract_tracks(details: dict) -> list[dict]:
    data = details.get("data") or {}
    response = data.get("response") or {}
    tracks = response.get("sunoData") or []
    if not isinstance(tracks, list):
        raise KieSunoError("Kie response contained invalid sunoData")
    return [track for track in tracks if isinstance(track, dict) and track.get("audioUrl")]

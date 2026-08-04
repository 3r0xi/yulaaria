from __future__ import annotations

import json
import math
import random
import struct
import wave
from dataclasses import dataclass
from pathlib import Path

from .rhythm import pattern_interrupt_times


SCALES = {
    "minor_pentatonic": (0, 3, 5, 7, 10),
    "major_pentatonic": (0, 2, 4, 7, 9),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
}

ASMR_PROFILES = {
    "soft_room",
    "rain_glass",
    "coffee_room",
    "coastal_air",
    "architecture_clicks",
    "travel_rumble",
    "hotel_hum",
    "fabric_jewelry_detail",
    "watch_shoes_jewelry",
}


@dataclass(frozen=True)
class AudioScore:
    duration_seconds: float
    seed: int
    bpm: float = 82.0
    root_midi: int = 50
    scale: str = "minor_pentatonic"
    mood: str = "cinematic_calm"
    ambience: float = 0.22
    pulse: float = 0.18
    melody: float = 0.12
    impacts: float = 0.16
    asmr: float = 0.12
    asmr_profile: str = "soft_room"
    sample_rate: int = 48_000

    @classmethod
    def from_dict(cls, raw: dict) -> "AudioScore":
        forbidden = {"artist", "song", "imitate", "reference_track"}.intersection(raw)
        if forbidden:
            raise ValueError(f"Imitation/reference fields are forbidden: {sorted(forbidden)}")
        score = cls(**raw)
        if not 1 <= score.duration_seconds <= 120:
            raise ValueError("duration_seconds must be between 1 and 120")
        if not 40 <= score.bpm <= 180:
            raise ValueError("bpm must be between 40 and 180")
        if score.scale not in SCALES:
            raise ValueError(f"Unsupported scale: {score.scale}")
        if score.sample_rate not in (44_100, 48_000):
            raise ValueError("sample_rate must be 44100 or 48000")
        if score.asmr_profile not in ASMR_PROFILES:
            raise ValueError(f"Unsupported asmr_profile: {score.asmr_profile}")
        for name in ("ambience", "pulse", "melody", "impacts", "asmr"):
            if not 0 <= getattr(score, name) <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        return score

    @classmethod
    def from_json(cls, path: Path) -> "AudioScore":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _midi_frequency(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def _soft_clip(value: float) -> float:
    return math.tanh(value * 1.35) * 0.82


def asmr_profile_for_theme(theme: str) -> str:
    value = str(theme).lower()
    for words, profile in (
        (("rain", "window", "storm"), "rain_glass"),
        (("coffee", "cafe", "breakfast", "sunday"), "coffee_room"),
        (("architecture", "building", "design", "door"), "architecture_clicks"),
        (("airport", "train", "travel", "journey"), "travel_rumble"),
        (("hotel", "lobby", "suite"), "hotel_hum"),
        (("fashion", "style", "jewelry", "coat"), "fabric_jewelry_detail"),
        (("sea", "coast", "mediterranean", "beach"), "coastal_air"),
    ):
        if any(word in value for word in words):
            return profile
    return "soft_room"


def generate_original_audio(score: AudioScore, output: Path, force: bool = False) -> Path:
    """Render a deterministic stereo WAV from a declarative score."""
    output = output.resolve()
    if output.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing audio: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(score.seed)
    total = int(score.duration_seconds * score.sample_rate)
    beat = 60.0 / score.bpm
    notes = [score.root_midi + interval for interval in SCALES[score.scale]]
    phrase = [rng.choice(notes) + rng.choice((0, 0, 12)) for _ in range(8)]
    impact_times = [0.0]
    cursor = beat * 8
    while cursor < score.duration_seconds:
        impact_times.append(cursor)
        cursor += beat * rng.choice((8, 12, 16))

    texture_rng = random.Random(score.seed ^ 0x5A17)
    texture_events: list[tuple[float, float, float]] = []
    cursor = texture_rng.uniform(0.35, 0.9)
    while cursor < score.duration_seconds:
        texture_events.append((cursor, texture_rng.uniform(0.55, 1.0), texture_rng.uniform(900, 2800)))
        cursor += texture_rng.uniform(0.65, 1.8)
    texture_index = 0
    retention_events = pattern_interrupt_times(score.duration_seconds, score.bpm, score.seed)
    retention_index = 0

    attack = min(1.2, score.duration_seconds * 0.12)
    release = min(1.8, score.duration_seconds * 0.15)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(score.sample_rate)
        block = bytearray()
        previous_noise = 0.0
        for index in range(total):
            t = index / score.sample_rate
            envelope = min(1.0, t / max(attack, 0.01), (score.duration_seconds - t) / max(release, 0.01))

            root = _midi_frequency(score.root_midi - 12)
            pad = (math.sin(2 * math.pi * root * t) + 0.45 * math.sin(2 * math.pi * root * 1.5 * t)) * score.ambience

            beat_phase = (t % beat) / beat
            kick = math.sin(2 * math.pi * (56 - 24 * beat_phase) * t) * math.exp(-beat_phase * 12)
            pulse = kick * score.pulse

            step = int(t / (beat / 2))
            note = phrase[step % len(phrase)]
            note_t = t % (beat / 2)
            pluck = math.sin(2 * math.pi * _midi_frequency(note) * t) * math.exp(-note_t * 5.5) * score.melody

            noise = rng.uniform(-1, 1)
            filtered_noise = previous_noise * 0.985 + noise * 0.015
            previous_noise = filtered_noise
            air = filtered_noise * 0.18 * score.ambience

            # Theme-aware ASMR bed: restrained air/rumble plus sparse tactile
            # events. It is procedural and deterministic, with no artist or
            # reference-track imitation.
            asmr = filtered_noise * 0.06
            if score.asmr_profile == "coastal_air":
                asmr += filtered_noise * (0.10 + 0.07 * math.sin(2 * math.pi * 0.10 * t))
            elif score.asmr_profile == "travel_rumble":
                asmr += math.sin(2 * math.pi * 37 * t) * 0.07 + math.sin(2 * math.pi * 61 * t) * 0.025
            elif score.asmr_profile == "hotel_hum":
                asmr += math.sin(2 * math.pi * 54 * t) * 0.035 + math.sin(2 * math.pi * 108 * t) * 0.012
            elif score.asmr_profile == "fabric_jewelry_detail":
                # Soft cloth friction with a restrained metallic shimmer.
                asmr += filtered_noise * (0.055 + 0.025 * math.sin(2 * math.pi * 0.42 * t))
                asmr += math.sin(2 * math.pi * 1680 * t) * 0.006
            elif score.asmr_profile == "watch_shoes_jewelry":
                # Low shoe/step body plus a quiet, regular watch-like tick bed.
                tick_phase = t % max(beat / 2, 0.1)
                asmr += math.sin(2 * math.pi * 68 * t) * 0.028
                if tick_phase < 0.035:
                    asmr += math.sin(2 * math.pi * 2100 * tick_phase) * math.exp(-tick_phase * 90) * 0.05

            while texture_index + 1 < len(texture_events) and texture_events[texture_index + 1][0] <= t:
                texture_index += 1
            if texture_events:
                event_time, event_gain, event_frequency = texture_events[texture_index]
                delta = t - event_time
                if 0 <= delta < 0.18:
                    if score.asmr_profile == "rain_glass":
                        asmr += math.sin(2 * math.pi * event_frequency * delta) * math.exp(-delta * 42) * 0.18 * event_gain
                    elif score.asmr_profile == "coffee_room":
                        asmr += math.sin(2 * math.pi * (event_frequency * 0.55) * delta) * math.exp(-delta * 28) * 0.12 * event_gain
                    elif score.asmr_profile == "architecture_clicks":
                        asmr += math.sin(2 * math.pi * event_frequency * delta) * math.exp(-delta * 55) * 0.15 * event_gain
                    elif score.asmr_profile == "fabric_jewelry_detail":
                        asmr += filtered_noise * math.exp(-delta * 18) * 0.13 * event_gain
                        asmr += math.sin(2 * math.pi * (event_frequency * 0.8) * delta) * math.exp(-delta * 48) * 0.07 * event_gain
                    elif score.asmr_profile == "watch_shoes_jewelry":
                        asmr += math.sin(2 * math.pi * (event_frequency * 0.65) * delta) * math.exp(-delta * 52) * 0.10 * event_gain
                        asmr += math.sin(2 * math.pi * 82 * delta) * math.exp(-delta * 30) * 0.055 * event_gain
                    elif score.asmr_profile == "soft_room":
                        asmr += math.sin(2 * math.pi * (event_frequency * 0.35) * delta) * math.exp(-delta * 24) * 0.055 * event_gain
            asmr *= score.asmr

            impact = 0.0
            for event in impact_times:
                delta = t - event
                if 0 <= delta < 0.9:
                    impact += (rng.uniform(-1, 1) * math.exp(-delta * 7) + math.sin(2 * math.pi * 72 * delta) * math.exp(-delta * 8)) * score.impacts

            retention = 0.0
            while retention_index + 1 < len(retention_events) and retention_events[retention_index + 1] <= t:
                retention_index += 1
            if retention_events:
                delta = t - retention_events[retention_index]
                if 0 <= delta < 0.16:
                    retention = (
                        math.sin(2 * math.pi * 1480 * delta) * math.exp(-delta * 34)
                        + filtered_noise * math.exp(-delta * 22)
                    ) * score.asmr * 0.12

            mono = _soft_clip((pad + pulse + pluck + air + asmr + impact + retention) * envelope)
            pan = math.sin(2 * math.pi * 0.035 * t) * 0.12
            left = int(max(-1, min(1, mono * (1 - pan))) * 32767)
            right = int(max(-1, min(1, mono * (1 + pan))) * 32767)
            block.extend(struct.pack("<hh", left, right))
            if len(block) >= 262_144:
                wav.writeframesraw(block)
                block.clear()
        if block:
            wav.writeframesraw(block)
    return output

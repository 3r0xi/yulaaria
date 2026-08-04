from __future__ import annotations

import copy
import random


def pattern_interrupt_times(duration_seconds: float, bpm: float, seed: int) -> list[float]:
    """Create deterministic retention cues snapped to half-beats."""
    duration = float(duration_seconds)
    half_beat = 30.0 / float(bpm)
    rng = random.Random(int(seed) ^ 0x71A5)
    result: list[float] = []
    cursor = rng.uniform(3.6, 5.2)
    while cursor < duration - 1.0:
        snapped = round(cursor / half_beat) * half_beat
        if snapped > 1.5 and (not result or snapped - result[-1] >= 3.2):
            result.append(round(snapped, 3))
        cursor = snapped + rng.uniform(4.0, 6.8)
    return result


def build_rhythm_cues(
    duration_seconds: float,
    bpm: float,
    seed: int,
    source_count: int,
    transition_seconds: float,
) -> dict:
    duration = float(duration_seconds)
    count = int(source_count)
    transition = float(transition_seconds)
    if duration <= 0 or bpm <= 0 or count < 1 or transition < 0:
        raise ValueError("duration, bpm, source_count, and transition values are invalid")
    half_beat = 30.0 / float(bpm)
    cuts: list[float] = []
    minimum_gap = max(1.2, transition + 0.25)
    for index in range(1, count):
        ideal = duration * index / count
        cue = round(ideal / half_beat) * half_beat
        lower = (cuts[-1] + minimum_gap) if cuts else minimum_gap
        upper = duration - minimum_gap * (count - index)
        cue = min(max(cue, lower), upper)
        cuts.append(round(cue, 3))

    boundaries = [0.0, *cuts, duration]
    clip_durations: list[float] = []
    for index in range(count):
        value = boundaries[index + 1] - boundaries[index]
        if index < count - 1:
            value += transition
        clip_durations.append(round(value, 3))

    interrupts = [
        cue for cue in pattern_interrupt_times(duration, bpm, seed)
        if all(abs(cue - cut) >= 0.65 for cut in cuts)
    ]
    return {
        "schema_version": "1.0",
        "duration_seconds": duration,
        "bpm": float(bpm),
        "beat_seconds": round(60.0 / float(bpm), 6),
        "cut_seconds": cuts,
        "transition_seconds": transition,
        "source_clip_durations": clip_durations,
        "pattern_interrupt_seconds": interrupts,
    }


def synchronise_job_to_audio(job: dict) -> tuple[dict, dict | None]:
    """Return a copy with source cuts aligned to the procedural score."""
    result = copy.deepcopy(job)
    audio_sync = (result.get("render") or {}).get("audio_sync")
    enabled = int(result.get("day", 0)) >= 11 if audio_sync is None else bool(audio_sync.get("enabled"))
    if not enabled:
        return result, None
    music = result.get("music") or {}
    if music.get("provider") == "kie_suno":
        brief = music.get("brief") or {}
        score = {
            "bpm": brief.get("tempo_bpm", 82.0),
            "seed": music.get("rhythm_seed", result.get("day", 1) * 10_007),
        }
    else:
        score = result.get("audio_score") or {}
    cues = build_rhythm_cues(
        duration_seconds=result["render"]["duration_seconds"],
        bpm=score.get("bpm", 82.0),
        seed=score["seed"],
        source_count=len(result["sources"]),
        transition_seconds=result["render"].get("transition_seconds", 0),
    )
    for source, duration in zip(result["sources"], cues["source_clip_durations"]):
        source["clip_duration_seconds"] = duration
    result["render"]["pattern_interrupt_seconds"] = cues["pattern_interrupt_seconds"]
    return result, cues

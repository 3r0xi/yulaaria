from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path


def _pcm_wave(source: Path, target: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for generated-audio analysis")
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],
        check=True,
    )


def detect_onsets(source: Path, minimum_gap_seconds: float = 0.22) -> list[float]:
    """Detect useful edit accents with a dependency-free short-time energy method."""
    with tempfile.TemporaryDirectory(prefix="yula-audio-analysis-") as temp:
        pcm = Path(temp) / "analysis.wav"
        _pcm_wave(source, pcm)
        with wave.open(str(pcm), "rb") as stream:
            rate = stream.getframerate()
            width = stream.getsampwidth()
            if width != 2:
                raise ValueError("audio analysis requires 16-bit PCM")
            frame_size = max(1, int(rate * 0.025))
            energies: list[float] = []
            while True:
                frames = stream.readframes(frame_size)
                if not frames:
                    break
                count = len(frames) // 2
                samples = memoryview(frames).cast("h")
                energies.append(math.sqrt(sum(int(value) ** 2 for value in samples) / max(1, count)))

    onsets: list[float] = []
    history = 16
    for index in range(history, len(energies)):
        baseline_values = energies[index - history:index]
        baseline = sorted(baseline_values)[len(baseline_values) // 2]
        previous = energies[index - 1]
        current = energies[index]
        if current > max(450.0, baseline * 1.65) and current > previous * 1.22:
            timestamp = index * 0.025
            if not onsets or timestamp - onsets[-1] >= minimum_gap_seconds:
                onsets.append(round(timestamp, 3))
    return onsets


def snap_to_onsets(times: list[float], onsets: list[float], max_shift_seconds: float = 0.28) -> list[float]:
    result: list[float] = []
    for value in times:
        candidate = min(onsets, key=lambda onset: abs(onset - value), default=value)
        snapped = candidate if abs(candidate - value) <= max_shift_seconds else value
        if not result or snapped - result[-1] >= 0.2:
            result.append(round(float(snapped), 3))
        else:
            result.append(round(float(value), 3))
    return result


def align_rhythm_cues_to_audio(cues: dict, audio_path: Path) -> dict:
    result = dict(cues)
    onsets = detect_onsets(audio_path)
    cuts = snap_to_onsets([float(value) for value in cues.get("cut_seconds", [])], onsets)
    interrupts = snap_to_onsets([float(value) for value in cues.get("pattern_interrupt_seconds", [])], onsets)
    duration = float(cues["duration_seconds"])
    transition = float(cues.get("transition_seconds", 0))
    boundaries = [0.0, *cuts, duration]
    clip_durations: list[float] = []
    for index in range(len(boundaries) - 1):
        value = boundaries[index + 1] - boundaries[index]
        if index < len(boundaries) - 2:
            value += transition
        clip_durations.append(round(value, 3))
    result.update(
        {
            "analysis": "short_time_energy_onsets_v1",
            "detected_onset_seconds": onsets,
            "cut_seconds": cuts,
            "pattern_interrupt_seconds": interrupts,
            "source_clip_durations": clip_durations,
        }
    )
    return result

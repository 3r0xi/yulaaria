from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from .qa import sha256_file


PLATFORMS = {"instagram", "facebook", "tiktok", "youtube_shorts", "threads", "x"}
STATUSES = {"planned", "assets_selected", "rendered", "qa_passed", "approved"}


def validate_manifest(path: Path, verify_files: bool = True) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Cannot read manifest: {exc}"]

    required = {"schema_version", "production_status", "day", "publish_date", "theme", "cover_text", "folder", "sources", "render", "platforms"}
    missing = sorted(required - data.keys())
    if missing:
        errors.append(f"Missing root fields: {', '.join(missing)}")
        return errors
    if data["schema_version"] != "1.0":
        errors.append("schema_version must be 1.0")
    if data["production_status"] not in STATUSES:
        errors.append("Unknown production_status")
    if not isinstance(data["day"], int) or not 1 <= data["day"] <= 30:
        errors.append("day must be an integer from 1 to 30")
    try:
        parsed_date = date.fromisoformat(data["publish_date"])
        if parsed_date.day != data["day"] or parsed_date.strftime("%Y-%m") != "2026-08":
            errors.append("publish_date must align Day 1–30 to 2026-08-01 through 2026-08-30")
    except (TypeError, ValueError):
        errors.append("publish_date must be an ISO date")
    if not str(data["folder"]).startswith(f"2026-08-{data['day']:02d}_D{data['day']:02d}_"):
        errors.append("folder does not align with day and August date")

    sources = data["sources"]
    if not isinstance(sources, list):
        errors.append("sources must be an array")
    elif data["production_status"] != "planned" and not sources:
        errors.append("Selected/rendered states require at least one source")
    else:
        for index, source in enumerate(sources):
            prefix = f"sources[{index}]"
            for field in ("asset_type", "provider", "url", "local_path", "sha256", "license_name", "license_checked_on"):
                if not source.get(field):
                    errors.append(f"{prefix}.{field} is required")
            digest = str(source.get("sha256", ""))
            if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                errors.append(f"{prefix}.sha256 is invalid")
            if verify_files and source.get("local_path"):
                local = (path.parent / source["local_path"]).resolve()
                if path.parent.resolve() not in local.parents:
                    errors.append(f"{prefix}.local_path escapes the daily folder")
                elif not local.is_file():
                    errors.append(f"{prefix}.local_path is missing")
                elif digest and sha256_file(local).lower() != digest.lower():
                    errors.append(f"{prefix}.sha256 does not match the file")
                evidence = source.get("license_evidence_path")
                if evidence and not (path.parent / evidence).is_file():
                    errors.append(f"{prefix}.license_evidence_path is missing")
            if source.get("asset_type") not in {"video", "photo", "texture"}:
                errors.append(f"{prefix}.asset_type must be video, photo, or texture")
            if source.get("selected") and source.get("asset_type") in {"video", "photo", "texture"}:
                clip_duration = source.get("clip_duration_seconds")
                offset = source.get("offset_seconds", 0)
                if not isinstance(clip_duration, (int, float)) or clip_duration <= 0:
                    errors.append(f"{prefix}.clip_duration_seconds must be greater than 0")
                if not isinstance(offset, (int, float)) or offset < 0:
                    errors.append(f"{prefix}.offset_seconds must be zero or greater")

    render = data["render"]
    if render.get("width") != 1080 or render.get("height") != 1920:
        errors.append("render must be 1080x1920")
    if render.get("video_codec") != "h264":
        errors.append("render.video_codec must be h264")
    if render.get("music_policy") not in {"no_music_platform_added", "clean_silent_master_preserved"}:
        errors.append("render.music_policy must preserve a clean silent master")
    duration = render.get("duration_seconds")
    if duration is not None and (not isinstance(duration, (int, float)) or not 0 < duration <= 120):
        errors.append("render.duration_seconds must be greater than 0 and at most 120")
    selected_durations = [
        float(source.get("clip_duration_seconds", 0))
        for source in sources
        if isinstance(source, dict) and source.get("selected") and source.get("asset_type") in {"video", "photo", "texture"}
    ] if isinstance(sources, list) else []
    transition = render.get("transition_seconds", 0)
    if not isinstance(transition, (int, float)) or transition < 0:
        errors.append("render.transition_seconds must be zero or greater")
        transition = 0
    if transition and selected_durations and transition >= min(selected_durations):
        errors.append("render.transition_seconds must be shorter than every selected clip")
    selected_duration = sum(selected_durations) - float(transition) * max(0, len(selected_durations) - 1)
    if selected_duration and isinstance(duration, (int, float)) and abs(selected_duration - duration) > 0.05:
        errors.append("selected video clip durations minus transition overlaps must equal render.duration_seconds")
    if render.get("audio_sync_enabled"):
        rhythm_file = render.get("rhythm_cues_file")
        if not rhythm_file:
            errors.append("render.rhythm_cues_file is required when audio sync is enabled")
        elif verify_files and not (path.parent / rhythm_file).is_file():
            errors.append("render.rhythm_cues_file is missing")
        for cue in render.get("pattern_interrupt_seconds", []):
            if not isinstance(cue, (int, float)) or cue <= 0 or (isinstance(duration, (int, float)) and cue >= duration):
                errors.append("render.pattern_interrupt_seconds contains an invalid cue")

    platforms = data["platforms"]
    if not isinstance(platforms, dict) or set(platforms) != PLATFORMS:
        errors.append("platforms must contain exactly Instagram, Facebook, TikTok, YouTube Shorts, Threads, and X")
    return errors

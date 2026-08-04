from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .audio import AudioScore, asmr_profile_for_theme, generate_original_audio
from .audio_analysis import align_rhythm_cues_to_audio
from .duration import validate_duration
from .editing import recent_styles, record_style, resolve_style, select_style
from .manifest import validate_manifest
from .metadata import add_youtube_companion_metadata, extend_caption
from .music_pipeline import prepare_or_generate_music, validate_music_config
from .paths import CONTENT_ROOT, inside_content_root
from .qa import finalize_automated_qa, inspect_folder, sha256_file
from .render import render_manifest
from .rhythm import synchronise_job_to_audio


LICENSE_NAME = "Pexels License - Free to use"
LICENSE_URL = "https://www.pexels.com/license/"
PLATFORM_ORDER = ("instagram", "facebook", "tiktok", "youtube_shorts", "threads", "x")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _job_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new(path: Path, content: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") == content:
            return
        raise FileExistsError(f"Refusing to overwrite changed file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _download(url: str, output: Path, attempts: int = 3) -> Path:
    if output.exists():
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    for attempt in range(attempts):
        request = Request(url, headers={"User-Agent": "YulaAriaContentFactory/0.2"})
        try:
            with urlopen(request, timeout=60) as response, partial.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            if partial.stat().st_size == 0:
                raise RuntimeError("Downloaded source is empty")
            partial.replace(output)
            return output
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            partial.unlink(missing_ok=True)
            if attempt == attempts - 1:
                raise RuntimeError(f"Could not download {url}") from exc
            time.sleep(2**attempt)
    raise RuntimeError(f"Could not download {url}")


def _ass_time(seconds: float) -> str:
    centiseconds = int(round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole:02d}.{fraction:02d}"


def _ass_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _overlay(events: list[dict]) -> str:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Arial,54,&H00FFFFFF,&H000000FF,&H70000000,&H60000000,-1,0,0,0,100,100,1,0,3,2,0,2,100,100,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [
        f"Dialogue: 0,{_ass_time(item['start'])},{_ass_time(item['end'])},Main,,0,0,0,,{_ass_escape(item['text'])}"
        for item in events
    ]
    return header + "\n".join(lines) + "\n"


def _cover(text: str, duration: float) -> str:
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cover,Arial,88,&H00FFFFFF,&H000000FF,&H70000000,&H50000000,-1,0,0,0,100,100,5,0,3,3,0,5,90,90,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,{_ass_time(duration)},Cover,,0,0,0,,{_ass_escape(text)}
"""


def _metadata(job: dict) -> str:
    lines = [
        f"YULA ARIA - DAY {job['day']:02d}",
        f"Publish date: {job['publish_date']}",
        f"Theme: {job['theme']}",
        f"Cover text: {job['cover_text']}",
        f"Notion: {job.get('notion_page_url', '')}",
        "",
        "MASTER PRODUCTION NOTES",
    ]
    lines.extend(f"- {item}" for item in job.get("production_notes", []))
    for platform in PLATFORM_ORDER:
        data = job["platforms"][platform]
        lines.extend(["", platform.replace("_", " ").upper()])
        for label, key in (
            ("Title", "title"),
            ("Caption", "caption"),
            ("CTA", "cta"),
            ("Hashtags", "hashtags"),
            ("Music", "music_search"),
            ("Scheduling", "schedule_notes"),
        ):
            value = data.get(key)
            if isinstance(value, list):
                value = ", ".join(value)
            if key == "caption" and value:
                value = extend_caption(value, "video")
            if value:
                lines.append(f"{label}: {value}")
    stories = job.get("stories") or {}
    if stories:
        lines.extend(["", "INSTAGRAM + FACEBOOK STORIES"])
        lines.extend(f"Frame {index}: {value}" for index, value in enumerate(stories.get("frames", []), 1))
        if stories.get("sticker"):
            lines.append(f"Sticker: {stories['sticker']}")
        if stories.get("timing"):
            lines.append(f"Timing: {stories['timing']}")
    text_posts = job.get("text_posts") or {}
    if text_posts:
        lines.extend(["", "TEXT-ONLY POSTS - THREADS + X"])
        for index, item in enumerate(text_posts.get("posts", []), 1):
            lines.append(f"Post {index}: {item}")
        if text_posts.get("instructions"):
            lines.append(f"Instructions: {text_posts['instructions']}")
    lines.extend(["", "PRE-SCHEDULING CHECKLIST"])
    lines.extend(f"[ ] {item}" for item in job.get("checklist", []))
    lines.extend(
        [
            "",
            "ACTUAL MUSIC USED AFTER SCHEDULING",
            "Instagram:",
            "Facebook:",
            "TikTok:",
            "YouTube Shorts:",
            "Threads:",
            "X:",
            "",
        ]
    )
    return "\n".join(lines)


def validate_job(job: dict) -> list[str]:
    errors: list[str] = []
    required = {"schema_version", "day", "publish_date", "folder", "theme", "cover_text", "output_stem", "sources", "render", "platforms"}
    missing = sorted(required - job.keys())
    if missing:
        return [f"Missing job fields: {', '.join(missing)}"]
    try:
        job, _ = synchronise_job_to_audio(job)
    except (KeyError, TypeError, ValueError) as exc:
        return [f"Invalid render.audio_sync configuration: {exc}"]
    if job["schema_version"] != "1.0":
        errors.append("job schema_version must be 1.0")
    if job.get("music") is not None:
        errors.extend(validate_music_config(job["music"]))
        brief_duration = (job["music"].get("brief") or {}).get("target_duration_seconds")
        if brief_duration is not None and abs(float(brief_duration) - float(job.get("render", {}).get("duration_seconds", -1))) > 0.1:
            errors.append("music.brief.target_duration_seconds must match render.duration_seconds")
        if str(job["music"].get("associated_content_id", "")) != str(job.get("output_stem", "")):
            errors.append("music.associated_content_id must match output_stem")
    elif not isinstance(job.get("audio_score"), dict):
        errors.append("audio_score is required when music is not configured")
    if job.get("content_slot", "primary") not in {"primary", "youtube_companion"}:
        errors.append("content_slot must be primary or youtube_companion")
    if set(job["platforms"]) != set(PLATFORM_ORDER):
        errors.append("job platforms must contain the six supported platform keys")
    if len(job.get("sources", [])) < 1:
        errors.append("job needs at least one selected source")
    try:
        publish = date.fromisoformat(job["publish_date"])
        if publish.day != int(job["day"]):
            errors.append("publish date and day number do not align")
    except (TypeError, ValueError):
        errors.append("publish_date must be an ISO date")
    render = job.get("render", {})
    source_durations = [float(source.get("clip_duration_seconds", 0)) for source in job.get("sources", [])]
    transition = float(render.get("transition_seconds", 0))
    duration = sum(source_durations) - transition * max(0, len(source_durations) - 1)
    if transition < 0:
        errors.append("render.transition_seconds must be zero or greater")
    if transition and source_durations and transition >= min(source_durations):
        errors.append("render.transition_seconds must be shorter than every source clip")
    if abs(duration - float(render.get("duration_seconds", -1))) > 0.05:
        errors.append("source clip durations minus transition overlaps must equal render.duration_seconds")
    duration_error = validate_duration(int(job["day"]), float(render.get("duration_seconds", -1)))
    if duration_error:
        errors.append(duration_error)
    for index, source in enumerate(job.get("sources", [])):
        for field in ("provider_id", "page_url", "download_url", "creator", "filename"):
            if not source.get(field):
                errors.append(f"sources[{index}].{field} is required")
        if source.get("asset_type", "video") not in {"video", "photo", "texture"}:
            errors.append(f"sources[{index}].asset_type must be video, photo, or texture")
        if source.get("fit_mode", "cover") not in {"cover", "contain_blur", "contain_color", "pan_zoom"}:
            errors.append(f"sources[{index}].fit_mode is unsupported")
        if str(source.get("provider", "Pexels")).lower() != "pexels":
            if not source.get("license_name") or not source.get("license_url"):
                errors.append(f"sources[{index}] non-Pexels assets require license_name and license_url")
    source_count = len(job.get("sources", []))
    for index in render.get("reverse_source_indices", []):
        if not isinstance(index, int) or not 0 <= index < source_count:
            errors.append("render.reverse_source_indices contains an invalid source index")
    carousel = render.get("carousel") or {}
    if carousel.get("enabled"):
        indices = carousel.get("source_indices", [])
        if not indices:
            errors.append("render.carousel.source_indices is required when carousel is enabled")
        for index in indices:
            if not isinstance(index, int) or not 0 <= index < source_count:
                errors.append("render.carousel.source_indices contains an invalid source index")
    text_posts = job.get("text_posts")
    if text_posts is not None:
        posts = text_posts.get("posts") if isinstance(text_posts, dict) else None
        if not isinstance(posts, list) or not 3 <= len(posts) <= 5 or any(not str(item).strip() for item in posts):
            errors.append("text_posts.posts must contain 3 to 5 non-empty English posts")
    explicit_style = render.get("editing_style")
    if explicit_style:
        try:
            resolve_style(str(explicit_style))
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def run_job(job_path: Path) -> dict:
    job_path = job_path.resolve()
    job, rhythm_cues = synchronise_job_to_audio(_load_json(job_path))
    errors = validate_job(job)
    if errors:
        raise ValueError("Invalid job: " + "; ".join(errors))
    day_dir = inside_content_root(CONTENT_ROOT / job["folder"])
    day_dir.mkdir(parents=True, exist_ok=True)
    content_slot = job.get("content_slot", "primary")
    slot_suffix = "" if content_slot == "primary" else ".youtube_companion"
    filename_suffix = "" if content_slot == "primary" else "_youtube_companion"
    state_path = day_dir / f"run_state{slot_suffix}.json"
    digest = _job_hash(job_path)
    if state_path.exists():
        state = _load_json(state_path)
        if state.get("job_sha256") == digest and state.get("status") == "qa_passed":
            return {"status": "cached", "codex_tokens_used_by_local_run": 0, "folder": str(day_dir), "qa": inspect_folder(day_dir)}
        raise FileExistsError("Day folder has a different completed job; create a new revision instead of overwriting it")

    source_records = []
    selected_style = select_style(
        job["theme"],
        [str(source.get("asset_type", "video")) for source in job["sources"]],
        recent_style_ids=recent_styles(),
        explicit_style=job.get("render", {}).get("editing_style"),
    )
    checked_on = datetime.now(timezone.utc).date().isoformat()
    for source in job["sources"]:
        provider = str(source.get("provider", "Pexels")).strip()
        license_name = str(source.get("license_name") or (LICENSE_NAME if provider.lower() == "pexels" else "")).strip()
        license_url = str(source.get("license_url") or (LICENSE_URL if provider.lower() == "pexels" else "")).strip()
        source_folder = day_dir / "sources" if content_slot == "primary" else day_dir / "sources" / "youtube_companion"
        local = source_folder / source["filename"]
        _download(source["download_url"], local)
        expected = source.get("expected_sha256")
        actual = sha256_file(local)
        if expected and actual.lower() != expected.lower():
            raise ValueError(f"Hash mismatch for {local.name}")
        provider_slug = "".join(character.lower() if character.isalnum() else "_" for character in provider).strip("_")
        evidence = source_folder / f"{provider_slug}_{source['provider_id']}_license_evidence.txt"
        evidence_text = "\n".join(
            [
                f"Provider: {provider}",
                f"Asset page: {source['page_url']}",
                f"Creator: {source['creator']}",
                f"Creator page: {source.get('creator_url', '')}",
                f"License: {license_name}",
                f"License URL: {license_url}",
                f"Checked on: {checked_on}",
                "Usage note: Curated stock material; do not imply Yula Aria personally filmed it.",
                f"Attribution note: Follow the recorded {provider} license and credit requirements.",
                "",
            ]
        )
        _write_new(evidence, evidence_text)
        source_records.append(
            {
                "asset_type": source.get("asset_type", "video"),
                "provider": provider,
                "provider_id": int(source["provider_id"]) if str(source["provider_id"]).isdigit() else str(source["provider_id"]),
                "url": source["page_url"],
                "creator": source["creator"],
                "creator_url": source.get("creator_url"),
                "local_path": local.relative_to(day_dir).as_posix(),
                "sha256": actual,
                "license_name": license_name,
                "license_url": license_url,
                "license_evidence_path": evidence.relative_to(day_dir).as_posix(),
                "license_checked_on": checked_on,
                "selected": True,
                "offset_seconds": float(source.get("offset_seconds", 0)),
                "clip_duration_seconds": float(source["clip_duration_seconds"]),
                "fit_mode": source.get("fit_mode", "pan_zoom" if source.get("asset_type") in {"photo", "texture"} else "cover"),
                "subject_anchor": source.get("subject_anchor", "center"),
            }
        )

    overlay_path = day_dir / "overlays" / f"day{job['day']:02d}{filename_suffix}_text.ass"
    cover_path = day_dir / "overlays" / f"day{job['day']:02d}{filename_suffix}_cover.ass"
    _write_new(overlay_path, _overlay(job["render"]["text_events"]))
    _write_new(cover_path, _cover(job["cover_text"], float(job["render"]["duration_seconds"])))

    music_result = None
    if job.get("music"):
        music_result = prepare_or_generate_music(job["music"], day_dir)
        if music_result["status"] == "planned":
            raise PermissionError(
                "The Kie request was prepared but not generated. Set music.generate=true and YULA_KIE_LIVE=1 only for an approved billable run."
            )
        audio_wav_path = Path(music_result["audio_file"])
        audio_score_path = Path(music_result["request_file"])
        score_data = {
            "seed": int(job["music"].get("rhythm_seed", int(job["day"]) * 10_007)),
            "bpm": float((job["music"].get("brief") or {}).get("tempo_bpm", 82.0)),
            "asmr_profile": "kie_suno_generated",
        }
    else:
        audio_score_path = day_dir / "audio" / f"day{job['day']:02d}{filename_suffix}_audio_score.json"
        audio_wav_path = day_dir / "audio" / f"day{job['day']:02d}{filename_suffix}_original_score.wav"
        score_data = dict(job["audio_score"])
        score_data.setdefault("asmr", 0.12)
        score_data.setdefault("asmr_profile", asmr_profile_for_theme(job["theme"]))
        _write_new(audio_score_path, json.dumps(score_data, indent=2, ensure_ascii=False) + "\n")
        if not audio_wav_path.exists():
            generate_original_audio(AudioScore.from_dict(score_data), audio_wav_path)
        elif audio_wav_path.stat().st_size <= 44:
            raise ValueError(f"Existing procedural audio is incomplete: {audio_wav_path}")
    if music_result and rhythm_cues:
        rhythm_cues = align_rhythm_cues_to_audio(rhythm_cues, audio_wav_path)
        for source, record, clip_duration in zip(job["sources"], source_records, rhythm_cues["source_clip_durations"]):
            source["clip_duration_seconds"] = clip_duration
            record["clip_duration_seconds"] = clip_duration
        job["render"]["pattern_interrupt_seconds"] = rhythm_cues["pattern_interrupt_seconds"]
    rhythm_cues_path = None
    if rhythm_cues:
        rhythm_cues_path = day_dir / "audio" / f"day{job['day']:02d}{filename_suffix}_rhythm_cues.json"
        _write_new(rhythm_cues_path, json.dumps(rhythm_cues, indent=2, ensure_ascii=False) + "\n")
    if content_slot == "primary":
        _write_new(day_dir / "metadata.txt", _metadata(job))
    else:
        add_youtube_companion_metadata(day_dir, job)

    manifest = {
        "schema_version": "1.0",
        "production_status": "assets_selected",
        "day": int(job["day"]),
        "publish_date": job["publish_date"],
        "theme": job["theme"],
        "cover_text": job["cover_text"],
        "folder": job["folder"],
        "notion_page_url": job.get("notion_page_url"),
        "sources": source_records,
        "render": {
            "width": 1080,
            "height": 1920,
            "fps": int(job["render"].get("fps", 30)),
            "video_codec": "h264",
            "duration_seconds": float(job["render"]["duration_seconds"]),
            "music_policy": "clean_silent_master_preserved" if music_result else "no_music_platform_added",
            "template_version": job["render"].get("template_version", "generic-v1"),
            "output_stem": job["output_stem"],
            "overlay_file": overlay_path.relative_to(day_dir).as_posix(),
            "cover_overlay_file": cover_path.relative_to(day_dir).as_posix(),
            "cover_source_index": int(job["render"].get("cover_source_index", 0)),
            "cover_offset_seconds": float(job["render"].get("cover_offset_seconds", 0)),
            "transition_seconds": float(job["render"].get("transition_seconds", 0)),
            "reverse_source_indices": job["render"].get("reverse_source_indices", []),
            "carousel": job["render"].get("carousel"),
            "audio_sync_enabled": bool(rhythm_cues),
            "rhythm_cues_file": rhythm_cues_path.relative_to(day_dir).as_posix() if rhythm_cues_path else None,
            "pattern_interrupt_seconds": job["render"].get("pattern_interrupt_seconds", []),
            "editing_style": selected_style,
            "transition_type": job["render"].get("transition_type", "fade"),
            "audio": {
                "mode": "kie_suno_generated" if music_result else "original_procedural",
                "master_mix": "full_original_score",
                "score_file": audio_score_path.relative_to(day_dir).as_posix(),
                "audio_file": audio_wav_path.relative_to(day_dir).as_posix(),
                "seed": int(score_data["seed"]),
                "asmr_profile": score_data["asmr_profile"],
                "license_record": None,
                "generation": music_result,
            },
        },
        "platforms": job["platforms"],
    }
    draft = day_dir / f"manifest{slot_suffix}.draft.json"
    _write_new(draft, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    manifest_errors = validate_manifest(draft, verify_files=True)
    if manifest_errors:
        raise ValueError("Generated manifest failed validation: " + "; ".join(manifest_errors))
    render_result = render_manifest(draft)
    qa_result = finalize_automated_qa(draft)
    record_style(
        job["output_stem"],
        int(job["day"]),
        "cross_platform",
        selected_style,
        day_dir / f"manifest{slot_suffix}.json",
    )
    state = {
        "status": "qa_passed",
        "job_path": str(job_path),
        "job_sha256": digest,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "codex_tokens_used_by_local_run": 0,
        "render_outputs": render_result["outputs"],
        "human_approval_required": True,
    }
    _write_new(state_path, json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    return {"status": "qa_passed", "codex_tokens_used_by_local_run": 0, "folder": str(day_dir), "qa": qa_result}

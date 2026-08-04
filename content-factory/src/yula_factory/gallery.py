from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .paths import CONTENT_ROOT, inside_content_root
from .pexels import search_photos
from .qa import sha256_file
from .metadata import extend_caption, unify_day_metadata


LICENSE_NAME = "Pexels License - Free to use"
LICENSE_URL = "https://www.pexels.com/license/"
PLATFORM_ORDER = ("instagram", "facebook", "tiktok", "threads", "x")
VARIANTS = {"instagram_facebook_4x5": (1080, 1350), "tiktok_9x16": (1080, 1920)}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_same_or_new(path: Path, text: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") == text:
            return
        raise FileExistsError(f"Refusing to overwrite changed file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _download(url: str, output: Path, attempts: int = 3) -> Path:
    if output.exists() and output.stat().st_size > 0:
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    for attempt in range(attempts):
        request = Request(url, headers={"User-Agent": "YulaAriaContentFactory/0.3"})
        try:
            with urlopen(request, timeout=60) as response, partial.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            if partial.stat().st_size <= 0:
                raise RuntimeError("Downloaded source is empty")
            partial.replace(output)
            return output
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            partial.unlink(missing_ok=True)
            if attempt == attempts - 1:
                raise RuntimeError(f"Could not download {url}") from exc
    raise RuntimeError(f"Could not download {url}")


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} is required but was not found on PATH")
    return path


def _probe(path: Path) -> dict:
    raw = subprocess.check_output(
        [_tool("ffprobe"), "-v", "error", "-show_entries", "format=size:stream=codec_type,codec_name,width,height", "-of", "json", str(path)],
        text=True,
        encoding="utf-8",
    )
    return json.loads(raw)


def _render_retouched(source: Path, output: Path, width: int, height: int) -> None:
    if output.exists() and output.stat().st_size > 0:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            _tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-n", "-i", str(source), "-frames:v", "1",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,eq=contrast=1.04:saturation=0.94:brightness=0.01,unsharp=5:5:0.45:5:5:0.0",
            "-q:v", "2", str(output),
        ],
        check=True,
    )


def _safe_stem(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value.lower()).strip("_")


def _selection(job: dict, job_hash: str, path: Path) -> dict:
    if path.exists():
        data = _load_json(path)
        if data.get("job_sha256") != job_hash:
            raise FileExistsError("Photo selection belongs to a different job revision; create a new revision instead")
        return data
    result = search_photos(job["photo_query"], per_page=max(20, int(job["photo_count"]) * 4), orientation="portrait", size="large")
    candidates = [item for item in result["candidates"] if item.get("id") and item.get("creator") and item.get("page_url") and item.get("download_url")]
    count = int(job["photo_count"])
    if len(candidates) < count:
        raise RuntimeError(f"Pexels returned only {len(candidates)} usable photo candidates; need {count}")
    record = {
        "schema_version": "1.0", "job_sha256": job_hash, "query": job["photo_query"],
        "checked_on": datetime.now(timezone.utc).date().isoformat(), "quota": result.get("quota"), "selected": candidates[:count],
    }
    _write_same_or_new(path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return record


def _metadata(job: dict) -> str:
    lines = [
        f"YULA ARIA - DAY {int(job['day']):02d} PHOTO GALLERY COMPANION",
        f"Publish date: {job['publish_date']}", f"Theme: {job['theme']}", f"Gallery title: {job['gallery_title']}", "",
    ]
    for platform in PLATFORM_ORDER:
        data = job["platforms"][platform]
        lines.extend(["", platform.upper()])
        for label, key in (("Caption", "caption"), ("CTA", "cta"), ("Hashtags", "hashtags"), ("Format", "format"), ("Scheduling", "schedule_notes")):
            value = data.get(key)
            if isinstance(value, list):
                value = ", ".join(value)
            if key == "caption" and value:
                value = extend_caption(value, "photo")
            if value:
                lines.append(f"{label}: {value}")
    story = job["story_sequence"]
    lines.extend(["", "INSTAGRAM + FACEBOOK STORY COMPANION"])
    lines.extend(f"Frame {number}: {text}" for number, text in enumerate(story["frames"], 1))
    lines.extend([f"Sticker: {story['sticker']}", f"Timing: {story['timing']}", "", "PRE-SCHEDULING CHECKLIST"])
    lines.extend(f"[ ] {item}" for item in job["checklist"])
    return "\n".join(lines) + "\n"


def validate_gallery_job(job: dict) -> list[str]:
    required = {"schema_version", "day", "publish_date", "folder", "theme", "gallery_title", "photo_query", "photo_count", "platforms", "story_sequence", "checklist"}
    missing = sorted(required - job.keys())
    if missing:
        return [f"Missing photo-gallery job fields: {', '.join(missing)}"]
    errors: list[str] = []
    if job["schema_version"] != "1.0":
        errors.append("photo-gallery job schema_version must be 1.0")
    if not isinstance(job["day"], int) or not 1 <= job["day"] <= 30:
        errors.append("day must be an integer from 1 to 30")
    if job["publish_date"] != f"2026-08-{int(job['day']):02d}":
        errors.append("publish date must align with the August 2026 day number")
    if not str(job["folder"]).startswith(f"2026-08-{int(job['day']):02d}_D{int(job['day']):02d}_"):
        errors.append("folder does not align with day and August date")
    if not isinstance(job["photo_count"], int) or not 1 <= job["photo_count"] <= 10:
        errors.append("photo_count must be an integer from 1 to 10")
    if set(job["platforms"]) != set(PLATFORM_ORDER):
        errors.append("photo-gallery platforms must contain Instagram, Facebook, TikTok, Threads, and X")
    story = job.get("story_sequence") or {}
    if not isinstance(story.get("frames"), list) or len(story["frames"]) < 2:
        errors.append("story_sequence needs at least two frames")
    return errors


def run_gallery_job(job_path: Path) -> dict:
    job_path = job_path.resolve()
    job = _load_json(job_path)
    errors = validate_gallery_job(job)
    if errors:
        raise ValueError("Invalid photo-gallery job: " + "; ".join(errors))
    day_dir = inside_content_root(CONTENT_ROOT / job["folder"])
    if not day_dir.is_dir():
        raise FileNotFoundError(f"Day folder is missing: {day_dir}")
    digest = hashlib.sha256(job_path.read_bytes()).hexdigest()
    state_path = day_dir / "photo_gallery_state.json"
    if state_path.exists():
        state = _load_json(state_path)
        if state.get("job_sha256") == digest and state.get("status") == "qa_passed":
            return {"status": "cached", "codex_tokens_used_by_local_run": 0, "folder": str(day_dir), "qa": _load_json(day_dir / "photo_gallery_qa.json")}
        raise FileExistsError("Photo gallery has a different completed job; create a new revision instead")

    selection = _selection(job, digest, day_dir / "photo sources" / "pexels_selection.json")
    source_records = []
    for number, source in enumerate(selection["selected"], 1):
        filename = f"pexels_{source['id']}_{_safe_stem(str(source['creator']))}_{number:02d}.jpg"
        local = day_dir / "photo sources" / filename
        _download(source["download_url"], local)
        evidence = day_dir / "photo sources" / f"pexels_{source['id']}_license_evidence.txt"
        _write_same_or_new(evidence, "\n".join([
            "Provider: Pexels", f"Asset page: {source['page_url']}", f"Creator: {source['creator']}",
            f"Creator page: {source.get('creator_url') or ''}", f"License: {LICENSE_NAME}", f"License URL: {LICENSE_URL}",
            f"Checked on: {selection['checked_on']}", "Usage note: Curated stock material; do not imply Yula Aria personally photographed it.",
            "Attribution note: Credit the creator and link to Pexels when practical.", "",
        ]))
        source_records.append({
            "provider": "Pexels", "provider_id": int(source["id"]), "url": source["page_url"], "creator": source["creator"],
            "creator_url": source.get("creator_url"), "local_path": local.relative_to(day_dir).as_posix(), "sha256": sha256_file(local),
            "license_name": LICENSE_NAME, "license_url": LICENSE_URL, "license_evidence_path": evidence.relative_to(day_dir).as_posix(), "license_checked_on": selection["checked_on"],
        })

    exports = []
    for number, record in enumerate(source_records, 1):
        source = day_dir / record["local_path"]
        for name, (width, height) in VARIANTS.items():
            output = day_dir / "exported photos" / name / f"YA_D{int(job['day']):02d}_gallery_{number:02d}_{name}.jpg"
            _render_retouched(source, output, width, height)
            video = next((stream for stream in _probe(output).get("streams", []) if stream.get("codec_type") == "video"), {})
            if video.get("width") != width or video.get("height") != height:
                raise ValueError(f"Retouched photo dimensions are wrong: {output}")
            exports.append({"source_number": number, "variant": name, "path": output.relative_to(day_dir).as_posix(), "sha256": sha256_file(output), "width": width, "height": height, "retouch_recipe": "center crop; contrast +4%; saturation -6%; brightness +0.01; light luma sharpening"})

    _write_same_or_new(day_dir / "photo_gallery_metadata.txt", _metadata(job))
    manifest = {"schema_version": "1.0", "production_status": "qa_passed", "approval_required": True, "day": job["day"], "publish_date": job["publish_date"], "theme": job["theme"], "gallery_title": job["gallery_title"], "folder": job["folder"], "selection_file": "photo sources/pexels_selection.json", "sources": source_records, "exports": exports, "metadata_file": "photo_gallery_metadata.txt", "platforms": job["platforms"], "story_sequence": job["story_sequence"]}
    manifest_path = day_dir / "photo_gallery_manifest.json"
    _write_same_or_new(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    expected = int(job["photo_count"]) * len(VARIANTS)
    report = {"passed": len(exports) == expected and all((day_dir / item["path"]).is_file() for item in exports), "approval_required": True, "checks": {"source_count_matches_job": len(source_records) == int(job["photo_count"]), "export_count_matches_variants": len(exports) == expected, "all_exports_are_1080x1350_or_1080x1920": all(item["width"] == 1080 and item["height"] in (1350, 1920) for item in exports), "metadata_exists": (day_dir / "photo_gallery_metadata.txt").is_file(), "manifest_exists": manifest_path.is_file(), "source_license_evidence_exists": all((day_dir / item["license_evidence_path"]).is_file() for item in source_records)}, "exports": exports, "note": "Editorial cropping and retouching improve presentation but do not guarantee platform distribution. Human approval and platform-native scheduling remain required."}
    if not report["passed"] or not all(report["checks"].values()):
        raise ValueError("Photo gallery QA failed")
    _write_same_or_new(day_dir / "photo_gallery_qa.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    state = {"status": "qa_passed", "job_path": str(job_path), "job_sha256": digest, "completed_at": datetime.now(timezone.utc).isoformat(), "codex_tokens_used_by_local_run": 0, "human_approval_required": True}
    _write_same_or_new(state_path, json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    unify_day_metadata(day_dir)
    return {"status": "qa_passed", "codex_tokens_used_by_local_run": 0, "folder": str(day_dir), "qa": report}

from __future__ import annotations

import json
import shutil
from pathlib import Path


UNIFIED_MARKER = "UNIFIED CONTENT METADATA"
VIDEO_EXTENSION = (
    " The pacing gives each visual detail room to register, while the final beat "
    "keeps the idea open long enough to invite a second look. Notice which small "
    "moment changes the feeling of the whole sequence."
)
PHOTO_EXTENSION = (
    " Together, the frames move from atmosphere to detail, turning the same theme "
    "into a slower visual story that rewards a second look. Notice how the mood "
    "shifts when one quiet detail becomes the focus."
)


def extend_caption(text: str, kind: str) -> str:
    """Gently extend short captions without inventing personal authorship."""
    clean = " ".join(str(text).split())
    if len(clean) >= 190:
        return clean
    addition = VIDEO_EXTENSION if kind == "video" else PHOTO_EXTENSION
    combined = clean.rstrip() + addition
    if len(combined) <= 250:
        return combined
    return combined[:247].rsplit(" ", 1)[0].rstrip(" ,.;:") + "..."


def _sanitise(lines: list[str], kind: str) -> list[str]:
    result: list[str] = []
    for line in lines:
        if line.startswith("Music reuse:"):
            continue
        if line.startswith("Caption: "):
            line = "Caption: " + extend_caption(line.removeprefix("Caption: "), kind)
        result.append(line)
    return result


def _after_heading(lines: list[str], heading: str) -> list[str]:
    try:
        return lines[lines.index(heading) :]
    except ValueError:
        return lines


def _copy_backup(source: Path, destination: Path) -> None:
    if destination.exists():
        if destination.read_bytes() != source.read_bytes():
            raise FileExistsError(f"Backup already exists with different content: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def unify_day_metadata(day_dir: Path) -> dict:
    """Combine video and gallery notes into the day's single human metadata file.

    Originals are retained in a dated backup folder before the gallery metadata
    file is removed, making this migration recoverable and idempotent.
    """
    day_dir = day_dir.resolve()
    video_path = day_dir / "metadata.txt"
    photo_path = day_dir / "photo_gallery_metadata.txt"
    if not video_path.is_file():
        raise FileNotFoundError(f"Video metadata is missing: {video_path}")
    current = video_path.read_text(encoding="utf-8")
    if UNIFIED_MARKER in current:
        return {"status": "cached", "metadata": str(video_path)}
    if not photo_path.is_file():
        raise FileNotFoundError(f"Photo metadata is missing: {photo_path}")

    video_lines = current.splitlines()
    photo_lines = photo_path.read_text(encoding="utf-8").splitlines()
    backup_dir = day_dir / "backups" / "metadata-before-unification-2026-08-01"
    _copy_backup(video_path, backup_dir / "metadata.video.txt")
    _copy_backup(photo_path, backup_dir / "metadata.photo.txt")

    header = video_lines[:6]
    video_body = _sanitise(_after_heading(video_lines, "MASTER PRODUCTION NOTES"), "video")
    photo_body = _sanitise(_after_heading(photo_lines, "INSTAGRAM"), "photo")
    unified = "\n".join(
        header
        + [UNIFIED_MARKER, "", "VIDEO / REEL", ""]
        + video_body
        + ["", "PHOTO / CAROUSEL", ""]
        + photo_body
    ).rstrip() + "\n"
    video_path.write_text(unified, encoding="utf-8")
    photo_path.unlink()

    manifest_path = day_dir / "photo_gallery_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["metadata_file"] = "metadata.txt"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    qa_path = day_dir / "photo_gallery_qa.json"
    if qa_path.is_file():
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        qa.setdefault("checks", {})["metadata_exists"] = video_path.is_file()
        qa_path.write_text(json.dumps(qa, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"status": "unified", "metadata": str(video_path), "backup": str(backup_dir)}


def add_youtube_companion_metadata(day_dir: Path, job: dict) -> dict:
    """Insert one YouTube companion entry into the day's single metadata file."""
    day_dir = day_dir.resolve()
    path = day_dir / "metadata.txt"
    if not path.is_file():
        raise FileNotFoundError(f"Primary metadata must exist before the companion Short: {path}")
    text = path.read_text(encoding="utf-8")
    marker = "YOUTUBE SHORTS - COMPANION"
    data = job["platforms"]["youtube_shorts"]
    hashtags = data.get("hashtags", [])
    if isinstance(hashtags, list):
        hashtags = ", ".join(hashtags)
    section = "\n".join(
        [
            marker,
            f"File stem: {job['output_stem']}",
            f"Title: {data.get('title', '')}",
            f"Caption: {extend_caption(data.get('caption', ''), 'video')}",
            f"CTA: {data.get('cta', '')}",
            f"Hashtags: {hashtags}",
            f"Music: {data.get('music_search', '')}",
            f"Scheduling: {data.get('schedule_notes', '')}",
        ]
    ).rstrip() + "\n"
    if marker in text:
        if f"File stem: {job['output_stem']}" in text:
            return {"status": "cached", "metadata": str(path)}
        backup = day_dir / "backups" / "metadata-before-youtube-companion-revision" / f"metadata-before-{job['output_stem']}.txt"
        _copy_backup(path, backup)
        start = text.index(marker)
        photo_heading = "\nPHOTO / CAROUSEL\n"
        end = text.find(photo_heading, start)
        if end < 0:
            updated = text[:start].rstrip() + "\n\n" + section
        else:
            updated = text[:start].rstrip() + "\n\n" + section + text[end:]
        path.write_text(updated, encoding="utf-8")
        return {"status": "revised", "metadata": str(path), "backup": str(backup)}
    backup = day_dir / "backups" / "metadata-before-youtube-companion" / "metadata.txt"
    _copy_backup(path, backup)
    photo_heading = "\nPHOTO / CAROUSEL\n"
    if photo_heading in text:
        updated = text.replace(photo_heading, f"\n{section}\nPHOTO / CAROUSEL\n", 1)
    else:
        updated = text.rstrip() + "\n\n" + section
    path.write_text(updated, encoding="utf-8")
    return {"status": "added", "metadata": str(path), "backup": str(backup)}

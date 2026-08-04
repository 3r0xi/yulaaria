from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from .paths import inside_content_root


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_folder(folder: Path) -> dict:
    folder = inside_content_root(folder)
    if not folder.is_dir():
        raise FileNotFoundError(folder)
    files = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        files.append({
            "path": str(path.relative_to(folder)),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    required = {"manifest.json", "metadata.txt", "qa_report.txt"}
    names = {item["path"] for item in files}
    return {
        "folder": str(folder),
        "files": files,
        "missing_required": sorted(required - names),
        "passed": required.issubset(names),
    }


def write_report(result: dict, output: Path) -> None:
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _probe_media(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required but was not found on PATH")
    raw = subprocess.check_output([
        ffprobe, "-v", "error",
        "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
        "-of", "json", str(path),
    ], text=True, encoding="utf-8")
    return json.loads(raw)


def finalize_automated_qa(draft_manifest: Path) -> dict:
    from .manifest import validate_manifest

    draft_manifest = draft_manifest.resolve()
    day_dir = draft_manifest.parent
    errors = validate_manifest(draft_manifest, verify_files=True)
    if errors:
        raise ValueError("Draft manifest validation failed: " + "; ".join(errors))
    data = json.loads(draft_manifest.read_text(encoding="utf-8"))
    output_stem = data["render"].get("output_stem")
    if not output_stem:
        raise ValueError("render.output_stem is required for deterministic QA")
    exports = day_dir / "exports"
    silent = exports / f"{output_stem}_silent.mp4"
    original = exports / f"{output_stem}_original_audio.mp4"
    cover = exports / f"{output_stem}_cover.png"
    receipt = exports / f"{output_stem}_render_receipt.json"
    contact_sheet = exports / f"{output_stem}_contact_sheet.png"
    carousel = data["render"].get("carousel") or {}
    carousel_count = len(carousel.get("source_indices", [])) if carousel.get("enabled") else 0
    carousel_paths = [exports / "carousel" / f"{output_stem}_carousel_{number:02d}.jpg" for number in range(1, carousel_count + 1)]
    missing_outputs = [str(path) for path in (silent, original, cover, receipt, contact_sheet, *carousel_paths) if not path.is_file()]
    if missing_outputs:
        raise ValueError("Missing render outputs: " + ", ".join(missing_outputs))
    silent_probe = _probe_media(silent)
    original_probe = _probe_media(original)

    silent_streams = silent_probe.get("streams", [])
    original_streams = original_probe.get("streams", [])
    silent_video = next((stream for stream in silent_streams if stream.get("codec_type") == "video"), {})
    original_video = next((stream for stream in original_streams if stream.get("codec_type") == "video"), {})
    original_audio = next((stream for stream in original_streams if stream.get("codec_type") == "audio"), {})
    silent_duration = float(silent_probe["format"]["duration"])
    original_duration = float(original_probe["format"]["duration"])
    expected_duration = float(data["render"]["duration_seconds"])
    tolerance = max(0.12, 1 / float(data["render"].get("fps", 30)) * 2)
    checks = {
        "silent_is_h264_1080x1920": silent_video.get("codec_name") == "h264" and silent_video.get("width") == 1080 and silent_video.get("height") == 1920,
        "silent_has_no_audio_stream": not any(stream.get("codec_type") == "audio" for stream in silent_streams),
        "silent_duration_matches_manifest": abs(silent_duration - expected_duration) <= tolerance,
        "original_video_matches_master": original_video.get("codec_name") == "h264" and original_video.get("width") == 1080 and original_video.get("height") == 1920,
        "original_has_aac_audio": original_audio.get("codec_name") == "aac" and int(original_audio.get("channels", 0)) == 2,
        "original_duration_matches_manifest": abs(original_duration - expected_duration) <= tolerance,
        "cover_exists": cover.is_file() and cover.stat().st_size > 0,
        "render_receipt_exists": receipt.is_file() and receipt.stat().st_size > 0,
        "contact_sheet_exists": contact_sheet.is_file() and contact_sheet.stat().st_size > 0,
        "metadata_exists": (day_dir / "metadata.txt").is_file(),
    }
    if data["render"].get("audio_sync_enabled"):
        rhythm_file = data["render"].get("rhythm_cues_file")
        checks["rhythm_cues_exist"] = bool(rhythm_file) and (day_dir / rhythm_file).is_file()
    carousel_outputs = []
    if carousel_paths:
        for path in carousel_paths:
            probe = _probe_media(path)
            video = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"), {})
            carousel_outputs.append({"path": str(path), "sha256": sha256_file(path), "probe": probe})
            checks[f"carousel_{len(carousel_outputs):02d}_is_1080x1350"] = (
                video.get("width") == 1080 and video.get("height") == 1350
            )
    passed = all(checks.values())
    outputs = {
        "silent_master": {"path": str(silent), "sha256": sha256_file(silent), "probe": silent_probe},
        "original_audio_master": {"path": str(original), "sha256": sha256_file(original), "probe": original_probe},
        "cover": {"path": str(cover), "sha256": sha256_file(cover)},
        "contact_sheet": {"path": str(contact_sheet), "sha256": sha256_file(contact_sheet)},
    }
    if carousel_outputs:
        outputs["carousel"] = carousel_outputs
    report = {
        "passed": passed,
        "approval_required": True,
        "checks": checks,
        "outputs": outputs,
        "note": "Automated QA does not replace a human visual/audio review and does not authorize publication.",
    }
    draft_name = draft_manifest.name
    if draft_name == "manifest.draft.json":
        suffix = ""
    elif draft_name.startswith("manifest.") and draft_name.endswith(".draft.json"):
        suffix = "." + draft_name[len("manifest.") : -len(".draft.json")]
    else:
        raise ValueError("Draft manifest must be named manifest.draft.json or manifest.<slot>.draft.json")
    report_path = day_dir / f"qa_report{suffix}.txt"
    final_manifest = day_dir / f"manifest{suffix}.json"
    if report_path.exists() or final_manifest.exists():
        raise FileExistsError("Refusing to overwrite an existing qa_report.txt or manifest.json")
    if not passed:
        raise ValueError("Automated QA failed: " + ", ".join(name for name, ok in checks.items() if not ok))
    data["production_status"] = "qa_passed"
    data["operator_notes"] = "Automated technical QA passed. Human visual/audio approval is still required before scheduling or publication."
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    final_manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report

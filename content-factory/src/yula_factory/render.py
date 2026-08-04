from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .manifest import validate_manifest
from .qa import sha256_file


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} is required but was not found on PATH")
    return path


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def _probe(path: Path) -> dict:
    output = subprocess.check_output(
        [
            _tool("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        encoding="utf-8",
    )
    return json.loads(output)


def _pattern_interrupt_filter(cues: list[float]) -> str:
    filters = []
    for cue in cues:
        start = max(0.0, float(cue))
        end = start + 0.14
        filters.append(f"eq=brightness=0.018:contrast=1.07:enable='between(t,{start:.3f},{end:.3f})'")
    return ",".join(filters)


def render_manifest(manifest_path: Path, force: bool = False) -> dict:
    manifest_path = manifest_path.resolve()
    errors = validate_manifest(manifest_path, verify_files=True)
    if errors:
        raise ValueError("Manifest validation failed: " + "; ".join(errors))
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    day_dir = manifest_path.parent
    selected = [
        item for item in data["sources"]
        if item.get("asset_type") in {"video", "photo", "texture"} and item.get("selected")
    ]
    if not selected:
        raise ValueError("At least one selected visual source is required")

    render = data["render"]
    duration = float(render["duration_seconds"])
    output_stem = render.get("output_stem") or f"YA_D{data['day']:02d}_{data['theme'].lower().replace(' ', '_')}_v01"
    overlay_file = render.get("overlay_file")
    cover_overlay_file = render.get("cover_overlay_file")
    audio_file = (render.get("audio") or {}).get("audio_file")
    if not overlay_file or not cover_overlay_file or not audio_file:
        raise ValueError("render.overlay_file, cover_overlay_file, and audio.audio_file are required")

    exports = day_dir / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    silent = exports / f"{output_stem}_silent.mp4"
    original = exports / f"{output_stem}_original_audio.mp4"
    cover = exports / f"{output_stem}_cover.png"
    receipt = exports / f"{output_stem}_render_receipt.json"
    contact_sheet = exports / f"{output_stem}_contact_sheet.png"
    carousel = render.get("carousel") or {}
    carousel_indices = carousel.get("source_indices", []) if carousel.get("enabled") else []
    carousel_dir = exports / "carousel"
    carousel_paths = [
        carousel_dir / f"{output_stem}_carousel_{number:02d}.jpg"
        for number in range(1, len(carousel_indices) + 1)
    ]
    targets = (silent, original, cover, receipt, contact_sheet, *carousel_paths)
    existing = [str(path) for path in targets if path.exists()]
    if existing and not force:
        raise FileExistsError("Refusing to overwrite existing render outputs: " + ", ".join(existing))

    ffmpeg = _tool("ffmpeg")
    input_args: list[str] = []
    filters: list[str] = []
    clip_durations: list[float] = []
    reverse_indices = set(render.get("reverse_source_indices", []))
    for index, item in enumerate(selected):
        source = day_dir / item["local_path"]
        offset = float(item.get("offset_seconds", 0))
        clip_duration = float(item.get("clip_duration_seconds", duration / len(selected)))
        clip_durations.append(clip_duration)
        asset_type = str(item.get("asset_type", "video"))
        if asset_type in {"photo", "texture"}:
            input_args.extend(["-loop", "1", "-t", str(clip_duration), "-i", str(source)])
        else:
            input_args.extend(["-ss", str(offset), "-t", str(clip_duration), "-i", str(source)])
        fit_mode = str(item.get("fit_mode", "pan_zoom" if asset_type in {"photo", "texture"} else "cover"))
        base = f"[{index}:v]trim=duration={clip_duration},setpts=PTS-STARTPTS"
        finish = "setsar=1,fps=30,format=yuv420p,eq=contrast=1.04:saturation=0.92:brightness=-0.01"
        reverse_filter = ",reverse" if index in reverse_indices and asset_type == "video" else ""
        if fit_mode == "contain_blur":
            filters.append(f"{base},split=2[bg{index}][fg{index}]")
            filters.append(
                f"[bg{index}]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                f"gblur=sigma=32[blur{index}]"
            )
            filters.append(
                f"[fg{index}]scale=1080:1920:force_original_aspect_ratio=decrease[front{index}]"
            )
            filters.append(
                f"[blur{index}][front{index}]overlay=(W-w)/2:(H-h)/2,{finish}{reverse_filter}[v{index}]"
            )
        elif fit_mode == "contain_color":
            filters.append(
                f"{base},scale=1080:1920:force_original_aspect_ratio=decrease,"
                f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x111111,{finish}{reverse_filter}[v{index}]"
            )
        elif fit_mode == "pan_zoom" or asset_type in {"photo", "texture"}:
            filters.append(
                f"{base},scale=1200:2134:force_original_aspect_ratio=increase,crop=1200:2134,"
                "zoompan=z='min(zoom+0.00045,1.08)':x='iw/2-(iw/zoom/2)':"
                "y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,"
                f"{finish}[v{index}]"
            )
        else:
            filters.append(
                f"{base},scale=1080:1920:force_original_aspect_ratio=increase,"
                f"crop=1080:1920,{finish}{reverse_filter}[v{index}]"
            )
    transition = float(render.get("transition_seconds", 0))
    if transition and len(selected) > 1:
        transition_type = str(render.get("transition_type", "fade"))
        if transition_type not in {"fade", "dissolve", "wipeleft", "smoothleft", "circleopen", "fadeblack"}:
            raise ValueError(f"Unsupported transition_type: {transition_type}")
        previous = "v0"
        cumulative_duration = clip_durations[0]
        for index in range(1, len(selected)):
            output = f"xf{index}"
            offset = cumulative_duration - transition * index
            filters.append(
                f"[{previous}][v{index}]xfade=transition={transition_type}:duration={transition}:offset={offset}[{output}]"
            )
            previous = output
            cumulative_duration += clip_durations[index]
        filters.append(f"[{previous}]null[montage]")
    else:
        concat_inputs = "".join(f"[v{index}]" for index in range(len(selected)))
        filters.append(f"{concat_inputs}concat=n={len(selected)}:v=1:a=0[montage]")
    retention_filter = _pattern_interrupt_filter(render.get("pattern_interrupt_seconds", []))
    retention_chain = f"{retention_filter}," if retention_filter else ""
    filters.append(f"[montage]{retention_chain}subtitles={overlay_file},format=yuv420p[finalv]")
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            *input_args,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[finalv]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-movflags",
            "+faststart",
            str(silent),
        ],
        day_dir,
    )

    carousel_results = []
    carousel_offsets = carousel.get("offset_seconds", [])
    if carousel_indices:
        carousel_dir.mkdir(parents=True, exist_ok=True)
        for number, source_index in enumerate(carousel_indices, 1):
            if not 0 <= int(source_index) < len(selected):
                raise ValueError("carousel source index is outside the selected source list")
            item = selected[int(source_index)]
            source = day_dir / item["local_path"]
            offset = (
                float(carousel_offsets[number - 1])
                if number - 1 < len(carousel_offsets)
                else float(item.get("offset_seconds", 0))
            )
            target = carousel_paths[number - 1]
            _run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y" if force else "-n",
                    "-ss",
                    str(offset),
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=1080:1350:force_original_aspect_ratio=increase,crop=1080:1350,setsar=1,"
                    "eq=contrast=1.03:saturation=0.90:brightness=0.01",
                    "-q:v",
                    "2",
                    str(target),
                ],
                day_dir,
            )
            carousel_results.append({"path": str(target), "sha256": sha256_file(target), "probe": _probe(target)})

    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            "-i",
            str(silent),
            "-stream_loop",
            "-1",
            "-i",
            str(day_dir / audio_file),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-af",
            f"atrim=0:{duration},asetpts=N/SR/TB,afade=t=in:st=0:d=0.08,"
            f"afade=t=out:st={max(0.0, duration - 0.25)}:d=0.25,loudnorm=I=-16:LRA=7:TP=-1.5",
            "-t",
            str(duration),
            "-movflags",
            "+faststart",
            str(original),
        ],
        day_dir,
    )

    cover_index = int(render.get("cover_source_index", 0))
    if not 0 <= cover_index < len(selected):
        raise ValueError("cover_source_index is outside the selected source list")
    cover_source = day_dir / selected[cover_index]["local_path"]
    cover_offset = float(render.get("cover_offset_seconds", selected[cover_index].get("offset_seconds", 0)))
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            "-ss",
            str(cover_offset),
            "-i",
            str(cover_source),
            "-frames:v",
            "1",
            "-vf",
            f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,subtitles={cover_overlay_file}",
            str(cover),
        ],
        day_dir,
    )

    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y" if force else "-n",
            "-i",
            str(silent),
            "-vf",
            f"fps={6 / duration},scale=360:640,tile=3x2",
            "-frames:v",
            "1",
            str(contact_sheet),
        ],
        day_dir,
    )

    output_results = {
        "silent_master": {"path": str(silent), "sha256": sha256_file(silent), "probe": _probe(silent)},
        "original_audio_master": {"path": str(original), "sha256": sha256_file(original), "probe": _probe(original)},
        "cover": {"path": str(cover), "sha256": sha256_file(cover)},
        "contact_sheet": {"path": str(contact_sheet), "sha256": sha256_file(contact_sheet)},
    }
    if carousel_results:
        output_results["carousel"] = carousel_results
    result = {
        "manifest": str(manifest_path),
        "sources": [str(day_dir / item["local_path"]) for item in selected],
        "outputs": output_results,
        "approval_required": True,
    }
    receipt.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result

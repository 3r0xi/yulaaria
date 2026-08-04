from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .kie_suno import KieSunoClient, build_generate_payload, extract_tracks
from .ledger import initialize_database
from .paths import DEFAULT_DB
from .qa import sha256_file
from .secrets import config_value


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_stable(path: Path, value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") == text:
            return
        raise FileExistsError(f"Refusing to overwrite changed music artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def validate_music_config(config: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(config, dict):
        return ["music must be an object"]
    if config.get("provider") != "kie_suno":
        errors.append("music.provider must be kie_suno")
    if not str(config.get("associated_content_id", "")).strip():
        errors.append("music.associated_content_id is required")
    try:
        version = int(config.get("version", 1))
        if version < 1:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("music.version must be a positive integer")
    brief = config.get("brief")
    if not isinstance(brief, dict):
        errors.append("music.brief must be an object")
    else:
        try:
            build_generate_payload(brief)
        except (TypeError, ValueError) as exc:
            errors.append(f"music.brief is invalid: {exc}")
    index = config.get("selected_variation_index", 0)
    if not isinstance(index, int) or index < 0:
        errors.append("music.selected_variation_index must be zero or greater")
    return errors


def prepare_or_generate_music(
    config: dict,
    day_dir: Path,
    db_path: Path = DEFAULT_DB,
    client: KieSunoClient | None = None,
) -> dict:
    """Persist a reproducible Kie request and optionally execute it.

    A billable request needs both config.generate=true and YULA_KIE_LIVE=1.
    """
    errors = validate_music_config(config)
    if errors:
        raise ValueError("Invalid music configuration: " + "; ".join(errors))
    content_id = str(config["associated_content_id"]).strip()
    version = int(config.get("version", 1))
    payload, decision = build_generate_payload(config["brief"])
    if not payload.get("callBackUrl"):
        callback_url = config_value("KIE_CALLBACK_URL")
        if not callback_url:
            public_base = config_value("YULA_PUBLIC_MEDIA_BASE_URL").rstrip("/")
            callback_url = f"{public_base}/v1/kie/callback" if public_base else ""
        if not callback_url.startswith("https://"):
            raise RuntimeError("Kie generation requires an HTTPS callback URL; start the public tunnel first")
        payload["callBackUrl"] = callback_url
    music_root = day_dir / "music"
    request_path = music_root / "requests" / f"v{version:02d}_generate.json"
    brief_path = music_root / "metadata" / f"v{version:02d}_brief.json"
    response_path = music_root / "responses" / f"v{version:02d}_response.json"
    metadata_path = music_root / "metadata" / f"v{version:02d}_track.json"
    _write_stable(request_path, payload)
    _write_stable(
        brief_path,
        {
            "associated_content_id": content_id,
            "version": version,
            "provider": "kie_suno",
            "model_decision": {"model": decision.model, "reason": decision.reason},
            "creative_brief": config["brief"],
            "creative_notes": config.get("creative_notes", ""),
            "licensing_notes": config.get("licensing_notes", "Not supplied by the API response; verify current service terms before distribution."),
            "request_file": request_path.relative_to(day_dir).as_posix(),
        },
    )

    initialize_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute(
            "SELECT id,status,task_id,selected_audio_path FROM music_generations WHERE associated_content_id=? AND version=?",
            (content_id, version),
        ).fetchone()
        if row and row[1] == "completed" and row[3] and Path(row[3]).is_file():
            return {
                "status": "cached",
                "generation_id": row[0],
                "task_id": row[2],
                "audio_file": row[3],
                "request_file": str(request_path),
            }
        if not row:
            cursor = connection.execute(
                """INSERT INTO music_generations
                (associated_content_id,version,model,model_reason,request_json,status,creative_notes,licensing_notes)
                VALUES (?,?,?,?,?,'planned',?,?)""",
                (
                    content_id,
                    version,
                    decision.model,
                    decision.reason,
                    _json(payload),
                    str(config.get("creative_notes", "")),
                    str(config.get("licensing_notes", "Not supplied by the API response; verify current service terms before distribution.")),
                ),
            )
            generation_id = int(cursor.lastrowid)
        else:
            generation_id = int(row[0])
            connection.execute(
                """UPDATE music_generations SET model=?,model_reason=?,request_json=?,status='planned',
                creative_notes=?,licensing_notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (
                    decision.model,
                    decision.reason,
                    _json(payload),
                    str(config.get("creative_notes", "")),
                    str(config.get("licensing_notes", "Not supplied by the API response; verify current service terms before distribution.")),
                    generation_id,
                ),
            )
        connection.commit()

    if not bool(config.get("generate", False)):
        return {
            "status": "planned",
            "generation_id": generation_id,
            "model": decision.model,
            "model_reason": decision.reason,
            "request_file": str(request_path),
            "network_used": False,
        }
    if os.environ.get("YULA_KIE_LIVE") != "1":
        raise PermissionError("Billable Kie generation blocked: set YULA_KIE_LIVE=1 for an explicitly approved run")

    api = client or KieSunoClient()
    task_id = api.submit_generation(payload)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "UPDATE music_generations SET task_id=?,status='submitted',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (task_id, generation_id),
        )
        connection.commit()
    try:
        response = api.wait_for_completion(
            task_id,
            timeout_seconds=int(config.get("timeout_seconds", 900)),
            poll_seconds=int(config.get("poll_seconds", 30)),
        )
        tracks = extract_tracks(response)
        if not tracks:
            raise RuntimeError("Kie generation completed without downloadable tracks")
        selected_index = int(config.get("selected_variation_index", 0))
        if selected_index >= len(tracks):
            raise ValueError(f"selected_variation_index {selected_index} exceeds {len(tracks)} returned tracks")
        track = tracks[selected_index]
        audio_id = str(track.get("id", "")).strip()
        extension = Path(str(track["audioUrl"]).split("?", 1)[0]).suffix.lower()
        if extension not in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}:
            extension = ".mp3"
        audio_path = music_root / "audio" / f"v{version:02d}_{audio_id or 'selected'}{extension}"
        api.download_audio(str(track["audioUrl"]), audio_path)
        _write_stable(response_path, response)
        metadata = {
            "associated_content_id": content_id,
            "version": version,
            "provider": "kie_suno",
            "task_id": task_id,
            "audio_id": audio_id,
            "model_requested": decision.model,
            "model_returned": track.get("modelName"),
            "title": track.get("title") or payload["title"],
            "duration_seconds": track.get("duration"),
            "tags": track.get("tags"),
            "prompt_or_lyrics": track.get("prompt"),
            "audio_file": audio_path.relative_to(day_dir).as_posix(),
            "audio_sha256": sha256_file(audio_path),
            "request_file": request_path.relative_to(day_dir).as_posix(),
            "response_file": response_path.relative_to(day_dir).as_posix(),
            "creative_notes": config.get("creative_notes", ""),
            "licensing_notes": config.get("licensing_notes", "Not supplied by the API response; verify current service terms before distribution."),
            "usage_history": [],
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_stable(metadata_path, metadata)
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(
                """UPDATE music_generations SET status='completed',response_json=?,selected_audio_id=?,
                selected_audio_path=?,duration_seconds=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (
                    _json(response),
                    audio_id or None,
                    str(audio_path.resolve()),
                    float(track.get("duration")) if track.get("duration") is not None else None,
                    generation_id,
                ),
            )
            connection.commit()
        return {
            "status": "completed",
            "generation_id": generation_id,
            "task_id": task_id,
            "audio_id": audio_id,
            "audio_file": str(audio_path),
            "request_file": str(request_path),
            "response_file": str(response_path),
            "metadata_file": str(metadata_path),
            "network_used": True,
        }
    except Exception as exc:
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(
                "UPDATE music_generations SET status='failed',response_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (_json({"error_type": type(exc).__name__, "message": str(exc)[:1000]}), generation_id),
            )
            connection.commit()
        raise

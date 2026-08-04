from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import buffer as buffer_api
from . import meta as meta_api
from . import tiktok as tiktok_api
from . import youtube as youtube_api
from .ledger import initialize_database
from .media_host import create_signed_media_url
from .paths import DEFAULT_DB, inside_content_root
from .secrets import config_value
from .storage import stage_media


PLATFORM_PROVIDERS = {
    "facebook": {"meta"},
    "instagram": {"meta"},
    "threads": {"meta", "buffer"},
    "youtube": {"youtube"},
    "x": {"buffer"},
    "tiktok": {"tiktok", "manual"},
}
DEFAULT_LEAD_MINUTES = {"meta": 0, "buffer": 10_080, "youtube": 1_440, "tiktok": 0, "manual": 10_080}
IMMEDIATE_SCHEDULING_PROVIDERS = {"buffer", "youtube"}
SECRET_FIELDS = {"access_token", "api_key", "client_secret", "refresh_token", "password"}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def plan_digest(plan: dict) -> str:
    return hashlib.sha256(_canonical(plan)).hexdigest()


def _aware_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("must include an explicit UTC offset")
    return parsed


def validate_plan(plan: dict, verify_files: bool = True) -> list[str]:
    errors: list[str] = []
    if plan.get("version") != 1:
        errors.append("version must be 1")
    if not str(plan.get("timezone", "")).strip():
        errors.append("timezone is required")
    posts = plan.get("posts")
    if not isinstance(posts, list) or not posts:
        return errors + ["posts must be a non-empty list"]
    seen: set[str] = set()
    for index, post in enumerate(posts):
        prefix = f"posts[{index}]"
        if not isinstance(post, dict):
            errors.append(f"{prefix} must be an object")
            continue
        forbidden = SECRET_FIELDS.intersection(key.lower() for key in post)
        if forbidden:
            errors.append(f"{prefix} contains forbidden secret fields: {', '.join(sorted(forbidden))}")
        platform = str(post.get("platform", "")).lower()
        provider = str(post.get("provider", "")).lower()
        if provider not in PLATFORM_PROVIDERS.get(platform, set()):
            errors.append(f"{prefix} provider {provider!r} is invalid for platform {platform!r}")
        try:
            day = int(post.get("day"))
            if not 1 <= day <= 30:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{prefix}.day must be between 1 and 30")
        if not str(post.get("slot", "")).strip():
            errors.append(f"{prefix}.slot is required")
        try:
            _aware_datetime(post.get("due_at"))
        except (TypeError, ValueError):
            errors.append(f"{prefix}.due_at must be timezone-aware ISO 8601")
        key = str(post.get("idempotency_key") or f"day{post.get('day')}:{post.get('slot')}:{platform}")
        if key in seen:
            errors.append(f"{prefix} duplicates idempotency key {key!r}")
        seen.add(key)
        media = post.get("media_path")
        if media and verify_files:
            try:
                resolved = inside_content_root(Path(str(media)))
                if not resolved.is_file():
                    errors.append(f"{prefix}.media_path does not exist: {resolved}")
            except ValueError as exc:
                errors.append(f"{prefix}.media_path {exc}")
        if platform in {"facebook", "instagram", "threads", "x"} and not str(post.get("text", "")).strip():
            errors.append(f"{prefix}.text is required")
        if platform == "youtube":
            if not media:
                errors.append(f"{prefix}.media_path is required for YouTube")
            if not str(post.get("title", "")).strip():
                errors.append(f"{prefix}.title is required for YouTube")
            tags = post.get("tags", [])
            if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
                errors.append(f"{prefix}.tags must be a list of strings")
        if platform == "tiktok" and provider == "tiktok":
            media_type = str(post.get("media_type", "video")).lower()
            if media_type == "video" and not media:
                errors.append(f"{prefix}.media_path is required for TikTok video Direct Post")
            if media_type in {"image", "photo", "carousel"}:
                urls = post.get("public_media_urls") or ([post.get("public_media_url")] if post.get("public_media_url") else [])
                if not isinstance(urls, list) or not urls or any(not str(url).startswith("https://") for url in urls):
                    errors.append(f"{prefix}.public_media_urls must contain verified HTTPS URLs for TikTok photos")
            elif media_type != "video":
                errors.append(f"{prefix}.media_type must be video, image, photo, or carousel for TikTok")
            privacy = str(post.get("privacy_level", "SELF_ONLY")).upper()
            if privacy not in {"PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"}:
                errors.append(f"{prefix}.privacy_level is invalid for TikTok")
        if platform in {"instagram", "threads"} and media and post.get("public_media_url"):
            url = str(post.get("public_media_url", ""))
            if not url.startswith("https://"):
                errors.append(f"{prefix}.public_media_url must be an HTTPS URL for Meta media publishing")
        if provider == "buffer":
            if not str(post.get("channel_id", "")).strip():
                errors.append(f"{prefix}.channel_id is required for Buffer")
            if media and not str(post.get("public_media_url", "")).startswith("https://"):
                errors.append(f"{prefix}.public_media_url is required for Buffer media")
    return errors


def load_plan(path: Path, verify_files: bool = True) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_plan(plan, verify_files=verify_files)
    if errors:
        raise ValueError("Invalid schedule plan: " + "; ".join(errors))
    return plan


def store_plan(path: Path, db_path: Path = DEFAULT_DB, verify_files: bool = True) -> dict:
    plan = load_plan(path, verify_files=verify_files)
    digest = plan_digest(plan)
    initialize_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        existing = connection.execute("SELECT id, status FROM schedule_plans WHERE digest=?", (digest,)).fetchone()
        if existing:
            return {"status": "cached", "plan_id": existing[0], "plan_status": existing[1], "digest": digest, "posts": len(plan["posts"])}
        cursor = connection.execute(
            "INSERT INTO schedule_plans(digest, source_path, timezone, status) VALUES (?,?,?,'planned')",
            (digest, str(path.resolve()), str(plan["timezone"])),
        )
        plan_id = int(cursor.lastrowid)
        for post in plan["posts"]:
            platform = str(post["platform"]).lower()
            provider = str(post["provider"]).lower()
            key = str(post.get("idempotency_key") or f"day{int(post['day']):02d}:{post['slot']}:{platform}")
            lead = int(post.get("dispatch_lead_minutes", DEFAULT_LEAD_MINUTES[provider]))
            connection.execute(
                """INSERT INTO scheduled_posts
                (plan_id,idempotency_key,day,slot,platform,provider,due_at,dispatch_lead_minutes,payload_json,status)
                VALUES (?,?,?,?,?,?,?,?,?,'planned')""",
                (plan_id, key, int(post["day"]), str(post["slot"]), platform, provider, str(post["due_at"]), lead, _canonical(post).decode("utf-8")),
            )
        connection.commit()
    return {"status": "planned", "plan_id": plan_id, "digest": digest, "posts": len(plan["posts"]), "network_used": False}


def approve_plan(plan_id: int, digest: str, db_path: Path = DEFAULT_DB) -> dict:
    initialize_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute("SELECT digest,status FROM schedule_plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            raise ValueError(f"Unknown schedule plan {plan_id}")
        if row[0] != digest:
            raise PermissionError("Approval blocked: digest does not match the stored plan")
        connection.execute("UPDATE schedule_plans SET status='approved', approved_at=CURRENT_TIMESTAMP WHERE id=?", (plan_id,))
        connection.execute("UPDATE scheduled_posts SET status='approved', updated_at=CURRENT_TIMESTAMP WHERE plan_id=? AND status='planned'", (plan_id,))
        connection.commit()
    return {"status": "approved", "plan_id": plan_id, "digest": digest, "network_used": False}


def _buffer_post(post: dict) -> dict:
    assets = []
    if post.get("public_media_url"):
        kind = "image" if str(post.get("media_type", "video")).lower() == "image" else "video"
        assets.append({kind: post["public_media_url"]})
    return buffer_api.create_post({
        "service": "twitter" if post["platform"] == "x" else post["platform"],
        "channel_id": post["channel_id"],
        "text": post["text"],
        "mode": "customScheduled",
        "due_at": post["due_at"],
        "assets": assets,
    })


def _publish(post: dict) -> dict:
    if post["provider"] == "meta":
        prepared = dict(post)
        if prepared.get("media_path") and prepared["platform"] in {"instagram", "threads"} and not prepared.get("public_media_url"):
            r2_ready = all(
                config_value(name)
                for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME")
            )
            if r2_ready:
                publishing_day = _aware_datetime(prepared["due_at"]).date().isoformat()
                staged = stage_media(Path(str(prepared["media_path"])), publishing_day, expires_hours=48)
                prepared["public_media_url"] = staged["public_media_url"]
                prepared["temporary_media"] = {
                    "provider": "cloudflare_r2",
                    "object_key": staged["object_key"],
                    "expires_at": staged["expires_at"],
                }
            else:
                prepared["public_media_url"] = create_signed_media_url(Path(str(prepared["media_path"])))
        return meta_api.publish(prepared)
    if post["provider"] == "youtube":
        return youtube_api.publish(post)
    if post["provider"] == "buffer":
        return _buffer_post(post)
    if post["provider"] == "tiktok":
        return tiktok_api.publish(post)
    if post["provider"] == "manual":
        return {"manual_required": True}
    raise ValueError(f"Unknown provider {post['provider']}")


def dispatch_due(
    limit: int = 10,
    now: datetime | None = None,
    db_path: Path = DEFAULT_DB,
    live: bool = False,
    catch_up_minutes: int | None = None,
) -> dict:
    if live and os.environ.get("YULA_SCHEDULER_LIVE") != "1":
        raise PermissionError("Live dispatch blocked: set YULA_SCHEDULER_LIVE=1 after controlled provider tests")
    initialize_database(db_path)
    current = now or datetime.now(timezone.utc)
    grace = int(catch_up_minutes if catch_up_minutes is not None else os.environ.get("YULA_SCHEDULER_CATCH_UP_MINUTES", "120"))
    if not 0 <= grace <= 1_440:
        raise ValueError("catch_up_minutes must be between 0 and 1440")
    max_attempts = max(1, min(int(os.environ.get("YULA_SCHEDULER_MAX_ATTEMPTS", "3")), 10))
    selected: list[tuple] = []
    missed: list[tuple] = []
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(
            """SELECT sp.id,sp.payload_json,sp.due_at,sp.dispatch_lead_minutes,sp.provider,sp.attempts
            FROM scheduled_posts sp JOIN schedule_plans p ON p.id=sp.plan_id
            WHERE p.status='approved' AND sp.status IN ('approved','failed')
            ORDER BY sp.due_at LIMIT ?""",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
        for row in rows:
            due = _aware_datetime(row[2]).astimezone(timezone.utc)
            if due < current.astimezone(timezone.utc) - timedelta(minutes=grace):
                missed.append(row)
            elif int(row[5]) < max_attempts and due <= current.astimezone(timezone.utc) + timedelta(minutes=int(row[3])):
                selected.append(row)

    preview = [{"post_id": row[0], "provider": row[4], "due_at": row[2]} for row in selected]
    missed_preview = [
        {"post_id": row[0], "provider": row[4], "due_at": row[2], "reason": "outside_catch_up_window"}
        for row in missed
    ]
    if not live:
        return {"status": "dry_run", "eligible": preview, "missed": missed_preview, "network_used": False}

    with closing(sqlite3.connect(db_path)) as connection:
        run_cursor = connection.execute(
            "INSERT INTO scheduler_runs(live,eligible_count,missed_count) VALUES (1,?,?)",
            (len(selected), len(missed)),
        )
        scheduler_run_id = int(run_cursor.lastrowid)
        for post_id, _, due_at, _, _, _ in missed:
            connection.execute(
                """UPDATE scheduled_posts SET status='manual_required',last_error=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status IN ('approved','failed')""",
                (f"Automatic dispatch window missed for {due_at}; operator review required", post_id),
            )
        connection.commit()

    results: list[dict] = []
    for post_id, payload_json, due_at, _, provider, _ in selected:
        post = json.loads(payload_json)
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute("UPDATE scheduled_posts SET status='submitting', attempts=attempts+1, updated_at=CURRENT_TIMESTAMP WHERE id=?", (post_id,))
            connection.commit()
        try:
            result = _publish(post)
            state = "manual_required" if result.get("manual_required") else ("scheduled" if result.get("provider_status") or _aware_datetime(due_at) > current else "published")
            external_id = result.get("external_id") or result.get("id")
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute(
                    "UPDATE scheduled_posts SET status=?,external_id=?,last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (state, str(external_id) if external_id else None, post_id),
                )
                connection.commit()
            results.append({"post_id": post_id, "status": state, "external_id": external_id, "provider": provider})
        except Exception as exc:
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute(
                    "UPDATE scheduled_posts SET status='failed',last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(exc)[:4000], post_id),
                )
                connection.commit()
            results.append({"post_id": post_id, "status": "failed", "provider": provider, "error": str(exc)})
    result = {
        "status": "complete",
        "scheduler_run_id": scheduler_run_id,
        "processed": len(results),
        "missed": missed_preview,
        "results": results,
        "network_used": True,
    }
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """UPDATE scheduler_runs SET finished_at=CURRENT_TIMESTAMP,processed_count=?,result_json=? WHERE id=?""",
            (len(results), json.dumps(result, ensure_ascii=False, separators=(",", ":")), scheduler_run_id),
        )
        connection.commit()
    return result


def submit_approved_now(
    plan_id: int,
    platforms: list[str] | None = None,
    db_path: Path = DEFAULT_DB,
    live: bool = False,
) -> dict:
    """Submit approved posts immediately to providers that support future scheduling.

    Meta is intentionally excluded: the current Meta publisher creates posts
    immediately instead of creating a native future-scheduled calendar item.
    """
    if live and os.environ.get("YULA_SCHEDULER_LIVE") != "1":
        raise PermissionError("Live submission blocked: set YULA_SCHEDULER_LIVE=1 after controlled provider tests")
    initialize_database(db_path)
    requested = {str(value).lower() for value in (platforms or []) if str(value).strip()}
    unknown = requested.difference(PLATFORM_PROVIDERS)
    if unknown:
        raise ValueError(f"Unknown platforms: {', '.join(sorted(unknown))}")

    with closing(sqlite3.connect(db_path)) as connection:
        plan = connection.execute("SELECT status FROM schedule_plans WHERE id=?", (plan_id,)).fetchone()
        if not plan:
            raise ValueError(f"Unknown schedule plan {plan_id}")
        if plan[0] != "approved":
            raise PermissionError(f"Schedule plan {plan_id} is not approved")
        rows = connection.execute(
            """SELECT id,payload_json,due_at,provider,platform
            FROM scheduled_posts
            WHERE plan_id=? AND status IN ('approved','failed')
            ORDER BY due_at,platform""",
            (plan_id,),
        ).fetchall()

    selected = [row for row in rows if (not requested or row[4] in requested)]
    eligible = [row for row in selected if row[3] in IMMEDIATE_SCHEDULING_PROVIDERS]
    deferred = [
        {
            "post_id": row[0],
            "platform": row[4],
            "provider": row[3],
            "reason": "platform_ui_required" if row[3] == "meta" else ("local_due_dispatch_required" if row[3] == "tiktok" else "manual_required"),
        }
        for row in selected
        if row[3] not in IMMEDIATE_SCHEDULING_PROVIDERS
    ]
    preview = [
        {"post_id": row[0], "platform": row[4], "provider": row[3], "due_at": row[2]}
        for row in eligible
    ]
    if not live:
        return {"status": "dry_run", "eligible": preview, "deferred": deferred, "network_used": False}

    current = datetime.now(timezone.utc)
    results: list[dict] = []
    for post_id, payload_json, due_at, provider, platform in eligible:
        post = json.loads(payload_json)
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(
                "UPDATE scheduled_posts SET status='submitting',attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (post_id,),
            )
            connection.commit()
        try:
            result = _publish(post)
            external_id = result.get("external_id") or result.get("id")
            state = "scheduled" if _aware_datetime(due_at).astimezone(timezone.utc) > current else "published"
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute(
                    "UPDATE scheduled_posts SET status=?,external_id=?,last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (state, str(external_id) if external_id else None, post_id),
                )
                connection.commit()
            results.append({"post_id": post_id, "platform": platform, "provider": provider, "status": state, "external_id": external_id})
        except Exception as exc:
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute(
                    "UPDATE scheduled_posts SET status='failed',last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(exc)[:4000], post_id),
                )
                connection.commit()
            results.append({"post_id": post_id, "platform": platform, "provider": provider, "status": "failed", "error": str(exc)})
    return {"status": "complete", "processed": len(results), "results": results, "deferred": deferred, "network_used": True}


def record_external_schedule(post_id: int, external_id: str, db_path: Path = DEFAULT_DB) -> dict:
    """Record a post scheduled through a platform UI without exposing secrets."""
    reference = str(external_id).strip()
    if not reference:
        raise ValueError("external_id is required")
    initialize_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute("SELECT status,external_id FROM scheduled_posts WHERE id=?", (post_id,)).fetchone()
        if not row:
            raise ValueError(f"Unknown scheduled post {post_id}")
        if row[0] == "scheduled" and row[1] == reference:
            return {"status": "cached", "post_id": post_id, "external_id": reference, "network_used": False}
        if row[0] in {"scheduled", "published"} and row[1] and row[1] != reference:
            raise FileExistsError(f"Post {post_id} already has a different external reference")
        if row[0] not in {"approved", "failed", "scheduled"}:
            raise PermissionError(f"Post {post_id} cannot be marked scheduled from status {row[0]}")
        connection.execute(
            "UPDATE scheduled_posts SET status='scheduled',external_id=?,last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (reference, post_id),
        )
        connection.commit()
    return {"status": "scheduled", "post_id": post_id, "external_id": reference, "network_used": False}


def plan_status(plan_id: int, db_path: Path = DEFAULT_DB) -> dict:
    initialize_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        plan = connection.execute("SELECT id,digest,source_path,timezone,status,created_at,approved_at FROM schedule_plans WHERE id=?", (plan_id,)).fetchone()
        if not plan:
            raise ValueError(f"Unknown schedule plan {plan_id}")
        posts = connection.execute(
            "SELECT id,day,slot,platform,provider,due_at,status,external_id,attempts,last_error FROM scheduled_posts WHERE plan_id=? ORDER BY due_at,platform",
            (plan_id,),
        ).fetchall()
    return {
        "plan": dict(zip(("id","digest","source_path","timezone","status","created_at","approved_at"), plan)),
        "posts": [dict(zip(("id","day","slot","platform","provider","due_at","status","external_id","attempts","last_error"), row)) for row in posts],
    }

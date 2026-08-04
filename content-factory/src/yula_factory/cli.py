from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audio import AudioScore, generate_original_audio
from .buffer import get_channels, get_organizations, load_schedule_plan, submit_schedule_plan
from .duration import target_duration_seconds
from .gallery import run_gallery_job, validate_gallery_job
from .ledger import initialize_database
from .job import run_job, validate_job
from .manifest import validate_manifest
from .media_host import create_signed_media_url, ensure_signing_key
from .metadata import unify_day_metadata
from .pexels import search_photos, search_videos, write_search_result
from .qa import finalize_automated_qa, inspect_folder
from .render import render_manifest
from .schedule import approve_plan, dispatch_due, load_plan, plan_status, record_external_schedule, store_plan, submit_approved_now
from .server import serve
from .storage import stage_media
from .tiktok import fetch_status as fetch_tiktok_status
from .youtube import authorize as authorize_youtube


def main() -> None:
    parser = argparse.ArgumentParser(prog="yula-factory")
    sub = parser.add_subparsers(dest="command", required=True)

    init_db = sub.add_parser("init-db", help="Create or upgrade the local learning ledger")
    init_db.add_argument("--path", type=Path)

    audio = sub.add_parser("audio", help="Generate deterministic original procedural audio")
    audio.add_argument("--score", required=True, type=Path)
    audio.add_argument("--output", required=True, type=Path)
    audio.add_argument("--force", action="store_true")

    qa = sub.add_parser("qa", help="Hash and inspect a daily content folder")
    qa.add_argument("--folder", required=True, type=Path)

    validate = sub.add_parser("validate-manifest", help="Validate fields, local sources, licenses, and hashes")
    validate.add_argument("--manifest", required=True, type=Path)
    validate.add_argument("--skip-files", action="store_true")

    worker = sub.add_parser("serve", help="Start the token-protected local HTTP worker")
    worker.add_argument("--host", default="127.0.0.1")
    worker.add_argument("--port", type=int, default=8765)

    render = sub.add_parser("render", help="Render silent/original-audio masters and cover from a manifest")
    render.add_argument("--manifest", required=True, type=Path)
    render.add_argument("--force", action="store_true")

    finalize = sub.add_parser("finalize-qa", help="Promote a rendered draft to manifest.json after automated media QA")
    finalize.add_argument("--manifest", required=True, type=Path)

    job_check = sub.add_parser("validate-job", help="Validate a compact day job without downloading or rendering")
    job_check.add_argument("--job", required=True, type=Path)

    run = sub.add_parser("run-job", help="Run the complete local, cached content-production job")
    run.add_argument("--job", required=True, type=Path)

    gallery_check = sub.add_parser("validate-photo-gallery", help="Validate a photo-gallery job without downloading")
    gallery_check.add_argument("--job", required=True, type=Path)

    gallery_run = sub.add_parser("run-photo-gallery", help="Download, retouch, document, and QA a Pexels photo gallery")
    gallery_run.add_argument("--job", required=True, type=Path)

    duration = sub.add_parser("duration-target", help="Show the editorial target duration for a calendar day")
    duration.add_argument("--day", required=True, type=int)

    metadata = sub.add_parser("unify-metadata", help="Back up and combine video/photo notes into metadata.txt")
    metadata.add_argument("--folder", required=True, type=Path)

    buffer_validate = sub.add_parser("buffer-validate-plan", help="Validate a Buffer schedule plan without network access")
    buffer_validate.add_argument("--plan", required=True, type=Path)

    buffer_channels = sub.add_parser("buffer-channels", help="List Buffer channels for an organization")
    buffer_channels.add_argument("--organization-id", required=True)

    sub.add_parser("buffer-organizations", help="List Buffer organizations for the configured API key")

    buffer_submit = sub.add_parser("buffer-submit", help="Submit a validated Buffer plan; requires explicit approval")
    buffer_submit.add_argument("--plan", required=True, type=Path)
    buffer_submit.add_argument("--approve", action="store_true")

    schedule_validate = sub.add_parser("schedule-validate-plan", help="Validate a cross-platform schedule plan offline")
    schedule_validate.add_argument("--plan", required=True, type=Path)
    schedule_validate.add_argument("--skip-files", action="store_true")

    schedule_store = sub.add_parser("schedule-store-plan", help="Store a validated plan in the approval ledger")
    schedule_store.add_argument("--plan", required=True, type=Path)
    schedule_store.add_argument("--skip-files", action="store_true")

    schedule_approve = sub.add_parser("schedule-approve", help="Approve an exact stored plan digest without publishing")
    schedule_approve.add_argument("--plan-id", required=True, type=int)
    schedule_approve.add_argument("--digest", required=True)

    schedule_dispatch = sub.add_parser("schedule-dispatch", help="Preview or dispatch approved due posts")
    schedule_dispatch.add_argument("--limit", type=int, default=10)
    schedule_dispatch.add_argument("--live", action="store_true")

    schedule_submit_now = sub.add_parser("schedule-submit-now", help="Immediately submit approved posts to providers with native future scheduling")
    schedule_submit_now.add_argument("--plan-id", required=True, type=int)
    schedule_submit_now.add_argument("--platform", action="append", dest="platforms")
    schedule_submit_now.add_argument("--live", action="store_true")

    schedule_record = sub.add_parser("schedule-record-external", help="Record a post scheduled through a platform UI")
    schedule_record.add_argument("--post-id", required=True, type=int)
    schedule_record.add_argument("--external-id", required=True)

    schedule_show = sub.add_parser("schedule-status", help="Show plan and per-platform delivery status")
    schedule_show.add_argument("--plan-id", required=True, type=int)

    tiktok_status = sub.add_parser("tiktok-status", help="Fetch a TikTok Content Posting publish status")
    tiktok_status.add_argument("--publish-id", required=True)

    youtube_auth = sub.add_parser("youtube-authorize", help="Run one-time local YouTube OAuth authorization")
    youtube_auth.add_argument("--open-browser", action="store_true")
    youtube_auth.add_argument("--url-file", type=Path, help="Write the consent URL for a separately controlled browser")

    r2_stage = sub.add_parser("r2-stage", help="Upload one local asset and return a temporary signed R2 URL")
    r2_stage.add_argument("--file", required=True, type=Path)
    r2_stage.add_argument("--publishing-day")
    r2_stage.add_argument("--expires-hours", type=int, default=48)

    sub.add_parser("media-init-key", help="Create the encrypted local media URL signing key")
    media_url = sub.add_parser("media-url", help="Create a temporary signed URL through the free local HTTPS tunnel")
    media_url.add_argument("--file", required=True, type=Path)
    media_url.add_argument("--base-url")
    media_url.add_argument("--expires-hours", type=int, default=2)

    pexels = sub.add_parser("pexels-search", help="Create a compact Pexels candidate index using PEXELS_API_KEY")
    pexels.add_argument("--query", required=True)
    pexels.add_argument("--output", required=True, type=Path)
    pexels.add_argument("--per-page", type=int, default=20)
    pexels.add_argument("--orientation", choices=("portrait", "landscape", "square"), default="portrait")
    pexels.add_argument("--size", choices=("large", "medium", "small"), default="medium")

    pexels_photo = sub.add_parser("pexels-photo-search", help="Create a Pexels photo candidate index using PEXELS_API_KEY")
    pexels_photo.add_argument("--query", required=True)
    pexels_photo.add_argument("--output", required=True, type=Path)
    pexels_photo.add_argument("--per-page", type=int, default=20)
    pexels_photo.add_argument("--orientation", choices=("portrait", "landscape", "square"), default="portrait")
    pexels_photo.add_argument("--size", choices=("large", "medium", "small"), default="large")

    args = parser.parse_args()
    if args.command == "init-db":
        path = initialize_database(args.path) if args.path else initialize_database()
        print(json.dumps({"status": "ok", "database": str(path)}))
    elif args.command == "audio":
        score = AudioScore.from_json(args.score)
        path = generate_original_audio(score, args.output, args.force)
        print(json.dumps({"status": "ok", "output": str(path), "bytes": path.stat().st_size}))
    elif args.command == "qa":
        print(json.dumps(inspect_folder(args.folder), indent=2, ensure_ascii=False))
    elif args.command == "validate-manifest":
        errors = validate_manifest(args.manifest, verify_files=not args.skip_files)
        print(json.dumps({"passed": not errors, "errors": errors}, indent=2, ensure_ascii=False))
        if errors:
            raise SystemExit(1)
    elif args.command == "serve":
        serve(args.host, args.port)
    elif args.command == "render":
        print(json.dumps(render_manifest(args.manifest, force=args.force), indent=2, ensure_ascii=False))
    elif args.command == "finalize-qa":
        print(json.dumps(finalize_automated_qa(args.manifest), indent=2, ensure_ascii=False))
    elif args.command == "validate-job":
        data = json.loads(args.job.read_text(encoding="utf-8"))
        errors = validate_job(data)
        print(json.dumps({"passed": not errors, "errors": errors}, indent=2, ensure_ascii=False))
        if errors:
            raise SystemExit(1)
    elif args.command == "run-job":
        print(json.dumps(run_job(args.job), indent=2, ensure_ascii=False))
    elif args.command == "validate-photo-gallery":
        data = json.loads(args.job.read_text(encoding="utf-8"))
        errors = validate_gallery_job(data)
        print(json.dumps({"passed": not errors, "errors": errors}, indent=2, ensure_ascii=False))
        if errors:
            raise SystemExit(1)
    elif args.command == "run-photo-gallery":
        print(json.dumps(run_gallery_job(args.job), indent=2, ensure_ascii=False))
    elif args.command == "duration-target":
        print(json.dumps({"day": args.day, "target_seconds": target_duration_seconds(args.day)}))
    elif args.command == "unify-metadata":
        print(json.dumps(unify_day_metadata(args.folder), indent=2, ensure_ascii=False))
    elif args.command == "buffer-validate-plan":
        plan = load_schedule_plan(args.plan)
        print(json.dumps({"passed": True, "posts": len(plan["posts"]), "network_used": False}, indent=2))
    elif args.command == "buffer-channels":
        print(json.dumps(get_channels(args.organization_id), indent=2, ensure_ascii=False))
    elif args.command == "buffer-organizations":
        print(json.dumps(get_organizations(), indent=2, ensure_ascii=False))
    elif args.command == "buffer-submit":
        print(json.dumps(submit_schedule_plan(args.plan, approve=args.approve), indent=2, ensure_ascii=False))
    elif args.command == "schedule-validate-plan":
        plan = load_plan(args.plan, verify_files=not args.skip_files)
        print(json.dumps({"passed": True, "posts": len(plan["posts"]), "network_used": False}, indent=2))
    elif args.command == "schedule-store-plan":
        print(json.dumps(store_plan(args.plan, verify_files=not args.skip_files), indent=2, ensure_ascii=False))
    elif args.command == "schedule-approve":
        print(json.dumps(approve_plan(args.plan_id, args.digest), indent=2, ensure_ascii=False))
    elif args.command == "schedule-dispatch":
        print(json.dumps(dispatch_due(limit=args.limit, live=args.live), indent=2, ensure_ascii=False))
    elif args.command == "schedule-submit-now":
        print(json.dumps(submit_approved_now(args.plan_id, args.platforms, live=args.live), indent=2, ensure_ascii=False))
    elif args.command == "schedule-record-external":
        print(json.dumps(record_external_schedule(args.post_id, args.external_id), indent=2, ensure_ascii=False))
    elif args.command == "schedule-status":
        print(json.dumps(plan_status(args.plan_id), indent=2, ensure_ascii=False))
    elif args.command == "tiktok-status":
        print(json.dumps(fetch_tiktok_status(args.publish_id), indent=2, ensure_ascii=False))
    elif args.command == "youtube-authorize":
        print(json.dumps(authorize_youtube(open_browser=args.open_browser, auth_url_file=args.url_file), indent=2, ensure_ascii=False))
    elif args.command == "r2-stage":
        print(json.dumps(stage_media(args.file, args.publishing_day, args.expires_hours), indent=2, ensure_ascii=False))
    elif args.command == "media-init-key":
        print(json.dumps({"status": "created" if ensure_signing_key() else "exists", "secret_printed": False}))
    elif args.command == "media-url":
        ensure_signing_key()
        print(json.dumps({"public_media_url": create_signed_media_url(args.file, args.base_url, args.expires_hours)}, ensure_ascii=False))
    elif args.command == "pexels-search":
        result = search_videos(args.query, args.per_page, args.orientation, args.size)
        output = write_search_result(result, args.output)
        print(json.dumps({"status": "ok", "output": str(output), "candidates": len(result["candidates"]), "quota": result["quota"]}, ensure_ascii=False))
    elif args.command == "pexels-photo-search":
        result = search_photos(args.query, args.per_page, args.orientation, args.size)
        output = write_search_result(result, args.output)
        print(json.dumps({"status": "ok", "output": str(output), "candidates": len(result["candidates"]), "quota": result["quota"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

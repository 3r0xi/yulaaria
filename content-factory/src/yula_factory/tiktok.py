from __future__ import annotations

import json
import math
import mimetypes
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .secrets import config_value, required_value, save_config_value


API_BASE = "https://open.tiktokapis.com"
MIN_CHUNK = 5 * 1024 * 1024
MAX_CHUNK = 64 * 1024 * 1024
ALLOWED_PRIVACY = {
    "PUBLIC_TO_EVERYONE",
    "MUTUAL_FOLLOW_FRIENDS",
    "FOLLOWER_OF_CREATOR",
    "SELF_ONLY",
}


def _error_message(exc: HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        error = payload.get("error") or {}
        code = error.get("code") or payload.get("error") or f"http_{exc.code}"
        message = error.get("message") or payload.get("error_description") or str(exc.reason)
        log_id = error.get("log_id") or payload.get("log_id")
        suffix = f" (log_id={log_id})" if log_id else ""
        return f"TikTok API {code}: {message}{suffix}"
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return f"TikTok API HTTP {exc.code}: {exc.reason}"


def _json_request(path: str, token: str, body: dict, timeout: int = 90) -> dict:
    request = Request(
        f"{API_BASE}{path}",
        data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(_error_message(exc)) from exc
    error = payload.get("error") or {}
    if error.get("code") not in (None, "", "ok"):
        raise RuntimeError(
            f"TikTok API {error.get('code')}: {error.get('message', 'request failed')}"
            + (f" (log_id={error['log_id']})" if error.get("log_id") else "")
        )
    return payload.get("data") or {}


def refresh_user_token() -> str:
    body = urlencode({
        "client_key": required_value("TIKTOK_CLIENT_KEY"),
        "client_secret": required_value("TIKTOK_CLIENT_SECRET"),
        "grant_type": "refresh_token",
        "refresh_token": required_value("TIKTOK_REFRESH_TOKEN"),
    }).encode("utf-8")
    request = Request(
        f"{API_BASE}/v2/oauth/token/",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(_error_message(exc)) from exc
    if payload.get("error"):
        raise RuntimeError(f"TikTok OAuth {payload['error']}: {payload.get('error_description', 'refresh failed')}")
    access_token = str(payload.get("access_token", ""))
    refresh_token = str(payload.get("refresh_token", ""))
    if not access_token or not refresh_token:
        raise RuntimeError("TikTok OAuth response did not contain refreshable user tokens")
    save_config_value("TIKTOK_ACCESS_TOKEN", access_token, secret=True)
    save_config_value("TIKTOK_REFRESH_TOKEN", refresh_token, secret=True)
    save_config_value("TIKTOK_ACCESS_TOKEN_EXPIRES_AT", str(int(time.time()) + int(payload.get("expires_in", 86400))), secret=True)
    if payload.get("open_id"):
        save_config_value("TIKTOK_OPEN_ID", str(payload["open_id"]), secret=True)
    return access_token


def _access_token() -> str:
    token = config_value("TIKTOK_ACCESS_TOKEN")
    expires = config_value("TIKTOK_ACCESS_TOKEN_EXPIRES_AT")
    if token and (not expires or int(expires) > int(time.time()) + 300):
        return token
    if config_value("TIKTOK_REFRESH_TOKEN"):
        return refresh_user_token()
    return required_value("TIKTOK_ACCESS_TOKEN")


def query_creator_info() -> dict:
    return _json_request("/v2/post/publish/creator_info/query/", _access_token(), {})


def fetch_status(publish_id: str) -> dict:
    if not str(publish_id).strip():
        raise ValueError("publish_id is required")
    return _json_request("/v2/post/publish/status/fetch/", _access_token(), {"publish_id": str(publish_id)})


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _privacy(post: dict, creator: dict) -> str:
    requested = str(post.get("privacy_level", "SELF_ONLY")).upper()
    if requested not in ALLOWED_PRIVACY:
        raise ValueError(f"Unsupported TikTok privacy level {requested}")
    if os.environ.get("TIKTOK_APP_AUDITED") != "1" and requested != "SELF_ONLY":
        raise PermissionError("Unaudited TikTok clients may publish only with SELF_ONLY privacy")
    options = {str(item) for item in creator.get("privacy_level_options", [])}
    if requested not in options:
        raise PermissionError(f"TikTok creator does not currently allow privacy level {requested}")
    return requested


def chunk_plan(video_size: int) -> tuple[int, int]:
    if video_size <= 0:
        raise ValueError("TikTok video file is empty")
    if video_size <= MAX_CHUNK:
        return video_size, 1
    count = math.ceil(video_size / MAX_CHUNK)
    chunk_size = video_size // count
    if chunk_size < MIN_CHUNK or count > 1000:
        raise ValueError("TikTok video cannot be represented by supported upload chunks")
    return chunk_size, video_size // chunk_size


def _upload_video(upload_url: str, media_path: Path, chunk_size: int, total_chunks: int) -> None:
    size = media_path.stat().st_size
    mime = mimetypes.guess_type(media_path.name)[0] or "video/mp4"
    if mime not in {"video/mp4", "video/quicktime", "video/webm"}:
        raise ValueError(f"Unsupported TikTok video MIME type {mime}")
    with media_path.open("rb") as stream:
        start = 0
        for index in range(total_chunks):
            length = size - start if index == total_chunks - 1 else chunk_size
            data = stream.read(length)
            if len(data) != length:
                raise OSError("TikTok upload source ended before the declared file size")
            end = start + length - 1
            request = Request(
                upload_url,
                data=data,
                headers={
                    "Content-Type": mime,
                    "Content-Length": str(length),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                },
                method="PUT",
            )
            try:
                with urlopen(request, timeout=300) as response:
                    expected = 201 if index == total_chunks - 1 else 206
                    if response.status != expected:
                        raise RuntimeError(f"TikTok upload returned HTTP {response.status}, expected {expected}")
            except HTTPError as exc:
                raise RuntimeError(_error_message(exc)) from exc
            start = end + 1


def _video_post(post: dict, creator: dict, token: str) -> dict:
    media_path = Path(str(post["media_path"])).resolve()
    size = media_path.stat().st_size
    chunk_size, total_chunks = chunk_plan(size)
    title = str(post.get("text") or post.get("title") or "")
    if _utf16_length(title) > 2200:
        raise ValueError("TikTok video caption exceeds 2200 UTF-16 code units")
    maximum = int(creator.get("max_video_post_duration_sec") or 0)
    duration = float(post.get("duration_seconds") or 0)
    if maximum and duration and duration > maximum:
        raise ValueError(f"TikTok video duration {duration:g}s exceeds creator limit {maximum}s")
    body = {
        "post_info": {
            "title": title,
            "privacy_level": _privacy(post, creator),
            "disable_duet": bool(post.get("disable_duet", False) or creator.get("duet_disabled", False)),
            "disable_comment": bool(post.get("disable_comment", False) or creator.get("comment_disabled", False)),
            "disable_stitch": bool(post.get("disable_stitch", False) or creator.get("stitch_disabled", False)),
            "video_cover_timestamp_ms": int(post.get("video_cover_timestamp_ms", 1000)),
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunks,
        },
    }
    data = _json_request("/v2/post/publish/video/init/", token, body)
    publish_id = str(data.get("publish_id", ""))
    upload_url = str(data.get("upload_url", ""))
    if not publish_id or not upload_url:
        raise RuntimeError("TikTok video initialization returned no publish ID or upload URL")
    _upload_video(upload_url, media_path, chunk_size, total_chunks)
    return {"id": publish_id, "external_id": publish_id, "provider_status": "PROCESSING_UPLOAD"}


def _photo_post(post: dict, creator: dict, token: str) -> dict:
    urls = post.get("public_media_urls") or ([post["public_media_url"]] if post.get("public_media_url") else [])
    if not isinstance(urls, list) or not urls or any(not str(url).startswith("https://") for url in urls):
        raise ValueError("TikTok photo posts require public_media_urls with verified HTTPS URLs")
    title = str(post.get("title", ""))
    description = str(post.get("text") or post.get("description") or "")
    if _utf16_length(title) > 90 or _utf16_length(description) > 4000:
        raise ValueError("TikTok photo title or description exceeds the API limit")
    body = {
        "media_type": "PHOTO",
        "post_mode": "DIRECT_POST",
        "post_info": {
            "title": title,
            "description": description,
            "privacy_level": _privacy(post, creator),
            "disable_comment": bool(post.get("disable_comment", False) or creator.get("comment_disabled", False)),
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_cover_index": int(post.get("photo_cover_index", 0)),
            "photo_images": [str(url) for url in urls],
        },
    }
    data = _json_request("/v2/post/publish/content/init/", token, body)
    publish_id = str(data.get("publish_id", ""))
    if not publish_id:
        raise RuntimeError("TikTok photo initialization returned no publish ID")
    return {"id": publish_id, "external_id": publish_id, "provider_status": "PROCESSING_DOWNLOAD"}


def publish(post: dict) -> dict:
    token = _access_token()
    creator = _json_request("/v2/post/publish/creator_info/query/", token, {})
    media_type = str(post.get("media_type", "video")).lower()
    if media_type in {"image", "photo", "carousel"}:
        return _photo_post(post, creator, token)
    if media_type == "video":
        return _video_post(post, creator, token)
    raise ValueError(f"TikTok does not support media_type {media_type!r}")

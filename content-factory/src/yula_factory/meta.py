from __future__ import annotations

import json
import mimetypes
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .secrets import required_value


HOSTS = {
    "facebook": "https://graph.facebook.com",
    "instagram": "https://graph.instagram.com",
    "threads": "https://graph.threads.net",
}
TOKEN_NAMES = {
    "facebook": "META_FACEBOOK_PAGE_ACCESS_TOKEN",
    "instagram": "META_INSTAGRAM_ACCESS_TOKEN",
    "threads": "META_THREADS_ACCESS_TOKEN",
}
VERSION_NAMES = {
    "facebook": "META_FACEBOOK_API_VERSION",
    "instagram": "META_INSTAGRAM_API_VERSION",
    "threads": "META_THREADS_API_VERSION",
}


def _open_json(request: Request, timeout: int) -> dict:
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            details = json.loads(exc.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            details = {"message": str(exc.reason)}
        raise RuntimeError(f"Meta API HTTP {exc.code}: {json.dumps(details, ensure_ascii=False)}") from exc


def _base_url(platform: str) -> str:
    version = required_value(VERSION_NAMES[platform])
    if not version.startswith("v"):
        raise RuntimeError(f"{VERSION_NAMES[platform]} must look like vXX.X")
    return f"{HOSTS[platform]}/{version}"


def _post_form(platform: str, path: str, fields: dict[str, object]) -> dict:
    body = {key: str(value) for key, value in fields.items() if value is not None}
    body["access_token"] = required_value(TOKEN_NAMES[platform])
    request = Request(
        f"{_base_url(platform)}/{path.lstrip('/')}",
        data=urlencode(body).encode("utf-8"),
        method="POST",
    )
    return _open_json(request, 90)


def _get(platform: str, path: str, fields: dict[str, object]) -> dict:
    query = {key: str(value) for key, value in fields.items() if value is not None}
    query["access_token"] = required_value(TOKEN_NAMES[platform])
    request = Request(f"{_base_url(platform)}/{path.lstrip('/')}?{urlencode(query)}")
    return _open_json(request, 45)


def _post_file(platform: str, path: str, media_path: Path, fields: dict[str, object]) -> dict:
    boundary = f"----YulaAria{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    data = {key: str(value) for key, value in fields.items() if value is not None}
    data["access_token"] = required_value(TOKEN_NAMES[platform])
    for key, value in data.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ])
    mime = mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="source"; filename="{media_path.name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        media_path.read_bytes(),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    request = Request(
        f"{_base_url(platform)}/{path.lstrip('/')}",
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    return _open_json(request, 900)


def _wait_for_container(platform: str, container_id: str, attempts: int = 30) -> None:
    for _ in range(attempts):
        field = "status" if platform == "threads" else "status_code"
        status = _get(platform, container_id, {"fields": field}).get(field)
        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Meta media container ended with status {status}")
        time.sleep(2)
    raise TimeoutError("Meta media container did not become ready in time")


def publish(post: dict) -> dict:
    platform = post["platform"]
    if platform == "facebook":
        return _publish_facebook(post)
    if platform == "instagram":
        return _publish_instagram(post)
    if platform == "threads":
        return _publish_threads(post)
    raise ValueError(f"Meta provider does not support {platform}")


def _publish_facebook(post: dict) -> dict:
    page_id = required_value("META_PAGE_ID")
    media = post.get("media_path")
    text = post.get("text", "")
    if not media:
        result = _post_form("facebook", f"{page_id}/feed", {"message": text})
    else:
        path = Path(media)
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            result = _post_file("facebook", f"{page_id}/photos", path, {"caption": text, "published": "true"})
        else:
            result = _post_file("facebook", f"{page_id}/videos", path, {"description": text, "published": "true"})
    return {"external_id": result.get("post_id") or result.get("id"), "raw": result}


def _publish_instagram(post: dict) -> dict:
    user_id = required_value("META_IG_USER_ID")
    public_url = post.get("public_media_url")
    if not public_url:
        raise RuntimeError("Instagram media publishing requires public_media_url")
    is_video = str(post.get("media_type", "video")).lower() == "video"
    fields: dict[str, object] = {"caption": post.get("text", "")}
    if is_video:
        fields.update({"media_type": "REELS", "video_url": public_url, "share_to_feed": "true"})
    else:
        fields["image_url"] = public_url
    container = _post_form("instagram", f"{user_id}/media", fields)
    container_id = str(container["id"])
    _wait_for_container("instagram", container_id)
    result = _post_form("instagram", f"{user_id}/media_publish", {"creation_id": container_id})
    return {"external_id": result.get("id"), "container_id": container_id, "raw": result}


def _publish_threads(post: dict) -> dict:
    user_id = required_value("META_THREADS_USER_ID")
    public_url = post.get("public_media_url")
    media_type = str(post.get("media_type", "text")).upper()
    fields: dict[str, object] = {"media_type": media_type, "text": post.get("text", "")}
    if media_type == "IMAGE":
        fields["image_url"] = public_url
    elif media_type == "VIDEO":
        fields["video_url"] = public_url
    container = _post_form("threads", f"{user_id}/threads", fields)
    container_id = str(container["id"])
    if media_type != "TEXT":
        _wait_for_container("threads", container_id)
    result = _post_form("threads", f"{user_id}/threads_publish", {"creation_id": container_id})
    return {"external_id": result.get("id"), "container_id": container_id, "raw": result}

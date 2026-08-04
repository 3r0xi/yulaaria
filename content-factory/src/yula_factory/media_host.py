from __future__ import annotations

import base64
import hashlib
import hmac
import mimetypes
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import paths
from .paths import inside_content_root
from .secrets import config_value, required_value, save_config_value


MEDIA_PREFIX = "/media/v1/"


def ensure_signing_key() -> bool:
    """Create the local URL-signing secret once; never print the secret."""
    if config_value("YULA_MEDIA_SIGNING_KEY"):
        return False
    save_config_value("YULA_MEDIA_SIGNING_KEY", secrets.token_urlsafe(48), secret=True)
    return True


def _encoded_relative_path(path: Path) -> str:
    media = inside_content_root(path)
    if not media.is_file():
        raise FileNotFoundError(media)
    relative = media.relative_to(paths.CONTENT_ROOT.resolve()).as_posix().encode("utf-8")
    return base64.urlsafe_b64encode(relative).decode("ascii").rstrip("=")


def _signature(encoded_path: str, expires_at: int) -> str:
    key = required_value("YULA_MEDIA_SIGNING_KEY").encode("utf-8")
    message = f"{encoded_path}.{expires_at}".encode("ascii")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def create_signed_media_url(
    path: Path,
    base_url: str | None = None,
    expires_hours: int = 2,
    now: int | None = None,
) -> str:
    if not 1 <= int(expires_hours) <= 24:
        raise ValueError("expires_hours must be between 1 and 24")
    configured_base = (base_url or config_value("YULA_PUBLIC_MEDIA_BASE_URL")).rstrip("/")
    parsed = urlparse(configured_base)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("YULA_PUBLIC_MEDIA_BASE_URL must be an HTTPS URL")
    encoded = _encoded_relative_path(path)
    expires_at = int(now if now is not None else time.time()) + int(expires_hours) * 3600
    signature = _signature(encoded, expires_at)
    return f"{configured_base}{MEDIA_PREFIX}{quote(encoded)}?expires={expires_at}&sig={signature}"


def resolve_signed_media_url(target: str, now: int | None = None) -> Path:
    parsed = urlparse(target)
    if not parsed.path.startswith(MEDIA_PREFIX):
        raise PermissionError("Unknown media route")
    encoded = parsed.path[len(MEDIA_PREFIX):]
    query = parse_qs(parsed.query, strict_parsing=True)
    try:
        expires_at = int(query["expires"][0])
        supplied = query["sig"][0]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise PermissionError("Invalid signed media URL") from exc
    if expires_at < int(now if now is not None else time.time()):
        raise PermissionError("Signed media URL expired")
    if not hmac.compare_digest(supplied, _signature(encoded, expires_at)):
        raise PermissionError("Invalid signed media URL")
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        relative = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise PermissionError("Invalid signed media URL") from exc
    media = inside_content_root(paths.CONTENT_ROOT / Path(relative))
    if not media.is_file():
        raise FileNotFoundError(media)
    return media


def serve_signed_media(handler, head_only: bool = False) -> None:
    media = resolve_signed_media_url(handler.path)
    total = media.stat().st_size
    start, end, status = 0, max(0, total - 1), 200
    range_header = handler.headers.get("Range", "")
    if range_header:
        if not range_header.startswith("bytes=") or "," in range_header:
            handler.send_error(416)
            return
        first, _, last = range_header[6:].partition("-")
        try:
            start = int(first) if first else 0
            end = int(last) if last else total - 1
        except ValueError:
            handler.send_error(416)
            return
        if start < 0 or end < start or end >= total:
            handler.send_error(416)
            return
        status = 206
    length = end - start + 1
    handler.send_response(status)
    handler.send_header("Content-Type", mimetypes.guess_type(media.name)[0] or "application/octet-stream")
    handler.send_header("Content-Length", str(length))
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Cache-Control", "private, no-store")
    if status == 206:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{total}")
    handler.end_headers()
    if head_only:
        return
    with media.open("rb") as stream:
        stream.seek(start)
        remaining = length
        while remaining:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            handler.wfile.write(chunk)
            remaining -= len(chunk)

from __future__ import annotations

import hashlib
import mimetypes
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .ledger import initialize_database
from .paths import DEFAULT_DB, inside_content_root
from .secrets import required_value


def _client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("Install the optional 'publishing' dependencies before R2 staging") from exc

    account_id = required_value("R2_ACCOUNT_ID")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=required_value("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=required_value("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 4, "mode": "standard"}),
    )


def object_key(path: Path, publishing_day: str | None = None) -> str:
    media_path = inside_content_root(path)
    digest = hashlib.sha256(media_path.read_bytes()).hexdigest()
    day = publishing_day or date.today().isoformat()
    safe_day = date.fromisoformat(day).isoformat()
    return f"yula-aria/{safe_day}/{digest}{media_path.suffix.lower()}"


def stage_media(
    path: Path,
    publishing_day: str | None = None,
    expires_hours: int = 48,
    client=None,
    db_path: Path = DEFAULT_DB,
) -> dict:
    media_path = inside_content_root(path)
    if not media_path.is_file():
        raise FileNotFoundError(media_path)
    if not 1 <= int(expires_hours) <= 168:
        raise ValueError("expires_hours must be between 1 and 168")

    bucket = required_value("R2_BUCKET_NAME")
    key = object_key(media_path, publishing_day)
    content_type = mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
    r2 = client or _client()
    r2.upload_file(
        str(media_path),
        bucket,
        key,
        ExtraArgs={"ContentType": content_type, "CacheControl": "private, max-age=3600"},
    )
    expires_seconds = int(expires_hours) * 3600
    signed_url = r2.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_seconds,
    )
    digest = hashlib.sha256(media_path.read_bytes()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
    initialize_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """INSERT INTO temporary_media_objects(object_key,local_path,sha256,expires_at)
            VALUES (?,?,?,?)
            ON CONFLICT(object_key) DO UPDATE SET local_path=excluded.local_path,sha256=excluded.sha256,
            expires_at=excluded.expires_at,deleted_at=NULL""",
            (key, str(media_path), digest, expires_at.isoformat()),
        )
        connection.commit()
    return {
        "status": "staged",
        "bucket": bucket,
        "object_key": key,
        "public_media_url": signed_url,
        "expires_in_seconds": expires_seconds,
        "expires_at": expires_at.isoformat(),
        "content_type": content_type,
    }

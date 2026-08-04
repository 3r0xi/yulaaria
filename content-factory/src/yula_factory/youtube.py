from __future__ import annotations

import json
from contextlib import nullcontext, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from .secrets import config_value, required_value, save_config_value


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def _required_path(name: str) -> Path:
    value = required_value(name)
    path = Path(value).expanduser().resolve()
    if not path.exists() and name == "YOUTUBE_CLIENT_SECRETS_FILE":
        raise FileNotFoundError(path)
    return path


def _credentials(open_browser: bool = False, auth_url_file: Path | None = None):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError("Install the optional 'publishing' dependencies before YouTube authorization") from exc

    credentials = None
    token_json = config_value("YOUTUBE_TOKEN_JSON")
    if token_json:
        token_info = json.loads(token_json)
        if set(SCOPES).issubset(set(token_info.get("scopes") or [])):
            credentials = Credentials.from_authorized_user_info(token_info, SCOPES)
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        save_config_value("YOUTUBE_TOKEN_JSON", credentials.to_json(), secret=True)
    if not credentials or not credentials.valid:
        client_file = config_value("YOUTUBE_CLIENT_SECRETS_FILE")
        if client_file:
            flow = InstalledAppFlow.from_client_secrets_file(str(_required_path("YOUTUBE_CLIENT_SECRETS_FILE")), SCOPES)
        else:
            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id": required_value("YOUTUBE_CLIENT_ID"),
                        "client_secret": required_value("YOUTUBE_CLIENT_SECRET"),
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }
                },
                SCOPES,
            )
        output_context = nullcontext()
        output_stream = None
        if auth_url_file:
            auth_url_file.parent.mkdir(parents=True, exist_ok=True)
            output_stream = auth_url_file.open("w", encoding="utf-8", buffering=1)
            output_context = redirect_stdout(output_stream)
        try:
            with output_context:
                credentials = flow.run_local_server(
                    host="127.0.0.1",
                    port=8766,
                    open_browser=open_browser,
                    access_type="offline",
                    prompt="consent",
                    authorization_prompt_message="YULA_YOUTUBE_AUTH_URL={url}",
                    success_message="YouTube authorization completed. You can close this tab.",
                )
        finally:
            if output_stream:
                output_stream.close()
        save_config_value("YOUTUBE_TOKEN_JSON", credentials.to_json(), secret=True)
    return credentials


def authorize(open_browser: bool = False, auth_url_file: Path | None = None) -> dict:
    credentials = _credentials(open_browser=open_browser, auth_url_file=auth_url_file)
    return {"status": "authorized", "scopes": list(credentials.scopes or SCOPES)}


def publish(post: dict) -> dict:
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError("Install the optional 'publishing' dependencies before YouTube upload") from exc

    media_path = Path(post["media_path"]).resolve()
    if not media_path.is_file():
        raise FileNotFoundError(media_path)
    snippet = {
        "title": post["title"],
        "description": post.get("description", ""),
        "tags": post.get("tags", []),
        "categoryId": str(post.get("category_id", "19")),
    }
    if post.get("default_language"):
        snippet["defaultLanguage"] = post["default_language"]

    due_at = datetime.fromisoformat(str(post["due_at"]).replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    status: dict[str, object] = {
        "privacyStatus": "private" if due_at.astimezone(timezone.utc) > now else post.get("privacy_status", "public"),
        "selfDeclaredMadeForKids": bool(post.get("made_for_kids", False)),
        "containsSyntheticMedia": bool(post.get("contains_synthetic_media", False)),
    }
    if due_at.astimezone(timezone.utc) > now:
        status["publishAt"] = due_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    youtube = build("youtube", "v3", credentials=_credentials(), cache_discovery=False)
    request = youtube.videos().insert(
        part="snippet,status",
        body={"snippet": snippet, "status": status},
        media_body=MediaFileUpload(str(media_path), chunksize=8 * 1024 * 1024, resumable=True),
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    return {"external_id": response.get("id"), "raw": {"id": response.get("id"), "status": response.get("status")}}

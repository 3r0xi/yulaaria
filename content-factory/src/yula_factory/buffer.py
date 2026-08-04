from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

from .secrets import required_value


API_URL = "https://api.buffer.com"
SUPPORTED_CREATE_SERVICES = {
    "instagram",
    "threads",
    "linkedin",
    "twitter",
    "facebook",
    "googlebusiness",
    "mastodon",
    "youtube",
    "pinterest",
    "bluesky",
}


def _api_key() -> str:
    return required_value("BUFFER_API_KEY")


def _graphql(query: str) -> dict:
    request = Request(
        API_URL,
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errors"):
        raise RuntimeError("Buffer API error: " + json.dumps(payload["errors"], ensure_ascii=False))
    return payload.get("data") or {}


def get_channels(organization_id: str) -> list[dict]:
    organization = json.dumps(str(organization_id))
    query = """query GetChannels {
      channels(input: { organizationId: %s }) {
        id name displayName service avatar isQueuePaused
      }
    }""" % organization
    return _graphql(query).get("channels") or []


def get_organizations() -> list[dict]:
    query = """query GetOrganizations {
      account {
        organizations { id name ownerEmail }
      }
    }"""
    return ((_graphql(query).get("account") or {}).get("organizations") or [])


def validate_schedule_plan(plan: dict) -> list[str]:
    errors: list[str] = []
    posts = plan.get("posts")
    if not isinstance(posts, list) or not posts:
        return ["plan.posts must be a non-empty list"]
    for index, post in enumerate(posts):
        prefix = f"posts[{index}]"
        if not str(post.get("channel_id", "")).strip():
            errors.append(f"{prefix}.channel_id is required")
        if not str(post.get("text", "")).strip():
            errors.append(f"{prefix}.text is required")
        service = str(post.get("service", "")).lower()
        if service not in SUPPORTED_CREATE_SERVICES:
            errors.append(f"{prefix}.service is not supported by the current Buffer createPost API")
        mode = post.get("mode", "customScheduled")
        if mode not in {"customScheduled", "addToQueue"}:
            errors.append(f"{prefix}.mode must be customScheduled or addToQueue")
        if mode == "customScheduled":
            try:
                value = str(post["due_at"]).replace("Z", "+00:00")
                if datetime.fromisoformat(value).tzinfo is None:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                errors.append(f"{prefix}.due_at must be a timezone-aware ISO 8601 value")
        assets = post.get("assets", [])
        if not isinstance(assets, list) or len(assets) > 10:
            errors.append(f"{prefix}.assets must be a list of at most 10 items")
            continue
        for asset_index, asset in enumerate(assets):
            if not isinstance(asset, dict) or set(asset) not in ({"image"}, {"video"}):
                errors.append(f"{prefix}.assets[{asset_index}] must contain exactly one image or video URL")
                continue
            url = str(next(iter(asset.values())))
            if not url.startswith("https://"):
                errors.append(f"{prefix}.assets[{asset_index}] must be a publicly accessible HTTPS URL")
    return errors


def load_schedule_plan(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_schedule_plan(plan)
    if errors:
        raise ValueError("Invalid Buffer schedule plan: " + "; ".join(errors))
    return plan


def _asset_literal(asset: dict) -> str:
    kind, url = next(iter(asset.items()))
    return "{%s:{url:%s}}" % (kind, json.dumps(str(url)))


def create_post(post: dict) -> dict:
    errors = validate_schedule_plan({"posts": [post]})
    if errors:
        raise ValueError("Invalid Buffer post: " + "; ".join(errors))
    fields = [
        f"text:{json.dumps(str(post['text']))}",
        f"channelId:{json.dumps(str(post['channel_id']))}",
        "schedulingType:automatic",
        f"mode:{post.get('mode', 'customScheduled')}",
    ]
    if post.get("mode", "customScheduled") == "customScheduled":
        fields.append(f"dueAt:{json.dumps(str(post['due_at']))}")
    if post.get("assets"):
        fields.append("assets:[%s]" % ",".join(_asset_literal(asset) for asset in post["assets"]))
    query = """mutation CreatePost {
      createPost(input: {%s}) {
        ... on PostActionSuccess { post { id text dueAt channelId assets { id mimeType } } }
        ... on MutationError { message }
      }
    }""" % ",".join(fields)
    result = _graphql(query).get("createPost") or {}
    if result.get("message"):
        raise RuntimeError(f"Buffer rejected post: {result['message']}")
    return result.get("post") or result


def submit_schedule_plan(path: Path, approve: bool = False) -> dict:
    plan = load_schedule_plan(path)
    if not approve:
        raise PermissionError("Submission blocked: explicit --approve is required")
    results = [create_post(post) for post in plan["posts"]]
    return {"status": "submitted", "count": len(results), "posts": results}

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .secrets import required_value


API_ROOT = "https://api.pexels.com/v1"


def _api_key() -> str:
    return required_value("PEXELS_API_KEY")


def _request_json(path: str, parameters: dict[str, object]) -> tuple[dict, dict]:
    url = f"{API_ROOT}/{path}?{urlencode(parameters)}"
    request = Request(
        url,
        headers={
            "Authorization": _api_key(),
            "Accept": "application/json",
            "User-Agent": "YulaAriaContentFactory/0.2",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
            quota = {
                "limit": response.headers.get("X-Ratelimit-Limit"),
                "remaining": response.headers.get("X-Ratelimit-Remaining"),
                "reset": response.headers.get("X-Ratelimit-Reset"),
            }
            return payload, quota
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError("Pexels rejected the configured API credential") from exc
        if exc.code == 429:
            raise RuntimeError("Pexels API rate limit reached; wait for the quota reset") from exc
        raise RuntimeError(f"Pexels API returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError("Pexels API could not be reached") from exc


def _best_video_file(files: list[dict], prefer_portrait: bool = True) -> dict | None:
    mp4 = [item for item in files if item.get("file_type") == "video/mp4" and item.get("width") and item.get("height")]
    if not mp4:
        return None

    def score(item: dict) -> tuple[int, int, int]:
        width = int(item["width"])
        height = int(item["height"])
        portrait = height > width
        enough = width >= 1080 and height >= 1920 if portrait else height >= 1080
        pixels = width * height
        target_pixels = 1080 * 1920
        return (
            2 if portrait == prefer_portrait else 0,
            1 if enough else 0,
            -abs(pixels - target_pixels) if enough else pixels,
        )

    return max(mp4, key=score)


def search_videos(query: str, per_page: int = 20, orientation: str = "portrait", size: str = "medium") -> dict:
    if not 1 <= per_page <= 80:
        raise ValueError("per_page must be between 1 and 80")
    payload, quota = _request_json(
        "videos/search",
        {"query": query, "per_page": per_page, "orientation": orientation, "size": size},
    )
    candidates = []
    for video in payload.get("videos", []):
        chosen = _best_video_file(video.get("video_files", []), prefer_portrait=orientation == "portrait")
        if not chosen:
            continue
        user = video.get("user") or {}
        candidates.append(
            {
                "id": video.get("id"),
                "duration_seconds": video.get("duration"),
                "page_url": video.get("url"),
                "preview_url": video.get("image"),
                "creator": user.get("name"),
                "creator_url": user.get("url"),
                "download_url": chosen.get("link"),
                "width": chosen.get("width"),
                "height": chosen.get("height"),
                "fps": chosen.get("fps"),
            }
        )
    return {
        "query": query,
        "orientation": orientation,
        "size": size,
        "searched_at_unix": int(time.time()),
        "quota": quota,
        "candidates": candidates,
        "note": "Review preview URLs before adding selected candidates to a day job.",
    }


def search_photos(query: str, per_page: int = 20, orientation: str = "portrait", size: str = "large") -> dict:
    """Return compact Pexels photo candidates without storing credentials."""
    if not 1 <= per_page <= 80:
        raise ValueError("per_page must be between 1 and 80")
    payload, quota = _request_json(
        "search",
        {"query": query, "per_page": per_page, "orientation": orientation, "size": size},
    )
    candidates = []
    for photo in payload.get("photos", []):
        source = photo.get("src") or {}
        download_url = source.get("large2x") or source.get("large") or source.get("original")
        if not download_url:
            continue
        candidates.append(
            {
                "id": photo.get("id"),
                "page_url": photo.get("url"),
                "preview_url": source.get("medium") or source.get("small"),
                "creator": photo.get("photographer"),
                "creator_url": photo.get("photographer_url"),
                "download_url": download_url,
                "width": photo.get("width"),
                "height": photo.get("height"),
                "alt": photo.get("alt") or "",
            }
        )
    return {
        "query": query,
        "orientation": orientation,
        "size": size,
        "searched_at_unix": int(time.time()),
        "quota": quota,
        "candidates": candidates,
        "note": "Selections are saved by the photo-gallery worker before downloading so retries use the same assets.",
    }


def write_search_result(result: dict, output: Path) -> Path:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite candidate file: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output

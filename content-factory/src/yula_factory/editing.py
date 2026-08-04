from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .ledger import initialize_database
from .paths import DEFAULT_DB, FACTORY_ROOT


DEFAULT_LIBRARY = FACTORY_ROOT / "config" / "editing_styles.json"


def load_style_library(path: Path = DEFAULT_LIBRARY) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not data.get("profiles") or not data.get("styles"):
        raise ValueError("Invalid editing-style library")
    ids = [str(item.get("id", "")) for item in data["styles"]]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        raise ValueError("Editing-style IDs must be unique and non-empty")
    for item in data["styles"]:
        if item.get("profile") not in data["profiles"]:
            raise ValueError(f"Unknown profile for editing style {item['id']}")
    return data


def resolve_style(style_id: str, library: dict | None = None) -> dict:
    data = library or load_style_library()
    for item in data["styles"]:
        if item["id"] == style_id:
            return {**data["profiles"][item["profile"]], **item}
    raise ValueError(f"Unknown editing style: {style_id}")


def select_style(
    theme: str,
    asset_types: list[str],
    recent_style_ids: list[str] | None = None,
    explicit_style: str | None = None,
    library: dict | None = None,
) -> dict:
    data = library or load_style_library()
    if explicit_style:
        selected = resolve_style(explicit_style, data)
        return {**selected, "selection_reason": "explicit project configuration"}
    words = {word.strip(".,:;!?()[]").lower() for word in str(theme).split() if word.strip()}
    assets = {str(value).lower() for value in asset_types}
    recent = set((recent_style_ids or [])[-int(data["selection"].get("minimum_repeat_gap_days", 3)):])
    ranked: list[tuple[int, str, dict, str]] = []
    for item in data["styles"]:
        keyword_hits = words.intersection(str(value).lower() for value in item.get("keywords", []))
        asset_fit = len(assets.intersection(str(value).lower() for value in item.get("asset_types", [])))
        repeat_penalty = 8 if item["id"] in recent else 0
        score = len(keyword_hits) * 4 + asset_fit * 2 - repeat_penalty
        tie = hashlib.sha256(f"{theme}|{item['id']}".encode("utf-8")).hexdigest()
        reason = f"theme matches={sorted(keyword_hits)}; asset fit={asset_fit}; recent penalty={repeat_penalty}"
        ranked.append((score, tie, item, reason))
    _, _, winner, reason = max(ranked, key=lambda value: (value[0], value[1]))
    return {**resolve_style(winner["id"], data), "selection_reason": reason}


def recent_styles(limit: int = 3, db_path: Path = DEFAULT_DB) -> list[str]:
    initialize_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT style_id FROM editing_style_history ORDER BY day DESC,id DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    return [str(row[0]) for row in rows]


def record_style(
    associated_content_id: str,
    day: int,
    platform: str,
    style: dict,
    manifest_path: Path | None = None,
    db_path: Path = DEFAULT_DB,
) -> None:
    initialize_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO editing_style_history
            (associated_content_id,day,platform,style_id,selection_reason,manifest_path)
            VALUES (?,?,?,?,?,?)""",
            (
                associated_content_id,
                int(day),
                str(platform),
                str(style["id"]),
                str(style.get("selection_reason", "configured")),
                str(manifest_path.resolve()) if manifest_path else None,
            ),
        )
        connection.commit()

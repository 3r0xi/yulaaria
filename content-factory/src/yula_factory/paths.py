from __future__ import annotations

import os
from pathlib import Path


FACTORY_ROOT = Path(__file__).resolve().parents[2]
CONTENT_ROOT = Path(os.environ.get("YULA_CONTENT_ROOT", FACTORY_ROOT.parent)).expanduser()
STATE_DIR = FACTORY_ROOT / "state"
DEFAULT_DB = STATE_DIR / "content_factory.sqlite3"


def inside_content_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    root = CONTENT_ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"Path must stay inside Content Sharing Plan: {resolved}")
    return resolved

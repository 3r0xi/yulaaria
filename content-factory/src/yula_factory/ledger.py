from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .paths import DEFAULT_DB


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS assets (
  sha256 TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  source_url TEXT NOT NULL,
  creator TEXT,
  license_name TEXT NOT NULL,
  license_url TEXT,
  license_checked_on TEXT NOT NULL,
  local_path TEXT NOT NULL,
  first_used_day INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS production_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day INTEGER NOT NULL,
  manifest_path TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL,
  template_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('started','passed','failed','approved')),
  n8n_execution_id TEXT,
  operator_notes TEXT,
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_run_manifest_pass
ON production_runs(manifest_sha256, status) WHERE status IN ('passed','approved');
CREATE TABLE IF NOT EXISTS post_performance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day INTEGER NOT NULL,
  platform TEXT NOT NULL,
  post_url TEXT,
  views INTEGER,
  average_watch_seconds REAL,
  completion_rate REAL,
  saves INTEGER,
  shares INTEGER,
  comments INTEGER,
  profile_actions INTEGER,
  measured_on TEXT NOT NULL,
  UNIQUE(day, platform, measured_on)
);
CREATE TABLE IF NOT EXISTS strategy_weights (
  key TEXT PRIMARY KEY,
  value REAL NOT NULL,
  evidence TEXT NOT NULL,
  approved INTEGER NOT NULL DEFAULT 0 CHECK(approved IN (0,1)),
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS learning_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  note TEXT NOT NULL,
  scope TEXT NOT NULL,
  author TEXT NOT NULL,
  approved INTEGER NOT NULL DEFAULT 0 CHECK(approved IN (0,1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS workflow_errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workflow_name TEXT NOT NULL,
  execution_id TEXT,
  failed_node TEXT,
  error_name TEXT,
  error_message TEXT NOT NULL,
  recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS schedule_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  digest TEXT NOT NULL UNIQUE,
  source_path TEXT NOT NULL,
  timezone TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('planned','approved','complete','cancelled')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  approved_at TEXT
);
CREATE TABLE IF NOT EXISTS scheduled_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_id INTEGER NOT NULL REFERENCES schedule_plans(id),
  idempotency_key TEXT NOT NULL UNIQUE,
  day INTEGER NOT NULL,
  slot TEXT NOT NULL,
  platform TEXT NOT NULL,
  provider TEXT NOT NULL,
  due_at TEXT NOT NULL,
  dispatch_lead_minutes INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('planned','approved','submitting','scheduled','published','manual_required','failed','cancelled')),
  external_id TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_scheduled_posts_due
ON scheduled_posts(status, due_at);
CREATE TABLE IF NOT EXISTS scheduler_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT,
  live INTEGER NOT NULL CHECK(live IN (0,1)),
  eligible_count INTEGER NOT NULL DEFAULT 0,
  processed_count INTEGER NOT NULL DEFAULT 0,
  missed_count INTEGER NOT NULL DEFAULT 0,
  result_json TEXT
);
CREATE TABLE IF NOT EXISTS music_generations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  associated_content_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  provider TEXT NOT NULL DEFAULT 'kie_suno',
  model TEXT NOT NULL,
  model_reason TEXT NOT NULL,
  request_json TEXT NOT NULL,
  task_id TEXT UNIQUE,
  status TEXT NOT NULL CHECK(status IN ('planned','submitted','pending','completed','failed')),
  response_json TEXT,
  selected_audio_id TEXT,
  selected_audio_path TEXT,
  duration_seconds REAL,
  creative_notes TEXT,
  licensing_notes TEXT,
  usage_history_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(associated_content_id, version)
);
CREATE INDEX IF NOT EXISTS ix_music_generations_content
ON music_generations(associated_content_id, version);
CREATE TABLE IF NOT EXISTS editing_style_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  associated_content_id TEXT NOT NULL,
  day INTEGER NOT NULL,
  platform TEXT NOT NULL,
  style_id TEXT NOT NULL,
  selection_reason TEXT NOT NULL,
  manifest_path TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(associated_content_id, platform)
);
CREATE TABLE IF NOT EXISTS temporary_media_objects (
  object_key TEXT PRIMARY KEY,
  provider TEXT NOT NULL DEFAULT 'cloudflare_r2',
  local_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  purpose TEXT NOT NULL DEFAULT 'final_media_delivery',
  expires_at TEXT,
  deleted_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def initialize_connection(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.commit()


def initialize_database(path: Path = DEFAULT_DB) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        initialize_connection(connection)
    return path


def record_workflow_error(payload: dict, path: Path = DEFAULT_DB) -> int:
    initialize_database(path)
    with closing(sqlite3.connect(path)) as connection:
        cursor = connection.execute(
            """INSERT INTO workflow_errors
            (workflow_name, execution_id, failed_node, error_name, error_message)
            VALUES (?, ?, ?, ?, ?)""",
            (
                str(payload.get("workflow_name") or "unknown")[:300],
                str(payload.get("execution_id") or "")[:100] or None,
                str(payload.get("failed_node") or "")[:300] or None,
                str(payload.get("error_name") or "")[:200] or None,
                str(payload.get("error_message") or "unknown error")[:4000],
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)

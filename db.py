"""
ZooSentry — SQLite layer.

Matches the schema in the system design doc (section 8):
  - videos
  - observations
  - shift_briefs

Keep this dumb on purpose. SQLite is sufficient for the hackathon MVP;
no Postgres, no vector DB, no graph DB.
"""

import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent / "observations.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    vss_sensor_id TEXT,
    upload_status TEXT,
    clip_summary TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    start_s REAL,
    end_s REAL,
    behavior TEXT NOT NULL,
    animals_visible TEXT,
    description TEXT,
    model_confidence TEXT,
    priority INTEGER DEFAULT 0,
    raw_response TEXT,
    source TEXT DEFAULT 'vss',
    track_id TEXT,
    vlm_description TEXT,
    corroborated INTEGER DEFAULT 0,
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

CREATE TABLE IF NOT EXISTS shift_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT,
    brief_json TEXT
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(reset: bool = False):
    """Create tables. If reset=True, wipe the DB file first (handy for demo re-runs)."""
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def upsert_video(video_id: str, filename: str, vss_sensor_id: str | None,
                  upload_status: str, clip_summary: str | None = None):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO videos (video_id, filename, vss_sensor_id, upload_status, clip_summary)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                filename=excluded.filename,
                vss_sensor_id=excluded.vss_sensor_id,
                upload_status=excluded.upload_status,
                clip_summary=COALESCE(excluded.clip_summary, videos.clip_summary)
            """,
            (video_id, filename, vss_sensor_id, upload_status, clip_summary),
        )


def insert_observation(video_id: str, start_s: float, end_s: float, behavior: str,
                        animals_visible: str, description: str, model_confidence: str,
                        priority: int, raw_response: dict, source: str = "vss",
                        track_id: str | None = None, vlm_description: str | None = None,
                        corroborated: bool = False):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO observations
                (video_id, start_s, end_s, behavior, animals_visible,
                 description, model_confidence, priority, raw_response,
                 source, track_id, vlm_description, corroborated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (video_id, start_s, end_s, behavior, animals_visible,
             description, model_confidence, priority, json.dumps(raw_response),
             source, track_id, vlm_description, int(corroborated)),
        )


def all_observations():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM observations ORDER BY priority DESC, start_s ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def all_videos():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM videos").fetchall()
        return [dict(r) for r in rows]


def save_shift_brief(generated_at: str, brief: dict):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO shift_briefs (generated_at, brief_json) VALUES (?, ?)",
            (generated_at, json.dumps(brief)),
        )


def latest_shift_brief():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM shift_briefs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
-- events table — §4.2 of the design doc. This is the handoff point to
-- whatever frontend/API layer gets designed later; schema is frozen here.
CREATE TABLE IF NOT EXISTS events (
  event_id           TEXT PRIMARY KEY,
  camera_id          TEXT NOT NULL,
  start_time         TIMESTAMPTZ NOT NULL,
  end_time           TIMESTAMPTZ NOT NULL,
  track_ids          INT[],
  trigger_type       TEXT,
  trigger_confidence REAL,
  vlm_summary        TEXT,
  priority           TEXT,
  category            TEXT,
  nemotron_reason    TEXT,
  worker_summary     TEXT,
  clip_reference     TEXT,
  status             TEXT DEFAULT 'new',   -- new | acknowledged | dismissed
  created_at         TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS events_priority_status_created_idx ON events (priority, status, created_at DESC);

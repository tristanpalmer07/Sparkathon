"""Event Writer service entrypoint.

Consumes nemotron-verdicts, persists every one to Postgres (per §3:
"only report=true events are surfaced by default, others kept for
audit/tuning" — so this writes every row unconditionally and lets
`report`/`status` filtering happen downstream).
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared import topics  # noqa: E402
from shared.kafka_utils import consume, get_consumer  # noqa: E402
from shared.schemas import NemotronVerdict  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("event-writer")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/events")

INSERT_SQL = """
INSERT INTO events (
    event_id, camera_id, start_time, end_time, track_ids,
    trigger_type, trigger_confidence, vlm_summary,
    priority, category, nemotron_reason, worker_summary, clip_reference
) VALUES (
    %(event_id)s, %(camera_id)s, %(start_time)s, %(end_time)s, %(track_ids)s,
    %(trigger_type)s, %(trigger_confidence)s, %(vlm_summary)s,
    %(priority)s, %(category)s, %(nemotron_reason)s, %(worker_summary)s, %(clip_reference)s
)
ON CONFLICT (event_id) DO NOTHING;
"""


def _connect_with_retry(retries: int = 30, delay_s: float = 2.0):
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(DATABASE_URL)
            conn.autocommit = True
            return conn
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("postgres connect attempt %d/%d failed: %s", attempt, retries, e)
            time.sleep(delay_s)
    raise RuntimeError("could not connect to Postgres") from last_err


def _row_from_verdict(v: NemotronVerdict) -> dict:
    return {
        "event_id": v.event_id,
        "camera_id": v.camera_id,
        "start_time": datetime.fromtimestamp(v.start_time, tz=timezone.utc),
        "end_time": datetime.fromtimestamp(v.end_time, tz=timezone.utc),
        "track_ids": v.track_ids,
        "trigger_type": v.trigger_type,
        "trigger_confidence": v.trigger_confidence,
        "vlm_summary": v.vlm_summary,
        "priority": v.priority,
        "category": v.category,
        "nemotron_reason": v.reason,
        "worker_summary": v.worker_summary,
        "clip_reference": v.clip_uri,
    }


def main() -> None:
    consumer = get_consumer(topics.NEMOTRON_VERDICTS, group_id="event-writer")
    conn = _connect_with_retry()

    logger.info("event-writer up, consuming %s -> Postgres", topics.NEMOTRON_VERDICTS)
    with conn.cursor() as cur:
        for verdict in consume(consumer, NemotronVerdict):
            row = _row_from_verdict(verdict)
            cur.execute(INSERT_SQL, row)
            logger.info("wrote event_id=%s priority=%s report=%s", verdict.event_id, verdict.priority, verdict.report)


if __name__ == "__main__":
    main()

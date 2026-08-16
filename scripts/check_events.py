"""Polls Postgres for a row landing in `events` — the end-to-end proof
that a synthetic trigger made it all the way through the pipeline."""
from __future__ import annotations

import os
import sys
import time

import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/events")
TIMEOUT_S = float(os.environ.get("TIMEOUT_S", "90"))


def main() -> None:
    conn = psycopg2.connect(DATABASE_URL)
    deadline = time.time() + TIMEOUT_S
    while time.time() < deadline:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_id, camera_id, trigger_type, trigger_confidence, priority, category, "
                "status, clip_reference FROM events ORDER BY created_at DESC LIMIT 5"
            )
            rows = cur.fetchall()
        if rows:
            print(f"found {len(rows)} row(s) in events:")
            for row in rows:
                print(" ", row)
            return
        time.sleep(2)
    print("TIMEOUT: no rows appeared in events within", TIMEOUT_S, "seconds")
    sys.exit(1)


if __name__ == "__main__":
    main()

"""Events API service.

Read/ack layer over the `events` table (§4.2) — the design doc scoped
this out ("frontend/API layer... designed separately"), but it's a
thin, well-contained addition: no new Kafka topics, no new write path
into `events` (Event Writer still owns that), just HTTP reads plus a
status transition (new -> acknowledged/dismissed) for whatever
frontend eventually consumes this.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("events-api")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/events")

app = FastAPI(title="Primate Event Intelligence — Events API")
_pool: ThreadedConnectionPool | None = None


@contextmanager
def get_conn():
    conn = _pool.getconn()
    try:
        yield conn
    finally:
        _pool.putconn(conn)


@app.on_event("startup")
def startup() -> None:
    global _pool
    _pool = ThreadedConnectionPool(1, 10, dsn=DATABASE_URL)
    logger.info("events-api up, DATABASE_URL host=%s", DATABASE_URL.split("@")[-1])


@app.on_event("shutdown")
def shutdown() -> None:
    if _pool:
        _pool.closeall()


class EventOut(BaseModel):
    event_id: str
    camera_id: str
    start_time: datetime
    end_time: datetime
    track_ids: list[int] | None
    trigger_type: str | None
    trigger_confidence: float | None
    vlm_summary: str | None
    priority: str | None
    category: str | None
    nemotron_reason: str | None
    worker_summary: str | None
    clip_reference: str | None
    status: str
    created_at: datetime


class StatusUpdate(BaseModel):
    status: Literal["new", "acknowledged", "dismissed"]


@app.get("/health")
def health():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/events", response_model=list[EventOut])
def list_events(
    priority: Optional[str] = Query(None, description="high | medium | low"),
    status: Optional[str] = Query(None, description="new | acknowledged | dismissed"),
    category: Optional[str] = None,
    camera_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    clauses, params = [], []
    for col, val in (("priority", priority), ("status", status), ("category", category), ("camera_id", camera_id)):
        if val is not None:
            clauses.append(f"{col} = %s")
            params.append(val)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT event_id, camera_id, start_time, end_time, track_ids, trigger_type,
               trigger_confidence, vlm_summary, priority, category, nemotron_reason,
               worker_summary, clip_reference, status, created_at
        FROM events
        {where}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@app.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: str):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT event_id, camera_id, start_time, end_time, track_ids, trigger_type,
                   trigger_confidence, vlm_summary, priority, category, nemotron_reason,
                   worker_summary, clip_reference, status, created_at
            FROM events WHERE event_id = %s
            """,
            (event_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")
    return row


@app.patch("/events/{event_id}", response_model=EventOut)
def update_status(event_id: str, body: StatusUpdate):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            UPDATE events SET status = %s WHERE event_id = %s
            RETURNING event_id, camera_id, start_time, end_time, track_ids, trigger_type,
                      trigger_confidence, vlm_summary, priority, category, nemotron_reason,
                      worker_summary, clip_reference, status, created_at
            """,
            (body.status, event_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")
    return row


@app.get("/stats")
def stats():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT priority, status, count(*) AS count
            FROM events
            GROUP BY priority, status
            ORDER BY priority, status
            """
        )
        rows = cur.fetchall()
    return {"by_priority_status": rows}

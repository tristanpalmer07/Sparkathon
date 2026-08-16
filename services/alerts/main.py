"""Alerts service.

Consumes nemotron-verdicts and surfaces report=true verdicts as
alerts — the design doc's §6 stretch goal ("VSS Alerts | Could
subscribe to nemotron-verdicts and push notifications"). Doesn't own
any storage (Event Writer already persists every verdict to Postgres
regardless of report worthiness) — this is purely the notify side
effect, kept as its own consumer group so a slow/down webhook can
never block Event Writer.

ALERT_WEBHOOK_URL is optional; without it, alerts are still logged
(structured, one line per alert) so the behavior is visible even with
no notification channel configured.
"""
from __future__ import annotations

import logging
import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared import topics  # noqa: E402
from shared.kafka_utils import consume, get_consumer  # noqa: E402
from shared.schemas import NemotronVerdict  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("alerts")

ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL")
# Only page for verdicts worth someone's attention right now — every
# verdict already lands in Postgres regardless via Event Writer, so
# "low" stays queryable there without also becoming noise here.
ALERT_PRIORITIES = {"high", "medium"}


def send_alert(verdict: NemotronVerdict) -> None:
    logger.info(
        "ALERT priority=%s category=%s camera=%s event_id=%s :: %s",
        verdict.priority,
        verdict.category,
        verdict.camera_id,
        verdict.event_id,
        verdict.worker_summary,
    )
    if not ALERT_WEBHOOK_URL:
        return
    try:
        requests.post(
            ALERT_WEBHOOK_URL,
            json={
                "event_id": verdict.event_id,
                "camera_id": verdict.camera_id,
                "priority": verdict.priority,
                "category": verdict.category,
                "summary": verdict.worker_summary,
                "reason": verdict.reason,
                "clip_uri": verdict.clip_uri,
            },
            timeout=10,
        )
    except requests.RequestException:
        logger.exception("failed to POST alert webhook for event_id=%s", verdict.event_id)


def main() -> None:
    consumer = get_consumer(topics.NEMOTRON_VERDICTS, group_id="alerts")
    logger.info(
        "alerts up, consuming %s (webhook %s)",
        topics.NEMOTRON_VERDICTS,
        "configured" if ALERT_WEBHOOK_URL else "not configured — logging only",
    )
    for verdict in consume(consumer, NemotronVerdict):
        if verdict.report and verdict.priority in ALERT_PRIORITIES:
            send_alert(verdict)


if __name__ == "__main__":
    main()

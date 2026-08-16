"""AlphaChimp -> nv.Frame Adapter service (design doc §3 row 3).

Consumes our alphachimp-events (JSON, one message per frame per
track), groups consecutive same-timestamp events per camera into a
single nv.Frame protobuf message (one Frame can carry many Objects),
and publishes it onto VSS's real `mdx-raw` topic — the same topic
vss-behavior-analytics reads by default (confirmed against
deploy/docker/services/analytics/behavior-analytics/configs/
vss-behavior-analytics-config.json in the VSS repo).

Grouping relies on alphachimp-events being partitioned/keyed by
camera_id (so per-camera order is preserved) and on Video Ingest/
AlphaChimp publishing all objects for a given frame timestamp back to
back before moving to the next frame. Overlapping ingest windows can
cause the same timestamp to be re-emitted more than once; that's an
accepted duplicate-Frame cost for this adapter, not a correctness bug
for downstream consumers, which key incidents off sustained windows
rather than single frames.
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from converter import to_nv_frame  # noqa: E402
from shared import topics  # noqa: E402
from shared.kafka_utils import consume, get_consumer, get_raw_producer  # noqa: E402
from shared.schemas import AlphaChimpEvent  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("nvframe-adapter")

MDX_RAW_TOPIC = os.environ.get("MDX_RAW_TOPIC", "mdx-raw")


def main() -> None:
    consumer = get_consumer(topics.ALPHACHIMP_EVENTS, group_id="nvframe-adapter")
    producer = get_raw_producer()

    buffers: dict[str, dict] = {}  # camera_id -> {"t": float, "events": [AlphaChimpEvent]}

    logger.info("nvframe-adapter up, %s -> %s (nv.Frame protobuf)", topics.ALPHACHIMP_EVENTS, MDX_RAW_TOPIC)

    def flush_camera(camera_id: str) -> None:
        buf = buffers.get(camera_id)
        if not buf or not buf["events"]:
            return
        frame = to_nv_frame(camera_id, buf["t"], buf["events"])
        producer.send(MDX_RAW_TOPIC, value=frame.SerializeToString(), key=camera_id)
        producer.flush()
        logger.debug("flushed frame camera=%s t=%.3f objects=%d", camera_id, buf["t"], len(buf["events"]))
        buf["events"] = []

    for event in consume(consumer, AlphaChimpEvent):
        buf = buffers.setdefault(event.camera_id, {"t": event.t, "events": []})
        if buf["events"] and event.t != buf["t"]:
            flush_camera(event.camera_id)
            buf["t"] = event.t
        buf["events"].append(event)

    for camera_id in buffers:
        flush_camera(camera_id)


if __name__ == "__main__":
    main()

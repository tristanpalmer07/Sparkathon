"""Clip Retrieval service.

Consumes candidate-clips and resolves each one to a playable clip URL
via VSS's real VIOS service, instead of cutting the clip ourselves
with ffmpeg out of a hand-rolled MinIO segment store. VIOS already
knows how to find the right recording and mux a clip out of it — see
skills/vss-manage-video-io-storage/references/api-reference.md §4 in
the VSS repo for the exact endpoint this wraps.

camera_id doubles as the VIOS sensorId (Video Ingest always uploads
with sensorId=camera_id), but streamId does NOT reliably equal
sensorId — see vios_client.find_stream_id's docstring — so we resolve
it per-candidate from VIOS's own timelines rather than caching a
single sensorId -> streamId mapping.
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared import topics, vios_client  # noqa: E402
from shared.kafka_utils import consume, get_consumer, get_producer, publish  # noqa: E402
from shared.schemas import CandidateClip, ClipReady  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("clip-retrieval")


def handle_candidate(producer, candidate: CandidateClip) -> None:
    stream_id = vios_client.find_stream_id(candidate.camera_id, candidate.t_start, candidate.t_end)
    if stream_id is None:
        logger.warning(
            "no VIOS stream covers camera=%s window [%.2f, %.2f] — skipping clip_id=%s",
            candidate.camera_id,
            candidate.t_start,
            candidate.t_end,
            candidate.clip_id,
        )
        return

    result = vios_client.get_clip_url(stream_id, candidate.t_start, candidate.t_end)
    clip_uri = result["videoUrl"]
    duration_s = candidate.t_end - candidate.t_start

    publish(
        producer,
        topics.CLIP_READY,
        ClipReady(clip_id=candidate.clip_id, clip_uri=clip_uri, duration_s=duration_s),
        key=candidate.clip_id,
    )
    logger.info("resolved clip %s -> %s (%.1fs)", candidate.clip_id, clip_uri, duration_s)


def main() -> None:
    vios_client.wait_for_vios()

    consumer = get_consumer(topics.CANDIDATE_CLIPS, group_id="clip-retrieval")
    producer = get_producer()

    logger.info("clip-retrieval up, consuming %s", topics.CANDIDATE_CLIPS)
    for candidate in consume(consumer, CandidateClip):
        try:
            handle_candidate(producer, candidate)
        except Exception:  # noqa: BLE001 - one bad clip must not kill the consumer loop
            logger.exception("failed to resolve candidate clip %s", candidate.clip_id)


if __name__ == "__main__":
    main()

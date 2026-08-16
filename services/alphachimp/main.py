"""AlphaChimp Inference service.

FastAPI endpoint that Video Ingest POSTs frame windows to (this hop is
off Kafka, per the architecture diagram). Runs the pluggable backend
(backend.py) and publishes one alphachimp-events message per
frame per detected track, matching §4.1 exactly.
"""
from __future__ import annotations

import logging
import os
import sys

from fastapi import FastAPI
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend import decode_frame, get_backend  # noqa: E402
from shared import topics  # noqa: E402
from shared.kafka_utils import get_producer, publish  # noqa: E402
from shared.schemas import AlphaChimpEvent  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("alphachimp")

app = FastAPI(title="AlphaChimp Inference")
backend = get_backend()
producer = get_producer()


class Frame(BaseModel):
    t: float
    jpeg_b64: str


class InferRequest(BaseModel):
    camera_id: str
    frames: list[Frame]


@app.get("/health")
def health():
    return {"status": "ok", "backend": type(backend).__name__}


@app.post("/infer")
def infer(req: InferRequest):
    images = [decode_frame(f.jpeg_b64) for f in req.frames]
    per_frame_detections = backend.infer_window(req.camera_id, images)

    published = 0
    for frame_meta, detections in zip(req.frames, per_frame_detections):
        for det in detections:
            event = AlphaChimpEvent(
                camera_id=req.camera_id,
                track_id=det.track_id,
                t=frame_meta.t,
                bbox=det.bbox,
                det_conf=det.det_conf,
                behaviors=det.behaviors,
            )
            publish(producer, topics.ALPHACHIMP_EVENTS, event, key=req.camera_id)
            published += 1

    logger.info("camera=%s window=%d frames -> %d events", req.camera_id, len(req.frames), published)
    return {"published": published}

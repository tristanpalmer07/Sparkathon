"""Converts AlphaChimp's per-frame-per-track events into VSS's native
nv.Frame protobuf (schema.proto vendored from
video-search-and-summarization/libs/nvschema/protobuf/schema.proto).

This is the "AlphaChimp -> nv.Frame Adapter" from design doc §3 row 3:
it exists so VSS-native downstream tooling (vss-behavior-analytics,
CA-RAG, Alerts) can consume AlphaChimp's output without knowing
anything about AlphaChimp — same reasoning any other VSS perception
service (rt-cv, etc.) publishes onto mdx-raw.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import schema_pb2 as nv  # noqa: E402
from google.protobuf.timestamp_pb2 import Timestamp  # noqa: E402

from shared.schemas import AlphaChimpEvent  # noqa: E402

OBJECT_TYPE = "chimp"


def to_nv_frame(camera_id: str, t: float, events: list[AlphaChimpEvent]) -> nv.Frame:
    frame = nv.Frame()
    frame.version = "1.0"
    frame.id = f"{camera_id}:{t:.6f}"
    ts = Timestamp()
    ts.FromNanoseconds(int(t * 1e9))
    frame.timestamp.CopyFrom(ts)
    frame.sensorId = camera_id

    for event in events:
        obj = frame.objects.add()
        obj.id = str(event.track_id)
        obj.type = OBJECT_TYPE
        obj.confidence = event.det_conf

        x, y, w, h = event.bbox
        obj.bbox.leftX = x
        obj.bbox.topY = y
        obj.bbox.rightX = x + w
        obj.bbox.bottomY = y + h
        obj.bbox.confidence = event.det_conf

        for behavior, score in event.behaviors.items():
            obj.info[behavior] = f"{score:.4f}"
        if event.global_id:
            obj.info["global_id"] = event.global_id

    return frame

"""Kafka message contracts — frozen per design doc §4.1.

Every service imports these instead of hand-rolling dicts, so a schema
change is a change in exactly one place. Fields marked "extension" are
additive fields not in the original §4.1 examples, needed to carry
enough context through to Event Writer for the `events` table (§4.2) —
they don't break anything consuming only the documented fields.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class AlphaChimpEvent(BaseModel):
    """One message per frame per detected track. Topic: alphachimp-events."""

    camera_id: str
    track_id: int
    t: float
    bbox: tuple[float, float, float, float]
    det_conf: float
    behaviors: dict[str, float]
    global_id: Optional[str] = None


class CandidateClip(BaseModel):
    """One message per rule firing. Topic: candidate-clips."""

    clip_id: str
    camera_id: str
    t_start: float
    t_end: float
    track_ids: list[int]
    trigger_rule: str
    trigger_confidence: float


class ClipReady(BaseModel):
    """Topic: clip-ready."""

    clip_id: str
    clip_uri: str
    duration_s: float


class VlmDescription(BaseModel):
    """Topic: vlm-descriptions."""

    clip_id: str
    description: str
    model: str
    latency_ms: int


class NemotronVerdict(BaseModel):
    """Topic: nemotron-verdicts."""

    event_id: str
    report: bool
    priority: Literal["high", "medium", "low"]
    category: Literal["aggression", "health", "social", "routine"]
    reason: str
    worker_summary: str
    clip_uri: str

    # --- extensions: carried context needed for the `events` table (§4.2) ---
    camera_id: str
    start_time: float
    end_time: float
    track_ids: list[int] = Field(default_factory=list)
    trigger_type: Optional[str] = None
    trigger_confidence: Optional[float] = None
    vlm_summary: Optional[str] = None

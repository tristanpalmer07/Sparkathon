"""Which frames of an ingest window actually run through the detector.

The model was trained as an 8-frame temporal clip. We still write the
whole window to disk so SampleAVAFrames can look at neighbors, but we
only run detector.predict on the center timestamp — one forward per
HTTP request instead of one per frame.
"""
from __future__ import annotations

from typing import Sequence, TypeVar

T = TypeVar("T")


def center_index(n_frames: int) -> int:
    if n_frames < 1:
        raise ValueError(f"n_frames must be >= 1, got {n_frames}")
    return n_frames // 2


def keep_only_center(items: Sequence[T], n_frames: int) -> list[T]:
    return [items[center_index(n_frames)]]


def place_at_center(n_frames: int, detections: T) -> list[T | list]:
    placed: list[T | list] = [[] for _ in range(n_frames)]
    placed[center_index(n_frames)] = detections
    return placed

"""Stateful rule engine — the core of the Event Evaluator (§3.1).

Ingests alphachimp-events in per-camera time order (Kafka partitions on
camera_id, so this holds as long as a camera's messages aren't
reordered upstream) and emits candidate-clips the moment a rule
sustains for its required duration.

No LLM, no model weights — pure state machine, per the design doc's
explicit goal of keeping triage fast, cheap, and debuggable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations

from rules import RuleConfig

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shared.schemas import AlphaChimpEvent, CandidateClip  # noqa: E402


def _bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, w, h = bbox
    return x + w / 2.0, y + h / 2.0


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class _BehaviorRun:
    """Tracks a continuous run of a behavior staying above threshold."""

    start_t: float | None = None
    fired: bool = False
    max_conf: float = 0.0

    def observe(self, t: float, conf: float, threshold: float) -> None:
        if conf > threshold:
            if self.start_t is None:
                self.start_t = t
                self.fired = False
                self.max_conf = conf
            else:
                self.max_conf = max(self.max_conf, conf)
        else:
            self.start_t = None
            self.fired = False
            self.max_conf = 0.0

    def duration_at(self, t: float) -> float:
        return 0.0 if self.start_t is None else t - self.start_t


@dataclass
class _TrackState:
    last_t: float = 0.0
    last_pos: tuple[float, float] = (0.0, 0.0)
    last_det_conf: float = 0.0
    # behavior name -> run state, covers both sustained_aggression and
    # sustained_target_behavior since both are "behavior sustained above
    # threshold" with different thresholds/durations
    behavior_runs: dict[str, _BehaviorRun] = field(default_factory=dict)

    def run_for(self, behavior: str) -> _BehaviorRun:
        return self.behavior_runs.setdefault(behavior, _BehaviorRun())


@dataclass
class _CameraState:
    tracks: dict[int, _TrackState] = field(default_factory=dict)
    proximity_runs: dict[frozenset[int], _BehaviorRun] = field(default_factory=dict)

    def track(self, track_id: int) -> _TrackState:
        return self.tracks.setdefault(track_id, _TrackState())


class EventEvaluator:
    def __init__(self, config: RuleConfig | None = None):
        self.config = config or RuleConfig()
        self._cameras: dict[str, _CameraState] = {}

    def _camera(self, camera_id: str) -> _CameraState:
        return self._cameras.setdefault(camera_id, _CameraState())

    def process(self, event: AlphaChimpEvent) -> list[CandidateClip]:
        cfg = self.config
        cam = self._camera(event.camera_id)
        track = cam.track(event.track_id)

        candidates: list[CandidateClip] = []

        # sustained_aggression
        agg_conf = event.behaviors.get(cfg.aggression_behavior, 0.0)
        agg_run = track.run_for(cfg.aggression_behavior)
        agg_run.observe(event.t, agg_conf, cfg.aggression_conf_threshold)
        if (
            not agg_run.fired
            and agg_run.start_t is not None
            and agg_run.duration_at(event.t) >= cfg.aggression_min_duration_s
        ):
            agg_run.fired = True
            candidates.append(
                self._make_candidate(
                    camera_id=event.camera_id,
                    t_start=agg_run.start_t,
                    t_end=event.t,
                    track_ids=[event.track_id],
                    trigger_rule="sustained_aggression",
                    trigger_confidence=agg_run.max_conf,
                )
            )

        # sustained_target_behavior — any watchlisted behavior sustaining
        for behavior in cfg.watchlist_behaviors:
            conf = event.behaviors.get(behavior, 0.0)
            run = track.run_for(behavior)
            run.observe(event.t, conf, cfg.watchlist_conf_threshold)
            if (
                not run.fired
                and run.start_t is not None
                and run.duration_at(event.t) >= cfg.watchlist_min_duration_s
            ):
                run.fired = True
                candidates.append(
                    self._make_candidate(
                        camera_id=event.camera_id,
                        t_start=run.start_t,
                        t_end=event.t,
                        track_ids=[event.track_id],
                        trigger_rule="sustained_target_behavior",
                        trigger_confidence=run.max_conf,
                    )
                )

        # update position/last-seen for proximity, then re-evaluate proximity
        # runs, this track paired against every other recently-seen track in
        # the same camera.
        track.last_t = event.t
        track.last_pos = _bbox_center(event.bbox)
        track.last_det_conf = event.det_conf

        for other_id, other in list(cam.tracks.items()):
            if other_id == event.track_id:
                continue
            if event.t - other.last_t > cfg.proximity_max_staleness_s:
                continue  # stale position, don't treat as "currently close"

            pair = frozenset((event.track_id, other_id))
            dist = _distance(track.last_pos, other.last_pos)
            run = cam.proximity_runs.setdefault(pair, _BehaviorRun())
            # reuse _BehaviorRun with an inverted "confidence": treat being
            # within threshold as conf=1.0, outside as conf=0.0, so the same
            # observe()/duration_at() sustain logic applies unchanged.
            within = 1.0 if dist < cfg.proximity_threshold_px else 0.0
            run.observe(event.t, within, 0.5)
            if (
                not run.fired
                and run.start_t is not None
                and run.duration_at(event.t) >= cfg.proximity_min_duration_s
            ):
                run.fired = True
                a, b = sorted(pair)
                candidates.append(
                    self._make_candidate(
                        camera_id=event.camera_id,
                        t_start=run.start_t,
                        t_end=event.t,
                        track_ids=[a, b],
                        trigger_rule="close_proximity",
                        trigger_confidence=min(track.last_det_conf, other.last_det_conf),
                    )
                )

        return candidates

    def _make_candidate(
        self,
        *,
        camera_id: str,
        t_start: float,
        t_end: float,
        track_ids: list[int],
        trigger_rule: str,
        trigger_confidence: float,
    ) -> CandidateClip:
        cfg = self.config
        clip_id = f"{camera_id}:{int(t_start)}"
        return CandidateClip(
            clip_id=clip_id,
            camera_id=camera_id,
            t_start=t_start - cfg.clip_pad_s,
            t_end=t_end + cfg.clip_pad_s,
            track_ids=track_ids,
            trigger_rule=trigger_rule,
            trigger_confidence=trigger_confidence,
        )

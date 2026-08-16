"""Rule configuration for the Event Evaluator — §3.1 of the design doc.

Deliberately plain data, no model weights: this is the "explicit,
inspectable rules" layer the design doc calls for. Tune these during
the offline-harness pass (§9 risk: "rule thresholds are guesses on day
one") without touching engine.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _float_env(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _list_env(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    return [b.strip() for b in raw.split(",")] if raw else default


@dataclass(frozen=True)
class RuleConfig:
    # sustained_aggression — "aggressing" is the real AlphaChimp model's
    # own label (see services/alphachimp/backend.py's ACTION_CLASS_NAMES,
    # taken from the checkpoint's 24-class taxonomy). The design doc's
    # original "aggression" was a hypothetical placeholder name predating
    # real-model integration.
    aggression_behavior: str = field(default_factory=lambda: os.environ.get("AGGRESSION_BEHAVIOR", "aggressing"))
    aggression_conf_threshold: float = field(default_factory=lambda: _float_env("AGGRESSION_CONF_THRESHOLD", 0.70))
    aggression_min_duration_s: float = field(default_factory=lambda: _float_env("AGGRESSION_MIN_DURATION_S", 2.0))

    # close_proximity
    proximity_threshold_px: float = field(default_factory=lambda: _float_env("PROXIMITY_THRESHOLD_PX", 150.0))
    proximity_min_duration_s: float = field(default_factory=lambda: _float_env("PROXIMITY_MIN_DURATION_S", 3.0))
    # a track's last-known position older than this is considered stale and dropped
    # from proximity consideration rather than compared against.
    proximity_max_staleness_s: float = field(default_factory=lambda: _float_env("PROXIMITY_MAX_STALENESS_S", 1.0))

    # sustained_target_behavior — example watchlist from the real 24-class
    # taxonomy (design doc: "configurable per deployment"); "displaying" is
    # an assertive/dominance display distinct from full "aggressing",
    # "solitary object playing" can flag social withdrawal. Tune per site.
    watchlist_behaviors: tuple[str, ...] = field(
        default_factory=lambda: tuple(_list_env("WATCHLIST_BEHAVIORS", ["displaying", "solitary object playing"]))
    )
    watchlist_conf_threshold: float = field(default_factory=lambda: _float_env("WATCHLIST_CONF_THRESHOLD", 0.60))
    watchlist_min_duration_s: float = field(default_factory=lambda: _float_env("WATCHLIST_MIN_DURATION_S", 5.0))

    # candidate-clips padding, per §3.1: "[t_start - 5s, t_end + 5s]"
    clip_pad_s: float = field(default_factory=lambda: _float_env("CLIP_PAD_S", 5.0))

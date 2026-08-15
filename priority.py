"""
ZooSentry — deterministic priority engine.

NOT anomaly detection. A fixed lookup table + simple modifiers, per
section 9 of the design doc. Explainable, easy to tune with keeper input.
"""

BASE_PRIORITY = {
    "aggression": 3,
    "piloerection": 2,
    "display": 2,
    "other": 1,
    "resting": 0,
    "travel_or_movement": 0,
    "feeding": 0,
    "grooming": 0,
    "playing": 0,
}

LABELS = {
    3: "HIGH",
    2: "MEDIUM",
    1: "REVIEW",
    0: "INFO",
}


def score_event(behavior: str, confidence: str, repeat_count_in_clip: int = 1) -> int:
    """
    repeat_count_in_clip: how many times this same review-worthy behavior
    appears in the same clip (>=1). Only matters if base priority > 0.
    """
    base = BASE_PRIORITY.get(behavior, 1)
    score = base

    if base > 0 and confidence == "high":
        score += 1
    if base > 0 and repeat_count_in_clip > 1:
        score += 1

    return max(0, min(3, score))


def label_for(score: int) -> str:
    return LABELS.get(score, "INFO")


def score_clip_events(events: list[dict]) -> list[dict]:
    """
    Given the raw event list from a single clip's VSS analysis, compute a
    priority score per event (accounting for repeats of the same behavior
    within that clip) and return the events annotated with 'priority' + 'label'.
    """
    behavior_counts = {}
    for e in events:
        behavior_counts[e["behavior"]] = behavior_counts.get(e["behavior"], 0) + 1

    scored = []
    for e in events:
        repeat_count = behavior_counts[e["behavior"]]
        score = score_event(e["behavior"], e.get("confidence", "low"), repeat_count)
        scored.append({**e, "priority": score, "label": label_for(score)})
    return scored
"""
ZooSentry — deterministic priority engine.

NOT anomaly detection. A fixed lookup table + simple modifiers.

Covers two vocabularies that both feed into the same `observations` table:

1. The 9-behavior vocabulary from the original VSS/Cosmos prompt
   (design doc section 7) — kept as-is for backward compatibility.
2. The full 23-category ethogram from ChimpACT/AlphaChimp (Table A1 in
   the AlphaChimp paper), which is far more precise and is what
   alphachimp_client.py emits.

Where a behavior exists in both vocabularies under different names
(e.g. VSS's "aggression" vs the ethogram's "aggressing"), both keys are
present and score identically, so priority stays consistent regardless
of which detector produced the event.
"""

BASE_PRIORITY = {
    # --- Original VSS/Cosmos vocabulary (design doc section 7) ---
    "aggression": 3,
    "piloerection": 2,
    "display": 2,
    "other": 1,
    "resting": 0,
    "travel_or_movement": 0,
    "feeding": 0,
    "grooming": 0,
    "playing": 0,

    # --- ChimpACT/AlphaChimp ethogram (Table A1) ---
    # Locomotion
    "moving": 0,
    "climbing": 0,
    "sleeping": 0,
    # ("resting" already covered above)

    # Object interaction
    "solitary_object_playing": 0,
    "eating": 0,
    "manipulating_object": 0,

    # Social interaction
    "being_groomed": 0,
    "aggressing": 3,                # same weight as "aggression"
    "embracing": 0,
    "begging": 1,                   # possible resource tension, worth a look
    "being_begged_from": 1,
    "taking_object": 1,             # contested resource — can precede conflict
    "losing_object": 1,
    "carrying": 0,
    "being_carried": 0,
    "nursing": 0,
    "being_nursed": 0,
    "touching": 0,
    # ("grooming" and "playing" already covered above)

    # Others
    "erection": 0,                  # physiological, not itself concerning
    "displaying": 2,                # same weight as "display"
}

LABELS = {
    3: "HIGH",
    2: "MEDIUM",
    1: "REVIEW",
    0: "INFO",
}

# Cheap corroboration check: does Cosmos's free-text description use
# language consistent with what AlphaChimp flagged? No extra API call —
# just a keyword match against the enrichment response you already have.
# This is a soft signal, not a re-classification: it only ever adds +1,
# never subtracts, since Cosmos disagreeing doesn't prove AlphaChimp wrong.
CORROBORATION_KEYWORDS = {
    "aggression": ["aggress", "fight", "attack", "chase", "bite", "hit", "slap", "conflict"],
    "aggressing": ["aggress", "fight", "attack", "chase", "bite", "hit", "slap", "conflict"],
    "display": ["display", "swagger", "piloerection", "dominance", "stomp"],
    "displaying": ["display", "swagger", "piloerection", "dominance", "stomp"],
    "begging": ["beg", "request", "reach", "extend", "palm"],
    "being_begged_from": ["beg", "request"],
    "taking_object": ["take", "grab", "snatch", "steal", "wrest"],
    "losing_object": ["lose", "taken", "grabbed"],
}


def check_corroboration(description: str, behavior: str) -> bool:
    """True if the VLM's free-text description uses language matching the
    flagged behavior. Only meaningful for behaviors with defined keywords
    (the ones worth the enrichment call in the first place)."""
    keywords = CORROBORATION_KEYWORDS.get(behavior, [])
    if not keywords:
        return False
    text = description.lower()
    return any(k in text for k in keywords)


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
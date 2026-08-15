"""
ZooSentry — Nemotron client.

Talks to NVIDIA's hosted OpenAI-compatible API for
nvidia/nvidia-nemotron-nano-9b-v2 to turn the structured shift event packet
into a worker-facing brief.

Live by default once NVIDIA_API_KEY is set. Set NEMOTRON_USE_MOCK=1 to force
the offline templated fallback (useful for demos without network access).
"""

import os
import json

import requests

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_API_BASE = os.environ.get("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1")
MODEL = os.environ.get("NEMOTRON_MODEL", "nvidia/nvidia-nemotron-nano-9b-v2")

# Live by default now that NVIDIA_API_KEY can be set. Force offline mock
# with NEMOTRON_USE_MOCK=1, or automatically fall back if no key is set.
USE_MOCK = os.environ.get("NEMOTRON_USE_MOCK", "0") == "1" or not NVIDIA_API_KEY

REQUEST_TIMEOUT = 60

SHIFT_BRIEF_PROMPT = """You are producing a shift handover brief for a zoo worker.

Use only the provided structured observations.
Do not invent events.
Do not make a medical diagnosis.
Prioritize evidence that a worker should review.

Return JSON:
{
  "headline": "...",
  "review_first": [
    {
      "video_id": "...",
      "timestamp": "...",
      "reason": "..."
    }
  ],
  "shift_summary": "...",
  "social_activity_summary": "...",
  "feeding_activity_summary": "...",
  "activity_summary": "..."
}
"""


def _mock_brief(event_packet: dict) -> dict:
    metrics = event_packet["metrics"]
    priority_events = event_packet["priority_events"]

    high_events = [e for e in priority_events if e["priority"] == 3]
    med_events = [e for e in priority_events if e["priority"] == 2]

    if high_events:
        headline = f"{len(high_events)} high-priority event(s) require review this shift."
    elif med_events:
        headline = f"{len(med_events)} medium-priority event(s) worth a look this shift."
    else:
        headline = "No high-priority events. Shift activity looks routine."

    review_first = [
        {
            "video_id": e["video_id"],
            "timestamp": f"{e['start_s']:.0f}s-{e['end_s']:.0f}s",
            "reason": e["description"],
        }
        for e in sorted(priority_events, key=lambda x: -x["priority"])[:5]
        if e["priority"] > 0
    ]

    return {
        "headline": headline,
        "review_first": review_first,
        "shift_summary": (
            f"{event_packet['clips_processed']} clips reviewed. "
            f"{len(high_events)} high-priority and {len(med_events)} medium-priority "
            f"events flagged for review."
        ),
        "social_activity_summary": (
            f"Grooming observed in {metrics.get('grooming_events', 0)} clip(s); "
            f"play observed in {metrics.get('playing_events', 0)} clip(s)."
        ),
        "feeding_activity_summary": f"Feeding observed in {metrics.get('feeding_events', 0)} clip(s).",
        "activity_summary": (
            f"Movement observed in {metrics.get('movement_events', 0)} clip(s); "
            f"resting observed in {metrics.get('resting_events', 0)} clip(s)."
        ),
    }


def generate_shift_brief(event_packet: dict) -> dict:
    if USE_MOCK:
        return _mock_brief(event_packet)

    resp = requests.post(
        f"{NVIDIA_API_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {NVIDIA_API_KEY}"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SHIFT_BRIEF_PROMPT},
                {"role": "user", "content": json.dumps(event_packet)},
            ],
            "temperature": 0.2,
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _parse_brief_json(content)


def _parse_brief_json(raw_text: str) -> dict:
    """
    Strip markdown fences if Nemotron wraps its JSON, and fail loudly with
    the raw text included if it still doesn't parse, since the prompt asks
    for JSON-only output and the dashboard assumes these keys exist.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Nemotron did not return valid JSON for the shift brief.\n"
            f"Raw response was:\n{raw_text}"
        ) from e

    # Ensure every key app.py reads is present, even if Nemotron omitted one.
    parsed.setdefault("headline", "")
    parsed.setdefault("review_first", [])
    parsed.setdefault("shift_summary", "")
    parsed.setdefault("social_activity_summary", "")
    parsed.setdefault("feeding_activity_summary", "")
    parsed.setdefault("activity_summary", "")
    return parsed
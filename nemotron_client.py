"""
ZooSentry — Nemotron client.

Today: mocked. Produces a shift brief from the structured event packet
using simple templating instead of a real LLM call.

When you have an NVIDIA API key:
    1. Set NVIDIA_API_KEY (env var).
    2. Flip USE_MOCK = False.
    3. Uncomment the real call below (OpenAI-compatible endpoint for
       nvidia/nvidia-nemotron-nano-9b-v2, per design doc section 11).
"""

import os
import json

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_API_BASE = "https://integrate.api.nvidia.com/v1"
MODEL = "nvidia/nvidia-nemotron-nano-9b-v2"
USE_MOCK = True

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

    # --- Real Nemotron call (uncomment when NVIDIA_API_KEY is set) ---
    # import requests
    # resp = requests.post(
    #     f"{NVIDIA_API_BASE}/chat/completions",
    #     headers={"Authorization": f"Bearer {NVIDIA_API_KEY}"},
    #     json={
    #         "model": MODEL,
    #         "messages": [
    #             {"role": "system", "content": SHIFT_BRIEF_PROMPT},
    #             {"role": "user", "content": json.dumps(event_packet)},
    #         ],
    #         "temperature": 0.2,
    #     },
    #     timeout=60,
    # )
    # resp.raise_for_status()
    # text = resp.json()["choices"][0]["message"]["content"]
    # return json.loads(text)
"""
ZooSentry — VSS client.

Today: no VSS deployment exists, so this returns realistic MOCK responses
shaped exactly like what the real VSS Agent API returns, per the design doc
(section 5, 7):

    POST {VSS_BASE_URL}/api/v1/videos          -> upload/register a clip
    POST {VSS_BASE_URL}/chat  (or /generate)    -> behavior-extraction Q&A

When you have a real VSS instance:
    1. Set VSS_BASE_URL (env var or below).
    2. Flip USE_MOCK = False.
    3. The real request/response code is already written below (commented) —
       uncomment it. Nothing else in the pipeline needs to change, because
       upload_video() and analyze_clip() keep the same return shape either way.
"""

import os
import json
import random
import time

VSS_BASE_URL = os.environ.get("VSS_BASE_URL", "http://localhost:8100")
USE_MOCK = True  # flip to False once a real VSS endpoint exists

BEHAVIOR_EXTRACTION_PROMPT = """You are reviewing chimpanzee enclosure footage for a zoo worker.

Analyze only directly visible behavior.
Do not diagnose illness.
Do not infer the persistent identity of any animal.
Do not assume an animal in this video is the same animal in another video.

Look for these behaviors:
- aggression
- grooming
- playing
- feeding
- resting
- travel_or_movement
- display
- piloerection
- other

Return JSON only.

Schema:
{
  "clip_summary": "one short factual sentence",
  "events": [
    {
      "start_s": 0.0,
      "end_s": 0.0,
      "behavior": "aggression|grooming|playing|feeding|resting|travel_or_movement|display|piloerection|other",
      "animals_visible": "0|1|2|3+|unknown",
      "description": "short directly visible observation",
      "confidence": "low|medium|high"
    }
  ]
}

Rules:
- Prefer observable facts over interpretation.
- If uncertain, use "other" or low confidence.
- Do not call normal resting a health problem.
- Do not claim an animal is isolated unless the video visibly supports it.
"""

# ---------------------------------------------------------------------------
# Mock behavior bank used to fabricate plausible clip analyses for the demo.
# ---------------------------------------------------------------------------
_MOCK_BEHAVIOR_POOL = [
    ("aggression", "Two chimpanzees engage in a brief physical altercation.", "high"),
    ("grooming", "One chimpanzee grooms another while seated.", "high"),
    ("playing", "Juvenile chimpanzees chase each other around a tire structure.", "medium"),
    ("feeding", "A chimpanzee forages and eats from scattered food.", "high"),
    ("resting", "A chimpanzee sits still in a shaded area.", "high"),
    ("travel_or_movement", "A chimpanzee moves across the enclosure toward the climbing structure.", "medium"),
    ("display", "A chimpanzee performs a bipedal display, arms raised.", "medium"),
    ("piloerection", "A chimpanzee's hair appears raised while facing another animal.", "low"),
    ("other", "Ambiguous movement near the enclosure edge.", "low"),
]


def _mock_upload(filename: str) -> dict:
    return {
        "video_id": filename.rsplit(".", 1)[0],
        "filename": filename,
        "vss_sensor_id": f"mock-sensor-{random.randint(1000, 9999)}",
        "status": "uploaded",
    }


def _mock_analyze(video_id: str) -> dict:
    """Fabricate a plausible VSS/Cosmos response for one clip."""
    random.seed(video_id)  # deterministic per video_id so re-runs are stable
    n_events = random.randint(1, 3)
    chosen = random.sample(_MOCK_BEHAVIOR_POOL, n_events)

    events = []
    cursor = 0.0
    for behavior, desc, conf in chosen:
        start = cursor + random.uniform(0, 3)
        end = start + random.uniform(3, 8)
        cursor = end
        events.append({
            "start_s": round(start, 1),
            "end_s": round(end, 1),
            "behavior": behavior,
            "animals_visible": random.choice(["1", "2", "3+"]),
            "description": desc,
            "confidence": conf,
        })

    return {
        "clip_summary": f"Chimpanzee enclosure footage showing {', '.join(b for b, _, _ in chosen)}.",
        "events": events,
    }


def upload_video(filepath: str) -> dict:
    """
    Register a clip with VSS.
    Returns: {"video_id", "filename", "vss_sensor_id", "status"}
    """
    filename = os.path.basename(filepath)

    if USE_MOCK:
        return _mock_upload(filename)

    # --- Real VSS call (uncomment when VSS_BASE_URL is live) ---
    # import requests
    # with open(filepath, "rb") as f:
    #     resp = requests.post(
    #         f"{VSS_BASE_URL}/api/v1/videos",
    #         files={"file": (filename, f, "video/mp4")},
    #         timeout=120,
    #     )
    # resp.raise_for_status()
    # data = resp.json()
    # return {
    #     "video_id": data["video_id"],
    #     "filename": filename,
    #     "vss_sensor_id": data.get("sensor_id"),
    #     "status": "uploaded",
    # }


def analyze_clip(video_id: str) -> dict:
    """
    Ask the VSS agent (Cosmos3 Nano Reasoner under the hood) to extract
    behaviors from a previously-uploaded clip.
    Returns: {"clip_summary": str, "events": [ {...}, ... ]}
    """
    if USE_MOCK:
        time.sleep(0.05)  # simulate latency
        return _mock_analyze(video_id)

    # --- Real VSS call (uncomment when VSS_BASE_URL is live) ---
    # import requests
    # resp = requests.post(
    #     f"{VSS_BASE_URL}/chat",
    #     json={
    #         "id": video_id,
    #         "prompt": BEHAVIOR_EXTRACTION_PROMPT,
    #     },
    #     timeout=180,
    # )
    # resp.raise_for_status()
    # text = resp.json()["choices"][0]["message"]["content"]
    # return json.loads(text)


def ask_followup(video_id: str, question: str) -> str:
    """Follow-up Q&A about a specific clip, routed through VSS."""
    if USE_MOCK:
        return (
            f"[MOCK VSS RESPONSE for {video_id}] In the moments before the event, "
            f"the animals were within close proximity near the same feeding area, "
            f"with no visible separation beforehand."
        )

    # --- Real VSS call (uncomment when VSS_BASE_URL is live) ---
    # import requests
    # resp = requests.post(
    #     f"{VSS_BASE_URL}/chat",
    #     json={"id": video_id, "prompt": question},
    #     timeout=180,
    # )
    # resp.raise_for_status()
    # return resp.json()["choices"][0]["message"]["content"]
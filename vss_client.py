"""
ZooSentry — VSS client.

Talks to a real NVIDIA VSS instance (dev-profile-base, edge deployment e.g.
DGX Spark) using the actual VSS REST API:

    POST {VSS_BASE_URL}/files              -> upload a clip, returns a file id
    POST {VSS_BASE_URL}/summarize          -> behavior-extraction "summary" call
    POST {VSS_BASE_URL}/chat/completions   -> follow-up Q&A on an ingested clip

Auth: Bearer token via the Authorization header (set VSS_API_KEY).

Set USE_MOCK = True (or env var VSS_USE_MOCK=1) to fall back to fabricated
responses when no VSS instance is reachable — useful for offline dev/demo.
"""

import os
import json
import random
import time

import requests

VSS_BASE_URL = os.environ.get("VSS_BASE_URL", "http://localhost:8100").rstrip("/")
VSS_API_KEY = os.environ.get("VSS_API_KEY", "")
VSS_MODEL = os.environ.get("VSS_MODEL", "cosmos-reason2")

# Live by default now that a real VSS endpoint + key are available.
# Set VSS_USE_MOCK=1 in the environment to force offline mock mode.
USE_MOCK = os.environ.get("VSS_USE_MOCK", "0") == "1"

REQUEST_TIMEOUT_UPLOAD = 120
REQUEST_TIMEOUT_SUMMARIZE = 180
REQUEST_TIMEOUT_CHAT = 120


def _auth_headers() -> dict:
    headers = {}
    if VSS_API_KEY:
        headers["Authorization"] = f"Bearer {VSS_API_KEY}"
    return headers

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
    Upload a clip to VSS via POST /files.
    Returns: {"video_id", "filename", "vss_sensor_id", "status"}
    """
    filename = os.path.basename(filepath)

    if USE_MOCK:
        return _mock_upload(filename)

    with open(filepath, "rb") as f:
        resp = requests.post(
            f"{VSS_BASE_URL}/files",
            headers=_auth_headers(),
            data={"purpose": "vision", "media_type": "video"},
            files={"file": (filename, f, "video/mp4")},
            timeout=REQUEST_TIMEOUT_UPLOAD,
        )
    resp.raise_for_status()
    data = resp.json()
    return {
        "video_id": data["id"],
        "filename": filename,
        "vss_sensor_id": data.get("id"),
        "status": "uploaded",
    }


def analyze_clip(video_id: str) -> dict:
    """
    Ask VSS (Cosmos Reason under the hood) to extract behaviors from a
    previously-uploaded clip via POST /summarize.
    Returns: {"clip_summary": str, "events": [ {...}, ... ]}
    """
    if USE_MOCK:
        time.sleep(0.05)  # simulate latency
        return _mock_analyze(video_id)

    body = {
        "id": video_id,
        "prompt": BEHAVIOR_EXTRACTION_PROMPT,
        "caption_summarization_prompt": (
            "Combine sequential captions of visible chimpanzee behavior into a "
            "single structured JSON event list matching the requested schema."
        ),
        "summary_aggregation_prompt": (
            "Return only the final JSON object matching the requested schema. "
            "No prose outside the JSON."
        ),
        "model": VSS_MODEL,
        "max_tokens": 1536,
        "temperature": 0.2,
        "top_p": 0.3,
        "chunk_duration": 20,
    }
    resp = requests.post(
        f"{VSS_BASE_URL}/summarize",
        headers=_auth_headers(),
        json=body,
        timeout=REQUEST_TIMEOUT_SUMMARIZE,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _parse_behavior_json(content)


def ask_followup(video_id: str, question: str) -> str:
    """Follow-up Q&A about a specific clip via POST /chat/completions."""
    if USE_MOCK:
        return (
            f"[MOCK VSS RESPONSE for {video_id}] In the moments before the event, "
            f"the animals were within close proximity near the same feeding area, "
            f"with no visible separation beforehand."
        )

    payload = {
        "id": video_id,
        "messages": [{"content": question, "role": "user"}],
        "model": VSS_MODEL,
    }
    resp = requests.post(
        f"{VSS_BASE_URL}/chat/completions",
        headers=_auth_headers(),
        json=payload,
        timeout=REQUEST_TIMEOUT_CHAT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _parse_behavior_json(raw_text: str) -> dict:
    """
    Cosmos/Nemotron sometimes wrap JSON in markdown fences or add stray text.
    Strip that before parsing, and fail loudly (with the raw text) if the
    model didn't return valid JSON, since the design doc's prompt asks for
    JSON-only output and downstream code assumes it.
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
            f"VSS did not return valid JSON for behavior extraction.\n"
            f"Raw response was:\n{raw_text}"
        ) from e

    parsed.setdefault("clip_summary", "")
    parsed.setdefault("events", [])
    return parsed
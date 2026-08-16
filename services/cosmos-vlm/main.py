"""Cosmos VLM service.

Consumes clip-ready, watches the clip, produces a free-text
description. If COSMOS_NIM_URL is set, calls the real rt-vlm service
from the VSS repo (deploy/docker/services/rtvi/rtvi-vlm/ — an
OpenAI-chat-completions-compatible wrapper around a Cosmos-class NIM;
image nvcr.io/nim/nvidia/cosmos-reason2-8b:1.6.0 in the standalone NIM
compose, or nvcr.io/nim/nvidia/cosmos3-reasoner:1.7 which is what the
VSS alerts profile actually defaults to — health check at
`GET /v1/health/ready`, chat at `POST /v1/chat/completions`).
Otherwise falls back to a stub description so the rest of the pipeline
can be exercised without a GPU/NIM present. Swap modes with one env
var — nothing downstream (Nemotron, Event Writer) needs to change
either way.
"""
from __future__ import annotations

import logging
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared import topics  # noqa: E402
from shared.kafka_utils import consume, get_consumer, get_producer, publish  # noqa: E402
from shared.schemas import ClipReady, VlmDescription  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("cosmos-vlm")

COSMOS_NIM_URL = os.environ.get("COSMOS_NIM_URL")  # e.g. http://host.docker.internal:<RTVI_VLM_PORT>/v1/chat/completions
COSMOS_MODEL_NAME = os.environ.get("COSMOS_MODEL_NAME", "cosmos3-reasoner")

PROMPT = (
    "Watch this enclosure clip and describe what happened before, during, "
    "and after the trigger moment. Note each animal's actions, whether "
    "there was physical contact, and how the group responded. Be concise "
    "and factual."
)


def _describe_via_nim(clip_uri: str) -> str:
    # NIM multimodal request shape varies by container version — this is a
    # representative OpenAI-chat-completions-style call; adjust the payload
    # to match the deployed NIM's actual API contract.
    resp = requests.post(
        COSMOS_NIM_URL,
        json={
            "model": COSMOS_MODEL_NAME,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "video_url", "video_url": {"url": clip_uri}},
                    ],
                }
            ],
            "max_tokens": 300,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _describe_via_stub(clip_uri: str, duration_s: float) -> str:
    try:
        exists = requests.head(clip_uri, timeout=10).ok
    except requests.RequestException:
        exists = False
    return (
        f"[stub] {duration_s:.1f}s clip{' reachable' if exists else ' NOT reachable'} at {clip_uri}. "
        "No Cosmos NIM configured (set COSMOS_NIM_URL) — this is a placeholder "
        "description standing in for what the real VLM would report about the animals' "
        "actions, contact, and group response in this window."
    )


def describe(clip: ClipReady) -> tuple[str, str]:
    if COSMOS_NIM_URL:
        return _describe_via_nim(clip.clip_uri), COSMOS_MODEL_NAME
    return _describe_via_stub(clip.clip_uri, clip.duration_s), "stub"


def main() -> None:
    consumer = get_consumer(topics.CLIP_READY, group_id="cosmos-vlm")
    producer = get_producer()

    logger.info("cosmos-vlm up (%s), consuming %s", "NIM" if COSMOS_NIM_URL else "stub", topics.CLIP_READY)
    for clip in consume(consumer, ClipReady):
        start = time.time()
        try:
            description, model_name = describe(clip)
        except Exception:  # noqa: BLE001
            logger.exception("failed to describe clip %s", clip.clip_id)
            continue
        latency_ms = int((time.time() - start) * 1000)

        publish(
            producer,
            topics.VLM_DESCRIPTIONS,
            VlmDescription(clip_id=clip.clip_id, description=description, model=model_name, latency_ms=latency_ms),
            key=clip.clip_id,
        )
        logger.info("described clip=%s model=%s latency_ms=%d", clip.clip_id, model_name, latency_ms)


if __name__ == "__main__":
    main()

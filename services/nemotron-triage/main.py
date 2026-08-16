"""Nemotron Triage service.

Joins the trigger context with the VLM description and decides
report-worthiness, priority, category, and reason. §3 lists the input
as "alphachimp-events (trigger context) + vlm-descriptions", but the
trigger context that actually matters (which rule fired, at what
confidence, over which tracks/time range) lives in candidate-clips,
not the raw per-frame stream — re-deriving it from alphachimp-events
would mean duplicating the Event Evaluator's state machine here. So
this service joins candidate-clips + clip-ready + vlm-descriptions on
clip_id — clip-ready is included too since it's the only message that
carries clip_uri, which nemotron-verdicts (§4.1) requires.

If NEMOTRON_NIM_URL is set, calls the real NIM — per
deploy/docker/services/nim/ in the VSS repo, the closest reasoning-
sized match is nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:1
(OpenAI-chat-completions-compatible, same contract every other NIM in
this repo uses). Otherwise a deterministic stub heuristic stands in so
the pipeline runs without a GPU/NIM present.
"""
from __future__ import annotations

import json
import logging
import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared import topics  # noqa: E402
from shared.kafka_utils import get_consumer, get_producer, publish  # noqa: E402
from shared.schemas import CandidateClip, ClipReady, NemotronVerdict, VlmDescription  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("nemotron-triage")

NEMOTRON_NIM_URL = os.environ.get("NEMOTRON_NIM_URL")  # e.g. http://host.docker.internal:<nim-port>/v1/chat/completions
NEMOTRON_MODEL_NAME = os.environ.get("NEMOTRON_MODEL_NAME", "nvidia-nemotron-nano-9b-v2")

SYSTEM_PROMPT = (
    "You triage primate enclosure events for zookeepers. Given the rule that "
    "fired and a vision-language model's description of the clip, decide "
    "whether this is worth a human's attention. Respond with strict JSON: "
    '{"report": bool, "priority": "high"|"medium"|"low", '
    '"category": "aggression"|"health"|"social"|"routine", '
    '"reason": str, "worker_summary": str}. "reason" explains your judgment '
    "for an internal audit trail; \"worker_summary\" is a one-sentence, "
    "plain-language note for the on-duty keeper."
)


def _verdict_via_nim(candidate: CandidateClip, vlm: VlmDescription) -> dict:
    user_prompt = (
        f"Trigger rule: {candidate.trigger_rule} (confidence {candidate.trigger_confidence:.2f})\n"
        f"Camera: {candidate.camera_id}, tracks: {candidate.track_ids}\n"
        f"VLM description: {vlm.description}"
    )
    resp = requests.post(
        NEMOTRON_NIM_URL,
        json={
            "model": NEMOTRON_MODEL_NAME,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 300,
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def _verdict_via_stub(candidate: CandidateClip, vlm: VlmDescription) -> dict:
    """Deterministic heuristic standing in for the real Nemotron NIM, so the
    pipeline is exercisable end-to-end without a GPU. NOT a validated
    judgment — see design doc §9 risk on unvalidated verdicts."""
    rule_category = {
        "sustained_aggression": "aggression",
        "close_proximity": "social",
        "sustained_target_behavior": "health",
    }.get(candidate.trigger_rule, "routine")

    if candidate.trigger_rule == "sustained_aggression" and candidate.trigger_confidence > 0.75:
        priority, report = "high", True
    elif candidate.trigger_confidence > 0.6:
        priority, report = "medium", True
    else:
        priority, report = "low", False

    reason = (
        f"[stub] {candidate.trigger_rule} trigger at confidence "
        f"{candidate.trigger_confidence:.2f}, corroborated by VLM description: "
        f"{vlm.description[:200]}"
    )
    worker_summary = f"Possible {rule_category} event on {candidate.camera_id}, tracks {candidate.track_ids}."
    return {
        "report": report,
        "priority": priority,
        "category": rule_category,
        "reason": reason,
        "worker_summary": worker_summary,
    }


def evaluate(candidate: CandidateClip, vlm: VlmDescription, clip_uri: str) -> NemotronVerdict:
    try:
        raw = _verdict_via_nim(candidate, vlm) if NEMOTRON_NIM_URL else _verdict_via_stub(candidate, vlm)
    except Exception:  # noqa: BLE001
        logger.exception("nemotron verdict generation failed, falling back to stub heuristic")
        raw = _verdict_via_stub(candidate, vlm)

    return NemotronVerdict(
        event_id=candidate.clip_id,
        report=raw["report"],
        priority=raw["priority"],
        category=raw["category"],
        reason=raw["reason"],
        worker_summary=raw["worker_summary"],
        clip_uri=clip_uri,
        camera_id=candidate.camera_id,
        start_time=candidate.t_start,
        end_time=candidate.t_end,
        track_ids=candidate.track_ids,
        trigger_type=candidate.trigger_rule,
        trigger_confidence=candidate.trigger_confidence,
        vlm_summary=vlm.description,
    )


_TOPIC_MODELS = {
    topics.CANDIDATE_CLIPS: ("candidate", CandidateClip),
    topics.CLIP_READY: ("clip_ready", ClipReady),
    topics.VLM_DESCRIPTIONS: ("vlm", VlmDescription),
}


def main() -> None:
    consumer = get_consumer(list(_TOPIC_MODELS), group_id="nemotron-triage")
    producer = get_producer()

    pending: dict[str, dict] = {}

    logger.info(
        "nemotron-triage up (%s), joining %s on clip_id",
        "NIM" if NEMOTRON_NIM_URL else "stub",
        ", ".join(_TOPIC_MODELS),
    )
    for record in consumer:
        field_name, model = _TOPIC_MODELS.get(record.topic, (None, None))
        if model is None:
            continue
        try:
            parsed = model.model_validate(record.value)
        except Exception:  # noqa: BLE001
            logger.exception("skipping malformed %s message: %r", record.topic, record.value)
            continue

        clip_id = parsed.clip_id
        entry = pending.setdefault(clip_id, {})
        entry[field_name] = parsed

        if all(k in entry for k, _ in _TOPIC_MODELS.values()):
            verdict = evaluate(entry["candidate"], entry["vlm"], entry["clip_ready"].clip_uri)
            publish(producer, topics.NEMOTRON_VERDICTS, verdict, key=verdict.event_id)
            logger.info("verdict event_id=%s report=%s priority=%s", verdict.event_id, verdict.report, verdict.priority)
            del pending[clip_id]


if __name__ == "__main__":
    main()

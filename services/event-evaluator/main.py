"""Event Evaluator service entrypoint.

Consumes alphachimp-events, runs them through the stateful rule engine
(engine.py), publishes any resulting candidate-clips. Pure CPU, no LLM.
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from engine import EventEvaluator  # noqa: E402
from rules import RuleConfig  # noqa: E402
from shared import topics  # noqa: E402
from shared.kafka_utils import consume, get_consumer, get_producer, publish  # noqa: E402
from shared.schemas import AlphaChimpEvent  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("event-evaluator")


def main() -> None:
    consumer = get_consumer(topics.ALPHACHIMP_EVENTS, group_id="event-evaluator")
    producer = get_producer()
    evaluator = EventEvaluator(RuleConfig())

    logger.info("event-evaluator up, consuming %s", topics.ALPHACHIMP_EVENTS)
    for event in consume(consumer, AlphaChimpEvent):
        for candidate in evaluator.process(event):
            logger.info(
                "rule fired: %s camera=%s tracks=%s conf=%.2f -> %s",
                candidate.trigger_rule,
                candidate.camera_id,
                candidate.track_ids,
                candidate.trigger_confidence,
                candidate.clip_id,
            )
            publish(producer, topics.CANDIDATE_CLIPS, candidate, key=candidate.camera_id)


if __name__ == "__main__":
    main()

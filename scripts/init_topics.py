"""Creates our 5 custom Kafka topics on VSS's real broker.

VSS's own Kafka runs with KAFKA_AUTO_CREATE_TOPICS_ENABLE=false
(deploy/docker/services/infra/compose.yml) and only pre-creates its own
mdx-* topics via kafka-topic-init-container — our alphachimp-events /
candidate-clips / clip-ready / vlm-descriptions / nemotron-verdicts
topics need their own one-shot bootstrap, run once before any of our
services start producing/consuming.
"""
from __future__ import annotations

import os
import sys
import time

from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

sys.path.insert(0, "/app")
from shared import topics  # noqa: E402

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
TOPIC_NAMES = [
    topics.ALPHACHIMP_EVENTS,
    topics.CANDIDATE_CLIPS,
    topics.CLIP_READY,
    topics.VLM_DESCRIPTIONS,
    topics.NEMOTRON_VERDICTS,
]


def main() -> None:
    last_err = None
    for attempt in range(1, 31):
        try:
            admin = KafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"admin client connect attempt {attempt}/30 failed: {e}")
            time.sleep(2)
    else:
        raise RuntimeError("could not connect admin client to Kafka") from last_err

    new_topics = [NewTopic(name=name, num_partitions=3, replication_factor=1) for name in TOPIC_NAMES]
    try:
        admin.create_topics(new_topics=new_topics, validate_only=False)
        print(f"created topics: {TOPIC_NAMES}")
    except TopicAlreadyExistsError:
        print("topics already exist, skipping")
    except Exception as e:  # noqa: BLE001
        # create_topics raises a combined error if *some* topics already
        # exist and others are new; fall back to creating one at a time.
        print(f"bulk create failed ({e}), retrying topic-by-topic")
        for t in new_topics:
            try:
                admin.create_topics(new_topics=[t], validate_only=False)
                print(f"created {t.name}")
            except TopicAlreadyExistsError:
                print(f"{t.name} already exists")
    admin.close()


if __name__ == "__main__":
    main()

"""Thin Kafka helpers shared by every service.

Wraps kafka-python with pydantic (de)serialization and a startup retry
loop, since in docker-compose the broker often isn't accepting
connections yet when a dependent service's container starts.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable, Iterator, Type, TypeVar

from kafka import KafkaConsumer, KafkaProducer
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")


def _connect_with_retry(factory: Callable[[], T], name: str, retries: int = 30, delay_s: float = 2.0) -> T:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return factory()
        except Exception as e:  # noqa: BLE001 - broad by design, this is a startup retry loop
            last_err = e
            logger.warning("%s connect attempt %d/%d failed: %s", name, attempt, retries, e)
            time.sleep(delay_s)
    raise RuntimeError(f"could not connect to Kafka for {name}") from last_err


def get_producer() -> KafkaProducer:
    return _connect_with_retry(
        lambda: KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k is not None else None,
        ),
        "producer",
    )


def get_raw_producer() -> KafkaProducer:
    """Producer with no value serialization — for topics that carry
    protobuf (or other non-JSON) payloads, e.g. VSS's mdx-raw."""
    return _connect_with_retry(
        lambda: KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: v,
            key_serializer=lambda k: k.encode("utf-8") if k is not None else None,
        ),
        "raw-producer",
    )


def publish(producer: KafkaProducer, topic: str, message: BaseModel, key: str | None = None) -> None:
    producer.send(topic, value=message.model_dump(mode="json"), key=key)
    producer.flush()


def get_consumer(topic: str | list[str], group_id: str) -> KafkaConsumer:
    topics = topic if isinstance(topic, list) else [topic]
    return _connect_with_retry(
        lambda: KafkaConsumer(
            *topics,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="earliest",
            enable_auto_commit=True,
        ),
        f"consumer[{topic}]",
    )


def consume(consumer: KafkaConsumer, model: Type[T]) -> Iterator[T]:
    for record in consumer:
        try:
            yield model.model_validate(record.value)
        except Exception:  # noqa: BLE001 - a malformed message must not kill the consumer loop
            logger.exception("skipping malformed message on %s: %r", record.topic, record.value)
            continue

"""Publishes a synthetic sustained_aggression burst straight onto
alphachimp-events, bypassing AlphaChimp/Video Ingest. Used to validate
that Event Evaluator -> Clip Retrieval -> Cosmos(stub) ->
Nemotron(stub) -> Event Writer actually wires together end-to-end,
without needing real video content to trigger a rule.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, "/app")
from shared import topics  # noqa: E402
from shared.kafka_utils import get_producer, publish  # noqa: E402
from shared.schemas import AlphaChimpEvent  # noqa: E402

CAMERA_ID = os.environ.get("CAMERA_ID", "enc_a")
SEGMENT_START = float(os.environ["SEGMENT_START"])  # must fall inside VIOS's recorded timeline for this sensor
TRACK_ID = int(os.environ.get("TRACK_ID", "99"))


def main() -> None:
    producer = get_producer()
    # 5 frames, 0.5s apart, aggression confidence sustained above 0.70 for
    # 2.0s -> should cross the sustained_aggression threshold (§3.1).
    for i in range(6):
        t = SEGMENT_START + 1.0 + i * 0.5
        event = AlphaChimpEvent(
            camera_id=CAMERA_ID,
            track_id=TRACK_ID,
            t=t,
            bbox=(10.0, 10.0, 20.0, 20.0),
            det_conf=0.95,
            behaviors={"aggressing": 0.85},
        )
        publish(producer, topics.ALPHACHIMP_EVENTS, event, key=CAMERA_ID)
        print(f"published t={t:.2f} aggressing=0.85")
        time.sleep(0.1)


if __name__ == "__main__":
    main()

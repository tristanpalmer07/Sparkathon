"""Video Ingest service.

Replays a dataset file (RTSP live-capture is the same cv2.VideoCapture
call with an rtsp:// URL — swap DATASET_PATH for RTSP_URL to go live,
nothing else in this file changes) for a given camera_id:

  1. Uploads the raw file to VSS's real VIOS service (§6 of the design
     doc: "VIOS ... Recommended if VSS is already deployed") under
     sensorId=camera_id, so Clip Retrieval can later ask VIOS itself
     for a clip instead of us cutting one by hand.
  2. Walks the video in WINDOW_FRAMES / WINDOW_STRIDE steps and POSTs
     each window to AlphaChimp over HTTP — this hop is intentionally
     NOT on Kafka, matching the architecture diagram (frames go
     straight to AlphaChimp; only alphachimp-events goes on the bus).
     Default is one frame every WINDOW_STRIDE frames; the detector
     still builds its own 8-frame temporal clip internally.
"""
from __future__ import annotations

import base64
import logging
import os
import sys
import time

import cv2
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shared import vios_client  # noqa: E402
from windows import WindowWalker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("video-ingest")

CAMERA_ID = os.environ.get("CAMERA_ID", "enc_a")
SOURCE_PATH = os.environ.get("DATASET_PATH") or os.environ.get("RTSP_URL")
ALPHACHIMP_URL = os.environ.get("ALPHACHIMP_URL", "http://alphachimp:8080/infer")
WINDOW_FRAMES = int(os.environ.get("WINDOW_FRAMES", "1"))
WINDOW_STRIDE = int(os.environ.get("WINDOW_STRIDE", "24"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "80"))


def _wait_for_alphachimp(retries: int = 30, delay_s: float = 2.0) -> None:
    health_url = ALPHACHIMP_URL.rsplit("/", 1)[0] + "/health"
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(health_url, timeout=3)
            if r.ok:
                return
        except requests.RequestException as e:
            logger.warning("alphachimp not ready (attempt %d/%d): %s", attempt, retries, e)
        time.sleep(delay_s)
    logger.warning("proceeding without confirmed alphachimp health check")


def _upload_to_vios(start_ts: float) -> dict:
    filename = f"{CAMERA_ID}_{int(start_ts)}.mp4"
    logger.info("uploading %s to VIOS under sensorId=%s", filename, CAMERA_ID)
    result = vios_client.upload_file(CAMERA_ID, SOURCE_PATH, filename, upload_timestamp=start_ts)
    logger.info("VIOS upload complete: streamId=%s sensorId=%s", result.get("streamId"), result.get("sensorId"))
    return result


def _encode_frame(frame) -> str:
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    if not ok:
        raise RuntimeError("failed to JPEG-encode frame")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _post_window(window: list[dict]) -> None:
    payload = {"camera_id": CAMERA_ID, "frames": window}
    try:
        resp = requests.post(ALPHACHIMP_URL, json=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("failed to post frame window to alphachimp: %s", e)


def main() -> None:
    if not SOURCE_PATH:
        raise RuntimeError("set DATASET_PATH (file) or RTSP_URL (stream) for video-ingest")

    vios_client.wait_for_vios()
    _wait_for_alphachimp()

    cap = cv2.VideoCapture(SOURCE_PATH)
    if not cap.isOpened():
        raise RuntimeError(f"could not open video source: {SOURCE_PATH}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

    segment_start_ts = time.time()
    if os.path.isfile(SOURCE_PATH):
        _upload_to_vios(segment_start_ts)
    else:
        logger.info("live source (%s) — skipping VIOS file upload; use vios_client sensor/add for RTSP", SOURCE_PATH)

    walker: WindowWalker[dict] = WindowWalker(WINDOW_FRAMES, WINDOW_STRIDE)
    frame_idx = 0
    logger.info("streaming %s at ~%.1f fps, window=%d stride=%d", SOURCE_PATH, fps, WINDOW_FRAMES, WINDOW_STRIDE)

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = segment_start_ts + frame_idx / fps
        frame_idx += 1
        if walker.skipping:
            walker.push(None)
            continue
        window = walker.push({"t": t, "jpeg_b64": _encode_frame(frame)})
        if window is not None:
            _post_window(window)

    leftover = walker.flush()
    if leftover is not None:
        _post_window(leftover)

    cap.release()
    logger.info("ingest complete: %d frames from %s", frame_idx, SOURCE_PATH)


if __name__ == "__main__":
    main()

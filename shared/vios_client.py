"""Thin client for VSS's real VIOS (Video I/O + Storage) service —
replaces the hand-rolled MinIO/ffmpeg clip store. Endpoints per
video-search-and-summarization/skills/vss-manage-video-io-storage/
references/api-reference.md (sections 3, 4, 8).

VIOS's ingress (`vst-ingress`) runs with `network_mode: host` inside
the VSS docker-compose deployment (deploy/docker/services/vios/
foundational/docker-compose.yaml), listening on VST_INGRESS_HTTP_PORT
(default 30888). Our services run in their own compose project, so we
reach it via the host gateway rather than a VSS-network service name —
see the `extra_hosts: host.docker.internal:host-gateway` entries in
docker-compose.yml for each service that imports this module.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

VIOS_ENDPOINT = os.environ.get("VIOS_ENDPOINT", "http://host.docker.internal:30888")
VIOS_BASE = f"{VIOS_ENDPOINT}/vst/api/v1"
CLIP_URL_EXPIRY_MINUTES = int(os.environ.get("VIOS_CLIP_URL_EXPIRY_MINUTES", "60"))


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def wait_for_vios(retries: int = 30, delay_s: float = 2.0) -> None:
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(f"{VIOS_BASE}/sensor/version", timeout=5)
            if r.ok:
                return
        except requests.RequestException as e:
            logger.warning("VIOS not reachable at %s (attempt %d/%d): %s", VIOS_ENDPOINT, attempt, retries, e)
        time.sleep(delay_s)
    raise RuntimeError(f"VIOS not reachable at {VIOS_ENDPOINT} after {retries} attempts")


def upload_file(camera_id: str, file_path: str, filename: str, upload_timestamp: float | None = None) -> dict:
    """PUT Upload v2 — groups the file under sensorId=camera_id (§8)."""
    ts = _iso(upload_timestamp if upload_timestamp is not None else time.time())
    size = os.path.getsize(file_path)
    url = f"{VIOS_BASE}/storage/file/{filename}"
    with open(file_path, "rb") as f:
        resp = requests.put(
            url,
            params={"timestamp": ts, "sensorId": camera_id},
            data=f,
            headers={"Content-Type": "application/octet-stream", "Content-Length": str(size)},
            timeout=120,
        )
    resp.raise_for_status()
    return resp.json()


def find_stream_id(camera_id: str, t_start: float, t_end: float) -> str | None:
    """File-uploaded sensors (our video-ingest path) aren't tracked by the
    sensor microservice at all — GET /sensor/<sensorId>/streams returns
    HTTP 200 with a VIOS-shaped error body, not a 404 — and streamId does
    NOT reliably equal sensorId: VIOS only names the very first stream
    under a sensorId identically to it; every subsequent upload under the
    same sensorId becomes a distinct sub-stream (confirmed empirically —
    a second upload for sensorId=enc_a produced streamId
    enc_a_enc_a_<epoch>, not enc_a). So instead of guessing the streamId,
    use §3's `GET /storage/timelines` (all streams' recorded windows) and
    pick whichever stream both (a) belongs to this camera (streamId ==
    camera_id or prefixed with it — matches VIOS's own sub-stream naming)
    and (b) has a timeline overlapping the requested [t_start, t_end].
    """
    resp = requests.get(f"{VIOS_BASE}/storage/timelines", timeout=10)
    resp.raise_for_status()
    timelines = resp.json()
    if not isinstance(timelines, dict):
        return None

    candidates = {sid: windows for sid, windows in timelines.items() if sid == camera_id or sid.startswith(f"{camera_id}_")}
    for stream_id, windows in candidates.items():
        for window in windows:
            win_start = datetime.fromisoformat(window["startTime"].replace("Z", "+00:00")).timestamp()
            win_end = datetime.fromisoformat(window["endTime"].replace("Z", "+00:00")).timestamp()
            if win_start <= t_end and win_end >= t_start:
                return stream_id
    return None


def get_clip_url(stream_id: str, t_start: float, t_end: float) -> dict:
    """§4: GET /storage/file/<streamId>/url — preferred over streaming bytes
    through us; downstream (Cosmos) fetches straight from VIOS."""
    resp = requests.get(
        f"{VIOS_BASE}/storage/file/{stream_id}/url",
        params={
            "startTime": _iso(t_start),
            "endTime": _iso(t_end),
            "container": "mp4",
            "disableAudio": "true",
            "expiryMinutes": CLIP_URL_EXPIRY_MINUTES,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()

"""Ingest API — the missing "input a database of videos" front door.

The existing pipeline's video-ingest is a one-shot CLI job
(`docker compose run --rm -e DATASET_PATH=... video-ingest`), not an
HTTP service. This service gives the frontend something to call: it
lists a video library (a directory of demo footage, e.g. the ChimpACT
dataset) plus anything uploaded through the browser, accepts uploads,
transcodes non-H.264 sources (VIOS rejects mpeg4 etc. — see the build
log's bug #15), and drives `docker compose run video-ingest` for the
chosen file, tracking job status/logs so the UI can poll it.

Docker-outside-of-Docker note: this container talks to the *host's*
Docker daemon over the mounted socket. When it shells out to
`docker compose run`, the compose CLI resolves the `./data:/data:ro`
relative volume in docker-compose.yml against `--project-directory`
and hands the *resulting path string* to the daemon as a bind-mount
source. Since the daemon lives outside this container, that path only
works if it's a real path on the *host* — so PROJECT_DIR must be
bind-mounted into this container at the identical absolute path it has
on the host (see docker-compose.yml), not some arbitrary internal
path. That's why every path below is the shared host path, not a
container-local convenience path.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingest-api")

# Mirrored host path — see module docstring. Must match the host path
# used for this same directory in docker-compose.yml's video-ingest
# `./data:/data:ro` mount.
PROJECT_DIR = os.environ.get("PROJECT_DIR", "/home/acer01/primate-event-intelligence")
UPLOADS_DIR = os.path.join(PROJECT_DIR, "data", "uploads")
LIBRARY_DIR = os.environ.get("LIBRARY_DIR", "/library")
COMPOSE_SERVICE = os.environ.get("COMPOSE_SERVICE", "video-ingest")

VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".m4v")
CAMERA_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,48}$")

os.makedirs(UPLOADS_DIR, exist_ok=True)

app = FastAPI(title="Primate Event Intelligence — Ingest API")


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

class VideoEntry(BaseModel):
    video_id: str
    filename: str
    source: Literal["library", "upload"]
    size_bytes: int
    suggested_camera_id: str
    last_job_id: Optional[str] = None
    last_status: Optional[str] = None
    last_camera_id: Optional[str] = None


class IngestRequest(BaseModel):
    source: Literal["library", "upload"]
    filename: str
    camera_id: Optional[str] = None


JobStatus = Literal["queued", "transcoding", "ingesting", "succeeded", "failed"]


class Job(BaseModel):
    job_id: str
    video_id: str
    filename: str
    camera_id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    log: list[str] = []
    error: Optional[str] = None


# --------------------------------------------------------------------------
# In-memory job registry (single-process, fine for a local demo tool)
# --------------------------------------------------------------------------

_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def _touch(job: Job, **fields) -> None:
    with _jobs_lock:
        for k, v in fields.items():
            setattr(job, k, v)
        job.updated_at = datetime.now(timezone.utc)


def _log(job: Job, line: str) -> None:
    logger.info("[job %s] %s", job.job_id, line)
    with _jobs_lock:
        job.log.append(line)
        job.updated_at = datetime.now(timezone.utc)


def _latest_job_for(video_id: str) -> Optional[Job]:
    with _jobs_lock:
        candidates = [j for j in _jobs.values() if j.video_id == video_id]
    if not candidates:
        return None
    return max(candidates, key=lambda j: j.created_at)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _slugify(text: str, maxlen: int = 48) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", text).strip("_").lower()
    return (s or "camera")[:maxlen]


def _safe_basename(name: str) -> str:
    base = os.path.basename(name)
    if not base or base in (".", "..") or base != name.strip():
        raise HTTPException(status_code=400, detail="invalid filename")
    return base


def _dir_entries(directory: str, source: Literal["library", "upload"]) -> list[VideoEntry]:
    entries: list[VideoEntry] = []
    if not os.path.isdir(directory):
        return entries
    for name in sorted(os.listdir(directory)):
        if not name.lower().endswith(VIDEO_EXTS):
            continue
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        video_id = f"{source}:{name}"
        job = _latest_job_for(video_id)
        stem = os.path.splitext(name)[0]
        entries.append(
            VideoEntry(
                video_id=video_id,
                filename=name,
                source=source,
                size_bytes=os.path.getsize(path),
                suggested_camera_id=_slugify(stem),
                last_job_id=job.job_id if job else None,
                last_status=job.status if job else None,
                last_camera_id=job.camera_id if job else None,
            )
        )
    return entries


def _probe_codec(path: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return result.stdout.strip() or None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("ffprobe failed for %s: %s", path, e)
        return None


def _prepare_dataset_path(job: Job, source_path: str) -> str:
    """Returns the DATASET_PATH to hand to video-ingest (a path inside
    *its* container, which mounts UPLOADS_DIR's host dir at /data:ro).
    Transcodes to H.264 first if the source isn't already — VIOS
    rejects other codecs (build log bug #15)."""
    codec = _probe_codec(source_path)
    _log(job, f"probed codec: {codec or 'unknown'}")

    if codec == "h264":
        final_path = source_path
    else:
        stem = os.path.splitext(os.path.basename(source_path))[0]
        final_path = os.path.join(UPLOADS_DIR, f"{stem}_h264.mp4")
        if os.path.exists(final_path):
            _log(job, f"reusing existing transcode: {os.path.basename(final_path)}")
        else:
            _log(job, f"transcoding {codec or 'source'} -> h264 (this can take a while)...")
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", source_path, "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "23", "-c:a", "aac", "-movflags", "+faststart", final_path],
                capture_output=True, text=True, timeout=1800,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg transcode failed: {proc.stderr[-2000:]}")
            _log(job, f"transcode complete: {os.path.basename(final_path)}")

    if not final_path.startswith(UPLOADS_DIR):
        # Library sources live outside UPLOADS_DIR; video-ingest's container
        # only mounts the uploads host dir, so make sure the final file
        # (transcoded output) really landed there. Non-h264 branch above
        # already writes into UPLOADS_DIR; this only fires if a library
        # file was already h264 and thus used in place.
        stem = os.path.splitext(os.path.basename(source_path))[0]
        ext = os.path.splitext(source_path)[1]
        copied = os.path.join(UPLOADS_DIR, f"{stem}{ext}")
        if not os.path.exists(copied):
            _log(job, f"copying library source into uploads: {os.path.basename(copied)}")
            shutil.copyfile(source_path, copied)
        final_path = copied

    filename = os.path.basename(final_path)
    return f"/data/uploads/{filename}"


def _run_job(job_id: str, source_path: str) -> None:
    job = _jobs[job_id]
    try:
        _touch(job, status="transcoding")
        dataset_path = _prepare_dataset_path(job, source_path)

        _touch(job, status="ingesting")
        cmd = [
            "docker", "compose", "--project-directory", PROJECT_DIR,
            "run", "--rm",
            "-e", f"CAMERA_ID={job.camera_id}",
            "-e", f"DATASET_PATH={dataset_path}",
            COMPOSE_SERVICE,
        ]
        _log(job, f"$ {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd, cwd=PROJECT_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            _log(job, line.rstrip())
        returncode = proc.wait(timeout=1800)

        if returncode == 0:
            _touch(job, status="succeeded")
        else:
            _touch(job, status="failed", error=f"video-ingest exited with code {returncode}")
    except Exception as e:  # noqa: BLE001 - job runner must never raise into the thread pool
        logger.exception("job %s failed", job_id)
        _touch(job, status="failed", error=str(e))


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/videos", response_model=list[VideoEntry])
def list_videos():
    return _dir_entries(LIBRARY_DIR, "library") + _dir_entries(UPLOADS_DIR, "upload")


@app.post("/uploads", response_model=VideoEntry)
async def upload_video(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(VIDEO_EXTS):
        raise HTTPException(status_code=400, detail=f"unsupported file type, allowed: {VIDEO_EXTS}")

    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", os.path.basename(file.filename))
    stem, ext = os.path.splitext(safe_name)
    dest_name = safe_name
    n = 1
    while os.path.exists(os.path.join(UPLOADS_DIR, dest_name)):
        dest_name = f"{stem}_{n}{ext}"
        n += 1

    dest_path = os.path.join(UPLOADS_DIR, dest_name)
    with open(dest_path, "wb") as out:
        shutil.copyfileobj(file.file, out)
    logger.info("uploaded %s (%d bytes)", dest_name, os.path.getsize(dest_path))

    return VideoEntry(
        video_id=f"upload:{dest_name}",
        filename=dest_name,
        source="upload",
        size_bytes=os.path.getsize(dest_path),
        suggested_camera_id=_slugify(stem),
    )


@app.post("/ingest", response_model=Job)
def start_ingest(body: IngestRequest):
    filename = _safe_basename(body.filename)
    directory = LIBRARY_DIR if body.source == "library" else UPLOADS_DIR
    source_path = os.path.join(directory, filename)
    if not os.path.isfile(source_path):
        raise HTTPException(status_code=404, detail="video not found")

    camera_id = body.camera_id.strip() if body.camera_id else _slugify(os.path.splitext(filename)[0])
    if not CAMERA_ID_RE.match(camera_id):
        raise HTTPException(
            status_code=400,
            detail="camera_id must be 1-48 chars of letters, digits, '_' or '-'",
        )

    job_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc)
    job = Job(
        job_id=job_id,
        video_id=f"{body.source}:{filename}",
        filename=filename,
        camera_id=camera_id,
        status="queued",
        created_at=now,
        updated_at=now,
        log=[f"queued ingest for {body.source}:{filename} as camera_id={camera_id}"],
    )
    with _jobs_lock:
        _jobs[job_id] = job

    threading.Thread(target=_run_job, args=(job_id, source_path), daemon=True).start()
    return job


@app.get("/jobs", response_model=list[Job])
def list_jobs():
    with _jobs_lock:
        return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)


@app.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job

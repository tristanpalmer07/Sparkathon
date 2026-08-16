# Primate Event Intelligence

Full pipeline from the design doc, **every stage running the real
component** on this box:

**Chimp video → real AlphaChimp detection/tracking/behavior → nv.Frame
→ real VSS behavior-analytics (+ custom Event Evaluator) → real VIOS
clip retrieval → real Cosmos-Reason2-8B VLM → real Nemotron NIM
reasoning → Postgres `events` → Events API → Alerts.**

Verified end-to-end on 2026-08-16, including a full run over the
AlphaChimp repo's own real chimp demo footage.

## What's real

| Piece | Status |
|---|---|
| **AlphaChimp Inference** | **Real model, real checkpoint, real GPU inference.** DINO detector + SwinTransformer3D-Large backbone + ByteTrack, running the actual `alphachimp_res576.pth` checkpoint on this box's aarch64/GB10 hardware. See "Porting AlphaChimp to ARM64" below. |
| Event Evaluator | Real rule engine (§3.1), unit-tested, using the model's actual 24-class behavior taxonomy (`aggressing`, `resting`, `grooming`, `displaying`, ...). |
| AlphaChimp → nv.Frame Adapter | Real. Publishes genuine `nv.Frame` protobuf onto VSS's real `mdx-raw` topic — verified consumed live by a real `vss-behavior-analytics` instance. |
| Video Ingest / Clip Retrieval | Real VIOS integration — uploads via `PUT /storage/file/...`, resolves clip URLs via `GET /storage/timelines` + `GET /storage/file/<streamId>/url` (see streamId-resolution note below). |
| Cosmos VLM | Real `nvcr.io/nim/nvidia/cosmos-reason2-8b:1.6.0` NIM, port 8018. |
| Nemotron Triage | Real `nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark:1.0.0-variant` NIM, port 30081. |
| Event Writer | Real — writes every verdict to Postgres per the frozen `events` schema (§4.2). |
| Alerts | Real — consumes `nemotron-verdicts`, logs + optionally webhooks `report=true` high/medium-priority verdicts. |
| Events API | Real — FastAPI read/ack layer over `events` (§ "out of scope" in the original doc; built per follow-up request). |

## Verified end-to-end result (real chimp footage)

Ran `AlphaChimp/infer_input/demo.mp4` (the repo's own demo clip) through
Video Ingest → real AlphaChimp → Event Evaluator. The model detected
and tracked **5 chimps** with stable boxes and real behavior scores
(`resting` 0.90, `grooming` 0.96, `being groomed` 0.92, ...), and
`close_proximity` fired for real from genuine tracked positions:

```
event-evaluator: rule fired: close_proximity camera=enc_a tracks=[0, 3] conf=0.92 -> enc_a:1786848261
```

A separate run injecting a synthetic `aggressing=0.85` trigger onto
the same real footage's timeline shows the "VLM explains, LLM judges"
design principle (§1) working as intended — the model doesn't just
trust the trigger:

```
vlm_summary:     "...chimps are seen sitting and moving slightly on a rope
                  structure. No direct interaction or physical contact...
                  The group appears calm..."
nemotron_reason: "The VLM description indicates no visible aggression or
                  conflict, with chimps in a calm, relaxed state. The
                  sustained_aggression trigger was likely a false positive."
priority: low   report: false
```

`clip_reference` in that row is a genuine VIOS-served URL; downloading
and extracting a frame from it confirms it's the real footage (chimps
on a rope structure), not a filename coincidence.

## Porting AlphaChimp to ARM64/GB10

The original repo pins `torch==1.9.1+cu111` — x86_64-only wheels, never
built for ARM64, and incompatible with this box's CUDA 13/Blackwell
GPU regardless. `services/alphachimp/Dockerfile.pytorch` instead:

1. Builds on `nvcr.io/nvidia/pytorch:25.09-py3` (NVIDIA's own PyTorch
   NGC image — torch 2.9, tested against this exact GPU: `get_device_capability()` → `(12, 1)`).
2. Compiles `mmcv` (the only dependency with compiled CUDA ops — the
   vendored mmdet/mmtracking/mmaction fork itself has none) from
   source against that torch build. **`FORCE_CUDA=1` is load-bearing**:
   `docker build` has no GPU visible, so mmcv's setup.py — which gates
   CUDA-extension compilation behind `torch.cuda.is_available()`, not
   just `MMCV_WITH_OPS` — silently builds CPU-only ops without it
   (symptom: `ms_deform_attn_impl_forward: implementation for device
   cuda:0 not found` at inference time, no build-time error).
3. Skips `decord` (no aarch64 wheels on PyPI at all) — it's only used
   by a video-reading transform (`DecordInit`/`DecordDecode`) our
   pipeline never calls, since we feed pre-extracted JPG frames through
   `RawFrameDecode` instead.
4. `services/alphachimp/backend.py`'s `PyTorchBackend` reimplements
   `tools/inference.py`'s `build_model → load_checkpoint → model.eval()`
   flow as a proper class (per design doc §5.1), adapted for per-window
   HTTP requests instead of whole-video batch jobs — see its docstring
   for how it keeps ByteTrack identity continuous across window
   boundaries despite each window's frame timestamps restarting at 0.

The checkpoint (`Desktop/big-files/alphachimp_res576.pth`, 1.3GB) is
mounted read-only into the container, not baked into the image.

## VIOS streamId gotcha

`streamId` does **not** reliably equal `sensorId` for file-uploaded
sensors: VIOS only names the *first* upload under a sensorId
identically to it (`enc_a` → `enc_a`); every subsequent upload under
the same sensorId becomes a distinct sub-stream with a synthesized ID
(`enc_a` → `enc_a_enc_a_1786848261`). `shared/vios_client.py`'s
`find_stream_id()` resolves this correctly by querying
`GET /storage/timelines` and matching on both camera-id prefix and
actual timeline overlap with the requested window, rather than
assuming equivalence.

## What's actually running on this box

Same as before — cherry-picked out of VSS's real compose graph rather
than a full profile deploy (see prior notes on GPU/memory constraints):
VIOS, VSS's real Kafka, the two standalone NIMs (each capped at
`NIM_KVCACHE_PERCENT=0.22` so they share the GB10's 121 GB unified
memory with AlphaChimp instead of each reserving 40%),
`vss-behavior-analytics-base`, plus this repo's own services — now
including AlphaChimp itself as a GPU consumer alongside the two NIMs.

## Running standalone (no VSS, no GPU)

`MODEL_BACKEND=stub` (motion-blob detection + tracking, synthetic
behavior scores) still works for local development without a GPU —
see `services/alphachimp/backend.py`'s `StubBackend`. `cosmos-vlm`/
`nemotron-triage` fall back to deterministic stub logic when
`COSMOS_NIM_URL`/`NEMOTRON_NIM_URL` are unset.

```bash
docker compose up -d postgres
docker compose run --rm kafka-topics-init
docker compose up -d event-evaluator nvframe-adapter cosmos-vlm nemotron-triage event-writer alerts events-api
docker compose run --rm -e SEGMENT_START=$(date +%s) -e TRACK_ID=1 test-client python inject_synthetic_burst.py
curl http://localhost:8001/events
```

## Kafka topics

Ours: `alphachimp-events`, `candidate-clips`, `clip-ready`,
`vlm-descriptions`, `nemotron-verdicts` (schemas in `shared/schemas.py`,
frozen per design doc §4.1/§4.2), bootstrapped by `scripts/init_topics.py`.

VSS-native: `mdx-raw` (written by `nvframe-adapter`, consumed live by
`vss-behavior-analytics-base`).

## Events API

```
GET  /events?priority=&status=&category=&camera_id=&limit=&offset=
GET  /events/{event_id}
PATCH /events/{event_id}   {"status": "acknowledged" | "dismissed" | "new"}
GET  /stats                 -- counts grouped by (priority, status)
GET  /health
```
Port 8001.

## Alerts

Consumes `nemotron-verdicts`; logs (and optionally POSTs to
`ALERT_WEBHOOK_URL`, unset by default) every `report=true` verdict at
`priority in {high, medium}`. `low`-priority verdicts still land in
Postgres via Event Writer — they're just not paged.

## Frontend

A containerized React/Vite dashboard (`services/frontend`) plus a new
`services/ingest-api` backend that gives the previously CLI-only
`video-ingest` job an HTTP front door — port 3000.

- **Flagged Events tab**: filterable/searchable table over the Events
  API (priority, status, category, camera), stats bar, and a detail
  drawer per event with inline clip playback (`clip_reference` is a
  real VIOS-served URL) plus VLM description, Nemotron reasoning, and
  Acknowledge/Dismiss controls.
- **Videos tab**: browse the bundled ChimpACT demo library (mounted
  read-only from `Desktop/big-files/ChimpACT_release_v1/videos_full`)
  or upload your own file; assign a `camera_id` and click Ingest.
  `ingest-api` transcodes non-H.264 sources automatically (the
  ChimpACT files are `mpeg4` — see bug #15) and drives
  `docker compose run video-ingest` over the mounted host Docker
  socket, with a live job log per run.

```bash
docker compose build ingest-api frontend
docker compose up -d ingest-api frontend
open http://localhost:3000
```

`ingest-api` (port 8002) needs `/var/run/docker.sock` and this
project directory bind-mounted at its own identical host path — see
`services/ingest-api/main.py`'s module docstring for why (docker-
outside-of-docker path resolution).

## Known gaps

- `vss-behavior-analytics-base`'s 0-incident output is by design — its
  native incident types (proximity/restrictedArea/confinedArea) don't
  cover "sustained behavior-class confidence," which is why the custom
  Event Evaluator exists per §6's original design call. It IS
  genuinely consuming our real detections (confirmed via its logs
  referencing `sensor enc_a`).
- The demo footage used for validation doesn't contain a genuinely
  aggressive incident, so the alerts path's `report=true` branch is
  exercised by unit-level reasoning (Nemotron correctly downgrading a
  synthetic false trigger) rather than a real high-priority alert
  firing end-to-end. The mechanism itself (`services/alerts/main.py`)
  is simple and was verified to correctly filter on priority.
- Track-ID continuity across AlphaChimp inference windows is
  best-effort (see `PyTorchBackend`'s docstring) — sound for a
  microservice adaptation of a whole-video-batch model, not identical
  to running the model on a continuous stream.

## Tests

```bash
python3 -m pytest services/event-evaluator/tests/ services/nvframe-adapter/tests/ -q
```

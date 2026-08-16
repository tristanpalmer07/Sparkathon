"""Pluggable inference backend for the AlphaChimp service.

StubBackend does real motion-based blob detection + a naive centroid
tracker so bbox/track_id continuity is genuine, but behavior scores
are synthetic noise — there's no substitute for the actual model
weights. Swap in PyTorchBackend (§5.1 of the design doc) once the
vendored AlphaChimp repo (mmdet/mmtracking/mmaction fork) is available
in this image; nothing outside this file needs to change; the FastAPI
route and the alphachimp-events schema stay identical either way.
"""
from __future__ import annotations

import base64
import os
import random
from dataclasses import dataclass, field

import cv2
import numpy as np

from infer_policy import keep_only_center, place_at_center

BEHAVIOR_LABELS = ["aggression", "feeding", "sitting", "pacing", "self_directed"]


@dataclass
class Detection:
    track_id: int
    bbox: tuple[float, float, float, float]
    det_conf: float
    behaviors: dict[str, float]


def decode_frame(jpeg_b64: str) -> np.ndarray:
    raw = base64.b64decode(jpeg_b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


class _CentroidTracker:
    """Nearest-centroid tracker, good enough to give the stub backend
    stable track_ids across a frame window without pulling in a real
    tracking model."""

    def __init__(self, max_distance_px: float = 80.0, max_misses: int = 5):
        self.max_distance_px = max_distance_px
        self.max_misses = max_misses
        self._next_id = 1
        self._tracks: dict[int, dict] = {}  # id -> {centroid, misses}

    def update(self, centroids: list[tuple[float, float]]) -> list[int]:
        assigned: list[int | None] = [None] * len(centroids)
        used_tracks: set[int] = set()

        for i, c in enumerate(centroids):
            best_id, best_dist = None, self.max_distance_px
            for tid, t in self._tracks.items():
                if tid in used_tracks:
                    continue
                d = float(np.hypot(c[0] - t["centroid"][0], c[1] - t["centroid"][1]))
                if d < best_dist:
                    best_id, best_dist = tid, d
            if best_id is not None:
                assigned[i] = best_id
                used_tracks.add(best_id)
                self._tracks[best_id] = {"centroid": c, "misses": 0}

        for i, c in enumerate(centroids):
            if assigned[i] is None:
                tid = self._next_id
                self._next_id += 1
                self._tracks[tid] = {"centroid": c, "misses": 0}
                assigned[i] = tid

        for tid in list(self._tracks):
            if tid not in used_tracks and tid not in assigned:
                self._tracks[tid]["misses"] += 1
                if self._tracks[tid]["misses"] > self.max_misses:
                    del self._tracks[tid]

        return assigned  # type: ignore[return-value]


class StubBackend:
    """Real motion-blob detection + tracking; synthetic behavior scores."""

    def __init__(self):
        self._trackers_by_camera: dict[str, _CentroidTracker] = {}
        self._bgsub_by_camera: dict[str, cv2.BackgroundSubtractorMOG2] = {}
        self._rng = random.Random(42)

    def _tracker(self, camera_id: str) -> _CentroidTracker:
        return self._trackers_by_camera.setdefault(camera_id, _CentroidTracker())

    def _bgsub(self, camera_id: str):
        return self._bgsub_by_camera.setdefault(
            camera_id, cv2.createBackgroundSubtractorMOG2(history=50, varThreshold=25, detectShadows=False)
        )

    def infer_window(self, camera_id: str, frames: list[np.ndarray]) -> list[list[Detection]]:
        """Returns, per frame, the list of Detections found in that frame."""
        bgsub = self._bgsub(camera_id)
        tracker = self._tracker(camera_id)
        results: list[list[Detection]] = []

        for frame in frames:
            fg = bgsub.apply(frame)
            _, fg = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)
            fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
            contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            boxes = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) > 300]
            centroids = [(x + w / 2.0, y + h / 2.0) for x, y, w, h in boxes]
            track_ids = tracker.update(centroids)

            frame_dets: list[Detection] = []
            for (x, y, w, h), tid in zip(boxes, track_ids):
                behaviors = {label: round(self._rng.uniform(0.0, 0.3), 3) for label in BEHAVIOR_LABELS}
                frame_dets.append(
                    Detection(
                        track_id=tid,
                        bbox=(float(x), float(y), float(w), float(h)),
                        det_conf=round(min(0.99, 0.5 + w * h / (frame.shape[0] * frame.shape[1])), 3),
                        behaviors=behaviors,
                    )
                )
            results.append(frame_dets)
        return results


# The model's real 24-class multi-label behavior taxonomy (order matches
# bbox_head.num_classes=24 in configs/alphachimp/alphachimp_infer256.py and
# the label list tools/inference.py's draw_vis_* functions use).
ACTION_CLASS_NAMES = [
    "other", "moving", "climbing", "resting", "sleeping",
    "solitary object playing", "eating", "manipulating object",
    "grooming", "being groomed", "aggressing", "embracing", "begging",
    "being begged from", "taking object", "losing object", "carrying",
    "being carried", "nursing", "being nursed", "playing", "touching",
    "erection", "displaying",
]


class PyTorchBackend:
    """Runs the real AlphaChimp checkpoint (build_model -> load_checkpoint
    -> model.eval(), per design doc §5.1) using the vendored mmdet/
    mmtracking/mmaction fork under AlphaChimp/.

    §5.1's original CUDA 11.1 / torch==1.9.1+cu111 image is unusable on
    this box: that combo only ever shipped x86_64 wheels, and this is
    aarch64 (DGX Spark / GB10). Dockerfile.pytorch instead builds on
    NVIDIA's own PyTorch NGC image (torch 2.9, CUDA 13, tested against
    this exact GPU) and compiles mmcv's ops from source against it — the
    vendored fork has no custom compiled CUDA kernels of its own, so this
    is a straight rebuild, not a port of any model code.

    Per-window HTTP requests vs. this repo's whole-video assumption: the
    dataset's frame timestamps always start at 0 per call (see
    ChimpDataset_Infer.load_data_list), and the tracker auto-resets its
    track table whenever it sees timestamp 0 (byte_tracker_chimp.py's
    track()). Left alone, every window would look like "a new video" and
    reset tracking. We keep one tracker instance + one running frame
    counter per camera_id, and overwrite each detection's timestamp with
    that continuous counter before handing it to the tracker, so track
    identity survives across window boundaries the way it would across
    frames of one continuously-processed video.
    """

    def __init__(self, checkpoint_path: str, config_path: str):
        import torch
        from mmengine.config import Config
        from mmaction.registry import MODELS

        # Import side effects register every `mmdet.*`/`mmaction.*` type
        # string used in the config (DINO, SwinTransformer3D, ByteTrackChimp,
        # ...) into mmengine's registry — nothing above imports these
        # directly, so without this the config fails to resolve.
        import mmdet.models  # noqa: F401
        import mmaction.models  # noqa: F401
        import mmaction.datasets  # noqa: F401

        self._torch = torch
        self._Config = Config
        self._MODELS = MODELS

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.cfg = Config.fromfile(config_path)

        model = MODELS.build(self.cfg.model)
        # weights_only=True (torch>=2.6 default) rejects this checkpoint's
        # embedded mmengine training metadata (HistoryBuffer etc.) even
        # though we only ever read ckpt['state_dict']; safe to disable
        # here since the checkpoint is the paper authors' own release.
        ckpt = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        model.detector.load_state_dict(ckpt["state_dict"], strict=True)
        model.eval()
        self.model = model.to(self.device)

        self._trackers: dict[str, object] = {}
        self._frame_counters: dict[str, int] = {}

    def _tracker_for(self, camera_id: str):
        if camera_id not in self._trackers:
            self._trackers[camera_id] = self._MODELS.build(self.cfg.model.tracker)
            self._frame_counters[camera_id] = 0
        return self._trackers[camera_id]

    def infer_window(self, camera_id: str, frames: list[np.ndarray]) -> list[list[Detection]]:
        import copy
        import json
        import tempfile
        from pathlib import Path

        from mmaction.registry import DATASETS
        from mmengine.dataset import pseudo_collate
        from torch.utils.data import DataLoader

        if not frames:
            return []

        tracker = self._tracker_for(camera_id)
        self.model.tracker = tracker
        start_frame = self._frame_counters[camera_id]

        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            img_dir_name = "clip"
            img_dir = tmp / img_dir_name
            img_dir.mkdir()
            for i, frame in enumerate(frames):
                cv2.imwrite(str(img_dir / f"{i:06d}.jpg"), frame)

            ann_path = tmp / "ann.json"
            ann_path.write_text(json.dumps([{"video_name": img_dir_name, "frame_len": len(frames)}]))

            dataset_cfg = copy.deepcopy(self.cfg.val_dataloader.dataset)
            dataset_cfg["ann_file"] = str(ann_path)
            dataset_cfg["exclude_file"] = None
            dataset_cfg["proposal_file"] = None
            dataset_cfg["data_prefix"] = dict(img=str(tmp))
            dataset_cfg["test_mode"] = True
            dataset = DATASETS.build(dataset_cfg)
            # One detector forward on the center timestamp. Neighbor
            # JPGs stay on disk so SampleAVAFrames can still build its
            # 8-frame temporal clip.
            dataset.data_list = keep_only_center(dataset.data_list, len(frames))

            loader = DataLoader(
                dataset,
                batch_size=1,
                shuffle=False,
                num_workers=0,
                collate_fn=pseudo_collate,
            )

            center_dets: list[Detection] = []
            with self._torch.no_grad():
                for data_batch in loader:
                    data = self.model.data_preprocessor(data_batch, training=False)
                    det_results = self.model.detector.predict(data["inputs"]["imgs"], data["data_samples"])
                    for det in det_results:
                        local_frame_id = int(det.metainfo["timestamp"])
                        # continuous per-camera counter so the tracker never
                        # sees timestamp 0 again after this camera's first
                        # window — see class docstring.
                        det.set_metainfo({"timestamp": start_frame + local_frame_id})

                        tracked = tracker.track(det)
                        center_dets = self._to_detections(tracked)

            self._frame_counters[camera_id] = start_frame + len(frames)

        return place_at_center(len(frames), center_dets)

    def _to_detections(self, tracked) -> list[Detection]:
        # byte_tracker_chimp.py's track() returns an InstanceData whose
        # `.labels` field is the full 24-dim multi-label action vector
        # (it reassigns the detector's original binary `labels` to
        # all-ones internally for IoU matching and outputs the saved
        # `act_labels` under this field name instead — confirmed by
        # reading its `pred_track_instances.labels = act_labels` line).
        bboxes = tracked.bboxes.detach().cpu().numpy()
        action_probs = tracked.labels.detach().cpu().numpy()
        scores = tracked.scores.detach().cpu().numpy()
        track_ids = tracked.instances_id.detach().cpu().numpy()

        detections = []
        for i, bbox in enumerate(bboxes):
            x1, y1, x2, y2 = bbox[:4]
            behaviors = {name: float(action_probs[i][j]) for j, name in enumerate(ACTION_CLASS_NAMES)}
            detections.append(
                Detection(
                    track_id=int(track_ids[i]),
                    bbox=(float(x1), float(y1), float(x2 - x1), float(y2 - y1)),
                    det_conf=float(scores[i]),
                    behaviors=behaviors,
                )
            )
        return detections


def get_backend():
    backend = os.environ.get("MODEL_BACKEND", "stub")
    if backend == "stub":
        return StubBackend()
    if backend == "pytorch":
        return PyTorchBackend(
            checkpoint_path=os.environ["ALPHACHIMP_CHECKPOINT"],
            config_path=os.environ["ALPHACHIMP_CONFIG"],
        )
    raise ValueError(f"unknown MODEL_BACKEND: {backend}")

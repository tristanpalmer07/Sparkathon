import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from infer_policy import center_index, keep_only_center, place_at_center  # noqa: E402


def test_center_index_is_middle_frame():
    assert center_index(1) == 0
    assert center_index(12) == 6
    assert center_index(8) == 4


def test_keep_only_center_drops_other_dataset_items():
    items = [{"timestamp": i} for i in range(12)]
    assert keep_only_center(items, 12) == [{"timestamp": 6}]


def test_place_at_center_leaves_other_frames_empty():
    dets = ["center-only"]
    placed = place_at_center(12, dets)
    assert len(placed) == 12
    assert placed[6] == dets
    assert all(placed[i] == [] for i in range(12) if i != 6)

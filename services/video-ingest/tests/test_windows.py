import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from windows import WindowWalker  # noqa: E402


def _walk(n_frames: int, window: int, stride: int) -> list[list[int]]:
    walker = WindowWalker(window=window, stride=stride)
    posted: list[list[int]] = []
    for i in range(n_frames):
        window_frames = walker.push(i)
        if window_frames is not None:
            posted.append(window_frames)
    leftover = walker.flush()
    if leftover is not None:
        posted.append(leftover)
    return posted


def test_stride_smaller_than_window_keeps_overlap():
    posted = _walk(n_frames=20, window=12, stride=6)
    assert posted == [
        list(range(0, 12)),
        list(range(6, 18)),
        list(range(12, 20)),
    ]


def test_stride_equal_to_window_is_adjacent():
    posted = _walk(n_frames=36, window=12, stride=12)
    assert posted == [
        list(range(0, 12)),
        list(range(12, 24)),
        list(range(24, 36)),
    ]


def test_stride_larger_than_window_skips_frames_between_windows():
    posted = _walk(n_frames=40, window=12, stride=24)
    assert posted == [
        list(range(0, 12)),
        list(range(24, 36)),
    ]


def test_stride_larger_than_window_flushes_partial_after_skip():
    posted = _walk(n_frames=30, window=12, stride=24)
    assert posted == [
        list(range(0, 12)),
        list(range(24, 30)),
    ]


def test_window_of_one_posts_single_frames_and_skips():
    posted = _walk(n_frames=50, window=1, stride=24)
    assert posted == [[0], [24], [48]]

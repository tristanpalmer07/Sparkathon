"""Sliding-window walk over a frame stream.

`stride < window` keeps overlap. `stride >= window` skips the frames
between the end of one window and the start of the next, so a stride
larger than the model window actually reduces how many inferences run.
"""
from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class WindowWalker(Generic[T]):
    def __init__(self, window: int, stride: int):
        if window < 1:
            raise ValueError(f"window must be >= 1, got {window}")
        if stride < 1:
            raise ValueError(f"stride must be >= 1, got {stride}")
        self.window = window
        self.stride = stride
        self._buffer: list[T] = []
        self._skip = 0

    @property
    def skipping(self) -> bool:
        return self._skip > 0

    def push(self, frame: T) -> list[T] | None:
        if self._skip > 0:
            self._skip -= 1
            return None
        self._buffer.append(frame)
        if len(self._buffer) < self.window:
            return None
        posted = self._buffer[: self.window]
        if self.stride < self.window:
            self._buffer = self._buffer[self.stride :]
        else:
            self._buffer = []
            self._skip = self.stride - self.window
        return posted

    def flush(self) -> list[T] | None:
        if not self._buffer:
            return None
        leftover = self._buffer
        self._buffer = []
        return leftover

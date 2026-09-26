"""Bounded byte/LF JSONL decoder for native subprocess stdout."""

from __future__ import annotations

from typing import Any

from ..protocol import strict_json

MAX_NATIVE_FRAME_BYTES = 1024 * 1024
MAX_RECORDS_PER_FEED = 1024


class JSONLDecoder:
    def __init__(self, *, max_frame_bytes: int = MAX_NATIVE_FRAME_BYTES):
        if (type(max_frame_bytes) is not int or
                not 0 < max_frame_bytes <= MAX_NATIVE_FRAME_BYTES):
            raise ValueError("invalid native frame byte limit")
        self.max_frame_bytes = max_frame_bytes
        self._buffer = bytearray()
        self._closed = False

    def feed(self, chunk: bytes) -> list[Any]:
        if self._closed:
            raise RuntimeError("decoder closed")
        if type(chunk) is not bytes:
            raise TypeError("native chunk must be bytes")
        # Callers must split larger reads. Otherwise a single feed can build
        # an unbounded returned list despite every individual frame fitting.
        if len(chunk) > self.max_frame_bytes:
            self._closed = True
            raise ValueError("native chunk exceeds byte limit")
        records: list[Any] = []
        start = 0
        for index, byte in enumerate(chunk):
            if byte != 10:  # Only LF is a frame delimiter.
                continue
            if len(records) >= MAX_RECORDS_PER_FEED:
                self._closed = True
                raise ValueError("native chunk exceeds record limit")
            self._buffer.extend(chunk[start:index])
            if len(self._buffer) > self.max_frame_bytes:
                self._closed = True
                raise ValueError("native frame exceeds byte limit")
            frame = bytes(self._buffer)
            self._buffer.clear()
            if frame.endswith(b"\r"):
                frame = frame[:-1]
            if not frame:
                self._closed = True
                raise ValueError("empty native frame")
            try:
                records.append(strict_json(frame.decode("utf-8", errors="strict")))
            except (UnicodeError, ValueError, RecursionError):
                self._closed = True
                raise
            start = index + 1
        self._buffer.extend(chunk[start:])
        if len(self._buffer) > self.max_frame_bytes:
            self._closed = True
            raise ValueError("native frame exceeds byte limit")
        return records

    def finish(self) -> None:
        self._closed = True
        if self._buffer:
            raise ValueError("incomplete native frame")

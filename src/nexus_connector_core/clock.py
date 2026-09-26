"""Default host clock; tests can inject a deterministic monotonic clock."""

from __future__ import annotations

import time
import math
import threading

from .ports import Clock


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def wall_time(self) -> float:
        return time.time()


class RollbackFencedClock:
    """Fail closed if a monotonic source regresses within this process.

    Returning infinity makes existing deadline comparisons expire rather than
    granting extra lease time. The fence is sticky: a later clock recovery
    cannot revive a lease whose timing evidence became untrustworthy.
    """

    def __init__(self, source: Clock) -> None:
        self._source = source
        self._lock = threading.Lock()
        self._last: float | None = None
        self._invalid = False

    def monotonic(self) -> float:
        with self._lock:
            if self._invalid:
                return math.inf
            now = self._source.monotonic()
            if not math.isfinite(now) or (self._last is not None and now < self._last):
                self._invalid = True
                return math.inf
            self._last = now
            return now

    def wall_time(self) -> float:
        return self._source.wall_time()

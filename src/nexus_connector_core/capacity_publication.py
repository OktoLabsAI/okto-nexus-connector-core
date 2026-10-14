"""Bounded change/refresh publication shared by local and remote host owners.

The host supplies authenticated binding IDs and a durable change cursor. No
session readiness is inferred here. Observations are hints to reassess, never
permission to claim or execute. One retained producer serves the whole owner;
slow observation or output cannot create tasks per binding or block dispatch.
"""
import asyncio
import math
import time

from .capacity import CAPACITY_REASONS


class CapacityChangePublisher:
    def __init__(self, *, boot_id, snapshot, emit, clock=time.monotonic,
                 page_size=32, max_bindings=256, poll_seconds=.5,
                 refresh_seconds=10, valid_for_ms=30000):
        if (not isinstance(boot_id, str) or not 0 < len(boot_id) <= 256
                or any(type(n) is not int or n <= 0 for n in (page_size, max_bindings))
                or page_size > max_bindings
                or not all(math.isfinite(n) and n > 0 for n in (poll_seconds, refresh_seconds))
                or type(valid_for_ms) is not int or not 100 <= valid_for_ms <= 60000
                or refresh_seconds >= valid_for_ms / 1000):
            raise ValueError('Invalid capacity publication settings.')
        self.boot_id, self.snapshot, self.emit, self.clock = boot_id, snapshot, emit, clock
        self.page_size, self.max_bindings = page_size, max_bindings
        self.poll_seconds, self.refresh_seconds, self.valid_for_ms = poll_seconds, refresh_seconds, valid_for_ms
        self._sent = {}
        self._task = None
        self._next_poll = 0
        self._closed = False
        self.last_error = None

    def tick(self):
        """Called by existing host maintenance; never waits for provider I/O."""
        if self._closed or self.clock() < self._next_poll or self._task is not None and not self._task.done():
            return
        self._next_poll = self.clock() + self.poll_seconds
        self._task = asyncio.create_task(self._publish(), name='capacity-observations')

    async def _publish(self):
        try:
            revision, bindings = await self.snapshot()
            if (type(revision) is not int or revision < 0 or not isinstance(bindings, dict)
                    or len(bindings) > self.max_bindings
                    or any(not isinstance(k, str) or not 0 < len(k) <= 256 or v not in CAPACITY_REASONS
                           for k, v in bindings.items())):
                raise ValueError('Invalid capacity publication snapshot.')
            self._sent = {k: v for k, v in self._sent.items() if k in bindings}
            now = self.clock()
            due = [k for k, reason in bindings.items() if k not in self._sent
                   or self._sent[k][:2] != (revision, reason)
                   or now - self._sent[k][2] >= self.refresh_seconds]
            # Oldest first also drains every binding under continuous changes;
            # restarting from the first sorted ID on each revision would starve.
            due.sort(key=lambda k: (self._sent.get(k, (0, '', float('-inf')))[2], k))
            for binding_id in due[:self.page_size]:
                if self._closed:
                    return
                reason = bindings[binding_id]
                await self.emit(binding_id=binding_id, boot_id=self.boot_id,
                    revision=revision, reason=reason, valid_for_ms=self.valid_for_ms)
                self._sent[binding_id] = (revision, reason, self.clock())
            self.last_error = None
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # A failed observation is allowed to expire. It cannot take down
            # healthy productive lanes or be reported as fresh availability.
            self.last_error = type(error).__name__

    async def aclose(self):
        self._closed = True
        if self._task is not None:
            await asyncio.shield(self._task)

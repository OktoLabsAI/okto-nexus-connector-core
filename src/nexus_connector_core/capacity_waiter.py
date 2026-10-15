"""One bounded change observer for all deferred productive calls of an owner."""
import asyncio
import time


class CapacityRetryWaiter:
    def __init__(self, read_revision, *, max_waiters=64, poll_seconds=.1, recheck_seconds=2):
        if (type(max_waiters) is not int or max_waiters <= 0 or poll_seconds <= 0
                or recheck_seconds < poll_seconds):
            raise ValueError('Invalid capacity waiter settings.')
        self.read_revision = read_revision
        self.max_waiters, self.poll_seconds, self.recheck_seconds = max_waiters, poll_seconds, recheck_seconds
        # asyncio may dispatch timers up to one clock tick early. On Windows
        # Python 3.11 that tick can exceed a short poll interval, making every
        # timeout immediately ready and turning the observer into a busy loop.
        self._poll_timeout = max(poll_seconds, 2 * time.get_clock_info('monotonic').resolution)
        self.version = 0
        self.closed = False
        self._waiters = set()
        self._monitor = None
        self._stop = asyncio.Event()
        self._revision = None
        self._observed_at = 0

    async def wait(self, version):
        if self.closed:
            return False
        if self.version != version:
            return True
        if len(self._waiters) >= self.max_waiters:
            raise RuntimeError('Capacity wait budget exhausted.')
        future = asyncio.get_running_loop().create_future()
        self._waiters.add(future)
        if self._monitor is None or self._monitor.done():
            self._monitor = asyncio.create_task(self._observe(), name='capacity-wait-observer')
        try:
            return await future
        finally:
            self._waiters.discard(future)

    def _wake(self, allowed=True):
        self.version += 1
        for future in tuple(self._waiters):
            if not future.done():
                future.set_result(allowed)

    async def _observe(self):
        while self._waiters and not self.closed:
            try:
                revision = await self.read_revision()
            except Exception:
                # Revalidate through the real admission path; never infer a
                # vacancy from missing observation or suppress a storage fault.
                self._wake()
                return
            now = time.monotonic()
            if revision != self._revision or now - self._observed_at >= self.recheck_seconds:
                self._revision, self._observed_at = revision, now
                self._wake()
            try:
                await asyncio.wait_for(self._stop.wait(), self._poll_timeout)
            except TimeoutError:
                pass

    def stop(self):
        self.closed = True
        self._stop.set()
        self._wake(False)

    async def aclose(self):
        self.stop()
        if self._monitor is not None:
            await asyncio.shield(self._monitor)

"""Single-threaded off-loop executor for blocking storage I/O (C1/PC01).

One dedicated worker thread owns a resource (for example a SQLite
connection) for its whole lifetime. Callers submit complete units of work;
the worker executes each unit start-to-finish with exclusive resource
ownership, then delivers the result to the caller's event loop via
``call_soon_threadsafe``. This module never uses ``check_same_thread=False``
and never shares the resource between threads.

Queueing discipline:

- Two bounded queues: *urgent* (reserved capacity for critical controls)
  and *normal*. The worker drains urgent first; a running unit is never
  preempted.
- Submission is bounded by item count and by a pending-payload byte
  budget. Saturation *before* enqueue raises :class:`ExecutorFull` (the
  caller maps it to a typed backpressure error before any effect);
  saturation *after* enqueue is impossible for the caller to observe
  except as a slower completion, and the work still completes.
- Cancellation of the awaiting task does not cancel an enqueued or
  running unit: the durable result is delivered to the store and remains
  queryable; a cancelled future simply drops the return value without
  raising ``InvalidStateError``.

Shutdown is explicit: :meth:`aclose` (from a running loop) or
:meth:`close` (bridge). A close timeout never declares the worker
stopped without proof; it raises instead.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from typing import Any, Callable, Optional

__all__ = ["OffLoopExecutor", "ExecutorFull", "ExecutorClosed"]


class ExecutorFull(Exception):
    """Backpressure: the bounded queue or byte budget rejected the work."""

    def __init__(self, *, urgent: bool, bytes_pending: int):
        super().__init__(
            f"off-loop executor {'urgent' if urgent else 'normal'} queue is full "
            f"(bytes pending: {bytes_pending})")
        self.urgent = urgent
        self.bytes_pending = bytes_pending


class ExecutorClosed(RuntimeError):
    """The executor worker has stopped; no new work is accepted."""


_WORK = Callable[[Any], Any]


class OffLoopExecutor:
    def __init__(self, *, name: str = "core-offloop",
                 normal_capacity: int = 256, urgent_capacity: int = 64,
                 max_pending_bytes: int = 8 * 1024 * 1024,
                 idle_poll_seconds: float = 0.002) -> None:
        if (type(normal_capacity) is not int or
                type(urgent_capacity) is not int or
                not 1 <= normal_capacity or not 1 <= urgent_capacity or
                type(max_pending_bytes) is not int or
                not 1 <= max_pending_bytes):
            raise ValueError("invalid executor capacities")
        self._name = name
        self._normal: "queue.Queue[tuple]" = queue.Queue(maxsize=normal_capacity)
        self._urgent: "queue.Queue[tuple]" = queue.Queue(maxsize=urgent_capacity)
        # C2/R05: coalesced wake notification. Producers raise ONE shared
        # pending flag and notify a Condition while holding its lock; the
        # worker consumes the flag before re-checking both queues. The
        # backlog is therefore bounded (<= 1 signal regardless of total
        # work) and the enqueue/sleep race is closed: state check and wait
        # happen under the same lock as the producer's notify.
        self._cond = threading.Condition()
        self._work_pending = False
        self._max_pending_bytes = max_pending_bytes
        self._idle_poll_seconds = idle_poll_seconds
        self._bytes_lock = threading.Lock()
        self._bytes_pending = 0
        self._stop = threading.Event()
        self._started = threading.Event()
        self._finished = threading.Event()
        self._worker: threading.Thread | None = None
        self._resource: Any = None
        self._setup_error: BaseException | None = None
        self._loop_ref: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self, setup: Callable[[], Any]) -> None:
        """Open the worker and run ``setup`` on it; blocks until ready.

        The resource returned by ``setup`` is passed to every unit of work.
        A setup failure closes the worker and re-raises here.
        """
        if self._worker is not None:
            raise RuntimeError("executor already started")
        self._worker = threading.Thread(
            target=self._run, args=(setup,), name=self._name, daemon=True)
        self._worker.start()
        self._started.wait()
        if self._setup_error is not None:
            self._finished.wait(timeout=5)
            raise self._setup_error

    def _run(self, setup: Callable[[], Any]) -> None:
        try:
            self._resource = setup()
        except BaseException as exc:  # noqa: BLE001 - reported to starter
            self._setup_error = exc
            self._started.set()
            self._finished.set()
            return
        self._started.set()
        try:
            while not self._stop.is_set():
                item = self._next_item()
                if item is None:
                    continue
                self._execute(item)
            # Drain whatever was already accepted before the stop signal.
            while True:
                item = self._next_item(drain=True)
                if item is None:
                    break
                self._execute(item)
        finally:
            teardown = getattr(self._resource, "close", None)
            if callable(teardown):
                try:
                    teardown()
                except Exception:  # noqa: BLE001 - closing best effort
                    pass
            self._finished.set()

    def _next_item(self, *, drain: bool = False):
        while True:
            try:
                return self._urgent.get_nowait()
            except queue.Empty:
                pass
            try:
                return self._normal.get_nowait()
            except queue.Empty:
                pass
            if drain or self._stop.is_set():
                return None
            # Spend the coalesced wake (at most one signal outstanding) and
            # re-check both queues; otherwise sleep until a producer or the
            # stop signal notifies under the same lock - no lost wakeups.
            with self._cond:
                if self._work_pending:
                    self._work_pending = False
                    continue
                self._cond.wait()

    def notification_backlog(self) -> int:
        """Outstanding wake signals (bounded: 0 or 1 under any load)."""
        with self._cond:
            return 1 if self._work_pending else 0

    def _notify_work(self) -> None:
        with self._cond:
            self._work_pending = True
            self._cond.notify()

    def _execute(self, item: tuple) -> None:
        work, future, loop, payload_bytes = item
        try:
            result = work(self._resource)
        except BaseException as exc:  # noqa: BLE001 - delivered to caller
            self._release_bytes(payload_bytes)
            self._deliver(future, loop, None, exc)
            return
        self._release_bytes(payload_bytes)
        self._deliver(future, loop, result, None)

    @staticmethod
    def _deliver(future: "asyncio.Future | None",
                 loop: asyncio.AbstractEventLoop | None,
                 result: Any, error: BaseException | None) -> None:
        if future is None or loop is None:
            return

        def settle() -> None:
            if future.done():
                # The awaiting task was cancelled after the work was
                # already accepted. The durable result lives in the store;
                # dropping the return value here is safe and silent.
                return
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(result)

        try:
            loop.call_soon_threadsafe(settle)
        except RuntimeError:
            # The caller's loop closed first; nothing to deliver to.
            pass

    # ------------------------------------------------------------------ #
    # Submission
    # ------------------------------------------------------------------ #
    def _reserve_bytes(self, payload_bytes: int, *, urgent: bool) -> None:
        if payload_bytes <= 0:
            return
        with self._bytes_lock:
            if self._bytes_pending + payload_bytes > self._max_pending_bytes:
                raise ExecutorFull(urgent=urgent,
                                   bytes_pending=self._bytes_pending)
            self._bytes_pending += payload_bytes

    def _release_bytes(self, payload_bytes: int) -> None:
        if payload_bytes <= 0:
            return
        with self._bytes_lock:
            self._bytes_pending -= payload_bytes

    def _check_open(self) -> None:
        if self._worker is None:
            raise ExecutorClosed("executor was never started")
        if self._stop.is_set() or self._finished.is_set():
            raise ExecutorClosed("executor worker has stopped")

    def submit(self, work: _WORK, *, urgent: bool = False,
               payload_bytes: int = 0) -> "asyncio.Future":
        """Enqueue one complete unit; returns a future on the caller loop."""
        self._check_open()
        self._reserve_bytes(payload_bytes, urgent=urgent)
        target = self._urgent if urgent else self._normal
        try:
            future: "asyncio.Future" = asyncio.get_running_loop().create_future()
        except RuntimeError:
            self._release_bytes(payload_bytes)
            raise
        item = (work, future, asyncio.get_running_loop(), payload_bytes)
        try:
            target.put_nowait(item)
        except queue.Full:
            self._release_bytes(payload_bytes)
            raise ExecutorFull(urgent=urgent,
                               bytes_pending=self._bytes_pending) from None
        self._notify_work()
        return future

    def submit_nowait(self, work: _WORK, *, urgent: bool = False,
                      payload_bytes: int = 0) -> None:
        """Enqueue without awaiting a result (fire-and-forget diagnostics)."""
        self._check_open()
        self._reserve_bytes(payload_bytes, urgent=urgent)
        target = self._urgent if urgent else self._normal
        item = (work, None, None, payload_bytes)
        try:
            target.put_nowait(item)
        except queue.Full:
            self._release_bytes(payload_bytes)
            raise ExecutorFull(urgent=urgent,
                               bytes_pending=self._bytes_pending) from None
        self._notify_work()

    def run_sync(self, work: _WORK, *, timeout: float = 30.0) -> Any:
        """Execute one unit on the worker, blocking the calling thread.

        For construction-time setup, tests and synchronous control paths
        only: never call this from the event loop that submits async work,
        because the worker may be busy with those units. The unit goes on
        the *normal* queue so it never jumps ahead of already-accepted
        normal writes (no read may bypass a preceding durable write).
        """
        self._check_open()
        done = threading.Event()
        outcome: list[tuple[Any, BaseException | None]] = []

        def wrapped(_resource: Any) -> None:
            try:
                outcome.append((work(self._resource), None))
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                outcome.append((None, exc))
            finally:
                done.set()

        item = (wrapped, None, None, 0)
        try:
            self._normal.put(item)
        except queue.Full:
            raise ExecutorFull(urgent=False, bytes_pending=0) from None
        self._notify_work()
        if not done.wait(timeout=timeout):
            raise TimeoutError(
                f"off-loop executor unit did not finish within {timeout}s")
        result, error = outcome[0]
        if error is not None:
            raise error
        return result

    # ------------------------------------------------------------------ #
    # Shutdown
    # ------------------------------------------------------------------ #
    @property
    def pending_items(self) -> int:
        return self._normal.qsize() + self._urgent.qsize()

    def metrics(self) -> dict[str, object]:
        """Bounded operational counters; never payloads or secrets."""
        return {
            "name": self._name,
            "pending_normal": self._normal.qsize(),
            "pending_urgent": self._urgent.qsize(),
            "bytes_pending": self.bytes_pending,
            "max_pending_bytes": self._max_pending_bytes,
            "worker_alive": bool(self._worker and self._worker.is_alive()),
            "worker_ident": self._worker.ident if self._worker else None,
            "stopped": self._stop.is_set(),
        }

    @property
    def bytes_pending(self) -> int:
        with self._bytes_lock:
            return self._bytes_pending

    def request_stop(self) -> None:
        self._stop.set()
        # Wake the worker from the coalesced condition sleep (and any other
        # waiter) so shutdown never waits for the next item to arrive.
        with self._cond:
            self._cond.notify_all()
        # Wake any thread blocked in run_sync as well: its work item may
        # already be drained, so the done-latch is what releases it; nothing
        # to do here for it because run_sync items carry their own latch.

    def join(self, timeout: float) -> bool:
        if self._worker is None:
            return True
        self._worker.join(timeout=timeout)
        return not self._worker.is_alive()

    async def aclose(self, *, timeout: float = 10.0) -> str:
        """Drain accepted work and stop the worker without blocking the loop."""
        self.request_stop()
        deadline = time.monotonic() + timeout
        while self.pending_items and time.monotonic() < deadline:
            await asyncio.sleep(0.002)
        stopped = await asyncio.to_thread(self.join, max(
            0.1, deadline - time.monotonic()))
        if not stopped:
            raise TimeoutError(
                "off-loop executor worker did not stop within its budget")
        return "closed"

    def close(self, *, timeout: float = 15.0) -> None:
        """Synchronous transitional bridge; see the module docstring."""
        self.request_stop()
        if not self.join(timeout):
            raise TimeoutError(
                "off-loop executor worker did not stop within its budget")

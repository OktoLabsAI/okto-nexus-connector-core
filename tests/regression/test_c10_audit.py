"""C10 audit tests — Z02 durable-release producers under shutdown.

Rebuilt from the reaudit reproductions (baseline: seed 1 FAIL on
c5bd955 - the owned producer was cancelled by the cleanup gather;
seed 2 FAIL on the audited snapshot, already bounded by the C9 fix
and kept as the regression guard). Storage barriers stay closed
until AFTER the assertions.
"""

import asyncio
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from nexus_connector_core import (
    CoreError, LaunchIntent, OpenOperation, SessionKey, ShutdownPolicy,
    create_runtime,
)
from nexus_connector_core.journal import SQLiteJournal

from tests.test_runtime import FakeClock, context

def _codex_candidate(tmp_path, name="codex"):
    from nexus_connector_core import InstallationCandidate
    from nexus_connector_core.discovery import fingerprint
    binary = tmp_path / name
    binary.write_bytes(b"synthetic binary")
    return InstallationCandidate(
        "codex_app_server", str(binary), fingerprint(binary),
        "explicit", "selected")


class _StoppableNative:
    native_id = "native-1"

    def __init__(self):
        self.queue = asyncio.Queue()
        self.stopped = False
        self.start_gate = threading.Event()

    async def send(self, verb, payload, operation_id, *,
                   expected_turn_id=None):
        pass

    async def events(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            yield item

    async def close(self):
        self.stopped = True
        await self.queue.put(None)
        return "graceful"

    async def force_stop(self):
        self.stopped = True

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


class _LedgerPort:
    """Lab ledger: first release refuses pre-commit; the next one can
    block on a barrier and observe its own cancellation."""

    def __init__(self, inner, *, release_gate: threading.Event):
        self._inner = inner
        self.gate = release_gate
        self.refused = False
        self.cancel_received = threading.Event()
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def release_owned_slot(self, key, session_id):
        self.calls += 1
        if not self.refused:
            self.refused = True
            raise CoreError("STORAGE_UNAVAILABLE", "slot_release",
                            retry_safe=True)
        try:
            await asyncio.to_thread(self.gate.wait, 5)
        except BaseException:
            self.cancel_received.set()
            raise
        return await self._inner.release_owned_slot(key, session_id)


async def _reach_stopped_obligation(runtime, native, ledger):
    clock = FakeClock(100.0)
    auth = replace(context(), lease_deadline_monotonic=clock.now + 60)
    prepared = await runtime.prepare(
        LaunchIntent("agent", "ws", "codex_app_server"), auth)
    opening = asyncio.create_task(runtime.open(
        OpenOperation("open-op", "session", "epoch", prepared), auth))
    await asyncio.sleep(0.2)
    opening.cancel()
    try:
        await opening
    except BaseException:
        pass
    native.start_gate.set()
    deadline = time.monotonic() + 3
    key = SessionKey("srv", "exe", "session")
    while (key not in runtime._release_obligations
           and time.monotonic() < deadline):
        await asyncio.sleep(0.05)
    assert key in runtime._release_obligations, "obligation not created"
    assert native.stopped


def test_shutdown_deadline_does_not_cancel_owned_release_producer(
        tmp_path):
    async def run():
        native = _StoppableNative()

        async def environment(prepared):
            return {}

        class _Factory:
            async def open(self, prepared, session_id, auth, *,
                           stream_epoch):
                await asyncio.to_thread(native.start_gate.wait, 5)
                return native

        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _codex_candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)},
            native_factory=_Factory(), clock=FakeClock(100.0),
            lease_grace_seconds=0.0, lease_poll_seconds=0.01,
            cleanup_budget_seconds=0.03)
        ledger = _LedgerPort(runtime._owned_slots,
                             release_gate=threading.Event())
        runtime._owned_slots = ledger
        key = SessionKey("srv", "exe", "session")
        try:
            await _reach_stopped_obligation(runtime, native, ledger)
            # The public shutdown expires its response budget while the
            # durable release producer is still running.
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.0,
                                                interrupt_seconds=0.0)),
                timeout=5)
            obligation = runtime._release_obligations.get(key)
            assert obligation is not None, "obligation lost"
            producer = obligation.retry_task
            assert producer is not None, "no durable producer exists"
            assert not producer.cancelled(), (
                "the shutdown budget CANCELLED the owned release "
                "producer")
            assert not ledger.cancel_received.is_set(), (
                "the backend received a cancellation for an operation "
                "the runtime claims to keep supervising")
        finally:
            ledger.gate.set()
            runtime._owned_slots = ledger._inner
            native.start_gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


def test_shutdown_return_does_not_wait_for_release_cancel_cleanup(
        tmp_path):
    async def run():
        native = _StoppableNative()

        async def environment(prepared):
            return {}

        class _Factory:
            async def open(self, prepared, session_id, auth, *,
                           stream_epoch):
                await asyncio.to_thread(native.start_gate.wait, 5)
                return native

        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _codex_candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)},
            native_factory=_Factory(), clock=FakeClock(100.0),
            lease_grace_seconds=0.0, lease_poll_seconds=0.01,
            cleanup_budget_seconds=0.03)
        ledger = _LedgerPort(runtime._owned_slots,
                             release_gate=threading.Event())
        runtime._owned_slots = ledger
        try:
            await _reach_stopped_obligation(runtime, native, ledger)
            # The backend's release needs its own cleanup time after a
            # cancellation; the PUBLIC return must still respect the
            # response budget - never wait for that cleanup.
            started = time.monotonic()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.0,
                                                interrupt_seconds=0.0)),
                timeout=3.5)
            elapsed = time.monotonic() - started
            assert elapsed < 3.0, (
                f"the public return waited {elapsed:.2f}s for the "
                "backend's cancellation cleanup")
            assert not ledger.gate.is_set(), (
                "the test released the storage barrier itself")
        finally:
            ledger.gate.set()
            runtime._owned_slots = ledger._inner
            native.start_gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


def test_concurrent_shutdown_retry_coalesces_the_current_force_producer(
        tmp_path):
    """Control (passes on the audited code): two public shutdowns keep
    at most ONE active physical force for the same resource."""
    from tests.regression.test_c8_audit import (
        _ThreadForceNative, _late_open_runtime, _cancel_open_late)

    async def run():
        native = _ThreadForceNative()
        runtime, journal = _late_open_runtime(tmp_path, native)
        try:
            await _cancel_open_late(runtime, FakeClock(100.0))
            first = asyncio.create_task(runtime.shutdown(
                ShutdownPolicy(drain_seconds=0.05,
                               interrupt_seconds=0.05)))
            await asyncio.sleep(0.1)
            native.start_gate.set()
            deadline = time.monotonic() + 3
            while native.force_calls < 1 and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert native.force_calls == 1
            second = await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.05,
                                                interrupt_seconds=0.05)),
                timeout=10)
            assert second is not None
            assert native.force_peak == 1
            native.force_gate.set()
            try:
                await asyncio.wait_for(first, timeout=10)
            except BaseException:
                pass
        finally:
            native.start_gate.set()
            native.force_gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())

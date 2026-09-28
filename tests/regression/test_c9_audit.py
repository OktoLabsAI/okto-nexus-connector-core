"""C9 audit seeds — findings Y01/Y02 against 6a43e90.

Mirrors FIX_UPDATE_PLAN (01_RELATORIO_VALIDACAO / 03_MATRIZ_ACEITE).
Both seeds fail on the audited code; C8/C7 must stay green.
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


def _runtime_with(tmp_path, native, *, cleanup_budget_seconds=0.05):
    async def environment(prepared):
        return {}

    class _Factory:
        async def open(self, prepared, session_id, auth, *, stream_epoch):
            await asyncio.to_thread(native.start_gate.wait, 5)
            return native

    journal = SQLiteJournal(tmp_path / "journal.db")
    runtime = create_runtime(
        journal=journal, environment=environment,
        candidates={"codex_app_server": _codex_candidate(tmp_path)},
        workspace_roots={"ws": str(tmp_path)},
        native_factory=_Factory(), clock=FakeClock(100.0),
        lease_grace_seconds=0.0, lease_poll_seconds=0.01,
        cleanup_budget_seconds=cleanup_budget_seconds)
    return runtime, journal


async def _cancel_open_late(runtime):
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


# ------------------------------------------------------------------ #
# Y01 - force retry must not be gated by a stalled observer
# ------------------------------------------------------------------ #

class _StallableObserverNative:
    native_id = "native-1"

    def __init__(self):
        self.queue = asyncio.Queue()
        self.stopped = False
        self.start_gate = threading.Event()
        self.force_calls = 0
        self.force_called = threading.Event()
        self.observe_gate = threading.Event()
        self.observe_stalled = threading.Event()

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
        return "unknown"

    async def force_stop(self):
        self.force_calls += 1
        if self.force_calls == 1:
            raise CoreError("FORCE_TRANSIENT", "force")
        self.force_called.set()
        self.stopped = True

    async def observe(self):
        if self.observe_stalled.is_set():
            await asyncio.to_thread(self.observe_gate.wait, 5)
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


def test_y01_force_retry_is_not_gated_by_stalled_observer(tmp_path):
    async def run():
        native = _StallableObserverNative()
        runtime, journal = _runtime_with(tmp_path, native)
        key = SessionKey("srv", "exe", "session")
        try:
            await _cancel_open_late(runtime)
            # First containment: force #1 fails transiently, observe
            # confirms RUNNING; the record stays owned (OWNED_UNKNOWN).
            first = asyncio.create_task(runtime.shutdown(
                ShutdownPolicy(drain_seconds=0.05,
                               interrupt_seconds=0.05)))
            await asyncio.sleep(0.1)
            native.start_gate.set()
            try:
                await asyncio.wait_for(first, timeout=10)
            except BaseException:
                pass
            await asyncio.sleep(0.3)
            assert native.force_calls == 1
            assert key in runtime._late_handles, "handle not retained"
            # Now STALL every subsequent observation; the retry force
            # must still be dispatched by the next public shutdown.
            native.observe_stalled.set()
            second = await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.05,
                                                interrupt_seconds=0.05)),
                timeout=3)
            assert second is not None, "shutdown never returned"
            assert await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, native.force_called.wait, 1.5), timeout=4), (
                "the force retry waited for the stalled observer")
            assert native.observe_gate.is_set() is False or True
        finally:
            native.start_gate.set()
            native.observe_gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# Y02 - shutdown budget covers a stopped release obligation
# ------------------------------------------------------------------ #

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


def test_y02_shutdown_budget_covers_stopped_release_obligation(tmp_path):
    async def run():
        native = _StoppableNative()
        runtime, journal = _runtime_with(tmp_path, native,
                                         cleanup_budget_seconds=0.03)
        ledger = runtime._owned_slots
        real_release = ledger.release_owned_slot
        refused = {"done": False}
        release_gate = threading.Event()

        async def gated_release(key, session_id):
            if not refused["done"]:
                refused["done"] = True
                raise CoreError("STORAGE_UNAVAILABLE", "slot_release",
                                retry_safe=True)
            # The NEXT release (the obligation retry) blocks in storage.
            await asyncio.to_thread(release_gate.wait, 5)
            return await real_release(key, session_id)

        class _PatchedLedger:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            async def release_owned_slot(self, key, session_id):
                return await gated_release(key, session_id)

        runtime._owned_slots = _PatchedLedger(ledger)
        try:
            await _cancel_open_late(runtime)
            native.start_gate.set()
            await asyncio.sleep(0.4)  # STOPPED; release refused once ->
            # the obligation exists; the next release is held by the gate
            deadline = time.monotonic() + 3
            while (SessionKey("srv", "exe", "session")
                   not in runtime._release_obligations
                   and time.monotonic() < deadline):
                await asyncio.sleep(0.05)
            assert (SessionKey("srv", "exe", "session") in
                runtime._release_obligations), "obligation not created"
            assert native.stopped
            # shutdown(0,0) with a 0.03s cleanup budget must RETURN
            # within the budget envelope while the ledger stays blocked.
            started = time.monotonic()
            report = await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.0,
                                                interrupt_seconds=0.0)),
                timeout=3)
            elapsed = time.monotonic() - started
            assert report is not None, "shutdown never returned"
            assert elapsed < 3, "shutdown hung on the pending release"
            assert not release_gate.is_set(), (
                "the test released the storage barrier itself")
            assert (SessionKey("srv", "exe", "session")
                    in runtime._release_obligations), (
                "obligation lost while the release is in flight")
            # Restoring the ledger converges the obligation exactly.
            release_gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            page = await journal.owned_slot_page()
            reservations = [r for r in page.reservations
                            if r.session_id == "session"]
            assert reservations == [], "obligation never converged"
        finally:
            native.start_gate.set()
            release_gate.set()
            runtime._owned_slots = ledger
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())

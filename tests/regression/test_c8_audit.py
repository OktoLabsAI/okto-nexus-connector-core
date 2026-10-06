"""C8 audit seeds — reaudit findings X01-X03 against 9f0ebab.

Mirrors FIX_UPDATE_PLAN (01_RELATORIO_REAVALIACAO / 03_MATRIZ_ACEITE).
Three seeds fail on the audited code; two positive controls pass.
"""

import asyncio
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from nexus_connector_core import (
    CoreError, LaunchIntent, OpenOperation, SessionKey, ShutdownPolicy,
    TurnOperation, create_runtime,
)
from nexus_connector_core.journal import SQLiteJournal

from tests.test_runtime import FakeClock, context, make_runtime

def _codex_candidate(tmp_path, name="codex"):
    from nexus_connector_core import InstallationCandidate
    from nexus_connector_core.discovery import fingerprint
    binary = tmp_path / name
    binary.write_bytes(b"synthetic binary")
    return InstallationCandidate(
        "codex_app_server", str(binary), fingerprint(binary),
        "explicit", "selected")


# ------------------------------------------------------------------ #
# X01 (AC8-01) - observed newer durable fence blocks the old context
# ------------------------------------------------------------------ #

def test_x01_observed_newer_durable_fence_blocks_old_context(tmp_path):
    clock = FakeClock(100.0)

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")

        class _Native:
            native_id = "native-1"

            def __init__(self):
                self.queue = asyncio.Queue()
                self.stopped = False
                self.sent = []

            async def send(self, verb, payload, operation_id, *,
                           expected_turn_id=None):
                self.sent.append((verb, operation_id))

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

        native = _Native()

        class _Factory:
            async def open(self, prepared, session_id, auth, *,
                           stream_epoch):
                return native

        async def environment(prepared):
            return {}

        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _codex_candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)},
            native_factory=_Factory(), clock=clock,
            lease_grace_seconds=0.0, lease_poll_seconds=0.01,
            reconnect_fence_seconds=0.2)
        key = SessionKey("srv", "exe", "session")
        try:
            base = replace(context(),
                           lease_deadline_monotonic=clock.now + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), base)
            await runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared),
                base)
            # A second authorized writer (two real SQLite connections)
            # advances the durable lease: generation 3 -> 5.
            peer = SQLiteJournal(tmp_path / "journal.db")
            await peer.cas_session_lease(
                key, expected_connection_generation=3,
                connection_generation=5, owner_generation=1,
                authorization_revision=1, configuration_revision=1,
                revoked=False)
            peer.close()
            # Renew to generation 4 with expected=3: the durable CAS
            # itself refuses (the proof reached the journal).
            with pytest.raises(CoreError) as excinfo:
                await runtime.renew_lease(
                    key, replace(base, connection_generation=4,
                                 lease_deadline_monotonic=clock.now + 90),
                    expected_connection_generation=3)
            assert excinfo.value.stage == "lease_cas", (
                "the refusal must come from the durable comparison, not "
                "from an earlier validation")
            # The durable row really is generation 5.
            lease = await journal.get_session_lease(key)
            assert lease is not None and lease.connection_generation == 5
            # The OLD context (generation 3) must now be refused: the
            # runtime OBSERVED the newer fence - zero productive writes.
            with pytest.raises(CoreError):
                await runtime.submit(
                    TurnOperation("stale", "session", "hello"), base)
            assert native.sent == [], (
                "an observed-superseded context still sent work")
        finally:
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


def test_control_normal_renewal_still_allows_authorized_work(tmp_path):
    clock = FakeClock(100.0)

    async def run():
        runtime, journal, factory = make_runtime(
            tmp_path, clock=clock, lease_grace_seconds=0.0,
            lease_poll_seconds=0.01)
        key = SessionKey("srv", "exe", "session")
        try:
            base = replace(context(),
                           lease_deadline_monotonic=clock.now + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), base)
            await runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared),
                base)
            renewed = replace(base, connection_generation=4,
                              lease_deadline_monotonic=clock.now + 90)
            await runtime.renew_lease(
                key, renewed, expected_connection_generation=3)
            receipt = await runtime.submit(
                TurnOperation("fresh", "session", "hello"), renewed)
            assert receipt.stage == "SUBMITTED"
            assert len(factory.native.sent) == 1
        finally:
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# X02 (AC8-02) - stopped late handle keeps a failed slot release
#                recoverable
# ------------------------------------------------------------------ #

class _LateStopNative:
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


def _late_open_runtime(tmp_path, native):
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
        cleanup_budget_seconds=0.2)
    return runtime, journal


async def _cancel_open_late(runtime, clock):
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


def test_x02_late_stop_keeps_failed_slot_release_recoverable(tmp_path):
    async def run():
        native = _LateStopNative()
        runtime, journal = _late_open_runtime(tmp_path, native)
        clock = FakeClock(100.0)
        try:
            await _cancel_open_late(runtime, clock)
            # Inject ONE pre-commit refusal into the durable release of
            # the LATE CONTAINMENT itself (the slot is still held when
            # the handle stops): the obligation must survive the failed
            # attempt and converge once the ledger answers again.
            ledger = runtime._owned_slots
            real_release = ledger.release_owned_slot
            refused = {"done": False}

            async def failing_release(key, session_id):
                if not refused["done"]:
                    refused["done"] = True
                    raise CoreError("STORAGE_UNAVAILABLE", "slot_release",
                                    retry_safe=True)
                return await real_release(key, session_id)

            runtime._owned_slots = _PatchedLedger(ledger, failing_release)
            native.start_gate.set()  # the late handle arrives
            await asyncio.sleep(0.5)  # stopped; release REFUSED once
            assert native.stopped
            runtime._owned_slots = ledger  # ledger restored
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            deadline = time.monotonic() + 3
            while True:
                page = await journal.owned_slot_page()
                reservations = [r for r in page.reservations
                                if r.key.session_id == "session"]
                if not reservations or time.monotonic() >= deadline:
                    break
                await asyncio.sleep(.01)
            assert reservations == [], (
                "the failed slot release obligation was forgotten")
        finally:
            native.start_gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


class _PatchedLedger:
    def __init__(self, inner, release):
        self._inner = inner
        self._release = release

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def release_owned_slot(self, key, session_id):
        return await self._release(key, session_id)


def test_control_late_stop_with_available_ledger_releases_slot(tmp_path):
    async def run():
        native = _LateStopNative()
        runtime, journal = _late_open_runtime(tmp_path, native)
        clock = FakeClock(100.0)
        try:
            await _cancel_open_late(runtime, clock)
            native.start_gate.set()
            await asyncio.sleep(0.4)
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            page = await journal.owned_slot_page()
            reservations = [r for r in page.reservations
                            if r.session_id == "session"]
            assert reservations == [], "normal release path broke"
        finally:
            native.start_gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# X03 (AC8-03) - repeat shutdown coalesces the in-flight physical force
# ------------------------------------------------------------------ #

class _ThreadForceNative(_LateStopNative):
    """force_stop blocks in a REAL thread unit (like the bridge); the
    graceful close never confirms a stop (the force is the containment)."""

    def __init__(self):
        super().__init__()
        self.force_gate = threading.Event()
        self.force_calls = 0
        self.force_active = 0
        self.force_peak = 0
        self._lock = threading.Lock()

    async def close(self):
        return "unknown"  # never confirms; force is the real containment

    async def force_stop(self):
        def _physical():
            with self._lock:
                self.force_calls += 1
                self.force_active += 1
                self.force_peak = max(self.force_peak,
                                      self.force_active)
            self.force_gate.wait(5)
            with self._lock:
                self.force_active -= 1
            self.stopped = True

        await asyncio.to_thread(_physical)


def test_x03_repeat_shutdown_coalesces_physical_force_in_flight(tmp_path):
    async def run():
        native = _ThreadForceNative()
        runtime, journal = _late_open_runtime(tmp_path, native)
        clock = FakeClock(100.0)
        try:
            await _cancel_open_late(runtime, clock)
            # First containment dispatches the physical force (a REAL
            # thread unit that stays held on the gate).
            first = asyncio.create_task(runtime.shutdown(
                ShutdownPolicy(drain_seconds=0.05,
                               interrupt_seconds=0.05)))
            await asyncio.sleep(0.1)
            native.start_gate.set()
            deadline = time.monotonic() + 3
            while native.force_calls < 1 and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert native.force_calls == 1, "first force never dispatched"
            # The second public shutdown expires its budget while the
            # first physical unit is STILL ACTIVE: recovery must share
            # it, never dispatch a second one over the same handle.
            second = await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.05,
                                                interrupt_seconds=0.05)),
                timeout=10)
            assert second is not None
            assert native.force_peak == 1, (
                f"physical force duplicated in flight "
                f"(peak={native.force_peak}, calls={native.force_calls})")
            assert not native.force_gate.is_set()
            # Release the held unit: the shared result completes and
            # the thread marks the stop BEFORE any further lifecycle
            # call (no observe-vs-thread race).
            native.force_gate.set()
            try:
                await asyncio.wait_for(first, timeout=10)
            except BaseException:
                pass
            deadline = time.monotonic() + 5
            while not native.stopped and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert native.stopped
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            assert native.force_calls == 1, (
                "a redundant second physical force ran after coalescing")
        finally:
            native.start_gate.set()
            native.force_gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())

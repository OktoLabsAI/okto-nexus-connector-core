"""C10-02.5 complementary controls: external cancellation, result
consumption before re-scheduling, ACK loss and cross-resource
independence for the unified durable-release route."""

import asyncio
import threading
import time
from dataclasses import replace

import pytest

from nexus_connector_core import (
    CoreError, LaunchIntent, OpenOperation, SessionKey, ShutdownPolicy,
    create_runtime,
)
from nexus_connector_core.journal import SQLiteJournal

from tests.regression.test_c10_audit import (
    _LedgerPort, _StoppableNative, _codex_candidate,
)
from tests.test_runtime import FakeClock, context


def _runtime(tmp_path, ledger_gate):
    native = _StoppableNative()

    async def environment(prepared):
        return {}

    class _Factory:
        async def open(self, prepared, session_id, auth, *,
                       stream_epoch):
            native.open_entered.set()
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
    ledger = _LedgerPort(runtime._owned_slots, release_gate=ledger_gate)
    runtime._owned_slots = ledger
    return runtime, journal, ledger, native


async def _reach_stopped(runtime, native, ledger):
    auth = replace(context(), lease_deadline_monotonic=160.0)
    prepared = await runtime.prepare(
        LaunchIntent("agent", "ws", "codex_app_server"), auth)
    opening = asyncio.create_task(runtime.open(
        OpenOperation("open-op", "session", "epoch", prepared), auth))
    await asyncio.wait_for(native.open_entered.wait(), 3)
    opening.cancel()
    with pytest.raises(asyncio.CancelledError):
        await opening
    native.start_gate.set()
    key = SessionKey("srv", "exe", "session")
    deadline = time.monotonic() + 3
    while (key not in runtime._release_obligations
           and time.monotonic() < deadline):
        await asyncio.sleep(0.05)
    assert key in runtime._release_obligations
    assert native.stopped
    return key


def test_external_cancellation_of_shutdown_keeps_owned_producer(tmp_path):
    async def run():
        gate = threading.Event()
        runtime, journal, ledger, native = _runtime(tmp_path, gate)
        try:
            key = await _reach_stopped(runtime, native, ledger)
            # The CALLER cancels its own shutdown while the durable
            # release producer is in flight: only the waiter dies.
            shutdown_call = asyncio.create_task(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.0,
                                                interrupt_seconds=0.0)))
            await asyncio.sleep(0.1)
            obligation = runtime._release_obligations.get(key)
            assert obligation and obligation.retry_task is not None
            producer = obligation.retry_task
            shutdown_call.cancel()
            try:
                await shutdown_call
            except BaseException:
                pass
            assert not producer.cancelled(), (
                "external cancellation of the CALLER cancelled the "
                "owned release producer")
            assert not ledger.cancel_received.is_set(), (
                "the backend received a cancellation")
            # The late commit converges on the next public call.
            gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            assert key not in runtime._release_obligations
            page = await journal.owned_slot_page()
            assert [r for r in page.reservations
                    if r.session_id == "session"] == []
        finally:
            gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


def test_success_harvested_before_scheduling_no_redundant_release(
        tmp_path):
    async def run():
        # The storage blocks the FIRST release (obligation created,
        # producer IN FLIGHT), then answers it with SUCCESS while no
        # lifecycle call is running. The next public call must CONSUME
        # that available result - never dispatch a second release of
        # the same reservation.
        gate = threading.Event()
        runtime, journal, ledger, native = _runtime(tmp_path, gate)
        inner = ledger._inner

        class _BlockingLedger:
            calls = 0

            def __init__(self, target):
                self._target = target

            def __getattr__(self, name):
                return getattr(self._target, name)

            async def release_owned_slot(self, k, sid):
                type(self).calls += 1
                await asyncio.to_thread(gate.wait, 5)
                return await inner.release_owned_slot(k, sid)

        blocking = _BlockingLedger(runtime._owned_slots)
        runtime._owned_slots = blocking
        try:
            key = await _reach_stopped(runtime, native, ledger)
            gate.set()  # the in-flight producer commits successfully
            await asyncio.sleep(0.3)
            calls_after_success = _BlockingLedger.calls
            assert calls_after_success == 1
            for _ in range(3):
                await asyncio.wait_for(
                    runtime.shutdown(ShutdownPolicy()), timeout=10)
            assert _BlockingLedger.calls == calls_after_success, (
                "a redundant durable release was dispatched after an "
                "already-available success")
            assert key not in runtime._release_obligations
            page = await journal.owned_slot_page()
            assert [r for r in page.reservations
                    if r.session_id == "session"] == []
        finally:
            gate.set()
            runtime._owned_slots = ledger
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


def test_ack_lost_after_commit_closes_same_obligation(tmp_path):
    """Commit succeeded but the confirmation was lost (error AFTER the
    effect): the retry consults the ledger idempotently - the SAME
    reservation closes; no rollback is inferred; no extra spawn."""
    async def run():
        gate = threading.Event()
        gate.set()
        runtime, journal, ledger, native = _runtime(tmp_path, gate)
        inner = ledger._inner
        real_release = ledger.release_owned_slot
        state = {"committed": False, "ack_errors": 0}
        class _AckLossLedger:
            def __init__(self, target):
                self._target = target

            def __getattr__(self, name):
                return getattr(self._target, name)

            async def release_owned_slot(self, k, sid):
                # The COMMIT itself succeeds; only the confirmation is
                # lost afterwards (possible_effect=True).
                result = await inner.release_owned_slot(k, sid)
                state["committed"] = True
                state["ack_errors"] += 1
                raise CoreError("STORAGE_UNAVAILABLE", "slot_release",
                                retry_safe=True, possible_effect=True)

        ack_ledger = _AckLossLedger(runtime._owned_slots)
        runtime._owned_slots = ack_ledger
        try:
            key = await _reach_stopped(runtime, native, ack_ledger)
            await asyncio.sleep(0.2)
            assert state["committed"], "the commit never happened"
            assert state["ack_errors"] == 1
            # Confirmation restored: the retry consults the ledger
            # idempotently (the reservation is already released) and
            # closes the SAME obligation - without a new physical
            # effect and without inferring rollback.
            class _ConfirmLedger:
                def __getattr__(self, name):
                    return getattr(inner, name)

                async def release_owned_slot(self, k, sid):
                    state["confirms"] = state.get("confirms", 0) + 1
                    return await inner.release_owned_slot(k, sid)

            confirm = _ConfirmLedger()
            runtime._owned_slots = confirm
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            assert key not in runtime._release_obligations
            page = await journal.owned_slot_page()
            assert [r for r in page.reservations
                    if r.session_id == "session"] == []
            assert state["ack_errors"] == 1, (
                "a redundant release ran after the ack loss")
        finally:
            gate.set()
            runtime._owned_slots = ledger
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("admission_delay", [0, 0.35])
def test_retained_ledger_does_not_delay_other_resource_force(tmp_path, admission_delay):
    """A blocked durable obligation for one stopped resource never
    delays containment of ANOTHER live resource."""
    async def run():
        gate = threading.Event()
        runtime, journal, ledger, native = _runtime(tmp_path, gate)
        # Slow durable receipt lookup may precede native-factory admission.
        # It must not move cancellation to a different lifecycle boundary.
        original_existing = runtime._existing

        async def delayed_existing(*args):
            await asyncio.sleep(admission_delay)
            return await original_existing(*args)

        runtime._existing = delayed_existing
        live = _StoppableNative()
        live.native_id = "native-live"

        class _LiveFactory:
            async def open(self, prepared, session_id, auth, *,
                           stream_epoch):
                return live

        # resource 1: stopped with a BLOCKED durable obligation.
        key = await _reach_stopped(runtime, native, ledger)
        assert key in runtime._release_obligations

        # resource 2: a live owned session on the SAME runtime that
        # must be forced even while the ledger is blocked.
        auth = replace(context(), lease_deadline_monotonic=160.0)
        prepared = await runtime.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), auth)
        runtime._native_factory = _LiveFactory()
        await runtime.open(
            OpenOperation("open-op-2", "session2", "epoch", prepared),
            auth)
        assert SessionKey("srv", "exe", "session2") in runtime._sessions

        started = time.monotonic()
        await asyncio.wait_for(
            runtime.shutdown(ShutdownPolicy(drain_seconds=0.0,
                                            interrupt_seconds=0.05)),
            timeout=10)
        elapsed = time.monotonic() - started
        assert live.stopped, (
            "the live resource was not contained while the durable "
            "obligation of another resource was blocked")
        assert elapsed < 5.0
        assert key in runtime._release_obligations, (
            "the blocked obligation was dropped without confirmation")
        assert not ledger.cancel_received.is_set()
        # Restored storage converges the exact reservation.
        gate.set()
        await asyncio.wait_for(
            runtime.shutdown(ShutdownPolicy()), timeout=10)
        assert key not in runtime._release_obligations
        page = await journal.owned_slot_page()
        assert [r for r in page.reservations
                if r.session_id == "session"] == []
        journal.close()

    asyncio.run(run())

import asyncio
import math
import time
from dataclasses import replace

import pytest

from nexus_connector_core import (CoreError, EventCursor, ExecutionContext,
                                  OperationKey, ProcessBirthEvidence, SessionKey,
                                  SQLiteOwnedSlotLedger)
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import JournalLimits, SQLiteJournal
from nexus_connector_core.native.adapter_types import RuntimeCommandNotSent
from nexus_connector_core.native.event_buffers import NativeEventOverflow
from nexus_connector_core.models import (
    CloseOperation, ControlOperation, InstallationCandidate, LaunchIntent,
    NativeApprovalOperation, OpenOperation, ReconcileRequest, RuntimeEvent, ShutdownPolicy,
    TurnOperation,
)
from nexus_connector_core.runtime import LocalRuntimeCore, _Session


class FakeNative:
    native_id = "native-1"

    def __init__(self):
        self.sent = []
        self.targets = []
        self.queue = asyncio.Queue()
        self.stopped = False

    async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
        self.sent.append((verb, dict(payload), operation_id))
        self.targets.append(expected_turn_id)

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

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


class FakeFactory:
    def __init__(self):
        self.open_count = 0
        self.native = FakeNative()

    async def open(self, prepared, session_id, context, *, stream_epoch):
        self.open_count += 1
        return self.native


class FakeClock:
    def __init__(self, now=100.0):
        self.now = now

    def monotonic(self):
        return self.now

    def wall_time(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def context(agent="agent", actions=None, server="srv"):
    return ExecutionContext(server, "exe", "binding", agent, "ws", 1, 1, 3,
                            time.monotonic() + 60,
                            frozenset(actions or {"runtime.open", "turn.submit",
                                                  "turn.interrupt", "runtime.close"}))


def make_runtime(tmp_path, *, clock=None, lease_grace_seconds=15.0,
                 lease_poll_seconds=0.25, adapter_id="codex_app_server",
                 max_lease_seconds=120.0,
                 max_concurrent_opens=8, max_owned_sessions=32,
                 reconnect_fence_seconds=5.0,
                 journal_limits=None,
                 owned_slot_ledger=None,
                 event_sink=None,
                 cleanup_budget_seconds=5.0):
    binary = tmp_path / "codex"
    binary.write_bytes(b"synthetic binary")
    candidate = InstallationCandidate(adapter_id, str(binary),
                                      fingerprint(binary), "explicit", "selected")
    journal = SQLiteJournal(tmp_path / "journal.db", limits=journal_limits)
    factory = FakeFactory()
    runtime = LocalRuntimeCore(journal, factory,
                               candidates={adapter_id: candidate},
                               workspace_roots={"ws": str(tmp_path)},
                               owned_slot_ledger=owned_slot_ledger,
                               clock=clock,
                               event_sink=event_sink,
                               lease_grace_seconds=lease_grace_seconds,
                               lease_poll_seconds=lease_poll_seconds,
                               max_lease_seconds=max_lease_seconds,
                               reconnect_fence_seconds=reconnect_fence_seconds,
                               max_concurrent_opens=max_concurrent_opens,
                               max_owned_sessions=max_owned_sessions,
                               cleanup_budget_seconds=cleanup_budget_seconds)
    return runtime, journal, factory


def test_runtime_rejects_nonfinite_or_untyped_lease_timing():
    journal = SQLiteJournal(":memory:")
    try:
        for name in ("lease_grace_seconds", "lease_poll_seconds",
                     "max_lease_seconds", "reconnect_fence_seconds"):
            for invalid in (math.nan, math.inf, -math.inf, True, "1", None,
                            10**1000):
                with pytest.raises(ValueError, match="invalid lease timing"):
                    LocalRuntimeCore(journal, object(), candidates={},
                                     workspace_roots={}, **{name: invalid})
        for invalid in (0, -1):
            with pytest.raises(ValueError, match="invalid lease timing"):
                LocalRuntimeCore(journal, object(), candidates={},
                                 workspace_roots={},
                                 reconnect_fence_seconds=invalid)
        with pytest.raises(ValueError, match="invalid lease timing"):
            LocalRuntimeCore(journal, object(), candidates={},
                             workspace_roots={}, max_lease_seconds=1e308,
                             lease_grace_seconds=1e308)
    finally:
        journal.close()


def test_shutdown_rejects_untyped_policy_before_drain():
    async def run():
        journal = SQLiteJournal(":memory:")
        runtime = LocalRuntimeCore(journal, object(), candidates={},
                                   workspace_roots={})
        try:
            for name in ("drain_seconds", "interrupt_seconds"):
                for invalid in (math.nan, math.inf, -math.inf, True, "1", None,
                                -1, 10**1000):
                    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
                        await runtime.shutdown(ShutdownPolicy(**{name: invalid}))
                    assert not runtime._shutting_down
            with pytest.raises(CoreError, match="VALIDATION_ERROR"):
                await runtime.shutdown({"drain_seconds": 0})
            with pytest.raises(CoreError, match="VALIDATION_ERROR"):
                await runtime.shutdown(ShutdownPolicy(1e308, 1e308))
            assert not runtime._shutting_down
        finally:
            journal.close()

    asyncio.run(run())


def test_slow_event_sink_does_not_block_native_pump(tmp_path):
    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()
        delivered = []

        async def sink(event):
            if not delivered:
                entered.set()
                await release.wait()
            delivered.append(event.sequence)

        runtime, journal, factory = make_runtime(tmp_path, event_sink=sink)
        prepared = await runtime.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())
        await runtime.open(OpenOperation("open-slow", "session", "epoch", prepared),
                           context())
        for index in range(25):
            await factory.native.queue.put(RuntimeEvent(
                "srv", "exe", "session", "epoch", 0, "delta", "native.delta",
                {"index": str(index)}))
        await asyncio.wait_for(entered.wait(), 2)
        cursor = EventCursor("srv", "exe", "session", "epoch")

        async def all_durable():
            while await journal.contiguous_watermark(cursor) < 25:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(all_durable(), 2)
        assert delivered == []
        urgent = await asyncio.wait_for(runtime.control(
            ControlOperation("interrupt-slow", "session", "interrupt"), context()), 2)
        assert urgent.stage == "SUBMITTED"
        release.set()

        async def all_delivered():
            while len(delivered) < 25:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(all_delivered(), 2)
        assert delivered == list(range(1, 26))
        await runtime.close(CloseOperation("close-slow", "session"), context())
        journal.close()

    asyncio.run(run())


def test_event_sink_failure_retries_from_journal_on_next_append(tmp_path):
    async def run():
        failed = asyncio.Event()
        delivered = []
        attempts = 0

        async def sink(event):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                failed.set()
                raise OSError("sink offline")
            delivered.append(event.sequence)

        runtime, journal, factory = make_runtime(tmp_path, event_sink=sink)
        prepared = await runtime.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())
        await runtime.open(OpenOperation("open-retry", "session", "epoch", prepared),
                           context())
        await factory.native.queue.put(RuntimeEvent(
            "srv", "exe", "session", "epoch", 0, "delta", "native.delta", {}))
        await asyncio.wait_for(failed.wait(), 2)
        binding = runtime._sessions[SessionKey("srv", "exe", "session")]

        async def failed_attempt_stopped():
            while binding.sink_task is None or not binding.sink_task.done():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(failed_attempt_stopped(), 2)
        assert attempts == 1
        await factory.native.queue.put(RuntimeEvent(
            "srv", "exe", "session", "epoch", 0, "delta", "native.delta", {}))

        async def both_delivered():
            while len(delivered) < 2:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(both_delivered(), 2)
        assert delivered == [1, 2]
        await runtime.close(CloseOperation("close-retry", "session"), context())
        journal.close()

    asyncio.run(run())


def test_event_sink_append_during_callback_failure_is_not_lost(tmp_path):
    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()
        delivered = []
        attempts = 0

        async def sink(item):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                entered.set()
                await release.wait()
                raise OSError("injected callback failure")
            delivered.append(item.sequence)

        runtime, journal, factory = make_runtime(tmp_path, event_sink=sink)
        prepared = await runtime.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())
        await runtime.open(OpenOperation("open-race", "session", "epoch", prepared),
                           context())
        for _ in range(2):
            await factory.native.queue.put(RuntimeEvent(
                "srv", "exe", "session", "epoch", 0, "delta", "native.delta", {}))
            if not entered.is_set():
                await asyncio.wait_for(entered.wait(), 2)
        binding = runtime._sessions[SessionKey("srv", "exe", "session")]

        async def second_append_pending():
            while not binding.sink_pending or await journal.contiguous_watermark(
                    EventCursor("srv", "exe", "session", "epoch")) < 2:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(second_append_pending(), 2)
        release.set()

        async def both_delivered():
            while len(delivered) < 2:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(both_delivered(), 2)
        assert delivered == [1, 2] and attempts == 3
        await runtime.close(CloseOperation("close-race", "session"), context())
        journal.close()

    asyncio.run(run())


def test_event_sink_notifies_durable_pump_fault(tmp_path):
    async def run():
        notified = asyncio.Event()
        seen = []

        async def sink(item):
            seen.append(item)
            notified.set()

        runtime, journal, factory = make_runtime(tmp_path, event_sink=sink)
        prepared = await runtime.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())
        await runtime.open(OpenOperation("open-fault", "session", "epoch", prepared),
                           context())
        await factory.native.queue.put(RuntimeEvent(
            "wrong-server", "exe", "session", "epoch", 0,
            "delta", "native.delta", {}))
        await asyncio.wait_for(notified.wait(), 2)
        assert len(seen) == 1
        assert seen[0].native_type == "core.event_pump_failed"
        assert seen[0].sequence == 1
        assert runtime._sessions[SessionKey("srv", "exe", "session")].faulted
        await runtime.close(CloseOperation("close-fault", "session"), context())
        journal.close()

    asyncio.run(run())


def test_one_native_overflow_fault_does_not_stop_another_session_pump(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        natives = []

        async def open_each(prepared, session_id, context, *, stream_epoch):
            native = FakeNative()
            native.native_id = f"native-{len(natives) + 1}"
            natives.append(native)
            return native

        factory.open = open_each
        prepared = await runtime.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())
        try:
            for session_id in ("noisy", "quiet"):
                await runtime.open(
                    OpenOperation(f"open-{session_id}", session_id, "epoch", prepared),
                    context())
            await natives[0].queue.put(NativeEventOverflow())
            await natives[1].queue.put(RuntimeEvent(
                "srv", "exe", "quiet", "epoch", 0, "delta", "native.delta", {}))

            async def quiet_recorded():
                cursor = EventCursor("srv", "exe", "quiet", "epoch", 0)
                while True:
                    items = [item async for item in journal.events(cursor)]
                    if items:
                        return items
                    await asyncio.sleep(0.01)

            items = await asyncio.wait_for(quiet_recorded(), 2)
            assert items[0].native_type == "native.delta"
            assert runtime._sessions[SessionKey("srv", "exe", "noisy")].faulted
            assert not runtime._sessions[SessionKey("srv", "exe", "quiet")].faulted
        finally:
            for session_id in ("noisy", "quiet"):
                await runtime.close(CloseOperation(f"close-{session_id}", session_id),
                                    context())
            journal.close()

    asyncio.run(run())


def test_async_runtime_admission_events_reconcile_and_close(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        opened = await runtime.open(OpenOperation("open-1", "session", "epoch", prepared),
                                    context())
        assert opened.stage == "SUBMITTED" and opened.native_id == "native-1"
        assert await runtime.open(OpenOperation("open-1", "session", "epoch", prepared),
                                  context()) == opened
        assert factory.open_count == 1
        with pytest.raises(CoreError, match="OPERATION_CONFLICT"):
            await runtime.open(OpenOperation("open-1", "session", "other", prepared),
                               context())
        with pytest.raises(CoreError, match="PROFILE_DRIFT"):
            await runtime.open(OpenOperation("open-tampered", "other", "epoch",
                                             replace(prepared, argv=("evil",))), context())
        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await runtime.submit(TurnOperation("turn-wrong", "session", "hello"),
                                 context(agent="other"))

        turn = TurnOperation("turn-1", "session", "hello")
        receipt = await runtime.submit(turn, context())
        assert receipt.stage == "SUBMITTED" and receipt.possible_effect
        assert await runtime.submit(turn, context()) == receipt
        assert factory.native.sent == [("send_turn", {"text": "hello"}, "turn-1")]
        interrupted = await runtime.control(ControlOperation("int-1", "session", "interrupt"),
                                            context())
        assert interrupted.stage == "SUBMITTED"
        targeted = await runtime.control(ControlOperation(
            "int-target", "session", "interrupt", expected_turn_id="native-turn-1"),
            context())
        assert targeted.stage == "SUBMITTED"
        assert factory.native.targets == [None, None, "native-turn-1"]

        event = RuntimeEvent("srv", "exe", "session", "epoch", 0,
                             "turn_state", "native.started", {}, "turn-1")
        await factory.native.queue.put(event)
        cursor = EventCursor("srv", "exe", "session", "epoch")
        async def first_event():
            async for item in runtime.events(cursor):
                return item
        seen = await asyncio.wait_for(first_event(), timeout=2)
        assert seen.sequence == 1 and seen.operation_id == "turn-1"
        assert (await runtime.inspect(SessionKey("srv", "exe", "session"))).last_sequence == 1
        report = await runtime.reconcile(ReconcileRequest("srv", "exe",
                                                           ("turn-1", "missing"),
                                                           ("session", "missing")))
        assert report.receipts == (receipt, None)
        assert report.snapshots[1].ownership == "unknown"

        closed = await runtime.close(CloseOperation("close-1", "session"), context())
        assert closed.stage == "SUBMITTED" and factory.native.stopped
        assert (await runtime.shutdown(ShutdownPolicy())).session_outcomes == {
            SessionKey("srv", "exe", "session"): "already_closed"}
        journal.close()

    asyncio.run(run())


def test_native_event_reader_starts_before_open_returns(tmp_path):
    class ReaderNative(FakeNative):
        def __init__(self):
            super().__init__()
            self.reader_started = asyncio.Event()

        async def events(self):
            self.reader_started.set()
            async for event in super().events():
                yield event

        async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
            assert self.reader_started.is_set(), "native write preceded event reader"
            await super().send(verb, payload, operation_id,
                               expected_turn_id=expected_turn_id)

    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        factory.native = ReaderNative()
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        opened = await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                                    context())
        assert opened.stage == "SUBMITTED"
        assert factory.native.reader_started.is_set()
        assert (await runtime.submit(TurnOperation("first", "session", "hello"),
                                     context())).stage == "SUBMITTED"
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

    asyncio.run(run())


def test_immediate_event_reader_failure_keeps_open_outcome_unknown(tmp_path):
    class BrokenNative(FakeNative):
        async def events(self):
            raise RuntimeError("reader failed before first event")
            yield  # Keep this an async iterator.

    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        factory.native = BrokenNative()
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        with pytest.raises(CoreError, match="EVENT_STREAM_UNAVAILABLE"):
            await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                               context())
        report = await runtime.reconcile(ReconcileRequest(
            "srv", "exe", ("open",), ("session",)))
        assert report.receipts[0].stage == "OUTCOME_UNKNOWN"
        assert report.snapshots[0].ownership == "owned"
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

    asyncio.run(run())


def test_control_proven_not_sent_has_no_positive_receipt(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared), context())

        async def reject_control(verb, payload, operation_id, *, expected_turn_id=None):
            if verb == "interrupt":
                raise RuntimeCommandNotSent("still requesting")
            factory.native.sent.append((verb, dict(payload), operation_id))

        factory.native.send = reject_control
        operation = ControlOperation("int-not-sent", "session", "interrupt")
        with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED") as exc:
            await runtime.control(operation, context())
        assert exc.value.retry_safe and not exc.value.possible_effect
        report = await runtime.reconcile(ReconcileRequest("srv", "exe",
                                                           ("int-not-sent",), ()))
        receipt = report.receipts[0]
        assert receipt is not None and receipt.stage == "FAILED"
        assert not receipt.possible_effect and receipt.retry_safe
        assert factory.native.sent == []
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

    asyncio.run(run())


def test_urgent_interrupt_is_not_blocked_by_pending_native_submit(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared), context())
        entered = asyncio.Event()
        release = asyncio.Event()
        original_send = factory.native.send

        async def slow_send(verb, payload, operation_id, *, expected_turn_id=None):
            if verb == "send_turn":
                entered.set()
                await release.wait()
            await original_send(verb, payload, operation_id,
                                expected_turn_id=expected_turn_id)

        factory.native.send = slow_send
        pending = asyncio.create_task(runtime.submit(
            TurnOperation("slow", "session", "hello"), context()))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            urgent = await asyncio.wait_for(runtime.control(
                ControlOperation("urgent", "session", "interrupt"), context()),
                timeout=1)
            assert urgent.stage == "SUBMITTED"
            assert factory.native.sent == [("interrupt", {}, "urgent")]
        finally:
            release.set()
            await asyncio.wait_for(pending, timeout=2)
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    asyncio.run(run())


def test_close_waits_for_normal_write_without_blocking_urgent_control(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared), context())
        entered = asyncio.Event()
        release = asyncio.Event()
        original_send = factory.native.send

        async def slow_send(verb, payload, operation_id, *, expected_turn_id=None):
            if verb == "send_turn":
                entered.set()
                await release.wait()
                assert not factory.native.stopped
            await original_send(verb, payload, operation_id,
                                expected_turn_id=expected_turn_id)

        factory.native.send = slow_send
        pending = asyncio.create_task(runtime.submit(
            TurnOperation("slow", "session", "hello"), context()))
        closing = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            closing = asyncio.create_task(runtime.close(
                CloseOperation("close", "session"), context()))
            interrupted = await asyncio.wait_for(runtime.control(
                ControlOperation("urgent", "session", "interrupt"), context()),
                timeout=1)
            assert interrupted.stage == "SUBMITTED"
            assert not closing.done() and not factory.native.stopped
        finally:
            release.set()
            assert (await asyncio.wait_for(pending, timeout=2)).stage == "SUBMITTED"
            if closing is not None:
                assert (await asyncio.wait_for(closing, timeout=2)).stage == "SUBMITTED"
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    asyncio.run(run())


def test_shutdown_reports_unknown_without_releasing_unfinished_native_send(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path, max_owned_sessions=1)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared), context())
        entered = asyncio.Event()
        release = asyncio.Event()
        original_send = factory.native.send

        async def slow_send(verb, payload, operation_id, *, expected_turn_id=None):
            if verb == "send_turn":
                entered.set()
                await release.wait()
            await original_send(verb, payload, operation_id,
                                expected_turn_id=expected_turn_id)

        factory.native.send = slow_send
        pending = asyncio.create_task(runtime.submit(
            TurnOperation("slow", "session", "hello"), context()))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            report = await asyncio.wait_for(runtime.shutdown(
                ShutdownPolicy(drain_seconds=0.02, interrupt_seconds=0.02)),
                timeout=1)
            key = SessionKey("srv", "exe", "session")
            assert report.session_outcomes[key] == "unknown"
            assert not factory.native.stopped
            assert (await runtime.inspect(key)).ownership == "owned"
        finally:
            release.set()
            assert (await asyncio.wait_for(pending, timeout=2)).stage == "SUBMITTED"
            await asyncio.wait_for(runtime.shutdown(ShutdownPolicy()), timeout=2)
            journal.close()

    asyncio.run(run())


def test_pending_public_close_does_not_hold_runtime_lock_or_shutdown(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                           context())
        entered = asyncio.Event()
        release = asyncio.Event()
        original_close = factory.native.close

        async def slow_close():
            entered.set()
            await release.wait()
            return await original_close()

        factory.native.close = slow_close
        closing = asyncio.create_task(runtime.close(
            CloseOperation("close", "session"), context()))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            key = SessionKey("srv", "exe", "session")
            assert (await asyncio.wait_for(runtime.inspect(key),
                                           timeout=1)).ownership == "owned"
            with pytest.raises(CoreError, match="SESSION_UNKNOWN"):
                await runtime.renew_lease(
                    key, replace(context(), connection_generation=4,
                                 lease_deadline_monotonic=time.monotonic() + 120),
                    expected_connection_generation=3)
            report = await asyncio.wait_for(runtime.shutdown(
                ShutdownPolicy(drain_seconds=0.02, interrupt_seconds=0.02)),
                timeout=1)
            assert report.session_outcomes[key] == "unknown"
        finally:
            release.set()
            assert (await asyncio.wait_for(closing, timeout=2)).stage == "SUBMITTED"
            await asyncio.wait_for(runtime.shutdown(ShutdownPolicy()), timeout=2)
            journal.close()

    asyncio.run(run())


def test_pending_lease_close_does_not_hold_runtime_lock_or_shutdown(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(
            tmp_path, clock=clock, lease_grace_seconds=0,
            lease_poll_seconds=0.01)
        initial = replace(context(), lease_deadline_monotonic=101)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         initial)
        await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                           initial)
        entered = asyncio.Event()
        release = asyncio.Event()
        original_close = factory.native.close

        async def slow_close():
            entered.set()
            await release.wait()
            return await original_close()

        factory.native.close = slow_close
        try:
            clock.advance(1.1)
            await asyncio.wait_for(entered.wait(), timeout=2)
            key = SessionKey("srv", "exe", "session")
            assert (await asyncio.wait_for(runtime.inspect(key),
                                           timeout=1)).ownership == "owned"
            report = await asyncio.wait_for(runtime.shutdown(
                ShutdownPolicy(drain_seconds=0.02, interrupt_seconds=0.02)),
                timeout=1)
            assert report.session_outcomes[key] == "unknown"
        finally:
            release.set()
            await asyncio.wait_for(runtime.shutdown(ShutdownPolicy()), timeout=2)
            journal.close()

    asyncio.run(run())


def test_monotonic_rollback_expires_open_lease_without_native_replay(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(
            tmp_path, clock=clock, lease_grace_seconds=0,
            lease_poll_seconds=0.01)
        auth = replace(context(), lease_deadline_monotonic=120)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         auth)
        opened = await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                                    auth)
        assert opened.stage == "SUBMITTED"
        clock.advance(1)
        assert (await runtime.inspect(SessionKey("srv", "exe", "session"))).ownership == "owned"
        clock.now = 99
        with pytest.raises(CoreError, match="AGENT_REVOKED"):
            await runtime.submit(TurnOperation("after-rollback", "session", "hello"), auth)
        assert factory.native.sent == []
        assert await journal.get_receipt(OperationKey("srv", "exe", "after-rollback")) is None
        clock.now = 110
        # The rollback fence and the lease watcher race to refuse the
        # renewal; either refusal proves the invariant (a rolled-back
        # clock never revives the lease). No native write may happen.
        with pytest.raises(CoreError, match="AGENT_REVOKED|SESSION_UNKNOWN|SESSION_CLOSING"):
            await runtime.renew_lease(
                SessionKey("srv", "exe", "session"),
                replace(auth, lease_deadline_monotonic=130),
                expected_connection_generation=auth.connection_generation)
        assert factory.native.sent == []
        for _ in range(1000):  # event barrier with a generous bound
            if factory.native.stopped:
                break
            await asyncio.sleep(0.01)
        assert factory.native.stopped
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

    asyncio.run(run())


def test_slow_close_does_not_block_other_sessions_during_shutdown(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        release = asyncio.Event()
        slow = FakeNative()
        fast = FakeNative()
        original_close = slow.close

        async def slow_close():
            await release.wait()
            return await original_close()

        slow.close = slow_close

        async def open_for(prepared, session_id, auth, *, stream_epoch):
            return slow if session_id == "slow" else fast

        factory.open = open_for
        await runtime.open(OpenOperation("open-slow", "slow", "slow-epoch", prepared),
                           context())
        await runtime.open(OpenOperation("open-fast", "fast", "fast-epoch", prepared),
                           context())
        try:
            report = await asyncio.wait_for(runtime.shutdown(
                ShutdownPolicy(drain_seconds=0.02, interrupt_seconds=0.02)),
                timeout=1)
            assert report.session_outcomes[SessionKey("srv", "exe", "slow")] == "unknown"
            assert report.session_outcomes[SessionKey("srv", "exe", "fast")] == "graceful"
            assert fast.stopped and not slow.stopped
        finally:
            release.set()
            await asyncio.wait_for(runtime.shutdown(ShutdownPolicy()), timeout=2)
            journal.close()

    asyncio.run(run())


def test_shutdown_drains_active_turn_then_journals_interrupt_before_close(tmp_path):
    class ActiveNative(FakeNative):
        def __init__(self):
            super().__init__()
            self.active = True
            self.interrupted = asyncio.Event()
            self.release = asyncio.Event()

        def active_turn(self):
            return self.active

        async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
            if verb == "interrupt":
                self.interrupted.set()
                await self.release.wait()
                self.active = False
            await super().send(verb, payload, operation_id,
                               expected_turn_id=expected_turn_id)

    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        native = ActiveNative()

        async def open_active(prepared, session_id, auth, *, stream_epoch):
            return native

        factory.open = open_active
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                           context())
        shutting_down = asyncio.create_task(runtime.shutdown(
            ShutdownPolicy(drain_seconds=0.04, interrupt_seconds=0.2)))
        try:
            await asyncio.sleep(0.01)
            assert not native.stopped
            assert not native.interrupted.is_set()
            await asyncio.wait_for(native.interrupted.wait(), timeout=1)
            receipt = journal._run_sync(lambda db: db.execute(
                "SELECT stage,possible_effect FROM operations_v2 WHERE operation_id LIKE 'core.internal.shutdown_interrupt.%'"
            ).fetchone())
            assert receipt == ("SUBMISSION_STARTED", 1)
            assert not native.stopped
        finally:
            native.release.set()
            report = await asyncio.wait_for(shutting_down, timeout=2)
            assert report.session_outcomes[SessionKey("srv", "exe", "session")] == "graceful"
            receipt = journal._run_sync(lambda db: db.execute(
                "SELECT stage FROM operations_v2 WHERE operation_id LIKE 'core.internal.shutdown_interrupt.%'"
            ).fetchone())
            assert receipt == ("SUBMITTED",)
            journal.close()

    asyncio.run(run())


def test_shutdown_active_turn_settles_during_drain_without_interrupt(tmp_path):
    class SettlingNative(FakeNative):
        def __init__(self):
            super().__init__()
            self.active = True

        def active_turn(self):
            return self.active

    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        native = SettlingNative()

        async def open_settling(prepared, session_id, auth, *, stream_epoch):
            return native

        factory.open = open_settling
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                           context())
        shutting_down = asyncio.create_task(runtime.shutdown(
            ShutdownPolicy(drain_seconds=0.2, interrupt_seconds=0.1)))
        await asyncio.sleep(0.02)
        assert not native.stopped
        native.active = False
        report = await asyncio.wait_for(shutting_down, timeout=1)
        assert report.session_outcomes[SessionKey("srv", "exe", "session")] == "graceful"
        assert not any(verb == "interrupt" for verb, _, _ in native.sent)
        assert journal._run_sync(lambda db: db.execute(
            "SELECT COUNT(*) FROM operations_v2 WHERE operation_id LIKE 'core.internal.shutdown_interrupt.%'"
        ).fetchone())[0] == 0
        journal.close()

    asyncio.run(run())


def test_shutdown_interrupt_refusal_records_safe_failure_and_closes(tmp_path):
    class RefusingNative(FakeNative):
        def active_turn(self):
            return True

        async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
            if verb == "interrupt":
                raise RuntimeCommandNotSent("native cannot interrupt now",
                                            code="NATIVE_CONTROL_UNSAFE")
            await super().send(verb, payload, operation_id,
                               expected_turn_id=expected_turn_id)

    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        native = RefusingNative()

        async def open_refusing(prepared, session_id, auth, *, stream_epoch):
            return native

        factory.open = open_refusing
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                           context())
        # This verifies the durable refusal receipt and subsequent close, not
        # sub-100 ms filesystem scheduling on a loaded Windows runner.
        report = await runtime.shutdown(ShutdownPolicy(
            drain_seconds=0.01, interrupt_seconds=5))
        assert report.session_outcomes[SessionKey("srv", "exe", "session")] == "graceful"
        assert journal._run_sync(lambda db: db.execute(
            "SELECT stage,possible_effect,retry_safe,error_code FROM operations_v2 WHERE operation_id LIKE 'core.internal.shutdown_interrupt.%'"
        ).fetchone()) == ("FAILED", 0, 1, "NATIVE_CONTROL_UNSAFE")
        journal.close()

    asyncio.run(run())


def test_shutdown_pending_interrupt_keeps_owned_slot_until_late_close(tmp_path):
    class StuckInterrupt(FakeNative):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        def active_turn(self):
            return True

        async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
            if verb == "interrupt":
                self.entered.set()
                await self.release.wait()
            await super().send(verb, payload, operation_id,
                               expected_turn_id=expected_turn_id)

    async def run():
        runtime, journal, factory = make_runtime(tmp_path, max_owned_sessions=1)
        native = StuckInterrupt()

        async def open_stuck(prepared, session_id, auth, *, stream_epoch):
            return native

        factory.open = open_stuck
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                           context())
        key = SessionKey("srv", "exe", "session")
        try:
            shutting_down = asyncio.create_task(runtime.shutdown(
                ShutdownPolicy(drain_seconds=0.01, interrupt_seconds=0.02)))
            # Race barrier (plan §4): wait for the interrupt to actually
            # enter the native send instead of assuming a wall-clock
            # budget; the send is stuck by design, so shutdown stays
            # pending and the slot must stay owned meanwhile.
            assert await asyncio.wait_for(native.entered.wait(), timeout=10)
            assert (await runtime.inspect(key)).ownership == "owned"
            assert not native.stopped
        finally:
            native.release.set()
            try:
                report = await asyncio.wait_for(shutting_down, timeout=10)
            except asyncio.TimeoutError:
                report = None
            if report is not None:
                assert report.session_outcomes[key] == "unknown"
            second = await asyncio.wait_for(runtime.shutdown(ShutdownPolicy()),
                                            timeout=10)
            assert second.session_outcomes[key] == "graceful"
            assert (await runtime.inspect(key)).ownership == "released"
            journal.close()

    asyncio.run(run())


def test_shutdown_force_request_does_not_release_pending_native_effect(tmp_path):
    class ForceNative(FakeNative):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.forced = asyncio.Event()
            self.journal = None
            self.stage_at_force = None

        async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
            if verb == "send_turn":
                self.entered.set()
                await self.release.wait()
            await super().send(verb, payload, operation_id,
                               expected_turn_id=expected_turn_id)

        async def force_stop(self):
            self.stage_at_force = self.journal._run_sync(lambda db: db.execute(
                "SELECT stage FROM operations_v2 WHERE operation_id LIKE 'core.internal.shutdown_force.%'"
            ).fetchone())
            self.forced.set()
            self.stopped = True
            await self.queue.put(None)

    async def run():
        runtime, journal, factory = make_runtime(tmp_path, max_owned_sessions=1)
        native = ForceNative()
        native.journal = journal

        async def open_force(prepared, session_id, auth, *, stream_epoch):
            return native

        factory.open = open_force
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                           context())
        pending = asyncio.create_task(runtime.submit(
            TurnOperation("slow", "session", "hello"), context()))
        key = SessionKey("srv", "exe", "session")
        try:
            await asyncio.wait_for(native.entered.wait(), timeout=2)
            report = await asyncio.wait_for(runtime.shutdown(
                ShutdownPolicy(drain_seconds=0.01, interrupt_seconds=0.02)),
                timeout=1)
            assert native.forced.is_set()
            # C4/T01: the physical force no longer waits for the journal
            # admission, so the admission may land after the dispatch -
            # the old synchronous stage_at_force expectation encoded the
            # pre-C4 storage-before-force order the reaudit removed. The
            # causal invariants stay: unknown outcome, owned slot, pending
            # submit unresolved, and the durable force receipt eventually
            # recorded (asserted after release below).
            assert report.session_outcomes[key] == "unknown"
            assert (await runtime.inspect(key)).ownership == "owned"
            assert not pending.done()
        finally:
            native.release.set()
            assert (await asyncio.wait_for(pending, timeout=2)).stage == "SUBMITTED"
            second = await asyncio.wait_for(runtime.shutdown(ShutdownPolicy()),
                                            timeout=2)
            assert second.session_outcomes[key] in {"unknown", "already_closed"}
            assert (await runtime.inspect(key)).ownership == "released"
            # The force bookkeeping runs as a background task; wait for its
            # durable receipt instead of racing it with a synchronous read.
            async def force_receipt_settled():
                while True:
                    row = await asyncio.to_thread(journal._run_sync, lambda db: db.execute(
                        "SELECT stage FROM operations_v2 WHERE operation_id LIKE 'core.internal.shutdown_force.%'"
                    ).fetchone())
                    if row == ("SUBMITTED",):
                        return row
                    await asyncio.sleep(0)
            assert await asyncio.wait_for(force_receipt_settled(), timeout=2)
            journal.close()

    asyncio.run(run())


def test_force_scheduler_never_targets_external_attach(tmp_path):
    class ExternalNative(FakeNative):
        def __init__(self):
            super().__init__()
            self.forced = False

        async def force_stop(self):
            self.forced = True

    async def run():
        runtime, journal, _ = make_runtime(tmp_path)
        native = ExternalNative()
        binding = _Session(native, context(), "epoch", "claude_attach")
        runtime._schedule_force(SessionKey("srv", "exe", "external"), binding,
                                asyncio.get_running_loop().time(), immediate=True)
        await asyncio.sleep(0)
        assert binding.force_task is None
        assert not native.forced
        journal.close()

    asyncio.run(run())


def test_shutdown_does_not_drain_an_already_closed_session(tmp_path):
    class StaleActiveNative(FakeNative):
        def active_turn(self):
            return True

    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        native = StaleActiveNative()

        async def open_stale(prepared, session_id, auth, *, stream_epoch):
            return native

        factory.open = open_stale
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                           context())
        await runtime.close(CloseOperation("close", "session"), context())
        report = await asyncio.wait_for(runtime.shutdown(ShutdownPolicy()),
                                        timeout=1)
        assert report.session_outcomes[SessionKey("srv", "exe", "session")] == "already_closed"
        assert not any(verb == "interrupt" for verb, _, _ in native.sent)
        journal.close()

    asyncio.run(run())


def test_slow_open_does_not_block_existing_session_or_escape_shutdown(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open-a", "session-a", "epoch-a", prepared),
                           context())
        second = FakeNative()
        entered = asyncio.Event()
        release = asyncio.Event()
        original_open = factory.open

        async def slow_open(prepared, session_id, auth, *, stream_epoch):
            if session_id == "session-b":
                entered.set()
                await release.wait()
                return second
            return await original_open(prepared, session_id, auth,
                                       stream_epoch=stream_epoch)

        factory.open = slow_open
        pending = asyncio.create_task(runtime.open(
            OpenOperation("open-b", "session-b", "epoch-b", prepared), context()))
        shutting_down = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            urgent = await asyncio.wait_for(runtime.control(
                ControlOperation("interrupt-a", "session-a", "interrupt"), context()),
                timeout=1)
            assert urgent.stage == "SUBMITTED"
            with pytest.raises(CoreError, match="SESSION_CONFLICT"):
                await asyncio.wait_for(runtime.open(
                    OpenOperation("conflicting-open", "session-b", "epoch-b", prepared),
                    context()), timeout=1)
            shutting_down = asyncio.create_task(runtime.shutdown(ShutdownPolicy()))
            await asyncio.sleep(0)
            assert not shutting_down.done()
        finally:
            release.set()
            assert (await asyncio.wait_for(pending, timeout=2)).stage == "SUBMITTED"
            if shutting_down is None:
                shutting_down = asyncio.create_task(runtime.shutdown(ShutdownPolicy()))
            report = await asyncio.wait_for(shutting_down, timeout=2)
            assert set(report.session_outcomes) == {
                SessionKey("srv", "exe", "session-a"),
                SessionKey("srv", "exe", "session-b"),
            }
            assert second.stopped
            journal.close()

    asyncio.run(run())


def test_shutdown_times_out_pending_open_and_closes_late_native_session(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        entered = asyncio.Event()
        release = asyncio.Event()
        native = FakeNative()

        async def late_open(prepared, session_id, auth, *, stream_epoch):
            entered.set()
            await release.wait()
            return native

        factory.open = late_open
        opening = asyncio.create_task(runtime.open(
            OpenOperation("open", "session", "epoch", prepared), context()))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            report = await asyncio.wait_for(runtime.shutdown(
                ShutdownPolicy(drain_seconds=0.02, interrupt_seconds=0.02)),
                timeout=1)
            assert report.session_outcomes == {
                SessionKey("srv", "exe", "session"): "unknown"}
            assert not native.stopped
        finally:
            release.set()
            assert (await asyncio.wait_for(opening, timeout=2)).stage == "SUBMITTED"
            async def stopped():
                while not native.stopped:
                    await asyncio.sleep(0)
            await asyncio.wait_for(stopped(), timeout=2)
            assert (await runtime.inspect(SessionKey(
                "srv", "exe", "session"))).ownership == "released"
            journal.close()

    asyncio.run(run())


def test_cancelled_open_releases_shutdown_reservation(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        entered = asyncio.Event()
        never = asyncio.Event()

        async def pending_open(prepared, session_id, auth, *, stream_epoch):
            entered.set()
            await never.wait()
            raise AssertionError("cancelled launch continued")

        factory.open = pending_open
        opening = asyncio.create_task(runtime.open(
            OpenOperation("cancelled", "session", "epoch", prepared), context()))
        await asyncio.wait_for(entered.wait(), timeout=2)
        # C6/V02c adaptation: the attempt outlives its cancelled waiter
        # (the producer can still spawn), so shutdown waits its OWN
        # budget for it - a short policy keeps the causal invariant
        # ("cancelled open never wedges shutdown beyond its budget").
        shutdown = asyncio.create_task(runtime.shutdown(
            ShutdownPolicy(drain_seconds=0.05, interrupt_seconds=0.05)))
        await asyncio.sleep(0)
        assert not shutdown.done()
        opening.cancel()
        with pytest.raises(asyncio.CancelledError):
            await opening
        assert (await asyncio.wait_for(shutdown, timeout=2)).session_outcomes == {
            SessionKey("srv", "exe", "session"): "unknown"}
        report = await runtime.reconcile(ReconcileRequest(
            "srv", "exe", ("cancelled",), ("session",)))
        assert report.receipts[0].stage == "OUTCOME_UNKNOWN"
        assert report.snapshots[0].ownership == "unknown"
        journal.close()

    asyncio.run(run())


def test_concurrent_open_limit_rejects_before_admission_and_releases_slot(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path, max_concurrent_opens=1)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        entered = asyncio.Event()
        release = asyncio.Event()
        created = []

        async def slow_open(prepared, session_id, auth, *, stream_epoch):
            if session_id == "session-a":
                entered.set()
                await release.wait()
            native = FakeNative()
            created.append(native)
            return native

        factory.open = slow_open
        first = asyncio.create_task(runtime.open(
            OpenOperation("open-a", "session-a", "epoch-a", prepared), context()))
        second = OpenOperation("open-b", "session-b", "epoch-b", prepared)
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            with pytest.raises(CoreError, match="CAPACITY_EXCEEDED") as denied:
                await runtime.open(second, context())
            assert denied.value.retry_safe and not denied.value.possible_effect
            assert (await runtime.reconcile(ReconcileRequest(
                "srv", "exe", ("open-b",), ()))).receipts == (None,)
        finally:
            release.set()
            assert (await asyncio.wait_for(first, timeout=2)).stage == "SUBMITTED"
        assert (await runtime.open(second, context())).stage == "SUBMITTED"
        assert len(created) == 2
        await runtime.shutdown(ShutdownPolicy())
        assert all(native.stopped for native in created)
        journal.close()

    asyncio.run(run())


def test_owned_session_limit_releases_only_after_observed_stop(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path, max_owned_sessions=1)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        first = OpenOperation("open-a", "session-a", "epoch-a", prepared)
        second = OpenOperation("open-b", "session-b", "epoch-b", prepared)
        assert (await runtime.open(first, context())).stage == "SUBMITTED"
        with pytest.raises(CoreError, match="CAPACITY_EXCEEDED") as denied:
            await runtime.open(second, context())
        assert denied.value.retry_safe and not denied.value.possible_effect
        assert (await runtime.reconcile(ReconcileRequest(
            "srv", "exe", ("open-b",), ()))).receipts == (None,)
        await runtime.close(CloseOperation("close-a", "session-a"), context())
        factory.native = FakeNative()
        assert (await runtime.open(second, context())).stage == "SUBMITTED"
        assert (await runtime.shutdown(ShutdownPolicy())).session_outcomes[
            SessionKey("srv", "exe", "session-b")] == "graceful"
        journal.close()

    asyncio.run(run())


def test_shared_journal_slot_fences_two_runtime_instances(tmp_path):
    async def run():
        limits = replace(JournalLimits(), max_owned_slots=1)
        first, journal_a, factory_a = make_runtime(
            tmp_path, journal_limits=limits, max_owned_sessions=32)
        second, journal_b, factory_b = make_runtime(
            tmp_path, journal_limits=limits, max_owned_sessions=32)
        prepared = await first.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())
        try:
            assert (await first.open(OpenOperation(
                "open-a", "session-a", "epoch-a", prepared), context())).stage == "SUBMITTED"
            with pytest.raises(CoreError, match="CAPACITY_EXCEEDED") as denied:
                await second.open(OpenOperation(
                    "open-b", "session-b", "epoch-b", prepared), context())
            assert denied.value.retry_safe and not denied.value.possible_effect
            assert factory_b.open_count == 0
            refused = await journal_b.get_receipt(OperationKey("srv", "exe", "open-b"))
            assert refused is not None and refused.stage == "FAILED"
            assert refused.retry_safe and not refused.possible_effect
            assert SessionKey("srv", "exe", "session-b") not in second._uncertain_opens
            await first.close(CloseOperation("close-a", "session-a"), context())
            assert (await second.open(OpenOperation(
                "open-c", "session-c", "epoch-c", prepared), context())).stage == "SUBMITTED"
            assert factory_b.open_count == 1
            await second.shutdown(ShutdownPolicy())
        finally:
            journal_a.close()
            journal_b.close()

    asyncio.run(run())


def test_installation_ledger_fences_distinct_executor_journals(tmp_path):
    async def run():
        first_root, second_root = tmp_path / "first", tmp_path / "second"
        first_root.mkdir()
        second_root.mkdir()
        ledger_path = tmp_path / "installation-slots.db"
        ledger_a = SQLiteOwnedSlotLedger(ledger_path, max_slots=1)
        ledger_b = SQLiteOwnedSlotLedger(ledger_path, max_slots=1)
        first, journal_a, factory_a = make_runtime(
            first_root, owned_slot_ledger=ledger_a, max_owned_sessions=32)
        second, journal_b, factory_b = make_runtime(
            second_root, owned_slot_ledger=ledger_b, max_owned_sessions=32)
        prepared_a = await first.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())
        prepared_b = await second.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())
        try:
            assert journal_a.path != journal_b.path
            assert (await first.open(OpenOperation(
                "open-a", "session-a", "epoch-a", prepared_a), context())).stage == "SUBMITTED"
            with pytest.raises(CoreError, match="CAPACITY_EXCEEDED") as denied:
                await second.open(OpenOperation(
                    "open-b", "session-b", "epoch-b", prepared_b), context())
            assert denied.value.retry_safe and not denied.value.possible_effect
            assert factory_b.open_count == 0
            assert (await journal_b.get_receipt(OperationKey(
                "srv", "exe", "open-b"))).stage == "FAILED"
            await first.close(CloseOperation("close-a", "session-a"), context())
            assert (await second.open(OpenOperation(
                "open-c", "session-c", "epoch-c", prepared_b), context())).stage == "SUBMITTED"
            assert factory_b.open_count == 1
            await second.shutdown(ShutdownPolicy())
            assert ledger_a._run_sync(lambda db: db.execute(
                "SELECT COUNT(*) FROM owned_slot_reservations WHERE released=0"
            ).fetchone())[0] == 0
        finally:
            journal_a.close()
            journal_b.close()
            ledger_a.close()
            ledger_b.close()

    asyncio.run(run())


def test_installation_ledger_retains_ambiguous_launch_across_journals(tmp_path):
    async def run():
        first_root, second_root = tmp_path / "first", tmp_path / "second"
        first_root.mkdir()
        second_root.mkdir()
        ledger_path = tmp_path / "installation-slots.db"
        ledger_a = SQLiteOwnedSlotLedger(ledger_path, max_slots=1)
        first, journal_a, factory_a = make_runtime(
            first_root, owned_slot_ledger=ledger_a)
        prepared_a = await first.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())

        async def ambiguous_open(*args, **kwargs):
            raise RuntimeError("synthetic ambiguous launch")

        factory_a.open = ambiguous_open
        try:
            with pytest.raises(RuntimeError, match="ambiguous"):
                await first.open(OpenOperation(
                    "open-a", "session-a", "epoch-a", prepared_a), context())
            receipt = await journal_a.get_receipt(OperationKey("srv", "exe", "open-a"))
            assert receipt is not None and receipt.stage == "OUTCOME_UNKNOWN"
        finally:
            journal_a.close()
            ledger_a.close()

        ledger_b = SQLiteOwnedSlotLedger(ledger_path, max_slots=1)
        second, journal_b, factory_b = make_runtime(
            second_root, owned_slot_ledger=ledger_b)
        prepared_b = await second.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())
        try:
            with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
                await second.open(OpenOperation(
                    "open-b", "session-b", "epoch-b", prepared_b), context())
            assert factory_b.open_count == 0
            assert ledger_b._run_sync(lambda db: db.execute(
                "SELECT COUNT(*) FROM owned_slot_reservations WHERE released=0"
            ).fetchone())[0] == 1
        finally:
            journal_b.close()
            ledger_b.close()

    asyncio.run(run())


def test_uncertain_open_pins_shared_journal_slot_across_reopen(tmp_path):
    async def run():
        limits = replace(JournalLimits(), max_owned_slots=1)
        first, journal_a, factory = make_runtime(
            tmp_path, journal_limits=limits)
        prepared = await first.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())

        async def ambiguous_open(*args, **kwargs):
            raise RuntimeError("synthetic ambiguous native launch")

        factory.open = ambiguous_open
        try:
            with pytest.raises(RuntimeError, match="ambiguous"):
                await first.open(OpenOperation(
                    "open-a", "session-a", "epoch-a", prepared), context())
            receipt = await journal_a.get_receipt(OperationKey("srv", "exe", "open-a"))
            assert receipt is not None and receipt.stage == "OUTCOME_UNKNOWN"
        finally:
            journal_a.close()

        second, journal_b, factory_b = make_runtime(
            tmp_path, journal_limits=limits)
        try:
            with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
                await second.open(OpenOperation(
                    "open-b", "session-b", "epoch-b", prepared), context())
            assert factory_b.open_count == 0
            assert journal_b._run_sync(lambda db: db.execute(
                "SELECT COUNT(*) FROM owned_slot_reservations WHERE released=0"
            ).fetchone())[0] == 1
        finally:
            journal_b.close()

    asyncio.run(run())


def test_proven_prelaunch_refusal_releases_shared_slot(tmp_path):
    async def run():
        limits = replace(JournalLimits(), max_owned_slots=1)
        first, journal_a, factory = make_runtime(
            tmp_path, journal_limits=limits)
        prepared = await first.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), context())

        async def refused_open(*args, **kwargs):
            raise CoreError("NATIVE_VERSION_UNQUALIFIED", "open",
                            retry_safe=True)

        factory.open = refused_open
        try:
            with pytest.raises(CoreError, match="NATIVE_VERSION_UNQUALIFIED"):
                await first.open(OpenOperation(
                    "open-a", "session-a", "epoch-a", prepared), context())
            assert journal_a._run_sync(lambda db: db.execute(
                "SELECT released FROM owned_slot_reservations"
            ).fetchone()) == (1,)
            assert SessionKey("srv", "exe", "session-a") not in first._uncertain_opens
        finally:
            journal_a.close()

        second, journal_b, factory_b = make_runtime(
            tmp_path, journal_limits=limits)
        try:
            assert (await second.open(OpenOperation(
                "open-b", "session-b", "epoch-b", prepared), context())).stage == "SUBMITTED"
            assert factory_b.open_count == 1
            await second.shutdown(ShutdownPolicy())
        finally:
            journal_b.close()

    asyncio.run(run())


def test_pending_open_uses_owned_slot_even_with_spare_launch_capacity(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(
            tmp_path, max_concurrent_opens=2, max_owned_sessions=1)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow_open(prepared, session_id, auth, *, stream_epoch):
            entered.set()
            await release.wait()
            return FakeNative()

        factory.open = slow_open
        first = asyncio.create_task(runtime.open(
            OpenOperation("open-a", "session-a", "epoch-a", prepared), context()))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
                await runtime.open(OpenOperation(
                    "open-b", "session-b", "epoch-b", prepared), context())
        finally:
            release.set()
            assert (await asyncio.wait_for(first, timeout=2)).stage == "SUBMITTED"
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    asyncio.run(run())


def test_uncertain_owned_close_retains_session_capacity(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path, max_owned_sessions=1)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open-a", "session-a", "epoch-a", prepared),
                           context())

        async def unknown_close():
            return "unknown"

        factory.native.close = unknown_close
        with pytest.raises(CoreError, match="OUTCOME_UNKNOWN"):
            await runtime.close(CloseOperation("close-a", "session-a"), context())
        with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
            await runtime.open(OpenOperation("open-b", "session-b", "epoch-b", prepared),
                               context())
        assert (await runtime.shutdown(ShutdownPolicy())).session_outcomes == {
            SessionKey("srv", "exe", "session-a"): "unknown"}
        journal.close()

    asyncio.run(run())


def test_ambiguous_native_open_retains_capacity_without_a_session_handle(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path, max_owned_sessions=1)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())

        async def ambiguous_open(prepared, session_id, auth, *, stream_epoch):
            raise RuntimeError("native factory may have spawned before failing")

        factory.open = ambiguous_open
        with pytest.raises(RuntimeError, match="may have spawned"):
            await runtime.open(OpenOperation("open-a", "session-a", "epoch-a", prepared),
                               context())
        receipt = (await runtime.reconcile(ReconcileRequest(
            "srv", "exe", ("open-a",), ("session-a",)))).receipts[0]
        assert receipt.stage == "OUTCOME_UNKNOWN" and receipt.possible_effect
        with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
            await runtime.open(OpenOperation("open-b", "session-b", "epoch-b", prepared),
                               context())
        assert (await runtime.shutdown(ShutdownPolicy())).session_outcomes == {
            SessionKey("srv", "exe", "session-a"): "unknown"}
        journal.close()

    asyncio.run(run())


def test_proven_prelaunch_rejection_does_not_consume_owned_capacity(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path, max_owned_sessions=1)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())

        async def safe_rejection(prepared, session_id, auth, *, stream_epoch):
            raise CoreError("NATIVE_VERSION_UNQUALIFIED", "open", retry_safe=True)

        factory.open = safe_rejection
        operation = OpenOperation("open-a", "session-a", "epoch-a", prepared)
        with pytest.raises(CoreError, match="NATIVE_VERSION_UNQUALIFIED"):
            await runtime.open(operation, context())
        receipt = (await runtime.reconcile(ReconcileRequest(
            "srv", "exe", ("open-a",), ()))).receipts[0]
        assert receipt.stage == "FAILED" and receipt.retry_safe
        assert not receipt.possible_effect
        factory.open = FakeFactory().open
        with pytest.raises(CoreError, match="SESSION_CONFLICT"):
            await runtime.open(OpenOperation(
                "open-a-new-id", "session-a", "epoch-a", prepared), context())
        assert (await runtime.open(OpenOperation(
            "open-b", "session-b", "epoch-b", prepared), context())).stage == "SUBMITTED"
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

    asyncio.run(run())


def test_steer_is_authorized_and_codex_only(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        allowed = context(actions={"runtime.open", "turn.steer", "runtime.close"})
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         allowed)
        await runtime.open(OpenOperation("open", "session", "epoch", prepared), allowed)
        operation = ControlOperation("steer", "session", "steer", "new direction",
                                     "native-turn-1")
        receipt = await runtime.control(operation, allowed)
        assert receipt.stage == "SUBMITTED"
        assert factory.native.sent == [("steer", {"text": "new direction"}, "steer")]
        assert factory.native.targets == ["native-turn-1"]
        with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED"):
            await runtime.control(ControlOperation("no-target", "session", "steer",
                                                   "new direction"), allowed)
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

    asyncio.run(run())


def test_non_codex_steer_refused_before_admission(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path, adapter_id="claude_stream")
        allowed = context(actions={"runtime.open", "turn.steer", "runtime.close"})
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "claude_stream"),
                                         allowed)
        await runtime.open(OpenOperation("open", "session", "epoch", prepared), allowed)
        operation = ControlOperation("steer", "session", "steer", "new direction",
                                     "native-turn-1")
        with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED"):
            await runtime.control(operation, allowed)
        assert factory.native.sent == []
        assert (await runtime.reconcile(ReconcileRequest("srv", "exe", ("steer",), ())))\
            .receipts == (None,)
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

    asyncio.run(run())


def test_pi_steer_is_admitted_without_native_turn_id(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path, adapter_id="pi_rpc")
        allowed = context(actions={"runtime.open", "turn.steer", "runtime.close"})
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "pi_rpc"),
                                         allowed)
        await runtime.open(OpenOperation("open", "session", "epoch", prepared), allowed)
        receipt = await runtime.control(
            ControlOperation("steer", "session", "steer", "new direction"),
            allowed)
        assert receipt.stage == "SUBMITTED"
        assert factory.native.sent == [("steer", {"text": "new direction"}, "steer")]
        assert factory.native.targets == [None]
        # Pi's wire has no native turn vocabulary: naming one is refused
        # before admission instead of being silently ignored or coerced.
        with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED"):
            await runtime.control(ControlOperation(
                "native-target", "session", "steer", "new direction",
                "native-turn-1"), allowed)
        assert (await runtime.reconcile(ReconcileRequest(
            "srv", "exe", ("native-target",), ()))).receipts == (None,)
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

    asyncio.run(run())


def test_stream_fault_does_not_claim_process_was_released(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open-1", "session", "epoch", prepared),
                           context())
        wrong = RuntimeEvent("different-server", "exe", "session", "epoch", 0,
                             "turn_state", "native.started", {})
        await factory.native.queue.put(wrong)
        cursor = EventCursor("srv", "exe", "session", "epoch")

        async def diagnostic():
            async for item in runtime.events(cursor):
                if item.native_type == "core.event_pump_failed":
                    return item

        item = await asyncio.wait_for(diagnostic(), timeout=2)
        assert item.payload["code"] == "EVENT_STREAM_UNAVAILABLE"
        snapshot = await runtime.inspect(SessionKey("srv", "exe", "session"))
        assert snapshot.ownership == "owned" and snapshot.turn_state == "UNKNOWN"
        with pytest.raises(CoreError, match="EVENT_STREAM_UNAVAILABLE"):
            await runtime.submit(TurnOperation("turn-1", "session", "hello"), context())
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

    asyncio.run(run())


def test_restart_returns_known_receipt_without_reopening_native(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        operation = OpenOperation("open-1", "session", "epoch", prepared)
        first = await runtime.open(operation, context())
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

        reopened_journal = SQLiteJournal(tmp_path / "journal.db")
        fresh = FakeFactory()
        second_runtime = LocalRuntimeCore(reopened_journal, fresh,
                                          candidates={}, workspace_roots={})
        assert await second_runtime.open(operation, context()) == first
        assert fresh.open_count == 0
        assert (await second_runtime.inspect(SessionKey("srv", "exe", "session"))).ownership == "unknown"
        reopened_journal.close()

    asyncio.run(run())


def test_restart_rejects_new_open_operation_for_claimed_session(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        old = OpenOperation("open-1", "session", "epoch", prepared)
        await runtime.open(old, context())
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

        reopened_journal = SQLiteJournal(tmp_path / "journal.db")
        fresh = FakeFactory()
        second_runtime = LocalRuntimeCore(
            reopened_journal, fresh, candidates=runtime._candidates,
            workspace_roots={"ws": str(tmp_path)})
        with pytest.raises(CoreError, match="SESSION_CONFLICT"):
            await second_runtime.open(
                OpenOperation("open-2", "session", "epoch-2", prepared), context())
        assert fresh.open_count == 0
        assert (await second_runtime.reconcile(ReconcileRequest(
            "srv", "exe", ("open-2",), ()))).receipts == (None,)
        reopened_journal.close()

    asyncio.run(run())


def test_two_servers_can_reuse_operation_and_session_ids(tmp_path):
    class TwoSessionFactory:
        def __init__(self):
            self.sessions = []

        async def open(self, prepared, session_id, context, *, stream_epoch):
            native = FakeNative()
            self.sessions.append(native)
            return native

    async def run():
        binary = tmp_path / "codex"
        binary.write_bytes(b"synthetic binary")
        candidate = InstallationCandidate("codex_app_server", str(binary),
                                          fingerprint(binary), "explicit", "selected")
        journal = SQLiteJournal(tmp_path / "journal.db")
        factory = TwoSessionFactory()
        runtime = LocalRuntimeCore(journal, factory,
                                   candidates={"codex_app_server": candidate},
                                   workspace_roots={"ws": str(tmp_path)})
        intent = LaunchIntent("agent", "ws", "codex_app_server")
        prepared = await runtime.prepare(intent, context(server="srv-a"))
        operation = OpenOperation("same-open", "same-session", "epoch", prepared)
        a = await runtime.open(operation, context(server="srv-a"))
        b = await runtime.open(operation, context(server="srv-b"))
        assert a.intent_hash != b.intent_hash
        assert len(factory.sessions) == 2
        turn = TurnOperation("same-turn", "same-session", "hello")
        await runtime.submit(turn, context(server="srv-a"))
        await runtime.submit(turn, context(server="srv-b"))
        assert all(len(native.sent) == 1 for native in factory.sessions)
        for server, native in zip(("srv-a", "srv-b"), factory.sessions):
            await native.queue.put(RuntimeEvent(server, "exe", "same-session",
                                                "epoch", 0, "text_delta",
                                                "native.delta", {"server": server}))

        async def first_for(server):
            async for item in runtime.events(EventCursor(server, "exe",
                                                         "same-session", "epoch")):
                return item

        event_a, event_b = await asyncio.gather(
            asyncio.wait_for(first_for("srv-a"), timeout=2),
            asyncio.wait_for(first_for("srv-b"), timeout=2))
        assert event_a.sequence == event_b.sequence == 1
        assert event_a.payload == {"server": "srv-a"}
        assert event_b.payload == {"server": "srv-b"}
        report_a = await runtime.reconcile(ReconcileRequest("srv-a", "exe",
                                                              ("same-turn",),
                                                              ("same-session",)))
        report_b = await runtime.reconcile(ReconcileRequest("srv-b", "exe",
                                                              ("same-turn",),
                                                              ("same-session",)))
        assert report_a.receipts[0].intent_hash != report_b.receipts[0].intent_hash
        assert report_a.snapshots[0].ownership == "owned"
        assert report_b.snapshots[0].ownership == "owned"
        outcomes = (await runtime.shutdown(ShutdownPolicy())).session_outcomes
        assert set(outcomes) == {SessionKey("srv-a", "exe", "same-session"),
                                 SessionKey("srv-b", "exe", "same-session")}
        journal.close()

    asyncio.run(run())


def test_lease_renewal_fences_old_generation_and_expiry_closes(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(
            tmp_path, clock=clock, lease_grace_seconds=2,
            lease_poll_seconds=0.01)
        initial = replace(context(), lease_deadline_monotonic=101)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         initial)
        await runtime.open(OpenOperation("open", "session", "epoch", prepared), initial)
        session = SessionKey("srv", "exe", "session")
        opening_claim = (await runtime.claimed_sessions("srv", "exe")).claims[0]
        assert opening_claim.opening_connection_generation == 3
        assert opening_claim.opening_owner_generation == 1

        clock.advance(1.1)
        await asyncio.sleep(0.03)
        assert (await runtime.inspect(session)).lease_state == "EXPIRED"
        forged = replace(initial, lease_deadline_monotonic=110)
        with pytest.raises(CoreError, match="AGENT_REVOKED"):
            await runtime.submit(TurnOperation("forged", "session", "hello"), forged)
        renewed = replace(initial, connection_generation=4,
                          lease_deadline_monotonic=110)
        with pytest.raises(CoreError, match="STALE_GENERATION"):
            await runtime.renew_lease(
                session, renewed, expected_connection_generation=2)
        with pytest.raises(CoreError, match="STALE_GENERATION"):
            await runtime.renew_lease(
                session, replace(renewed, session_owner_generation=2),
                expected_connection_generation=3)
        snapshot = await runtime.renew_lease(
            session, renewed, expected_connection_generation=3)
        assert snapshot.lease_state == "ACTIVE"
        assert snapshot.connection_generation == 4
        assert (await runtime.claimed_sessions("srv", "exe")).claims[0] == opening_claim
        with pytest.raises(CoreError, match="STALE_GENERATION"):
            await runtime.submit(TurnOperation("stale", "session", "hello"),
                                 replace(initial, lease_deadline_monotonic=110))
        await runtime.submit(TurnOperation("fresh", "session", "hello"), renewed)

        clock.advance(9.1)
        await asyncio.sleep(0.03)
        assert (await runtime.inspect(session)).lease_state == "EXPIRED"
        clock.advance(2.1)
        # Physical stop and durable lease/slot release are asynchronous. Wait
        # for their observable result rather than a 30 ms scheduler assumption.
        async with asyncio.timeout(3):
            while True:
                snapshot = await runtime.inspect(session)
                if snapshot.lease_state == 'CLOSED' and snapshot.ownership == 'released':
                    break
                await asyncio.sleep(.01)
        assert factory.native.stopped
        assert snapshot.lease_state == "CLOSED"
        assert snapshot.ownership == "released"
        internal = journal._run_sync(lambda db: db.execute(
            "SELECT stage,possible_effect,retry_safe FROM operations_v2 WHERE operation_id LIKE 'core.internal.lease_close.%'"
        ).fetchall())
        assert internal == [("SUCCEEDED", 1, 0)]
        journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("verb", ["send_turn", "interrupt"])
def test_reconnect_cas_waits_for_old_native_effect(tmp_path, verb):
    async def run():
        runtime, journal, factory = make_runtime(
            tmp_path, reconnect_fence_seconds=0.05)
        old = context()
        prepared = await runtime.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), old)
        await runtime.open(OpenOperation("open", "session", "epoch", prepared), old)
        session = SessionKey("srv", "exe", "session")
        entered = asyncio.Event()
        release = asyncio.Event()
        original_send = factory.native.send

        async def held_send(sent_verb, payload, operation_id, *,
                            expected_turn_id=None):
            if sent_verb == verb:
                entered.set()
                await release.wait()
            await original_send(sent_verb, payload, operation_id,
                                expected_turn_id=expected_turn_id)

        factory.native.send = held_send
        if verb == "send_turn":
            pending = asyncio.create_task(runtime.submit(
                TurnOperation("old-send", "session", "hello"), old))
        else:
            pending = asyncio.create_task(runtime.control(
                ControlOperation("old-control", "session", "interrupt"), old))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            renewed = replace(old, connection_generation=4,
                              lease_deadline_monotonic=old.lease_deadline_monotonic + 10)
            with pytest.raises(CoreError, match="RECONNECT_BUSY") as caught:
                await asyncio.wait_for(runtime.renew_lease(
                    session, renewed, expected_connection_generation=3),
                    timeout=1)
            assert caught.value.retry_safe is True
            assert (await runtime.inspect(session)).connection_generation == 3
        finally:
            release.set()
            assert (await asyncio.wait_for(pending, timeout=2)).stage == "SUBMITTED"

        snapshot = await runtime.renew_lease(
            session, renewed, expected_connection_generation=3)
        assert snapshot.connection_generation == 4
        with pytest.raises(CoreError, match="STALE_GENERATION"):
            await runtime.submit(TurnOperation("stale-after-cas", "session",
                                               "hello"), old)
        await runtime.close(CloseOperation("close", "session"), renewed)
        journal.close()

    asyncio.run(run())


def test_revocation_does_not_report_success_during_old_native_effect(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(
            tmp_path, reconnect_fence_seconds=0.05)
        old = context()
        prepared = await runtime.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), old)
        await runtime.open(OpenOperation("open", "session", "epoch", prepared), old)
        session = SessionKey("srv", "exe", "session")
        entered = asyncio.Event()
        release = asyncio.Event()
        original_send = factory.native.send

        async def held_send(verb, payload, operation_id, *,
                            expected_turn_id=None):
            entered.set()
            await release.wait()
            await original_send(verb, payload, operation_id,
                                expected_turn_id=expected_turn_id)

        factory.native.send = held_send
        pending = asyncio.create_task(runtime.submit(
            TurnOperation("old-send", "session", "hello"), old))
        revoked = replace(old, authorization_revision=2,
                          allowed_actions=frozenset())
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            with pytest.raises(CoreError, match="REVOKE_BUSY") as caught:
                await asyncio.wait_for(runtime.revoke_lease(
                    session, revoked, expected_connection_generation=3),
                    timeout=1)
            assert caught.value.retry_safe is True
            assert (await runtime.inspect(session)).lease_state == "ACTIVE"
        finally:
            release.set()
            assert (await asyncio.wait_for(pending, timeout=2)).stage == "SUBMITTED"

        # The 50 ms fence above tests a held native effect. Restore the normal
        # budget before requiring the durable SQLite revocation to complete.
        runtime._reconnect_fence_seconds = 5.0
        await runtime.revoke_lease(
            session, revoked, expected_connection_generation=3)
        assert (await runtime.inspect(session)).lease_state == "REVOKED"
        with pytest.raises(CoreError, match="AGENT_REVOKED"):
            await runtime.submit(TurnOperation("old-after-revoke", "session",
                                               "hello"), old)
        await runtime.shutdown(ShutdownPolicy())
        journal.close()

    asyncio.run(run())


def test_revocation_cannot_be_undone_by_lease_renewal(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(
            tmp_path, clock=clock, lease_grace_seconds=1,
            lease_poll_seconds=0.01)
        initial = replace(context(), lease_deadline_monotonic=150)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         initial)
        await runtime.open(OpenOperation("open", "session", "epoch", prepared), initial)
        session = SessionKey("srv", "exe", "session")
        revoked = replace(initial, authorization_revision=2,
                          allowed_actions=frozenset())
        with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
            await runtime.revoke_lease(SessionKey("other", "exe", "session"),
                                       revoked, expected_connection_generation=3)
        await runtime.revoke_lease(session, revoked,
                                   expected_connection_generation=3)
        assert (await runtime.inspect(session)).lease_state == "REVOKED"
        with pytest.raises(CoreError, match="SESSION_UNKNOWN"):
            await runtime.renew_lease(
                session, replace(initial, authorization_revision=3,
                                 lease_deadline_monotonic=160),
                expected_connection_generation=3)
        clock.advance(1.1)
        deadline = asyncio.get_running_loop().time() + 2
        while not factory.native.stopped and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        assert factory.native.stopped
        journal.close()

    asyncio.run(run())


def test_exact_maximum_lease_uses_absolute_deadline_without_subtraction_drift(tmp_path):
    async def run():
        clock = FakeClock(100.002)
        deadline = clock.monotonic() + 120.0
        assert deadline - clock.monotonic() > 120.0  # deterministic FP regression
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        valid = replace(context(), lease_deadline_monotonic=deadline)
        try:
            prepared = await runtime.prepare(LaunchIntent('agent', 'ws', 'codex_app_server'), valid)
            with pytest.raises(CoreError, match='LEASE_INVALID'):
                await runtime.open(OpenOperation('too-far', 'session', 'epoch', prepared),
                                   replace(valid, lease_deadline_monotonic=math.nextafter(deadline, math.inf)))
            assert factory.open_count == 0
            await runtime.open(OpenOperation('exact-max', 'session', 'epoch', prepared), valid)
            assert factory.open_count == 1
        finally:
            await runtime.shutdown(ShutdownPolicy(1, 1))
            journal.close()
    asyncio.run(run())


def test_open_rejects_lease_far_beyond_local_maximum(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        valid = replace(context(), lease_deadline_monotonic=110)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         valid)
        oversized = replace(valid, lease_deadline_monotonic=300)
        with pytest.raises(CoreError, match="LEASE_INVALID"):
            await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                               oversized)
        assert factory.open_count == 0
        journal.close()

    asyncio.run(run())


def test_nonfinite_or_untyped_lease_deadline_cannot_admit_native_effect(tmp_path):
    async def run():
        clock = FakeClock()
        runtime, journal, factory = make_runtime(tmp_path, clock=clock)
        valid = replace(context(), lease_deadline_monotonic=110)
        prepared = await runtime.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), valid)
        try:
            for invalid in (math.nan, math.inf, -math.inf, True, "110", None,
                            10**1000):
                malformed = replace(valid, lease_deadline_monotonic=invalid)
                with pytest.raises(CoreError, match="LEASE_INVALID"):
                    await runtime.prepare(
                        LaunchIntent("agent", "ws", "codex_app_server"),
                        malformed)
                with pytest.raises(CoreError, match="LEASE_INVALID"):
                    await runtime.open(
                        OpenOperation("bad-open", "bad-session", "epoch", prepared),
                        malformed)
            assert factory.open_count == 0
            assert await journal.get_receipt(
                OperationKey("srv", "exe", "bad-open")) is None

            await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                               valid)
            malformed = replace(valid, lease_deadline_monotonic=math.nan)
            with pytest.raises(CoreError, match="LEASE_INVALID"):
                await runtime.submit(TurnOperation("bad-submit", "session", "text"),
                                     malformed)
            with pytest.raises(CoreError, match="LEASE_INVALID"):
                await runtime.renew_lease(
                    SessionKey("srv", "exe", "session"), malformed,
                    expected_connection_generation=3)
            assert factory.native.sent == []
            assert runtime._sessions[SessionKey("srv", "exe", "session")].context == valid
        finally:
            journal.close()

    asyncio.run(run())


async def _emit_durable_native_request(runtime, native, request):
    await native.queue.put(RuntimeEvent(
        "srv", "exe", "session", "epoch", 0, "native_unknown",
        request["method"], {"native_approval": request}))

    async def observed():
        while True:
            async for event in runtime.events(EventCursor(
                    "srv", "exe", "session", "epoch")):
                if event.payload.get("native_approval") == request:
                    return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(observed(), timeout=2)


def test_native_decision_rejects_hostile_json_before_canonical_copy(
        tmp_path, monkeypatch):
    async def run():
        runtime, journal, _ = make_runtime(tmp_path)
        authority = context(actions={"input.provide"})
        request = {"request_id": 8, "request_hash": "b" * 64,
                   "method": "item/tool/requestUserInput",
                   "params": {"threadId": "thread", "turnId": "turn",
                              "itemId": "item"}}
        cycle = []
        cycle.append(cycle)
        deep = "answer"
        for _ in range(66):
            deep = [deep]
        answers = [
            {"answers": "x" * 1_000_000},
            {"answers": cycle},
            {"answers": deep},
            {"answers": {1: "not a JSON key"}},
            {"answers": float("inf")},
        ]

        def canonical_must_not_run(_):
            raise AssertionError("hostile native JSON reached canonicalization")

        monkeypatch.setattr("nexus_connector_core.runtime.canonical_json",
                            canonical_must_not_run)
        try:
            for index, answer in enumerate(answers):
                operation_id = f"hostile-{index}"
                with pytest.raises(CoreError, match="VALIDATION_ERROR"):
                    await runtime.decide_native_approval(
                        NativeApprovalOperation(operation_id, "session",
                                                request, "accept", answer),
                        authority)
                assert await journal.get_receipt(
                    OperationKey("srv", "exe", operation_id)) is None
            huge_request = {**request, "params": {**request["params"],
                                                  "extra": "x" * 1_000_000}}
            with pytest.raises(CoreError, match="VALIDATION_ERROR"):
                await runtime.decide_native_approval(
                    NativeApprovalOperation("huge-request", "session",
                                            huge_request, "decline"), authority)
        finally:
            journal.close()

    asyncio.run(run())


def test_native_approval_is_authorized_deduped_and_journals_no_answer(tmp_path):
    class ApprovalNative(FakeNative):
        def __init__(self):
            super().__init__()
            self.replies = []

        async def reply_native_approval(self, request, decision, response):
            self.replies.append((request, decision, response))

    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        factory.native = ApprovalNative()
        authority = context(actions={"runtime.open", "runtime.close",
                                     "approval.decide", "input.provide"})
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            request = {"request_id": 7, "request_hash": "a" * 64,
                       "method": "item/commandExecution/requestApproval",
                       "params": {"threadId": "thread", "turnId": "turn", "itemId": "item"}}
            with pytest.raises(CoreError, match="NATIVE_REQUEST_NOT_OBSERVED"):
                await runtime.decide_native_approval(
                    NativeApprovalOperation("unobserved", "session", request,
                                            "decline"), authority)
            refused = await journal.get_receipt(
                OperationKey("srv", "exe", "unobserved"))
            assert refused.stage == "FAILED" and refused.retry_safe
            assert not refused.possible_effect
            assert refused.error_code == "NATIVE_REQUEST_NOT_OBSERVED"
            await _emit_durable_native_request(runtime, factory.native, request)
            altered = {**request, "params": {**request["params"],
                                            "itemId": "other"}}
            with pytest.raises(CoreError, match="NATIVE_REQUEST_NOT_OBSERVED"):
                await runtime.decide_native_approval(
                    NativeApprovalOperation("altered", "session", altered,
                                            "decline"), authority)
            refused = await journal.get_receipt(
                OperationKey("srv", "exe", "altered"))
            assert refused.stage == "FAILED" and refused.retry_safe
            assert not refused.possible_effect
            assert refused.error_code == "NATIVE_REQUEST_NOT_OBSERVED"
            decision = NativeApprovalOperation("decision", "session", request,
                                               "decline")
            receipt = await runtime.decide_native_approval(decision, authority)
            assert receipt.stage == "SUBMITTED" and receipt.possible_effect
            assert await runtime.decide_native_approval(decision, authority) == receipt
            assert len(factory.native.replies) == 1
            with pytest.raises(CoreError, match="NATIVE_REQUEST_NOT_OBSERVED"):
                await runtime.decide_native_approval(
                    NativeApprovalOperation("second-decision", "session",
                                            request, "decline"), authority)
            refused = await journal.get_receipt(
                OperationKey("srv", "exe", "second-decision"))
            assert refused.stage == "FAILED" and refused.retry_safe
            assert not refused.possible_effect
            assert refused.error_code == "NATIVE_REQUEST_NOT_OBSERVED"
            with pytest.raises(CoreError, match="OPERATION_CONFLICT"):
                await runtime.decide_native_approval(
                    replace(decision, decision="accept"), authority)

            input_request = {"request_id": 8, "request_hash": "b" * 64,
                             "method": "item/tool/requestUserInput",
                             "params": {"threadId": "thread", "turnId": "turn",
                                        "itemId": "item"}}
            await _emit_durable_native_request(runtime, factory.native,
                                               input_request)
            with pytest.raises(CoreError, match="VALIDATION_ERROR"):
                await runtime.decide_native_approval(
                    NativeApprovalOperation("missing-answer", "session",
                                            input_request, "accept"), authority)
            with pytest.raises(CoreError, match="VALIDATION_ERROR"):
                await runtime.decide_native_approval(
                    NativeApprovalOperation("nonfinite-answer", "session",
                                            input_request, "accept",
                                            {"value": math.nan}), authority)
            secret = "operator-secret-answer-marker"
            answer = NativeApprovalOperation(
                "answer", "session", input_request, "accept",
                {"answers": {"q": {"answers": [secret]}}})
            assert (await runtime.decide_native_approval(
                answer, authority)).stage == "SUBMITTED"
            assert factory.native.replies[-1][2] == answer.operator_response
            assert secret not in "\n".join(journal._run_sync(lambda db: "".join(db.iterdump())))
            assert await journal.get_receipt(
                OperationKey("srv", "exe", "missing-answer")) is None
            assert await journal.get_receipt(
                OperationKey("srv", "exe", "nonfinite-answer")) is None

            unauthorized = replace(
                authority, allowed_actions=frozenset({"runtime.open"}))
            with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
                await runtime.decide_native_approval(
                    NativeApprovalOperation("unauthorized", "session", request,
                                            "decline"), unauthorized)
            approval_only = replace(
                authority, allowed_actions=frozenset({"approval.decide"}))
            with pytest.raises(CoreError, match="BINDING_NOT_AUTHORIZED"):
                await runtime.decide_native_approval(
                    NativeApprovalOperation("wrong-action", "session",
                                            input_request, "decline"),
                    approval_only)
            assert len(factory.native.replies) == 2
        finally:
            await runtime.shutdown(ShutdownPolicy(0.01, 0.01))
            journal.close()

    asyncio.run(run())


def test_native_terminal_forgets_pending_approval_before_decision(tmp_path):
    class ApprovalNative(FakeNative):
        async def reply_native_approval(self, request, decision, response):
            raise AssertionError("terminal approval must not reach native")

    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        factory.native = ApprovalNative()
        authority = context(actions={"runtime.open", "runtime.close",
                                     "approval.decide"})
        request = {"request_id": 7, "request_hash": "a" * 64,
                   "method": "item/fileChange/requestApproval",
                   "params": {"threadId": "thread", "turnId": "turn",
                              "itemId": "item"}}
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            await _emit_durable_native_request(runtime, factory.native, request)
            await factory.native.queue.put(RuntimeEvent(
                "srv", "exe", "session", "epoch", 0, "turn_state",
                "turn/completed", {"delivery_phase": "terminal",
                                   "turn_id": "turn"}))

            async def terminal_observed():
                while True:
                    async for event in runtime.events(EventCursor(
                            "srv", "exe", "session", "epoch")):
                        if event.payload.get("delivery_phase") == "terminal":
                            return
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(terminal_observed(), timeout=2)
            with pytest.raises(CoreError, match="NATIVE_REQUEST_NOT_OBSERVED"):
                await runtime.decide_native_approval(
                    NativeApprovalOperation("late", "session", request,
                                            "decline"), authority)
            refused = await journal.get_receipt(
                OperationKey("srv", "exe", "late"))
            assert refused.stage == "FAILED" and refused.retry_safe
            assert not refused.possible_effect
            assert refused.error_code == "NATIVE_REQUEST_NOT_OBSERVED"
        finally:
            await runtime.shutdown(ShutdownPolicy(0.01, 0.01))
            journal.close()

    asyncio.run(run())


def test_native_approval_stale_refusal_and_write_failure_are_distinct(tmp_path):
    class ApprovalNative(FakeNative):
        def __init__(self):
            super().__init__()
            self.failure = None

        async def reply_native_approval(self, request, decision, response):
            raise self.failure

    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        factory.native = ApprovalNative()
        authority = context(actions={"runtime.open", "runtime.close",
                                     "approval.decide"})
        request = {"request_id": 7, "request_hash": "a" * 64,
                   "method": "item/fileChange/requestApproval",
                   "params": {"threadId": "thread", "turnId": "turn", "itemId": "item"}}
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            await _emit_durable_native_request(runtime, factory.native, request)
            factory.native.failure = RuntimeCommandNotSent("stale", code="STALE_TURN")
            with pytest.raises(CoreError, match="STALE_TURN") as refused:
                await runtime.decide_native_approval(
                    NativeApprovalOperation("stale", "session", request,
                                            "decline"), authority)
            assert refused.value.retry_safe and not refused.value.possible_effect
            safe = await journal.get_receipt(OperationKey("srv", "exe", "stale"))
            assert safe.stage == "FAILED" and not safe.possible_effect

            factory.native.failure = RuntimeError("uncertain native write")
            with pytest.raises(RuntimeError, match="uncertain native write"):
                await runtime.decide_native_approval(
                    NativeApprovalOperation("uncertain", "session", request,
                                            "decline"), authority)
            unknown = await journal.get_receipt(
                OperationKey("srv", "exe", "uncertain"))
            assert unknown.stage == "OUTCOME_UNKNOWN" and unknown.possible_effect
            with pytest.raises(CoreError, match="NATIVE_REQUEST_NOT_OBSERVED"):
                await runtime.decide_native_approval(
                    NativeApprovalOperation("after-uncertain", "session",
                                            request, "decline"), authority)
            refused = await journal.get_receipt(
                OperationKey("srv", "exe", "after-uncertain"))
            assert refused.stage == "FAILED" and refused.retry_safe
            assert not refused.possible_effect
            assert refused.error_code == "NATIVE_REQUEST_NOT_OBSERVED"
        finally:
            await runtime.shutdown(ShutdownPolicy(0.01, 0.01))
            journal.close()

    asyncio.run(run())


def test_lease_grace_arithmetic_must_remain_finite_before_open(tmp_path):
    async def run():
        clock = FakeClock(now=1e308)
        runtime, journal, factory = make_runtime(
            tmp_path, clock=clock, max_lease_seconds=1e308,
            lease_grace_seconds=1e307)
        context_with_overflowing_grace = replace(
            context(), lease_deadline_monotonic=1.7e308)
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"),
                context_with_overflowing_grace)
            with pytest.raises(CoreError, match="LEASE_INVALID"):
                await runtime.open(
                    OpenOperation("open", "session", "epoch", prepared),
                    context_with_overflowing_grace)
            assert factory.open_count == 0
        finally:
            journal.close()

    asyncio.run(run())


def test_unobserved_close_keeps_ownership_and_unknown_receipt(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                           context())

        async def unknown_close():
            return "unknown"

        factory.native.close = unknown_close
        with pytest.raises(CoreError, match="OUTCOME_UNKNOWN"):
            await runtime.close(CloseOperation("close", "session"), context())
        report = await runtime.reconcile(ReconcileRequest("srv", "exe",
                                                         ("close",), ("session",)))
        assert report.receipts[0].stage == "OUTCOME_UNKNOWN"
        assert report.snapshots[0].ownership == "owned"
        journal.close()

    asyncio.run(run())


def test_observed_stop_with_unknown_method_releases_slot_without_claiming_force(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path, max_owned_sessions=1)
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                           context())

        async def unknown_close():
            factory.native.stopped = True
            await factory.native.queue.put(None)
            return "unknown"

        factory.native.close = unknown_close
        with pytest.raises(CoreError, match="OUTCOME_UNKNOWN"):
            await runtime.close(CloseOperation("close", "session"), context())
        key = SessionKey("srv", "exe", "session")
        assert (await runtime.inspect(key)).ownership == "released"
        assert (await runtime.shutdown(ShutdownPolicy())).session_outcomes[key] == "already_closed"
        journal.close()

    asyncio.run(run())


@pytest.mark.parametrize('platform,containment', [
    ('linux', 'linux_guardian'), ('darwin', 'darwin_launchd_coalition')])
def test_runtime_persists_owned_birth_as_history_not_restarted_ownership(tmp_path, platform, containment):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        evidence = ProcessBirthEvidence(platform, 4321,
                                        "boot-start:boot-1:123", containment)
        factory.native.owned_process_birth = lambda: evidence
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                           context())
        key = SessionKey("srv", "exe", "session")
        record = await runtime.process_birth(key)
        assert record is not None and record.evidence == evidence
        assert record.opening_operation_id == "open"
        await runtime.shutdown(ShutdownPolicy(0, 0))
        journal.close()

        reopened = SQLiteJournal(tmp_path / "journal.db")
        restarted = LocalRuntimeCore(reopened, object(), candidates={},
                                     workspace_roots={})
        assert await restarted.process_birth(key) == record
        assert (await restarted.inspect(key)).ownership == "unknown"
        assert (await restarted.observe_process_birth(
            SessionKey("srv", "exe", "unclaimed"))).state == "UNRECORDED"
        reopened.close()

    asyncio.run(run())


def test_birth_journal_failure_cannot_publish_successful_open(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        factory.native.owned_process_birth = lambda: ProcessBirthEvidence(
            "linux", 4321, "boot-start:boot-1:123", "linux_guardian")

        async def fail_birth(*args):
            raise CoreError("JOURNAL_FULL", "process_birth", possible_effect=True)

        journal.record_process_birth = fail_birth
        prepared = await runtime.prepare(LaunchIntent("agent", "ws", "codex_app_server"),
                                         context())
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await runtime.open(OpenOperation("open", "session", "epoch", prepared),
                               context())
        receipt = await journal.get_receipt(OperationKey("srv", "exe", "open"))
        assert receipt is not None and receipt.stage == "OUTCOME_UNKNOWN"
        key = SessionKey("srv", "exe", "session")
        assert (await runtime.inspect(key)).ownership == "owned"
        assert await runtime.process_birth(key) is None
        await runtime.shutdown(ShutdownPolicy(0, 0))
        journal.close()

    asyncio.run(run())

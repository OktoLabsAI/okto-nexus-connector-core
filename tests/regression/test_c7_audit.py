"""C7 audit seeds — reaudit findings W01-W04 against 12dae55.

Mirrors FIX_UPDATE_PLAN (01_RELATORIO_REAVALIACAO / 03_MATRIZ_ACEITE).
Eight seeds fail on the audited code; the accept control passes.
"""

import asyncio
import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from nexus_connector_core import (
    CoreError, ControlOperation, LaunchIntent, NativeApprovalOperation,
    OpenOperation, SessionKey, ShutdownPolicy, TurnOperation,
    create_runtime,
)
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.protocol import canonical_json

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
# W01 (AC7-04) - unknown session returns the typed error
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("kind", ["submit", "steer"])
def test_w01_unknown_session_returns_typed_error(tmp_path, kind):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        try:
            with pytest.raises(CoreError) as excinfo:
                steer_context = replace(
                    context(),
                    allowed_actions=frozenset({
                        "runtime.open", "turn.submit", "turn.steer",
                        "turn.interrupt", "runtime.close"}))
                if kind == "submit":
                    await runtime.submit(
                        TurnOperation("op-1", "never-existed", "hello"),
                        context())
                else:
                    await runtime.control(
                        ControlOperation("op-1", "never-existed", "steer",
                                         text="late instruction",
                                         expected_turn_id="t-1"),
                        steer_context)
            assert excinfo.value.code == "SESSION_UNKNOWN", (
                f"{kind} on an unknown session must be a typed error, "
                f"not {type(excinfo.value).__name__}")
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# W02 (AC7-02) - recovery finishes a failed attempt when proven
# ------------------------------------------------------------------ #

class _PreDeliveryFailJournal(SQLiteJournal):
    """CAS refuses BEFORE any delivery (JOURNAL_FULL, retry_safe, no
    possible effect); the first recovery read fails, later reads return
    the REAL pre-attempt row."""

    def __init__(self, path):
        super().__init__(path)
        self.armed = False
        self.read_failures_left = 1

    async def cas_session_lease(self, session, **kwargs):
        if self.armed:
            self.armed = False
            raise CoreError("JOURNAL_FULL", "cas_submit", retry_safe=True)
        return await super().cas_session_lease(session, **kwargs)

    async def get_session_lease(self, session):
        if self.read_failures_left > 0:
            self.read_failures_left -= 1
            raise CoreError("STORAGE_UNAVAILABLE", "lease_read")
        return await super().get_session_lease(session)


@pytest.mark.parametrize("operation", ["renew", "revoke"])
def test_w02_recovery_finishes_failed_attempt_when_old_row_is_proven(
        tmp_path, operation):
    clock = FakeClock(100.0)

    async def run():
        journal = _PreDeliveryFailJournal(tmp_path / "journal.db")

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
            reconnect_fence_seconds=0.2, cleanup_budget_seconds=0.2)
        key = SessionKey("srv", "exe", "session")
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=clock.now + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            await runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared), auth)
            journal.armed = True
            with pytest.raises(CoreError):
                if operation == "renew":
                    await runtime.renew_lease(
                        key, replace(auth, authorization_revision=2,
                                     lease_deadline_monotonic=clock.now + 90),
                        expected_connection_generation=auth.connection_generation)
                else:
                    await runtime.revoke_lease(
                        key, replace(auth, authorization_revision=2),
                        expected_connection_generation=auth.connection_generation)
            # The recovery converges: the failed pre-delivery attempt is
            # finalized against the proven pre-attempt row, so a NEW
            # explicitly-requested submit with still-valid authorization
            # proceeds. (The baseline never converges; the wait exhausts.)
            # The failed renew was NOT applied - the binding keeps its
            # CURRENT authorization; the explicitly-requested new submit
            # uses that still-valid context (revalidation of state).
            fresh = auth
            deadline = time.monotonic() + 25
            receipt = None
            while time.monotonic() < deadline:
                try:
                    receipt = await asyncio.wait_for(
                        runtime.submit(TurnOperation("fresh", "session", "x"),
                                       fresh), timeout=2)
                    break
                except CoreError as exc:
                    if exc.code not in {"LEASE_UPDATE_PENDING",
                                        "AGENT_REVOKED", "STALE_GENERATION"}:
                        raise
                    await asyncio.sleep(0.25)
            assert receipt is not None and receipt.stage == "SUBMITTED", (
                "recovery never finished the failed attempt")
            assert len(native.sent) == 1
            return
            if operation == "revoke":
                # Convergence for the revoke attempt itself: the hold and
                # the CAS reservation are released once the row proves
                # nothing was delivered (a retry revoke would no longer
                # see LEASE_UPDATE_PENDING/REVOKE_BUSY).
                deadline = time.monotonic() + 25
                binding = runtime._sessions.get(key)
                while binding is not None and time.monotonic() < deadline:
                    if not binding.lease_hold and                             not binding.lease_cas_pending:
                        break
                    await asyncio.sleep(0.25)
                    binding = runtime._sessions.get(key)
                assert binding is not None and                     not binding.lease_hold and                     not binding.lease_cas_pending, (
                    "revoke recovery never finished the failed attempt")
                return
        finally:
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# W03 (AC7-01) - late-handle containment and recovery
# ------------------------------------------------------------------ #

class _SlowCancelCloseNative:
    """close() observes CancelledError but keeps waiting its barrier."""

    native_id = "native-1"

    def __init__(self):
        self.queue = asyncio.Queue()
        self.stopped = False
        self.start_gate = threading.Event()
        self.close_barrier = asyncio.Event()
        self.close_saw_cancel = threading.Event()
        self.force_calls = 0
        self.force_called = threading.Event()

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
        try:
            await self.close_barrier.wait()
        except asyncio.CancelledError:
            # Cooperative cancel OBSERVED - but the resource release
            # still needs the backend barrier (a slow cleanup).
            self.close_saw_cancel.set()
            await self.close_barrier.wait()
        self.stopped = True
        await self.queue.put(None)
        return "graceful"

    async def force_stop(self):
        self.force_calls += 1
        self.force_called.set()
        self.stopped = True

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


@pytest.mark.parametrize("pre_open_delay", [0.0, 0.3])
def test_w03_force_does_not_wait_for_close_cancellation_to_finish(
        tmp_path, monkeypatch, pre_open_delay):
    clock = FakeClock(100.0)

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        native = _SlowCancelCloseNative()
        factory_entered = asyncio.Event()

        class _Factory:
            async def open(self, prepared, session_id, auth, *,
                           stream_epoch):
                factory_entered.set()
                await asyncio.to_thread(native.start_gate.wait, 5)
                return native

        async def environment(prepared):
            return {}

        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _codex_candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)},
            native_factory=_Factory(), clock=clock,
            lease_grace_seconds=0.0, lease_poll_seconds=0.01,
            cleanup_budget_seconds=0.2)
        existing = runtime._existing

        async def delayed_existing(*args, **kwargs):
            await asyncio.sleep(pre_open_delay)
            return await existing(*args, **kwargs)

        monkeypatch.setattr(runtime, "_existing", delayed_existing)
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=clock.now + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            opening = asyncio.create_task(runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared),
                auth))
            # Cancellation follows actual factory entry, even when journal
            # admission takes longer than the old fixed 200 ms sleep.
            await asyncio.wait_for(factory_entered.wait(), timeout=5)
            opening.cancel()
            try:
                await opening
            except BaseException:
                pass
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.0,
                                                interrupt_seconds=0.0)),
                timeout=5)
            native.start_gate.set()  # the late handle arrives
            assert await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, native.force_called.wait, 3.0), timeout=6), (
                "force waited for the close's cancellation to finish")
            # The cooperative cancel reaches the close within its budget.
            deadline = time.monotonic() + 3
            while not native.close_saw_cancel.is_set() and                     time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert native.close_saw_cancel.is_set()
            assert not native.close_barrier.is_set(), (
                "the force required releasing the close barrier")
        finally:
            native.start_gate.set()
            native.close_barrier.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


class _StalledObserverNative(_SlowCancelCloseNative):
    """close->unknown; first force fails; observe stalls until released."""

    def __init__(self):
        super().__init__()
        self.close_barrier.set()  # close completes (unknown)
        self.observe_gate = threading.Event()

    async def close(self):
        self.close_saw_cancel.set()
        return "unknown"

    async def force_stop(self):
        self.force_calls += 1
        if self.force_calls == 1:
            raise CoreError("FORCE_TRANSIENT", "force")
        self.force_called.set()
        self.stopped = True

    async def observe(self):
        if not self.observe_gate.is_set() and self.force_calls <= 1:
            await asyncio.to_thread(self.observe_gate.wait, 5)
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


def test_w03b_second_shutdown_can_retry_late_handle_after_observer_stalls(
        tmp_path):
    clock = FakeClock(100.0)

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        native = _StalledObserverNative()

        class _Factory:
            async def open(self, prepared, session_id, auth, *,
                           stream_epoch):
                await asyncio.to_thread(native.start_gate.wait, 5)
                return native

        async def environment(prepared):
            return {}

        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _codex_candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)},
            native_factory=_Factory(), clock=clock,
            lease_grace_seconds=0.0, lease_poll_seconds=0.01,
            cleanup_budget_seconds=0.2)
        key = SessionKey("srv", "exe", "session")
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=clock.now + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            opening = asyncio.create_task(runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared),
                auth))
            await asyncio.sleep(0.2)
            opening.cancel()
            try:
                await opening
            except BaseException:
                pass
            # First shutdown: the late handle arrives, close->unknown,
            # force #1 fails, observe STALLS; the budget expires.
            first = asyncio.create_task(runtime.shutdown(
                ShutdownPolicy(drain_seconds=0.05,
                               interrupt_seconds=0.05)))
            await asyncio.sleep(0.1)
            native.start_gate.set()
            try:
                await asyncio.wait_for(first, timeout=10)
            except BaseException:
                pass
            # The handle must already be registered for recovery even
            # though the observer never returned.
            deadline = time.monotonic() + 3
            while (key not in getattr(runtime, "_late_handles", {})
                   and time.monotonic() < deadline):
                await asyncio.sleep(0.05)
            assert key in runtime._late_handles, (
                "stalled observer left the handle outside recovery")
            assert native.force_calls == 1
            # Backend restored: the SECOND public shutdown retries the
            # SAME handle - no new spawn, force #2 succeeds.
            native.observe_gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.05,
                                                interrupt_seconds=0.05)),
                timeout=10)
            assert native.force_calls >= 2, (
                "second shutdown never retried the late handle")
            assert native.force_called.is_set()
        finally:
            native.start_gate.set()
            native.close_barrier.set()
            native.observe_gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# W04 (AC7-03) - public approval: containment vs new permission
# ------------------------------------------------------------------ #

class _ApprovalNative:
    native_id = "native-1"

    def __init__(self):
        self.queue = asyncio.Queue()
        self.stopped = False
        self.sent = []
        self.replies = []

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

    async def reply_native_approval(self, request, decision, response):
        # The runtime's native port: (request, decision, response).
        self.replies.append(decision if decision is not None
                            else "decline")


@pytest.mark.parametrize("decision", ["decline", "cancel", "accept"])
def test_w04_public_approval_distinguishes_containment_from_new_permission(
        tmp_path, decision):
    clock = FakeClock(100.0)

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        native = _ApprovalNative()

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
            lease_grace_seconds=0.0, lease_poll_seconds=0.01)
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=clock.now + 60,
                           allowed_actions=frozenset({
                               "runtime.open", "runtime.close",
                               "turn.submit", "turn.interrupt",
                               "approval.decide", "input.provide"}))
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            await runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared), auth)
            request = {
                "request_id": 7, "request_hash": "a" * 64,
                "method": "item/commandExecution/requestApproval",
                "params": {"threadId": "thread-1", "turnId": "turn-1",
                           "availableDecisions": ["accept", "decline"]},
            }
            encoded = canonical_json({
                "request_id": 7, "request_hash": "a" * 64,
                "method": "item/commandExecution/requestApproval",
                "params": request["params"]})
            binding = runtime._sessions[SessionKey("srv", "exe", "session")]
            binding.pending_native_requests[
                json.dumps(7)] = encoded  # durably observed request
            # The productive lease expires; the request/turn remain valid.
            clock.advance(200)
            operation = NativeApprovalOperation(
                f"decide-{decision}", "session", request, decision)
            if decision == "accept":
                # Control: accept still refuses with zero peer effects.
                with pytest.raises(CoreError) as excinfo:
                    await runtime.decide_native_approval(operation, auth)
                assert excinfo.value.code == "AGENT_REVOKED"
                assert native.replies == [] and native.sent == []
            else:
                # Decline/cancel are containment: exactly one negative
                # reply reaches the peer through the PUBLIC path.
                receipt = await runtime.decide_native_approval(
                    operation, auth)
                assert receipt.stage == "SUBMITTED"
                assert native.replies == [decision], (
                    f"{decision} did not produce its negative reply")
        finally:
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())

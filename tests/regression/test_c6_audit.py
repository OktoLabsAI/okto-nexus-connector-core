"""C6 audit seeds â€” reaudit findings V01-V03 (+M01) against df3baaf.

Mirrors FIX_UPDATE_PLAN (01_RELATORIO_REAVALIACAO / 03_MATRIZ_ACEITE).
Six new seeds fail on the audited code; M01 tightens the original C5 u07
boundary (cap+1 names). Every seed starts authorized and injects the
fault AFTER entering the real wait.
"""

import asyncio
import gc
import json
import os
import threading
import time
import weakref
from dataclasses import replace
from pathlib import Path

import pytest

from nexus_connector_core import (
    CoreError, ExecutionContext, LaunchIntent, OpenOperation, SessionKey,
    ShutdownPolicy, TurnOperation, create_runtime,
)
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.native import runtime_bridge
from nexus_connector_core.native.adapters import codex as codex_module

from tests.test_c1_bridge_stubs import harness_session
from tests.test_runtime import FakeClock, context

def _codex_candidate(tmp_path, name="codex"):
    from nexus_connector_core.discovery import fingerprint
    from nexus_connector_core import InstallationCandidate
    binary = tmp_path / name
    binary.write_bytes(b"synthetic binary")
    return InstallationCandidate(
        "codex_app_server", str(binary), fingerprint(binary),
        "explicit", "selected")


class _SendNative:
    native_id = "native-1"

    def __init__(self):
        self.queue = asyncio.Queue()
        self.stopped = False
        self.sent = []
        self.force_called = threading.Event()

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
        self.force_called.set()

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


def _runtime_with(tmp_path, journal, native, *, clock, **kwargs):
    class _Factory:
        async def open(self, prepared, session_id, auth, *, stream_epoch):
            return native

    async def environment(prepared):
        return {}

    return create_runtime(
        journal=journal, environment=environment,
        candidates={"codex_app_server": _codex_candidate(tmp_path)},
        workspace_roots={"ws": str(tmp_path)},
        native_factory=_Factory(), clock=clock,
        lease_grace_seconds=0.0, lease_poll_seconds=0.01,
        reconnect_fence_seconds=0.2, cleanup_budget_seconds=0.2, **kwargs)


# ------------------------------------------------------------------ #
# V01 (AC6-01) - uncertain revocation never allows old work
# ------------------------------------------------------------------ #

class _LostAckJournal(SQLiteJournal):
    """Commits the revocation, then loses the confirmation."""

    def __init__(self, path):
        super().__init__(path)
        self.armed = False
        self.hold = asyncio.Event()
        self.read_fails = False

    async def cas_session_lease(self, session, **kwargs):
        if kwargs.get("revoked") and self.armed:
            await self.hold.wait()
            result = await super().cas_session_lease(session, **kwargs)
            raise CoreError("CAS_CONFIRMATION_LOST", "cas_commit",
                            possible_effect=True)
        return await super().cas_session_lease(session, **kwargs)

    async def get_session_lease(self, session):
        if self.read_fails:
            raise CoreError("STORAGE_UNAVAILABLE", "lease_read")
        return await super().get_session_lease(session)


@pytest.mark.parametrize("case", ["cancel_then_lost_ack",
                                  "read_unavailable_after_commit"])
def test_v01_uncertain_revocation_never_allows_old_work(tmp_path, case):
    clock = FakeClock(100.0)

    async def run():
        journal = _LostAckJournal(tmp_path / "journal.db")
        native = _SendNative()
        runtime = _runtime_with(tmp_path, journal, native, clock=clock)
        key = SessionKey("srv", "exe", "session")
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=clock.now + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            await runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared), auth)
            journal.armed = True
            if case == "cancel_then_lost_ack":
                # The caller is CANCELLED before the commit; the producer
                # continues and the confirmation is lost afterwards.
                revoking = asyncio.create_task(runtime.revoke_lease(
                    key, replace(auth, authorization_revision=2),
                    expected_connection_generation=auth.connection_generation))
                await asyncio.sleep(0.1)
                revoking.cancel()
                try:
                    await revoking
                except BaseException:
                    pass
                journal.hold.set()  # commit + lost ACK happen now
                await asyncio.sleep(0.3)
            else:
                # Direct path: commit + lost ACK, and the recovery READ
                # is unavailable.
                journal.read_fails = True
                with pytest.raises(CoreError):
                    await runtime.revoke_lease(
                        key, replace(auth, authorization_revision=2),
                        expected_connection_generation=auth.connection_generation)
                journal.hold.set()  # the commit + lost ACK land now
                await asyncio.sleep(0.2)  # the finalizer reads and fails
            # Durable proof the revocation COMMITTED.
            journal.read_fails = False
            lease = await journal.get_session_lease(key)
            assert lease is not None and lease.revoked
            # The OLD context must not grant work now.
            with pytest.raises(CoreError):
                await runtime.submit(
                    TurnOperation("post", "session", "hello"), auth)
            assert native.sent == [], (
                f"{case}: send_turn flowed under a committed revocation")
        finally:
            journal.hold.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# V02 (AC6-02) - late-open ownership
# ------------------------------------------------------------------ #

class _HungCloseNative(_SendNative):
    def __init__(self):
        super().__init__()
        self.start_gate = threading.Event()
        self.close_gate = asyncio.Event()

    async def close(self):
        await self.close_gate.wait()  # graceful close never returns
        self.stopped = True
        await self.queue.put(None)
        return "graceful"


def test_v02_late_open_force_is_independent_of_hung_close(tmp_path):
    clock = FakeClock(100.0)

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        native = _HungCloseNative()
        open_entered = asyncio.Event()

        class _Factory:
            async def open(self, prepared, session_id, auth, *,
                           stream_epoch):
                open_entered.set()
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
            # Cancel only once the native factory actually owns the opening.
            await asyncio.wait_for(open_entered.wait(), timeout=5)
            opening.cancel()
            try:
                await opening
            except BaseException:
                pass
            # Zero-budget shutdown BEFORE the handle returns.
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.0,
                                                interrupt_seconds=0.0)),
                timeout=5)
            native.start_gate.set()  # the late handle arrives now
            assert await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, native.force_called.wait, 2.0), timeout=6), (
                "hung graceful close blocked the physical force")
            assert not native.close_gate.is_set(), (
                "force required releasing the close barrier")
        finally:
            native.start_gate.set()
            native.close_gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


class _FlakyUnknownNative(_SendNative):
    def __init__(self):
        super().__init__()
        self.start_gate = threading.Event()
        self.force_failures = 0
        self.force_calls = 0

    async def close(self):
        return "unknown"

    async def force_stop(self):
        self.force_calls += 1
        if self.force_calls <= self.force_failures:
            raise CoreError("FORCE_TRANSIENT", "force")
        self.force_called.set()

    async def observe(self):
        return ("STOPPED" if self.force_called.is_set() else "RUNNING",
                "IDLE")


def test_v02b_unconfirmed_late_handle_remains_owned_for_recovery(tmp_path):
    clock = FakeClock(100.0)

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        native = _FlakyUnknownNative()
        native.force_failures = 1  # first force fails transiently

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
        holder = {"native": native}
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
            native.start_gate.set()  # late handle; close->unknown, force
            await asyncio.sleep(0.5)  # first containment fails (unknown)
            assert key in runtime._uncertain_opens
            # The runtime - not the fixture - must keep the handle alive
            # for recovery while the stop is unproven.
            ref = weakref.ref(holder["native"])
            holder["native"] = None
            gc.collect()
            assert ref() is not None, (
                "unconfirmed late handle was dropped by the Core")
            # Recovery: a later containment attempt reaches STOPPED on the
            # SAME handle (force succeeds this time).
            recovered = await runtime.shutdown(
                ShutdownPolicy(drain_seconds=0.05,
                               interrupt_seconds=0.05))
            assert recovered.session_outcomes.get(key) in {
                "unknown", "forced", "already_closed"}
            assert native.force_called.is_set(), (
                "recovery never re-contained the retained handle")
        finally:
            native.start_gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


def test_v02c_shutdown_fences_cancelled_open_before_late_start(
        tmp_path, monkeypatch):
    spawn_calls = {"count": 0}

    def spawn_sentinel(*args, **kwargs):
        spawn_calls["count"] += 1
        raise OSError("sentinel: no process created")

    monkeypatch.setattr(codex_module, "spawn_owned_process", spawn_sentinel)
    monkeypatch.setattr(runtime_bridge, "qualified_build",
                        lambda *a, **k: True, raising=True)
    monkeypatch.setattr(
        "nexus_connector_core.native.process.require_containment",
        lambda: None, raising=True)
    clock = FakeClock(100.0)
    env_release = asyncio.Event()
    producer_tasks = set()  # fixture keeps the producer ALIVE (as the
    # audit's runner does): the waiter's cancellation must not let GC
    # silently swallow the producer - the RUNTIME is what must own it.

    async def environment(prepared):
        await env_release.wait()  # held across cancel + shutdown
        return {}

    real_open = runtime_bridge.CopiedAdapterFactory.open

    async def held_open(self, prepared, session_id, context, *,
                        stream_epoch, opening_guard=None):
        task = asyncio.current_task()
        producer_tasks.add(task)
        task.add_done_callback(producer_tasks.discard)
        return await real_open(self, prepared, session_id, context,
                               stream_epoch=stream_epoch,
                               opening_guard=opening_guard)

    monkeypatch.setattr(runtime_bridge.CopiedAdapterFactory, "open",
                        held_open)

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _codex_candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)}, clock=clock)
        real_connector = codex_module.CodexAppServerConnector(
            command=["lab-codex"], cwd=os.getcwd())
        monkeypatch.setattr(
            runtime_bridge, "load_adapter",
            lambda adapter_id: (lambda **kw: real_connector))
        try:
            # A long-but-valid lease (max window): only draining can
            # fence this open, not the clock.
            auth = replace(context(),
                           lease_deadline_monotonic=clock.now + 120)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            opening = asyncio.create_task(runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared),
                auth))
            await asyncio.sleep(0.3)  # waiting inside environment
            # Cancel the WAITER, then run a public shutdown.
            opening.cancel()
            try:
                await opening
            except BaseException:
                pass
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.0,
                                                interrupt_seconds=0.0)),
                timeout=5)
            # NOW the environment callback resolves: draining must still
            # fence the spawn - the attempt cannot vanish with its waiter.
            env_release.set()
            try:
                await asyncio.wait_for(_drain_openings(runtime), timeout=5)
            except BaseException:
                pass
            await asyncio.sleep(0.3)
            assert spawn_calls["count"] == 0, (
                "cancelled open started a process after shutdown")
        finally:
            env_release.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


async def _drain_openings(runtime):
    # Best-effort wait for the pending producer to settle in tests.
    await asyncio.sleep(0)


# ------------------------------------------------------------------ #
# V03 (AC6-03) - pre-write refused accept can still be declined
# ------------------------------------------------------------------ #

def test_v03_prewrite_refused_accept_can_still_be_declined():
    async def run():
        from tests.regression.test_c5_audit import (
            _register_pending_approval, _wired_codex_connector)
        connector, transport, stdin = _wired_codex_connector()
        clock = FakeClock(100.0)
        fence = runtime_bridge.EffectFence(
            lambda: (False, False, False, False, False),
            clock=clock.monotonic, lease_deadline=160.0)
        session = runtime_bridge.CopiedAdapterSession(
            connector, harness_session(), session_id="native-session",
            stream_epoch="e",
            context=ExecutionContext(
                "srv", "exe", "bind", "agent", "ws", 1, 1, 1,
                time.monotonic() + 60,
                frozenset({"turn.submit", "approval.decide",
                           "input.provide"})))
        session.effect_fence = fence
        session._active_operation_id = "op-1"
        session._active_turn_id = "turn-1"
        _register_pending_approval(connector)
        request = {"request_id": 7, "request_hash": "hash-1",
                   "method": "item/commandExecution/requestApproval",
                   "params": {"threadId": "thread-1", "turnId": "turn-1"}}

        import concurrent.futures
        loop = asyncio.get_running_loop()
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=2))
        park = threading.Event()
        busy = loop.run_in_executor(None, lambda: park.wait(5))
        assert transport._write_lock.acquire(timeout=1)
        await asyncio.sleep(0.05)

        accepting = asyncio.create_task(
            session.reply_native_approval(request, "accept", None))
        await asyncio.sleep(0.3)  # the reply waits on the write lock
        assert not accepting.done()
        clock.advance(61.0)  # authorization expires mid-wait
        transport._write_lock.release()
        park.set()
        await asyncio.wrap_future(busy)
        with pytest.raises(runtime_bridge.RuntimeCommandNotSent):
            await asyncio.wait_for(accepting, timeout=5)
        assert stdin.bytes == b"", "zero bytes must have left the writer"

        # The SAME request, still correlated to the same turn, must now
        # accept a DECLINE - a denial never grants work and the guard
        # consumed the pending record without writing anything.
        await session.reply_native_approval(request, "decline", None)
        assert stdin.bytes.count(b"decline") == 1, (
            "the recoverable denial never reached the wire")
        await session.close()

    asyncio.run(run())

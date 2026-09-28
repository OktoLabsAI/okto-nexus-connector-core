"""C5 audit seeds — reaudit findings U01-U07 against 3d304f9.

Mirrors FIX_UPDATE_PLAN (01_RELATORIO_REAVALIACAO / 03_MATRIZ_ACEITE,
cases AC5-01-01..05, AC5-02-01, AC5-03-x, AC5-04-x, AC5-05-x, AC5-06-x).
Ten seeds fail on the audited code; one positive control passes before
and after. Every seed starts authorized and trips DURING a real wait.
"""

import asyncio
import concurrent.futures
import json
import os
import shutil
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from nexus_connector_core import (
    CoreError, ExecutionContext, InstallationCandidate, LaunchIntent,
    OpenOperation, SessionKey, ShutdownPolicy, TurnOperation,
    create_runtime,
)
from nexus_connector_core.build_identity import pi_build_identity
from nexus_connector_core.discovery import (
    candidate_pi_node_cli, fingerprint as discovery_fingerprint,
)
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.native import runtime_bridge
from nexus_connector_core.native.adapters import codex as codex_module

from tests.test_c1_bridge_stubs import harness_session
from tests.test_runtime import FakeClock, context

def _patch_factory_gates(monkeypatch):
    monkeypatch.setattr(runtime_bridge, "qualified_build",
                        lambda *a, **k: True, raising=True)
    monkeypatch.setattr(
        "nexus_connector_core.native.process.require_containment",
        lambda: None, raising=True)


def _codex_candidate(tmp_path, name="codex"):
    binary = tmp_path / name
    binary.write_bytes(b"synthetic binary")
    return InstallationCandidate(
        "codex_app_server", str(binary), discovery_fingerprint(binary),
        "explicit", "selected")


# ------------------------------------------------------------------ #
# shared lab transport for the real Codex serializer/writer
# ------------------------------------------------------------------ #

class _RecordingStdin:
    def __init__(self):
        self.bytes = bytearray()

    def write(self, data):
        self.bytes.extend(data.encode())

    def flush(self):
        pass


def _wired_codex_connector():
    """Real connector + real transport with a lab process on stdin."""
    connector = codex_module.CodexAppServerConnector(
        command=["lab-codex"], cwd=os.getcwd())
    stdin = _RecordingStdin()
    transport = codex_module._CodexTransport(
        command=["lab-codex"], cwd=os.getcwd(), env=None,
        on_notification=lambda n: None,
        on_unmatched_response=lambda i, r, e: None,
        on_child_exit=lambda c, t: None,
        on_malformed_line=lambda l, e: None,
        on_dispatch_error=lambda w, e: None,
        dispatch_guards=connector._dispatch_guards)
    connector._transport = transport
    transport._proc = SimpleNamespace(
        stdin=stdin, poll=lambda: None,
        terminate=lambda: None, kill=lambda: None,
        wait=lambda *a, **k: 0, returncode=0)
    return connector, transport, stdin


def _register_pending_approval(connector, *, turn_id="turn-1",
                               request_id=7):
    state = codex_module._ThreadState(
        "native-session", "thread-1", "agent", active_turn_id=turn_id)
    connector._sessions_by_id["native-session"] = state
    request = {
        "request_id": request_id, "request_hash": "hash-1",
        "method": "item/commandExecution/requestApproval",
        "params": {"threadId": "thread-1", "turnId": turn_id,
                   "availableDecisions": ["accept", "decline"]},
    }
    connector._approval_requests[json.dumps(request_id)] = {
        "pending": True, "session_id": "native-session",
        "request": request}
    return state, request


def _bridge_session(connector, *, fence=None, active_turn=None):
    session = runtime_bridge.CopiedAdapterSession(
        connector, harness_session(), session_id="native-session",
        stream_epoch="e",
        context=ExecutionContext(
            "srv", "exe", "bind", "agent", "ws", 1, 1, 1,
            time.monotonic() + 60,
            frozenset({"turn.submit", "approval.decide",
                       "input.provide"})))
    if fence is not None:
        session.effect_fence = fence
    if active_turn is not None:
        session._active_operation_id = "op-1"
        session._active_turn_id = active_turn
    return session


# ------------------------------------------------------------------ #
# U01 (AC5-01-01/02) - approval guard reaches the native writer
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("case", ["deadline", "turn"])
def test_u01_approval_guard_reaches_native_writer_after_lock(case):
    async def run():
        connector, transport, stdin = _wired_codex_connector()
        clock = FakeClock(100.0)
        fence = runtime_bridge.EffectFence(
            lambda: (False, False, False, False, False),
            clock=clock.monotonic, lease_deadline=160.0)
        session = _bridge_session(connector, fence=fence,
                                  active_turn="turn-1")
        _register_pending_approval(connector)
        request = {"request_id": 7, "request_hash": "hash-1",
                   "method": "item/commandExecution/requestApproval",
                   "params": {"threadId": "thread-1", "turnId": "turn-1"}}

        loop = asyncio.get_running_loop()
        # TWO workers: the dispatch must REACH the transport write lock
        # (thread running, blocked on OUR held lock) - not queue behind
        # an occupied executor where the entry check would catch it.
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=2))
        park = threading.Event()
        busy = loop.run_in_executor(None, lambda: park.wait(5))
        assert transport._write_lock.acquire(timeout=1)
        await asyncio.sleep(0.05)

        replying = asyncio.create_task(
            session.reply_native_approval(request, "accept", None))
        await asyncio.sleep(0.3)  # the reply thread waits on the lock
        assert not replying.done(), "reply never reached the lock wait"
        if case == "deadline":
            clock.advance(61.0)  # 100 -> 161: past the 160 deadline
        else:
            session._active_turn_id = "turn-2"  # a NEW turn took over
        transport._write_lock.release()  # the writer wakes past the guard
        park.set()
        await asyncio.wrap_future(busy)
        with pytest.raises(runtime_bridge.RuntimeCommandNotSent):
            await asyncio.wait_for(replying, timeout=5)
        assert stdin.bytes == b"", (
            f"{case}: a permissive approval reached the wire")
        await session.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# U02 (AC5-01-03/04) - spawn guard reaches the real adapter start
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("case", ["deadline", "shutdown"])
def test_u02_spawn_guard_reaches_real_adapter_after_start_lock(
        tmp_path, monkeypatch, case):
    spawn_calls = {"count": 0}

    def spawn_sentinel(*args, **kwargs):
        spawn_calls["count"] += 1
        raise OSError("sentinel: no process created")

    monkeypatch.setattr(codex_module, "spawn_owned_process", spawn_sentinel)
    _patch_factory_gates(monkeypatch)
    started = {"adapter": False}

    class _FakeAdapter:
        def __init__(self, **kwargs):
            pass

        def start(self, *, owning_agent_id):
            started["adapter"] = True
            return harness_session()

        def send(self, session, command):
            pass

        def events(self):
            return iter(())

        def close(self):
            pass

        def force_stop(self):
            pass

        def observe_lifecycle(self, session):
            return {"stop_observed": True}

    monkeypatch.setattr(runtime_bridge, "load_adapter",
                        lambda adapter_id: _FakeAdapter)
    clock = FakeClock(100.0)

    async def environment(prepared):
        return {}

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _codex_candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)}, clock=clock)
        try:
            deadline = 160.0
            auth = replace(context(), lease_deadline_monotonic=deadline)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            # Hold the REAL adapter start lock: the thread-level guard
            # already passed; only the wait inside connector.start
            # remains before the spawn primitive.
            import nexus_connector_core.native.adapters.codex as cm
            lock_holder = cm.CodexAppServerConnector(
                command=["lab"], cwd=os.getcwd())
            # Use the runtime's own adapter instance once created: hook
            # load_adapter to hand back a connector whose class shares a
            # class-level lock is wrong; instead block via the sentinel
            # adapter start path: patch adapter start to acquire the real
            # connector's _start_lock through the factory's connector.
            # Simpler faithful path: run the REAL Codex connector here.
            real_connector = cm.CodexAppServerConnector(
                command=["lab-codex"], cwd=os.getcwd())
            monkeypatch.setattr(
                runtime_bridge, "load_adapter",
                lambda adapter_id: (lambda **kw: real_connector))
            acquired = real_connector._start_lock.acquire(timeout=1)
            assert acquired

            loop = asyncio.get_running_loop()
            loop.set_default_executor(
                concurrent.futures.ThreadPoolExecutor(max_workers=2))
            park = threading.Event()
            busy = loop.run_in_executor(None, lambda: park.wait(5))
            await asyncio.sleep(0.05)

            opening = asyncio.create_task(runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared),
                auth))
            await asyncio.sleep(0.4)  # connector.start waits on the lock
            assert not opening.done(), "start never reached the lock wait"
            if case == "deadline":
                clock.advance(61.0)
            else:
                await runtime.shutdown(ShutdownPolicy(drain_seconds=0.0,
                                                      interrupt_seconds=0.0))
            real_connector._start_lock.release()  # start wakes past guard
            park.set()
            await asyncio.wrap_future(busy)
            with pytest.raises(CoreError):
                await asyncio.wait_for(opening, timeout=5)
            assert spawn_calls["count"] == 0, (
                f"{case}: spawn primitive reached after the guard tripped")
        finally:
            try:
                real_connector._start_lock.release()
            except RuntimeError:
                pass
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# positive control (AC5-01-05) - normal turn stays guarded post-C4
# ------------------------------------------------------------------ #

def test_control_c4_guarded_turn_refuses_after_real_write_lock():
    async def run():
        connector, transport, stdin = _wired_codex_connector()
        connector._sessions_by_id["native-session"] = codex_module._ThreadState(
            "native-session", "thread-1", "agent")
        clock = FakeClock(100.0)
        fence = runtime_bridge.EffectFence(
            lambda: (False, False, False, False, False),
            clock=clock.monotonic, lease_deadline=160.0)
        session = _bridge_session(connector, fence=fence)

        loop = asyncio.get_running_loop()
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=2))
        park = threading.Event()
        busy = loop.run_in_executor(None, lambda: park.wait(5))
        assert transport._write_lock.acquire(timeout=1)
        await asyncio.sleep(0.05)

        sending = asyncio.create_task(session.send(
            "send_turn", {"text": "late"}, "op-late"))
        await asyncio.sleep(0.3)
        assert not sending.done(), "send never reached the lock wait"
        clock.advance(61.0)
        transport._write_lock.release()
        park.set()
        await asyncio.wrap_future(busy)
        with pytest.raises(runtime_bridge.RuntimeCommandNotSent):
            await asyncio.wait_for(sending, timeout=5)
        assert stdin.bytes == b""
        await session.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# U03 (AC5-02-01) - cancelled open still supervises the late result
# ------------------------------------------------------------------ #

class _LateHandleNative:
    native_id = "native-1"

    def __init__(self):
        self.queue = asyncio.Queue()
        self.stopped = False
        self.contained = threading.Event()
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
        self.contained.set()
        self.stopped = True
        await self.queue.put(None)
        return "graceful"

    async def force_stop(self):
        self.contained.set()
        self.stopped = True

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


def test_u03_cancelled_open_still_supervises_late_native_result(tmp_path):
    clock = FakeClock(100.0)

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        native = _LateHandleNative()

        class _Factory:
            async def open(self, prepared, session_id, auth, *,
                           stream_epoch):
                # The native producer blocks inside a worker thread and
                # returns a LIVE handle long after the caller gave up.
                await asyncio.to_thread(native.start_gate.wait, 5)
                return native

        async def environment(prepared):
            return {}

        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _codex_candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)},
            native_factory=_Factory(), clock=clock)
        key = SessionKey("srv", "exe", "session")
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=clock.now + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            opening = asyncio.create_task(runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared),
                auth))
            await asyncio.sleep(0.2)  # the producer is blocked in-thread
            opening.cancel()
            try:
                await opening
            except BaseException:
                pass
            await asyncio.sleep(0.05)
            # C6/V02c adaptation: the WAITER is done but the attempt
            # STAYS registered while its producer can still produce an
            # effect (shutdown keeps fencing it); it is removed only
            # when the late result is consumed below.
            attempt = runtime._opening.get(key)
            assert attempt is not None and attempt.waiter_done
            # Conservative unknown retention without a consumed handle:
            assert key in runtime._uncertain_opens
            await runtime.shutdown(ShutdownPolicy())
            # The blocked worker NOW returns a live handle: the runtime
            # must consume it and request containment - never abandon it.
            native.start_gate.set()
            assert await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, native.contained.wait, 3.0), timeout=6), (
                "late native handle was never supervised/contained")
            deadline = time.monotonic() + 5
            while key in runtime._uncertain_opens and \
                    time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert key not in runtime._uncertain_opens, (
                "uncertainty never resolved after containment")
            assert key not in runtime._opening, (
                "attempt never resolved after containment")
            # A second shutdown is idempotent over the resolved attempt.
            await runtime.shutdown(ShutdownPolicy())
        finally:
            native.start_gate.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# U04 (AC5-03) - zero shutdown shortens an existing FUTURE force
# ------------------------------------------------------------------ #

class _CloseBlockedForceNative(_LateHandleNative):
    def __init__(self):
        super().__init__()
        self.start_gate.set()
        self.close_gate = asyncio.Event()

    async def close(self):
        await self.close_gate.wait()
        self.stopped = True
        await self.queue.put(None)
        return "graceful"


def test_u04_zero_shutdown_shortens_existing_future_force(tmp_path):
    clock = FakeClock(100.0)

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        native = _CloseBlockedForceNative()

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
            cleanup_budget_seconds=0.2)
        key = SessionKey("srv", "exe", "session")
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=clock.now + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            await runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared),
                auth)
            # First shutdown with a LONG budget schedules the force for
            # ~40s out; the graceful close never confirms.
            started = time.monotonic()
            first = asyncio.create_task(runtime.shutdown(
                ShutdownPolicy(drain_seconds=20.0, interrupt_seconds=20.0)))
            await asyncio.sleep(0.3)  # close entered; force scheduled far
            # A second, ZERO-budget shutdown must ANTICIPATE the dispatch.
            second = await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.0,
                                                interrupt_seconds=0.0)),
                timeout=5)
            assert second.session_outcomes[key] == "unknown"
            assert await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, native.contained.wait, 2.0), timeout=6), (
                "zero shutdown did not shorten the scheduled force")
            assert time.monotonic() - started < 10, (
                "the dispatch waited for the old far deadline")
        finally:
            native.close_gate.set()
            try:
                await asyncio.wait_for(first, timeout=10)
            except BaseException:
                pass
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# U06 (AC5-04) - ambiguous post-commit revoke blocks work and reconciles
# ------------------------------------------------------------------ #

class _ConfirmLossRevokeJournal(SQLiteJournal):
    def __init__(self, path):
        super().__init__(path)
        self.armed = False

    async def cas_session_lease(self, session, **kwargs):
        if kwargs.get("revoked") and self.armed:
            result = await super().cas_session_lease(session, **kwargs)
            # Commit happened; the confirmation to the caller is LOST
            # (explicit possible-effect error, per the public port).
            raise CoreError("CAS_CONFIRMATION_LOST", "cas_commit",
                            possible_effect=True)
        return await super().cas_session_lease(session, **kwargs)


def test_u06_ambiguous_revoke_blocks_work_and_reconciles_committed_lease(
        tmp_path):
    clock = FakeClock(100.0)

    async def run():
        journal = _ConfirmLossRevokeJournal(tmp_path / "journal.db")
        native = _CloseBlockedForceNative()
        native.close_gate.set()

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
            reconnect_fence_seconds=1.0)
        key = SessionKey("srv", "exe", "session")
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=clock.now + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            await runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared),
                auth)
            # Durable proof the revoke COMMITTED.
            journal.armed = True
            with pytest.raises(CoreError) as excinfo:
                await runtime.revoke_lease(
                    key, replace(auth, authorization_revision=2),
                    expected_connection_generation=auth.connection_generation)
            assert excinfo.value.possible_effect
            lease = await journal.get_session_lease(key)
            assert lease is not None and lease.revoked
            # The OLD context must not grant work after reconciliation.
            with pytest.raises(CoreError):
                await runtime.submit(
                    TurnOperation("post", "session", "hello"), auth)
            assert native.sent if hasattr(native, "sent") else True
            await asyncio.sleep(0.1)
            binding = runtime._sessions.get(key)
            if binding is not None:
                assert binding.revoked or binding.lease_expired or \
                    binding.closing or binding.closed, (
                    "memory was never fenced after the committed revoke")
        finally:
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# U05 (AC5-05) - Pi launch revalidates CLI/dependency artifacts
# ------------------------------------------------------------------ #

def _pi_launch_fixture(tmp_path):
    install = tmp_path / "install"
    node = tmp_path / "node.exe"
    node.write_bytes(b"node-bytes")
    node.chmod(0o755)
    scope = install / "node_modules" / "@earendil-works"
    package = scope / "pi-coding-agent"
    (package / "dist" / "bundle").mkdir(parents=True)
    (package / "dist" / "bundle" / "cli.js").write_bytes(b"cli-v1")
    (package / "package.json").write_text(json.dumps(
        {"name": "pi", "version": "0.87.1",
         "dependencies": {"helper": "1.0.0"}}))
    helper = install / "node_modules" / "helper"
    helper.mkdir(parents=True)
    (helper / "package.json").write_text(
        '{"name":"helper","version":"1.0.0"}')
    (helper / "index.js").write_bytes(b"helper-v1")
    cli = package / "dist" / "bundle" / "cli.js"
    candidate = candidate_pi_node_cli(node, cli, explicit=True)
    return node, package, cli, helper / "index.js", candidate


@pytest.mark.parametrize("case", ["cli", "dependency"])
def test_u05_pi_launch_revalidates_non_node_artifacts(
        tmp_path, monkeypatch, case):
    _patch_factory_gates(monkeypatch)
    started = {"adapter": False}

    class _FakeAdapter:
        def __init__(self, **kwargs):
            pass

        def start(self, *, owning_agent_id):
            started["adapter"] = True
            return harness_session()

        def send(self, session, command):
            pass

        def events(self):
            return iter(())

        def close(self):
            pass

        def force_stop(self):
            pass

        def observe_lifecycle(self, session):
            return {"stop_observed": True}

    monkeypatch.setattr(runtime_bridge, "load_adapter",
                        lambda adapter_id: _FakeAdapter)
    node, package, cli, dep_index, candidate = _pi_launch_fixture(tmp_path)
    target = cli if case == "cli" else dep_index

    async def environment(prepared):
        target.write_bytes(b"DRIFTED")  # ordinary content change
        return {}

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"pi_rpc": candidate},
            workspace_roots={"ws": str(tmp_path)})
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=time.monotonic() + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "pi_rpc"), auth)
            with pytest.raises(CoreError) as excinfo:
                await runtime.open(
                    OpenOperation("open-op", "session", "epoch", prepared),
                    auth)
            assert excinfo.value.code == "PROFILE_DRIFT", (
                f"{case} drift reached the launch")
            assert not started["adapter"], (
                f"{case}: adapter started with drifted content")
        finally:
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# U07 (AC5-06) - directory scan enforces budget DURING enumeration
# ------------------------------------------------------------------ #

def test_u07_directory_scan_enforces_budget_during_enumeration(
        tmp_path, monkeypatch):
    import nexus_connector_core.build_identity as bi
    install = tmp_path / "install"
    node = tmp_path / "node.exe"
    node.write_bytes(b"n")
    node.chmod(0o755)
    package = install / "node_modules" / "@earendil-works" / "pi-coding-agent"
    (package / "dist" / "bundle").mkdir(parents=True)
    (package / "dist" / "bundle" / "cli.js").write_bytes(b"cli")
    (package / "package.json").write_text('{"name":"pi","version":"1"}')
    wide = package / "wide"
    wide.mkdir()
    for i in range(1000):
        (wide / f"f{i}.txt").write_bytes(b"x")

    names_seen = {"count": 0}
    real_scandir = os.scandir
    real_listdir = os.listdir

    def counting_scandir(path, *a, **k):
        iterator = real_scandir(path, *a, **k)

        def wrapped():
            for entry in iterator:
                names_seen["count"] += 1
                yield entry
        return wrapped()

    def counting_listdir(path, *a, **k):
        result = real_listdir(path, *a, **k)
        names_seen["count"] += len(result)
        return result

    monkeypatch.setattr(bi.os, "scandir", counting_scandir)
    monkeypatch.setattr(bi.os, "listdir", counting_listdir)
    old_cap = bi._MAX_MANIFEST_ENTRIES
    try:
        bi._MAX_MANIFEST_ENTRIES = 4
        with pytest.raises(ValueError):
            pi_build_identity(node, package)
    finally:
        bi._MAX_MANIFEST_ENTRIES = old_cap
    assert names_seen["count"] <= 5, (
        f"enumeration obtained {names_seen['count']} names for a "
        "4-entry budget (cap+1 sentinel allowed, never more)")

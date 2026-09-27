"""C2 correction seeds — reaudit findings R01-R10 against the real Core.

Each test mirrors the independent reaudit of e6b6305
(FIX_UPDATE_PLAN/RELATORIO_REAVALIACAO_CORE_E6B6305.md). They describe
the required behavior; on the audited code each one failed (recorded
2026-09-27 before any fix). Markers are removed as each C2 phase lands.
"""

import asyncio
import ctypes
import gc
import sys
import threading
import time
import weakref
from dataclasses import replace
from pathlib import Path

import pytest

from nexus_connector_core import (
    CoreError, ExecutionContext, InstallationCandidate, LaunchIntent,
    OpenOperation, RuntimeEvent, SessionKey, ShutdownPolicy, TurnOperation,
    create_runtime,
)
from nexus_connector_core.build_identity import pi_build_identity
from nexus_connector_core.discovery import (
    candidate_pi_node_cli, fingerprint as discovery_fingerprint,
    probe_selected_codex,
)
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.native import runtime_bridge
from nexus_connector_core.native.process import preflight
from nexus_connector_core.offloop import OffLoopExecutor

from tests.test_runtime import FakeClock, context, make_runtime

_SEEDS = pytest.mark.xfail(strict=True, reason="C2 reaudit finding")


# ------------------------------------------------------------------ #
# R01 - storage reads must never hold the global state lock
# ------------------------------------------------------------------ #

class _RetainedGetReceiptJournal(SQLiteJournal):
    """Retains get_receipt for one operation until released."""

    def __init__(self, path, held_operation: str):
        super().__init__(path)
        self._held = held_operation
        self.release = asyncio.Event()
        self.read_entered = asyncio.Event()

    async def get_receipt(self, key):
        if key.operation_id == self._held:
            self.read_entered.set()
            await self.release.wait()
        return await super().get_receipt(key)


class _ForceNative:
    native_id = "native-1"

    def __init__(self):
        self.sent = []
        self.queue = asyncio.Queue()
        self.stopped = False
        self.force_called = threading.Event()

    async def send(self, verb, payload, operation_id, *,
                   expected_turn_id=None):
        self.sent.append((verb, dict(payload), operation_id))

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


async def _open_force_session(tmp_path, clock):
    """Open one session with a retained-get_receipt journal (same loop)."""
    journal = _RetainedGetReceiptJournal(
        tmp_path / "journal.db", "held-op")
    binary = tmp_path / "codex"
    binary.write_bytes(b"synthetic binary")
    candidate = InstallationCandidate(
        "codex_app_server", str(binary), discovery_fingerprint(binary),
        "explicit", "selected")
    native = _ForceNative()

    class _Factory:
        async def open(self, prepared, session_id, auth, *, stream_epoch):
            return native

    async def unused_environment(prepared):
        return {}

    runtime = create_runtime(
        journal=journal, environment=unused_environment, candidates={
            "codex_app_server": candidate},
        workspace_roots={"ws": str(tmp_path)},
        native_factory=_Factory(),
        clock=clock, lease_grace_seconds=0.0, lease_poll_seconds=0.01,
        max_lease_seconds=120.0)
    auth = replace(context(), lease_deadline_monotonic=clock.now + 60)
    prepared = await runtime.prepare(
        LaunchIntent("agent", "ws", "codex_app_server"), auth)
    opened = await runtime.open(
        OpenOperation("open-op", "session", "epoch", prepared), auth)
    assert opened.stage == "SUBMITTED"
    return runtime, journal, native


async def _wait_force(native):
    return await asyncio.get_running_loop().run_in_executor(
        None, native.force_called.wait, 2.0)


def test_r01_storage_read_under_global_lock_must_not_block_lease_containment(
        tmp_path):
    clock = FakeClock()

    async def run():
        runtime, journal, native = await _open_force_session(tmp_path, clock)
        try:
            submit = asyncio.create_task(
                runtime.submit(TurnOperation("held-op", "session", "hello"),
                               replace(context(),
                                       lease_deadline_monotonic=clock.now + 60)))
            await asyncio.wait_for(journal.read_entered.wait(), timeout=5)
            # The retained storage read is in flight; the lease now expires
            # beyond every tolerance. Physical containment must still fire.
            clock.advance(120)
            assert await asyncio.wait_for(_wait_force(native), timeout=5), (
                "lease containment waited for a journal storage read")
        finally:
            journal.release.set()
            try:
                await asyncio.wait_for(submit, timeout=5)
            except BaseException:
                pass
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.05,
                                                interrupt_seconds=0.05)),
                timeout=10)
            journal.close()

    asyncio.run(run())


def test_r01b_eof_fence_must_not_wait_for_journal_read_lock(tmp_path):
    clock = FakeClock()

    async def run():
        runtime, journal, native = await _open_force_session(tmp_path, clock)
        key = SessionKey("srv", "exe", "session")
        try:
            submit = asyncio.create_task(
                runtime.submit(TurnOperation("held-op", "session", "hello"),
                               replace(context(),
                                       lease_deadline_monotonic=clock.now + 60)))
            await asyncio.wait_for(journal.read_entered.wait(), timeout=5)
            native.queue.put_nowait(None)  # stream EOF while read is held

            async def _faulted() -> bool:
                binding = runtime._sessions.get(key)
                return binding is None or binding.faulted

            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if await _faulted():
                    break
                await asyncio.sleep(0.01)
            assert await _faulted(), (
                "EOF fence waited for the global lock behind a journal read")
        finally:
            journal.release.set()
            try:
                await asyncio.wait_for(submit, timeout=5)
            except BaseException:
                pass
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.05,
                                                interrupt_seconds=0.05)),
                timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# R02 - containment capacity independent of the default executor
# ------------------------------------------------------------------ #

class _SyncPeer:
    def __init__(self):
        self.started = False
        self.forced = threading.Event()
        self.session = object()

    def start(self, *, owning_agent_id: str):
        self.started = True
        return self.session

    def send(self, session, command):
        pass

    def events(self):
        return iter(())

    def close(self):
        pass

    def force_stop(self):
        self.forced.set()

    def observe_lifecycle(self, session):
        return {}


def test_r02_force_must_have_capacity_independent_of_default_thread_pool():
    from tests.test_c1_bridge_stubs import harness_session

    async def run():
        import concurrent.futures
        loop = asyncio.get_running_loop()
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=1))
        release = threading.Event()
        busy = loop.run_in_executor(None, lambda: release.wait(10))
        await asyncio.sleep(0.05)  # the single default worker is now busy
        try:
            peer = _SyncPeer()
            session = runtime_bridge.CopiedAdapterSession(
                peer, harness_session(), session_id="s", stream_epoch="e",
                context=ExecutionContext(
                    "srv", "exe", "bind", "agent", "ws", 1, 1, 1,
                    time.monotonic() + 60,
                    frozenset({"turn.submit", "turn.interrupt"})))
            # The single default-executor worker stays blocked; the
            # physical force must still be reached within reserved capacity.
            await asyncio.wait_for(session.force_stop(), timeout=3)
            assert peer.forced.is_set(), (
                "physical force sat in the same queue as blocked normal work")
            state, _ = await asyncio.wait_for(session.observe(), timeout=5)
            assert state == "RUNNING"  # no stop confirmation is not stop
            await session.close()
        finally:
            release.set()
            await asyncio.wrap_future(busy)

    asyncio.run(run())


# ------------------------------------------------------------------ #
# R03 - the guard consults the live clock at the write frontier
# ------------------------------------------------------------------ #

class _ClockLateNative:
    native_id = "native-1"

    def __init__(self):
        self.writes = []

    async def send(self, verb, payload, operation_id, *,
                   expected_turn_id=None):
        self.writes.append((verb, operation_id))

    async def events(self):
        return
        yield  # pragma: no cover

    async def close(self):
        return "graceful"

    async def observe(self):
        return ("STOPPED", "IDLE")


def test_r03_late_dispatch_checks_clock_not_only_watcher_flags():
    from tests.test_c1_bridge_stubs import harness_session

    async def run():
        native = _ClockLateNative()
        session = runtime_bridge.CopiedAdapterSession(
            native, harness_session(), session_id="s", stream_epoch="e",
            context=ExecutionContext(
                "srv", "exe", "bind", "agent", "ws", 1, 1, 1,
                time.monotonic() + 60,
                frozenset({"turn.submit", "turn.interrupt"})))
        clock = FakeClock(100.0)
        # Starts valid: every watcher flag is clean and the deadline is in
        # the future. It expires while the dispatch waits for a worker.
        fence = runtime_bridge.EffectFence(
            lambda: (False, False, False, False, False),
            clock=clock.monotonic, lease_deadline=100.5)
        session.effect_fence = fence

        import concurrent.futures
        loop = asyncio.get_running_loop()
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=1))
        release = threading.Event()
        busy = loop.run_in_executor(None, lambda: release.wait(5))
        await asyncio.sleep(0.05)

        async def dispatch():
            await session.send("send_turn", {"text": "late"}, "op-late")

        task = asyncio.create_task(dispatch())
        await asyncio.sleep(0.1)  # queued, not yet running
        clock.advance(1.0)  # the lease expires mid-wait
        release.set()
        await asyncio.wrap_future(busy)
        with pytest.raises(runtime_bridge.RuntimeCommandNotSent):
            await asyncio.wait_for(task, timeout=5)
        assert native.writes == []
        await session.close()

    asyncio.run(run())


def test_r03b_factory_must_revalidate_after_environment_resolution(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        runtime_bridge, "qualified_build", lambda *a, **k: True,
        raising=True)
    monkeypatch.setattr(
        "nexus_connector_core.native.process.require_containment",
        lambda: None, raising=True)
    started = {"adapter": False}

    class _FakeAdapter(_SyncPeer):
        def start(self, *, owning_agent_id: str):
            started["adapter"] = True
            return super().start(owning_agent_id=owning_agent_id)

    monkeypatch.setattr(runtime_bridge, "load_adapter",
                        lambda adapter_id: _FakeAdapter)

    clock = FakeClock(100.0)

    async def environment(prepared):
        # The environment callback stalls; the lease expires while it
        # resolves, before any process exists.
        clock.advance(200)
        return {}

    async def run():
        binary = tmp_path / "codex"
        binary.write_bytes(b"synthetic binary")
        candidate = InstallationCandidate(
            "codex_app_server", str(binary), discovery_fingerprint(binary),
            "explicit", "selected")
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": candidate},
            workspace_roots={"ws": str(tmp_path)}, clock=clock,
            lease_grace_seconds=0.0, lease_poll_seconds=0.01)
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=clock.now + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            with pytest.raises(CoreError):
                await runtime.open(
                    OpenOperation("open-op", "session", "epoch", prepared),
                    auth)
            assert not started["adapter"], (
                "factory spawned after the lease had already expired")
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# R04 - idempotent receipts survive stream faults and eviction
# ------------------------------------------------------------------ #

def test_r04_duplicate_known_submit_survives_stream_fault(tmp_path):
    async def run():
        runtime, journal, factory = make_runtime(tmp_path)
        auth = context()
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            await runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared), auth)
            first = await runtime.submit(
                TurnOperation("known", "session", "hello"), auth)
            # Stream EOF: the session is faulted but the durable receipt
            # of the completed submit must answer the retry.
            factory.native.queue.put_nowait(None)
            await asyncio.sleep(0.05)
            again = await runtime.submit(
                TurnOperation("known", "session", "hello"), auth)
            assert again.intent_hash == first.intent_hash
            assert again.stage == first.stage
            assert len([s for s in factory.native.sent
                        if s[2] == "known"]) == 1, "duplicate native write"
            with pytest.raises(CoreError, match="OPERATION_CONFLICT"):
                await runtime.submit(
                    TurnOperation("known", "session", "different"), auth)
            await runtime.shutdown(ShutdownPolicy())
            # After full close and eviction the receipt still answers.
            once_more = await runtime.submit(
                TurnOperation("known", "session", "hello"), auth)
            assert once_more.stage == first.stage
        finally:
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# R05 - worker wake notifications are bounded
# ------------------------------------------------------------------ #

def test_r05_wake_notifications_are_bounded_under_sustained_load():
    executor = OffLoopExecutor(name="r05", normal_capacity=1,
                               urgent_capacity=1)
    try:
        executor.start(lambda: object())
        observed = []

        def chain(index: int):
            if index == 100:
                observed.append(executor.notification_backlog())
            if index + 1 < 200:
                executor.submit_nowait(lambda _r: chain(index + 1))

        executor.submit_nowait(lambda _r: chain(0))
        deadline = time.monotonic() + 30
        while not observed and time.monotonic() < deadline:
            time.sleep(0.005)
        assert observed, "sustained chain never progressed"
        assert observed[0] <= 1, (
            "wake notifications grow with total work, not capacity")
        assert executor.notification_backlog() <= 1
    finally:
        executor.request_stop()
        assert executor.join(timeout=5)


# ------------------------------------------------------------------ #
# R06 - Pi build identity: correct root, declared dependencies covered
# ------------------------------------------------------------------ #

def _write_pi_package(scope_root: Path, *, cli=b"cli-bytes",
                      version="0.87.1", dep: str | None = None) -> Path:
    package = scope_root / "pi-coding-agent"
    (package / "dist" / "bundle").mkdir(parents=True, exist_ok=True)
    (package / "dist" / "bundle" / "cli.js").write_bytes(cli)
    package_json = '{"name":"pi","version":"%s"}' % version
    manifest = package_json
    if dep is not None:
        manifest = package_json[:-1] + \
            f', "dependencies": {{"leftpad": "1.0.0"}}}}'
    (package / "package.json").write_text(manifest)
    return package


def test_r06_pi_build_ignores_unrelated_sibling_package(tmp_path):
    install = tmp_path / "install"
    node = tmp_path / "node.exe"
    node.write_bytes(b"node-bytes")
    node.chmod(0o755)  # POSIX selection requires the executable bit
    scope = install / "node_modules" / "@earendil-works"
    scope.mkdir(parents=True)
    package = _write_pi_package(scope)
    cli = package / "dist" / "bundle" / "cli.js"
    base = candidate_pi_node_cli(node, cli, explicit=True).build_identity

    # Same package content in a different directory: identical identity.
    other = tmp_path / "elsewhere" / "node_modules" / "@earendil-works"
    other.mkdir(parents=True)
    twin = _write_pi_package(other)
    twin_cli = twin / "dist" / "bundle" / "cli.js"
    assert candidate_pi_node_cli(
        node, twin_cli, explicit=True).build_identity == base

    # An unrelated sibling package under the same scope is not Pi code.
    sibling = scope / "unrelated-pkg"
    sibling.mkdir()
    (sibling / "noise.txt").write_bytes(b"noise")
    assert candidate_pi_node_cli(
        node, cli, explicit=True).build_identity == base


def test_r06b_pi_build_covers_resolvable_dependencies_outside_scope(tmp_path):
    install = tmp_path / "install"
    node = tmp_path / "node.exe"
    node.write_bytes(b"node-bytes")
    node.chmod(0o755)  # POSIX selection requires the executable bit
    scope = install / "node_modules" / "@earendil-works"
    scope.mkdir(parents=True)
    package = _write_pi_package(scope, dep="leftpad")
    dep_dir = install / "node_modules" / "leftpad"
    dep_dir.mkdir(parents=True)
    (dep_dir / "index.js").write_bytes(b"leftpad-v1")
    (dep_dir / "package.json").write_text(
        '{"name":"leftpad","version":"1.0.0","main":"index.js"}')

    base = pi_build_identity(node, package)
    (dep_dir / "index.js").write_bytes(b"leftpad-v2")
    changed = pi_build_identity(node, package)
    assert changed != base, (
        "a declared, resolvable dependency changed without changing identity")

    # Undeclared packages in node_modules stay out of the identity.
    stray = install / "node_modules" / "stray"
    stray.mkdir()
    (stray / "x.js").write_bytes(b"stray")
    assert pi_build_identity(node, package) == changed


# ------------------------------------------------------------------ #
# R07 - correct subreaper ABI; active probes behind the containment gate
# ------------------------------------------------------------------ #

def test_r07_preflight_queries_actual_subreaper_abi():
    calls = []

    def fake_prctl(op, arg2, arg3, arg4, arg5):
        calls.append((op, arg2, arg3, arg4, arg5))
        arg2._obj.value = 0  # the kernel writes the flag through int*
        return 0

    status = preflight._query_subreaper(fake_prctl)
    assert status == "ok"
    (op, arg2, *_rest) = calls[0]
    assert op == 37, "PR_GET_CHILD_SUBREAPER is operation 37"
    assert hasattr(arg2, "_obj") and isinstance(
        arg2._obj, ctypes.c_int), "the query must pass an int* out pointer"


def test_r07b_active_version_probe_must_refuse_before_observer_if_containment_unavailable(
        tmp_path, monkeypatch):
    from nexus_connector_core.native.adapters import compatibility

    def refuse():
        raise CoreError("PROCESS_CONTAINMENT_UNAVAILABLE", "preflight",
                        retry_safe=True)

    monkeypatch.setattr(
        "nexus_connector_core.discovery.require_containment", refuse)
    reached = {"observer": False}

    def sentinel_observer(command, *, cwd, env):
        reached["observer"] = True
        return {"native_version": "0.0.0"}

    monkeypatch.setattr(compatibility, "codex_version_observation",
                        sentinel_observer)

    async def run():
        binary = tmp_path / "codex"
        binary.write_bytes(b"synthetic binary")
        candidate = InstallationCandidate(
            "codex_app_server", str(binary),
            discovery_fingerprint(binary), "explicit", "selected")
        with pytest.raises(CoreError) as excinfo:
            await probe_selected_codex(candidate, cwd=str(tmp_path), env={})
        # C3/S07: the typed code is the stable contract; details live in
        # the message field (fixture adapted to the coordinated contract).
        assert excinfo.value.code == "PROCESS_CONTAINMENT_UNAVAILABLE"
        assert not reached["observer"], (
            "an active probe spawned before the containment gate refused")

    asyncio.run(run())


# ------------------------------------------------------------------ #
# R08 - the public discovery path composes the Pi release resolver
# ------------------------------------------------------------------ #

def test_r08_discovery_public_path_reuses_pi_layout_resolution(tmp_path):
    from nexus_connector_core import DiscoveryRequest, LocalRuntimeCore

    async def run():
        install = tmp_path / "piroot"
        install.mkdir(parents=True)
        node = install / "node.exe"
        node.write_bytes(b"node-bytes")
        node.chmod(0o755)  # POSIX selection requires the executable bit
        for version in ("0.86.0", "0.87.1"):
            release = install / "releases" / version
            _write_pi_package(
                release / "node_modules" / "@earendil-works",
                cli=f"cli-{version}".encode(), version=version)
        journal = SQLiteJournal(tmp_path / "journal.db")

        async def noop_open(prepared, session_id, context, *,
                            stream_epoch):
            raise AssertionError("discovery never opens")

        runtime = LocalRuntimeCore(
            journal, noop_open, candidates={},
            workspace_roots={"ws": str(tmp_path)},
            trusted_discovery_roots=(tmp_path,),
            pi_install_root=install, pi_node=node)
        try:
            inventory = await runtime.discover(
                DiscoveryRequest(("pi_rpc",)))
            versions = {c.version for c in inventory.candidates}
            assert versions == {"0.86.0", "0.87.1"}, (
                "the public path must surface the Pi release layouts")
            assert inventory.candidates[0].version == "0.87.1"
            assert all(c.launch_script.endswith("cli.js")
                       for c in inventory.candidates)
        finally:
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# R09 - public resume contract without private imports
# ------------------------------------------------------------------ #

def test_r09_public_resume_contract_is_constructible_without_private_import():
    from nexus_connector_core import CodexResumeGrant  # public import only

    assert runtime_bridge.CodexResumeGrant is CodexResumeGrant
    grant = CodexResumeGrant(
        thread_id="thread-1", session_id="s", server_id="srv",
        executor_id="exe", binding_id="bind", agent_id="agent",
        workspace_id="ws", session_owner_generation=1,
        candidate_fingerprint="sha256:" + "0" * 64,
        root_fingerprint="sha256:" + "0" * 64,
        profile_fingerprint="sha256:" + "0" * 64,
        terminal_observed=True, persisted_rollout_observed=True,
        exclusive_owner=True)
    assert grant.thread_id == "thread-1"
    import typing
    hints = typing.get_type_hints(create_runtime)
    environment = str(hints["environment"])
    assert "PreparedLaunch" in environment
    assert "InstallationCandidate" not in environment


# ------------------------------------------------------------------ #
# R10 - stopped sessions release natives even with a stalled sink
# ------------------------------------------------------------------ #

def test_r10_stopped_session_native_is_released_even_when_host_sink_stalls(
        tmp_path):
    async def run():
        stall = asyncio.Event()
        delivered = []

        async def stalled_sink(event):
            delivered.append(event)
            await stall.wait()

        runtime, journal, factory = make_runtime(
            tmp_path, event_sink=stalled_sink, cleanup_budget_seconds=0.05)
        auth = context()
        key = SessionKey("srv", "exe", "session")
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            await runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared), auth)
            await runtime.submit(
                TurnOperation("turn-1", "session", "hi"), auth)
            # A real durable native event schedules the sink delivery task.
            factory.native.queue.put_nowait(RuntimeEvent(
                "srv", "exe", "session", "epoch", 0, "lifecycle",
                "x", {}))
            await asyncio.sleep(0.1)
            binding = runtime._sessions[key]
            assert binding.sink_task is not None, "sink was never scheduled"
            ref = weakref.ref(factory.native)
            await runtime.shutdown(ShutdownPolicy(drain_seconds=0.05))
            deadline = time.monotonic() + 8
            while runtime._sessions.get(key) is not None and \
                    time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert runtime._sessions.get(key) is None, "session not evicted"
            assert binding.sink_sequence == 0, \
                "cursor advanced without delivery"
            factory.native = None
            gc.collect()
            assert ref() is None, (
                "a stalled host sink kept the native adapter alive")
        finally:
            stall.set()
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# C2-10 (§6 extras): async journal construction; Win32 ABI smoke
# ------------------------------------------------------------------ #

def test_open_journal_constructs_off_the_loop(tmp_path):
    from nexus_connector_core.journal import open_journal

    async def run():
        journal = await open_journal(str(tmp_path / "j.db"))
        try:
            assert type(journal).__name__ == "SQLiteJournal"
        finally:
            await journal.aclose()

    asyncio.run(run())


def test_windows_preflight_uses_declared_win32_abi():
    if sys.platform != "win32":
        pytest.skip("Win32 ABI smoke runs on Windows")
    status = preflight.containment_preflight()
    assert status.get("job_objects") == "ok"

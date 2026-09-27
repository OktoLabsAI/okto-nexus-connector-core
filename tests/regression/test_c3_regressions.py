"""C3 correction seeds — reaudit findings S01-S08 against 7a7a248.

Each test mirrors FIX_UPDATE_PLAN/RELATORIO_REAVALIACAO_CORE_7A7A248.md.
They start authorized, cross a real wait, and the protection must trip
DURING the wait - never a fence born already closed. On the audited code
every seed fails.
"""

import asyncio
import concurrent.futures
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from nexus_connector_core import (
    CoreError, ExecutionContext, InstallationCandidate, LaunchIntent,
    OpenOperation, SessionKey, ShutdownPolicy, TurnOperation,
    create_runtime,
)
from nexus_connector_core.build_identity import pi_build_identity
from nexus_connector_core.discovery import fingerprint as discovery_fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.native import runtime_bridge
from nexus_connector_core.native.process import preflight

from tests.test_c1_bridge_stubs import harness_session
from tests.test_runtime import FakeClock, context, make_runtime

def _patch_factory_gates(monkeypatch):
    monkeypatch.setattr(runtime_bridge, "qualified_build",
                        lambda *a, **k: True, raising=True)
    monkeypatch.setattr(
        "nexus_connector_core.native.process.require_containment",
        lambda: None, raising=True)


def _candidate(tmp_path, name="codex"):
    binary = tmp_path / name
    binary.write_bytes(b"synthetic binary")
    return InstallationCandidate(
        "codex_app_server", str(binary), discovery_fingerprint(binary),
        "explicit", "selected")


# ------------------------------------------------------------------ #
# S01 - the default public composition keeps temporal protection on
# ------------------------------------------------------------------ #

def test_s01_default_public_factory_checks_expiry_after_environment(
        tmp_path, monkeypatch):
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
            return {}

    monkeypatch.setattr(runtime_bridge, "load_adapter",
                        lambda adapter_id: _FakeAdapter)

    async def environment(prepared):
        # Real-clock crossing: the deadline expires while the host's
        # environment callback resolves (stable margin, no microsecond race).
        await asyncio.sleep(1.0)
        return {}

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)})
        try:
            deadline = time.monotonic() + 0.5  # valid at admission
            auth = replace(context(), lease_deadline_monotonic=deadline)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            with pytest.raises(CoreError) as excinfo:
                await runtime.open(
                    OpenOperation("open-op", "session", "epoch", prepared),
                    auth)
            assert excinfo.value.code == "AGENT_REVOKED"
            assert not started["adapter"], (
                "default composition spawned after the lease had expired")
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# S02 - the spawn unit itself revalidates when the worker starts
# ------------------------------------------------------------------ #

def test_s02_spawn_queued_in_worker_revalidates_when_worker_starts(
        tmp_path, monkeypatch):
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
            return {}

    monkeypatch.setattr(runtime_bridge, "load_adapter",
                        lambda adapter_id: _FakeAdapter)
    clock = FakeClock(100.0)

    async def environment(prepared):
        return {}

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)}, clock=clock)
        factory = runtime._native_factory
        try:
            deadline = 160.0
            auth = replace(context(), lease_deadline_monotonic=deadline)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)

            loop = asyncio.get_running_loop()
            loop.set_default_executor(
                concurrent.futures.ThreadPoolExecutor(max_workers=1))
            release = threading.Event()
            busy = loop.run_in_executor(None, lambda: release.wait(5))
            await asyncio.sleep(0.05)

            # The factory reaches the spawn queue with a still-valid lease
            # (every pre-queue check passes); only the WORKER START is late.
            opening = asyncio.create_task(factory.open(
                prepared, "session", auth, stream_epoch="epoch"))
            await asyncio.sleep(0.2)  # the spawn unit is queued, not running
            clock.advance(61.0)  # deadline 160 -> now 161: expired mid-wait
            release.set()
            await asyncio.wrap_future(busy)
            with pytest.raises(CoreError) as excinfo:
                await asyncio.wait_for(opening, timeout=5)
            assert excinfo.value.code == "AGENT_REVOKED"
            assert not started["adapter"], (
                "the worker started the process under an expired lease")
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# S03 - permissive approval replies share the effect guard
# ------------------------------------------------------------------ #

class _ReplyPeer:
    def __init__(self):
        self.replied = threading.Event()
        self.forced = threading.Event()
        self.session = harness_session()

    def start(self, *, owning_agent_id):
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

    def reply_native_approval(self, session_id, request, decision):
        self.replied.set()


def test_s03_approval_reply_revalidates_at_delayed_native_write():
    peer = _ReplyPeer()

    async def run():
        session = runtime_bridge.CopiedAdapterSession(
            peer, harness_session("claude_code"), session_id="s",
            stream_epoch="e",
            context=ExecutionContext(
                "srv", "exe", "bind", "agent", "ws", 1, 1, 1,
                time.monotonic() + 60,
                frozenset({"turn.submit", "approval.decide",
                           "input.provide"})))
        clock = FakeClock(100.0)
        fence = runtime_bridge.EffectFence(
            lambda: (False, False, False, False, False),
            clock=clock.monotonic, lease_deadline=160.0)
        session.effect_fence = fence
        session._active_operation_id = "op-1"

        request = {"method": "control_request:can_use_tool",
                   "params": {"id": "req-1"}}

        loop = asyncio.get_running_loop()
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=1))
        release = threading.Event()
        busy = loop.run_in_executor(None, lambda: release.wait(5))
        await asyncio.sleep(0.05)

        replying = asyncio.create_task(
            session.reply_native_approval(request, "accept", None))
        await asyncio.sleep(0.2)  # queued behind the busy worker
        clock.advance(61.0)  # deadline 160 -> expired mid-wait
        release.set()
        await asyncio.wrap_future(busy)
        with pytest.raises(runtime_bridge.RuntimeCommandNotSent):
            await asyncio.wait_for(replying, timeout=5)
        assert not peer.replied.is_set(), (
            "a permissive approval produced its effect after expiry")
        # A deny-style answer stays allowed past the deadline: refusing
        # never grants work.
        await session.reply_native_approval(request, "decline", None)
        await session.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# S04 - lease CAS never holds the global containment lock
# ------------------------------------------------------------------ #

class _RetainedCasJournal(SQLiteJournal):
    def __init__(self, path):
        super().__init__(path)
        self.cas_entered = asyncio.Event()
        self.cas_release = asyncio.Event()

    async def cas_session_lease(self, session, **kwargs):
        self.cas_entered.set()
        await self.cas_release.wait()
        return await super().cas_session_lease(session, **kwargs)


class _CasNative:
    native_id = "native-1"

    def __init__(self):
        self.queue = asyncio.Queue()
        self.stopped = False
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
        self.stopped = True
        await self.queue.put(None)
        return "graceful"

    async def force_stop(self):
        self.force_called.set()

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


async def _unused_env(prepared):
    return {}


async def _open_cas_session(tmp_path, clock):
    journal = _RetainedCasJournal(tmp_path / "journal.db")
    native = _CasNative()

    class _Factory:
        async def open(self, prepared, session_id, auth, *, stream_epoch):
            return native

    runtime = create_runtime(
        journal=journal, environment=_unused_env,
        candidates={"codex_app_server": _candidate(tmp_path)},
        workspace_roots={"ws": str(tmp_path)},
        native_factory=_Factory(), clock=clock,
        lease_grace_seconds=0.0, lease_poll_seconds=0.01)
    auth = replace(context(), lease_deadline_monotonic=clock.now + 60)
    prepared = await runtime.prepare(
        LaunchIntent("agent", "ws", "codex_app_server"), auth)
    opened = await runtime.open(
        OpenOperation("open-op", "session", "epoch", prepared), auth)
    assert opened.stage == "SUBMITTED"
    return runtime, journal, native


@pytest.mark.parametrize("operation", ["renew", "revoke"])
def test_s04_lease_cas_does_not_hold_global_containment_lock(
        tmp_path, operation):
    clock = FakeClock(100.0)

    async def run():
        runtime, journal, native = await _open_cas_session(tmp_path, clock)
        key = SessionKey("srv", "exe", "session")
        auth = context()
        try:
            if operation == "renew":
                task = asyncio.create_task(runtime.renew_lease(
                    key, replace(auth, lease_deadline_monotonic=clock.now + 120,
                                 authorization_revision=2),
                    expected_connection_generation=auth.connection_generation))
            else:
                task = asyncio.create_task(runtime.revoke_lease(
                    key, replace(auth, authorization_revision=2),
                    expected_connection_generation=auth.connection_generation))
            await asyncio.wait_for(journal.cas_entered.wait(), timeout=5)
            # The CAS is retained; the lease now expires beyond every
            # tolerance. Physical containment must still be reachable.
            clock.advance(200)
            assert await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, native.force_called.wait, 2.0),
                timeout=5), (
                f"{operation} CAS held the global containment lock")
            assert not journal.cas_release.is_set()
        finally:
            journal.cas_release.set()
            try:
                await asyncio.wait_for(task, timeout=5)
            except BaseException:
                pass
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.05,
                                                interrupt_seconds=0.05)),
                timeout=10)
            journal.close()

    asyncio.run(run())


def test_s04b_late_cas_commit_applies_after_caller_cancellation(tmp_path):
    """Fault point: the CAS is delivered to the journal worker and commits
    after the caller stopped waiting - the runtime must still apply the
    durable result (recovery), never assume absence of effect."""
    clock = FakeClock(100.0)

    async def run():
        runtime, journal, native = await _open_cas_session(tmp_path, clock)
        key = SessionKey("srv", "exe", "session")
        auth = context()
        try:
            renewing = asyncio.create_task(runtime.renew_lease(
                key, replace(auth, lease_deadline_monotonic=clock.now + 120,
                             authorization_revision=2),
                expected_connection_generation=auth.connection_generation))
            await asyncio.wait_for(journal.cas_entered.wait(), timeout=5)
            renewing.cancel()
            try:
                await renewing
            except asyncio.CancelledError:
                pass
            # The worker commits the CAS afterwards.
            journal.cas_release.set()
            deadline = time.monotonic() + 5
            applied = False
            while time.monotonic() < deadline:
                binding = runtime._sessions.get(key)
                if binding is not None and \
                        binding.context.authorization_revision == 2:
                    applied = True
                    break
                await asyncio.sleep(0.02)
            assert applied, "late durable CAS commit was never applied"
        finally:
            journal.cas_release.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.05,
                                                interrupt_seconds=0.05)),
                timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# S05 - observation/close load cannot starve physical force
# ------------------------------------------------------------------ #

class _BlockingObservePeer(_ReplyPeer):
    def __init__(self):
        super().__init__()
        self.observe_gate = threading.Event()
        self.observe_calls = 0

    def observe_lifecycle(self, session):
        self.observe_calls += 1
        self.observe_gate.wait(5)
        return {}


def test_s05_observation_load_cannot_starve_reserved_physical_force():
    async def run():
        control = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        force = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        try:
            sessions = []
            for _ in range(4):
                peer = _BlockingObservePeer()
                session = runtime_bridge.CopiedAdapterSession(
                    peer, harness_session(), session_id="s",
                    stream_epoch="e",
                    context=ExecutionContext(
                        "srv", "exe", "bind", "agent", "ws", 1, 1, 1,
                        time.monotonic() + 60, frozenset({"turn.submit"})),
                    control_executor=control, force_executor=force)
                sessions.append(session)
            fifth = _ReplyPeer()
            victim = runtime_bridge.CopiedAdapterSession(
                fifth, harness_session(), session_id="v", stream_epoch="e",
                context=ExecutionContext(
                    "srv", "exe", "bind", "agent", "ws", 1, 1, 1,
                    time.monotonic() + 60, frozenset({"turn.submit"})),
                control_executor=control, force_executor=force)

            # All four control workers blocked inside observations; the
            # physical force of a fifth session must still be reached.
            observing = [asyncio.create_task(s.observe()) for s in sessions]
            # Coalescing: repeated polls on one blocked session must not
            # pile additional observation units.
            extra = [asyncio.create_task(sessions[0].observe())
                     for _ in range(3)]
            await asyncio.sleep(0.2)
            forcing = asyncio.create_task(victim.force_stop())
            assert await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, fifth.forced.wait, 2.0), timeout=5), (
                "blocked observations starved the reserved physical force")
            coalesced_calls = sessions[0]._connector.observe_calls
            for session in sessions:
                session._connector.observe_gate.set()
            for task in (*observing, *extra, forcing):
                await asyncio.wait_for(task, timeout=5)
            assert coalesced_calls <= 2, (
                "coalesced observation spawned unbounded units")
        finally:
            control.shutdown(wait=False, cancel_futures=True)
            force.shutdown(wait=False, cancel_futures=True)

    asyncio.run(run())


# ------------------------------------------------------------------ #
# S06 - identity covers the code Node actually loads
# ------------------------------------------------------------------ #

def _pi_fixture(tmp_path, dep_manifest, files):
    install = tmp_path / "install"
    node = tmp_path / "node.exe"
    node.write_bytes(b"node-bytes")
    node.chmod(0o755)
    scope = install / "node_modules" / "@earendil-works"
    package = scope / "pi-coding-agent"
    (package / "dist" / "bundle").mkdir(parents=True, exist_ok=True)
    (package / "dist" / "bundle" / "cli.js").write_bytes(b"cli")
    (package / "package.json").write_text(
        '{"name":"pi","version":"0.87.1","dependencies":{"dep":"1.0.0"}}')
    dep = install / "node_modules" / "dep"
    dep.mkdir(parents=True)
    (dep / "package.json").write_text(dep_manifest)
    for relative, content in files.items():
        target = dep / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return node, package


@pytest.mark.parametrize("case", ["implicit_index", "relative_import",
                                  "exports"])
def test_s06_qualified_identity_covers_code_node_actually_loads(
        tmp_path, case):
    if case == "implicit_index":
        manifest = '{"name":"dep","version":"1.0.0"}'
        files = {"index.js": b"v1"}
        mutate = "index.js"
    elif case == "relative_import":
        manifest = '{"name":"dep","version":"1.0.0","main":"lib/index.js"}'
        files = {"lib/index.js": b"require('./value.js')",
                 "lib/value.js": b"v1"}
        mutate = "lib/value.js"
    else:
        manifest = ('{"name":"dep","version":"1.0.0",'
                    '"exports":{".":"./entry.js"}}')
        files = {"entry.js": b"v1"}
        mutate = "entry.js"
    node, package = _pi_fixture(tmp_path, manifest, files)
    base = pi_build_identity(node, package)
    target = package.parent.parent / "dep" / mutate
    target.write_bytes(b"v2")
    changed = pi_build_identity(node, package)
    assert changed != base, (
        f"{case}: loaded-but-unlisted code changed without changing identity")
    # A different directory with identical content keeps the identity.
    other_root = tmp_path / "copy"
    other_root.mkdir()
    import shutil
    shutil.copytree(tmp_path / "install",
                    other_root / "install")
    assert pi_build_identity(node, other_root / "install/node_modules/"
                             "@earendil-works/pi-coding-agent") == changed


# ------------------------------------------------------------------ #
# S07 - machine-readable error code stays exact
# ------------------------------------------------------------------ #

def test_s07_preflight_preserves_machine_readable_error_code(monkeypatch):
    monkeypatch.setattr(
        preflight, "containment_preflight",
        lambda *, platform=None: {"job_objects": "simulated unavailable",
                                  "proc_children": "simulated unavailable"})
    with pytest.raises(CoreError) as excinfo:
        preflight.require_containment()
    assert excinfo.value.code == "PROCESS_CONTAINMENT_UNAVAILABLE", (
        "the typed code must not absorb host diagnostics")
    message = str(excinfo.value)
    assert "job_objects" in message and "proc_children" in message
    assert chr(92) not in message  # no Windows paths in the diagnostic


# ------------------------------------------------------------------ #
# S08 - public shutdown disposes the factory-owned executors
# ------------------------------------------------------------------ #

def _control_threads():
    return [t for t in threading.enumerate()
            if t.name.startswith("nexus-core-control")]


def test_s08_runtime_shutdown_releases_factory_owned_control_pool(
        tmp_path, monkeypatch):
    _patch_factory_gates(monkeypatch)

    class _ResolvableAdapter:
        def __init__(self, **kwargs):
            self.stopped = False

        def start(self, *, owning_agent_id):
            return harness_session()

        def send(self, session, command):
            pass

        def events(self):
            # A live stream: it ends when the adapter stops, never an
            # immediate EOF that would race the open barrier.
            import time as _time
            deadline = _time.monotonic() + 10
            while not self.stopped and _time.monotonic() < deadline:
                _time.sleep(0.02)
            return
            yield  # pragma: no cover

        def close(self):
            self.stopped = True  # graceful end; stop confirmed afterwards

        def force_stop(self):
            self.stopped = True

        def observe_lifecycle(self, session):
            return {"stop_observed": self.stopped}

    monkeypatch.setattr(runtime_bridge, "load_adapter",
                        lambda adapter_id: _ResolvableAdapter)

    async def environment(prepared):
        return {}

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)})
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=time.monotonic() + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            await runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared), auth)
            # A public observation activates a factory executor worker.
            await runtime.inspect(SessionKey("srv", "exe", "session"))
            assert _control_threads(), "no factory executor threads appeared"
            await runtime.shutdown(ShutdownPolicy())
            deadline = time.monotonic() + 5
            while _control_threads() and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert not _control_threads(), (
                "public shutdown left factory-owned executors open")
            # Idempotent: repeated shutdown stays safe.
            await runtime.shutdown(ShutdownPolicy())
        finally:
            journal.close()

    asyncio.run(run())


def test_s08b_uncertain_ownership_keeps_containment_capacity(
        tmp_path, monkeypatch):
    """A partial shutdown (unknown ownership) must NOT destroy the
    supervisor capacity those sessions may still need."""
    _patch_factory_gates(monkeypatch)

    class _NeverStopsAdapter:
        def __init__(self, **kwargs):
            self.stopped = False

        def start(self, *, owning_agent_id):
            return harness_session()

        def send(self, session, command):
            pass

        def events(self):
            import time as _time
            deadline = _time.monotonic() + 8
            while not self.stopped and _time.monotonic() < deadline:
                _time.sleep(0.02)
            return
            yield  # pragma: no cover

        def close(self):
            pass  # graceful end only; stop is never confirmed

        def force_stop(self):
            pass

        def observe_lifecycle(self, session):
            return {}  # stop_observed never True

    monkeypatch.setattr(runtime_bridge, "load_adapter",
                        lambda adapter_id: _NeverStopsAdapter)

    async def environment(prepared):
        return {}

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)})
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=time.monotonic() + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            await runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared), auth)
            await runtime.shutdown(ShutdownPolicy(drain_seconds=0.05))
            await asyncio.sleep(0.2)  # retention is deliberate, not instant
            assert _control_threads(), (
                "uncertain ownership destroyed containment capacity")
        finally:
            journal.close()

    asyncio.run(run())

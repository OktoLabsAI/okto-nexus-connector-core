"""C4 audit seeds â€” reaudit findings T01-T07 against 8677145.

Mirrors FIX_UPDATE_PLAN (01_RELATORIO_REAVALIACAO / 03_MATRIZ_ACEITE,
cases C4T-01..C4T-10). Each seed starts authorized, crosses a real wait,
and the protection must trip during the wait - never a fence born closed.
On the audited code every seed fails.
"""

import asyncio
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
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
from nexus_connector_core.discovery import fingerprint as discovery_fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.native import runtime_bridge
from nexus_connector_core.native.adapter_types import HarnessCommand
from nexus_connector_core.native.adapters import codex as codex_module

from tests.test_c1_bridge_stubs import harness_session
from tests.test_runtime import FakeClock, context

_SEEDS = pytest.mark.xfail(strict=True, reason="C4 reaudit finding")

NODE = shutil.which("node") or (
    r"C:\Program Files\nodejs\node.exe"
    if os.name == "nt" and Path(r"C:\Program Files\nodejs\node.exe").is_file()
    else None)


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


def _control_threads():
    return [t for t in threading.enumerate()
            if t.name.startswith("nexus-core-control")]


async def _unused_env(prepared):
    return {}


# ------------------------------------------------------------------ #
# T01 (C4T-01) - emergency force does not wait for journal admission
# ------------------------------------------------------------------ #

class _RetainedAdmitJournal(SQLiteJournal):
    def __init__(self, path):
        super().__init__(path)
        self.admit_entered = asyncio.Event()
        self.admit_release = asyncio.Event()

    async def admit(self, key, *args, **kwargs):
        if key.operation_id.startswith("core.internal.shutdown_force"):
            self.admit_entered.set()
            await self.admit_release.wait()
        return await super().admit(key, *args, **kwargs)


class _CloseBlockedNative:
    native_id = "native-1"

    def __init__(self):
        self.queue = asyncio.Queue()
        self.stopped = False
        self.force_called = threading.Event()
        self.close_gate = asyncio.Event()

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
        await self.close_gate.wait()  # graceful close never returns
        self.stopped = True
        return "graceful"

    async def force_stop(self):
        self.force_called.set()

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


def test_t01_emergency_force_does_not_wait_for_journal_admission(tmp_path):
    clock = FakeClock(100.0)

    async def run():
        journal = _RetainedAdmitJournal(tmp_path / "journal.db")
        native = _CloseBlockedNative()

        class _Factory:
            async def open(self, prepared, session_id, auth, *,
                           stream_epoch):
                return native

        async def environment(prepared):
            return {}

        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)},
            native_factory=_Factory(), clock=clock,
            lease_grace_seconds=0.0, lease_poll_seconds=0.01,
            reconnect_fence_seconds=0.2, cleanup_budget_seconds=0.2)
        key = SessionKey("srv", "exe", "session")
        auth = replace(context(), lease_deadline_monotonic=clock.now + 60)
        prepared = await runtime.prepare(
            LaunchIntent("agent", "ws", "codex_app_server"), auth)
        await runtime.open(
            OpenOperation("open-op", "session", "epoch", prepared), auth)
        report = None
        try:
            # Shutdown with a tiny budget: graceful close blocks, the
            # force escalation path runs while journal.admit is retained.
            report = await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.05,
                                                interrupt_seconds=0.05)),
                timeout=5)
            assert native.force_called.is_set() or True  # maybe already
            assert await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, native.force_called.wait, 1.5), timeout=5), (
                "emergency force waited for the journal admission")
            # Storage stays retained the whole time.
            assert not journal.admit_release.is_set()
        finally:
            native.close_gate.set()
            journal.admit_release.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy(drain_seconds=0.05,
                                                interrupt_seconds=0.05)),
                timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# T02 (C4T-02/03) - CAS failure before delivery must not poison leases
# ------------------------------------------------------------------ #

class _FailFirstCasJournal(SQLiteJournal):
    def __init__(self, path):
        super().__init__(path)
        self.failed = False

    async def cas_session_lease(self, session, **kwargs):
        if not self.failed:
            self.failed = True
            # Proven pre-delivery refusal: nothing reached the worker.
            raise CoreError("JOURNAL_FULL", "cas_submit", retry_safe=True)
        return await super().cas_session_lease(session, **kwargs)


@pytest.mark.parametrize("operation", ["renew", "revoke"])
def test_t02_cas_failure_does_not_poison_future_lease_operations(
        tmp_path, operation):
    clock = FakeClock(100.0)

    async def run():
        journal = _FailFirstCasJournal(tmp_path / "journal.db")
        native = _CloseBlockedNative()
        native.close_gate.set()  # close resolves for cleanup

        class _Factory:
            async def open(self, prepared, session_id, auth, *,
                           stream_epoch):
                return native

        async def environment(prepared):
            return {}

        runtime = create_runtime(
            journal=journal, environment=environment,
            candidates={"codex_app_server": _candidate(tmp_path)},
            workspace_roots={"ws": str(tmp_path)},
            native_factory=_Factory(), clock=clock,
            lease_grace_seconds=0.0, lease_poll_seconds=0.01,
            reconnect_fence_seconds=1.0)
        key = SessionKey("srv", "exe", "session")
        auth = replace(context(), lease_deadline_monotonic=clock.now + 60)
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            await runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared), auth)
            new_auth = replace(auth,
                               lease_deadline_monotonic=clock.now + 120,
                               authorization_revision=2)
            # First attempt fails provably before any delivery.
            with pytest.raises(CoreError):
                if operation == "renew":
                    await runtime.renew_lease(
                        key, new_auth,
                        expected_connection_generation=auth.connection_generation)
                else:
                    await runtime.revoke_lease(
                        key, new_auth,
                        expected_connection_generation=auth.connection_generation)
            # Storage recovered: the SAME operation must now progress.
            if operation == "renew":
                await runtime.renew_lease(
                    key, new_auth,
                    expected_connection_generation=auth.connection_generation)
            else:
                await runtime.revoke_lease(
                    key, new_auth,
                    expected_connection_generation=auth.connection_generation)
        finally:
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# T03 (C4T-04) - deadline rechecked after the real Codex write lock
# ------------------------------------------------------------------ #

class _RecordingStdin:
    def __init__(self):
        self.bytes = bytearray()

    def write(self, data):
        self.bytes.extend(data.encode())

    def flush(self):
        pass


def test_t03_deadline_rechecked_after_real_codex_transport_write_lock():
    async def run():
        connector = codex_module.CodexAppServerConnector(
            command=["lab-codex"], cwd=os.getcwd())
        stdin = _RecordingStdin()
        # A lab process on the REAL transport: the write frontier under
        # test is the genuine _write (lock -> guard -> stdin.write).
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
            terminate=lambda: None, kill=lambda: None, wait=lambda *a, **k: 0,
            returncode=0)
        connector._sessions_by_id["native-session"] = codex_module._ThreadState(
            "native-session", "thread-1", "agent")

        clock = FakeClock(100.0)
        fence = runtime_bridge.EffectFence(
            lambda: (False, False, False, False, False),
            clock=clock.monotonic, lease_deadline=160.0)
        session = runtime_bridge.CopiedAdapterSession(
            connector, harness_session(), session_id="s", stream_epoch="e",
            context=ExecutionContext(
                "srv", "exe", "bind", "agent", "ws", 1, 1, 1,
                time.monotonic() + 60,
                frozenset({"turn.submit", "turn.interrupt"})))
        session.effect_fence = fence

        loop = asyncio.get_running_loop()
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=1))
        release = threading.Event()
        # Hold the REAL transport write lock: the command passes the
        # bridge guard, then waits here while the clock crosses the line.
        acquired = transport._write_lock.acquire(timeout=1)
        assert acquired
        busy = loop.run_in_executor(None, lambda: release.wait(5))
        await asyncio.sleep(0.05)

        sending = asyncio.create_task(session.send(
            "send_turn", {"text": "late"}, "op-late"))
        await asyncio.sleep(0.2)  # the write unit waits on the lock
        clock.advance(61.0)  # deadline 160 -> expired mid-wait
        release.set()
        await asyncio.wrap_future(busy)
        with pytest.raises(runtime_bridge.RuntimeCommandNotSent):
            await asyncio.wait_for(sending, timeout=5)
        assert stdin.bytes == b"", (
            "expired turn/start bytes reached the transport stdin")
        await session.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# T04 (C4T-05/06) - shutdown, pending opens and drained spawns
# ------------------------------------------------------------------ #

class _LabAdapter:
    starts = 0

    def __init__(self, **kwargs):
        pass

    def start(self, *, owning_agent_id):
        type(self).starts += 1
        return harness_session()

    def send(self, session, command):
        pass

    def events(self):
        import time as _time
        deadline = _time.monotonic() + 10
        while _time.monotonic() < deadline:
            _time.sleep(0.02)
        return
        yield  # pragma: no cover

    def close(self):
        pass

    def force_stop(self):
        pass

    def observe_lifecycle(self, session):
        return {"stop_observed": True}


def _pending_open_runtime(tmp_path, monkeypatch, *, environment):
    _patch_factory_gates(monkeypatch)
    monkeypatch.setattr(runtime_bridge, "load_adapter",
                        lambda adapter_id: _LabAdapter)
    journal = SQLiteJournal(tmp_path / "journal.db")
    runtime = create_runtime(
        journal=journal, environment=environment,
        candidates={"codex_app_server": _candidate(tmp_path)},
        workspace_roots={"ws": str(tmp_path)},
        lease_grace_seconds=0.0, lease_poll_seconds=0.01)
    return runtime, journal


def test_t04_shutdown_retains_executors_while_native_open_is_pending(
        tmp_path, monkeypatch):
    release = threading.Event()

    async def environment(prepared):
        await asyncio.get_running_loop().run_in_executor(
            None, release.wait, 5)
        return {}

    async def run():
        runtime, journal = _pending_open_runtime(
            tmp_path, monkeypatch, environment=environment)
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=time.monotonic() + 60)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            opening = asyncio.create_task(runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared),
                auth))
            await asyncio.sleep(0.3)  # the open waits inside environment
            await runtime.shutdown(ShutdownPolicy(drain_seconds=0.0,
                                                  interrupt_seconds=0.0))
            # The pending open can still produce an effect: the factory's
            # capacity must NOT have been disposed (fault-injection read of
            # the runtime's own disposal state, mirroring the audit).
            await asyncio.sleep(0.1)
            assert not runtime._factory_disposed, (
                "shutdown disposed executors while an open was pending")
            release.set()
            try:
                await asyncio.wait_for(opening, timeout=5)
            except CoreError:
                pass  # a drained refusal is the correct outcome
        finally:
            release.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            # Fully resolved now: the public lifecycle DOES dispose.
            assert runtime._factory_disposed
            journal.close()

    asyncio.run(run())


def test_t04b_shutdown_fences_pending_environment_before_spawn(
        tmp_path, monkeypatch):
    release = threading.Event()
    _LabAdapter.starts = 0

    async def environment(prepared):
        await asyncio.get_running_loop().run_in_executor(
            None, release.wait, 5)
        return {}

    async def run():
        runtime, journal = _pending_open_runtime(
            tmp_path, monkeypatch, environment=environment)
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=time.monotonic() + 120)
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), auth)
            opening = asyncio.create_task(runtime.open(
                OpenOperation("open-op", "session", "epoch", prepared),
                auth))
            await asyncio.sleep(0.3)  # still waiting inside environment
            await runtime.shutdown(ShutdownPolicy(drain_seconds=0.0,
                                                  interrupt_seconds=0.0))
            # Releasing the callback AFTER shutdown must not reach start:
            # draining propagates to the spawn frontier.
            release.set()
            try:
                await asyncio.wait_for(opening, timeout=5)
            except CoreError:
                pass
            assert _LabAdapter.starts == 0, (
                "a drained opening still started the native adapter")
        finally:
            release.set()
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# T05 (C4T-07) - build drift after the environment callback
# ------------------------------------------------------------------ #

def test_t05_launch_rechecks_build_after_environment_callback(
        tmp_path, monkeypatch):
    _patch_factory_gates(monkeypatch)
    started = {"adapter": False}

    class _DriftAdapter(_LabAdapter):
        def start(self, *, owning_agent_id):
            started["adapter"] = True
            return harness_session()

    monkeypatch.setattr(runtime_bridge, "load_adapter",
                        lambda adapter_id: _DriftAdapter)
    binary = tmp_path / "codex"
    binary.write_bytes(b"synthetic binary v1")

    async def environment(prepared):
        # A local update lands while the launch waits for credentials:
        # the bytes drift away from the approved/verified snapshot.
        binary.write_bytes(b"synthetic binary v2 - UPDATED")
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
            with pytest.raises(CoreError) as excinfo:
                await runtime.open(
                    OpenOperation("open-op", "session", "epoch", prepared),
                    auth)
            assert excinfo.value.code in {"PROFILE_DRIFT"}, (
                "drifted build started without re-approval")
            assert not started["adapter"], (
                "the adapter started with content differing from prepare")
        finally:
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=10)
            journal.close()

    asyncio.run(run())


# ------------------------------------------------------------------ #
# T06 (C4T-08/09) - optional/peer dependencies present are covered
# ------------------------------------------------------------------ #

def _pi_optional_fixture(tmp_path, relation):
    install = tmp_path / "install"
    node = tmp_path / "node.exe"
    node.write_bytes(b"node-bytes")
    node.chmod(0o755)
    package = install / "node_modules" / "@earendil-works" / "pi-coding-agent"
    (package / "dist" / "bundle").mkdir(parents=True)
    (package / "dist" / "bundle" / "cli.js").write_bytes(b"cli")
    manifest = {
        "name": "pi", "version": "0.87.1",
        relation: {"helper": "1.0.0"},
    }
    (package / "package.json").write_text(json.dumps(manifest))
    helper = install / "node_modules" / "helper"
    helper.mkdir(parents=True)
    (helper / "package.json").write_text(
        '{"name":"helper","version":"1.0.0"}')
    (helper / "index.js").write_bytes(b'module.exports = "v1";')
    # The entrypoint actually loads the helper (CommonJS resolution).
    (package / "dist" / "bundle" / "cli.js").write_bytes(
        b'console.log(require("helper"));')
    return node, package, helper


@pytest.mark.parametrize("relation", ["optionalDependencies",
                                      "peerDependencies"])
def test_t06_present_production_dependencies_are_covered(tmp_path, relation):
    node, package, helper = _pi_optional_fixture(tmp_path, relation)
    base = pi_build_identity(node, package)
    helper_index = helper / "index.js"
    # Process startup on shared Windows runners can exceed ten seconds.
    # This checks dependency identity, not launch latency; keep a bounded wait.
    # Real Node proves the layout loads this file (audit's v1 -> v2).
    if NODE:
        script = package / "dist" / "bundle" / "cli.js"
        out1 = subprocess.run(
            [NODE, str(script)], capture_output=True, text=True,
            cwd=str(package), timeout=60, check=True).stdout.strip()
        assert out1 == "v1"
    helper_index.write_bytes(b'module.exports = "v2";')
    if NODE:
        script = package / "dist" / "bundle" / "cli.js"
        out2 = subprocess.run(
            [NODE, str(script)], capture_output=True, text=True,
            cwd=str(package), timeout=60, check=True).stdout.strip()
        assert out2 == "v2", "fixture must actually load the helper"
    changed = pi_build_identity(node, package)
    assert changed != base, (
        f"installed {relation} code changed without changing the identity")


# ------------------------------------------------------------------ #
# T07 (C4T-10) - byte budget checked BEFORE reading the last file
# ------------------------------------------------------------------ #

def test_t07_manifest_byte_budget_checked_before_reading_last_file(
        tmp_path, monkeypatch):
    import nexus_connector_core.build_identity as bi
    install = tmp_path / "install"
    node = tmp_path / "node.exe"
    node.write_bytes(b"n")  # 1 byte
    node.chmod(0o755)
    package = install / "node_modules" / "@earendil-works" / "pi-coding-agent"
    (package / "dist" / "bundle").mkdir(parents=True)
    # Sorted enumeration reads dist/bundle/cli.js FIRST and the 64-byte
    # package.json LAST: only the last entry must cross the budget.
    (package / "dist" / "bundle" / "cli.js").write_bytes(b"x" * 8)
    manifest = '{"name":"pi","version":"0.87.1","' + "p" * 27 + '":1}'
    assert len(manifest.encode()) == 64, len(manifest.encode())
    (package / "package.json").write_bytes(manifest.encode())
    reads = {"digest": 0}
    real_digest = bi._file_digest

    def counting_digest(path):
        reads["digest"] += 1
        return real_digest(path)

    monkeypatch.setattr(bi, "_file_digest", counting_digest)
    budget = 8 + 63  # cli.js fits exactly; package.json's 64th byte is over
    with pytest.raises(ValueError):
        with _budget(bi, _MAX_BYTES=budget):
            pi_build_identity(node, package)
    assert reads["digest"] <= 1, (
        "the oversized file was fully read before the budget refused")


class _budget:
    def __init__(self, module, *, _MAX_BYTES):
        self.module = module
        self.new = _MAX_BYTES

    def __enter__(self):
        self.old = self.module._MAX_MANIFEST_BYTES
        self.module._MAX_MANIFEST_BYTES = self.new
        return self

    def __exit__(self, *exc):
        self.module._MAX_MANIFEST_BYTES = self.old
        return False

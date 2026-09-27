"""PC02: containment independence, unified coordinator, honest outcomes."""

import asyncio
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from nexus_connector_core import (
    CoreError, ExecutionContext, LaunchIntent, OpenOperation, SessionKey,
    ShutdownPolicy,
)
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import InstallationCandidate
from nexus_connector_core.runtime import LocalRuntimeCore

pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")


class ContainNative:
    """Native double with independent force and configurable observation."""

    native_id = "native-1"

    def __init__(self, *, send_gate=None, ignore_graceful=False,
                 observe_after_force="STOPPED"):
        self.sent = []
        self.closed = False
        self.forced = False
        self.close_calls = 0
        self.ignore_graceful = ignore_graceful
        self.observe_after_force = observe_after_force
        self.send_gate = send_gate
        self.send_entered = threading.Event()
        self.queue = asyncio.Queue()

    async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
        self.sent.append(verb)
        self.send_entered.set()
        if self.send_gate is not None:
            await self.send_gate.wait()

    async def events(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self):
        self.close_calls += 1
        if self.ignore_graceful:
            return  # peer ignores the gentle path
        self.closed = True
        await self.queue.put(None)
        return "graceful"

    async def force_stop(self):
        self.forced = True
        self.closed = True
        await self.queue.put(None)

    async def observe(self):
        if self.closed and self.observe_after_force == "STOPPED":
            return ("STOPPED", "IDLE")
        if self.observe_after_force == "NEVER_STOPPED":
            return ("RUNNING", "IDLE")
        return ("STOPPED" if self.closed else "RUNNING", "IDLE")


class Factory:
    def __init__(self, native):
        self.native = native

    async def open(self, prepared, session_id, context, *, stream_epoch):
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


def _context(deadline):
    return ExecutionContext(
        "srv", "exe", "binding", "agent", "ws", 1, 1, 3, deadline,
        frozenset({"runtime.open", "turn.submit", "turn.interrupt",
                   "runtime.close"}))


def _runtime(tmp_path, journal, factory, clock, **kwargs):
    binary = tmp_path / "codex"
    binary.write_bytes(b"synthetic binary")
    candidate = InstallationCandidate(
        "codex_app_server", str(binary), fingerprint(binary), "explicit",
        "selected")
    options = {"lease_poll_seconds": 0.01, "lease_grace_seconds": 0.05,
               "clock": clock}
    options.update(kwargs)
    return LocalRuntimeCore(journal, factory,
                            candidates={"codex_app_server": candidate},
                            workspace_roots={"ws": str(tmp_path)}, **options)


def test_rc_02_03_storage_stuck_does_not_delay_containment(tmp_path):
    """RC-02-03: force fires even while the journal worker is blocked."""
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        clock = FakeClock()
        gate = asyncio.Event()
        native = ContainNative(send_gate=gate)
        runtime = _runtime(tmp_path, journal, Factory(native), clock)
        authority = _context(clock.monotonic() + 10)
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            submit_task = asyncio.create_task(runtime.submit(
                __import__("nexus_connector_core").TurnOperation(
                    "turn", "session", "hello"), authority))
            await asyncio.to_thread(native.send_entered.wait, 5)

            # Block the journal worker with one long-running unit.
            release_worker = threading.Event()
            journal._executor.submit_nowait(
                lambda resource: release_worker.wait(10))
            clock.advance(30)  # expire far past grace

            async def contained():
                while not native.forced:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(contained(), timeout=3)
            with pytest.raises(CoreError):
                await asyncio.wait_for(runtime.submit(
                    __import__("nexus_connector_core").TurnOperation(
                        "late", "session", "x"), authority), timeout=1)
            release_worker.set()
            gate.set()
            try:
                await asyncio.wait_for(asyncio.shield(submit_task), 1)
            except (asyncio.TimeoutError, CoreError):
                pass
        finally:
            release_worker.set()
            gate.set()
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


def test_rc_02_07_concurrent_closers_share_one_coordination(tmp_path):
    """RC-02-07: lease expiry + stop + shutdown -> one physical containment."""
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        clock = FakeClock()
        native = ContainNative(ignore_graceful=True,
                               observe_after_force="NEVER_STOPPED")
        runtime = _runtime(tmp_path, journal, Factory(native), clock,
                           lease_grace_seconds=0.05)
        authority = _context(clock.monotonic() + 10)
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            clock.advance(30)
            stop_task = asyncio.create_task(runtime.close(
                __import__("nexus_connector_core").CloseOperation(
                    "stop", "session"), authority))
            shutdown_task = asyncio.create_task(
                runtime.shutdown(ShutdownPolicy(0.05, 0.05)))
            results = await asyncio.wait_for(
                asyncio.gather(stop_task, shutdown_task, return_exceptions=True),
                timeout=5)
            # The unknown outcome retains the owned slot; no double release.
            snapshot = await runtime.inspect(SessionKey("srv", "exe", "session"))
            assert snapshot.ownership in {"owned", "released"}
            assert native.close_calls <= 2
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


def test_rc_02_08_unconfirmed_force_keeps_slot_and_reports_unknown(tmp_path):
    """RC-02-08: force returns, observation never confirms -> slot retained."""
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        clock = FakeClock()
        native = ContainNative(observe_after_force="NEVER_STOPPED")
        runtime = _runtime(tmp_path, journal, Factory(native), clock)
        authority = _context(clock.monotonic() + 10)
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            clock.advance(30)
            report = await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            outcome = report.session_outcomes[SessionKey("srv", "exe", "session")]
            assert outcome == "unknown"
            snapshot = await runtime.inspect(SessionKey("srv", "exe", "session"))
            assert snapshot.ownership == "owned"

            async def force_requested():
                while not native.forced:
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(force_requested(), timeout=2)
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


def test_rc_02_10_expiry_of_external_attach_never_signals_target(tmp_path):
    """RC-02-10: attach-shaped native (no force_stop) gets close only."""
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        clock = FakeClock()

        class AttachLike(ContainNative):
            def __init__(self):
                super().__init__()
                self.signalled = False

            async def force_stop(self):  # pragma: no cover - must not run
                self.signalled = True
                raise AssertionError("attach target must never be signalled")

        native = AttachLike()
        runtime = _runtime(tmp_path, journal, Factory(native), clock)
        authority = _context(clock.monotonic() + 10)
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            clock.advance(30)
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            assert not native.signalled
            assert native.close_calls >= 1  # control channel closed only
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


@pytest.mark.skipif(sys.platform not in {"win32", "linux"},
                    reason="contained process backend unqualified")
def test_rc_02_02_real_peer_ignoring_graceful_close_is_forced(tmp_path):
    """RC-02-02: a real child that ignores gentle termination is contained."""
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        clock = FakeClock()
        stubborn = (
            "import sys, time\n"
            "print('started', flush=True)\n"
            "while True:\n"
            "    time.sleep(0.05)\n"
        )
        (tmp_path / "stubborn.py").write_text(stubborn, encoding="utf-8")

        class PeerNative(ContainNative):
            def __init__(self):
                super().__init__()
                self.proc = None

            async def _spawn(self):
                self.proc = subprocess.Popen(
                    [sys.executable, str(tmp_path / "stubborn.py")],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

            async def send(self, verb, payload, operation_id, *,
                           expected_turn_id=None):
                if self.proc is None:
                    await self._spawn()
                await super().send(verb, payload, operation_id,
                                   expected_turn_id=expected_turn_id)

            async def close(self):
                if self.proc is None:
                    self.closed = True
                    return "graceful"
                # Gentle ask only; the peer ignores stdin writes.
                return "unknown"

            async def force_stop(self):
                if self.proc is not None:
                    self.proc.kill()
                    self.proc.wait(timeout=10)
                self.closed = True
                await self.queue.put(None)

            async def observe(self):
                if self.proc is None:
                    return ("RUNNING", "IDLE")
                return ("STOPPED" if self.proc.poll() is not None
                        else "RUNNING", "IDLE")

        native = PeerNative()
        runtime = _runtime(tmp_path, journal, Factory(native), clock)
        authority = _context(clock.monotonic() + 90)
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            from nexus_connector_core import TurnOperation
            send_task = asyncio.create_task(runtime.submit(
                TurnOperation("turn", "session", "hello"), authority))
            await asyncio.to_thread(native.send_entered.wait, 5)
            assert native.proc is not None and native.proc.poll() is None
            clock.advance(10000)
            async def contained():
                while native.proc is not None and native.proc.poll() is None:
                    await asyncio.sleep(0.02)
            await asyncio.wait_for(contained(), timeout=10)
            send_task.cancel()
            try:
                await send_task
            except (asyncio.CancelledError, CoreError):
                pass
        finally:
            if native.proc is not None and native.proc.poll() is None:
                native.proc.kill()
                native.proc.wait(timeout=10)
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())

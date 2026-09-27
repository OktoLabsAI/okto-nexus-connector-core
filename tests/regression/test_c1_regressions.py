"""Directed regression seeds for correction campaign C1 (PC00.03).

Reconstructed from the audit findings: the package's original
``regressoes_originais/`` runner and seeds were not delivered, so these
encode the nine historical cases from the finding descriptions in
``01_PLANO_CORRECAO_CORE.md`` / ``02_MATRIZ_REGRESSOES.md``.

Eight seeds assert the *corrected* behaviour and are marked
``xfail(strict=True)`` while their phase is open: they document the
defect's presence and will flip to XPASS-strict failures the moment a
correction lands, forcing the marker's removal with the fix. The ninth
(the Pi binding-fingerprint observation) is a property that must stay
true and passes today.
"""

from __future__ import annotations

import asyncio
import gc
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import weakref
from dataclasses import replace
from pathlib import Path

import pytest

from nexus_connector_core import (
    CloseOperation, CoreError, EventCursor, ExecutionContext, LaunchIntent,
    OpenOperation, ReconcileRequest, SessionKey, ShutdownPolicy,
    TurnOperation,
)
from nexus_connector_core.discovery import candidate_pi_node_cli, fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import InstallationCandidate
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory
from nexus_connector_core.runtime import LocalRuntimeCore

pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")


class SeedNative:
    """Configurable native double for the directed seeds."""

    native_id = "native-1"

    def __init__(self, *, events_mode="sentinel", block_send=None):
        self.sent = []
        self.closed = False
        self.stop_forced = False
        self.events_mode = events_mode
        self.block_send = block_send
        self.send_entered = threading.Event()
        self.queue = asyncio.Queue()

    async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
        self.sent.append((verb, dict(payload), operation_id))
        self.send_entered.set()
        if self.block_send is not None:
            await self.block_send.wait()

    async def events(self):
        if self.events_mode == "eof_after_one":
            yield (await self.queue.get())
            return
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self):
        self.closed = True
        await self.queue.put(None)
        return "graceful"

    async def force_stop(self):
        self.stop_forced = True
        self.closed = True
        await self.queue.put(None)

    async def observe(self):
        return ("STOPPED" if self.closed else "RUNNING", "IDLE")


class SeedFactory:
    def __init__(self, native: SeedNative):
        self.native = native

    async def open(self, prepared, session_id, context, *, stream_epoch):
        return self.native


def _context(actions=None, deadline=None):
    return ExecutionContext(
        "srv", "exe", "binding", "agent", "ws", 1, 1, 3,
        deadline if deadline is not None else time.monotonic() + 60,
        frozenset(actions or {"runtime.open", "turn.submit",
                              "turn.interrupt", "runtime.close"}))


def _runtime(tmp_path, journal, factory, clock=None, **kwargs):
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


class FakeClock:
    def __init__(self, now=100.0):
        self.now = now

    def monotonic(self):
        return self.now

    def wall_time(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# ---------------------------------------------------------------- F01
def test_f01_lease_contains_session_while_send_is_stuck(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        clock = FakeClock()
        native = SeedNative(block_send=asyncio.Event())
        runtime = _runtime(tmp_path, journal, SeedFactory(native), clock=clock)
        authority = _context(deadline=clock.monotonic() + 10)
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            submit_task = asyncio.create_task(runtime.submit(
                TurnOperation("turn", "session", "hello"), authority))
            await asyncio.to_thread(native.send_entered.wait, 5)
            # Lease expires far past grace while the send never completes.
            clock.advance(30)
            try:
                await asyncio.wait_for(asyncio.shield(submit_task), timeout=0.5)
            except (asyncio.TimeoutError, CoreError):
                pass
            # Containment must proceed without the send finishing.
            async def contained():
                while not native.closed and not native.stop_forced:
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(contained(), timeout=2.0)
            with pytest.raises(CoreError):
                await runtime.submit(
                    TurnOperation("late", "session", "again"), authority)
        finally:
            native.block_send.set()
            try:
                await asyncio.wait_for(submit_task, timeout=2)
            except BaseException:
                pass
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


# ---------------------------------------------------------------- F02
class _ClockAdvancingJournal:
    """Host journal adapter that advances the clock during marker writes."""

    def __init__(self, inner, clock, at):
        self._inner = inner
        self._clock = clock
        self._at = at
        self._armed = threading.Event()

    def arm(self):
        self._armed.set()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def mark_possible_effect(self, key):
        if self._armed.is_set():
            self._clock.advance(self._at)
        return await self._inner.mark_possible_effect(key)


def test_f02_no_effect_when_lease_expires_during_marker_persistence(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        clock = FakeClock()
        native = SeedNative()
        wrapped = _ClockAdvancingJournal(
            journal, clock, at=100)  # expires the 10s lease during marker
        runtime = _runtime(tmp_path, wrapped, SeedFactory(native), clock=clock)
        authority = _context(deadline=clock.monotonic() + 10)
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            wrapped.arm()  # expire the lease during the submit's marker write
            with pytest.raises(CoreError):
                await runtime.submit(
                    TurnOperation("turn", "session", "hello"), authority)
            assert native.sent == [], "effect must not start under a stale lease"
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


# ---------------------------------------------------------------- F03
def test_f03_eof_with_live_process_blocks_new_submits(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        native = SeedNative(events_mode="eof_after_one")
        runtime = _runtime(tmp_path, journal, SeedFactory(native))
        authority = _context()
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            from nexus_connector_core import RuntimeEvent
            await native.queue.put(RuntimeEvent(
                "srv", "exe", "session", "epoch", 0, "text_delta",
                "seed.delta", {"text": "one"}))
            # The iterator yields the single event and then returns: EOF
            # with the process still alive per observe().
            async def stream_lost():
                while True:
                    snapshot = await runtime.inspect(SessionKey(
                        "srv", "exe", "session"))
                    if snapshot.turn_state == "UNKNOWN" and (
                            snapshot.process_state == "RUNNING"):
                        return
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(stream_lost(), timeout=3)
            # The process is still alive per observe(); new work must be
            # refused because the Core can no longer observe replies.
            with pytest.raises(CoreError, match="EVENT_STREAM_UNAVAILABLE"):
                await runtime.submit(
                    TurnOperation("turn", "session", "hello"), authority)
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


# ---------------------------------------------------------------- F04
def test_f04_sqlite_lock_does_not_block_event_loop_timers(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        sql_threads = []
        original = journal._storage_status

        def probing_status(db=None):
            sql_threads.append(threading.get_ident())
            return original(db)

        journal._storage_status = probing_status
        blocker = sqlite3.connect(tmp_path / "journal.db")
        blocker.execute("BEGIN IMMEDIATE")
        try:
            ticks = []

            async def ticker():
                started = time.monotonic()
                while time.monotonic() - started < 0.6:
                    ticks.append(time.monotonic())
                    await asyncio.sleep(0.02)

            ticker_task = asyncio.create_task(ticker())
            from nexus_connector_core import OperationKey
            admit_task = asyncio.create_task(journal.admit(
                OperationKey("srv", "exe", "blocked-op"),
                "sha256:" + "1" * 64, "session"))
            await asyncio.sleep(0.05)  # the unit is enqueued, awaiting the lock
            await ticker_task
            # Timers progressed while another writer held the database...
            assert len(ticks) >= 15, "event loop stalled behind SQLite"
            # ...and the SQL ran off the loop thread.
            assert sql_threads and sql_threads[0] != threading.get_ident()
            # Releasing the writer lets the queued write commit faithfully.
            blocker.rollback()
            receipt, fresh = await asyncio.wait_for(admit_task, timeout=5)
            assert fresh and receipt.stage == "RECEIVED_DURABLE"
        finally:
            blocker.rollback()
            blocker.close()
            journal.close()

    asyncio.run(run())


# ---------------------------------------------------------------- F05
@pytest.mark.xfail(strict=True, reason="C1/PC05 pending: admitted IDs must be reconcilable (F05)")
def test_f05_every_admitted_operation_id_is_reconcilable(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        native = SeedNative()
        runtime = _runtime(tmp_path, journal, SeedFactory(native))
        authority = _context()
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            long_id = "op-" + "x" * 195  # 199 chars: admitted by dev0 rules
            try:
                await runtime.submit(
                    TurnOperation(long_id, "session", "hello"), authority)
            except CoreError:
                return  # refused up front is also consistent
            report = await runtime.reconcile(ReconcileRequest(
                "srv", "exe", (long_id,), ()))
            assert report.receipts[0] is not None
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


# ---------------------------------------------------------------- F06
@pytest.mark.xfail(strict=True, reason="C1/PC07 pending: closed sessions must not retain adapters (F06)")
def test_f06_twelve_closed_sessions_release_native_adapters(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        natives = []
        refs = []
        runtime = _runtime(tmp_path, journal, _LateFactory(natives, refs),
                           max_owned_sessions=4)
        authority = _context()
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            for cycle in range(12):
                await runtime.open(OpenOperation(
                    f"open-{cycle}", f"session-{cycle}", f"epoch-{cycle}",
                    prepared), authority)
                await runtime.close(CloseOperation(
                    f"close-{cycle}", f"session-{cycle}"), authority)
            del runtime
            gc.collect()
            alive = [ref for ref in refs if ref() is not None]
            assert not alive, f"{len(alive)} closed adapters still retained"
        finally:
            journal.close()

    asyncio.run(run())


class _LateFactory:
    def __init__(self, natives, refs):
        self._natives = natives
        self._refs = refs

    async def open(self, prepared, session_id, context, *, stream_epoch):
        native = SeedNative()
        self._natives.append(native)
        self._refs.append(weakref.ref(native))
        return native


# ---------------------------------------------------------------- F07
@pytest.mark.xfail(strict=True, reason="C1/PC08 pending: explicit model must reach the Codex native mechanism (F07)")
def test_f07_codex_model_reaches_native_thread_configuration(tmp_path):
    async def run():
        import nexus_connector_core.native.runtime_bridge as bridge_module
        journal = SQLiteJournal(tmp_path / "journal.db")
        captured = {}

        class RecordingConnector(SeedNative):
            def __init__(self, **kwargs):
                super().__init__()
                captured.update(kwargs)

        original_loader = bridge_module.load_adapter

        def recording_loader(adapter_id):
            captured["adapter_id"] = adapter_id
            return RecordingConnector

        bridge_module.load_adapter = recording_loader
        try:
            binary = tmp_path / "codex"
            binary.write_bytes(b"synthetic binary")
            candidate = InstallationCandidate(
                "codex_app_server", str(binary), fingerprint(binary),
                "explicit", "selected")
            runtime = LocalRuntimeCore(
                journal,
                CopiedAdapterFactory(lambda prepared: {} ),
                candidates={"codex_app_server": candidate},
                workspace_roots={"ws": str(tmp_path)})
            authority = _context()
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server",
                             model="gpt-5-codex-marker"), authority)
            await runtime.open(OpenOperation(
                "open", "session", "epoch", prepared), authority)
            assert any("gpt-5-codex-marker" in str(value)
                       for value in captured.values()), captured
        finally:
            bridge_module.load_adapter = original_loader
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


@pytest.mark.xfail(strict=True, reason="C1/PC08 pending: explicit model must reach the Claude native argv (F07)")
def test_f07_claude_model_reaches_native_argv(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        binary = tmp_path / "claude"
        binary.write_bytes(b"synthetic binary")
        candidate = InstallationCandidate(
            "claude_stream", str(binary), fingerprint(binary), "explicit",
            "selected")
        runtime = LocalRuntimeCore(
            journal, CopiedAdapterFactory(lambda prepared: {}),
            candidates={"claude_stream": candidate},
            workspace_roots={"ws": str(tmp_path)})
        authority = _context()
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "claude_stream",
                             model="claude-opus-marker"), authority)
            assert any("claude-opus-marker" == part for part in prepared.argv
                       ), prepared.argv
        finally:
            journal.close()

    asyncio.run(run())


# ------------------------------------------------- Pi observation (stays true)
def test_pi_binding_fingerprint_is_path_sensitive():
    """The audit's one passing observation: local binding stays path-bound.

    The portable ``build_identity`` of PC09 is a separate, additional test;
    this property must remain true so moving an installation always
    requires a newly approved binding.
    """
    with tempfile.TemporaryDirectory() as first, \
            tempfile.TemporaryDirectory() as second:
        first_root = Path(first)
        second_root = Path(second)
        node_names = {"win32": "node.exe", "linux": "node"}
        from sys import platform as current_platform
        node_name = node_names.get(current_platform, "node")
        for root in (first_root, second_root):
            package = root / "releases" / "0.87.1" / "node_modules" / \
                "@earendil-works" / "pi-coding-agent" / "dist" / "bundle"
            package.mkdir(parents=True)
            (package / "cli.js").write_text(
                "// synthetic pi cli\n", encoding="utf-8")
            node = root / node_name
            node.write_bytes(b"synthetic node binary")
            if os.name != "nt":
                node.chmod(0o755)  # POSIX candidates must be executable
        def candidate_for(root):
            return candidate_pi_node_cli(
                str(root / node_name),
                str(root / "releases" / "0.87.1" / "node_modules" /
                    "@earendil-works" / "pi-coding-agent" / "dist" /
                    "bundle" / "cli.js"),
                explicit=True)
        first_candidate = candidate_for(first_root)
        second_candidate = candidate_for(second_root)
        assert first_candidate.fingerprint != second_candidate.fingerprint
        # Same files, same layout: contents are equal, only paths differ.
        assert (first_root / node_name).read_bytes() == (
            second_root / node_name).read_bytes()

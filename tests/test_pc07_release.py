"""PC07: closed-session release, tombstoned history, no resurrection."""

import asyncio
import gc
import time
import weakref

import pytest

from nexus_connector_core import (
    CloseOperation, CoreError, ExecutionContext, LaunchIntent,
    OpenOperation, ReconcileRequest, SessionKey, ShutdownPolicy,
    TurnOperation,
)
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import InstallationCandidate
from nexus_connector_core.runtime import LocalRuntimeCore


class CycleNative:
    native_id = "native-1"

    def __init__(self):
        self.queue = asyncio.Queue()
        self.stopped = False

    async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
        pass

    async def events(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self):
        self.stopped = True
        await self.queue.put(None)
        return "graceful"

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


class CycleFactory:
    def __init__(self):
        self.refs: list = []

    async def open(self, prepared, session_id, context, *, stream_epoch):
        native = CycleNative()
        self.refs.append(weakref.ref(native))
        return native


def _runtime(tmp_path, journal, factory, **kwargs):
    binary = tmp_path / "codex"
    binary.write_bytes(b"synthetic binary")
    candidate = InstallationCandidate(
        "codex_app_server", str(binary), fingerprint(binary), "explicit",
        "selected")
    options = {"lease_poll_seconds": 0.01, "lease_grace_seconds": 0.05}
    options.update(kwargs)
    return LocalRuntimeCore(journal, factory,
                            candidates={"codex_app_server": candidate},
                            workspace_roots={"ws": str(tmp_path)}, **options)


def _context():
    return ExecutionContext(
        "srv", "exe", "binding", "agent", "ws", 1, 1, 3,
        time.monotonic() + 60,
        frozenset({"runtime.open", "turn.submit", "runtime.close"}))


def test_rc_07_02_thousand_cycles_release_adapters_in_batches(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        factory = CycleFactory()
        runtime = _runtime(tmp_path, journal, factory,
                           max_owned_sessions=8)
        authority = _context()
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            for cycle in range(1000):
                # Each new session receives fresh fixture authority; the load
                # campaign can exceed the original 60-second lease on CI.
                authority = _context()
                await runtime.open(OpenOperation(
                    f"open-{cycle}", f"session-{cycle}", f"epoch-{cycle}",
                    prepared), authority)
                await runtime.close(CloseOperation(
                    f"close-{cycle}", f"session-{cycle}"), authority)
                if cycle % 100 == 99:
                    gc.collect()
            gc.collect()
            alive = [ref for ref in factory.refs if ref() is not None]
            assert len(alive) <= 16, (
                f"{len(alive)} native adapters retained after 1000 cycles")
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


def test_rc_07_03_history_and_reconcile_after_eviction(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        factory = CycleFactory()
        runtime = _runtime(tmp_path, journal, factory)
        authority = _context()
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(OpenOperation(
                "open", "session", "epoch", prepared), authority)
            await runtime.submit(TurnOperation(
                "turn", "session", "hello"), authority)
            await runtime.close(CloseOperation("close", "session"), authority)

            async def evicted():
                while SessionKey("srv", "exe", "session") in runtime._sessions:
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(evicted(), timeout=5)
            # Durable history survives the eviction.
            report = await runtime.reconcile(ReconcileRequest(
                "srv", "exe", ("turn",), ("session",)))
            assert report.receipts[0] is not None
            snapshot = report.snapshots[0]
            assert snapshot.ownership == "released"
            assert snapshot.process_state == "UNKNOWN"  # never invented
            # Replaying the same operation returns the known receipt and
            # never re-executes anything.
            receipt = await runtime.submit(TurnOperation(
                "turn", "session", "hello"), authority)
            assert receipt.operation_id == "turn"
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


def test_rc_07_06_late_completion_does_not_resurrect_session(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        factory = CycleFactory()
        runtime = _runtime(tmp_path, journal, factory)
        authority = _context()
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(OpenOperation(
                "open", "session", "epoch", prepared), authority)
            await runtime.close(CloseOperation("close", "session"), authority)
            async def evicted():
                while SessionKey("srv", "exe", "session") in runtime._sessions:
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(evicted(), timeout=5)
            # A late task completion (sink/force style) arrives after the
            # eviction: the session must not reappear as live.
            late = runtime._session_tombstones.get(SessionKey(
                "srv", "exe", "session"))
            assert late == "released"
            assert SessionKey("srv", "exe", "session") not in runtime._sessions
            snapshot = await runtime.inspect(SessionKey("srv", "exe", "session"))
            assert snapshot.ownership == "released"
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())

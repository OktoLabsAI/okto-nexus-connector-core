"""PC04: EOF classification, expected-close silence, single incident."""

import asyncio
import time

import pytest

from nexus_connector_core import (
    CloseOperation, CoreError, EventCursor, ExecutionContext, LaunchIntent,
    OpenOperation, RuntimeEvent, SessionKey, ShutdownPolicy,
    TurnOperation,
)
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import InstallationCandidate
from nexus_connector_core.runtime import LocalRuntimeCore


class EofNative:
    native_id = "native-1"

    def __init__(self, mode="eof"):
        self.queue = asyncio.Queue()
        self.mode = mode
        self.stopped = False

    async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
        pass

    async def events(self):
        if self.mode == "eof":
            # One real event, then unexpected EOF (process alive).
            item = await self.queue.get()
            yield item
            return
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self):
        self.stopped = True
        await self.queue.put(None)
        return "graceful"

    async def force_stop(self):
        self.stopped = True
        await self.queue.put(None)

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


class Factory:
    def __init__(self, native):
        self.native = native

    async def open(self, prepared, session_id, context, *, stream_epoch):
        return self.native


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
        frozenset({"runtime.open", "turn.submit", "turn.interrupt",
                   "runtime.close"}))


def _loss_events(runtime, journal):
    async def collect():
        cursor = EventCursor("srv", "exe", "session", "epoch")
        return tuple([event async for event in journal.events(cursor)])
    return asyncio.run(collect())


def test_rc_04_03_expected_close_does_not_emit_stream_loss(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        native = EofNative(mode="live")
        runtime = _runtime(tmp_path, journal, Factory(native))
        authority = _context()
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            await runtime.close(
                CloseOperation("close", "session"), authority)
            await runtime.shutdown(ShutdownPolicy(1, 1))
            cursor = EventCursor("srv", "exe", "session", "epoch")
            events = tuple([event async for event in journal.events(cursor)])
            assert all(event.native_type != "core.event_pump_failed"
                       for event in events)
        finally:
            journal.close()

    asyncio.run(run())


def test_rc_04_08_unexpected_eof_records_single_incident_per_epoch(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        native = EofNative(mode="eof")
        runtime = _runtime(tmp_path, journal, Factory(native))
        authority = _context()
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(
                OpenOperation("open", "session", "epoch", prepared), authority)
            await native.queue.put(RuntimeEvent(
                "srv", "exe", "session", "epoch", 0, "text_delta",
                "pc04.delta", {"text": "one"}))
            # Wait until the pump observed the EOF and fenced the session.
            async def fenced():
                while True:
                    snapshot = await runtime.inspect(
                        SessionKey("srv", "exe", "session"))
                    if snapshot.turn_state == "UNKNOWN":
                        return
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(fenced(), timeout=3)
            with pytest.raises(CoreError, match="EVENT_STREAM_UNAVAILABLE"):
                await runtime.submit(
                    TurnOperation("turn", "session", "hello"), authority)
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            cursor = EventCursor("srv", "exe", "session", "epoch")
            events = tuple([event async for event in journal.events(cursor)])
            incidents = [event for event in events
                         if event.native_type == "core.event_pump_failed"]
            assert len(incidents) == 1
            assert incidents[0].payload["code"] == "EVENT_STREAM_UNAVAILABLE"
        finally:
            journal.close()

    asyncio.run(run())

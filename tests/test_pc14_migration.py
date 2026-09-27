"""PC14: dev0 journal migration rehearsal and rollback honesty."""

import asyncio

import pytest

from nexus_connector_core import (
    CoreError, ExecutionContext, LaunchIntent, OpenOperation,
    OperationKey, SessionKey, ShutdownPolicy, TurnOperation,
)
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import InstallationCandidate
from nexus_connector_core.runtime import LocalRuntimeCore


class Native:
    native_id = "native-1"

    def __init__(self):
        self.queue = asyncio.Queue()

    async def send(self, verb, payload, operation_id, *, expected_turn_id=None):
        pass

    async def events(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self):
        await self.queue.put(None)
        return "graceful"

    async def observe(self):
        return ("STOPPED", "IDLE")


class Factory:
    def __init__(self):
        self.native = Native()

    async def open(self, prepared, session_id, context, *, stream_epoch):
        return self.native


def test_rc_14_01_dev0_journal_reopens_with_history_intact(tmp_path):
    database = tmp_path / "journal.db"

    # --- Stage 1: write dev0-era state with long IDs and mixed facts.
    import time as _time
    legacy_long = "legacy-" + "q" * 190  # 197 chars, dev0-admissible
    async def seed():
        journal = SQLiteJournal(database)
        try:
            from nexus_connector_core import RuntimeEvent
            await journal.admit(
                OperationKey("srv", "exe", legacy_long),
                "sha256:" + "1" * 64, "session", effect_imminent=True)
            await journal.admit(
                OperationKey("srv", "exe", "open-op"),
                "sha256:" + "2" * 64, "session", claim_session=True,
                effect_imminent=True,
                connection_generation=2, session_owner_generation=3,
                authorization_revision=1, configuration_revision=1)
            await journal.reserve_owned_slot(
                OperationKey("srv", "exe", "open-op"), "session")
            await journal.record_event(RuntimeEvent(
                "srv", "exe", "session", "epoch", 0, "text_delta",
                "seed.one", {"text": "one"}))
            await journal.record_event(RuntimeEvent(
                "srv", "exe", "session", "epoch", 0, "text_delta",
                "seed.two", {"text": "two"}))  # un-ACKed
            await journal.acknowledge_events(
                __import__("nexus_connector_core").EventCursor(
                    "srv", "exe", "session", "epoch"), 1)
        finally:
            journal.close()
    asyncio.run(seed())

    # --- Stage 2: reopen under the corrected Core; nothing re-keyed/lost.
    async def reopen():
        journal = SQLiteJournal(database)
        binary = tmp_path / "codex"
        binary.write_bytes(b"synthetic binary")
        candidate = InstallationCandidate(
            "codex_app_server", str(binary), fingerprint(binary),
            "explicit", "selected")
        runtime = LocalRuntimeCore(
            journal, Factory(),
            candidates={"codex_app_server": candidate},
            workspace_roots={"ws": str(tmp_path)})
        try:
            # Long ID readable via the legacy query; never re-admitted.
            receipt = await runtime.legacy_operation_receipt(
                "srv", "exe", legacy_long)
            assert receipt is not None and receipt.operation_id == legacy_long
            with pytest.raises(CoreError, match="OPERATION_INVALID"):
                await runtime.submit(TurnOperation(
                    legacy_long, "session", "again"), ExecutionContext(
                        "srv", "exe", "b", "a", "ws", 1, 1, 1,
                        _time.monotonic() + 60,
                        frozenset({"turn.submit"})))
            # Claims/slots preserved: the same session cannot be re-opened
            # through the ordinary prepare+open path.
            authority = ExecutionContext(
                "srv", "exe", "b", "a", "ws", 1, 1, 1,
                _time.monotonic() + 60, frozenset({"runtime.open"}))
            prepared = await runtime.prepare(
                LaunchIntent("a", "ws", "codex_app_server"), authority)
            with pytest.raises(CoreError, match="SESSION_CONFLICT"):
                await runtime.open(
                    OpenOperation("reopen", "session", "epoch2", prepared),
                    authority)
            # Un-ACKed events still replay; ACKed body compactable only
            # through the public path.
            from nexus_connector_core import EventCursor
            sequences = tuple([event.sequence async for event in
                               journal.events(EventCursor(
                                   "srv", "exe", "session", "epoch"))])
            assert sequences == (1, 2)
            page = await journal.claimed_sessions("srv", "exe")
            assert page.claims and page.claims[0].key.session_id == "session"
            assert page.claims[0].opening_connection_generation == 2
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()
    asyncio.run(reopen())


def test_rc_14_02_repeated_reopen_cycles_are_stable(tmp_path):
    database = tmp_path / "journal.db"

    async def cycle():
        journal = SQLiteJournal(database)
        try:
            await journal.admit(OperationKey("srv", "exe", f"op"),
                                "sha256:" + "3" * 64, "session",
                                effect_imminent=True)
        finally:
            journal.close()
    asyncio.run(cycle())
    asyncio.run(cycle())  # reopen keeps working; no partial schema state

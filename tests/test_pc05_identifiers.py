"""PC05: identifier policy boundaries, typed refusals, legacy reads."""

import asyncio
import time

import pytest

from nexus_connector_core import (
    CloseOperation, CoreError, ExecutionContext, LaunchIntent,
    LocalRuntimeCore, OpenOperation, OperationKey, SessionKey,
    ShutdownPolicy, TurnOperation,
)
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import InstallationCandidate


class Native:
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


class Factory:
    def __init__(self):
        self.native = Native()

    async def open(self, prepared, session_id, context, *, stream_epoch):
        return self.native


def _context():
    return ExecutionContext(
        "srv", "exe", "binding", "agent", "ws", 1, 1, 3,
        time.monotonic() + 60,
        frozenset({"runtime.open", "turn.submit", "turn.close"}))


def _runtime(tmp_path, journal):
    binary = tmp_path / "codex"
    binary.write_bytes(b"synthetic binary")
    candidate = InstallationCandidate(
        "codex_app_server", str(binary), fingerprint(binary), "explicit",
        "selected")
    return LocalRuntimeCore(journal, Factory(),
                            candidates={"codex_app_server": candidate},
                            workspace_roots={"ws": str(tmp_path)})


@pytest.mark.parametrize("length,admitted", [
    (0, False), (1, True), (159, True), (160, True),
    (161, False), (256, False), (257, False),
])
def test_rc_05_01_operation_id_boundaries(tmp_path, length, admitted):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = _runtime(tmp_path, journal)
        authority = _context()
        operation_id = "op-" + "x" * max(0, length - 3)
        operation_id = operation_id[:length] if length else ""
        try:
            prepared = await runtime.prepare(
                LaunchIntent("agent", "ws", "codex_app_server"), authority)
            await runtime.open(OpenOperation(
                "open", "session", "epoch", prepared), authority)
            if admitted:
                receipt = await runtime.submit(TurnOperation(
                    operation_id, "session", "hello"), authority)
                assert receipt.stage == "SUBMITTED"
            else:
                with pytest.raises(CoreError, match="OPERATION_INVALID"):
                    await runtime.submit(TurnOperation(
                        operation_id, "session", "hello"), authority)
        finally:
            await runtime.shutdown(ShutdownPolicy(0.1, 0.1))
            journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("bad", [None, True, False, 7, b"bytes", [], {}, 3.5])
def test_rc_05_02_non_string_ids_refused_without_cast(tmp_path, bad):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = _runtime(tmp_path, journal)
        authority = _context()
        try:
            with pytest.raises(CoreError, match="OPERATION_INVALID"):
                await runtime.submit(TurnOperation(
                    bad, "session", "hello"), authority)
        finally:
            journal.close()

    asyncio.run(run())


def test_rc_05_06_legacy_long_id_readable_but_not_admitted(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        legacy_id = "legacy-" + "y" * 200  # 207 chars: dev0-era admission
        # Simulate the development journal that already persisted it.
        await journal.admit(OperationKey("srv", "exe", legacy_id),
                            "sha256:" + "1" * 64, "session",
                            effect_imminent=True)
        runtime = _runtime(tmp_path, journal)
        try:
            receipt = await runtime.legacy_operation_receipt(
                "srv", "exe", legacy_id)
            assert receipt is not None and receipt.operation_id == legacy_id
            # New admission of the same long ID stays refused.
            authority = _context()
            with pytest.raises(CoreError, match="OPERATION_INVALID"):
                await runtime.submit(TurnOperation(
                    legacy_id, "session", "hello"), authority)
            # The legacy read never mutates or re-executes anything.
            again = await runtime.legacy_operation_receipt(
                "srv", "exe", legacy_id)
            assert again == receipt
        finally:
            journal.close()

    asyncio.run(run())


def test_rc_05_07_legacy_lookup_validates_scope_and_shape(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = _runtime(tmp_path, journal)
        try:
            with pytest.raises(CoreError, match="OPERATION_INVALID"):
                await runtime.legacy_operation_receipt(
                    "srv", "exe", "z" * 257)
            with pytest.raises(CoreError, match="OPERATION_INVALID"):
                await runtime.legacy_operation_receipt("srv", "exe", "")
            # Absent key: None, not an error.
            assert await runtime.legacy_operation_receipt(
                "srv", "exe", "x" * 100) is None
            # Namespace mismatch never crosses servers.
            assert await runtime.legacy_operation_receipt(
                "other", "exe", "x" * 100) is None
        finally:
            journal.close()

    asyncio.run(run())

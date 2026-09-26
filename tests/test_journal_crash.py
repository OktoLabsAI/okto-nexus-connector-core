import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from nexus_connector_core import (CoreError, EventCursor, OperationKey,
                                  ProcessBirthEvidence, RuntimeEvent, SessionKey)
from nexus_connector_core.journal import SQLiteJournal


PEER = Path(__file__).parent / "fixtures" / "journal_crash_peer.py"
INTENT = "sha256:" + "1" * 64
KEY = OperationKey("crash-server", "crash-executor", "crash-operation")
CURSOR = EventCursor("crash-server", "crash-executor", "crash-session", "crash-epoch")


@pytest.mark.parametrize("boundary,stage,possible_effect,retry_safe", [
    ("before_admit", None, None, None),
    ("uncommitted_admit", None, None, None),
    ("after_admit", "RECEIVED_DURABLE", False, True),
    ("after_mark", "SUBMISSION_STARTED", True, False),
    ("after_no_write", "FAILED", False, True),
    ("after_unknown", "OUTCOME_UNKNOWN", True, False),
    ("after_terminal", "SUCCEEDED", True, False),
])
def test_abrupt_child_exit_preserves_only_committed_facts(
        tmp_path, boundary, stage, possible_effect, retry_safe):
    path = tmp_path / f"{boundary}.db"
    child = subprocess.run([sys.executable, str(PEER), str(path), boundary],
                           capture_output=True, text=True, timeout=20)
    assert child.returncode == 91, child.stderr

    async def inspect():
        journal = SQLiteJournal(path)
        try:
            receipt = await journal.get_receipt(KEY)
            if stage is None:
                assert receipt is None
                fresh_receipt, fresh = await journal.admit(
                    KEY, INTENT, CURSOR.session_id)
                assert fresh and fresh_receipt.stage == "RECEIVED_DURABLE"
                return
            assert receipt is not None
            assert (receipt.stage, receipt.possible_effect, receipt.retry_safe) == (
                stage, possible_effect, retry_safe)
            replay, fresh = await journal.admit(KEY, INTENT, CURSOR.session_id)
            assert not fresh and replay == receipt
            if boundary == "after_terminal":
                assert [item.sequence async for item in journal.events(CURSOR)] == [1]
                assert await journal.contiguous_watermark(CURSOR) == 1
            else:
                assert [item async for item in journal.events(CURSOR)] == []
        finally:
            journal.close()

    asyncio.run(inspect())


def test_abrupt_exit_after_ack_keeps_watermark_and_prevents_sequence_reuse(tmp_path):
    path = tmp_path / "after_ack.db"
    child = subprocess.run([sys.executable, str(PEER), str(path), "after_ack"],
                           capture_output=True, text=True, timeout=20)
    assert child.returncode == 91, child.stderr

    async def inspect():
        journal = SQLiteJournal(path)
        try:
            assert await journal.contiguous_watermark(CURSOR) == 1
            assert await journal.acknowledge_events(CURSOR, 1) == 1
            compacted, _ = await journal.compact_acked(max_rows=1)
            assert compacted == 1
            with pytest.raises(CoreError, match="EVENT_GAP"):
                _ = [event async for event in journal.events(CURSOR)]
            next_event = await journal.record_event(RuntimeEvent(
                CURSOR.server_id, CURSOR.executor_id, CURSOR.session_id,
                CURSOR.stream_epoch, 0, "lifecycle", "crash.reopened", {}))
            assert next_event.sequence == 2
        finally:
            journal.close()

    asyncio.run(inspect())


@pytest.mark.parametrize("boundary,persisted", [
    ("before_birth", False),
    ("uncommitted_birth", False),
    ("after_birth", True),
])
def test_abrupt_exit_at_process_birth_commit_boundary(tmp_path, boundary, persisted):
    path = tmp_path / f"{boundary}.db"
    child = subprocess.run([sys.executable, str(PEER), str(path), boundary],
                           capture_output=True, text=True, timeout=20)
    assert child.returncode == 91, child.stderr

    async def inspect():
        journal = SQLiteJournal(path)
        try:
            session = SessionKey(KEY.server_id, KEY.executor_id,
                                 CURSOR.session_id)
            receipt = await journal.get_receipt(KEY)
            assert receipt is not None
            assert receipt.stage == "SUBMISSION_STARTED"
            assert receipt.possible_effect is True
            claim = (await journal.claimed_sessions(
                KEY.server_id, KEY.executor_id)).claims[0]
            assert claim.opening_connection_generation == 3
            assert claim.opening_owner_generation == 1
            record = await journal.get_process_birth(session)
            assert (record is not None) is persisted
            if record is not None:
                assert record.opening_operation_id == KEY.operation_id
                assert record.evidence == ProcessBirthEvidence(
                    "linux", 45678, "boot-start:crash-boot:123",
                    "linux_guardian")
            replay, fresh = await journal.admit(KEY, INTENT, session.session_id)
            assert not fresh and replay == receipt
        finally:
            journal.close()

    asyncio.run(inspect())

import asyncio
import sqlite3

import pytest

from nexus_connector_core import (CoreError, EventCursor, LocalRuntimeCore,
                                  OperationKey, RuntimeEvent)
from nexus_connector_core.journal import JournalLimits, SQLiteJournal


def event(sequence=0, *, server="srv", category="text_delta", operation_id=None,
          payload=None):
    return RuntimeEvent(server, "exe", "session", "epoch", sequence, category,
                        "native.event", payload or {"text": "x"}, operation_id)


def test_ack_compaction_releases_quota_without_reusing_sequence(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        limits = JournalLimits(total_event_rows=3, reserved_event_rows=0,
                               server_event_rows=3, server_reserved_rows=0)
        journal = SQLiteJournal(path, limits=limits)
        cursor = EventCursor("srv", "exe", "session", "epoch")
        for _ in range(3):
            await journal.record_event(event())
        assert await journal.acknowledge_events(cursor, 2) == 2
        assert [item.sequence async for item in journal.events(cursor)] == [1, 2, 3]
        assert (await journal.compact_acked(max_rows=1))[0] == 1
        with pytest.raises(CoreError, match="EVENT_GAP"):
            [item async for item in journal.events(cursor)]
        assert [item.sequence async for item in journal.events(
            EventCursor("srv", "exe", "session", "epoch", 1))] == [2, 3]
        assert (await journal.compact_acked())[0] == 1
        assert await journal.contiguous_watermark(cursor) == 3
        assert (await journal.record_event(event())).sequence == 4
        journal.close()

        journal = SQLiteJournal(path, limits=limits)
        assert (await journal.record_event(event())).sequence == 5
        with pytest.raises(CoreError, match="EVENT_GAP"):
            [item async for item in journal.events(cursor)]
        assert await journal.contiguous_watermark(cursor) == 5
        assert [item.sequence async for item in journal.events(
            EventCursor("srv", "exe", "session", "epoch", 2))] == [3, 4, 5]
        journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("batch", [True, 0, -1, 1.5, 4097, 2**63])
def test_compaction_rejects_unbounded_or_untyped_batch_before_deletion(
        tmp_path, batch):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        cursor = EventCursor("srv", "exe", "session", "epoch")
        assert (await journal.record_event(event())).sequence == 1
        assert await journal.acknowledge_events(cursor, 1) == 1
        with pytest.raises(ValueError, match="max_rows"):
            await journal.compact_acked(max_rows=batch)
        assert [item.sequence async for item in journal.events(cursor)] == [1]
        assert (await journal.compact_acked(max_rows=1))[0] == 1
        assert await journal.compact_acked(max_rows=4096) == (0, 0)
        journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("batch", [True, 1.5, 0, 4097])
def test_runtime_rejects_invalid_compaction_batch_before_host_journal(batch):
    class HostJournal:
        called = False

        async def compact_acked(self, *, max_rows):
            self.called = True
            return 0, 0

    async def run():
        journal = HostJournal()
        runtime = LocalRuntimeCore(journal, object(), candidates={},
                                   workspace_roots={})
        with pytest.raises(ValueError, match="max_rows"):
            await runtime.compact_events(max_rows=batch)
        assert not journal.called

    asyncio.run(run())


def test_ack_requires_contiguous_events_and_pruned_duplicate_is_explicit(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        cursor = EventCursor("srv", "exe", "session", "epoch")
        await journal.append_event(event(1))
        await journal.append_event(event(3))
        with pytest.raises(CoreError, match="EVENT_INVALID"):
            await journal.acknowledge_events(cursor, True)
        with pytest.raises(CoreError, match="EVENT_GAP"):
            await journal.acknowledge_events(EventCursor("wrong", "exe", "session", "epoch"), 1)
        with pytest.raises(CoreError, match="EVENT_GAP"):
            await journal.acknowledge_events(cursor, 3)
        assert await journal.acknowledge_events(cursor, 1) == 1
        await journal.append_event(event(1))
        await journal.append_event(event(2))
        assert await journal.acknowledge_events(cursor, 3) == 3
        assert await journal.acknowledge_events(cursor, 1) == 3
        assert (await journal.compact_acked())[0] == 3
        with pytest.raises(CoreError, match="EVENT_GAP"):
            await journal.append_event(event(1))
        assert await journal.contiguous_watermark(cursor) == 3
        journal.close()

    asyncio.run(run())


def test_compaction_is_namespaced_and_retains_terminal_receipt(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        key = OperationKey("srv", "exe", "op")
        await journal.admit(key, "hash", "session")
        await journal.mark_possible_effect(key)
        terminal = await journal.record_event(event(
            category="turn_state", operation_id="op",
            payload={"delivery_phase": "terminal", "delivery_outcome": "success"}))
        other = await journal.record_event(event(server="other"))
        assert (terminal.sequence, other.sequence) == (1, 1)
        assert (await journal.get_receipt(key)).stage == "SUCCEEDED"
        await journal.acknowledge_events(EventCursor("srv", "exe", "session", "epoch"), 1)
        assert (await journal.compact_acked())[0] == 1
        assert (await journal.get_receipt(key)).stage == "SUCCEEDED"
        assert [item.sequence async for item in journal.events(
            EventCursor("other", "exe", "session", "epoch"))] == [1]
        journal.close()

    asyncio.run(run())


def test_legacy_event_stream_migration_preserves_high_water(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        journal = SQLiteJournal(path)
        await journal.append_event(event(7))
        journal.close()
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE event_streams")
            db.execute("""CREATE TABLE event_streams (
                server_id TEXT NOT NULL, executor_id TEXT NOT NULL,
                session_id TEXT NOT NULL, stream_epoch TEXT NOT NULL,
                next_sequence INTEGER NOT NULL, acked_sequence INTEGER NOT NULL,
                PRIMARY KEY(server_id,executor_id,session_id,stream_epoch))""")
        journal = SQLiteJournal(path)
        assert (await journal.record_event(event())).sequence == 8
        journal.close()

    asyncio.run(run())


def test_runtime_facade_exposes_ack_and_compaction_without_internal_db(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        core = LocalRuntimeCore(journal, object(), candidates={}, workspace_roots={})
        cursor = EventCursor("srv", "exe", "session", "epoch")
        await journal.record_event(event())
        assert await core.acknowledge_events(cursor, 1) == 1
        assert (await core.compact_events())[0] == 1
        journal.close()

    asyncio.run(run())

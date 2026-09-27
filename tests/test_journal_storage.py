import asyncio
import sqlite3
from dataclasses import replace

import pytest

from nexus_connector_core import (CoreError, EventCursor, LocalRuntimeCore, OperationKey,
                                  RuntimeEvent)
from nexus_connector_core.journal import JournalLimits, SQLiteJournal


def event(text: str, *, category: str = "text_delta", server: str = "srv",
          session: str = "session") -> RuntimeEvent:
    return RuntimeEvent(server, "exe", session, "epoch", 0, category,
                        "native.output", {"text": text})


def test_physical_pressure_gates_new_work_and_reports_files(tmp_path):
    async def run():
        limits = JournalLimits(max_storage_bytes=384 * 1024,
                               reserved_storage_bytes=64 * 1024)
        path = tmp_path / "journal.db"
        journal = SQLiteJournal(path, limits=limits)
        core = LocalRuntimeCore(journal, object(), candidates={}, workspace_roots={})
        before = await core.storage_status()
        assert before.database_bytes > 0 and before.page_size > 0
        assert before.total_bytes == (before.database_bytes + before.wal_bytes +
                                      before.shm_bytes)
        reader = sqlite3.connect(path, isolation_level=None)
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM events").fetchone()
        written = 0
        for _ in range(100):
            try:
                await journal.record_event(event("x" * 8192))
                written += 1
            except CoreError as exc:
                assert exc.code == "JOURNAL_FULL" and exc.possible_effect
                break
        else:
            pytest.fail("physical pressure never stopped event admission")
        assert written > 0
        after = await core.storage_status()
        assert after.total_bytes > before.total_bytes
        for index in range(100):
            try:
                await journal.admit(OperationKey("srv", "exe", f"new-work-{index}"),
                                    "hash", "session")
            except CoreError as exc:
                assert exc.code == "JOURNAL_FULL"
                assert exc.retry_safe and not exc.possible_effect
                break
        else:
            pytest.fail("physical pressure never stopped operation admission")
        after_admission = await core.storage_status()
        if (after_admission.total_bytes + after_admission.page_size * 4 + 512
                <= limits.max_storage_bytes):
            _, fresh = await journal.admit(
                OperationKey("srv", "exe", "interrupt"), "hash", "session",
                critical=True)
            assert fresh
        reader.execute("ROLLBACK")
        reader.close()
        recovered, fresh = await journal.admit(
            OperationKey("srv", "exe", "recovered"), "hash", "session")
        assert fresh and recovered.stage == "RECEIVED_DURABLE"
        journal.close()

    asyncio.run(run())


def test_reader_can_pin_wal_and_checkpoint_reports_busy(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        journal = SQLiteJournal(path)
        await journal.record_event(event("first"))
        reader = sqlite3.connect(path, isolation_level=None)
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM events").fetchone()
        for _ in range(4):
            await journal.record_event(event("x" * 1024))
        busy, _, _ = await journal.checkpoint_wal()
        assert busy == 1
        reader.execute("ROLLBACK")
        reader.close()
        busy, _, _ = await journal.checkpoint_wal()
        assert busy == 0
        assert (await journal.storage_status()).wal_bytes == 0
        journal.close()

    asyncio.run(run())


def test_pressure_compacts_only_acked_events_before_new_admission(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        existing = OperationKey("srv", "exe", "existing")
        await journal.admit(existing, "hash", "session")
        for label in ("first", "second", "unacked"):
            await journal.record_event(event(label))
        cursor = EventCursor("srv", "exe", "session", "epoch", 0)
        assert await journal.acknowledge_events(cursor, 2) == 2
        before = await journal.storage_status()
        journal.limits = JournalLimits(max_storage_bytes=before.total_bytes,
                                       reserved_storage_bytes=4096)
        same, fresh = await journal.admit(existing, "hash", "session")
        assert not fresh and same.operation_id == "existing"
        assert journal._run_sync(lambda db: db.execute("SELECT COUNT(*) FROM events").fetchone())[0] == 3
        try:
            await journal.admit(OperationKey("srv", "exe", "new"), "hash", "session")
        except CoreError as exc:
            assert exc.code == "JOURNAL_FULL" and exc.retry_safe
        assert journal._run_sync(lambda db: db.execute(
            "SELECT sequence FROM events ORDER BY sequence").fetchall()) == [(3,)]
        assert [item.sequence async for item in journal.events(
            EventCursor("srv", "exe", "session", "epoch", 2))] == [3]
        journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("writer", ["record", "append"])
def test_event_write_recovers_only_acked_rows_under_storage_pressure(
        tmp_path, writer):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        for index in range(15):
            await journal.record_event(event(f"old-{index}" + "x" * 1024))
        cursor = EventCursor("srv", "exe", "session", "epoch", 0)
        assert await journal.acknowledge_events(cursor, 10) == 10
        before = await journal.storage_status()
        journal.limits = JournalLimits(max_storage_bytes=before.total_bytes,
                                       reserved_storage_bytes=4096)
        if writer == "record":
            written = await journal.record_event(event("new"))
            assert written.sequence == 16
        else:
            await journal.append_event(replace(event("new"), sequence=16))
        assert [item.sequence async for item in journal.events(replace(
            cursor, after_sequence=10))] == [11, 12, 13, 14, 15, 16]
        with pytest.raises(CoreError, match="EVENT_GAP"):
            [item async for item in journal.events(cursor)]
        assert journal._run_sync(lambda db: db.execute(
            "SELECT COUNT(*) FROM events").fetchone())[0] == 6
        journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("writer", ["record", "append"])
@pytest.mark.parametrize("in_memory", [False, True])
def test_logical_quota_recovery_prioritizes_the_pressured_session(
        tmp_path, writer, in_memory):
    async def run():
        limits = JournalLimits(session_event_rows=3, session_reserved_rows=1)
        journal = SQLiteJournal(
            ":memory:" if in_memory else tmp_path / "journal.db", limits=limits)
        for index in range(130):
            session = f"other-{index:03d}"
            await journal.record_event(event("acked", server="aaa",
                                             session=session))
            assert await journal.acknowledge_events(
                EventCursor("aaa", "exe", session, "epoch", 0), 1) == 1
        for label in ("first", "second"):
            await journal.record_event(event(label, server="zzz",
                                             session="target"))
        cursor = EventCursor("zzz", "exe", "target", "epoch", 0)
        assert await journal.acknowledge_events(cursor, 1) == 1
        candidate = event("third", server="zzz", session="target")
        if writer == "record":
            assert (await journal.record_event(candidate)).sequence == 3
        else:
            await journal.append_event(replace(candidate, sequence=3))
        assert [item.sequence async for item in journal.events(replace(
            cursor, after_sequence=1))] == [2, 3]
        with pytest.raises(CoreError, match="EVENT_GAP"):
            [item async for item in journal.events(cursor)]
        assert journal._run_sync(lambda db: db.execute(
            "SELECT COUNT(*) FROM events WHERE server_id='zzz'").fetchone())[0] == 2
        journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("scope", ["total", "server", "session"])
@pytest.mark.parametrize("measure", ["rows", "bytes"])
def test_normal_event_recovers_each_logical_quota(tmp_path, scope, measure):
    async def run():
        first = event("x")
        body_size = len(SQLiteJournal._event_body(replace(first, sequence=1)))
        names = {
            ("total", "rows"): ("total_event_rows", "reserved_event_rows"),
            ("total", "bytes"): ("total_event_bytes", "reserved_event_bytes"),
            ("server", "rows"): ("server_event_rows", "server_reserved_rows"),
            ("server", "bytes"): ("server_event_bytes", "server_reserved_bytes"),
            ("session", "rows"): ("session_event_rows", "session_reserved_rows"),
            ("session", "bytes"): ("session_event_bytes", "session_reserved_bytes"),
        }
        maximum, reserve = names[(scope, measure)]
        limits = JournalLimits(**{maximum: 2 if measure == "rows" else
                                  body_size * 2, reserve: 0})
        journal = SQLiteJournal(":memory:", limits=limits)
        assert (await journal.record_event(first)).sequence == 1
        assert (await journal.record_event(first)).sequence == 2
        cursor = EventCursor("srv", "exe", "session", "epoch", 0)
        assert await journal.acknowledge_events(cursor, 1) == 1
        assert (await journal.record_event(first)).sequence == 3
        assert [item.sequence async for item in journal.events(replace(
            cursor, after_sequence=1))] == [2, 3]
        journal.close()

    asyncio.run(run())


def test_storage_path_identity_drift_fails_closed(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        journal._storage_identity = (-1, -1)
        with pytest.raises(CoreError, match="PROFILE_DRIFT"):
            await journal.admit(OperationKey("srv", "exe", "op"), "hash", "session")
        journal.close()

    asyncio.run(run())

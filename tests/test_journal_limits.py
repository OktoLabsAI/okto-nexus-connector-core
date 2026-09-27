import asyncio
import sqlite3

import pytest

from nexus_connector_core import CoreError, EventCursor, OperationKey, RuntimeEvent
from nexus_connector_core.journal import JournalLimits, SQLiteJournal


def event(server="srv", category="text_delta", sequence=0, session="session"):
    return RuntimeEvent(server, "exe", session, "epoch", sequence,
                        category, "native.event", {"text": "x"})


def test_journal_limits_reject_hostile_types_before_open(tmp_path):
    for name in JournalLimits.__dataclass_fields__:
        for invalid in (True, 1.0, "1", None, 2**63):
            with pytest.raises(ValueError, match="invalid journal limit"):
                JournalLimits(**{name: invalid})
    path = tmp_path / "not-created.db"
    with pytest.raises(TypeError, match="JournalLimits"):
        SQLiteJournal(path, limits={"max_storage_bytes": 1})
    assert not path.exists()


def test_critical_event_reservation_survives_reopen_and_duplicate(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        limits = JournalLimits(total_event_rows=3, reserved_event_rows=1,
                               server_event_rows=3, server_reserved_rows=1)
        journal = SQLiteJournal(path, limits=limits)
        first = await journal.record_event(event())
        await journal.record_event(event())
        with pytest.raises(CoreError, match="JOURNAL_FULL") as denied:
            await journal.record_event(event())
        assert denied.value.possible_effect
        await journal.append_event(first)  # idempotent despite saturation
        assert (await journal.record_event(event(category="turn_state"))).sequence == 3
        journal.close()

        journal = SQLiteJournal(path, limits=limits)
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.record_event(event(category="error"))
        cursor = EventCursor("srv", "exe", "session", "epoch")
        assert [item.sequence async for item in journal.events(cursor)] == [1, 2, 3]
        journal.close()

    asyncio.run(run())


def test_one_server_cannot_consume_anothers_local_reservation(tmp_path):
    async def run():
        limits = JournalLimits(total_event_rows=6, reserved_event_rows=1,
                               server_event_rows=2, server_reserved_rows=1)
        journal = SQLiteJournal(tmp_path / "journal.db", limits=limits)
        await journal.record_event(event("server-a"))
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.record_event(event("server-a"))
        await journal.record_event(event("server-b"))
        await journal.record_event(event("server-a", "error"))
        assert [item.sequence async for item in journal.events(
            EventCursor("server-b", "exe", "session", "epoch"))] == [1]
        journal.close()

    asyncio.run(run())


def test_operation_admission_reserves_control_slots(tmp_path):
    async def run():
        limits = JournalLimits(max_operation_rows=3, reserved_operation_rows=1)
        journal = SQLiteJournal(tmp_path / "journal.db", limits=limits)
        await journal.admit(OperationKey("srv", "exe", "op1"), "h1", "session")
        await journal.admit(OperationKey("srv", "exe", "op2"), "h2", "session")
        with pytest.raises(CoreError, match="JOURNAL_FULL") as denied:
            await journal.admit(OperationKey("srv", "exe", "op3"), "h3", "session")
        assert denied.value.retry_safe and not denied.value.possible_effect
        await journal.admit(OperationKey("srv", "exe", "interrupt"), "h4",
                            "session", critical=True)
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.admit(OperationKey("srv", "exe", "close"), "h5",
                                "session", critical=True)
        old, fresh = await journal.admit(OperationKey("srv", "exe", "op1"),
                                         "h1", "session")
        assert not fresh and old.stage == "RECEIVED_DURABLE"
        journal.close()

    asyncio.run(run())


def test_eighty_percent_event_usage_blocks_new_work_but_not_control(tmp_path):
    async def run():
        limits = JournalLimits(total_event_rows=5, reserved_event_rows=1,
                               server_event_rows=5, server_reserved_rows=1)
        journal = SQLiteJournal(tmp_path / "journal.db", limits=limits)
        for _ in range(4):
            await journal.record_event(event(category="error"))
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.admit(OperationKey("srv", "exe", "new-work"),
                                "h", "session")
        await journal.admit(OperationKey("srv", "exe", "interrupt"),
                            "h2", "session", critical=True)
        journal.close()

    asyncio.run(run())


def test_byte_budget_and_conflict_do_not_spend_reserved_capacity(tmp_path):
    async def run():
        sample = event(sequence=1)
        size = len(SQLiteJournal._event_body(sample))
        limits = JournalLimits(total_event_bytes=size * 2,
                               reserved_event_bytes=size,
                               server_event_bytes=size * 2,
                               server_reserved_bytes=size)
        journal = SQLiteJournal(tmp_path / "journal.db", limits=limits)
        await journal.append_event(sample)
        with pytest.raises(CoreError, match="EVENT_CONFLICT"):
            await journal.append_event(RuntimeEvent("srv", "exe", "session",
                                                    "epoch", 1, "text_delta",
                                                    "native.event", {"text": "different"}))
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.append_event(event(sequence=2))
        await journal.append_event(event(category="error", sequence=2))
        journal.close()

    asyncio.run(run())


def test_one_server_admission_threshold_does_not_block_another(tmp_path):
    async def run():
        limits = JournalLimits(total_event_rows=100, reserved_event_rows=10,
                               server_event_rows=5, server_reserved_rows=1)
        journal = SQLiteJournal(tmp_path / "journal.db", limits=limits)
        for _ in range(4):
            await journal.record_event(event("server-a", "error"))
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.admit(OperationKey("server-a", "exe", "new-work"),
                                "h", "session")
        receipt, fresh = await journal.admit(
            OperationKey("server-b", "exe", "new-work"), "h", "session")
        assert fresh and receipt.stage == "RECEIVED_DURABLE"
        journal.close()

    asyncio.run(run())


def test_pre_quota_event_rows_are_counted_on_upgrade(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        journal = SQLiteJournal(path)
        await journal.record_event(event())
        journal.close()
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE journal_usage")
            db.execute("DROP TABLE server_usage")
        limits = JournalLimits(total_event_rows=2, reserved_event_rows=1,
                               server_event_rows=2, server_reserved_rows=1)
        journal = SQLiteJournal(path, limits=limits)
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.record_event(event())
        assert (await journal.record_event(event(category="turn_state"))).sequence == 2
        journal.close()

    asyncio.run(run())


def test_two_connections_cannot_overspend_quota(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        limits = JournalLimits(total_event_rows=3, reserved_event_rows=0,
                               server_event_rows=3, server_reserved_rows=0)
        first = SQLiteJournal(path, limits=limits)
        second = SQLiteJournal(path, limits=limits)
        results = await asyncio.gather(*(
            journal.record_event(event()) for journal in (first, second)
            for _ in range(5)), return_exceptions=True)
        written = [item for item in results if isinstance(item, RuntimeEvent)]
        denied = [item for item in results if isinstance(item, CoreError)]
        assert sorted(item.sequence for item in written) == [1, 2, 3]
        assert len(denied) == 7
        assert all(item.code == "JOURNAL_FULL" for item in denied)
        first.close()
        second.close()

    asyncio.run(run())


def test_saturated_session_preserves_other_session_and_critical_reserve(tmp_path):
    async def run():
        limits = JournalLimits(total_event_rows=20, reserved_event_rows=2,
                               server_event_rows=20, server_reserved_rows=2,
                               session_event_rows=5, session_reserved_rows=1)
        journal = SQLiteJournal(tmp_path / "journal.db", limits=limits)
        for _ in range(4):
            await journal.record_event(event(session="busy"))
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.record_event(event(session="busy"))
        with pytest.raises(CoreError, match="JOURNAL_FULL") as denied:
            await journal.admit(OperationKey("srv", "exe", "busy-work"),
                                "hash", "busy")
        assert denied.value.retry_safe and not denied.value.possible_effect
        assert (await journal.record_event(event(session="busy", category="error"))).sequence == 5
        assert (await journal.record_event(event(session="other"))).sequence == 1
        receipt, fresh = await journal.admit(OperationKey("srv", "exe", "other-work"),
                                              "hash", "other")
        assert fresh and receipt.stage == "RECEIVED_DURABLE"
        await journal.admit(OperationKey("srv", "exe", "busy-interrupt"),
                            "hash", "busy", critical=True)
        cursor = EventCursor("srv", "exe", "busy", "epoch")
        assert await journal.acknowledge_events(cursor, 5) == 5
        assert (await journal.compact_acked(max_rows=5))[0] == 5
        assert (await journal.record_event(event(session="busy"))).sequence == 6
        receipt, fresh = await journal.admit(OperationKey("srv", "exe", "busy-retry"),
                                              "hash", "busy")
        assert fresh and receipt.stage == "RECEIVED_DURABLE"
        journal.close()

    asyncio.run(run())


def test_session_quota_rebuilt_from_existing_events_and_serializes_writers(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        limits = JournalLimits(total_event_rows=10, reserved_event_rows=0,
                               server_event_rows=10, server_reserved_rows=0,
                               session_event_rows=2, session_reserved_rows=0)
        first = SQLiteJournal(path, limits=limits)
        second = SQLiteJournal(path, limits=limits)
        results = await asyncio.gather(*(
            journal.record_event(event(session="busy"))
            for journal in (first, second) for _ in range(3)),
            return_exceptions=True)
        assert sorted(item.sequence for item in results
                      if isinstance(item, RuntimeEvent)) == [1, 2]
        assert len([item for item in results if isinstance(item, CoreError)]) == 4
        first.close()
        second.close()
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE session_usage")
        journal = SQLiteJournal(path, limits=limits)
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.record_event(event(session="busy"))
        assert (await journal.record_event(event(session="other"))).sequence == 1
        journal.close()

    asyncio.run(run())


def test_session_byte_budget_does_not_consume_anothers_capacity(tmp_path):
    async def run():
        sample = event(sequence=1, session="busy")
        size = len(SQLiteJournal._event_body(sample))
        limits = JournalLimits(session_event_bytes=size * 3,
                               session_reserved_bytes=size * 2 - 1)
        journal = SQLiteJournal(tmp_path / "journal.db", limits=limits)
        await journal.append_event(sample)
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.append_event(event(sequence=2, session="busy"))
        assert (await journal.record_event(event(session="other"))).sequence == 1
        assert (await journal.record_event(event(session="busy", category="error"))).sequence == 2
        journal.close()

    asyncio.run(run())


def test_concurrent_noisy_session_cannot_starve_quiet_session(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        limits = JournalLimits(total_event_rows=40, reserved_event_rows=0,
                               server_event_rows=40, server_reserved_rows=0,
                               session_event_rows=5, session_reserved_rows=0)
        first = SQLiteJournal(path, limits=limits)
        second = SQLiteJournal(path, limits=limits)
        results = await asyncio.gather(*(
            first.record_event(event(session="noisy")) for _ in range(20)),
            *(second.record_event(event(session="quiet")) for _ in range(3)),
            return_exceptions=True)
        assert len([item for item in results[:20]
                    if isinstance(item, RuntimeEvent)]) == 5
        assert all(isinstance(item, CoreError) and item.code == "JOURNAL_FULL"
                   for item in results[:20] if not isinstance(item, RuntimeEvent))
        assert [item.sequence for item in results[20:]] == [1, 2, 3]
        first.close()
        second.close()

    asyncio.run(run())


def test_operation_slots_are_reserved_per_session_and_survive_restart(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        limits = JournalLimits(max_operation_rows=10, reserved_operation_rows=2,
                               session_operation_rows=3,
                               session_reserved_operation_rows=1)
        journal = SQLiteJournal(path, limits=limits)
        for index in range(2):
            _, fresh = await journal.admit(
                OperationKey("srv", "exe", f"busy-{index}"),
                f"hash-{index}", "busy")
            assert fresh
        with pytest.raises(CoreError, match="JOURNAL_FULL") as denied:
            await journal.admit(OperationKey("srv", "exe", "busy-2"),
                                "hash-2", "busy")
        assert denied.value.retry_safe and not denied.value.possible_effect
        _, fresh = await journal.admit(OperationKey("srv", "exe", "quiet-0"),
                                        "quiet-hash", "quiet")
        assert fresh
        _, fresh = await journal.admit(OperationKey("srv", "exe", "busy-control"),
                                        "control-hash", "busy", critical=True)
        assert fresh
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.admit(OperationKey("srv", "exe", "busy-control-2"),
                                "control-hash-2", "busy", critical=True)
        old, fresh = await journal.admit(OperationKey("srv", "exe", "busy-0"),
                                         "hash-0", "busy")
        assert not fresh and old.session_id == "busy"
        journal.close()
        journal = SQLiteJournal(path, limits=limits)
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.admit(OperationKey("srv", "exe", "busy-after-restart"),
                                "hash", "busy")
        _, fresh = await journal.admit(OperationKey("srv", "exe", "quiet-1"),
                                        "quiet-hash-1", "quiet")
        assert fresh
        journal.close()

    asyncio.run(run())


def test_operation_usage_rebuild_and_concurrent_connections(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        limits = JournalLimits(max_operation_rows=20, reserved_operation_rows=0,
                               session_operation_rows=3,
                               session_reserved_operation_rows=0)
        first = SQLiteJournal(path, limits=limits)
        second = SQLiteJournal(path, limits=limits)
        results = await asyncio.gather(*(
            journal.admit(OperationKey("srv", "exe", f"busy-{index}"),
                          f"hash-{index}", "busy")
            for index, journal in enumerate((first, second) * 4)),
            return_exceptions=True)
        assert len([item for item in results if isinstance(item, tuple)]) == 3
        assert len([item for item in results if isinstance(item, CoreError)]) == 5
        first.close()
        second.close()
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE session_operation_usage")
        journal = SQLiteJournal(path, limits=limits)
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.admit(OperationKey("srv", "exe", "busy-new"),
                                "new-hash", "busy")
        _, fresh = await journal.admit(OperationKey("srv", "exe", "quiet-new"),
                                        "quiet-hash", "quiet")
        assert fresh
        journal.close()

    asyncio.run(run())


def test_operation_slots_are_reserved_per_server_executor(tmp_path):
    async def run():
        limits = JournalLimits(max_operation_rows=20, reserved_operation_rows=2,
                               server_operation_rows=4,
                               server_reserved_operation_rows=1)
        journal = SQLiteJournal(tmp_path / "journal.db", limits=limits)
        for index in range(3):
            _, fresh = await journal.admit(
                OperationKey("noisy", "exe", f"op-{index}"),
                f"hash-{index}", f"session-{index}")
            assert fresh
        with pytest.raises(CoreError, match="JOURNAL_FULL") as denied:
            await journal.admit(OperationKey("noisy", "exe", "normal-denied"),
                                "hash", "another-session")
        assert denied.value.retry_safe and not denied.value.possible_effect
        _, fresh = await journal.admit(OperationKey("quiet", "exe", "normal"),
                                        "quiet-hash", "session")
        assert fresh
        _, fresh = await journal.admit(OperationKey("noisy", "exe", "urgent"),
                                        "urgent-hash", "another-session",
                                        critical=True)
        assert fresh
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.admit(OperationKey("noisy", "exe", "urgent-denied"),
                                "hash", "third-session", critical=True)
        old, fresh = await journal.admit(OperationKey("noisy", "exe", "op-0"),
                                         "hash-0", "session-0")
        assert not fresh and old.operation_id == "op-0"
        journal.close()

    asyncio.run(run())


def test_server_operation_usage_rebuild_and_concurrent_connections(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        limits = JournalLimits(max_operation_rows=20, reserved_operation_rows=0,
                               server_operation_rows=3,
                               server_reserved_operation_rows=0)
        first = SQLiteJournal(path, limits=limits)
        second = SQLiteJournal(path, limits=limits)
        results = await asyncio.gather(*(
            journal.admit(OperationKey("noisy", "exe", f"op-{index}"),
                          f"hash-{index}", f"session-{index}")
            for index, journal in enumerate((first, second) * 4)),
            return_exceptions=True)
        assert len([item for item in results if isinstance(item, tuple)]) == 3
        assert len([item for item in results if isinstance(item, CoreError)]) == 5
        first.close()
        second.close()
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE server_operation_usage")
        journal = SQLiteJournal(path, limits=limits)
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.admit(OperationKey("noisy", "exe", "after-upgrade"),
                                "hash", "fresh-session")
        _, fresh = await journal.admit(OperationKey("quiet", "exe", "allowed"),
                                        "hash", "session")
        assert fresh
        journal.close()

    asyncio.run(run())


def test_global_operation_counter_reserve_duplicate_and_upgrade(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        limits = JournalLimits(max_operation_rows=4, reserved_operation_rows=1)
        journal = SQLiteJournal(path, limits=limits)
        for index in range(3):
            _, fresh = await journal.admit(
                OperationKey(f"server-{index}", "exe", f"op-{index}"),
                f"hash-{index}", f"session-{index}")
            assert fresh
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.admit(OperationKey("other", "exe", "normal-denied"),
                                "hash", "session")
        _, fresh = await journal.admit(OperationKey("other", "exe", "urgent"),
                                        "urgent-hash", "session", critical=True)
        assert fresh
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.admit(OperationKey("another", "exe", "urgent-denied"),
                                "hash", "session", critical=True)
        old, fresh = await journal.admit(
            OperationKey("server-0", "exe", "op-0"), "hash-0", "session-0")
        assert not fresh and old.operation_id == "op-0"
        assert journal._run_sync(lambda db: db.execute(
            "SELECT operation_rows FROM operation_usage").fetchone())[0] == 4
        journal.close()

        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE operation_usage")
        journal = SQLiteJournal(path, limits=limits)
        assert journal._run_sync(lambda db: db.execute(
            "SELECT operation_rows FROM operation_usage").fetchone())[0] == 4
        with pytest.raises(CoreError, match="JOURNAL_FULL"):
            await journal.admit(OperationKey("new", "exe", "after-upgrade"),
                                "hash", "session", critical=True)
        journal.close()

    asyncio.run(run())


def test_global_operation_counter_serializes_two_connections(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        limits = JournalLimits(max_operation_rows=3, reserved_operation_rows=0)
        first = SQLiteJournal(path, limits=limits)
        second = SQLiteJournal(path, limits=limits)
        results = await asyncio.gather(*(
            journal.admit(OperationKey(f"server-{index}", "exe", f"op-{index}"),
                          f"hash-{index}", f"session-{index}")
            for index, journal in enumerate((first, second) * 4)),
            return_exceptions=True)
        assert len([item for item in results if isinstance(item, tuple)]) == 3
        assert len([item for item in results if isinstance(item, CoreError)]) == 5
        assert first._run_sync(lambda db: db.execute(
            "SELECT operation_rows FROM operation_usage").fetchone())[0] == 3
        first.close()
        second.close()

    asyncio.run(run())

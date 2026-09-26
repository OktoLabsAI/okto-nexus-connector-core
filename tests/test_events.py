import asyncio

import pytest

from nexus_connector_core import CoreError, EventCursor, OperationKey, OperationReceipt, RuntimeEvent
from nexus_connector_core.journal import SQLiteJournal


def test_contiguous_event_watermark_and_conflict(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        def event(sequence, payload):
            return RuntimeEvent("srv", "exe", "session", "epoch", sequence,
                                "text_delta", "native.delta", payload)
        cursor = EventCursor("srv", "exe", "session", "epoch")
        await journal.append_event(event(1, {"text": "a"}))
        await journal.append_event(event(3, {"text": "c"}))
        assert await journal.contiguous_watermark(cursor) == 1
        await journal.append_event(event(1, {"text": "a"}))
        with pytest.raises(CoreError, match="EVENT_CONFLICT"):
            await journal.append_event(event(1, {"text": "different"}))
        await journal.append_event(event(2, {"text": "b"}))
        assert await journal.contiguous_watermark(cursor) == 3
        assert [item.sequence async for item in journal.events(EventCursor("srv", "exe", "session", "epoch", 1))] == [2, 3]
        journal.close()
    asyncio.run(run())


def test_event_namespace_and_persistent_allocation(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        journal = SQLiteJournal(path)
        a = EventCursor("srv-a", "exe", "same-session", "epoch")
        b = EventCursor("srv-b", "exe", "same-session", "epoch")

        def event(server):
            return RuntimeEvent(server, "exe", "same-session", "epoch", 0,
                                "lifecycle", "native.started", {})

        first = await journal.record_event(event("srv-a"))
        other = await journal.record_event(event("srv-b"))
        assert (first.sequence, other.sequence) == (1, 1)
        journal.close()

        journal = SQLiteJournal(path)
        second = await journal.record_event(event("srv-a"))
        assert second.sequence == 2
        assert [item.sequence async for item in journal.events(a)] == [1, 2]
        assert [item.sequence async for item in journal.events(b)] == [1]
        assert await journal.contiguous_watermark(a) == 2
        assert await journal.contiguous_watermark(b) == 1
        with pytest.raises(CoreError, match="EVENT_INVALID"):
            await journal.record_event(first)
        journal.close()

    asyncio.run(run())


def test_two_journal_connections_allocate_without_collision(tmp_path):
    async def run():
        path = tmp_path / "journal.db"
        first = SQLiteJournal(path)
        second = SQLiteJournal(path)
        event = RuntimeEvent("srv", "exe", "session", "epoch", 0,
                             "lifecycle", "native.state", {})
        items = await asyncio.gather(*(journal.record_event(event)
                                       for journal in (first, second) for _ in range(10)))
        assert sorted(item.sequence for item in items) == list(range(1, 21))
        first.close()
        second.close()

    asyncio.run(run())


def test_replay_and_watermark_cross_bounded_pages(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        cursor = EventCursor("srv", "exe", "session", "epoch")
        for sequence in range(1, 301):
            await journal.append_event(RuntimeEvent("srv", "exe", "session",
                                                    "epoch", sequence,
                                                    "text_delta", "native.delta", {}))
        assert [item.sequence async for item in journal.events(cursor)] == list(range(1, 301))
        assert [item.sequence async for item in journal.events(
            EventCursor("srv", "exe", "session", "epoch", 255))] == list(range(256, 301))
        assert await journal.contiguous_watermark(cursor) == 300
        journal.close()

    asyncio.run(run())


def test_terminal_event_and_receipt_commit_together(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        key = OperationKey("srv", "exe", "op")
        await journal.admit(key, "hash", "session")
        await journal.mark_possible_effect(key)
        terminal = RuntimeEvent("srv", "exe", "session", "epoch", 0,
                                "turn_state", "native.completed",
                                {"delivery_phase": "terminal",
                                 "delivery_outcome": "success"}, "op")
        stored = await journal.record_event(terminal)
        assert stored.sequence == 1
        assert (await journal.get_receipt(key)).stage == "SUCCEEDED"
        late = await journal.record_receipt(key, OperationReceipt(
            "op", "hash", "SUBMITTED", True, False, "session", "native-id"))
        assert late.stage == "SUCCEEDED" and late.native_id == "native-id"
        journal.close()

    asyncio.run(run())


def test_wrong_session_terminal_cannot_mutate_operation_or_spend_sequence(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        key = OperationKey("srv", "exe", "op")
        await journal.admit(key, "hash", "session")
        await journal.mark_possible_effect(key)
        wrong = RuntimeEvent("srv", "exe", "other", "epoch", 0,
                             "turn_state", "native.completed",
                             {"delivery_phase": "terminal",
                              "delivery_outcome": "failed"}, "op")
        with pytest.raises(CoreError, match="EVENT_OPERATION_MISMATCH"):
            await journal.record_event(wrong)
        assert (await journal.get_receipt(key)).stage == "SUBMISSION_STARTED"
        assert [item async for item in journal.events(
            EventCursor("srv", "exe", "other", "epoch"))] == []
        valid = await journal.record_event(RuntimeEvent(
            "srv", "exe", "session", "epoch", 0, "turn_state",
            "native.completed", {"delivery_phase": "terminal",
                                 "delivery_outcome": "failed"}, "op"))
        assert valid.sequence == 1
        assert (await journal.get_receipt(key)).stage == "FAILED"
        journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("outcome,stage", [
    ("success", "SUCCEEDED"), ("failed", "FAILED"),
    ("interrupted", "CANCELLED"),
])
def test_terminal_outcome_mapping(tmp_path, outcome, stage):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        key = OperationKey("srv", "exe", "op")
        await journal.admit(key, "hash", "session")
        await journal.mark_possible_effect(key)
        await journal.record_event(RuntimeEvent(
            "srv", "exe", "session", "epoch", 0, "turn_state",
            "native.completed", {"delivery_phase": "terminal",
                                 "delivery_outcome": outcome}, "op"))
        assert (await journal.get_receipt(key)).stage == stage
        journal.close()

    asyncio.run(run())

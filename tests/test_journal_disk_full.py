"""Physical SQLite page exhaustion must not manufacture durable facts."""

import asyncio

import pytest

from nexus_connector_core import CoreError, EventCursor, OperationKey, RuntimeEvent
from nexus_connector_core.journal import SQLiteJournal


def test_sqlite_page_limit_rolls_back_event_and_preserves_sequence(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        pages = journal._db.execute("PRAGMA page_count").fetchone()[0]
        journal._db.execute(f"PRAGMA max_page_count={pages}")
        event = RuntimeEvent("srv", "exe", "session", "epoch", 0,
                             "text_delta", "native.output", {"text": "x" * 100_000})
        with pytest.raises(CoreError, match="JOURNAL_FULL") as failed:
            await journal.record_event(event)
        assert failed.value.possible_effect
        cursor = EventCursor("srv", "exe", "session", "epoch", 0)
        assert [item async for item in journal.events(cursor)] == []
        journal._db.execute(f"PRAGMA max_page_count={pages + 128}")
        recorded = await journal.record_event(event)
        assert recorded.sequence == 1
        assert [item.sequence async for item in journal.events(cursor)] == [1]
        journal.close()

    asyncio.run(run())


def test_sqlite_page_limit_rolls_back_admission(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        pages = journal._db.execute("PRAGMA page_count").fetchone()[0]
        journal._db.execute(f"PRAGMA max_page_count={pages}")
        key = OperationKey("srv", "exe", "new-work")
        with pytest.raises(CoreError, match="JOURNAL_FULL") as failed:
            await journal.admit(key, "hash", "session" * 20_000)
        assert failed.value.retry_safe and not failed.value.possible_effect
        assert await journal.get_receipt(key) is None
        journal._db.execute(f"PRAGMA max_page_count={pages + 128}")
        receipt, fresh = await journal.admit(key, "hash", "session" * 20_000)
        assert fresh and receipt.stage == "RECEIVED_DURABLE"
        journal.close()

    asyncio.run(run())

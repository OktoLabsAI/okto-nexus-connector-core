import asyncio

import pytest

from nexus_connector_core import CoreError, EventCursor
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.native.adapter_types import HarnessEvent
from nexus_connector_core.native.event_ingest import NativeEventIngestor


def test_native_events_are_durable_before_publication(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "events.db")
        published = []

        async def publish(event):
            cursor = EventCursor("srv", "exe", "session", "epoch")
            assert [item.sequence async for item in journal.events(cursor)] == [event.sequence]
            published.append(event)

        ingest = NativeEventIngestor(journal, server_id="srv", executor_id="exe",
                                     session_id="session", stream_epoch="epoch",
                                     publish=publish)
        native = HarnessEvent("session", "pi", "output_delta", "message_update",
                              "2026-09-25T00:00:00Z", {"text": "hello"},
                              operation_id="op1")
        stored = await ingest.ingest(native)
        assert stored.sequence == 1
        assert stored.category == "text_delta"
        assert stored.native_type == "message_update"
        assert stored.operation_id == "op1"
        assert published == [stored]
        journal.close()

    asyncio.run(run())


def test_native_event_rejects_wrong_session_and_oversize(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "events.db")
        ingest = NativeEventIngestor(journal, server_id="srv", executor_id="exe",
                                     session_id="session", stream_epoch="epoch")
        wrong = HarnessEvent("other", "pi", "error", "error",
                             "2026-09-25T00:00:00Z")
        with pytest.raises(CoreError, match="EVENT_SESSION_MISMATCH"):
            await ingest.ingest(wrong)
        huge = HarnessEvent("session", "pi", "output_delta", "message_update",
                            "2026-09-25T00:00:00Z", {"text": "x" * (256 * 1024)})
        with pytest.raises(CoreError, match="EVENT_TOO_LARGE"):
            await ingest.ingest(huge)
        journal.close()

    asyncio.run(run())


def test_publication_failure_does_not_erase_committed_event(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "events.db")

        async def failing_publish(_event):
            raise OSError("sink unavailable")

        ingest = NativeEventIngestor(journal, server_id="srv", executor_id="exe",
                                     session_id="session", stream_epoch="epoch",
                                     publish=failing_publish)
        native = HarnessEvent("session", "pi", "error", "native.error",
                              "2026-09-25T00:00:00Z")
        with pytest.raises(OSError, match="sink unavailable"):
            await ingest.ingest(native)
        cursor = EventCursor("srv", "exe", "session", "epoch")
        assert [item.sequence async for item in journal.events(cursor)] == [1]
        journal.close()

    asyncio.run(run())

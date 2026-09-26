import asyncio
from copy import deepcopy

import pytest

from nexus_connector_core import CoreError, EventCursor, RuntimeEvent
from nexus_connector_core.event_reducer import (
    event_ack_frame, event_batch_frame, reduce_durable_event_batch,
)
from nexus_connector_core.frame_codec import decode_frame, encode_frame
from nexus_connector_core.journal import SQLiteJournal


def _event(sequence, *, text="ok", session="session"):
    return RuntimeEvent("server", "executor", session, "epoch", sequence,
                        "text_delta", "native.delta", {"output_text": text}, "op")


def test_producer_round_trip_and_contiguous_scope_gate():
    frame = event_batch_frame([_event(1), _event(2)])
    assert decode_frame(encode_frame(frame).rstrip(b"\n")) == frame
    assert [event["sequence"] for event in frame["events"]] == [1, 2]
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        event_batch_frame([_event(1), _event(3)])
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        event_batch_frame([_event(1), _event(2, session="other")])
    with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
        event_batch_frame([])
    with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
        event_batch_frame([_event(seq) for seq in range(1, 130)])
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        event_batch_frame(["not-an-event"])


def test_gap_is_not_acked_until_durable_contiguous_sequence_arrives():
    pending = reduce_durable_event_batch(None, event_batch_frame([_event(3)]))
    assert pending.watermark == 0
    assert pending.pending[0][0] == 3
    with pytest.raises(CoreError, match="EVENT_GAP"):
        event_ack_frame(pending)
    complete = reduce_durable_event_batch(
        pending, event_batch_frame([_event(1), _event(2)]))
    assert complete.watermark == 3
    assert complete.pending == ()
    assert event_ack_frame(complete)["sequence"] == 3
    assert reduce_durable_event_batch(
        complete, event_batch_frame([_event(2), _event(3)])).watermark == 3


def test_conflicting_duplicate_and_scope_change_fail_closed():
    batch = event_batch_frame([_event(1)])
    current = reduce_durable_event_batch(None, batch)
    changed = event_batch_frame([_event(1, text="changed")])
    with pytest.raises(CoreError, match="EVENT_CONFLICT"):
        reduce_durable_event_batch(current, changed)
    with pytest.raises(CoreError, match="EVENT_SESSION_MISMATCH"):
        reduce_durable_event_batch(current, event_batch_frame([_event(2, session="other")]))
    invalid = deepcopy(batch)
    invalid["events"][0]["unknown"] = "x"
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        reduce_durable_event_batch(None, invalid)


def test_bounded_replay_window_requires_host_durable_check_for_old_duplicates():
    current = None
    for start in (1, 129, 257):
        current = reduce_durable_event_batch(
            current, event_batch_frame([_event(seq) for seq in range(start, start + 128)]))
    assert current.watermark == 384
    assert len(current.recent) == 256
    with pytest.raises(CoreError, match="EVENT_GAP"):
        reduce_durable_event_batch(current, event_batch_frame([_event(1)]))


def test_far_gap_is_rejected_without_advancing_ack():
    first = reduce_durable_event_batch(None, event_batch_frame([_event(1)]))
    with pytest.raises(CoreError, match="EVENT_GAP"):
        reduce_durable_event_batch(first, event_batch_frame([_event(258)]))
    assert first.watermark == 1


def test_wrong_family_and_revision_are_rejected():
    batch = event_batch_frame([_event(1)])
    batch["contract_revision"] = "nxl-1-agent-centric-http-only-2026-09-25-r1"
    with pytest.raises(CoreError):
        reduce_durable_event_batch(None, batch)
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        reduce_durable_event_batch(None, {"type": "event.ack"})


def test_ack_projection_matches_reference_journal_only_after_commit(tmp_path):
    async def run():
        journal = SQLiteJournal(tmp_path / "ingress.db")
        cursor = EventCursor("server", "executor", "session", "epoch")
        projection = None
        for event in (_event(3), _event(1), _event(2)):
            await journal.append_event(event)
            projection = reduce_durable_event_batch(
                projection, event_batch_frame([event]))
            assert projection.watermark == await journal.contiguous_watermark(cursor)
        ack = event_ack_frame(projection)
        assert ack["sequence"] == 3
        assert await journal.acknowledge_events(cursor, ack["sequence"]) == 3
        journal.close()

    asyncio.run(run())

"""R4 event ACKs require durable contiguous identity across reconnects."""

from __future__ import annotations

import pytest

from nexus_connector_core import (
    CoreError, R4_PREVIEW_REVISION, reduce_r4_durable_event_batch,
    r4_event_ack_frame,
)


def _batch(sequence: int, *, connection_id: str = "control-1",
           connection_generation: int = 1, payload=None) -> dict:
    return {
        "protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
        "type": "event.batch", "server_id": "srv",
        "executor_id": "exe", "binding_id": "binding",
        "agent_id": "agent", "session_id": "session",
        "stream_epoch": "epoch", "connection_id": connection_id,
        "connection_generation": connection_generation,
        "events": [{"server_id": "srv", "executor_id": "exe",
                    "session_id": "session", "stream_epoch": "epoch",
                    "sequence": sequence, "category": "lifecycle",
                    "payload": payload or {}}],
    }


def test_r4_event_watermark_waits_for_gap_and_fences_old_connection():
    with pytest.raises(CoreError):
        r4_event_ack_frame(None)
    gap = reduce_r4_durable_event_batch(
        None, _batch(2), connection_id="control-1",
        connection_generation=1)
    assert gap.watermark == 0
    with pytest.raises(CoreError):
        r4_event_ack_frame(gap)
    contiguous = reduce_r4_durable_event_batch(
        gap, _batch(1), connection_id="control-1",
        connection_generation=1)
    assert contiguous.watermark == 2
    assert r4_event_ack_frame(contiguous)["sequence"] == 2
    replay = reduce_r4_durable_event_batch(
        contiguous, _batch(1, connection_id="control-2",
                           connection_generation=2),
        connection_id="control-2", connection_generation=2)
    assert replay.watermark == 2
    assert r4_event_ack_frame(replay)["connection_id"] == "control-2"
    with pytest.raises(CoreError):
        reduce_r4_durable_event_batch(
            replay, _batch(1), connection_id="control-1",
            connection_generation=1)
    with pytest.raises(CoreError):
        reduce_r4_durable_event_batch(
            replay, _batch(1, connection_id="control-2",
                           connection_generation=2, payload={"changed": True}),
            connection_id="control-2", connection_generation=2)
    with pytest.raises(CoreError):
        reduce_r4_durable_event_batch(
            replay, {**_batch(3, connection_id="control-2",
                             connection_generation=2),
                     "events": [{**_batch(3)["events"][0],
                                 "session_id": "foreign"}]},
            connection_id="control-2", connection_generation=2)

"""Bounded pure NXL event batch and post-commit ACK projections.

The consumer reducer MUST be called only after the host has durably committed
and deduplicated every event in its batch. It cannot perform or prove a DB
commit itself. Its watermark never means UI delivery.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .frame_codec import decode_frame
from .models import CoreError, RuntimeEvent
from .protocol import CONTRACT_REVISION, PROTOCOL_MAJOR, canonical_json

_WINDOW = 256


@dataclass(frozen=True, slots=True)
class EventCommitProjection:
    server_id: str
    executor_id: str
    session_id: str
    stream_epoch: str
    watermark: int = 0
    recent: tuple[tuple[int, str], ...] = ()
    pending: tuple[tuple[int, str], ...] = ()


def _validated(frame: Mapping[str, Any], kind: str) -> dict[str, Any]:
    if not isinstance(frame, Mapping):
        raise CoreError("VALIDATION_ERROR", "event_reducer", retry_safe=True)
    try:
        parsed = decode_frame(canonical_json(dict(frame)))
    except (TypeError, ValueError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "event_reducer", retry_safe=True) from exc
    if parsed["type"] != kind:
        raise CoreError("VALIDATION_ERROR", "event_reducer", retry_safe=True)
    return parsed


def event_batch_frame(events: Sequence[RuntimeEvent]) -> dict[str, Any]:
    """Produce one schema-checked batch of 1..128 contiguous native events."""
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        raise CoreError("VALIDATION_ERROR", "event_batch")
    if not events or len(events) > 128:
        raise CoreError("CAPACITY_EXCEEDED", "event_batch")
    if any(not isinstance(event, RuntimeEvent) or
           not isinstance(event.payload, Mapping) for event in events):
        raise CoreError("VALIDATION_ERROR", "event_batch")
    first = events[0]
    payload = []
    for event in events:
        item: dict[str, Any] = {
            "server_id": event.server_id, "executor_id": event.executor_id,
            "session_id": event.session_id, "stream_epoch": event.stream_epoch,
            "sequence": event.sequence, "category": event.category,
            "payload": dict(event.payload),
        }
        if event.native_type is not None:
            item["native_type"] = event.native_type
        if event.operation_id is not None:
            item["operation_id"] = event.operation_id
        payload.append(item)
    frame = {
        "protocol_major": PROTOCOL_MAJOR,
        "contract_revision": CONTRACT_REVISION,
        "type": "event.batch", "server_id": first.server_id,
        "executor_id": first.executor_id, "session_id": first.session_id,
        "stream_epoch": first.stream_epoch, "events": payload,
    }
    return _validated(frame, "event.batch")


def reduce_durable_event_batch(previous: EventCommitProjection | None,
                               frame: Mapping[str, Any]) -> EventCommitProjection:
    """Advance only over events the caller has already durably committed.

    A gap may be held within a 256-sequence window, but cannot be ACKed.
    Recent/pending duplicate hashes are checked here; older duplicates need
    the host's durable identity/hash check before invoking this reducer.
    """
    parsed = _validated(frame, "event.batch")
    scope = (parsed["server_id"], parsed["executor_id"], parsed["session_id"],
             parsed["stream_epoch"])
    if previous is None:
        previous = EventCommitProjection(*scope)
    elif (previous.server_id, previous.executor_id, previous.session_id,
          previous.stream_epoch) != scope:
        raise CoreError("EVENT_SESSION_MISMATCH", "event_reducer")
    recent = dict(previous.recent)
    pending = dict(previous.pending)
    watermark = previous.watermark
    for event in parsed["events"]:
        sequence = event["sequence"]
        digest = hashlib.sha256(canonical_json(event)).hexdigest()
        if sequence <= watermark:
            if sequence not in recent:
                raise CoreError("EVENT_GAP", "event_reducer")
            if recent[sequence] != digest:
                raise CoreError("EVENT_CONFLICT", "event_reducer")
            continue
        if sequence > watermark + _WINDOW:
            raise CoreError("EVENT_GAP", "event_reducer")
        if sequence in pending and pending[sequence] != digest:
            raise CoreError("EVENT_CONFLICT", "event_reducer")
        pending[sequence] = digest
    while watermark + 1 in pending:
        watermark += 1
        recent[watermark] = pending.pop(watermark)
    recent = {seq: digest for seq, digest in recent.items()
              if seq > watermark - _WINDOW}
    if len(pending) > _WINDOW:
        raise CoreError("CAPACITY_EXCEEDED", "event_reducer")
    return EventCommitProjection(*scope, watermark,
                                 tuple(sorted(recent.items())),
                                 tuple(sorted(pending.items())))


def event_ack_frame(projection: EventCommitProjection) -> dict[str, Any]:
    """Produce an ACK only for a nonzero contiguous durable watermark."""
    if projection.watermark < 1:
        raise CoreError("EVENT_GAP", "event_ack")
    return _validated({
        "protocol_major": PROTOCOL_MAJOR,
        "contract_revision": CONTRACT_REVISION,
        "type": "event.ack", "server_id": projection.server_id,
        "executor_id": projection.executor_id,
        "session_id": projection.session_id,
        "stream_epoch": projection.stream_epoch,
        "sequence": projection.watermark,
    }, "event.ack")

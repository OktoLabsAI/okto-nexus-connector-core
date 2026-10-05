"""Pure R4 event watermark after the host has durably committed events."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

from .frame_codec_r4 import R4_PREVIEW_REVISION, decode_r4_frame
from .models import CoreError
from .protocol import canonical_json


_WINDOW = 256


@dataclass(frozen=True, slots=True)
class R4EventCommitProjection:
    server_id: str
    executor_id: str
    binding_id: str
    agent_id: str
    session_id: str
    stream_epoch: str
    source_connection_id: str
    source_connection_generation: int
    watermark: int = 0
    recent: tuple[tuple[int, str], ...] = ()
    pending: tuple[tuple[int, str], ...] = ()


def _validated(frame: Mapping[str, Any], kind: str) -> dict[str, Any]:
    if not isinstance(frame, Mapping):
        raise CoreError("VALIDATION_ERROR", "r4_event", retry_safe=True)
    try:
        parsed = decode_r4_frame(canonical_json(dict(frame)))
    except (TypeError, ValueError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "r4_event", retry_safe=True) from exc
    if parsed["type"] != kind:
        raise CoreError("VALIDATION_ERROR", "r4_event", retry_safe=True)
    return parsed


def reduce_r4_durable_event_batch(
    previous: R4EventCommitProjection | None, frame: Mapping[str, Any], *,
    connection_id: str, connection_generation: int,
) -> R4EventCommitProjection:
    """Advance only after durable deduplication of the exact event identity.

    A reconnect may change the envelope's connection origin, while each
    event keeps its original stream epoch, sequence and hash.
    """
    parsed = _validated(frame, "event.batch")
    if (parsed["connection_id"] != connection_id or
            parsed["connection_generation"] != connection_generation):
        raise CoreError("STALE_GENERATION", "r4_event")
    scope = tuple(parsed[field] for field in (
        "server_id", "executor_id", "binding_id", "agent_id",
        "session_id", "stream_epoch",
    ))
    if previous is not None and tuple(getattr(previous, field) for field in (
            "server_id", "executor_id", "binding_id", "agent_id",
            "session_id", "stream_epoch")) != scope:
        raise CoreError("EVENT_SESSION_MISMATCH", "r4_event")
    if previous is not None and (
            connection_generation < previous.source_connection_generation or
            (connection_generation == previous.source_connection_generation and
             connection_id != previous.source_connection_id) or
            (connection_generation > previous.source_connection_generation and
             connection_id == previous.source_connection_id)):
        raise CoreError("STALE_GENERATION", "r4_event")
    watermark = previous.watermark if previous else 0
    recent = dict(previous.recent) if previous else {}
    pending = dict(previous.pending) if previous else {}
    for event in parsed["events"]:
        if any(event[field] != parsed[field] for field in (
                "server_id", "executor_id", "session_id", "stream_epoch")):
            raise CoreError("EVENT_SESSION_MISMATCH", "r4_event")
        sequence = event["sequence"]
        digest = hashlib.sha256(canonical_json(event)).hexdigest()
        if sequence <= watermark:
            if sequence not in recent:
                raise CoreError("EVENT_GAP", "r4_event")
            if recent[sequence] != digest:
                raise CoreError("EVENT_CONFLICT", "r4_event")
            continue
        if sequence > watermark + _WINDOW:
            raise CoreError("EVENT_GAP", "r4_event")
        if sequence in pending and pending[sequence] != digest:
            raise CoreError("EVENT_CONFLICT", "r4_event")
        pending[sequence] = digest
    while watermark + 1 in pending:
        watermark += 1
        recent[watermark] = pending.pop(watermark)
    recent = {sequence: digest for sequence, digest in recent.items()
              if sequence > watermark - _WINDOW}
    return R4EventCommitProjection(
        *scope, connection_id, connection_generation, watermark,
        tuple(sorted(recent.items())), tuple(sorted(pending.items())),
    )


def r4_event_ack_frame(projection: R4EventCommitProjection) -> dict[str, Any]:
    """Return only the last contiguous watermark from committed storage."""
    if not isinstance(projection, R4EventCommitProjection) or projection.watermark < 1:
        raise CoreError("EVENT_GAP", "r4_event_ack")
    return _validated({
        "protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
        "type": "event.ack", "server_id": projection.server_id,
        "executor_id": projection.executor_id,
        "binding_id": projection.binding_id, "agent_id": projection.agent_id,
        "session_id": projection.session_id,
        "stream_epoch": projection.stream_epoch,
        "connection_id": projection.source_connection_id,
        "connection_generation": projection.source_connection_generation,
        "sequence": projection.watermark,
    }, "event.ack")

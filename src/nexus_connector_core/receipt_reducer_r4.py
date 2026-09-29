"""Pure R4 receipt projection with exact operation and source correlation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

from .frame_codec_r4 import decode_r4_frame
from .models import CoreError
from .protocol import canonical_json


_PROGRESS = {
    "RECEIVED_DURABLE": 1, "PREPARED": 2, "SUBMISSION_STARTED": 3,
    "SUBMITTED": 4, "ACCEPTED": 5, "RUNNING": 6, "WAITING_INPUT": 7,
}
_TERMINAL = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})


@dataclass(frozen=True, slots=True)
class R4ReceiptProjection:
    server_id: str
    executor_id: str
    binding_id: str
    agent_id: str
    session_id: str
    operation_id: str
    intent_hash: str
    receipt_revision: int
    stage: str
    possible_effect: bool
    retry_safe: bool
    native_id: str | None
    source_connection_id: str
    source_connection_generation: int
    observed: tuple[tuple[int, str], ...]


def _validated(frame: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(frame, Mapping):
        raise CoreError("VALIDATION_ERROR", "r4_receipt", retry_safe=True)
    try:
        parsed = decode_r4_frame(canonical_json(dict(frame)))
    except (ValueError, TypeError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "r4_receipt", retry_safe=True) from exc
    if parsed["type"] != "operation.receipt":
        raise CoreError("VALIDATION_ERROR", "r4_receipt", retry_safe=True)
    if parsed["possible_effect"] and parsed["retry_safe"]:
        raise CoreError("VALIDATION_ERROR", "r4_receipt", retry_safe=True)
    return parsed


def reduce_r4_receipt(previous: R4ReceiptProjection | None,
                      frame: Mapping[str, Any]) -> R4ReceiptProjection:
    """Apply a receipt only within its original operation and ordered revision."""
    parsed = _validated(frame)
    scope = tuple(parsed[field] for field in (
        "server_id", "executor_id", "binding_id", "agent_id",
        "session_id", "operation_id", "intent_hash",
        "connection_id", "connection_generation",
    ))
    digest = "sha256:" + hashlib.sha256(canonical_json(parsed)).hexdigest()
    revision = parsed["receipt_revision"]
    if previous is not None:
        old_scope = tuple(getattr(previous, field) for field in (
            "server_id", "executor_id", "binding_id", "agent_id",
            "session_id", "operation_id", "intent_hash",
            "source_connection_id", "source_connection_generation",
        ))
        if scope != old_scope:
            raise CoreError("OPERATION_CONFLICT", "r4_receipt")
        if revision <= previous.receipt_revision:
            for observed_revision, observed_digest in previous.observed:
                if observed_revision == revision:
                    if observed_digest != digest:
                        raise CoreError("OPERATION_CONFLICT", "r4_receipt")
                    return previous
            raise CoreError("OPERATION_CONFLICT", "r4_receipt")
        if revision != previous.receipt_revision + 1:
            raise CoreError("OPERATION_CONFLICT", "r4_receipt")
        if previous.possible_effect and not parsed["possible_effect"]:
            raise CoreError("OPERATION_CONFLICT", "r4_receipt")
        if (previous.native_id is not None and parsed.get("native_id") is not None
                and previous.native_id != parsed["native_id"]):
            raise CoreError("OPERATION_CONFLICT", "r4_receipt")
        if previous.stage in _TERMINAL and parsed["stage"] != previous.stage:
            raise CoreError("OPERATION_CONFLICT", "r4_receipt")
        if (previous.stage in _PROGRESS and parsed["stage"] in _PROGRESS and
                _PROGRESS[parsed["stage"]] < _PROGRESS[previous.stage] and
                not (previous.stage == "WAITING_INPUT" and
                     parsed["stage"] == "RUNNING")):
            raise CoreError("OPERATION_CONFLICT", "r4_receipt")
    elif revision != 1:
        raise CoreError("OPERATION_CONFLICT", "r4_receipt")
    observed = ((previous.observed if previous else ()) +
                ((revision, digest),))[-256:]
    return R4ReceiptProjection(
        *scope[:7], revision, parsed["stage"], parsed["possible_effect"],
        parsed["retry_safe"], parsed.get("native_id"),
        parsed["connection_id"], parsed["connection_generation"], observed,
    )

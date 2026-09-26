"""Pure NXL receipt producer/consumer state, independent of transport or DB.

Only observed receipt stages enter the projection. Transport ACK and native
acceptance are not inferred from a later terminal receipt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .frame_codec import decode_frame
from .models import CoreError, OperationReceipt
from .protocol import CONTRACT_REVISION, PROTOCOL_MAJOR, canonical_json

_PROGRESS = {
    "RECEIVED_DURABLE": 1, "PREPARED": 2, "SUBMISSION_STARTED": 3,
    "SUBMITTED": 4, "ACCEPTED": 5, "RUNNING": 6, "WAITING_INPUT": 7,
}
_TERMINAL = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})


@dataclass(frozen=True, slots=True)
class ReceiptProjection:
    server_id: str
    executor_id: str
    receipt: OperationReceipt
    observed: tuple[OperationReceipt, ...]


def _validated_receipt_frame(frame: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(frame, Mapping):
        raise CoreError("VALIDATION_ERROR", "receipt_reducer", retry_safe=True)
    try:
        parsed = decode_frame(canonical_json(dict(frame)))
    except (TypeError, ValueError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "receipt_reducer", retry_safe=True) from exc
    if parsed["type"] != "operation.receipt":
        raise CoreError("VALIDATION_ERROR", "receipt_reducer", retry_safe=True)
    return parsed


def receipt_frame(receipt: OperationReceipt, *, server_id: str,
                  executor_id: str) -> dict[str, Any]:
    """Produce a schema-checked NXL receipt frame from a Core receipt."""
    frame: dict[str, Any] = {
        "protocol_major": PROTOCOL_MAJOR,
        "contract_revision": CONTRACT_REVISION,
        "type": "operation.receipt",
        "server_id": server_id,
        "executor_id": executor_id,
        "session_id": receipt.session_id,
        "operation_id": receipt.operation_id,
        "intent_hash": receipt.intent_hash,
        "stage": receipt.stage,
        "possible_effect": receipt.possible_effect,
        "retry_safe": receipt.retry_safe,
    }
    if receipt.native_id is not None:
        frame["native_id"] = receipt.native_id
    if receipt.error_code is not None:
        frame["error_code"] = receipt.error_code
    return _validated_receipt_frame(frame)


def reduce_receipt(previous: ReceiptProjection | None,
                   frame: Mapping[str, Any]) -> ReceiptProjection:
    """Apply one validated observation; duplicates are idempotent.

    A later terminal may jump over absent ACK/stages. OUTCOME_UNKNOWN is not a
    safe failure or retry instruction; it can be resolved only by fresh
    progress/terminal evidence. Older out-of-order stages cannot roll state
    backward. Conflicting evidence for an already observed stage fails closed.
    """
    parsed = _validated_receipt_frame(frame)
    incoming = OperationReceipt(
        parsed["operation_id"], parsed["intent_hash"], parsed["stage"],
        parsed["possible_effect"], parsed["retry_safe"], parsed["session_id"],
        parsed.get("native_id"), parsed.get("error_code"))
    if previous is None:
        return ReceiptProjection(parsed["server_id"], parsed["executor_id"],
                                 incoming, (incoming,))
    if ((previous.server_id, previous.executor_id,
         previous.receipt.operation_id, previous.receipt.session_id,
         previous.receipt.intent_hash) !=
            (parsed["server_id"], parsed["executor_id"], incoming.operation_id,
             incoming.session_id, incoming.intent_hash)):
        raise CoreError("OPERATION_CONFLICT", "receipt_reducer")
    for observed in previous.observed:
        if observed.stage == incoming.stage:
            if observed != incoming:
                raise CoreError("OPERATION_CONFLICT", "receipt_reducer")
            return previous
    latest = previous.receipt.stage
    if latest in _TERMINAL:
        if incoming.stage in _TERMINAL:
            raise CoreError("OPERATION_CONFLICT", "receipt_reducer")
        return previous
    if incoming.stage == "OUTCOME_UNKNOWN":
        return ReceiptProjection(previous.server_id, previous.executor_id,
                                 incoming, previous.observed + (incoming,))
    if incoming.stage in _TERMINAL:
        return ReceiptProjection(previous.server_id, previous.executor_id,
                                 incoming, previous.observed + (incoming,))
    highest = max((_PROGRESS.get(item.stage, 0) for item in previous.observed),
                  default=0)
    if latest == "WAITING_INPUT" and incoming.stage == "RUNNING":
        return ReceiptProjection(previous.server_id, previous.executor_id,
                                 incoming, previous.observed + (incoming,))
    if _PROGRESS[incoming.stage] <= highest:
        return previous
    return ReceiptProjection(previous.server_id, previous.executor_id,
                             incoming, previous.observed + (incoming,))

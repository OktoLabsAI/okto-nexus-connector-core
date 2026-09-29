"""Verified projection of a Core turn receipt into an R4 transport fact.

The runtime journal and R4 wire protocol intentionally hash different
semantic domains. The host may publish this projection only after receiving
the corresponding Core receipt; copying either hash into the other domain
would defeat idempotency on one side.
"""

from __future__ import annotations

from typing import Any, Mapping

from .frame_codec_r4 import decode_r4_frame, encode_r4_frame
from .models import CoreError, ExecutionContext, Operation, OperationReceipt
from .protocol import canonical_json, intent_hash


def project_r4_turn_receipt(
    submit_frame: Mapping[str, Any], core_receipt: OperationReceipt,
    context: ExecutionContext, *, receipt_revision: int,
) -> dict[str, Any]:
    """Prove the Core turn semantic before producing a closed R4 receipt.

    The R4 delivery_id is admission metadata and is covered by the R4 hash;
    Core's native turn semantic is the text and optional expected turn ID.
    The host remains responsible for admission, lease, source connection and
    monotonic receipt revision. This function grants no effect authority.
    """
    if (not isinstance(core_receipt, OperationReceipt) or
            not isinstance(context, ExecutionContext) or
            type(receipt_revision) is not int or receipt_revision < 1):
        raise CoreError("VALIDATION_ERROR", "r4_receipt_projection")
    frame = decode_r4_frame(canonical_json(dict(submit_frame)))
    if frame["type"] != "operation.submit" or frame["action"] != "turn.submit":
        raise CoreError("CAPABILITY_UNSUPPORTED", "r4_receipt_projection")
    expected_scope = {
        "server_id": context.server_id,
        "executor_id": context.executor_id,
        "binding_id": context.binding_id,
        "agent_id": context.agent_id,
        "workspace_id": context.workspace_id,
        "authorization_revision": context.authorization_revision,
        "configuration_revision": context.configuration_revision,
        "connection_generation": context.connection_generation,
        "session_owner_generation": context.session_owner_generation,
    }
    if (any(frame[name] != value for name, value in expected_scope.items()) or
            core_receipt.operation_id != frame["operation_id"] or
            core_receipt.session_id != frame["session_id"]):
        raise CoreError("SCOPE_MISMATCH", "r4_receipt_projection")
    semantic = Operation(
        frame["operation_id"], frame["session_id"], "turn.submit",
        {"text": frame["payload"]["text"]}, frame.get("expected_turn_id"),
    )
    if core_receipt.intent_hash != intent_hash(semantic, context):
        raise CoreError("OPERATION_CONFLICT", "r4_receipt_projection")
    projected = {
        "protocol_major": frame["protocol_major"],
        "contract_revision": frame["contract_revision"],
        "type": "operation.receipt",
        "server_id": context.server_id,
        "executor_id": context.executor_id,
        "binding_id": context.binding_id,
        "agent_id": context.agent_id,
        "session_id": frame["session_id"],
        "connection_id": frame["connection_id"],
        "connection_generation": frame["connection_generation"],
        "operation_id": frame["operation_id"],
        "intent_hash": frame["intent_hash"],
        "receipt_revision": receipt_revision,
        "stage": core_receipt.stage,
        "possible_effect": core_receipt.possible_effect,
        "retry_safe": core_receipt.retry_safe,
    }
    if core_receipt.native_id is not None:
        projected["native_id"] = core_receipt.native_id
    if core_receipt.error_code is not None:
        projected["error_code"] = core_receipt.error_code
    return decode_r4_frame(encode_r4_frame(projected))

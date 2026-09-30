"""Verified projection of a Core operation receipt into an R4 transport fact.

The runtime journal and R4 wire protocol intentionally hash different
semantic domains. The host may publish this projection only after receiving
the corresponding Core receipt; copying either hash into the other domain
would defeat idempotency on one side.
"""

from __future__ import annotations

from typing import Any, Mapping

from .frame_codec_r4 import decode_r4_frame, encode_r4_frame
from .installation import effective_installation_ref
from .models import (
    CoreError, ExecutionContext, NativeApprovalOperation, Operation, OperationReceipt, PreparedLaunch,
)
from .decision_bridge_r4 import native_decision_semantic, r4_native_decision_operation
from .protocol import canonical_json, intent_hash


def project_r4_open_receipt(
    submit_frame: Mapping[str, Any], core_receipt: OperationReceipt,
    context: ExecutionContext, prepared: PreparedLaunch, *,
    stream_epoch: str, receipt_revision: int,
) -> dict[str, Any]:
    """Verify the selected local launch and Core open journal receipt."""
    frame = _checked_submit(
        submit_frame, core_receipt, context,
        receipt_revision=receipt_revision, action="runtime.open")
    if (not isinstance(prepared, PreparedLaunch) or
            not isinstance(stream_epoch, str) or not stream_epoch or
            prepared.intent.agent_id != context.agent_id or
            prepared.intent.workspace_id != context.workspace_id or
            prepared.intent.adapter_id != frame["payload"]["adapter_id"] or
            prepared.intent.mode != frame["payload"]["mode"] or
            prepared.intent.model != frame["payload"].get("model") or
            effective_installation_ref(prepared.candidate) !=
            frame["payload"]["candidate_ref"]):
        raise CoreError("PROFILE_DRIFT", "r4_receipt_projection",
                        possible_effect=True,
                        operation_id=core_receipt.operation_id)
    semantic = Operation(
        frame["operation_id"], frame["session_id"], "runtime.open",
        {"adapter_id": prepared.intent.adapter_id,
         "profile_fingerprint": prepared.profile_fingerprint,
         "root_fingerprint": prepared.root_fingerprint,
         "stream_epoch": stream_epoch},
    )
    if core_receipt.intent_hash != intent_hash(semantic, context):
        raise CoreError("OPERATION_CONFLICT", "r4_receipt_projection",
                        possible_effect=True,
                        operation_id=core_receipt.operation_id)
    return _wire_receipt(frame, core_receipt, context,
                         receipt_revision=receipt_revision)


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
    return _project_r4_receipt(
        submit_frame, core_receipt, context, receipt_revision=receipt_revision,
        action="turn.submit",
    )


def project_r4_steer_receipt(
    submit_frame: Mapping[str, Any], core_receipt: OperationReceipt,
    context: ExecutionContext, *, receipt_revision: int,
) -> dict[str, Any]:
    """Verify a Core steer receipt before publishing its R4 wire fact."""
    return _project_r4_receipt(
        submit_frame, core_receipt, context, receipt_revision=receipt_revision,
        action="turn.steer",
    )


def project_r4_interrupt_receipt(
    submit_frame: Mapping[str, Any], core_receipt: OperationReceipt,
    context: ExecutionContext, *, receipt_revision: int,
) -> dict[str, Any]:
    """Verify the reason and turn target of a Core interrupt receipt."""
    return _project_r4_receipt(
        submit_frame, core_receipt, context, receipt_revision=receipt_revision,
        action="turn.interrupt",
    )


def project_r4_close_receipt(
    submit_frame: Mapping[str, Any], core_receipt: OperationReceipt,
    context: ExecutionContext, *, receipt_revision: int,
) -> dict[str, Any]:
    """Verify the reason of a Core close receipt."""
    return _project_r4_receipt(
        submit_frame, core_receipt, context, receipt_revision=receipt_revision,
        action="runtime.close",
    )


def project_r4_decision_receipt(
    submit_frame: Mapping[str, Any], core_receipt: OperationReceipt,
    context: ExecutionContext, applied_operation: NativeApprovalOperation, *,
    receipt_revision: int,
) -> dict[str, Any]:
    """Verify the exact native request/response applied before publishing its fact.

    The native journal intentionally omits raw operator input. Verification
    therefore requires the typed operation used at the application boundary;
    recovery without protected response content cannot invent this proof.
    """
    if not isinstance(applied_operation, NativeApprovalOperation):
        raise CoreError("VALIDATION_ERROR", "r4_receipt_projection", possible_effect=True)
    try:
        semantic = native_decision_semantic(applied_operation)
        frame = _checked_submit(submit_frame, core_receipt, context,
                                receipt_revision=receipt_revision, action=semantic.action)
        projected = r4_native_decision_operation(
            frame, resolved_response=(applied_operation.operator_response
                                      if frame["payload"].get("response_ref") else None))
        expected_hash = intent_hash(semantic, context)
    except (CoreError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise CoreError(getattr(exc, "code", "VALIDATION_ERROR"),
                        "r4_receipt_projection", possible_effect=True,
                        operation_id=getattr(core_receipt, "operation_id", None)) from exc
    if projected != applied_operation or core_receipt.intent_hash != expected_hash:
        raise CoreError("OPERATION_CONFLICT", "r4_receipt_projection",
                        possible_effect=True, operation_id=core_receipt.operation_id)
    return _wire_receipt(frame, core_receipt, context, receipt_revision=receipt_revision)


def _project_r4_receipt(
    submit_frame: Mapping[str, Any], core_receipt: OperationReceipt,
    context: ExecutionContext, *, receipt_revision: int, action: str,
) -> dict[str, Any]:
    frame = _checked_submit(
        submit_frame, core_receipt, context,
        receipt_revision=receipt_revision, action=action)
    payload_key = ("text" if action in {"turn.submit", "turn.steer"}
                   else "reason")
    semantic = Operation(
        frame["operation_id"], frame["session_id"], action,
        {payload_key: frame["payload"][payload_key]},
        frame.get("expected_turn_id"),
    )
    if action == "runtime.close":
        from .close_operation import close_operation_semantic, r4_close_operation
        semantic = close_operation_semantic(r4_close_operation(frame))
    if core_receipt.intent_hash != intent_hash(semantic, context):
        raise CoreError("OPERATION_CONFLICT", "r4_receipt_projection",
                        possible_effect=True,
                        operation_id=core_receipt.operation_id)
    return _wire_receipt(frame, core_receipt, context,
                         receipt_revision=receipt_revision)


def _checked_submit(
    submit_frame: Mapping[str, Any], core_receipt: OperationReceipt,
    context: ExecutionContext, *, receipt_revision: int, action: str,
) -> dict[str, Any]:
    if (not isinstance(core_receipt, OperationReceipt) or
            not isinstance(context, ExecutionContext) or
            type(receipt_revision) is not int or receipt_revision < 1):
        raise CoreError("VALIDATION_ERROR", "r4_receipt_projection",
                        possible_effect=True)
    try:
        frame = _checked_source(submit_frame, context, action=action)
    except CoreError as error:
        # Preserve the established live-projection diagnostic identity even
        # when the submitted envelope itself is malformed or foreign.
        raise CoreError(error.code, "r4_receipt_projection", possible_effect=True,
                        operation_id=core_receipt.operation_id) from error
    if (core_receipt.operation_id != frame["operation_id"] or
            core_receipt.session_id != frame["session_id"]):
        raise CoreError("SCOPE_MISMATCH", "r4_receipt_projection",
                        possible_effect=True, operation_id=core_receipt.operation_id)
    return frame


def _checked_source(submit_frame, context, *, action):
    if not isinstance(context, ExecutionContext):
        raise CoreError("VALIDATION_ERROR", "r4_receipt_projection")
    try:
        frame = decode_r4_frame(canonical_json(dict(submit_frame)))
    except (CoreError, ValueError, TypeError, AttributeError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "r4_receipt_projection",
                        possible_effect=True,
                        operation_id=None) from exc
    if frame["type"] != "operation.submit" or frame["action"] != action:
        raise CoreError("CAPABILITY_UNSUPPORTED", "r4_receipt_projection",
                        possible_effect=True,
                        operation_id=frame.get("operation_id"))
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
    if context.r4_authority is not None:
        authority = context.r4_authority
        expected_scope.update({
            "session_id": authority.session_id,
            "workspace_binding_id": authority.workspace_binding_id,
            "binding_revision": authority.binding_revision,
            "credential_epoch": authority.credential_epoch,
            "grant_id": authority.grant_id,
            "connection_id": authority.connection_id,
        })
    if any(frame[name] != value for name, value in expected_scope.items()):
        raise CoreError("SCOPE_MISMATCH", "r4_receipt_projection",
                        possible_effect=True,
                        operation_id=frame["operation_id"])
    return frame


def _wire_receipt(
    frame: Mapping[str, Any], core_receipt: OperationReceipt,
    context: ExecutionContext, *, receipt_revision: int,
) -> dict[str, Any]:
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
    try:
        return decode_r4_frame(encode_r4_frame(projected))
    except (CoreError, ValueError, TypeError) as exc:
        raise CoreError("VALIDATION_ERROR", "r4_receipt_projection",
                        possible_effect=True,
                        operation_id=core_receipt.operation_id) from exc

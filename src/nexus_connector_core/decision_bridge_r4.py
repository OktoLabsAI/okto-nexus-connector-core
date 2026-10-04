"""Typed R4 decisions over the unchanged native request and journal semantics.

The R4 request hash covers the entire operational proposal. The native hash
inside it remains byte-for-byte unchanged, including its historical encoding.
These helpers grant no authority; RuntimeCore still requires a live context
and the exact pending request observed from the native session.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .frame_codec_r4 import decode_r4_frame
from .models import CoreError, NativeApprovalOperation, Operation
from .protocol import canonical_json


def r4_operational_request_hash(request: Mapping[str, Any]) -> str:
    """Digest the complete proposal without rewriting its native request_hash."""
    if not isinstance(request, Mapping):
        raise CoreError("VALIDATION_ERROR", "r4_native_request")
    try:
        return "sha256:" + hashlib.sha256(canonical_json(dict(request))).hexdigest()
    except (ValueError, TypeError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "r4_native_request") from exc


def r4_native_decision_operation(
    submit_frame: Mapping[str, Any], *,
    resolved_response: Mapping[str, Any] | None = None,
) -> NativeApprovalOperation:
    """Validate wire action/response integrity before invoking the public Core.

    A response_ref is resolved by the authorized host. Supplying it does not
    bypass digest validation, and a missing response is never fabricated.
    """
    try:
        frame = decode_r4_frame(canonical_json(dict(submit_frame)))
    except (ValueError, TypeError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "r4_native_decision") from exc
    if frame["type"] != "operation.submit" or frame["action"] not in {
        "approval.decide", "input.provide",
    }:
        raise CoreError("CAPABILITY_UNSUPPORTED", "r4_native_decision")
    payload = frame["payload"]
    request = payload["request"]
    action = native_request_action(request)
    if action != frame["action"]:
        raise CoreError("CAPABILITY_UNSUPPORTED", "r4_native_decision")
    response = payload.get("response")
    if payload.get("response_ref") is not None:
        if not isinstance(resolved_response, Mapping):
            raise CoreError("INPUT_RESPONSE_UNAVAILABLE", "r4_native_decision",
                            retry_safe=True)
        response = dict(resolved_response)
    elif resolved_response is not None:
        raise CoreError("VALIDATION_ERROR", "r4_native_decision")
    try:
        # Freeze caller-owned data before the await in the host's runtime call.
        # The strict codec has already frozen the operational request.
        response_bytes = canonical_json(response) if response is not None else None
        response_digest = ("sha256:" + hashlib.sha256(response_bytes).hexdigest()
                           if response_bytes is not None else None)
    except (ValueError, TypeError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "r4_native_decision") from exc
    if payload["response_digest"] != response_digest:
        raise CoreError("OPERATION_CONFLICT", "r4_native_decision")
    if response_bytes is not None:
        from .protocol import strict_json
        response = strict_json(response_bytes.decode("utf-8"))
    return NativeApprovalOperation(
        operation_id=frame["operation_id"], session_id=frame["session_id"],
        request=request, decision=payload["decision"], operator_response=response,
    )


def native_request_action(request: Mapping[str, Any]) -> str:
    """Core-owned classification shared with RuntimeCore's native decision API."""
    from .native.native_inputs import INPUT_METHODS, claude_permission_tool_supported

    method, params = request.get("method"), request.get("params")
    if not isinstance(params, dict):
        raise CoreError("VALIDATION_ERROR", "approval_decide")
    if method == "extension_ui_request":
        from .native.native_inputs import validate_request
        try:
            validate_request(method, params)
            if type(request.get("local_generation")) is not int or request["local_generation"] < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise CoreError("VALIDATION_ERROR", "approval_decide") from None
        return "input.provide"
    if method in INPUT_METHODS or method in {
        "item/commandExecution/requestApproval", "item/fileChange/requestApproval",
    }:
        if type(params.get("turnId")) is not str or not params["turnId"]:
            raise CoreError("VALIDATION_ERROR", "approval_decide")
        return "input.provide" if method in INPUT_METHODS else "approval.decide"
    if method == "control_request:can_use_tool":
        tool_name = params.get("tool_name")
        if not claude_permission_tool_supported(tool_name):
            raise CoreError("CAPABILITY_UNSUPPORTED", "approval_decide")
        generation = request.get("local_generation")
        if type(generation) is not int or generation < 0:
            raise CoreError("VALIDATION_ERROR", "approval_decide")
        return "input.provide" if tool_name == "AskUserQuestion" else "approval.decide"
    raise CoreError("CAPABILITY_UNSUPPORTED", "approval_decide")


def native_decision_semantic(operation: NativeApprovalOperation) -> Operation:
    """Preserve the existing native journal hash domain, including response hash."""
    response = operation.operator_response
    return Operation(
        operation.operation_id, operation.session_id,
        native_request_action(operation.request),
        {"request_id": operation.request["request_id"],
         "request_hash": operation.request["request_hash"],
         "method": operation.request["method"], "decision": operation.decision,
         "response_sha256": (hashlib.sha256(canonical_json(dict(response))).hexdigest()
                             if response is not None else None)},
    )

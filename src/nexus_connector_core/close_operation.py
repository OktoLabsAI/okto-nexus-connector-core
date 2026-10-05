"""Typed close policy and lossless projection of the R4 close payload."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .frame_codec_r4 import decode_r4_frame
from .models import CloseOperation, CoreError, Operation, ShutdownPolicy
from .protocol import canonical_json


def close_operation_semantic(operation: CloseOperation) -> Operation:
    if not isinstance(operation, CloseOperation):
        raise CoreError("VALIDATION_ERROR", "close")
    if operation.reason is not None and (
            type(operation.reason) is not str or len(operation.reason) > 1024):
        raise CoreError("VALIDATION_ERROR", "close")
    payload = {"reason": operation.reason} if operation.reason is not None else {}
    if operation.policy is not None:
        if not isinstance(operation.policy, ShutdownPolicy):
            raise CoreError("VALIDATION_ERROR", "close_policy")
        for name, maximum in (("drain_seconds", 30), ("interrupt_seconds", 15)):
            value = getattr(operation.policy, name)
            if (type(value) not in (int, float) or not 0 <= value <= maximum or
                    not math.isfinite(value)):
                raise CoreError("VALIDATION_ERROR", "close_policy")
            payload[name] = value
    return Operation(operation.operation_id, operation.session_id, "runtime.close", payload)


def r4_close_operation(frame: Mapping[str, Any]) -> CloseOperation:
    """Validate the Core wire and preserve every close field in the operation."""
    parsed = decode_r4_frame(canonical_json(dict(frame)))
    if parsed["type"] != "operation.submit" or parsed["action"] != "runtime.close" or parsed.get("expected_turn_id") is not None:
        raise CoreError("VALIDATION_ERROR", "r4_close")
    payload = parsed["payload"]
    operation = CloseOperation(parsed["operation_id"], parsed["session_id"],
        payload["reason"], ShutdownPolicy(payload["drain_seconds"], payload["interrupt_seconds"]))
    close_operation_semantic(operation)
    return operation

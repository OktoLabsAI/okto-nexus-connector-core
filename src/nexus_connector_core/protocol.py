"""Pure NXL intent canonicalization and negotiation."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

import rfc8785

from .models import CoreError, ExecutionContext, Operation

CONTRACT_REVISION = "nxl-1-agent-centric-http-only-2026-09-25-r3"
PROTOCOL_MAJOR = 1


def strict_json(text: str) -> Any:
    """Parse one interoperable JSON value, rejecting ambiguous Unicode/numbers."""
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant: {value}")

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("non-finite JSON number")
        return parsed

    parsed = json.loads(text, object_pairs_hook=pairs,
                        parse_constant=invalid_constant, parse_float=finite_float)
    _validate(parsed)
    return parsed


def _validate(value: Any) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("unpaired surrogate")
        return
    if isinstance(value, int):
        if not (-9007199254740991 <= value <= 9007199254740991):
            raise ValueError("integer outside interoperable JSON range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return
    if isinstance(value, list):
        for member in value:
            _validate(member)
        return
    if isinstance(value, dict):
        for key, member in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object key must be string")
            if any(0xD800 <= ord(char) <= 0xDFFF for char in key):
                raise ValueError("unpaired surrogate")
            _validate(member)
        return
    raise ValueError(f"not a JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    """RFC 8785 JCS bytes for an unambiguous JSON value."""
    _validate(value)
    return rfc8785.dumps(value)


def intent_hash(operation: Operation, context: ExecutionContext) -> str:
    semantic = {
        "server_id": context.server_id,
        "executor_id": context.executor_id,
        "binding_id": context.binding_id,
        "agent_id": context.agent_id,
        "workspace_id": context.workspace_id,
        "session_id": operation.session_id,
        "action": operation.action,
        "payload": dict(operation.payload),
        "configuration_revision": context.configuration_revision,
        "expected_turn_id": operation.expected_turn_id,
    }
    return "sha256:" + hashlib.sha256(canonical_json(semantic)).hexdigest()


def submit_frame_intent_hash(frame: Mapping[str, Any]) -> str:
    """Recompute the semantic intent from a schema-validated submit frame.

    Transport attempt/generation, authorization revision, workspace binding
    and operation ID are deliberately excluded, matching ``intent_hash``.
    Callers must validate the frame first; this does not authorize an effect.
    """
    semantic = {key: frame[key] for key in (
        "server_id", "executor_id", "binding_id", "agent_id", "workspace_id",
        "session_id", "action", "payload", "configuration_revision")}
    semantic["expected_turn_id"] = frame.get("expected_turn_id")
    return "sha256:" + hashlib.sha256(canonical_json(semantic)).hexdigest()


def require_contract(protocol_major: int, revision: str) -> None:
    if protocol_major != PROTOCOL_MAJOR or revision != CONTRACT_REVISION:
        raise CoreError("VERSION_INCOMPATIBLE", "negotiation", retry_safe=False)

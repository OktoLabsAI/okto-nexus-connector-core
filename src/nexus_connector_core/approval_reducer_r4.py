"""Pure R4 approval notification correlation; no native decision application."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from typing import Any, Mapping

from .frame_codec_r4 import decode_r4_frame
from .models import CoreError
from .protocol import canonical_json


_SCOPE = (
    "server_id", "executor_id", "binding_id", "agent_id",
    "workspace_id", "workspace_binding_id", "session_id",
    "session_owner_generation", "authorization_revision",
    "configuration_revision", "binding_revision", "credential_epoch",
    "connection_id", "connection_generation",
)


@dataclass(frozen=True, slots=True)
class R4ApprovalProjection:
    scope: tuple[Any, ...]
    canonical_request_id: str
    request_hash: str
    request_revision: int
    kind: str
    decision_id: str | None = None
    decision_revision: int = 0
    decision: str | None = None
    decision_digest: str | None = None


def _validated(frame: Mapping[str, Any], kind: str) -> dict[str, Any]:
    if not isinstance(frame, Mapping):
        raise CoreError("VALIDATION_ERROR", "r4_approval", retry_safe=True)
    try:
        parsed = decode_r4_frame(canonical_json(dict(frame)))
    except (TypeError, ValueError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "r4_approval", retry_safe=True) from exc
    if parsed["type"] != kind:
        raise CoreError("VALIDATION_ERROR", "r4_approval", retry_safe=True)
    return parsed


def reduce_r4_approval_request(previous: R4ApprovalProjection | None,
                               frame: Mapping[str, Any]
                               ) -> R4ApprovalProjection:
    """Retain the original operational request identity, never just UI text."""
    parsed = _validated(frame, "approval.request")
    if parsed["operational_request"]["request_hash"] != parsed["request_hash"]:
        raise CoreError("OPERATION_CONFLICT", "r4_approval")
    scope = tuple(parsed[field] for field in _SCOPE)
    if previous is not None:
        if (previous.scope != scope or
                previous.canonical_request_id != parsed["canonical_request_id"]):
            raise CoreError("OPERATION_CONFLICT", "r4_approval")
        if parsed["request_revision"] < previous.request_revision:
            raise CoreError("STALE_GENERATION", "r4_approval")
        if parsed["request_revision"] == previous.request_revision:
            if (parsed["request_hash"] != previous.request_hash or
                    parsed["kind"] != previous.kind):
                raise CoreError("OPERATION_CONFLICT", "r4_approval")
            return previous
        if previous.decision_id is not None:
            raise CoreError("OPERATION_CONFLICT", "r4_approval")
    return R4ApprovalProjection(
        scope, parsed["canonical_request_id"], parsed["request_hash"],
        parsed["request_revision"], parsed["kind"],
    )


def reduce_r4_approval_decision(previous: R4ApprovalProjection,
                                frame: Mapping[str, Any]
                                ) -> R4ApprovalProjection:
    """Record a server notification; only operation.submit may apply it."""
    if not isinstance(previous, R4ApprovalProjection):
        raise CoreError("VALIDATION_ERROR", "r4_approval")
    parsed = _validated(frame, "approval.decision")
    if (tuple(parsed[field] for field in _SCOPE) != previous.scope or
            parsed["canonical_request_id"] != previous.canonical_request_id or
            parsed["request_hash"] != previous.request_hash):
        raise CoreError("OPERATION_CONFLICT", "r4_approval")
    digest = "sha256:" + hashlib.sha256(canonical_json(parsed)).hexdigest()
    if previous.decision_id is not None:
        if (parsed["decision_id"] == previous.decision_id and
                parsed["decision_revision"] == previous.decision_revision and
                digest == previous.decision_digest):
            return previous
        raise CoreError("OPERATION_CONFLICT", "r4_approval")
    return replace(previous, decision_id=parsed["decision_id"],
                   decision_revision=parsed["decision_revision"],
                   decision=parsed["decision"], decision_digest=digest)

"""Scoped native domain-action port for harness extensions without MCP HTTP.

This module does not implement inbox, claim, completion, approval or MCP.
Trusted hosts inject their existing canonical backend for these operations.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any, Protocol

from .clock import RollbackFencedClock, SystemClock
from .models import CoreError, ExecutionContext
from .ports import Clock
from .protocol import canonical_json

_MAX_RESULT_BYTES = 16 * 1024
_FORBIDDEN_ENVELOPE_KEYS = frozenset({"jsonrpc", "method", "params", "tools", "mcpServers"})


@dataclass(frozen=True, slots=True)
class NativeActionGrant:
    capability_ref: str
    server_id: str
    executor_id: str
    binding_id: str
    agent_id: str
    workspace_id: str
    session_id: str
    connection_generation: int
    authorization_revision: int
    configuration_revision: int
    expires_monotonic: float
    allowed_actions: frozenset[str]


@dataclass(frozen=True, slots=True)
class NativeActionRequest:
    operation_id: str
    session_id: str
    capability_ref: str
    handoff_id: str


@dataclass(frozen=True, slots=True)
class ContextGet(NativeActionRequest):
    pass


@dataclass(frozen=True, slots=True)
class HandoffClaim(NativeActionRequest):
    idempotency_key: str
    claim_epoch: int | None = None


@dataclass(frozen=True, slots=True)
class HandoffComplete(NativeActionRequest):
    claim_epoch: int
    result: Any


class CanonicalNativeActions(Protocol):
    async def get_context(self, request: ContextGet,
                          context: ExecutionContext) -> Mapping[str, Any]: ...
    async def claim_handoff(self, request: HandoffClaim,
                            context: ExecutionContext) -> Mapping[str, Any]: ...
    async def complete_handoff(self, request: HandoffComplete,
                               context: ExecutionContext) -> Mapping[str, Any]: ...


def _bounded_id(value: str, *, maximum: int = 160) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= maximum and
            all(char.isprintable() and char not in "\r\n\x00" for char in value))


class ScopedNativeActionBridge:
    """Local scope gate; all domain decisions remain in the injected backend."""

    def __init__(self, backend: CanonicalNativeActions, grant: NativeActionGrant,
                 *, clock: Clock | None = None):
        if (not grant.capability_ref.startswith("native-cap:") or
                not _bounded_id(grant.capability_ref, maximum=256) or
                not all(_bounded_id(value) for value in (
                    grant.server_id, grant.executor_id, grant.binding_id,
                    grant.agent_id, grant.workspace_id, grant.session_id)) or
                not math.isfinite(grant.expires_monotonic) or
                not grant.allowed_actions <= {
                    "handoff.get", "handoff.claim", "handoff.complete"}):
            raise ValueError("invalid native action grant")
        self._backend = backend
        self._grant = grant
        self._clock = RollbackFencedClock(clock or SystemClock())

    async def invoke(self, request: NativeActionRequest,
                     context: ExecutionContext) -> Mapping[str, Any]:
        if type(request) is ContextGet:
            action = "handoff.get"
        elif type(request) is HandoffClaim:
            action = "handoff.claim"
        elif type(request) is HandoffComplete:
            action = "handoff.complete"
        else:
            raise CoreError("CAPABILITY_UNSUPPORTED", "native_action")
        grant = self._grant
        if (not _bounded_id(request.operation_id) or
                not _bounded_id(request.session_id) or
                not _bounded_id(request.handoff_id) or
                not isinstance(request.capability_ref, str)):
            raise CoreError("VALIDATION_ERROR", "native_action")
        if (request.capability_ref != grant.capability_ref or
                request.session_id != grant.session_id or
                (context.server_id, context.executor_id, context.binding_id,
                 context.agent_id, context.workspace_id,
                 context.connection_generation,
                 context.authorization_revision,
                 context.configuration_revision) !=
                (grant.server_id, grant.executor_id, grant.binding_id,
                 grant.agent_id, grant.workspace_id,
                 grant.connection_generation,
                 grant.authorization_revision,
                 grant.configuration_revision)):
            raise CoreError("BINDING_NOT_AUTHORIZED", "native_action")
        if (action not in grant.allowed_actions or
                action not in context.allowed_actions):
            raise CoreError("BINDING_NOT_AUTHORIZED", "native_action")
        if (not math.isfinite(context.lease_deadline_monotonic) or
                self._clock.monotonic() >= min(grant.expires_monotonic,
                                              context.lease_deadline_monotonic)):
            raise CoreError("AGENT_REVOKED", "native_action")
        if type(request) is HandoffClaim:
            if (not _bounded_id(request.idempotency_key, maximum=128) or
                    (request.claim_epoch is not None and
                     (type(request.claim_epoch) is not int or request.claim_epoch < 1))):
                raise CoreError("VALIDATION_ERROR", "native_action")
        if type(request) is HandoffComplete:
            if type(request.claim_epoch) is not int or request.claim_epoch < 1:
                raise CoreError("VALIDATION_ERROR", "native_action")
            if (isinstance(request.result, Mapping) and
                    _FORBIDDEN_ENVELOPE_KEYS.intersection(request.result)):
                raise CoreError("CAPABILITY_UNSUPPORTED", "native_action")
            try:
                if len(canonical_json(request.result)) > _MAX_RESULT_BYTES:
                    raise CoreError("CAPACITY_EXCEEDED", "native_action")
            except (TypeError, ValueError, RecursionError) as exc:
                raise CoreError("VALIDATION_ERROR", "native_action") from exc
        try:
            if type(request) is ContextGet:
                response = await self._backend.get_context(request, context)
            elif type(request) is HandoffClaim:
                response = await self._backend.claim_handoff(request, context)
            else:
                response = await self._backend.complete_handoff(request, context)
        except CoreError:
            raise
        except Exception:
            if type(request) is ContextGet:
                raise CoreError("EXECUTOR_OFFLINE", "native_action",
                                retry_safe=True,
                                operation_id=request.operation_id) from None
            # The backend may have committed a claim/completion before failing.
            # Never infer safe retry from a lost response.
            raise CoreError("OUTCOME_UNKNOWN", "native_action",
                            possible_effect=True,
                            operation_id=request.operation_id) from None
        if (not isinstance(response, Mapping) or
                _FORBIDDEN_ENVELOPE_KEYS.intersection(response)):
            raise CoreError("VALIDATION_ERROR" if type(request) is ContextGet
                            else "OUTCOME_UNKNOWN", "native_action",
                            possible_effect=type(request) is not ContextGet,
                            retry_safe=type(request) is ContextGet,
                            operation_id=request.operation_id)
        try:
            if len(canonical_json(dict(response))) > _MAX_RESULT_BYTES:
                raise CoreError("CAPACITY_EXCEEDED" if type(request) is ContextGet
                                else "OUTCOME_UNKNOWN", "native_action",
                                possible_effect=type(request) is not ContextGet,
                                retry_safe=type(request) is ContextGet,
                                operation_id=request.operation_id)
        except (TypeError, ValueError, RecursionError) as exc:
            raise CoreError("VALIDATION_ERROR" if type(request) is ContextGet
                            else "OUTCOME_UNKNOWN", "native_action",
                            possible_effect=type(request) is not ContextGet,
                            retry_safe=type(request) is ContextGet,
                            operation_id=request.operation_id) from exc
        return response

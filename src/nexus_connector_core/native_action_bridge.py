"""Scoped native domain-action port for harness extensions without MCP HTTP.

This module does not implement inbox, claim, completion, approval or MCP.
Trusted hosts inject their existing canonical backend for these operations.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import math
import json
from types import MappingProxyType
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
    r4_scope: Mapping[str, Any] | None = None
    r4_connection_id: str | None = None


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


@dataclass(frozen=True, slots=True)
class RuntimeInputList:
    operation_id: str
    session_id: str
    capability_ref: str


@dataclass(frozen=True, slots=True)
class RuntimeInputRespond(RuntimeInputList):
    request: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MessageCreate(RuntimeInputList):
    message: Mapping[str, Any]


class CanonicalNativeActions(Protocol):
    async def create_message(self, request: MessageCreate,
                             context: ExecutionContext) -> Mapping[str, Any]: ...
    async def list_runtime_inputs(self, request: RuntimeInputList,
                                  context: ExecutionContext) -> Mapping[str, Any]: ...
    async def respond_runtime_input(self, request: RuntimeInputRespond,
                                    context: ExecutionContext) -> Mapping[str, Any]: ...
    async def get_context(self, request: ContextGet,
                          context: ExecutionContext) -> Mapping[str, Any]: ...
    async def claim_handoff(self, request: HandoffClaim,
                            context: ExecutionContext) -> Mapping[str, Any]: ...
    async def complete_handoff(self, request: HandoffComplete,
                               context: ExecutionContext) -> Mapping[str, Any]: ...


def _bounded_id(value: str, *, maximum: int = 160) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= maximum and
            all(char.isprintable() and char not in "\r\n\x00" for char in value))


_SCOPE_IDS = ('server_id', 'executor_id', 'binding_id', 'agent_id',
              'workspace_id', 'workspace_binding_id', 'session_id')
_SCOPE_REVISIONS = ('session_owner_generation', 'binding_revision', 'credential_epoch',
                    'authorization_revision', 'configuration_revision')


def native_action_scope(scope: Mapping[str, Any]) -> dict[str, Any]:
    """Snapshot the complete canonical R4 session scope without coercion."""
    if (not isinstance(scope, Mapping) or set(scope) != set(_SCOPE_IDS + _SCOPE_REVISIONS)
            or any(not _bounded_id(scope[k]) for k in _SCOPE_IDS)
            or any(type(scope[k]) is not int or scope[k] < 1 for k in _SCOPE_REVISIONS)):
        raise CoreError('VALIDATION_ERROR', 'native_action_scope')
    return dict(scope)


def native_action_context_scope(context: ExecutionContext) -> dict[str, Any]:
    """Extract the full typed R4 scope without weakening lease identity."""
    authority = context.r4_authority
    if authority is None:
        raise CoreError('LEASE_REVALIDATION_REQUIRED', 'native_action_scope')
    return native_action_scope({
        'server_id': context.server_id, 'executor_id': context.executor_id,
        'binding_id': context.binding_id, 'agent_id': context.agent_id,
        'workspace_id': context.workspace_id, 'session_id': authority.session_id,
        'workspace_binding_id': authority.workspace_binding_id,
        'binding_revision': authority.binding_revision, 'credential_epoch': authority.credential_epoch,
        'session_owner_generation': context.session_owner_generation,
        'authorization_revision': context.authorization_revision,
        'configuration_revision': context.configuration_revision,
    })


def native_action_request_body(request: NativeActionRequest, scope: Mapping[str, Any]) -> dict[str, Any]:
    """Translate the public typed request to the canonical native action DTO.

    Hosts own transport and authentication. This helper never invents IDs,
    retries a request or implements a handoff transition.
    """
    scope = native_action_scope(scope)
    types = {ContextGet: 'context', HandoffClaim: 'claim', HandoffComplete: 'complete',
             RuntimeInputList: 'input_list', RuntimeInputRespond: 'input_respond', MessageCreate: 'message_create'}
    action = types.get(type(request))
    if action is None:
        raise CoreError('CAPABILITY_UNSUPPORTED', 'native_action')
    question = type(request) in {RuntimeInputList, RuntimeInputRespond, MessageCreate}
    if (not _bounded_id(request.operation_id) or (not question and not _bounded_id(request.handoff_id))
            or request.session_id != scope['session_id']
            or not _bounded_id(request.capability_ref, maximum=256)
            or not request.capability_ref.startswith('native-cap:')):
        raise CoreError('VALIDATION_ERROR', 'native_action')
    payload = {} if question else dict(handoff_id=request.handoff_id)
    if type(request) is MessageCreate:
        if not isinstance(request.message, Mapping):
            raise CoreError('VALIDATION_ERROR', 'native_action')
        payload['message'] = dict(request.message)
    if type(request) is RuntimeInputRespond:
        if not isinstance(request.request, Mapping):
            raise CoreError('VALIDATION_ERROR', 'native_action')
        payload['request'] = dict(request.request)
    if type(request) is HandoffClaim:
        if not _bounded_id(request.idempotency_key, maximum=128):
            raise CoreError('VALIDATION_ERROR', 'native_action')
        payload['idempotency_key'] = request.idempotency_key
        if request.claim_epoch is not None:
            payload['claim_epoch'] = request.claim_epoch
    if type(request) is HandoffComplete:
        if isinstance(request.result, Mapping) and _FORBIDDEN_ENVELOPE_KEYS.intersection(request.result):
            raise CoreError('CAPABILITY_UNSUPPORTED', 'native_action')
        payload.update(claim_epoch=request.claim_epoch, result=request.result)
    if 'claim_epoch' in payload and (type(payload['claim_epoch']) is not int or payload['claim_epoch'] < 1):
        raise CoreError('VALIDATION_ERROR', 'native_action')
    try:
        encoded = canonical_json(dict(action_id=request.operation_id, scope=scope, action=action, payload=payload))
    except (TypeError, ValueError, RecursionError):
        raise CoreError('VALIDATION_ERROR', 'native_action') from None
    if len(encoded) > _MAX_RESULT_BYTES:
        raise CoreError('CAPACITY_EXCEEDED', 'native_action')
    return json.loads(encoded)


class ScopedNativeActionBridge:
    """Local scope gate; all domain decisions remain in the injected backend."""

    def __init__(self, backend: CanonicalNativeActions, grant: NativeActionGrant,
                 *, clock: Clock | None = None, r4_runtime=None):
        if (not _bounded_id(grant.capability_ref, maximum=256) or
                not grant.capability_ref.startswith("native-cap:") or
                not all(_bounded_id(value) for value in (
                    grant.server_id, grant.executor_id, grant.binding_id,
                    grant.agent_id, grant.workspace_id, grant.session_id)) or
                type(grant.expires_monotonic) not in (int, float) or
                not math.isfinite(grant.expires_monotonic) or
                not grant.allowed_actions <= {
                    "handoff.get", "handoff.claim", "handoff.complete",
                    "runtime.input.list", "runtime.input.respond", "message.create"}):
            raise ValueError("invalid native action grant")
        if any(type(v) is not int or v < 1 for v in (
                grant.connection_generation, grant.authorization_revision, grant.configuration_revision)):
            raise ValueError("Invalid native action revisions.")
        if grant.r4_scope is not None:
            scope = native_action_scope(grant.r4_scope)
            if (r4_runtime is None or not _bounded_id(grant.r4_connection_id)
                    or any(scope[k] != getattr(grant, k) for k in (
                        'server_id', 'executor_id', 'binding_id', 'agent_id', 'workspace_id',
                        'session_id', 'authorization_revision', 'configuration_revision'))):
                raise ValueError("An installed runtime and matching R4 grant scope are required.")
            grant = replace(grant, r4_scope=MappingProxyType(scope))
        elif r4_runtime is not None or grant.r4_connection_id is not None:
            raise ValueError("A complete R4 native grant is required.")
        self._r4_runtime = r4_runtime
        self._backend = backend
        self._grant = replace(grant, allowed_actions=frozenset(grant.allowed_actions))
        self._clock = RollbackFencedClock(clock or SystemClock())

    async def invoke(self, request: NativeActionRequest,
                     context: ExecutionContext) -> Mapping[str, Any]:
        if type(request) is ContextGet:
            action = "handoff.get"
        elif type(request) is HandoffClaim:
            action = "handoff.claim"
        elif type(request) is HandoffComplete:
            action = "handoff.complete"
        elif type(request) is RuntimeInputList:
            action = 'runtime.input.list'
        elif type(request) is RuntimeInputRespond:
            action = 'runtime.input.respond'
        elif type(request) is MessageCreate:
            action = 'message.create'
        else:
            raise CoreError("CAPABILITY_UNSUPPORTED", "native_action")
        grant = self._grant
        if (not _bounded_id(request.operation_id) or
                not _bounded_id(request.session_id) or
                (type(request) not in {RuntimeInputList, RuntimeInputRespond, MessageCreate} and not _bounded_id(request.handoff_id)) or
                not isinstance(request.capability_ref, str)):
            raise CoreError("VALIDATION_ERROR", "native_action")
        self._authorize(request, context, action)
        read_only = type(request) in {ContextGet, RuntimeInputList}
        if type(request) is MessageCreate:
            try:
                if not isinstance(request.message, Mapping):
                    raise CoreError('VALIDATION_ERROR', 'native_action')
                if len(canonical_json(dict(request.message))) > _MAX_RESULT_BYTES:
                    raise CoreError('CAPACITY_EXCEEDED', 'native_action')
            except (TypeError, ValueError, RecursionError) as exc:
                raise CoreError('VALIDATION_ERROR', 'native_action') from exc
        if type(request) is RuntimeInputRespond:
            if not isinstance(request.request, Mapping):
                raise CoreError('VALIDATION_ERROR', 'native_action')
            try:
                if len(canonical_json(dict(request.request))) > _MAX_RESULT_BYTES:
                    raise CoreError('CAPACITY_EXCEEDED', 'native_action')
            except (TypeError, ValueError, RecursionError) as exc:
                raise CoreError('VALIDATION_ERROR', 'native_action') from exc
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
            elif type(request) is RuntimeInputList:
                response = await self._backend.list_runtime_inputs(request, context)
            elif type(request) is RuntimeInputRespond:
                response = await self._backend.respond_runtime_input(request, context)
            elif type(request) is MessageCreate:
                response = await self._backend.create_message(request, context)
            else:
                response = await self._backend.complete_handoff(request, context)
        except CoreError:
            raise
        except Exception:
            if read_only:
                raise CoreError("EXECUTOR_OFFLINE", "native_action",
                                retry_safe=True,
                                operation_id=request.operation_id) from None
            # The backend may have committed a claim/completion before failing.
            # Never infer safe retry from a lost response.
            raise CoreError("OUTCOME_UNKNOWN", "native_action",
                            possible_effect=True,
                            operation_id=request.operation_id) from None
        try:
            self._authorize(request, context, action)
        except CoreError:
            if read_only:
                raise
            raise CoreError('OUTCOME_UNKNOWN', 'native_action', possible_effect=True,
                            operation_id=request.operation_id) from None
        if (not isinstance(response, Mapping) or
                _FORBIDDEN_ENVELOPE_KEYS.intersection(response)):
            raise CoreError("VALIDATION_ERROR" if read_only
                            else "OUTCOME_UNKNOWN", "native_action",
                            possible_effect=not read_only,
                            retry_safe=read_only,
                            operation_id=request.operation_id)
        try:
            if len(canonical_json(dict(response))) > _MAX_RESULT_BYTES:
                raise CoreError("CAPACITY_EXCEEDED" if read_only
                                else "OUTCOME_UNKNOWN", "native_action",
                                possible_effect=not read_only,
                                retry_safe=read_only,
                                operation_id=request.operation_id)
        except (TypeError, ValueError, RecursionError) as exc:
            raise CoreError("VALIDATION_ERROR" if read_only
                            else "OUTCOME_UNKNOWN", "native_action",
                            possible_effect=not read_only,
                            retry_safe=read_only,
                            operation_id=request.operation_id) from exc
        return response

    def _authorize(self, request, context, action):
        grant = self._grant
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
        if action not in grant.allowed_actions:
            raise CoreError("BINDING_NOT_AUTHORIZED", "native_action")
        if grant.r4_scope is not None:
            current = self._r4_runtime.r4_native_action_context(
                grant.r4_scope, connection_id=grant.r4_connection_id,
                connection_generation=grant.connection_generation)
            if (context != current or type(context.connection_generation) is not int
                    or canonical_json(native_action_context_scope(context)) != canonical_json(dict(grant.r4_scope))):
                raise CoreError('STALE_GENERATION', 'native_action')
        elif context.r4_authority is not None or action not in context.allowed_actions:
            raise CoreError('BINDING_NOT_AUTHORIZED', 'native_action')
        if (not math.isfinite(context.lease_deadline_monotonic) or
                self._clock.monotonic() >= min(grant.expires_monotonic,
                                              context.lease_deadline_monotonic)):
            raise CoreError("AGENT_REVOKED", "native_action")

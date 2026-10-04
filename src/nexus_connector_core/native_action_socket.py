"""Host-owned, loopback-only JSONL ingress for explicit native actions.

This is not MCP and does not own inbox, claim, completion or governance.
The host injects its canonical backend into ``ScopedNativeActionBridge`` and
supplies a current execution context for every request.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import json
import math
from typing import Any

from .models import CoreError, ExecutionContext, SessionKey
from .native_action_bridge import (
    ContextGet, HandoffClaim, HandoffComplete, ScopedNativeActionBridge,
    RuntimeInputList, RuntimeInputRespond, MessageCreate,
)
from .protocol import canonical_json

_MAX_RECORD_BYTES = 16 * 1024
_MAX_ACTIVE_CONNECTIONS = 16
_TIMEOUT_S = 10.0
_COMMON_KEYS = frozenset({"action", "operation_id", "session_id",
                          "capability_ref", "handoff_id"})
_ACTION_KEYS = {
    'message.create': ((_COMMON_KEYS - {'handoff_id'}) | {'message'}, (_COMMON_KEYS - {'handoff_id'}) | {'message'}),
    'runtime.input.list': (_COMMON_KEYS - {'handoff_id'}, _COMMON_KEYS - {'handoff_id'}),
    'runtime.input.respond': ((_COMMON_KEYS - {'handoff_id'}) | {'request'}, (_COMMON_KEYS - {'handoff_id'}) | {'request'}),
    "handoff.get": (_COMMON_KEYS, _COMMON_KEYS),
    "handoff.claim": (_COMMON_KEYS | {"idempotency_key"},
                      _COMMON_KEYS | {"idempotency_key", "claim_epoch"}),
    "handoff.complete": (_COMMON_KEYS | {"claim_epoch", "result"},
                         _COMMON_KEYS | {"claim_epoch", "result"}),
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate native-action field")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("non-JSON numeric constant")


def _decode_request(line: bytes) -> ContextGet | HandoffClaim | HandoffComplete:
    if (not line.endswith(b"\n") or len(line) > _MAX_RECORD_BYTES + 1 or
            b"\n" in line[:-1]):
        raise CoreError("VALIDATION_ERROR", "native_action_ingress")
    try:
        value = json.loads(line[:-1].decode("utf-8"),
                           object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "native_action_ingress") from exc
    if not isinstance(value, dict):
        raise CoreError("VALIDATION_ERROR", "native_action_ingress")
    action = value.get("action")
    if not isinstance(action, str) or action not in _ACTION_KEYS:
        raise CoreError("CAPABILITY_UNSUPPORTED", "native_action_ingress")
    required, allowed = _ACTION_KEYS[action]
    if not required <= value.keys() or not value.keys() <= allowed:
        raise CoreError("VALIDATION_ERROR", "native_action_ingress")
    if action == 'message.create':
        return MessageCreate(value['operation_id'], value['session_id'], value['capability_ref'], value['message'])
    if action.startswith('runtime.input.'):
        base = (value['operation_id'], value['session_id'], value['capability_ref'])
        return RuntimeInputList(*base) if action == 'runtime.input.list' else RuntimeInputRespond(*base, value['request'])
    base = (value["operation_id"], value["session_id"],
            value["capability_ref"], value["handoff_id"])
    if action == "handoff.get":
        return ContextGet(*base)
    if action == "handoff.claim":
        return HandoffClaim(*base, value["idempotency_key"],
                            value.get("claim_epoch"))
    return HandoffComplete(*base, value["claim_epoch"], value["result"])


class NativeActionSocketService:
    """One owned session ingress; observation timeouts never cancel effects.

    Closing fences admission immediately and closes client sockets. Backend
    producers remain owned until they settle, even when the caller stops
    waiting. Hosts retain this service and its dependencies while close()
    returns False. A closed service cannot be restarted.
    """

    def __init__(self, bridge: ScopedNativeActionBridge,
                 context_provider: Callable[[], ExecutionContext]):
        self._bridge = bridge
        self._context_provider = context_provider
        self._server: asyncio.AbstractServer | None = None
        self._start_task = None
        self._close_task = None
        self._closing = False
        self._handlers = set()
        self._effects = set()
        self._writers = set()

    @property
    def port(self) -> int:
        if self._closing or self._server is None or not self._server.sockets:
            raise RuntimeError("The native action service is not running.")
        return int(self._server.sockets[0].getsockname()[1])

    @property
    def pending_count(self) -> int:
        return len(self._effects)

    async def start(self) -> int:
        if self._start_task is not None or self._closing:
            raise RuntimeError("The native action service has already started or closed.")
        self._start_task = asyncio.create_task(self._start(), name="native-action-listener")
        self._start_task.add_done_callback(self._observe)
        await asyncio.shield(self._start_task)
        return self.port

    async def _start(self):
        self._server = await asyncio.start_server(self._accept,
            host="127.0.0.1", port=0, limit=_MAX_RECORD_BYTES + 2)

    @staticmethod
    def _observe(task):
        if not task.cancelled():
            task.exception()

    def _accept(self, reader, writer):
        # A synchronous callback claims ownership before the first await.
        if (self._closing or len(self._handlers) >= _MAX_ACTIVE_CONNECTIONS
                or len(self._effects) >= _MAX_ACTIVE_CONNECTIONS):
            writer.close()
            return
        self._writers.add(writer)
        task = asyncio.create_task(self._handle(reader, writer), name="native-action-client")
        self._handlers.add(task)
        task.add_done_callback(self._handlers.discard)
        task.add_done_callback(self._observe)

    async def close(self, *, timeout_seconds: float = _TIMEOUT_S) -> bool:
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise ValueError("The native action close timeout must be finite and nonnegative.")
        self._closing = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="native-action-close")
            self._close_task.add_done_callback(self._observe)
        # asyncio.wait observes completion without cancelling the producer.
        done, _ = await asyncio.wait((self._close_task,), timeout=timeout_seconds)
        if not done:
            return False
        self._close_task.result()
        return True

    async def _close(self):
        if self._start_task is not None:
            await asyncio.gather(self._start_task, return_exceptions=True)
        if self._server is not None:
            self._server.close()
        for writer in tuple(self._writers):
            writer.close()
        handlers = tuple(self._handlers)
        for task in handlers:
            task.cancel()  # Socket observers only; backend tasks are shielded.
        await asyncio.gather(*handlers, return_exceptions=True)
        if self._server is not None:
            await self._server.wait_closed()
            self._server = None
        await asyncio.gather(*tuple(self._effects), return_exceptions=True)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        request = None
        effect_started = False
        try:
            try:
                line = await asyncio.wait_for(reader.readline(), _TIMEOUT_S)
                request = _decode_request(line)
                if self._closing:
                    raise CoreError("RUNTIME_DRAINING", "native_action_ingress")
                if len(self._effects) >= _MAX_ACTIVE_CONNECTIONS:
                    raise CoreError("CAPACITY_EXCEEDED", "native_action_ingress")
                context = self._context_provider()
                if not isinstance(context, ExecutionContext):
                    raise CoreError("EXECUTOR_OFFLINE", "native_action_ingress")
                task = asyncio.create_task(self._bridge.invoke(request, context),
                                           name="native-action-backend")
                self._effects.add(task)
                task.add_done_callback(self._effects.discard)
                task.add_done_callback(self._observe)
                effect_started = True
                result: Mapping[str, Any] = await asyncio.wait_for(asyncio.shield(task), _TIMEOUT_S)
                payload = canonical_json({"ok": True, "data": dict(result)})
            except CoreError as exc:
                payload = canonical_json({"ok": False, "code": exc.code,
                    "possible_effect": exc.possible_effect, "retry_safe": exc.retry_safe,
                    "operation_id": request.operation_id if request is not None else None})
            except Exception:
                payload = self._uncertain(request, effect_started)
            if len(payload) > _MAX_RECORD_BYTES:
                payload = self._uncertain(request, effect_started)
            try:
                writer.write(payload + b"\n")
                await asyncio.wait_for(writer.drain(), _TIMEOUT_S)
            except (ConnectionError, asyncio.TimeoutError):
                pass
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), _TIMEOUT_S)
            except (ConnectionError, asyncio.TimeoutError):
                pass
            self._writers.discard(writer)

    @staticmethod
    def _uncertain(request, effect_started):
        mutation = effect_started and isinstance(request, (HandoffClaim, HandoffComplete, RuntimeInputRespond, MessageCreate))
        return canonical_json({"ok": False,
            "code": "OUTCOME_UNKNOWN" if mutation else "EXECUTOR_OFFLINE",
            "possible_effect": mutation, "retry_safe": not mutation,
            "operation_id": request.operation_id if request is not None else None})


class PiNativeActionOwner:
    """Trusted host hook for one Pi session, with retained ingress ownership."""

    def __init__(self, bridge, context_provider, *, capability_ref: str, session_id: str):
        from .pi_extension_resource import PiNativeActionLaunch
        # Reuse public launch validation before allocating a listener.
        PiNativeActionLaunch(1, capability_ref, session_id)
        self._reference, self._session_id = capability_ref, session_id
        self.session_key = None
        self._context_provider = context_provider
        self._service = NativeActionSocketService(bridge, context_provider)
        self._start_task = None
        self._closing = False

    @property
    def pending_count(self):
        return self._service.pending_count

    def _authorize(self, prepared, session_id, context):
        if (self._closing or prepared.intent.adapter_id != "pi_rpc"
                or session_id != self._session_id or self._reference not in prepared.secret_refs
                or context != self._context_provider()):
            raise CoreError("BINDING_NOT_AUTHORIZED", "native_action_launch")

    async def launch(self, prepared, session_id, context):
        from .pi_extension_resource import PiNativeActionLaunch
        self._authorize(prepared, session_id, context)
        self.session_key = SessionKey(context.server_id, context.executor_id, session_id)
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._service.start(), name="pi-native-action-start")
            self._start_task.add_done_callback(NativeActionSocketService._observe)
        port = await asyncio.shield(self._start_task)
        self._authorize(prepared, session_id, context)
        return PiNativeActionLaunch(port, self._reference, self._session_id)

    async def close(self, *, timeout_seconds: float = _TIMEOUT_S) -> bool:
        self._closing = True
        return await self._service.close(timeout_seconds=timeout_seconds)

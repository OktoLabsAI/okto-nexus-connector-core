"""Host-owned, loopback-only JSONL ingress for explicit native actions.

This is not MCP and does not own inbox, claim, completion or governance.
The host injects its canonical backend into ``ScopedNativeActionBridge`` and
supplies a current execution context for every request.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import json
from typing import Any

from .models import CoreError, ExecutionContext
from .native_action_bridge import (
    ContextGet, HandoffClaim, HandoffComplete, ScopedNativeActionBridge,
)
from .protocol import canonical_json

_MAX_RECORD_BYTES = 16 * 1024
_MAX_ACTIVE_CONNECTIONS = 16
_TIMEOUT_S = 10.0
_COMMON_KEYS = frozenset({"action", "operation_id", "session_id",
                          "capability_ref", "handoff_id"})
_ACTION_KEYS = {
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
    base = (value["operation_id"], value["session_id"],
            value["capability_ref"], value["handoff_id"])
    if action == "handoff.get":
        return ContextGet(*base)
    if action == "handoff.claim":
        return HandoffClaim(*base, value["idempotency_key"],
                            value.get("claim_epoch"))
    return HandoffComplete(*base, value["claim_epoch"], value["result"])


class NativeActionSocketService:
    """One session's narrow ingress, bound only to IPv4 loopback.

    ``start`` and ``close`` run on the host's event loop. The returned port
    is passed only to the owned Pi child along with its session capability.
    """

    def __init__(self, bridge: ScopedNativeActionBridge,
                 context_provider: Callable[[], ExecutionContext]):
        self._bridge = bridge
        self._context_provider = context_provider
        self._server: asyncio.AbstractServer | None = None
        self._active = 0

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("native action service is not running")
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> int:
        if self._server is not None:
            raise RuntimeError("native action service already started")
        self._server = await asyncio.start_server(self._handle,
                                                   host="127.0.0.1", port=0,
                                                   limit=_MAX_RECORD_BYTES + 2)
        return self.port

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter) -> None:
        if self._active >= _MAX_ACTIVE_CONNECTIONS:
            writer.close()
            await writer.wait_closed()
            return
        self._active += 1
        try:
            line = await asyncio.wait_for(reader.readline(), _TIMEOUT_S)
            request = _decode_request(line)
            context = self._context_provider()
            if not isinstance(context, ExecutionContext):
                raise CoreError("EXECUTOR_OFFLINE", "native_action_ingress")
            result: Mapping[str, Any] = await asyncio.wait_for(
                self._bridge.invoke(request, context), _TIMEOUT_S)
            payload = canonical_json({"ok": True, "data": dict(result)})
        except CoreError as exc:
            payload = canonical_json({"ok": False, "code": exc.code,
                                      "possible_effect": exc.possible_effect,
                                      "retry_safe": exc.retry_safe})
        except (asyncio.TimeoutError, asyncio.IncompleteReadError,
                ValueError, TypeError, RuntimeError):
            payload = canonical_json({"ok": False, "code": "OUTCOME_UNKNOWN"})
        except Exception:
            # The backend may have committed before an unexpected failure.
            payload = canonical_json({"ok": False, "code": "OUTCOME_UNKNOWN"})
        try:
            if len(payload) > _MAX_RECORD_BYTES:
                payload = canonical_json({"ok": False, "code": "OUTCOME_UNKNOWN"})
            writer.write(payload + b"\n")
            await asyncio.wait_for(writer.drain(), _TIMEOUT_S)
        except (ConnectionError, asyncio.TimeoutError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self._active -= 1

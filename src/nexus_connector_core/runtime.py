"""Host-neutral asynchronous runtime orchestration.

Native implementations are injected; this module owns admission, namespace
fencing, durable receipts and event replay, not application authorization.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from .discovery import discover_path
from .clock import RollbackFencedClock, SystemClock
from .journal import (SQLiteJournal, validate_claim_namespace,
                      validate_claim_page, validate_compaction_rows)
from .kernel import OperationKernel
from .models import (
    CloseOperation, ControlOperation, CoreError, DiscoveryRequest, EventCursor,
    EffectNotSent, ExecutionContext, InstallationCandidate, Inventory, LaunchIntent,
    OpenOperation, Operation, OperationKey, OperationReceipt, NativeApprovalOperation,
    PreparedLaunch,
    ReconcileReport, ReconcileRequest, RuntimeEvent, RuntimeSnapshot,
    SessionKey, ShutdownPolicy, ShutdownReport, TurnOperation,
    StorageStatus, SessionClaimPage, ProcessBirthRecord,
    ProcessBirthObservation,
)
from .profiles import prepare_launch, verify_prepared
from .protocol import intent_hash
from .protocol import canonical_json
from .ports import Clock, OwnedSlotLedger


def _finite_timing(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


_NATIVE_DECISION_MAX_BYTES = 16 * 1024
_NATIVE_DECISION_MAX_DEPTH = 64


def _preflight_native_json(value: object) -> None:
    """Reject oversized/deep JSON trees before canonicalization copies them."""
    stack = [(value, 0)]
    lower_bound = 0
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if depth > _NATIVE_DECISION_MAX_DEPTH or nodes > _NATIVE_DECISION_MAX_BYTES:
            raise ValueError("native decision JSON tree exceeds limit")
        if type(item) is dict:
            if len(item) > _NATIVE_DECISION_MAX_BYTES:
                raise ValueError("native decision object exceeds limit")
            for key, child in item.items():
                if type(key) is not str:
                    raise TypeError("native decision JSON keys must be strings")
                lower_bound += len(key) + 1
                stack.append((child, depth + 1))
        elif type(item) is list:
            if len(item) > _NATIVE_DECISION_MAX_BYTES:
                raise ValueError("native decision array exceeds limit")
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            lower_bound += len(item)
        elif type(item) is int:
            lower_bound += max(0, (item.bit_length() - 1) // 4)
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("native decision JSON number must be finite")
        elif item is None or type(item) is bool:
            pass
        else:
            raise TypeError("native decision value is not JSON")
        if lower_bound + nodes > _NATIVE_DECISION_MAX_BYTES:
            raise ValueError("native decision JSON tree exceeds limit")


class NativeSession(Protocol):
    """One owned native session; no canonical application state or MCP path."""

    native_id: str

    async def send(self, verb: str, payload: Mapping[str, str],
                   operation_id: str, *,
                   expected_turn_id: str | None = None) -> None: ...
    def events(self) -> AsyncIterator[RuntimeEvent]: ...
    async def close(self) -> str: ...
    async def observe(self) -> tuple[str, str]: ...
    async def reply_native_approval(
            self, request: Mapping[str, object], decision: str,
            operator_response: Mapping[str, object] | None) -> None: ...


class NativeFactory(Protocol):
    async def open(self, prepared: PreparedLaunch, session_id: str,
                   context: ExecutionContext, *,
                   stream_epoch: str) -> NativeSession: ...


@dataclass(slots=True)
class _Session:
    native: NativeSession
    context: ExecutionContext
    epoch: str
    adapter_id: str
    opening_operation_id: str | None = None
    slot_reserved: bool = False
    pump: asyncio.Task[None] | None = None
    pump_started: asyncio.Event = field(default_factory=asyncio.Event)
    sink_task: asyncio.Task[None] | None = None
    sink_sequence: int = 0
    sink_pending: bool = False
    lease_task: asyncio.Task[None] | None = None
    shutdown_task: asyncio.Task[str] | None = None
    force_task: asyncio.Task[None] | None = None
    force_started: asyncio.Event = field(default_factory=asyncio.Event)
    force_requested: bool = False
    closing: bool = False
    closed: bool = False
    faulted: bool = False
    lease_expired: bool = False
    revoked: bool = False
    normal_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    control_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Populated only after the native request event is durable. Session
    # ownership is process-local, so this index is not a restart authority.
    pending_native_requests: dict[str, bytes] = field(default_factory=dict)


class LocalRuntimeCore:
    """One installation's runtime kernel.

    The trusted host supplies selected binaries, local roots and a native
    factory. No Server-side path or caller-provided agent hint is authority.
    Session handles are intentionally process-local; after restart, known
    operation receipts remain queryable but process ownership is UNKNOWN.
    """

    def __init__(self, journal: SQLiteJournal, native_factory: NativeFactory,
                 *, candidates: Mapping[str, InstallationCandidate],
                 workspace_roots: Mapping[str, str],
                 owned_slot_ledger: OwnedSlotLedger | None = None,
                 trusted_discovery_roots: tuple[str, ...] = (),
                 event_sink: Callable[[RuntimeEvent], Awaitable[None]] | None = None,
                 clock: Clock | None = None,
                 lease_grace_seconds: float = 15.0,
                 lease_poll_seconds: float = 0.25,
                 max_lease_seconds: float = 120.0,
                 reconnect_fence_seconds: float = 5.0,
                 max_concurrent_opens: int = 8,
                 max_owned_sessions: int = 8):
        if any(not _finite_timing(value)
               for value in (lease_grace_seconds, lease_poll_seconds,
                             max_lease_seconds, reconnect_fence_seconds)):
            raise ValueError("invalid lease timing")
        if (lease_grace_seconds < 0 or lease_poll_seconds <= 0 or
                max_lease_seconds <= 0 or reconnect_fence_seconds <= 0):
            raise ValueError("invalid lease timing")
        if not _finite_timing(max_lease_seconds + lease_grace_seconds):
            raise ValueError("invalid lease timing")
        if (not isinstance(max_concurrent_opens, int) or
                isinstance(max_concurrent_opens, bool) or
                max_concurrent_opens <= 0):
            raise ValueError("max_concurrent_opens must be a positive integer")
        if (not isinstance(max_owned_sessions, int) or
                isinstance(max_owned_sessions, bool) or
                max_owned_sessions <= 0):
            raise ValueError("max_owned_sessions must be a positive integer")
        self._journal = journal
        self._owned_slots = owned_slot_ledger or journal
        self._clock = RollbackFencedClock(clock or SystemClock())
        self._kernel = OperationKernel(journal, self._clock)
        self._lease_grace_seconds = lease_grace_seconds
        self._lease_poll_seconds = lease_poll_seconds
        self._max_lease_seconds = max_lease_seconds
        self._reconnect_fence_seconds = reconnect_fence_seconds
        self._max_concurrent_opens = max_concurrent_opens
        self._max_owned_sessions = max_owned_sessions
        self._native_factory = native_factory
        self._candidates = dict(candidates)
        self._workspace_roots = dict(workspace_roots)
        self._trusted_discovery_roots = tuple(Path(root)
                                              for root in trusted_discovery_roots)
        self._event_sink = event_sink
        self._sessions: dict[SessionKey, _Session] = {}
        self._opening: dict[SessionKey, asyncio.Event] = {}
        self._uncertain_opens: set[SessionKey] = set()
        self._lock = asyncio.Lock()
        self._event_changed = asyncio.Condition()
        self._shutting_down = False
        self._shutdown_policy = ShutdownPolicy()

    async def discover(self, request: DiscoveryRequest) -> Inventory:
        candidates = []
        for adapter_id in request.adapter_ids:
            candidates.extend(await asyncio.to_thread(
                discover_path, adapter_id,
                trusted_roots=self._trusted_discovery_roots))
        return Inventory(tuple(candidates))

    async def prepare(self, intent: LaunchIntent,
                      context: ExecutionContext) -> PreparedLaunch:
        self._authorize(context, "runtime.open")
        if (intent.agent_id != context.agent_id or
                intent.workspace_id != context.workspace_id):
            raise CoreError("BINDING_NOT_AUTHORIZED", "prepare")
        candidate = self._candidates.get(intent.adapter_id)
        root = self._workspace_roots.get(intent.workspace_id)
        if candidate is None:
            raise CoreError("BINARY_NOT_FOUND", "prepare")
        if root is None:
            raise CoreError("WORKSPACE_UNAVAILABLE", "prepare")
        return await asyncio.to_thread(prepare_launch, intent, candidate, root)

    async def open(self, operation: OpenOperation,
                   context: ExecutionContext) -> OperationReceipt:
        self._external_operation_id(operation.operation_id)
        self._authorize(context, "runtime.open")
        self._validate_lease_window(context)
        if not operation.stream_epoch or not operation.session_id:
            raise CoreError("VALIDATION_ERROR", "open")
        prepared = operation.prepared
        if (prepared.intent.agent_id != context.agent_id or
                prepared.intent.workspace_id != context.workspace_id):
            raise CoreError("BINDING_NOT_AUTHORIZED", "open")
        semantic = Operation(operation.operation_id, operation.session_id,
                             "runtime.open", {
                                 "adapter_id": prepared.intent.adapter_id,
                                 "profile_fingerprint": prepared.profile_fingerprint,
                                 "root_fingerprint": prepared.root_fingerprint,
                                 "stream_epoch": operation.stream_epoch,
                             })
        session_key = SessionKey(context.server_id, context.executor_id,
                                 operation.session_id)
        async with self._lock:
            old = await self._existing(semantic, context)
            if old is not None:
                return old
            if (self._shutting_down or session_key in self._sessions or
                    session_key in self._opening or
                    session_key in self._uncertain_opens):
                raise CoreError("SESSION_CONFLICT", "open")
            selected = self._candidates.get(prepared.intent.adapter_id)
            root = self._workspace_roots.get(prepared.intent.workspace_id)
            if selected is None or root is None:
                raise CoreError("PROFILE_DRIFT", "open")
            if len(self._opening) >= self._max_concurrent_opens:
                raise CoreError("CAPACITY_EXCEEDED", "open", retry_safe=True,
                                operation_id=operation.operation_id)
            # An in-flight open reserves one possible process slot. After it
            # registers a binding, the binding takes over that slot. Unknown
            # native opens without a handle stay reserved until host recovery.
            occupied = (len(self._opening) + len(self._uncertain_opens) +
                        sum(not binding.closed and key not in self._opening
                            for key, binding in self._sessions.items()))
            if occupied >= self._max_owned_sessions:
                raise CoreError("CAPACITY_EXCEEDED", "open", retry_safe=True,
                                operation_id=operation.operation_id)
            finished = asyncio.Event()
            self._opening[session_key] = finished
        effect_started = False
        binding_registered = False
        try:
            refreshed = await asyncio.to_thread(prepare_launch,
                                                prepared.intent, selected, root)
            if prepared != refreshed:
                raise CoreError("PROFILE_DRIFT", "open")
            await asyncio.to_thread(verify_prepared, prepared)

            async def effect() -> str:
                nonlocal effect_started, binding_registered
                async with self._lock:
                    if self._shutting_down:
                        raise EffectNotSent("runtime is draining",
                                            code="RUNTIME_DRAINING")
                effect_started = True
                slot_reserved = False
                if prepared.intent.mode == "managed":
                    opening_key = OperationKey(
                        context.server_id, context.executor_id,
                        operation.operation_id)
                    try:
                        await self._owned_slots.reserve_owned_slot(
                            opening_key, operation.session_id)
                    except CoreError as exc:
                        if ((exc.code in {"CAPACITY_EXCEEDED", "JOURNAL_FULL"}
                             and exc.retry_safe) or
                                exc.code == "PROFILE_DRIFT"):
                            effect_started = False
                            raise EffectNotSent(
                                "owned slot unavailable before native launch",
                                code=exc.code) from exc
                        raise
                    slot_reserved = True
                try:
                    native = await self._native_factory.open(
                        prepared, operation.session_id, context,
                        stream_epoch=operation.stream_epoch)
                except EffectNotSent:
                    if slot_reserved:
                        await self._owned_slots.release_owned_slot(
                            opening_key, operation.session_id)
                    effect_started = False
                    raise
                except CoreError as exc:
                    if exc.retry_safe and not exc.possible_effect:
                        if slot_reserved:
                            await self._owned_slots.release_owned_slot(
                                opening_key, operation.session_id)
                        effect_started = False
                    raise
                binding = _Session(native, context, operation.stream_epoch,
                                   prepared.intent.adapter_id,
                                   operation.operation_id, slot_reserved)
                async with self._lock:
                    self._sessions[session_key] = binding
                    binding_registered = True
                    binding.pump = asyncio.create_task(
                        self._pump(session_key, binding))
                    binding.lease_task = asyncio.create_task(
                        self._watch_lease(session_key, binding))
                birth_reader = getattr(native, "owned_process_birth", None)
                if birth_reader is not None:
                    evidence = await asyncio.to_thread(birth_reader)
                    if evidence is not None:
                        await self._journal.record_process_birth(
                            OperationKey(context.server_id, context.executor_id,
                                         operation.operation_id),
                            operation.session_id, evidence)
                # Do not publish a successful open before its event consumer
                # has entered the native iterator. Copied adapters start pipe
                # reader threads in start(); this barrier covers the Core pump.
                await binding.pump_started.wait()
                if binding.faulted:
                    raise CoreError("EVENT_STREAM_UNAVAILABLE", "open",
                                    possible_effect=True,
                                    operation_id=operation.operation_id)
                return native.native_id

            return await self._kernel.execute(semantic, context, effect)
        finally:
            async with self._lock:
                self._opening.pop(session_key, None)
                if effect_started and not binding_registered:
                    self._uncertain_opens.add(session_key)
                if self._shutting_down and (binding := self._sessions.get(session_key)):
                    if binding.shutdown_task is None or binding.shutdown_task.done():
                        binding.shutdown_task = asyncio.create_task(
                            self._shutdown_session(session_key, binding,
                                                   self._shutdown_policy))
                        self._schedule_force(session_key, binding,
                                             asyncio.get_running_loop().time() +
                                             self._shutdown_policy.drain_seconds +
                                             self._shutdown_policy.interrupt_seconds)
                finished.set()

    async def submit(self, operation: TurnOperation,
                     context: ExecutionContext) -> OperationReceipt:
        self._external_operation_id(operation.operation_id)
        if not operation.text or len(operation.text.encode("utf-8")) > 1024 * 1024:
            raise CoreError("VALIDATION_ERROR", "submit")
        semantic = Operation(operation.operation_id, operation.session_id,
                             "turn.submit", {"text": operation.text},
                             operation.expected_turn_id)
        return await self._send(semantic, context, "send_turn",
                                {"text": operation.text})

    async def control(self, operation: ControlOperation,
                      context: ExecutionContext) -> OperationReceipt:
        self._external_operation_id(operation.operation_id)
        if operation.verb == "interrupt" and operation.text is None:
            semantic = Operation(operation.operation_id, operation.session_id,
                                 "turn.interrupt", {}, operation.expected_turn_id)
            return await self._send(semantic, context, "interrupt", {})
        if operation.verb != "steer" or not operation.text or not operation.expected_turn_id:
            raise CoreError("CAPABILITY_UNSUPPORTED", "control")
        if len(operation.text.encode("utf-8")) > 1024 * 1024:
            raise CoreError("VALIDATION_ERROR", "control")
        semantic = Operation(operation.operation_id, operation.session_id,
                             "turn.steer", {"text": operation.text},
                             operation.expected_turn_id)
        return await self._send(semantic, context, "steer", {"text": operation.text})

    async def decide_native_approval(
            self, operation: NativeApprovalOperation,
            context: ExecutionContext) -> OperationReceipt:
        """Journal an authorized reply to one still-pending native request."""
        from .native.native_inputs import INPUT_METHODS

        if not isinstance(operation, NativeApprovalOperation):
            raise CoreError("VALIDATION_ERROR", "approval_decide")
        self._external_operation_id(operation.operation_id)
        request = operation.request
        if not isinstance(request, Mapping):
            raise CoreError("VALIDATION_ERROR", "approval_decide")
        request_id = request.get("request_id")
        request_hash = request.get("request_hash")
        method = request.get("method")
        params = request.get("params")
        if (not ((type(request_id) is str and 1 <= len(request_id) <= 256) or
                 (type(request_id) is int and 0 <= request_id <= 9223372036854775807)) or
                type(request_hash) is not str or len(request_hash) != 64 or
                any(char not in "0123456789abcdef" for char in request_hash) or
                type(method) is not str or not isinstance(params, dict) or
                type(operation.decision) is not str or
                operation.decision not in {"accept", "decline", "cancel"}):
            raise CoreError("VALIDATION_ERROR", "approval_decide")
        if method in INPUT_METHODS:
            action = "input.provide"
            if (type(params.get("turnId")) is not str or
                    not params["turnId"]):
                raise CoreError("VALIDATION_ERROR", "approval_decide")
        elif method in {"item/commandExecution/requestApproval",
                        "item/fileChange/requestApproval"}:
            action = "approval.decide"
            if (type(params.get("turnId")) is not str or
                    not params["turnId"]):
                raise CoreError("VALIDATION_ERROR", "approval_decide")
        elif method == "control_request:can_use_tool":
            tool_name = params.get("tool_name")
            if (type(tool_name) is not str or
                    tool_name not in {"Write", "Edit", "Bash", "AskUserQuestion"}):
                raise CoreError("CAPABILITY_UNSUPPORTED", "approval_decide")
            action = ("input.provide" if tool_name == "AskUserQuestion"
                      else "approval.decide")
            generation = request.get("local_generation")
            if type(generation) is not int or generation < 0:
                raise CoreError("VALIDATION_ERROR", "approval_decide")
        else:
            raise CoreError("CAPABILITY_UNSUPPORTED", "approval_decide")
        if (action == "input.provide" and operation.decision == "accept" and
                operation.operator_response is None):
            raise CoreError("VALIDATION_ERROR", "approval_decide")
        if (operation.operator_response is not None and
                not isinstance(operation.operator_response, Mapping)):
            raise CoreError("VALIDATION_ERROR", "approval_decide")
        projected = {"request_id": request_id, "request_hash": request_hash,
                     "method": method, "params": params}
        if method == "control_request:can_use_tool":
            projected["local_generation"] = request["local_generation"]
        self._authorize(context, action)
        try:
            _preflight_native_json(projected)
            if operation.operator_response is not None:
                _preflight_native_json(operation.operator_response)
            encoded_request = canonical_json(projected)
            encoded_response = (canonical_json(dict(operation.operator_response))
                                if operation.operator_response is not None else None)
            if (len(encoded_request) > _NATIVE_DECISION_MAX_BYTES or
                    (encoded_response is not None and
                     len(encoded_response) > _NATIVE_DECISION_MAX_BYTES)):
                raise ValueError("native approval payload too large")
            frozen_request = json.loads(encoded_request)
            frozen_response = (json.loads(encoded_response)
                               if encoded_response is not None else None)
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise CoreError("VALIDATION_ERROR", "approval_decide") from exc
        semantic = Operation(
            operation.operation_id, operation.session_id, action,
            {"request_id": request_id, "request_hash": request_hash,
             "method": method, "decision": operation.decision,
             "response_sha256": (hashlib.sha256(encoded_response).hexdigest()
                                 if encoded_response is not None else None)})
        request_key = json.dumps(request_id)
        async with self._lock:
            old = await self._existing(semantic, context)
            if old is not None:
                return old
            binding = self._session(operation.session_id, context,
                                    require_live_lease=True)
        async with binding.control_lock:
            async with self._lock:
                old = await self._existing(semantic, context)
                if old is not None:
                    return old
                binding = self._session(operation.session_id, context,
                                        require_live_lease=True)
                if (self._shutting_down or binding.closed or binding.closing or
                        binding.faulted):
                    raise CoreError("SESSION_CLOSING", "approval_decide")
                if action not in binding.context.allowed_actions:
                    raise CoreError("BINDING_NOT_AUTHORIZED", "approval_decide")
                if binding.adapter_id not in {"codex_app_server", "claude_stream"}:
                    raise CoreError("CAPABILITY_UNSUPPORTED", "approval_decide")
                reply = getattr(binding.native, "reply_native_approval", None)
                if not callable(reply):
                    raise CoreError("CAPABILITY_UNSUPPORTED", "approval_decide")
                if binding.pending_native_requests.get(request_key) != encoded_request:
                    raise CoreError("NATIVE_REQUEST_NOT_OBSERVED", "approval_decide",
                                    retry_safe=True)

            async def effect() -> None:
                try:
                    await reply(frozen_request, operation.decision,
                                frozen_response)
                except EffectNotSent:
                    # A proven pre-write refusal may be retried with a new
                    # answer while the original request is still pending.
                    raise
                except BaseException:
                    binding.pending_native_requests.pop(request_key, None)
                    raise
                binding.pending_native_requests.pop(request_key, None)

            return await self._kernel.execute(semantic, context, effect)

    async def _send(self, semantic: Operation, context: ExecutionContext,
                    verb: str, payload: Mapping[str, str]) -> OperationReceipt:
        self._authorize(context, semantic.action)
        async with self._lock:
            old = await self._existing(semantic, context)
            if old is not None:
                return old
            binding = self._session(semantic.session_id, context,
                                    require_live_lease=semantic.action == "turn.submit")
        # A slow normal write must not hold the runtime-wide state lock: an
        # interrupt/steer may need to reach that same native session urgently.
        # Separate session locks let controls overlap normal sends, while
        # close/shutdown acquire both before releasing ownership.
        command_lock = (binding.normal_lock if verb == "send_turn"
                        else binding.control_lock)
        async with command_lock:
            async with self._lock:
                old = await self._existing(semantic, context)
                if old is not None:
                    return old
                binding = self._session(
                    semantic.session_id, context,
                    require_live_lease=semantic.action == "turn.submit")
                if self._shutting_down:
                    raise CoreError("RUNTIME_DRAINING", "admission")
                if binding.closed:
                    raise CoreError("SESSION_CLOSED", "admission")
                if binding.closing:
                    raise CoreError("SESSION_CLOSING", "admission")
                if binding.faulted:
                    raise CoreError("EVENT_STREAM_UNAVAILABLE", "admission")
                if verb == "steer" and binding.adapter_id != "codex_app_server":
                    raise CoreError("CAPABILITY_UNSUPPORTED", "control")
                if semantic.action not in binding.context.allowed_actions:
                    raise CoreError("BINDING_NOT_AUTHORIZED", "admission")

            async def effect() -> None:
                await binding.native.send(
                    verb, payload, semantic.operation_id,
                    expected_turn_id=semantic.expected_turn_id)
                return None

            return await self._kernel.execute(semantic, context, effect)

    async def close(self, operation: CloseOperation,
                    context: ExecutionContext) -> OperationReceipt:
        self._external_operation_id(operation.operation_id)
        semantic = Operation(operation.operation_id, operation.session_id,
                             "runtime.close")
        self._authorize(context, semantic.action)
        async with self._lock:
            old = await self._existing(semantic, context)
            if old is not None:
                return old
            binding = self._session(operation.session_id, context)
        async with binding.normal_lock:
            async with binding.control_lock:
                async with self._lock:
                    old = await self._existing(semantic, context)
                    if old is not None:
                        return old
                    binding = self._session(operation.session_id, context)

                async def effect() -> None:
                    async with self._lock:
                        binding.closing = True
                    outcome = await self._close_owned(
                        SessionKey(context.server_id, context.executor_id,
                                   operation.session_id), binding)
                    if outcome == "unknown":
                        raise CoreError("OUTCOME_UNKNOWN", "close",
                                        possible_effect=True,
                                        operation_id=operation.operation_id)
                    return None

                return await self._kernel.execute(semantic, context, effect)

    async def events(self, cursor: EventCursor) -> AsyncIterator[RuntimeEvent]:
        if cursor.after_sequence < 0:
            raise CoreError("EVENT_INVALID", "events")
        position = cursor.after_sequence
        while True:
            received = False
            async for event in self._journal.events(
                EventCursor(cursor.server_id, cursor.executor_id,
                            cursor.session_id, cursor.stream_epoch, position)):
                received = True
                position = event.sequence
                yield event
            if self._shutting_down:
                return
            if received:
                continue
            async with self._event_changed:
                try:
                    await asyncio.wait_for(self._event_changed.wait(), timeout=0.5)
                except TimeoutError:
                    pass

    async def acknowledge_events(self, cursor: EventCursor,
                                 through_sequence: int) -> int:
        """Called by the trusted host only after Server durable-ingress ACK."""
        return await self._journal.acknowledge_events(cursor, through_sequence)

    async def compact_events(self, *, max_rows: int = 128) -> tuple[int, int]:
        validate_compaction_rows(max_rows)
        return await self._journal.compact_acked(max_rows=max_rows)

    async def storage_status(self) -> StorageStatus:
        return await self._journal.storage_status()

    async def checkpoint_wal(self) -> tuple[int, int, int]:
        return await self._journal.checkpoint_wal()

    async def inspect(self, session: SessionKey) -> RuntimeSnapshot:
        binding = self._sessions.get(session)
        if binding is None:
            return RuntimeSnapshot(session.session_id, "UNKNOWN", "UNKNOWN", "unknown", 0)
        try:
            process_state, turn_state = await binding.native.observe()
        except Exception:
            process_state, turn_state = "UNKNOWN", "UNKNOWN"
        if binding.faulted:
            turn_state = "UNKNOWN"
        cursor = EventCursor(binding.context.server_id, binding.context.executor_id,
                             session.session_id, binding.epoch)
        sequence = await self._journal.contiguous_watermark(cursor)
        lease_state = ("CLOSED" if binding.closed else "REVOKED" if binding.revoked
                       else "EXPIRED" if
                       self._clock.monotonic() >= binding.context.lease_deadline_monotonic
                       else "ACTIVE")
        return RuntimeSnapshot(session.session_id, process_state, turn_state,
                               "owned" if not binding.closed else "released", sequence,
                               lease_state, binding.context.connection_generation,
                               binding.context.session_owner_generation)

    async def claimed_sessions(
            self, server_id: str, executor_id: str, *, after_rowid: int = 0,
            high_water_rowid: int | None = None,
            limit: int = 128) -> SessionClaimPage:
        validate_claim_page(after_rowid, high_water_rowid, limit)
        validate_claim_namespace(server_id, executor_id)
        return await self._journal.claimed_sessions(
            server_id, executor_id, after_rowid=after_rowid,
            high_water_rowid=high_water_rowid, limit=limit)

    async def process_birth(self, session: SessionKey) -> ProcessBirthRecord | None:
        """Return historical birth evidence, never live ownership authority."""
        if not isinstance(session, SessionKey):
            raise ValueError("invalid process birth session")
        validate_claim_namespace(session.server_id, session.executor_id)
        if type(session.session_id) is not str or not session.session_id:
            raise ValueError("invalid process birth session")
        return await self._journal.get_process_birth(session)

    async def observe_process_birth(
            self, session: SessionKey) -> ProcessBirthObservation:
        """Compare one historical birth to a read-only OS PID observation."""
        record = await self.process_birth(session)
        if record is None:
            return ProcessBirthObservation(None, "UNRECORDED")
        from .native.process import observe_recorded_process_birth
        state = await asyncio.to_thread(observe_recorded_process_birth,
                                        record.evidence)
        return ProcessBirthObservation(record, state)

    async def reconcile(self, request: ReconcileRequest) -> ReconcileReport:
        if not isinstance(request, ReconcileRequest):
            raise ValueError("invalid reconcile request")
        identifiers = (request.server_id, request.executor_id)
        if any(type(value) is not str or not 1 <= len(value) <= 160
               for value in identifiers):
            raise ValueError("invalid reconcile namespace")
        for ids in (request.operation_ids, request.session_ids):
            if (type(ids) is not tuple or len(ids) > 256 or
                    any(type(value) is not str or not 1 <= len(value) <= 160
                        for value in ids) or len(set(ids)) != len(ids)):
                raise ValueError("invalid reconcile identifiers")
        receipts = tuple([await self._journal.get_receipt(OperationKey(
            request.server_id, request.executor_id, operation_id))
                          for operation_id in request.operation_ids])
        snapshots = tuple([await self.inspect(SessionKey(
            request.server_id, request.executor_id, session_id))
                           for session_id in request.session_ids])
        return ReconcileReport(receipts, snapshots)

    async def shutdown(self, policy: ShutdownPolicy) -> ShutdownReport:
        if not isinstance(policy, ShutdownPolicy) or any(
                not _finite_timing(value) or value < 0
                for value in (policy.drain_seconds,
                              policy.interrupt_seconds)):
            raise CoreError("VALIDATION_ERROR", "shutdown")
        loop = asyncio.get_running_loop()
        total_seconds = policy.drain_seconds + policy.interrupt_seconds
        if not _finite_timing(total_seconds):
            raise CoreError("VALIDATION_ERROR", "shutdown")
        deadline = loop.time() + total_seconds
        if not _finite_timing(deadline):
            raise CoreError("VALIDATION_ERROR", "shutdown")
        async with self._lock:
            self._shutting_down = True
            self._shutdown_policy = policy
            opening = tuple(self._opening.values())
        async with self._event_changed:
            self._event_changed.notify_all()
        if opening:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(finished.wait() for finished in opening)),
                    timeout=max(0.0, deadline - loop.time()))
            except TimeoutError:
                pass
        async with self._lock:
            sessions = tuple(self._sessions.items())
            uncertain = tuple(self._uncertain_opens)
            still_opening = tuple(self._opening)
        outcomes: dict[SessionKey, str] = {key: "unknown" for key in uncertain}
        outcomes.update({key: "unknown" for key in still_opening})
        closing: dict[SessionKey, asyncio.Task[str]] = {}
        for session_key, binding in sessions:
            if binding.shutdown_task is None or binding.shutdown_task.done():
                binding.shutdown_task = asyncio.create_task(
                    self._shutdown_session(session_key, binding, policy))
            self._schedule_force(session_key, binding, deadline)
            closing[session_key] = binding.shutdown_task
        if closing:
            # Waiting for a native thread is not proof that it stopped. Keep
            # unresolved tasks and their owned slots after the observation
            # budget expires; a later shutdown may await the same task.
            await asyncio.wait(tuple(closing.values()), timeout=max(
                0.0, deadline - loop.time()))
            for session_key, task in closing.items():
                outcomes[session_key] = task.result() if task.done() else "unknown"
            dispatching = []
            for session_key, binding in sessions:
                if (outcomes[session_key] == "unknown" and not binding.closed and
                        binding.force_task is not None):
                    self._schedule_force(session_key, binding, loop.time(),
                                         immediate=True)
                    dispatching.append(binding.force_started.wait())
            if dispatching:
                # Give an independent owned-tree force request one loop turn
                # to start before the host can dispose of this event loop.
                try:
                    await asyncio.wait_for(asyncio.gather(*dispatching),
                                           timeout=0.1)
                except TimeoutError:
                    pass
        return ShutdownReport(outcomes)

    def _schedule_force(self, session: SessionKey, binding: _Session,
                        deadline: float,
                        *, immediate: bool = False) -> None:
        # Attach is somebody else's process. Only a Core-owned managed backend
        # may expose this independent containment primitive.
        if (binding.adapter_id == "claude_attach" or binding.force_requested or
                not callable(getattr(binding.native, "force_stop", None))):
            return
        if (immediate and binding.force_task is not None and
                not binding.force_task.done()):
            binding.force_task.cancel()
            binding.force_task = None
        if binding.force_task is None or binding.force_task.done():
            binding.force_started = asyncio.Event()
            binding.force_task = asyncio.create_task(
                self._force_after_deadline(session, binding, deadline,
                                           binding.force_started))

    async def _force_after_deadline(self, session: SessionKey,
                                    binding: _Session,
                                    deadline: float,
                                    started: asyncio.Event) -> None:
        try:
            await asyncio.sleep(max(0.0, deadline -
                                    asyncio.get_running_loop().time()))
            if binding.closed:
                return
            force_stop = getattr(binding.native, "force_stop", None)
            if not callable(force_stop):
                return
            identity = [session.server_id, session.executor_id,
                        session.session_id, binding.epoch,
                        binding.context.session_owner_generation]
            operation_id = "core.internal.shutdown_force." + hashlib.sha256(
                canonical_json(identity)).hexdigest()
            operation = Operation(operation_id, session.session_id,
                                  "runtime.shutdown_force",
                                  {"stream_epoch": binding.epoch})
            key = OperationKey(session.server_id, session.executor_id,
                               operation_id)
            digest = intent_hash(operation, binding.context)
            admitted = False
            try:
                _, admitted = await self._journal.admit(
                    key, digest, session.session_id, critical=True,
                    effect_imminent=True)
            except Exception:
                # Disk pressure cannot be allowed to defeat containment.
                binding.faulted = True
            binding.force_requested = True
            started.set()
            try:
                await force_stop()
            except BaseException:
                if admitted:
                    await self._journal.record_receipt(key, OperationReceipt(
                        operation_id, digest, "OUTCOME_UNKNOWN", True, False,
                        session.session_id, error_code="OUTCOME_UNKNOWN"))
                return
            if admitted:
                await self._journal.record_receipt(key, OperationReceipt(
                    operation_id, digest, "SUBMITTED", True, False,
                    session.session_id))
        except BaseException:
            # Neither an attempted force nor an exception proves tree stop.
            # The normal shutdown task retains the effect slot and observes
            # termination only after any in-flight native calls settle.
            return
        finally:
            started.set()

    @staticmethod
    def _active_turn(binding: _Session) -> bool:
        probe = getattr(binding.native, "active_turn", None)
        if probe is None:
            return False
        try:
            return probe() is True
        except Exception:
            return False

    async def _wait_turn_drain(self, binding: _Session, deadline: float) -> None:
        loop = asyncio.get_running_loop()
        while binding.normal_lock.locked() or self._active_turn(binding):
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.01, remaining))

    async def _shutdown_interrupt(self, session: SessionKey,
                                  binding: _Session) -> bool:
        async with binding.control_lock:
            if binding.closed or binding.closing or not self._active_turn(binding):
                return False
            identity = [session.server_id, session.executor_id,
                        session.session_id, binding.epoch,
                        binding.context.session_owner_generation]
            operation_id = "core.internal.shutdown_interrupt." + hashlib.sha256(
                canonical_json(identity)).hexdigest()
            operation = Operation(operation_id, session.session_id,
                                  "runtime.shutdown_interrupt",
                                  {"stream_epoch": binding.epoch})
            key = OperationKey(session.server_id, session.executor_id,
                               operation_id)
            digest = intent_hash(operation, binding.context)
            try:
                old, fresh = await self._journal.admit(
                    key, digest, session.session_id, critical=True,
                    effect_imminent=True)
            except CoreError:
                return False
            if not fresh:
                return old.possible_effect
            try:
                await binding.native.send("interrupt", {}, operation_id)
            except EffectNotSent as exc:
                await self._journal.record_not_sent(key, exc.code)
                return False
            except BaseException:
                await self._journal.record_receipt(key, OperationReceipt(
                    operation_id, digest, "OUTCOME_UNKNOWN", True, False,
                    session.session_id, error_code="OUTCOME_UNKNOWN"))
                return True
            await self._journal.record_receipt(key, OperationReceipt(
                operation_id, digest, "SUBMITTED", True, False,
                session.session_id))
            return True

    async def _shutdown_session(self, session: SessionKey, binding: _Session,
                                policy: ShutdownPolicy) -> str:
        try:
            async with self._lock:
                if binding.closed:
                    return "already_closed"
                closing = binding.closing
            if not closing:
                loop = asyncio.get_running_loop()
                await self._wait_turn_drain(binding,
                                            loop.time() + policy.drain_seconds)
                if self._active_turn(binding):
                    interrupted = await self._shutdown_interrupt(session, binding)
                    if interrupted:
                        await self._wait_turn_drain(
                            binding, loop.time() + policy.interrupt_seconds)
            async with binding.normal_lock:
                async with binding.control_lock:
                    async with self._lock:
                        if binding.closed:
                            return "already_closed"
                        binding.closing = True
                    return await self._close_owned(session, binding)
        except BaseException:
            return "unknown"

    async def _close_owned(self, session: SessionKey, binding: _Session) -> str:
        reported = await binding.native.close()
        try:
            process_state, _ = await binding.native.observe()
        except Exception:
            process_state = "UNKNOWN"
        if process_state == "STOPPED":
            if binding.slot_reserved:
                await self._owned_slots.release_owned_slot(
                    OperationKey(session.server_id, session.executor_id,
                                 binding.opening_operation_id),
                    session.session_id)
                binding.slot_reserved = False
            binding.closed = True
            if binding.lease_task is not None and binding.lease_task is not asyncio.current_task():
                binding.lease_task.cancel()
            if binding.force_requested and reported != "forced":
                return "unknown"
            return reported if reported in {"graceful", "forced"} else "unknown"
        binding.faulted = True
        return "unknown"

    async def renew_lease(self, session: SessionKey, context: ExecutionContext,
                          *, expected_connection_generation: int) -> RuntimeSnapshot:
        """Host-authorized CAS after reconnect reconciliation or normal renewal."""
        async with self._lock:
            if self._shutting_down:
                raise CoreError("RUNTIME_DRAINING", "lease_renew")
            binding = self._sessions.get(session)
            if (binding is None or binding.closed or binding.closing or
                    binding.revoked):
                raise CoreError("SESSION_UNKNOWN", "lease_renew")
        # Both kinds of send hold a session lock through their native effect.
        # A new generation must not become active while an old effect is
        # pending. A stuck send leaves the old generation in place.
        try:
            async with asyncio.timeout(self._reconnect_fence_seconds):
                async with binding.normal_lock:
                    async with binding.control_lock:
                        async with self._lock:
                            if self._shutting_down:
                                raise CoreError("RUNTIME_DRAINING", "lease_renew")
                            if (self._sessions.get(session) is not binding or
                                    binding.closed or binding.closing or
                                    binding.revoked):
                                raise CoreError("SESSION_UNKNOWN", "lease_renew")
                            old = binding.context
                            if ((context.server_id, context.executor_id,
                                 context.binding_id, context.agent_id,
                                 context.workspace_id) !=
                                (old.server_id, old.executor_id,
                                 old.binding_id, old.agent_id,
                                 old.workspace_id)):
                                raise CoreError("BINDING_NOT_AUTHORIZED",
                                                "lease_renew")
                            self._validate_lease_window(context)
                            if (expected_connection_generation != old.connection_generation or
                                    context.connection_generation < old.connection_generation or
                                    context.session_owner_generation != old.session_owner_generation or
                                    context.authorization_revision < old.authorization_revision or
                                    context.configuration_revision < old.configuration_revision):
                                raise CoreError("STALE_GENERATION", "lease_renew")
                            if (context.lease_deadline_monotonic <= self._clock.monotonic() or
                                    context.lease_deadline_monotonic <= old.lease_deadline_monotonic):
                                raise CoreError("AGENT_REVOKED", "lease_renew")
                            if (not context.allowed_actions.issubset(old.allowed_actions) and
                                    context.authorization_revision == old.authorization_revision):
                                raise CoreError("BINDING_NOT_AUTHORIZED",
                                                "lease_renew")
                            binding.context = context
                            binding.lease_expired = False
        except TimeoutError as exc:
            raise CoreError("RECONNECT_BUSY", "lease_renew",
                            retry_safe=True) from exc
        snapshot = await self.inspect(session)
        await self._lease_event(session, binding, "core.lease_renewed", {})
        return snapshot

    async def revoke_lease(self, session: SessionKey, context: ExecutionContext,
                           *, expected_connection_generation: int) -> None:
        """Apply a host-verified revocation without granting another identity."""
        if session != SessionKey(context.server_id, context.executor_id,
                                 session.session_id):
            raise CoreError("BINDING_NOT_AUTHORIZED", "lease_revoke")
        async with self._lock:
            binding = self._session(session.session_id, context,
                                    require_live_lease=False,
                                    allow_newer_revision=True)
        # A successful revocation also fences effects already admitted by the
        # old context. On timeout, report non-application; the host must retry
        # or use shutdown rather than assuming the native channel is quiet.
        try:
            async with asyncio.timeout(self._reconnect_fence_seconds):
                async with binding.normal_lock:
                    async with binding.control_lock:
                        async with self._lock:
                            if self._sessions.get(session) is not binding:
                                raise CoreError("SESSION_UNKNOWN", "lease_revoke")
                            self._session(session.session_id, context,
                                          require_live_lease=False,
                                          allow_newer_revision=True)
                            old = binding.context
                            if (expected_connection_generation != old.connection_generation or
                                    context.session_owner_generation != old.session_owner_generation or
                                    context.authorization_revision <= old.authorization_revision or
                                    context.configuration_revision < old.configuration_revision):
                                raise CoreError("STALE_GENERATION", "lease_revoke")
                            binding.context = replace(
                                context,
                                lease_deadline_monotonic=self._clock.monotonic(),
                                allowed_actions=frozenset())
                            binding.lease_expired = True
                            binding.revoked = True
        except TimeoutError as exc:
            raise CoreError("REVOKE_BUSY", "lease_revoke",
                            retry_safe=True) from exc
        await self._lease_event(session, binding, "core.lease_revoked", {})

    async def _watch_lease(self, session: SessionKey, binding: _Session) -> None:
        try:
            while not binding.closed:
                deadline = binding.context.lease_deadline_monotonic
                now = self._clock.monotonic()
                if now < deadline:
                    await asyncio.sleep(min(deadline - now, self._lease_poll_seconds))
                    continue
                if not binding.lease_expired:
                    binding.lease_expired = True
                    await self._lease_event(session, binding, "core.lease_expired", {})
                if now < deadline + self._lease_grace_seconds:
                    await asyncio.sleep(min(deadline + self._lease_grace_seconds - now,
                                            self._lease_poll_seconds))
                    continue
                async with binding.normal_lock:
                    async with binding.control_lock:
                        async with self._lock:
                            if (binding.closed or
                                    self._clock.monotonic() <
                                    binding.context.lease_deadline_monotonic +
                                    self._lease_grace_seconds):
                                continue
                            binding.closing = True
                        try:
                            outcome = await self._close_expired(session, binding)
                        except Exception:
                            binding.faulted = True
                            outcome = "unknown"
                await self._lease_event(session, binding, "core.lease_closed",
                                        {"outcome": outcome})
                return
        except asyncio.CancelledError:
            return

    async def _close_expired(self, session: SessionKey,
                             binding: _Session) -> str:
        identity = [session.server_id, session.executor_id, session.session_id,
                    binding.epoch, binding.context.session_owner_generation]
        operation_id = "core.internal.lease_close." + hashlib.sha256(
            canonical_json(identity)).hexdigest()
        operation = Operation(operation_id, session.session_id,
                              "runtime.lease_close", {"stream_epoch": binding.epoch})
        key = OperationKey(session.server_id, session.executor_id, operation_id)
        digest = intent_hash(operation, binding.context)
        admitted = False
        try:
            _, fresh = await self._journal.admit(key, digest, session.session_id,
                                                 critical=True,
                                                 effect_imminent=True)
            if not fresh:
                binding.faulted = True
                return "unknown"
            admitted = True
        except CoreError as exc:
            if exc.code != "JOURNAL_FULL":
                raise
            # Disk saturation may prevent the intent record. Still attempt
            # containment rather than leave an owned process running forever.
            binding.faulted = True
        try:
            outcome = await self._close_owned(session, binding)
        except BaseException:
            if admitted:
                await self._journal.record_receipt(key, OperationReceipt(
                    operation_id, digest, "OUTCOME_UNKNOWN", True, False,
                    session.session_id, error_code="OUTCOME_UNKNOWN"))
            raise
        if admitted:
            await self._journal.record_receipt(key, OperationReceipt(
                operation_id, digest,
                "SUCCEEDED" if binding.closed else "OUTCOME_UNKNOWN",
                True, False, session.session_id,
                error_code=None if binding.closed else "OUTCOME_UNKNOWN"))
        return outcome

    async def _lease_event(self, session: SessionKey, binding: _Session,
                           native_type: str, payload: Mapping[str, str]) -> None:
        try:
            await self._journal.record_event(RuntimeEvent(
                session.server_id, session.executor_id, session.session_id,
                binding.epoch, 0, "lifecycle", native_type, payload))
            async with self._event_changed:
                self._event_changed.notify_all()
        except Exception:
            binding.faulted = True

    async def _pump(self, session: SessionKey, binding: _Session) -> None:
        try:
            binding.pump_started.set()
            async for event in binding.native.events():
                if (event.session_id != session.session_id or
                        event.server_id != session.server_id or
                        event.executor_id != session.executor_id or
                        event.stream_epoch != binding.epoch or event.sequence != 0):
                    raise CoreError("EVENT_SESSION_MISMATCH", "native_pump")
                await self._journal.record_event(event)
                request = event.payload.get("native_approval")
                if isinstance(request, dict):
                    request_id = request.get("request_id")
                    if (((type(request_id) is str and 1 <= len(request_id) <= 256) or
                         (type(request_id) is int and
                          0 <= request_id <= 9223372036854775807)) and
                            type(request.get("request_hash")) is str and
                            type(request.get("method")) is str and
                            isinstance(request.get("params"), dict)):
                        projected = {name: request.get(name) for name in
                                     ("request_id", "request_hash", "method", "params")}
                        if request.get("method") == "control_request:can_use_tool":
                            projected["local_generation"] = request.get("local_generation")
                        try:
                            encoded = canonical_json(projected)
                        except (TypeError, ValueError, OverflowError, RecursionError):
                            pass
                        else:
                            if len(encoded) <= 16384:
                                binding.pending_native_requests[json.dumps(request_id)] = encoded
                if (event.payload.get("delivery_phase") == "terminal" and
                        event.category == "turn_state"):
                    turn_id = event.payload.get("turn_id")
                    for key, encoded in tuple(binding.pending_native_requests.items()):
                        pending = json.loads(encoded)
                        if (binding.adapter_id == "claude_stream" or
                                pending["params"].get("turnId") == turn_id):
                            binding.pending_native_requests.pop(key, None)
                async with self._event_changed:
                    self._event_changed.notify_all()
                if self._event_sink is not None:
                    self._schedule_sink(session, binding)
        except Exception:
            # A dead stream does not prove process death or turn completion.
            # Keep ownership until explicit close/shutdown.
            binding.faulted = True
            try:
                await self._journal.record_event(RuntimeEvent(
                    session.server_id, session.executor_id,
                    session.session_id, binding.epoch, 0, "error", "core.event_pump_failed",
                    {"code": "EVENT_STREAM_UNAVAILABLE"}))
                async with self._event_changed:
                    self._event_changed.notify_all()
                if self._event_sink is not None:
                    self._schedule_sink(session, binding)
            except Exception:
                pass

    def _schedule_sink(self, session: SessionKey, binding: _Session) -> None:
        # The journal, not an in-memory queue, buffers a slow notification
        # consumer. One task/cursor per binding bounds transient memory while
        # the native pipe continues to drain independently.
        binding.sink_pending = True
        if binding.sink_task is None or binding.sink_task.done():
            binding.sink_task = asyncio.create_task(
                self._deliver_sink(session, binding))

    async def _deliver_sink(self, session: SessionKey,
                            binding: _Session) -> None:
        cursor = EventCursor(session.server_id, session.executor_id,
                             session.session_id, binding.epoch)
        while True:
            binding.sink_pending = False
            try:
                async for event in self._journal.events(replace(
                        cursor, after_sequence=binding.sink_sequence)):
                    # Advance only after the callback returns. On failure a
                    # later append retries from durable storage; hosts must
                    # explicitly replay, as notification is not guaranteed.
                    await self._event_sink(event)
                    binding.sink_sequence = event.sequence
            except Exception:
                # An append can race with a callback failure while this task
                # is still active. Spend that pending wake on one fresh replay
                # attempt; with no new append, do not spin on a broken sink.
                if binding.sink_pending:
                    continue
                return
            if not binding.sink_pending:
                return

    def _authorize(self, context: ExecutionContext, action: str) -> None:
        self._validate_lease_deadline(context)
        if (self._clock.monotonic() >= context.lease_deadline_monotonic and
                action not in {"turn.interrupt", "runtime.close"}):
            raise CoreError("AGENT_REVOKED", "admission", retry_safe=True)
        if action not in context.allowed_actions:
            raise CoreError("BINDING_NOT_AUTHORIZED", "admission", retry_safe=True)

    def _validate_lease_window(self, context: ExecutionContext) -> None:
        self._validate_lease_deadline(context)
        if (not _finite_timing(context.lease_deadline_monotonic +
                               self._lease_grace_seconds) or
                context.lease_deadline_monotonic - self._clock.monotonic() >
                self._max_lease_seconds):
            raise CoreError("LEASE_INVALID", "admission")

    @staticmethod
    def _validate_lease_deadline(context: ExecutionContext) -> None:
        deadline = context.lease_deadline_monotonic
        if not _finite_timing(deadline):
            raise CoreError("LEASE_INVALID", "admission")

    @staticmethod
    def _external_operation_id(operation_id: str) -> None:
        if (not operation_id or len(operation_id) > 256 or
                operation_id.startswith("core.internal.")):
            raise CoreError("OPERATION_INVALID", "admission")

    async def _existing(self, semantic: Operation,
                        context: ExecutionContext) -> OperationReceipt | None:
        old = await self._journal.get_receipt(OperationKey(
            context.server_id, context.executor_id, semantic.operation_id))
        if old is not None and old.intent_hash != intent_hash(semantic, context):
            raise CoreError("OPERATION_CONFLICT", "admission",
                            operation_id=semantic.operation_id)
        return old

    def _session(self, session_id: str, context: ExecutionContext, *,
                 require_live_lease: bool = False,
                 allow_newer_revision: bool = False) -> _Session:
        binding = self._sessions.get(SessionKey(context.server_id,
                                                context.executor_id, session_id))
        if binding is None:
            raise CoreError("SESSION_UNKNOWN", "admission")
        original = binding.context
        if ((context.server_id, context.executor_id, context.binding_id,
             context.agent_id, context.workspace_id) !=
            (original.server_id, original.executor_id, original.binding_id,
             original.agent_id, original.workspace_id)):
            raise CoreError("BINDING_NOT_AUTHORIZED", "admission")
        if (context.connection_generation != original.connection_generation or
                context.session_owner_generation != original.session_owner_generation):
            raise CoreError("STALE_GENERATION", "admission")
        if (context.authorization_revision != original.authorization_revision and
                not (allow_newer_revision and
                     context.authorization_revision > original.authorization_revision)):
            raise CoreError("AGENT_REVOKED", "admission")
        if (context.configuration_revision != original.configuration_revision and
                not allow_newer_revision):
            raise CoreError("PROFILE_DRIFT", "admission")
        if (require_live_lease and
                self._clock.monotonic() >= original.lease_deadline_monotonic):
            raise CoreError("AGENT_REVOKED", "admission")
        return binding

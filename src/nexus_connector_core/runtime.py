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

from .discovery import discover_path, discover_pi_releases
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
    StorageStatus, SessionClaimPage, SessionLeaseState, ProcessBirthRecord,
    ProcessBirthObservation,
)
from .profiles import prepare_launch, verify_prepared
from .protocol import intent_hash
from .protocol import canonical_json
from .ports import Journal, Clock, OwnedSlotLedger


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
    # C5/U04: scheduled-force coordination - the effective deadline is
    # the MINIMUM of every authorized request; a WAITING worker re-reads
    # it on wake and is never cancelled once physically DISPATCHING.
    force_deadline: float | None = None
    force_awake: asyncio.Event | None = None
    force_dispatched: bool = False
    closing: bool = False
    closed: bool = False
    faulted: bool = False
    effect_fence: object = field(default=None)
    lease_expired: bool = False
    revoked: bool = False
    # C3/S04: conservative in-memory marker while a lease CAS is in flight
    # on the journal worker (the caller may stop waiting; the durable
    # commit can still land and is applied by the late-commit callback).
    lease_cas_pending: bool = False
    # C6/V01: productive-grant barrier held while a lease update (most
    # critically a revocation) is RESERVED or in an UNKNOWN durable
    # state. Distinct from lease_cas_pending (which only fences another
    # CAS): this blocks NEW work grants - submits, steers, permissive
    # approvals/inputs - while the authorization itself is uncertain.
    # Containment (deny/interrupt/force/observe) stays available.
    lease_hold: bool = False
    # Monotonic token of the CURRENT lease-update attempt; finalizers and
    # late callbacks may only touch the attempt whose token still matches.
    lease_attempt_token: int = 0
    # C8/X01: the binding OBSERVED a newer durable fence (another
    # authorized writer advanced the lease): the local context is known
    # obsolete - productive grants are fenced (containment stays), and
    # only the host-authorized reconcile/reopen cycle can clear it.
    superseded: bool = False
    lease_reconcile_task: "asyncio.Task | None" = None
    eviction_scheduled: bool = False
    normal_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    control_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Populated only after the native request event is durable. Session
    # ownership is process-local, so this index is not a restart authority.
    pending_native_requests: dict[str, bytes] = field(default_factory=dict)


class _SessionTombstones:
    """Bounded lightweight history for evicted sessions (PC07).

    Never retains the native adapter or task closures; records only the
    durable ownership outcome observed at eviction time so ``inspect`` can
    distinguish a historically released session from a genuinely unknown
    one without inventing process state.
    """

    __slots__ = ("_entries", "_capacity")

    def __init__(self, capacity: int = 1024):
        if type(capacity) is not int or not 1 <= capacity <= 65536:
            raise ValueError("invalid tombstone capacity")
        self._entries: "dict[SessionKey, str]" = {}
        self._capacity = capacity

    def record(self, session: SessionKey, ownership: str) -> None:
        if len(self._entries) >= self._capacity and session not in self._entries:
            self._entries.pop(next(iter(self._entries)))
        self._entries[session] = ownership

    def get(self, session: SessionKey) -> "str | None":
        return self._entries.get(session)


class _ReleaseObligation:
    """Durable slot-release obligation after a proven stop (C8/X02).

    STOPPED is a physical fact; the ledger release is a separate
    durable fact. A refused/pre-commit-failed release keeps THIS
    lightweight record (no heavy adapter) so the next public lifecycle
    call retries the exact reservation until confirmation - never
    spawning or forcing an already-stopped resource again.
    """

    __slots__ = ("key", "session_id", "attempt", "retry_task")

    def __init__(self, key: "OperationKey", session_id: str,
                 attempt: "._OpeningAttempt | None"):
        self.key = key
        self.session_id = session_id
        # C10/Z02: optional - owned sessions (independent containment)
        # have no opening attempt to signal.
        self.attempt = attempt
        # C9/Y02: the owned durable-release producer (coalesced; the
        # obligation survives a budget-expired wait).
        self.retry_task: "asyncio.Task | None" = None


class _LateHandleRecord:
    """Strongly-owned late handle awaiting proven stop (C6/V02b)."""

    __slots__ = ("native", "attempt", "close_task", "force_task",
                 "observe_task", "last_state")

    def __init__(self, native, attempt: "_OpeningAttempt"):
        self.native = native
        self.attempt = attempt
        # C8/X03: the OWNED physical control units - a retry SHARES an
        # in-flight close/force instead of dispatching a duplicate.
        self.close_task: "asyncio.Task | None" = None
        self.force_task: "asyncio.Task | None" = None
        # C9/Y01: the observation is ALSO an owned, coalesced unit with
        # its own budget - a stalled observer never gates the force
        # decision, which uses the LAST KNOWN state instead.
        self.observe_task: "asyncio.Task | None" = None
        self.last_state: "str | None" = None


class _ForceAudit:
    """Shared state between the force dispatch and its parallel journal
    audit (C4/T01): `admitted` is True only after the journal confirms the
    admission; `outcome` is the dispatch result observed by the runtime.
    Neither field ever fabricates durable evidence."""

    __slots__ = ("admitted", "outcome", "outcome_set")

    def __init__(self) -> None:
        self.admitted = False
        self.outcome: str | None = None
        self.outcome_set = asyncio.Event()

    def set_outcome(self, outcome: str) -> None:
        if self.outcome is None:
            self.outcome = outcome
        self.outcome_set.set()


class _OpeningGuard:
    """Thread-safe draining fence for one pending open (C4/T04).

    Registered in memory BEFORE any callback or queued unit with spawn
    capacity; the runtime closes it at the START of shutdown, and the
    factory consults it after every await and inside the spawn thread -
    so a late environment resolution cannot start a native adapter under
    a runtime that already began draining."""

    __slots__ = ("closed",)

    def __init__(self) -> None:
        self.closed = False


class _OpeningAttempt:
    """Traceable pending-open record (C4-03.01 + C5/U03): completion
    event, draining guard AND the native producer task - a cancelled
    caller never abandons the Future that may still return a live
    handle; the runtime supervises and contains it."""

    __slots__ = ("finished", "guard", "native_task", "operation_id",
                 "slot_reserved", "waiter_done")

    def __init__(self) -> None:
        self.finished = asyncio.Event()
        self.guard = _OpeningGuard()
        self.native_task: "asyncio.Task | None" = None
        self.operation_id: str | None = None
        self.slot_reserved = False
        self.waiter_done = False


class LocalRuntimeCore:
    """One installation's runtime kernel.

    The trusted host supplies selected binaries, local roots and a native
    factory. No Server-side path or caller-provided agent hint is authority.
    Session handles are intentionally process-local; after restart, known
    operation receipts remain queryable but process ownership is UNKNOWN.
    """

    def __init__(self, journal: "Journal", native_factory: NativeFactory,
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
                 max_owned_sessions: int = 8,
                 pi_install_root: str | "Path | None" = None,
                 pi_node: str | "Path | None" = None,
                 cleanup_budget_seconds: float = 5.0):
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
        # C2/R08: explicit public contract for the composed Pi release
        # resolver - both inputs or neither; nothing implicit is scanned.
        if (pi_install_root is None) != (pi_node is None):
            raise ValueError(
                "pi_install_root and pi_node must be provided together")
        if not _finite_timing(cleanup_budget_seconds) or \
                cleanup_budget_seconds <= 0:
            raise ValueError("invalid cleanup budget")
        self._cleanup_budget_seconds = cleanup_budget_seconds
        self._pi_install_root = (Path(pi_install_root)
                                  if pi_install_root is not None else None)
        self._pi_node = Path(pi_node) if pi_node is not None else None
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
        self._session_tombstones = _SessionTombstones()
        self._opening: dict[SessionKey, _OpeningAttempt] = {}
        # C4/T04: additive opening_guard seam - passed only when declared.
        import inspect as _inspect
        try:
            self._factory_accepts_opening_guard = "opening_guard" in                 _inspect.signature(self._native_factory.open).parameters
        except (TypeError, ValueError, AttributeError):
            # Legacy seams (bare async functions) do not declare it.
            self._factory_accepts_opening_guard = False
        self._uncertain_opens: set[SessionKey] = set()
        self._lock = asyncio.Lock()
        self._event_changed = asyncio.Condition()
        self._shutting_down = False
        self._shutdown_policy = ShutdownPolicy()
        # C2/R10: tracked cooperative-cleanup tasks (evictions). Shutdown
        # waits for them within the cleanup budget; none is discarded while
        # ownership could still be uncertain.
        self._cleanup_tasks: set[asyncio.Task] = set()
        # C6/V02b: late native handles with unproven stop - strongly
        # referenced so recovery can re-contain the SAME object.
        self._late_handles: dict[SessionKey, _LateHandleRecord] = {}
        # C8/X02: durable slot-release obligations after proven stops.
        self._release_obligations: dict[SessionKey, _ReleaseObligation] = {}
        # C10/Z02: strong refs for owned durable-release producers (NOT
        # members of the cancellable cleanup gather).
        self._release_producers: set[asyncio.Task] = set()
        # C3/S08: one-shot public disposal of factory-owned executors.
        self._factory_disposed = False

    async def discover(self, request: DiscoveryRequest) -> Inventory:
        # C9/C01: a request without explicit IDs asks the single-source
        # catalog which adapters admit discovery - no host-side adapter
        # array. Attach (no executable/discoverable=False) is skipped;
        # an explicit tuple keeps its filter semantics (unknown IDs are
        # refused by discover_path as before).
        if request.adapter_ids is None:
            from .catalog import get_runtime_catalog
            adapter_ids = tuple(
                descriptor.adapter_id
                for descriptor in get_runtime_catalog().runtimes
                if descriptor.discoverable)
        else:
            adapter_ids = request.adapter_ids
        candidates = []
        for adapter_id in adapter_ids:
            found = await asyncio.to_thread(
                discover_path, adapter_id,
                trusted_roots=self._trusted_discovery_roots)
            if (adapter_id == "pi_rpc" and self._pi_install_root is not
                    None and self._pi_node is not None):
                # C2/R08: the public path composes the same supported
                # resolver the helpers expose - one inventory from the
                # approved roots, no helper imports, no wrapper execution.
                found = list(found) + list(await asyncio.to_thread(
                    discover_pi_releases, self._pi_install_root,
                    self._pi_node,
                    trusted_roots=self._trusted_discovery_roots))
            candidates.extend(found)
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
        # C2/R01+C2/R04: the dedup read is authorized I/O and never runs
        # under the global state lock; a retried open answers from its
        # durable receipt regardless of concurrent fence transitions.
        old = await self._existing(semantic, context)
        if old is not None:
            return old
        async with self._lock:
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
            attempt = _OpeningAttempt()
            self._opening[session_key] = attempt
        # C4/T04: factories that declare the additive opening_guard seam
        # receive the draining fence (legacy/test factories without the
        # parameter are simply not passed it).
        open_kwargs = {"stream_epoch": operation.stream_epoch}
        if self._factory_accepts_opening_guard:
            open_kwargs["opening_guard"] = attempt.guard
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
                    attempt.operation_id = operation.operation_id
                    attempt.slot_reserved = True
                # C5/U03: the producer runs as its OWN task and the
                # attempt owns it - a cancelled caller stops waiting but
                # the Future (and any live handle it returns) stays
                # supervised by the runtime, never abandoned.
                open_task = asyncio.ensure_future(
                    self._native_factory.open(
                        prepared, operation.session_id, context,
                        **open_kwargs))
                attempt.native_task = open_task
                try:
                    native = await asyncio.shield(open_task)
                except asyncio.CancelledError:
                    loop = asyncio.get_running_loop()
                    open_task.add_done_callback(
                        lambda done, _key=session_key, _attempt=attempt:
                        loop.call_soon(self._consume_late_open, _key,
                                       _attempt, done))
                    raise
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
                    # PC03: thread-safe pre-dispatch guard shared with the
                    # native bridge; probes plain binding attributes (GIL-
                    # safe reads) at the closest point to the native write.
                    from .native.runtime_bridge import EffectFence
                    binding.effect_fence = EffectFence(
                        lambda: (binding.closed, binding.closing,
                                 binding.revoked,
                                 binding.lease_expired or
                                 binding.lease_hold or
                                 binding.superseded,
                                 binding.faulted),
                        clock=self._clock.monotonic,
                        deadline_probe=lambda:
                            binding.context.lease_deadline_monotonic)
                    try:
                        setattr(native, "effect_fence", binding.effect_fence)
                    except (AttributeError, TypeError):
                        pass  # host double without attribute support
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
                # C6/V02c: the WAITER ended, but the PRODUCER may still be
                # able to create an effect. The attempt stays registered
                # while the producer lives (shutdown keeps fencing its
                # guard; the late consumer finishes it) - ownership does
                # not vanish with the caller.
                producer = attempt.native_task
                if producer is None or producer.done():
                    self._opening.pop(session_key, None)
                    attempt.waiter_done = True
                    attempt.finished.set()
                else:
                    attempt.waiter_done = True
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

    async def submit(self, operation: TurnOperation,
                     context: ExecutionContext) -> OperationReceipt:
        self._external_operation_id(operation.operation_id)
        self._external_session_id(operation.session_id, "submit")
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
        self._external_session_id(operation.session_id, "control")
        if operation.verb == "interrupt" and operation.text is None:
            semantic = Operation(operation.operation_id, operation.session_id,
                                 "turn.interrupt", {}, operation.expected_turn_id)
            return await self._send(semantic, context, "interrupt", {})
        # Steer targeting is adapter-specific: Codex correlates an explicit
        # native turn ID, while Pi has no native turn ID on the wire and is
        # steered ID-less against its observed active agent run. The
        # per-adapter gate in _send refuses the shapes an adapter cannot
        # target before operation admission.
        if operation.verb != "steer" or not operation.text:
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
        # C7/W04: ONE classification - decline/cancel map to a strictly
        # negative native reply (never new permission); accept and any
        # input carrying operator content remain productive.
        containment_reply = operation.decision in {"decline", "cancel"}
        self._authorize(context, action,
                        containment_reply=containment_reply)
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
        # C7/W04: the kernel treats a strictly negative reply as
        # containment (deadline-exempt like turn.interrupt).
        kernel_containment = containment_reply
        # C2/R01+C2/R04: dedup read outside the locks; memory revalidation
        # afterwards.
        old = await self._existing(semantic, context)
        if old is not None:
            return old
        binding = self._session(operation.session_id, context,
                                require_live_lease=True,
                                containment_reply=containment_reply)
        async with binding.control_lock:
            old = await self._existing(semantic, context)
            if old is not None:
                return old
            binding = self._session(operation.session_id, context,
                                    require_live_lease=True,
                                    containment_reply=containment_reply)
            if binding.closed:
                raise CoreError("SESSION_CLOSED", "approval_decide")
            if (self._shutting_down or binding.closing or binding.faulted) and                     not containment_reply:
                # C7/W04: a closing/faulted stream still accepts its
                # strictly NEGATIVE reply (containment); draining must
                # never make a pending approval unanswerable.
                raise CoreError("SESSION_CLOSING", "approval_decide")
            if binding.lease_hold and not containment_reply:
                raise CoreError("LEASE_UPDATE_PENDING", "approval_decide",
                                retry_safe=True)
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

            return await self._kernel.execute(
                    semantic, context, effect,
                    containment=kernel_containment)

    async def _send(self, semantic: Operation, context: ExecutionContext,
                    verb: str, payload: Mapping[str, str]) -> OperationReceipt:
        self._authorize(context, semantic.action)
        # C2/R04: an idempotent retry (same ID, same hash) must receive the
        # known receipt even when the session is faulted, closing, closed or
        # already evicted; a divergent hash stays an OPERATION_CONFLICT.
        # This read is authorized I/O and runs OUTSIDE every state lock so a
        # stuck journal can never delay the containment fences (C2/R01).
        old = await self._existing(semantic, context)
        if old is not None:
            return old
        # PC02.02/C2-R01: the in-memory admission fence is a memory-only
        # critical section - no durable I/O under the global lock, so an
        # expired/revoked/closing session is refused even while some other
        # coroutine is still waiting on storage.
        fence_key = SessionKey(context.server_id, context.executor_id,
                               semantic.session_id)
        async with self._lock:
            fence_binding = self._sessions.get(fence_key)
            if (self._shutting_down or fence_binding is None):
                pass  # precise typed errors come from _session below
            elif (fence_binding.closed or fence_binding.closing or
                    fence_binding.revoked or fence_binding.faulted):
                if fence_binding.closed:
                    error = "SESSION_CLOSED"
                elif fence_binding.revoked:
                    error = "AGENT_REVOKED"
                elif fence_binding.faulted:
                    error = "EVENT_STREAM_UNAVAILABLE"
                else:
                    error = "SESSION_CLOSING"
                raise CoreError(error, "admission", retry_safe=True)
            if (fence_binding is not None and
                    (fence_binding.lease_hold or
                     fence_binding.superseded) and
                    semantic.action in {"turn.submit", "turn.steer",
                                        "approval.decide", "input.provide"}):
                # A permissive decision grants work: it shares the lease
                # hold. Denials (containment) are NOT blocked here - the
                # approval path admits them explicitly.
                raise CoreError("LEASE_UPDATE_PENDING", "admission",
                                retry_safe=True,
                                operation_id=semantic.operation_id)
            elif (fence_binding is not None and
                  semantic.action in {"turn.submit", "turn.steer"} and
                    (fence_binding.lease_expired or
                     fence_binding.lease_hold or
                     fence_binding.superseded)):
                # C6/V01: an uncertain lease update (notably a reserved or
                # unconfirmed revocation) fences NEW work grants; the
                # refusal is its own operation's safe outcome - it never
                # inherits possible_effect from the pending CAS.
                raise CoreError(
                    "LEASE_UPDATE_PENDING" if fence_binding.lease_hold
                    and not fence_binding.lease_expired
                    else "AGENT_REVOKED",
                    "admission", retry_safe=True,
                    operation_id=semantic.operation_id)
        binding = self._session(semantic.session_id, context,
                                require_live_lease=semantic.action == "turn.submit")
        # A slow normal write must not hold the runtime-wide state lock: an
        # interrupt/steer may need to reach that same native session urgently.
        # Separate session locks let controls overlap normal sends, while
        # close/shutdown acquire both before releasing ownership.
        command_lock = (binding.normal_lock if verb == "send_turn"
                        else binding.control_lock)
        async with command_lock:
            # Revalidation after the (unlocked) journal read: pure memory
            # checks; the global lock stays free for containment.
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
            if verb == "steer":
                # Codex steer must name the active native turn ID. Pi
                # steer is the ID-less contract: the bridge targets the
                # agent run it observed starting for the active submit
                # (native queue semantics, next turn boundary) and
                # refuses before the write when there is none. Supplying
                # a native turn ID for Pi is refused the same way, so
                # neither adapter silently accepts an untargetable
                # steer. Other adapters keep refusing steer outright.
                if binding.adapter_id == "codex_app_server":
                    if not semantic.expected_turn_id:
                        raise CoreError("CAPABILITY_UNSUPPORTED", "control")
                elif binding.adapter_id == "pi_rpc":
                    if semantic.expected_turn_id is not None:
                        raise CoreError("CAPABILITY_UNSUPPORTED", "control")
                else:
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
        self._external_session_id(operation.session_id, "close")
        semantic = Operation(operation.operation_id, operation.session_id,
                             "runtime.close")
        self._authorize(context, semantic.action)
        # C2/R01+C2/R04: the dedup read answers an idempotent retry from
        # its durable receipt even after EOF/closing/eviction; it never
        # runs under the global state lock.
        old = await self._existing(semantic, context)
        if old is not None:
            return old
        binding = self._session(operation.session_id, context)
        async with binding.normal_lock:
            async with binding.control_lock:
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
            ownership = self._session_tombstones.get(session)
            if ownership is not None:
                # Historical fact recorded at eviction; no process state is
                # invented from it (PC07.01/.03).
                return RuntimeSnapshot(session.session_id, "UNKNOWN",
                                       "UNKNOWN", ownership, 0,
                                       "CLOSED" if ownership == "released"
                                       else "UNKNOWN")
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

    async def legacy_operation_receipt(
            self, server_id: str, executor_id: str,
            legacy_operation_id: str) -> OperationReceipt | None:
        """Read-only legacy lookup for development-journal IDs of 161-256.

        PC05/F05: new external IDs are admitted only up to 160 characters,
        matching the bundled schemas. Older development journals may hold
        longer IDs; this bounded, namespace-scoped, exact-key query makes
        that history inspectable without re-admitting, re-keying or
        re-executing anything. It never mutates state and grants no
        authority; hosts export diagnostics from it under their own
        approval. Batches stay on the ordinary reconcile path (1-160).
        """
        from .identifiers import validate_legacy_id
        if type(server_id) is not str or type(executor_id) is not str:
            raise CoreError("VALIDATION_ERROR", "legacy_query")
        validate_legacy_id(legacy_operation_id)
        validate_claim_namespace(server_id, executor_id)
        return await self._journal.get_receipt(OperationKey(
            server_id, executor_id, legacy_operation_id))

    async def persisted_lease(self, session: SessionKey) -> SessionLeaseState | None:
        """Durable last-known lease fence for one claimed session.

        Written atomically with the session claim and advanced by
        `renew_lease`/`revoke_lease` through journal CAS. This is fence
        evidence for host reconciliation after a restart or a second Core
        instance sharing the journal — not process liveness, not a lease
        deadline and not takeover authority. Claims made without lease
        evidence report None.
        """
        if not isinstance(session, SessionKey):
            raise ValueError("invalid lease session")
        validate_claim_namespace(session.server_id, session.executor_id)
        if type(session.session_id) is not str or not session.session_id:
            raise ValueError("invalid lease session")
        return await self._journal.get_session_lease(session)

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
            raise CoreError("VALIDATION_ERROR", "reconcile")
        identifiers = (request.server_id, request.executor_id)
        if any(type(value) is not str or not 1 <= len(value) <= 160
               for value in identifiers):
            raise CoreError("VALIDATION_ERROR", "reconcile")
        for ids in (request.operation_ids, request.session_ids):
            if (type(ids) is not tuple or len(ids) > 256 or
                    any(type(value) is not str or not 1 <= len(value) <= 160
                        for value in ids) or len(set(ids)) != len(ids)):
                raise CoreError("VALIDATION_ERROR", "reconcile")
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
            # C4/T04: draining closes the guard of EVERY pending open
            # before any drain wait - a late callback or a queued spawn
            # unit will refuse at the frontier instead of starting a new
            # native effect under a draining runtime.
            for pending_attempt in self._opening.values():
                pending_attempt.guard.closed = True
            opening = tuple(attempt.finished for attempt in
                            self._opening.values())
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
        # Sessions already closed and evicted from the live registry keep an
        # honest shutdown answer from their tombstone (PC07): "already_closed"
        # for released history, "unknown" where ownership stayed uncertain.
        for tombstoned, ownership in self._session_tombstones._entries.items():
            outcomes.setdefault(
                tombstoned,
                "already_closed" if ownership == "released" else "unknown")
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
        # C2/R10: tracked cooperative-cleanup tasks (evictions) are awaited
        # within the cleanup budget; uncertain ownership is never silently
        # discarded - the tombstone keeps the honest outcome either way.
        if self._cleanup_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tuple(self._cleanup_tasks),
                                   return_exceptions=True),
                    timeout=self._cleanup_budget_seconds + 1.0)
            except (asyncio.TimeoutError, TimeoutError):
                pass
        # C9/Y02: containment of STILL-LIVE resources first - a stopped
        # resource's blocked durable release never delays another
        # resource's force/recovery.
        if self._late_handles:
            self._retry_late_handles(policy)
        # C8/X02 + C9/Y02 + C10/Z02: the durable release retries run as
        # OWNED producers; the public return waits only its budget (a
        # NON-destructive asyncio.wait - never a gather that cancels)
        # and the obligation + in-flight producer survive the timeout.
        if self._release_obligations:
            await self._retry_release_obligations()
        try:
            await asyncio.wait_for(
                asyncio.gather(*tuple(self._cleanup_tasks),
                               return_exceptions=True),
                timeout=self._cleanup_budget_seconds + 1.0)
        except (asyncio.TimeoutError, TimeoutError):
            pass
        # C3/S08: dispose factory-owned executors through the PUBLIC
        # lifecycle - never by the host reaching into privates - once the
        # shutdown is fully resolved. Uncertain ownership (unknown closes,
        # still-running forces, live bindings) RETAINS the containment
        # capacity those sessions may still need; a later fully-resolved
        # shutdown disposes it. Idempotent by flag.
        self._dispose_factory_if_resolved()
        return ShutdownReport(outcomes)

    def _dispose_factory_if_resolved(self) -> None:
        if self._factory_disposed:
            return
        # C4/T04: a pending open can still produce an effect (callbacks,
        # queued spawn units) - its capacity is NOT disposable.
        if (self._opening or self._uncertain_opens or self._cleanup_tasks
                or self._late_handles or self._release_obligations):
            return
        for binding in self._sessions.values():
            if not binding.closed:
                return
            force = binding.force_task
            if force is not None and not force.done():
                return
        dispose = getattr(self._native_factory, "close", None)
        if callable(dispose) and not asyncio.iscoroutine(dispose):
            try:
                dispose()
                self._factory_disposed = True
            except Exception:
                pass

    def _schedule_force(self, session: SessionKey, binding: _Session,
                        deadline: float,
                        *, immediate: bool = False) -> None:
        # Attach is somebody else's process. Only a Core-owned managed backend
        # may expose this independent containment primitive.
        if (binding.adapter_id == "claude_attach" or binding.force_dispatched or
                not callable(getattr(binding.native, "force_stop", None))):
            return
        if binding.force_task is not None and not binding.force_task.done():
            # C5/U04: a WAITING worker exists - tighten to the MINIMUM
            # deadline and WAKE it (immediate == now). A worker already
            # DISPATCHING is never touched: the physical request in
            # flight is not cancelled to fake rescheduling.
            if deadline < (binding.force_deadline
                           if binding.force_deadline is not None
                           else deadline):
                binding.force_deadline = deadline
            if binding.force_awake is not None:
                binding.force_awake.set()
            return
        binding.force_deadline = deadline
        binding.force_awake = asyncio.Event()
        binding.force_started = asyncio.Event()
        binding.force_task = asyncio.create_task(
            self._force_after_deadline(session, binding,
                                       binding.force_started))

    async def _force_after_deadline(self, session: SessionKey,
                                    binding: _Session,
                                    started: asyncio.Event) -> None:
        """WAITING worker for one session's emergency force (C5/U04).

        Waits on the wake Event with the CURRENT minimum deadline as the
        timeout - a later, more urgent request tightens
        ``binding.force_deadline`` and wakes the worker instead of
        sleeping to a stale far deadline. Once DISPATCHING, the physical
        request is never cancelled.
        """
        try:
            loop = asyncio.get_running_loop()
            while not binding.closed:
                deadline = binding.force_deadline
                if deadline is None:
                    await binding.force_awake.wait()
                    continue
                now = loop.time()
                if now >= deadline:
                    break
                try:
                    await asyncio.wait_for(binding.force_awake.wait(),
                                           timeout=deadline - now)
                except (asyncio.TimeoutError, TimeoutError):
                    break  # the (possibly tightened) deadline arrived
                # woken: the deadline changed - re-read it
            if binding.closed:
                return
            force_stop = getattr(binding.native, "force_stop", None)
            if not callable(force_stop):
                return
            binding.force_dispatched = True
            binding.force_requested = True
            started.set()
            # C4/T01: the PHYSICAL force is dispatched FIRST; the durable
            # audit (admission + receipt) runs in PARALLEL on a tracked
            # side task. Storage can never delay or veto containment of a
            # tree the Core already owns; while stop is not observed the
            # honest outcome stays unknown and ownership is retained.
            audit = _ForceAudit()
            audit_task = asyncio.create_task(
                self._force_audit(session, binding, audit))
            self._cleanup_tasks.add(audit_task)
            audit_task.add_done_callback(self._cleanup_tasks.discard)
            try:
                await force_stop()
            except asyncio.CancelledError:
                audit.set_outcome("OUTCOME_UNKNOWN")
                raise
            except BaseException:
                audit.set_outcome("OUTCOME_UNKNOWN")
                return
            audit.set_outcome("SUBMITTED")
        except BaseException:
            # Neither an attempted force nor an exception proves tree stop.
            # The normal shutdown task retains the effect slot and observes
            # termination only after any in-flight native calls settle.
            return
        finally:
            started.set()

    async def _force_audit(self, session: SessionKey, binding: _Session,
                           audit: "_ForceAudit") -> None:
        """Best-effort durable audit of one force dispatch (C4/T01).

        Admission and the receipt are diagnostics recorded when storage
        cooperates; a stuck journal parks here without ever delaying the
        physical force (already dispatched) and without inventing a
        committed receipt - `admitted` stays False until the journal
        confirms, so nothing claims durable evidence that is not on disk.
        """
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
        try:
            _, admitted = await self._journal.admit(
                key, digest, session.session_id, critical=True,
                effect_imminent=True)
        except Exception:
            # Audit unavailable: in-memory diagnostic only. The physical
            # request already happened; no receipt is invented.
            binding.faulted = True
            return
        if not admitted:
            return
        audit.admitted = True
        try:
            await asyncio.wait_for(
                audit.outcome_set.wait(),
                timeout=self._cleanup_budget_seconds + 5.0)
        except (asyncio.TimeoutError, TimeoutError):
            audit.set_outcome("OUTCOME_UNKNOWN")
        stage = audit.outcome or "OUTCOME_UNKNOWN"
        try:
            await self._journal.record_receipt(key, OperationReceipt(
                operation_id, digest, stage, True, False, session.session_id,
                error_code=None if stage == "SUBMITTED" else stage))
        except Exception:
            binding.faulted = True

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
            if binding.force_awake is not None:
                binding.force_awake.set()  # release a WAITING worker
            self._schedule_eviction(session, binding)
            if binding.force_requested and reported != "forced":
                return "unknown"
            return reported if reported in {"graceful", "forced"} else "unknown"
        binding.faulted = True
        return "unknown"

    def _schedule_eviction(self, session: SessionKey, binding: _Session) -> None:
        """Release the live-session entry once its tasks no longer need it.

        PC07 (F06): evict only after stop was observed (binding.closed) and
        the pump/lease tasks finished, so no callback reinstalls state and
        the heavy native adapter becomes collectable. The durable history
        (receipts/claims/events) is untouched; a bounded tombstone keeps
        the honest ownership outcome for ``inspect``.
        """
        if getattr(binding, "eviction_scheduled", False):
            return
        binding.eviction_scheduled = True

        async def _evict() -> None:
            try:
                pump = binding.pump
                if pump is not None and not pump.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(pump),
                                               timeout=self._cleanup_budget_seconds)
                    except (asyncio.TimeoutError, asyncio.CancelledError,
                            Exception):
                        pass
                for task in (binding.lease_task, binding.sink_task,
                             binding.force_task):
                    if task is not None and not task.done():
                        try:
                            await asyncio.wait_for(asyncio.shield(task),
                                                   timeout=self._cleanup_budget_seconds)
                        except (asyncio.TimeoutError, asyncio.CancelledError,
                                Exception):
                            pass
                # C2/R10: a stalled host sink must not retain the native
                # adapter. After the cooperative budget expires the sink
                # task is cancelled WITHOUT advancing its cursor - a lost
                # notification stays recoverable from durable replay; it is
                # never confirmed fictitiously - and the heavy native
                # reference is dropped from the evicted binding.
                sink = binding.sink_task
                if sink is not None and not sink.done():
                    sink.cancel()
                    try:
                        await asyncio.wait_for(asyncio.shield(sink),
                                               timeout=self._cleanup_budget_seconds)
                    except (asyncio.TimeoutError, asyncio.CancelledError,
                            Exception):
                        pass
                binding.native = None
                async with self._lock:
                    if (self._sessions.get(session) is binding and
                            binding.closed):
                        del self._sessions[session]
                        self._session_tombstones.record(
                            session,
                            "released" if not binding.slot_reserved
                            else "unknown")
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

        task = asyncio.create_task(_evict())
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

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
                            if binding.lease_cas_pending:
                                raise CoreError("RECONNECT_BUSY", "lease_renew",
                                                retry_safe=True)
                            # C6/V01: the attempt is identified and the
                            # productive hold reserved BEFORE storage.
                            binding.lease_attempt_token += 1
                            binding.lease_hold = True
                            # C3/S04: reserve in memory under the SHORT lock
                            # (no I/O), then run the durable CAS OUTSIDE
                            # every state lock: the containment coordinator
                            # never queues behind storage latency. The race
                            # is explicit: the worker may accept and commit
                            # the CAS after the caller stopped waiting, so
                            # the answer on timeout/cancel is BUSY - never a
                            # claim that nothing happened - and a late
                            # commit is applied conservatively below.
                            binding.lease_cas_pending = True
                        cas = asyncio.ensure_future(self._journal.cas_session_lease(
                            session,
                            expected_connection_generation=old.connection_generation,
                            connection_generation=context.connection_generation,
                            owner_generation=context.session_owner_generation,
                            authorization_revision=context.authorization_revision,
                            configuration_revision=context.configuration_revision,
                            revoked=False))
                        try:
                            # The shield keeps the delivered unit alive when
                            # the caller stops waiting: the worker may still
                            # commit, and the applier recovers it below.
                            await asyncio.shield(cas)
                        except asyncio.CancelledError:
                            cas.add_done_callback(self._late_cas_applier(
                                session, binding, context, revoke=False))
                            raise
                        except BaseException:
                            # C5/U06: reconcile against the durable record
                            # before touching the reservation - a Future
                            # that finished with an exception proves
                            # nothing about the commit (the port allows
                            # confirmation loss after the write). Pre-
                            # delivery refusals resolve here as "no row
                            # change"; a committed revocation closes the
                            # fences immediately.
                            await self._finalize_lease_attempt(
                                session, binding, context, revoke=False,
                                producer_done=cas.done(),
                                base_context=old)
                            raise
                        async with self._lock:
                            binding.lease_cas_pending = False
                            binding.lease_hold = False
                            if (self._sessions.get(session) is binding and
                                    not binding.closed and
                                    not binding.revoked):
                                # Durable fence already advanced (PC1): a
                                # competing Core lost without ever becoming
                                # the active generation in memory.
                                binding.context = context
                                binding.lease_expired = False
        except TimeoutError as exc:
            raise CoreError("RECONNECT_BUSY", "lease_renew",
                            retry_safe=True) from exc
        snapshot = await self.inspect(session)
        await self._lease_event(session, binding, "core.lease_renewed", {})
        return snapshot

    async def _reconcile_cas_error(self, session: SessionKey,
                                    binding: _Session,
                                    context: ExecutionContext, *,
                                    revoke: bool) -> None:
        """Reconcile a CAS error against the DURABLE record (C5/U06).

        A completed-with-exception Future proves nothing about the
        commit: the public port allows confirmation loss AFTER the
        durable write. The reservation is only finalized on a proven
        outcome read from storage; a revoked row closes the in-memory
        fences immediately (no work may flow under the old context);
        an unreadable store keeps the conservative BUSY hold - with
        containment unaffected either way.
        """
        try:
            lease = await self._journal.get_session_lease(session)
        except Exception:
            return  # conservative hold; retry after storage recovers
        if lease is None:
            # No durable row exists: this CAS never committed.
            binding.lease_cas_pending = False
            return
        if lease.revoked:
            if self._sessions.get(session) is binding:
                binding.context = replace(
                    binding.context,
                    lease_deadline_monotonic=self._clock.monotonic(),
                    allowed_actions=frozenset())
                binding.lease_expired = True
                binding.revoked = True
            binding.lease_cas_pending = False
            return
        if (not revoke and
                lease.authorization_revision == context.authorization_revision
                and lease.connection_generation == context.connection_generation
                and self._sessions.get(session) is binding and
                not (binding.closed or binding.closing or binding.revoked)):
            # The renewal DID commit before the confirmation was lost.
            binding.context = context
            binding.lease_expired = False
        binding.lease_cas_pending = False

    def _consume_late_open(self, session: SessionKey,
                           attempt: _OpeningAttempt,
                           task: "asyncio.Task") -> None:
        """Consume a cancelled open's native producer result (C5/U03).

        Runs on the loop when the producer task completes - independent
        of the caller that stopped waiting. A producer error left no
        handle (the factory closes its own half-spawned resources); a
        returned native session is CONTAINED by the runtime: ownership
        is never assumed from an operation whose caller already
        received an unknown outcome, and never abandoned either.
        """
        if task.cancelled():
            self._opening.pop(session, None)
            attempt.finished.set()
            return
        exc = task.exception()
        if exc is not None:
            # No handle was produced; the conservative uncertain-open
            # retention stays (the receipt already recorded unknown).
            self._opening.pop(session, None)
            attempt.finished.set()
            return
        native = task.result()
        if native is None:
            self._opening.pop(session, None)
            attempt.finished.set()
            return
        supervisor = asyncio.create_task(
            self._contain_late_open(session, attempt, native))
        self._cleanup_tasks.add(supervisor)
        supervisor.add_done_callback(self._cleanup_tasks.discard)

    async def _contain_late_open(self, session: SessionKey,
                                 attempt: _OpeningAttempt,
                                 native) -> None:
        """Contain a late handle with the COMMON containment model
        (C7/W03): ownership is registered BEFORE any await; the graceful
        close runs as an OWNED task whose cancellation is never a
        precondition - the physical force is dispatched in PARALLEL on
        its own task (a close that observes CancelledError but keeps
        waiting its backend cannot delay it); an unproven stop keeps the
        handle strongly registered for the next recovery pass.
        """
        # C7/W03: register ownership FIRST - before close, observe,
        # force or any journal I/O. A stalled observer or an exhausted
        # shutdown budget leaves the handle reachable by the NEXT
        # public lifecycle call.
        self._late_handles.setdefault(session, _LateHandleRecord(
            native, attempt))
        try:
            if self._sessions.get(session) is not None:
                # A live binding owns this scope now; never fight it.
                self._opening.pop(session, None)
                self._late_handles.pop(session, None)
                attempt.finished.set()
                return
            # C8/X03: the RECORD owns the physical units. A retry that
            # finds an IN-FLIGHT close/force SHARES it (one physical
            # dispatch per resource); a new unit is only created after
            # the previous one CONCLUDED.
            record = self._late_handles.setdefault(
                session, _LateHandleRecord(native, attempt))
            close = getattr(native, "close", None)
            close_task = record.close_task
            if (close_task is None or close_task.done()) and callable(close):
                close_task = asyncio.ensure_future(close())
                record.close_task = close_task
                # C8/X03: the RECORD owns the physical units - they are
                # NEVER members of the cancellable cleanup gather. A
                # budget expiry cancels only the WAITING coroutine; the
                # thread unit underneath keeps running and the next
                # retry SHARES this exact task.

            # Physical force in PARALLEL with the close (C7/W03): the
            # unit is created ONCE per resource and owned by the record
            # - never a member of the cancellable gather. A budget
            # expiry cancels only the waiting coroutine; the thread unit
            # underneath keeps running and every retry SHARES it.
            force = getattr(native, "force_stop", None)
            force_task = record.force_task
            force_created_here = force_task is None
            if force_task is None and callable(force):
                force_task = asyncio.ensure_future(force())
                record.force_task = force_task

            if close_task is not None:
                done, _pending = await asyncio.wait(
                    {close_task}, timeout=self._cleanup_budget_seconds)
                if close_task not in done:
                    close_task.cancel()  # cooperative; not awaited

            # C8/X03: a shared IN-FLIGHT unit is awaited, never
            # duplicated.
            if force_task is not None and not force_task.done():
                try:
                    await asyncio.shield(force_task)
                except BaseException:
                    pass

            # C9/Y01: the observation is an OWNED, coalesced unit with
            # its own budget - and the force-retry decision uses the
            # LAST KNOWN state, never a fresh blocking consultation. A
            # stalled observer can therefore not gate containment of a
            # still-owned resource; a proven STOPPED (cached) still
            # prevents any re-force.
            state = await self._observed_state(record, native)

            if (state != "STOPPED" and not force_created_here and
                    force_task is not None and force_task.done() and
                    callable(force)):
                # C8/X03 retry on a LATER lifecycle call: the PREVIOUS
                # containment's unit concluded without a proven stop -
                # a NEW unit is created here (never overlapping: the old
                # one is done). A unit created by THIS containment that
                # concluded unproven leaves the record OWNED_UNKNOWN for
                # the next call instead (v02b semantics).
                force_task = asyncio.ensure_future(force())
                record.force_task = force_task
                try:
                    await asyncio.shield(force_task)
                except BaseException:
                    pass
                # Best-effort post-force observation (budgeted, owned);
                # its absence never blocks the containment flow.
                state = await self._observed_state(record, native)
            if state == "STOPPED":
                released = True
                if attempt.slot_reserved and attempt.operation_id:
                    key = OperationKey(session.server_id,
                                       session.executor_id,
                                       attempt.operation_id)
                    # C10/Z02.3: the INITIAL stopped-handle release and
                    # every retry share the SAME obligation record - an
                    # owned producer that survives waiter cancellation
                    # (a refused release keeps the obligation for the
                    # next public lifecycle call; never dropped).
                    released = await self._durable_release(
                        session, key, attempt)
                if released:
                    self._uncertain_opens.discard(session)
                    self._late_handles.pop(session, None)
                    self._opening.pop(session, None)
            # else: OWNED_UNKNOWN - the record stays registered; the
            # next public lifecycle call re-contains the SAME handle.
            attempt.finished.set()
        except asyncio.CancelledError:
            # Shutdown budget exhaustion cancels the WAIT, not the
            # ownership: the record (and any in-flight close/force
            # tasks) stay available to the next recovery pass.
            raise
        except Exception:
            self._late_handles.setdefault(
                session, _LateHandleRecord(native, attempt))
            attempt.finished.set()

    async def _observed_state(self, record: "_LateHandleRecord",
                              native) -> str:
        """Owned, coalesced, budgeted observation (C9/Y01).

        The unit lives on the record: an IN-FLIGHT observe is shared
        (never duplicated, never cancelled by a budget expiry - only the
        WAIT ends); a CONCLUDED one updates ``last_state`` and is not
        re-run within the same pass. The returned state is the LAST
        KNOWN one: a stalled observer yields the previous observation
        (or UNKNOWN) instead of blocking the caller indefinitely.
        """
        if record.observe_task is None or record.observe_task.done():
            if record.observe_task is not None:
                try:
                    record.last_state, _ = record.observe_task.result()
                except BaseException:
                    pass  # UNKNOWN stays; the error is the unit's result
            observe = getattr(native, "observe", None)
            if callable(observe):
                record.observe_task = asyncio.ensure_future(observe())
                done, _pending = await asyncio.wait(
                    {record.observe_task},
                    timeout=self._cleanup_budget_seconds)
                if record.observe_task in done:
                    try:
                        record.last_state, _ = \
                            record.observe_task.result()
                    except BaseException:
                        pass
                # else: the unit keeps running owned; the WAIT simply
                # ended - last_state (possibly None => UNKNOWN) returns.
        else:
            done, _pending = await asyncio.wait(
                {record.observe_task},
                timeout=self._cleanup_budget_seconds)
            if record.observe_task in done:
                try:
                    record.last_state, _ = record.observe_task.result()
                except BaseException:
                    pass
        return record.last_state if record.last_state is not None \
            else "UNKNOWN"

    def _process_release_results(self) -> None:
        """Consume FINISHED producers exactly once (C10/Z02.3).

        Runs before any scheduling decision on every route: a success
        already available is applied (the exact obligation is
        finalized), a pre-delivery refusal or uncertain outcome clears
        the finished task and keeps the obligation retryable (C8/X02).
        A NEW producer may only be scheduled after this step.
        """
        for session, obligation in list(
                self._release_obligations.items()):
            task = obligation.retry_task
            if task is None or not task.done():
                continue  # in flight: shared, never duplicated
            try:
                task.result()
            except BaseException:
                # Pre-delivery refusal or uncertain outcome: keep the
                # obligation; clear the FINISHED task so the next
                # lifecycle call may retry the same reservation.
                obligation.retry_task = None
                continue
            del self._release_obligations[session]
            self._uncertain_opens.discard(session)
            self._opening.pop(session, None)
            if obligation.attempt is not None:
                obligation.attempt.finished.set()

    def _schedule_release_retries(self) -> "asyncio.Task | None":
        """Schedule ONE coalesced release-retry producer (C9/Y02).

        Results of FINISHED producers are consumed FIRST (C10/Z02.3);
        then each still-pending obligation without an in-flight task
        gets exactly one OWNED producer. The collector is a pure
        bounded waiter: a blocked or slow ledger ends the WAIT - never
        a producer - and the obligation plus its in-flight release
        survive for the next public lifecycle call.
        """
        self._process_release_results()
        pending = [o for o in self._release_obligations.values()
                   if o.retry_task is None]
        for obligation in pending:
            # C10/Z02: the durable producer is owned by the OBLIGATION
            # (strong ref) - NEVER a member of the cancellable cleanup
            # gather: a response-budget expiry must not cancel a commit
            # the runtime keeps supervising. Only a NEW lifecycle call
            # may inspect/consume its result.
            obligation.retry_task = asyncio.ensure_future(
                self._owned_slots.release_owned_slot(
                    obligation.key, obligation.session_id))
            self._release_producers.add(obligation.retry_task)
            obligation.retry_task.add_done_callback(
                self._release_producers.discard)

        async def _collect() -> None:
            tasks = [o.retry_task for o in
                     self._release_obligations.values()
                     if o.retry_task is not None]
            if tasks:
                await asyncio.wait(set(tasks),
                                   timeout=self._cleanup_budget_seconds)

        collector = asyncio.ensure_future(_collect())
        # The collector only ENDS waits (asyncio.wait with timeout) -
        # cancelling it never touches the producers - but it stays out
        # of the cleanup gather as well so the public return never
        # waits for its teardown either.
        self._release_producers.add(collector)
        collector.add_done_callback(self._release_producers.discard)
        return collector

    async def _durable_release(self, session: SessionKey,
                               key: "OperationKey",
                               attempt: "._OpeningAttempt | None") -> bool:
        """The ONE durable-release route for a proven-stopped slot
        (C10/Z02.3): initial release of a stopped handle, containment
        retry and shutdown all consult the OBLIGATION first.

        An in-flight producer is SHARED (never duplicated); a finished
        one is consumed before anything new is scheduled; the waiter
        awaits it through a SHIELD - cancelling the waiter (a
        supervisor in the cleanup gather, the shutdown budget, the
        caller itself) ends only this wait. The owned producer keeps
        running and the reservation stays supervised until durable
        confirmation. Returns True ONLY on confirmed release.
        """
        obligation = self._release_obligations.get(session)
        if obligation is None:
            obligation = _ReleaseObligation(key, session.session_id,
                                            attempt)
            self._release_obligations[session] = obligation
        self._schedule_release_retries()
        task = obligation.retry_task
        if task is None:
            # Another route consumed a confirmed success just now.
            return session not in self._release_obligations
        try:
            await asyncio.shield(task)
        except BaseException:
            # Failed, uncertain, or the WAITER was cancelled: the
            # obligation keeps supervising the exact reservation -
            # never re-force, never drop, never re-deliver.
            return False
        self._process_release_results()
        return session not in self._release_obligations

    async def _retry_release_obligations(self) -> None:
        """Backwards-compatible bounded await over the coalesced
        producer (C9/Y02): never unbounded - the cleanup budget bounds
        the wait; obligations/in-flight releases survive the timeout."""
        collector = self._schedule_release_retries()
        if collector is None:
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(collector),
                timeout=self._cleanup_budget_seconds + 0.05)
        except (asyncio.TimeoutError, TimeoutError):
            pass  # the producer keeps running owned

    def _retry_late_handles(self, policy: ShutdownPolicy) -> None:
        """Re-contain every still-owned late handle (C6/V02b)."""
        for session, record in list(self._late_handles.items()):
            supervisor = asyncio.create_task(
                self._contain_late_open(session, record.attempt,
                                        record.native))
            self._cleanup_tasks.add(supervisor)
            supervisor.add_done_callback(self._cleanup_tasks.discard)

    async def _finalize_lease_attempt(self, session: SessionKey,
                                      binding: _Session,
                                      context: ExecutionContext, *,
                                      revoke: bool,
                                      producer_done: bool,
                                      base_context=None) -> str:
        """ONE finalizer for every lease-update termination (C6/V01 +
        C7/W02): classification is the SHARED transition function; the
        reconciler inherits the producer's termination proof, so a
        proven pre-delivery failure converges when storage answers."""
        if self._sessions.get(session) is not binding:
            binding.lease_cas_pending = False
            binding.lease_hold = False
            return "DETACHED"
        try:
            lease = await self._journal.get_session_lease(session)
        except Exception:
            self._schedule_lease_reconciler(session, binding, context,
                                            revoke=revoke,
                                            producer_done=producer_done,
                                            base_context=base_context)
            return "UNKNOWN"
        outcome = self._classify_lease_row(
            binding, lease, context, revoke=revoke,
            producer_done=producer_done,
            base_context=base_context)
        if outcome == "UNKNOWN":
            self._schedule_lease_reconciler(session, binding, context,
                                            revoke=revoke,
                                            producer_done=producer_done,
                                            base_context=base_context)
            return outcome
        self._apply_lease_classification(binding, outcome, context,
                                         revoke=revoke)
        return outcome

    def _classify_lease_row(self, binding: "_Session", lease, context, *,
                            revoke: bool, producer_done: bool,
                            base_context=None) -> str:
        """ONE transition function (C7/W02 + C8/X01) shared by the
        direct path, the late callback and every reconciler retry: same
        proofs, same classification, same actions. The row is compared
        BOTH to the proposal and to the attempt's BASE context: a valid
        row matching NEITHER means another authorized writer advanced
        the durable fence - the local context is SUPERSEDED (known
        obsolete), never "not delivered". NOT_DELIVERED requires the row
        to still show the exact BASE state (plus the producer's
        termination proof) - producer_done alone never proves rollback.
        The durable row is fence EVIDENCE only: it never installs
        permissions, deadlines or identity into this runtime."""
        if lease is not None and lease.revoked:
            return "COMMITTED_REVOKE"
        if (not revoke and lease is not None and
                lease.authorization_revision == context.authorization_revision
                and lease.connection_generation == context.connection_generation
                and lease.owner_generation == context.session_owner_generation
                and lease.configuration_revision == context.configuration_revision):
            return "COMMITTED_RENEW"
        if lease is not None and base_context is not None:
            if (lease.connection_generation == base_context.connection_generation
                    and lease.owner_generation == base_context.session_owner_generation
                    and lease.authorization_revision == base_context.authorization_revision
                    and lease.configuration_revision == base_context.configuration_revision):
                # The row still shows the exact BASE state: the attempt
                # changed nothing durably.
                if producer_done:
                    return "NOT_DELIVERED"
                return "UNKNOWN"
            # A valid row that matches neither proposal nor base: the
            # fence moved - this runtime's context is obsolete.
            return "SUPERSEDED"
        if lease is None and producer_done:
            return "NOT_DELIVERED"
        return "UNKNOWN"

    def _apply_lease_classification(self, binding: "_Session", outcome: str,
                                    context, *, revoke: bool) -> None:
        if outcome == "COMMITTED_REVOKE":
            binding.context = replace(
                binding.context,
                lease_deadline_monotonic=self._clock.monotonic(),
                allowed_actions=frozenset())
            binding.lease_expired = True
            binding.revoked = True
        elif outcome == "COMMITTED_RENEW":
            if not (binding.closed or binding.closing or binding.revoked):
                binding.context = context
                binding.lease_expired = False
        if outcome in {"COMMITTED_REVOKE", "COMMITTED_RENEW",
                       "NOT_DELIVERED", "SUPERSEDED"}:
            # SUPERSEDED resolves the ATTEMPT (pending/hold belong to
            # it) but fences the BINDING: the observed-newer durable
            # row makes the local context known-obsolete (C8/X01).
            binding.lease_cas_pending = False
            binding.lease_hold = False
            if outcome == "SUPERSEDED":
                binding.superseded = True

    def _schedule_lease_reconciler(self, session: SessionKey,
                                   binding: _Session,
                                   context: ExecutionContext, *,
                                   revoke: bool,
                                   producer_done: bool,
                                   base_context=None) -> None:
        """ONE coalesced reconciler per binding (C6/V01 + C7/W02): the
        producer's termination proof travels WITH the attempt, so a
        proven pre-delivery failure converges once storage answers -
        never by timeout, never by dropping the hold."""
        if (binding.lease_reconcile_task is not None and
                not binding.lease_reconcile_task.done()):
            return

        async def _reconcile() -> None:
            token = binding.lease_attempt_token
            delay = 0.05
            for _ in range(20):
                await asyncio.sleep(delay)
                delay = min(delay * 2, 1.0)
                if (self._sessions.get(session) is not binding or
                        binding.lease_attempt_token != token or
                        not binding.lease_hold):
                    return
                try:
                    lease = await self._journal.get_session_lease(session)
                except Exception:
                    continue
                outcome = self._classify_lease_row(
                    binding, lease, context, revoke=revoke,
                    producer_done=producer_done,
                    base_context=base_context)
                if outcome != "UNKNOWN":
                    self._apply_lease_classification(
                        binding, outcome, context, revoke=revoke)
                    return
                # UNKNOWN: the producer may still commit - keep the hold.

        binding.lease_reconcile_task = asyncio.create_task(_reconcile())
        self._cleanup_tasks.add(binding.lease_reconcile_task)
        binding.lease_reconcile_task.add_done_callback(
            self._cleanup_tasks.discard)

    def _late_cas_applier(self, session: SessionKey, binding: _Session,
                          context: ExecutionContext, *, revoke: bool):
        """Recover a durable lease CAS the caller no longer waits for.

        C3/S04 fault point: the journal worker may accept and commit the
        CAS after the caller was cancelled or timed out. Cancelling the
        await never proves absence of effect - the durable row advanced.
        The applier runs on the loop when the CAS task completes and
        applies the commit conservatively: a renewal applies only to a
        still-live, unrevoked binding; a revocation always tightens. A
        failed CAS commits nothing and only clears the pending marker
        (durable storage stays the reconcile authority either way).
        """
        def _on_done(task: asyncio.Task) -> None:
            # C6/V01: EVERY termination routes through the ONE finalizer -
            # a failed Future proves nothing about the commit (the port
            # allows confirmation loss after the write), and a successful
            # one is reconciled/applied under the same rules.
            loop = asyncio.get_running_loop()

            async def _finalize() -> None:
                token = binding.lease_attempt_token
                if (self._sessions.get(session) is not binding or
                        binding.lease_attempt_token != token):
                    return
                try:
                    task.result()
                except BaseException:
                    pass
                await self._finalize_lease_attempt(
                    session, binding, context, revoke=revoke,
                    producer_done=True)
            finalizer = asyncio.create_task(_finalize())
            self._cleanup_tasks.add(finalizer)
            finalizer.add_done_callback(self._cleanup_tasks.discard)
        return _on_done

    def _apply_committed_cas(self, session: SessionKey, binding: _Session,
                             context: ExecutionContext, revoke: bool) -> None:
        if self._sessions.get(session) is binding:
            if revoke:
                binding.context = replace(
                    context,
                    lease_deadline_monotonic=self._clock.monotonic(),
                    allowed_actions=frozenset())
                binding.lease_expired = True
                binding.revoked = True
            elif not (binding.closed or binding.closing or binding.revoked):
                binding.context = context
                binding.lease_expired = False
        binding.lease_cas_pending = False

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
                            if binding.lease_cas_pending:
                                raise CoreError("REVOKE_BUSY", "lease_revoke",
                                                retry_safe=True)
                            # C6/V01: identified attempt + productive
                            # hold closed BEFORE the durable CAS - a
                            # revocation in flight already fences grants.
                            binding.lease_attempt_token += 1
                            binding.lease_hold = True
                            # C3/S04: reserve in memory, durable revocation
                            # OUTSIDE the state locks (a crash or a stuck
                            # journal between the two leaves a durably
                            # revoked lease - never a revoked session whose
                            # journal row could still be renewed). A late
                            # commit after caller cancellation still
                            # tightens memory via the applier.
                            binding.lease_cas_pending = True
                        cas = asyncio.ensure_future(self._journal.cas_session_lease(
                            session,
                            expected_connection_generation=old.connection_generation,
                            connection_generation=context.connection_generation,
                            owner_generation=context.session_owner_generation,
                            authorization_revision=context.authorization_revision,
                            configuration_revision=context.configuration_revision,
                            revoked=True))
                        try:
                            # The shield keeps the delivered unit alive when
                            # the caller stops waiting: the worker may still
                            # commit, and the applier recovers it below.
                            await asyncio.shield(cas)
                        except asyncio.CancelledError:
                            cas.add_done_callback(self._late_cas_applier(
                                session, binding, context, revoke=True))
                            raise
                        except BaseException:
                            # C5/U06: same durable reconciliation as the
                            # renewal path - never infer rollback from the
                            # failed Future; a committed revocation applies.
                            await self._finalize_lease_attempt(
                                session, binding, context, revoke=True,
                                producer_done=cas.done(),
                                base_context=old)
                            raise
                        async with self._lock:
                            binding.lease_cas_pending = False
                            binding.lease_hold = False
                            if self._sessions.get(session) is binding:
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
                    # Memory fence first: no new work is admitted from this
                    # instant, even if the journal is stuck (PC02.02). The
                    # durable events are recorded best-effort AFTER
                    # containment is underway - they are diagnostics, never
                    # a prerequisite for the physical supervisor.
                    binding.lease_expired = True
                    expired_event_pending = True
                if now < deadline + self._lease_grace_seconds:
                    await asyncio.sleep(min(deadline + self._lease_grace_seconds - now,
                                            self._lease_poll_seconds))
                    continue
                async with self._lock:
                    if binding.closed or binding.closing:
                        # Containment coordination already belongs to another
                        # route (explicit stop/shutdown); never spin.
                        return
                    if (self._clock.monotonic() <
                            binding.context.lease_deadline_monotonic +
                            self._lease_grace_seconds):
                        continue
                    # Idempotent containment coordinator entry (PC02.03):
                    # every concurrent route (lease expiry, explicit stop,
                    # shutdown) shares this transition.
                    binding.closing = True
                try:
                    outcome = await self._contain_expired(session, binding)
                except Exception:
                    binding.faulted = True
                    outcome = "unknown"
                if expired_event_pending:
                    await self._bounded_lease_event(
                        session, binding, "core.lease_expired", {})
                await self._bounded_lease_event(
                    session, binding, "core.lease_closed",
                    {"outcome": outcome})
                return
        except asyncio.CancelledError:
            return

    async def _bounded_lease_event(self, session: SessionKey,
                                   binding: _Session, kind: str,
                                   payload: dict) -> None:
        """Best-effort durable lease event; never gates containment.

        A stuck or saturated journal must not delay (let alone prevent)
        physical containment of an expired owned session. The bounded wait
        keeps the watcher responsive; a timed-out event is dropped - it is
        diagnostics, not an ACK.
        """
        try:
            await asyncio.wait_for(
                self._lease_event(session, binding, kind, payload),
                timeout=5.0)
        except (asyncio.TimeoutError, CoreError, Exception):
            pass

    async def _contain_expired(self, session: SessionKey,
                               binding: _Session) -> str:
        """Contain an expired owned session without waiting for send locks.

        F01/G05: a stuck native send holds ``normal_lock``/``control_lock``
        across its await; lease containment must never queue behind it. The
        durable intent is attempted first (tolerating storage failure),
        then the independent physical path runs lock-free against the
        Core-owned backend (``force_stop`` first, ``close`` as fallback).
        """
        identity = [session.server_id, session.executor_id,
                    session.session_id, binding.epoch,
                    binding.context.session_owner_generation]
        operation_id = "core.internal.lease_close." + hashlib.sha256(
            canonical_json(identity)).hexdigest()
        operation = Operation(operation_id, session.session_id,
                              "runtime.lease_close", {"stream_epoch": binding.epoch})
        key = OperationKey(session.server_id, session.executor_id, operation_id)
        digest = intent_hash(operation, binding.context)
        admitted = False
        try:
            # Emergency containment of an owned resource must not queue
            # behind storage: the intent write is bounded, and its failure
            # degrades to a best-effort fault marker, never to inaction.
            _, fresh = await asyncio.wait_for(
                self._journal.admit(key, digest, session.session_id,
                                    critical=True, effect_imminent=True),
                timeout=1.0)
            if not fresh:
                binding.faulted = True
            else:
                admitted = True
        except (asyncio.TimeoutError, CoreError):
            # Disk saturation (or a stuck worker) may prevent the intent
            # record. Still contain rather than leave an owned process
            # running forever.
            binding.faulted = True
        outcome = await self._independent_containment(session, binding)
        if admitted:
            try:
                await asyncio.wait_for(
                    self._journal.record_receipt(key, OperationReceipt(
                        operation_id, digest,
                        "SUCCEEDED" if binding.closed else "OUTCOME_UNKNOWN",
                        True, False, session.session_id,
                        error_code=None if binding.closed else "OUTCOME_UNKNOWN")),
                    timeout=1.0)
            except (asyncio.TimeoutError, CoreError):
                binding.faulted = True
        return outcome

    async def _independent_containment(self, session: SessionKey,
                                       binding: _Session) -> str:
        """Physical containment of a Core-owned tree, lock-free (PC02.04).

        Never waits for ``normal_lock``/``control_lock`` (a stuck send may
        hold them), the journal, the event sink or a pending native write.
        Attach targets have no ``force_stop`` and are never signalled.
        """
        force = getattr(binding.native, "force_stop", None)
        reported = "forced" if callable(force) else "unknown"
        if callable(force):
            binding.force_requested = True
            try:
                await force()
            except BaseException:
                reported = "unknown"
        else:
            close = getattr(binding.native, "close", None)
            if callable(close):
                try:
                    await close()
                    reported = "graceful"
                except BaseException:
                    reported = "unknown"
        try:
            process_state, _ = await binding.native.observe()
        except Exception:
            process_state = "UNKNOWN"
        if process_state == "STOPPED":
            if binding.slot_reserved:
                # C10/Z02.3: same unified durable route - a failed or
                # blocked ledger keeps a TRACKED obligation instead of
                # being silently swallowed; the reservation converges
                # on a later public lifecycle call.
                released = await self._durable_release(
                    session,
                    OperationKey(session.server_id, session.executor_id,
                                 binding.opening_operation_id),
                    None)
                binding.slot_reserved = not released
            binding.closed = True
            if (binding.lease_task is not None and
                    binding.lease_task is not asyncio.current_task()):
                binding.lease_task.cancel()
            if binding.force_awake is not None:
                binding.force_awake.set()  # release a WAITING worker
            self._schedule_eviction(session, binding)
            if binding.force_requested and reported != "forced":
                return "unknown"
            return reported if reported in {"graceful", "forced"} else "unknown"
        binding.faulted = True
        return "unknown"

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
        except asyncio.CancelledError:
            # Unexpected watcher cancellation (RC-04-04): outside a
            # Core-initiated close this is an observation loss, not a
            # healthy idle state. Fence first, then record best-effort.
            async with self._lock:
                expected = binding.closing or binding.closed
                if not expected:
                    binding.faulted = True
            if not expected:
                await self._record_stream_loss(session, binding)
            return
        except Exception:
            # A dead stream does not prove process death or turn completion.
            # Keep ownership until explicit close/shutdown.
            binding.faulted = True
            await self._record_stream_loss(session, binding)
        else:
            # Iterator exhausted without exception (audit F03 / RC-04-01):
            # with a live process this is an unexpected EOF, not a turn
            # boundary and not a Core-initiated close. Fence the session in
            # memory BEFORE any durable I/O (RC-04-02) so new work is
            # refused even while the journal is stuck; the durable incident
            # is best-effort and bounded, and fires at most once per
            # stream epoch (one pump task per epoch).
            async with self._lock:
                expected = binding.closing or binding.closed
                if not expected:
                    binding.faulted = True
            if not expected:
                await self._record_stream_loss(session, binding)

    async def _record_stream_loss(self, session: SessionKey,
                                  binding: _Session) -> None:
        """Best-effort bounded incident record; never gates the fence."""
        try:
            await asyncio.wait_for(
                self._journal.record_event(RuntimeEvent(
                    session.server_id, session.executor_id,
                    session.session_id, binding.epoch, 0, "error",
                    "core.event_pump_failed",
                    {"code": "EVENT_STREAM_UNAVAILABLE"})),
                timeout=5.0)
        except (asyncio.TimeoutError, CoreError, Exception):
            pass
        async with self._event_changed:
            self._event_changed.notify_all()
        if self._event_sink is not None:
            self._schedule_sink(session, binding)

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

    def _authorize(self, context: ExecutionContext, action: str, *,
                   containment_reply: bool = False) -> None:
        self._validate_lease_deadline(context)
        # C7/W04: a strictly NEGATIVE approval reply (decline/cancel to
        # a still-observed request of the same turn) is containment, not
        # new permission: identity, allowed_actions, binding, generation
        # and correlation all remain validated; only the PRODUCTIVE
        # lease window is exempt - exactly like turn.interrupt.
        if (self._clock.monotonic() >= context.lease_deadline_monotonic and
                action not in {"turn.interrupt", "runtime.close"} and
                not containment_reply):
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
        # PC05: exact 1-160 policy shared with the bundled schemas; typed
        # refusal before any mutable persistence. Longer historical IDs
        # remain readable only through legacy_operation_receipt.
        from .identifiers import validate_external_id
        validate_external_id(operation_id)

    @staticmethod
    def _external_session_id(session_id: str, stage: str = "admission") -> None:
        from .identifiers import validate_external_session_id
        validate_external_session_id(session_id, stage=stage)

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
                 allow_newer_revision: bool = False,
                 containment_reply: bool = False) -> _Session:
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
        if require_live_lease and not containment_reply:
            if binding.superseded:
                # C8/X01: a newer durable fence was OBSERVED - this
                # local context is known obsolete.
                raise CoreError("STALE_GENERATION", "admission")
            if self._clock.monotonic() >= original.lease_deadline_monotonic:
                raise CoreError("AGENT_REVOKED", "admission")
        return binding

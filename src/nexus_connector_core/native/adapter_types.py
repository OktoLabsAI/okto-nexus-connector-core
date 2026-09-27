"""Neutral transport types extracted from Nexus harness port.

These types exist to preserve the native adapter behavior during extraction.
They are not the NXL/public RuntimeCore domain model.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol
from uuid import uuid4

from ..models import EffectNotSent


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CONFLICT = "CONFLICT"
    NOT_FOUND = "NOT_FOUND"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    CONTENT_TOO_LARGE = "CONTENT_TOO_LARGE"


class NativeAdapterError(Exception):
    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class RuntimeCommandNotSent(EffectNotSent):
    """Native effect was rejected before a protocol write."""


class DispatchGuards:
    """Thread-scoped operation guard for native write frontiers (C4/T03).

    The bridge installs the per-operation guard (a tiny sync callable
    raising :class:`RuntimeCommandNotSent`) right before dispatching on a
    worker thread; the adapter's transport consults it AFTER acquiring its
    own write lock and immediately BEFORE the first byte reaches the
    stream/process - the true effect frontier, after every internal wait.
    Thread-scoped so concurrent dispatches never overwrite each other's
    guard. A refusal here is provably pre-effect (zero bytes written) and
    maps to the kernel's durable not-sent evidence.
    """

    __slots__ = ("_local",)

    def __init__(self):
        import threading
        self._local = threading.local()

    def set(self, check) -> None:
        self._local.check = check

    def clear(self) -> None:
        self._local.check = None

    def check(self) -> None:
        check = getattr(self._local, "check", None)
        if check is not None:
            check()


class Clock(Protocol):
    def now_iso(self) -> str: ...


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_harness_session_id() -> str:
    return "hsess_" + uuid4().hex


def check_inline_size(field: str, value: str, maximum: int) -> None:
    if len(value.encode("utf-8")) > maximum:
        raise NativeAdapterError(
            ErrorCode.CONTENT_TOO_LARGE,
            f"{field} inline content exceeds {maximum} UTF-8 bytes",
            {"field": field, "max_inline_bytes": maximum},
        )


STATUS_STARTING = "STARTING"
STATUS_RUNNING = "RUNNING"
STATUS_INTERRUPTING = "INTERRUPTING"
STATUS_ENDED = "ENDED"
STATUS_ERRORED = "ERRORED"
STEER_TIMING_IMMEDIATE = "IMMEDIATE"
STEER_TIMING_NEXT_TURN_BOUNDARY = "NEXT_TURN_BOUNDARY"
COMMAND_VERBS = frozenset({"send_turn", "steer", "interrupt", "end"})
_TRANSITIONS = frozenset({
    (STATUS_STARTING, STATUS_RUNNING), (STATUS_STARTING, STATUS_ERRORED),
    (STATUS_RUNNING, STATUS_INTERRUPTING), (STATUS_RUNNING, STATUS_ENDED),
    (STATUS_RUNNING, STATUS_ERRORED), (STATUS_INTERRUPTING, STATUS_RUNNING),
    (STATUS_INTERRUPTING, STATUS_ENDED), (STATUS_INTERRUPTING, STATUS_ERRORED),
})


def can_transition_session(current: str, target: str) -> bool:
    return (current, target) in _TRANSITIONS


@dataclass(frozen=True, slots=True)
class HarnessCapabilities:
    send_only: bool
    steer_timing: str | None
    interrupt_requires_settle_wait: bool
    multiplexes_sessions: bool
    observes_session_end: bool


@dataclass(slots=True)
class HarnessSession:
    session_id: str
    harness_kind: str
    owning_agent_id: str
    status: str
    capabilities: HarnessCapabilities
    started_at: str
    ended_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    compatibility_report: dict[str, Any] = field(default_factory=dict)
    endpoint_id: str | None = None
    workspace_id: str | None = None
    presence_session_id: str | None = None
    lifecycle_state: str = "legacy_unlinked"
    connection_id: str | None = None
    owner_epoch: int | None = None

    def __post_init__(self) -> None:
        if self.harness_kind not in {"pi", "codex", "claude_code"}:
            raise NativeAdapterError(ErrorCode.VALIDATION_ERROR,
                                     "unknown harness kind", {})
        if self.status not in {STATUS_STARTING, STATUS_RUNNING,
                               STATUS_INTERRUPTING, STATUS_ENDED, STATUS_ERRORED}:
            raise NativeAdapterError(ErrorCode.VALIDATION_ERROR,
                                     "invalid session status", {})


@dataclass(frozen=True, slots=True)
class HarnessEvent:
    session_id: str
    harness_kind: str
    kind: str
    native_event: str
    occurred_at: str
    payload: dict[str, Any] = field(default_factory=dict)
    thread_id: str | None = None
    turn_id: str | None = None
    event_id: str | None = None
    sequence: int | None = None
    origin: str = "native"
    operation_id: str | None = None
    attempt_id: str | None = None
    owner_epoch: int | None = None
    delivery_phase: str | None = None
    output_text: str | None = None
    output_snapshot: bool = False
    native_approval: dict[str, Any] | None = None
    delivery_outcome: str | None = None

    def __post_init__(self) -> None:
        if self.harness_kind not in {"pi", "codex", "claude_code"}:
            raise NativeAdapterError(ErrorCode.VALIDATION_ERROR,
                                     "unknown harness kind", {})
        if self.kind not in {"turn_started", "output_delta", "turn_completed",
                             "tool_activity", "error"} or not self.native_event:
            raise NativeAdapterError(ErrorCode.VALIDATION_ERROR,
                                     "invalid native event", {})
        if self.origin not in {"native", "nexus"}:
            raise NativeAdapterError(ErrorCode.VALIDATION_ERROR,
                                     "invalid event origin", {})
        if self.delivery_phase not in {None, "started", "progress", "terminal"}:
            raise NativeAdapterError(ErrorCode.VALIDATION_ERROR,
                                     "invalid delivery phase", {})
        if self.delivery_outcome not in {None, "success", "failed", "interrupted"}:
            raise NativeAdapterError(ErrorCode.VALIDATION_ERROR,
                                     "invalid delivery outcome", {})


@dataclass(frozen=True, slots=True)
class HarnessCommand:
    session_id: str
    verb: str
    payload: dict[str, Any] = field(default_factory=dict)
    operation_id: str | None = None
    attempt_id: str | None = None
    owner_epoch: int | None = None
    external_work_channel: bool = False
    expected_operation_id: str | None = None
    expected_turn_id: str | None = None

    def __post_init__(self) -> None:
        if self.verb not in COMMAND_VERBS:
            raise NativeAdapterError(ErrorCode.VALIDATION_ERROR,
                                     "unknown native command verb", {})


@dataclass(frozen=True, slots=True)
class EndpointCapabilities:
    conversation: bool = False
    managed_work: bool = False
    context_without_execution: bool = False
    events: bool = False
    observes_acceptance: bool = False
    correlated_results: bool = False
    native_deduplication: bool = False
    native_replay: bool = False
    multiplexing: bool = False
    steer_timing: str | None = None
    interrupt: bool = False
    interrupt_requires_settle: bool = False
    observes_stop: bool = False
    approvals: bool = False

    def restrict(self, allowed: EndpointCapabilities) -> EndpointCapabilities:
        return EndpointCapabilities(**{
            item.name: (self.steer_timing if self.steer_timing == allowed.steer_timing else None)
            if item.name == "steer_timing" else
            bool(self.interrupt_requires_settle or allowed.interrupt_requires_settle)
            if item.name == "interrupt_requires_settle" else
            bool(getattr(self, item.name) and getattr(allowed, item.name))
            for item in fields(self)
        })

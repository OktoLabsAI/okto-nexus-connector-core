"""Pure R4 channel and lane ACK correlation, without runtime effects."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from .frame_codec_r4 import decode_r4_frame
from .models import CoreError
from .protocol import canonical_json


@dataclass(frozen=True, slots=True)
class R4ReconcileAttempt:
    reconcile_id: str
    server_id: str
    executor_id: str
    connection_id: str
    connection_generation: int
    boot_id: str


@dataclass(frozen=True, slots=True)
class R4ControlProjection:
    reconcile_id: str
    server_id: str
    executor_id: str
    connection_id: str
    connection_generation: int
    boot_id: str
    recovery_remaining: bool
    ready_lane_ids: tuple[str, ...]
    session_lease_requirements: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.recovery_remaining


@dataclass(frozen=True, slots=True)
class R4AttachAttempt:
    attach_request_id: str
    server_id: str
    executor_id: str
    binding_id: str
    agent_id: str
    credential_epoch: int
    authorization_revision: int
    configuration_revision: int
    connection_id: str
    connection_generation: int
    boot_id: str
    sent_at_monotonic: float


@dataclass(frozen=True, slots=True)
class R4LaneProjection:
    attach_request_id: str
    server_id: str
    executor_id: str
    binding_id: str
    agent_id: str
    credential_epoch: int
    authorization_revision: int
    configuration_revision: int
    connection_id: str
    connection_generation: int
    boot_id: str
    sent_at_monotonic: float
    deadline_monotonic: float


def _validated(frame: Mapping[str, Any], kind: str) -> dict[str, Any]:
    if not isinstance(frame, Mapping):
        raise CoreError("VALIDATION_ERROR", "r4_control", retry_safe=True)
    try:
        parsed = decode_r4_frame(canonical_json(dict(frame)))
    except (ValueError, TypeError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "r4_control", retry_safe=True) from exc
    if parsed["type"] != kind:
        raise CoreError("VALIDATION_ERROR", "r4_control", retry_safe=True)
    return parsed


def reduce_r4_reconcile_accepted(attempt: R4ReconcileAttempt,
                                 frame: Mapping[str, Any]
                                 ) -> R4ControlProjection:
    """A committed reconcile ACK establishes control state, never a lease."""
    if not isinstance(attempt, R4ReconcileAttempt) or not attempt.boot_id:
        raise CoreError("VALIDATION_ERROR", "r4_control")
    parsed = _validated(frame, "reconcile.accepted")
    for field in ("reconcile_id", "server_id", "executor_id",
                  "connection_id", "connection_generation"):
        if parsed[field] != getattr(attempt, field):
            raise CoreError("STALE_GENERATION", "r4_control")
    return R4ControlProjection(
        attempt.reconcile_id, attempt.server_id, attempt.executor_id,
        attempt.connection_id, attempt.connection_generation,
        attempt.boot_id, parsed["recovery_remaining"],
        tuple(parsed["ready_lane_ids"]),
        tuple(parsed["session_lease_requirements"]),
    )


def reduce_r4_binding_attached(attempt: R4AttachAttempt,
                               frame: Mapping[str, Any], *,
                               received_at_monotonic: float
                               ) -> R4LaneProjection:
    """Correlate one attach ACK and anchor its ticket TTL before send."""
    if (not isinstance(attempt, R4AttachAttempt) or not attempt.boot_id or
            type(attempt.sent_at_monotonic) not in (int, float) or
            type(received_at_monotonic) not in (int, float) or
            not math.isfinite(attempt.sent_at_monotonic) or
            attempt.sent_at_monotonic < 0 or
            not math.isfinite(received_at_monotonic) or
            received_at_monotonic < attempt.sent_at_monotonic):
        raise CoreError("VALIDATION_ERROR", "r4_control")
    parsed = _validated(frame, "binding.attached")
    for field in ("attach_request_id", "server_id", "executor_id",
                  "binding_id", "agent_id", "credential_epoch",
                  "authorization_revision", "configuration_revision",
                  "connection_id", "connection_generation"):
        if parsed[field] != getattr(attempt, field):
            raise CoreError("STALE_GENERATION", "r4_control")
    deadline = attempt.sent_at_monotonic + parsed["expires_in"]
    if received_at_monotonic >= deadline:
        raise CoreError("LEASE_EXPIRED", "r4_control")
    return R4LaneProjection(
        attempt.attach_request_id, attempt.server_id, attempt.executor_id,
        attempt.binding_id, attempt.agent_id, attempt.credential_epoch,
        attempt.authorization_revision, attempt.configuration_revision,
        attempt.connection_id, attempt.connection_generation,
        attempt.boot_id, attempt.sent_at_monotonic, deadline,
    )


def r4_lane_ready(control: R4ControlProjection, lane: R4LaneProjection, *,
                  boot_id: str, now_monotonic: float) -> bool:
    """Channel/lane condition only; a session still needs its Core lease."""
    return (isinstance(control, R4ControlProjection) and control.ready and
            isinstance(lane, R4LaneProjection) and
            lane.server_id == control.server_id and
            lane.executor_id == control.executor_id and
            lane.connection_id == control.connection_id and
            lane.connection_generation == control.connection_generation and
            lane.boot_id == control.boot_id == boot_id and
            lane.binding_id in control.ready_lane_ids and
            type(now_monotonic) in (int, float) and
            math.isfinite(now_monotonic) and
            0 <= now_monotonic < lane.deadline_monotonic)

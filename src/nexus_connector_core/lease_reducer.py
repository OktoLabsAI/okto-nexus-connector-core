"""Pure NXL r3 lease request/grant projection; never a standalone authority.

The trusted host authorizes each request and supplies a new unpredictable
lease_id per attempt. A grant echoes that ID. It cannot extend a prior grant
on replay, and the host must reconcile/revalidate after reboot or expiry.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from typing import Any, Mapping

from .frame_codec import decode_frame
from .models import CoreError
from .protocol import CONTRACT_REVISION, PROTOCOL_MAJOR, canonical_json


@dataclass(frozen=True, slots=True)
class LeaseRenewalAttempt:
    server_id: str
    executor_id: str
    binding_id: str
    agent_id: str
    session_id: str
    lease_id: str
    connection_generation: int
    authorization_revision: int
    expected_owner_generation: int
    boot_id: str
    sent_at_monotonic: float


@dataclass(frozen=True, slots=True)
class LeaseProjection:
    server_id: str
    executor_id: str
    binding_id: str
    agent_id: str
    session_id: str
    lease_id: str
    connection_generation: int
    authorization_revision: int
    session_owner_generation: int
    boot_id: str
    sent_at_monotonic: float
    deadline_monotonic: float
    grant_digest: str
    revoked: bool = False


def _finite_time(value: object) -> bool:
    return (type(value) in (int, float) and 0 <= value <= 1e15 and
            math.isfinite(value))


def _validated(frame: Mapping[str, Any], kind: str) -> dict[str, Any]:
    if not isinstance(frame, Mapping):
        raise CoreError("VALIDATION_ERROR", "lease_reducer", retry_safe=True)
    try:
        parsed = decode_frame(canonical_json(dict(frame)))
    except (TypeError, ValueError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "lease_reducer", retry_safe=True) from exc
    if parsed["type"] != kind:
        raise CoreError("VALIDATION_ERROR", "lease_reducer", retry_safe=True)
    return parsed


def lease_renew_frame(attempt: LeaseRenewalAttempt) -> dict[str, Any]:
    """Produce a schema-checked request from a host-authorized attempt."""
    if (not isinstance(attempt, LeaseRenewalAttempt) or
            not isinstance(attempt.boot_id, str) or not attempt.boot_id or
            not _finite_time(attempt.sent_at_monotonic) or
            type(attempt.expected_owner_generation) is not int or
            attempt.expected_owner_generation < 0):
        raise CoreError("VALIDATION_ERROR", "lease_renew")
    return _validated({
        "protocol_major": PROTOCOL_MAJOR,
        "contract_revision": CONTRACT_REVISION,
        "type": "lease.renew", "server_id": attempt.server_id,
        "executor_id": attempt.executor_id, "binding_id": attempt.binding_id,
        "agent_id": attempt.agent_id, "session_id": attempt.session_id,
        "lease_id": attempt.lease_id,
        "connection_generation": attempt.connection_generation,
        "authorization_revision": attempt.authorization_revision,
    }, "lease.renew")


def lease_granted_frame(attempt: LeaseRenewalAttempt, *, valid_for_ms: int,
                        session_owner_generation: int) -> dict[str, Any]:
    """Produce a schema-checked grant fixture/Server-side frame."""
    lease_renew_frame(attempt)
    return _validated({
        "protocol_major": PROTOCOL_MAJOR,
        "contract_revision": CONTRACT_REVISION,
        "type": "lease.granted", "server_id": attempt.server_id,
        "executor_id": attempt.executor_id, "binding_id": attempt.binding_id,
        "agent_id": attempt.agent_id, "session_id": attempt.session_id,
        "lease_id": attempt.lease_id, "valid_for_ms": valid_for_ms,
        "session_owner_generation": session_owner_generation,
        "authorization_revision": attempt.authorization_revision,
    }, "lease.granted")


def reduce_lease_grant(previous: LeaseProjection | None,
                       attempt: LeaseRenewalAttempt,
                       frame: Mapping[str, Any], *,
                       received_at_monotonic: float,
                       safety_seconds: float = 0.5) -> LeaseProjection:
    """Correlate one grant and conservatively compute a local deadline.

    The deadline is based on send time, not receive time; round-trip delay
    cannot enlarge it. No new work is authorized merely by this projection.
    """
    request = lease_renew_frame(attempt)
    grant = _validated(frame, "lease.granted")
    if (not _finite_time(received_at_monotonic) or
            received_at_monotonic < attempt.sent_at_monotonic or
            not _finite_time(safety_seconds)):
        raise CoreError("VALIDATION_ERROR", "lease_reducer")
    for field in ("server_id", "executor_id", "binding_id", "agent_id",
                  "session_id", "lease_id", "authorization_revision"):
        if grant[field] != request[field]:
            raise CoreError("STALE_GENERATION", "lease_reducer")
    if grant["session_owner_generation"] != attempt.expected_owner_generation:
        raise CoreError("STALE_GENERATION", "lease_reducer")
    digest = hashlib.sha256(canonical_json(grant)).hexdigest()
    if previous is not None:
        if previous.revoked:
            raise CoreError("AGENT_REVOKED", "lease_reducer")
        old_scope = (previous.server_id, previous.executor_id,
                     previous.binding_id, previous.agent_id, previous.session_id)
        new_scope = (attempt.server_id, attempt.executor_id,
                     attempt.binding_id, attempt.agent_id, attempt.session_id)
        if old_scope != new_scope or previous.boot_id != attempt.boot_id:
            raise CoreError("LEASE_REVALIDATION_REQUIRED", "lease_reducer")
        if attempt.lease_id == previous.lease_id:
            if digest != previous.grant_digest:
                raise CoreError("LEASE_CONFLICT", "lease_reducer")
            return previous
        if (received_at_monotonic >= previous.deadline_monotonic or
                attempt.sent_at_monotonic <= previous.sent_at_monotonic or
                attempt.connection_generation < previous.connection_generation or
                attempt.authorization_revision < previous.authorization_revision or
                attempt.expected_owner_generation != previous.session_owner_generation):
            raise CoreError("LEASE_REVALIDATION_REQUIRED", "lease_reducer")
    deadline = (attempt.sent_at_monotonic +
                grant["valid_for_ms"] / 1000 - safety_seconds)
    if deadline <= received_at_monotonic:
        raise CoreError("LEASE_EXPIRED", "lease_reducer")
    return LeaseProjection(
        attempt.server_id, attempt.executor_id, attempt.binding_id,
        attempt.agent_id, attempt.session_id, attempt.lease_id,
        attempt.connection_generation, attempt.authorization_revision,
        attempt.expected_owner_generation, attempt.boot_id,
        attempt.sent_at_monotonic, deadline, digest)


def revoke_lease_projection(previous: LeaseProjection) -> LeaseProjection:
    """Apply an already host-verified revocation; never restore locally."""
    if not isinstance(previous, LeaseProjection):
        raise CoreError("VALIDATION_ERROR", "lease_reducer")
    return replace(previous, revoked=True)


def lease_active(projection: LeaseProjection, *, boot_id: str,
                 now_monotonic: float) -> bool:
    """Local time gate only; host authorization and ownership remain required."""
    return (isinstance(projection, LeaseProjection) and not projection.revoked and
            boot_id == projection.boot_id and _finite_time(now_monotonic) and
            now_monotonic < projection.deadline_monotonic)

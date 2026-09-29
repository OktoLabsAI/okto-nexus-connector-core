"""Pure R4 lease correlation and local deadline projection.

A host must persist and install an ExecutionContext in Core before it emits
lease.applied. This reducer tracks the wire proof; it grants no native effect.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
from typing import Any, Mapping

from .frame_codec_r4 import R4_PREVIEW_REVISION, decode_r4_frame
from .models import CoreError
from .protocol import canonical_json


@dataclass(frozen=True, slots=True)
class R4LeaseAttempt:
    request_id: str
    grant_id: str
    expected_lease_serial: int
    scope: Mapping[str, Any]
    connection_id: str
    connection_generation: int
    purpose: str
    boot_id: str
    sent_at_monotonic: float


@dataclass(frozen=True, slots=True)
class R4LeaseProjection:
    request_id: str
    lease_id: str
    lease_serial: int
    grant_id: str
    scope: Mapping[str, Any]
    connection_id: str
    connection_generation: int
    allowed_actions: tuple[str, ...]
    boot_id: str
    sent_at_monotonic: float
    deadline_monotonic: float
    grant_digest: str
    applied: bool = False
    revoked: bool = False


def _finite_time(value: object) -> bool:
    return (type(value) in (int, float) and 0 <= value <= 1e15 and
            math.isfinite(value))


def _validated(frame: Mapping[str, Any], kind: str) -> dict[str, Any]:
    if not isinstance(frame, Mapping):
        raise CoreError("VALIDATION_ERROR", "r4_lease", retry_safe=True)
    try:
        parsed = decode_r4_frame(canonical_json(dict(frame)))
    except (ValueError, TypeError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "r4_lease", retry_safe=True) from exc
    if parsed["type"] != kind:
        raise CoreError("VALIDATION_ERROR", "r4_lease", retry_safe=True)
    return parsed


def r4_lease_renew_frame(attempt: R4LeaseAttempt) -> dict[str, Any]:
    """Build a schema-checked request after the caller captures monotonic t0."""
    if (not isinstance(attempt, R4LeaseAttempt) or
            not isinstance(attempt.boot_id, str) or not attempt.boot_id or
            not _finite_time(attempt.sent_at_monotonic)):
        raise CoreError("VALIDATION_ERROR", "r4_lease")
    return _validated({
        "protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
        "type": "lease.renew", "request_id": attempt.request_id,
        "grant_id": attempt.grant_id,
        "expected_lease_serial": attempt.expected_lease_serial,
        "scope": dict(attempt.scope),
        "connection_id": attempt.connection_id,
        "connection_generation": attempt.connection_generation,
        "purpose": attempt.purpose,
    }, "lease.renew")


def reduce_r4_lease_grant(previous: R4LeaseProjection | None,
                          attempt: R4LeaseAttempt,
                          frame: Mapping[str, Any], *,
                          received_at_monotonic: float,
                          safety_seconds: float = 0.5) -> R4LeaseProjection:
    """Correlate a grant without treating receipt as Core application."""
    request = r4_lease_renew_frame(attempt)
    grant = _validated(frame, "lease.granted")
    if (not _finite_time(received_at_monotonic) or
            received_at_monotonic < attempt.sent_at_monotonic or
            not _finite_time(safety_seconds)):
        raise CoreError("VALIDATION_ERROR", "r4_lease")
    for field in ("request_id", "grant_id", "scope"):
        if grant[field] != request[field]:
            raise CoreError("STALE_GENERATION", "r4_lease")
    if grant["lease_serial"] != attempt.expected_lease_serial + 1:
        raise CoreError("STALE_GENERATION", "r4_lease")
    digest = "sha256:" + hashlib.sha256(canonical_json(grant)).hexdigest()
    if previous is not None:
        if previous.revoked:
            raise CoreError("AGENT_REVOKED", "r4_lease")
        if (previous.boot_id != attempt.boot_id or
                previous.scope != attempt.scope or
                previous.grant_id != attempt.grant_id):
            raise CoreError("LEASE_REVALIDATION_REQUIRED", "r4_lease")
        if previous.request_id == attempt.request_id:
            if digest != previous.grant_digest:
                raise CoreError("LEASE_CONFLICT", "r4_lease")
            return previous
        if (attempt.expected_lease_serial != previous.lease_serial or
                attempt.sent_at_monotonic <= previous.sent_at_monotonic or
                received_at_monotonic >= previous.deadline_monotonic or
                attempt.connection_generation < previous.connection_generation):
            raise CoreError("LEASE_REVALIDATION_REQUIRED", "r4_lease")
    deadline = (attempt.sent_at_monotonic +
                grant["valid_for_ms"] / 1000 - safety_seconds)
    if deadline <= received_at_monotonic:
        raise CoreError("LEASE_EXPIRED", "r4_lease")
    return R4LeaseProjection(
        request_id=attempt.request_id, lease_id=grant["lease_id"],
        lease_serial=grant["lease_serial"], grant_id=grant["grant_id"],
        scope=dict(grant["scope"]), connection_id=attempt.connection_id,
        connection_generation=attempt.connection_generation,
        allowed_actions=tuple(grant["allowed_actions"]),
        boot_id=attempt.boot_id, sent_at_monotonic=attempt.sent_at_monotonic,
        deadline_monotonic=deadline, grant_digest=digest,
    )


def reduce_r4_lease_applied(previous: R4LeaseProjection,
                            frame: Mapping[str, Any]) -> R4LeaseProjection:
    """Record a host-reported Core application ACK for the same grant."""
    if not isinstance(previous, R4LeaseProjection):
        raise CoreError("VALIDATION_ERROR", "r4_lease")
    applied = _validated(frame, "lease.applied")
    for field in ("request_id", "lease_id", "lease_serial", "grant_id",
                  "scope", "connection_id", "connection_generation"):
        if applied[field] != getattr(previous, field):
            raise CoreError("STALE_GENERATION", "r4_lease")
    if applied["application_stage"] == "REVOKED":
        return replace(previous, revoked=True, applied=False)
    if previous.revoked:
        raise CoreError("AGENT_REVOKED", "r4_lease")
    return replace(previous, applied=True)


def r4_lease_productive(projection: R4LeaseProjection, *, boot_id: str,
                        now_monotonic: float, action: str) -> bool:
    """Local lease condition; host authority/ownership are checked separately."""
    return (isinstance(projection, R4LeaseProjection) and
            projection.applied and not projection.revoked and
            projection.boot_id == boot_id and
            _finite_time(now_monotonic) and
            now_monotonic < projection.deadline_monotonic and
            action in projection.allowed_actions)

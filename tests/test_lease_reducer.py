from dataclasses import replace
from copy import deepcopy

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.frame_codec import decode_frame, encode_frame
from nexus_connector_core.lease_reducer import (
    LeaseRenewalAttempt, lease_active, lease_granted_frame,
    lease_renew_frame, reduce_lease_grant, revoke_lease_projection,
)


def _attempt(lease_id="attempt-one", sent=10.0, boot="boot-one",
             generation=1, revision=2, owner=3):
    return LeaseRenewalAttempt("server", "executor", "binding", "agent",
                               "session", lease_id, generation, revision,
                               owner, boot, sent)


def test_producer_frames_round_trip_and_conservative_deadline():
    attempt = _attempt()
    request = lease_renew_frame(attempt)
    grant = lease_granted_frame(attempt, valid_for_ms=2000,
                                session_owner_generation=3)
    assert decode_frame(encode_frame(request).rstrip(b"\n")) == request
    assert decode_frame(encode_frame(grant).rstrip(b"\n")) == grant
    state = reduce_lease_grant(None, attempt, grant, received_at_monotonic=10.25)
    assert state.deadline_monotonic == 11.5
    assert lease_active(state, boot_id="boot-one", now_monotonic=11.49)
    assert not lease_active(state, boot_id="boot-one", now_monotonic=11.5)
    assert not lease_active(state, boot_id="other-boot", now_monotonic=10.5)


def test_replay_does_not_extend_and_new_attempt_does():
    first_attempt = _attempt()
    first_grant = lease_granted_frame(first_attempt, valid_for_ms=2000,
                                      session_owner_generation=3)
    first = reduce_lease_grant(None, first_attempt, first_grant,
                               received_at_monotonic=10.2)
    assert reduce_lease_grant(first, first_attempt, first_grant,
                              received_at_monotonic=11.2) is first
    next_attempt = _attempt("attempt-two", sent=11.0, generation=2)
    next_grant = lease_granted_frame(next_attempt, valid_for_ms=2000,
                                     session_owner_generation=3)
    renewed = reduce_lease_grant(first, next_attempt, next_grant,
                                 received_at_monotonic=11.1)
    assert renewed.deadline_monotonic == 12.5
    with pytest.raises(CoreError, match="LEASE_REVALIDATION_REQUIRED"):
        reduce_lease_grant(renewed, _attempt("attempt-three", sent=12.0),
                           lease_granted_frame(_attempt("attempt-three", sent=12.0),
                                               valid_for_ms=2000,
                                               session_owner_generation=3),
                           received_at_monotonic=12.6)


def test_mismatched_or_changed_grant_fails_closed():
    attempt = _attempt()
    grant = lease_granted_frame(attempt, valid_for_ms=2000,
                                session_owner_generation=3)
    for name, value in (("lease_id", "wrong"), ("agent_id", "other"),
                        ("authorization_revision", 3),
                        ("session_owner_generation", 4)):
        changed = deepcopy(grant)
        changed[name] = value
        with pytest.raises(CoreError, match="STALE_GENERATION"):
            reduce_lease_grant(None, attempt, changed,
                               received_at_monotonic=10.2)
    first = reduce_lease_grant(None, attempt, grant, received_at_monotonic=10.2)
    changed = deepcopy(grant)
    changed["valid_for_ms"] = 3000
    with pytest.raises(CoreError, match="LEASE_CONFLICT"):
        reduce_lease_grant(first, attempt, changed, received_at_monotonic=10.3)


def test_reboot_revocation_and_generation_fences():
    attempt = _attempt()
    grant = lease_granted_frame(attempt, valid_for_ms=3000,
                                session_owner_generation=3)
    first = reduce_lease_grant(None, attempt, grant, received_at_monotonic=10.1)
    for next_attempt in (
        _attempt("new", sent=11.0, boot="reboot"),
        _attempt("new", sent=11.0, generation=0),
        _attempt("new", sent=11.0, revision=1),
        _attempt("new", sent=11.0, owner=4),
    ):
        next_grant = lease_granted_frame(
            next_attempt, valid_for_ms=3000,
            session_owner_generation=next_attempt.expected_owner_generation)
        with pytest.raises(CoreError, match="LEASE_REVALIDATION_REQUIRED"):
            reduce_lease_grant(first, next_attempt, next_grant,
                               received_at_monotonic=11.1)
    revoked = revoke_lease_projection(first)
    assert not lease_active(revoked, boot_id="boot-one", now_monotonic=11.0)
    next_attempt = _attempt("new", sent=11.0)
    with pytest.raises(CoreError, match="AGENT_REVOKED"):
        reduce_lease_grant(revoked, next_attempt,
                           lease_granted_frame(next_attempt, valid_for_ms=3000,
                                               session_owner_generation=3),
                           received_at_monotonic=11.1)


def test_rtt_window_and_invalid_times_are_not_authority():
    attempt = _attempt()
    grant = lease_granted_frame(attempt, valid_for_ms=1000,
                                session_owner_generation=3)
    with pytest.raises(CoreError, match="LEASE_EXPIRED"):
        reduce_lease_grant(None, attempt, grant, received_at_monotonic=10.5)
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        reduce_lease_grant(None, attempt, grant, received_at_monotonic=float("nan"))
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        lease_renew_frame(replace(attempt, sent_at_monotonic=float("inf")))
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        lease_granted_frame(attempt, valid_for_ms=120001,
                            session_owner_generation=3)

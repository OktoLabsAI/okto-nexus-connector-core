"""R4 lease request/reply correlation without implicit Core application."""

from __future__ import annotations

from dataclasses import replace

import pytest

from nexus_connector_core import (
    CoreError, R4LeaseAttempt, R4_PREVIEW_REVISION,
    r4_lease_renew_frame, reduce_r4_lease_grant,
    reduce_r4_lease_applied, r4_lease_productive,
)


def _scope() -> dict:
    return {
        "server_id": "srv", "executor_id": "exe", "binding_id": "binding",
        "agent_id": "agent", "workspace_id": "ws",
        "workspace_binding_id": "wxb", "session_id": "session",
        "session_owner_generation": 1, "authorization_revision": 1,
        "configuration_revision": 1, "binding_revision": 1,
        "credential_epoch": 1,
    }


def _attempt(**changes) -> R4LeaseAttempt:
    fields = dict(request_id="request-1", grant_id="grant",
                  expected_lease_serial=0, scope=_scope(),
                  connection_id="connection", connection_generation=1,
                  purpose="initial", boot_id="boot", sent_at_monotonic=10.0)
    fields.update(changes)
    return R4LeaseAttempt(**fields)


def _grant(attempt: R4LeaseAttempt, *, duration: int = 120000) -> dict:
    return {"protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
            "type": "lease.granted", "request_id": attempt.request_id,
            "lease_id": "lease-1", "lease_serial": 1,
            "grant_id": attempt.grant_id, "scope": dict(attempt.scope),
            "allowed_actions": ["runtime.open", "turn.submit"],
            "valid_for_ms": duration}


def _applied(projection, *, stage="INSTALLED") -> dict:
    return {"protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
            "type": "lease.applied", "request_id": projection.request_id,
            "lease_id": projection.lease_id,
            "lease_serial": projection.lease_serial,
            "grant_id": projection.grant_id, "scope": dict(projection.scope),
            "connection_id": projection.connection_id,
            "connection_generation": projection.connection_generation,
            "application_stage": stage}


def test_reply_deadline_uses_send_time_and_needs_separate_application():
    attempt = _attempt()
    request = r4_lease_renew_frame(attempt)
    assert "sent_at_monotonic" not in request
    assert request["request_id"] == "request-1"
    projection = reduce_r4_lease_grant(
        None, attempt, _grant(attempt), received_at_monotonic=11.0,
    )
    assert projection.deadline_monotonic == 129.5
    assert not r4_lease_productive(
        projection, boot_id="boot", now_monotonic=12.0,
        action="runtime.open")
    installed = reduce_r4_lease_applied(projection, _applied(projection))
    assert r4_lease_productive(
        installed, boot_id="boot", now_monotonic=12.0,
        action="runtime.open")
    assert not r4_lease_productive(
        installed, boot_id="boot", now_monotonic=12.0,
        action="approval.decide")
    assert not r4_lease_productive(
        installed, boot_id="boot-after-restart", now_monotonic=12.0,
        action="runtime.open")


def test_replay_cannot_reanchor_and_scope_mismatch_refused():
    attempt = _attempt()
    grant = _grant(attempt)
    first = reduce_r4_lease_grant(
        None, attempt, grant, received_at_monotonic=11.0)
    replay = reduce_r4_lease_grant(
        first, replace(attempt, sent_at_monotonic=20.0), grant,
        received_at_monotonic=21.0)
    assert replay is first
    altered = {**grant, "valid_for_ms": 119999}
    with pytest.raises(CoreError):
        reduce_r4_lease_grant(
            first, attempt, altered, received_at_monotonic=11.0)
    wrong_scope = {**grant, "scope": {**grant["scope"], "agent_id": "other"}}
    with pytest.raises(CoreError):
        reduce_r4_lease_grant(
            None, attempt, wrong_scope, received_at_monotonic=11.0)
    with pytest.raises(CoreError):
        reduce_r4_lease_grant(
            None, attempt, grant, received_at_monotonic=130.0)
    with pytest.raises(CoreError):
        reduce_r4_lease_grant(
            first, replace(attempt, boot_id="other-boot"), grant,
            received_at_monotonic=11.0)


def test_application_ack_must_match_connection_and_revocation_fences():
    attempt = _attempt()
    projection = reduce_r4_lease_grant(
        None, attempt, _grant(attempt), received_at_monotonic=11.0)
    wrong_connection = {**_applied(projection), "connection_generation": 2}
    with pytest.raises(CoreError):
        reduce_r4_lease_applied(projection, wrong_connection)
    revoked = reduce_r4_lease_applied(
        projection, _applied(projection, stage="REVOKED"))
    assert revoked.revoked and not revoked.applied
    assert not r4_lease_productive(
        revoked, boot_id="boot", now_monotonic=12.0,
        action="runtime.open")
    with pytest.raises(CoreError):
        reduce_r4_lease_applied(revoked, _applied(projection))

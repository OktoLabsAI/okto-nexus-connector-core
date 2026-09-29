"""R4 approval notifications preserve request identity without native effect."""

from __future__ import annotations

import pytest

from nexus_connector_core import (
    CoreError, R4_PREVIEW_REVISION, reduce_r4_approval_request,
    reduce_r4_approval_decision,
)


def _scope() -> dict:
    return {"server_id": "srv", "executor_id": "exe",
            "binding_id": "binding", "agent_id": "agent",
            "workspace_id": "ws", "workspace_binding_id": "wxb",
            "session_id": "session", "session_owner_generation": 1,
            "authorization_revision": 1, "configuration_revision": 1,
            "binding_revision": 1, "credential_epoch": 1,
            "connection_id": "control", "connection_generation": 1}


def _request(**changes) -> dict:
    frame = {"protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
             "type": "approval.request", **_scope(),
             "canonical_request_id": "request",
             "request_hash": "sha256:" + "a" * 64,
             "request_revision": 1, "kind": "native_approval",
             "expires_in": 60,
             "operational_request": {"request_hash": "sha256:" + "a" * 64,
                                     "native_request_id": "native"}}
    frame.update(changes)
    return frame


def _decision(**changes) -> dict:
    frame = {"protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
             "type": "approval.decision", **_scope(),
             "canonical_request_id": "request",
             "request_hash": "sha256:" + "a" * 64,
             "decision_id": "decision", "decision_revision": 1,
             "decision": "decline"}
    frame.update(changes)
    return frame


def test_request_and_decision_are_correlated_notifications():
    request = reduce_r4_approval_request(None, _request())
    assert reduce_r4_approval_request(request, _request()) is request
    with pytest.raises(CoreError):
        reduce_r4_approval_request(
            None, _request(operational_request={"request_hash":
                        "sha256:" + "b" * 64}))
    with pytest.raises(CoreError):
        reduce_r4_approval_decision(
            request, _decision(connection_generation=2))
    decided = reduce_r4_approval_decision(request, _decision())
    assert decided.decision == "decline"
    assert reduce_r4_approval_decision(decided, _decision()) is decided
    with pytest.raises(CoreError):
        reduce_r4_approval_decision(decided, _decision(decision="accept"))
    with pytest.raises(CoreError):
        reduce_r4_approval_request(
            decided, _request(request_revision=2))

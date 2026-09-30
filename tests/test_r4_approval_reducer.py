"""R4 approval notifications preserve request identity without native effect."""

from __future__ import annotations

import pytest

from nexus_connector_core import (
    CoreError, R4_PREVIEW_REVISION, reduce_r4_approval_request,
    reduce_r4_approval_decision, r4_operational_request_hash,
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
    operational = {"schema_version": 1, "request_hash": "a" * 64,
                   "request_id": "native",
                   "method": "item/commandExecution/requestApproval",
                   "params": {"turnId": "turn", "itemId": "item"}}
    frame = {"protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
             "type": "approval.request", **_scope(),
             "canonical_request_id": "request",
             "request_hash": r4_operational_request_hash(operational),
             "request_revision": 1, "kind": "native_approval",
             "expires_in": 60,
             "operational_request": operational}
    frame.update(changes)
    return frame


def _decision(**changes) -> dict:
    frame = {"protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
             "type": "approval.decision", **_scope(),
             "canonical_request_id": "request",
             "request_hash": _request()["request_hash"],
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
    changed = _request()
    changed["operational_request"]["params"]["itemId"] = "changed"
    with pytest.raises(CoreError, match="OPERATION_CONFLICT"):
        reduce_r4_approval_request(request, changed)
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

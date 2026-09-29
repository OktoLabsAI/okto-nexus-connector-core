"""The R4 transport hash cannot masquerade as the Core journal hash."""

from dataclasses import replace

import pytest

from nexus_connector_core import (
    CoreError, ExecutionContext, Operation, OperationReceipt,
    R4_PREVIEW_REVISION, project_r4_turn_receipt,
    r4_submit_intent_hash,
)
from nexus_connector_core.protocol import intent_hash


def _frame():
    frame = {
        "protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
        "type": "operation.submit", "server_id": "server",
        "executor_id": "executor", "binding_id": "binding",
        "agent_id": "agent", "workspace_id": "workspace",
        "workspace_binding_id": "workspace-binding",
        "session_id": "session", "session_owner_generation": 1,
        "authorization_revision": 1, "configuration_revision": 1,
        "binding_revision": 1, "credential_epoch": 1,
        "connection_id": "connection", "connection_generation": 1,
        "grant_id": "grant", "operation_id": "operation",
        "action": "turn.submit", "payload": {"text": "Hello",
                                              "delivery_id": "delivery"},
    }
    frame["intent_hash"] = r4_submit_intent_hash(frame)
    return frame


def test_r4_turn_receipt_projects_distinct_hashes_after_core_proof():
    frame = _frame()
    context = ExecutionContext(
        "server", "executor", "binding", "agent", "workspace",
        1, 1, 1, 100.0, frozenset({"turn.submit"}),
    )
    semantic = Operation("operation", "session", "turn.submit",
                         {"text": "Hello"})
    receipt = OperationReceipt(
        "operation", intent_hash(semantic, context), "RECEIVED_DURABLE",
        False, True, "session",
    )
    assert receipt.intent_hash != frame["intent_hash"]
    projected = project_r4_turn_receipt(
        frame, receipt, context, receipt_revision=1)
    assert projected["intent_hash"] == frame["intent_hash"]
    assert projected["operation_id"] == receipt.operation_id
    assert projected["stage"] == receipt.stage

    changed = {**frame, "payload": {"text": "Different",
                                     "delivery_id": "delivery"}}
    changed["intent_hash"] = r4_submit_intent_hash(changed)
    with pytest.raises(CoreError) as altered:
        project_r4_turn_receipt(changed, receipt, context,
                                receipt_revision=1)
    assert altered.value.code == "OPERATION_CONFLICT"
    with pytest.raises(CoreError) as stale:
        project_r4_turn_receipt(frame, receipt,
                                replace(context, configuration_revision=2),
                                receipt_revision=1)
    assert stale.value.code == "SCOPE_MISMATCH"
    with pytest.raises(CoreError):
        project_r4_turn_receipt(frame, replace(receipt, operation_id="other"),
                                context, receipt_revision=1)

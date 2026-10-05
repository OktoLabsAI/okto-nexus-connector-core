"""The R4 transport hash cannot masquerade as the Core journal hash."""

from dataclasses import replace

import pytest

from nexus_connector_core import (
    CoreError, ExecutionContext, InstallationCandidate, LaunchIntent,
    Operation, OperationReceipt, PreparedLaunch, installation_ref,
    R4_PREVIEW_REVISION, project_r4_open_receipt, project_r4_turn_receipt,
    project_r4_steer_receipt, project_r4_interrupt_receipt,
    project_r4_close_receipt,
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


def test_r4_open_receipt_proves_core_launch_and_selected_installation():
    frame = _frame()
    candidate = InstallationCandidate(
        "codex_app_server", "C:/synthetic-codex.exe", "fingerprint",
        "explicit", "selected")
    frame["action"] = "runtime.open"
    frame["payload"] = {
        "adapter_id": "codex_app_server",
        "candidate_ref": installation_ref(
            candidate.adapter_id, candidate.executable),
        "inventory_revision": "sha256:" + "b" * 64,
        "realization_ref": "realization", "realization_revision": 1,
        "profile_revision": 3, "mode": "managed",
    }
    frame["intent_hash"] = r4_submit_intent_hash(frame)
    context = ExecutionContext(
        "server", "executor", "binding", "agent", "workspace",
        1, 1, 1, 100.0, frozenset({"runtime.open"}),
    )
    prepared = PreparedLaunch(
        LaunchIntent("agent", "workspace", "codex_app_server"),
        candidate, (candidate.executable,), "C:/workspace", "C:/workspace",
        "root-fingerprint", "profile-fingerprint", (),
    )
    semantic = Operation(
        "operation", "session", "runtime.open",
        {"adapter_id": "codex_app_server",
         "profile_fingerprint": "profile-fingerprint",
         "root_fingerprint": "root-fingerprint",
         "stream_epoch": "stream"},
    )
    receipt = OperationReceipt(
        "operation", intent_hash(semantic, context), "SUBMITTED",
        True, False, "session",
    )
    projected = project_r4_open_receipt(
        frame, receipt, context, prepared, stream_epoch="stream",
        receipt_revision=1)
    assert projected["intent_hash"] == frame["intent_hash"]
    assert projected["stage"] == "SUBMITTED"
    altered = {**frame, "payload": {**frame["payload"],
                                    "candidate_ref": "nexus-install-v1:" + "f" * 64}}
    altered["intent_hash"] = r4_submit_intent_hash(altered)
    with pytest.raises(CoreError) as drift:
        project_r4_open_receipt(
            altered, receipt, context, prepared, stream_epoch="stream",
            receipt_revision=1)
    assert drift.value.code == "PROFILE_DRIFT"
    assert drift.value.possible_effect and not drift.value.retry_safe
    with pytest.raises(CoreError) as semantic_drift:
        project_r4_open_receipt(
            frame, receipt, context, replace(
                prepared, profile_fingerprint="changed"),
            stream_epoch="stream", receipt_revision=1)
    assert semantic_drift.value.code == "OPERATION_CONFLICT"
    with pytest.raises(CoreError):
        project_r4_open_receipt(
            frame, receipt, context, prepared,
            stream_epoch="changed", receipt_revision=1)


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
    assert altered.value.possible_effect is True
    assert altered.value.retry_safe is False
    with pytest.raises(CoreError) as stale:
        project_r4_turn_receipt(frame, receipt,
                                replace(context, configuration_revision=2),
                                receipt_revision=1)
    assert stale.value.code == "SCOPE_MISMATCH"
    with pytest.raises(CoreError):
        project_r4_turn_receipt(frame, replace(receipt, operation_id="other"),
                                context, receipt_revision=1)


def test_r4_steer_receipt_requires_matching_core_semantic_and_turn_target():
    frame = _frame()
    frame["action"] = "turn.steer"
    frame["payload"] = {"text": "Change direction"}
    frame["expected_turn_id"] = "turn-1"
    frame["intent_hash"] = r4_submit_intent_hash(frame)
    context = ExecutionContext(
        "server", "executor", "binding", "agent", "workspace",
        1, 1, 1, 100.0, frozenset({"turn.steer"}),
    )
    semantic = Operation("operation", "session", "turn.steer",
                         {"text": "Change direction"}, "turn-1")
    receipt = OperationReceipt(
        "operation", intent_hash(semantic, context), "SUBMITTED",
        True, False, "session",
    )
    projected = project_r4_steer_receipt(
        frame, receipt, context, receipt_revision=1)
    assert projected["intent_hash"] == frame["intent_hash"]
    assert projected["stage"] == "SUBMITTED"

    altered = {**frame, "expected_turn_id": "turn-2"}
    altered["intent_hash"] = r4_submit_intent_hash(altered)
    with pytest.raises(CoreError) as mismatch:
        project_r4_steer_receipt(altered, receipt, context,
                                 receipt_revision=1)
    assert mismatch.value.code == "OPERATION_CONFLICT"
    assert mismatch.value.possible_effect is True
    assert mismatch.value.retry_safe is False
    with pytest.raises(CoreError) as wrong_action:
        project_r4_turn_receipt(frame, receipt, context,
                                receipt_revision=1)
    assert wrong_action.value.code == "CAPABILITY_UNSUPPORTED"


@pytest.mark.parametrize("action,project", [
    ("turn.interrupt", project_r4_interrupt_receipt),
    ("runtime.close", project_r4_close_receipt),
])
def test_r4_reason_receipt_requires_matching_core_reason(action, project):
    frame = _frame()
    frame["action"] = action
    frame["payload"] = {"reason": "Requested by the agent"}
    if action == "turn.interrupt":
        frame["expected_turn_id"] = "turn-1"
    else:
        frame["payload"].update(drain_seconds=1, interrupt_seconds=1)
    frame["intent_hash"] = r4_submit_intent_hash(frame)
    context = ExecutionContext(
        "server", "executor", "binding", "agent", "workspace",
        1, 1, 1, 100.0, frozenset({action}),
    )
    semantic = Operation(
        "operation", "session", action,
        frame["payload"],
        frame.get("expected_turn_id"),
    )
    receipt = OperationReceipt(
        "operation", intent_hash(semantic, context), "SUBMITTED",
        True, False, "session",
    )
    projected = project(frame, receipt, context, receipt_revision=1)
    assert projected["intent_hash"] == frame["intent_hash"]
    changed = {**frame, "payload": {**frame["payload"], "reason": "A different request"}}
    changed["intent_hash"] = r4_submit_intent_hash(changed)
    with pytest.raises(CoreError) as mismatch:
        project(changed, receipt, context, receipt_revision=1)
    assert mismatch.value.code == "OPERATION_CONFLICT"
    assert mismatch.value.possible_effect is True
    assert mismatch.value.retry_safe is False

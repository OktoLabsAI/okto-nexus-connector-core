"""Decision payloads preserve native evidence and refuse altered input before I/O."""

from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

from nexus_connector_core import (
    CoreError, ExecutionContext, OperationReceipt, encode_r4_frame,
    project_r4_decision_receipt, r4_native_decision_operation,
    r4_submit_intent_hash,
)
from nexus_connector_core.decision_bridge_r4 import native_decision_semantic
from nexus_connector_core.protocol import canonical_json, intent_hash
from test_r4_development_bundle import open_frame


def decision_frame(action="approval.decide"):
    frame = open_frame()
    frame["action"] = action
    frame["payload"] = {
        "canonical_request_id": "canonical", "decision_id": "decision",
        "decision_revision": 1, "decision": "accept",
        "request": {"schema_version": 1, "request_id": 7, "request_hash": "a" * 64,
                    "method": ("item/tool/requestUserInput" if action == "input.provide"
                               else "item/commandExecution/requestApproval"),
                    "params": {"threadId": "thread", "turnId": "turn", "itemId": "item"}},
        "response_digest": None,
    }
    if action == "input.provide":
        response = {"answers": {"q": {"answers": ["private operator response"]}}}
        frame["payload"].update(
            response=response,
            response_digest="sha256:" + hashlib.sha256(canonical_json(response)).hexdigest())
    frame["intent_hash"] = r4_submit_intent_hash(frame)
    return frame


@pytest.mark.parametrize("action", ["approval.decide", "input.provide"])
def test_verified_native_and_r4_decision_hash_domains_are_distinct(action):
    frame = decision_frame(action)
    operation = r4_native_decision_operation(frame)
    assert operation.request == frame["payload"]["request"]
    assert operation.request["request_hash"] == "a" * 64
    context = ExecutionContext("srv", "exe", "bind", "agent", "ws",
                               1, 1, 1, 100, frozenset({action}))
    receipt = OperationReceipt("op", intent_hash(native_decision_semantic(operation), context),
                               "SUBMITTED", True, False, "session")
    wire = project_r4_decision_receipt(frame, receipt, context, operation, receipt_revision=1)
    assert wire["intent_hash"] == frame["intent_hash"] != receipt.intent_hash
    assert wire["stage"] == receipt.stage
    altered = deepcopy(frame)
    altered["payload"]["request"]["params"]["itemId"] = "different"
    altered["intent_hash"] = r4_submit_intent_hash(altered)
    for bad_frame, bad_receipt, bad_context in (
        (altered, receipt, context),
        (frame, replace(receipt, intent_hash=frame["intent_hash"]), context),
        (frame, receipt, replace(context, session_owner_generation=2)),
    ):
        with pytest.raises(CoreError) as rejected:
            project_r4_decision_receipt(bad_frame, bad_receipt, bad_context,
                                        operation, receipt_revision=1)
        assert rejected.value.possible_effect and not rejected.value.retry_safe


def test_response_reference_requires_exact_content_and_does_not_alias_caller():
    frame = decision_frame("input.provide")
    response = frame["payload"].pop("response")
    frame["payload"]["response_ref"] = "protected-response"
    frame["intent_hash"] = r4_submit_intent_hash(frame)
    with pytest.raises(CoreError, match="INPUT_RESPONSE_UNAVAILABLE"):
        r4_native_decision_operation(frame)
    with pytest.raises(CoreError, match="OPERATION_CONFLICT"):
        r4_native_decision_operation(frame, resolved_response={"answer": "changed"})
    operation = r4_native_decision_operation(frame, resolved_response=response)
    response.clear()
    assert operation.operator_response["answers"]["q"]["answers"] == ["private operator response"]


@pytest.mark.parametrize("mutation", [
    lambda f: f["payload"].update(response_digest="sha256:" + "b" * 64),
    lambda f: f.update(action="approval.decide"),
    lambda f: f.update(expected_turn_id="ignored-turn"),
    lambda f: f["payload"]["request"].update(authorized=True),
    lambda f: f["payload"]["request"].update(request_hash="sha256:" + "a" * 64),
    lambda f: f["payload"]["request"].update(method="unknown-method"),
    lambda f: f["payload"]["request"]["params"].update(turnId=""),
])
def test_invalid_decisions_are_refused_before_a_runtime_call(mutation):
    frame = decision_frame("input.provide")
    mutation(frame)
    frame["intent_hash"] = r4_submit_intent_hash(frame)
    with pytest.raises(CoreError):
        r4_native_decision_operation(frame)


def test_approval_and_input_actions_cannot_be_substituted():
    frame = decision_frame()
    frame["payload"]["request"]["method"] = "item/tool/requestUserInput"
    frame["intent_hash"] = r4_submit_intent_hash(frame)
    encode_r4_frame(frame)  # Closed shape alone is not proof of the native capability.
    with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED"):
        r4_native_decision_operation(frame)

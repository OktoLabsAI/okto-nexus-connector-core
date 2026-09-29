"""R4 preview rejects ambiguous or unauthorized wire shapes before effect."""

from __future__ import annotations

import copy
import json

import pytest

from nexus_connector_core import (
    CONTRACT_REVISION, R4_BUNDLE_EXECUTABLE, R4_PREVIEW_REVISION,
    decode_r4_frame, encode_r4_frame, r4_submit_intent_hash,
    verify_r4_development_bundle,
)
from nexus_connector_core.frame_codec import decode_frame
from nexus_connector_core.models import CoreError
from nexus_connector_core.protocol import canonical_json


def open_frame() -> dict:
    frame = {
        "protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
        "type": "operation.submit", "server_id": "srv",
        "executor_id": "exe", "binding_id": "bind", "agent_id": "agent",
        "workspace_id": "ws", "workspace_binding_id": "wb",
        "session_id": "session", "session_owner_generation": 1,
        "authorization_revision": 1, "configuration_revision": 1,
        "binding_revision": 1, "credential_epoch": 1,
        "connection_id": "conn", "connection_generation": 1,
        "grant_id": "grant", "operation_id": "op", "action": "runtime.open",
        "payload": {
            "adapter_id": "codex_app_server",
            "candidate_ref": "nexus-install-v1:" + "a" * 64,
            "inventory_revision": "sha256:" + "b" * 64,
            "realization_ref": "real", "realization_revision": 1,
            "profile_revision": 1, "mode": "managed",
        },
    }
    frame["intent_hash"] = r4_submit_intent_hash(frame)
    return frame


def test_partial_bundle_is_integral_but_not_executable():
    info = verify_r4_development_bundle()
    assert info["revision"] == R4_PREVIEW_REVISION
    assert info["status"] == "development-partial"
    assert info["executable"] is R4_BUNDLE_EXECUTABLE is False
    assert CONTRACT_REVISION.endswith("-r3")
    assert "operation.submit" in info["supported_frames"]
    assert "binding.attach" in info["supported_frames"]
    assert "reconcile.report" in info["supported_frames"]
    assert "event.batch" in info["supported_frames"]
    assert "approval.request" in info["supported_frames"]


def test_r4_handshake_and_reconcile_pages_are_closed():
    base = {"protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION}
    hello = {**base, "type": "hello", "link_attempt_id": "attempt",
             "server_id": "srv", "executor_id": "exe",
             "core_version": "0.2.18.dev0",
             "management_revision": "nexus-connections-2026-09-29-r4",
             "supported_nxl": [R4_PREVIEW_REVISION],
             "snapshot_formats": [1], "control_capabilities": []}
    attach = {**base, "type": "binding.attach",
              "attach_request_id": "attach", "server_id": "srv",
              "executor_id": "exe", "binding_id": "bind",
              "agent_id": "agent", "connection_id": "connection",
              "expected_connection_generation": 1,
              "credential_epoch": 1, "authorization_revision": 1,
              "configuration_revision": 1, "ticket": "nxt4_" + "x" * 48}
    report = {**base, "type": "reconcile.report",
              "reconcile_id": "reconcile", "connection_id": "connection",
              "connection_generation": 1, "server_id": "srv",
              "executor_id": "exe", "cursor": None, "next_cursor": None,
              "complete": True,
              "receipts": [{"operation_id": "op",
                            "intent_hash": "sha256:" + "a" * 64,
                            "receipt_revision": 1,
                            "stage": "RECEIVED_DURABLE"}],
              "claims": [], "stream_watermarks": [],
              "ownership_facts": []}
    for value in (hello, attach, report):
        assert decode_r4_frame(encode_r4_frame(value)) == value
    for value in (
        {**hello, "management_revision": "legacy"},
        {**attach, "api_key": "secret"},
        {**report, "root_path": "/private/workspace"},
        {**report, "receipts": [{**report["receipts"][0], "output": "secret"}]},
    ):
        with pytest.raises(CoreError):
            encode_r4_frame(value)


def test_r4_event_identity_and_approval_notification_are_closed():
    base = {"protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION}
    connection = {"connection_id": "control", "connection_generation": 1}
    event = {"server_id": "srv", "executor_id": "exe",
             "session_id": "session", "stream_epoch": "epoch",
             "sequence": 1, "category": "lifecycle", "payload": {}}
    batch = {**base, "type": "event.batch", "server_id": "srv",
             "executor_id": "exe", "binding_id": "binding",
             "agent_id": "agent", "session_id": "session",
             "stream_epoch": "epoch", **connection, "events": [event]}
    scope = {key: value for key, value in open_frame().items() if key in {
        "server_id", "executor_id", "binding_id", "agent_id",
        "workspace_id", "workspace_binding_id", "session_id",
        "session_owner_generation", "authorization_revision",
        "configuration_revision", "binding_revision", "credential_epoch",
    }}
    approval = {**base, "type": "approval.decision", **scope,
                **connection, "canonical_request_id": "request",
                "decision_id": "decision", "decision_revision": 1,
                "decision": "decline",
                "request_hash": "sha256:" + "c" * 64}
    assert decode_r4_frame(encode_r4_frame(batch)) == batch
    assert decode_r4_frame(encode_r4_frame(approval)) == approval
    for value in (
        {**batch, "events": [{**event, "connection_generation": 2}]},
        {**approval, "apply_native": True},
    ):
        with pytest.raises(CoreError):
            encode_r4_frame(value)


def test_open_roundtrip_and_r3_cross_revision_rejection():
    frame = open_frame()
    raw = encode_r4_frame(frame)
    assert decode_r4_frame(raw) == frame
    assert raw.endswith(b"\n")
    with pytest.raises(CoreError) as old:
        decode_frame(raw)
    assert old.value.code == "VERSION_INCOMPATIBLE"
    with pytest.raises(CoreError) as new:
        decode_r4_frame(canonical_json({**frame, "contract_revision": CONTRACT_REVISION}))
    assert new.value.code == "VERSION_INCOMPATIBLE"


@pytest.mark.parametrize("mutation", [
    lambda f: f["payload"].update(executable="/tmp/codex"),
    lambda f: f["payload"].update(argv=["codex"]),
    lambda f: f["payload"].update(env={"TOKEN": "secret"}),
    lambda f: f.update(operator=True),
    lambda f: f.pop("session_owner_generation"),
    lambda f: f.pop("grant_id"),
    lambda f: f["payload"].update(mode="attach"),
    lambda f: f["payload"].update(adapter_id="invented_adapter"),
])
def test_open_rejects_raw_launch_and_missing_authority(mutation):
    frame = open_frame()
    mutation(frame)
    if "intent_hash" in frame:
        frame["intent_hash"] = r4_submit_intent_hash(frame)
    with pytest.raises(CoreError) as error:
        decode_r4_frame(canonical_json(frame))
    assert error.value.code == "VALIDATION_ERROR"


def test_hash_domain_and_transport_attempt_are_separate():
    frame = open_frame()
    changed = copy.deepcopy(frame)
    changed["connection_generation"] += 1
    changed["grant_id"] = "another"
    assert r4_submit_intent_hash(changed) == frame["intent_hash"]
    changed["payload"]["realization_revision"] += 1
    assert r4_submit_intent_hash(changed) != frame["intent_hash"]


def test_ambiguous_json_and_wrong_decision_payload_are_rejected():
    frame = open_frame()
    raw = canonical_json(frame)
    ambiguous = raw[:-1] + b',"operation_id":"different"}'
    with pytest.raises(CoreError):
        decode_r4_frame(ambiguous)
    frame["action"] = "approval.decide"
    frame["intent_hash"] = r4_submit_intent_hash(frame)
    with pytest.raises(CoreError) as error:
        decode_r4_frame(json.dumps(frame).encode())
    assert error.value.code == "VALIDATION_ERROR"


def test_correlated_native_decision_payloads_are_closed():
    base = open_frame()
    request = {"request_hash": "sha256:" + "c" * 64,
               "native_request_id": "provider-request"}
    decision = {
        "canonical_request_id": "canonical-request", "decision_id": "decision",
        "decision_revision": 1, "decision": "accept", "request": request,
        "response_digest": None,
    }
    base["action"] = "approval.decide"
    base["payload"] = decision
    base["intent_hash"] = r4_submit_intent_hash(base)
    assert decode_r4_frame(encode_r4_frame(base)) == base

    input_frame = copy.deepcopy(base)
    input_frame["action"] = "input.provide"
    input_frame["payload"]["response"] = {"answer": "example"}
    input_frame["intent_hash"] = r4_submit_intent_hash(input_frame)
    assert decode_r4_frame(encode_r4_frame(input_frame)) == input_frame

    for mutation in (
        lambda f: f["payload"].update(authority="operator"),
        lambda f: f["payload"].update(response_ref="alternate"),
        lambda f: f["payload"].update(decision_revision=0),
        lambda f: f["payload"]["request"].pop("request_hash"),
    ):
        invalid = copy.deepcopy(input_frame)
        mutation(invalid)
        invalid["intent_hash"] = r4_submit_intent_hash(invalid)
        with pytest.raises(CoreError) as error:
            encode_r4_frame(invalid)
        assert error.value.code == "VALIDATION_ERROR"

    declined = copy.deepcopy(input_frame)
    declined["payload"].update(decision="decline", response=None)
    declined["intent_hash"] = r4_submit_intent_hash(declined)
    assert decode_r4_frame(encode_r4_frame(declined)) == declined


def test_lease_reply_has_bounded_duration_and_closed_scope():
    scope = {key: value for key, value in open_frame().items() if key in {
        "server_id", "executor_id", "binding_id", "agent_id",
        "workspace_id", "workspace_binding_id", "session_id",
        "session_owner_generation", "authorization_revision",
        "configuration_revision", "binding_revision", "credential_epoch",
    }}
    frame = {
        "protocol_major": 1, "contract_revision": R4_PREVIEW_REVISION,
        "type": "lease.granted", "request_id": "request", "lease_id": "lease",
        "lease_serial": 1, "grant_id": "grant", "scope": scope,
        "allowed_actions": ["runtime.open"], "valid_for_ms": 120000,
    }
    assert decode_r4_frame(encode_r4_frame(frame)) == frame
    frame["valid_for_ms"] = 120001
    with pytest.raises(CoreError):
        encode_r4_frame(frame)


def test_receipt_and_query_require_connection_and_scoped_identity():
    submit = open_frame()
    common = {key: submit[key] for key in (
        "protocol_major", "contract_revision", "server_id", "executor_id",
        "binding_id", "agent_id", "session_id", "connection_id",
        "connection_generation", "operation_id", "intent_hash",
    )}
    receipt = {**common, "type": "operation.receipt", "receipt_revision": 1,
               "stage": "RECEIVED_DURABLE", "possible_effect": False,
               "retry_safe": True}
    query = {**common, "type": "operation.query"}
    assert decode_r4_frame(encode_r4_frame(receipt)) == receipt
    assert decode_r4_frame(encode_r4_frame(query)) == query
    for bad in ({**receipt, "receipt_revision": 0},
                {key: value for key, value in receipt.items()
                 if key != "connection_id"},
                {**query, "agent_id": ""},
                {**query, "operator": True}):
        with pytest.raises(CoreError):
            encode_r4_frame(bad)

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


def test_ambiguous_json_and_unsupported_decision_are_rejected():
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

import json
import random
from importlib.resources import files

import pytest

from nexus_connector_core import CONTRACT_REVISION, CoreError, ExecutionContext, Operation, intent_hash
from nexus_connector_core.frame_codec import MAX_FRAME_BYTES, decode_frame, encode_frame
import nexus_connector_core.frame_codec as frame_codec
from nexus_connector_core.protocol import submit_frame_intent_hash


def _fixtures():
    resource = files("nexus_connector_core.contracts.nxl.v1").joinpath("fixtures.json")
    return json.loads(resource.read_text(encoding="utf-8"))["frames"]


def _valid(kind):
    return next(frame for frame in _fixtures()["valid"] if frame["type"] == kind)


def test_all_positive_frames_roundtrip_and_invalid_fixtures_rejected():
    for frame in _fixtures()["valid"]:
        encoded = encode_frame(frame)
        assert encoded.endswith(b"\n")
        assert decode_frame(encoded) == frame
    for frame in _fixtures()["invalid"]:
        with pytest.raises(CoreError):
            decode_frame(json.dumps(frame, ensure_ascii=False).encode())


def test_wire_bytes_checked_before_json_parse_and_duplicate_keys_rejected():
    frame = _valid("heartbeat")
    raw = encode_frame(frame)
    assert encode_frame(frame, max_frame_bytes=len(raw)) == raw
    with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
        encode_frame(frame, max_frame_bytes=len(raw) - 1)
    with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
        decode_frame(raw, max_frame_bytes=len(raw) - 1)
    with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
        encode_frame(frame, max_frame_bytes=len(raw) - 2)
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        decode_frame(raw[:-2] + b',"type":"heartbeat"}')
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        decode_frame(b'{"x":NaN}')
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        decode_frame(b'\xff')


def test_encoder_rejects_oversized_or_cyclic_host_object_before_jcs(monkeypatch):
    frame = _valid("event.batch")
    frame["events"][0]["payload"]["huge"] = "x" * (MAX_FRAME_BYTES + 1)

    def must_not_serialize(_value):
        raise AssertionError("oversized host input reached JCS allocation")

    monkeypatch.setattr(frame_codec, "canonical_json", must_not_serialize)
    with pytest.raises(CoreError, match="CAPACITY_EXCEEDED"):
        encode_frame(frame)

    cyclic = _valid("event.batch")
    payload = cyclic["events"][0]["payload"]
    payload["cycle"] = payload
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        encode_frame(cyclic)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, MAX_FRAME_BYTES + 1])
def test_frame_limit_must_be_a_positive_bounded_integer(limit):
    with pytest.raises(ValueError):
        encode_frame(_valid("heartbeat"), max_frame_bytes=limit)
    with pytest.raises(ValueError):
        decode_frame(b"{}", max_frame_bytes=limit)


@pytest.mark.parametrize("hostile", [
    b'{"type":1,"t\\u0079pe":2}',
    b'{"text":"\\ud800"}',
    b'{"number":1e9999}',
    b'{"number":' + b"9" * 5000 + b'}',
    b"[" * 1000 + b"0" + b"]" * 1000,
    b'{"text":"\xc0\xaf"}',
])
def test_hostile_json_is_rejected_without_uncaught_parser_error(hostile):
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        decode_frame(hostile)


def test_seeded_byte_mutations_never_escape_codec_error_boundary():
    rng = random.Random(20260925)
    sources = [encode_frame(_valid(kind)) for kind in
               ("heartbeat", "event.batch", "operation.submit")]
    for source in sources:
        for _ in range(200):
            raw = bytearray(source)
            for _ in range(rng.randint(1, 4)):
                action = rng.randrange(3)
                offset = rng.randrange(len(raw))
                if action == 0:
                    raw[offset] = rng.randrange(256)
                elif action == 1:
                    del raw[offset]
                else:
                    raw.insert(offset, rng.randrange(256))
            try:
                frame = decode_frame(bytes(raw))
            except CoreError:
                continue
            assert decode_frame(encode_frame(frame)) == frame


def test_exact_revision_and_closed_security_fields():
    frame = _valid("operation.submit")
    with pytest.raises(CoreError, match="VERSION_INCOMPATIBLE"):
        encode_frame({**frame, "contract_revision": "nxl-1-draft-r1"})
    with pytest.raises(CoreError, match="VERSION_INCOMPATIBLE"):
        encode_frame({**frame, "protocol_major": 2})
    assert frame["contract_revision"] == CONTRACT_REVISION
    for bad in ({**frame, "action": "shell.exec"},
                {**frame, "user_id": "spoof"}):
        with pytest.raises(CoreError, match="VALIDATION_ERROR"):
            encode_frame(bad)


def test_event_batch_requires_same_identity_and_contiguous_sequence():
    frame = _valid("event.batch")
    first = frame["events"][0]
    second = {**first, "sequence": first["sequence"] + 1}
    assert decode_frame(encode_frame({**frame, "events": [first, second]}))
    for bad in ({**second, "session_id": "another"},
                {**second, "sequence": first["sequence"] + 2},
                {**second, "stream_epoch": "another"}):
        with pytest.raises(CoreError, match="VALIDATION_ERROR"):
            encode_frame({**frame, "events": [first, bad]})


def test_inventory_delta_cannot_add_and_remove_same_candidate():
    frame = _valid("inventory.delta")
    candidate_id = frame["candidates"][0]["candidate_id"]
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        encode_frame({**frame, "removed_candidate_ids": [candidate_id]})
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        encode_frame({**frame, "candidates": frame["candidates"] * 2})
    snapshot = _valid("inventory.snapshot")
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        encode_frame({**snapshot, "candidates": snapshot["candidates"] * 2})


def test_unknown_receipt_cannot_claim_no_effect_or_safe_retry():
    frame = _valid("operation.receipt")
    for possible, safe in ((False, False), (True, True)):
        with pytest.raises(CoreError, match="VALIDATION_ERROR"):
            encode_frame({**frame, "stage": "OUTCOME_UNKNOWN",
                          "possible_effect": possible, "retry_safe": safe})
    assert decode_frame(encode_frame({**frame, "stage": "OUTCOME_UNKNOWN",
                                      "possible_effect": True,
                                      "retry_safe": False}))


def test_submit_frame_hash_matches_runtime_semantics_and_ignores_reconnect():
    frame = _valid("operation.submit")
    context = ExecutionContext(
        frame["server_id"], frame["executor_id"], frame["binding_id"],
        frame["agent_id"], frame["workspace_id"],
        frame["authorization_revision"], frame["configuration_revision"],
        frame["connection_generation"], 100.0, frozenset({frame["action"]}))
    operation = Operation(frame["operation_id"], frame["session_id"],
                          frame["action"], frame["payload"])
    assert frame["intent_hash"] == submit_frame_intent_hash(frame)
    assert frame["intent_hash"] == intent_hash(operation, context)
    reconnect = {**frame, "connection_generation": frame["connection_generation"] + 1}
    assert decode_frame(encode_frame(reconnect)) == reconnect
    for change in ({"payload": {"text": "outro"}},
                   {"configuration_revision": frame["configuration_revision"] + 1}):
        with pytest.raises(CoreError, match="VALIDATION_ERROR"):
            encode_frame({**frame, **change})
    ambiguous = {**frame, "payload": {**frame["payload"],
                                       "expected_turn_id": "hidden"}}
    ambiguous["intent_hash"] = submit_frame_intent_hash(ambiguous)
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        encode_frame(ambiguous)


def test_conditional_controls_require_hashed_expected_turn_id():
    controls = [frame for frame in _fixtures()["valid"]
                if frame["type"] == "operation.submit" and
                frame["action"] in {"turn.interrupt", "turn.steer"}]
    assert {frame["action"] for frame in controls} == {"turn.interrupt", "turn.steer"}
    for frame in controls:
        assert decode_frame(encode_frame(frame)) == frame
        with pytest.raises(CoreError, match="VALIDATION_ERROR"):
            encode_frame({key: value for key, value in frame.items()
                          if key != "expected_turn_id"})
        with pytest.raises(CoreError, match="VALIDATION_ERROR"):
            encode_frame({**frame, "expected_turn_id": "different"})
        context = ExecutionContext(
            frame["server_id"], frame["executor_id"], frame["binding_id"],
            frame["agent_id"], frame["workspace_id"],
            frame["authorization_revision"], frame["configuration_revision"],
            frame["connection_generation"], 100.0, frozenset({frame["action"]}))
        operation = Operation(frame["operation_id"], frame["session_id"],
                              frame["action"], frame["payload"], frame["expected_turn_id"])
        assert frame["intent_hash"] == intent_hash(operation, context)

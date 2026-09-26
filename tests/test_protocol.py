import json
import math
import struct

import pytest

from nexus_connector_core import ExecutionContext, Operation, intent_hash
from nexus_connector_core.protocol import canonical_json, strict_json, require_contract
from nexus_connector_core import CONTRACT_REVISION, CoreError


def test_canonical_unicode_order_and_reconnect_hash():
    a = {"\U0001f600": "emoji", "\ue000": "private", "á": [1, True]}
    b = dict(reversed(list(a.items())))
    assert canonical_json(a) == canonical_json(b)
    assert canonical_json(a).startswith(b'{"\xc3\xa1"')
    base = dict(server_id="srv", executor_id="exe", binding_id="bind",
                agent_id="agent", workspace_id="ws", authorization_revision=1,
                configuration_revision=2, connection_generation=1,
                lease_deadline_monotonic=99, allowed_actions=frozenset({"turn.submit"}))
    op = Operation("op", "session", "turn.submit", a)
    first = intent_hash(op, ExecutionContext(**base))
    base["connection_generation"] = 2
    assert first == intent_hash(op, ExecutionContext(**base))


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}',
                                  '{"x":"\\ud800"}', '{"\\ud800":1}',
                                  '{"x":9007199254740992}'])
def test_reject_ambiguous_json(text):
    with pytest.raises(ValueError):
        strict_json(text)


def test_jcs_rfc8785_number_vectors():
    # RFC 8785 Appendix B: decimal rendering must follow ECMAScript, not
    # Python's default JSON float formatting.
    vectors = {
        "8000000000000000": "0",
        "0000000000000001": "5e-324",
        "7fefffffffffffff": "1.7976931348623157e+308",
        "4430000000000000": "295147905179352830000",
        "44b52d02c7e14af6": "1e+23",
        "3eb0c6f7a0b5ed8d": "0.000001",
        "43143ff3c1cb0959": "1424953923781206.2",
    }
    for bits, expected in vectors.items():
        number = struct.unpack(">d", bytes.fromhex(bits))[0]
        assert canonical_json(number) == expected.encode("ascii")


def test_reject_unqualified_numbers():
    with pytest.raises(ValueError):
        canonical_json({"x": 2**53})
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            canonical_json({"x": value})
    with pytest.raises(ValueError):
        strict_json('{"x":1e400}')


def test_jcs_nested_unicode_and_float_semantic_hash():
    assert canonical_json({"z": [1.0, -0.0, 1e-7], "a": "\u20ac"}) == (
        b'{"a":"\xe2\x82\xac","z":[1,0,1e-7]}')


def test_exact_revision_negotiation():
    require_contract(1, CONTRACT_REVISION)
    with pytest.raises(CoreError, match="VERSION_INCOMPATIBLE"):
        require_contract(1, "nxl-1-draft-2026-09-24-r1")


def test_schema_operation_submit():
    jsonschema = pytest.importorskip("jsonschema")
    from importlib.resources import files
    path = files("nexus_connector_core").joinpath("contracts/nxl/v1/frame.schema.json")
    schema = json.loads(path.read_text(encoding="utf-8"))
    frame = {
        "protocol_major": 1, "contract_revision": CONTRACT_REVISION,
        "type": "operation.submit", "server_id": "srv", "executor_id": "exe",
        "binding_id": "bind", "agent_id": "agent", "workspace_id": "ws",
        "workspace_binding_id": "wb", "session_id": "session",
        "operation_id": "op", "action": "turn.submit",
        "connection_generation": 1, "authorization_revision": 1,
        "configuration_revision": 1, "intent_hash": "sha256:" + "0" * 64,
        "payload": {"text": "olá"},
    }
    jsonschema.validate(frame, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**frame, "action": "shell.exec"}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**frame, "user_id": "spoof"}, schema)

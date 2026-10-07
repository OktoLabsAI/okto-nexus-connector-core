"""Generate the Core-owned NXL development contract bundle deterministically."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import rfc8785

# Active adapter enums derive from the registry. This frozen wire revision
# also retains its retired identifier for historical record decoding only.
# Schema acceptance never grants execution; the native registry rejects it.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from nexus_connector_core.native.registry import adapter_specs  # noqa: E402

ADAPTER_IDS = [spec.adapter_id for spec in adapter_specs()] + ["claude_attach"]

REVISION = "nxl-1-agent-centric-http-only-2026-09-25-r3"
DESTINATION = Path(__file__).resolve().parents[1] / "src/nexus_connector_core/contracts/nxl/v1"
SCHEMA = "https://json-schema.org/draft/2020-12/schema"
BASE_ID = "https://nexus.oktolabs.ai/contracts/nxl/v1/"


def ref(name: str) -> dict:
    return {"$ref": f"#/$defs/{name}"}


ID = {"type": "string", "minLength": 1, "maxLength": 160}
REV = {"type": "integer", "minimum": 0, "maximum": 9007199254740991}
HASH = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
STRING = {"type": "string", "minLength": 1, "maxLength": 4096}
ID_LIST = {"type": "array", "items": ref("id"), "maxItems": 256,
           "uniqueItems": True}
PAYLOAD = {"type": "object", "maxProperties": 32}
STAGES = ["RECEIVED_DURABLE", "PREPARED", "SUBMISSION_STARTED", "SUBMITTED",
          "ACCEPTED", "RUNNING", "WAITING_INPUT", "SUCCEEDED", "FAILED",
          "CANCELLED", "OUTCOME_UNKNOWN"]
ACTIONS = ["runtime.open", "turn.submit", "turn.interrupt", "turn.steer",
           "runtime.close", "approval.decide", "input.provide"]
CONTROL_ACTIONS = ["turn.interrupt", "turn.steer"]
EVENT_CATEGORIES = ["lifecycle", "turn_state", "text_delta", "text_snapshot",
                    "tool_activity", "approval_request", "input_request",
                    "usage", "system_warning", "rate_limit", "error",
                    "native_unknown"]


def object_schema(title: str, required: list[str], properties: dict,
                  *, definitions: dict | None = None) -> dict:
    value = {"$schema": SCHEMA, "$id": BASE_ID + title + ".schema.json",
             "title": title, "type": "object", "required": required,
             "properties": properties, "additionalProperties": False}
    if definitions:
        value["$defs"] = definitions
    return value


ERROR = object_schema("error", ["code", "stage", "possible_effect", "retry_safe"], {
    "code": {"type": "string", "minLength": 1, "maxLength": 80},
    "stage": {"type": "string", "minLength": 1, "maxLength": 80},
    "possible_effect": {"type": "boolean"},
    "retry_safe": {"type": "boolean"},
    "operation_id": ID,
    "corrective_action": {"type": "string", "maxLength": 512},
})
EVENT = object_schema("event", ["server_id", "executor_id", "session_id",
                                 "stream_epoch", "sequence", "category", "payload"], {
    "server_id": ID, "executor_id": ID, "session_id": ID,
    "stream_epoch": ID, "sequence": {"type": "integer", "minimum": 1,
                                     "maximum": 9007199254740991},
    "category": {"enum": EVENT_CATEGORIES},
    "native_type": {"type": ["string", "null"], "maxLength": 160},
    "payload": PAYLOAD, "operation_id": ID,
})
INTENT = object_schema("intent", ["server_id", "executor_id", "binding_id",
                                   "agent_id", "workspace_id", "session_id",
                                   "action", "payload", "configuration_revision"], {
    "server_id": ID, "executor_id": ID, "binding_id": ID,
    "agent_id": ID, "workspace_id": ID, "session_id": ID,
    "action": {"enum": ACTIONS}, "payload": PAYLOAD,
    "configuration_revision": REV,
    "expected_turn_id": ID,
})
INTENT["allOf"] = [{
    "if": {"properties": {"action": {"enum": CONTROL_ACTIONS}}},
    "then": {"required": ["expected_turn_id"]},
    "else": {"not": {"required": ["expected_turn_id"]}},
}]
CANDIDATE = {
    "type": "object", "required": ["candidate_id", "adapter_id", "fingerprint",
                                   "trust"],
    "properties": {
        "candidate_id": ID, "adapter_id": {"enum": ADAPTER_IDS},
        "fingerprint": HASH, "trust": {"enum": ["selected", "untrusted", "rejected"]},
        "version": {"type": ["string", "null"], "maxLength": 80},
        "architecture": {"type": ["string", "null"], "maxLength": 80},
    }, "additionalProperties": False,
}
INVENTORY = object_schema("inventory", ["server_id", "executor_id", "revision",
                                         "candidates"], {
    "server_id": ID, "executor_id": ID, "revision": REV,
    "candidates": {"type": "array", "items": CANDIDATE, "maxItems": 128},
})
CAPABILITY = object_schema("capability", ["adapter_id", "native_version",
                                           "platform", "conversation",
                                           "managed_work", "tool_path"], {
    "adapter_id": {"enum": ADAPTER_IDS},
    "native_version": {"type": ["string", "null"], "maxLength": 80},
    "platform": {"type": "string", "minLength": 1, "maxLength": 80},
    "conversation": {"type": "boolean"},
    "managed_work": {"type": "boolean"},
    "tool_path": {"enum": ["direct_mcp_http", "structured_native", "none"]},
    "interrupt": {"type": "boolean"}, "steer_timing": {"enum": ["IMMEDIATE",
                                    "NEXT_TURN_BOUNDARY", "UNSUPPORTED"]},
    "approvals": {"type": "boolean"},
})
HTTP_RESPONSE = object_schema("http-response", ["request_id", "status"], {
    "request_id": ID, "status": {"type": "integer", "minimum": 100, "maximum": 599},
    "data": {"type": ["object", "array", "null"]},
    "error": {k: v for k, v in ERROR.items() if k not in {"$schema", "$id", "title"}},
}, definitions={"id": ID})
HTTP_RESPONSE["oneOf"] = [
    {"properties": {"status": {"minimum": 200, "maximum": 299}},
     "required": ["data"], "not": {"required": ["error"]}},
    {"properties": {"status": {"minimum": 400, "maximum": 599}},
     "required": ["error"], "not": {"required": ["data"]}},
]

FRAME_FIELDS = {
    "server_id": ref("id"), "executor_id": ref("id"),
    "binding_id": ref("id"), "agent_id": ref("id"),
    "workspace_id": ref("id"), "workspace_binding_id": ref("id"),
    "session_id": ref("id"), "operation_id": ref("id"),
    "request_id": ref("id"), "lease_id": ref("id"),
    "ticket": {"type": "string", "minLength": 1, "maxLength": 4096,
               "description": "Sensitive attach ticket; never log or place in a URL."},
    "core_version": {"type": "string", "minLength": 1, "maxLength": 80},
    "event_types": ID_LIST, "limits": {"type": "object", "maxProperties": 32},
    "capabilities": {"type": "array", "items": CAPABILITY, "maxItems": 16},
    "connection_generation": ref("revision"),
    "session_owner_generation": ref("revision"),
    "authorization_revision": ref("revision"),
    "configuration_revision": ref("revision"),
    "credential_epoch": ref("revision"), "inventory_revision": ref("revision"),
    "candidates": {"type": "array", "items": CANDIDATE, "maxItems": 128},
    "removed_candidate_ids": ID_LIST,
    "intent_hash": ref("hash"), "action": {"enum": ACTIONS},
    "expected_turn_id": ref("id"),
    "payload": PAYLOAD, "stage": {"enum": STAGES},
    "possible_effect": {"type": "boolean"}, "retry_safe": {"type": "boolean"},
    "native_id": ref("id"), "error_code": {"type": "string", "minLength": 1,
                                            "maxLength": 80},
    "stream_epoch": ref("id"), "sequence": ref("revision"),
    "events": {"type": "array", "minItems": 1, "maxItems": 128,
               "items": {k: v for k, v in EVENT.items()
                         if k not in {"$schema", "$id", "title"}}},
    "operation_ids": ID_LIST, "session_ids": ID_LIST,
    "receipts": {"type": "array", "maxItems": 256,
                 "items": {"type": "object", "required": ["operation_id", "stage"],
                           "properties": {"operation_id": ID, "stage": {"enum": STAGES}},
                           "additionalProperties": False}},
    "snapshots": {"type": "array", "maxItems": 256,
                  "items": {"type": "object", "required": ["session_id", "ownership"],
                            "properties": {"session_id": ID,
                                           "ownership": {"enum": ["owned", "released", "unknown"]}},
                            "additionalProperties": False}},
    "valid_for_ms": {"type": "integer", "minimum": 1, "maximum": 120000},
    "kind": {"enum": ["approval", "input"]},
    "proposal": PAYLOAD, "decision": {"enum": ["accept", "decline", "cancel"]},
    "reason": STRING, "code": {"type": "string", "minLength": 1,
                                   "maxLength": 80},
    "corrective_action": {"type": "string", "maxLength": 512},
}

FRAME_SPEC = {
    "hello": (["server_id", "executor_id", "core_version", "event_types",
               "limits", "capabilities"], []),
    "welcome": (["server_id", "executor_id", "core_version",
                 "connection_generation", "event_types", "limits", "capabilities"], []),
    "binding.attach": (["server_id", "executor_id", "binding_id", "agent_id",
                        "authorization_revision", "credential_epoch", "ticket"], []),
    "binding.detach": (["server_id", "executor_id", "binding_id", "agent_id",
                        "reason"], []),
    "inventory.snapshot": (["server_id", "executor_id", "inventory_revision",
                            "candidates"], []),
    "inventory.delta": (["server_id", "executor_id", "inventory_revision",
                         "candidates", "removed_candidate_ids"], []),
    "operation.submit": (["server_id", "executor_id", "binding_id", "agent_id",
                          "workspace_id", "workspace_binding_id", "session_id",
                          "operation_id", "action", "connection_generation",
                          "authorization_revision", "configuration_revision",
                          "intent_hash", "payload"],
                         ["session_owner_generation", "expected_turn_id"]),
    "operation.receipt": (["server_id", "executor_id", "session_id", "operation_id",
                           "intent_hash", "stage", "possible_effect", "retry_safe"],
                          ["native_id", "error_code"]),
    "operation.query": (["server_id", "executor_id", "operation_id"], []),
    "event.batch": (["server_id", "executor_id", "session_id", "stream_epoch",
                     "events"], []),
    "event.ack": (["server_id", "executor_id", "session_id", "stream_epoch",
                   "sequence"], []),
    "reconcile.request": (["server_id", "executor_id", "operation_ids",
                           "session_ids"], []),
    "reconcile.report": (["server_id", "executor_id", "receipts", "snapshots"], []),
    "lease.renew": (["server_id", "executor_id", "binding_id", "agent_id",
                     "session_id", "connection_generation", "authorization_revision",
                     "lease_id"], []),
    "lease.granted": (["server_id", "executor_id", "binding_id", "agent_id",
                       "session_id", "lease_id", "valid_for_ms",
                       "session_owner_generation", "authorization_revision"], []),
    "approval.request": (["server_id", "executor_id", "binding_id", "agent_id",
                          "session_id", "operation_id", "request_id", "kind",
                          "proposal"], []),
    "approval.decision": (["server_id", "executor_id", "binding_id", "agent_id",
                           "session_id", "operation_id", "request_id", "decision",
                           "authorization_revision"], []),
    "heartbeat": (["server_id", "executor_id", "connection_generation"], []),
    "error": (["server_id", "executor_id", "code", "stage", "possible_effect",
               "retry_safe"], ["operation_id", "corrective_action"]),
    "goaway": (["server_id", "executor_id", "reason"], []),
}


def frame_schema() -> dict:
    variants = []
    for name, (required, optional) in FRAME_SPEC.items():
        properties = {
            "protocol_major": {"const": 1},
            "contract_revision": {"const": REVISION},
            "type": {"const": name},
            **{field: FRAME_FIELDS[field] for field in [*required, *optional]},
        }
        variant = {"title": name, "type": "object",
                   "required": ["protocol_major", "contract_revision", "type", *required],
                   "properties": properties, "additionalProperties": False}
        if name == "operation.submit":
            variant["allOf"] = [{
                "if": {"properties": {"action": {"enum": CONTROL_ACTIONS}}},
                "then": {"required": ["expected_turn_id"]},
                "else": {"not": {"required": ["expected_turn_id"]}},
            }]
        variants.append(variant)
    return {"$schema": SCHEMA, "$id": BASE_ID + "frame.schema.json",
            "title": "NXL v1 frame (development revision r3)",
            "oneOf": variants,
            "$defs": {"id": ID, "revision": REV, "hash": HASH}}


def fixtures() -> dict:
    base = {"protocol_major": 1, "contract_revision": REVISION}
    common = {"server_id": "srv_A", "executor_id": "exe_B",
              "binding_id": "bind_C", "agent_id": "ag_D",
              "workspace_id": "ws_E", "workspace_binding_id": "wb_F",
              "session_id": "session_G", "operation_id": "op_H",
              "request_id": "req_I", "lease_id": "lease_J",
              "ticket": "fixture-ticket-not-a-secret", "core_version": "0.1.0.dev0",
              "event_types": ["turn_state"], "limits": {"frame_bytes": 1048576},
              "capabilities": [{"adapter_id": "codex_app_server", "native_version": None,
                                "platform": "win32", "conversation": False,
                                "managed_work": False, "tool_path": "none"}],
              "connection_generation": 7, "session_owner_generation": 2,
              "authorization_revision": 3, "configuration_revision": 4,
              "credential_epoch": 5, "inventory_revision": 6,
              "candidates": [{"candidate_id": "candidate_K", "adapter_id": "pi_rpc",
                              "fingerprint": "sha256:" + "0" * 64,
                              "trust": "selected", "version": "0.85.1"}],
              "removed_candidate_ids": [], "intent_hash": "sha256:" + "0" * 64,
              "action": "turn.submit", "payload": {"text": "Olá", "delivery_id": "dlv_1"},
              "stage": "SUBMITTED", "possible_effect": True, "retry_safe": False,
              "native_id": "native_L", "error_code": "OUTCOME_UNKNOWN",
              "stream_epoch": "epoch_M", "sequence": 1,
              "events": [{"server_id": "srv_A", "executor_id": "exe_B",
                          "session_id": "session_G", "stream_epoch": "epoch_M",
                          "sequence": 1, "category": "turn_state", "payload": {},
                          "native_type": "turn/completed"}],
              "operation_ids": ["op_H"], "session_ids": ["session_G"],
              "receipts": [{"operation_id": "op_H", "stage": "SUBMITTED"}],
              "snapshots": [{"session_id": "session_G", "ownership": "owned"}],
              "valid_for_ms": 120000, "kind": "approval", "proposal": {"action": "write"},
              "decision": "decline", "reason": "drain", "code": "EXECUTOR_OFFLINE",
              "corrective_action": "reconnect"}
    valid = []
    invalid = []
    for name, (required, _) in FRAME_SPEC.items():
        frame = {**base, "type": name,
                 **{field: common[field] for field in required}}
        if name == "operation.submit":
            frame["intent_hash"] = _fixture_submit_hash(frame)
        valid.append(frame)
        missing = dict(frame)
        missing.pop(required[-1])
        invalid.append(missing)
    invalid.extend([
        {**valid[7], "stage": "EXACTLY_ONCE"},
        {**valid[6], "action": "shell.exec"},
        {**valid[6], "action": "turn.steer"},
        {**valid[6], "expected_turn_id": "unexpected_turn"},
        {**valid[-2], "contract_revision": "nxl-1-draft-2026-09-24-r1"},
        {**valid[-2], "ticket": "not-allowed-on-error"},
        {**valid[9], "events": [{**common["events"][0], "sequence": 0}]},
    ])
    for action in CONTROL_ACTIONS:
        control = {**valid[6], "action": action,
                   "operation_id": "op_" + action.replace(".", "_"),
                   "expected_turn_id": "turn_N"}
        control["intent_hash"] = _fixture_submit_hash(control)
        valid.append(control)
    models = {
        "intent": {"valid": [
            {k: common[k] for k in INTENT["required"]},
            {**{k: common[k] for k in INTENT["required"]},
             "action": "turn.steer", "expected_turn_id": "turn_N"},
        ], "invalid": [
            {"action": "shell.exec"},
            {**{k: common[k] for k in INTENT["required"]},
             "action": "turn.interrupt"},
            {**{k: common[k] for k in INTENT["required"]},
             "expected_turn_id": "unexpected_turn"},
        ]},
        "event": {"valid": common["events"],
                  "invalid": [{**common["events"][0], "sequence": 0}]},
        "error": {"valid": [{k: common[k] for k in ERROR["required"]}],
                  "invalid": [{"code": "EXECUTOR_OFFLINE", "retry_safe": True}]},
        "inventory": {"valid": [{"server_id": "srv_A", "executor_id": "exe_B",
                                 "revision": 6, "candidates": common["candidates"]}],
                      "invalid": [{"server_id": "srv_A", "executor_id": "exe_B",
                                   "revision": 6, "candidates": [{"adapter_id": "pi_rpc"}]}]},
        "capability": {"valid": common["capabilities"],
                       "invalid": [{**common["capabilities"][0],
                                    "tool_path": "local_mcp_proxy"}]},
        "http-response": {"valid": [
            {"request_id": "req_I", "status": 200, "data": {"ok": True}},
            {"request_id": "req_I", "status": 403,
             "error": {"code": "BINDING_NOT_AUTHORIZED", "stage": "admission",
                       "possible_effect": False, "retry_safe": True}},
        ], "invalid": [
            {"request_id": "req_I", "status": 200, "secret": "forbidden"},
            {"request_id": "req_I", "status": 500, "data": {"ok": False}},
        ]},
    }
    return {"revision": REVISION, "frames": {"valid": valid, "invalid": invalid},
            "models": models}


def _fixture_submit_hash(frame: dict) -> str:
    semantic = {key: frame[key] for key in (
        "server_id", "executor_id", "binding_id", "agent_id", "workspace_id",
        "session_id", "action", "payload", "configuration_revision")}
    semantic["expected_turn_id"] = frame.get("expected_turn_id")
    return "sha256:" + hashlib.sha256(rfc8785.dumps(semantic)).hexdigest()


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2,
                       sort_keys=True) + "\n").encode("utf-8")


def hash_vectors() -> dict:
    # Canonical strings are fixed expectations, not generated by the Core
    # implementation under test. They cover ECMAScript numbers and UTF-16
    # property ordering; hashes are derived from those expected bytes.
    cases = [
        ({"z": 1.0, "a": "á"}, '{"a":"á","z":1}'),
        ({"😀": 1, "\ue000": 2}, '{"😀":1,"\ue000":2}'),
        ({"n": [-0.0, 1e-7, 1e21]}, '{"n":[0,1e-7,1e+21]}'),
    ]
    return {"revision": REVISION, "vectors": [
        {"input": value, "canonical": canonical,
         "sha256": "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()}
        for value, canonical in cases
    ]}


def main(*, check: bool = False) -> None:
    generated = {"frame.schema.json": frame_schema(),
                 "intent.schema.json": INTENT, "event.schema.json": EVENT,
                 "error.schema.json": ERROR, "inventory.schema.json": INVENTORY,
                 "capability.schema.json": CAPABILITY,
                 "http-response.schema.json": HTTP_RESPONSE,
                 "fixtures.json": fixtures(),
                 "hash-vectors.json": hash_vectors()}
    rendered = {name: json_bytes(value) for name, value in generated.items()}
    manifest = {"protocol_major": 1, "revision": REVISION,
                "core_version": "0.1.0.dev0", "status": "development-partial",
                "files": {name: "sha256:" + hashlib.sha256(
                    rendered[name]).hexdigest()
                          for name in sorted(generated)}}
    rendered["manifest.json"] = json_bytes(manifest)
    if check:
        stale = [name for name, content in rendered.items()
                 if not (DESTINATION / name).is_file() or
                 (DESTINATION / name).read_bytes() != content]
        if stale:
            raise SystemExit("stale contract resources: " + ", ".join(stale))
        return
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for name, content in rendered.items():
        (DESTINATION / name).write_bytes(content)


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--check"]):
        raise SystemExit("usage: generate.py [--check]")
    main(check=sys.argv[1:] == ["--check"])

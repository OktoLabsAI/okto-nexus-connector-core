"""Generate the independent, intentionally partial NXL R4 schema bundle.

R3 resources are never modified. This bundle covers the first admission
handshake and remote open/turn transport; other R4 frames must be added before
any host advertises the revision as executable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


REVISION = "nxl-1-agent-centric-http-only-2026-09-29-r4"
MANAGEMENT = "nexus-connections-2026-09-29-r4"
OUT = Path(__file__).resolve().parents[1] / "src/nexus_connector_core/contracts/nxl/r4"
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from nexus_connector_core.executor_inventory import SNAPSHOT_FORMAT_VERSION  # noqa: E402
from nexus_connector_core.catalog import CATALOG_FORMAT_VERSION  # noqa: E402

ID = {"type": "string", "minLength": 1, "maxLength": 160}
REV = {"type": "integer", "minimum": 0, "maximum": 9007199254740991}
HASH = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}


def obj(properties: dict, required: tuple[str, ...] | list[str]) -> dict:
    return {"type": "object", "additionalProperties": False,
            "properties": properties, "required": list(required)}


def frame(kind: str, properties: dict, required: tuple[str, ...] | list[str]) -> dict:
    base = {
        "protocol_major": {"const": 1},
        "contract_revision": {"const": REVISION},
        "type": {"const": kind},
    }
    result = obj({**base, **properties},
                 ("protocol_major", "contract_revision", "type", *required))
    result["title"] = kind
    return result


SCOPE = {
    "server_id": ID, "executor_id": ID, "binding_id": ID,
    "agent_id": ID, "workspace_id": ID, "workspace_binding_id": ID,
    "session_id": ID, "session_owner_generation": REV,
    "authorization_revision": REV, "configuration_revision": REV,
    "binding_revision": REV, "credential_epoch": REV,
}
SCOPE_REQUIRED = tuple(SCOPE)
CONNECTION = {"connection_id": ID, "connection_generation": REV}

OPEN = obj({
    # Identifier syntax is portable; decoding additionally requires the local
    # trusted static registry. No module or connector class travels on the wire.
    "adapter_id": ID,
    "candidate_ref": {"type": "string", "pattern": "^nexus-install-v1:[0-9a-f]{64}$"},
    "inventory_revision": HASH,
    "realization_ref": ID,
    "realization_revision": REV,
    "profile_revision": REV,
    "mode": {"const": "managed"},
    "model": {"type": ["string", "null"], "maxLength": 160},
    "mcp_preset": {"type": "array", "maxItems": 32, "items": {"type": "object"}},
    "harness_settings": {
        "type": "object", "additionalProperties": False,
        "properties": {
            name: {"type": "string", "minLength": 1, "maxLength": 200}
            for name in ("approval_policy", "effort", "permission_mode", "provider", "sandbox", "user_input")
        } | {"inherit_global_mcps": {"type": "string", "enum": ["enabled", "disabled"]}},
    },
}, ("adapter_id", "candidate_ref", "inventory_revision", "realization_ref",
    "realization_revision", "profile_revision", "mode"))
SUBMIT = obj({"text": {"type": "string", "minLength": 1, "maxLength": 65536},
              "delivery_id": ID}, ("text",))
STEER = obj({"text": {"type": "string", "minLength": 1, "maxLength": 65536}},
            ("text",))
INTERRUPT = obj({"reason": {"type": "string", "maxLength": 1024}},
                ("reason",))
CLOSE = obj({"reason": {"type": "string", "maxLength": 1024},
             "drain_seconds": {"type": "number", "minimum": 0, "maximum": 30},
             "interrupt_seconds": {"type": "number", "minimum": 0, "maximum": 15}},
            ("reason", "drain_seconds", "interrupt_seconds"))
NATIVE_REQUEST = {
    "type": "object", "minProperties": 1, "maxProperties": 32,
    "required": ["request_hash"],
    "properties": {"request_hash": HASH},
    # The original adapter request is opaque here; its native schema is
    # checked by Core at application time, never reconstructed by a host.
    "additionalProperties": True,
}
NATIVE_DECISION_REQUEST = obj({
    "schema_version": {"const": 1},
    "request_id": {"oneOf": [
        {"type": "string", "minLength": 1, "maxLength": 256}, REV,
    ]},
    # Native historical hashes are raw hex, not R4's prefixed JCS digest.
    "request_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "method": {"type": "string", "minLength": 1, "maxLength": 160},
    "params": {"type": "object", "maxProperties": 32},
    "local_generation": REV,
}, ("request_id", "request_hash", "method", "params"))
DECISION_FIELDS = {
    "canonical_request_id": ID, "decision_id": ID,
    "decision_revision": {"type": "integer", "minimum": 1},
    "decision": {"enum": ["accept", "decline", "cancel"]},
    "request": NATIVE_DECISION_REQUEST,
    "response_digest": {"oneOf": [HASH, {"type": "null"}]},
}
DECISION_REQUIRED = tuple(DECISION_FIELDS)
APPROVAL = obj(DECISION_FIELDS, DECISION_REQUIRED)
INPUT = obj({
    **DECISION_FIELDS,
    "response": {"type": ["object", "null"], "maxProperties": 32},
    "response_ref": {"oneOf": [ID, {"type": "null"}]},
}, DECISION_REQUIRED)
INPUT["allOf"] = [{
    "if": {"properties": {"decision": {"const": "accept"}},
           "required": ["decision"]},
    "then": {"oneOf": [
        {"required": ["response"],
         "properties": {"response": {"type": "object"},
                        "response_ref": {"type": "null"}}},
        {"required": ["response_ref"],
         "properties": {"response_ref": ID, "response": {"type": "null"}}},
    ]},
    "else": {"not": {"anyOf": [
        {"required": ["response"], "properties": {"response": {"type": "object"}}},
        {"required": ["response_ref"], "properties": {"response_ref": ID}},
    ]}},
}]
PAYLOADS = {
    "runtime.open": OPEN, "turn.submit": SUBMIT, "turn.steer": STEER,
    "turn.interrupt": INTERRUPT, "runtime.close": CLOSE,
    "approval.decide": APPROVAL, "input.provide": INPUT,
}
STAGES = ["RECEIVED_DURABLE", "PREPARED", "SUBMISSION_STARTED", "SUBMITTED",
          "ACCEPTED", "RUNNING", "WAITING_INPUT", "SUCCEEDED", "FAILED",
          "CANCELLED", "OUTCOME_UNKNOWN"]
EVENT_CATEGORIES = [
    "lifecycle", "turn_state", "text_delta", "text_snapshot",
    "tool_activity", "approval_request", "input_request", "usage",
    "system_warning", "rate_limit", "error", "native_unknown",
]


def build_schema() -> dict:
    operation = frame("operation.submit", {
        **SCOPE, **CONNECTION,
        "grant_id": ID, "operation_id": ID, "intent_hash": HASH,
        "action": {"enum": list(PAYLOADS)},
        "payload": {"type": "object"},
        "expected_turn_id": {"type": ["string", "null"], "maxLength": 160},
    }, (*SCOPE_REQUIRED, *CONNECTION, "grant_id", "operation_id",
        "intent_hash", "action", "payload"))
    operation["oneOf"] = [
        {"properties": {"action": {"const": action}, "payload": payload,
                        **({"expected_turn_id": {"type": "null"}}
                           if action in {"approval.decide", "input.provide"} else {})}}
        for action, payload in PAYLOADS.items()
    ]
    scope_obj = obj(SCOPE, SCOPE_REQUIRED)
    id_list = {"type": "array", "items": ID, "uniqueItems": True,
               "maxItems": 256}
    watermarks = {"type": "array", "maxItems": 256,
                  "items": obj({"session_id": ID, "stream_epoch": ID,
                                "sequence": REV},
                               ("session_id", "stream_epoch", "sequence"))}
    receipt_checkpoint = obj({
        "operation_id": ID, "intent_hash": HASH,
        "receipt_revision": {"type": "integer", "minimum": 1},
        "stage": {"enum": STAGES},
    }, ("operation_id", "intent_hash", "receipt_revision", "stage"))
    claim = obj({"session_id": ID,
                 "state": {"enum": ["OWNED", "RELEASED", "UNKNOWN"]},
                 "owner_generation": REV},
                ("session_id", "state", "owner_generation"))
    ownership_fact = obj({
        "session_id": ID, "owner_generation": REV,
        "process_state": {"enum": ["ALIVE", "EXITED", "UNKNOWN"]},
        "proof_digest": HASH,
    }, ("session_id", "owner_generation", "process_state"))
    event = obj({
        "server_id": ID, "executor_id": ID, "session_id": ID,
        "stream_epoch": ID, "sequence": {"type": "integer", "minimum": 1},
        "category": {"enum": EVENT_CATEGORIES},
        "payload": {"type": "object", "maxProperties": 32},
        "native_type": {"type": ["string", "null"], "maxLength": 160},
        "operation_id": ID,
    }, ("server_id", "executor_id", "session_id", "stream_epoch",
        "sequence", "category", "payload"))
    frames = [
        frame("hello", {
            "resume_connection_id": ID, "resume_connection_generation": REV,
            "link_attempt_id": ID, "server_id": ID, "executor_id": ID,
            "core_version": ID, "management_revision": {"const": MANAGEMENT},
            "supported_nxl": {"type": "array", "items": {"const": REVISION},
                              "minItems": 1, "maxItems": 1},
            "snapshot_formats": {"type": "array", "items": {"const": SNAPSHOT_FORMAT_VERSION},
                                 "minItems": 1, "maxItems": 1},
            "control_capabilities": id_list,
        }, ("link_attempt_id", "server_id", "executor_id", "core_version",
            "management_revision", "supported_nxl", "snapshot_formats",
            "control_capabilities")),
        frame("welcome", {
            "resumed": {"type": "boolean"},
            "link_attempt_id": ID, "server_id": ID, "executor_id": ID,
            **CONNECTION, "management_revision": {"const": MANAGEMENT},
            "accepted_nxl": {"const": REVISION},
            "snapshot_format": {"const": SNAPSHOT_FORMAT_VERSION},
            "control_capabilities": id_list,
        }, ("link_attempt_id", "server_id", "executor_id", *CONNECTION,
            "management_revision", "accepted_nxl", "snapshot_format",
            "control_capabilities")),
        frame("binding.attach", {
            "attach_request_id": ID, "server_id": ID, "executor_id": ID,
            "binding_id": ID, "agent_id": ID, "connection_id": ID,
            "expected_connection_generation": REV,
            "credential_epoch": REV, "authorization_revision": REV,
            "configuration_revision": REV,
            "ticket": {"type": "string", "minLength": 32, "maxLength": 4096},
        }, ("attach_request_id", "server_id", "executor_id", "binding_id",
            "agent_id", "connection_id", "expected_connection_generation",
            "credential_epoch", "authorization_revision",
            "configuration_revision", "ticket")),
        frame("binding.detach", {
            "server_id": ID, "executor_id": ID, "binding_id": ID,
            "agent_id": ID, **CONNECTION,
            "reason": {"type": "string", "minLength": 1, "maxLength": 256},
        }, ("server_id", "executor_id", "binding_id", "agent_id",
            *CONNECTION, "reason")),
        frame("binding.attached", {
            "attach_request_id": ID, **CONNECTION,
            "server_id": ID, "executor_id": ID, "binding_id": ID,
            "agent_id": ID, "credential_epoch": REV,
            "authorization_revision": REV, "configuration_revision": REV,
            "expires_in": {"type": "integer", "minimum": 1, "maximum": 600},
        }, ("attach_request_id", *CONNECTION, "server_id", "executor_id",
            "binding_id", "agent_id", "credential_epoch",
            "authorization_revision", "configuration_revision", "expires_in")),
        frame("reconcile.request", {
            "reconcile_id": ID, **CONNECTION, "server_id": ID,
            "executor_id": ID, "cursor": {"type": ["string", "null"],
                                           "maxLength": 160},
            "operation_ids": id_list, "session_ids": id_list,
            "stream_watermarks": watermarks,
        }, ("reconcile_id", *CONNECTION, "server_id", "executor_id",
            "cursor", "operation_ids", "session_ids", "stream_watermarks")),
        frame("reconcile.report", {
            "reconcile_id": ID, **CONNECTION, "server_id": ID,
            "executor_id": ID, "cursor": {"type": ["string", "null"],
                                           "maxLength": 160},
            "next_cursor": {"type": ["string", "null"], "maxLength": 160},
            "complete": {"type": "boolean"},
            "receipts": {"type": "array", "items": receipt_checkpoint,
                         "maxItems": 256},
            "claims": {"type": "array", "items": claim, "maxItems": 256},
            "stream_watermarks": watermarks,
            "ownership_facts": {"type": "array", "items": ownership_fact,
                                "maxItems": 256},
        }, ("reconcile_id", *CONNECTION, "server_id", "executor_id",
            "cursor", "next_cursor", "complete", "receipts", "claims",
            "stream_watermarks", "ownership_facts")),
        frame("reconcile.accepted", {
            "reconcile_id": ID, **CONNECTION, "server_id": ID,
            "executor_id": ID, "recovery_remaining": {"type": "boolean"},
            "ready_lane_ids": {"type": "array", "items": ID, "uniqueItems": True,
                               "maxItems": 1024},
            "session_lease_requirements": {"type": "array", "items": ID,
                                           "uniqueItems": True, "maxItems": 1024},
        }, ("reconcile_id", *CONNECTION, "server_id", "executor_id",
            "recovery_remaining", "ready_lane_ids", "session_lease_requirements")),
        frame("lease.renew", {
            "request_id": ID, "grant_id": ID, "expected_lease_serial": REV,
            "scope": scope_obj, **CONNECTION,
            "purpose": {"enum": ["initial", "renew", "reconnect"]},
        }, ("request_id", "grant_id", "expected_lease_serial", "scope",
            *CONNECTION, "purpose")),
        frame("lease.granted", {
            "request_id": ID, "lease_id": ID, "lease_serial": REV,
            "grant_id": ID, "scope": scope_obj,
            "allowed_actions": {"type": "array", "items": {"enum": list(PAYLOADS)},
                                "uniqueItems": True, "maxItems": len(PAYLOADS)},
            "valid_for_ms": {"type": "integer", "minimum": 1, "maximum": 120000},
        }, ("request_id", "lease_id", "lease_serial", "grant_id", "scope",
            "allowed_actions", "valid_for_ms")),
        frame("lease.applied", {
            "request_id": ID, "lease_id": ID, "lease_serial": REV,
            "grant_id": ID, "scope": scope_obj, **CONNECTION,
            "application_stage": {"enum": ["INSTALLED", "RENEWED", "REVOKED"]},
        }, ("request_id", "lease_id", "lease_serial", "grant_id", "scope",
            *CONNECTION, "application_stage")),
        operation,
        frame("operation.receipt", {
            "server_id": ID, "executor_id": ID, "binding_id": ID,
            "agent_id": ID, "session_id": ID, **CONNECTION,
            "operation_id": ID, "intent_hash": HASH,
            "receipt_revision": {"type": "integer", "minimum": 1},
            "stage": {"enum": STAGES}, "possible_effect": {"type": "boolean"},
            "retry_safe": {"type": "boolean"},
            "native_id": ID, "error_code": ID,
        }, ("server_id", "executor_id", "binding_id", "agent_id", "session_id",
            *CONNECTION, "operation_id", "intent_hash", "receipt_revision",
            "stage", "possible_effect", "retry_safe")),
        frame("operation.query", {
            "server_id": ID, "executor_id": ID, "binding_id": ID,
            "agent_id": ID, "session_id": ID, **CONNECTION,
            "operation_id": ID, "intent_hash": HASH,
        }, ("server_id", "executor_id", "binding_id", "agent_id", "session_id",
            *CONNECTION, "operation_id", "intent_hash")),
        frame("event.batch", {
            "server_id": ID, "executor_id": ID, "binding_id": ID,
            "agent_id": ID, "session_id": ID, "stream_epoch": ID,
            **CONNECTION,
            "events": {"type": "array", "items": event,
                       "minItems": 1, "maxItems": 128},
        }, ("server_id", "executor_id", "binding_id", "agent_id",
            "session_id", "stream_epoch", *CONNECTION, "events")),
        frame("event.ack", {
            "server_id": ID, "executor_id": ID, "binding_id": ID,
            "agent_id": ID, "session_id": ID, "stream_epoch": ID,
            **CONNECTION,
            "sequence": {"type": "integer", "minimum": 1},
        }, ("server_id", "executor_id", "binding_id", "agent_id",
            "session_id", "stream_epoch", *CONNECTION, "sequence")),
        frame("approval.request", {
            **SCOPE, **CONNECTION,
            "canonical_request_id": ID,
            "request_hash": HASH,
            "request_revision": {"type": "integer", "minimum": 1},
            "kind": {"enum": ["native_approval", "native_input",
                               "administrative"]},
            "expires_in": {"type": "integer", "minimum": 1,
                           "maximum": 86400},
            "operational_request": {"oneOf": [NATIVE_REQUEST, NATIVE_DECISION_REQUEST]},
        }, (*SCOPE_REQUIRED, *CONNECTION, "canonical_request_id",
            "request_hash", "request_revision", "kind", "expires_in",
            "operational_request")),
        frame("approval.decision", {
            **SCOPE, **CONNECTION,
            "canonical_request_id": ID, "decision_id": ID,
            "decision_revision": {"type": "integer", "minimum": 1},
            "decision": {"enum": ["accept", "decline", "cancel"]},
            "request_hash": HASH,
        }, (*SCOPE_REQUIRED, *CONNECTION, "canonical_request_id",
            "decision_id", "decision_revision", "decision",
            "request_hash")),
        frame("connection.renew", {
            "server_id": ID, "executor_id": ID, **CONNECTION,
            "request_id": ID,
        }, ("server_id", "executor_id", *CONNECTION, "request_id")),
        frame("connection.renewed", {
            "server_id": ID, "executor_id": ID, **CONNECTION,
            "request_id": ID,
            "expires_in": {"type": "integer", "minimum": 1, "maximum": 600},
            "binding_ids": {"type": "array", "items": ID, "maxItems": 256, "uniqueItems": True},
        }, ("server_id", "executor_id", *CONNECTION, "request_id", "expires_in", "binding_ids")),
        frame("heartbeat", {
            "server_id": ID, "executor_id": ID, **CONNECTION,
        }, ("server_id", "executor_id", *CONNECTION)),
        frame("error", {
            "server_id": ID, "executor_id": ID, **CONNECTION,
            "code": ID, "stage": ID,
            "possible_effect": {"type": "boolean"},
            "retry_safe": {"type": "boolean"},
            "operation_id": ID,
            "corrective_action": {"type": "string", "maxLength": 512},
        }, ("server_id", "executor_id", *CONNECTION, "code", "stage",
            "possible_effect", "retry_safe")),
        frame("goaway", {
            "server_id": ID, "executor_id": ID, **CONNECTION,
            "code": ID, "reason": {"type": "string", "minLength": 1,
                                   "maxLength": 256},
        }, ("server_id", "executor_id", *CONNECTION, "code", "reason")),
    ]
    hello = next(item for item in frames if item['title'] == 'hello')
    hello['dependentRequired'] = {
        'resume_connection_id': ['resume_connection_generation'],
        'resume_connection_generation': ['resume_connection_id'],
    }
    approval_request = next(item for item in frames if item["title"] == "approval.request")
    approval_request["allOf"] = [{
        "if": {"properties": {"kind": {"enum": ["native_approval", "native_input"]}}},
        "then": {"properties": {"operational_request": NATIVE_DECISION_REQUEST}},
    }]
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://nexus.oktolabs.ai/contracts/nxl/r4/frame.schema.json",
            "oneOf": frames}


def build_inventory_schema() -> dict:
    source = Path(__file__).parent / "specification/executor-inventory-baseline.json"
    definitions = json.loads(source.read_text(encoding="utf-8"))["definitions"]
    definitions["ExecutorInventorySnapshot"]["properties"]["snapshot_format_version"] = {
        "const": SNAPSHOT_FORMAT_VERSION}
    definitions["RuntimeCatalog"]["properties"]["format_version"] = {
        "const": CATALOG_FORMAT_VERSION}
    controls = obj({
        "action": {"enum": ["turn.steer", "turn.interrupt"]},
        "supported": {"type": "boolean"},
        "native_turn_id": {"enum": ["required", "optional", "forbidden"]},
        "requires_active_run": {"type": "boolean"},
        "steer_timing": {"enum": ["IMMEDIATE", "NEXT_TURN_BOUNDARY", None]},
    }, ("action", "supported", "native_turn_id", "requires_active_run", "steer_timing"))
    descriptor = definitions["RuntimeDescriptor"]
    descriptor["properties"]["control_targeting"] = {
        "type": "array", "items": controls, "minItems": 2, "maxItems": 2}
    descriptor["required"].append("control_targeting")
    evidence = definitions["CandidateEvidence"]
    for name in ("qualification", "containment"):
        evidence["properties"][name] = definitions["CandidateAvailability"]["properties"][name]
        evidence["required"].append(name)
    evidence["properties"]["qualified_control_actions"] = {
        "type": "array", "items": {"enum": ["turn.steer", "turn.interrupt"]},
        "uniqueItems": True, "maxItems": 2}
    evidence["required"].append("qualified_control_actions")
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://nexus.oktolabs.ai/contracts/nxl/r4/inventory.schema.json",
            "$defs": definitions, "$ref": "#/$defs/ExecutorInventorySnapshot"}


def generated_files() -> dict[str, bytes]:
    schema_bytes = (json.dumps(build_schema(), sort_keys=True, ensure_ascii=False,
                               indent=2) + "\n").encode("utf-8")
    inventory_bytes = (json.dumps(build_inventory_schema(), sort_keys=True,
                                  ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    manifest = {
        "revision": REVISION, "protocol_major": 1,
        "management_revision": MANAGEMENT,
        "status": "executable",
        "supported_frames": [item["title"] for item in build_schema()["oneOf"]],
        "unsupported_actions": [],
        "files": {"frame.schema.json":
                  "sha256:" + hashlib.sha256(schema_bytes).hexdigest(),
                  "inventory.schema.json":
                  "sha256:" + hashlib.sha256(inventory_bytes).hexdigest()},
    }
    return {
        "__init__.py": b'"""Independent executable NXL R4 contract bundle."""\n',
        "frame.schema.json": schema_bytes,
        "inventory.schema.json": inventory_bytes,
        "manifest.json": (json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                                     indent=2) + "\n").encode("utf-8"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify generated bytes without writing files")
    args = parser.parse_args()
    expected = generated_files()
    if args.check:
        changed = [name for name, value in expected.items()
                   if not (OUT / name).is_file() or (OUT / name).read_bytes() != value]
        if changed:
            raise SystemExit("R4 generated contract drift: " + ", ".join(changed))
        print("R4 generated contract matches its source.")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    for name, value in expected.items():
        (OUT / name).write_bytes(value)


if __name__ == "__main__":
    main()

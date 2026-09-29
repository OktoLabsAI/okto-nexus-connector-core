"""Generate the independent, intentionally partial NXL R4 schema bundle.

R3 resources are never modified. This bundle covers the first admission
handshake and remote open/turn transport; other R4 frames must be added before
any host advertises the revision as executable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


REVISION = "nxl-1-agent-centric-http-only-2026-09-29-r4"
MANAGEMENT = "nexus-connections-2026-09-29-r4"
OUT = Path(__file__).resolve().parents[1] / "src/nexus_connector_core/contracts/nxl/r4"
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
    "adapter_id": ID,
    "candidate_ref": {"type": "string", "pattern": "^nexus-install-v1:[0-9a-f]{64}$"},
    "inventory_revision": HASH,
    "realization_ref": ID,
    "realization_revision": REV,
    "profile_revision": REV,
    "mode": {"const": "managed"},
    "model": {"type": ["string", "null"], "maxLength": 160},
}, ("adapter_id", "candidate_ref", "inventory_revision", "realization_ref",
    "realization_revision", "profile_revision", "mode"))
SUBMIT = obj({"text": {"type": "string", "minLength": 1, "maxLength": 65536},
              "delivery_id": ID}, ("text",))
STEER = obj({"text": {"type": "string", "minLength": 1, "maxLength": 65536}},
            ("text",))
INTERRUPT = obj({"reason": {"type": "string", "minLength": 1, "maxLength": 256}},
                ("reason",))
CLOSE = obj({"reason": {"type": "string", "minLength": 1, "maxLength": 256}},
            ("reason",))
PAYLOADS = {
    "runtime.open": OPEN, "turn.submit": SUBMIT, "turn.steer": STEER,
    "turn.interrupt": INTERRUPT, "runtime.close": CLOSE,
}


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
        {"properties": {"action": {"const": action}, "payload": payload}}
        for action, payload in PAYLOADS.items()
    ]
    scope_obj = obj(SCOPE, SCOPE_REQUIRED)
    frames = [
        frame("binding.attached", {
            "attach_request_id": ID, **CONNECTION,
            "server_id": ID, "executor_id": ID, "binding_id": ID,
            "agent_id": ID, "credential_epoch": REV,
            "authorization_revision": REV, "configuration_revision": REV,
            "expires_in": {"type": "integer", "minimum": 1, "maximum": 600},
        }, ("attach_request_id", *CONNECTION, "server_id", "executor_id",
            "binding_id", "agent_id", "credential_epoch",
            "authorization_revision", "configuration_revision", "expires_in")),
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
    ]
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://nexus.oktolabs.ai/contracts/nxl/r4/frame.schema.json",
            "oneOf": frames}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "__init__.py").write_text('"""Independent NXL R4 development bundle."""\n',
                                      encoding="utf-8")
    schema_bytes = (json.dumps(build_schema(), sort_keys=True, ensure_ascii=False,
                               indent=2) + "\n").encode("utf-8")
    (OUT / "frame.schema.json").write_bytes(schema_bytes)
    manifest = {
        "revision": REVISION, "protocol_major": 1,
        "management_revision": MANAGEMENT,
        "status": "development-partial",
        "supported_frames": [item["title"] for item in build_schema()["oneOf"]],
        "unsupported_actions": ["approval.decide", "input.provide"],
        "files": {"frame.schema.json":
                  "sha256:" + hashlib.sha256(schema_bytes).hexdigest()},
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

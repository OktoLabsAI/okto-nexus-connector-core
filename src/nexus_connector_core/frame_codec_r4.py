"""Strict, effect-free codec for the independent executable NXL R4 bundle.

The R3 codec and its historical hashes are untouched. Contract conformance
does not qualify a provider or automatically enable execution in a host.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib.resources import files
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .frame_codec import MAX_FRAME_BYTES, _preflight_encode
from .models import CoreError
from .protocol import canonical_json, strict_json

R4_CONTRACT_REVISION = "nxl-1-agent-centric-http-only-2026-09-29-r4"
# Compatibility name used by development consumers; the wire bytes are stable.
R4_PREVIEW_REVISION = R4_CONTRACT_REVISION
R4_BUNDLE_EXECUTABLE = True
MAX_OPERATION_PAYLOAD_BYTES = 65536
MAX_JSON_DEPTH = 64


@lru_cache(maxsize=1)
def _resources() -> tuple[Draft202012Validator, dict[str, Any], str]:
    folder = files("nexus_connector_core.contracts.nxl.r4")
    manifest_bytes = folder.joinpath("manifest.json").read_bytes()
    manifest = strict_json(manifest_bytes.decode("utf-8"))
    schema_bytes = folder.joinpath("frame.schema.json").read_bytes()
    inventory_bytes = folder.joinpath("inventory.schema.json").read_bytes()
    if (manifest.get("revision") != R4_PREVIEW_REVISION or
            manifest.get("protocol_major") != 1 or
            manifest.get("status") != "executable" or
            manifest.get("unsupported_actions") != [] or
            manifest.get("files") != {"frame.schema.json":
                "sha256:" + hashlib.sha256(schema_bytes).hexdigest(),
                "inventory.schema.json":
                "sha256:" + hashlib.sha256(inventory_bytes).hexdigest()}):
        raise CoreError("CONTRACT_MISMATCH", "r4_bundle")
    schema = strict_json(schema_bytes.decode("utf-8"))
    Draft202012Validator.check_schema(schema)
    return (Draft202012Validator(schema), manifest,
            "sha256:" + hashlib.sha256(manifest_bytes).hexdigest())


def verify_r4_bundle() -> dict[str, Any]:
    """Return verified manifest facts; never a claim of runtime readiness."""
    _, manifest, digest = _resources()
    return {"manifest_sha256": digest, "revision": manifest["revision"],
            "status": manifest["status"],
            "supported_frames": tuple(manifest["supported_frames"]),
            "executable": R4_BUNDLE_EXECUTABLE}


def verify_r4_development_bundle() -> dict[str, Any]:
    """Compatibility alias for consumers of the development bundle API."""
    return verify_r4_bundle()


def _check_depth(value: Any) -> None:
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise CoreError("VALIDATION_ERROR", "r4_depth", retry_safe=True)
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def r4_submit_intent_hash(frame: Mapping[str, Any]) -> str:
    """Hash R4 semantic intent in a domain disjoint from historical R3."""
    fields = (
        "server_id", "executor_id", "binding_id", "agent_id",
        "workspace_id", "workspace_binding_id", "session_id",
        "configuration_revision", "action", "payload",
    )
    semantic = {field: frame[field] for field in fields}
    semantic["expected_turn_id"] = frame.get("expected_turn_id")
    semantic["nxl_revision"] = R4_PREVIEW_REVISION
    return "sha256:" + hashlib.sha256(canonical_json(semantic)).hexdigest()


def _validate(frame: dict[str, Any]) -> None:
    if frame.get("protocol_major") != 1 or frame.get("contract_revision") != R4_PREVIEW_REVISION:
        raise CoreError("VERSION_INCOMPATIBLE", "r4_negotiation", retry_safe=False)
    _check_depth(frame)
    try:
        _resources()[0].validate(frame)
    except ValidationError as exc:
        raise CoreError("VALIDATION_ERROR", "r4_schema", retry_safe=True) from exc
    if frame["type"] == "operation.submit":
        if len(canonical_json(frame["payload"])) > MAX_OPERATION_PAYLOAD_BYTES:
            raise CoreError("CAPACITY_EXCEEDED", "r4_payload", retry_safe=True)
        if frame["intent_hash"] != r4_submit_intent_hash(frame):
            raise CoreError("VALIDATION_ERROR", "r4_intent_hash", retry_safe=True)


def decode_r4_frame(raw: bytes, *, max_frame_bytes: int = MAX_FRAME_BYTES) -> dict[str, Any]:
    """Decode an R4 preview frame without admitting or executing an effect."""
    if (not isinstance(raw, bytes) or type(max_frame_bytes) is not int or
            not 0 < max_frame_bytes <= MAX_FRAME_BYTES):
        raise ValueError("invalid frame input or limit")
    if len(raw) > max_frame_bytes:
        raise CoreError("CAPACITY_EXCEEDED", "r4_decode", retry_safe=True)
    try:
        frame = strict_json(raw.decode("utf-8", errors="strict"))
        canonical_json(frame)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "r4_decode", retry_safe=True) from exc
    if not isinstance(frame, dict):
        raise CoreError("VALIDATION_ERROR", "r4_decode", retry_safe=True)
    _validate(frame)
    return frame


def encode_r4_frame(frame: Mapping[str, Any], *,
                    max_frame_bytes: int = MAX_FRAME_BYTES) -> bytes:
    """Encode a bounded R4 preview frame as canonical UTF-8 JSON plus LF."""
    if not isinstance(frame, Mapping):
        raise CoreError("VALIDATION_ERROR", "r4_encode", retry_safe=True)
    if type(max_frame_bytes) is not int or not 0 < max_frame_bytes <= MAX_FRAME_BYTES:
        raise ValueError("invalid frame limit")
    materialized = dict(frame)
    _preflight_encode(materialized, max_frame_bytes - 1)
    try:
        raw = canonical_json(materialized)
    except (ValueError, TypeError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "r4_encode", retry_safe=True) from exc
    if len(raw) + 1 > max_frame_bytes:
        raise CoreError("CAPACITY_EXCEEDED", "r4_encode", retry_safe=True)
    decode_r4_frame(raw, max_frame_bytes=max_frame_bytes)
    return raw + b"\n"

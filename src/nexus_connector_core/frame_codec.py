"""Bounded NXL r3 frame encoding and validation from bundled resources."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .models import CoreError
from .protocol import canonical_json, require_contract, strict_json, submit_frame_intent_hash

MAX_FRAME_BYTES = 1024 * 1024


def _preflight_encode(value: Any, limit: int) -> None:
    """Reject obviously oversized/cyclic host objects before JCS allocation.

    This counts a lower bound on wire bytes, so it cannot reject a frame that
    would fit. The exact UTF-8/JCS size is still checked after encoding.
    """
    remaining = limit
    active: set[int] = set()
    stack: list[tuple[Any, Any]] = [(None, iter((value,)))]
    while stack:
        parent, members = stack[-1]
        try:
            member = next(members)
        except StopIteration:
            stack.pop()
            if parent is not None:
                active.remove(id(parent))
            continue
        if isinstance(parent, dict):
            key, item = member
            if isinstance(key, str):
                remaining -= len(key) + 3
        else:
            item = member
        if isinstance(item, (dict, list)):
            identity = id(item)
            if identity in active:
                raise CoreError("VALIDATION_ERROR", "frame_encode", retry_safe=True)
            active.add(identity)
            remaining -= 2 + max(0, len(item) - 1)
            stack.append((item, iter(item.items()) if isinstance(item, dict)
                          else iter(item)))
        elif isinstance(item, str):
            remaining -= len(item) + 2
        else:
            remaining -= 1
        if remaining < 0:
            raise CoreError("CAPACITY_EXCEEDED", "frame_encode", retry_safe=True)


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    resource = files("nexus_connector_core.contracts.nxl.v1").joinpath(
        "frame.schema.json")
    schema = json.loads(resource.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _semantic_checks(frame: dict[str, Any]) -> None:
    kind = frame["type"]
    if kind == "event.batch":
        events = frame["events"]
        first = events[0]["sequence"]
        if any((event["server_id"] != frame["server_id"] or
                event["executor_id"] != frame["executor_id"] or
                event["session_id"] != frame["session_id"] or
                event["stream_epoch"] != frame["stream_epoch"] or
                event["sequence"] != first + index)
               for index, event in enumerate(events)):
            raise CoreError("VALIDATION_ERROR", "frame_semantics", retry_safe=True)
    elif kind == "inventory.delta":
        present = {candidate["candidate_id"] for candidate in frame["candidates"]}
        if (len(present) != len(frame["candidates"]) or
                present.intersection(frame["removed_candidate_ids"])):
            raise CoreError("VALIDATION_ERROR", "frame_semantics", retry_safe=True)
    elif kind == "inventory.snapshot":
        candidates = frame["candidates"]
        if len({candidate["candidate_id"] for candidate in candidates}) != len(candidates):
            raise CoreError("VALIDATION_ERROR", "frame_semantics", retry_safe=True)
    elif kind == "operation.receipt":
        if (frame["stage"] == "OUTCOME_UNKNOWN" and
                (not frame["possible_effect"] or frame["retry_safe"])):
            raise CoreError("VALIDATION_ERROR", "frame_semantics", retry_safe=True)
    elif kind == "operation.submit":
        if ("expected_turn_id" in frame["payload"] or
                frame["intent_hash"] != submit_frame_intent_hash(frame)):
            raise CoreError("VALIDATION_ERROR", "frame_semantics", retry_safe=True)


def decode_frame(raw: bytes, *, max_frame_bytes: int = MAX_FRAME_BYTES) -> dict[str, Any]:
    """Parse one complete JSON frame; never perform an operation effect."""
    if (not isinstance(raw, bytes) or type(max_frame_bytes) is not int or
            not 0 < max_frame_bytes <= MAX_FRAME_BYTES):
        raise ValueError("invalid frame input or limit")
    if len(raw) > max_frame_bytes:
        raise CoreError("CAPACITY_EXCEEDED", "frame_decode", retry_safe=True)
    try:
        frame = strict_json(raw.decode("utf-8", errors="strict"))
        canonical_json(frame)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "frame_decode", retry_safe=True) from exc
    if not isinstance(frame, dict):
        raise CoreError("VALIDATION_ERROR", "frame_decode", retry_safe=True)
    if "protocol_major" in frame and "contract_revision" in frame:
        require_contract(frame["protocol_major"], frame["contract_revision"])
    try:
        _validator().validate(frame)
    except (ValidationError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "frame_schema", retry_safe=True) from exc
    _semantic_checks(frame)
    return frame


def encode_frame(frame: Mapping[str, Any], *,
                 max_frame_bytes: int = MAX_FRAME_BYTES) -> bytes:
    """Emit deterministic UTF-8 JSON plus LF after the same inbound checks."""
    if not isinstance(frame, Mapping):
        raise CoreError("VALIDATION_ERROR", "frame_encode", retry_safe=True)
    if type(max_frame_bytes) is not int or not 0 < max_frame_bytes <= MAX_FRAME_BYTES:
        raise ValueError("invalid frame limit")
    materialized = dict(frame)
    _preflight_encode(materialized, max_frame_bytes - 1)
    try:
        raw = canonical_json(materialized)
    except (ValueError, TypeError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "frame_encode", retry_safe=True) from exc
    if len(raw) + 1 > max_frame_bytes:
        raise CoreError("CAPACITY_EXCEEDED", "frame_encode", retry_safe=True)
    decode_frame(raw, max_frame_bytes=max_frame_bytes)
    return raw + b"\n"

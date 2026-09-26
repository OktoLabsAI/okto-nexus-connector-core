"""Pure NXL inventory snapshot/delta producer and revision reducer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .frame_codec import decode_frame
from .models import CoreError
from .protocol import CONTRACT_REVISION, PROTOCOL_MAJOR, canonical_json


@dataclass(frozen=True, slots=True)
class InventoryCandidate:
    candidate_id: str
    adapter_id: str
    fingerprint: str
    trust: str
    version: str | None = None
    architecture: str | None = None


@dataclass(frozen=True, slots=True)
class InventoryProjection:
    server_id: str
    executor_id: str
    revision: int
    candidates: tuple[InventoryCandidate, ...]
    last_delta: bytes | None = None


def _candidate_dict(candidate: InventoryCandidate) -> dict[str, Any]:
    if not isinstance(candidate, InventoryCandidate):
        raise CoreError("VALIDATION_ERROR", "inventory_producer")
    data: dict[str, Any] = {
        "candidate_id": candidate.candidate_id,
        "adapter_id": candidate.adapter_id,
        "fingerprint": candidate.fingerprint,
        "trust": candidate.trust,
    }
    if candidate.version is not None:
        data["version"] = candidate.version
    if candidate.architecture is not None:
        data["architecture"] = candidate.architecture
    return data


def _candidate(data: Mapping[str, Any]) -> InventoryCandidate:
    return InventoryCandidate(data["candidate_id"], data["adapter_id"],
                              data["fingerprint"], data["trust"],
                              data.get("version"), data.get("architecture"))


def _validated(frame: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(frame, Mapping):
        raise CoreError("VALIDATION_ERROR", "inventory_reducer", retry_safe=True)
    try:
        parsed = decode_frame(canonical_json(dict(frame)))
    except (TypeError, ValueError, RecursionError) as exc:
        raise CoreError("VALIDATION_ERROR", "inventory_reducer", retry_safe=True) from exc
    if parsed["type"] not in {"inventory.snapshot", "inventory.delta"}:
        raise CoreError("VALIDATION_ERROR", "inventory_reducer", retry_safe=True)
    return parsed


def _frame(kind: str, *, server_id: str, executor_id: str, revision: int,
           candidates: Sequence[InventoryCandidate],
           removed_candidate_ids: Sequence[str] = ()) -> dict[str, Any]:
    if (not isinstance(candidates, Sequence) or
            isinstance(candidates, (str, bytes)) or
            len(candidates) > 128 or
            not isinstance(removed_candidate_ids, Sequence) or
            isinstance(removed_candidate_ids, (str, bytes))):
        raise CoreError("VALIDATION_ERROR", "inventory_producer")
    frame: dict[str, Any] = {
        "protocol_major": PROTOCOL_MAJOR,
        "contract_revision": CONTRACT_REVISION,
        "type": kind, "server_id": server_id, "executor_id": executor_id,
        "inventory_revision": revision,
        "candidates": [_candidate_dict(item) for item in candidates],
    }
    if kind == "inventory.delta":
        frame["removed_candidate_ids"] = list(removed_candidate_ids)
    return _validated(frame)


def inventory_snapshot_frame(*, server_id: str, executor_id: str,
                             revision: int,
                             candidates: Sequence[InventoryCandidate]) -> dict[str, Any]:
    """Produce a complete schema-checked NXL inventory snapshot."""
    return _frame("inventory.snapshot", server_id=server_id,
                  executor_id=executor_id, revision=revision,
                  candidates=candidates)


def inventory_delta_frame(*, server_id: str, executor_id: str,
                          revision: int,
                          candidates: Sequence[InventoryCandidate] = (),
                          removed_candidate_ids: Sequence[str] = ()) -> dict[str, Any]:
    """Produce one schema-checked change, not an implicit full snapshot."""
    return _frame("inventory.delta", server_id=server_id,
                  executor_id=executor_id, revision=revision,
                  candidates=candidates,
                  removed_candidate_ids=removed_candidate_ids)


def _delta_identity(parsed: dict[str, Any]) -> bytes:
    return canonical_json({
        "candidates": sorted(parsed["candidates"],
                             key=lambda item: item["candidate_id"]),
        "removed_candidate_ids": sorted(parsed["removed_candidate_ids"]),
    })


def reduce_inventory(previous: InventoryProjection | None,
                     frame: Mapping[str, Any]) -> InventoryProjection:
    """Apply snapshots and only gap-free deltas for one executor scope.

    A newer snapshot is authoritative resynchronization. A delta has no
    base-revision field in NXL r3, so only current revision + 1 is safe.
    """
    parsed = _validated(frame)
    scope = (parsed["server_id"], parsed["executor_id"])
    if previous is not None and (previous.server_id, previous.executor_id) != scope:
        raise CoreError("INVENTORY_SCOPE_MISMATCH", "inventory_reducer")
    revision = parsed["inventory_revision"]
    kind = parsed["type"]
    if kind == "inventory.snapshot":
        incoming = tuple(sorted((_candidate(item) for item in parsed["candidates"]),
                                key=lambda item: item.candidate_id))
        if previous is not None:
            if revision < previous.revision:
                return previous
            if revision == previous.revision:
                if incoming != previous.candidates:
                    raise CoreError("INVENTORY_CONFLICT", "inventory_reducer")
                return previous
        return InventoryProjection(*scope, revision, incoming)
    if previous is None:
        raise CoreError("INVENTORY_GAP", "inventory_reducer")
    if revision < previous.revision:
        return previous
    identity = _delta_identity(parsed)
    if revision == previous.revision:
        if previous.last_delta != identity:
            raise CoreError("INVENTORY_CONFLICT", "inventory_reducer")
        return previous
    if revision != previous.revision + 1:
        raise CoreError("INVENTORY_GAP", "inventory_reducer")
    current = {item.candidate_id: item for item in previous.candidates}
    for candidate_id in parsed["removed_candidate_ids"]:
        if candidate_id not in current:
            raise CoreError("INVENTORY_CONFLICT", "inventory_reducer")
        del current[candidate_id]
    for item in parsed["candidates"]:
        candidate = _candidate(item)
        current[candidate.candidate_id] = candidate
    if len(current) > 128:
        raise CoreError("CAPACITY_EXCEEDED", "inventory_reducer")
    return InventoryProjection(*scope, revision,
                               tuple(sorted(current.values(),
                                            key=lambda item: item.candidate_id)),
                               identity)

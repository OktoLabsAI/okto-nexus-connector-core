from copy import deepcopy

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.frame_codec import decode_frame, encode_frame
from nexus_connector_core.inventory_reducer import (
    InventoryCandidate, inventory_delta_frame, inventory_snapshot_frame,
    reduce_inventory,
)


def _candidate(name="one", fingerprint="0"):
    return InventoryCandidate(name, "pi_rpc", "sha256:" + fingerprint * 64,
                              "selected", "0.85.1", "x86_64")


def _snapshot(revision, candidates=()):
    return inventory_snapshot_frame(server_id="server", executor_id="executor",
                                    revision=revision, candidates=candidates)


def _delta(revision, candidates=(), removed=()):
    return inventory_delta_frame(server_id="server", executor_id="executor",
                                 revision=revision, candidates=candidates,
                                 removed_candidate_ids=removed)


def test_producer_schema_round_trip_and_snapshot_authoritative_resync():
    frame = _snapshot(4, [_candidate()])
    assert decode_frame(encode_frame(frame).rstrip(b"\n")) == frame
    current = reduce_inventory(None, frame)
    assert current.revision == 4
    assert current.candidates == (_candidate(),)
    assert reduce_inventory(current, _snapshot(3, [])) is current
    assert reduce_inventory(current, _snapshot(4, [_candidate()])) is current
    fresh = reduce_inventory(current, _snapshot(9, []))
    assert fresh.revision == 9 and fresh.candidates == ()


def test_delta_needs_exact_next_revision_and_snapshot_repairs_gap():
    current = reduce_inventory(None, _snapshot(1, [_candidate()]))
    with pytest.raises(CoreError, match="INVENTORY_GAP"):
        reduce_inventory(current, _delta(3, [_candidate("two")]))
    resynced = reduce_inventory(current, _snapshot(3, [_candidate("two")]))
    next_state = reduce_inventory(resynced, _delta(4, [_candidate("three")]))
    assert [item.candidate_id for item in next_state.candidates] == ["three", "two"]
    with pytest.raises(CoreError, match="INVENTORY_GAP"):
        reduce_inventory(None, _delta(1, [_candidate()]))


def test_update_removal_and_semantic_duplicate_are_idempotent():
    current = reduce_inventory(None, _snapshot(1, [_candidate("one")]))
    changed = reduce_inventory(current, _delta(
        2, [_candidate("one", "1"), _candidate("two")]))
    assert [item.candidate_id for item in changed.candidates] == ["one", "two"]
    equivalent = _delta(2, [_candidate("two"), _candidate("one", "1")])
    assert reduce_inventory(changed, equivalent) is changed
    removed = reduce_inventory(changed, _delta(3, removed=["one"]))
    assert removed.candidates == (_candidate("two"),)
    with pytest.raises(CoreError, match="INVENTORY_CONFLICT"):
        reduce_inventory(removed, _delta(4, removed=["missing"]))


def test_same_revision_conflict_and_namespace_switch_fail_closed():
    current = reduce_inventory(None, _snapshot(1, [_candidate()]))
    with pytest.raises(CoreError, match="INVENTORY_CONFLICT"):
        reduce_inventory(current, _snapshot(1, [_candidate("other")]))
    changed = reduce_inventory(current, _delta(2, [_candidate("two")]))
    with pytest.raises(CoreError, match="INVENTORY_CONFLICT"):
        reduce_inventory(changed, _delta(2, [_candidate("three")]))
    other = deepcopy(_snapshot(2, []))
    other["server_id"] = "other-server"
    with pytest.raises(CoreError, match="INVENTORY_SCOPE_MISMATCH"):
        reduce_inventory(current, other)


def test_schema_rejects_duplicate_ids_invalid_candidate_and_wrong_family():
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        _snapshot(1, [_candidate(), _candidate()])
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        _delta(2, [_candidate()], removed=["one"])
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        _snapshot(1, ["not-a-candidate"])
    invalid = deepcopy(_snapshot(1, [_candidate()]))
    invalid["candidates"][0]["unexpected"] = True
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        reduce_inventory(None, invalid)
    with pytest.raises(CoreError, match="VALIDATION_ERROR"):
        reduce_inventory(None, {"type": "heartbeat"})

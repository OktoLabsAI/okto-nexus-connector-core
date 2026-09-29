"""R4 executor inventory evidence shared by Nexus and Connector."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from nexus_connector_core import (
    CoreError, InstallationCandidate, build_executor_inventory_snapshot,
    verify_executor_inventory_snapshot,
)


def _candidate(path: str, fingerprint: str = "sha256:abc") -> InstallationCandidate:
    return InstallationCandidate(
        adapter_id="codex_app_server", executable=path,
        fingerprint=fingerprint, source="path", trust="selected",
        version="0.157.0", architecture="x86_64",
        build_identity="sha256:build",
    )


def _snapshot(*candidates: InstallationCandidate, sequence: int = 1,
              age: int = 0):
    return build_executor_inventory_snapshot(
        candidates, server_id="server-a", executor_id="executor-a",
        producer_instance_id="producer-a", publication_sequence=sequence,
        observation_age_ms=age,
    )


def test_snapshot_is_path_free_and_distinguishes_identical_copies(tmp_path):
    first = _candidate(str(tmp_path / "first" / "codex"))
    second = _candidate(str(tmp_path / "second" / "codex"))
    snapshot = _snapshot(first, second)
    assert len(snapshot["evidence"]) == 2
    assert snapshot["evidence"][0]["candidate_ref"] != \
        snapshot["evidence"][1]["candidate_ref"]
    assert snapshot["inventory_revision"].startswith("sha256:")
    assert len(snapshot["inventory_revision"]) == 71
    assert str(tmp_path) not in str(snapshot)
    verify_executor_inventory_snapshot(snapshot)


def test_revision_tracks_evidence_but_not_publication_metadata(tmp_path):
    first = _candidate(str(tmp_path / "first" / "codex"))
    second = _candidate(str(tmp_path / "second" / "codex"))
    original = _snapshot(first, second)
    reordered = _snapshot(second, first, sequence=2, age=100)
    assert reordered["inventory_revision"] == original["inventory_revision"]
    changed = _snapshot(replace(first, fingerprint="sha256:new"), second)
    assert changed["inventory_revision"] != original["inventory_revision"]
    same_version_new_build = _snapshot(
        replace(first, build_identity="sha256:another-build"), second)
    assert same_version_new_build["inventory_revision"] != original["inventory_revision"]


def test_tampered_evidence_is_rejected(tmp_path):
    snapshot = _snapshot(_candidate(str(tmp_path / "codex")))
    tampered = deepcopy(snapshot)
    tampered["evidence"][0]["technical_state"] = "READY_FOR_RUNTIME"
    with pytest.raises(CoreError) as error:
        verify_executor_inventory_snapshot(tampered)
    assert error.value.code == "VALIDATION_ERROR"
    leaked = deepcopy(snapshot)
    leaked["evidence"][0]["executable"] = str(tmp_path / "codex")
    with pytest.raises(CoreError):
        verify_executor_inventory_snapshot(leaked)


def test_duplicate_ref_and_candidate_limit_are_rejected(tmp_path):
    one = _candidate(str(tmp_path / "codex"))
    with pytest.raises(CoreError):
        _snapshot(one, one)
    with pytest.raises(CoreError):
        _snapshot(*(_candidate(str(tmp_path / str(index)))
                    for index in range(129)))


def test_no_provider_is_valid_inventory():
    snapshot = _snapshot()
    assert snapshot["evidence"] == []
    verify_executor_inventory_snapshot(snapshot)

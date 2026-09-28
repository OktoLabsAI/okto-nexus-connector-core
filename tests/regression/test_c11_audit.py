"""C11 audit seeds — A11-01: byte-identical installs in distinct
locations must have unambiguous public refs (two parametrized FAILs on
the audited snapshot 6909435 / 0.2.9.dev0) plus the reviewer's three
controls. Uses ONLY the public API: real discovery over trusted roots
put on a controlled PATH, a factory that forbids any open, passive
availability projection. No file is ever executed."""

import asyncio
import os

import pytest

from nexus_connector_core import (
    DiscoveryRequest, LocalRuntimeCore, ShutdownPolicy,
    evaluate_runtime_availability,
)
from nexus_connector_core.journal import SQLiteJournal

_LAB_BINARY = b"#!/bin/sh\n# nexus lab binary (never executed)\n"


class _ForbidOpenFactory:
    """Contract-level factory: any open attempt fails the test."""

    async def open(self, *args, **kwargs):
        raise AssertionError("discovery/availability must never open")


async def _environment(prepared):
    return {}


def _binary_name(name: str) -> str:
    return name + (".exe" if os.name == "nt" else "")


def _make_copies(tmp_path, name, count=2, content=_LAB_BINARY):
    """`count` trusted-root directories, each holding a byte-identical
    copy of the lab binary (distinct physical targets, same bytes)."""
    roots = []
    for index in range(count):
        root = tmp_path / f"root{index}" / "bin"
        root.mkdir(parents=True)
        binary = root / _binary_name(name)
        binary.write_bytes(content)
        binary.chmod(0o755)  # POSIX: candidates must be executable
        roots.append(root)
    return tuple(roots)


def _put_on_path(monkeypatch, roots):
    joined = os.pathsep.join(str(root) for root in roots)
    monkeypatch.setenv("PATH", joined + os.pathsep +
                       os.environ.get("PATH", ""))


def _runtime_for(tmp_path, roots):
    # Discovery-only runtime: an empty selected-candidates mapping is
    # the honest state (nothing composed yet); the public composition
    # factory requires non-empty, the port does not.
    journal = SQLiteJournal(tmp_path / "journal.db")
    return LocalRuntimeCore(
        journal, _ForbidOpenFactory(), candidates={},
        workspace_roots={"ws": str(tmp_path)},
        trusted_discovery_roots=tuple(str(root) for root in roots)
    ), journal


@pytest.mark.parametrize("adapter_id,name", [
    ("codex_app_server", "codex"),
    ("claude_stream", "claude"),
])
def test_distinct_identical_installations_have_unambiguous_public_refs(
        tmp_path, adapter_id, name, monkeypatch):
    roots = _make_copies(tmp_path, name)
    _put_on_path(monkeypatch, roots)
    runtime, journal = _runtime_for(tmp_path, roots)

    async def run():
        try:
            inventory = await runtime.discover(
                DiscoveryRequest((adapter_id,)))
            report = evaluate_runtime_availability(inventory)
            return inventory, report
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    inventory, report = asyncio.run(run())
    rows = [row for row in report.availability
            if row.adapter_id == adapter_id]
    # Two distinct local installations were discovered...
    assert len(inventory.candidates) == 2, (
        "the fixture must surface two installations")
    assert len({c.executable for c in inventory.candidates}) == 2
    # ...same build content (same bytes)...
    fingerprints = {c.fingerprint for c in inventory.candidates}
    assert len(fingerprints) == 1
    builds = {c.build_identity for c in inventory.candidates}
    assert len(builds) == 1
    # ...but the PUBLIC projection must distinguish them: two rows
    # with two distinct candidate_refs - the serialized rows cannot be
    # literally equal, or the binding contract cannot express WHICH
    # installation was selected.
    assert len(rows) == 2
    refs = {row.candidate_ref for row in rows}
    assert len(refs) == 2, (
        "byte-identical installations in distinct locations share one "
        "candidate_ref: the selection contract is ambiguous")
    serialized = [item for item in report.to_dict()["availability"]
                  if item["adapter_id"] == adapter_id]
    assert len({repr(item) for item in serialized}) == 2


def test_control_distinct_builds_already_have_distinct_refs(
        tmp_path, monkeypatch):
    from nexus_connector_core.discovery import discover_path
    root = tmp_path / "bin"
    root.mkdir()
    (root / _binary_name("codex")).write_bytes(b"lab binary A")
    (root / _binary_name("codex")).chmod(0o755)
    _put_on_path(monkeypatch, (root,))
    runtime, journal = _runtime_for(tmp_path, (root,))

    async def run():
        try:
            found = discover_path("codex_app_server",
                                  trusted_roots=(root,))
            assert len(found) == 1
            # A DIFFERENT build in the same location must not collapse
            # with the first candidate's identity.
            (root / _binary_name("codex")).write_bytes(
                b"lab binary B (different)")
            other = discover_path("codex_app_server",
                                  trusted_roots=(root,))
            assert other[0].fingerprint != found[0].fingerprint
            return True
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    assert asyncio.run(run())


def test_control_repeat_of_same_inventory_is_stable_and_path_free(
        tmp_path, monkeypatch):
    import json
    root = tmp_path / "bin"
    root.mkdir()
    (root / _binary_name("claude")).write_bytes(_LAB_BINARY)
    (root / _binary_name("claude")).chmod(0o755)
    _put_on_path(monkeypatch, (root,))
    runtime, journal = _runtime_for(tmp_path, (root,))

    async def run():
        try:
            inventory = await runtime.discover(
                DiscoveryRequest(("claude_stream",)))
            first = evaluate_runtime_availability(inventory).to_dict()
            second = evaluate_runtime_availability(inventory).to_dict()
            assert first == second, "projection is not repeatable"
            return first, str(root)
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    data, root_str = asyncio.run(run())
    blob = json.dumps(data)
    assert root_str not in blob, "projection leaks local paths"
    for row in data["availability"]:
        assert row["state"] != "READY_FOR_RUNTIME", (
            "an unqualified lab build must never be READY_FOR_RUNTIME")


def test_control_catalog_has_no_private_loading_coordinates():
    from nexus_connector_core import get_runtime_catalog
    catalog = get_runtime_catalog()
    for descriptor in catalog.runtimes:
        payload = repr(descriptor)
        for forbidden in ("module", "class_name", "load_adapter"):
            assert forbidden not in payload, (descriptor.adapter_id,
                                              forbidden)
    ids = [d.adapter_id for d in catalog.runtimes]
    assert len(ids) == len(set(ids))

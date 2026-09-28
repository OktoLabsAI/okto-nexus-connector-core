"""C11 installation identity: resolution, reordering, aliases, drift,
legacy migration, format negotiation, executor scope, labels."""

import asyncio
import os

import pytest

from nexus_connector_core import (
    DiscoveryRequest, InstallationCandidate, LocalRuntimeCore,
    ShutdownPolicy, evaluate_runtime_availability, installation_ref,
    resolve_installation,
)
from nexus_connector_core.installation import (
    INSTALLATION_REF_SCHEME, REF_AMBIGUOUS, REF_NOT_FOUND,
)
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import CoreError

from tests.regression.test_c11_audit import (
    _ForbidOpenFactory, _LAB_BINARY, _binary_name, _make_copies,
    _put_on_path, _runtime_for,
)


def test_ref_derivation_is_opaque_versioned_and_target_bound():
    a = installation_ref("codex_app_server", "/inst/a/codex")
    b = installation_ref("codex_app_server", "/inst/b/codex")
    assert a.startswith(INSTALLATION_REF_SCHEME + ":")
    assert a != b, "distinct targets must have distinct refs"
    assert installation_ref("codex_app_server", "/inst/a/codex") == a
    assert "/inst" not in a, "ref must not embed literal paths"
    assert installation_ref("pi_rpc", "/inst/a/codex") != a, (
        "adapter is part of the installation identity")


def test_resolution_ab_is_exact_and_reorder_proof(tmp_path, monkeypatch):
    """AC11-07 + AC11-08: selecting A resolves A, B resolves B - even
    with the inventory in the OPPOSITE order; zero matches and genuine
    ambiguity raise typed errors, never an order-based choice."""
    roots = _make_copies(tmp_path, "codex")
    _put_on_path(monkeypatch, roots)
    runtime, journal = _runtime_for(tmp_path, roots)

    async def run():
        try:
            return await runtime.discover(
                DiscoveryRequest(("codex_app_server",)))
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    inventory = asyncio.run(run())
    (first, second) = inventory.candidates
    refs = {first.installation_ref, second.installation_ref}
    assert len(refs) == 2
    # Reversed order: resolution is still exact per ref.
    reversed_inventory = type(inventory)(
        (second, first))
    for inv in (inventory, reversed_inventory):
        for candidate in (first, second):
            resolved = resolve_installation(
                inv, "codex_app_server", candidate.installation_ref)
            assert resolved is candidate
    # Zero matches: typed NOT_FOUND (missing/stale/foreign).
    with pytest.raises(CoreError) as missing:
        resolve_installation(inventory, "codex_app_server",
                             INSTALLATION_REF_SCHEME + ":" + "0" * 64)
    assert missing.value.code == REF_NOT_FOUND
    # Unknown adapter stays typed as unsupported.
    with pytest.raises(CoreError) as unsupported:
        resolve_installation(inventory, "not_an_adapter", "x")
    assert unsupported.value.code == "CAPABILITY_UNSUPPORTED"


def test_ambiguity_is_typed_never_order_based():
    """AC11-08: two DISTINCT targets under one ref is impossible by
    construction - the guard raises the typed ambiguity error and never
    picks candidates[0]."""
    from dataclasses import replace
    left = InstallationCandidate("codex_app_server", "/inst/a/codex",
                                 "sha256:" + "a" * 64, "explicit",
                                 "selected")
    right = InstallationCandidate("codex_app_server", "/inst/b/codex",
                                  "sha256:" + "a" * 64, "explicit",
                                  "selected")
    # Forged inventory: two DISTINCT targets claimed under ONE ref
    # (impossible from real discovery - the guard must not trust it).
    forged = installation_ref("codex_app_server", "/inst/a/codex")
    left = replace(left, installation_ref=forged)
    right = replace(right, installation_ref=forged)
    with pytest.raises(CoreError) as info:
        resolve_installation((left, right), "codex_app_server", forged)
    assert info.value.code == REF_AMBIGUOUS
    # Identical duplicate rows of ONE installation still resolve.
    twin = InstallationCandidate(left.adapter_id, left.executable,
                                 left.fingerprint, left.source,
                                 left.trust,
                                 installation_ref=installation_ref(
                                     "codex_app_server", "/inst/a/codex"))
    assert resolve_installation(
        (twin, twin), "codex_app_server",
        twin.installation_ref) is twin


def test_path_aliases_to_same_target_are_one_installation(
        tmp_path, monkeypatch):
    """AC11-09: a symlinked PATH entry resolving to the SAME canonical
    target is an ALIAS - one installation, never two distinct targets
    under one ref."""
    from nexus_connector_core.discovery import discover_path
    real_root = tmp_path / "real" / "bin"
    real_root.mkdir(parents=True)
    (real_root / _binary_name("codex")).write_bytes(_LAB_BINARY)
    (real_root / _binary_name("codex")).chmod(0o755)
    alias_root = tmp_path / "alias" / "bin"
    alias_root.mkdir(parents=True)
    os.symlink(real_root / _binary_name("codex"),
               alias_root / _binary_name("codex"))
    _put_on_path(monkeypatch, (real_root, alias_root))
    runtime, journal = _runtime_for(tmp_path, (real_root, alias_root))

    async def run():
        try:
            found = discover_path("codex_app_server",
                                  trusted_roots=(real_root, alias_root))
            inventory = await runtime.discover(
                DiscoveryRequest(("codex_app_server",)))
            return found, inventory
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    found, inventory = asyncio.run(run())
    assert len(found) == 1, "aliases must collapse to ONE installation"
    assert len(inventory.candidates) == 1


def test_drift_after_selection_is_refused_before_effect(tmp_path):
    """AC11-10: content updated between selection and prepare is
    refused by the existing revalidation - the old evidence never
    authorizes new content; no implicit requalification."""
    from dataclasses import replace
    from nexus_connector_core import LaunchIntent
    from nexus_connector_core.discovery import candidate as         select_candidate
    from tests.test_runtime import FakeClock, context
    binary = tmp_path / _binary_name("codex")
    binary.write_bytes(b"original lab binary")
    binary.chmod(0o755)
    # Selected through the real selector (fingerprint matches disk).
    candidate_obj = select_candidate("codex_app_server", binary,
                                     explicit=True)
    intent = LaunchIntent("agent", "ws", "codex_app_server")

    async def run():
        journal = SQLiteJournal(tmp_path / "journal.db")
        runtime = LocalRuntimeCore(
            journal, _ForbidOpenFactory(),
            candidates={"codex_app_server": candidate_obj},
            workspace_roots={"ws": str(tmp_path)},
            clock=FakeClock(100.0))
        try:
            auth = replace(context(),
                           lease_deadline_monotonic=160.0)
            prepared = await runtime.prepare(intent, auth)
            assert prepared is not None
            # The installation's content CHANGED after selection: the
            # recorded evidence (fingerprint) no longer describes the
            # target - prepare must refuse before any effect.
            binary.write_bytes(b"updated lab binary (drift)")
            with pytest.raises(CoreError) as refused:
                await runtime.prepare(intent, auth)
            return refused.value
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    error = asyncio.run(run())
    assert error.code in {"PROFILE_DRIFT", "BINARY_NOT_FOUND",
                          "NATIVE_VERSION_UNQUALIFIED"}, error.code


def test_legacy_v1_ref_migration_rules(tmp_path, monkeypatch):
    """AC11-11: a legacy v1 ref (content fingerprint) migrates ONLY
    when the inventory proves exactly one target; with two identical
    copies it is ambiguous BY CONSTRUCTION - typed reselection, never
    an order-based pick."""
    roots = _make_copies(tmp_path, "claude")
    _put_on_path(monkeypatch, roots)
    runtime, journal = _runtime_for(tmp_path, roots)

    async def run():
        try:
            return await runtime.discover(
                DiscoveryRequest(("claude_stream",)))
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    inventory = asyncio.run(run())
    assert len(inventory.candidates) == 2
    legacy_ref = inventory.candidates[0].fingerprint
    with pytest.raises(CoreError) as ambiguous:
        resolve_installation(inventory, "claude_stream", legacy_ref)
    assert ambiguous.value.code == REF_AMBIGUOUS
    # Single-target inventory: the legacy ref migrates exactly.
    single = inventory.candidates[0]
    single_inventory = type(inventory)((single,))
    assert resolve_installation(
        single_inventory, "claude_stream", legacy_ref) is single


def test_unknown_projection_format_is_refused(tmp_path, monkeypatch):
    """AC11-12: an unknown format version is an explicit incompatible
    state - never a silent READY render."""
    roots = _make_copies(tmp_path, "codex")
    _put_on_path(monkeypatch, roots)
    runtime, journal = _runtime_for(tmp_path, roots)

    async def run():
        try:
            inventory = await runtime.discover(
                DiscoveryRequest(("codex_app_server",)))
            report = evaluate_runtime_availability(inventory)
            return report, report.to_dict()
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    report, data = asyncio.run(run())
    parsed = type(report).from_dict(data)
    assert parsed.format_version == report.format_version
    assert parsed.availability == report.availability
    future = dict(data)
    future["format_version"] = report.format_version + 1
    with pytest.raises(CoreError) as unknown:
        type(report).from_dict(future)
    assert unknown.value.code == "VALIDATION_ERROR"
    assert "unavailable" in unknown.value.message


def test_ref_of_another_executor_does_not_resolve(tmp_path):
    """AC11-13: refs are scoped to the producing host's inventory - a
    selection from executor A raises typed NOT_FOUND against executor
    B's inventory (even with similar-looking paths)."""
    host_a = tmp_path / "host-a" / "bin"
    host_a.mkdir(parents=True)
    (host_a / "codex").write_bytes(_LAB_BINARY)
    (host_a / "codex").chmod(0o755)
    host_b = tmp_path / "host-b" / "bin"
    host_b.mkdir(parents=True)
    (host_b / "codex").write_bytes(b"different build on host B")
    (host_b / "codex").chmod(0o755)
    candidate_a = InstallationCandidate(
        "codex_app_server", str(host_a / "codex"), "sha256:" + "1" * 64,
        "explicit", "selected")
    candidate_b = InstallationCandidate(
        "codex_app_server", str(host_b / "codex"), "sha256:" + "2" * 64,
        "explicit", "selected")
    ref_a = installation_ref("codex_app_server", candidate_a.executable)
    # Executor B resolves ITS OWN inventory - A's ref is foreign.
    assert resolve_installation(
        (candidate_b,), "codex_app_server",
        candidate_b.installation_ref
        or installation_ref("codex_app_server",
                            candidate_b.executable)) is candidate_b
    with pytest.raises(CoreError) as foreign:
        resolve_installation((candidate_b,), "codex_app_server", ref_a)
    assert foreign.value.code == REF_NOT_FOUND


def test_labels_differentiate_copies_without_paths(tmp_path,
                                                   monkeypatch):
    """C11-01.04: same display_name and build, INEQUIVOCAL selection -
    labels differ (file name + short ref), no full path, label is not
    a key."""
    roots = _make_copies(tmp_path, "codex")
    _put_on_path(monkeypatch, roots)
    runtime, journal = _runtime_for(tmp_path, roots)

    async def run():
        try:
            inventory = await runtime.discover(
                DiscoveryRequest(("codex_app_server",)))
            return inventory, evaluate_runtime_availability(inventory)
        finally:
            await runtime.shutdown(ShutdownPolicy())
            journal.close()

    inventory, report = asyncio.run(run())
    rows = [row for row in report.availability
            if row.adapter_id == "codex_app_server"]
    assert len(rows) == 2
    assert len({row.label for row in rows}) == 2, (
        "identical copies need distinguishable labels")
    for row in rows:
        assert str(tmp_path) not in row.label
        assert row.label.endswith(row.candidate_ref[-8:])
        # NOT_PROBED stays restrictive; READY is never granted here.
        assert row.state == NOT_PROBED
    # Each ref resolves back to exactly ONE physical installation.
    for candidate in inventory.candidates:
        assert resolve_installation(
            inventory, "codex_app_server",
            candidate.installation_ref) is candidate


NOT_PROBED = "NOT_PROBED"


def test_not_installed_rows_stay_informative():
    report = evaluate_runtime_availability([])
    for row in report.availability:
        assert row.state == "NOT_INSTALLED"
        assert row.candidate_ref == "", (
            "informative rows carry no fictitious installation id")
        assert row.label == row.display_name

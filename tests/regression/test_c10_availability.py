"""C10/Z01: the public per-candidate availability assessment.

A08-A12 of the acceptance matrix: public API without private imports,
unknown build never READY, platform/containment restrictions, two
candidates of one family, safe remote projection.
"""

import json

import pytest

import nexus_connector_core as core
from nexus_connector_core import InstallationCandidate, Inventory
import nexus_connector_core.availability as availability
from nexus_connector_core.availability import (
    CONTAINMENT_UNAVAILABLE, NOT_INSTALLED, NOT_PROBED,
    PREPARATION_REQUIRED, READY_FOR_RUNTIME, UNSUPPORTED_PLATFORM,
    UNQUALIFIED_BUILD, evaluate_runtime_availability,
)
from nexus_connector_core.models import CoreError


def _candidate(adapter_id="codex_app_server", *, trust="selected",
               version=None, architecture=None, fingerprint="fp-1",
               build_identity=None, source="explicit"):
    return InstallationCandidate(adapter_id, f"/bin/{adapter_id}",
                                 fingerprint, source, trust,
                                 version=version,
                                 architecture=architecture,
                                 build_identity=build_identity)


def test_qualified_selected_candidate_is_ready_for_runtime(monkeypatch):
    # Same policy seam the product consults (the module's binding of
    # compatibility.qualified_build): an exact qualified build.
    monkeypatch.setattr(
        availability, "qualified_build",
        lambda kind, version, platform, architecture, fingerprint,
        *, control=False, build_identity=None:
        (kind, version, architecture, fingerprint)
        == ("codex", "0.157.0", "x86_64", "fp-qualified"))
    report = evaluate_runtime_availability([
        _candidate(version="0.157.0", architecture="x86_64",
                   fingerprint="fp-qualified")])
    (row,) = [r for r in report.availability
              if r.candidate_ref == "fp-qualified"]
    assert row.state == READY_FOR_RUNTIME
    assert row.reasons == ()
    assert row.qualification == "qualified"
    # Technical readiness only - never the agent's authorization.


def test_present_but_unprobed_is_never_ready():
    report = evaluate_runtime_availability([_candidate()])
    row = report.availability[0]
    assert row.state == NOT_PROBED
    assert "no_build_observation" in row.reasons
    assert row.qualification == "not_probed"


def test_unqualified_build_reports_explicit_reason(monkeypatch):
    monkeypatch.setattr(availability, "qualified_build",
                        lambda *a, **k: False)
    report = evaluate_runtime_availability([
        _candidate(version="9.9.9", architecture="x86_64")])
    row = report.availability[0]
    assert row.state == UNQUALIFIED_BUILD
    assert "build_not_qualified" in row.reasons


def test_unsupported_execution_platform():
    report = evaluate_runtime_availability(
        [_candidate(version="0.157.0", architecture="x86_64")],
        platform="sunos")
    row = report.availability[0]
    assert row.state == UNSUPPORTED_PLATFORM
    assert "platform_not_implemented:sunos" in row.reasons
    assert report.platform == "sunos"


def test_containment_unavailable_blocks_readiness(monkeypatch):
    # The same preflight seam the product consults, denied on one
    # requirement; the build itself is qualified so containment is the
    # ONLY blocker.
    monkeypatch.setattr(availability, "qualified_build",
                        lambda *a, **k: True)
    monkeypatch.setattr(
        availability, "containment_preflight",
        lambda *, platform=None: {"job_objects": "denied"})
    report = evaluate_runtime_availability([
        _candidate(version="0.157.0", architecture="x86_64")])
    row = report.availability[0]
    assert row.state == CONTAINMENT_UNAVAILABLE
    assert "containment_unavailable:job_objects" in row.reasons
    assert row.containment == "unavailable"


def test_unselected_trust_requires_preparation(monkeypatch):
    monkeypatch.setattr(availability, "qualified_build",
                        lambda *a, **k: True)
    report = evaluate_runtime_availability([
        _candidate(trust="candidate", version="0.157.0",
                   architecture="x86_64")])
    row = report.availability[0]
    assert row.state == PREPARATION_REQUIRED
    assert "selection_required" in row.reasons


def test_two_candidates_same_family_never_merge(monkeypatch):
    monkeypatch.setattr(
        availability, "qualified_build",
        lambda kind, version, platform, architecture, fingerprint,
        *, control=False, build_identity=None: fingerprint == "fp-b")
    report = evaluate_runtime_availability([
        _candidate(fingerprint="fp-a", trust="candidate"),
        _candidate(fingerprint="fp-b", trust="selected",
                   version="0.157.0", architecture="x86_64"),
    ])
    rows = [r for r in report.availability if r.adapter_id
            == "codex_app_server"]
    assert len(rows) == 2
    states = {r.candidate_ref: r.state for r in rows}
    assert states["fp-a"] == NOT_PROBED  # unprobed AND unselected
    assert states["fp-b"] == READY_FOR_RUNTIME  # distinct assessment
    # No selection by display_name: identity is the opaque ref.


def test_attach_is_never_ready_and_not_discovered():
    # On a platform the attach IMPLEMENTATION covers, registration
    # still never qualifies it merely by existing.
    report = evaluate_runtime_availability(
        [_candidate(adapter_id="claude_attach", version="1.0",
                    architecture="x86_64")],
        platform="linux")
    row = report.availability[0]
    assert row.state == UNQUALIFIED_BUILD
    assert "attach_not_qualified" in row.reasons
    assert row.connection_mode == "attach"
    # On an UNCOVERED execution platform the restriction is even
    # stronger - and still never READY.
    win = evaluate_runtime_availability(
        [_candidate(adapter_id="claude_attach", version="1.0",
                    architecture="x86_64")],
        platform="win32")
    assert win.availability[0].state == UNSUPPORTED_PLATFORM


def test_missing_installations_stay_visible():
    report = evaluate_runtime_availability([])
    states = {r.adapter_id: r.state for r in report.availability}
    assert states["codex_app_server"] == NOT_INSTALLED
    assert states["pi_rpc"] == NOT_INSTALLED
    assert states["claude_stream"] == NOT_INSTALLED
    # attach is not discoverable: no NOT_INSTALLED row for it.
    assert "claude_attach" not in states


def test_unknown_adapter_is_a_typed_error():
    with pytest.raises(CoreError) as info:
        evaluate_runtime_availability([_candidate("not_an_adapter")])
    assert info.value.code == "CAPABILITY_UNSUPPORTED"


def test_projection_is_versioned_json_safe_and_path_free():
    report = evaluate_runtime_availability(
        Inventory(candidates=(
            _candidate(fingerprint="fp-a", trust="candidate"),
            _candidate(adapter_id="pi_rpc", fingerprint="fp-p",
                       version="0.87.1", architecture="x86_64"),
        )))
    data = report.to_dict()
    encoded = json.dumps(data)  # must round-trip
    assert json.loads(encoded) == data
    assert data["format_version"] == core.AVAILABILITY_FORMAT_VERSION
    assert data["core_version"] == core.__version__
    blob = encoded.lower()
    assert "/bin/" not in blob  # no local paths
    assert "executable" not in blob
    assert "class" not in blob and "module" not in blob
    refs = [r["candidate_ref"] for r in data["availability"]
            if r["state"] != NOT_INSTALLED]
    assert refs == ["fp-a", "fp-p"]


def test_assessment_is_pure_and_repeatable():
    items = [_candidate(version="0.157.0", architecture="x86_64")]
    first = evaluate_runtime_availability(items)
    second = evaluate_runtime_availability(items)
    assert first == second


def test_public_api_importable_from_package_root():
    assert callable(core.evaluate_runtime_availability)
    assert core.AvailabilityReport is not None
    assert core.CandidateAvailability is not None
